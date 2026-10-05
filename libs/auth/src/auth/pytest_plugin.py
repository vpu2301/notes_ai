"""Pytest fixtures for authenticating against a service in-process (``pytest_plugins = ["auth.pytest_plugin"]``).

Tokens are really RS256-signed and verified by the service's own ``current_user``; nothing is stubbed past the verifier.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest

from .testing import TestIssuer, auth_headers, install_test_issuer, shared_issuer


@pytest.fixture(scope="session")
def test_issuer() -> TestIssuer:
    """The process-wide RS256 issuer. One key for the whole session."""
    return shared_issuer()


@pytest.fixture
def auth_headers_factory() -> Callable[..., dict[str, str]]:
    """``auth_headers_factory(sub=…, tid=…, roles=[…])`` → request headers."""
    return auth_headers


@pytest.fixture
def auth_client_factory(test_issuer: TestIssuer) -> Callable[..., Any]:
    """Yield an ``AsyncClient`` speaking to ``app`` as an authenticated caller (``state`` defaults to ``app.state.svc``)."""
    import httpx

    @asynccontextmanager
    async def _factory(
        app: Any,
        *,
        sub: UUID | None = None,
        tid: UUID | None = None,
        roles: list[str] | None = None,
        state: Any = None,
        issuer: str | None = None,
        audience: str | None = None,
        base_url: str = "http://test",
        **claim_overrides: Any,
    ) -> AsyncIterator[Any]:
        target = state if state is not None else getattr(app.state, "svc", None)
        if target is None:
            raise RuntimeError(
                "cannot find the service state to install the test issuer on; "
                "pass state=… explicitly"
            )
        # `issuer`/`audience` are what the service's own `current_user` demands.
        install_test_issuer(target, issuer=issuer)
        if issuer is not None:
            claim_overrides.setdefault("iss", issuer)
        if audience is not None:
            claim_overrides.setdefault("aud", audience)
            claim_overrides.setdefault("azp", audience)
        headers = auth_headers(
            sub=sub or uuid4(),
            tid=tid or uuid4(),
            roles=roles or ["member"],
            **claim_overrides,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=base_url, headers=headers
        ) as client:
            yield client

    return _factory
