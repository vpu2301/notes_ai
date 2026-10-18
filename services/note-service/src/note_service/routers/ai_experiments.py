"""A/B experiments on fixed transcripts (S3).

    POST /v1/ai/experiments                          admin: queue (``idempotency_key`` in the body)
    GET  /v1/ai/experiments/{id}                     every member: status, per-run metrics
    GET  /v1/ai/experiments/{id}/runs/{run}/artifact the produced note, under source access
    POST /v1/ai/experiments/{id}/cancel              admin: stop what has not started
    POST /v1/ai/experiments/{id}/reviews             a reviewer with source access
    GET  /v1/ai/experiments/{id}/reviews             reviews, under source access

Nothing here writes a note. Sources are read with the caller's own access (the
note's view level and its transcript gate) and its own bearer, frozen as the
experiment's snapshot, and checked again whenever results that may quote them are
read. Errors: 403 forbidden or plan, 404 inaccessible (never a hint of another
workspace), 409 conflicts (revision, processor, budget), 422 invalid, 429 busy.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..config import settings as app_settings
from ..deps import get_state, requires
from ..domain import access, experiments, generation_service
from ..domain import ai_settings as settings_rules
from ..domain import generation_repository as gen_repo
from ..domain import notes_repository as repo
from ..domain import prompt_profile_repository as profile_repo
from ..domain import prompt_profiles as profile_rules
from . import ai_profiles
from .notes_from_transcript import _fetch_transcript

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ai", tags=["ai"])


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    transcript_rev: int = Field(ge=1)


class StartExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[SourceRef] = Field(min_length=1, max_length=experiments.MAX_SOURCES)
    """Candidate profile versions in order; null = the bundled profile."""
    candidate_version_ids: list[UUID | None] = Field(
        min_length=1, max_length=experiments.MAX_CANDIDATES
    )
    repetitions: int = Field(default=3, ge=1, le=experiments.MAX_REPETITIONS)
    length: Literal["short", "standard", "detailed"] = "standard"
    output_language: str = Field(default="auto", pattern=r"^(auto|en|de|uk)$")
    budget_cap_cents: int = Field(ge=0, le=1_000_000)
    """The client's key for this request: a retry with it returns the first experiment.
    In the body, not a header — the service's CORS allows no custom headers."""
    idempotency_key: str = Field(min_length=8, max_length=200)


class RunView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    candidate_index: int
    source_index: int
    repetition: int
    state: str
    metrics: dict[str, Any]
    error_kind: str | None
    cost_cents: float | None
    latency_ms: int | None
    """The produced note may be opened (the caller can still read the source's transcript)."""
    artifact_available: bool
    config: dict[str, Any]


class ExperimentView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    state: str
    sources: list[dict[str, Any]]
    candidates: list[UUID | None]
    repetitions: int
    length: str
    output_language: str
    budget_cap_cents: int
    reserved_cents: float
    spent_cents: float
    """False: a backend has no price; cost is unknown and ``token_cap`` bounds the run."""
    cost_known: bool
    token_cap: int
    tokens_used: int
    error_kind: str | None
    runs: list[RunView]
    """True when a source's transcript was re-labelled since the experiment was queued:
    the comparison no longer counts as evidence for activation."""
    stale: bool = False


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_a_id: UUID
    run_b_id: UUID
    blind: bool
    revealed: bool = False
    preference: Literal["a", "b", "tie", "neither"]
    findings: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    comment: str = Field(default="", max_length=4000)


def _require_admin(claims: Claims) -> None:
    ai_profiles._require_admin(claims)


async def _audit(claims: Claims, kind: str, target: UUID, payload: dict[str, Any]) -> None:
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="tenant",
        target_id=target,
        payload=payload,
        severity=Severity.INFO,
    )


def _costs() -> Any:
    try:
        from jobs import CostTable

        return CostTable.load(app_settings.models_config)
    except Exception:  # noqa: BLE001 — no prices: cost is unknown, never invented
        return None


def _routed_backend(tenant_id: UUID) -> dict[str, Any]:
    """The backend the workspace's routing picks for the notes writer, pinned now."""
    try:
        resolved = ai_profiles.ai_settings_router._registry().resolve(str(tenant_id), "summarize")
        return {"backend": resolved.name, "model_id": resolved.model_id, "routed": True}
    except Exception:  # noqa: BLE001
        writer, _small = ai_profiles.ai_settings_router._writers()
        return {
            "backend": writer.backend if writer else None,
            "model_id": writer.model_id if writer else None,
            "routed": True,
        }


