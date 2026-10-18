#!/usr/bin/env python3
"""CI gate (W5): every table that references ``notes(id)`` or ``transcription_jobs(id)``
is named in ``public.move_note_to_workspace``, or is left alone on purpose below.
A new note-owned table the move forgets would stay behind in the old workspace.

    uv run python scripts/ci/check-note-move-covers-all-tables.py [migrations_dir]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS = ROOT / "infra/postgres/migrations"

# Not moved, by decision (0078's header says why).
LEFT_ALONE: frozenset[str] = frozenset({"note_versions", "workspace_glossary"})

_REFERENCE = re.compile(r"(?i)REFERENCES\s+(notes|transcription_jobs)\s*\(\s*id\s*\)")
_TABLE = re.compile(
    r"(?i)^\s*(?:CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|ALTER\s+TABLE(?:\s+ONLY)?)\s+"
    r"(?:public\.)?\"?([a-z_][a-z0-9_]*)\"?"
)
_DROP = re.compile(r"(?i)^\s*DROP\s+TABLE(?:\s+IF\s+EXISTS)?\s+(?:public\.)?\"?([a-z_][a-z0-9_]*)")
_FUNCTION = re.compile(
    r"(?is)CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+public\.move_note_to_workspace\s*\(.*?\$\$(.*?)\$\$"
)
_COMMENT = re.compile(r"--[^\n]*")


def _migrations(directory: Path) -> list[Path]:
    return sorted(p for p in directory.glob("*.sql") if not p.name.endswith(".down.sql"))


def referencing_tables(directory: Path) -> set[str]:
    """Tables alive after the last migration with a column referencing a note or a job."""
    tables: set[str] = set()
    for path in _migrations(directory):
        text = _COMMENT.sub("", path.read_text())
        for statement in text.split(";"):
            dropped = _DROP.match(statement)
            if dropped:
                tables.discard(dropped.group(1))
                continue
            table = _TABLE.match(statement)
            if table and _REFERENCE.search(statement):
                tables.add(table.group(1))
    return tables


def function_body(directory: Path) -> str | None:
    """The newest definition of the move function."""
    body = None
    for path in _migrations(directory):
        match = _FUNCTION.search(path.read_text())
        if match:
            body = match.group(1)
    return body


def missing(directory: Path) -> list[str]:
    body = function_body(directory)
    if body is None:
        return ["public.move_note_to_workspace is not defined"]
    code = _COMMENT.sub("", body)
    return sorted(
        t
        for t in referencing_tables(directory) - LEFT_ALONE
        if not re.search(rf"\b{re.escape(t)}\b", code)
    )


def main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) > 1 else MIGRATIONS
    gaps = missing(directory)
    if gaps:
        print(
            "check-note-move-covers-all-tables: these tables reference a note or its "
            "transcription job but move_note_to_workspace does not move them (add them to the "
            "function, or to LEFT_ALONE with a reason):",
            file=sys.stderr,
        )
        for name in gaps:
            print(f"  - {name}", file=sys.stderr)
        return 1
    print(f"check-note-move-covers-all-tables: OK ({len(referencing_tables(directory))} tables)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
