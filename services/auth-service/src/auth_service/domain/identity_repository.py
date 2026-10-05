"""SQL for `identities`, `auth_challenges`, `auth_sessions`.

Everything runs on ``tenant_writer``: these tables have no ``tenant_id``, so
isolation is the role grant plus the writer-only RLS policy; ``app_role`` cannot
reach them. Decision logic lives in :mod:`auth_service.domain.email_code`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from . import email_code as ec

logger = logging.getLogger(__name__)


def _as_json(value: Any) -> dict[str, Any]:
    """asyncpg hands back JSONB as text unless a codec is registered."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str | bytes):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    return {}


_CHALLENGE_COLUMNS = """
    id, kind, email, identity_id, code_hash, expires_at,
    attempts, max_attempts, consumed_at, created_at, metadata
"""

_IDENTITY_COLUMNS = """
    id, email, email_verified_at, display_name, status, mfa_enabled,
    (password_hash IS NOT NULL) AS has_password, last_tenant_id,
    failed_login_count, lock_count, locked_until, lock_notified_at,
    deletion_requested_at, locale, timezone, legacy_idp, created_at
"""

# Membership role → the platform roles the JWT carries (explicit on purpose).
_PLATFORM_ROLES: dict[str, tuple[str, ...]] = {
    # `tenant_admin` alone carries no content permission, so owners/admins get
    # `member` too or they 403 on every note.
    "owner": ("tenant_admin", "member"),
    "admin": ("tenant_admin", "member"),
    "member": ("member",),
    "assistant": ("member",),
    "viewer": ("viewer",),
}
# A membership role we do not recognise must not silently become an admin.
_FALLBACK_ROLES: tuple[str, ...] = ("viewer",)


def platform_roles_for(membership_role: str, *, tenant_kind: str = "team") -> list[str]:
    """The `roles` claim for one membership; ``tenant_kind`` is accepted but no longer changes the answer."""
    return list(_PLATFORM_ROLES.get(membership_role, _FALLBACK_ROLES))


# `users.role` for the founding owner of a personal workspace.
_PERSONAL_OWNER_USER_ROLE = "tenant_admin"


@dataclass(frozen=True, slots=True)
class Identity:
    id: UUID
    email: str
    email_verified_at: datetime | None
    display_name: str
    status: str
    mfa_enabled: bool
    has_password: bool
    last_tenant_id: UUID | None
    failed_login_count: int
    lock_count: int
    locked_until: datetime | None
    lock_notified_at: datetime | None
    deletion_requested_at: datetime | None
    # Person-level: follows them across workspaces (`users` keeps its own copies).
    locale: str = "en"
    timezone: str = "UTC"
    # True while the password and second factor live in Keycloak; NOT inferable
    # from `has_password` (a native signup has no hash either).
    legacy_idp: bool = False
    # For first-run hints.
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: asyncpg.Record) -> Identity:
        return cls(
            id=row["id"],
            email=row["email"],
            email_verified_at=row["email_verified_at"],
            display_name=row["display_name"],
            status=row["status"],
            mfa_enabled=row["mfa_enabled"],
            has_password=row["has_password"],
            last_tenant_id=row["last_tenant_id"],
            failed_login_count=row["failed_login_count"],
            lock_count=row["lock_count"],
            locked_until=row["locked_until"],
            lock_notified_at=row["lock_notified_at"],
            deletion_requested_at=row["deletion_requested_at"],
            locale=row["locale"],
            timezone=row["timezone"],
            legacy_idp=row["legacy_idp"],
            created_at=row.get("created_at"),
        )


@dataclass(frozen=True, slots=True)
class Membership:
    tenant_id: UUID
    name: str
    kind: str
    role: str
    status: str


@dataclass(frozen=True, slots=True)
class MembershipLookup:
    """What one identity's membership in one workspace looks like.

    ``membership`` None means "no row" — no membership, or no such
    tenant. ``tenant_active`` is only meaningful when there is one.
    """

    membership: Membership | None
    tenant_active: bool


@dataclass(frozen=True, slots=True)
class LockState:
    """What one recorded failure did to an identity."""

    locked_until: datetime | None
    newly_locked: bool
    failed_login_count: int


# ── challenges ───────────────────────────────────────────────────────────


