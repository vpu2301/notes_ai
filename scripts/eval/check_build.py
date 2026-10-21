"""Task 4 step 1: did the dev worker that wrote the newest generation run this checkout?

Reads ``note_generations.stats->'build'`` of the newest row (numbers and hashes only)
and compares it with the working tree: the commit and the engine's code digest.
Exit 1 when stale or when no generation carries a build stamp yet.

    uv run --project services/note-service --with asyncpg python scripts/eval/check_build.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import git_sha, stale_build  # noqa: E402

DEFAULT_DSN = "postgresql://funnel_reader:funnel_reader@localhost:5432/notes"
QUERY = """
SELECT stats->'build' AS build, created_at
FROM note_generations
WHERE stats IS NOT NULL AND finished_at IS NOT NULL
ORDER BY created_at DESC
LIMIT 1
"""


async def main(dsn: str) -> int:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(QUERY)
    finally:
        await conn.close()
    build = row["build"] if row else None
    if isinstance(build, str):
        build = json.loads(build)
    print(f"HEAD {git_sha(short=False)}")
    print(f"newest generation: {row['created_at'].isoformat() if row else None}")
    print(f"build: {json.dumps(build)}")
    if not build:
        print("STALE: the newest generation carries no stats.build (pre-Task-4 image)")
        return 1
    reason = stale_build(build)
    if reason:
        print(f"STALE: {reason}")
        return 1
    if str(build.get("git_sha") or "unknown") == "unknown":
        print("OK by code digest; git_sha unknown — the image was built outside `make dev-up`")
        return 0
    print("OK: the dev worker runs this checkout")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    sys.exit(asyncio.run(main(ap.parse_args().dsn)))
