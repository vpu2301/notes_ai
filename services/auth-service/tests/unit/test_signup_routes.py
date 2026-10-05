"""BE-0 — self-serve signup: the router, the service and their refusals.

The load-bearing assertions here are the ones about what the endpoint
does NOT say. `/auth/signup` is reachable by anyone with a socket, and an
endpoint that answers differently for a registered address than for an
unknown one is a membership oracle: point it at a list and read off which
addresses are customers.

Everything is faked except the decision logic — Keycloak, the challenge
store, the mailer and the pool are stand-ins, so these run with no
container in the loop. The wiring is covered by the `_db`/`_e2e` suites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_service.domain import email_code as ec
from auth_service.domain.onboarding_service import (
    OnboardingService,
    SignupConfig,
    generate_password,
)
from auth_service.keycloak_client import KeycloakError

GOOD_PASSWORD = "correct-horse-battery-staple-9"
KNOWN = "olena@acme.example"
UNKNOWN = "nobody@acme.example"


# ── fakes ────────────────────────────────────────────────────────────────


class FakeKeycloak:
    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.deleted: list[UUID] = []
        self.create_error: Exception | None = None
        self.enable_error: Exception | None = None
        self.created_payloads: list[dict[str, Any]] = []

    async def create_user_with_password(
        self,
        *,
        email: str,
        display_name: str,
        tenant_id: UUID,
        password: str,
        realm_roles: list[str],
        enabled: bool = False,
    ) -> UUID:
        if self.create_error is not None:
            raise self.create_error
        if email in self.users:
            raise KeycloakError(status=409, body={}, message="exists")
        sub = uuid4()
        self.users[email] = {
            "id": sub,
            "enabled": enabled,
            "emailVerified": False,
            "roles": list(realm_roles),
            "password": password,
        }
        self.created_payloads.append(
            {"email": email, "enabled": enabled, "roles": list(realm_roles)}
        )
        return sub

    async def set_email_verified(self, sub: UUID, *, verified: bool = True) -> None:
        if self.enable_error is not None:
            raise self.enable_error
        for row in self.users.values():
            if row["id"] == sub:
                row["enabled"] = verified
                row["emailVerified"] = verified

    async def delete_user(self, sub: UUID) -> None:
        self.deleted.append(sub)
        for email, row in list(self.users.items()):
            if row["id"] == sub:
                del self.users[email]

    async def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.users.get(email)


class FakeChallenges:
    def __init__(self) -> None:
        self.rows: dict[UUID, ec.Challenge] = {}

    async def open(self, **kw: Any) -> ec.Challenge:
        row = ec.Challenge(
            id=kw["challenge_id"],
            kind=kw["kind"],
            email=kw["email"],
            identity_id=kw["identity_id"],
            code_hash=kw["code_hash"],
            expires_at=kw["expires_at"],
            attempts=0,
            max_attempts=kw["max_attempts"],
            consumed_at=None,
            created_at=datetime.now(UTC),
            metadata=kw.get("metadata") or {},
        )
        self.rows[row.id] = row
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

    async def consume(self, challenge_id: UUID) -> bool:
        row = self.rows.get(challenge_id)
        if row is None or row.consumed_at is not None:
            return False
        self.rows[challenge_id] = replace(row, consumed_at=datetime.now(UTC))
        return True

    async def record_attempt(self, challenge_id: UUID, *, attempts: int) -> None:
        self.rows[challenge_id] = replace(self.rows[challenge_id], attempts=attempts)


@dataclass
class SentMail:
    kind: str
    to: str
    code: str = ""
    password: str = ""


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[SentMail] = []
        self.fail = False

    async def send_verify(
        self, *, to: str, code: str, lang: str, user_agent: str, ttl_seconds: int
    ) -> None:
        if self.fail:
            raise RuntimeError("relay down")
        self.sent.append(SentMail("signup_verify", to, code=code))

    async def send_exists(self, *, to: str, lang: str, user_agent: str) -> None:
        if self.fail:
            raise RuntimeError("relay down")
        self.sent.append(SentMail("signup_exists", to))

    async def send_concierge(
        self, *, to: str, display_name: str, temporary_password: str, lang: str
    ) -> None:
        self.sent.append(SentMail("concierge_welcome", to, password=temporary_password))


class FakeConn:
    """Just enough asyncpg surface for the service's four statements."""

    def __init__(self, store: FakeStore) -> None:
        self._store = store

    async def execute(self, sql: str, *args: Any) -> str | None:
        if self._store.fail_writes:
            raise RuntimeError("database is down")
        sql_l = " ".join(sql.split()).lower()
        if sql_l.startswith("insert into tenants"):
            if args[1] in self._store.tenant_names:
                import asyncpg

                exc = asyncpg.UniqueViolationError("duplicate")
                exc.constraint_name = "tenants_name_key"  # type: ignore[attr-defined]
                raise exc
            self._store.tenant_names.add(args[1])
            self._store.tenants[args[0]] = {
                "name": args[1],
                "locale": args[4],
                "signup_source": args[5],
                "plan_limits": args[6],
            }
        elif sql_l.startswith("insert into referrals"):
            self._store.referrals.append({"ref_code": args[0], "sub": args[1], "tenant_id": None})
        elif sql_l.startswith("update referrals"):
            stamped = 0
            for row in self._store.referrals:
                if row["sub"] == args[0] and row["tenant_id"] is None:
                    row["tenant_id"] = args[1]
                    stamped += 1
            self._store.referrals_stamped += stamped
            return f"UPDATE {stamped}"
        elif sql_l.startswith("insert into tenant_memberships"):
            self._store.memberships.append((args[0], args[1]))
        elif sql_l.startswith("insert into identities"):
            self._store.identities[args[0]] = {
                "email": args[1],
                "verified_at": args[2],
                "last_tenant_id": args[5],
            }
        elif sql_l.startswith("insert into users"):
            self._store.users[args[0]] = {
                "tenant_id": args[1],
                "email": args[2],
                "status": args[5],
            }
        elif sql_l.startswith("update identities"):
            row = self._store.identities.get(args[0])
            if row is not None and row["verified_at"] is None:
                row["verified_at"] = datetime.now(UTC)
        elif sql_l.startswith("update users"):
            row = self._store.users.get(args[0])
            if row is not None and row["status"] == "invited":
                row["status"] = "active"
        elif sql_l.startswith("select set_config"):
            pass

    async def fetchval(self, sql: str, *args: Any) -> Any:
        sql_l = " ".join(sql.split()).lower()
        if sql_l.startswith("update referrals"):
            return None
        if "select 1 from identities where email" in sql_l:
            return (
                1 if any(i["email"] == args[0] for i in self._store.identities.values()) else None
            )
        if "select id from identities" in sql_l and "email_verified_at is null" in sql_l:
            for ident_id, row in self._store.identities.items():
                if row["email"] == args[0] and row["verified_at"] is None:
                    return ident_id
            return None
        if "select last_tenant_id from identities" in sql_l:
            row = self._store.identities.get(args[0])
            return row["last_tenant_id"] if row else None
        return None

    def transaction(self) -> Any:
        return _Ctx()