class PgChallengeStore:
    """:class:`~auth_service.domain.email_code.ChallengeStore` backed by ``auth_challenges``."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @staticmethod
    def _row(row: asyncpg.Record) -> ec.Challenge:
        return ec.Challenge(
            id=row["id"],
            kind=row["kind"],
            email=row["email"],
            identity_id=row["identity_id"],
            code_hash=row["code_hash"],
            expires_at=row["expires_at"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            consumed_at=row["consumed_at"],
            created_at=row["created_at"],
            metadata=_as_json(row["metadata"]),
        )

    async def open(
        self,
        *,
        challenge_id: UUID,
        kind: str,
        email: str,
        identity_id: UUID | None,
        code_hash: str,
        expires_at: datetime,
        max_attempts: int,
        client_type: str,
        ip: str,
        metadata: dict[str, Any] | None = None,
    ) -> ec.Challenge:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                INSERT INTO auth_challenges
                    (id, kind, email, identity_id, code_hash, expires_at,
                     max_attempts, client_type, ip, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING {_CHALLENGE_COLUMNS}
                """,
                challenge_id,
                kind,
                email,
                identity_id,
                code_hash,
                expires_at,
                max_attempts,
                client_type,
                ip,
                json.dumps(metadata or {}),
            )
        assert row is not None
        return self._row(row)

    async def consume_open_for_email(self, *, kind: str, email: str) -> int:
        """Supersede every open challenge for this address: only the newest code may work."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE auth_challenges
                SET consumed_at = now()
                WHERE kind = $1 AND email = $2 AND consumed_at IS NULL
                RETURNING id
                """,
                kind,
                email,
            )
        return len(rows)

    async def latest_open_for_email(self, *, kind: str, email: str) -> ec.Challenge | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {_CHALLENGE_COLUMNS} FROM auth_challenges
                WHERE kind = $1 AND email = $2 AND consumed_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                kind,
                email,
            )
        return self._row(row) if row is not None else None

    async def get(self, challenge_id: UUID) -> ec.Challenge | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_CHALLENGE_COLUMNS} FROM auth_challenges WHERE id = $1",
                challenge_id,
            )
        return self._row(row) if row is not None else None

    async def record_attempt(self, challenge_id: UUID, *, attempts: int) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE auth_challenges SET attempts = $2 WHERE id = $1",
                challenge_id,
                attempts,
            )

    async def consume(self, challenge_id: UUID) -> bool:
        """Spend the challenge; False when someone else spent it first (``consumed_at IS NULL`` guard)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE auth_challenges
                SET consumed_at = now()
                WHERE id = $1 AND consumed_at IS NULL
                RETURNING id
                """,
                challenge_id,
            )
        return row is not None

    async def delete(self, challenge_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM auth_challenges WHERE id = $1", challenge_id)


# ── identities, workspaces, memberships ──────────────────────────────────


class IdentityRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_by_email(self, email: str) -> Identity | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_IDENTITY_COLUMNS} FROM identities WHERE email = $1",
                ec.normalise_email(email),
            )
        return Identity.from_row(row) if row is not None else None

    async def get(self, identity_id: UUID) -> Identity | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_IDENTITY_COLUMNS} FROM identities WHERE id = $1", identity_id
            )
        return Identity.from_row(row) if row is not None else None

    async def list_memberships(self, identity_id: UUID) -> list[Membership]:
        """Every workspace this identity can reach (cross-tenant, hence the writer pool)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.id AS tenant_id, t.name, t.kind, m.role, m.status
                FROM tenant_memberships m
                JOIN tenants t ON t.id = m.tenant_id
                WHERE m.user_sub = $1 AND m.status = 'active' AND t.is_active
                ORDER BY (t.kind = 'personal') DESC, t.display_name, t.id
                """,
                identity_id,
            )
        return [
            Membership(
                tenant_id=r["tenant_id"],
                name=r["name"],
                kind=r["kind"],
                role=r["role"],
                status=r["status"],
            )
            for r in rows
        ]

    async def membership_in(self, identity_id: UUID, tenant_id: UUID) -> MembershipLookup:
        """This identity's standing in one workspace, unfiltered: the caller needs to tell the 403s apart."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT t.id AS tenant_id, t.name, t.kind, t.is_active,
                       m.role, m.status
                FROM tenants t
                LEFT JOIN tenant_memberships m
                       ON m.tenant_id = t.id AND m.user_sub = $1
                WHERE t.id = $2
                """,
                identity_id,
                tenant_id,
            )
        if row is None or row["role"] is None:
            # No such tenant or no membership: same answer, no enumeration.
            return MembershipLookup(membership=None, tenant_active=False)
        return MembershipLookup(
            membership=Membership(
                tenant_id=row["tenant_id"],
                name=row["name"],
                kind=row["kind"],
                role=row["role"],
                status=row["status"],
            ),
            tenant_active=row["is_active"],
        )

    async def set_last_tenant(self, identity_id: UUID, *, tenant_id: UUID) -> None:
        """Remember the workspace this person chose; the next sign-in lands there."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE identities SET last_tenant_id = $2 WHERE id = $1",
                identity_id,
                tenant_id,
            )

    async def create_with_personal_workspace(
        self,
        email: str,
        *,
        locale: str = "en",
        slug_hex: str | None = None,
        attempts: int = 3,
        display_name: str | None = None,
        password_hash: str | None = None,
        email_verified: bool = True,
    ) -> tuple[Identity, Membership]:
        """Signup in one transaction: identity + tenant + membership + ``users`` row, all or none.

        The ``users`` row is how the rest of the estate resolves a ``sub``. The last
        three arguments are the password-signup variant (code signup is the default).
        """
        email = ec.normalise_email(email)
        last_exc: asyncpg.UniqueViolationError | None = None
        for attempt in range(attempts):
            names = ec.personal_workspace_names(email, slug_hex=slug_hex)
            # Collisions are on the workspace name (email local part) or the slug;
            # retry with a suffixed name and a fresh slug.
            name = names.name if attempt == 0 else f"{names.name}-{secrets.token_hex(2)}"
            try:
                async with self._pool.acquire() as conn, conn.transaction():
                    identity_row = await conn.fetchrow(
                        f"""
                        INSERT INTO identities
                            (email, email_verified_at, display_name, status, password_hash)
                        VALUES ($1, CASE WHEN $3 THEN now() END, $2, 'active', $4)
                        RETURNING {_IDENTITY_COLUMNS}
                        """,
                        email,
                        # Email local part until the welcome step overrides it.
                        (display_name or "").strip() or names.name,
                        email_verified,
                        password_hash,
                    )
                    assert identity_row is not None
                    identity_id: UUID = identity_row["id"]

                    tenant_row = await conn.fetchrow(
                        """
                        INSERT INTO tenants
                            (name, display_name, slug, kind, locale, timezone,
                             status, is_active)
                        VALUES ($1, $2, $3, 'personal', $4, 'UTC', 'active', true)
                        RETURNING id, name, kind
                        """,
                        name,
                        names.display_name,
                        names.slug,
                        locale,
                    )
                    assert tenant_row is not None
                    tenant_id: UUID = tenant_row["id"]

                    await conn.execute(
                        """
                        INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
                        VALUES ($1, $2, 'owner', 'active')
                        """,
                        tenant_id,
                        identity_id,
                    )

                    # `users` is RLS-scoped even for tenant_writer; transaction-local setting.
                    await conn.execute(
                        "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                    )
                    await conn.execute(
                        """
                        INSERT INTO users (sub, tenant_id, email, display_name, role, status)
                        VALUES ($1, $2, $3, $5, $4, 'active')
                        """,
                        identity_id,
                        tenant_id,
                        email,
                        _PERSONAL_OWNER_USER_ROLE,
                        # Same name as the identity, or the two rows disagree.
                        identity_row["display_name"],
                    )

                    identity_row = await conn.fetchrow(
                        f"""
                        UPDATE identities SET last_tenant_id = $2 WHERE id = $1
                        RETURNING {_IDENTITY_COLUMNS}
                        """,
                        identity_id,
                        tenant_id,
                    )
                    assert identity_row is not None
            except asyncpg.UniqueViolationError as exc:
                # Email collision: somebody signed up between our lookup and here; no retry.
                if "identities" in str(getattr(exc, "constraint_name", "") or exc):
                    raise
                last_exc = exc
                logger.info(
                    "auth.signup.workspace_name_taken",
                    extra={"attempt": attempt + 1},
                )
                continue
            return Identity.from_row(identity_row), Membership(
                tenant_id=tenant_id,
                name=tenant_row["name"],
                kind=tenant_row["kind"],
                role="owner",
                status="active",
            )
        assert last_exc is not None
        raise last_exc

    async def ensure_personal_workspace(
        self,
        identity_id: UUID,
        email: str,
        *,
        locale: str = "en",
        slug_hex: str | None = None,
        attempts: int = 3,
    ) -> Membership | None:
        """Give an EXISTING identity a personal workspace if it has none; None when it already has one.

        Check and insert are one transaction so concurrent refreshes cannot both heal.
        """
        email = ec.normalise_email(email)
        last_exc: asyncpg.UniqueViolationError | None = None
        for attempt in range(attempts):
            names = ec.personal_workspace_names(email, slug_hex=slug_hex)
            name = names.name if attempt == 0 else f"{names.name}-{secrets.token_hex(2)}"
            try:
                async with self._pool.acquire() as conn, conn.transaction():
                    # FOR UPDATE on the identity row serialises racing callers.
                    locked = await conn.fetchrow(
                        "SELECT id FROM identities WHERE id = $1 FOR UPDATE", identity_id
                    )
                    if locked is None:
                        return None

                    existing = await conn.fetchval(
                        """
                        SELECT count(*) FROM tenant_memberships m
                          JOIN tenants t ON t.id = m.tenant_id
                         WHERE m.user_sub = $1 AND m.status = 'active'
                           AND t.status = 'active'
                        """,
                        identity_id,
                    )
                    if existing:
                        return None

                    tenant_row = await conn.fetchrow(
                        """
                        INSERT INTO tenants
                            (name, display_name, slug, kind, locale, timezone,
                             status, is_active)
                        VALUES ($1, $2, $3, 'personal', $4, 'UTC', 'active', true)
                        RETURNING id, name, kind
                        """,
                        name,
                        names.display_name,
                        names.slug,
                        locale,
                    )
                    assert tenant_row is not None
                    tenant_id: UUID = tenant_row["id"]

                    await conn.execute(
                        """
                        INSERT INTO tenant_memberships (tenant_id, user_sub, role, status)
                        VALUES ($1, $2, 'owner', 'active')
                        """,
                        tenant_id,
                        identity_id,
                    )

                    await conn.execute(
                        "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id)
                    )
                    # ON CONFLICT: a re-run must not fail (PK is (sub, tenant_id)).
                    await conn.execute(
                        """
                        INSERT INTO users (sub, tenant_id, email, display_name, role, status)
                        VALUES ($1, $2, $3, $5, $4, 'active')
                        ON CONFLICT DO NOTHING
                        """,
                        identity_id,
                        tenant_id,
                        email,
                        _PERSONAL_OWNER_USER_ROLE,
                        names.name,
                    )

                    await conn.execute(
                        "UPDATE identities SET last_tenant_id = $2 WHERE id = $1",
                        identity_id,
                        tenant_id,
                    )
            except asyncpg.UniqueViolationError as exc:
                last_exc = exc
                logger.info("auth.workspace.heal_name_taken", extra={"attempt": attempt + 1})
                continue
            logger.info(
                "auth.workspace.healed",
                extra={"identity_id": str(identity_id), "tenant_id": str(tenant_id)},
            )
            return Membership(
                tenant_id=tenant_id,
                name=tenant_row["name"],
                kind=tenant_row["kind"],
                role="owner",
                status="active",
            )
        assert last_exc is not None
        raise last_exc

    async def password_hash_for(self, identity_id: UUID) -> str | None:
        """The stored verifier, read on its own; :class:`Identity` deliberately never carries it."""
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT password_hash FROM identities WHERE id = $1", identity_id
            )

    async def set_password_hash(self, identity_id: UUID, *, password_hash: str) -> None:
        """Write a new verifier. Used at signup and by the silent rehash."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE identities SET password_hash = $2 WHERE id = $1",
                identity_id,
                password_hash,
            )

    async def mark_email_verified(self, identity_id: UUID) -> Identity | None:
        """Stamp ``email_verified_at`` unless already stamped (idempotent via the ``IS NULL`` guard)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE identities
                   SET email_verified_at = COALESCE(email_verified_at, now())
                 WHERE id = $1
             RETURNING {_IDENTITY_COLUMNS}
                """,
                identity_id,
            )
        return Identity.from_row(row) if row is not None else None

    async def reactivate(self, identity_id: UUID) -> list[UUID]:
        """Cancel a pending deletion; revives only the tenants this identity is alone in (mirror of :meth:`request_deletion`)."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE identities
                SET status = 'active', deletion_requested_at = NULL
                WHERE id = $1 AND status = 'pending_deletion'
                """,
                identity_id,
            )
            rows = await conn.fetch(
                """
                UPDATE tenants SET status = 'active', is_active = true
                WHERE status = 'dissolved' AND id IN (
                    SELECT m.tenant_id FROM tenant_memberships m
                    WHERE m.user_sub = $1 AND m.status = 'active'
                      AND (SELECT count(*) FROM tenant_memberships x
                           WHERE x.tenant_id = m.tenant_id AND x.status = 'active'
                             AND x.user_sub <> $1) = 0
                )
                RETURNING id
                """,
                identity_id,
            )
        return [r["id"] for r in rows]

    async def note_successful_login(self, identity_id: UUID, *, tenant_id: UUID) -> None:
        """Clear the failure counter and remember where they landed; ``lock_count`` is deliberately kept."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE identities
                SET failed_login_count = 0,
                    locked_until = NULL,
                    lock_notified_at = NULL,
                    last_tenant_id = $2
                WHERE id = $1
                """,
                identity_id,
                tenant_id,
            )

    async def register_failure(
        self, identity_id: UUID, *, policy: ec.LockoutPolicy, now: datetime | None = None
    ) -> LockState:
        """Record one failed sign-in under ``FOR UPDATE``; the arithmetic is :class:`~auth_service.domain.email_code.LockoutPolicy`."""
        now = now or datetime.now(UTC)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT failed_login_count, lock_count, locked_until
                FROM identities WHERE id = $1 FOR UPDATE
                """,
                identity_id,
            )
            if row is None:
                return LockState(locked_until=None, newly_locked=False, failed_login_count=0)
            if ec.is_locked(row["locked_until"], now=now):
                # Already locked: re-locking per attempt would extend the lock indefinitely.
                return LockState(
                    locked_until=row["locked_until"],
                    newly_locked=False,
                    failed_login_count=row["failed_login_count"],
                )
            count, locked_until = policy.after_failure(
                failed_count=row["failed_login_count"],
                previous_locks=row["lock_count"],
                now=now,
            )
            updated = await conn.fetchrow(
                """
                UPDATE identities
                SET failed_login_count = $2,
                    locked_until = $3,
                    lock_count = lock_count + $4,
                    lock_notified_at = CASE WHEN $3::timestamptz IS NULL
                                            THEN lock_notified_at ELSE NULL END
                WHERE id = $1
                RETURNING failed_login_count, locked_until
                """,
                identity_id,
                count,
                locked_until,
                1 if locked_until is not None else 0,
            )
            assert updated is not None
        return LockState(
            locked_until=updated["locked_until"],
            newly_locked=locked_until is not None,
            failed_login_count=updated["failed_login_count"],
        )

    async def claim_lock_notice(self, identity_id: UUID) -> bool:
        """True at most once per lock (the UPDATE is the claim), so N racing requests send one mail."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE identities
                SET lock_notified_at = now()
                WHERE id = $1
                  AND locked_until IS NOT NULL AND locked_until > now()
                  AND lock_notified_at IS NULL
                RETURNING id
                """,
                identity_id,
            )
        return row is not None

    # ── MFA state, profile, email change, deletion ───────────────────

    async def set_mfa_enabled(self, identity_id: UUID, *, enabled: bool) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE identities SET mfa_enabled = $2 WHERE id = $1", identity_id, enabled
            )

    async def update_profile(
        self,
        identity_id: UUID,
        *,
        display_name: str | None = None,
        locale: str | None = None,
        timezone: str | None = None,
    ) -> Identity | None:
        """PATCH semantics: only the fields actually supplied are written."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                UPDATE identities
                SET display_name = COALESCE($2, display_name),
                    locale       = COALESCE($3, locale),
                    timezone     = COALESCE($4, timezone)
                WHERE id = $1
                RETURNING {_IDENTITY_COLUMNS}
                """,
                identity_id,
                display_name,
                locale,
                timezone,
            )
        return Identity.from_row(row) if row is not None else None

    async def email_is_taken(self, email: str, *, excluding: UUID | None = None) -> bool:
        """Is this address already somebody's login? Includes `pending_deletion`, excludes `deleted`."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT 1 FROM identities
                WHERE email = $1 AND status <> 'deleted'
                  AND ($2::uuid IS NULL OR id <> $2)
                """,
                ec.normalise_email(email),
                excluding,
            )
        return row is not None

    async def change_email(self, identity_id: UUID, *, new_email: str) -> Identity | None:
        """Move the login identifier, re-stamp verification (a code reached the new address) and mirror onto `users`."""
        new_email = ec.normalise_email(new_email)
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                f"""
                UPDATE identities
                SET email = $2, email_verified_at = now()
                WHERE id = $1
                RETURNING {_IDENTITY_COLUMNS}
                """,
                identity_id,
                new_email,
            )
            if row is None:
                return None
            for tenant_id in await conn.fetch(
                "SELECT tenant_id FROM tenant_memberships WHERE user_sub = $1", identity_id
            ):
                await conn.execute(
                    "SELECT set_config('app.tenant_id', $1, true)", str(tenant_id["tenant_id"])
                )
                await conn.execute(
                    "UPDATE users SET email = $2 WHERE sub = $1", identity_id, new_email
                )
        return Identity.from_row(row)

    async def sole_owner_tenants_with_members(self, identity_id: UUID) -> list[Membership]:
        """Workspaces this identity would orphan: only owner AND somebody else still active."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.id AS tenant_id, t.name, t.kind, m.role, m.status
                FROM tenant_memberships m
                JOIN tenants t ON t.id = m.tenant_id
                WHERE m.user_sub = $1 AND m.role = 'owner' AND m.status = 'active'
                  AND (SELECT count(*) FROM tenant_memberships o
                       WHERE o.tenant_id = m.tenant_id AND o.role = 'owner'
                         AND o.status = 'active' AND o.user_sub <> $1) = 0
                  AND (SELECT count(*) FROM tenant_memberships x
                       WHERE x.tenant_id = m.tenant_id AND x.status = 'active'
                         AND x.user_sub <> $1) > 0
                ORDER BY t.display_name
                """,
                identity_id,
            )
        return [
            Membership(
                tenant_id=r["tenant_id"],
                name=r["name"],
                kind=r["kind"],
                role=r["role"],
                status=r["status"],
            )
            for r in rows
        ]

    async def request_deletion(self, identity_id: UUID) -> list[UUID]:
        """Mark for deletion and dissolve the workspaces nobody else is in; returns their ids. Nothing is destroyed here."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                UPDATE identities
                SET status = 'pending_deletion', deletion_requested_at = now()
                WHERE id = $1
                """,
                identity_id,
            )
            rows = await conn.fetch(
                """
                UPDATE tenants SET status = 'dissolved', is_active = false
                WHERE id IN (
                    SELECT m.tenant_id FROM tenant_memberships m
                    WHERE m.user_sub = $1 AND m.status = 'active'
                      AND (SELECT count(*) FROM tenant_memberships x
                           WHERE x.tenant_id = m.tenant_id AND x.status = 'active'
                             AND x.user_sub <> $1) = 0
                )
                RETURNING id
                """,
                identity_id,
            )
        return [r["id"] for r in rows]


# ── sessions ─────────────────────────────────────────────────────────────


def hash_refresh_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class SessionRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(
        self,
        *,
        identity_id: UUID,
        tenant_id: UUID,
        refresh_token: str,
        ttl_seconds: int,
        client_type: str,
        ip: str,
        user_agent: str,
        mfa: bool = False,
        device_name: str = "",
    ) -> tuple[UUID, datetime]:
        """Open a session and return ``(sid, expires_at)``."""
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO auth_sessions
                    (identity_id, tenant_id, refresh_token_hash, client_type,
                     ip, user_agent, mfa, expires_at, device_name,
                     last_authenticated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
                RETURNING id, expires_at
                """,
                identity_id,
                tenant_id,
                hash_refresh_token(refresh_token),
                client_type,
                ip,
                user_agent[:512],
                mfa,
                expires_at,
                device_name[:120],
            )
        assert row is not None
        return row["id"], row["expires_at"]

    async def get(self, session_id: UUID) -> SessionRow | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT {_SESSION_COLUMNS} FROM auth_sessions WHERE id = $1", session_id
            )
        return _session_row(row) if row is not None else None

    async def list_live(self, identity_id: UUID) -> list[SessionRow]:
        """Live sessions only (revoked and expired filtered here, not in the router)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT {_SESSION_COLUMNS} FROM auth_sessions
                WHERE identity_id = $1 AND revoked_at IS NULL AND expires_at > now()
                ORDER BY last_used_at DESC
                """,
                identity_id,
            )
        return [_session_row(r) for r in rows]

    async def revoke(self, session_id: UUID, *, identity_id: UUID, reason: str) -> bool:
        """End one session; False if not this identity's or already dead (``identity_id`` is in the WHERE)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE auth_sessions
                SET revoked_at = now(), revoked_reason = $3
                WHERE id = $1 AND identity_id = $2 AND revoked_at IS NULL
                RETURNING id
                """,
                session_id,
                identity_id,
                reason,
            )
        return row is not None

    async def revoke_all(
        self, identity_id: UUID, *, reason: str, except_session_id: UUID | None = None
    ) -> list[UUID]:
        """End every live session, optionally sparing the caller's own; returns the sids for the denylist."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE auth_sessions
                SET revoked_at = now(), revoked_reason = $2
                WHERE identity_id = $1 AND revoked_at IS NULL
                  AND ($3::uuid IS NULL OR id <> $3)
                RETURNING id
                """,
                identity_id,
                reason,
                except_session_id,
            )
        return [r["id"] for r in rows]

    async def find_by_refresh_token(self, token: str) -> RefreshMatch | None:
        """Which session this refresh token belongs to, matching both the current and the retired generation in one read."""
        digest = hash_refresh_token(token)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT {_SESSION_COLUMNS},
                       (refresh_token_hash = $1) AS is_current,
                       rotated_at
                FROM auth_sessions
                WHERE refresh_token_hash = $1 OR previous_refresh_token_hash = $1
                """,
                digest,
            )
        if row is None:
            return None
        return RefreshMatch(
            session=_session_row(row),
            is_current=row["is_current"],
            rotated_at=row["rotated_at"],
        )

    async def rotate(
        self,
        *,
        session_id: UUID,
        presented: str,
        new_token: str,
        expires_at: datetime,
        ip: str,
        presented_is_current: bool,
    ) -> bool:
        """Swap the session's refresh token for ``new_token``; the replaced token is in the WHERE.

        Invariants: ``previous_refresh_token_hash`` is always the token this rotation
        replaced (even on the grace path); ``rotated_at`` moves only when the
        presented token was the current one.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE auth_sessions
                SET refresh_token_hash = $3,
                    previous_refresh_token_hash = refresh_token_hash,
                    rotated_at = CASE WHEN $5 THEN now() ELSE rotated_at END,
                    expires_at = $4,
                    last_used_at = now(),
                    ip = COALESCE(NULLIF($6, ''), ip)
                WHERE id = $1
                  AND revoked_at IS NULL
                  AND (CASE WHEN $5 THEN refresh_token_hash ELSE previous_refresh_token_hash END)
                      = $2
                RETURNING id
                """,
                session_id,
                hash_refresh_token(presented),
                hash_refresh_token(new_token),
                expires_at,
                presented_is_current,
                ip,
            )
        return row is not None

    async def set_tenant(self, session_id: UUID, *, tenant_id: UUID) -> bool:
        """Point a live session at another workspace (refresh re-mints from the row)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE auth_sessions
                SET tenant_id = $2, last_used_at = now()
                WHERE id = $1 AND revoked_at IS NULL AND expires_at > now()
                RETURNING id
                """,
                session_id,
                tenant_id,
            )
        return row is not None

    async def touch_authenticated(self, session_id: UUID) -> None:
        """Stamp a fresh proof of identity on the session."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE auth_sessions SET last_authenticated_at = now(), last_used_at = now()"
                " WHERE id = $1",
                session_id,
            )


