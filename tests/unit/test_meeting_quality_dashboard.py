"""The admin "Meeting quality" dashboard: generated JSON, every panel on the funnel_reader
datasource, no content column queried or granted, dev Grafana local with sign-up off.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "build_meeting_quality_dashboard",
    REPO / "scripts" / "grafana" / "build_meeting_quality_dashboard.py",
)
assert _spec is not None and _spec.loader is not None
builder = importlib.util.module_from_spec(_spec)
sys.modules["build_meeting_quality_dashboard"] = builder
_spec.loader.exec_module(builder)

DASHBOARD = REPO / "infra" / "grafana" / "dashboards" / "meeting-quality.json"
MIGRATION = (REPO / "infra" / "postgres" / "migrations" / "0067_meeting_quality.sql").read_text()
CONTENT = (
    "title",
    "text",
    "vocabulary_hint",
    "speaker_names",
    "previous_speaker_names",
    "speaker_name_candidates",
    "error_detail",
    "to_text",
    "from_forms",
    "occurrences",
    "decided_by",
    "content_jsonb",
    "failed_ranges",
    "snapshot_key",
    "requested_by",
    "requester_sub",
)


def _sql() -> list[str]:
    return [re.sub(r"--[^\n]*", "", s) for s in builder.ALL_SQL]


def test_json_is_in_sync_with_the_generator() -> None:
    assert builder.main(["--check"]) == 0


def test_every_panel_reads_the_funnel_reader_datasource() -> None:
    d = json.loads(DASHBOARD.read_text())
    assert d["uid"] == "meeting-quality" and "admin" in d["tags"]
    for panel in d["panels"]:
        assert panel["datasource"] == {"type": "postgres", "uid": "funnel"}, panel["title"]
        for target in panel["targets"]:
            assert target["datasource"]["uid"] == "funnel"
            assert "$__timeFilter(" in target["rawSql"], panel["title"]


def test_no_query_reads_a_content_column() -> None:
    for sql in _sql():
        for column in CONTENT:
            assert not re.search(rf"\.{column}\b", sql), (column, sql[:80])
        # jsonb keys are read with ->> from quality/stats/metadata only
        for obj in re.findall(r"\b([a-z])\.([a-z_]+)\s*->", sql):
            assert obj[1] in {"quality", "stats", "metadata"}, obj


def test_the_grants_leave_out_every_content_column() -> None:
    grants = " ".join(re.findall(r"GRANT SELECT \(([^)]*)\)", MIGRATION))
    for column in CONTENT:
        assert not re.search(rf"\b{column}\b", grants), column
    # A whole-table grant would reach content columns.
    assert not re.search(r"GRANT SELECT ON", MIGRATION)


def test_dev_grafana_is_local_with_signup_and_anonymous_off() -> None:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    grafana = compose["services"]["grafana"]
    env = grafana["environment"]
    assert str(env["GF_USERS_ALLOW_SIGN_UP"]).lower() == "false"
    assert str(env.get("GF_AUTH_ANONYMOUS_ENABLED", "false")).lower() == "false"
    assert all(str(p).startswith("127.0.0.1:") for p in grafana["ports"])
