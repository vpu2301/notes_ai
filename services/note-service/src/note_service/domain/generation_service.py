"""Starting a generation: snapshot, row, job, in that order.

The snapshot is written before the transaction commits (an orphan object beats
an orphan row); the row and the job share the note's transaction; the job
payload carries ids only. The snapshot exists because note-service has no
service identity to read the transcript later on its own behalf.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Final
from uuid import UUID, uuid4

import asyncpg

from ..config import settings
from . import ai_settings
from . import generation_repository as gen_repo
from . import prompt_profile_repository as profile_repo
from . import prompt_profiles as profiles

logger = logging.getLogger(__name__)

JOB_KIND = "note.generate"
MAX_ATTEMPTS = 3
# A note nobody is watching does not need regenerating ten times a day.
MAX_REGENERATIONS_PER_DAY = 10


# A person pressing Regenerate is waiting on the screen; an automatic run is not.
PRIORITY_REGENERATE: Final = 5
PRIORITY_FOLLOWUP: Final = 3
PRIORITY_AUTO: Final = 0


class GenerationBusyError(Exception):
    """A generation is already queued or running for this note."""


class GenerationDisabledError(Exception):
    """This workspace has turned note generation off."""


class BudgetExceededError(Exception):
    """This workspace has spent its monthly AI budget; the note still works."""

    def __init__(self, spent: int, budget: int) -> None:
        super().__init__(f"{spent} of {budget} cents")
        self.spent = spent
        self.budget = budget


class GenerationRateLimitedError(Exception):
    """Too many runs for this note today."""


def snapshot_key(tenant_id: UUID, note_id: UUID, generation_id: UUID) -> str:
    """Tenant-prefixed, so a key cannot address another tenant's object."""
    return f"{tenant_id}/generation/{note_id}/{generation_id}.json"


async def start(
    conn: asyncpg.Connection,
    *,
    queue: Any,
    store: Any,
    tenant_id: UUID,
    note_id: UUID,
    requested_by: UUID,
    transcript: dict[str, Any],
    reason: str = "auto",
    transcript_rev: int = 1,
    enforce_limit: bool = False,
    priority: int | None = None,
    required_processors: list[Any] | None = None,
) -> tuple[UUID, str]:
    """Snapshot, row, job. Returns ``(generation_id, status)``. The caller holds the transaction."""
    if enforce_limit:
        used = await gen_repo.regenerations_today(conn, note_id=note_id)
        if used >= MAX_REGENERATIONS_PER_DAY:
            raise GenerationRateLimitedError

    # Checked HERE, not in the worker, so a workspace over budget never queues work.
    await check_allowed(conn, tenant_id=tenant_id, required_processors=required_processors)

    generation_id = uuid4()
    job_id = uuid4()
    # Pinned now: a settings or profile change after this never alters this job.
    config_snapshot, incompatible = await pinned_configuration(
        conn, tenant_id=tenant_id, language_hint=str(transcript.get("language") or "en")
    )
    prompt_version = str(config_snapshot["prompt_version"])
    key = snapshot_key(tenant_id, note_id, generation_id)

    # Before the row: an orphan object is cheap, an orphan row is not.
    try:
        await store.put(
            key=key,
            plaintext=json.dumps(transcript).encode("utf-8"),
            tenant_id=tenant_id,
            aad=generation_id.bytes,
        )
    except Exception:  # noqa: BLE001
        # No object store: the note is still a note, it simply has no generation.
        logger.warning("generation.snapshot_failed", extra={"note_id": str(note_id)})
        raise

    try:
        stored_id = await gen_repo.create(
            conn,
            tenant_id=tenant_id,
            note_id=note_id,
            job_id=job_id,
            requested_by=requested_by,
            reason=reason,
            prompt_version=prompt_version,
            transcript_rev=transcript_rev,
            snapshot_key=key,
            # Must be the id the snapshot was sealed with (AAD + object key), or the DEK unwrap fails.
            generation_id=generation_id,
            config_snapshot=config_snapshot,
        )
    except asyncpg.UniqueViolationError as exc:
        # The live-generation index. One run per note at a time.
        raise GenerationBusyError from exc

    if incompatible is not None:
        # The active profile cannot run on this deployment: a visible failure, never a
        # quiet switch to some other configuration.
        await gen_repo.mark(
            conn,
            generation_id=stored_id,
            status=gen_repo.FAILED,
            error_kind=PROFILE_INCOMPATIBLE,
            finished=True,
        )
        return stored_id, gen_repo.FAILED

    await queue.enqueue(
        tenant_id,
        JOB_KIND,
        # Ids only: a job row is read by operators and shipped to metrics.
        {"generation_id": str(stored_id), "note_id": str(note_id)},
        max_attempts=MAX_ATTEMPTS,
        priority=PRIORITY_REGENERATE
        if reason == "regenerate"
        else (priority if priority is not None else PRIORITY_AUTO),
        idempotency_key=(f"{note_id}:{transcript_rev}:{prompt_version}:{secrets.token_hex(4)}"),
        conn=conn,
    )
    return stored_id, gen_repo.QUEUED


