"""Erase one ASR job: transcript, every re-labelled revision, audio, rows. Dry run
unless --apply; every statement filters by the given tenant; refuses a running job;
prints counts only.

    DB_ERASE_DSN=... S3_ENDPOINT=... uv run --project services/asr-service python scripts/ops/erase_asr_job.py --tenant-id <uuid> --job-id <uuid> [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from uuid import UUID

from asr_service.domain import job_erasure
from storage import EncryptedObjectStore, S3Client

REQUIRED = ("DB_ERASE_DSN", "S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY")


async def main(tenant_id: UUID, job_id: UUID, apply: bool) -> int:
    import asyncpg

    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        print(f"missing environment: {', '.join(missing)}", file=sys.stderr)
        return 2
    s3 = S3Client(
        endpoint_url=os.environ["S3_ENDPOINT"],
        access_key=os.environ["S3_ACCESS_KEY"],
        secret_key=os.environ["S3_SECRET_KEY"],
        region=os.environ.get("S3_REGION", "us-east-1"),
        use_ssl=os.environ.get("S3_USE_SSL", "false").lower() == "true",
    )
    transcripts = EncryptedObjectStore(
        s3=s3,
        bucket=os.environ.get("S3_TRANSCRIPTS_BUCKET", "mdx-transcripts"),
        envelope=None,  # type: ignore[arg-type]  # delete/exists never decrypt
    )
    audio = EncryptedObjectStore(
        s3=s3,
        bucket=os.environ.get("S3_AUDIO_BUCKET", "mdx-audio"),
        envelope=None,  # type: ignore[arg-type]
    )
    conn = await asyncpg.connect(os.environ["DB_ERASE_DSN"])
    try:
        async with conn.transaction():
            try:
                plan = await job_erasure.plan(conn, tenant_id=tenant_id, job_id=job_id)
            except job_erasure.ErasureError as exc:
                print(str(exc), file=sys.stderr)
                return 3
            if plan is None:
                print("job not found in this tenant", file=sys.stderr)
                return 1
            print(f"transcript objects: {len(plan.transcript_keys)}; audio objects: 1")
            if not apply:
                print("dry run — pass --apply to erase")
                return 0
            try:
                counts = await job_erasure.erase(
                    conn, transcripts=transcripts, audio=audio, erase_plan=plan
                )
            except job_erasure.ErasureError as exc:
                print(str(exc), file=sys.stderr)
                return 3
        print(" ".join(f"{k}={v}" for k, v in counts.items()))
        return 0
    finally:
        await conn.close()
        await s3.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--job-id", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.tenant_id, args.job_id, args.apply)))
