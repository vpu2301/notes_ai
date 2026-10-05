#!/usr/bin/env python3
"""CI gate: no model-vendor SDK (anthropic, openai, huggingface_hub, mistralai, litellm, ...)
is imported outside ``libs/models`` and ``scripts/models`` (build-time tooling).

Exit 0 clean, 1 violations (file:line).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED_IMPORTS = re.compile(
    r"^\s*(?:import|from)\s+"
    r"(?:anthropic|openai|huggingface_hub|cohere|mistralai|groq|together|replicate"
    r"|google\.generativeai|google\.genai|vertexai|langchain\w*|litellm)\b",
    re.MULTILINE,
)

ALLOWED_PREFIXES: tuple[str, ...] = (
    "libs/models/",  # the provider seam itself
    "scripts/models/",  # build-time model fetch (huggingface_hub snapshot_download)
    "scripts/ci/check-no-vendor-import.py",  # this checker
)

SKIP_PARTS = ("/.venv/", "/__pycache__/", "site-packages", "/dist/", "/node_modules/")


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    violations: list[tuple[Path, int, str]] = []
    for path in repo.rglob("*.py"):
        rel = path.relative_to(repo).as_posix()
        if rel.startswith(ALLOWED_PREFIXES):
            continue
        if any(part in f"/{rel}" for part in SKIP_PARTS):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in BANNED_IMPORTS.finditer(text):
            line = text[: match.start()].count("\n") + 1
            violations.append((path.relative_to(repo), line, match.group(0).strip()))

    if violations:
        print("no-vendor-import: model-vendor SDK imported outside libs/models:", file=sys.stderr)
        for rel, line, snippet in violations:
            print(f"  {rel}:{line}  {snippet}", file=sys.stderr)
        print(
            "\nRoute the call through models.registry / build_chat_provider instead "
            "(Foundation plan decision 11).",
            file=sys.stderr,
        )
        return 1
    print("ok: no vendor SDK imports outside libs/models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
