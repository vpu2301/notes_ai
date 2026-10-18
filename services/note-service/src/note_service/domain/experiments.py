"""A/B experiments on fixed transcripts (S3): candidate profile versions run on the
same snapshots, repeated, into their own tables and the object store — never into a
note. Limits, the budget reservation and the repository live here; the run itself is
``jobs/evaluate_note.py``.

Cost is never made up: a backend without a price makes the experiment's cost
unknown, and a conservative token cap bounds it instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import asyncpg

JOB_KIND: Final = "note.evaluate"
MAX_CANDIDATES: Final = 2
MAX_REPETITIONS: Final = 3
MAX_SOURCES: Final = 12
# Tokens a run of the engine reads and writes, per character of transcript (extraction
# reads it, verification and composition read its facts) plus fixed overhead. An
# over-estimate on purpose: it is what the budget reserves.
TOKENS_PER_CHAR: Final = 1.2
TOKENS_PER_RUN: Final = 30_000
# With no price for a backend, this many tokens per run at most.
UNPRICED_TOKENS_PER_RUN: Final = 120_000
ACTIVE: Final[frozenset[str]] = frozenset({"queued", "running"})
FINAL: Final[frozenset[str]] = frozenset({"completed", "partial", "failed", "cancelled"})
FINDING_LABELS: Final[frozenset[str]] = frozenset(
    {
        "wrong_actor",
        "missing_condition",
        "unsupported_claim",
        "omission",
        "duplicate",
        "unclear_attribution",
    }
)


class ExperimentActiveError(Exception):
    """This workspace already has an experiment queued or running."""


class BudgetRefusedError(Exception):
    """The estimate does not fit the cap or what is left of the month's budget."""

    def __init__(self, *, estimate_cents: float | None, cap_cents: int, left_cents: int) -> None:
        super().__init__("experiment_budget")
        self.estimate_cents = estimate_cents
        self.cap_cents = cap_cents
        self.left_cents = left_cents


@dataclass(frozen=True, slots=True)
class Estimate:
    """What the experiment reserves: cents when every backend is priced, else None
    (unknown) — and always a token cap."""

    cents: float | None
    tokens: int
    runs: int


def estimate(
    *,
    source_chars: list[int],
    candidates: int,
    repetitions: int,
    cents_per_1k: float | None,
) -> Estimate:
    """Reservation for ``candidates × sources × repetitions`` runs. ``cents_per_1k`` is
    the dearest bound backend's price per 1,000 tokens, None when any is unpriced."""
    runs = candidates * len(source_chars) * repetitions
    per_source = [int(chars * TOKENS_PER_CHAR) + TOKENS_PER_RUN for chars in source_chars]
    tokens = candidates * repetitions * sum(per_source)
    if cents_per_1k is None:
        return Estimate(cents=None, tokens=min(tokens, runs * UNPRICED_TOKENS_PER_RUN), runs=runs)
    return Estimate(cents=round(tokens / 1000 * cents_per_1k, 4), tokens=tokens, runs=runs)


def price_per_1k(costs: Any, backends: list[str]) -> float | None:
    """The dearest of ``backends`` per 1,000 tokens (a 4:1 read/write mix), from the
    cost table the usage ledger uses; None when any of them has no price."""
    if costs is None or not backends:
        return None
    from models import UsageRecord

    prices = []
    for backend in backends:
        if not costs.is_priced(backend):
            return None
        prices.append(
            costs.estimate_cents(
                UsageRecord(
                    backend=backend, model_id="", operation="chat.complete", ok=True,
                    latency_ms=0, input_tokens=800, output_tokens=200,
                )
            )
        )  # fmt: skip
    return max(prices)


def source_key(tenant_id: UUID, experiment_id: UUID, index: int) -> str:
    """Tenant-prefixed, like a generation snapshot: a key cannot address another workspace."""
    return f"{tenant_id}/experiment/{experiment_id}/source-{index}.json"


def artifact_key(tenant_id: UUID, experiment_id: UUID, run_id: UUID) -> str:
    return f"{tenant_id}/experiment/{experiment_id}/run-{run_id}.json"


# ── Rows ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Experiment:
    id: UUID
    created_by: UUID
    idempotency_key: str
    sources: list[dict[str, Any]]
    candidates: list[str | None]
    repetitions: int
    length: str
    output_language: str
    state: str
    budget_cap_cents: int
    reserved_cents: Decimal
    spent_cents: Decimal
    cost_known: bool
    token_cap: int
    tokens_used: int
    error_kind: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(slots=True)
class Run:
    id: UUID
    experiment_id: UUID
    candidate_index: int
    source_index: int
    repetition: int
    state: str
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    artifact_key: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error_kind: str | None = None
    cost_cents: Decimal | None = None
    latency_ms: int | None = None


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


