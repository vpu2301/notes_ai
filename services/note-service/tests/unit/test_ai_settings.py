"""Who processes this workspace's meetings, and what it may cost: never a
processor nobody acknowledged; over budget stops generating and says so.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import ai_settings as rules

TENANT = UUID("22222222-2222-2222-2222-222222222222")
USER = UUID("11111111-1111-1111-1111-111111111111")

ANTHROPIC = rules.Processor(
    name="Anthropic", region="us", purposes=("writing your meeting notes",), tiers=("premium",)
)
HETZNER = rules.Processor(
    name="Hetzner", region="eu", purposes=("writing your meeting notes",), tiers=("standard",)
)


def _row(**over) -> rules.SettingsRow:  # noqa: ANN003
    base: dict = {"tenant_id": TENANT}
    base.update(over)
    return rules.SettingsRow(**base)


# ── The rules, as pure functions ────────────────────────────────────


def test_budget_prefers_the_workspaces_own_number_then_the_plans() -> None:
    assert rules.budget_cents(_row(monthly_budget_cents=500), {"ai_cents_per_month": 9000}) == 500
    assert rules.budget_cents(_row(), {"ai_cents_per_month": 9000}) == 9000
    assert rules.budget_cents(_row(), {}) == rules.DEFAULT_BUDGET_CENTS
    # A plan limit that is not a number is a misconfiguration, not a
    # licence to spend without limit.
    assert rules.budget_cents(_row(), {"ai_cents_per_month": "lots"}) == rules.DEFAULT_BUDGET_CENTS


def test_a_processor_that_moved_region_is_a_new_processor() -> None:
    row = _row(acknowledged=[{"name": "Anthropic", "region": "eu"}])
    assert rules.missing_acknowledgement(row, [ANTHROPIC], None) == [ANTHROPIC]
    assert (
        rules.missing_acknowledgement(row, [rules.Processor(name="anthropic", region="EU")], None)
        == []
    )


def test_routing_that_gains_a_processor_falls_back_to_platform_standard() -> None:
    """The safety valve: `config/models.yaml` cannot put a new company in
    somebody's data path by being edited."""
    chose_premium = _row(
        provider="anthropic", tier="premium", acknowledged=[{"name": "Anthropic", "region": "us"}]
    )
    assert rules.effective(chose_premium, [ANTHROPIC]) == ("anthropic", "premium", [])

    provider, tier, missing = rules.effective(chose_premium, [ANTHROPIC, HETZNER])
    assert (provider, tier) == (rules.PLATFORM, rules.STANDARD)
    assert missing == [HETZNER]


def test_only_paid_plans_may_ask_for_premium() -> None:
    assert rules.may_choose_premium("pro")
    assert rules.may_choose_premium("Enterprise")
    assert not rules.may_choose_premium("free")
    assert not rules.may_choose_premium(None)


def test_acknowledgement_records_who_and_when() -> None:
    [stamped] = rules.stamp([ANTHROPIC], actor=USER)
    assert stamped["name"] == "Anthropic"
    assert stamped["acknowledged_by"] == str(USER)
    assert stamped["acknowledged_at"]


def test_cached_defaults_down_when_nothing_is_cached() -> None:
    """`resolve()` is synchronous. Answering with the platform default can
    only ever route to FEWER processors than the workspace agreed to."""
    source = rules.WorkspaceSettings(pool=object())
    assert source.cached(str(TENANT)).tier == rules.STANDARD
    assert source.cached(str(TENANT)).provider == rules.PLATFORM


# ── The routes ──────────────────────────────────────────────────────


