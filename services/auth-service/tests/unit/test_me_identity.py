"""`GET /auth/me` carries the identity and its memberships (`_identity_and_memberships`).

The lookup must degrade, not fail: keycloak mode has no identity store; the native shape
matches the web client's `MeResponse`; a raising store costs the caller their name, not their session.
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
    """Put the module-global `deps._state` back so later tests keep their pools."""
    previous = deps._state
    yield
    deps._state = previous


def _install(services: Any) -> None:
    deps.install_state(SimpleNamespace(account_services=services))  # type: ignore[arg-type]


def _claims(sub: UUID = IDENTITY_ID) -> Any:
    return SimpleNamespace(sub=sub, tid=TENANT_ID)


@pytest.mark.asyncio
async def test_keycloak_mode_has_no_identity_and_says_so_quietly() -> None:
    # `account_services` is None in keycloak mode: 200 with nulls, not a 404.
    _install(None)

    identity, memberships = await _identity_and_memberships(_claims())

    assert identity is None
    assert memberships == []


@pytest.mark.asyncio
async def test_native_mode_returns_the_shape_the_web_client_declares() -> None:
    _install(SimpleNamespace(identities=FakeIdentities(identity=_identity())))

    identity, memberships = await _identity_and_memberships(_claims())

    # Every key `web/src/api/types.ts::Identity` names, and no extra.
    assert identity == {
        "id": str(IDENTITY_ID),
        "email": "olena@acme.example",
        "display_name": "Olena K",
        "mfa_enabled": True,
        "has_password": False,
        "status": "active",
        "created_at": None,
    }
    # `kind` tells a personal workspace from a team one; the signup criterion rests on it.
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
    # Subject with no row: revoked between issue and use, or a Keycloak-era `sub`.
    _install(SimpleNamespace(identities=FakeIdentities(identity=None)))

    identity, memberships = await _identity_and_memberships(_claims(uuid4()))

    assert identity is None
    assert memberships == []


@pytest.mark.asyncio
async def test_a_broken_identity_store_costs_a_name_not_a_session() -> None:
    _install(SimpleNamespace(identities=FakeIdentities(identity=_identity(), raises=True)))

    # Propagating would bounce every signed-in browser to /login on a database blip.
    identity, memberships = await _identity_and_memberships(_claims())

    assert identity is None
    assert memberships == []


# ── W1: `db_user` derived from the active membership in dual/native mode ──


TEAM_ID = UUID("33333333-3333-4333-8333-333333333333")


class TwoWorkspaces(FakeIdentities):
    async def list_memberships(self, identity_id: UUID) -> list[Membership]:
        return [
            Membership(
                tenant_id=TENANT_ID, name="Olena K", kind="personal", role="owner", status="active"
            ),
            Membership(
                tenant_id=TEAM_ID, name="Acme Inc", kind="team", role="viewer", status="active"
            ),
        ]


def _request() -> Any:
    from starlette.requests import Request

    return Request({"type": "http", "headers": [(b"x-client-type", b"macos")]})


@pytest.fixture
def _no_reminders(monkeypatch: pytest.MonkeyPatch) -> None:
    import contextlib

    from auth_service.routers import me as me_mod

    class _Conn:
        async def fetchrow(self, *_: Any) -> None:
            return None

    @contextlib.asynccontextmanager
    async def _fake_conn(pool: Any, tenant_id: Any):  # noqa: ANN202
        yield _Conn()

    monkeypatch.setattr(me_mod, "tenant_connection", _fake_conn)


@pytest.mark.asyncio
async def test_me_outside_the_home_tenant_derives_db_user(
    monkeypatch: pytest.MonkeyPatch, _no_reminders: None
) -> None:
    from auth_service.routers import me as me_mod

    monkeypatch.setattr(me_mod.settings, "idp_mode", "dual")
    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            account_services=SimpleNamespace(identities=TwoWorkspaces(identity=_identity())),
            app_pool=object(),
        )
    )
    claims = SimpleNamespace(
        sub=IDENTITY_ID, tid=TEAM_ID, roles=["viewer"], scope="", mfa=False, iss="native"
    )

    body = await me_mod.me(_request(), claims)  # type: ignore[arg-type]

    assert body["db_user"]["tenant_id"] == str(TEAM_ID)
    assert body["db_user"]["role"] == "viewer"
    assert body["db_user"]["email"] == "olena@acme.example"
    assert body["active_membership"] == {
        "tenant_id": str(TEAM_ID),
        "name": "Acme Inc",
        "kind": "team",
        "role": "viewer",
        "status": "active",
    }
    assert body["personal_tenant_id"] == str(TENANT_ID)


@pytest.mark.asyncio
async def test_keycloak_mode_keeps_the_users_row_path(
    monkeypatch: pytest.MonkeyPatch, _no_reminders: None
) -> None:
    from auth_service.routers import me as me_mod

    monkeypatch.setattr(me_mod.settings, "idp_mode", "keycloak")
    deps.install_state(SimpleNamespace(account_services=None, app_pool=object()))  # type: ignore[arg-type]
    claims = SimpleNamespace(
        sub=IDENTITY_ID, tid=TEAM_ID, roles=["member"], scope="", mfa=False, iss="kc"
    )

    body = await me_mod.me(_request(), claims)  # type: ignore[arg-type]

    # No `users` row in this tenant → null, exactly as before W1.
    assert body["db_user"] is None
    assert body["active_membership"] is None
