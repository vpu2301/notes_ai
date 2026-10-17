"""Scheduled maintenance for the identity tables (ADR-0041).

Every job is idempotent (predicate deletes, no advisory lock), batched, and
reports a row count (audit payload + `mdx_auth_maint_rows_total`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from opentelemetry import metrics

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.auth.maint")
_rows_total = _meter.create_counter(
    "mdx_auth_maint_rows_total",
    description="Rows affected by a maintenance job",
    unit="1",
)
_last_success = _meter.create_gauge(
    "mdx_auth_maint_last_success_timestamp",
    description="Unix time of a maintenance job's last successful run",
    unit="s",
)
_session_active = _meter.create_gauge(
    "mdx_auth_session_active",
    description="Live (unrevoked, unexpired) native sessions",
    unit="1",
)
_device_active = _meter.create_gauge(
    "mdx_auth_device_active",
    description="Active device credentials",
    unit="1",
)

# Chunk size for predicate deletes.
BATCH = 5_000

# Spent challenges are kept a day for support questions (rows carry no secret).
CHALLENGE_RETENTION_HOURS = 24
# Revoked session rows are audit context; 90 days matches the audit retention.
SESSION_RETENTION_DAYS = 90
DELETION_GRACE_DAYS = 30


@dataclass(frozen=True, slots=True)
class JobResult:
    """What a job did. Becomes the audit payload and the metric."""

    job: str
    rows: int
    detail: dict[str, Any] | None = None

    def as_payload(self) -> dict[str, Any]:
        return {"job": self.job, "rows": self.rows, **(self.detail or {})}


async def _delete_in_batches(pool: Any, sql: str, *args: Any) -> int:
    """Run a `DELETE ... WHERE id IN (SELECT ... LIMIT $n)` until it stops; counts rows."""
    total = 0
    async with pool.acquire() as conn:
        while True:
            tag = await conn.execute(sql, *args, BATCH)
            moved = int(tag.rsplit(" ", 1)[-1] or 0)
            total += moved
            if moved < BATCH:
                return total


# ── the jobs ─────────────────────────────────────────────────────────────


async def purge_challenges(pool: Any) -> JobResult:
    """Drop `auth_challenges` rows a day past expiry, every kind."""
    rows = await _delete_in_batches(
        pool,
        f"""
        DELETE FROM auth_challenges
        WHERE id IN (
            SELECT id FROM auth_challenges
            WHERE expires_at < now() - interval '{CHALLENGE_RETENTION_HOURS} hours'
            LIMIT $1
        )
        """,
    )
    return JobResult("purge-challenges", rows)


async def expire_sessions(pool: Any) -> JobResult:
    """Revoke sessions past their absolute expiry (so the sessions list is honest), then reap old dead rows."""
    async with pool.acquire() as conn:
        tag = await conn.execute(
            """
            UPDATE auth_sessions
            SET revoked_at = now(), revoked_reason = COALESCE(revoked_reason, 'admin')
            WHERE revoked_at IS NULL AND expires_at < now()
            """
        )
        expired = int(tag.rsplit(" ", 1)[-1] or 0)

    reaped = await _delete_in_batches(
        pool,
        f"""
        DELETE FROM auth_sessions
        WHERE id IN (
            SELECT id FROM auth_sessions
            WHERE revoked_at IS NOT NULL
              AND revoked_at < now() - interval '{SESSION_RETENTION_DAYS} days'
            LIMIT $1
        )
        """,
    )
    return JobResult("expire-sessions", expired + reaped, {"expired": expired, "reaped": reaped})


async def purge_deleted_identities(pool: Any) -> JobResult:
    """The account purge on a schedule; same implementation as the operator script."""
    from .purge_impl import due_identities, purge_one

    purged = 0
    async with pool.acquire() as conn:
        due = await due_identities(conn, grace_days=DELETION_GRACE_DAYS)
        for row in due:
            await purge_one(conn, row["id"])
            purged += 1
            logger.info("auth.maint.identity_purged", extra={"identity_id": str(row["id"])})
    return JobResult("purge-deleted-identities", purged)


async def sweep_invitations(pool: Any) -> JobResult:
    """W2: revoked/expired invitations 90 days on (the address is PII), and "Left" rows after 30."""
    from ..domain.invitation_repository import InvitationRepository
    from ..tenants_repository import sweep_left_members

    invitations = await InvitationRepository(pool).sweep(older_than_days=SESSION_RETENTION_DAYS)
    async with pool.acquire() as conn:
        left = await sweep_left_members(conn, older_than_days=DELETION_GRACE_DAYS)
    return JobResult(
        "sweep-invitations", invitations + left, {"invitations": invitations, "left": left}
    )


async def sweep_guests(pool: Any) -> JobResult:
    """W3: a guest whose last note grant is gone (and who has no open note invitation) leaves.

    Not immediately: the membership must be older than a day, so an author who re-shares
    the same day does not have to re-invite. The row becomes "Left" (suspended + left_at);
    the person's session moves to Personal on its next refresh; `sweep-invitations` deletes
    the row 30 days later.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            UPDATE tenant_memberships m
               SET status = 'suspended', left_at = now()
             WHERE m.role = 'guest' AND m.status = 'active'
               AND m.created_at < now() - interval '24 hours'
               AND NOT EXISTS (SELECT 1 FROM note_collaborators c
                                WHERE c.tenant_id = m.tenant_id AND c.user_sub = m.user_sub)
               AND NOT EXISTS (SELECT 1 FROM tenant_invitations i
                                 JOIN identities p ON p.email = i.email
                                WHERE i.tenant_id = m.tenant_id AND p.id = m.user_sub
                                  AND i.note_id IS NOT NULL
                                  AND i.accepted_at IS NULL AND i.revoked_at IS NULL
                                  AND i.expires_at > now())
            RETURNING m.tenant_id, m.user_sub
            """
        )
    for row in rows:
        logger.info(
            "auth.maint.guest_removed",
            extra={"tenant_id": str(row["tenant_id"]), "identity_id": str(row["user_sub"])},
        )
    return JobResult("sweep-guests", len(rows), {"reason": "no_grants"})


async def sample_gauges(pool: Any) -> JobResult:
    """Publish the two size gauges (sampled, not maintained incrementally: counters drift across restarts)."""
    async with pool.acquire() as conn:
        sessions = int(
            await conn.fetchval(
                "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at > now()"
            )
            or 0
        )
        devices = int(
            await conn.fetchval(
                "SELECT count(*) FROM service_credentials"
                " WHERE kind = 'device' AND status = 'active'"
            )
            or 0
        )
    _session_active.set(sessions)
    _device_active.set(devices)
    return JobResult("sample-gauges", 0, {"sessions_active": sessions, "devices_active": devices})


async def signing_key_status(pool: Any, *, warn_days: int = 30) -> JobResult:
    """Report the signing keys and warn before one expires with no successor (the service would stop minting)."""
    from ..config import settings
    from ..domain.signing_keys import KeySet

    del pool
    raw = settings.signing_keys_json()
    if not raw:
        return JobResult("signing-key-status", 0, {"configured": False})
    keys = KeySet.from_json(raw)
    now = datetime.now(UTC)
    active = keys.active(now)
    days_left = (active.not_after - now).days
    detail = {
        "active_kid": active.kid,
        "not_after": active.not_after.isoformat(),
        "days_left": days_left,
        "kids": list(keys.kids),
    }
    if days_left < warn_days:
        logger.warning("auth.maint.signing_key_expiring", extra=detail)
    else:
        logger.info("auth.maint.signing_key_ok", extra=detail)
    return JobResult("signing-key-status", 0, detail)


async def rotate_kek(pool: Any) -> JobResult:
    """Re-wrap TOTP secrets under the current keys; manual by design (see scripts/ops/idx-rekey-totp-secrets.py)."""
    del pool
    return JobResult(
        "rotate-kek",
        0,
        {
            "manual": True,
            "run": "uv run python scripts/ops/idx-rekey-totp-secrets.py --dry-run",
        },
    )


def record_success(job: str, rows: int) -> None:
    """Stamp the freshness gauge (ONLY on success, so `AuthMaintenanceStale` can fire) and the row counter."""
    # ``job_name``: the Prometheus exporter reserves ``job`` and drops a metric that reuses it.
    _rows_total.add(rows, {"job_name": job})
    _last_success.set(datetime.now(UTC).timestamp(), {"job_name": job})
