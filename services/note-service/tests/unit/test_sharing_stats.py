"""`GET /v1/admin/sharing/stats` — counts for the person who runs the
workspace, nothing for anyone else (Sprint 22)."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import notes_repository as repo

USER = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")


def _claims(roles: list[str]) -> Claims:
    return Claims(
        sub=USER,
        tid=TENANT,
        roles=roles,
        sid="s",
        iss="i",
        aud="a",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import sharing_stats as router_mod

    audit: list[dict] = []

    async def _write_event(**kwargs):  # noqa: ANN003
        audit.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(app_pool=object(), audit_writer=SimpleNamespace(write_event=_write_event))
    )

    @contextlib.asynccontextmanager
    async def _conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(router_mod, "tenant_connection", _conn)

    async def _stats(conn, *, days):  # noqa: ANN001
        return {
            "links_created": 10,
            "links_sent": 8,
            "links_opened": 6,
            "links_responded": 4,
            "cta_clicks": 2,
            "disputes": 1,
            "item_responses": 5,
            "opted_out": 1,
            "top_senders": [(USER, 7)],
        }

    async def _members(conn, *, subs):  # noqa: ANN001
        return [SimpleNamespace(sub=USER, email="anna@acme.com", display_name="Anna Koval")]

    monkeypatch.setattr(repo, "sharing_stats", _stats)
    monkeypatch.setattr(repo, "fetch_members", _members)

    from note_service.domain import sharing_policy

    box = {"policy": sharing_policy.SharingPolicy(), "plan": "free", "saved": [], "revoked": 0}

    async def _load(conn, *, tenant_id):  # noqa: ANN001
        return box["policy"], box["plan"]

    async def _save(conn, *, tenant_id, policy):  # noqa: ANN001
        box["policy"] = policy
        box["saved"].append(policy)

    async def _revoke_all(conn, *, actor_sub):  # noqa: ANN001
        box["revoked"] += 1
        return [uuid4(), uuid4()]

    monkeypatch.setattr(sharing_policy, "load_policy", _load)
    monkeypatch.setattr(sharing_policy, "save_policy", _save)
    monkeypatch.setattr(repo, "revoke_all_external_links", _revoke_all)
    app = create_app()
    c = TestClient(app)
    c.app_ = app  # type: ignore[attr-defined]
    c.box = box  # type: ignore[attr-defined]
    c.audit = audit  # type: ignore[attr-defined]
    return c


def test_admin_gets_counts_and_display_names_only(client: TestClient) -> None:
    from note_service import deps

    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(["tenant_admin"])
    r = client.get("/v1/admin/sharing/stats", params={"days": 90})
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 90
    assert body["links_sent"] == 8
    assert body["dispute_rate"] == 0.2
    assert body["top_senders"] == [{"display_name": "Anna Koval", "links": 7}]
    assert "anna@acme.com" not in r.text


def test_a_member_is_refused(client: TestClient) -> None:
    from note_service import deps

    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(["member"])
    assert client.get("/v1/admin/sharing/stats").status_code == 403


# ── Sprint 23: the policy ────────────────────────────────────────────


def test_admin_reads_and_writes_the_policy_with_an_audit_of_the_keys(client: TestClient) -> None:
    from note_service import deps

    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(["tenant_admin"])
    assert client.get("/v1/admin/sharing/policy").json()["max_link_days"] == 180
    body = client.get("/v1/admin/sharing/policy").json()
    body.update({"max_link_days": 60, "verified_recipients_required": True})
    r = client.put("/v1/admin/sharing/policy", json=body)
    assert r.status_code == 200
    assert r.json()["max_link_days"] == 60
    changed = [a for a in client.audit if a["kind"] == "tenant.sharing_policy_changed"]
    assert changed[0]["payload"] == {
        "changed_keys": ["max_link_days", "verified_recipients_required"]
    }
    # Same body again: nothing saved, nothing audited.
    client.put("/v1/admin/sharing/policy", json=r.json())
    assert len(client.box["saved"]) == 1


def test_re_enabling_product_mail_clears_the_abuse_mark(client: TestClient) -> None:
    from note_service import deps
    from note_service.domain import sharing_policy

    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(["tenant_admin"])
    client.box["policy"] = sharing_policy.SharingPolicy(
        product_email_enabled=False, auto_disabled_reason="abuse_reports"
    )
    body = client.get("/v1/admin/sharing/policy").json()
    assert body["auto_disabled_reason"] == "abuse_reports"
    body["product_email_enabled"] = True
    assert client.put("/v1/admin/sharing/policy", json=body).json()["auto_disabled_reason"] is None


def test_member_cannot_write_the_policy_and_revoke_all_is_audited_per_note(
    client: TestClient,
) -> None:
    from note_service import deps

    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(["member"])
    body = {"external_links_enabled": False}
    assert client.put("/v1/admin/sharing/policy", json=body).status_code == 403
    client.app_.dependency_overrides[deps.current_user] = lambda: _claims(["tenant_admin"])
    r = client.post("/v1/admin/sharing/revoke-all")
    assert r.status_code == 200
    assert r.json() == {"notes": 2}
    revoked = [a for a in client.audit if a["kind"] == "note.link_revoked"]
    assert len(revoked) == 2 and revoked[0]["payload"]["reason"] == "policy"
