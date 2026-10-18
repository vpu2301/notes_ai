"""The experiment worker (S3-05): the same pipeline into the experiment's own sink.
A tripwire on everything that could change a note proves it never does; runs go one
by one, honour cancellation and the budget, and every run's usage is accounted.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from note_service.domain import experiments
from note_service.domain import prompt_profiles as profiles
from note_service.jobs import evaluate_note

from .meeting_doc_fakes import ScriptedProvider

TENANT = uuid4()
GERMAN = (
    "Willkommen zur Hafenrunde. Der Containerumschlag in Bremerhaven ist im dritten Quartal "
    "um sechs Prozent gesunken, vor allem wegen der Umleitungen der Reedereien."
)
SOURCE = {
    "result": {
        "language": "de",
        "result_rev": 2,
        "turns": [
            {"speaker": "SPEAKER_1", "name": "Lena", "start_ms": n * 20_000,
             "end_ms": n * 20_000 + 19_000, "paragraphs": [GERMAN]}
            for n in range(3)
        ],
    },
    "role_by_key": {},
    "template_family": None,
    "meeting_type": "auto",
}  # fmt: skip


class _Store:
    def __init__(self, experiment_id: UUID) -> None:
        self.objects: dict[str, bytes] = {
            experiments.source_key(TENANT, experiment_id, 0): json.dumps(SOURCE).encode()
        }
        self.aads: dict[str, bytes] = {}

    async def get(self, *, key: str, tenant_id: UUID, aad: bytes) -> bytes:
        assert tenant_id == TENANT
        return self.objects[key]

    async def put(self, *, key: str, plaintext: bytes, tenant_id: UUID, aad: bytes) -> None:
        assert tenant_id == TENANT and key.startswith(f"{TENANT}/experiment/")
        self.objects[key] = plaintext
        self.aads[key] = aad


class _Db:
    """The experiment tables, in memory. Every other statement is a failure."""

    def __init__(self, *, runs: int = 2, state: str = "queued", token_cap: int = 10**9) -> None:
        self.experiment = experiments.Experiment(
            id=uuid4(), created_by=uuid4(), idempotency_key="key-12345678",
            sources=[{"note_id": str(uuid4()), "transcript_rev": 2}], candidates=[None, None],
            repetitions=1, length="standard", output_language="de", state=state,
            budget_cap_cents=100, reserved_cents=Decimal(10), spent_cents=Decimal(0),
            cost_known=True, token_cap=token_cap, tokens_used=0, error_kind=None,
            created_at=datetime.now(UTC), finished_at=None,
        )  # fmt: skip
        snap = profiles.snapshot(
            profiles.BUNDLED, version_id=None, version_hash=None, multilingual=True,
            fidelity=True, language_hint="de",
            models={s: {"routed": True} for s in profiles.STAGES},
        )  # fmt: skip
        self.runs = [
            experiments.Run(
                id=uuid4(),
                experiment_id=self.experiment.id,
                candidate_index=i,
                source_index=0,
                repetition=1,
                state="pending",
                config_snapshot=snap,
            )  # fmt: skip
            for i in range(runs)
        ]
        self.finished: list[dict[str, Any]] = []
        self.on_start: Any = None

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = self

        @contextlib.asynccontextmanager
        async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
            assert tenant_id == TENANT
            yield _NoSql()

        async def _fetch(conn: Any, *, experiment_id: UUID) -> Any:
            return db.experiment if experiment_id == db.experiment.id else None

        async def _runs(conn: Any, *, experiment_id: UUID) -> list[Any]:
            return list(db.runs)

        async def _set_state(conn: Any, *, experiment_id: UUID, state: str, **kw: Any) -> bool:
            only = kw.get("only_from")
            if only is not None and db.experiment.state not in only:
                return False
            db.experiment.state = state
            return True

        async def _start_run(conn: Any, *, run_id: UUID) -> None:
            run = next(r for r in db.runs if r.id == run_id)
            run.state = "running"
            if db.on_start:
                db.on_start(run)

        async def _finish_run(conn: Any, **kw: Any) -> None:
            run = next(r for r in db.runs if r.id == kw["run_id"])
            run.state = kw["state"]
            db.finished.append(kw)
            db.experiment.tokens_used += kw["tokens"]
            db.experiment.spent_cents += Decimal(str(kw["cost_cents"] or 0))

        async def _cancel_pending(conn: Any, *, experiment_id: UUID, error_kind: str) -> int:
            pending = [r for r in db.runs if r.state == "pending"]
            for r in pending:
                r.state, r.error_kind = "cancelled", error_kind
            return len(pending)

        monkeypatch.setattr(evaluate_note, "tenant_connection", _conn)
        for name, fn in (
            ("fetch", _fetch), ("runs", _runs), ("set_state", _set_state),
            ("start_run", _start_run), ("finish_run", _finish_run),
            ("cancel_pending", _cancel_pending),
        ):  # fmt: skip
            monkeypatch.setattr(experiments, name, fn)


class _NoSql:
    """A connection on which any statement outside the experiment repository fails."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected database call: {name}")


