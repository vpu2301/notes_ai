"""Telemetry sprint 3 guard: no code calls a model API directly outside the instrumented
provider (libs/models' OpenAI-compatible chat provider), except the allowlisted files."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALLOWLIST = Path(__file__).with_name("llm_call_sites.allowlist")
# Provider SDKs, local runtimes and the raw endpoints of chat/generation servers.
PATTERN = re.compile(
    r"\bimport (openai|anthropic|ollama|llama_cpp|mlx_lm)\b"
    r"|\bfrom (openai|anthropic|ollama|llama_cpp|mlx_lm)\b"
    r"|['\"]/(v1/)?chat/completions['\"]|['\"]/api/(generate|chat)['\"]|['\"]/completion['\"]"
)


def _allowed() -> set[str]:
    lines = ALLOWLIST.read_text(encoding="utf-8").splitlines()
    return {ln.split("|", 1)[0].strip() for ln in lines if ln.strip() and not ln.startswith("#")}


def _sources() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "services", "libs"],
        cwd=REPO, capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    return [p for p in out if p.endswith(".py") and "/src/" in p]


def test_every_model_call_goes_through_the_instrumented_provider() -> None:
    allowed = _allowed()
    offenders = []
    for rel in _sources():
        if rel in allowed:
            continue
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if PATTERN.search(line):
                offenders.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert not offenders, "direct model calls outside telemetry's reach:\n" + "\n".join(offenders)


def test_the_allowlist_has_no_stale_entries() -> None:
    for rel in _allowed():
        assert (REPO / rel).exists(), f"allowlisted file is gone: {rel}"


def test_the_guard_catches_a_direct_call() -> None:
    for line in (
        "import openai",
        "from anthropic import Anthropic",
        'resp = await client.post("/chat/completions", json=body)',
        'await http.post("/api/generate", json=req)',
    ):
        assert PATTERN.search(line), line
    assert not PATTERN.search('resp = await self._client.post("/v1/audio/transcriptions")')
