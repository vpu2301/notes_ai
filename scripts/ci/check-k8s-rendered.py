#!/usr/bin/env python3
"""CI gate on the RENDERED Helm chart: it renders for staging and prod, the prod render
is secret-clean with no dev escape hatches, and the chart's vendored ops files match
their source (files/jobs/ <- scripts/jobs/, files/postgres-init.sql <- infra/postgres/init.sql).

Needs ``helm``; SKIP_HELM=1 runs the drift check only.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "infra" / "k8s" / "notes"

FORBIDDEN_LITERALS = ["dev-secret-change-in-prod", "dev-password"]
TRUTHY_FLAGS = re.compile(
    r"(MD_OBJECT_STORE_DISABLED|MDX_DEMO_MODE|AUTH_BYPASS_DEV)"
    r"\W+['\"]?(true|1|yes|on)['\"]?"
    # The dev-only chat switch, set to anything, is a violation.
    r"|MDX_DEV_[A-Z0-9_]+\W+['\"]?[A-Za-z0-9_]+",
    re.IGNORECASE,
)

DRIFT_PAIRS = [
    ("files/jobs/nightly_verify.py", "scripts/jobs/nightly_verify.py"),
    ("files/jobs/weekly_funnel.py", "scripts/jobs/weekly_funnel.py"),
    ("files/jobs/loop_funnel.sql", "scripts/ops/loop_funnel.sql"),
    ("files/jobs/share_retention.py", "scripts/jobs/share_retention.py"),
    ("files/jobs/ai_retention.py", "scripts/jobs/ai_retention.py"),
    ("files/jobs/weekly_speakers.py", "scripts/jobs/weekly_speakers.py"),
    ("files/jobs/speaker_quality.sql", "scripts/ops/speaker_quality.sql"),
    ("files/jobs/weekly_notes_quality.py", "scripts/jobs/weekly_notes_quality.py"),
    ("files/jobs/notes_quality.sql", "scripts/ops/notes_quality.sql"),
    ("files/postgres-init.sql", "infra/postgres/init.sql"),
]


def render(values: Path | None) -> str:
    cmd = ["helm", "template", "notes", str(CHART)]
    if values is not None:
        cmd += ["-f", str(values)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print(
            f"helm template failed ({values or 'staging defaults'}):\n{out.stderr}", file=sys.stderr
        )
        sys.exit(1)
    return out.stdout


def main() -> int:
    failures: list[str] = []

    for chart_rel, src_rel in DRIFT_PAIRS:
        chart_file = CHART / chart_rel
        src_file = ROOT / src_rel
        if chart_file.read_bytes() != src_file.read_bytes():
            failures.append(
                f"chart file {chart_rel} drifted from {src_rel} — "
                f"re-copy it (cp {src_rel} infra/k8s/notes/{chart_rel})"
            )

    if shutil.which("helm") and not os.environ.get("SKIP_HELM"):
        render(None)  # staging must render
        prod = render(CHART / "values-prod.yaml")
        for literal in FORBIDDEN_LITERALS:
            if literal in prod:
                failures.append(f"prod render contains forbidden literal {literal!r}")
        m = TRUTHY_FLAGS.search(prod)
        if m:
            failures.append(f"prod render enables demo/dev escape hatch {m.group(1)}")
        print("check-k8s-rendered: staging + prod rendered; prod is secret-clean")
    else:
        print("check-k8s-rendered: helm not available — drift check only")

    if failures:
        print("check-k8s-rendered: FAILURES:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1
    print("check-k8s-rendered: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
