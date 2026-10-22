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


def git_sha(*, short: bool = True) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", *(["--short"] if short else []), "HEAD"],
            capture_output=True,
            text=True,
            cwd=REPO,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def stale_build(build: dict[str, Any] | None) -> str | None:
    """Why ``build`` is not this checkout (None when it is): a different commit, or a
    different engine source digest (an uncommitted tree the image missed)."""
    if not build:
        return None
    head = git_sha(short=False)
    sha = str(build.get("git_sha") or "")
    # An image built outside `make dev-up` carries no commit ("unknown"): the code digest
    # alone decides then, and the report says so.
    if sha and sha != "unknown" and head and not (head.startswith(sha) or sha.startswith(head)):
        return f"git_sha {sha[:12]} != HEAD {head[:12]}"
    digest = build.get("code_digest")
    if digest:
        try:
            from note_service import build_info
        except ImportError:
            return None
        here = build_info.code_digest()
        if digest != here:
            return f"code_digest {digest} != tree {here}"
    # The prompt set under test must be the one that ran.
    effective = build.get("effective_version")
    if effective:
        try:
            from note_service.domain.prompts import PROMPT_VERSION
        except ImportError:
            return None
        if effective != PROMPT_VERSION:
            return f"effective_version {effective} != PROMPT_VERSION {PROMPT_VERSION}"
    return None


def write_report(
    kind: str,
    backend: str,
    payload: dict[str, Any],
    *,
    suffix: str = "",
    allow_stale: bool = False,
) -> Path:
    # Task 4: a report says what code wrote its first generation, and is not written
    # when that code is not this checkout (unless the caller says --allow-stale).
    reason = stale_build(payload.get("build"))
    if reason is not None:
        print(f"build: {payload.get('build')}")
        if not allow_stale:
            raise SystemExit(f"stale build: {reason} (pass --allow-stale to write the report)")
        payload = {**payload, "build_stale": reason}
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


class Paced:
    """An eval provider that waits out a rate limit (``retry_after_s``, else 5/10/20/40 s)
    instead of scoring a 429 as the model's answer. Never used by the service."""

    WAITS = (5.0, 10.0, 20.0, 40.0)

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.rate_limited = 0

    async def complete(self, *args: Any, **kwargs: Any) -> Any:
        import asyncio

        from models import ProviderError

        for wait in (*self.WAITS, None):
            try:
                return await self._inner.complete(*args, **kwargs)
            except ProviderError as exc:
                if exc.kind != "rate_limited" or wait is None:
                    raise
                self.rate_limited += 1
                await asyncio.sleep(exc.retry_after_s or wait)
        raise AssertionError("unreachable")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
