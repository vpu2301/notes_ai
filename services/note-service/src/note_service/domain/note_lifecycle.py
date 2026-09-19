"""Note status state machine — one transition left.

    draft → cancelled   via POST /notes/{id}/cancel

The finalize / revert / amend lifecycle was retired (migration 0042).
Rows that still carry the old statuses in the database were moved back
to ``draft`` by that migration; the enum keeps the values so nothing
that reads history has to change.

The transition is one ``UPDATE notes SET status=... WHERE id=$1 AND
status=<expected>``: the WHERE clause is the optimistic check, and a
0-row result means another transition raced — 409 with the observed
state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

import asyncpg

from note_models import NoteStatus

logger = logging.getLogger(__name__)


class TransitionAction(StrEnum):
    CANCEL = "cancel"


_ALLOWED: Final[dict[tuple[NoteStatus, TransitionAction], NoteStatus]] = {
    (NoteStatus.DRAFT, TransitionAction.CANCEL): NoteStatus.CANCELLED,
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


@dataclass(slots=True)
class TransitionResult:
    note_id: UUID
    from_status: NoteStatus
    to_status: NoteStatus
    action: TransitionAction


class NoteStateMachine:
    """Stateless verifier + applier of note status transitions."""

    def expected_to(self, from_status: NoteStatus, action: TransitionAction) -> NoteStatus:
        try:
            return _ALLOWED[(from_status, action)]
        except KeyError as exc:
            raise IllegalTransitionError(from_status, action) from exc

    def allowed_actions(self, from_status: NoteStatus) -> list[TransitionAction]:
        return [act for (st, act) in _ALLOWED if st == from_status]

    async def cancel(
        self,
        conn: asyncpg.Connection,
        *,
        note_id: UUID,
        from_status: NoteStatus,
        reason: str,
    ) -> TransitionResult:
        to = self.expected_to(from_status, TransitionAction.CANCEL)
        row = await conn.fetchrow(
            """
            UPDATE notes
            SET status = $2, cancelled_at = now(), updated_at = now(), cancelled_reason = $4
            WHERE id = $1 AND status = $3
            RETURNING id
            """,
            note_id,
            to.value,
            from_status.value,
            reason,
        )
        if row is None:
            current = await conn.fetchrow("SELECT status FROM notes WHERE id = $1", note_id)
            observed = NoteStatus(current["status"]) if current else None
            raise ConcurrentTransitionError(observed)
        return TransitionResult(note_id, from_status, to, TransitionAction.CANCEL)
