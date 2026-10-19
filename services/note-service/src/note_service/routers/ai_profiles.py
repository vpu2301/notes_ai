"""Prompt/model profiles (S3): versions saved, never edited; one pointer activated.

    GET  /v1/ai/prompt-profiles                          every member: profiles, versions, active
    POST /v1/ai/prompt-profiles                          admin: a new profile (optionally a copy)
    POST /v1/ai/prompt-profiles/{id}/versions            admin: validate and save; never activates
    GET  /v1/ai/prompt-profiles/{id}/versions/{version}  every member: configuration and preview
    POST /v1/ai/prompt-profiles/{id}/activate            admin: move the pointer (expected revision)
    GET  /v1/ai/prompt-profiles/history                  every member: who activated what, when
    GET  /v1/ai/model-capabilities                       every member: what may be bound, and how
    GET  /v1/ai/runtime                                  every member: what new notes here run on

The same permissions as ``/v1/ai/settings`` (``ai_settings.read`` to look, an admin
with ``ai_settings.write`` to change), checked here, not in a client. Ids of another
workspace are invisible (RLS) and answer 404.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..config import settings as app_settings
from ..deps import get_state, requires
from ..domain import acceptance, experiments
from ..domain import ai_settings as settings_rules
from ..domain import prompt_profile_repository as repo
from ..domain import prompt_profiles as rules
from ..domain.meeting_doc import prompts
from . import ai_settings as ai_settings_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ai", tags=["ai"])

_ADMIN_ROLES = frozenset({"tenant_admin"})


def _require_admin(claims: Claims) -> None:
    if not (_ADMIN_ROLES & set(claims.roles)):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="only a workspace admin can change how notes are written",
        )


# ── Views ───────────────────────────────────────────────────────────


class VersionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version_number: int
    content_hash: str
    created_by: UUID
    created_at: datetime
    """Whether this deployment can run it; else ``incompatible_reason`` says what to do."""
    compatible: bool
    incompatible_reason: str | None = None


class ProfileView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str
    created_at: datetime
    versions: list[VersionSummary]


class ActiveView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    """None = the profile bundled with this deployment."""
    profile_version_id: UUID | None
    revision: int
    activated_by: UUID | None = None
    activated_at: datetime | None = None


class ProfilesView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: ActiveView
    profiles: list[ProfileView]
    can_edit: bool
    contract_version: str
    algorithm_version: str
    stages: list[str]
    max_stage_chars: int
    variables: list[str]


class CreateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    """Duplicate: version 1 of the new profile is a copy of this version."""
    copy_of_version_id: UUID | None = None


class SaveVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: rules.ProfileConfig


class VersionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    profile_id: UUID
    version_number: int
    config: rules.ProfileConfig
    content_hash: str
    contract_version: str
    schema_version: str
    algorithm_version: str
    created_by: UUID
    created_at: datetime
    compatible: bool
    incompatible_reason: str | None = None
    """``{stage: its first call's full system text}`` on the path a test run takes."""
    effective: dict[str, str]
    language: str
    """Every call a run makes, resolved exactly (``mode``, flags, model profile in ``flags``)."""
    calls: list[ResolvedCallView] = []
    flags: dict[str, Any] = {}


class ActivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    """None = back to the bundled profile."""
    version_id: UUID | None
    expected_active_revision: int = Field(ge=0)
    """The experiment this activation rests on, recorded in the history."""
    evaluation_ref: UUID | None = None


class CapabilitiesView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    models: list[dict[str, Any]]
    """The stage → routing-operation mapping these bindings use (all ``chat``)."""
    stage_operations: dict[str, str]
    writer: dict[str, Any] | None = None


# ── Helpers ─────────────────────────────────────────────────────────


def _compatibility(version: repo.Version) -> str | None:
    return rules.compatible(
        contract_version=version.contract_version,
        schema=version.schema_version,
        algorithm_version=version.algorithm_version,
    )


def _summary(version: repo.Version) -> VersionSummary:
    why = _compatibility(version)
    return VersionSummary(
        id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
        created_by=version.created_by,
        created_at=version.created_at,
        compatible=why is None,
        incompatible_reason=why,
    )


async def _capabilities(conn: asyncpg.Connection, tenant_id: UUID) -> list[rules.Capability]:
    row = await settings_rules.fetch(conn, tenant_id=tenant_id)
    try:
        registry = ai_settings_router._registry()
    except Exception:  # noqa: BLE001 — no registry: nothing can be bound
        logger.warning("ai_profiles.registry_unavailable", exc_info=True)
        return []
    return rules.capabilities(registry, acknowledged=frozenset(row.acknowledged_keys))


def _unprocessable(problems: list[rules.Problem]) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "invalid_profile",
            "detail": "the configuration cannot be saved",
            "problems": [p.as_dict() for p in problems],
        },
    )


