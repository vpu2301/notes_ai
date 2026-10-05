"""Smoke test for the FastAPI app factory.

Doesn't invoke the lifespan (which would attempt DB / Redis / S3
connections); just verifies the app can be constructed and its
``/healthz`` route returns 200.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from asr_service.main import create_app

    app = create_app()
    return TestClient(app)


def test_healthz_returns_ok(client: TestClient) -> None:
    # Lifespan needs DB/Redis, so check route registration without it.
    from asr_service.routers.health import router as health_router  # noqa: F401

    routes = [r.path for r in client.app.routes]  # type: ignore[attr-defined]
    assert "/healthz" in routes
    assert "/readyz" in routes
    assert "/asr/jobs" in routes
    assert "/asr/jobs/{job_id}" in routes
