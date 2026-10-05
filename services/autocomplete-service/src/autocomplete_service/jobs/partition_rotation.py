"""Monthly partition rotation for autocomplete_telemetry.

Ensures current + next two months' partitions, then DETACH+DROPs partitions past
90-day retention via a SECURITY DEFINER function (app_role owns no DDL). With
``MDX_TELEMETRY_COLD_ARCHIVE_ENABLED`` rows are archived (gzip JSONL, encrypted
under the global tenant) before the drop; an archive failure blocks the drop.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import asyncpg

from db import create_pool

from .. import repository as repo
from ..config import settings

logger = logging.getLogger(__name__)

MONTHS_AHEAD = 2
RETENTION_DAYS = 90

# Reserved global tenant: envelope identity for cross-tenant archives, audit home for scheduler runs.
GLOBAL_TENANT = UUID("00000000-0000-0000-0000-000000000000")


def _month_start(year: int, month: int) -> datetime:
    while month > 12:
        year, month = year + 1, month - 12
    return datetime(year, month, 1, tzinfo=UTC)


def _partition_bounds(now: datetime) -> list[tuple[datetime, datetime]]:
    """Month boundaries for the current and next ``MONTHS_AHEAD`` months (current included so a restart self-heals)."""
    return [
        (
            _month_start(now.year, now.month + offset),
            _month_start(now.year, now.month + offset + 1),
        )
        for offset in range(MONTHS_AHEAD + 1)
    ]


async def ensure_partitions(app_pool: asyncpg.Pool) -> list[str]:
    now = datetime.now(UTC)
    names: list[str] = []
    async with app_pool.acquire() as conn:
        for start, end in _partition_bounds(now):
            names.append(await repo.create_next_telemetry_partition(conn, start=start, end=end))
    return names


async def _build_archive_store() -> Any:
    """Lazy EncryptedObjectStore for the archive bucket (flag-gated)."""
    from crypto import Envelope, TenantKekRepository, build_master_key_provider
    from storage import EncryptedObjectStore, S3Client

    master = build_master_key_provider(
        provider=settings.master_key_provider,
        file_path=settings.master_key_path,
        vault_addr=settings.vault_addr,
        vault_token=settings.vault_token,
        vault_transit_key=settings.vault_transit_key,
        vault_transit_mount=settings.vault_transit_mount,
    )
    await master.startup_self_check()
    crypto_pool = await create_pool(
        settings.db_crypto_writer_dsn,
        application_name="autocomplete-service/telemetry-archive",
        min_size=1,
        max_size=2,
    )
    kek_repo = TenantKekRepository(pool=crypto_pool, master_key_provider=master)
    envelope = Envelope(master_key_provider=master, kek_repository=kek_repo)
    s3 = S3Client(
        endpoint_url=settings.s3_endpoint,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        region=settings.s3_region,
        use_ssl=settings.s3_use_ssl,
    )
    store = EncryptedObjectStore(
        s3=s3, bucket=settings.s3_telemetry_archive_bucket, envelope=envelope
    )
    return store, s3, crypto_pool


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


async def archive_partition(conn: asyncpg.Connection, store: Any, name: str) -> str:
    """Export one partition as gzip JSONL; returns the object key, raises on failure (caller must not drop)."""
    rows = await conn.fetch(f'SELECT * FROM "{name}"')  # noqa: S608 — relname from pg_class
    lines = "\n".join(
        json.dumps({k: _jsonable(v) for k, v in dict(r).items()}, ensure_ascii=False) for r in rows
    )
    payload = gzip.compress(lines.encode("utf-8"))
    key = f"autocomplete_telemetry/{name}.jsonl.gz"
    await store.put(
        key=key,
        plaintext=payload,
        tenant_id=GLOBAL_TENANT,
        aad=name.encode("ascii"),
    )
    logger.info(
        "partition_rotation.partition_archived",
        extra={"partition": name, "key": key, "rows": len(rows), "bytes": len(payload)},
    )
    return key


async def enforce_retention(app_pool: asyncpg.Pool) -> tuple[list[str], list[str]]:
    """Archive (flag-gated) then DETACH+DROP partitions past retention; returns ``(dropped, archived)``.

    Idempotent: the DB function returns NULL for absent partitions; an archive failure skips that drop until next run.
    """
    today = datetime.now(UTC).date()
    dropped: list[str] = []
    archived: list[str] = []
    store_bundle: Any = None
    try:
        async with app_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_inherits i ON c.oid = i.inhrelid
                WHERE i.inhparent = 'autocomplete_telemetry'::regclass
                """
            )
            for r in rows:
                name: str = r["relname"]
                # autocomplete_telemetry_YYYY_MM → month start
                try:
                    y, m = name.rsplit("_", 2)[-2:]
                    start = date(int(y), int(m), 1)
                except (ValueError, IndexError):
                    continue
                end = _month_start(start.year, start.month + 1).date()
                if (today - end).days <= RETENTION_DAYS:
                    continue

                if settings.telemetry_cold_archive_enabled:
                    try:
                        if store_bundle is None:
                            store_bundle = await _build_archive_store()
                        await archive_partition(conn, store_bundle[0], name)
                        archived.append(name)
                    except Exception:  # noqa: BLE001 — archive failure blocks the drop
                        logger.exception(
                            "partition_rotation.archive_failed_drop_blocked",
                            extra={"partition": name},
                        )
                        continue

                dropped_name = await conn.fetchval(
                    "SELECT autocomplete_drop_telemetry_partition($1)", start
                )
                if dropped_name:
                    dropped.append(dropped_name)
                    logger.warning(
                        "partition_rotation.partition_dropped",
                        extra={
                            "partition": dropped_name,
                            "retention_days": RETENTION_DAYS,
                            "archived": name in archived,
                        },
                    )
    finally:
        if store_bundle is not None:
            await store_bundle[1].aclose()
            await store_bundle[2].close()
    return dropped, archived


