"""Starting a generation: snapshot, row, job.

Three things happen in a fixed order, and the order is the point.

1. **The snapshot is written first**, before the transaction commits. An
   orphaned object beats an orphaned row — the same rule `submit_job`
   follows for audio. A row pointing at an object that is not there is a
   generation that can never run and never explains itself; an object no
   row points at is swept in a day.
2. **The generation row and the job go in the same transaction** as the
   note. Either the note exists with a job queued for it, or neither
   does.
3. **The job payload carries ids only.** Not the transcript, not the
   title, not a name — a job row is read by operators and shipped to
   metrics, and `jobs.last_error` is scrubbed to an error kind for the
   same reason.

Why a snapshot at all: note-service has no service identity, so it cannot
read another service's artifact on its own behalf later. It reads the
transcript once, in the user's own request, with the user's own bearer —
and keeps what it read, so a re-labelling in asr-service afterwards does
not silently change what a finished note was built from.
"""

from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Final
from uuid import UUID, uuid4

import asyncpg

from . import ai_settings
from . import generation_repository as gen_repo
from .meeting_doc.prompts import PROMPT_VERSION

logger = logging.getLogger(__name__)

JOB_KIND = "note.generate"
MAX_ATTEMPTS = 3
# A note nobody is watching does not need regenerating ten times a day.
MAX_REGENERATIONS_PER_DAY = 10


# Sprint 37 — a queue that is FIFO by priority alone lets one workspace
# uploading fifty recordings starve everyone else's single meeting.
# A person pressing Regenerate is waiting on the screen; an automatic run
# after an upload is not.
PRIORITY_REGENERATE: Final = 5
PRIORITY_FOLLOWUP: Final = 3
PRIORITY_AUTO: Final = 0


class GenerationBusyError(Exception):
    """A generation is already queued or running for this note."""


class GenerationDisabledError(Exception):
    """This workspace has turned note generation off."""


class BudgetExceededError(Exception):
    """This workspace has spent its monthly AI budget.

    The note still works; it simply is not written for them this month,
    and they are told so rather than left watching a spinner.
    """

    def __init__(self, spent: int, budget: int) -> None:
        super().__init__(f"{spent} of {budget} cents")
        self.spent = spent
        self.budget = budget


class GenerationRateLimitedError(Exception):
    """Too many runs for this note today."""


def snapshot_key(tenant_id: UUID, note_id: UUID, generation_id: UUID) -> str:
    """Tenant-prefixed, so a key cannot address another tenant's object
    even if one leaked into a log."""
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
) -> tuple[UUID, str]:
    """Snapshot, row, job. Returns ``(generation_id, status)``.

    The caller holds the transaction; on any failure after this returns,
    the row and the job roll back with it and the object is swept.
    """
    if enforce_limit:
        used = await gen_repo.regenerations_today(conn, note_id=note_id)
        if used >= MAX_REGENERATIONS_PER_DAY:
            raise GenerationRateLimitedError

    # Sprint 37: the workspace's own settings decide whether this runs at
    # all, and what it may cost. Checked HERE rather than in the worker so
    # a workspace over budget never queues work it cannot pay for.
    await check_allowed(conn, tenant_id=tenant_id)

    generation_id = uuid4()
    job_id = uuid4()
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
        # No object store (the privacy-first posture, or a dev Mac with
        # MinIO down). The note is still a note; it simply has no
        # generation, and the client says so rather than spinning.
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
            prompt_version=PROMPT_VERSION,
            transcript_rev=transcript_rev,
            snapshot_key=key,
            # The same id the snapshot was sealed with (AAD + object key).
            # Before this was passed, the database picked a different id
            # and the worker failed every run with "DEK unwrap failed".
            generation_id=generation_id,
        )
    except asyncpg.UniqueViolationError as exc:
        # The live-generation index. One run per note at a time.
        raise GenerationBusyError from exc

    await queue.enqueue(
        tenant_id,
        JOB_KIND,
        # Ids only. A job row is read by operators and shipped to
        # metrics; nothing about the meeting belongs in it.
        {"generation_id": str(stored_id), "note_id": str(note_id)},
        max_attempts=MAX_ATTEMPTS,
        priority=PRIORITY_REGENERATE
        if reason == "regenerate"
        else (priority if priority is not None else PRIORITY_AUTO),
        idempotency_key=(f"{note_id}:{transcript_rev}:{PROMPT_VERSION}:{secrets.token_hex(4)}"),
        conn=conn,
    )
    return stored_id, gen_repo.QUEUED


async def check_allowed(conn: asyncpg.Connection, *, tenant_id: UUID) -> None:
    """Raise when this workspace may not generate right now.

    Two reasons, both the workspace's own choice or its plan's: the admin
    turned generation off, or the month's budget is spent. Neither is a
    fault in the note — the note is fine, and the caller says which it is
    rather than leaving a spinner that never resolves.
    """
    row = await ai_settings.fetch(conn, tenant_id=tenant_id)
    if not row.generation_enabled:
        raise GenerationDisabledError

    record = await conn.fetchrow("SELECT plan_limits FROM tenants WHERE id = $1", tenant_id)
    limits = record["plan_limits"] if record is not None else None
    if isinstance(limits, str):
        limits = json.loads(limits)
    budget = ai_settings.budget_cents(row, limits or {})
    spent = await ai_settings.month_to_date_cents(conn, tenant_id=tenant_id)
    if spent >= budget:
        raise BudgetExceededError(spent, budget)
