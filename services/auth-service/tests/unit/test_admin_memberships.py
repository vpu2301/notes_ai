"""W1: in dual/native mode `/admin/users/*` acts on memberships, and invite answers 410."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from auth_service import deps
from auth_service.routers import admin

TENANT = UUID("00000000-0000-0000-0000-00000000000a")
ADMIN = uuid4()


@pytest.fixture
def state(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(admin.settings, "idp_mode", "dual")
    seen: dict[str, Any] = {"members": {}, "audit": []}

    async def _write_event(**kw: Any) -> None:
        seen["audit"].append(kw)

    previous = deps._state
    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            tenant_writer_pool=object(), audit_writer=SimpleNamespace(write_event=_write_event)
        )
    )

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: Any):  # noqa: ANN202
        yield SimpleNamespace()

    async def _get_membership(conn: Any, *, tenant_id: UUID, user_sub: UUID) -> Any:
        return seen["members"].get(user_sub)

    async def _count_owners(conn: Any, *, tenant_id: UUID, exclude_sub: UUID | None = None) -> int:
        return sum(
            1
            for sub, m in seen["members"].items()
            if m["role"] == "owner" and m["status"] == "active" and sub != exclude_sub
        )

    async def _update_role(conn: Any, *, tenant_id: UUID, user_sub: UUID, role: str) -> Any:
        seen["members"][user_sub]["role"] = role

    monkeypatch.setattr(admin, "tenant_connection", _conn)
    monkeypatch.setattr(admin.tenants_repo, "get_membership", _get_membership)
    monkeypatch.setattr(admin.tenants_repo, "count_active_owners", _count_owners)
    monkeypatch.setattr(admin.tenants_repo, "update_member_role", _update_role)
    yield seen
    deps._state = previous


def _claims() -> Any:
    return SimpleNamespace(sub=ADMIN, tid=TENANT, roles=["tenant_admin"])


def _member(sub: UUID, role: str) -> dict[str, Any]:
    return {"user_sub": sub, "role": role, "status": "active"}


async def test_invite_is_gone_in_dual_mode(state: dict[str, Any]) -> None:
    body = admin.InviteRequest(email="a@b.example", display_name="A", role="member")
    with pytest.raises(HTTPException) as exc:
        await admin.invite_user(body, _claims())
    assert exc.value.status_code == 410
    assert exc.value.problem_extras["code"] == "use_invitations"  # type: ignore[attr-defined]


async def test_roles_map_to_the_membership_role(state: dict[str, Any]) -> None:
    sub = uuid4()
    state["members"][sub] = _member(sub, "member")

    out = await admin._set_membership_role(sub, {"viewer"}, _claims())

    assert state["members"][sub]["role"] == "viewer"
    assert out.roles == ["viewer"]


async def test_an_owner_asked_for_tenant_admin_stays_owner(state: dict[str, Any]) -> None:
    sub = uuid4()
    state["members"][sub] = _member(sub, "owner")

    await admin._set_membership_role(sub, {"tenant_admin", "member"}, _claims())

    assert state["members"][sub]["role"] == "owner"


async def test_the_last_owner_cannot_be_demoted(state: dict[str, Any]) -> None:
    sub = uuid4()
    state["members"][sub] = _member(sub, "owner")

    with pytest.raises(HTTPException) as exc:
        await admin._set_membership_role(sub, {"member"}, _claims())
    assert exc.value.status_code == 409


async def test_a_non_member_is_404(state: dict[str, Any]) -> None:
    with pytest.raises(HTTPException) as exc:
        await admin._set_membership_role(uuid4(), {"member"}, _claims())
    assert exc.value.status_code == 404


def test_guest_maps_to_a_guest_token_without_asr() -> None:
    from auth.perms import can
    from auth_service.domain.identity_repository import platform_roles_for, primary_role

    assert platform_roles_for("guest") == ["guest"]
    assert primary_role({"guest"}) == "guest"
    # W3: notes only (narrowed to its grants by note-service); never transcripts directly.
    assert not can("guest", "asr.read", "asr_job")
