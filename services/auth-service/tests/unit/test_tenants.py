"""Tenant management surface with ``tenant_connection`` + repo functions stubbed.

Covers create/update + audit + owner bootstrap, role-based access, isolation, active-tenant
scoping, membership creation, the last-owner guard and unauthorized access.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims

TENANT_A = UUID("00000000-0000-0000-0000-00000000000a")
TENANT_B = UUID("00000000-0000-0000-0000-00000000000b")
ADMIN_SUB = UUID("0a000000-0000-0000-0000-00000000000a")
NOW = datetime(2026, 6, 1, tzinfo=UTC)


def _claims(*, roles: list[str], tid: UUID = TENANT_A, sub: UUID = ADMIN_SUB) -> Claims:
    return Claims(
        sub=sub,
        tid=tid,
        roles=roles,
        scope="",
        mfa=False,
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _tenant_row(tenant_id: UUID = TENANT_A, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": tenant_id,
        "name": "tenant-a",
        "display_name": "Dev Hospital A",
        "legal_name": "Dev Hospital A LLC",
        "slug": "tenant-a",
        "locale": "uk",
        "timezone": "Europe/Kyiv",
        "status": "active",
        "is_active": True,
        "logo_url": "",
        "logo_content_type": "",
        "contact_email": "contact@tenant-a.example",
        "phone_number": "",
        "website": "",
        "address_line1": "",
        "address_line2": "",
        "postal_code": "",
        "city": "Kyiv",
        "state_or_region": "",
        "country": "Ukraine",
        "tax_id": "",
        "registration_number": "",
        "created_at": NOW,
        "updated_at": NOW,
        "kind": "team",
    }
    base.update(over)
    return base


def _membership_row(role: str = "owner", tenant_id: UUID = TENANT_A) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "user_sub": ADMIN_SUB,
        "role": role,
        "status": "active",
        "invited_by": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):
    """TestClient whose current_user resolves to the given claims; repo functions patched per-test."""
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from auth_service import deps
    from auth_service.main import create_app
    from auth_service.routers import tenants

    audit_calls: list[dict] = []

    async def _write_event(**kwargs: Any) -> None:
        audit_calls.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            tenant_writer_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
        )
    )

    @contextlib.asynccontextmanager
    async def _fake_conn(pool: Any, tenant_id: Any):
        yield SimpleNamespace()

    monkeypatch.setattr(tenants, "tenant_connection", _fake_conn)
    # requires_mfa() reads settings.require_mfa (off by default) — leave as-is.

    def _build(claims: Claims) -> TestClient:
        app = create_app()
        app.dependency_overrides[deps.current_user] = lambda: claims
        c = TestClient(app)
        c.audit_calls = audit_calls  # type: ignore[attr-defined]
        return c

    return _build


# ── Create ───────────────────────────────────────────────────────────────


def test_create_tenant_happy_path(make_client, monkeypatch: pytest.MonkeyPatch) -> None:
    from auth_service.routers import tenants

    created: dict[str, Any] = {}

    async def _create_tenant(conn, **kw):  # noqa: ANN001
        created.update(kw)
        return _tenant_row(uuid4(), name=kw["name"], slug=kw["slug"])

    async def _add_member(conn, **kw):  # noqa: ANN001
        created["owner_sub"] = kw["user_sub"]
        return _membership_row(kw["role"])

    monkeypatch.setattr(tenants.repo, "create_tenant", _create_tenant)
    monkeypatch.setattr(tenants.repo, "add_member", _add_member)

    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.post("/tenants", json={"name": "acme-inc", "display_name": "Acme Inc"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "acme-inc"
    assert body["my_role"] == "owner"
    # Creator was made the founding owner.
    assert created["owner_sub"] == str(ADMIN_SUB) or created["owner_sub"] == ADMIN_SUB
    kinds = [c["kind"] for c in client.audit_calls]  # type: ignore[attr-defined]
    assert "tenant.created" in kinds


def test_create_tenant_forbidden_for_member(make_client) -> None:
    client = make_client(_claims(roles=["member"]))
    resp = client.post("/tenants", json={"name": "x-corp", "display_name": "X"})
    assert resp.status_code == 403


def test_create_tenant_rejects_bad_slug(make_client) -> None:
    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.post(
        "/tenants",
        json={"name": "ok-name", "display_name": "Ok", "slug": "Bad Slug!"},
    )
    assert resp.status_code == 422


# ── Update ───────────────────────────────────────────────────────────────


def test_update_tenant_happy_path(make_client, monkeypatch: pytest.MonkeyPatch) -> None:
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("owner")

    async def _update_tenant(conn, *, tenant_id, fields):  # noqa: ANN001
        return _tenant_row(tenant_id, **{k: v for k, v in fields.items() if k in _tenant_row()})

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "update_tenant", _update_tenant)

    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.patch(f"/tenants/{TENANT_A}", json={"city": "Lviv", "phone_number": "+380"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["city"] == "Lviv"
    assert "tenant.updated" in [c["kind"] for c in client.audit_calls]  # type: ignore[attr-defined]


def test_update_tenant_denied_for_non_active_tenant(make_client, monkeypatch) -> None:
    """A write against a tenant that is not the caller's active tenant → 403."""
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("owner", tenant_id=TENANT_B)

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)

    client = make_client(_claims(roles=["tenant_admin"], tid=TENANT_A))
    resp = client.patch(f"/tenants/{TENANT_B}", json={"city": "Lviv"})
    assert resp.status_code == 403