class _Ctx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: Any) -> bool:
        return False


@dataclass
class FakeStore:
    tenants: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    referrals: list[dict[str, Any]] = field(default_factory=list)
    referrals_stamped: int = 0
    tenant_names: set[str] = field(default_factory=set)
    memberships: list[tuple[UUID, UUID]] = field(default_factory=list)
    users: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    identities: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    fail_writes: bool = False

    def acquire(self) -> Any:
        store = self

        class _Acquire:
            async def __aenter__(self) -> FakeConn:
                return FakeConn(store)

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        return _Acquire()


class FakeLimiter:
    def __init__(self) -> None:
        self.counts: dict[tuple[str, str], int] = {}
        self.blocked: set[str] = set()

    async def allow(
        self, scope: str, subject: str, *, limit: int, window_seconds: int, fail_open: bool
    ) -> Any:
        if scope in self.blocked:
            return _Decision(False, 60)
        key = (scope, subject)
        self.counts[key] = self.counts.get(key, 0) + 1
        return _Decision(self.counts[key] <= limit, 60)


@dataclass
class _Decision:
    allowed: bool
    retry_after: int


@dataclass
class Env:
    service: OnboardingService
    kc: FakeKeycloak
    challenges: FakeChallenges
    mailer: FakeMailer
    store: FakeStore
    limiter: FakeLimiter
    audit: list[dict[str, Any]]
    client: TestClient


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    from auth_service import deps
    from auth_service.config import settings
    from auth_service.routers import signup as signup_router

    kc, challenges, mailer = FakeKeycloak(), FakeChallenges(), FakeMailer()
    store, limiter = FakeStore(), FakeLimiter()
    audit: list[dict[str, Any]] = []

    async def _audit(**kw: Any) -> None:
        audit.append(kw)

    service = OnboardingService(
        keycloak=kc,
        pool=store,  # type: ignore[arg-type]
        challenges=challenges,
        mailer=mailer,
        config=SignupConfig(disposable_domains=frozenset({"mailinator.com"})),
        limiter=limiter,
        audit=_audit,
    )

    class _State:
        onboarding_service = service

    deps.install_state(_State())  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "signup_resend_seconds", 60)
    # The timing floor is a property of the deployment, not of the logic
    # under test; holding every request for 300 ms would only slow this file.
    monkeypatch.setattr(settings, "signup_min_response_ms", 0)

    app = FastAPI()
    from observability import register_exception_handlers

    register_exception_handlers(app)
    app.include_router(signup_router.router)
    return Env(service, kc, challenges, mailer, store, limiter, audit, TestClient(app))