def _unacknowledged(
    config: rules.ProfileConfig, available: list[rules.Capability]
) -> list[dict[str, str]]:
    by_name = {c.backend: c for c in available}
    out = []
    for name in {n for n in config.models.values() if n}:
        capability = by_name.get(name)
        if capability is not None and not capability.acknowledged:
            out.append({"name": capability.processor or name, "region": capability.region or ""})
    return out


async def _audit(
    claims: Claims, kind: str, target_id: UUID | None, payload: dict[str, Any]
) -> None:
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="tenant",
        target_id=target_id or claims.tid,
        payload=payload,
        severity=Severity.INFO,
    )


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/prompt-profiles", response_model=ProfilesView)
async def list_profiles(
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> ProfilesView:
    """Every member may see how this workspace's notes are written."""
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        profiles = await repo.list_profiles(conn)
        versions = await repo.list_versions(conn)
        pointer = await repo.binding(conn, tenant_id=claims.tid)
    by_profile: dict[UUID, list[VersionSummary]] = {}
    for version in versions:
        by_profile.setdefault(version.profile_id, []).append(_summary(version))
    return ProfilesView(
        active=ActiveView(
            profile_version_id=pointer.profile_version_id,
            revision=pointer.revision,
            activated_by=pointer.activated_by,
            activated_at=pointer.activated_at,
        ),
        profiles=[
            ProfileView(
                id=p.id,
                name=p.name,
                description=p.description,
                created_at=p.created_at,
                versions=by_profile.get(p.id, []),
            )
            for p in profiles
        ],
        can_edit=bool(_ADMIN_ROLES & set(claims.roles)),
        contract_version=rules.CONTRACT_VERSION,
        algorithm_version=rules.ALGORITHM_VERSION,
        stages=list(rules.STAGES),
        max_stage_chars=rules.MAX_STAGE_CHARS,
        variables=sorted(rules.VARIABLES),
    )


@router.post("/prompt-profiles", status_code=status.HTTP_201_CREATED, response_model=ProfileView)
async def create_profile(
    body: CreateProfileRequest,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> ProfileView:
    _require_admin(claims)
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        source: repo.Version | None = None
        if body.copy_of_version_id is not None:
            source = await repo.fetch_version(conn, version_id=body.copy_of_version_id)
            if source is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")
        profile = await repo.create_profile(
            conn,
            tenant_id=claims.tid,
            name=body.name.strip(),
            description=body.description.strip(),
            created_by=claims.sub,
        )
        versions: list[VersionSummary] = []
        if source is not None:
            copied = await repo.create_version(
                conn,
                tenant_id=claims.tid,
                profile_id=profile.id,
                config=source.config,
                created_by=claims.sub,
            )
            versions.append(_summary(copied))
    return ProfileView(
        id=profile.id,
        name=profile.name,
        description=profile.description,
        created_at=profile.created_at,
        versions=versions,
    )


@router.post(
    "/prompt-profiles/{profile_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionSummary,
)
async def save_version(
    profile_id: UUID,
    body: SaveVersionRequest,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> VersionSummary:
    """Validate and save an immutable version. It does not activate: what writes the
    workspace's notes changes only through ``activate``."""
    _require_admin(claims)
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        if await repo.fetch_profile(conn, profile_id=profile_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="profile not found")
        available = await _capabilities(conn, claims.tid)
        context = min((c.context_window for c in available), default=None)
        problems = rules.validate(body.config, available, context_tokens=context)
        if problems:
            raise _unprocessable(problems)
        try:
            version = await repo.create_version(
                conn,
                tenant_id=claims.tid,
                profile_id=profile_id,
                config=body.config,
                created_by=claims.sub,
            )
        except asyncpg.UniqueViolationError:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "version_conflict", "detail": "another version was saved; retry"},
            ) from None
    await _audit(
        claims,
        audit_kinds.AI_PROFILE_VERSION_SAVED,
        profile_id,
        {
            "profile_id": str(profile_id),
            "version_number": version.version_number,
            "stages": sorted(s for s, t in body.config.stages.items() if t is not None),
        },
    )
    return _summary(version)


class ResolvedCallView(BaseModel):
    """One call a run makes and its exact system text: where the text comes from
    (``profile``, ``bundled``, ``not_applied`` — the flags send no profile text — or
    ``code``, read-only here), and its sha256 (what the run's request hash must equal)."""

    model_config = ConfigDict(extra="forbid")

    call: str
    stage: str
    source: str
    sha: str
    system: str


# "production": what a note generated now runs with in this deployment; "test": the path
# an experiment run always takes (multilingual evidence and fidelity on).
PreviewMode = Literal["production", "test"]
VersionView.model_rebuild()


def _mode_flags(mode: str) -> tuple[bool, bool]:
    if mode == "test":
        return True, True
    multilingual = app_settings.note_multilingual_evidence
    return multilingual, multilingual and app_settings.note_fidelity


def _resolved(
    config: rules.ProfileConfig,
    *,
    language: str,
    mode: str,
    available: list[rules.Capability],
) -> tuple[list[ResolvedCallView], dict[str, Any]]:
    """The calls for ``mode`` — the resolver a generation and an experiment use — with
    the small-model profile of the model bound to extraction (else the routed writer's)."""
    multilingual, fidelity = _mode_flags(mode)
    bound = config.models.get("extraction")
    capability = next((c for c in available if c.backend == bound), None) if bound else None
    small = bool(capability.small_model) if capability is not None else False
    calls = rules.resolve(
        config, language=language, multilingual=multilingual, fidelity=fidelity, small=small
    )
    views = [
        ResolvedCallView(call=c.call, stage=c.stage, source=c.source, sha=c.sha, system=c.system)
        for c in calls
    ]
    flags = {
        "mode": mode,
        "multilingual_evidence": multilingual,
        "fidelity": fidelity,
        "final_check": fidelity,
        "small_model": small,
        "bullets": rules.DEFAULT_BULLETS,
        "profile_instructions_apply": multilingual,
    }
    return views, flags


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: rules.ProfileConfig
    language: str = Field(default="en", pattern=r"^(en|de|uk)$")
    mode: PreviewMode = "test"


class PreviewView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    """Every reason it could not be saved (empty: it can), field by field."""
    problems: list[dict[str, str]]
    """What each stage would send — the same function a generation uses. A preview is
    not a test: nothing has run on this configuration."""
    effective: dict[str, str]
    language: str
    """Each stage's bundled task text for ``language``: where an edit starts."""
    bundled: dict[str, str]
    """Every call, resolved exactly for ``flags`` (empty while the draft has problems)."""
    calls: list[ResolvedCallView] = []
    flags: dict[str, Any] = {}
    """Variables each editable stage must keep (its bundled text uses them)."""
    required_variables: dict[str, list[str]] = {}


@router.post("/prompt-profiles/preview", response_model=PreviewView)
async def preview(
    body: PreviewRequest,
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> PreviewView:
    """An unsaved draft, validated and resolved. Saves nothing."""
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        available = await _capabilities(conn, claims.tid)
    context = min((c.context_window for c in available), default=None)
    problems = rules.validate(body.config, available, context_tokens=context)
    effective = {
        stage: rules.effective_instructions(body.config, stage, language=body.language)
        for stage in rules.STAGES
        if not any(p.field == f"stages.{stage}" for p in problems)
    }
    calls, flags = (
        _resolved(body.config, language=body.language, mode=body.mode, available=available)
        if not problems
        else ([], {"mode": body.mode})
    )
    return PreviewView(
        problems=[p.as_dict() for p in problems],
        effective=effective,
        language=body.language,
        bundled={stage: rules.bundled_text(stage, body.language) for stage in rules.STAGES},
        calls=calls,
        flags=flags,
        required_variables={s: sorted(rules.required_variables(s)) for s in rules.STAGES},
    )


@router.get("/prompt-profiles/{profile_id}/versions/{version_id}", response_model=VersionView)
async def get_version(
    profile_id: UUID,
    version_id: UUID,
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
    language: Annotated[str, Query(pattern=r"^(en|de|uk)$")] = "en",
    mode: Annotated[PreviewMode, Query()] = "test",
) -> VersionView:
    """The configuration and its effective instructions — the same function a
    generation uses — with no secret in it (bindings are backend names)."""
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        version = await repo.fetch_version(conn, version_id=version_id)
        available = await _capabilities(conn, claims.tid)
    if version is None or version.profile_id != profile_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")
    why = _compatibility(version)
    calls, flags = _resolved(version.config, language=language, mode=mode, available=available)
    return VersionView(
        id=version.id,
        profile_id=version.profile_id,
        version_number=version.version_number,
        config=version.config,
        content_hash=version.content_hash,
        contract_version=version.contract_version,
        schema_version=version.schema_version,
        algorithm_version=version.algorithm_version,
        created_by=version.created_by,
        created_at=version.created_at,
        compatible=why is None,
        incompatible_reason=why,
        effective={
            stage: rules.effective_instructions(version.config, stage, language=language)
            for stage in rules.STAGES
        },
        language=language,
        calls=calls,
        flags=flags,
    )


@router.post("/prompt-profiles/{profile_id}/activate", response_model=ActiveView)
async def activate(
    profile_id: UUID,
    body: ActivateRequest,
    claims: Annotated[Claims, Depends(requires("ai_settings.write", "tenant"))],
) -> ActiveView:
    """Move the active pointer — activation and rollback alike — atomically from the
    revision the admin saw. Future generations only; queued ones keep their pin."""
    _require_admin(claims)
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        if body.version_id is not None:
            version = await repo.fetch_version(conn, version_id=body.version_id)
            if version is None or version.profile_id != profile_id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="version not found")
            why = _compatibility(version)
            if why is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={"code": "incompatible_version", "detail": why},
                )
            available = await _capabilities(conn, claims.tid)
            missing = _unacknowledged(version.config, available)
            if missing:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    detail={
                        "code": "processor_unacknowledged",
                        "detail": "a workspace admin has to agree to who processes your meetings",
                        "processors": missing,
                    },
                )
            problems = rules.validate(version.config, available)
            if problems:
                # A bound model or setting no longer offered: the version stays a draft.
                raise _unprocessable(problems)
            # A version that wrote this workspace's notes before is a rollback; anything
            # else needs a finished evaluation with no critical finding against it.
            was_active = any(
                h.get("profile_version_id") == body.version_id for h in await repo.history(conn)
            )
            if not was_active:
                why_not = (
                    "an untested version stays a draft: run an evaluation first"
                    if body.evaluation_ref is None
                    else await experiments.evidence_problem(
                        conn, experiment_id=body.evaluation_ref, version_id=body.version_id
                    )
                )
                if why_not is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        detail={"code": "evaluation_required", "detail": why_not},
                    )
                # P1-04: and the critical cases, passed on this code — preference or cost
                # alone never activates a version that inverts a claim or invents a guest.
                why_critical = await experiments.acceptance_problem(
                    conn, version_id=body.version_id, suite_version=acceptance.suite_version()
                )
                if why_critical is not None:
                    raise HTTPException(
                        status.HTTP_409_CONFLICT,
                        detail={"code": "acceptance_required", "detail": why_critical},
                    )
        previous = await repo.binding(conn, tenant_id=claims.tid)
        try:
            moved = await repo.activate(
                conn,
                tenant_id=claims.tid,
                version_id=body.version_id,
                expected_revision=body.expected_active_revision,
                actor=claims.sub,
                evaluation_ref=body.evaluation_ref,
            )
        except repo.ActivationConflictError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "active_revision_conflict",
                    "detail": "another admin changed the active profile; reload and decide again",
                    "current_revision": exc.current_revision,
                },
            ) from None
    await _audit(
        claims,
        audit_kinds.AI_PROFILE_ACTIVATED,
        profile_id,
        {
            "version_id": str(body.version_id) if body.version_id else None,
            "previous_version_id": (
                str(previous.profile_version_id) if previous.profile_version_id else None
            ),
            "revision": moved.revision,
            "evaluation_ref": str(body.evaluation_ref) if body.evaluation_ref else None,
        },
    )
    return ActiveView(
        profile_version_id=moved.profile_version_id,
        revision=moved.revision,
        activated_by=moved.activated_by,
        activated_at=moved.activated_at,
    )


