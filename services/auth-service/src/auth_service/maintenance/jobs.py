"""Scheduled maintenance for the identity tables (IDX-B3 D).

Every job here obeys the three rules ADR-0041 sets, and each rule is
load-bearing rather than ceremonial:

**Idempotent.** There is deliberately no advisory lock, so two replicas
can run the same job at the same instant. Every statement below is
therefore a predicate delete or a guarded update — "delete what is past
its expiry", never "delete the oldest 5000". Two concurrent runs converge
on the same state; the loser simply reports fewer rows.

**Batched.** A single unbounded `DELETE` on a table with months of
challenges takes a lock long enough to be an outage. Each job deletes in
bounded chunks until it runs out, so the longest statement is one chunk.

**Reports its work.** Each returns a row count, which becomes the
`scheduler.job.completed` audit payload and the `mdx_auth_maint_rows_total`
metric. A job that silently does nothing is indistinguishable from a job
that is not running, and that distinction is the entire point of the
freshness alert.
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

# Chunk size for predicate deletes. Big enough that a quiet system
# finishes in one pass, small enough that one statement is never the
# long pole.
BATCH = 5_000

# How long a spent challenge is kept. Not zero: a support question of the
# form "did a code go out at 09:14" is answerable for a day, and the rows
# carry no secret — the code is a hash bound to a consumed row.
CHALLENGE_RETENTION_HOURS = 24
# A revoked session row is audit context, not state. Ninety days matches
# the audit retention window.
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
    """Run a `DELETE ... WHERE id IN (SELECT ... LIMIT $n)` until it stops.

    The LIMIT lives in the caller's SQL so each job can express its own
    predicate; this only drives the loop and counts.
    """
    total = 0
    async with pool.acquire() as conn:
        while True:
            tag = await conn.execute(sql, *args, BATCH)
            # asyncpg returns "DELETE <n>" / "UPDATE <n>".
            moved = int(tag.rsplit(" ", 1)[-1] or 0)
            total += moved
            if moved < BATCH:
                return total


# ── the jobs ─────────────────────────────────────────────────────────────


async def purge_challenges(pool: Any) -> JobResult:
    """Drop `auth_challenges` rows a day past expiry (IDX-A3 J, deferred here).

    Covers every kind — email_login, mfa_login, totp_enroll, email_change,
    reauth — because the predicate is expiry, not purpose. A row that has
    expired cannot be used for anything by anyone.
    """
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
    """Revoke sessions past their absolute expiry, then reap old dead rows.

    Two steps because they mean different things. The first closes
    sessions the database still considers live — a refresh would be
    refused anyway, but the row is what `GET /auth/sessions` shows a user,
    and showing somebody a session that cannot be used is a support
    ticket. The second is housekeeping.
    """
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
    """The IDX-A5 F6 purge, on a schedule.

    Shares its implementation with
    ``scripts/ops/idx-purge-deleted-identities.py`` rather than
    reimplementing it: an account deletion that behaves differently
    depending on whether an operator or a timer ran it is the worst kind
    of bug to discover from a GDPR request.
    """
    from .purge_impl import due_identities, purge_one

    purged = 0
    async with pool.acquire() as conn:
        due = await due_identities(conn, grace_days=DELETION_GRACE_DAYS)
        for row in due:
            await purge_one(conn, row["id"])
            purged += 1
            logger.info("auth.maint.identity_purged", extra={"identity_id": str(row["id"])})
    return JobResult("purge-deleted-identities", purged)


async def sample_gauges(pool: Any) -> JobResult:
    """Publish the two "how much is out there" gauges.

    Sampled rather than maintained incrementally: a counter kept in step
    with every session start and revoke drifts the first time a process
    restarts mid-operation, and the number is only ever read by a human
    looking at a dashboard.
    """
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
    """Report the signing keys, and warn before one strands the fleet.

    A key that expires with no successor is not a degraded issuer, it is
    no issuer: `KeySet.active()` raises and the service stops minting.
    The warning window has to be long enough to schedule a deploy.
    """
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
    """Re-wrap TOTP secrets under the current keys.

    Manual by design. Re-keying every second factor in the estate is not
    something a timer should decide to do, and the operator wants the
    dry-run output first — see `scripts/ops/idx-rekey-totp-secrets.py`,
    which is the real implementation.
    """
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
    """Stamp the freshness gauge and the row counter.

    The gauge is set **only** on success. That is what makes
    `AuthMaintenanceStale` meaningful: a job failing every run keeps its
    timestamp frozen and the alert fires, where a gauge set on every
    attempt would look healthy while the work never happened.
    """
    # ``job_name`` rather than ``job``: the Prometheus exporter reserves
    # ``job`` for the service and drops a metric that reuses it.
    _rows_total.add(rows, {"job_name": job})
    _last_success.set(datetime.now(UTC).timestamp(), {"job_name": job})
