"""IDX-A3 — the database-free core of email-code sign-in."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from auth_service.domain import email_code as ec
from auth_service.domain.transport import AuthResult, ClientType, IdentitySummary, MembershipSummary

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
CID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


def _challenge(
    code: str = "482913",
    *,
    attempts: int = 0,
    max_attempts: int = 5,
    expired: bool = False,
    consumed: bool = False,
) -> ec.Challenge:
    return ec.Challenge(
        id=CID,
        kind=ec.KIND_EMAIL_LOGIN,
        email="ada@example.test",
        identity_id=None,
        code_hash=ec.code_hash(code, CID),
        expires_at=NOW - timedelta(seconds=1) if expired else NOW + timedelta(minutes=10),
        attempts=attempts,
        max_attempts=max_attempts,
        consumed_at=NOW - timedelta(minutes=1) if consumed else None,
        created_at=NOW - timedelta(minutes=1),
    )


# ── codes and hashes ─────────────────────────────────────────────────────


def test_generate_code_is_six_digits_with_leading_zeros() -> None:
    codes = {ec.generate_code() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert len(codes) > 150  # not a constant


def test_hash_is_bound_to_the_challenge_id() -> None:
    other = uuid4()
    assert ec.code_hash("482913", CID) != ec.code_hash("482913", other)
    assert ec.code_hash("482913", CID) == ec.code_hash("482913", CID)


def test_normalise_code_accepts_the_grouped_form() -> None:
    assert ec.normalise_code(" 482 913 ") == "482913"
    assert ec.normalise_code("48-29-13") == "482913"


def test_email_subject_hash_is_not_the_address() -> None:
    h = ec.email_subject_hash("  Ada@Example.TEST ")
    assert h == ec.email_subject_hash("ada@example.test")
    assert "ada" not in h and len(h) == 32


# ── verify state machine ─────────────────────────────────────────────────


def test_correct_code_is_ok_and_consumes() -> None:
    d = ec.evaluate(_challenge(), "482 913", now=NOW)
    assert d.outcome is ec.VerifyOutcome.OK and d.consume


def test_wrong_code_counts_and_reports_attempts_left() -> None:
    d = ec.evaluate(_challenge(attempts=0), "000000", now=NOW)
    assert d == ec.VerifyDecision(ec.VerifyOutcome.INVALID, 1, 4, consume=False)


def test_fifth_wrong_code_exhausts_and_consumes() -> None:
    d = ec.evaluate(_challenge(attempts=4), "000000", now=NOW)
    assert d.outcome is ec.VerifyOutcome.EXHAUSTED and d.consume and d.attempts_after == 5


def test_sixth_attempt_is_impossible_even_with_the_right_code() -> None:
    d = ec.evaluate(_challenge(attempts=5), "482913", now=NOW)
    assert d.outcome is ec.VerifyOutcome.EXHAUSTED and d.consume


def test_expired_challenge_learns_nothing_about_the_code() -> None:
    assert (
        ec.evaluate(_challenge(expired=True), "482913", now=NOW).outcome is ec.VerifyOutcome.EXPIRED
    )
    assert (
        ec.evaluate(_challenge(expired=True), "000000", now=NOW).outcome is ec.VerifyOutcome.EXPIRED
    )


def test_consumed_challenge_is_consumed_regardless_of_code() -> None:
    d = ec.evaluate(_challenge(consumed=True), "482913", now=NOW)
    assert d.outcome is ec.VerifyOutcome.CONSUMED and not d.consume


def test_resend_cooldown_from_created_at() -> None:
    c = _challenge()
    assert ec.resend_allowed_at(c.created_at, cooldown_seconds=60) == c.created_at + timedelta(
        seconds=60
    )


# ── lockout ──────────────────────────────────────────────────────────────


def test_lock_duration_doubles_and_caps() -> None:
    p = ec.LockoutPolicy()
    assert [p.lock_duration(n).total_seconds() for n in range(4)] == [900, 1800, 3600, 3600]


def test_tenth_failure_locks_and_resets_the_counter() -> None:
    p = ec.LockoutPolicy()
    assert p.after_failure(failed_count=8, previous_locks=0, now=NOW) == (9, None)
    count, until = p.after_failure(failed_count=9, previous_locks=0, now=NOW)
    assert count == 0 and until == NOW + timedelta(minutes=15)
    assert ec.is_locked(until, now=NOW) and not ec.is_locked(until, now=NOW + timedelta(minutes=16))
    assert not ec.is_locked(None, now=NOW)


# ── personal workspace ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("email", "name", "display"),
    [
        ("Ada.L@Example.test", "ada.l", "ada.l's workspace"),
        ("o'neil+notes@x.io", "o-neil-notes", "o'neil+notes's workspace"),
        ("@weird", "me", "me's workspace"),
    ],
)
def test_personal_workspace_names(email: str, name: str, display: str) -> None:
    w = ec.personal_workspace_names(email, slug_hex="deadbeefcafe")
    assert (w.name, w.display_name, w.slug) == (name, display, "ws-deadbeef")


# ── AuthResult ───────────────────────────────────────────────────────────


def test_auth_result_is_a_superset_of_the_token_response() -> None:
    r = AuthResult.authenticated(
        client_type=ClientType.WEB,
        access_token="at",
        expires_in=900,
        tenant_id="t1",
        roles=["member"],
        refresh_token="rt",
        refresh_expires_in=7776000,
        identity=IdentitySummary(
            id="i",
            email="a@b.test",
            display_name="",
            mfa_enabled=False,
            has_password=False,
            status="active",
        ),
        memberships=[
            MembershipSummary(
                tenant_id="t1", name="ada", kind="personal", role="owner", status="active"
            )
        ],
        is_new_identity=True,
    )
    body = r.model_dump(exclude_none=True)
    assert body["status"] == "authenticated" and body["is_new_identity"] is True
    assert body["default_tenant_id"] == "t1"
    assert {"access_token", "expires_in", "token_type"} <= set(body)
    assert "refresh_token" not in body  # web: cookie carries it
    native = r.model_copy(update={"refresh_token": "rt"})
    assert native.refresh_token == "rt"
