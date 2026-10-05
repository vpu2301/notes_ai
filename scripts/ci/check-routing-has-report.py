#!/usr/bin/env python3
"""CI gate (Sprint SQ1 T6, SM-15) — a model is routed only with a number.

For every backend that ``config/models.yaml`` routes a chat operation to
(``routing``, standard and premium, plus the staging/prod
``env_overrides``), ``docs/eval/`` must hold a notes report for that backend
id, at the current ``PROMPT_VERSION``, on the real corpus
(``eval/notes/v2``) — or ``docs/eval/routing-waivers.yaml`` must carry an
unexpired waiver for that exact (backend, prompt_version), with a reason
and an owner. A routing change or a prompt bump without either fails here,
naming the missing pair.

    python scripts/ci/check-routing-has-report.py [--config config/models.yaml]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
PROMPTS = REPO / "services/note-service/src/note_service/domain/meeting_doc/prompts.py"
EVAL = REPO / "docs" / "eval"
WAIVERS = EVAL / "routing-waivers.yaml"
CHAT_OPERATIONS = ("understand", "summarize", "classify", "title", "entities")
REAL_CORPUS = "eval/notes/v2"
ROUTED_ENVS = ("staging", "prod")


def prompt_version() -> str:
    m = re.search(r'^PROMPT_VERSION: Final = "([^"]+)"', PROMPTS.read_text("utf-8"), re.M)
    if not m:
        raise SystemExit(f"PROMPT_VERSION not found in {PROMPTS}")
    return m.group(1)


def routed_chat_backends(config: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for op in CHAT_OPERATIONS:
        for tier in (config.get("routing") or {}).get(op, {}).values():
            out.add(str(tier))
    for env in ROUTED_ENVS:
        for key, value in ((config.get("env_overrides") or {}).get(env) or {}).items():
            if key not in ("chat", *CHAT_OPERATIONS):
                continue
            if isinstance(value, dict):
                out.update(str(v) for k, v in value.items() if k in ("primary", "fallback"))
            else:
                out.add(str(value))
    return out


def reports(eval_dir: Path) -> set[tuple[str, str]]:
    """(backend, prompt_version) of every notes report on the real corpus."""
    out: set[tuple[str, str]] = set()
    for path in eval_dir.glob("notes-*.json"):
        try:
            d = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        corpus = str(d.get("corpus") or "")
        if (
            corpus.rstrip("/").endswith(REAL_CORPUS)
            and d.get("backend")
            and d.get("prompt_version")
        ):
            out.add((str(d["backend"]), str(d["prompt_version"])))
    return out


def waivers(path: Path, today: date) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.exists():
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for w in (yaml.safe_load(path.read_text("utf-8")) or {}).get("waivers") or []:
        if not all(w.get(k) for k in ("backend", "prompt_version", "reason", "owner", "expires")):
            raise SystemExit(
                f"{path}: a waiver needs backend, prompt_version, reason, owner, expires"
            )
        if date.fromisoformat(str(w["expires"])) >= today:
            out[(str(w["backend"]), str(w["prompt_version"]))] = w
    return out


def missing(
    config: dict[str, Any],
    version: str,
    have: set[tuple[str, str]],
    waived: dict[tuple[str, str], Any],
) -> list[str]:
    return sorted(
        b
        for b in routed_chat_backends(config)
        if (b, version) not in have and (b, version) not in waived
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=REPO / "config" / "models.yaml")
    ap.add_argument("--eval-dir", type=Path, default=EVAL)
    ap.add_argument("--waivers", type=Path, default=WAIVERS)
    args = ap.parse_args(argv)
    config = yaml.safe_load(args.config.read_text("utf-8"))
    version = prompt_version()
    gaps = missing(config, version, reports(args.eval_dir), waivers(args.waivers, date.today()))
    if gaps:
        for b in gaps:
            print(
                f"FAIL: chat routes to {b!r} with no {REAL_CORPUS} report at PROMPT_VERSION "
                f"{version} and no unexpired waiver (docs/eval/routing-waivers.yaml)"
            )
        return 1
    print(f"PASS: every routed chat backend has a report or a waiver at PROMPT_VERSION {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