async def rotate(app_pool: asyncpg.Pool) -> tuple[list[str], list[str]]:
    ensured = await ensure_partitions(app_pool)
    dropped, _archived = await enforce_retention(app_pool)
    return ensured, dropped


async def run_forever(*, interval_seconds: float = 86400.0) -> None:  # pragma: no cover
    from audit import AuditWriter, Severity

    from .. import audit_kinds

    app_pool = await create_pool(
        settings.db_app_role_dsn,
        application_name="autocomplete-service/partition-rotation",
        min_size=1,
        max_size=2,
    )
    audit_pool = await create_pool(
        settings.db_audit_writer_dsn,
        application_name="autocomplete-service/partition-rotation-audit",
        min_size=1,
        max_size=2,
    )
    audit_writer = AuditWriter(audit_pool)
    try:
        while True:
            try:
                ensured = await ensure_partitions(app_pool)
                dropped, archived = await enforce_retention(app_pool)
                await audit_writer.write_event(
                    tenant_id=GLOBAL_TENANT,
                    kind=audit_kinds.SCHEDULER_JOB_COMPLETED,
                    actor_sub=None,
                    actor_role="scheduler",
                    target_kind="job",
                    target_id="telemetry_partition_rotation",
                    payload={
                        "ensured": ensured,
                        "dropped": dropped,
                        "archived": archived,
                        "cold_archive_enabled": settings.telemetry_cold_archive_enabled,
                    },
                    severity=Severity.INFO,
                )
            except Exception:  # noqa: BLE001
                logger.exception("partition_rotation.iteration_failed")
                try:
                    await audit_writer.write_event(
                        tenant_id=GLOBAL_TENANT,
                        kind=audit_kinds.SCHEDULER_JOB_FAILED,
                        actor_sub=None,
                        actor_role="scheduler",
                        target_kind="job",
                        target_id="telemetry_partition_rotation",
                        payload={},
                        severity=Severity.WARN,
                    )
                except Exception:  # noqa: BLE001 — audit is best-effort here
                    logger.exception("partition_rotation.audit_failed")
            await asyncio.sleep(interval_seconds)
    finally:
        await app_pool.close()
        await audit_pool.close()


def _main() -> None:  # pragma: no cover — manual ops entrypoint
    """Manual run: uv run --project services/autocomplete-service \
    python -m autocomplete_service.jobs.partition_rotation"""

    async def _run() -> None:
        app_pool = await create_pool(
            settings.db_app_role_dsn,
            application_name="autocomplete-rotation-manual",
            min_size=1,
            max_size=2,
        )
        try:
            ensured, dropped = await rotate(app_pool)
            print(f"ensured: {ensured}")
            print(f"dropped: {dropped or '(none)'}")
        finally:
            await app_pool.close()

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    _main()
