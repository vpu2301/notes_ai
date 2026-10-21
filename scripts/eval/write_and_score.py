#!/usr/bin/env python3
"""Sprint P3 — the loop: write the given notes again on the dev stack (N runs each, one at
a time so a rate limit never costs a window), then score every run with
``score_notes.py`` into one table.

    make write-and-score IDS=NOTE-2026-00077,NOTE-2026-00079 RUNS=3 [JUDGE=dev_mac] [HANDSCORE=dir] [REFERENCES=dir] [SAVE=dir]

Reads the API with a dev account (``NOTES_API_EMAIL`` / ``NOTES_API_PASSWORD``, default
member@tenant-a); resolves codes to ids in the notes DB (``--dsn``). Saves each run's
Markdown under ``--save`` (default ``scripts/eval/local/writer-v2/<date>/<code>/run<n>.md``,
outside git). Prints numbers only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score_notes  # noqa: E402
from _common import REPO  # noqa: E402

AUTH = os.environ.get("NOTES_AUTH_URL", "http://localhost:8000")
NOTE = os.environ.get("NOTES_NOTE_URL", "http://localhost:8006")
POLL_S = 5
TIMEOUT_S = 1800


def _call(method: str, url: str, token: str | None = None, body: Any = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, text
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def login() -> str:
    email = os.environ.get("NOTES_API_EMAIL", "member@tenant-a.example")
    password = os.environ.get("NOTES_API_PASSWORD", "dev-password")
    status, body = _call("POST", f"{AUTH}/auth/login", body={"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"login failed: {status}")
    return str(body["access_token"])


async def resolve(dsn: str, ids: list[str]) -> list[tuple[str, str]]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            "SELECT id, code FROM notes WHERE id::text = ANY($1) OR code = ANY($1) ORDER BY code",
            ids,
        )
    finally:
        await conn.close()
    return [(str(r["id"]), str(r["code"])) for r in rows]


def write_once(token: str, note_id: str, template: str | None) -> tuple[str, str, str]:
    """``(generation_id, status, text)`` of one run, or a status that names the refusal."""
    status, body = _call(
        "POST",
        f"{NOTE}/v1/notes/{note_id}/generation",
        token,
        {"template": template} if template else {},
    )
    if status != 202:
        code = body.get("code") if isinstance(body, dict) else body
        return "", f"refused_{status}_{code}", ""
    gen_id = str(body["id"])
    started = time.time()
    view: dict[str, Any] = {}
    while time.time() - started < TIMEOUT_S:
        time.sleep(POLL_S)
        status, view = _call("GET", f"{NOTE}/v1/notes/{note_id}/generation?purpose=review", token)
        if (
            status == 200
            and view.get("id") == gen_id
            and view.get("status") not in ("queued", "running")
        ):
            break
    return gen_id, str(view.get("status") or "timeout"), str(view.get("text") or "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--ids", required=True, help="note codes or uuids, comma-separated")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--template", default=None, help="write every note with this template")
    ap.add_argument("--dsn", default=score_notes.DEFAULT_DSN)
    ap.add_argument("--judge", default=None)
    ap.add_argument("--handscore", type=Path, default=None)
    ap.add_argument("--references", type=Path, default=None)
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    save = args.save or REPO / "scripts" / "eval" / "local" / "writer-v2" / day
    ids = [i for i in args.ids.split(",") if i]
    notes = asyncio.run(resolve(args.dsn, ids))
    if not notes:
        print("no such notes", file=sys.stderr)
        return 3
    token = login()
    generation_ids: list[str] = []
    for note_id, code in notes:
        for run in range(1, args.runs + 1):
            t0 = time.time()
            gen_id, status, text = write_once(token, note_id, args.template)
            seconds = round(time.time() - t0)
            print(f"{code} run{run}: {status} ({seconds}s, {len(text.split())} words)", flush=True)
            if gen_id and status in ("complete", "partial"):
                generation_ids.append(gen_id)
                folder = save / code
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"run{run}.md").write_text(text, "utf-8")
    if not generation_ids:
        return 1
    score_args = [
        "--generation-ids",
        ",".join(generation_ids),
        "--dsn",
        args.dsn,
        "--label",
        args.label,
    ]
    if args.judge:
        score_args += ["--judge", args.judge]
    if args.handscore:
        score_args += ["--handscore", str(args.handscore)]
    if args.references:
        score_args += ["--references", str(args.references)]
    return asyncio.run(score_notes.main(score_args))


if __name__ == "__main__":
    raise SystemExit(main())
