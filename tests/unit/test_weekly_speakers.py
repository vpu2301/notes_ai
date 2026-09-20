"""The weekly speaker-quality report (Sprint 30): counts only, never content."""

from __future__ import annotations

import asyncio
import csv
import importlib.util
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "weekly_speakers", REPO / "scripts" / "jobs" / "weekly_speakers.py"
)
assert _spec is not None and _spec.loader is not None
weekly_speakers = importlib.util.module_from_spec(_spec)
sys.modules["weekly_speakers"] = weekly_speakers
_spec.loader.exec_module(weekly_speakers)

SQL_TEXT = (REPO / "scripts" / "ops" / "speaker_quality.sql").read_text(encoding="utf-8")
# SQL without its comments: what the database actually runs.
SQL_CODE = re.sub(r"--[^\n]*", "", SQL_TEXT)

# Migration 0046's column-level grant on transcription_jobs.
GRANTED_JOB_COLUMNS = {
    "id",
    "tenant_id",
    "status",
    "finished_at",
    "result_first_read_at",
    "metadata",
    "diarization_rev",
    "diarization_runs",
    "capture_context",
}
CONTENT_COLUMNS = (
    "speaker_names",
    "speaker_name_candidates",
    "previous_speaker_names",
    "result_storage_uri",
    "previous_result_storage_uri",
    "error_detail",
    "requester_sub",
    "actor_sub",
    "segment_indices",
)
# Every output column is a count, a rate, a mean, the week, or one of the
# two closed-vocabulary grouping columns.
EXPECTED_COLUMNS = [
    "week",
    "dimension",
    "bucket",
    "diarized_jobs",
    "opened_jobs",
    "corrected_jobs",
    "correction_rate_pct",
    "jobs_merged",
    "jobs_reassigned",
    "jobs_rediarized",
    "merge_edits",
    "reassign_edits",
    "rediarize_runs",
    "reverted_edits",
    "labels_created",
    "count_scored_jobs",
    "count_error_mean_abs",
    "count_error_mean_signed",
    "overcount_pct",
    "undercount_pct",
    "rediarize_kept",
    "rediarize_kept_then_edited",
    "rediarize_undone",
    "rediarize_failed",
    "rediarize_repeated",
    "rediarize_success_pct",
]


def _output_columns() -> list[str]:
    final_select = SQL_CODE[SQL_CODE.rindex("\nSELECT") : SQL_CODE.rindex("\nFROM per_job")]
    return re.findall(r"\bAS\s+([a-z_]+)\s*,?\s*$", final_select, flags=re.MULTILINE) or []


def test_sql_selects_no_content_column() -> None:
    for column in CONTENT_COLUMNS:
        assert not re.search(rf"\b{column}\b", SQL_CODE), column


def test_sql_reads_only_the_granted_job_columns() -> None:
    referenced = set(re.findall(r"\bj\.([a-z_]+)", SQL_CODE)) - {"*"}
    assert referenced <= GRANTED_JOB_COLUMNS, referenced - GRANTED_JOB_COLUMNS


def test_sql_output_is_counts_and_closed_vocabularies() -> None:
    columns = ["week", "dimension", "bucket", *_output_columns()]
    assert columns == EXPECTED_COLUMNS
    # The only free-form jsonb strings reaching the output are folded
    # into a closed vocabulary or a label-shaped regex.
    assert "'^[a-z0-9._-]{1,40}$'" in SQL_CODE
    assert "IN ('web', 'ios', 'macos')" in SQL_CODE
    assert "IN ('calendar_event', 'manual', 'upload')" in SQL_CODE


def test_sql_evaluates_jobs_seven_days_after_completion() -> None:
    assert "j.finished_at < now() - interval '7 days'" in SQL_CODE


def test_report_is_named_by_iso_week(tmp_path: Path) -> None:
    # 2027-01-01 is a Friday in ISO week 53 of 2026.
    now = datetime(2027, 1, 1, 6, 15, tzinfo=UTC)
    assert weekly_speakers.report_path(tmp_path, now).name == "speakers-2026-53.csv"


def test_csv_keeps_the_header_for_an_empty_cohort(tmp_path: Path) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    target = weekly_speakers.write_csv(EXPECTED_COLUMNS, [], tmp_path / "out", now)
    assert target.read_text(encoding="utf-8").strip() == ",".join(EXPECTED_COLUMNS)


def test_csv_writes_rows_in_column_order_and_overwrites(tmp_path: Path) -> None:
    now = datetime(2026, 9, 21, tzinfo=UTC)
    cols = ["week", "dimension", "bucket", "opened_jobs"]
    weekly_speakers.write_csv(cols, [dict.fromkeys(cols, "x")], tmp_path, now)
    row = {"opened_jobs": 7, "bucket": "all", "week": "2026-09-07", "dimension": "all"}
    target = weekly_speakers.write_csv(cols, [row], tmp_path, now)
    with target.open(encoding="utf-8") as fh:
        assert list(csv.reader(fh)) == [cols, ["2026-09-07", "all", "all", "7"]]


def test_main_refuses_without_database_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert asyncio.run(weekly_speakers.main(tmp_path)) == 2
    assert not list(tmp_path.iterdir())