def _signup(env: Env, email: str, password: str = GOOD_PASSWORD, name: str = "Olena") -> Any:
    return env.client.post(
        "/auth/signup", json={"email": email, "password": password, "display_name": name}
    )


def _code_for(env: Env, email: str) -> str:
    """Pull the code out of the mail the fake captured."""
    for mail in reversed(env.mailer.sent):
        if mail.to == email and mail.kind == "signup_verify":
            return mail.code
    raise AssertionError(f"no verification mail for {email}")


# ── the uniform 202 ──────────────────────────────────────────────────────


def test_a_new_address_gets_an_account_a_workspace_and_a_code(env: Env) -> None:
    response = _signup(env, UNKNOWN)
    assert response.status_code == 202, response.text
    assert response.json() == {"status": "verification_sent", "resend_after": 60}

    assert UNKNOWN in env.kc.users
    # Disabled until confirmed: an account nobody has verified must not be
    # able to obtain a token by ANY grant, not merely through our proxy.
    assert env.kc.users[UNKNOWN]["enabled"] is False
    # BOTH roles. `tenant_admin` alone holds no content permission at all
    # (S14), so the account could not write the first note.
    assert env.kc.created_payloads[0]["roles"] == ["tenant_admin", "member"]

    assert len(env.store.tenants) == 1
    assert len(env.store.memberships) == 1
    assert len(env.store.users) == 1
    assert next(iter(env.store.users.values()))["status"] == "invited"
    # The identity row goes in the same transaction, so a BE-0 account is
    # shaped exactly like a migrated one and `/auth/me` can see it.
    assert len(env.store.identities) == 1

    assert [m.kind for m in env.mailer.sent] == ["signup_verify"]
    assert re.fullmatch(r"\d{6}", _code_for(env, UNKNOWN))


def test_an_existing_address_gets_the_same_202_and_no_second_account(env: Env) -> None:
    """The membership oracle this endpoint must not be."""
    first = _signup(env, UNKNOWN)
    env.mailer.sent.clear()

    second = _signup(env, UNKNOWN)
    assert second.status_code == first.status_code == 202
    assert second.json() == first.json()

    assert len(env.kc.users) == 1
    assert len(env.store.users) == 1
    # The only place the difference exists is a mailbox.
    assert [m.kind for m in env.mailer.sent] == ["signup_exists"]


def test_the_existing_branch_sends_no_code(env: Env) -> None:
    _signup(env, UNKNOWN)
    env.mailer.sent.clear()
    _signup(env, UNKNOWN)
    assert all(not m.code for m in env.mailer.sent)


# ── password policy ──────────────────────────────────────────────────────


def test_a_weak_password_is_refused_with_a_reason(env: Env) -> None:
    """Checked here rather than left to Keycloak, so the person gets a
    field-level message instead of a realm error in a language nobody
    chose."""
    response = _signup(env, UNKNOWN, password="password123")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "password_policy"
    assert body["min_length"] == 12
    assert body["reasons"]
    assert not env.kc.users, "nothing may be created before the password is accepted"


