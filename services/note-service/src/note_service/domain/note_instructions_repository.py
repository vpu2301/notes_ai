"""The ``workspace_note_instructions`` rows (N1, N4): one per (tenant, scope) — the
workspace text and one per meeting type that extends it — and the ``note_instructions``
row of one note (N4), on a tenant connection under RLS. No row is the default: notes are
written as today."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import asyncpg

WORKSPACE: Final = "workspace"
# N4: one text per meeting family (`auto` is "no type yet" and resolves to the workspace).
TYPE_SCOPES: Final = ("client", "team", "sales", "one_on_one", "interview", "broadcast", "memo")
SCOPES: Final = (WORKSPACE, *TYPE_SCOPES)
NOTE: Final = "note"
STALE: Final = "stale"

_COLUMNS: Final = (
    "tenant_id, scope, version, text, profile, profile_hash, compile_status, "
    "compile_error_kind, compiler_version, backend, updated_by, created_at, updated_at, "
    "base_versions"
)


@dataclass(frozen=True, slots=True)
class Row:
    tenant_id: UUID
    scope: str
    version: int
    text: str
    profile: dict[str, Any]
    profile_hash: str
    compile_status: str
    compile_error_kind: str | None
    compiler_version: str
    backend: str | None
    updated_by: UUID
    created_at: datetime
    updated_at: datetime
    """N4 — the parents' versions this row was compiled with: `{"workspace": 3}`."""
    base_versions: dict[str, int] = field(default_factory=dict)

    @property
    def stale(self) -> bool:
        return self.compile_status == STALE


def _object(raw: Any) -> dict[str, Any]:
    value = json.loads(raw) if isinstance(raw, str) else raw
    return dict(value) if isinstance(value, dict) else {}


