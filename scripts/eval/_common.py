"""Shared plumbing for the DEP-S0 eval scripts: registry from env, JSON out."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config" / "models.yaml"
DOCS_EVAL = REPO / "docs" / "eval"


def registry_env() -> str:
    return os.environ.get("ENV") or os.environ.get("MODELS_ENV") or "dev"


def load_registry() -> Any:
    from models import Registry

    # validate=False: an eval targets ONE named backend; the other routes in
    # this env (e.g. hf_eu on staging) need not be configured on this host.
    return Registry.load(CONFIG, env=registry_env(), environ=os.environ, validate=False)


def host_info() -> dict[str, Any]:
    info: dict[str, Any] = {"platform": platform.platform(), "machine": platform.machine()}
    if platform.system() == "Darwin":
        for key, field in (("hw.memsize", "memory_bytes"), ("machdep.cpu.brand_string", "cpu")):
            try:
                out = subprocess.run(
                    ["sysctl", "-n", key], capture_output=True, text=True, timeout=5
                )
                info[field] = out.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
    return info


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def write_report(kind: str, backend: str, payload: dict[str, Any], *, suffix: str = "") -> Path:
    DOCS_EVAL.mkdir(parents=True, exist_ok=True)
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    path = DOCS_EVAL / f"{kind}-{date}-{backend}{suffix}.json"
    payload = {
        "kind": kind,
        "backend": backend,
        "date": date,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_sha(),
        "host": host_info(),
        **payload,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