def test_a_password_built_from_the_address_is_refused(env: Env) -> None:
    response = _signup(env, "ada@acme.example", password="ada@acme.example1")
    assert response.status_code == 400
    assert response.json()["code"] == "password_policy"


def test_a_whitespace_display_name_is_refused_with_the_documented_code(env: Env) -> None:
    """Pydantic's `min_length=1` accepts "   "; the service does not.

    The distinction matters for the client: `400 display_name_required`
    is a field to fix, while a 422 body is a validation dump nobody
    renders.
    """
    response = _signup(env, UNKNOWN, name="   ")
    assert response.status_code == 400
    assert response.json()["code"] == "display_name_required"
    assert not env.kc.users


# ── compensation ─────────────────────────────────────────────────────────


def test_a_database_failure_deletes_the_keycloak_user(env: Env) -> None:
    """The whole reason Keycloak is written first.

    A Keycloak user with no rows is invisible to the product AND occupies
    the address, so the person cannot retry — the worst of both.
    """
    env.store.fail_writes = True
    response = _signup(env, UNKNOWN)
    assert response.status_code == 503
    assert response.json()["code"] == "signup_unavailable"

    assert env.kc.deleted, "the Keycloak user was not compensated"
    assert not env.kc.users, "an orphan was left in Keycloak"
    assert not env.store.users


def test_a_keycloak_outage_creates_nothing(env: Env) -> None:
    env.kc.create_error = KeycloakError(status=502, body={}, message="down")
    response = _signup(env, UNKNOWN)
    assert response.status_code == 503
    assert response.json()["code"] == "signup_unavailable"
    assert not env.store.users and not env.store.tenants


# ── verify ───────────────────────────────────────────────────────────────


def _verify(env: Env, email: str, code: str) -> Any:
    return env.client.post("/auth/signup/verify", json={"email": email, "code": code})


def test_the_right_code_enables_the_account_and_activates_the_row(env: Env) -> None:
    _signup(env, UNKNOWN)
    response = _verify(env, UNKNOWN, _code_for(env, UNKNOWN))
    assert response.status_code == 200
    assert response.json() == {"verified": True}

    assert env.kc.users[UNKNOWN]["enabled"] is True
    assert env.kc.users[UNKNOWN]["emailVerified"] is True
    assert next(iter(env.store.users.values()))["status"] == "active"
    assert any(a["kind"] == "auth.email_verified" for a in env.audit)


def test_the_grouped_form_from_the_mail_is_accepted(env: Env) -> None:
    _signup(env, UNKNOWN)
    code = _code_for(env, UNKNOWN)
    assert _verify(env, UNKNOWN, f"{code[:3]} {code[3:]}").status_code == 200


def test_a_wrong_code_reports_the_attempts_left(env: Env) -> None:
    _signup(env, UNKNOWN)
    real = _code_for(env, UNKNOWN)
    wrong = "000000" if real != "000000" else "111111"
    for expected_left in (4, 3, 2, 1):
        response = _verify(env, UNKNOWN, wrong)
        assert response.status_code == 400
        assert response.json()["code"] == "code_invalid"
        assert response.json()["attempts_left"] == expected_left
    fifth = _verify(env, UNKNOWN, wrong)
    assert fifth.status_code == 429
    assert fifth.json()["code"] == "too_many_attempts"


def test_an_unknown_address_looks_exactly_like_an_expired_code(env: Env) -> None:
    """Otherwise verify becomes the oracle signup refuses to be."""
    unknown = _verify(env, "stranger@acme.example", "123456")
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "challenge_expired"


def test_a_keycloak_failure_during_verify_keeps_the_code(env: Env) -> None:
    """`409 verify_retry`: the person must not lose their code to an
    outage that was not theirs."""
    _signup(env, UNKNOWN)
    code = _code_for(env, UNKNOWN)
    env.kc.enable_error = KeycloakError(status=503, body={}, message="down")

    response = _verify(env, UNKNOWN, code)
    assert response.status_code == 409
    assert response.json()["code"] == "verify_retry"

    env.kc.enable_error = None
    assert _verify(env, UNKNOWN, code).status_code == 200


# ── resend ───────────────────────────────────────────────────────────────


