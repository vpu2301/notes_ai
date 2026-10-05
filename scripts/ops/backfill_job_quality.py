#!/usr/bin/env python3
"""Fill ``transcription_jobs.quality`` for jobs that completed before 0067.

    uv run python scripts/ops/backfill_job_quality.py            # dry run: counts only
    uv run python scripts/ops/backfill_job_quality.py --apply    # write the summaries

The admin "Meeting quality" dashboard reads the numbers-only summary the
worker now writes on completion (asr_worker/quality.py). Older jobs have
none; this reads each one's stored transcript through the worker's own read
path (libs/storage + libs/crypto, AAD = job id), computes the same summary
and writes it. Only jobs whose ``quality`` is NULL are touched, so a re-run
is a no-op. It prints counts, never transcript content.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_READER_DSN = "postgresql://funnel_reader:funnel_reader@localhost:5432/notes"


async def run(
    apply: bool, reader_dsn: str, limit: int
) -> int:  # pragma: no cover — needs the stack
    sys.path.insert(0, str(REPO / "services" / "asr-worker" / "src"))
    from asr_models import TranscriptionOutput
    from asr_worker import quality
    from asr_worker.config import settings
    from crypto import Envelope, TenantKekRepository, build_master_key_provider
    from db import create_pool, tenant_connection
    from storage import EncryptedObjectStore, S3Client

    reader = await create_pool(reader_dsn, application_name="quality-backfill")
    try:
        # funnel_reader sees every tenant's job ids (0046/0067); the app role
        # below reads each one inside its own tenant.
        jobs = await reader.fetch(
            """
            SELECT id, tenant_id FROM transcription_jobs
             WHERE status = 'complete' AND quality IS NULL
             ORDER BY finished_at DESC
             LIMIT $1
            """,
            limit,
        )
    finally:
        await reader.close()
    print(f"jobs without a quality summary: {len(jobs)}")
    if not apply or not jobs:
        return 0

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
        settings.db_crypto_writer_dsn, application_name="quality-backfill"
    )
    app_pool = await create_pool(settings.db_app_role_dsn, application_name="quality-backfill")
    written = failed = 0
    try:
        store = EncryptedObjectStore(
            s3=S3Client(
                endpoint_url=settings.s3_endpoint,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                region=settings.s3_region,
                use_ssl=settings.s3_use_ssl,
            ),
            bucket=settings.s3_transcripts_bucket,
            envelope=Envelope(
                master_key_provider=master,
                kek_repository=TenantKekRepository(pool=crypto_pool, master_key_provider=master),
            ),
        )
        for job in jobs:
            job_id, tenant_id = job["id"], job["tenant_id"]
            try:
                async with tenant_connection(app_pool, tenant_id) as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT j.result_storage_uri, a.duration_ms
                          FROM transcription_jobs j
                          LEFT JOIN audio_files a ON a.id = j.audio_id
                         WHERE j.id = $1
                        """,
                        job_id,
                    )
                if row is None or not row["result_storage_uri"]:
                    failed += 1
                    continue
                key = str(row["result_storage_uri"]).split("://", 1)[-1].split("/", 1)[1]
                output = TranscriptionOutput.model_validate_json(
                    await store.get(key=key, tenant_id=tenant_id, aad=job_id.bytes)
                )
                if row["duration_ms"]:
                    audio_seconds = row["duration_ms"] / 1000
                elif output.segments:
                    audio_seconds = output.segments[-1].end_ms / 1000
                else:
                    audio_seconds = 0.0
                summary = quality.summarize(output, audio_seconds=audio_seconds)
                summary["backfilled"] = True
                async with tenant_connection(app_pool, tenant_id) as conn:
                    await conn.execute(
                        "UPDATE transcription_jobs SET quality = $2::jsonb"
                        " WHERE id = $1 AND quality IS NULL",
                        job_id,
                        json.dumps(summary),
                    )
                written += 1
            except Exception as exc:  # noqa: BLE001 — one unreadable job must not stop the rest
                failed += 1
                print(f"job {job_id}: {type(exc).__name__}", file=sys.stderr)
    finally:
        await app_pool.close()
        await crypto_pool.close()
    print(f"written: {written}  skipped or failed: {failed}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--reader-dsn", default=DEFAULT_READER_DSN)
    ap.add_argument("--limit", type=int, default=1000)
    ns = ap.parse_args(argv)
    return asyncio.run(run(ns.apply, ns.reader_dsn, ns.limit))


if __name__ == "__main__":
    raise SystemExit(main())
