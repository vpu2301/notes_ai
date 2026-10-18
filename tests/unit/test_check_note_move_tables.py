"""The move function names every table that hangs off a note or its job (W5)."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_note_move", REPO / "scripts/ci/check-note-move-covers-all-tables.py"
)
assert _spec and _spec.loader
check = importlib.util.module_from_spec(_spec)
sys.modules["check_note_move"] = check
_spec.loader.exec_module(check)

MIGRATIONS = REPO / "infra/postgres/migrations"


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS, target, ignore=shutil.ignore_patterns("*.down.sql", "DEV_ONLY"))
    return target


def test_the_repo_migrations_pass() -> None:
    assert check.missing(MIGRATIONS) == []


def test_a_new_note_owned_table_the_function_forgets_fails(tmp_path: Path) -> None:
    migrations = _copy(tmp_path)
    (migrations / "9999_note_foo.sql").write_text(
        "CREATE TABLE note_foo (\n"
        "    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,\n"
        "    tenant_id UUID NOT NULL\n);\n"
    )
    assert check.missing(migrations) == ["note_foo"]
    assert check.main(["check", str(migrations)]) == 1


def test_a_table_hanging_off_the_job_counts_too(tmp_path: Path) -> None:
    migrations = _copy(tmp_path)
    (migrations / "9999_job_bar.sql").write_text(
        "CREATE TABLE job_bar (job_id UUID REFERENCES transcription_jobs(id));\n"
    )
    assert check.missing(migrations) == ["job_bar"]


def test_a_dropped_table_is_not_required(tmp_path: Path) -> None:
    migrations = _copy(tmp_path)
    (migrations / "9998_note_foo.sql").write_text(
        "CREATE TABLE note_foo (note_id UUID REFERENCES notes(id));\n"
    )
    (migrations / "9999_drop.sql").write_text("DROP TABLE note_foo;\n")
    assert check.missing(migrations) == []
