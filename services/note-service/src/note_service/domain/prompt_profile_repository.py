"""Profiles, their immutable versions and the active pointer (migration 0079).

Every call runs inside ``tenant_connection``: RLS scopes each query to the
workspace, and the tables' composite foreign keys keep a version, a binding or an
activation inside it. Activation is a compare-and-set on ``revision``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from . import prompt_profiles as rules


class ActivationConflictError(Exception):
    """Another admin moved the pointer first; nothing was changed."""

    def __init__(self, current_revision: int) -> None:
        super().__init__("active_revision_conflict")
        self.current_revision = current_revision


@dataclass(slots=True)
class Profile:
    id: UUID
    name: str
    description: str
    created_by: UUID
    created_at: datetime


@dataclass(slots=True)
class Version:
    id: UUID
    profile_id: UUID
    version_number: int
    config: rules.ProfileConfig
    contract_version: str
    schema_version: str
    algorithm_version: str
    content_hash: str
    created_by: UUID
    created_at: datetime


@dataclass(slots=True)
class Binding:
    profile_version_id: UUID | None
    revision: int
    activated_by: UUID | None
    activated_at: datetime | None


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _version(r: asyncpg.Record) -> Version:
    return Version(
        id=r["id"],
        profile_id=r["profile_id"],
        version_number=r["version_number"],
        config=rules.ProfileConfig.model_validate(_json(r["config"])),
        contract_version=r["contract_version"],
        schema_version=r["schema_version"],
        algorithm_version=r["algorithm_version"],
        content_hash=r["content_hash"],
        created_by=r["created_by"],
        created_at=r["created_at"],
    )


_VERSION_COLUMNS = (
    "id, profile_id, version_number, config, contract_version, schema_version, "
    "algorithm_version, content_hash, created_by, created_at"
)


async def create_profile(
    conn: asyncpg.Connection, *, tenant_id: UUID, name: str, description: str, created_by: UUID
) -> Profile:
    r = await conn.fetchrow(
        """
        INSERT INTO prompt_profiles (tenant_id, name, description, created_by)
        VALUES ($1, $2, $3, $4)
        RETURNING id, name, description, created_by, created_at
        """,
        tenant_id,
        name,
        description,
        created_by,
    )
    return Profile(**dict(r))


async def list_profiles(conn: asyncpg.Connection) -> list[Profile]:
    rows = await conn.fetch(
        "SELECT id, name, description, created_by, created_at FROM prompt_profiles "
        "ORDER BY created_at"
    )
    return [Profile(**dict(r)) for r in rows]


async def fetch_profile(conn: asyncpg.Connection, *, profile_id: UUID) -> Profile | None:
    r = await conn.fetchrow(
        "SELECT id, name, description, created_by, created_at FROM prompt_profiles WHERE id = $1",
        profile_id,
    )
    return Profile(**dict(r)) if r is not None else None


async def create_version(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    profile_id: UUID,
    config: rules.ProfileConfig,
    created_by: UUID,
) -> Version:
    """The next version number of this profile; two saves at once: the second gets
    the unique violation and the route answers 409 (never an overwrite)."""
    r = await conn.fetchrow(
        f"""
        INSERT INTO prompt_profile_versions (
            tenant_id, profile_id, version_number, config, contract_version,
            schema_version, algorithm_version, content_hash, created_by
        )
        SELECT $1, $2, COALESCE(MAX(version_number), 0) + 1, $3::jsonb, $4, $5, $6, $7, $8
          FROM prompt_profile_versions WHERE profile_id = $2
        RETURNING {_VERSION_COLUMNS}
        """,
        tenant_id,
        profile_id,
        json.dumps(config.model_dump(mode="json")),
        rules.CONTRACT_VERSION,
        rules.schema_version(),
        rules.ALGORITHM_VERSION,
        rules.content_hash(config),
        created_by,
    )
    return _version(r)


async def list_versions(
    conn: asyncpg.Connection, *, profile_id: UUID | None = None
) -> list[Version]:
    if profile_id is None:
        rows = await conn.fetch(
            f"SELECT {_VERSION_COLUMNS} FROM prompt_profile_versions ORDER BY profile_id, version_number"
        )
    else:
        rows = await conn.fetch(
            f"SELECT {_VERSION_COLUMNS} FROM prompt_profile_versions WHERE profile_id = $1 "
            "ORDER BY version_number",
            profile_id,
        )
    return [_version(r) for r in rows]


async def fetch_version(conn: asyncpg.Connection, *, version_id: UUID) -> Version | None:
    r = await conn.fetchrow(
        f"SELECT {_VERSION_COLUMNS} FROM prompt_profile_versions WHERE id = $1", version_id
    )
    return _version(r) if r is not None else None


async def binding(conn: asyncpg.Connection, *, tenant_id: UUID) -> Binding:
    """The active pointer; revision 0 and no version when nobody ever activated one."""
    r = await conn.fetchrow(
        "SELECT profile_version_id, revision, activated_by, activated_at "
        "FROM prompt_profile_bindings WHERE tenant_id = $1",
        tenant_id,
    )
    if r is None:
        return Binding(profile_version_id=None, revision=0, activated_by=None, activated_at=None)
    return Binding(**dict(r))


async def activate(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    version_id: UUID | None,
    expected_revision: int,
    actor: UUID,
    evaluation_ref: UUID | None = None,
) -> Binding:
    """Move the pointer from ``expected_revision`` to the next one, atomically, and
    record it. ``version_id=None`` returns the workspace to the bundled profile."""
    current = await binding(conn, tenant_id=tenant_id)
    if expected_revision == 0 and current.revision == 0:
        r = await conn.fetchrow(
            """
            INSERT INTO prompt_profile_bindings (tenant_id, profile_version_id, revision, activated_by)
            VALUES ($1, $2, 1, $3)
            ON CONFLICT (tenant_id) DO NOTHING
            RETURNING profile_version_id, revision, activated_by, activated_at
            """,
            tenant_id,
            version_id,
            actor,
        )
    else:
        r = await conn.fetchrow(
            """
            UPDATE prompt_profile_bindings
               SET profile_version_id = $2, revision = revision + 1,
                   activated_by = $3, activated_at = now()
             WHERE tenant_id = $1 AND revision = $4
            RETURNING profile_version_id, revision, activated_by, activated_at
            """,
            tenant_id,
            version_id,
            actor,
            expected_revision,
        )
    if r is None:
        raise ActivationConflictError((await binding(conn, tenant_id=tenant_id)).revision)
    moved = Binding(**dict(r))
    await conn.execute(
        """
        INSERT INTO prompt_profile_activations (
            tenant_id, profile_version_id, previous_version_id, revision, actor, evaluation_ref
        ) VALUES ($1, $2, $3, $4, $5, $6)
        """,
        tenant_id,
        version_id,
        current.profile_version_id,
        moved.revision,
        actor,
        evaluation_ref,
    )
    return moved


async def history(conn: asyncpg.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT profile_version_id, previous_version_id, revision, actor, evaluation_ref, created_at "
        "FROM prompt_profile_activations ORDER BY created_at DESC LIMIT $1",
        limit,
    )
    return [dict(r) for r in rows]


async def active_config(
    conn: asyncpg.Connection, *, tenant_id: UUID
) -> tuple[rules.ProfileConfig, Version | None]:
    """What the workspace's next generation runs: the active version, else the bundle."""
    pointer = await binding(conn, tenant_id=tenant_id)
    if pointer.profile_version_id is None:
        return rules.BUNDLED, None
    version = await fetch_version(conn, version_id=pointer.profile_version_id)
    if version is None:
        # Versions are never deleted while bound (FK RESTRICT); this is corruption.
        raise LookupError("active profile version not found")
    return version.config, version