# A generation whose workspace's active profile this deployment cannot run.
PROFILE_INCOMPATIBLE: Final = "profile_incompatible"


async def pinned_configuration(
    conn: asyncpg.Connection, *, tenant_id: UUID, language_hint: str
) -> tuple[dict[str, Any], str | None]:
    """``(config snapshot, why the active version cannot run or None)`` for a generation
    queued now: the active profile version (else the bundled one), the flags as they are
    now, and each stage's binding — a named backend, or the workspace's routing."""
    config, version = await profile_repo.active_config(conn, tenant_id=tenant_id)
    incompatible = (
        profiles.compatible(
            contract_version=version.contract_version,
            schema=version.schema_version,
            algorithm_version=version.algorithm_version,
        )
        if version is not None
        else None
    )
    snapshot = profiles.snapshot(
        config,
        version_id=str(version.id) if version is not None else None,
        version_hash=version.content_hash if version is not None else None,
        multilingual=settings.note_multilingual_evidence,
        fidelity=settings.note_fidelity,
        language_hint=language_hint if language_hint in profiles.LANGUAGE_NAMES else "en",
        models={
            stage: (
                {"backend": config.models[stage], "routed": False}
                if config.models.get(stage)
                else {"routed": True}
            )
            for stage in profiles.STAGES
        },
    )
    return snapshot, incompatible


async def check_allowed(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    required_processors: list[Any] | None = None,
) -> None:
    """Raise when this workspace may not generate right now: generation turned off,
    a processor not agreed to (`required_processors`), or the month's budget spent."""
    row = await ai_settings.fetch(conn, tenant_id=tenant_id)
    if not row.generation_enabled:
        raise GenerationDisabledError
    if required_processors:
        missing = ai_settings.missing_acknowledgement(row, required_processors, None)
        if missing:
            raise ProcessorUnacknowledgedError(missing)

    record = await conn.fetchrow("SELECT plan_limits FROM tenants WHERE id = $1", tenant_id)
    limits = record["plan_limits"] if record is not None else None
    if isinstance(limits, str):
        limits = json.loads(limits)
    budget = ai_settings.budget_cents(row, limits or {})
    spent = await ai_settings.month_to_date_cents(conn, tenant_id=tenant_id)
    if spent >= budget:
        raise BudgetExceededError(spent, budget)


class ProcessorUnacknowledgedError(Exception):
    """A processor in the data path no admin of this workspace has agreed to; nothing
    is sent until they do. `processors` is the list to show, by (name, region)."""

    def __init__(self, processors: list[Any]) -> None:
        super().__init__("processor_unacknowledged")
        self.processors = processors
