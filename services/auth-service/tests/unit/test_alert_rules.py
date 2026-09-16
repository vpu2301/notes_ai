"""IDX-B3 H — the alert rules stay loadable and on-contract.

The important test is the last one. A rule that names a metric nothing
exports never fires, and on a dashboard "never fires" is
indistinguishable from "no problem" — which is precisely how the
sprint-08 and sprint-10 incidents went unnoticed. It has one loud
failure mode too: an alert written as `(sum(...) or vector(0)) == 0`
against an absent series evaluates to 0 and pages continuously about a
healthy system.

So: every `mdx_auth_*` metric referenced by a rule must be a string that
appears in a `create_*` call in auth-service's source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[4]
RULES = REPO / "infra" / "prometheus" / "rules" / "auth-audit.yml"
SRC = REPO / "services" / "auth-service" / "src"
LIBS = REPO / "libs"
# Not every mdx_* series comes from a service. The audit-chain gauges are
# written by a Prometheus textfile exporter run out of band — the same
# exception `scripts/ci/check-metric-names.py` documents. Scanning the
# real producers beats an exemption list that goes stale.
EXPORTERS = (REPO / "scripts" / "jobs", REPO / "infra" / "k8s" / "notes" / "files" / "jobs")

# The IDX rules, and the severity each is contracted at. Pinned so a
# well-meaning downgrade of DenylistPushFailed shows up in review.
IDX_RULES = {
    "OtpVerifyFailureRatioHigh": "warning",
    "OtpStartRateLimitedBurst": "warning",
    "AccountLockoutBurst": "warning",
    "ClientCredentialsFailureBurst": "warning",
    "DenylistPushFailed": "critical",
    "AuthMaintenanceStale": "warning",
    "EmailSendFailures": "warning",
    "MfaVerifyFailureBurst": "warning",
    "RecoveryCodeUsageSpike": "warning",
}

# Prometheus suffixes an OTel histogram into three series and a counter
# into one; a rule may legitimately name any of them.
_SUFFIXES = ("_bucket", "_count", "_sum", "_total")


def _groups() -> dict[str, list[dict]]:
    doc = yaml.safe_load(RULES.read_text("utf-8"))
    return {g["name"]: g["rules"] for g in doc["groups"]}


def _emitted_metrics() -> set[str]:
    """Every metric name auth-service (or a lib it uses) actually creates."""
    names: set[str] = set()
    # Service code declares a metric as a quoted instrument name; a
    # textfile exporter writes `# TYPE <name> gauge` lines instead.
    pattern = re.compile(r'"(mdx_[a-z0-9_]+)"|#\s*TYPE\s+(mdx_[a-z0-9_]+)')
    for root in (SRC, LIBS, *EXPORTERS):
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts or "/tests/" in path.as_posix():
                continue
            for quoted, typed in pattern.findall(path.read_text("utf-8", errors="ignore")):
                names.add(quoted or typed)
    return names


def test_the_rules_file_parses_and_has_the_idx_group() -> None:
    groups = _groups()
    assert "auth-idx" in groups, "the IDX rules must live in their own group"
    assert len(groups["auth-idx"]) == len(IDX_RULES)


def test_every_idx_rule_exists_with_its_contracted_severity() -> None:
    rules = {r["alert"]: r for r in _groups()["auth-idx"]}
    assert set(rules) == set(IDX_RULES)
    for name, severity in IDX_RULES.items():
        assert rules[name]["labels"]["severity"] == severity, name


def test_every_rule_has_a_runbook_anchor() -> None:
    """An alert without somewhere to go is a page that wakes somebody for
    nothing they can act on."""
    for group in _groups().values():
        for rule in group:
            anchor = rule["annotations"].get("runbook", "")
            assert anchor, f"{rule['alert']} has no runbook annotation"
            doc, _, fragment = anchor.partition("#")
            assert (REPO / doc).exists(), f"{rule['alert']} → missing {doc}"
            assert fragment, f"{rule['alert']} → {doc} with no anchor"
            # The anchor must actually be a heading in that document. A
            # link into nothing sends whoever is paged at 3am to the top
            # of a long runbook to search.
            headings = {
                re.sub(r"[^a-z0-9]+", "-", line.lstrip("#").strip().lower()).strip("-")
                for line in (REPO / doc).read_text("utf-8").splitlines()
                if line.startswith("#")
            }
            assert fragment in headings, (
                f"{rule['alert']} → {doc}#{fragment} is not a heading there"
            )


@pytest.mark.parametrize("group_name", ["auth", "audit", "auth-idx"])
def test_every_metric_referenced_is_actually_emitted(group_name: str) -> None:
    emitted = _emitted_metrics()
    referenced: set[str] = set()
    for rule in _groups()[group_name]:
        referenced.update(re.findall(r"\b(mdx_[a-z0-9_]+)", rule["expr"]))

    missing = set()
    for name in referenced:
        if name in emitted:
            continue
        # A rule may name the exporter's suffixed form of a declared
        # instrument (`..._bucket` off a histogram).
        base = next(
            (name[: -len(s)] for s in _SUFFIXES if name.endswith(s) and name[: -len(s)] in emitted),
            None,
        )
        if base is None:
            missing.add(name)

    assert not missing, (
        f"{group_name}: rules reference metrics no code emits: {sorted(missing)}. "
        "A rule on an absent series never fires — and 'never fires' looks "
        "exactly like 'no problem'."
    )
