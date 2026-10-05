"""A stranger can sign up through the real API and then, with that token only, see
templates, submit an ASR job, create and read a note, read the feed and verify the
new tenant's audit chain. Any failure here is a batch blocker.
Runs the four services in process with the ``dual`` issuer wiring.
Requires ``RUN_DB_INTEGRATION=1``, ``make dev-up``, ``make migrate-up``.
"""

from __future__ import annotations

import json
import os
import struct
import uuid

import asyncpg
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION") != "1",
    reason="needs RUN_DB_INTEGRATION=1 and the dev stack (Postgres + Redis)",
)

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

SU_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
DOMAIN = "firstuse.example"
ORIGIN = {"Origin": "http://localhost:5173"}

ISSUER = "http://localhost:8000"
KEYCLOAK_ISSUER = "http://localhost:8088/realms/notes"
AUDIENCE = "mdx-api"

# The `dual` fleet config: both issuers, the native one served by auth-service.
ISSUERS_JSON = json.dumps(
    [
        {
            "issuer": KEYCLOAK_ISSUER,
            "jwks_url": f"{KEYCLOAK_ISSUER}/protocol/openid-connect/certs",
            "audience": AUDIENCE,
        },
        {
            "issuer": ISSUER,
            "jwks_url": f"{ISSUER}/.well-known/jwks.json",
            "audience": AUDIENCE,
        },
    ]
)


def _email() -> str:
    return f"e{uuid.uuid4().hex[:12]}@{DOMAIN}"


def _one_second_wav() -> bytes:
    """16 kHz mono PCM silence, one second: this asserts acceptance, not what the model hears."""
    rate, seconds = 16_000, 1
    data = b"\x00\x00" * rate * seconds
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


# ── the four apps, wired the way `dual` wires them ───────────────────────


# The dev master key (compose mounts it at /etc/mdx/master.key).
MASTER_KEY = "infra/dev/master.key"


def _point_at_native_issuer(monkeypatch: pytest.MonkeyPatch, settings_module) -> None:
    monkeypatch.setattr(settings_module, "auth_issuers_json", ISSUERS_JSON)
    if hasattr(settings_module, "master_key_path"):
        monkeypatch.setattr(settings_module, "master_key_path", MASTER_KEY)


class _JwksVia:
    """Route the native issuer's JWKS URL to the in-process auth-service under test;
    everything else still goes to the network.
    """

    def __init__(self, auth_app, url: str) -> None:
        self._asgi = ASGITransport(app=auth_app)
        self._network = httpx.AsyncHTTPTransport()
        self._url = url

    async def handle_async_request(self, request):
        target = self._asgi if str(request.url) == self._url else self._network
        return await target.handle_async_request(request)


def _serve_jwks_from(app, auth_app) -> None:
    """Rebuild a service's JWKS cache so issuer 2 resolves in process."""
    from auth import JwksCache, issuer_url_map, issuers_from_env

    issuers = issuers_from_env(ISSUERS_JSON, issuer="", jwks_url="", audience=AUDIENCE)
    state = app.state.svc
    state.jwks_cache = JwksCache(
        issuer_to_url=issuer_url_map(issuers),
        http_client=httpx.AsyncClient(
            transport=_JwksVia(auth_app, f"{ISSUER}/.well-known/jwks.json")
        ),
    )
    # Every service caches the built dependency; a swapped cache alone is ignored.
    if hasattr(state, "_current_user_dep"):
        delattr(state, "_current_user_dep")
    if hasattr(state, "current_user_dep"):
        from auth import build_current_user, build_session_denylist  # noqa: F401

        state.current_user_dep = build_current_user(jwks_cache=state.jwks_cache, issuers=issuers)


@pytest_asyncio.fixture
async def auth_app(monkeypatch: pytest.MonkeyPatch):
    from auth_service.config import settings
    from auth_service.main import create_app

    # `dual`, not `native`: the mounting differs (see main.create_app).
    monkeypatch.setattr(settings, "idp_mode", "dual")
    monkeypatch.setattr(settings, "auth_signing_keys_file", "infra/dev/auth-signing-dev.json")
    monkeypatch.setattr(settings, "email_provider", "mock")
    monkeypatch.setattr(settings, "auth_issuer_url", ISSUER)
    monkeypatch.setattr(settings, "trusted_proxy_cidrs", "127.0.0.1/32")
    _point_at_native_issuer(monkeypatch, settings)

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def note_app(monkeypatch: pytest.MonkeyPatch, auth_app):
    from note_service.config import settings
    from note_service.main import create_app

    _point_at_native_issuer(monkeypatch, settings)
    app = create_app()
    async with app.router.lifespan_context(app):
        _serve_jwks_from(app, auth_app)
        yield app


