"""``python -m auth_service.maintenance <job>`` — the cron twin (IDX-B3 D).

    python -m auth_service.maintenance --list
    python -m auth_service.maintenance purge-challenges
    python -m auth_service.maintenance expire-sessions --dsn postgresql://…

Also installed as ``mdx-auth-maint``. Runs the same :func:`run_job` the
scheduler does, so a job run by hand emits the same metrics and does the
same work — the failure mode this avoids is a manual path that quietly
diverges until nobody trusts it.

Exit codes: 0 success, 1 the job raised, 2 unknown job. The non-zero exit
is the point of the CLI twin — a cron that cannot fail is a cron nobody
notices has stopped.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import BY_NAME, JOBS, run_job


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mdx-auth-maint", description=__doc__)
    parser.add_argument("job", nargs="?", help="job name (see --list)")
    parser.add_argument("--list", action="store_true", help="list jobs and exit")
    parser.add_argument(
        "--dsn",
        default=None,
        help="tenant_writer DSN; defaults to the service's DB_TENANT_WRITER_DSN",
    )
    return parser


async def _run(name: str, dsn: str | None) -> int:
    from db import create_pool

    from ..config import settings

    job = BY_NAME.get(name)
    if job is None:
        print(f"unknown job {name!r}; try --list", file=sys.stderr)
        return 2

    # min_size=1/max_size=2: a maintenance run is one connection's worth
    # of work, and a cron that opens the service's full pool on a busy
    # database is a self-inflicted incident.
    pool = await create_pool(
        dsn or settings.db_tenant_writer_dsn,
        application_name=f"{settings.service_name}/maint",
        min_size=1,
        max_size=2,
    )
    try:
        result = await run_job(job, pool)
    except Exception as exc:  # noqa: BLE001 — the exit code is the report
        print(f"{name}: FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        await pool.close()

    print(f"{name}: ok  rows={result.rows}")
    for key, value in (result.detail or {}).items():
        print(f"  {key}: {value}")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = _build_parser().parse_args()

    if args.list or not args.job:
        width = max(len(j.name) for j in JOBS)
        print("jobs:")
        for job in JOBS:
            when = (
                f"every {job.interval_seconds // 60} min"
                if job.scheduled and job.interval_seconds and job.interval_seconds < 3600
                else f"every {job.interval_seconds // 3600} h"
                if job.scheduled and job.interval_seconds
                else "manual"
            )
            print(f"  {job.name:<{width}}  {when:<12}  {job.summary}")
        return 0 if args.list else 2

    return asyncio.run(_run(args.job, args.dsn))


if __name__ == "__main__":
    sys.exit(main())
