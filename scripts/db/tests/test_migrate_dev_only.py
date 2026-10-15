"""``migrate.py up`` records DEV_ONLY files as skipped (never runs them) under
``--skip-dev-seeds`` / ``MDX_ENV=prod``, and rolls a skipped file back as a no-op.
"""

from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATE = Path(__file__).resolve().parent.parent / "migrate.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migrate", _MIGRATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeConn:
    """Just enough of asyncpg.Connection for the runner: a schema_migrations dict."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.ran: list[str] = []

    @asynccontextmanager
    async def transaction(self):  # type: ignore[no-untyped-def]
        yield

    async def execute(self, sql: str, *args: Any) -> None:
        if sql.startswith("INSERT INTO schema_migrations"):
            version, name, checksum, skipped = args
            self.rows[version] = {
                "version": version,
                "name": name,
                "checksum": checksum,
                "skipped": skipped,
            }
        elif sql.startswith("DELETE FROM schema_migrations"):
            self.rows.pop(args[0])
        elif "schema_migrations" not in sql:
            self.ran.append(sql.strip())

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        rows = list(self.rows.values())
        return [r for r in rows if r["skipped"]] if "WHERE skipped" in sql else rows

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        if "ORDER BY version DESC" in sql:
            return max(self.rows.values(), key=lambda r: r["version"], default=None)
        return self.rows.get(args[0])


@pytest.fixture
def migrate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for name, sql in {
        "0001_schema.sql": "CREATE TABLE t();",
        "0002_seed_dev_tenants.sql": "INSERT INTO tenants VALUES ('acme');",
        "0003_more.sql": "ALTER TABLE t ADD c int;",
    }.items():
        (tmp_path / name).write_text(sql)
        (tmp_path / name.replace(".sql", ".down.sql")).write_text(f"-- undo {name}")
    (tmp_path / "DEV_ONLY").write_text("# fixtures\n0002_seed_dev_tenants.sql\n")
    module = _load()
    monkeypatch.setattr(module, "MIGRATIONS_DIR", tmp_path)
    return module


async def test_prod_records_dev_seed_as_skipped(migrate: ModuleType) -> None:
    conn = FakeConn()
    assert await migrate.cmd_up(conn, skip_dev_seeds=True) == 0
    assert sorted(conn.rows) == ["0001", "0002", "0003"]  # numbering stays dense
    assert conn.rows["0002"]["skipped"] is True
    assert not any("acme" in sql for sql in conn.ran)


async def test_dev_runs_the_seed(migrate: ModuleType) -> None:
    conn = FakeConn()
    await migrate.cmd_up(conn)
    assert conn.rows["0002"]["skipped"] is False
    assert any("acme" in sql for sql in conn.ran)


async def test_rollback_of_skipped_file_is_noop(migrate: ModuleType) -> None:
    conn = FakeConn()
    await migrate.cmd_up(conn, skip_dev_seeds=True)
    conn.rows.pop("0003")
    conn.ran.clear()
    await migrate.cmd_down(conn)
    assert "0002" not in conn.rows
    assert conn.ran == []


async def test_status_prints_skipped(
    migrate: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    conn = FakeConn()
    await migrate.cmd_up(conn, skip_dev_seeds=True)
    capsys.readouterr()
    await migrate.cmd_status(conn)
    assert "skipped  0002" in capsys.readouterr().out


def test_repo_dev_only_lists_the_demo_tenants() -> None:
    migrations = _MIGRATE.resolve().parent.parent.parent / "infra" / "postgres" / "migrations"
    assert "0013_seed_dev_tenants.sql" in _load()._dev_only_names(migrations)