def test_update_tenant_denied_for_viewer_membership(make_client, monkeypatch) -> None:
    """tenant_admin JWT but only a 'doctor' (non-manager) membership → 403."""
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("doctor")

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)

    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.patch(f"/tenants/{TENANT_A}", json={"city": "Lviv"})
    assert resp.status_code == 403


def test_update_tenant_forbidden_for_viewer_role(make_client) -> None:
    client = make_client(_claims(roles=["viewer"]))
    resp = client.patch(f"/tenants/{TENANT_A}", json={"city": "Lviv"})
    assert resp.status_code == 403


# ── Isolation / read ─────────────────────────────────────────────────────


def test_get_tenant_not_a_member_is_404(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return None  # caller has no membership in TENANT_B

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)

    client = make_client(_claims(roles=["tenant_admin"], tid=TENANT_A))
    resp = client.get(f"/tenants/{TENANT_B}")
    assert resp.status_code == 404


def test_get_tenant_member_ok(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("admin")

    async def _get_tenant(conn, *, tenant_id):  # noqa: ANN001
        return _tenant_row(tenant_id)

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "get_tenant", _get_tenant)

    client = make_client(_claims(roles=["member"]))
    resp = client.get(f"/tenants/{TENANT_A}")
    assert resp.status_code == 200
    assert resp.json()["my_role"] == "admin"


