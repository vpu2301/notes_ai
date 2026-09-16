"""IDX-A3 — the email one-time-code HTTP surface.

Written around the properties the pack's acceptance criteria name, not
around the happy path:

  * ``/start`` is an enumeration dead end — a known address and an
    unknown one produce the same status, the same body shape, and
    exactly one mail each.
  * The sixth wrong code is impossible: the fifth consumes the challenge.
  * A brand-new address ends up with an identity, a personal workspace,
    an owner membership, and a token scoped to that workspace.
  * With the rate limiter down, ``/start`` refuses and mails nothing,
    while ``/verify`` keeps working.
  * No log record contains an address or a code.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from auth_service.domain import email_code as ec
from auth_service.domain.email_code_service import (
    CodeMailer,
    EmailCodeConfig,
    EmailCodeService,
)
from auth_service.domain.identity_repository import Identity, Membership
from auth_service.domain.session_service import SessionService
from auth_service.domain.signing_keys import KeySet
from auth_service.domain.token_service import TokenService
from ratelimit import FixedWindowLimiter

KNOWN = "olena@acme.example"
UNKNOWN = "nobody@acme.example"
ORIGIN = {"Origin": "http://localhost:5173"}
DEV_KEYS = Path(__file__).resolve().parents[4] / "infra" / "dev" / "auth-signing-dev.json"


# ── fakes ────────────────────────────────────────────────────────────────


class FakeRedis:
    """Enough of the async Redis surface for ``FixedWindowLimiter``."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.down = False

    async def incrby(self, key: str, amount: int) -> int:
        if self.down:
            raise ConnectionError("redis is down")
        self.counts[key] = self.counts.get(key, 0) + amount
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        if self.down:
            raise ConnectionError("redis is down")
        return True


class FakeChallenges:
    """In-memory ``auth_challenges``."""

    def __init__(self) -> None:
        self.rows: dict[UUID, ec.Challenge] = {}

    async def open(
        self,
        *,
        challenge_id: UUID,
        kind: str,
        email: str,
        identity_id: UUID | None,
        code_hash: str,
        expires_at: datetime,
        max_attempts: int,
        client_type: str,
        ip: str,
    ) -> ec.Challenge:
        row = ec.Challenge(
            id=challenge_id,
            kind=kind,
            email=email,
            identity_id=identity_id,
            code_hash=code_hash,
            expires_at=expires_at,
            attempts=0,
            max_attempts=max_attempts,
            consumed_at=None,
            created_at=datetime.now(UTC),
        )
        self.rows[challenge_id] = row
        return row

    async def consume_open_for_email(self, *, kind: str, email: str) -> int:
        n = 0
        for cid, row in list(self.rows.items()):
            if row.kind == kind and row.email == email and row.consumed_at is None:
                self.rows[cid] = replace(row, consumed_at=datetime.now(UTC))
                n += 1
        return n

    async def latest_open_for_email(self, *, kind: str, email: str) -> ec.Challenge | None:
        open_rows = [
            r
            for r in self.rows.values()
            if r.kind == kind and r.email == email and r.consumed_at is None
        ]
        return max(open_rows, key=lambda r: r.created_at) if open_rows else None

    async def get(self, challenge_id: UUID) -> ec.Challenge | None:
        return self.rows.get(challenge_id)

    async def record_attempt(self, challenge_id: UUID, *, attempts: int) -> None:
        self.rows[challenge_id] = replace(self.rows[challenge_id], attempts=attempts)

    async def consume(self, challenge_id: UUID) -> bool:
        row = self.rows.get(challenge_id)
        if row is None or row.consumed_at is not None:
            return False
        self.rows[challenge_id] = replace(row, consumed_at=datetime.now(UTC))
        return True

    async def delete(self, challenge_id: UUID) -> None:
        self.rows.pop(challenge_id, None)


@dataclass
class FakeTenant:
    id: UUID
    name: str
    display_name: str
    slug: str
    kind: str


