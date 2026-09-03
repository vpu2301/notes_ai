"""Signed OAuth state for the calendar connect flow (0019)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from note_service.domain.calendar_state import (
    STATE_TTL_SECONDS,
    InvalidStateError,
    issue_state,
    verify_state,
)

KEY = "00" * 32
OTHER_KEY = "11" * 32


def test_round_trip() -> None:
    tenant, user = uuid4(), uuid4()
    token = issue_state(
        tenant_id=tenant, user_sub=user, return_to="http://localhost:5173/", key_hex=KEY, now=1_000
    )
    parsed = verify_state(token, key_hex=KEY, now=1_100)
    assert parsed.tenant_id == tenant
    assert parsed.user_sub == user
    assert parsed.return_to == "http://localhost:5173/"
    assert parsed.provider == "google"
    assert parsed.issued_at == 1_000


def test_two_issues_differ() -> None:
    args: dict = {
        "tenant_id": uuid4(),
        "user_sub": uuid4(),
        "return_to": "notesai://x",
        "key_hex": KEY,
        "now": 5,
    }
    assert issue_state(**args) != issue_state(**args)  # nonce


@pytest.mark.parametrize("bad", [None, "", "nodot", "a.b", "x" * 3000])
def test_malformed_rejected(bad: str | None) -> None:
    with pytest.raises(InvalidStateError):
        verify_state(bad, key_hex=KEY)


def test_tampered_payload_rejected() -> None:
    token = issue_state(tenant_id=uuid4(), user_sub=uuid4(), return_to="http://a/", key_hex=KEY)
    body, sig = token.split(".")
    flipped = ("A" if body[0] != "A" else "B") + body[1:]
    with pytest.raises(InvalidStateError):
        verify_state(f"{flipped}.{sig}", key_hex=KEY)


def test_wrong_key_rejected() -> None:
    token = issue_state(tenant_id=uuid4(), user_sub=uuid4(), return_to="http://a/", key_hex=KEY)
    with pytest.raises(InvalidStateError):
        verify_state(token, key_hex=OTHER_KEY)


def test_expired_rejected() -> None:
    token = issue_state(
        tenant_id=uuid4(), user_sub=uuid4(), return_to="http://a/", key_hex=KEY, now=1_000
    )
    verify_state(token, key_hex=KEY, now=1_000 + STATE_TTL_SECONDS - 1)
    with pytest.raises(InvalidStateError):
        verify_state(token, key_hex=KEY, now=1_000 + STATE_TTL_SECONDS + 1)


def test_future_dated_rejected() -> None:
    token = issue_state(
        tenant_id=uuid4(), user_sub=uuid4(), return_to="http://a/", key_hex=KEY, now=10_000
    )
    with pytest.raises(InvalidStateError):
        verify_state(token, key_hex=KEY, now=1_000)
