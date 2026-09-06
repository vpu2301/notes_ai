from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from jobs import CostTable, UsageLedger
from models import UsageRecord, emit, set_usage_sink

REPO_COSTS = Path(__file__).resolve().parents[4] / "config" / "model_costs.yaml"


def _rec(**kw: Any) -> UsageRecord:
    base: dict[str, Any] = {
        "backend": "hf_eu",
        "model_id": "google/gemma-3-4b-it",
        "operation": "chat.complete",
        "ok": True,
        "latency_ms": 1200,
        "input_tokens": 3000,
        "output_tokens": 500,
    }
    base.update(kw)
    return UsageRecord(**base)


def test_repo_cost_table_loads_and_prices_hf() -> None:
    t = CostTable.load(REPO_COSTS)
    assert t.currency == "EUR"
    assert t.is_priced("hf_eu") and t.is_priced("hf_eu_asr")
    assert not t.is_priced("hosted_eu") and not t.is_priced("anthropic")
    assert t.estimate_cents(_rec()) == pytest.approx(3 * 0.08 + 0.5 * 0.83, abs=1e-4)
    assert t.estimate_cents(
        _rec(
            backend="hf_eu_asr",
            operation="asr.transcribe",
            input_tokens=0,
            output_tokens=0,
            audio_seconds=600,
        )
    ) == pytest.approx(10 * 0.04, abs=1e-4)
    assert t.estimate_cents(_rec(backend="dev_mac")) == 0.0
    assert t.estimate_cents(_rec(attempts=3)) == pytest.approx(3 * 0.08 + 0.5 * 0.83 + 6, abs=1e-4)


def test_unknown_backend_costs_zero_and_is_unpriced() -> None:
    t = CostTable.empty()
    assert t.estimate_cents(_rec(backend="whatever")) == 0.0 and not t.is_priced("whatever")


class _Conn:
    def __init__(self) -> None:
        self.rows: list[tuple[Any, ...]] = []
        self.sql = ""

    async def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        self.sql = sql
        self.rows.extend(rows)


async def test_ledger_buffers_per_job_and_flushes_rows_without_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ledger = UsageLedger(CostTable.load(REPO_COSTS))
    ledger.install()
    try:
        ledger.begin()
        emit(_rec(workspace_id="ws-1"))
        emit(_rec(ok=False, error_kind="timeout", output_tokens=0))
        records = ledger.drain()
        assert len(records) == 2 and ledger.drain() == []
        conn = _Conn()
        tenant, job = uuid4(), uuid4()
        n = await ledger.flush(conn, tenant_id=tenant, job_id=job, records=records)  # type: ignore[arg-type]
        assert n == 2 and "INSERT INTO model_usage" in conn.sql
        first = conn.rows[0]
        assert first[0] == tenant and first[1] == job and first[2] == "hf_eu" and first[5] is True
        assert conn.rows[1][6] == "timeout" and conn.rows[1][5] is False
        assert conn.rows[0][13] > 0  # cost_cents_est
        blob = json.dumps([str(x) for row in conn.rows for x in row])
        assert "Phoenix" not in blob  # no content ever
    finally:
        set_usage_sink(None)


def test_unbuffered_records_are_logged_not_lost(caplog: pytest.LogCaptureFixture) -> None:
    ledger = UsageLedger(CostTable.empty())
    ledger.install()
    try:
        ledger.drain()  # ensure no buffer
        with caplog.at_level(logging.INFO, logger="jobs.ledger"):
            emit(_rec())
    finally:
        set_usage_sink(None)
    assert any(r.getMessage() == "model_usage.unbuffered" for r in caplog.records)
