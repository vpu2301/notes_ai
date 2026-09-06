"""DEP-S1-04: a worker cannot reach an arbitrary host (RUN_EGRESS_TEST=1).

Drives scripts/k8s/egress-allowlist.sh test against the running staging
cluster (or the compose stack). It is a *deployment* test: it proves the
allowlist is enforced where the workers actually run, which no unit test can.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_EGRESS_TEST") != "1",
    reason="set RUN_EGRESS_TEST=1; needs a running staging cluster or compose stack with the allowlist applied",
)

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "k8s" / "egress-allowlist.sh"


def test_worker_cannot_reach_example_com_but_reaches_model_endpoint() -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "test"], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "example.com blocked" in proc.stdout