def test_resend_supersedes_the_previous_code(env: Env) -> None:
    _signup(env, UNKNOWN)
    first = _code_for(env, UNKNOWN)

    response = env.client.post("/auth/signup/resend", json={"email": UNKNOWN})
    assert response.status_code == 202
    second = _code_for(env, UNKNOWN)
    assert second != first

    assert _verify(env, UNKNOWN, first).status_code == 400
    assert _verify(env, UNKNOWN, second).status_code == 200


def test_resend_for_an_unknown_address_is_silent_and_still_202(env: Env) -> None:
    response = env.client.post("/auth/signup/resend", json={"email": "nobody@nowhere.example"})
    assert response.status_code == 202
    assert not env.mailer.sent


# ── rate limits ──────────────────────────────────────────────────────────


def test_the_per_ip_cap_refuses_with_retry_after(env: Env) -> None:
    env.limiter.blocked.add("signup_ip")
    response = _signup(env, UNKNOWN)
    assert response.status_code == 429
    assert response.json()["code"] == "signup_rate_limited"
    assert response.headers["Retry-After"] == "60"


def test_the_per_email_cap_is_keyed_on_a_hash_not_the_address(env: Env) -> None:
    """The rate-limit subject must not be the address itself: Redis keys
    end up in logs, dashboards and support screenshots."""
    _signup(env, UNKNOWN)
    subjects = {subject for _scope, subject in env.limiter.counts}
    assert UNKNOWN not in subjects
    assert ec.email_subject_hash(UNKNOWN) in subjects


# ── the 404 posture ──────────────────────────────────────────────────────


def test_the_routes_404_when_signup_is_not_wired() -> None:
    """A deployment with signup off looks like one that has no such
    endpoint, so a prober learns nothing about what is switched off."""
    from auth_service import deps
    from auth_service.routers import signup as signup_router

    class _State:
        onboarding_service = None

    deps.install_state(_State())  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(signup_router.router)
    client = TestClient(app)
    response = client.post(
        "/auth/signup",
        json={"email": UNKNOWN, "password": GOOD_PASSWORD, "display_name": "X"},
    )
    assert response.status_code == 404


# ── concierge ────────────────────────────────────────────────────────────


async def test_the_concierge_path_creates_an_enabled_account_and_sends_no_code(
    env: Env,
) -> None:
    account = await env.service.create_account(
        email=KNOWN,
        password=GOOD_PASSWORD,
        display_name="Olena",
        source="concierge",
        verified=True,
    )
    assert env.kc.users[KNOWN]["enabled"] is True
    assert env.store.users[account.sub]["status"] == "active"
    # No verification mail: the operator IS the verification.
    assert not any(m.kind == "signup_verify" for m in env.mailer.sent)
    signup_event = next(a for a in env.audit if a["kind"] == "auth.signup")
    assert signup_event["payload"] == {"source": "concierge", "plan": "free", "ref_present": False}


def test_a_generated_password_satisfies_the_policy_it_will_be_checked_against() -> None:
    """The concierge password is never typed by the operator, but Keycloak
    still applies the realm policy to it."""
    from auth_service.domain.password_policy import check_password

    for _ in range(20):
        assert check_password(generate_password(), min_length=12).ok


# ── the naming retry ─────────────────────────────────────────────────────


async def test_a_workspace_name_collision_is_retried_not_failed(env: Env) -> None:
    """Every `ada@` on every domain wants the workspace called "ada"."""
    await env.service.create_account(
        email="ada@one.example", password=GOOD_PASSWORD, display_name="Ada"
    )
    await env.service.create_account(
        email="ada@two.example", password=GOOD_PASSWORD, display_name="Ada"
    )
    assert len(env.store.tenants) == 2
    names = sorted(t["name"] for t in env.store.tenants.values())
    assert names[0] == "ada"
    assert names[1].startswith("ada-")


async def test_the_locale_reaches_the_new_workspace(env: Env) -> None:
    await env.service.create_account(
        email=UNKNOWN, password=GOOD_PASSWORD, display_name="Olena", locale="uk"
    )
    assert next(iter(env.store.tenants.values()))["locale"] == "uk"


# ── the challenge is bound to its row ────────────────────────────────────