def test_list_tenants_returns_memberships(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    async def _list_for_user(conn, *, user_sub):  # noqa: ANN001
        return [
            {**_tenant_row(TENANT_A), "membership_role": "owner", "membership_status": "active"},
            {
                **_tenant_row(TENANT_B, name="tenant-b", slug="tenant-b"),
                "membership_role": "admin",
                "membership_status": "active",
            },
        ]

    monkeypatch.setattr(tenants.repo, "list_tenants_for_user", _list_for_user)

    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.get("/tenants")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert {i["my_role"] for i in items} == {"owner", "admin"}


# ── Members ──────────────────────────────────────────────────────────────


def test_add_member_validates_role(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("owner")

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)

    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.post(
        f"/tenants/{TENANT_A}/members",
        json={"user_sub": str(uuid4()), "role": "superuser"},
    )
    assert resp.status_code == 422


def test_add_member_happy_path(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    new_sub = uuid4()

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("owner")

    async def _add_member(conn, **kw):  # noqa: ANN001
        return _membership_row(kw["role"])

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "add_member", _add_member)

    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.post(
        f"/tenants/{TENANT_A}/members", json={"user_sub": str(new_sub), "role": "viewer"}
    )
    assert resp.status_code == 201, resp.text
    assert "tenant.member_added" in [c["kind"] for c in client.audit_calls]  # type: ignore[attr-defined]


def test_add_member_forbidden_for_member(make_client) -> None:
    client = make_client(_claims(roles=["member"]))
    resp = client.post(
        f"/tenants/{TENANT_A}/members", json={"user_sub": str(uuid4()), "role": "viewer"}
    )
    assert resp.status_code == 403


def test_demote_last_owner_blocked(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    target = uuid4()

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        # caller is owner; target is the (only) owner being demoted
        return _membership_row("owner")

    async def _count_active_owners(conn, *, tenant_id, exclude_sub=None):  # noqa: ANN001
        return 0  # no other owners remain

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "count_active_owners", _count_active_owners)

    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.patch(f"/tenants/{TENANT_A}/members/{target}", json={"role": "admin"})
    assert resp.status_code == 409


def test_remove_last_owner_blocked(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    target = uuid4()

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("owner")

    async def _count_active_owners(conn, *, tenant_id, exclude_sub=None):  # noqa: ANN001
        return 0

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "count_active_owners", _count_active_owners)

    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.delete(f"/tenants/{TENANT_A}/members/{target}")
    assert resp.status_code == 409


# ── Switch ───────────────────────────────────────────────────────────────


def test_switch_requires_membership(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return None

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    client = make_client(_claims(roles=["member"], tid=TENANT_A))
    resp = client.post(f"/tenants/{TENANT_B}/switch")
    assert resp.status_code == 404


def test_switch_member_ok(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("admin", tenant_id=TENANT_B)

    async def _get_tenant(conn, *, tenant_id):  # noqa: ANN001
        return _tenant_row(tenant_id, name="tenant-b")

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "get_tenant", _get_tenant)

    client = make_client(_claims(roles=["member"], tid=TENANT_A))
    resp = client.post(f"/tenants/{TENANT_B}/switch")
    assert resp.status_code == 200
    assert resp.json()["active_tenant"]["my_role"] == "admin"
    assert "tenant.switched" in [c["kind"] for c in client.audit_calls]  # type: ignore[attr-defined]


# ── W1: Personal is a kind; rosters read identities ──────────────────────


def test_list_tenants_carries_kind(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    async def _list_for_user(conn, *, user_sub):  # noqa: ANN001
        return [
            {
                **_tenant_row(TENANT_B, name="olena-k", kind="personal"),
                "membership_role": "owner",
                "membership_status": "active",
            },
            {**_tenant_row(TENANT_A), "membership_role": "member", "membership_status": "active"},
        ]

    monkeypatch.setattr(tenants.repo, "list_tenants_for_user", _list_for_user)

    resp = make_client(_claims(roles=["member"])).get("/tenants")
    assert resp.status_code == 200
    assert [i["kind"] for i in resp.json()["items"]] == ["personal", "team"]


def _patch_personal(monkeypatch) -> None:  # noqa: ANN001
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("owner")

    async def _get_tenant(conn, *, tenant_id):  # noqa: ANN001
        return _tenant_row(tenant_id, kind="personal")

    async def _update_tenant(conn, *, tenant_id, fields):  # noqa: ANN001
        return _tenant_row(tenant_id, kind="personal", **fields)

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "get_tenant", _get_tenant)
    monkeypatch.setattr(tenants.repo, "update_tenant", _update_tenant)


def test_personal_workspace_status_change_is_refused(make_client, monkeypatch) -> None:
    _patch_personal(monkeypatch)
    client = make_client(_claims(roles=["tenant_admin"]))

    resp = client.patch(f"/tenants/{TENANT_A}", json={"is_active": False})

    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "personal_workspace"


def test_personal_workspace_can_be_renamed(make_client, monkeypatch) -> None:
    _patch_personal(monkeypatch)
    client = make_client(_claims(roles=["tenant_admin"]))

    resp = client.patch(f"/tenants/{TENANT_A}", json={"display_name": "Home"})

    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Home"


def test_list_members_profile_from_identity_and_platform_role_computed(
    make_client, monkeypatch
) -> None:
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("owner")

    async def _list_members(conn, *, tenant_id):  # noqa: ANN001
        # A member whose home tenant is elsewhere: the profile still comes from `identities`.
        return [
            {**_membership_row("admin"), "email": "anna@globex.example", "display_name": "Anna"},
            {**_membership_row("guest"), "email": "g@out.example", "display_name": "G"},
        ]

    async def _seat_meter(conn, *, tenant_id):  # noqa: ANN001
        return 2, 3

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "list_members", _list_members)
    monkeypatch.setattr(tenants.repo, "seat_meter", _seat_meter)

    resp = make_client(_claims(roles=["tenant_admin"])).get(f"/tenants/{TENANT_A}/members")

    assert resp.status_code == 200, resp.text
    assert resp.json()["seat_meter"] == {"active": 2, "limit": 3}
    items = resp.json()["items"]
    assert items[0]["email"] == "anna@globex.example"
    assert [i["platform_role"] for i in items] == ["tenant_admin", "guest"]


def test_add_member_by_email_is_scoped_to_this_workspace(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    seen: dict[str, Any] = {}

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row("owner")

    async def _resolve(conn, *, tenant_id, email):  # noqa: ANN001
        seen["tenant_id"] = tenant_id
        return None  # no membership here → no probe across the platform

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "resolve_sub_by_email", _resolve)

    resp = make_client(_claims(roles=["tenant_admin"])).post(
        f"/tenants/{TENANT_A}/members", json={"email": "someone@else.example", "role": "member"}
    )

    assert resp.status_code == 404
    assert seen["tenant_id"] == TENANT_A


# ── W2: self-serve create, leave, dissolve ───────────────────────────────


def test_short_create_is_a_free_self_serve_team_for_anyone(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    seen: dict[str, Any] = {}

    async def _create_tenant(conn, **kw):  # noqa: ANN001
        seen.update(kw)
        return _tenant_row(uuid4(), name=kw["name"], display_name=kw["display_name"])

    async def _add_member(conn, **kw):  # noqa: ANN001
        seen["role"] = kw["role"]
        return _membership_row(kw["role"])

    monkeypatch.setattr(tenants.repo, "create_tenant", _create_tenant)
    monkeypatch.setattr(tenants.repo, "add_member", _add_member)

    # A plain member (no tenant.create) may still make their own workspace.
    resp = make_client(_claims(roles=["member"])).post("/tenants", json={"name": "Sunrise Studio"})

    assert resp.status_code == 201, resp.text
    assert seen["plan"] == "free" and seen["signup_source"] == "self_serve"
    assert seen["display_name"] == "Sunrise Studio"
    # `tenants.name` is UNIQUE: the short form always suffixes.
    assert seen["name"].startswith("sunrise-studio-") and seen["name"] != "sunrise-studio"
    assert seen["role"] == "owner"


def test_long_create_still_needs_tenant_create(make_client) -> None:
    resp = make_client(_claims(roles=["member"])).post(
        "/tenants", json={"name": "acme-two", "display_name": "Acme Two"}
    )
    assert resp.status_code == 403


def _patch_member(
    monkeypatch,
    role: str,
    *,
    owners: int = 0,
    others: int = 0,
    kind: str = "team",
    tenant_status: str = "active",
):  # noqa: ANN001, ANN202
    from auth_service.routers import tenants

    calls: dict[str, Any] = {}

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row(role)

    async def _get_tenant(conn, *, tenant_id):  # noqa: ANN001
        return _tenant_row(
            tenant_id, kind=kind, status=tenant_status, is_active=tenant_status == "active"
        )

    async def _count_owners(conn, *, tenant_id, exclude_sub=None):  # noqa: ANN001
        return owners

    async def _count_others(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return others

    async def _leave(conn, *, tenant_id, user_sub):  # noqa: ANN001
        calls["left"] = True
        return True

    async def _dissolve(conn, *, tenant_id):  # noqa: ANN001
        calls["dissolved"] = True

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "get_tenant", _get_tenant)
    monkeypatch.setattr(tenants.repo, "count_active_owners", _count_owners)
    monkeypatch.setattr(tenants.repo, "count_other_active_members", _count_others)
    monkeypatch.setattr(tenants.repo, "leave", _leave)

    async def _archive(conn, *, tenant_id):  # noqa: ANN001
        calls["archived"] = True

    async def _unarchive(conn, *, tenant_id):  # noqa: ANN001
        calls["unarchived"] = True

    monkeypatch.setattr(tenants.repo, "dissolve", _dissolve)
    monkeypatch.setattr(tenants.repo, "archive", _archive)
    monkeypatch.setattr(tenants.repo, "unarchive", _unarchive)
    return calls


def test_the_last_owner_cannot_leave(make_client, monkeypatch) -> None:
    calls = _patch_member(monkeypatch, "owner", owners=0)
    resp = make_client(_claims(roles=["tenant_admin"])).delete(f"/tenants/{TENANT_A}/members/me")
    assert resp.status_code == 409 and resp.json()["code"] == "last_owner"
    assert "left" not in calls


def test_a_member_leaves(make_client, monkeypatch) -> None:
    calls = _patch_member(monkeypatch, "member")
    client = make_client(_claims(roles=["member"]))
    resp = client.delete(f"/tenants/{TENANT_A}/members/me")
    assert resp.status_code == 200, resp.text
    assert calls["left"]
    assert "tenant.member_left" in [c["kind"] for c in client.audit_calls]  # type: ignore[attr-defined]


def test_dissolve_refusals(make_client, monkeypatch) -> None:
    _patch_member(monkeypatch, "owner", others=1)
    client = make_client(_claims(roles=["tenant_admin"]))
    url = f"/tenants/{TENANT_A}/dissolve"
    assert client.post(url, json={"confirm_name": "nope"}).json()["code"] == "confirm_name_mismatch"
    assert (
        client.post(url, json={"confirm_name": "Dev Hospital A"}).json()["code"]
        == "has_other_members"
    )

    _patch_member(monkeypatch, "owner", kind="personal")
    resp = client.post(url, json={"confirm_name": "Dev Hospital A"})
    assert resp.json()["code"] == "personal_workspace"

    _patch_member(monkeypatch, "admin")
    assert client.post(url, json={"confirm_name": "Dev Hospital A"}).json()["code"] == "owner_only"


def test_dissolve_an_empty_team_workspace(make_client, monkeypatch) -> None:
    calls = _patch_member(monkeypatch, "owner")
    client = make_client(_claims(roles=["tenant_admin"]))
    # The display name or the technical name, any case.
    resp = client.post(f"/tenants/{TENANT_A}/dissolve", json={"confirm_name": "dev hospital a"})
    assert resp.status_code == 202, resp.text
    assert resp.json()["status"] == "dissolved" and calls["dissolved"]


def test_archive_keeps_members_and_needs_no_name(make_client, monkeypatch) -> None:
    # Unlike dissolve, other members do not block it.
    calls = _patch_member(monkeypatch, "owner", others=3)
    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.post(f"/tenants/{TENANT_A}/archive")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "archived" and calls["archived"]
    assert "tenant.archived" in [c["kind"] for c in client.audit_calls]  # type: ignore[attr-defined]


def test_archive_refusals(make_client, monkeypatch) -> None:
    client = make_client(_claims(roles=["tenant_admin"]))
    url = f"/tenants/{TENANT_A}/archive"
    _patch_member(monkeypatch, "admin")
    assert client.post(url).json()["code"] == "owner_only"
    _patch_member(monkeypatch, "owner", kind="personal")
    assert client.post(url).json()["code"] == "personal_workspace"
    _patch_member(monkeypatch, "owner", tenant_status="archived")
    assert client.post(url).json()["code"] == "not_active"


def test_unarchive_restores_an_archived_workspace(make_client, monkeypatch) -> None:
    client = make_client(_claims(roles=["tenant_admin"]))
    url = f"/tenants/{TENANT_A}/unarchive"
    _patch_member(monkeypatch, "owner")
    assert client.post(url).json()["code"] == "not_archived"
    _patch_member(monkeypatch, "member", tenant_status="archived")
    assert client.post(url).json()["code"] == "owner_only"
    calls = _patch_member(monkeypatch, "owner", tenant_status="archived")
    resp = client.post(url)
    assert resp.status_code == 200, resp.text
    assert calls["unarchived"]
    assert "tenant.unarchived" in [c["kind"] for c in client.audit_calls]  # type: ignore[attr-defined]


def test_add_member_by_email_says_use_invitations_in_dual(make_client, monkeypatch) -> None:
    from auth_service.routers import tenants

    _patch_member(monkeypatch, "owner")
    monkeypatch.setattr(tenants.settings, "idp_mode", "dual")

    async def _step_up() -> None:
        return None

    client = make_client(_claims(roles=["tenant_admin"]))
    client.app.dependency_overrides[tenants.manage_step_up] = _step_up  # type: ignore[attr-defined]
    resp = client.post(
        f"/tenants/{TENANT_A}/members", json={"email": "tom@client.com", "role": "member"}
    )
    assert resp.status_code == 409 and resp.json()["code"] == "use_invitations"


def _roles_by_sub(monkeypatch, caller_role: str, target_role: str, owners: int):  # noqa: ANN001, ANN202
    from auth_service.routers import tenants

    async def _get_membership(conn, *, tenant_id, user_sub):  # noqa: ANN001
        return _membership_row(caller_role if user_sub == ADMIN_SUB else target_role)

    async def _count_owners(conn, *, tenant_id, exclude_sub=None):  # noqa: ANN001
        return owners

    monkeypatch.setattr(tenants.repo, "get_membership", _get_membership)
    monkeypatch.setattr(tenants.repo, "count_active_owners", _count_owners)


def test_an_admin_cannot_change_or_remove_an_owner(make_client, monkeypatch) -> None:
    _roles_by_sub(monkeypatch, "admin", "owner", owners=2)
    client = make_client(_claims(roles=["tenant_admin"]))
    other = uuid4()
    patched = client.patch(f"/tenants/{TENANT_A}/members/{other}", json={"role": "member"})
    removed = client.delete(f"/tenants/{TENANT_A}/members/{other}")
    assert patched.status_code == removed.status_code == 403
    assert patched.json()["code"] == removed.json()["code"] == "owner_only"


def test_an_admin_cannot_make_an_owner(make_client, monkeypatch) -> None:
    _roles_by_sub(monkeypatch, "admin", "member", owners=1)
    resp = make_client(_claims(roles=["tenant_admin"])).patch(
        f"/tenants/{TENANT_A}/members/{uuid4()}", json={"role": "owner"}
    )
    assert resp.status_code == 403 and resp.json()["code"] == "owner_only"


def test_the_last_owner_refusal_has_a_code(make_client, monkeypatch) -> None:
    _roles_by_sub(monkeypatch, "owner", "owner", owners=0)
    client = make_client(_claims(roles=["tenant_admin"]))
    resp = client.patch(f"/tenants/{TENANT_A}/members/{uuid4()}", json={"role": "member"})
    assert resp.status_code == 409 and resp.json()["code"] == "last_owner"
