"""Alert rules parse, the contract rule names exist with fixed severities, and every metric is one the service emits."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[4]
RULES = REPO / "infra" / "prometheus" / "rules" / "autocomplete.yml"
SRC = REPO / "services" / "autocomplete-service" / "src"

EXPECTED = {
    "AutocompleteSuggestLatencyHigh": "page",
    "AutocompleteCacheHitRatioLow": "warn",
    "AutocompleteScrubberRedactionSpike": "warn",
    "AutocompletePhraseWritePiiRejectionSpike": "warn",
    "AutocompleteRollupMissed": "page",
}


def _rules() -> list[dict]:
    doc = yaml.safe_load(RULES.read_text("utf-8"))
    (group,) = doc["groups"]
    return group["rules"]


def test_five_rules_with_fixed_names_and_severities():
    rules = {r["alert"]: r for r in _rules()}
    assert set(rules) == set(EXPECTED)
    for name, severity in EXPECTED.items():
        assert rules[name]["labels"]["severity"] == severity, name
        assert "runbook" in rules[name]["annotations"], f"{name} missing runbook anchor"


def test_rules_are_loaded_from_the_directory_prometheus_actually_reads():
    # Prometheus mounts infra/prometheus/rules; a rules file anywhere else never loads.
    assert RULES.exists()


def test_every_metric_referenced_is_actually_emitted():
    emitted = set()
    for p in SRC.rglob("*.py"):
        emitted.update(re.findall(r'"(mdx_autocomplete_[a-z0-9_]+)"', p.read_text("utf-8")))
    # histogram instruments export _bucket/_count/_sum
    for h in [
        m for m in emitted if "histogram" in m or m.endswith("_seconds") or m.endswith("_bytes")
    ]:
        emitted.update({f"{h}_bucket", f"{h}_count", f"{h}_sum"})

    text = RULES.read_text("utf-8")
    referenced = set(re.findall(r"(mdx_autocomplete_[a-z0-9_]+)", text))
    unknown = referenced - emitted
    assert not unknown, f"alert rules reference metrics nothing emits: {sorted(unknown)}"
