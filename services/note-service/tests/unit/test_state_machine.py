"""Unit tests for NoteStateMachine.

These tests use a stub asyncpg.Connection so we can drive the SQL paths
without a live DB. Cancel is the one transition left (0042): the happy
path, the illegal sources and the concurrent race are exercised here.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from note_models import NoteStatus
from note_service.domain.note_lifecycle import (
    ConcurrentTransitionError,
    IllegalTransitionError,
    NoteStateMachine,
    TransitionAction,
)

# Async tests get the marker explicitly so the module works under
# pytest-asyncio modes other than auto. Sync tests at the bottom are
# left unmarked.
_aio = pytest.mark.asyncio


class StubConn:
    """Minimal asyncpg-shaped stub used in pure unit tests.

    Driven entirely by the prepared responses queued on the instance.
    """

    def __init__(self) -> None:
        self._fetchrow_queue: list = []
        self.executed: list[tuple[str, tuple]] = []

    def push_fetchrow(self, *rows) -> None:
        self._fetchrow_queue.extend(rows)

    async def fetchrow(self, sql, *args):
        self.executed.append((sql, args))
        if not self._fetchrow_queue:
            return None
        return self._fetchrow_queue.pop(0)

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return "OK"


def _row(**kw):
    """asyncpg.Record-like dict that supports row['key'] indexing."""
    return kw


# ── Cancel ──────────────────────────────────────────────────────────


@_aio
async def test_cancel_from_draft_allowed():
    sm = NoteStateMachine()
    conn = StubConn()
    conn.push_fetchrow(_row(id=uuid4()))
    result = await sm.cancel(conn, note_id=uuid4(), from_status=NoteStatus.DRAFT, reason="dup")
    assert result.to_status == NoteStatus.CANCELLED
    sql, args = conn.executed[0]
    assert "cancelled_reason" in sql
    assert args[3] == "dup"


@_aio
@pytest.mark.parametrize("status", [NoteStatus.CANCELLED, NoteStatus.FINALIZED, NoteStatus.AMENDED])
async def test_cancel_from_anything_but_draft_disallowed(status):
    sm = NoteStateMachine()
    conn = StubConn()
    with pytest.raises(IllegalTransitionError):
        await sm.cancel(conn, note_id=uuid4(), from_status=status, reason="x")
    assert conn.executed == []


@_aio
async def test_cancel_concurrent_returns_observed_state():
    sm = NoteStateMachine()
    conn = StubConn()
    # UPDATE matched nothing; the re-read says it is already cancelled.
    conn.push_fetchrow(None, _row(status="cancelled"))
    with pytest.raises(ConcurrentTransitionError) as ei:
        await sm.cancel(conn, note_id=uuid4(), from_status=NoteStatus.DRAFT, reason="x")
    assert ei.value.observed_status == NoteStatus.CANCELLED


@_aio
async def test_cancel_concurrent_deleted_row():
    sm = NoteStateMachine()
    conn = StubConn()
    conn.push_fetchrow(None, None)
    with pytest.raises(ConcurrentTransitionError) as ei:
        await sm.cancel(conn, note_id=uuid4(), from_status=NoteStatus.DRAFT, reason="x")
    assert ei.value.observed_status is None


# ── Table ───────────────────────────────────────────────────────────


def test_allowed_actions_match_spec_table():
    sm = NoteStateMachine()
    assert sm.allowed_actions(NoteStatus.DRAFT) == [TransitionAction.CANCEL]
    for status in (NoteStatus.FINALIZED, NoteStatus.AMENDED, NoteStatus.CANCELLED):
        assert sm.allowed_actions(status) == []


def test_expected_to_lookup_raises_on_disallowed():
    sm = NoteStateMachine()
    assert sm.expected_to(NoteStatus.DRAFT, TransitionAction.CANCEL) == NoteStatus.CANCELLED
    with pytest.raises(IllegalTransitionError):
        sm.expected_to(NoteStatus.CANCELLED, TransitionAction.CANCEL)
