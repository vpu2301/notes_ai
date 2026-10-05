"""Sprint TQ3 T2 — the spelling overlay's routes.

    GET  /asr/jobs/{id}/corrections              what was unified / is proposed
    PUT  /asr/jobs/{id}/corrections/{cid}        accept | reject (to_text editable on accept)
    POST /asr/jobs/{id}/corrections:recompute    run the unifier again (people's decisions kept)

Tenant from the token's membership, never from the body; another
workspace's job is a 404. A PUT names the ``corrections_rev`` it saw: a
stale one is a 409, so a decision made on an outdated view is refused
rather than applied to the wrong spelling. Audit payloads carry counts,
source and status — never a spelling.
"""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from asr_models import EntityCorrectionView, JobStatus, TranscriptionOutput
from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..config import settings
from ..deps import get_state, requires
from ..domain import corrections, entity_unify, repository

router = APIRouter(prefix="/asr", tags=["asr"])


class CorrectionsView(BaseModel):
    job_id: UUID
    corrections_rev: int
    corrections: list[EntityCorrectionView]


class CorrectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "rejected"]
    # An edited spelling, on accept only: whole words, ≤ 80 characters.
    to_text: str | None = Field(default=None, max_length=entity_unify.TO_TEXT_MAX)
    corrections_rev: int = Field(ge=0)

    @field_validator("to_text")
    @classmethod
    def _whole_words(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not entity_unify.valid_to_text(value):
            raise ValueError("to_text must be whole words: letters, spaces, hyphens, apostrophes")
        return value


def _problem(status_code: int, code: str, detail: str) -> HTTPException:
    exc = HTTPException(status_code=status_code, detail=detail)
    exc.problem_extras = {  # type: ignore[attr-defined]
        "type_uri": f"urn:mdx:asr:corrections:{code}",
        "code": code,
    }
    return exc


async def _view(conn: Any, job_id: UUID) -> CorrectionsView | None:
    state_ = await corrections.job_state(conn, job_id=job_id)
    if state_ is None:
        return None
    rows = await corrections.list_rows(conn, job_id=job_id)
    return CorrectionsView(
        job_id=job_id, corrections_rev=state_.rev, corrections=[r.view() for r in rows]
    )


@router.get(
    "/jobs/{job_id}/corrections",
    response_model=CorrectionsView,
    summary="Spellings unified (or proposed) for this transcript.",
)
async def list_corrections(
    job_id: UUID,
    claims: Annotated[Claims, Depends(requires("asr.read", "asr_job"))] = ...,
) -> CorrectionsView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        view = await _view(conn, job_id)
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return view


@router.put(
    "/jobs/{job_id}/corrections/{correction_id}",
    response_model=CorrectionsView,
    summary="Accept or reject one unified spelling.",
)
async def decide_correction(
    job_id: UUID,
    correction_id: UUID,
    body: CorrectionDecision,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,
) -> CorrectionsView:
    """Accept applies the spelling on the next read (all clients); reject
    reverts every occurrence. The same decision twice is a no-op."""
    if body.to_text is not None and body.status != "accepted":
        raise _problem(422, "to_text_on_reject", "a spelling can only be edited when accepting")
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        try:
            decided = await corrections.decide(
                conn,
                job_id=job_id,
                correction_id=correction_id,
                status=body.status,
                to_text=body.to_text,
                decided_by=claims.sub,
                expected_rev=body.corrections_rev,
            )
        except corrections.StaleRevError:
            raise _problem(
                409, "stale_corrections_rev", "the corrections changed since this view; reload"
            ) from None
        except corrections.ToTextTakenError:
            raise _problem(
                409, "to_text_exists", "another correction already uses that spelling"
            ) from None
        if decided is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        view = await _view(conn, job_id)
    row, _rev = decided
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=(
            audit_kinds.TRANSCRIPT_CORRECTION_ACCEPTED
            if body.status == "accepted"
            else audit_kinds.TRANSCRIPT_CORRECTION_REJECTED
        ),
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        payload={
            "correction_id": str(row.id),
            "source": row.source,
            "occurrences": len(row.occurrences),
            "edited": body.to_text is not None,
        },
        severity=Severity.INFO,
    )
    assert view is not None
    return view


@router.post(
    "/jobs/{job_id}/corrections:recompute",
    response_model=CorrectionsView,
    summary="Run the spelling unifier again (decisions people made are kept).",
)
async def recompute_corrections(
    job_id: UUID,
    claims: Annotated[Claims, Depends(requires("asr.write", "asr_job"))] = ...,
) -> CorrectionsView:
    """For a job whose first run had no glossary (route down, terms added
    since). Idempotent: the same transcript and priors give the same rows."""
    state = get_state()
    decision = await state.limiter.allow(
        "corrections_recompute_user",
        str(claims.sub),
        limit=settings.entity_unify_recompute_hourly_limit,
        window_seconds=3600,
        fail_open=True,
    )
    if not decision.allowed:
        exc = _problem(429, "rate_limited", "too many recompute requests; try again later")
        exc.headers = {"Retry-After": str(decision.retry_after)}
        raise exc
    from .jobs import _load_transcript  # one artefact reader, the result route's

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        found = await repository.get_job_and_result_uri(conn, job_id=job_id)
        job_state = await corrections.job_state(conn, job_id=job_id)
        attendees = await repository.name_candidates(conn, job_id=job_id) if found else []
        glossary = await corrections.glossary_terms(conn)
    if found is None or job_state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    view, uri = found
    if view.status != JobStatus.COMPLETE:
        raise _problem(409, "not_complete", "the transcript is not ready")
    output = TranscriptionOutput.model_validate_json(
        await _load_transcript(state, claims.tid, job_id, uri)
    )
    outcome, proposals, _discarded = await corrections.plan_for(
        output,
        glossary=glossary,
        attendees=attendees,
        hint=job_state.hint,
        auto_apply=settings.entity_unify_auto_apply,
        per_hour=settings.entity_unify_budget_s_per_hour,
        floor=settings.entity_unify_budget_floor_s,
    )
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        await corrections.recompute(
            conn, tenant_id=claims.tid, job_id=job_id, status=outcome, proposals=proposals
        )
        result = await _view(conn, job_id)
    await audit_proposed(state, claims, job_id, proposals)
    assert result is not None
    return result


async def audit_proposed(
    state: object, claims: Claims, job_id: UUID, proposals: list[entity_unify.Proposal]
) -> None:
    if not proposals:
        return
    await state.audit_writer.write_event(  # type: ignore[attr-defined]
        tenant_id=claims.tid,
        kind=audit_kinds.TRANSCRIPT_CORRECTION_PROPOSED,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="asr_job",
        target_id=str(job_id),
        payload={
            "by_status": dict(Counter(p.status for p in proposals)),
            "by_source": dict(Counter(p.source for p in proposals)),
        },
        severity=Severity.INFO,
    )
