"""Scheduled maintenance for auth-service (IDX-B3 D), per ADR-0041.

One registry, two hosts:

* in-process, wrapped in ``observability.run_periodic`` inside the
  service lifespan, behind ``MDX_BACKGROUND_JOBS``;
* out-of-process, ``python -m auth_service.maintenance <job>`` (also
  installed as ``mdx-auth-maint``), for a cron or a one-off.

Both go through the same :func:`run_job`, so a job run by hand does
exactly what the scheduler does — including the audit row and the
metrics. The alternative, a CLI that reimplements the job, is how the
two drift until the manual path is the one nobody trusts.

No advisory lock, deliberately: ADR-0041's stated trade-off is that every
job is idempotent, so a second replica running the same job is redundant
rather than harmful.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from . import jobs
from .jobs import JobResult

logger = logging.getLogger(__name__)

# The reserved tenant scheduler audit rows are written under (ADR-0041).
# The same platform tenant IDX-A3 introduced for events that belong to no
# customer — a purge sweep is nobody's workspace's business.
GLOBAL_TENANT_SETTING = "auth_platform_tenant_id"


@dataclass(frozen=True, slots=True)
class Job:
    name: str
    interval_seconds: int | None
    fn: Callable[[Any], Awaitable[JobResult]]
    summary: str

    @property
    def scheduled(self) -> bool:
        """False for jobs an operator must decide to run."""
        return self.interval_seconds is not None


JOBS: tuple[Job, ...] = (
    Job(
        "purge-challenges",
        15 * 60,
        jobs.purge_challenges,
        "delete auth_challenges more than 24 h past expiry",
    ),
    Job(
        "expire-sessions",
        60 * 60,
        jobs.expire_sessions,
        "revoke sessions past absolute expiry; reap rows revoked over 90 days ago",
    ),
    Job(
        "purge-deleted-identities",
        24 * 60 * 60,
        jobs.purge_deleted_identities,
        "crypto-shred identities whose 30-day deletion grace has run out",
    ),
    Job(
        "sample-gauges",
        5 * 60,
        jobs.sample_gauges,
        "publish mdx_auth_session_active and mdx_auth_device_active",
    ),
    Job(
        "signing-key-status",
        24 * 60 * 60,
        jobs.signing_key_status,
        "report the active signing key and warn when it is within 30 days of expiry",
    ),
    # Manual: re-keying every second factor in the estate is not a
    # decision a timer should make, and the operator wants the dry run
    # first.
    Job("rotate-kek", None, jobs.rotate_kek, "re-wrap TOTP secrets under the current keys"),
)

BY_NAME: dict[str, Job] = {j.name: j for j in JOBS}


async def run_job(job: Job, pool: Any) -> JobResult:
    """Run one job and record its success. Errors propagate to the caller.

    ``run_job_once`` (the scheduler) swallows and logs; the CLI wants a
    non-zero exit. Neither wants a job that reports success after failing,
    so ``record_success`` is reached only on the way out.
    """
    result = await job.fn(pool)
    jobs.record_success(job.name, result.rows)
    logger.info("auth.maint.completed", extra=result.as_payload())
    return result