def _row(record: asyncpg.Record) -> Row:
    profile = record["profile"]
    return Row(
        tenant_id=record["tenant_id"],
        scope=record["scope"],
        version=int(record["version"]),
        text=record["text"],
        profile=json.loads(profile) if isinstance(profile, str) else dict(profile or {}),
        profile_hash=record["profile_hash"],
        compile_status=record["compile_status"],
        compile_error_kind=record["compile_error_kind"],
        compiler_version=record["compiler_version"],
        backend=record["backend"],
        updated_by=record["updated_by"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        base_versions={k: int(v) for k, v in _object(record.get("base_versions")).items()},
    )


async def fetch(conn: asyncpg.Connection, *, tenant_id: UUID, scope: str = WORKSPACE) -> Row | None:
    record = await conn.fetchrow(
        f"SELECT {_COLUMNS} FROM workspace_note_instructions WHERE tenant_id = $1 AND scope = $2",
        tenant_id,
        scope,
    )
    return _row(record) if record is not None else None


async def upsert(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    scope: str,
    text: str,
    profile: dict[str, Any],
    profile_hash: str,
    compile_status: str,
    compile_error_kind: str | None,
    compiler_version: str,
    backend: str | None,
    updated_by: UUID,
    bump_version: bool,
    base_versions: dict[str, int] | None = None,
) -> Row:
    """Insert version 1, or replace the row; ``bump_version`` adds one to the version
    (the text changed), else it stays (a re-compile of the same text)."""
    record = await conn.fetchrow(
        f"""
        INSERT INTO workspace_note_instructions (
            tenant_id, scope, version, text, profile, profile_hash, compile_status,
            compile_error_kind, compiler_version, backend, updated_by, base_versions
        )
        VALUES ($1, $2, 1, $3, $4::jsonb, $5, $6, $7, $8, $9, $10, $12::jsonb)
        ON CONFLICT (tenant_id, scope) DO UPDATE SET
            version = workspace_note_instructions.version + CASE WHEN $11 THEN 1 ELSE 0 END,
            text = EXCLUDED.text,
            profile = EXCLUDED.profile,
            profile_hash = EXCLUDED.profile_hash,
            compile_status = EXCLUDED.compile_status,
            compile_error_kind = EXCLUDED.compile_error_kind,
            compiler_version = EXCLUDED.compiler_version,
            backend = EXCLUDED.backend,
            updated_by = EXCLUDED.updated_by,
            base_versions = EXCLUDED.base_versions
        RETURNING {_COLUMNS}
        """,
        tenant_id,
        scope,
        text,
        json.dumps(profile),
        profile_hash,
        compile_status,
        compile_error_kind,
        compiler_version,
        backend,
        updated_by,
        bump_version,
        json.dumps(base_versions or {}),
    )
    return _row(record)


async def delete(conn: asyncpg.Connection, *, tenant_id: UUID, scope: str = WORKSPACE) -> bool:
    status = await conn.execute(
        "DELETE FROM workspace_note_instructions WHERE tenant_id = $1 AND scope = $2",
        tenant_id,
        scope,
    )
    return str(status).endswith(" 1")


async def fetch_many(
    conn: asyncpg.Connection, *, tenant_id: UUID, scopes: tuple[str, ...] | list[str]
) -> dict[str, Row]:
    """The rows of these scopes, by scope (one round trip; absent scopes are missing)."""
    records = await conn.fetch(
        f"SELECT {_COLUMNS} FROM workspace_note_instructions"
        " WHERE tenant_id = $1 AND scope = ANY($2::text[])",
        tenant_id,
        list(scopes),
    )
    return {r["scope"]: _row(r) for r in records}


# ── One note's instructions (N4) ───────────────────────────────────

_NOTE_COLUMNS: Final = (
    "tenant_id, note_id, text, profile, profile_hash, compile_status, compile_error_kind, "
    "compiler_version, base_versions, updated_by, created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class NoteRow:
    tenant_id: UUID
    note_id: UUID
    text: str
    profile: dict[str, Any]
    profile_hash: str
    compile_status: str
    compile_error_kind: str | None
    compiler_version: str
    base_versions: dict[str, int]
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


def _note_row(record: asyncpg.Record) -> NoteRow:
    return NoteRow(
        tenant_id=record["tenant_id"],
        note_id=record["note_id"],
        text=record["text"],
        profile=_object(record["profile"]),
        profile_hash=record["profile_hash"],
        compile_status=record["compile_status"],
        compile_error_kind=record["compile_error_kind"],
        compiler_version=record["compiler_version"],
        base_versions={k: int(v) for k, v in _object(record["base_versions"]).items()},
        updated_by=record["updated_by"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
    )


async def fetch_note(conn: asyncpg.Connection, *, note_id: UUID) -> NoteRow | None:
    record = await conn.fetchrow(
        f"SELECT {_NOTE_COLUMNS} FROM note_instructions WHERE note_id = $1", note_id
    )
    return _note_row(record) if record is not None else None


async def upsert_note(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    note_id: UUID,
    text: str,
    profile: dict[str, Any],
    profile_hash: str,
    compile_status: str,
    compile_error_kind: str | None,
    compiler_version: str,
    base_versions: dict[str, int],
    updated_by: UUID,
) -> NoteRow:
    record = await conn.fetchrow(
        f"""
        INSERT INTO note_instructions (
            tenant_id, note_id, text, profile, profile_hash, compile_status,
            compile_error_kind, compiler_version, base_versions, updated_by
        )
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9::jsonb, $10)
        ON CONFLICT (note_id) DO UPDATE SET
            text = EXCLUDED.text, profile = EXCLUDED.profile,
            profile_hash = EXCLUDED.profile_hash, compile_status = EXCLUDED.compile_status,
            compile_error_kind = EXCLUDED.compile_error_kind,
            compiler_version = EXCLUDED.compiler_version,
            base_versions = EXCLUDED.base_versions, updated_by = EXCLUDED.updated_by
        RETURNING {_NOTE_COLUMNS}
        """,
        tenant_id,
        note_id,
        text,
        json.dumps(profile),
        profile_hash,
        compile_status,
        compile_error_kind,
        compiler_version,
        json.dumps(base_versions),
        updated_by,
    )
    return _note_row(record)


async def delete_note(conn: asyncpg.Connection, *, note_id: UUID) -> bool:
    status = await conn.execute("DELETE FROM note_instructions WHERE note_id = $1", note_id)
    return str(status).endswith(" 1")