def _tripwire(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Everything that could change a note, a title, an item or a generation raises."""
    from note_service.domain import generation_repository, note_title, notes_repository
    from note_service.domain.meeting_doc import writer
    from note_service.jobs import generate_note

    touched: list[str] = []
    watched = [
        (writer, ("apply",)),
        (generation_repository, ("create", "mark", "put_items", "put_lines", "supersede_previous")),
        (note_title, tuple(n for n in dir(note_title) if n.startswith(("set_", "save", "apply", "store")))),
        (notes_repository, tuple(
            n for n in dir(notes_repository)
            if n.startswith(("set_", "create", "update", "soft_delete", "put_", "mark_", "remove_", "lock_"))
        )),
        (generate_note, ("_name_note", "_store_items", "_store_detected_type", "handle_generate")),
    ]  # fmt: skip
    for module, names in watched:
        for name in names:
            if not callable(getattr(module, name, None)):
                continue

            def boom(*_a: Any, _n: str = f"{module.__name__}.{name}", **_k: Any) -> Any:
                touched.append(_n)
                raise AssertionError(f"an experiment called {_n}")

            monkeypatch.setattr(module, name, boom)
    return touched


def _deps(db: _Db, store: _Store, provider: Any, costs: Any = None) -> evaluate_note.EvaluationDeps:
    async def provider_for(_tenant: str) -> Any:
        return provider

    return evaluate_note.EvaluationDeps(
        app_pool=object(), transcripts_store=store, provider_for=provider_for, costs=costs
    )


def _run(db: _Db, deps: evaluate_note.EvaluationDeps) -> dict[str, Any]:
    return asyncio.run(
        evaluate_note.handle_evaluate(
            deps, tenant_id=TENANT, payload={"experiment_id": str(db.experiment.id)}
        )
    )


def test_an_experiment_writes_no_note_and_stores_its_own_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Db()
    db.install(monkeypatch)
    touched = _tripwire(monkeypatch)
    store = _Store(db.experiment.id)
    outcome = _run(db, _deps(db, store, ScriptedProvider()))
    assert touched == []
    assert outcome == {"runs_done": 2, "runs_failed": 0}
    assert db.experiment.state == "completed"
    artifacts = [k for k in store.objects if "/run-" in k]
    assert len(artifacts) == 2
    # Each artifact is sealed with its own run id, and holds lines and original quotes.
    for run in db.runs:
        key = experiments.artifact_key(TENANT, db.experiment.id, run.id)
        assert store.aads[key] == run.id.bytes
        produced = json.loads(store.objects[key])
        assert produced["sections"] and all("quote" in f for f in produced["facts"])
    # Usage is accounted per run, from the calls that actually answered.
    assert all(f["tokens"] >= 0 and f["metrics"]["calls"] for f in db.finished)
    assert {c["stage"] for f in db.finished for c in f["metrics"]["calls"]} >= {"extraction"}


def test_cancellation_stops_what_has_not_started_and_keeps_what_finished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Db(runs=3)
    db.install(monkeypatch)

    def cancel_after_first(run: Any) -> None:
        if run.candidate_index == 0:
            db.experiment.state = "cancelled"  # an admin pressed Cancel during run 1

    db.on_start = cancel_after_first
    outcome = _run(db, _deps(db, _Store(db.experiment.id), ScriptedProvider()))
    # The run in flight finished (and is accounted); the rest never started.
    assert outcome["runs_done"] == 1 and len(db.finished) == 1
    assert [r.state for r in db.runs] == ["done", "cancelled", "cancelled"]
    assert db.experiment.state == "cancelled"


def test_an_exhausted_budget_stops_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _Db(runs=2, token_cap=1)
    db.experiment.tokens_used = 1  # the cap was reached by earlier runs
    db.install(monkeypatch)
    _run(db, _deps(db, _Store(db.experiment.id), ScriptedProvider()))
    assert [r.state for r in db.runs] == ["cancelled", "cancelled"]
    assert {r.error_kind for r in db.runs} == {"budget_exhausted"}
    assert db.experiment.state == "partial"


def test_a_failed_run_is_a_result_and_the_experiment_says_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Db(runs=2)
    db.install(monkeypatch)
    deps = _deps(db, _Store(db.experiment.id), ScriptedProvider())

    async def flaky(_tenant: str) -> Any:
        if db.runs[0].state == "running":
            raise RuntimeError("backend could not be built")
        return ScriptedProvider()

    deps.provider_for = flaky
    _run(db, deps)
    assert [r.state for r in db.runs] == ["failed", "done"]
    assert db.finished[0]["error_kind"] == "RuntimeError" and db.finished[0]["artifact_key"] is None
    assert db.experiment.state == "partial"


def test_a_model_failure_inside_a_run_is_recorded_as_a_partial_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Db(runs=1)
    db.install(monkeypatch)

    class Down(ScriptedProvider):
        async def complete(self, *a: Any, **k: Any) -> Any:  # type: ignore[override]
            raise RuntimeError("model down")

    _run(db, _deps(db, _Store(db.experiment.id), Down()))
    [finished] = db.finished
    assert finished["state"] == "done" and finished["metrics"]["partial"] is True
    assert all(c["failed"] == c["calls"] for c in finished["metrics"]["calls"])


def test_cost_is_unknown_when_a_backend_has_no_price() -> None:
    calls = [
        {"backend": "dev_mac", "model_id": "m", "ok": True, "input_tokens": 10, "output_tokens": 5}
    ]
    priced = SimpleNamespace(is_priced=lambda b: True, estimate_cents=lambda r: 1.5)
    unpriced = SimpleNamespace(is_priced=lambda b: False, estimate_cents=lambda r: 0.0)
    assert evaluate_note._cost(priced, calls) == 1.5
    assert evaluate_note._cost(unpriced, calls) is None
    assert evaluate_note._cost(None, calls) is None


def test_the_reservation_errs_high_and_unpriced_backends_get_a_token_cap() -> None:
    priced = experiments.estimate(
        source_chars=[10_000], candidates=2, repetitions=3, cents_per_1k=0.5
    )
    assert priced.runs == 6 and priced.cents is not None and priced.cents > 0
    unknown = experiments.estimate(
        source_chars=[10_000], candidates=2, repetitions=3, cents_per_1k=None
    )
    assert unknown.cents is None and unknown.tokens <= 6 * experiments.UNPRICED_TOKENS_PER_RUN


def test_the_worker_never_imports_a_writer_path_of_its_own() -> None:
    source = inspect.getsource(evaluate_note)
    for forbidden in ("writer.apply", "put_items", "put_lines", "_name_note", "notification"):
        assert forbidden not in source
