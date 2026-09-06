"""IDX-A2 — signing keys, TokenService, JWKS/discovery, transport."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from auth import Claims, verify_token
from auth.testing import TestIssuer
from auth_service.domain.signing_keys import (
    KeySet,
    SigningKeyError,
    kid_for_public_key,
    load_signing_keys,
)
from auth_service.domain.token_service import TokenService
from auth_service.domain.transport import ClientType, TokenResponse, client_type_of, token_response
from auth_service.routers import wellknown
from auth_service.routers.wellknown import PRIVATE_JWK_MEMBERS

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _entry(*, not_after: datetime, bits: int = 2048, kid: str | None = None) -> dict[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return {
        "kid": kid or kid_for_public_key(private.public_key()),
        "private_pem": pem,
        "not_after": not_after.isoformat().replace("+00:00", "Z"),
    }


# ── signing keys ─────────────────────────────────────────────────────────


def test_active_key_is_furthest_not_after_still_ahead() -> None:
    old = _entry(not_after=NOW + timedelta(days=10))
    new = _entry(not_after=NOW + timedelta(days=200))
    past = _entry(not_after=NOW - timedelta(days=1))
    keys = KeySet.from_json(json.dumps([old, past, new]))
    assert keys.active(NOW).kid == new["kid"]


def test_jwks_publishes_retired_key_until_its_tokens_can_expire() -> None:
    ttl = 900
    just_retired = _entry(not_after=NOW - timedelta(seconds=ttl - 1))
    long_retired = _entry(not_after=NOW - timedelta(seconds=ttl + 1))
    live = _entry(not_after=NOW + timedelta(days=30))
    keys = KeySet.from_json(json.dumps([just_retired, long_retired, live]))
    kids = {k["kid"] for k in keys.jwks(access_ttl_seconds=ttl, now=NOW)["keys"]}
    assert kids == {just_retired["kid"], live["kid"]}


def test_jwks_never_carries_private_members() -> None:
    keys = KeySet.from_json(json.dumps([_entry(not_after=NOW + timedelta(days=1))]))
    for key in keys.jwks(access_ttl_seconds=900, now=NOW)["keys"]:
        assert set(key) == {"kty", "kid", "use", "alg", "n", "e"}
        assert not (PRIVATE_JWK_MEMBERS & set(key))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda e: e.__setitem__("kid", "wrong-kid"), "does not match"),
        (lambda e: e.__setitem__("not_after", "yesterday"), "ISO-8601"),
        (lambda e: e.__setitem__("not_after", "2027-01-01T00:00:00"), "timezone"),
        (lambda e: e.__setitem__("private_pem", "nope"), "PEM"),
        (lambda e: e.pop("kid"), "kid missing"),
    ],
)
def test_bad_key_entries_are_refused(mutate, message) -> None:  # noqa: ANN001
    entry = _entry(not_after=NOW + timedelta(days=1))
    mutate(entry)
    with pytest.raises(SigningKeyError, match=message):
        load_signing_keys(json.dumps([entry]))


def test_small_rsa_key_is_refused() -> None:
    with pytest.raises(SigningKeyError, match="2048"):
        load_signing_keys(json.dumps([_entry(not_after=NOW + timedelta(days=1), bits=1024)]))


def test_duplicate_kid_and_empty_list_are_refused() -> None:
    e = _entry(not_after=NOW + timedelta(days=1))
    with pytest.raises(SigningKeyError, match="duplicate"):
        load_signing_keys(json.dumps([e, e]))
    with pytest.raises(SigningKeyError, match="non-empty"):
        load_signing_keys("[]")
    with pytest.raises(SigningKeyError, match="valid JSON"):
        load_signing_keys("{not json")


def test_all_keys_expired_means_no_active_key() -> None:
    keys = KeySet.from_json(json.dumps([_entry(not_after=NOW - timedelta(days=1))]))
    with pytest.raises(SigningKeyError, match="past its not_after"):
        keys.active(NOW)


def test_dev_key_file_loads_and_matches_its_kid() -> None:
    from pathlib import Path

    raw = (Path(__file__).resolve().parents[4] / "infra/dev/auth-signing-dev.json").read_text()
    keys = KeySet.from_json(raw)
    assert keys.kids == ["8b5e3d8e2576"]


# ── TokenService ─────────────────────────────────────────────────────────


@pytest.fixture
def issuer_keys() -> KeySet:
    return KeySet.from_json(json.dumps([_entry(not_after=NOW + timedelta(days=90))]))


@pytest.fixture
def token_service(issuer_keys: KeySet) -> TokenService:
    return TokenService(
        keys=issuer_keys,
        issuer="https://auth.example.test",
        audience="mdx-api",
        access_ttl_seconds=900,
        clock=lambda: NOW.timestamp(),
    )


def test_minted_token_is_exactly_the_claims_contract(token_service: TokenService) -> None:
    sub, tid = uuid4(), uuid4()
    minted = token_service.mint(
        identity_id=sub,
        session_id="sess-1",
        tenant_id=tid,
        roles=["member"],
        email="a@example.test",
        name="Ada",
    )
    header = jwt.get_unverified_header(minted.token)
    assert header == {"alg": "RS256", "kid": minted.kid, "typ": "JWT"}
    payload = jwt.get_unverified_claims(minted.token)
    claims = Claims(**payload)  # extra="forbid": any claim Claims forbids fails here
    assert (claims.sub, claims.tid, claims.sid, claims.roles) == (sub, tid, "sess-1", ["member"])
    assert claims.iss == "https://auth.example.test" and claims.aud == "mdx-api"
    assert claims.exp - claims.iat == 900 == minted.expires_in
    assert claims.email == "a@example.test" and claims.name == "Ada"
    assert claims.mfa is False and claims.mfa_enrolled is False and claims.scope == ""
    assert claims.jti == minted.jti and claims.typ == "Bearer"


@pytest.mark.asyncio
async def test_minted_token_verifies_through_libs_auth(
    issuer_keys: KeySet, token_service: TokenService
) -> None:
    import time

    live = TokenService(
        keys=issuer_keys, issuer=token_service.issuer, audience="mdx-api", access_ttl_seconds=900
    )
    minted = live.mint(identity_id=uuid4(), session_id="s", tenant_id=uuid4(), roles=["viewer"])
    harness = TestIssuer(issuer=live.issuer, audience="mdx-api")
    # Serve OUR key set through the in-memory JWKS transport.
    harness.public_jwk = issuer_keys.jwks(access_ttl_seconds=900)["keys"][0]
    harness.kid = harness.public_jwk["kid"]
    claims = await verify_token(
        minted.token,
        expected_audience="mdx-api",
        expected_issuer=live.issuer,
        jwks_cache=harness.jwks_cache(),
    )
    assert claims.roles == ["viewer"] and claims.exp > time.time()


def test_mint_requires_roles_and_session(token_service: TokenService) -> None:
    with pytest.raises(ValueError, match="role"):
        token_service.mint(identity_id=uuid4(), session_id="s", tenant_id=uuid4(), roles=[])
    with pytest.raises(ValueError, match="session_id"):
        token_service.mint(identity_id=uuid4(), session_id="", tenant_id=uuid4(), roles=["member"])


def test_mint_uses_the_active_key_after_rotation() -> None:
    old = _entry(not_after=NOW + timedelta(days=5))
    new = _entry(not_after=NOW + timedelta(days=180))
    svc = TokenService(
        keys=KeySet.from_json(json.dumps([old, new])),
        issuer="https://i",
        audience="a",
        access_ttl_seconds=60,
        clock=lambda: NOW.timestamp(),
    )
    assert (
        svc.mint(identity_id=uuid4(), session_id="s", tenant_id=uuid4(), roles=["member"]).kid
        == new["kid"]
    )


# ── well-known routes ────────────────────────────────────────────────────


@pytest.fixture
def wellknown_client(
    monkeypatch: pytest.MonkeyPatch, issuer_keys: KeySet, token_service: TokenService
) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from auth_service import deps

    deps.install_state(SimpleNamespace(signing_keys=issuer_keys, token_service=token_service))  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(wellknown.router)
    return TestClient(app)


def test_discovery_document(wellknown_client: TestClient) -> None:
    doc = wellknown_client.get("/.well-known/openid-configuration").json()
    assert doc == {
        "issuer": "https://auth.example.test",
        "jwks_uri": "https://auth.example.test/.well-known/jwks.json",
        "token_endpoint": "https://auth.example.test/auth/refresh",
        "id_token_signing_alg_values_supported": ["RS256"],
    }


def test_jwks_route_serves_public_keys_with_cache_header(
    wellknown_client: TestClient, issuer_keys: KeySet
) -> None:
    resp = wellknown_client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=300"
    keys = resp.json()["keys"]
    assert [k["kid"] for k in keys] == issuer_keys.kids
    assert all(not (PRIVATE_JWK_MEMBERS & set(k)) for k in keys)
    assert "PRIVATE" not in resp.text


def test_jwks_is_empty_but_valid_without_a_configured_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FND-1: the URL exists before the key does.

    The fleet is configured to trust this issuer BEFORE auth-service can
    sign (compose/Helm `AUTH_ISSUERS_JSON`), so during that rollout the
    honest answer is an empty key set — a valid JWKS every cache accepts.
    A 404 or 503 would make the rollout unverifiable: an operator could
    not tell "not deployed yet" from "wrong URL" without reading logs on
    eight services.
    """
    from auth_service import deps

    deps.install_state(SimpleNamespace(signing_keys=None, token_service=None))  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(wellknown.router)
    client = TestClient(app)

    resp = client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    assert resp.json() == {"keys": []}

    # Discovery still 503s: it describes an issuer, and there is none.
    assert client.get("/.well-known/openid-configuration").status_code == 503


