from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from jobs import (
    WARMING_BUDGET_FACTOR,
    WARMING_RESCHEDULE_S,
    next_run_at,
    retry_backoff_seconds,
    warming_decision,
)

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)


def test_first_warming_parks_the_job_thirty_seconds_out() -> None:
    d = warming_decision(now=NOW, waiting_since=None, cold_start_seconds=300)
    assert d.wait is True
    assert d.run_at == NOW + timedelta(seconds=WARMING_RESCHEDULE_S)
    assert d.waited_seconds == 0.0 and d.budget_seconds == 300 * WARMING_BUDGET_FACTOR


def test_retry_after_is_honoured_within_bounds() -> None:
    assert warming_decision(
        now=NOW, waiting_since=None, cold_start_seconds=300, retry_after_s=45
    ).run_at == NOW + timedelta(seconds=45)
    assert warming_decision(
        now=NOW, waiting_since=None, cold_start_seconds=300, retry_after_s=600
    ).run_at == NOW + timedelta(seconds=60)
    assert warming_decision(
        now=NOW, waiting_since=None, cold_start_seconds=300, retry_after_s=0
    ).run_at == NOW + timedelta(seconds=30)


@pytest.mark.parametrize(
    ("waited", "wait"), [(0, True), (299, True), (599, True), (600, False), (3600, False)]
)
def test_budget_is_twice_the_cold_start(waited: int, wait: bool) -> None:
    d = warming_decision(
        now=NOW, waiting_since=NOW - timedelta(seconds=waited), cold_start_seconds=300
    )
    assert d.wait is wait


def test_backend_without_cold_start_never_waits() -> None:
    assert warming_decision(now=NOW, waiting_since=None, cold_start_seconds=0).wait is False


def test_backoff_is_exponential_and_capped() -> None:
    assert [retry_backoff_seconds(a) for a in (1, 2, 3, 4)] == [15.0, 30.0, 60.0, 120.0]
    assert retry_backoff_seconds(20) == 900.0
    assert next_run_at(NOW, 2) == NOW + timedelta(seconds=30)