def _claims(role: str = "tenant_admin") -> Claims:
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


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import ai_settings as router_mod

    audit: list[dict] = []
    invalidated: list[UUID] = []
    stored = {"row": _row()}
    processors = {"required": [ANTHROPIC]}
    plan = {"plan": "pro", "limits": {}}

    async def _write_event(**kwargs):  # noqa: ANN003
        audit.append(kwargs)

    deps.install_state(  # type: ignore[arg-type]
        SimpleNamespace(
            app_pool=object(),
            audit_writer=SimpleNamespace(write_event=_write_event),
            workspace_model_settings=SimpleNamespace(invalidate=invalidated.append),
        )
    )

    @contextlib.asynccontextmanager
    async def _conn(pool, tenant_id):  # noqa: ANN001
        yield None

    async def _fetch(conn, *, tenant_id):  # noqa: ANN001
        return stored["row"]

    async def _upsert(conn, **kw):  # noqa: ANN001, ANN003
        stored["row"] = rules.SettingsRow(
            tenant_id=kw["tenant_id"],
            provider=kw["provider"],
            tier=kw["tier"],
            generation_enabled=kw["generation_enabled"],
            acknowledged=kw["acknowledged"],
            monthly_budget_cents=kw["monthly_budget_cents"],
        )
        return stored["row"]

    async def _spend(conn, *, tenant_id):  # noqa: ANN001
        return 314

    async def _plan(conn, tenant_id):  # noqa: ANN001
        return plan["plan"], plan["limits"]

    monkeypatch.setattr(router_mod, "tenant_connection", _conn)
    monkeypatch.setattr(router_mod.rules, "fetch", _fetch)
    monkeypatch.setattr(router_mod.rules, "upsert", _upsert)
    monkeypatch.setattr(router_mod.rules, "month_to_date_cents", _spend)
    monkeypatch.setattr(router_mod, "_plan", _plan)
    monkeypatch.setattr(router_mod, "_required_processors", lambda: list(processors["required"]))

    app = create_app()
    client = TestClient(app)
    yield SimpleNamespace(
        app=app,
        client=client,
        stored=stored,
        processors=processors,
        plan=plan,
        audit=audit,
        invalidated=invalidated,
        deps=deps,
    )
    app.dependency_overrides.clear()
    deps.install_state(None)  # type: ignore[arg-type]


def _as(harness, role: str) -> None:  # noqa: ANN001
    harness.app.dependency_overrides[harness.deps.current_user] = lambda: _claims(role)


def test_every_member_may_see_who_processes_their_meetings(harness) -> None:  # noqa: ANN001
    _as(harness, "member")
    body = harness.client.get("/v1/ai/settings").json()
    assert [p["name"] for p in body["processors"]] == ["Anthropic"]
    assert body["month_to_date_cents"] == 314
    # …and may not change any of it.
    assert body["can_edit"] is False


def test_a_member_cannot_change_how_meetings_are_processed(harness) -> None:  # noqa: ANN001
    _as(harness, "member")
    assert harness.client.put("/v1/ai/settings", json={"tier": "premium"}).status_code == 403


def test_premium_needs_a_plan_that_has_it(harness) -> None:  # noqa: ANN001
    _as(harness, "tenant_admin")
    harness.plan["plan"] = "free"
    res = harness.client.put("/v1/ai/settings", json={"tier": "premium"})
    assert res.status_code == 403
    # RFC 9457: a dict detail is flattened, so `code` is a top-level member.
    assert res.json()["code"] == "plan_required"


def test_a_routing_change_is_refused_until_the_processors_are_acknowledged(harness) -> None:  # noqa: ANN001
    _as(harness, "tenant_admin")
    res = harness.client.put("/v1/ai/settings", json={"provider": "anthropic"})
    assert res.status_code == 409
    body = res.json()
    assert body["code"] == "processors_not_acknowledged"
    assert body["processors"] == [{"name": "Anthropic", "region": "us"}]
    # Nothing was written.
    assert harness.stored["row"].provider == rules.PLATFORM


