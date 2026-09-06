"""``model_usage`` ledger — the DB sink for the libs/models usage hook (DEP-S1-06).

Records emitted during a job are buffered per task (a ContextVar) and
flushed **inside the job's completion transaction** by the runner, so a
usage row and the job outcome commit or roll back together — that is the
"outbox in the job transaction" of the spec. Records emitted outside any
job (eval scripts, probes) are flushed by whoever owns the connection or
dropped with a log line — never lost silently.

Rows carry counts, identifiers and an estimated cost; never content.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import asdict
from typing import Any
from uuid import UUID

import asyncpg

from models import UsageRecord, set_usage_sink

from . import metrics
from .costs import CostTable

logger = logging.getLogger("jobs.ledger")

_INSERT = """
INSERT INTO model_usage (tenant_id, job_id, backend, model_id, operation, ok, error_kind,
                         input_tokens, output_tokens, audio_seconds, latency_ms, attempts,
                         structured_mode, cost_cents_est)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
"""

_buffer: ContextVar[list[UsageRecord] | None] = ContextVar("model_usage_buffer", default=None)


class UsageLedger:
    def __init__(self, costs: CostTable | None = None, *, tier_of: Any = None) -> None:
        self._costs = costs or CostTable.empty()
        self._tier_of = (
            tier_of  # Callable[[str], str] | None — workspace → tier for the cost metric
        )

    # ── sink side (called from libs/models on every call) ───────────────
    def install(self) -> None:
        set_usage_sink(self.record)

    def record(self, rec: UsageRecord) -> None:
        cents = self._costs.estimate_cents(rec)
        labels = {
            "backend": rec.backend,
            "operation": rec.operation,
            "outcome": "ok" if rec.ok else (rec.error_kind or "error"),
        }
        metrics.model_calls_total.add(1, labels)
        metrics.model_latency_seconds.record(
            rec.latency_ms / 1000.0, {"backend": rec.backend, "operation": rec.operation}
        )
        if cents:
            tier = (
                self._tier_of(rec.workspace_id)
                if (self._tier_of and rec.workspace_id)
                else "standard"
            )
            metrics.model_cost_cents_total.add(cents, {"backend": rec.backend, "tier": tier})
        buf = _buffer.get()
        if buf is None:
            logger.info(
                "model_usage.unbuffered",
                extra={"model_usage": asdict(rec), "cost_cents_est": cents},
            )
            return
        buf.append(rec)

    # ── job side ────────────────────────────────────────────────────────
    @staticmethod
    def begin() -> None:
        """Start buffering for the current task (the runner calls this per job)."""
        _buffer.set([])

    @staticmethod
    def drain() -> list[UsageRecord]:
        buf = _buffer.get() or []
        _buffer.set(None)
        return buf

    async def flush(
        self,
        conn: asyncpg.Connection,
        *,
        tenant_id: UUID,
        job_id: UUID | None,
        records: list[UsageRecord],
    ) -> int:
        """Insert buffered records under the job's tenant transaction."""
        if not records:
            return 0
        rows = [
            (
                tenant_id,
                job_id,
                r.backend,
                r.model_id,
                r.operation,
                r.ok,
                r.error_kind,
                r.input_tokens,
                r.output_tokens,
                round(r.audio_seconds, 3),
                r.latency_ms,
                r.attempts,
                r.structured_mode,
                self._costs.estimate_cents(r),
            )
            for r in records
        ]
        await conn.executemany(_INSERT, rows)
        return len(rows)
