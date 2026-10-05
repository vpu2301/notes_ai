"""Billing (0068) — the plan, the month's usage, and changing the plan.

What is worth a test:

* a plan never changes without a payment provider that allows it — with
  none connected the change is refused, not faked;
* the AI allowance on the page is the one generation enforces;
* only an admin sees or changes what the workspace pays.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import ai_settings
from note_service.domain import billing as rules

TENANT = UUID("22222222-2222-2222-2222-222222222222")
USER = UUID("11111111-1111-1111-1111-111111111111")


def test_a_recorded_exception_wins_over_the_catalogue() -> None:
    limits = rules.effective_limits(rules.PLANS["free"], {"members": 10})
    assert limits["members"] == 10
    assert limits["notes_per_month"] == 50


def test_an_unknown_plan_reads_as_legacy() -> None:
    assert rules.plan_of("gold").code == "legacy"
    assert rules.plan_of(" PRO ").code == "pro"


def test_every_offered_plan_has_an_ai_allowance_the_budget_can_read() -> None:
    # A missing number is the platform default to the budget, not "no limit".
    for plan in rules.PLANS.values():
        if plan.offered:
            assert plan.limits.get("ai_cents_per_month") is not None, plan.code


def _claims(role: str) -> Claims:
    return Claims(
        sub=USER,
        tid=TENANT,
        roles=[role, "member"] if role != "member" else ["member"],
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


class _Conn:
    async def fetchval(self, query: str, *args: object) -> datetime:
        return datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import billing as router_mod

    audit: list[dict] = []
    tenant = {"plan": "free", "limits": {"notes_per_month": 50, "members": 3}}
    applied: list[str] = []
    stored_sub: dict = {"sub": None}

    async def _write_event(**kwargs):  # noqa: ANN003
        audit.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            workspace_model_settings=SimpleNamespace(invalidate=lambda _t: None),
        )
    )

    @contextlib.asynccontextmanager
    async def _conn(pool, tenant_id):  # noqa: ANN001
        yield _Conn()

    async def _tenant_plan(conn, *, tenant_id):  # noqa: ANN001
        return tenant["plan"], tenant["limits"]

    async def _usage(conn, *, tenant_id):  # noqa: ANN001
        return rules.Usage(notes=12, recording_minutes=95, members=2, ai_cents=150)

    async def _subscription(conn, *, tenant_id):  # noqa: ANN001
        return stored_sub["sub"]

    async def _apply(conn, *, tenant_id, plan, provider, actor, interval="monthly", **_kw):  # noqa: ANN001, ANN003
        applied.append(f"{plan.code}/{interval}")
        tenant["plan"], tenant["limits"] = plan.code, dict(plan.limits)
        stored_sub["sub"] = rules.Subscription(
            provider=provider,
            status="active",
            current_period_end=None,
            cancel_at_period_end=False,
            interval=interval,
        )

    async def _fetch(conn, *, tenant_id):  # noqa: ANN001
        return ai_settings.SettingsRow(
            tenant_id=TENANT,
            provider="platform",
            tier="standard",
            generation_enabled=True,
            acknowledged=[],
            monthly_budget_cents=None,
        )

    monkeypatch.setattr(router_mod, "tenant_connection", _conn)
    monkeypatch.setattr(router_mod.rules, "tenant_plan", _tenant_plan)
    monkeypatch.setattr(router_mod.rules, "usage", _usage)
    monkeypatch.setattr(router_mod.rules, "subscription", _subscription)
    monkeypatch.setattr(router_mod.rules, "apply_plan", _apply)
    monkeypatch.setattr(router_mod.ai_settings, "fetch", _fetch)

    async def _not_due(conn, *, tenant_id):  # noqa: ANN001
        return False

    monkeypatch.setattr(router_mod.rules, "expire_if_due", _not_due)

    app = create_app()
    yield SimpleNamespace(
        app=app,
        client=TestClient(app),
        deps=deps,
        audit=audit,
        applied=applied,
        tenant=tenant,
        stored_sub=stored_sub,
        settings=router_mod.app_settings,
    )
    app.dependency_overrides.clear()
    deps.install_state(None)  # type: ignore[arg-type]


def _as(harness, role: str) -> None:  # noqa: ANN001
    harness.app.dependency_overrides[harness.deps.current_user] = lambda: _claims(role)


def test_an_admin_sees_the_plan_and_the_months_usage(harness) -> None:  # noqa: ANN001
    _as(harness, "tenant_admin")
    body = harness.client.get("/v1/billing").json()
    assert body["plan"]["code"] == "free"
    meters = {m["key"]: m for m in body["usage"]}
    assert meters["notes"] == {"key": "notes", "used": 12, "limit": 50}
    assert meters["members"]["limit"] == 3
    # The allowance generation enforces: the plan records none, so the
    # platform default — the same number check_allowed() uses.
    assert meters["ai"]["limit"] == ai_settings.DEFAULT_BUDGET_CENTS
    assert [p["code"] for p in body["plans"]] == ["free", "pro", "enterprise"]
    assert body["can_edit"] is True


def test_a_member_does_not_see_what_the_workspace_pays(harness) -> None:  # noqa: ANN001
    _as(harness, "member")
    assert harness.client.get("/v1/billing").status_code == 403
    assert harness.client.post("/v1/billing/plan", json={"plan": "pro"}).status_code == 403


def test_without_a_payment_provider_the_plan_does_not_change(  # noqa: ANN001
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(harness, "tenant_admin")
    monkeypatch.setattr(harness.settings, "billing_provider", "none")
    assert harness.client.get("/v1/billing").json()["payments_connected"] is False
    res = harness.client.post("/v1/billing/plan", json={"plan": "pro"})
    assert res.status_code == 409
    assert res.json()["code"] == "billing_not_connected"
    assert harness.applied == []
    assert harness.audit == []


def test_a_manual_provider_switches_at_once_and_says_so(  # noqa: ANN001
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(harness, "tenant_admin")
    monkeypatch.setattr(harness.settings, "billing_provider", "manual")
    res = harness.client.post("/v1/billing/plan", json={"plan": "pro"})
    assert res.status_code == 200
    body = res.json()
    assert body["action"] == "applied"
    assert body["billing"]["plan"]["code"] == "pro"
    assert harness.applied == ["pro/monthly"]
    [event] = harness.audit
    assert event["kind"] == "billing.plan_changed"
    assert event["payload"] == {
        "from_plan": "free",
        "to_plan": "pro",
        "interval": "monthly",
        "provider": "manual",
    }


def test_yearly_is_its_own_choice_on_the_same_plan(  # noqa: ANN001
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(harness, "tenant_admin")
    monkeypatch.setattr(harness.settings, "billing_provider", "manual")
    body = harness.client.get("/v1/billing").json()
    pro = next(p for p in body["plans"] if p["code"] == "pro")
    # Two months free: ten monthly prices for twelve months.
    assert pro["yearly_price_cents"] == 10 * pro["price_cents"]

    harness.client.post("/v1/billing/plan", json={"plan": "pro"})
    res = harness.client.post("/v1/billing/plan", json={"plan": "pro", "interval": "yearly"})
    assert res.json()["billing"]["subscription"]["interval"] == "yearly"
    # Monthly → yearly on the same plan is a change; the same again is not.
    harness.client.post("/v1/billing/plan", json={"plan": "pro", "interval": "yearly"})
    assert harness.applied == ["pro/monthly", "pro/yearly"]


def test_a_plan_without_a_yearly_price_is_billed_monthly(  # noqa: ANN001
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(harness, "tenant_admin")
    monkeypatch.setattr(harness.settings, "billing_provider", "manual")
    harness.tenant["plan"] = "pro"
    harness.client.post("/v1/billing/plan", json={"plan": "free", "interval": "yearly"})
    assert harness.applied == ["free/monthly"]


def test_enterprise_and_unknown_plans_are_not_self_serve(  # noqa: ANN001
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(harness, "tenant_admin")
    monkeypatch.setattr(harness.settings, "billing_provider", "manual")
    res = harness.client.post("/v1/billing/plan", json={"plan": "enterprise"})
    assert res.json()["code"] == "plan_contact_sales"
    assert harness.client.post("/v1/billing/plan", json={"plan": "legacy"}).status_code == 422
    assert harness.applied == []


# ── Redeem codes (0069) ─────────────────────────────────────────────


def test_a_code_is_forgiving_about_case_spaces_and_dashes() -> None:
    assert rules.normalise_code(" abcd-efgh ijkl_mnop ") == "ABCDEFGHIJKLMNOP"
    assert rules.code_hash("abcd-efgh-ijkl-mnop") == rules.code_hash("ABCDEFGHIJKLMNOP")


def test_a_redeemed_code_puts_the_workspace_on_its_plan(  # noqa: ANN001
    harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(harness, "tenant_admin")
    # Codes work with no payment provider at all.
    monkeypatch.setattr(harness.settings, "billing_provider", "none")

    async def _redeem(conn, *, tenant_id, raw, actor):  # noqa: ANN001
        assert raw == "abcd-efgh-ijkl-mnop"
        harness.tenant["plan"] = "pro"
        return rules.Redeemed(plan=rules.PLANS["pro"], period_end=None, days=90)

    monkeypatch.setattr(rules, "redeem", _redeem)
    res = harness.client.post("/v1/billing/redeem", json={"code": "abcd-efgh-ijkl-mnop"})
    assert res.status_code == 200
    assert res.json()["billing"]["plan"]["code"] == "pro"
    [event] = harness.audit
    assert event["kind"] == "billing.code_redeemed"
    # Never the code itself.
    assert event["payload"] == {"from_plan": "free", "to_plan": "pro", "days": 90}


@pytest.mark.parametrize(
    ("reason", "status_code"),
    [("unknown", 404), ("expired", 409), ("used_up", 409), ("already", 409)],
)
def test_a_code_that_cannot_be_redeemed_says_why(  # noqa: ANN001
    harness, monkeypatch: pytest.MonkeyPatch, reason: str, status_code: int
) -> None:
    _as(harness, "tenant_admin")

    async def _redeem(conn, **_kw):  # noqa: ANN001, ANN003
        raise rules.RedeemError(reason)

    monkeypatch.setattr(rules, "redeem", _redeem)
    res = harness.client.post("/v1/billing/redeem", json={"code": "WHATEVER-CODE"})
    assert res.status_code == status_code
    assert res.json()["code"] == f"redeem_{reason}"
    assert harness.audit == []


def test_a_member_cannot_redeem_for_the_workspace(harness) -> None:  # noqa: ANN001
    _as(harness, "member")
    assert harness.client.post("/v1/billing/redeem", json={"code": "X" * 16}).status_code == 403


@pytest.mark.anyio
async def test_a_too_short_code_never_reaches_the_database() -> None:
    class _Never:
        async def fetchrow(self, *a: object) -> None:
            raise AssertionError("looked up")

    with pytest.raises(rules.RedeemError) as exc:
        await rules.redeem(_Never(), tenant_id=TENANT, raw="ab-c", actor=USER)  # type: ignore[arg-type]
    assert exc.value.reason == "unknown"