_EXPERIMENT_COLUMNS: Final = (
    "id, created_by, idempotency_key, sources, candidates, repetitions, length, "
    "output_language, state, budget_cap_cents, reserved_cents, spent_cents, cost_known, "
    "token_cap, tokens_used, error_kind, created_at, finished_at"
)
_RUN_COLUMNS: Final = (
    "id, experiment_id, candidate_index, source_index, repetition, state, config_snapshot, "
    "artifact_key, metrics, error_kind, cost_cents, latency_ms"
)


def _experiment(r: asyncpg.Record) -> Experiment:
    data = dict(r)
    data["sources"] = _json(data["sources"])
    data["candidates"] = _json(data["candidates"])
    return Experiment(**data)


def _run(r: asyncpg.Record) -> Run:
    data = dict(r)
    data["config_snapshot"] = _json(data["config_snapshot"]) or {}
    data["metrics"] = _json(data["metrics"]) or {}
    return Run(**data)


async def by_key(conn: asyncpg.Connection, *, idempotency_key: str) -> Experiment | None:
    r = await conn.fetchrow(
        f"SELECT {_EXPERIMENT_COLUMNS} FROM note_experiments WHERE idempotency_key = $1",
        idempotency_key,
    )
    return _experiment(r) if r is not None else None


async def fetch(conn: asyncpg.Connection, *, experiment_id: UUID) -> Experiment | None:
    r = await conn.fetchrow(
        f"SELECT {_EXPERIMENT_COLUMNS} FROM note_experiments WHERE id = $1", experiment_id
    )
    return _experiment(r) if r is not None else None


async def create(
    conn: asyncpg.Connection,
    *,
    experiment_id: UUID,
    tenant_id: UUID,
    created_by: UUID,
    idempotency_key: str,
    sources: list[dict[str, Any]],
    candidates: list[str | None],
    repetitions: int,
    length: str,
    output_language: str,
    budget_cap_cents: int,
    reservation: Estimate,
    run_snapshots: dict[int, dict[str, Any]],
) -> tuple[Experiment, bool]:
    """``(experiment, created)``. The same idempotency key returns the first experiment
    unchanged (``created=False``); a second active one raises ``ExperimentActiveError``.
    Every run row is created now, pending, with its candidate's pinned snapshot."""
    existing = await by_key(conn, idempotency_key=idempotency_key)
    if existing is not None:
        return existing, False
    try:
        r = await conn.fetchrow(
            f"""
            INSERT INTO note_experiments (
                tenant_id, created_by, idempotency_key, sources, candidates, repetitions,
                length, output_language, budget_cap_cents, reserved_cents, cost_known, token_cap,
                id
            ) VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING {_EXPERIMENT_COLUMNS}
            """,
            tenant_id,
            created_by,
            idempotency_key,
            json.dumps(sources),
            json.dumps(candidates),
            repetitions,
            length,
            output_language,
            budget_cap_cents,
            Decimal(str(reservation.cents or 0)),
            reservation.cents is not None,
            reservation.tokens,
            experiment_id,
        )
    except asyncpg.UniqueViolationError as exc:
        if "one_active" in str(exc):
            raise ExperimentActiveError from exc
        # The same key raced us: the first one wins, as if we had found it.
        again = await by_key(conn, idempotency_key=idempotency_key)
        if again is None:
            raise
        return again, False
    experiment = _experiment(r)
    for candidate_index in range(len(candidates)):
        for source_index in range(len(sources)):
            for repetition in range(1, repetitions + 1):
                await conn.execute(
                    """
                    INSERT INTO note_experiment_runs (
                        tenant_id, experiment_id, candidate_index, source_index, repetition,
                        config_snapshot
                    ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                    """,
                    tenant_id,
                    experiment.id,
                    candidate_index,
                    source_index,
                    repetition,
                    json.dumps(run_snapshots.get(candidate_index, {})),
                )
    return experiment, True


async def runs(conn: asyncpg.Connection, *, experiment_id: UUID) -> list[Run]:
    rows = await conn.fetch(
        f"SELECT {_RUN_COLUMNS} FROM note_experiment_runs WHERE experiment_id = $1 "
        "ORDER BY source_index, repetition, candidate_index",
        experiment_id,
    )
    return [_run(r) for r in rows]


async def set_state(
    conn: asyncpg.Connection,
    *,
    experiment_id: UUID,
    state: str,
    error_kind: str | None = None,
    only_from: frozenset[str] | None = None,
) -> bool:
    """Move the experiment; ``only_from`` makes it a compare-and-set (cancel races finish)."""
    final = state in FINAL
    result = await conn.execute(
        """
        UPDATE note_experiments
           SET state = $2, error_kind = COALESCE($3, error_kind),
               finished_at = CASE WHEN $4 THEN now() ELSE finished_at END,
               reserved_cents = CASE WHEN $4 THEN 0 ELSE reserved_cents END
         WHERE id = $1 AND ($5::text[] IS NULL OR state = ANY($5::text[]))
        """,
        experiment_id,
        state,
        error_kind,
        final,
        sorted(only_from) if only_from is not None else None,
    )
    return result.endswith(" 1")


async def start_run(conn: asyncpg.Connection, *, run_id: UUID) -> None:
    await conn.execute(
        "UPDATE note_experiment_runs SET state = 'running', started_at = now() WHERE id = $1",
        run_id,
    )


