"""SQL for `service_credentials` and `service_credential_secrets` (0026).

Runs on the ``tenant_writer`` pool. The secrets table has no ``app_role``
grant at all, so this module is the only code in the estate that can read
a hash — which is the point of putting the lookup in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from . import credentials as cred

_CREDENTIAL_COLUMNS = """
    id, kind, tenant_id, name, roles, status, created_by,
    last_used_at, revoked_at, created_at
"""


@dataclass(frozen=True, slots=True)
class Credential:
    id: UUID
    kind: str
    tenant_id: UUID | None
    name: str
    roles: list[str]
    status: str
    created_by: UUID | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    @property
    def active(self) -> bool:
        return self.status == "active" and self.revoked_at is None

    @classmethod
    def from_row(cls, row: asyncpg.Record) -> Credential:
        return cls(
            id=row["id"],
            kind=row["kind"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            roles=list(row["roles"]),
            status=row["status"],
            created_by=row["created_by"],
            last_used_at=row["last_used_at"],
            revoked_at=row["revoked_at"],
            created_at=row["created_at"],
        )


@dataclass(frozen=True, slots=True)
class SecretRef:
    """A live secret, described without disclosing it."""

    id: UUID
    prefix: str
    expires_at: datetime | None
    created_at: datetime


class CredentialRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── credentials ──────────────────────────────────────────────────

    async def create(
        self,
        *,
        kind: str,
        tenant_id: UUID | None,
        name: str,
        created_by: UUID | None,
        secret_hash: str,
        secret_prefix: str,
    ) -> Credential:
        """Insert the credential and its first secret together.

        One transaction, because a credential with no secret cannot
        authenticate and cannot be given one afterwards through any route
        that exists — it would be a dead row that looks like a working
        device in the management list.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"""
                INSERT INTO service_credentials
                    (kind, tenant_id, name, roles, created_by)
                VALUES ($1, $2, $3, $4::text[], $5)
                RETURNING {_CREDENTIAL_COLUMNS}
                """,
                kind,
                tenant_id,
                name,
                cred.roles_for(kind),
                created_by,
            )
            assert row is not None
            await conn.execute(
                """
                INSERT INTO service_credential_secrets
                    (credential_id, secret_hash, secret_prefix)
                VALUES ($1, $2, $3)
                """,
                row["id"],
                secret_hash,
                secret_prefix,
            )
        return Credential.from_row(row)

    async def get(self, credential_id: UUID) -> Credential | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_CREDENTIAL_COLUMNS} FROM service_credentials WHERE id = $1",
                credential_id,
            )
        return Credential.from_row(row) if row is not None else None

    async def list_for_tenant(self, tenant_id: UUID) -> list[Credential]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_CREDENTIAL_COLUMNS} FROM service_credentials
                WHERE kind = 'device' AND tenant_id = $1
                ORDER BY name
                """,
                tenant_id,
            )
        return [Credential.from_row(r) for r in rows]

    async def list_services(self) -> list[Credential]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_CREDENTIAL_COLUMNS} FROM service_credentials
                WHERE kind = 'service'
                ORDER BY name
                """
            )
        return [Credential.from_row(r) for r in rows]

    async def revoke(self, credential_id: UUID) -> bool:
        """Revoke the credential and every secret it holds, atomically.

        Both halves matter: the credential row is what the grant checks
        first, and the secrets are what an attacker holding a copy would
        present. Leaving either behind leaves a way in.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE service_credentials
                SET status = 'revoked', revoked_at = now()
                WHERE id = $1 AND status = 'active'
                RETURNING id
                """,
                credential_id,
            )
            if row is None:
                return False
            await conn.execute(
                "UPDATE service_credential_secrets SET revoked_at = now()"
                " WHERE credential_id = $1 AND revoked_at IS NULL",
                credential_id,
            )
        return True

    async def touch_used(self, credential_id: UUID, *, throttle_seconds: int = 300) -> None:
        """Stamp ``last_used_at``, at most once per ``throttle_seconds``.

        A busy room fetches a token every 15 minutes, but a chatty service
        could fetch one per request. The throttle is in the WHERE clause
        so the write is skipped in the database rather than guessed at in
        Python — "when did this device last check in" stays useful without
        turning every grant into a row update.
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE service_credentials
                SET last_used_at = now()
                WHERE id = $1
                  AND (last_used_at IS NULL
                       OR last_used_at < now() - make_interval(secs => $2))
                """,
                credential_id,
                throttle_seconds,
            )

    # ── secrets ──────────────────────────────────────────────────────

    async def find_by_secret_hash(self, secret_hash: str) -> tuple[Credential, UUID] | None:
        """Resolve a presented secret to its credential, or None.

        Deliberately keyed on the hash alone, with no ``client_id`` in the
        predicate: the caller compares the returned credential's id to the
        one presented, so a secret belonging to credential A cannot be
        used by claiming to be credential B — and the lookup itself takes
        the same work either way.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT s.id AS secret_id, {", ".join("c." + c.strip() for c in _CREDENTIAL_COLUMNS.split(","))}
                FROM service_credential_secrets s
                JOIN service_credentials c ON c.id = s.credential_id
                WHERE s.secret_hash = $1
                  AND s.revoked_at IS NULL
                  AND (s.expires_at IS NULL OR s.expires_at > now())
                """,
                secret_hash,
            )
        if row is None:
            return None
        return Credential.from_row(row), row["secret_id"]

    async def live_secrets(self, credential_id: UUID) -> list[SecretRef]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, secret_prefix, expires_at, created_at
                FROM service_credential_secrets
                WHERE credential_id = $1
                  AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY created_at
                """,
                credential_id,
            )
        return [
            SecretRef(
                id=r["id"],
                prefix=r["secret_prefix"],
                expires_at=r["expires_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def add_secret_and_expire_others(
        self,
        credential_id: UUID,
        *,
        secret_hash: str,
        secret_prefix: str,
        old_ttl_seconds: int,
    ) -> datetime:
        """Rotation: issue a new secret and put a clock on the old ones.

        The old secret is *not* revoked. A room is re-keyed by deploying
        the new secret whenever somebody is next in the room; revoking on
        rotation would take the room offline the moment the button was
        pressed, which is how rotations stop happening.
        """
        expires_at = datetime.now(UTC) + timedelta(seconds=old_ttl_seconds)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE service_credential_secrets
                SET expires_at = LEAST(COALESCE(expires_at, $2), $2)
                WHERE credential_id = $1 AND revoked_at IS NULL
                """,
                credential_id,
                expires_at,
            )
            await conn.execute(
                """
                INSERT INTO service_credential_secrets
                    (credential_id, secret_hash, secret_prefix)
                VALUES ($1, $2, $3)
                """,
                credential_id,
                secret_hash,
                secret_prefix,
            )
        return expires_at