async def test_a_code_hash_cannot_be_replayed_against_another_challenge(env: Env) -> None:
    """`code_hash` is sha256("<code>:<challenge id>"), so a hash lifted
    from a backup fits exactly one row."""
    _signup(env, UNKNOWN)
    row = next(iter(env.challenges.rows.values()))
    other_id = uuid4()
    assert ec.code_hash("482913", row.id) != ec.code_hash("482913", other_id)


def test_an_expired_challenge_is_refused(env: Env) -> None:
    _signup(env, UNKNOWN)
    cid = next(iter(env.challenges.rows))
    env.challenges.rows[cid] = replace(
        env.challenges.rows[cid], expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    response = _verify(env, UNKNOWN, _code_for(env, UNKNOWN))
    assert response.status_code == 400
    assert response.json()["code"] == "challenge_expired"


# ── Sprint 21: the conversion step ───────────────────────────────────


def test_a_referred_signup_records_plan_source_and_attribution(env: Env) -> None:
    r = env.client.post(
        "/auth/signup",
        json={
            "email": UNKNOWN,
            "password": GOOD_PASSWORD,
            "display_name": "Tom",
            "ref": "abcdefghijkl",
        },
    )
    assert r.status_code == 202
    (tenant,) = env.store.tenants.values()
    assert tenant["signup_source"] == "referral"
    assert tenant["plan_limits"] == '{"notes_per_month": 50, "members": 3}'
    assert env.store.referrals == [
        {"ref_code": "abcdefghijkl", "sub": _sub_of(env, UNKNOWN), "tenant_id": None}
    ]
    signup_event = next(a for a in env.audit if a["kind"] == "auth.signup")
    assert signup_event["payload"] == {"source": "referral", "plan": "free", "ref_present": True}
    assert "abcdefghijkl" not in repr(env.audit)

    # Verifying makes the workspace real, and that is when it is attributed.
    v = env.client.post(
        "/auth/signup/verify", json={"email": UNKNOWN, "code": _code_for(env, UNKNOWN)}
    )
    assert v.status_code == 200
    assert env.store.referrals[0]["tenant_id"] == _tenant_of(env, UNKNOWN)
    verified_event = next(a for a in env.audit if a["kind"] == "auth.email_verified")
    assert verified_event["payload"] == {"ref_present": True}


def test_a_plain_signup_is_self_serve_with_no_referral_row(env: Env) -> None:
    assert _signup(env, UNKNOWN).status_code == 202
    (tenant,) = env.store.tenants.values()
    assert tenant["signup_source"] == "self_serve"
    assert env.store.referrals == []
    env.client.post("/auth/signup/verify", json={"email": UNKNOWN, "code": _code_for(env, UNKNOWN)})
    assert env.store.referrals_stamped == 0


def test_a_bad_ref_code_is_refused_before_anything_is_created(env: Env) -> None:
    r = env.client.post(
        "/auth/signup",
        json={
            "email": UNKNOWN,
            "password": GOOD_PASSWORD,
            "display_name": "Tom",
            "ref": "not a code",
        },
    )
    assert r.status_code == 422
    assert env.store.tenants == {}


def test_a_disposable_address_gets_the_same_202_and_nothing_else(env: Env) -> None:
    r = _signup(env, "throwaway@mailinator.com")
    assert r.status_code == 202
    assert r.json() == _signup(env, UNKNOWN).json()
    assert "throwaway@mailinator.com" not in env.kc.users
    assert not any(m.to == "throwaway@mailinator.com" for m in env.mailer.sent)
    assert all(t["name"] != "throwaway" for t in env.store.tenants.values())


def test_config_says_whether_signup_is_on(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from auth_service import deps

    r = env.client.get("/auth/signup/config")
    assert r.status_code == 200
    assert r.json() == {
        "enabled": True,
        "min_password_length": 12,
        "disposable_domains_blocked": True,
    }

    class _Off:
        onboarding_service = None

    deps.install_state(_Off())  # type: ignore[arg-type]
    assert env.client.get("/auth/signup/config").json()["enabled"] is False
    assert _signup(env, UNKNOWN).status_code == 404


def _sub_of(env: Env, email: str) -> UUID:
    return env.kc.users[email]["id"]


def _tenant_of(env: Env, email: str) -> UUID:
    return next(
        row["last_tenant_id"] for row in env.store.identities.values() if row["email"] == email
    )