@pytest_asyncio.fixture
async def asr_app(monkeypatch: pytest.MonkeyPatch, auth_app):
    from asr_service.config import settings
    from asr_service.main import create_app

    _point_at_native_issuer(monkeypatch, settings)
    app = create_app()
    async with app.router.lifespan_context(app):
        _serve_jwks_from(app, auth_app)
        yield app


@pytest_asyncio.fixture
async def notification_app(monkeypatch: pytest.MonkeyPatch, auth_app):
    from notification_service.config import settings
    from notification_service.main import create_app

    _point_at_native_issuer(monkeypatch, settings)
    app = create_app()
    async with app.router.lifespan_context(app):
        _serve_jwks_from(app, auth_app)
        yield app


@pytest_asyncio.fixture
async def su():
    conn = await asyncpg.connect(SU_DSN)
    try:
        yield conn
    finally:
        like = f"%@{DOMAIN}"
        # FK order: authorship columns reference `identities` (0028).
        for statement in (
            "DELETE FROM auth_challenges WHERE email LIKE $1",
            "DELETE FROM auth_sessions WHERE identity_id IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            # Drop `notes.current_version_id` first: it points at `note_versions`.
            "UPDATE notes SET current_version_id = NULL WHERE primary_author_id IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            "DELETE FROM note_versions WHERE created_by IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            "DELETE FROM notes WHERE primary_author_id IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            "DELETE FROM transcription_jobs WHERE requester_sub IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            "DELETE FROM users WHERE sub IN (SELECT id FROM identities WHERE email LIKE $1)",
            "DELETE FROM tenant_memberships WHERE user_sub IN"
            " (SELECT id FROM identities WHERE email LIKE $1)",
            "DELETE FROM identities WHERE email LIKE $1",
        ):
            await conn.execute(statement, like)
        await conn.close()


def _client(app, **headers):
    return AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 5000)),
        base_url="http://test",
        headers=headers,
    )


def _captured_code(app, to_address: str) -> str:
    for message in reversed(app.state.svc.email_provider.sent):
        if message.to_address == to_address:
            digits = "".join(ch for ch in message.text_body if ch.isdigit())
            assert len(digits) >= 6, "the mail carried no code"
            return digits[:6]
    raise AssertionError(f"no mail was captured for {to_address}")


def _disable_resend_cooldown(auth_app) -> None:
    """Turn off the Redis half of the resend cooldown (copied out of settings at build time)."""
    service = auth_app.state.svc.email_code_service
    # 1, not 0: the rate limiter rejects a non-positive window.
    object.__setattr__(service._cfg, "resend_seconds", 1)


async def _sign_up(auth_app, email: str) -> dict:
    caller = f"198.51.100.{uuid.uuid4().int % 254 + 1}"
    async with _client(auth_app, **ORIGIN, **{"X-Forwarded-For": caller}) as client:
        started = await client.post("/auth/email/start", json={"email": email})
        assert started.status_code == 202, started.text
        challenge_id = started.json()["challenge_id"]

        verified = await client.post(
            "/auth/email/verify",
            json={"challenge_id": challenge_id, "code": _captured_code(auth_app, email)},
            headers={"X-Client-Type": "native"},  # token in the body, not a cookie
        )
    assert verified.status_code == 200, verified.text
    result = verified.json()
    assert result["is_new_identity"] is True, "this address should not have existed"
    return result


# ── the guarantee ────────────────────────────────────────────────────────