class FakeIdentities:
    """In-memory ``identities`` + the signup transaction's side effects."""

    def __init__(self) -> None:
        self.rows: dict[UUID, Identity] = {}
        self.tenants: list[FakeTenant] = []
        self.memberships: dict[UUID, list[Membership]] = {}
        self.users: list[tuple[UUID, UUID]] = []
        self.lock_notices: list[UUID] = []
        self.signup_locales: list[str] = []

    # -- helpers used by tests, not part of the repository interface --

    def seed(self, email: str, **kwargs: Any) -> Identity:
        identity = Identity(
            id=kwargs.pop("id", uuid4()),
            email=email,
            email_verified_at=datetime.now(UTC),
            display_name=kwargs.pop("display_name", ""),
            status=kwargs.pop("status", "active"),
            mfa_enabled=kwargs.pop("mfa_enabled", False),
            legacy_idp=kwargs.pop("legacy_idp", False),
            has_password=False,
            last_tenant_id=kwargs.pop("last_tenant_id", None),
            failed_login_count=kwargs.pop("failed_login_count", 0),
            lock_count=kwargs.pop("lock_count", 0),
            locked_until=kwargs.pop("locked_until", None),
            lock_notified_at=kwargs.pop("lock_notified_at", None),
            deletion_requested_at=kwargs.pop("deletion_requested_at", None),
        )
        self.rows[identity.id] = identity
        return identity

    def add_membership(self, identity_id: UUID, membership: Membership) -> None:
        self.memberships.setdefault(identity_id, []).append(membership)

    # -- the interface EmailCodeService uses --

    async def get_by_email(self, email: str) -> Identity | None:
        for row in self.rows.values():
            if row.email == ec.normalise_email(email):
                return row
        return None

    async def get(self, identity_id: UUID) -> Identity | None:
        return self.rows.get(identity_id)

    async def list_memberships(self, identity_id: UUID) -> list[Membership]:
        return list(self.memberships.get(identity_id, []))

    async def create_with_personal_workspace(
        self,
        email: str,
        *,
        locale: str = "en",
        slug_hex: str | None = None,
        attempts: int = 3,
    ) -> tuple[Identity, Membership]:
        self.signup_locales.append(locale)
        names = ec.personal_workspace_names(email, slug_hex=slug_hex)
        if any(t.name == names.name for t in self.tenants):
            raise AssertionError("the repository retries name collisions; test wants a fresh name")
        tenant = FakeTenant(
            id=uuid4(),
            name=names.name,
            display_name=names.display_name,
            slug=names.slug,
            kind="personal",
        )
        self.tenants.append(tenant)
        identity = self.seed(ec.normalise_email(email), last_tenant_id=tenant.id)
        membership = Membership(
            tenant_id=tenant.id, name=tenant.name, kind="personal", role="owner", status="active"
        )
        self.add_membership(identity.id, membership)
        self.users.append((identity.id, tenant.id))
        return identity, membership

    async def ensure_personal_workspace(
        self,
        identity_id: UUID,
        email: str,
        *,
        locale: str = "en",
        slug_hex: str | None = None,
        attempts: int = 3,
    ) -> Membership | None:
        """BE-2 F3: heal an identity that has no active membership."""
        if self.memberships.get(identity_id):
            return None
        names = ec.personal_workspace_names(email, slug_hex=slug_hex)
        tenant = FakeTenant(
            id=uuid4(),
            name=names.name,
            display_name=names.display_name,
            slug=names.slug,
            kind="personal",
        )
        self.tenants.append(tenant)
        membership = Membership(
            tenant_id=tenant.id, name=tenant.name, kind="personal", role="owner", status="active"
        )
        self.add_membership(identity_id, membership)
        self.users.append((identity_id, tenant.id))
        return membership

    async def reactivate(self, identity_id: UUID) -> None:
        row = self.rows[identity_id]
        self.rows[identity_id] = replace(row, status="active", deletion_requested_at=None)

    async def note_successful_login(self, identity_id: UUID, *, tenant_id: UUID) -> None:
        row = self.rows[identity_id]
        self.rows[identity_id] = replace(
            row,
            failed_login_count=0,
            locked_until=None,
            lock_notified_at=None,
            last_tenant_id=tenant_id,
        )

    async def register_failure(
        self, identity_id: UUID, *, policy: ec.LockoutPolicy, now: datetime | None = None
    ) -> Any:
        now = now or datetime.now(UTC)
        row = self.rows[identity_id]
        if ec.is_locked(row.locked_until, now=now):
            return SimpleNamespace(
                locked_until=row.locked_until,
                newly_locked=False,
                failed_login_count=row.failed_login_count,
            )
        count, locked_until = policy.after_failure(
            failed_count=row.failed_login_count, previous_locks=row.lock_count, now=now
        )
        self.rows[identity_id] = replace(
            row,
            failed_login_count=count,
            locked_until=locked_until,
            lock_count=row.lock_count + (1 if locked_until else 0),
            lock_notified_at=None if locked_until else row.lock_notified_at,
        )
        return SimpleNamespace(
            locked_until=locked_until,
            newly_locked=locked_until is not None,
            failed_login_count=count,
        )

    async def claim_lock_notice(self, identity_id: UUID) -> bool:
        row = self.rows[identity_id]
        if not ec.is_locked(row.locked_until) or row.lock_notified_at is not None:
            return False
        self.rows[identity_id] = replace(row, lock_notified_at=datetime.now(UTC))
        self.lock_notices.append(identity_id)
        return True


