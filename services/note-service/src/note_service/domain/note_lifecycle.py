"""Sprint-08 Day-2 — Note status state machine.

Allowed transitions:

    draft       → finalized      via POST /notes/{id}/finalize
    draft       → cancelled      via POST /notes/{id}/cancel
    finalized   → draft          via POST /notes/{id}/revert-to-draft
                                 (author + within 1h)
    finalized   → amended        via POST /notes/{id}/amend
    finalized   → cancelled      via POST /notes/{id}/cancel
    amended     → amended        further amendments append versions

Everything else raises :class:`IllegalTransitionError` → HTTP 422.

Each transition is materialised as a single-statement
``UPDATE notes SET status=... WHERE id=$1 AND status=<expected>``.
The status-match WHERE clause is the optimistic check: if 0 rows
match, another transition raced — return 409 with the current state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

import asyncpg

from note_models import NoteStatus

logger = logging.getLogger(__name__)


REVERT_WINDOW: Final = timedelta(hours=1)


class TransitionAction(StrEnum):
    FINALIZE = "finalize"
    REVERT_TO_DRAFT = "revert_to_draft"
    AMEND = "amend"
    CANCEL = "cancel"


# (from_status, action) -> to_status
_ALLOWED: Final[dict[tuple[NoteStatus, TransitionAction], NoteStatus]] = {
    (NoteStatus.DRAFT, TransitionAction.FINALIZE): NoteStatus.FINALIZED,
    (NoteStatus.DRAFT, TransitionAction.CANCEL): NoteStatus.CANCELLED,
    (NoteStatus.FINALIZED, TransitionAction.REVERT_TO_DRAFT): NoteStatus.DRAFT,
    (NoteStatus.FINALIZED, TransitionAction.AMEND): NoteStatus.AMENDED,
    (NoteStatus.FINALIZED, TransitionAction.CANCEL): NoteStatus.CANCELLED,
    (NoteStatus.AMENDED, TransitionAction.AMEND): NoteStatus.AMENDED,
}


class IllegalTransitionError(Exception):
    def __init__(self, from_status: NoteStatus, action: TransitionAction) -> None:
        self.from_status = from_status
        self.action = action
        super().__init__(f"action {action.value!r} not allowed from status {from_status.value!r}")


class ConcurrentTransitionError(Exception):
    """Another transaction transitioned the row before our UPDATE landed."""

    def __init__(self, observed_status: NoteStatus | None) -> None:
        self.observed_status = observed_status
        super().__init__(
            f"concurrent transition; note is now in status "
            f"{observed_status.value if observed_status else '<deleted>'}"
        )


class RevertWindowExceededError(Exception):
    pass


class NotPrimaryAuthorError(Exception):
    pass


class FinalizeValidationError(Exception):
    """Required sections missing / incomplete per template."""

    def __init__(self, problems: list[dict[str, str]]) -> None:
        self.problems = problems
        super().__init__(f"finalize validation failed: {len(problems)} problem(s)")


@dataclass(slots=True)
class TransitionResult:
    note_id: UUID
    from_status: NoteStatus
    to_status: NoteStatus
    action: TransitionAction


class NoteStateMachine:
    """Stateless verifier + applier of note status transitions.

    Single instance per service; methods take an asyncpg connection
    that has already been opened via ``tenant_connection``.
    """

    def expected_to(self, from_status: NoteStatus, action: TransitionAction) -> NoteStatus:
        try:
            return _ALLOWED[(from_status, action)]
        except KeyError as exc:
            raise IllegalTransitionError(from_status, action) from exc

    def allowed_actions(self, from_status: NoteStatus) -> list[TransitionAction]:
        return [act for (st, act) in _ALLOWED if st == from_status]

    # ── Atomic UPDATE helpers ───────────────────────────────────────

    async def _atomic_update_status(
        self,
        conn: asyncpg.Connection,
        *,
        note_id: UUID,
        expected_from: NoteStatus,
        to: NoteStatus,
        timestamp_col: str | None,
        extra_set: str = "",
        extra_args: tuple = (),
    ) -> None:
        sets = ["status = $2"]
        if timestamp_col is not None:
            sets.append(f"{timestamp_col} = now()")
        sets.append("updated_at = now()")
        if extra_set:
            sets.append(extra_set)
        args: list = [note_id, to.value, expected_from.value, *extra_args]
        sql = f"UPDATE notes SET {', '.join(sets)} WHERE id = $1 AND status = $3 RETURNING id"
        row = await conn.fetchrow(sql, *args)
        if row is None:
            current = await conn.fetchrow("SELECT status FROM notes WHERE id = $1", note_id)
            observed = NoteStatus(current["status"]) if current else None
            raise ConcurrentTransitionError(observed)

    # ── Public actions ──────────────────────────────────────────────

    async def finalize(
        self,
        conn: asyncpg.Connection,
        *,
        note_id: UUID,
    ) -> TransitionResult:
        to = self.expected_to(NoteStatus.DRAFT, TransitionAction.FINALIZE)
        await self._atomic_update_status(
            conn,
            note_id=note_id,
            expected_from=NoteStatus.DRAFT,
            to=to,
            timestamp_col="finalized_at",
        )
        return TransitionResult(note_id, NoteStatus.DRAFT, to, TransitionAction.FINALIZE)

    async def cancel(
        self,
        conn: asyncpg.Connection,
        *,
        note_id: UUID,
        from_status: NoteStatus,
        reason: str,
    ) -> TransitionResult:
        if from_status not in (NoteStatus.DRAFT, NoteStatus.FINALIZED):
            raise IllegalTransitionError(from_status, TransitionAction.CANCEL)
        to = NoteStatus.CANCELLED
        await self._atomic_update_status(
            conn,
            note_id=note_id,
            expected_from=from_status,
            to=to,
            timestamp_col="cancelled_at",
            extra_set="cancelled_reason = $4",
            extra_args=(reason,),
        )
        return TransitionResult(note_id, from_status, to, TransitionAction.CANCEL)

    async def revert_to_draft(
        self,
        conn: asyncpg.Connection,
        *,
        note_id: UUID,
        actor_user_id: UUID,
        now: datetime | None = None,
    ) -> TransitionResult:
        now = now or datetime.now(UTC)
        row = await conn.fetchrow(
            "SELECT status, primary_author_id, finalized_at FROM notes WHERE id = $1",
            note_id,
        )
        if row is None:
            raise ConcurrentTransitionError(None)
        current = NoteStatus(row["status"])
        if current != NoteStatus.FINALIZED:
            raise IllegalTransitionError(current, TransitionAction.REVERT_TO_DRAFT)
        if row["primary_author_id"] != actor_user_id:
            raise NotPrimaryAuthorError()
        finalized_at: datetime | None = row["finalized_at"]
        if finalized_at is None or (now - finalized_at) > REVERT_WINDOW:
            raise RevertWindowExceededError()

        to = NoteStatus.DRAFT
        await self._atomic_update_status(
            conn,
            note_id=note_id,
            expected_from=NoteStatus.FINALIZED,
            to=to,
            timestamp_col=None,
            extra_set="finalized_at = NULL",
        )
        return TransitionResult(note_id, NoteStatus.FINALIZED, to, TransitionAction.REVERT_TO_DRAFT)

    async def mark_amended(
        self,
        conn: asyncpg.Connection,
        *,
        note_id: UUID,
        from_status: NoteStatus,
    ) -> TransitionResult:
        """``finalized → amended`` (or amended → amended for further
        amendments). Driven by the amend route after the amendment
        version row is appended."""
        to = self.expected_to(from_status, TransitionAction.AMEND)
        await self._atomic_update_status(
            conn,
            note_id=note_id,
            expected_from=from_status,
            to=to,
            timestamp_col=None,
        )
        return TransitionResult(note_id, from_status, to, TransitionAction.AMEND)