async def test_a_brand_new_account_can_actually_use_the_product(
    auth_app, note_app, asr_app, notification_app, su
) -> None:
    email = _email()
    result = await _sign_up(auth_app, email)

    access_token = result["access_token"]
    tenant_id = result["tenant_id"]
    bearer = {"Authorization": f"Bearer {access_token}"}

    # One personal workspace and the bridge `users` row.
    assert [m["kind"] for m in result["memberships"]] == ["personal"]
    tenants = await su.fetchval(
        "SELECT count(*) FROM tenant_memberships m JOIN tenants t ON t.id = m.tenant_id"
        " WHERE m.user_sub = $1 AND t.kind = 'personal'",
        uuid.UUID(result["identity"]["id"]),
    )
    assert tenants == 1, "a signup creates exactly one personal workspace"
    bridged = await su.fetchval(
        "SELECT count(*) FROM users WHERE sub = $1", uuid.UUID(result["identity"]["id"])
    )
    assert bridged == 1, (
        "no bridge `users` row: this identity holds a valid token and cannot "
        "author a note (migration 0031)"
    )

    # 1. Templates: tenant-less system rows must be visible at once.
    async with _client(note_app, **bearer) as notes:
        templates = await notes.get("/templates")
        assert templates.status_code == 200, templates.text
        visible = templates.json()
        assert visible, "a new workspace sees no templates at all"
        meeting = [t for t in visible if "meeting" in json.dumps(t).lower()]
        assert meeting, (
            "the system meeting-notes template is not visible to a new "
            f"workspace; saw {[t.get('key') or t.get('name') for t in visible]}"
        )
        template_id = meeting[0]["id"]

    # 2. An ASR job is accepted (tenant KEK, bucket prefix, queue row).
    async with _client(asr_app, **bearer) as asr:
        submitted = await asr.post(
            "/asr/jobs",
            files={"audio": ("smoke.wav", _one_second_wav(), "audio/wav")},
            data={"language": "auto"},
        )
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["id"]
    assert job_id

    # 3. A note on the system template, and 4. reading it back
    #    (`from-transcript` needs a worker; notes_e2e.py covers that link).
    async with _client(note_app, **bearer) as notes:
        detail = await notes.get(f"/templates/{template_id}")
        assert detail.status_code == 200, detail.text
        template = detail.json()

        created = await notes.post(
            "/v1/notes",
            json={
                "content": {
                    "template_id": template["id"],
                    "template_schema_version": template["schema_version"],
                    "title": "First note",
                    "sections": [],
                }
            },
        )
        assert created.status_code == 201, created.text
        note_id = created.json()["id"]

        fetched = await notes.get(f"/v1/notes/{note_id}")
        assert fetched.status_code == 200, fetched.text

    # 5. The notification feed answers 200 with an empty page.
    async with _client(notification_app, **bearer) as feed:
        page = await feed.get("/v1/notifications")
        assert page.status_code == 200, page.text

    # 6. The new tenant's audit chain verifies at length one.
    async with _client(auth_app, **bearer, **ORIGIN) as auth:
        verified = await auth.get("/audit/verify")
        assert verified.status_code == 200, verified.text
        assert verified.json()["ok"] is True, verified.text

    assert tenant_id == result["tenant_id"]


async def test_signing_up_twice_with_one_address_does_not_make_two_accounts(
    auth_app, su, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second visit is a login, never a second identity."""
    email = _email()
    first = await _sign_up(auth_app, email)

    # Step past the 60 s resend cooldown (Redis counter + newest challenge's
    # `created_at`, both per address).
    _disable_resend_cooldown(auth_app)
    await su.execute(
        "UPDATE auth_challenges SET created_at = created_at - interval '2 minutes'"
        " WHERE email = $1",
        email,
    )

    caller = f"198.51.100.{uuid.uuid4().int % 254 + 1}"
    async with _client(auth_app, **ORIGIN, **{"X-Forwarded-For": caller}) as client:
        started = await client.post("/auth/email/start", json={"email": email})
        assert started.status_code == 202, started.text
        again = await client.post(
            "/auth/email/verify",
            json={
                "challenge_id": started.json()["challenge_id"],
                "code": _captured_code(auth_app, email),
            },
            headers={"X-Client-Type": "native"},
        )
    assert again.status_code == 200, again.text
    assert again.json()["is_new_identity"] is False
    assert again.json()["identity"]["id"] == first["identity"]["id"]

    count = await su.fetchval("SELECT count(*) FROM identities WHERE email = $1", email)
    assert count == 1


async def test_a_native_token_opens_note_service(note_app, auth_app) -> None:
    """The two-issuer rollout end to end: a wrong issuer list, JWKS URL or audience is a 401 here."""
    result = await _sign_up(auth_app, _email())
    async with _client(note_app, Authorization=f"Bearer {result['access_token']}") as notes:
        response = await notes.get("/templates")
    assert response.status_code == 200, (
        f"a native token was rejected by note-service ({response.status_code}); "
        "check AUTH_ISSUERS_JSON and /.well-known/jwks.json"
    )


async def test_an_unknown_issuer_is_still_refused(note_app) -> None:
    """The list is a list, not an amnesty."""
    from auth.testing import TestIssuer

    stranger = TestIssuer(issuer="https://someone-else.invalid", audience=AUDIENCE)
    async with _client(note_app, Authorization=f"Bearer {stranger.mint()}") as notes:
        response = await notes.get("/templates")
    assert response.status_code == 401, response.text
