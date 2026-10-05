#!/usr/bin/env python3
"""Build infra/grafana/dashboards/meeting-quality.json (the admin view).

    uv run python scripts/grafana/build_meeting_quality_dashboard.py          # write
    uv run python scripts/grafana/build_meeting_quality_dashboard.py --check  # CI: in sync?

One row per real recording: how the transcript went (duration, language,
confidence, coverage, guards, speakers, spellings) and how the note went
(writer, model, prompt version, facts, unsupported lines, open lint
findings). Every query runs as ``funnel_reader`` (migrations 0046/0060/0067),
whose column grants stop at metadata: no transcript text, no note text, no
title, no name or spelling can be selected. The SQL lives here, not inline
in the JSON, so it can be read and reviewed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "infra" / "grafana" / "dashboards" / "meeting-quality.json"
DS = {"type": "postgres", "uid": "funnel"}

# The writer's latest attempt per note, and spelling decisions per job.
_GEN = """gen AS (
    SELECT DISTINCT ON (g.note_id)
           g.note_id, g.status, g.backend, g.model_id, g.prompt_version, g.stats,
           g.windows_failed, g.error_kind,
           EXTRACT(EPOCH FROM (g.finished_at - g.created_at)) AS seconds
      FROM note_generations g
     ORDER BY g.note_id, g.created_at DESC
)"""
_CORR = """corr AS (
    SELECT c.job_id,
           count(*) FILTER (WHERE c.status = 'accepted') AS accepted,
           count(*) FILTER (WHERE c.status = 'proposed') AS proposed,
           count(*) FILTER (WHERE c.status = 'rejected') AS rejected
      FROM transcript_corrections c
     GROUP BY c.job_id
)"""


# Sum of a jsonb object's integer values (e.g. {"loop": 2, "artefact": 1}).
def _jsum(expr: str) -> str:
    return (
        f"(SELECT coalesce(sum(v::int), 0) FROM jsonb_each_text(coalesce({expr}, '{{}}')) x(k, v))"
    )


_MODEL = "regexp_replace(coalesce(j.quality->>'model', j.metadata->>'model'), '^.*/models/([^/]+)/.*$', '\\1')"

MEETINGS_SQL = f"""-- One row per recording in the time range, newest first. Numbers only.
WITH {_GEN},
{_CORR}
SELECT coalesce(j.finished_at, j.queued_at)                         AS "Finished",
       coalesce(n.code, '—')                                         AS "Note",
       t.name                                                        AS "Workspace",
       j.status                                                      AS "ASR",
       round((j.quality->>'audio_s')::numeric / 60, 1)               AS "Min",
       coalesce(j.detected_language, j.language)                     AS "Lang",
       {_MODEL}                                                      AS "ASR model",
       (j.quality->>'rtf')::numeric                                  AS "RTF",
       (j.quality->>'coverage_share')::numeric                       AS "Coverage",
       (j.quality->>'avg_confidence')::numeric                       AS "Confidence",
       (j.quality->>'low_confidence_word_share')::numeric            AS "Low-conf words",
       (j.quality->>'speakers')::int                                 AS "Speakers",
       (j.quality->>'diarization_unknown_share')::numeric            AS "Unknown speaker",
       {_jsum("j.quality->'dropped'")}                               AS "Dropped",
       (j.quality->>'prompt_echo_spans')::int                        AS "Echo",
       (j.quality->>'backend_errors')::int                           AS "Backend err",
       coalesce(c.accepted, 0) || ' / ' || coalesce(c.proposed, 0)
           || ' / ' || coalesce(c.rejected, 0)                       AS "Spellings ✓/?/✗",
       g.status                                                      AS "Note status",
       g.backend                                                     AS "Writer",
       g.model_id                                                    AS "Writer model",
       g.prompt_version                                              AS "Prompt",
       round(g.seconds::numeric)                                     AS "Note s",
       (g.stats->>'facts_kept')::int                                 AS "Facts",
       (g.stats->>'key_points')::int                                 AS "Key points",
       (g.stats->'facts_by_third'->>0) || ' / ' || (g.stats->'facts_by_third'->>1)
           || ' / ' || (g.stats->'facts_by_third'->>2)               AS "Facts by third",
       {_jsum("g.stats->'lines_unsupported'")}                       AS "Unsupported",
       {_jsum("g.stats->'lint'->'unresolved_hard'")}                 AS "Lint open",
       g.stats->>'recording_type'                                    AS "Type",
       coalesce(g.error_kind, j.error_kind)                          AS "Error"
  FROM transcription_jobs j
  JOIN tenants t ON t.id = j.tenant_id
  LEFT JOIN notes n ON n.source_asr_job_id = j.id AND n.deleted_at IS NULL
  LEFT JOIN gen g ON g.note_id = n.id
  LEFT JOIN corr c ON c.job_id = j.id
 WHERE $__timeFilter(j.queued_at)
 ORDER BY coalesce(j.finished_at, j.queued_at) DESC
 LIMIT 500"""

STAT_SQL = {
    "Recordings": "SELECT count(*) FROM transcription_jobs j WHERE $__timeFilter(j.queued_at)",
    "Minutes transcribed": (
        "SELECT round(coalesce(sum((j.quality->>'audio_s')::numeric), 0) / 60) "
        "FROM transcription_jobs j WHERE j.status = 'complete' AND $__timeFilter(j.queued_at)"
    ),
    "Mean coverage": (
        "SELECT avg((j.quality->>'coverage_share')::numeric) FROM transcription_jobs j "
        "WHERE j.status = 'complete' AND $__timeFilter(j.queued_at)"
    ),
    "Mean confidence": (
        "SELECT avg((j.quality->>'avg_confidence')::numeric) FROM transcription_jobs j "
        "WHERE j.status = 'complete' AND $__timeFilter(j.queued_at)"
    ),
    "Notes written": (
        "SELECT count(*) FROM note_generations g "
        "WHERE g.status = 'complete' AND $__timeFilter(g.created_at)"
    ),
    "Failures": (
        "SELECT (SELECT count(*) FROM transcription_jobs j "
        "WHERE j.status = 'failed' AND $__timeFilter(j.queued_at)) "
        "+ (SELECT count(*) FROM note_generations g "
        "WHERE g.status = 'failed' AND $__timeFilter(g.created_at))"
    ),
}

TRANSCRIPT_TS_SQL = """-- Per recording: how much of the speech made it, and how sure the model was.
SELECT j.finished_at AS time,
       (j.quality->>'coverage_share')::numeric            AS "coverage",
       (j.quality->>'avg_confidence')::numeric            AS "confidence",
       (j.quality->>'low_confidence_word_share')::numeric AS "low-confidence words",
       (j.quality->>'diarization_unknown_share')::numeric AS "unknown speaker"
  FROM transcription_jobs j
 WHERE j.status = 'complete' AND j.quality IS NOT NULL AND $__timeFilter(j.finished_at)
 ORDER BY 1"""

NOTE_TS_SQL = f"""-- Per note (the writer's latest attempt): what it kept and what it could not support.
WITH {_GEN}
SELECT n.created_at AS time,
       (g.stats->>'facts_kept')::int                    AS "facts",
       (g.stats->>'key_points')::int                    AS "key points",
       {_jsum("g.stats->'lines_unsupported'")}          AS "unsupported lines",
       {_jsum("g.stats->'lint'->'unresolved_hard'")}    AS "open lint findings"
  FROM gen g
  JOIN notes n ON n.id = g.note_id
 WHERE g.status = 'complete' AND $__timeFilter(n.created_at)
 ORDER BY 1"""

SPEED_TS_SQL = f"""-- Per recording: transcription real-time factor (lower is faster) and the note's seconds.
WITH {_GEN}
SELECT j.finished_at AS time,
       (j.quality->>'rtf')::numeric   AS "ASR RTF",
       g.seconds                      AS "note seconds"
  FROM transcription_jobs j
  LEFT JOIN notes n ON n.source_asr_job_id = j.id AND n.deleted_at IS NULL
  LEFT JOIN gen g ON g.note_id = n.id
 WHERE j.status = 'complete' AND j.quality IS NOT NULL AND $__timeFilter(j.finished_at)
 ORDER BY 1"""

GUARDS_TS_SQL = f"""-- Per recording: what the transcript guards removed or flagged (TQ2).
SELECT j.finished_at AS time,
       {_jsum("j.quality->'dropped'")}                     AS "dropped segments",
       {_jsum("j.quality->'loops'")}                       AS "loops",
       (j.quality->>'prompt_echo_spans')::int             AS "prompt echo",
       (j.quality->>'backend_errors')::int                AS "backend errors",
       (j.quality->>'other_language_chunks')::int         AS "other-language chunks"
  FROM transcription_jobs j
 WHERE j.status = 'complete' AND j.quality IS NOT NULL AND $__timeFilter(j.finished_at)
 ORDER BY 1"""

SPELLINGS_SQL = """-- Spelling unification (TQ3): how often each source fired and what people decided.
SELECT c.source AS "Source",
       count(*) FILTER (WHERE c.status = 'accepted') AS "Accepted",
       count(*) FILTER (WHERE c.status = 'proposed') AS "Proposed",
       count(*) FILTER (WHERE c.status = 'rejected') AS "Rejected",
       round(avg(c.confidence), 3)                   AS "Mean confidence"
  FROM transcript_corrections c
 WHERE $__timeFilter(c.created_at)
 GROUP BY c.source
 ORDER BY 2 DESC"""

FAILURES_SQL = """-- What failed, by stage and error kind.
SELECT 'transcript' AS "Stage", coalesce(j.error_kind, '—') AS "Error kind", count(*) AS "Count"
  FROM transcription_jobs j
 WHERE j.status = 'failed' AND $__timeFilter(j.queued_at)
 GROUP BY 2
UNION ALL
SELECT 'note', coalesce(g.error_kind, '—'), count(*)
  FROM note_generations g
 WHERE g.status = 'failed' AND $__timeFilter(g.created_at)
 GROUP BY 2
 ORDER BY 3 DESC"""

ALL_SQL = [
    MEETINGS_SQL,
    *STAT_SQL.values(),
    TRANSCRIPT_TS_SQL,
    NOTE_TS_SQL,
    SPEED_TS_SQL,
    GUARDS_TS_SQL,
    SPELLINGS_SQL,
    FAILURES_SQL,
]


def _target(sql: str, fmt: str) -> dict[str, Any]:
    return {
        "refId": "A",
        "datasource": DS,
        "format": fmt,
        "rawQuery": True,
        "editorMode": "code",
        "rawSql": sql,
    }


def _unit_override(names: list[str], unit: str) -> dict[str, Any]:
    return {
        "matcher": {"id": "byRegexp", "options": "^(" + "|".join(names) + ")$"},
        "properties": [{"id": "unit", "value": unit}],
    }


def build() -> dict[str, Any]:
    panels: list[dict[str, Any]] = []
    pid = 1

    def add(panel: dict[str, Any]) -> None:
        nonlocal pid
        panel["id"] = pid
        panel["datasource"] = DS
        pid += 1
        panels.append(panel)

    share_units = {"Mean coverage": "percentunit", "Mean confidence": "percentunit"}
    for i, (title, sql) in enumerate(STAT_SQL.items()):
        add(
            {
                "type": "stat",
                "title": title,
                "gridPos": {"x": i * 4, "y": 0, "w": 4, "h": 4},
                "targets": [_target(sql, "table")],
                "fieldConfig": {
                    "defaults": {
                        "unit": share_units.get(title, "none"),
                        "decimals": 1 if title in share_units else 0,
                    },
                    "overrides": [],
                },
                "options": {
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "colorMode": "value",
                    "graphMode": "none",
                    "textMode": "value",
                },
            }
        )
    add(
        {
            "type": "table",
            "title": "Meetings — one row per recording (transcript, then note)",
            "description": (
                "Numbers only, read as funnel_reader. Coverage = share of detected speech that was "
                "transcribed. Dropped = segments the guards removed. Spellings = unified names "
                "accepted / proposed / rejected. Facts by third = key facts from the first, middle and "
                "last third of the recording. Unsupported = written lines the verifier could not "
                "ground. Lint open = hard document-standard findings left unresolved."
            ),
            "gridPos": {"x": 0, "y": 4, "w": 24, "h": 14},
            "targets": [_target(MEETINGS_SQL, "table")],
            "fieldConfig": {
                "defaults": {"custom": {"align": "auto", "filterable": True}},
                "overrides": [
                    _unit_override(
                        ["Coverage", "Confidence", "Low-conf words", "Unknown speaker"],
                        "percentunit",
                    ),
                    _unit_override(["Finished"], "dateTimeAsLocal"),
                ],
            },
            "options": {
                "showHeader": True,
                "footer": {"show": False},
                "sortBy": [{"displayName": "Finished", "desc": True}],
            },
        }
    )
    ts_defaults = {
        "custom": {
            "drawStyle": "line",
            "showPoints": "always",
            "pointSize": 6,
            "lineWidth": 1,
            "spanNulls": True,
        }
    }
    for title, sql, x, y, unit in [
        ("Transcript per recording", TRANSCRIPT_TS_SQL, 0, 18, "percentunit"),
        ("Note per recording", NOTE_TS_SQL, 12, 18, "none"),
        ("Speed per recording", SPEED_TS_SQL, 0, 26, "none"),
        ("Transcript guards per recording", GUARDS_TS_SQL, 12, 26, "none"),
    ]:
        add(
            {
                "type": "timeseries",
                "title": title,
                "gridPos": {"x": x, "y": y, "w": 12, "h": 8},
                "targets": [_target(sql, "time_series")],
                "fieldConfig": {"defaults": {**ts_defaults, "unit": unit}, "overrides": []},
                "options": {
                    "legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi"},
                },
            }
        )
    for title, sql, x in [
        ("Spelling unification by source", SPELLINGS_SQL, 0),
        ("Failures by stage and kind", FAILURES_SQL, 12),
    ]:
        add(
            {
                "type": "table",
                "title": title,
                "gridPos": {"x": x, "y": 34, "w": 12, "h": 7},
                "targets": [_target(sql, "table")],
                "fieldConfig": {"defaults": {}, "overrides": []},
                "options": {"showHeader": True},
            }
        )
    return {
        "title": "Meeting quality (admin)",
        "uid": "meeting-quality",
        "description": (
            "Admin-only: how each real recording's transcript and note went. Numbers only — "
            "built by scripts/grafana/build_meeting_quality_dashboard.py."
        ),
        "schemaVersion": 39,
        "tags": ["notes", "quality", "admin"],
        "time": {"from": "now-30d", "to": "now"},
        "refresh": "1m",
        "editable": False,
        "panels": panels,
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if the JSON is out of date")
    ns = ap.parse_args(argv)
    text = render()
    if ns.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(
                f"{OUT.relative_to(REPO)} is out of date; run {Path(__file__).name}",
                file=sys.stderr,
            )
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
