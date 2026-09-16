#!/usr/bin/env python3
"""CI gate — no Keycloak anywhere (IDX-B2 F3/L).

**This gate is NOT wired into CI yet, and will fail if you run it.** That
is correct: Keycloak is still the issuer in every environment. It is
committed now so that the sprint which actually performs the removal has
a finish line it can run against, rather than deciding what "removed"
means while half-way through deleting things.

Wire it up — add `make check-no-keycloak` to the architectural-gates step
in `.github/workflows/ci.yml` — on the commit that deletes the last
Keycloak artefact. Until then:

    uv run python scripts/ci/check-no-keycloak.py        # see what is left
    uv run python scripts/ci/check-no-keycloak.py --count  # just the number

The count is the removal's progress bar.

What is deliberately exempt, and why:

* `docs/adr/`   — an ADR is a record of a decision that WAS made. ADR-0006
                  chose Keycloak; superseding it does not un-make it, and
                  editing the history would leave the supersession
                  pointing at nothing.
* `docs/sprints/` — sprint logs are the same kind of record.
* `CHANGELOG`   — likewise.
* this file     — it necessarily contains every term it bans.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# The names that must not survive. Client ids are included because they
# outlive the word "keycloak": a leftover `mdx-asr-worker` in a config is
# a credential nobody rotates and nobody owns.
BANNED = re.compile(
    r"keycloak|KEYCLOAK_|mdx-backend|mdx-admin|mdx-dev-cli|"
    r"mdx-asr-worker|mdx-dictation|room-device-demo",
    re.IGNORECASE,
)

EXEMPT_PREFIXES = (
    "docs/adr/",
    "docs/sprints/",
    "CHANGELOG",
    "scripts/ci/check-no-keycloak.py",
)

# Binary and vendored paths git tracks but nobody greps.
SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".ico", ".pdf", ".woff", ".woff2", ".lock")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return [p for p in out.stdout.splitlines() if p]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", action="store_true", help="print the count only")
    args = parser.parse_args()

    hits: list[tuple[str, int, str]] = []
    for rel in tracked_files():
        if rel.startswith(EXEMPT_PREFIXES) or rel.endswith(SKIP_SUFFIXES):
            continue
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if BANNED.search(line):
                hits.append((rel, lineno, line.strip()[:120]))

    if args.count:
        print(len(hits))
        return 0 if not hits else 1

    if not hits:
        print("ok: no Keycloak references outside ADR/sprint history")
        return 0

    by_file: dict[str, int] = {}
    for rel, _, _ in hits:
        by_file[rel] = by_file.get(rel, 0) + 1

    print(f"Keycloak references remaining: {len(hits)} in {len(by_file)} file(s)", file=sys.stderr)
    for rel in sorted(by_file, key=lambda r: (-by_file[r], r)):
        print(f"  {by_file[rel]:4d}  {rel}", file=sys.stderr)
    print(
        "\nThis gate is expected to fail until IDX-B2's removal step runs. "
        "See docs/sprints/IDX-B2.md for what still blocks it.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
