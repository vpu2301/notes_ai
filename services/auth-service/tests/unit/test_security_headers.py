"""IDX-B3 E/K — response headers, body limits and the CORS contract.

What is asserted here is only what FastAPI can truthfully control. HSTS
and the cookie's `Secure` flag depend on the TLS terminator; asserting
them in-process would prove nothing and hide where they actually live
(`docs/runbooks/idx-secrets.md` and `AUTH_COOKIE_SECURE`).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from auth_service import deps
    from auth_service.main import create_app

    deps.install_state(SimpleNamespace(jwks_cache=object()))  # type: ignore[arg-type]
    return TestClient(create_app())


def test_every_response_refuses_content_sniffing_and_referrers(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_auth_json_is_never_stored(client: TestClient) -> None:
    """These bodies carry tokens, challenge ids, session lists, addresses.

    A shared proxy or a back-button re-serving one is the whole risk.
    """
    response = client.post("/auth/password/policy")
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Pragma") == "no-cache"


def test_the_jwks_document_keeps_its_own_cache_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one `/auth`-adjacent response that SHOULD be cached.

    It is a public key. `setdefault` in the middleware is what preserves
    the router's `public, max-age=300`; a plain assignment would have
    quietly made every service re-fetch it on every token.
    """
    monkeypatch.setenv("TESTING", "true")
    from auth_service import deps
    from auth_service.config import settings
    from auth_service.domain.signing_keys import KeySet
    from auth_service.domain.token_service import TokenService
    from auth_service.main import create_app

    monkeypatch.setattr(settings, "idp_mode", "native")
    from pathlib import Path

    keys = KeySet.from_json(
        (
            Path(__file__).resolve().parents[4] / "infra" / "dev" / "auth-signing-dev.json"
        ).read_text()
    )
    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            jwks_cache=object(),
            signing_keys=keys,
            token_service=TokenService(
                keys=keys, issuer="http://i", audience="mdx-api", access_ttl_seconds=900
            ),
        )
    )
    response = TestClient(create_app()).get("/.well-known/jwks.json")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "public, max-age=300"


def test_a_body_over_the_limit_is_refused_before_it_is_parsed(client: TestClient) -> None:
    oversized = "x" * (17 * 1024)
    response = client.post(
        "/auth/email/start",
        content=f'{{"email": "{oversized}@x.example"}}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "body_too_large"


def test_a_normal_body_passes(client: TestClient) -> None:
    response = client.post(
        "/auth/email/start",
        json={"email": "someone@example.com"},
        headers={"Origin": "http://localhost:5173"},
    )
    # 404 in keycloak mode (the route is native-only) — the point is that
    # it was not refused for size.
    assert response.status_code != 413


def test_cors_allows_the_headers_the_new_clients_send(client: TestClient) -> None:
    """`X-Client-Type` is IDX-A2's; without it in `allow_headers` a browser
    preflight fails and the SPA cannot declare itself."""
    response = client.options(
        "/auth/email/start",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-client-type",
        },
    )
    assert response.status_code in (200, 204)
    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert "x-client-type" in allowed
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_cors_does_not_answer_an_unknown_origin(client: TestClient) -> None:
    response = client.options(
        "/auth/email/start",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_the_allowed_origin_list_is_never_a_wildcard() -> None:
    """`allow_credentials=True` forbids `*`, and the refresh cookie needs it."""
    from auth_service.config import settings

    assert "*" not in settings.cors_origins_list
    assert all(o.startswith("http") for o in settings.cors_origins_list)
