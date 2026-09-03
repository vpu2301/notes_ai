"""Merging upcoming events across connections, and token refresh (0019)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from crypto import EnvelopeBlob
from note_service.domain import calendar_repository as repo
from note_service.domain import calendar_sync
from note_service.domain.calendar_sync import UpcomingEvent, merge_events
from note_service.domain.google_calendar import (
    CalendarEvent,
    CalendarInfo,
    GoogleCalendarClient,
    NeedsReauthError,
)

TENANT = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _event(
    id: str,
    start: datetime,
    *,
    end: datetime | None = None,
    ical: str | None = None,
    title: str = "t",
) -> CalendarEvent:
    return CalendarEvent(
        id=id,
        ical_uid=ical or id,
        calendar_id="c",
        calendar_name="C",
        color=None,
        title=title,
        start=start,
        end=end or start + timedelta(hours=1),
        all_day=False,
        location=None,
        meeting_url=None,
        html_link=None,
        attendee_count=0,
        organizer=None,
        response_status=None,
    )


def _tag(connection_id: UUID, *events: CalendarEvent) -> list[UpcomingEvent]:
    return [
        UpcomingEvent(connection_id=connection_id, account_email="a@x", event=e) for e in events
    ]


def test_merge_drops_ended_dedupes_and_sorts() -> None:
    c1, c2 = uuid4(), uuid4()
    later = _event("late", NOW + timedelta(hours=3))
    soon = _event("soon", NOW + timedelta(minutes=10))
    ended = _event("old", NOW - timedelta(hours=2), end=NOW - timedelta(hours=1))
    in_progress = _event("now", NOW - timedelta(minutes=20))  # ends in 40 min → keep
    copy = _event(
        "copy", NOW + timedelta(minutes=10), ical="soon"
    )  # the same invite, other calendar
    merged = merge_events([_tag(c1, later, ended, soon), _tag(c2, copy, in_progress)], now=NOW)
    assert [i.event.id for i in merged] == ["now", "soon", "late"]
    assert merged[1].connection_id == c1  # first copy wins


def test_merge_caps() -> None:
    items = _tag(uuid4(), *[_event(str(i), NOW + timedelta(minutes=i)) for i in range(100)])
    assert len(merge_events([items], now=NOW, limit=5)) == 5


def test_visible_calendars_filters_hidden() -> None:
    cals = [
        CalendarInfo(id="a", name="A", color=None, primary=True, selected=True),
        CalendarInfo(id="b", name="B", color=None, primary=False, selected=True),
    ]
    assert [c.id for c in calendar_sync.visible_calendars(cals, hidden=("b",))] == ["a"]
    assert [c.id for c in calendar_sync.visible_calendars(cals, hidden=())] == ["a", "b"]


# ── usable_access_token: a fake envelope that "encrypts" by tagging ──


class _FakeEnvelope:
    async def encrypt(
        self, plaintext: bytes, *, tenant_id: UUID, aad: bytes | None = None
    ) -> EnvelopeBlob:
        return EnvelopeBlob(
            ciphertext=plaintext[::-1],
            iv=b"i" * 12,
            tag=b"t" * 16,
            wrapped_dek=b"w" * 32,
            dek_iv=b"d" * 12,
            dek_tag=b"g" * 16,
            tenant_id=tenant_id,
            master_key_id="fake",
            extra_aad=aad,
        )

    async def decrypt(
        self, blob: EnvelopeBlob, *, tenant_id: UUID, aad: bytes | None = None
    ) -> bytes:
        assert blob.tenant_id == tenant_id
        return blob.ciphertext[::-1]


def _row(blob: bytes, *, expires_at: datetime | None) -> repo.ConnectionRow:
    return repo.ConnectionRow(
        id=uuid4(),
        tenant_id=TENANT,
        user_sub=uuid4(),
        provider="google",
        account_email="a@x",
        token_blob=blob,
        token_expires_at=expires_at,
        scopes=(),
        hidden_calendar_ids=(),
        created_at=NOW,
        updated_at=NOW,
        revoked_at=None,
        needs_reauth=False,
        last_synced_at=None,
        last_error=None,
    )


async def test_token_blob_round_trip() -> None:
    env = _FakeEnvelope()
    blob = await repo.seal_tokens(env, tenant_id=TENANT, tokens=repo.StoredTokens("at", "rt"))  # type: ignore[arg-type]
    assert b"at" not in blob  # not stored in the clear
    back = await repo.open_tokens(env, tenant_id=TENANT, token_blob=blob)  # type: ignore[arg-type]
    assert back == repo.StoredTokens("at", "rt")


async def test_fresh_token_is_returned_without_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _FakeEnvelope()
    blob = await repo.seal_tokens(env, tenant_id=TENANT, tokens=repo.StoredTokens("at", "rt"))  # type: ignore[arg-type]
    row = _row(blob, expires_at=datetime.now(UTC) + timedelta(minutes=30))
    google = GoogleCalendarClient(
        client_id="c",
        client_secret="s",
        redirect_uri="r",
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
    )
    stored: list[dict] = []

    async def _store(conn, **kwargs):  # noqa: ANN001, ANN003
        stored.append(kwargs)

    monkeypatch.setattr(repo, "store_tokens", _store)
    token = await calendar_sync.usable_access_token(None, envelope=env, google=google, row=row)  # type: ignore[arg-type]
    assert token == "at"
    assert stored == []


async def test_expiring_token_is_refreshed_and_resealed(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _FakeEnvelope()
    blob = await repo.seal_tokens(env, tenant_id=TENANT, tokens=repo.StoredTokens("old", "rt"))  # type: ignore[arg-type]
    row = _row(blob, expires_at=datetime.now(UTC) + timedelta(seconds=30))
    google = GoogleCalendarClient(
        client_id="c",
        client_secret="s",
        redirect_uri="r",
        http=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, json={"access_token": "new", "expires_in": 3600})
            )
        ),
    )
    stored: list[dict] = []

    async def _store(conn, **kwargs):  # noqa: ANN001, ANN003
        stored.append(kwargs)

    monkeypatch.setattr(repo, "store_tokens", _store)
    token = await calendar_sync.usable_access_token(None, envelope=env, google=google, row=row)  # type: ignore[arg-type]
    assert token == "new"
    assert len(stored) == 1
    resealed = await repo.open_tokens(env, tenant_id=TENANT, token_blob=stored[0]["token_blob"])  # type: ignore[arg-type]
    assert resealed == repo.StoredTokens("new", "rt")  # refresh token carried over


async def test_missing_refresh_token_needs_reauth() -> None:
    env = _FakeEnvelope()
    blob = await repo.seal_tokens(env, tenant_id=TENANT, tokens=repo.StoredTokens("old", None))  # type: ignore[arg-type]
    row = _row(blob, expires_at=None)
    google = SimpleNamespace()
    with pytest.raises(NeedsReauthError):
        await calendar_sync.usable_access_token(None, envelope=env, google=google, row=row)  # type: ignore[arg-type]


async def test_upcoming_isolates_a_failing_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _FakeEnvelope()
    good_blob = await repo.seal_tokens(
        env, tenant_id=TENANT, tokens=repo.StoredTokens("good", "rt")
    )  # type: ignore[arg-type]
    dead_blob = await repo.seal_tokens(
        env, tenant_id=TENANT, tokens=repo.StoredTokens("dead", "rt")
    )  # type: ignore[arg-type]
    good = _row(good_blob, expires_at=datetime.now(UTC) + timedelta(hours=1))
    dead = _row(dead_blob, expires_at=None)  # forces a refresh → invalid_grant

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(400, json={"error": "invalid_grant"})
        if request.url.path.endswith("/calendarList"):
            return httpx.Response(
                200, json={"items": [{"id": "p", "summary": "P", "primary": True}]}
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "e",
                        "summary": "Standup",
                        "start": {"dateTime": (NOW + timedelta(hours=1)).isoformat()},
                    }
                ]
            },
        )

    google = GoogleCalendarClient(
        client_id="c",
        client_secret="s",
        redirect_uri="r",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    failed: list[dict] = []
    synced: list[UUID] = []

    async def _list_live(conn, *, user_sub):  # noqa: ANN001
        return [good, dead]

    async def _mark_failed(conn, **kwargs):  # noqa: ANN001, ANN003
        failed.append(kwargs)

    async def _mark_synced(conn, *, connection_id):  # noqa: ANN001
        synced.append(connection_id)

    monkeypatch.setattr(repo, "list_live", _list_live)
    monkeypatch.setattr(repo, "mark_failed", _mark_failed)
    monkeypatch.setattr(repo, "mark_synced", _mark_synced)

    result = await calendar_sync.upcoming(
        None,
        envelope=env,
        google=google,
        user_sub=uuid4(),
        days=7,
        now=NOW,  # type: ignore[arg-type]
    )
    assert [i.event.title for i in result.events] == ["Standup"]
    assert result.events[0].connection_id == good.id
    assert synced == [good.id]
    assert len(result.problems) == 1
    assert result.problems[0].connection_id == dead.id
    assert result.problems[0].needs_reauth
    assert failed[0]["needs_reauth"] is True
