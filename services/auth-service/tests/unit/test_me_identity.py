"""IDX-B3 — `GET /auth/me` carries the identity and its memberships.

Scoped to `_identity_and_memberships`, which is where the decision lives.
The endpoint's other half (the per-tenant `users` row) is unchanged and
already covered; what is new is a lookup that must degrade rather than
fail, because `/auth/me` is what the SPA hydrates from on **every** page
load. A 500 here is a signed-in person looking at a sign-in screen.

Three behaviours, one property each:

  * keycloak mode has no identity store, and that is not an error;
  * the native shape is the one the web client's `MeResponse` declares;
  * a store that raises costs the caller their name, not their session.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from auth_service import deps
from auth_service.domain.identity_repository import Identity, Membership
from auth_service.routers.me import _identity_and_memberships

IDENTITY_ID = UUID("11111111-1111-4111-8111-111111111111")
TENANT_ID = UUID("22222222-2222-4222-8222-222222222222")


def _identity() -> Identity:
    return Identity(
        id=IDENTITY_ID,
        email="olena@acme.example",
        email_verified_at=None,
        display_name="Olena K",
        status="active",
        mfa_enabled=True,
        has_password=False,
        last_tenant_id=TENANT_ID,
        failed_login_count=0,
        lock_count=0,
        locked_until=None,
        lock_notified_at=None,
        deletion_requested_at=None,
    )


class FakeIdentities:
    def __init__(self, *, identity: Identity | None, raises: bool = False) -> None:
        self._identity = identity
        self._raises = raises

    async def get(self, identity_id: UUID) -> Identity | None:
        if self._raises:
            raise ConnectionError("the pool is gone")
        return self._identity if identity_id == IDENTITY_ID else None

    async def list_memberships(self, identity_id: UUID) -> list[Membership]:
        return [
            Membership(
                tenant_id=TENANT_ID,
                name="Olena K",
                kind="personal",
                role="owner",
                status="active",
            )
        ]


@pytest.fixture(autouse=True)
def _restore_state() -> Any:
    """Put `deps._state` back afterwards.

    It is a module global, so a test that installs a two-field stand-in and
    walks away hands the next test in the session an app state with no
    pools on it. Cheap to undo, and the failure it prevents is the kind
    that only appears when the suite is run in a different order.
    """
    previous = deps._state
    yield
    deps._state = previous


def _install(services: Any) -> None:
    deps.install_state(SimpleNamespace(account_services=services))  # type: ignore[arg-type]


def _claims(sub: UUID = IDENTITY_ID) -> Any:
    return SimpleNamespace(sub=sub, tid=TENANT_ID)


@pytest.mark.asyncio
async def test_keycloak_mode_has_no_identity_and_says_so_quietly() -> None:
    # `account_services` is None whenever the native surface is not wired,
    # which is every keycloak-mode deployment. 200 with nulls, not a 404:
    # the claims in the token are still enough to render a signed-in shell.
    _install(None)

    identity, memberships = await _identity_and_memberships(_claims())

    assert identity is None
    assert memberships == []


@pytest.mark.asyncio
async def test_native_mode_returns_the_shape_the_web_client_declares() -> None:
    _install(SimpleNamespace(identities=FakeIdentities(identity=_identity())))

    identity, memberships = await _identity_and_memberships(_claims())

    # Every key `web/src/api/types.ts::Identity` names, and no extra: the
    # SPA reads this on page load and `AuthResult` on sign-in, and the two
    # have to be the same object or the UI changes shape under people.
    assert identity == {
        "id": str(IDENTITY_ID),
        "email": "olena@acme.example",
        "display_name": "Olena K",
        "mfa_enabled": True,
        "has_password": False,
        "status": "active",
    }
    # `kind` is what tells a personal workspace from a team one — the whole
    # signup acceptance criterion (`memberships[0].kind == "personal"`)
    # rests on it surviving this mapping.
    assert memberships == [
        {
            "tenant_id": str(TENANT_ID),
            "name": "Olena K",
            "kind": "personal",
            "role": "owner",
            "status": "active",
        }
    ]


@pytest.mark.asyncio
async def test_an_identity_row_that_vanished_is_not_a_crash() -> None:
    # A token whose subject no longer has a row: revoked between issue and
    # use, or a Keycloak-era `sub` on a native deployment.
    _install(SimpleNamespace(identities=FakeIdentities(identity=None)))

    identity, memberships = await _identity_and_memberships(_claims(uuid4()))

    assert identity is None
    assert memberships == []


@pytest.mark.asyncio
async def test_a_broken_identity_store_costs_a_name_not_a_session() -> None:
    _install(SimpleNamespace(identities=FakeIdentities(identity=_identity(), raises=True)))

    # The alternative — letting it propagate — turns a database blip into
    # every signed-in browser bouncing to /login, because the SPA treats a
    # failed `/auth/me` as "the session is gone".
    identity, memberships = await _identity_and_memberships(_claims())

    assert identity is None
    assert memberships == []
