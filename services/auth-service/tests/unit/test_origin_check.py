"""IDX-A2 F5 — Origin check for browser state changes on /auth."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_service.middleware.origin_check import OriginCheckMiddleware

ALLOWED = ["http://localhost:5173", "https://app.example.test"]


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.add_middleware(OriginCheckMiddleware, allowed_origins=ALLOWED)

    @app.post("/auth/refresh")
    async def refresh() -> dict[str, str]:
        return {"ok": "refresh"}

    @app.get("/auth/me")
    async def me() -> dict[str, str]:
        return {"ok": "me"}

    @app.post("/other")
    async def other() -> dict[str, str]:
        return {"ok": "other"}

    return TestClient(app)


def test_web_post_with_allowed_origin_passes(client: TestClient) -> None:
    assert (
        client.post("/auth/refresh", headers={"Origin": "https://app.example.test"}).status_code
        == 200
    )


def test_web_post_with_foreign_origin_is_403_with_code(client: TestClient) -> None:
    resp = client.post("/auth/refresh", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["code"] == "origin_not_allowed"


def test_web_post_without_any_origin_is_403(client: TestClient) -> None:
    assert client.post("/auth/refresh").status_code == 403


def test_referer_counts_when_origin_is_absent(client: TestClient) -> None:
    assert (
        client.post(
            "/auth/refresh", headers={"Referer": "http://localhost:5173/notes/1"}
        ).status_code
        == 200
    )
    assert (
        client.post("/auth/refresh", headers={"Referer": "https://evil.example/x"}).status_code
        == 403
    )


def test_native_client_without_origin_is_exempt(client: TestClient) -> None:
    assert client.post("/auth/refresh", headers={"X-Client-Type": "macos"}).status_code == 200


def test_native_header_with_a_browser_origin_is_still_checked(client: TestClient) -> None:
    # A page cannot drop its Origin; a forged client-type header alone must not open the door.
    resp = client.post(
        "/auth/refresh", headers={"X-Client-Type": "ios", "Origin": "https://evil.example"}
    )
    assert resp.status_code == 403
    ok = client.post(
        "/auth/refresh", headers={"X-Client-Type": "ios", "Origin": "http://localhost:5173"}
    )
    assert ok.status_code == 200


def test_reads_and_other_prefixes_are_untouched(client: TestClient) -> None:
    assert client.get("/auth/me").status_code == 200
    assert client.post("/other", headers={"Origin": "https://evil.example"}).status_code == 200