def test_acknowledging_in_the_same_call_lets_the_change_through(harness) -> None:  # noqa: ANN001
    _as(harness, "tenant_admin")
    res = harness.client.put(
        "/v1/ai/settings",
        json={
            "provider": "anthropic",
            "tier": "premium",
            "acknowledge": [{"name": "Anthropic", "region": "us"}],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["effective_provider"], body["effective_tier"]) == ("anthropic", "premium")
    assert body["needs_acknowledgement"] == []
    # The registry's one-minute cache would otherwise serve the old tier.
    assert harness.invalidated == [TENANT]
    # The audit line carries counts and closed vocabulary, never a name.
    [event] = harness.audit
    assert event["payload"] == {
        "tier": "premium",
        "provider": "anthropic",
        "generation_enabled": True,
        "acknowledged": 1,
    }


def test_turning_generation_off_needs_no_acknowledgement(harness) -> None:  # noqa: ANN001
    """It reaches fewer processors, not more."""
    _as(harness, "tenant_admin")
    res = harness.client.put("/v1/ai/settings", json={"generation_enabled": False})
    assert res.status_code == 200, res.text
    assert res.json()["generation_enabled"] is False


def test_a_new_processor_in_the_routing_shows_up_as_work_for_the_admin(harness) -> None:  # noqa: ANN001
    _as(harness, "tenant_admin")
    harness.stored["row"] = _row(
        provider="anthropic", tier="premium", acknowledged=[{"name": "Anthropic", "region": "us"}]
    )
    harness.processors["required"] = [ANTHROPIC, HETZNER]
    body = harness.client.get("/v1/ai/settings").json()
    assert body["tier"] == "premium"
    # What it ACTUALLY resolves to until somebody agrees.
    assert (body["effective_provider"], body["effective_tier"]) == ("platform", "standard")
    assert [p["name"] for p in body["needs_acknowledgement"]] == ["Hetzner"]


# ── The budget, at enqueue ──────────────────────────────────────────


class _Conn:
    """Just enough asyncpg to answer `check_allowed`."""

    def __init__(self, *, enabled: bool = True, budget: int | None = None, spent: int = 0) -> None:
        self.enabled, self.budget, self.spent = enabled, budget, spent

    async def fetchrow(self, sql: str, *args):  # noqa: ANN002, ANN201
        if "workspace_model_settings" in sql:
            return {
                "tenant_id": TENANT,
                "provider": "platform",
                "tier": "standard",
                "generation_enabled": self.enabled,
                "acknowledged_processors": [],
                "monthly_budget_cents": self.budget,
                "updated_at": None,
            }
        return {"plan_limits": {}}

    async def fetchval(self, sql: str, *args):  # noqa: ANN002, ANN201
        return self.spent


@pytest.mark.anyio
async def test_a_workspace_over_budget_does_not_queue_work_it_cannot_pay_for() -> None:
    from note_service.domain import generation_service as gen

    with pytest.raises(gen.BudgetExceededError) as caught:
        await gen.check_allowed(_Conn(budget=1000, spent=1000), tenant_id=TENANT)
    assert (caught.value.spent, caught.value.budget) == (1000, 1000)

    # A cent under is still allowed: the cap is a cap, not a warning.
    await gen.check_allowed(_Conn(budget=1000, spent=999), tenant_id=TENANT)


@pytest.mark.anyio
async def test_generation_turned_off_is_refused_before_anything_is_written() -> None:
    from note_service.domain import generation_service as gen

    with pytest.raises(gen.GenerationDisabledError):
        await gen.check_allowed(_Conn(enabled=False), tenant_id=TENANT)


def test_a_person_waiting_on_the_screen_outranks_a_background_upload() -> None:
    from note_service.domain import generation_service as gen

    assert gen.PRIORITY_REGENERATE > gen.PRIORITY_FOLLOWUP > gen.PRIORITY_AUTO


def test_processor_identity_ignores_case_and_padding() -> None:
    assert rules.Processor(name=" Anthropic ", region="US").key() == ("anthropic", "us")


# ── The notification ────────────────────────────────────────────────


class _Redis:
    """SET NX / XADD, enough for the once-a-month guard."""

    def __init__(self) -> None:
        self.keys: dict[str, bytes] = {}
        self.published: list[dict] = []

    async def set(self, key, value, *, nx=False, ex=None):  # noqa: ANN001, ANN202
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True

    async def xadd(self, _stream, fields, **_kw):  # noqa: ANN001, ANN202
        self.published.append(fields)
        return b"1-1"


@pytest.mark.anyio
async def test_an_admin_hears_once_a_month_not_once_a_meeting(monkeypatch) -> None:  # noqa: ANN001
    from note_service import notifications

    monkeypatch.setattr(notifications.settings, "notifications_enabled", True)
    redis = _Redis()

    first = await notifications.emit_budget_reached(
        redis, tenant_id=TENANT, actor_user_id=USER, spent_cents=2100, budget_cents=2000
    )
    again = await notifications.emit_budget_reached(
        redis, tenant_id=TENANT, actor_user_id=USER, spent_cents=2200, budget_cents=2000
    )
    assert (first, again) == (True, False)
    assert len(redis.published) == 1
    # Counts, never a note and never a meeting title.
    import json

    payload = json.loads(redis.published[0][b"value"])["payload"]
    assert payload == {"spent_cents": 2100, "budget_cents": 2000}


@pytest.mark.anyio
async def test_a_redis_outage_still_tells_the_admin() -> None:
    """The guard is a convenience. Losing it costs a duplicate banner;
    losing the notification costs a month of silence."""

    class _Broken(_Redis):
        async def set(self, *a, **k):  # noqa: ANN002, ANN003, ANN202
            raise RuntimeError("redis is down")

    from note_service import notifications

    redis = _Broken()
    assert await notifications.emit_budget_reached(
        redis, tenant_id=TENANT, actor_user_id=None, spent_cents=1, budget_cents=0
    )