def build_repositories(pool: Any) -> tuple[IdentityRepository, PgChallengeStore, SessionRepository]:
    return IdentityRepository(pool), PgChallengeStore(pool), SessionRepository(pool)


# ── second factors ───────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class TotpRecord:
    identity_id: UUID
    secret_enc: str
    kek_tenant_id: UUID
    confirmed_at: datetime | None
    last_used_step: int | None


class TotpRepository:
    """``identity_totp`` — one candidate-or-confirmed secret per identity."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @staticmethod
    def _row(row: asyncpg.Record) -> TotpRecord:
        return TotpRecord(
            identity_id=row["identity_id"],
            secret_enc=row["secret_enc"],
            kek_tenant_id=row["kek_tenant_id"],
            confirmed_at=row["confirmed_at"],
            last_used_step=row["last_used_step"],
        )

    async def get(self, identity_id: UUID) -> TotpRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT identity_id, secret_enc, kek_tenant_id, confirmed_at, last_used_step"
                " FROM identity_totp WHERE identity_id = $1",
                identity_id,
            )
        return self._row(row) if row is not None else None

    async def put_candidate(
        self, identity_id: UUID, *, secret_enc: str, kek_tenant_id: UUID
    ) -> None:
        """Store an unconfirmed secret, replacing any earlier attempt; unconfirmed rows gate nothing."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO identity_totp
                    (identity_id, secret_enc, kek_tenant_id, confirmed_at, last_used_step)
                VALUES ($1, $2, $3, NULL, NULL)
                ON CONFLICT (identity_id) DO UPDATE
                SET secret_enc = EXCLUDED.secret_enc,
                    kek_tenant_id = EXCLUDED.kek_tenant_id,
                    confirmed_at = NULL,
                    last_used_step = NULL
                """,
                identity_id,
                secret_enc,
                kek_tenant_id,
            )

    async def confirm(self, identity_id: UUID, *, step: int) -> bool:
        """Promote the candidate to a real second factor; False if already confirmed (no step reset)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE identity_totp
                SET confirmed_at = now(), last_used_step = $2
                WHERE identity_id = $1 AND confirmed_at IS NULL
                RETURNING identity_id
                """,
                identity_id,
                step,
            )
        return row is not None

    async def spend_step(self, identity_id: UUID, *, step: int) -> bool:
        """Claim a TOTP time step; False when already spent (comparison in the WHERE, not Python)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE identity_totp
                SET last_used_step = $2
                WHERE identity_id = $1
                  AND confirmed_at IS NOT NULL
                  AND (last_used_step IS NULL OR last_used_step < $2)
                RETURNING identity_id
                """,
                identity_id,
                step,
            )
        return row is not None

    async def delete(self, identity_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM identity_totp WHERE identity_id = $1", identity_id)


class RecoveryCodeRepository:
    """``identity_recovery_codes`` — ten single-use hashes per identity."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def replace_all(self, identity_id: UUID, *, hashes: list[bytes]) -> None:
        """Issue a fresh set, invalidating every old code in the same transaction."""
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM identity_recovery_codes WHERE identity_id = $1", identity_id
            )
            await conn.executemany(
                "INSERT INTO identity_recovery_codes (identity_id, code_hash) VALUES ($1, $2)",
                [(identity_id, h) for h in hashes],
            )

    async def consume(self, identity_id: UUID, *, code_hash: bytes) -> bool:
        """Spend one code (single-statement claim); False if unknown or already used."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE identity_recovery_codes
                SET used_at = now()
                WHERE identity_id = $1 AND code_hash = $2 AND used_at IS NULL
                RETURNING id
                """,
                identity_id,
                code_hash,
            )
        return row is not None

    async def count_unused(self, identity_id: UUID) -> int:
        async with self._pool.acquire() as conn:
            n = await conn.fetchval(
                "SELECT count(*) FROM identity_recovery_codes"
                " WHERE identity_id = $1 AND used_at IS NULL",
                identity_id,
            )
        return int(n or 0)

    async def delete_all(self, identity_id: UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM identity_recovery_codes WHERE identity_id = $1", identity_id
            )


