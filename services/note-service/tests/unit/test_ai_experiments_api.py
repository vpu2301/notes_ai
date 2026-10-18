"""`/v1/ai/experiments` (S3-04/05): a retry never doubles a paid experiment; sources
are read with the caller's own access and checked again on every read of results;
revision, processor and budget conflicts block work; one experiment at a time.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from auth import Claims
from note_service.domain import experiments
from note_service.domain import prompt_profiles as profiles

TENANT = UUID("22222222-2222-2222-2222-222222222222")
USER = UUID("11111111-1111-1111-1111-111111111111")


def _claims(role: str = "tenant_admin") -> Claims:
    return Claims(
        sub=USER, tid=TENANT, roles=[role, "member"] if role != "member" else ["member"],
        sid="s", iss="https://test/issuer", aud="mdx", exp=9_999_999_999, iat=1_700_000_000,
    )  # fmt: skip


class _World:
    def __init__(self) -> None:
        self.note = SimpleNamespace(id=uuid4(), source_asr_job_id=uuid4(), meeting_type="auto")
        self.visible = True
        self.transcript_readable = True
        self.transcript_rev = 3
        self.experiments: dict[UUID, experiments.Experiment] = {}
        self.runs: dict[UUID, list[experiments.Run]] = {}
        self.reviews: list[dict[str, Any]] = []
        self.enqueued: list[dict[str, Any]] = []
        self.stored: dict[str, bytes] = {}
        self.budget_cents = 10_000
        self.price_per_1k: float | None = 0.01

    def experiment(self, **over: Any) -> experiments.Experiment:
        e = experiments.Experiment(
            id=uuid4(), created_by=USER, idempotency_key=f"seed-{uuid4()}",
            sources=[{"note_id": str(self.note.id), "transcript_rev": 3}], candidates=[None],
            repetitions=1, length="standard", output_language="de", state="completed",
            budget_cap_cents=100, reserved_cents=Decimal(0), spent_cents=Decimal(0),
            cost_known=True, token_cap=10**6, tokens_used=0, error_kind=None,
            created_at=datetime.now(UTC), finished_at=None,
        )  # fmt: skip
        for k, v in over.items():
            setattr(e, k, v)
        self.experiments[e.id] = e
        return e


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    from note_service import deps
    from note_service.main import create_app
    from note_service.routers import ai_experiments as router

    w = _World()

    async def _write_event(**kw: Any) -> None:
        return None

    async def _enqueue(tenant_id: UUID, kind: str, payload: dict, **kw: Any) -> None:
        w.enqueued.append({"kind": kind, **payload, "key": kw.get("idempotency_key")})

    async def _put(*, key: str, plaintext: bytes, tenant_id: UUID, aad: bytes) -> None:
        w.stored[key] = plaintext

    async def _get(*, key: str, tenant_id: UUID, aad: bytes) -> bytes:
        return w.stored[key]

    deps.install_state(SimpleNamespace(  # type: ignore[arg-type]
        app_pool=object(),
        audit_writer=SimpleNamespace(write_event=_write_event),
        job_queue=SimpleNamespace(enqueue=_enqueue),
        transcripts_store=SimpleNamespace(put=_put, get=_get),
    ))  # fmt: skip

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        yield None

    async def _fetch_note(conn: Any, *, note_id: UUID) -> Any:
        return w.note if note_id == w.note.id else None

    def _require_view(note: Any, claims: Any) -> Any:
        if note is None or not w.visible:
            raise HTTPException(404, detail="note not found")
        return note

    async def _transcript(job_id: UUID, *, auth_header: str) -> dict:
        assert auth_header == "Bearer caller"  # the caller's own bearer, never a service identity
        return {"language": "de", "result_rev": w.transcript_rev, "turns": []}

    async def _caps(conn: Any, tenant_id: UUID) -> list:
        return []

    async def _role_map(conn: Any, *, note_id: UUID) -> Any:
        return {}, None

    async def _allowed(conn: Any, *, tenant_id: UUID, **kw: Any) -> None:
        return None

    async def _settings(conn: Any, *, tenant_id: UUID) -> Any:
        return SimpleNamespace(monthly_budget_cents=w.budget_cents)

    async def _plan(conn: Any, tenant_id: UUID) -> Any:
        return "pro", {}

    async def _zero(conn: Any, **kw: Any) -> Any:
        return Decimal(0) if not kw else 0

    async def _by_key(conn: Any, *, idempotency_key: str) -> Any:
        return next(
            (e for e in w.experiments.values() if e.idempotency_key == idempotency_key), None
        )

    async def _create(conn: Any, **kw: Any) -> Any:
        if any(e.state in experiments.ACTIVE for e in w.experiments.values()):
            raise experiments.ExperimentActiveError
        e = w.experiment(
            id=kw["experiment_id"], idempotency_key=kw["idempotency_key"], state="queued",
            candidates=kw["candidates"], repetitions=kw["repetitions"], sources=kw["sources"],
            cost_known=kw["reservation"].cents is not None, token_cap=kw["reservation"].tokens,
        )  # fmt: skip
        w.runs[e.id] = [
            experiments.Run(id=uuid4(), experiment_id=e.id, candidate_index=c, source_index=0,
                            repetition=r, state="pending", config_snapshot=kw["run_snapshots"][c])
            for c in range(len(kw["candidates"])) for r in range(1, kw["repetitions"] + 1)
        ]  # fmt: skip
        return e, True

    async def _fetch(conn: Any, *, experiment_id: UUID) -> Any:
        return w.experiments.get(experiment_id)

    async def _runs(conn: Any, *, experiment_id: UUID) -> list:
        return list(w.runs.get(experiment_id, []))

    async def _set_state(
        conn: Any, *, experiment_id: UUID, state: str, only_from: Any = None, **k: Any
    ) -> bool:  # noqa: E501
        e = w.experiments[experiment_id]
        if only_from is not None and e.state not in only_from:
            return False
        e.state = state
        return True

    async def _cancel_pending(conn: Any, *, experiment_id: UUID, error_kind: str) -> int:
        pending = [r for r in w.runs[experiment_id] if r.state == "pending"]
        for r in pending:
            r.state = "cancelled"
        return len(pending)

    async def _add_review(conn: Any, **kw: Any) -> UUID:
        w.reviews.append(kw)
        return uuid4()

    async def _reviews(conn: Any, *, experiment_id: UUID) -> list:
        return [{"id": uuid4(), **r} for r in w.reviews]

    async def _latest(conn: Any, *, note_id: UUID) -> Any:
        return None

    async def _recent(conn: Any, *, limit: int = 20) -> list:
        return sorted(w.experiments.values(), key=lambda e: e.created_at, reverse=True)

    patches = {
        (router, "tenant_connection"): _conn,
        (router, "_fetch_transcript"): _transcript,
        (router.repo, "fetch_note"): _fetch_note,
        (router.access, "require_view"): _require_view,
        (router.access, "can_view"): lambda note, claims: w.visible,
        (router.access, "can_read_transcript"): lambda note, claims: w.transcript_readable,
        (router.ai_profiles, "_capabilities"): _caps,
        (router.generation_service, "check_allowed"): _allowed,
        (router.settings_rules, "fetch"): _settings,
        (router.settings_rules, "month_to_date_cents"): lambda conn, **k: _zero(conn),
        (router.ai_profiles.ai_settings_router, "_plan"): _plan,
        (router.experiments, "reserved_elsewhere"): lambda conn: _zero(conn),
        (router.experiments, "by_key"): _by_key,
        (router.experiments, "create"): _create,
        (router.experiments, "fetch"): _fetch,
        (router.experiments, "runs"): _runs,
        (router.experiments, "set_state"): _set_state,
        (router.experiments, "cancel_pending"): _cancel_pending,
        (router.experiments, "add_review"): _add_review,
        (router.experiments, "reviews"): _reviews,
        (router.experiments, "recent"): _recent,
        (router.gen_repo, "latest_for_note"): _latest,
        (router, "_routed_backend"): lambda tenant: {
            "backend": "mistral_eu",
            "model_id": "m",
            "routed": True,
        },  # noqa: E501
        (router, "_costs"): lambda: None,
        (router.experiments, "price_per_1k"): lambda costs, backends: w.price_per_1k,
    }
    for (module, name), value in patches.items():
        monkeypatch.setattr(module, name, value)
    from note_service.jobs import generate_note

    monkeypatch.setattr(generate_note, "_role_map", _role_map)
    monkeypatch.setattr(router.settings_rules, "budget_cents", lambda row, limits: w.budget_cents)

    app = create_app()
    client = TestClient(app, headers={"Authorization": "Bearer caller"})

    def as_(role: str) -> None:
        app.dependency_overrides[deps.current_user] = lambda: _claims(role)

    as_("tenant_admin")
    yield SimpleNamespace(client=client, w=w, as_=as_)
    app.dependency_overrides.clear()
    deps.install_state(None)  # type: ignore[arg-type]


def _body(api: Any, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "sources": [{"note_id": str(api.w.note.id), "transcript_rev": 3}],
        "candidate_version_ids": [None],
        "repetitions": 3,
        "length": "detailed",
        "output_language": "de",
        "budget_cap_cents": 300,
    }
    body.update(over)
    return body


def _start(api: Any, key: str = "key-0000001", **over: Any) -> Any:
    return api.client.post(
        "/v1/ai/experiments", json={**_body(api, **over), "idempotency_key": key}
    )


def test_a_retry_with_the_same_key_never_doubles_the_experiment(api: Any) -> None:
    first = _start(api)
    assert first.status_code == 202 and first.json()["state"] == "queued"
    again = _start(api)
    assert again.json()["id"] == first.json()["id"]
    assert len(api.w.enqueued) == 1 and api.w.enqueued[0]["kind"] == experiments.JOB_KIND
    # Three repetitions of one candidate on one source, each pinned.
    runs = first.json()["runs"]
    assert len(runs) == 3 and all(r["config"]["prompt_version"] for r in runs)


def test_the_sources_are_frozen_with_the_experiment_and_sealed_to_it(api: Any) -> None:
    started = _start(api).json()
    key = experiments.source_key(TENANT, UUID(started["id"]), 0)
    frozen = json.loads(api.w.stored[key])
    assert frozen["result"]["result_rev"] == 3


def test_a_source_the_caller_cannot_see_is_404_and_a_hidden_transcript_403(api: Any) -> None:
    api.w.visible = False
    assert _start(api).status_code == 404
    api.w.visible, api.w.transcript_readable = True, False
    r = _start(api, key="key-0000002")
    assert r.status_code == 403 and r.json()["code"] == "transcript_not_shared"


def test_a_transcript_that_moved_on_is_a_revision_conflict(api: Any) -> None:
    api.w.transcript_rev = 4
    r = _start(api)
    assert r.status_code == 409 and r.json()["code"] == "source_revision_conflict"
    assert api.w.enqueued == []


def test_an_estimate_over_the_cap_or_the_month_is_refused(api: Any) -> None:
    r = _start(api, budget_cap_cents=0)
    assert r.status_code == 409 and r.json()["code"] == "experiment_budget"
    assert r.json()["estimate_cents"] > 0 and api.w.enqueued == []
    api.w.budget_cents = 0
    assert _start(api, key="key-0000003").json()["code"] == "experiment_budget"


def test_without_a_price_the_cost_is_unknown_not_invented(api: Any) -> None:
    api.w.price_per_1k = None
    r = _start(api, budget_cap_cents=0)
    # Nothing to compare a cap with: it is queued, cost unknown, bounded by tokens.
    assert r.status_code == 202
    assert r.json()["cost_known"] is False and r.json()["reserved_cents"] == 0
    assert 0 < r.json()["token_cap"] <= 3 * experiments.UNPRICED_TOKENS_PER_RUN


def test_one_experiment_at_a_time(api: Any) -> None:
    assert _start(api).status_code == 202
    busy = _start(api, key="key-0000004")
    assert busy.status_code == 429 and busy.json()["code"] == "experiment_active"


def test_limits_are_validated(api: Any) -> None:
    assert _start(api, repetitions=4).status_code == 422
    assert _start(api, candidate_version_ids=[None, None, None]).status_code == 422
    too_many = [{"note_id": str(uuid4()), "transcript_rev": 1}] * (experiments.MAX_SOURCES + 1)
    assert _start(api, sources=too_many).status_code == 422
    no_key = api.client.post("/v1/ai/experiments", json=_body(api))
    assert no_key.status_code == 422  # the idempotency key is required


def test_members_cannot_start_or_cancel(api: Any) -> None:
    api.as_("member")
    assert _start(api).status_code == 403
    e = api.w.experiment(state="running")
    assert api.client.post(f"/v1/ai/experiments/{e.id}/cancel").status_code == 403


def test_cancel_stops_pending_runs_and_keeps_finished_ones(api: Any) -> None:
    started = _start(api).json()
    eid = UUID(started["id"])
    api.w.runs[eid][0].state = "done"
    r = api.client.post(f"/v1/ai/experiments/{eid}/cancel")
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    assert [x["state"] for x in r.json()["runs"]] == ["done", "cancelled", "cancelled"]


def test_results_follow_the_sources_current_access(api: Any) -> None:
    e = api.w.experiment()
    run = experiments.Run(id=uuid4(), experiment_id=e.id, candidate_index=0, source_index=0,
                          repetition=1, state="done", artifact_key="k")  # fmt: skip
    api.w.runs[e.id] = [run]
    api.w.stored["k"] = json.dumps({"sections": [], "facts": []}).encode()
    assert api.client.get(f"/v1/ai/experiments/{e.id}/runs/{run.id}/artifact").status_code == 200
    # Access to the source revoked after the experiment ran: no content, metrics still.
    api.w.transcript_readable = False
    assert api.client.get(f"/v1/ai/experiments/{e.id}/runs/{run.id}/artifact").status_code == 404
    view = api.client.get(f"/v1/ai/experiments/{e.id}").json()
    assert (
        view["runs"][0]["artifact_available"] is False and view["sources"][0]["readable"] is False
    )


def test_a_review_compares_two_runs_of_the_same_source(api: Any) -> None:
    e = api.w.experiment()
    a, b = (experiments.Run(id=uuid4(), experiment_id=e.id, candidate_index=i, source_index=0,
                            repetition=1, state="done") for i in (0, 1))  # fmt: skip
    api.w.runs[e.id] = [a, b]
    body = {"run_a_id": str(a.id), "run_b_id": str(b.id), "blind": True, "preference": "b",
            "findings": [{"run": "a", "label": "missing_condition"}]}  # fmt: skip
    assert api.client.post(f"/v1/ai/experiments/{e.id}/reviews", json=body).status_code == 201
    assert api.w.reviews[0]["blind"] is True and api.w.reviews[0]["revealed"] is False
    bad = {**body, "findings": [{"run": "a", "label": "too_long"}]}
    assert api.client.post(f"/v1/ai/experiments/{e.id}/reviews", json=bad).status_code == 422
    api.w.transcript_readable = False
    assert api.client.post(f"/v1/ai/experiments/{e.id}/reviews", json=body).status_code == 404
    assert api.client.get(f"/v1/ai/experiments/{e.id}/reviews").json() == []


def test_another_workspaces_experiment_is_a_plain_404(api: Any) -> None:
    assert api.client.get(f"/v1/ai/experiments/{uuid4()}").status_code == 404
    assert api.client.post(f"/v1/ai/experiments/{uuid4()}/cancel").status_code == 404


def test_the_pinned_run_config_carries_no_instruction_text(api: Any) -> None:
    started = _start(api).json()
    assert all("config" not in r["config"] for r in started["runs"])
    assert {"prompt_hashes", "models", "profile_version_id"} <= set(started["runs"][0]["config"])
    assert tuple(started["runs"][0]["config"]["models"]) == profiles.STAGES


def test_an_estimate_reserves_nothing_and_says_what_a_start_would(api: Any) -> None:
    r = api.client.post(
        "/v1/ai/experiments/estimate", json={**_body(api), "idempotency_key": "est-0000001"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["runs"] == 3 and body["cost_known"] is True and body["estimate_cents"] > 0
    assert body["sources"] == [
        {"note_id": str(api.w.note.id), "transcript_rev": 3, "languages": ["de"]}
    ]
    assert api.w.enqueued == [] and api.w.experiments == {} and api.w.stored == {}
    api.w.price_per_1k = None
    assert (
        api.client.post(
            "/v1/ai/experiments/estimate", json={**_body(api), "idempotency_key": "est-0000001"}
        ).json()["estimate_cents"]
        is None
    )
    api.w.transcript_rev = 9
    assert (
        api.client.post(
            "/v1/ai/experiments/estimate", json={**_body(api), "idempotency_key": "est-0000001"}
        ).json()["code"]
        == "source_revision_conflict"
    )


def test_the_list_shows_states_and_counts_not_content(api: Any) -> None:
    _start(api)
    [only] = api.client.get("/v1/ai/experiments").json()
    assert only["state"] == "queued" and only["sources"] == 1 and only["repetitions"] == 3
    assert set(only) == {
        "id",
        "state",
        "candidates",
        "sources",
        "repetitions",
        "cost_known",
        "spent_cents",
        "created_at",
    }  # noqa: E501
