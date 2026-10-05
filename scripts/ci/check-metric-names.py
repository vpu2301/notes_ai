#!/usr/bin/env python3
"""CI gate: exported metric names equal the declared instrument names. The OTel
Prometheus exporter appends the unit (``_ratio``, ``_milliseconds``) unless
``add_metric_suffixes: false``; a rule on a mangled name never fires, or fires on ``vector(0)``.

Checks every collector config sets the flag and no rule/dashboard queries a mangled name.
Textfile-exporter metrics (nightly_verify.py) need not be declared instruments.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

COLLECTOR_CONFIGS = (
    "infra/otel/otel-collector-config.yaml",
    "infra/k8s/notes/templates/observability.yaml",
)

RULE_DIRS = ("infra/prometheus/rules",)
DASHBOARD_DIRS = ("infra/grafana/dashboards",)

# Unit -> suffix the OTel Prometheus exporter appends ("_ratio" is flagged
# for any instrument, not only gauges).
_UNIT_SUFFIX = {
    "1": "ratio",
    "s": "seconds",
    "ms": "milliseconds",
    "us": "microseconds",
    "ns": "nanoseconds",
    "By": "bytes",
    "MB": "MB",
    "bps": "bps",
}

_INSTRUMENT_RE = re.compile(
    r"create_(?:gauge|counter|up_down_counter|histogram"
    r"|observable_gauge|observable_counter|observable_up_down_counter)\("
    r"\s*\"(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\"(?P<rest>.*?)\)\n",
    re.S,
)
_UNIT_RE = re.compile(r"unit\s*=\s*\"(?P<unit>[^\"]*)\"")
_METRIC_REF_RE = re.compile(r"\bmdx_[a-z0-9_]+")
# Histogram/summary suffixes Prometheus itself appends; stripped before comparing.
_SERIES_SUFFIX_RE = re.compile(r"_(bucket|count|sum)$")


def declared_instruments() -> dict[str, str]:
    """Map instrument name -> unit, over every service and lib."""
    found: dict[str, str] = {}
    for path in ROOT.rglob("*.py"):
        if any(part in {".venv", "__pycache__", "node_modules"} for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "create_" not in source:
            continue
        for match in _INSTRUMENT_RE.finditer(source):
            unit = _UNIT_RE.search(match.group("rest"))
            found[match.group("name")] = unit.group("unit") if unit else ""
    return found


def query_files() -> list[Path]:
    files: list[Path] = []
    for rel in RULE_DIRS:
        files.extend(sorted((ROOT / rel).glob("*.yml")))
        files.extend(sorted((ROOT / rel / "tests").glob("*.yml")))
    for rel in DASHBOARD_DIRS:
        files.extend(sorted((ROOT / rel).glob("*.json")))
    return [f for f in files if f.is_file()]


def check_collector_configs(errors: list[str]) -> None:
    for rel in COLLECTOR_CONFIGS:
        path = ROOT / rel
        if not path.is_file():
            errors.append(f"{rel}: collector config missing")
            continue
        text = path.read_text(encoding="utf-8")
        if not re.search(r"^\s*prometheus:\s*$", text, re.M):
            continue  # no prometheus exporter in this config
        if not re.search(r"^\s*add_metric_suffixes:\s*false\s*$", text, re.M):
            errors.append(
                f"{rel}: prometheus exporter does not set "
                "`add_metric_suffixes: false` — exported names will carry a "
                "unit suffix (_ratio/_milliseconds/...) and every alert rule "
                "will query a series that does not exist"
            )


def check_query_references(instruments: dict[str, str], errors: list[str]) -> None:
    # Longest-first so `mdx_a_b` wins over `mdx_a` when both are declared.
    by_len = sorted(instruments.items(), key=lambda kv: -len(kv[0]))
    for path in query_files():
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        for ref in sorted(set(_METRIC_REF_RE.findall(text))):
            stem = _SERIES_SUFFIX_RE.sub("", ref)
            if stem in instruments:
                continue
            for name, unit in by_len:
                suffix = _UNIT_SUFFIX.get(unit)
                if suffix and stem == f"{name}_{suffix}":
                    errors.append(
                        f"{rel}: queries `{ref}` — that is the instrument "
                        f"`{name}` (unit={unit!r}) with the exporter's unit "
                        f"suffix appended. Query `{name}` and keep "
                        "`add_metric_suffixes: false` in the collector config."
                    )
                    break


def main() -> int:
    errors: list[str] = []
    instruments = declared_instruments()
    if not instruments:
        print("check-metric-names: found no instruments to check", file=sys.stderr)
        return 1
    check_collector_configs(errors)
    check_query_references(instruments, errors)

    if errors:
        print("Metric-name drift (exported name != declared instrument):\n", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        print(
            f"\n{len(errors)} violation(s). See infra/otel/otel-collector-config.yaml for the why.",
            file=sys.stderr,
        )
        return 1

    print(f"check-metric-names: OK ({len(instruments)} instruments checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
