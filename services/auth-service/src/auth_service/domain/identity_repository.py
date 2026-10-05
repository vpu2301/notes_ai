"""SQL for `identities`, `auth_challenges`, `auth_sessions` (migration 0024).

Everything here runs on the ``tenant_writer`` pool. That is not a
convenience: these three tables have no ``tenant_id`` to scope by (an
identity exists before it has a workspace), so their isolation is the
role grant plus the writer-only RLS policy, and ``app_role`` — what the
rest of the fleet connects as — cannot reach them at all.

The one place a tenant scope *is* set is :meth:`IdentityRepository.
create_with_personal_workspace`: the ``users`` row it writes lives under
``users_writer_tenant``, which reads ``app.tenant_id``. That transaction
sets it with ``set_config(..., true)`` after the tenant row exists, so
the setting dies with the transaction exactly as ``tenant_connection``
would leave it.

The pure decision logic — which attempt consumes a challenge, when a
lock trips, what a personal workspace is called — is in
:mod:`auth_service.domain.email_code`. This module only reads and writes
rows, so that logic stays testable without a database.
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

# Management role on the membership → the platform roles the JWT carries.
# Membership roles are the workspace's own vocabulary (who may manage the
# team); the `roles` claim is the fleet's authorization vocabulary. Kept
# explicit rather than derived so that adding a membership role is a
# deliberate decision about what it may do everywhere else.
_PLATFORM_ROLES: dict[str, tuple[str, ...]] = {
    # Whoever runs a workspace also works in it. `tenant_admin` alone
    # carries no content permission at all (S14), so an owner mapped to
    # it alone signs in and then 403s on every note, space and recording
    # — which is every self-serve account on its first use, since the
    # person who creates a workspace is its owner. `docs/auth/roles.md`
    # has always said a founder holds BOTH roles; this is that guidance
    # applied by default instead of left as a manual step nobody does.
    "owner": ("tenant_admin", "member"),
    "admin": ("tenant_admin", "member"),
    "member": ("member",),
    "assistant": ("member",),
    "viewer": ("viewer",),
}
# A membership role we do not recognise must not silently become an admin.
_FALLBACK_ROLES: tuple[str, ...] = ("viewer",)


def platform_roles_for(membership_role: str, *, tenant_kind: str = "team") -> list[str]:
    """The `roles` claim for one membership.

    Membership roles are the workspace's own vocabulary (who may manage
    the team); the `roles` claim is the fleet's authorization vocabulary.
    The map above is explicit rather than derived so that adding a
    membership role is a deliberate decision about what it may do
    everywhere else.

    **Managing a workspace never removes the ability to work in it.**
    S14 split administration from content so that `tenant_admin` holds
    no `note.*`, `asr.*` or `dictation.*` — but that split is a statement
    about the *role*, not about the person: `docs/auth/roles.md` says a
    founder who both runs the workspace and takes notes holds both roles,
    and a permission check passes on any granting role. Handing an owner
    `tenant_admin` alone does not restrict an administrator, it locks out
    the only account the workspace has. BE-3's first-use test caught
    exactly that shape: `403 deny: roles=['tenant_admin'] cannot
    'asr.write'` on the first recording a new account ever attempts.

    An admin-only account — administration without content — is still
    expressible; it is a realm-role assignment somebody makes on purpose
    (`PUT /admin/users/{sub}/roles`), not the default a person lands in
    by creating the workspace they are the only member of.

    ``tenant_kind`` is accepted for callers that pass it and no longer
    changes the answer: a personal workspace's owner and a team's owner
    both work in what they administer.
    """
    return list(_PLATFORM_ROLES.get(membership_role, _FALLBACK_ROLES))


# The `users.role` value written for the founding owner of a personal
# workspace. They are alone in it, so they administer it.
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
    # Person-level, not workspace-level: the language someone reads mail
    # in follows them across workspaces. `users` keeps its own copies
    # until IDX-B2 retires that table.
    locale: str = "en"
    timezone: str = "UTC"
    # BE-1 / migration 0031. True while this person's password and second
    # factor live in Keycloak. Read with `mfa_enabled` by BE-3: the two
    # together are what make an emailed code an unacceptable single
    # factor. NOT inferable from `has_password` — a native signup has no
    # password hash either (see the migration header).
    legacy_idp: bool = False
    # Sprint 21: when the account came to exist, for first-run hints.
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
    """The :class:`auth_service.domain.email_code.ChallengeStore` Protocol,
    backed by ``auth_challenges``."""

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
        """Supersede every open challenge for this address.

        Only the newest code may work. Without this, asking for a second
        code because the first mail was slow would leave two live codes,
        doubling an attacker's guessing budget for the same address.
        """
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
        """Spend the challenge. False when someone else spent it first.

        The ``consumed_at IS NULL`` guard is what makes a double-submitted
        code log in exactly once: both requests read a live challenge and
        both match the code, but only one UPDATE returns a row.
        """
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
        """Every workspace this identity can reach.

        Cross-tenant by definition, which is why it runs on the writer
        pool — ``tenant_memberships``' app_role policy sees one tenant.
        """
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
        """This identity's standing in one workspace, whatever that standing is.

        Unlike :meth:`list_memberships` — which answers "where may I go"
        and therefore filters to live memberships in live tenants — this
        answers "why not", and the caller needs the difference between a
        suspended membership, a dissolved workspace and a workspace this
        person was never in. Those are three different 403s
        (``docs/api/error-codes.md``).
        """
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
            # No such tenant, or no membership in it. Deliberately the same
            # answer: whether a workspace exists is not this caller's
            # business, and two answers here would enumerate them.
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
        """Remember the workspace this person chose.

        It is where the next sign-in — on this Mac or another device —
        lands, which is the whole point of switching being a decision
        rather than a per-session accident.
        """
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
        """Signup, in one transaction: identity + tenant + membership + user.

        All four or none. A half-built account is worse than no account:
        the address is taken, so the person cannot retry, and there is no
        workspace for them to land in — they are locked out by their own
        successful signup.

        The ``users`` row is not in the pack's list, and is written anyway.
        ``users`` is how the rest of the estate resolves a ``sub`` to a
        person: note-service reads it to offer share recipients,
        notification-service reads it to find an address to mail. An
        identity without one holds a perfectly valid token and is
        invisible to both.

        The last three arguments are BE-0's password signup and default to
        BE-3's code signup, which is the older caller: a code signup proves
        the address as part of creating the account (``email_verified``
        True) and sets no password. A password signup passes a name the
        person typed, a verifier, and ``email_verified=False`` — the
        account exists but cannot start a session until the mailed code
        comes back. Both write the same four rows; only these three columns
        differ, which is why this stayed one method.
        """
        email = ec.normalise_email(email)
        last_exc: asyncpg.UniqueViolationError | None = None
        for attempt in range(attempts):
            names = ec.personal_workspace_names(email, slug_hex=slug_hex)
            # Collisions are on the workspace NAME (the email local part:
            # every `ada@` on every domain wants "ada") and, far less
            # likely, on the random slug. Suffix the name on retry; the
            # slug is redrawn by generating fresh names.
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
                        # BE-3 F4: the email local part until the welcome
                        # step overrides it. An empty display name renders
                        # as a blank avatar and an unnamed author on every
                        # note the person writes before they finish
                        # onboarding — which some of them never will.
                        # BE-0 has a better answer: the person typed one.
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

                    # `users` is RLS-scoped even for tenant_writer, so the
                    # connection needs a tenant before the insert. Local to
                    # this transaction, cleared at COMMIT.
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
                        # The same name the identity got, or the two rows
                        # disagree about who this is the moment somebody
                        # types one at signup.
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
                # An identity-email collision means someone signed up with
                # this address between our lookup and here — that is not a
                # naming problem and retrying will not help.
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
        """Give an EXISTING identity a personal workspace if it has none.

        BE-2 F3 (pulled forward from IDX-B1 F5). The account states this
        heals are all real and none of them is the user's fault:

        * an identity backfilled from a ``users`` row whose only
          membership was later removed;
        * a signup whose transaction committed the identity and then lost
          the connection (the transaction makes this impossible today —
          this is defence against the day it stops being one method);
        * a person removed from the last team workspace they were in, who
          would otherwise get ``409 no_workspace`` on every sign-in with
          no way to act on it.

        Returns ``None`` when the identity already has an active
        membership: healing is what this does, not what it insists on. The
        check and the insert are in one transaction, so two concurrent
        refreshes cannot each decide the workspace is missing.

        The bridge ``users`` row is written here for the same reason
        signup writes one — an identity without it cannot author content
        until IDX-B2 (see migration 0031).
        """
        email = ec.normalise_email(email)
        last_exc: asyncpg.UniqueViolationError | None = None
        for attempt in range(attempts):
            names = ec.personal_workspace_names(email, slug_hex=slug_hex)
            name = names.name if attempt == 0 else f"{names.name}-{secrets.token_hex(2)}"
            try:
                async with self._pool.acquire() as conn, conn.transaction():
                    # FOR UPDATE on the identity row, not on memberships:
                    # it is the one row both racing callers are certain to
                    # touch, and it is what serialises them.
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
                    # ON CONFLICT because a `users` row for this sub may
                    # survive in another tenant; the PK is (sub, tenant_id)
                    # so this one is new, but a re-run must not fail.
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
        """The stored verifier, read on its own and never as part of :class:`Identity`.

        ``Identity`` exposes ``has_password`` and not the hash, deliberately:
        the dataclass is passed around routers, logged in tests and returned
        through service layers, and a verifier that rides along in it will
        eventually be somewhere it should not be. One caller needs the real
        value — the password login — so it asks for it explicitly.
        """
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
        """Stamp ``email_verified_at``, unless it is already stamped.

        Idempotent, and the ``IS NULL`` guard is the reason: two tabs
        submitting the same code must not move the timestamp, which is the
        record of when the address was first proved.
        """
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
        """Cancel a pending deletion because the owner just signed in.

        Symmetric with :meth:`request_deletion`, and it has to be: that
        method dissolves the workspaces nobody else is in, and a
        reactivation that restored only the identity would hand the user
        back an account with nowhere to go — no memberships, so no `tid`,
        so no token. The mail this flow sends promises the account comes
        back "exactly as it was", and this is the half that keeps it.

        Only tenants this identity is alone in are revived, so a workspace
        dissolved for any other reason stays dissolved.
        """
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
        """Clear the lockout counters and remember where they landed.

        ``lock_count`` is deliberately NOT reset: it is the memory that
        makes the next lock longer than the last one, and an attacker who
        can reach a successful login has already won more than that.
        """
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
        """Record one failed sign-in and apply the lockout policy.

        Read-modify-write under ``FOR UPDATE`` so two concurrent wrong
        codes cannot both read count 9 and leave the account at 10 with
        no lock. The arithmetic itself is
        :class:`~auth_service.domain.email_code.LockoutPolicy`, unit-tested
        without a database.
        """
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
                # Already locked: the count is not the interesting number
                # any more, and re-locking on every attempt would extend
                # the lock for as long as an attacker keeps knocking.
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
        """True at most once per lock — the caller may send the locked mail.

        The claim is the UPDATE itself (``lock_notified_at IS NULL`` in the
        WHERE), so N racing requests against a locked account produce one
        mail, not N. Without it the lockout is a way to make us mail
        somebody as fast as an attacker can type.
        """
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

    # ── IDX-A5: MFA state, profile, email change, deletion ───────────

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
        """Is this address already somebody's login?

        Includes `pending_deletion` identities: their address is still
        theirs until the purge rewrites it, and signing in reclaims the
        account. Excludes `deleted`, whose address was rewritten and can
        never collide.
        """
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
        """Move the login identifier, and re-stamp verification.

        `email_verified_at` is reset to now rather than cleared: the change
        only happens after a code delivered to the new address, so it is
        verified at exactly this moment. Also mirrors the address onto the
        `users` rows the rest of the estate still reads (IDX-B2 retires
        that duplication).
        """
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
        """Workspaces this identity would orphan by leaving.

        The rule is "only owner AND somebody else is still active" — a
        one-person workspace is dissolved with the account, but a team
        must never be left with nobody who can administer it.
        """
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
        """Mark for deletion and dissolve the workspaces nobody else is in.

        Returns the dissolved tenant ids. The identity row survives the
        grace period intact — that is what makes signing in able to undo
        this — so nothing is destroyed here; the purge does that.
        """
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
        """Every session the sessions screen should show.

        Revoked and expired rows are filtered out here rather than in the
        router: "where am I signed in" is a question about live access,
        and a list padded with dead sessions makes the live ones harder to
        spot — which is the one thing the screen exists for.
        """
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
        """End one session. False if it is not this identity's, or already dead.

        ``identity_id`` is in the WHERE clause, not checked beforehand, so
        there is no window in which a session could be re-owned between
        the check and the write — and so the route can answer 404 for
        "someone else's sid" and "no such sid" identically.
        """
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
        """End every live session, optionally sparing the caller's own.

        Returns the sids so the caller can push each onto the denylist —
        the DB row stops the next refresh, the denylist stops the access
        token already in someone's hands, and only both together close the
        window.
        """
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
        """Which session, if any, this refresh token belongs to.

        Answers for both generations at once — the current token and the
        one the last rotation retired — because the caller has to tell
        those apart and a second round trip to do it would open a window
        between the two reads.
        """
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
        """Swap the session's refresh token for ``new_token``.

        The token being replaced is in the WHERE clause, so two concurrent
        refreshes carrying the same token cannot both succeed: the second
        UPDATE matches nothing and its caller is told to look again, which
        is how the grace and replay paths get their evidence.

        Two invariants, and the reason for each:

        * ``previous_refresh_token_hash`` is always **the token this
          rotation replaced**. Even on the grace path — where the caller
          presented the already-retired token — the outgoing current token
          is the one worth remembering: it is live, somebody is holding it,
          and orphaning it would sign that somebody out for having won a
          race they did not know they were in.
        * ``rotated_at`` moves only when the presented token *was* the
          current one. The grace window is measured from the rotation that
          retired a token, so a caller re-presenting one cannot keep
          extending its own grace.
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
        """Point a live session at another workspace.

        The session row is what `refresh` re-mints from, so this is what
        makes a switch outlive the access token that carried it — and what
        makes "I closed the lid in workspace B" still true tomorrow.
        """
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
        """Stamp a fresh proof of identity on the session (IDX-A5 F3)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE auth_sessions SET last_authenticated_at = now(), last_used_at = now()"
                " WHERE id = $1",
                session_id,
            )


def build_repositories(pool: Any) -> tuple[IdentityRepository, PgChallengeStore, SessionRepository]:
    return IdentityRepository(pool), PgChallengeStore(pool), SessionRepository(pool)


# ── second factors (IDX-A5) ──────────────────────────────────────────────


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
        """Store an unconfirmed secret, replacing any earlier attempt.

        Unconfirmed (``confirmed_at IS NULL``) so it gates nothing: a
        person who scans the QR and then closes the tab has not enabled
        MFA and must not be locked out by the row that is left behind.
        """
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
        """Promote the candidate to a real second factor. False if already confirmed.

        The ``confirmed_at IS NULL`` guard makes a double-submitted
        confirmation idempotent instead of resetting the step counter,
        which would reopen the replay window this sprint closes.
        """
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
        """Claim a TOTP time step. False when it was already spent.

        The comparison is in the WHERE clause, not in Python, so two
        requests carrying the same code in the same window cannot both
        read the old value and both succeed.
        """
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
        """Issue a fresh set, invalidating every old code in the same transaction.

        Regeneration must not leave a window where both sets work: a user
        regenerates precisely because they think the old list leaked.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM identity_recovery_codes WHERE identity_id = $1", identity_id
            )
            await conn.executemany(
                "INSERT INTO identity_recovery_codes (identity_id, code_hash) VALUES ($1, $2)",
                [(identity_id, h) for h in hashes],
            )

    async def consume(self, identity_id: UUID, *, code_hash: bytes) -> bool:
        """Spend one code. False if it is unknown or already used.

        Single-statement claim: the same code submitted twice concurrently
        marks one row once, and the loser is told the code is invalid —
        which, by then, it is.
        """
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


# ── sessions: listing, revocation, step-up (IDX-A5 F4) ───────────────────


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
    # Whether the sign-in that opened this session passed a second factor.
    # Refresh re-mints the access token from the session row, and dropping
    # the claim on the way through would quietly demote every MFA session
    # fifteen minutes after it started.
    mfa: bool = False


@dataclass(frozen=True, slots=True)
class RefreshMatch:
    """A refresh token resolved to its session, and to its generation.

    ``is_current`` False means the token is the one the last rotation
    retired: a retry inside the grace window, or a replay after it. The
    difference is arithmetic on ``rotated_at``, and it is the caller's to
    make — the repository does not decide what a session deserves.
    """

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