@router.get("/prompt-profiles/history")
async def history(
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> list[dict[str, Any]]:
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        return await repo.history(conn)


class RuntimeView(BaseModel):
    """F1-01 — what a note generated now is pinned with in this deployment: the code, the
    flags (``fidelity`` includes the final check), the prompt and algorithm versions. Profile
    instructions apply only with ``multilingual_evidence`` on; a test run always uses it."""

    model_config = ConfigDict(extra="forbid")

    build_sha: str | None
    multilingual_evidence: bool
    fidelity: bool
    prompt_version: str
    algorithm_version: str
    profile_instructions_apply: bool


@router.get("/runtime", response_model=RuntimeView)
async def runtime(
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> RuntimeView:
    multilingual = app_settings.note_multilingual_evidence
    fidelity = multilingual and app_settings.note_fidelity
    return RuntimeView(
        build_sha=app_settings.build_sha or None,
        multilingual_evidence=multilingual,
        fidelity=fidelity,
        prompt_version=prompts.effective_version(multilingual=multilingual),
        algorithm_version=rules.ALGORITHM_VERSION,
        profile_instructions_apply=multilingual,
    )


@router.get("/model-capabilities", response_model=CapabilitiesView)
async def model_capabilities(
    claims: Annotated[Claims, Depends(requires("ai_settings.read", "tenant"))],
) -> CapabilitiesView:
    """Registered backends this deployment offers and whether this workspace has
    acknowledged their processor; the parameters each supports, and why not the rest."""
    async with tenant_connection(get_state().app_pool, claims.tid) as conn:
        available = await _capabilities(conn, claims.tid)
    writer, _small = ai_settings_router._writers()
    return CapabilitiesView(
        models=[c.as_dict() for c in available],
        stage_operations=dict(rules.STAGE_OPERATION),
        writer=writer.model_dump() if writer else None,
    )
