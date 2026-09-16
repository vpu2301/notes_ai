"""Pytest fixtures for authenticating against a service in-process (IDX-B2 F4).

Enable in a service's ``conftest.py``::

    pytest_plugins = ["auth.pytest_plugin"]

Then::

    async def test_reads_a_note(auth_client_factory, app):
        async with auth_client_factory(app, roles=["member"]) as client:
            assert (await client.get("/v1/notes")).status_code == 200

This replaces the fixtures that logged in through a running Keycloak. Two
things that bought us, and are kept: a real signature (the token is
RS256-signed and verified by the service's own ``current_user``, not
stubbed past it), and a real ``Claims`` round-trip. Two things it cost,
and are now gone: a container in the loop, and a suite that could only
run where the dev stack was up.

What it deliberately does NOT do is override ``current_user`` with a
lambda. That style of fixture passes even when the verifier is broken —
a wrong audience, an expired token, a forbidden claim all sail through —
which is precisely the class of bug an auth test exists to catch.
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
    """Yield an ``AsyncClient`` that speaks to ``app`` as an authenticated caller.

    ``state`` is resolved from ``app.state.svc`` when present — every
    service in this fleet keeps its singletons there — but can be passed
    explicitly for one that does not.
    """
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
        # `issuer`/`audience` are what the service's own `current_user`
        # demands — pass its `settings.auth_issuer` / `auth_audience`.
        # Defaulting to the harness's values keeps the simple case simple.
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