# ── transport ────────────────────────────────────────────────────────────


def _request(headers: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(headers=headers)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ({}, ClientType.WEB),
        ({"X-Client-Type": "macos"}, ClientType.MACOS),
        ({"X-Client-Type": " IOS "}, ClientType.IOS),
        ({"X-Client-Type": "toaster"}, ClientType.WEB),
    ],
)
def test_client_type_header_parsing(header, expected) -> None:  # noqa: ANN001
    from starlette.datastructures import Headers

    assert client_type_of(_request(Headers(header))) is expected  # type: ignore[arg-type]


def test_web_response_omits_refresh_token_native_carries_it() -> None:
    common = {
        "access_token": "at",
        "expires_in": 900,
        "tenant_id": "t",
        "roles": ["member"],
        "refresh_token": "rt",
        "refresh_expires_in": 7776000,
    }
    web = token_response(client_type=ClientType.WEB, **common)
    native = token_response(client_type=ClientType.IOS, **common)
    assert web.refresh_token is None and web.refresh_expires_in is None
    assert "refresh_token" not in web.model_dump(exclude_none=True)
    assert native.refresh_token == "rt" and native.refresh_expires_in == 7776000
    # Superset of the legacy LoginResponse: the old reader's three fields are all there.
    legacy = {"access_token", "expires_in", "token_type"}
    assert legacy <= set(TokenResponse.model_fields)


