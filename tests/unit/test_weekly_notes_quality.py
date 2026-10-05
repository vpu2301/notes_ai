"""The weekly notes-quality report (Summary Engine v2, Q6 T8): counts only,
never content, with the concept's kill thresholds printed next to them."""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "weekly_notes_quality", REPO / "scripts" / "jobs" / "weekly_notes_quality.py"
)
assert _spec is not None and _spec.loader is not None
weekly = importlib.util.module_from_spec(_spec)
sys.modules["weekly_notes_quality"] = weekly
_spec.loader.exec_module(weekly)

SQL_TEXT = (REPO / "scripts" / "ops" / "notes_quality.sql").read_text(encoding="utf-8")
SQL_CODE = re.sub(r"--[^\n]*", "", SQL_TEXT)
MIGRATION = (
    REPO / "infra" / "postgres" / "migrations" / "0060_notes_quality_reader.sql"
).read_text(encoding="utf-8")

# Migration 0060's column-level grants, by the alias the SQL uses.
GRANTED = {
    # `g` is also the `gens` CTE, which adds what it computes from those.
    "g": {"id", "tenant_id", "note_id", "reason", "status", "stats", "created_at", "finished_at"}
    | {"week", "recording_type", "language"},
    "r": {"id", "tenant_id", "note_id", "reason", "status", "stats", "created_at", "finished_at"},
    "i": {
        "id",
        "tenant_id",
        "note_id",
        "generation_id",
        "item_key",
        "kind",
        "placement",
        "created_at",
    },
    "c": {"id", "tenant_id", "note_id", "item_key", "kind", "action", "reason", "created_at"},
    "m": {
        "note_id",
        "tenant_id",
        "meeting_type",
        "meeting_type_detected",
        "detected_by",
        "created_at",
    },
}
CONTENT = (
    "quote",
    "speaker_name",
    "owner_label",
    "due_text",
    "attributed_to",
    "mentions",
    "calendar_context",
    "content_jsonb",
    "rendered_text",
    "actor_sub",
    "title",
)
METRICS = {
    "kept_line_rate",
    "dismiss_rate",
    "dismiss_reason",
    "dismiss_code",
    "regenerate_rate",
    "share_without_edit",
    "minutes_to_first_share",
    "corrections_accepted",
    "type_changed",
    "title_changed",
}


def test_sql_reads_no_content_column() -> None:
    for column in CONTENT:
        assert not re.search(rf"\.{column}\b", SQL_CODE), column
    # A line's text is read only inside 0060's functions, never by the role.
    assert not re.search(r"\bi\.text\b", SQL_CODE)


def test_sql_reads_only_granted_columns() -> None:
    for alias, granted in GRANTED.items():
        referenced = set(re.findall(rf"\b{alias}\.([a-z_]+)", SQL_CODE))
        assert referenced <= granted, (alias, referenced - granted)


def test_the_grants_leave_out_every_content_column() -> None:
    grants = " ".join(re.findall(r"GRANT SELECT \(([^)]*)\)", MIGRATION))
    for column in ("text", "quote", "corrections", "mentions", "calendar_context", "actor_sub"):
        assert not re.search(rf"\b{column}\b", grants), column


def test_content_is_read_only_through_count_functions() -> None:
    for fn in (
        "notes_quality_kept_lines",
        "notes_quality_shares",
        "notes_quality_corrections_offered",
    ):
        block = MIGRATION[MIGRATION.index(f"FUNCTION {fn}()") :]
        header = block[: block.index("AS $$")]
        assert "SECURITY DEFINER" in header and "SET search_path" in header
        # ids, integers, timestamps and booleans only
        returns = header[
            header.index("RETURNS TABLE") : header.index("\n", header.index("RETURNS TABLE"))
        ]
        assert not re.search(r"\bTEXT\b|JSONB", returns), returns
        assert f"REVOKE ALL ON FUNCTION {fn}() FROM PUBLIC" in MIGRATION
        assert f"GRANT EXECUTE ON FUNCTION {fn}() TO funnel_reader" in MIGRATION


def test_every_metric_the_sprint_names_is_produced() -> None:
    produced = set(re.findall(r"'([a-z_]+)'(?:\s+AS metric)?,", SQL_CODE)) & METRICS
    assert produced == METRICS


def test_the_output_has_no_workspace_id() -> None:
    final = SQL_CODE[SQL_CODE.rindex("\nSELECT week") :]
    assert "tenant_id" not in final and "note_id" not in final