async def _readable_source(conn: Any, claims: Claims, note_id: UUID) -> Any:
    """The note when the caller may read its transcript: 404 when they cannot even see
    it, 403 when they see it but not its transcript."""
    note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
    if not access.can_read_transcript(note, claims):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "transcript_not_shared", "detail": "you cannot read this transcript"},
        )
    return note


async def _can_read(conn: Any, claims: Claims, note_id: UUID) -> bool:
    note = await repo.fetch_note(conn, note_id=note_id)
    return (
        note is not None
        and access.can_view(note, claims)
        and access.can_read_transcript(note, claims)
    )


@dataclass(slots=True)
class _Prepared:
    candidates: list[tuple[profile_rules.ProfileConfig, profile_repo.Version | None]]
    notes: list[Any]
    transcripts: list[dict[str, Any]]
    roles_of: list[tuple[dict[str, str], str | None]]
    routed: dict[str, Any]
    reservation: experiments.Estimate


async def _prepare(
    state: Any, claims: Claims, body: StartExperimentRequest, auth_header: str
) -> _Prepared:
    """Candidates checked (exist, compatible, valid, processors agreed), sources read with
    the caller's own access and bearer at the chosen revision, and the reservation.
    Shared by start and estimate, so an estimate is what a start would reserve."""
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        candidates: list[tuple[profile_rules.ProfileConfig, profile_repo.Version | None]] = []
        for version_id in body.candidate_version_ids:
            if version_id is None:
                candidates.append((profile_rules.BUNDLED, None))
                continue
            version = await profile_repo.fetch_version(conn, version_id=version_id)
            if version is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")
            why = ai_profiles._compatibility(version)
            if why is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={"code": "incompatible_version", "detail": why},
                )
            candidates.append((version.config, version))
        available = await ai_profiles._capabilities(conn, claims.tid)
        for config, _version in candidates:
            problems = profile_rules.validate(config, available)
            if problems:
                raise ai_profiles._unprocessable(problems)
            missing = ai_profiles._unacknowledged(config, available)
            if missing:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={
                        "code": "processor_unacknowledged",
                        "detail": "a workspace admin has to agree to who processes your meetings",
                        "processors": missing,
                    },
                )
        notes = [await _readable_source(conn, claims, s.note_id) for s in body.sources]
        for note in notes:
            if note.source_asr_job_id is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={
                        "code": "no_transcript",
                        "detail": "a source was not made from a recording",
                    },
                )
        from ..jobs.generate_note import _role_map

        roles_of = [await _role_map(conn, note_id=n.id) for n in notes]

    # Outside the transaction, with the caller's bearer: asr-service authorises the read.
    transcripts = [
        await _fetch_transcript(n.source_asr_job_id, auth_header=auth_header) for n in notes
    ]
    for ref, transcript in zip(body.sources, transcripts, strict=True):
        if int(transcript.get("result_rev") or 1) != ref.transcript_rev:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "source_revision_conflict",
                    "detail": "a transcript changed since it was chosen; choose it again",
                    "note_id": str(ref.note_id),
                    "transcript_rev": int(transcript.get("result_rev") or 1),
                },
            )

    routed = _routed_backend(claims.tid)
    costs = _costs()
    bound = sorted(
        {
            (config.models.get(stage) or routed.get("backend") or "")
            for config, _v in candidates
            for stage in profile_rules.STAGES
        }
        - {""}
    )
    reservation = experiments.estimate(
        source_chars=[len(json.dumps(t)) for t in transcripts],
        candidates=len(candidates),
        repetitions=body.repetitions,
        cents_per_1k=experiments.price_per_1k(costs, bound),
    )

    return _Prepared(
        candidates=candidates,
        notes=notes,
        transcripts=transcripts,
        roles_of=roles_of,
        routed=routed,
        reservation=reservation,
    )