# ── mode switch ──────────────────────────────────────────────────────────


def _route_paths(app: FastAPI) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def test_keycloak_mode_mounts_no_native_session_routes_and_no_origin_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from auth_service.config import settings
    from auth_service.main import create_app
    from auth_service.middleware.origin_check import OriginCheckMiddleware

    monkeypatch.setattr(settings, "idp_mode", "keycloak")
    app = create_app()
    # FND-1: the JWKS route is mounted in every mode (it answers
    # `{"keys": []}` here). What keycloak mode does NOT get is the native
    # session surface or the origin check.
    assert "/.well-known/jwks.json" in _route_paths(app)
    assert "/auth/login" in _route_paths(app)
    assert all(m.cls is not OriginCheckMiddleware for m in app.user_middleware)


def test_native_mode_mounts_issuer_routes_and_origin_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from auth_service.config import settings
    from auth_service.main import create_app
    from auth_service.middleware.origin_check import OriginCheckMiddleware

    monkeypatch.setattr(settings, "idp_mode", "native")
    app = create_app()
    paths = _route_paths(app)
    assert {"/.well-known/jwks.json", "/.well-known/openid-configuration"} <= paths
    # IDX-M1: the session routes are native now. `login.router` proxies all
    # three to Keycloak, so in this mode it is not mounted at all — and
    # `/auth/login` is what native mode still owes (IDX-A4's password grant).
    assert {"/auth/refresh", "/auth/logout"} <= paths
    assert "/auth/login" not in paths
    assert any(m.cls is OriginCheckMiddleware for m in app.user_middleware)


def test_build_issuer_refuses_native_mode_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from auth_service.config import settings
    from auth_service.main_deps import build_issuer

    monkeypatch.setattr(settings, "idp_mode", "native")
    monkeypatch.setattr(settings, "auth_signing_keys_file", "")
    with pytest.raises(SigningKeyError, match="AUTH_SIGNING_KEYS_JSON"):
        build_issuer()


def test_build_issuer_from_dev_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    from auth_service.config import settings
    from auth_service.main_deps import build_issuer

    dev = Path(__file__).resolve().parents[4] / "infra/dev/auth-signing-dev.json"
    monkeypatch.setattr(settings, "idp_mode", "native")
    monkeypatch.setattr(settings, "auth_signing_keys_file", str(dev))
    monkeypatch.setattr(settings, "auth_issuer_url", "http://localhost:8000")
    keys, svc = build_issuer()
    assert keys is not None and svc is not None
    assert keys.active().kid == "8b5e3d8e2576"
    minted = svc.mint(identity_id=uuid4(), session_id="s", tenant_id=uuid4(), roles=["member"])
    assert Claims(**jwt.get_unverified_claims(minted.token)).iss == "http://localhost:8000"


def test_dev_key_file_is_refused_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from auth_service.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "auth_signing_keys_file", "/etc/mdx/auth-signing.json")
    with pytest.raises(ValueError, match="dev-only"):
        settings.signing_keys_json()