def test_kept_lines_are_read_seven_days_after_the_generation() -> None:
    assert "g.finished_at <  now() - interval '7 days'" in MIGRATION
    assert "g.finished_at + interval '7 days'" in MIGRATION


def test_report_is_named_by_iso_week(tmp_path: Path) -> None:
    now = datetime(2027, 1, 1, 6, 45, tzinfo=UTC)
    assert weekly.report_path(tmp_path, now).name == "notes-quality-2026-53.csv"


def _row(metric: str, week: str, value: float, num: int = 1, den: int = 2) -> dict:
    return {
        "week": date.fromisoformat(week),
        "dimension": "all",
        "bucket": "all",
        "metric": metric,
        "numerator": num,
        "denominator": den,
        "value": value,
    }


def test_headline_prints_thresholds_and_verdicts() -> None:
    now = datetime(2026, 10, 19, 6, 45, tzinfo=UTC)  # a Monday
    rows = [
        _row("kept_line_rate", "2026-10-05", 42.0, 42, 100),  # one week further back
        _row("regenerate_rate", "2026-10-12", 25.0, 1, 4),
        _row("share_without_edit", "2026-10-12", 60.0, 3, 5),
    ]
    text = "\n".join(weekly.headline(rows, now))
    assert "week of 2026-10-12" in text
    assert "kept_line_rate           42.0 % (42/100)  [threshold ≥ 50 %: BELOW" in text
    assert "regenerate_rate          25.0 % (1/4)  [threshold ≤ 40 %: ok" in text
    assert "not send-ready unless above the baseline week" in text
    assert "dismiss_rate             no data" in text
    assert "evidence_opened_per_line  not reported" in text


def test_csv_keeps_the_header_for_an_empty_week(tmp_path: Path) -> None:
    cols = ["week", "dimension", "bucket", "metric", "numerator", "denominator", "value"]
    target = weekly.write_csv(cols, [], tmp_path / "out", datetime(2026, 9, 21, tzinfo=UTC))
    assert target.read_text(encoding="utf-8").strip() == ",".join(cols)


def test_main_refuses_without_database_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert asyncio.run(weekly.main(tmp_path)) == 2
    assert not list(tmp_path.iterdir())


# ── Error taxonomy (docs/eval/error-taxonomy.md) ────────────────────


def test_dismissals_are_counted_by_the_taxonomy_code_of_their_reason() -> None:
    spec = importlib.util.spec_from_file_location(
        "taxonomy", REPO / "scripts" / "eval" / "taxonomy.py"
    )
    assert spec and spec.loader
    taxonomy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(taxonomy)
    in_sql = dict(re.findall(r"WHEN '([a-z_]+)'\s+THEN '([A-Z]-[A-Z]+)'", SQL_TEXT))
    assert in_sql == taxonomy.REASON_CODES
    route = (
        REPO / "services" / "note-service" / "src" / "note_service" / "routers"
        / "notes_corrections.py"
    ).read_text("utf-8")  # fmt: skip
    block = route[
        route.index("DismissReason = Literal[") : route.index("]", route.index("DismissReason"))
    ]
    assert set(re.findall(r'"([a-z_]+)"', block)) == set(taxonomy.REASON_CODES)
    assert set(taxonomy.REASON_CODES.values()) <= set(taxonomy.CODES)


def _code_row(code: str, week: str, value: float) -> dict:
    return {**_row("dismiss_code", week, value), "dimension": "code", "bucket": code}


def test_a_code_rising_two_weeks_running_is_flagged() -> None:
    now = datetime(2026, 10, 19, 6, 45, tzinfo=UTC)
    rows = [
        _code_row("F-INV", "2026-09-28", 10.0),
        _code_row("F-INV", "2026-10-05", 12.0),
        _code_row("F-INV", "2026-10-12", 15.0),
        _code_row("F-ATTR", "2026-09-28", 10.0),
        _code_row("F-ATTR", "2026-10-05", 20.0),
        _code_row("F-ATTR", "2026-10-12", 5.0),
    ]
    text = "\n".join(weekly.headline(rows, now))
    assert "dismiss codes rising two weeks running: F-INV  [open a sprint item]" in text
    assert "F-ATTR" not in text
    assert "rising two weeks running: none" in "\n".join(weekly.headline([], now))