@router.post("/experiments", status_code=status.HTTP_202_ACCEPTED, response_model=ExperimentView)
async def start_experiment(
    body: StartExperimentRequest,
    request: Request,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> ExperimentView:
    """Queue every candidate on the same frozen sources. A retry with the same
    ``idempotency_key`` returns the first experiment: a paid run is never doubled."""
    idempotency_key = body.idempotency_key
    _require_admin(claims)
    state = get_state()
    auth_header = request.headers.get("authorization") or ""

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        existing = await experiments.by_key(conn, idempotency_key=idempotency_key)
        if existing is not None:
            return await _view(conn, claims, existing)

    prepared = await _prepare(state, claims, body, auth_header)
    candidates, notes, transcripts, roles_of = (
        prepared.candidates,
        prepared.notes,
        prepared.transcripts,
        prepared.roles_of,
    )
    routed, reservation = prepared.routed, prepared.reservation

    experiment_id = uuid4()
    # Before the row, like a generation snapshot: an orphan object is cheap, an orphan row is not.
    for index, (transcript, note, (role_by_key, template_code)) in enumerate(
        zip(transcripts, notes, roles_of, strict=True)
    ):
        await state.transcripts_store.put(
            key=experiments.source_key(claims.tid, experiment_id, index),
            plaintext=json.dumps(
                {
                    "result": transcript,
                    "role_by_key": role_by_key,
                    "template_family": template_code,
                    "meeting_type": getattr(note, "meeting_type", None),
                }
            ).encode("utf-8"),
            tenant_id=claims.tid,
            aad=experiment_id.bytes,
        )

    snapshots = {
        index: profile_rules.snapshot(
            config,
            version_id=str(version.id) if version else None,
            version_hash=version.content_hash if version else None,
            multilingual=True,
            fidelity=True,
            language_hint=body.output_language if body.output_language != "auto" else "en",
            models={
                stage: (
                    {"backend": config.models[stage], "routed": False}
                    if config.models.get(stage)
                    else routed
                )
                for stage in profile_rules.STAGES
            },
        )
        for index, (config, version) in enumerate(candidates)
    }

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        try:
            await generation_service.check_allowed(conn, tenant_id=claims.tid)
        except generation_service.GenerationDisabledError:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "generation_disabled",
                    "detail": "AI is turned off for this workspace",
                },
            ) from None
        except generation_service.BudgetExceededError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "budget_exceeded", "detail": "this workspace has spent its AI budget",
                        "spent_cents": exc.spent, "budget_cents": exc.budget},
            ) from None  # fmt: skip
        row = await settings_rules.fetch(conn, tenant_id=claims.tid)
        _plan, limits = await ai_profiles.ai_settings_router._plan(conn, claims.tid)
        budget = settings_rules.budget_cents(row, limits)
        spent = await settings_rules.month_to_date_cents(conn, tenant_id=claims.tid)
        held = float(await experiments.reserved_elsewhere(conn))
        # numeric sums come back as Decimal; the budget is whole cents.
        left = int(float(budget) - float(spent) - held)
        if reservation.cents is not None and (
            reservation.cents > body.budget_cap_cents or reservation.cents > left
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "experiment_budget",
                    "detail": "the estimate does not fit the cap or the month's budget",
                    "estimate_cents": reservation.cents,
                    "cap_cents": body.budget_cap_cents,
                    "left_cents": left,
                },
            )
        try:
            experiment, created = await experiments.create(
                conn,
                experiment_id=experiment_id,
                tenant_id=claims.tid,
                created_by=claims.sub,
                idempotency_key=idempotency_key,
                sources=[
                    {
                        "note_id": str(ref.note_id),
                        "transcript_rev": ref.transcript_rev,
                        "snapshot_key": experiments.source_key(claims.tid, experiment_id, i),
                    }
                    for i, ref in enumerate(body.sources)
                ],
                candidates=[str(v) if v else None for v in body.candidate_version_ids],
                repetitions=body.repetitions,
                length=body.length,
                output_language=body.output_language,
                budget_cap_cents=body.budget_cap_cents,
                reservation=reservation,
                run_snapshots=snapshots,
            )
        except experiments.ExperimentActiveError:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "experiment_active",
                    "detail": "one experiment at a time; wait or cancel it",
                },
            ) from None
        if created:
            await state.job_queue.enqueue(
                claims.tid,
                experiments.JOB_KIND,
                {"experiment_id": str(experiment.id)},
                max_attempts=2,
                idempotency_key=f"experiment:{experiment.id}",
                conn=conn,
            )
        view = await _view(conn, claims, experiment)
    if created:
        await _audit(
            claims,
            audit_kinds.AI_EXPERIMENT_STARTED,
            experiment.id,
            {
                "sources": len(body.sources),
                "candidates": len(candidates),
                "repetitions": body.repetitions,
                "cost_known": reservation.cents is not None,
            },
        )
    return view


class EstimateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runs: int
    """None when a bound backend has no price: shown as unknown, never guessed."""
    estimate_cents: float | None
    token_cap: int
    cost_known: bool
    """Each source at the revision that would be frozen, and the languages it was spoken in."""
    sources: list[dict[str, Any]]


@router.post("/experiments/estimate", response_model=EstimateView)
async def estimate_experiment(
    body: StartExperimentRequest,
    request: Request,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> EstimateView:
    """What starting this experiment would reserve, through the same checks as a start
    (access, revision, processors). Queues nothing."""
    _require_admin(claims)
    prepared = await _prepare(get_state(), claims, body, request.headers.get("authorization") or "")
    return EstimateView(
        runs=prepared.reservation.runs,
        estimate_cents=prepared.reservation.cents,
        token_cap=prepared.reservation.tokens,
        cost_known=prepared.reservation.cents is not None,
        sources=[
            {
                "note_id": str(ref.note_id),
                "transcript_rev": int(t.get("result_rev") or 1),
                "languages": _languages(t),
            }
            for ref, t in zip(body.sources, prepared.transcripts, strict=True)
        ],
    )


def _languages(result: dict[str, Any]) -> list[str]:
    """The recording's language first, then any other a turn was decoded in."""
    found = [str(result.get("language") or "")]
    for turn in result.get("turns") or []:
        code = str(turn.get("language") or "")
        if code and code not in found:
            found.append(code)
    return [c for c in found if c]


class ExperimentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    state: str
    candidates: list[UUID | None]
    sources: int
    repetitions: int
    cost_known: bool
    spent_cents: float
    created_at: datetime


@router.get("/experiments", response_model=list[ExperimentSummary])
async def list_experiments(
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> list[ExperimentSummary]:
    """The workspace's recent experiments: states and counts, no content."""
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        found = await experiments.recent(conn)
    return [
        ExperimentSummary(
            id=e.id,
            state=e.state,
            candidates=[UUID(c) if c else None for c in e.candidates],
            sources=len(e.sources),
            repetitions=e.repetitions,
            cost_known=e.cost_known,
            spent_cents=float(e.spent_cents),
            created_at=e.created_at,
        )
        for e in found
    ]


async def _view(conn: Any, claims: Claims, experiment: experiments.Experiment) -> ExperimentView:
    readable = [await _can_read(conn, claims, UUID(s["note_id"])) for s in experiment.sources]
    planned = await experiments.runs(conn, experiment_id=experiment.id)
    # Versions never change; a source does when its transcript was re-labelled since.
    stale = False
    for source in experiment.sources:
        latest = await gen_repo.latest_for_note(conn, note_id=UUID(source["note_id"]))
        if latest is not None and latest.transcript_rev != source["transcript_rev"]:
            stale = True
    return ExperimentView(
        id=experiment.id,
        state=experiment.state,
        # Which notes, and which revision: references, never content.
        sources=[
            {
                "note_id": s["note_id"],
                "transcript_rev": s["transcript_rev"],
                "readable": readable[i],
            }
            for i, s in enumerate(experiment.sources)
        ],
        candidates=[UUID(c) if c else None for c in experiment.candidates],
        repetitions=experiment.repetitions,
        length=experiment.length,
        output_language=experiment.output_language,
        budget_cap_cents=experiment.budget_cap_cents,
        reserved_cents=float(experiment.reserved_cents),
        spent_cents=float(experiment.spent_cents),
        cost_known=experiment.cost_known,
        token_cap=experiment.token_cap,
        tokens_used=experiment.tokens_used,
        error_kind=experiment.error_kind,
        runs=[
            RunView(
                id=r.id,
                candidate_index=r.candidate_index,
                source_index=r.source_index,
                repetition=r.repetition,
                state=r.state,
                metrics=r.metrics,
                error_kind=r.error_kind,
                cost_cents=float(r.cost_cents) if r.cost_cents is not None else None,
                latency_ms=r.latency_ms,
                artifact_available=bool(r.artifact_key) and readable[r.source_index],
                # Hashes, flags, versions and models; the stage texts stay with the version.
                config={k: v for k, v in r.config_snapshot.items() if k != "config"},
            )
            for r in planned
        ],
        stale=stale,
    )


async def _experiment_or_404(conn: Any, experiment_id: UUID) -> experiments.Experiment:
    found = await experiments.fetch(conn, experiment_id=experiment_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="experiment not found")
    return found


@router.get("/experiments/{experiment_id}", response_model=ExperimentView)
async def get_experiment(
    experiment_id: UUID,
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> ExperimentView:
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        return await _view(conn, claims, await _experiment_or_404(conn, experiment_id))


@router.get("/experiments/{experiment_id}/runs/{run_id}/artifact")
async def get_artifact(
    experiment_id: UUID,
    run_id: UUID,
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> dict[str, Any]:
    """The produced note of one run — only for someone who can read the source's
    transcript now (access is checked again on every read)."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        experiment = await _experiment_or_404(conn, experiment_id)
        run = next(
            (
                r
                for r in await experiments.runs(conn, experiment_id=experiment_id)
                if r.id == run_id
            ),
            None,
        )
        if run is None or not run.artifact_key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
        source = experiment.sources[run.source_index]
        if not await _can_read(conn, claims, UUID(source["note_id"])):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="run not found")
    raw = await state.transcripts_store.get(
        key=run.artifact_key, tenant_id=claims.tid, aad=run.id.bytes
    )
    return json.loads(raw)


@router.post("/experiments/{experiment_id}/cancel", response_model=ExperimentView)
async def cancel_experiment(
    experiment_id: UUID,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> ExperimentView:
    """Stops what has not started. A run already in flight may finish, and its cost
    stays accounted; completed results are kept."""
    _require_admin(claims)
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        await _experiment_or_404(conn, experiment_id)
        moved = await experiments.set_state(
            conn, experiment_id=experiment_id, state="cancelled", only_from=experiments.ACTIVE
        )
        cancelled = (
            await experiments.cancel_pending(
                conn, experiment_id=experiment_id, error_kind="cancelled"
            )
            if moved
            else 0
        )
        view = await _view(conn, claims, await _experiment_or_404(conn, experiment_id))
    if moved:
        await _audit(
            claims,
            audit_kinds.AI_EXPERIMENT_CANCELLED,
            experiment_id,
            {"runs_cancelled": cancelled},
        )
    return view


@router.post("/experiments/{experiment_id}/reviews", status_code=status.HTTP_201_CREATED)
async def add_review(
    experiment_id: UUID,
    body: ReviewRequest,
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> dict[str, Any]:
    """A preference and factual findings for one pair of runs on the same source and
    repetition. The reviewer must be able to read that source's transcript."""
    for finding in body.findings:
        if finding.get("label") not in experiments.FINDING_LABELS or finding.get("run") not in (
            "a",
            "b",
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "invalid_finding", "labels": sorted(experiments.FINDING_LABELS)},
            )
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        experiment = await _experiment_or_404(conn, experiment_id)
        by_id = {r.id: r for r in await experiments.runs(conn, experiment_id=experiment_id)}
        a, b = by_id.get(body.run_a_id), by_id.get(body.run_b_id)
        if a is None or b is None or a.source_index != b.source_index or a.id == b.id:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="runs not found in this experiment"
            )
        if not await _can_read(conn, claims, UUID(experiment.sources[a.source_index]["note_id"])):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="runs not found in this experiment"
            )
        review_id = await experiments.add_review(
            conn,
            tenant_id=claims.tid,
            experiment_id=experiment_id,
            run_a_id=a.id,
            run_b_id=b.id,
            reviewer=claims.sub,
            blind=body.blind,
            revealed=body.revealed,
            preference=body.preference,
            findings=body.findings,
            comment=body.comment,
        )
    return {"id": str(review_id)}


@router.get("/experiments/{experiment_id}/reviews")
async def list_reviews(
    experiment_id: UUID,
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> list[dict[str, Any]]:
    """Reviews whose source the caller can still read; comments may quote it."""
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        experiment = await _experiment_or_404(conn, experiment_id)
        runs = {r.id: r for r in await experiments.runs(conn, experiment_id=experiment_id)}
        readable = [await _can_read(conn, claims, UUID(s["note_id"])) for s in experiment.sources]
        out = []
        for review in await experiments.reviews(conn, experiment_id=experiment_id):
            run = runs.get(review["run_a_id"])
            if run is not None and readable[run.source_index]:
                out.append({k: (str(v) if isinstance(v, UUID) else v) for k, v in review.items()})
    return out