# ── sessions: listing, revocation, step-up ───────────────────────────────


@dataclass(frozen=True, slots=True)
class SessionRow:
    id: UUID
    identity_id: UUID
    tenant_id: UUID
    client_type: str
    device_name: str
    user_agent: str
    ip: str
    created_at: datetime
    last_used_at: datetime
    last_authenticated_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    # Whether the sign-in passed a second factor; refresh re-mints the claim from here.
    mfa: bool = False


@dataclass(frozen=True, slots=True)
class RefreshMatch:
    """A refresh token resolved to its session; ``is_current`` False = the retired generation (grace or replay is the caller's call)."""

    session: SessionRow
    is_current: bool
    rotated_at: datetime | None


def _session_row(row: asyncpg.Record) -> SessionRow:
    return SessionRow(
        id=row["id"],
        identity_id=row["identity_id"],
        tenant_id=row["tenant_id"],
        client_type=row["client_type"],
        device_name=row["device_name"],
        user_agent=row["user_agent"],
        ip=row["ip"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        last_authenticated_at=row["last_authenticated_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
        mfa=row["mfa"],
    )


_SESSION_COLUMNS = """
    id, identity_id, tenant_id, client_type, device_name, user_agent, ip,
    created_at, last_used_at, last_authenticated_at, expires_at, revoked_at,
    mfa
"""