class FakeSessionRepo:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> tuple[UUID, datetime]:
        self.created.append(kwargs)
        return uuid4(), datetime.now(UTC) + timedelta(seconds=kwargs["ttl_seconds"])


class CapturingProvider:
    """An ``EmailProvider`` that records what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[Any] = []
        self.fail = False

    async def send(self, message: Any) -> Any:
        if self.fail:
            raise RuntimeError("relay refused")
        self.sent.append(message)
        return SimpleNamespace(provider_message_id="m-1")

    async def aclose(self) -> None:
        return None


# ── harness ──────────────────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from auth_service import deps
    from auth_service.config import settings
    from auth_service.main import create_app

    # The A3 routes exist only in native mode, and so does the origin
    # check the requests below must satisfy.
    monkeypatch.setattr(settings, "idp_mode", "native")

    identities = FakeIdentities()
    challenges = FakeChallenges()
    sessions_repo = FakeSessionRepo()
    provider = CapturingProvider()
    redis = FakeRedis()
    audit_calls: list[dict[str, Any]] = []
    locks_audited: list[UUID] = []

    async def _write_event(**kwargs: Any) -> None:
        audit_calls.append(kwargs)

    async def _on_locked(*, identity_id: UUID, locked_until: datetime) -> None:
        locks_audited.append(identity_id)

    keys = KeySet.from_json(DEV_KEYS.read_text())
    token_service = TokenService(
        keys=keys,
        issuer="http://localhost:8000",
        audience="mdx-api",
        access_ttl_seconds=900,
    )
    service = EmailCodeService(
        identities=identities,  # type: ignore[arg-type]
        challenges=challenges,
        sessions=SessionService(
            tokens=token_service,
            sessions=sessions_repo,  # type: ignore[arg-type]
            refresh_ttl_seconds=2592000,
        ),
        mailer=CodeMailer(provider, reply_to="sales@notes-ai.local", timeout_seconds=5.0),
        limiter=FixedWindowLimiter(redis, prefix="mdx:auth:rl"),
        config=EmailCodeConfig(),
        on_account_locked=_on_locked,
    )

    state = SimpleNamespace(
        jwks_cache=object(),
        audit_writer=SimpleNamespace(write_event=_write_event),
        email_code_service=service,
    )
    deps.install_state(state)  # type: ignore[arg-type]

    return SimpleNamespace(
        client=TestClient(create_app()),
        identities=identities,
        challenges=challenges,
        sessions=sessions_repo,
        provider=provider,
        redis=redis,
        audit=audit_calls,
        locks_audited=locks_audited,
        service=service,
        settings=settings,
    )


def _code_of(env: Any, challenge_id: str) -> str:
    """Recover the plaintext code by brute-forcing the stored hash.

    Six digits is 10^6 candidates, which is exactly why the production
    path needs a five-attempt budget — here it is the cheapest way to
    read the code without a mailbox. In practice the mail is captured, so
    parse that instead when it is available.
    """
    row = env.challenges.rows[UUID(challenge_id)]
    for message in env.provider.sent:
        digits = "".join(ch for ch in message.text_body if ch.isdigit())
        for start in range(len(digits) - 5):
            candidate = digits[start : start + 6]
            if ec.hashes_match(row.code_hash, ec.code_hash(candidate, row.id)):
                return candidate
    raise AssertionError("no captured mail carried a code for this challenge")


def _start(env: Any, email: str, **kwargs: Any):
    return env.client.post("/auth/email/start", json={"email": email}, headers=ORIGIN, **kwargs)


def _verify(env: Any, challenge_id: str, code: str, headers: dict[str, str] | None = None):
    return env.client.post(
        "/auth/email/verify",
        json={"challenge_id": challenge_id, "code": code},
        headers={**ORIGIN, **(headers or {})},
    )


def _skip_cooldown(env: Any) -> None:
    """Step past the sixty-second resend window — both halves of it.

    The cooldown is enforced twice on purpose: a Redis counter (fast, and
    fails open) and the newest open challenge's ``created_at`` (slow, and
    authoritative). A test that only moved one of them would be measuring
    the other.
    """
    for row in list(env.challenges.rows.values()):
        env.challenges.rows[row.id] = replace(row, created_at=row.created_at - timedelta(minutes=5))
    for key in [k for k in env.redis.counts if ":otp_cooldown:" in k]:
        del env.redis.counts[key]


def _skip_start_window(env: Any) -> None:
    """As ``_skip_cooldown``, plus the 15-minute per-address start window.

    Only for tests that need many rounds of start-and-fail. The caps are
    what make that slow in reality — reaching a lockout through exhausted
    codes takes over half an hour, because only five codes per address
    are issued per quarter hour. That is the intended cost, not an
    obstacle to the lockout arithmetic this exercises.
    """
    _skip_cooldown(env)
    for key in [k for k in env.redis.counts if ":otp_start_" in k]:
        del env.redis.counts[key]


def _seed_known(env: Any) -> tuple[Identity, UUID]:
    tenant_id = uuid4()
    identity = env.identities.seed(KNOWN, last_tenant_id=tenant_id)
    env.identities.add_membership(
        identity.id,
        Membership(tenant_id=tenant_id, name="acme", kind="team", role="admin", status="active"),
    )
    return identity, tenant_id


# ── start: the enumeration dead end ──────────────────────────────────────


def test_start_is_identical_for_known_and_unknown_addresses(env: Any) -> None:
    _seed_known(env)

    known = _start(env, KNOWN)
    unknown = _start(env, UNKNOWN)

    assert known.status_code == unknown.status_code == 202
    assert (
        set(known.json())
        == set(unknown.json())
        == {
            "challenge_id",
            "expires_in",
            "resend_after",
        }
    )
    # Every field but the opaque id is byte-identical.
    assert known.json()["expires_in"] == unknown.json()["expires_in"] == 600
    assert known.json()["resend_after"] == unknown.json()["resend_after"] == 60
    assert known.json()["challenge_id"] != unknown.json()["challenge_id"]
    # Exactly one mail each — the unknown address gets a code too, because
    # that is the signup path.
    assert len(env.provider.sent) == 2


def test_start_rejects_a_malformed_address(env: Any) -> None:
    response = env.client.post(
        "/auth/email/start", json={"email": "not-an-address"}, headers=ORIGIN
    )
    assert response.status_code == 422  # pydantic EmailStr rejects it first
    assert env.provider.sent == []


def test_the_code_is_never_in_the_subject(env: Any) -> None:
    _start(env, UNKNOWN)
    message = env.provider.sent[0]
    assert not any(ch.isdigit() for ch in message.subject)
    # And the body carries no link and does not echo the address.
    assert "http" not in message.text_body
    assert UNKNOWN not in message.text_body
    assert UNKNOWN not in message.html_body


def test_a_second_start_supersedes_the_first_code(env: Any) -> None:
    first = _start(env, UNKNOWN).json()
    first_code = _code_of(env, first["challenge_id"])
    _skip_cooldown(env)  # this test is about supersession, not the wait

    second = _start(env, UNKNOWN).json()
    assert second["challenge_id"] != first["challenge_id"]

    stale = _verify(env, first["challenge_id"], first_code)
    assert stale.status_code == 400
    assert stale.json()["code"] == "challenge_consumed"


def test_a_resend_inside_the_cooldown_is_refused(env: Any) -> None:
    _start(env, UNKNOWN)
    again = _start(env, UNKNOWN)
    assert again.status_code == 429
    assert again.json()["code"] == "rate_limited"
    assert int(again.headers["Retry-After"]) >= 1
    assert len(env.provider.sent) == 1


# ── start: limits and failure postures ───────────────────────────────────


def test_the_sixth_start_for_one_address_in_the_window_is_refused(env: Any) -> None:
    # The per-address cap is 5 / 15 min; the 60 s cooldown would fire
    # first, so it is stepped over by ageing each challenge.
    for i in range(5):
        response = _start(env, f"person{i}@acme.example")
        assert response.status_code == 202
    # Now the same address five times, with the cooldown stepped over so
    # the cap is the only thing that can refuse.
    for _ in range(5):
        assert _start(env, UNKNOWN).status_code == 202
        _skip_cooldown(env)
    sixth = _start(env, UNKNOWN)
    assert sixth.status_code == 429
    assert sixth.json()["code"] == "rate_limited"
    assert "Retry-After" in sixth.headers


def test_start_fails_closed_when_redis_is_down_and_verify_still_works(env: Any) -> None:
    opened = _start(env, UNKNOWN).json()
    code = _code_of(env, opened["challenge_id"])
    sent_before = len(env.provider.sent)

    env.redis.down = True

    refused = _start(env, "someone-else@acme.example")
    assert refused.status_code == 503
    assert refused.json()["code"] == "rate_limiter_unavailable"
    assert len(env.provider.sent) == sent_before, "a refused start sends no mail"

    # Verify's per-IP cap fails OPEN: the challenge's own attempt budget
    # is the real bound, and it does not need Redis.
    ok = _verify(env, opened["challenge_id"], code)
    assert ok.status_code == 200


def test_a_mail_failure_deletes_the_challenge(env: Any) -> None:
    env.provider.fail = True
    response = _start(env, UNKNOWN)
    assert response.status_code == 503
    assert response.json()["code"] == "email_delivery_unavailable"
    # No dangling code: nothing was left for anyone to guess against.
    assert env.challenges.rows == {}


# ── verify: signup ───────────────────────────────────────────────────────


def test_an_unknown_address_signs_up_and_lands_in_its_own_workspace(env: Any) -> None:
    opened = _start(env, UNKNOWN).json()
    code = _code_of(env, opened["challenge_id"])

    response = _verify(env, opened["challenge_id"], code)
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "authenticated"
    assert body["is_new_identity"] is True
    assert body["identity"]["email"] == UNKNOWN
    assert body["identity"]["has_password"] is False

    # Exactly one personal workspace, with an owner membership.
    assert len(env.identities.tenants) == 1
    workspace = env.identities.tenants[0]
    assert workspace.kind == "personal"
    assert workspace.display_name == "nobody's workspace"
    assert workspace.slug.startswith("ws-")
    assert body["memberships"] == [
        {
            "tenant_id": str(workspace.id),
            "name": workspace.name,
            "kind": "personal",
            "role": "owner",
            "status": "active",
        }
    ]
    # ...and a `users` row, so the rest of the estate can see this person.
    assert env.identities.users == [(UUID(body["identity"]["id"]), workspace.id)]

    # The token is scoped to that workspace and to nothing else.
    claims = jwt.get_unverified_claims(body["access_token"])
    assert claims["tid"] == str(workspace.id)
    assert claims["sub"] == body["identity"]["id"]
    # `tenant_admin` AND `member`, because whoever owns a workspace also
    # works in it. S14's admin/content separation gives `tenant_admin` no
    # content permission at all, so the first token of every self-serve
    # account used to be one that could not write a note, submit an ASR
    # job or dictate — `403 deny: roles=['tenant_admin'] cannot
    # 'asr.write'` on the first thing the person tried
    # (docs/auth/roles.md § "a person who administers a workspace and
    # takes notes holds both").
    assert claims["roles"] == ["tenant_admin", "member"]
    assert body["tenant_id"] == body["default_tenant_id"] == str(workspace.id)

    kinds = [c["kind"] for c in env.audit]
    assert "auth.signup" in kinds and "auth.login" in kinds
    signup = next(c for c in env.audit if c["kind"] == "auth.signup")
    assert signup["tenant_id"] == workspace.id, "the new workspace's own first event"


def test_a_web_client_gets_the_refresh_cookie_and_no_body_token(env: Any) -> None:
    opened = _start(env, UNKNOWN).json()
    response = _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))
    assert response.json()["refresh_token"] is None
    assert "mdx_rt" in response.cookies


def test_a_native_client_gets_the_token_in_the_body_and_no_cookie(env: Any) -> None:
    started = env.client.post(
        "/auth/email/start",
        json={"email": UNKNOWN},
        headers={"X-Client-Type": "macos"},
    )
    assert started.status_code == 202
    opened = started.json()
    response = env.client.post(
        "/auth/email/verify",
        json={
            "challenge_id": opened["challenge_id"],
            "code": _code_of(env, opened["challenge_id"]),
        },
        headers={"X-Client-Type": "ios"},
    )
    assert response.status_code == 200
    assert response.json()["refresh_token"]
    assert "mdx_rt" not in response.cookies


# ── verify: returning users ──────────────────────────────────────────────


def test_a_known_address_lands_in_its_last_workspace(env: Any) -> None:
    identity, tenant_id = _seed_known(env)
    other = uuid4()
    env.identities.add_membership(
        identity.id,
        Membership(tenant_id=other, name="globex", kind="team", role="viewer", status="active"),
    )

    opened = _start(env, KNOWN).json()
    response = _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))

    assert response.status_code == 200
    body = response.json()
    assert body["is_new_identity"] is False
    assert body["tenant_id"] == str(tenant_id)
    assert len(body["memberships"]) == 2
    assert jwt.get_unverified_claims(body["access_token"])["roles"] == [
        "tenant_admin",
        "member",
    ], "an admin of a team works in it too — managing is not a lockout"
    assert env.identities.tenants == [], "no workspace is created for a returning user"


def test_signing_in_during_the_deletion_grace_reactivates_the_account(env: Any) -> None:
    tenant_id = uuid4()
    identity = env.identities.seed(
        KNOWN,
        status="pending_deletion",
        last_tenant_id=tenant_id,
        deletion_requested_at=datetime.now(UTC) - timedelta(days=1),
    )
    env.identities.add_membership(
        identity.id,
        Membership(tenant_id=tenant_id, name="acme", kind="team", role="owner", status="active"),
    )

    opened = _start(env, KNOWN).json()
    response = _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))

    assert response.status_code == 200
    assert env.identities.rows[identity.id].status == "active"
    assert env.identities.rows[identity.id].deletion_requested_at is None
    assert "auth.account_deletion_cancelled" in [c["kind"] for c in env.audit]


def test_a_disabled_account_cannot_sign_in(env: Any) -> None:
    identity = env.identities.seed(KNOWN, status="disabled")
    env.identities.add_membership(
        identity.id,
        Membership(tenant_id=uuid4(), name="acme", kind="team", role="owner", status="active"),
    )
    opened = _start(env, KNOWN).json()
    response = _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))
    assert response.status_code == 403
    assert response.json()["code"] == "account_disabled"


def test_an_identity_with_no_workspace_gets_one_back(env: Any) -> None:
    """BE-2 F3, replacing the `no_workspace` refusal on this path.

    An account whose last membership was removed used to be told 409 and
    left with nothing to act on — signing in again could not fix it, and
    neither could the person. It now gets the personal workspace every
    identity is entitled to. Their existing notes are wherever they were;
    this restores a place to stand, not any content.
    """
    identity = env.identities.seed(KNOWN)
    opened = _start(env, KNOWN).json()
    response = _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_new_identity"] is False
    assert [w["kind"] for w in body["memberships"]] == ["personal"]
    # The bridge `users` row goes with it — without one the account holds
    # a valid token and cannot save a note (migration 0031).
    assert any(sub == identity.id for sub, _ in env.identities.users)


def test_a_keycloak_account_with_mfa_is_sent_to_the_password_form(env: Any) -> None:
    """BE-3 F3 — `409 use_password`.

    An emailed code is a single factor. This person's second factor lives
    in Keycloak, where auth-service can neither see nor challenge it, so
    minting a native session from a code alone would quietly downgrade an
    account whose owner deliberately turned two-factor on.
    """
    identity = env.identities.seed(KNOWN, legacy_idp=True, mfa_enabled=True)
    env.identities.add_membership(
        identity.id,
        Membership(tenant_id=uuid4(), name="acme", kind="team", role="owner", status="active"),
    )
    opened = _start(env, KNOWN).json()
    response = _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))
    assert response.status_code == 409
    assert response.json()["code"] == "use_password"


def test_a_keycloak_account_without_mfa_gets_a_native_session(env: Any) -> None:
    """The ordinary migrated user: `legacy_idp` alone is not a refusal.

    That is the whole point of the dual period — they sign in with a code
    today and their password keeps working tomorrow.
    """
    identity = env.identities.seed(KNOWN, legacy_idp=True, mfa_enabled=False)
    env.identities.add_membership(
        identity.id,
        Membership(tenant_id=uuid4(), name="acme", kind="team", role="owner", status="active"),
    )
    opened = _start(env, KNOWN).json()
    response = _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))
    assert response.status_code == 200, response.text
    assert response.json()["is_new_identity"] is False


def test_a_native_account_with_mfa_is_challenged_not_refused(env: Any) -> None:
    """`mfa_enabled` alone must not trigger `use_password`.

    A native second factor is one this service CAN challenge; routing it
    to the password form would send the person to a form they may have no
    password for.
    """
    identity = env.identities.seed(KNOWN, legacy_idp=False, mfa_enabled=True)
    env.identities.add_membership(
        identity.id,
        Membership(tenant_id=uuid4(), name="acme", kind="team", role="owner", status="active"),
    )
    opened = _start(env, KNOWN).json()
    response = _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))
    assert response.status_code != 409 or response.json()["code"] != "use_password"


# ── verify: the attempt budget ───────────────────────────────────────────


def test_the_fifth_wrong_code_consumes_the_challenge(env: Any) -> None:
    _seed_known(env)
    opened = _start(env, KNOWN).json()
    cid = opened["challenge_id"]
    real_code = _code_of(env, cid)
    wrong = "000000" if real_code != "000000" else "111111"

    for expected_left in (4, 3, 2, 1):
        response = _verify(env, cid, wrong)
        assert response.status_code == 400
        assert response.json()["code"] == "code_invalid"
        assert response.json()["attempts_left"] == expected_left

    fifth = _verify(env, cid, wrong)
    assert fifth.status_code == 429
    assert fifth.json()["code"] == "too_many_attempts"
    assert env.challenges.rows[UUID(cid)].consumed_at is not None

    # The sixth attempt is impossible even holding the right code.
    sixth = _verify(env, cid, real_code)
    assert sixth.status_code == 400
    assert sixth.json()["code"] == "challenge_consumed"


def test_an_expired_challenge_is_refused_without_checking_the_code(env: Any) -> None:
    opened = _start(env, UNKNOWN).json()
    cid = UUID(opened["challenge_id"])
    code = _code_of(env, opened["challenge_id"])
    row = env.challenges.rows[cid]
    env.challenges.rows[cid] = replace(row, expires_at=datetime.now(UTC) - timedelta(seconds=1))

    response = _verify(env, str(cid), code)
    assert response.status_code == 400
    assert response.json()["code"] == "challenge_expired"


def test_an_unknown_challenge_id_looks_like_an_expired_one(env: Any) -> None:
    response = _verify(env, str(uuid4()), "123456")
    assert response.status_code == 400
    assert response.json()["code"] == "challenge_expired"


def test_a_double_submitted_code_logs_in_exactly_once(env: Any) -> None:
    opened = _start(env, UNKNOWN).json()
    code = _code_of(env, opened["challenge_id"])

    first = _verify(env, opened["challenge_id"], code)
    second = _verify(env, opened["challenge_id"], code)

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["code"] == "challenge_consumed"
    assert len(env.sessions.created) == 1


def test_the_grouped_form_from_the_mail_is_accepted(env: Any) -> None:
    opened = _start(env, UNKNOWN).json()
    code = _code_of(env, opened["challenge_id"])
    response = _verify(env, opened["challenge_id"], f"{code[:3]} {code[3:]}")
    assert response.status_code == 200


# ── lockout ──────────────────────────────────────────────────────────────


def test_ten_exhausted_challenges_lock_the_account_and_mail_once(env: Any) -> None:
    identity, _ = _seed_known(env)
    wrong = "000000"

    for _ in range(10):
        opened = _start(env, KNOWN).json()
        cid = opened["challenge_id"]
        real = _code_of(env, cid)
        for _ in range(5):
            _verify(env, cid, "111111" if real == wrong else wrong)
        _skip_start_window(env)

    locked = env.identities.rows[identity.id]
    assert locked.locked_until is not None
    assert locked.locked_until > datetime.now(UTC)
    assert env.locks_audited == [identity.id], "one auth.account_locked security event"

    # A start while locked still returns the uniform 202 — but mails the
    # lock notice instead of a code, and only once.
    codes_before = len(env.provider.sent)
    for _ in range(3):
        assert _start(env, KNOWN).status_code == 202
        _skip_start_window(env)
    assert len(env.provider.sent) == codes_before + 1
    assert "locked" in env.provider.sent[-1].subject.lower()
    assert env.identities.lock_notices == [identity.id]


def test_a_successful_sign_in_clears_the_failure_counters(env: Any) -> None:
    identity, tenant_id = _seed_known(env)
    env.identities.rows[identity.id] = replace(
        env.identities.rows[identity.id], failed_login_count=7
    )

    opened = _start(env, KNOWN).json()
    _verify(env, opened["challenge_id"], _code_of(env, opened["challenge_id"]))

    assert env.identities.rows[identity.id].failed_login_count == 0
    assert env.identities.rows[identity.id].locked_until is None


# ── hygiene ──────────────────────────────────────────────────────────────


def test_no_log_record_carries_an_address_or_a_code(
    env: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="auth_service")
    _seed_known(env)

    opened = _start(env, KNOWN).json()
    code = _code_of(env, opened["challenge_id"])
    _verify(env, opened["challenge_id"], "000000" if code != "000000" else "111111")
    _verify(env, opened["challenge_id"], code)

    haystack = "\n".join(
        record.getMessage()
        + json.dumps({k: str(v) for k, v in record.__dict__.items() if not k.startswith("_")})
        for record in caplog.records
    )
    assert KNOWN not in haystack
    assert "acme.example" not in haystack
    assert code not in haystack


def test_audit_payloads_never_carry_the_address_or_the_code(env: Any) -> None:
    _seed_known(env)
    opened = _start(env, KNOWN).json()
    code = _code_of(env, opened["challenge_id"])
    _verify(env, opened["challenge_id"], code)

    blob = json.dumps([{k: str(v) for k, v in c.items()} for c in env.audit])
    assert KNOWN not in blob
    assert code not in blob


def test_the_routes_do_not_exist_in_keycloak_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    from auth_service.config import settings
    from auth_service.main import create_app

    monkeypatch.setattr(settings, "idp_mode", "keycloak")
    paths = {route.path for route in create_app().routes}  # type: ignore[attr-defined]
    assert "/auth/email/start" not in paths
    assert "/auth/email/verify" not in paths


def test_the_routes_exist_in_dual_mode_beside_the_keycloak_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BE-3 F2 — the headline of the batch.

    `dual` is the mode where a stranger can sign up while every existing
    user's password login is still mounted and unchanged. Both halves are
    asserted here because either one alone is a different feature.
    """
    monkeypatch.setenv("TESTING", "true")
    from auth_service.config import settings
    from auth_service.main import create_app

    monkeypatch.setattr(settings, "idp_mode", "dual")
    paths = {route.path for route in create_app().routes}  # type: ignore[attr-defined]
    assert {"/auth/email/start", "/auth/email/verify"} <= paths
    assert {"/auth/login", "/auth/password/change", "/auth/mfa/verify"} <= paths
    # session_native claims these; login.py's copies are shadowed and its
    # handler is reached by delegation instead (`_belongs_to_keycloak`).
    assert {"/auth/refresh", "/auth/logout", "/auth/token"} <= paths
    # `PATCH /auth/me` is needed by the welcome step (BE-3 F4).
    assert "/auth/me" in paths


def test_a_new_workspace_takes_its_locale_from_accept_language(env: Any) -> None:
    """BE-3 F4. A guess, and a better one than `en` for a product with
    Ukrainian and German customers — but only from a header the browser
    actually sends, and only for a language we have copy for."""
    started = _start(env, UNKNOWN)
    assert started.status_code == 202, started.text
    opened = started.json()
    _verify(
        env,
        opened["challenge_id"],
        _code_of(env, opened["challenge_id"]),
        headers={"Accept-Language": "uk-UA,uk;q=0.9,en;q=0.8"},
    )
    assert env.identities.signup_locales == ["uk"]


def test_an_unsupported_accept_language_falls_back_to_english(env: Any) -> None:
    started = _start(env, UNKNOWN)
    assert started.status_code == 202, started.text
    opened = started.json()
    _verify(
        env,
        opened["challenge_id"],
        _code_of(env, opened["challenge_id"]),
        headers={"Accept-Language": "fr-FR,fr;q=0.9"},
    )
    assert env.identities.signup_locales == ["en"]