async def finish_run(
    conn: asyncpg.Connection,
    *,
    experiment_id: UUID,
    run_id: UUID,
    state: str,
    artifact_key: str | None,
    metrics: dict[str, Any],
    error_kind: str | None,
    cost_cents: float | None,
    tokens: int,
    latency_ms: int,
) -> None:
    """The run's outcome, and its usage added to the experiment's account — a failed
    run's tokens were spent too."""
    await conn.execute(
        """
        UPDATE note_experiment_runs
           SET state = $2, artifact_key = $3, metrics = $4::jsonb, error_kind = $5,
               cost_cents = $6, latency_ms = $7, finished_at = now()
         WHERE id = $1
        """,
        run_id,
        state,
        artifact_key,
        json.dumps(metrics),
        error_kind,
        Decimal(str(cost_cents)) if cost_cents is not None else None,
        latency_ms,
    )
    await conn.execute(
        """
        UPDATE note_experiments
           SET spent_cents = spent_cents + $2, tokens_used = tokens_used + $3,
               cost_known = cost_known AND $4
         WHERE id = $1
        """,
        experiment_id,
        Decimal(str(cost_cents or 0)),
        tokens,
        cost_cents is not None,
    )


async def cancel_pending(conn: asyncpg.Connection, *, experiment_id: UUID, error_kind: str) -> int:
    result = await conn.execute(
        "UPDATE note_experiment_runs SET state = 'cancelled', error_kind = $2 "
        "WHERE experiment_id = $1 AND state = 'pending'",
        experiment_id,
        error_kind,
    )
    return int(result.split()[-1])


async def add_review(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    experiment_id: UUID,
    run_a_id: UUID,
    run_b_id: UUID,
    reviewer: UUID,
    blind: bool,
    revealed: bool,
    preference: str,
    findings: list[dict[str, Any]],
    comment: str,
) -> UUID:
    review_id: UUID = await conn.fetchval(
        """
        INSERT INTO note_experiment_reviews (
            tenant_id, experiment_id, run_a_id, run_b_id, reviewer, blind, revealed,
            preference, findings, comment
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
        RETURNING id
        """,
        tenant_id,
        experiment_id,
        run_a_id,
        run_b_id,
        reviewer,
        blind,
        revealed,
        preference,
        json.dumps(findings),
        comment,
    )
    return review_id


async def reviews(conn: asyncpg.Connection, *, experiment_id: UUID) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT id, run_a_id, run_b_id, reviewer, blind, revealed, preference, findings, "
        "comment, created_at FROM note_experiment_reviews WHERE experiment_id = $1 "
        "ORDER BY created_at",
        experiment_id,
    )
    return [{**dict(r), "findings": _json(r["findings"])} for r in rows]


async def reserved_elsewhere(conn: asyncpg.Connection) -> Decimal:
    """What this workspace's unfinished experiments still hold of the month's budget."""
    value = await conn.fetchval(
        "SELECT coalesce(sum(reserved_cents - spent_cents), 0) FROM note_experiments "
        "WHERE state IN ('queued', 'running')"
    )
    return Decimal(value or 0)


# A reviewer's finding that blocks activation on the candidate it was made against.
CRITICAL_FINDINGS: Final[frozenset[str]] = frozenset(
    {"wrong_actor", "missing_condition", "unsupported_claim"}
)


async def evidence_problem(
    conn: asyncpg.Connection, *, experiment_id: UUID, version_id: UUID
) -> str | None:
    """None when this experiment is evidence for activating ``version_id``: it finished,
    the version was a candidate, every one of its runs is done, and no review found a
    critical error in them. Else what is missing, in words for the admin."""
    experiment = await fetch(conn, experiment_id=experiment_id)
    if experiment is None:
        return "the evaluation was not found"
    if experiment.state != "completed":
        return f"the evaluation is {experiment.state}, not completed"
    if str(version_id) not in experiment.candidates:
        return "this version was not tested in that evaluation"
    candidate = experiment.candidates.index(str(version_id))
    mine = [
        r for r in await runs(conn, experiment_id=experiment_id) if r.candidate_index == candidate
    ]
    if not mine or any(r.state != "done" for r in mine):
        return "not every run of this version finished"
    ids = {r.id for r in mine}
    for review in await reviews(conn, experiment_id=experiment_id):
        for finding in review["findings"] or []:
            run_id = review["run_a_id"] if finding.get("run") == "a" else review["run_b_id"]
            if run_id in ids and finding.get("label") in CRITICAL_FINDINGS:
                return f"a reviewer found {finding['label'].replace('_', ' ')} in this version's output"
    return None


async def recent(conn: asyncpg.Connection, *, limit: int = 20) -> list[Experiment]:
    rows = await conn.fetch(
        f"SELECT {_EXPERIMENT_COLUMNS} FROM note_experiments ORDER BY created_at DESC LIMIT $1",
        limit,
    )
    return [_experiment(r) for r in rows]
