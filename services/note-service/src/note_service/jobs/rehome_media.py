"""``note.rehome_media``: re-encrypt a moved note's audio and transcripts into the
workspace it moved to (W5). Queued under the TARGET workspace by `routers/notes_move.py`.

Per object: read under the old tenant → write under the new key and tenant → verify →
point the row at it → delete the old one. Every step is safe to repeat: an object
already at its new key is not written again, an old key that is gone with the new one
present is done. At no point are there zero copies. When the last object is home the
note's ``media_state`` turns ``ready`` and the transcript opens; a dead job marks it
``failed`` and leaves whatever copies exist where they are.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from audit import Severity
from db import tenant_connection

from .. import audit_kinds
from ..collaboration_metrics import rehome_bytes, rehome_seconds, rehome_total

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Item:
    """One object to re-home, and the row column that names it (None: derived key)."""

    store: str  # "audio" | "transcripts"
    old_key: str
    aad: bytes
    table: str | None = None
    column: str | None = None
    row_id: UUID | None = None


def key_from_uri(uri: str) -> str:
    """``minio://bucket/<key>`` → ``<key>`` (asr-service's rule)."""
    return uri.split("://", 1)[-1].split("/", 1)[1]


def _uri_for(uri: str, new_key: str) -> str:
    scheme_bucket = uri[: len(uri) - len(key_from_uri(uri))]
    return f"{scheme_bucket}{new_key}"


def new_key_for(old_key: str, *, from_tenant: UUID, to_tenant: UUID) -> str | None:
    """The same name under the new tenant's segment; None when the key is not under the old one."""
    parts = old_key.split("/")
    for i, part in enumerate(parts):
        if part == str(from_tenant):
            parts[i] = str(to_tenant)
            return "/".join(parts)
    return None


async def plan(conn: Any, *, from_tenant: UUID, payload: dict[str, Any]) -> list[Item]:
    """Every object of the moved note, read from the rows (already in the target workspace).
    Revisions first and the current transcript last, so its URI flips when the rest is home."""
    items: list[Item] = []
    job_id = UUID(payload["job_id"]) if payload.get("job_id") else None
    session_id = UUID(payload["session_id"]) if payload.get("session_id") else None
    job_audio: UUID | None = None
    if job_id is not None:
        job = await conn.fetchrow(
            "SELECT audio_id, diarization_rev, result_storage_uri, previous_result_storage_uri"
            " FROM transcription_jobs WHERE id = $1",
            job_id,
        )
        if job is not None:
            job_audio = job["audio_id"]
            # Re-runs have no column of their own; asr derives them from the tenant (job_erasure).
            for n in range(2, max(1, int(job["diarization_rev"] or 1)) + 2):
                items.append(
                    Item("transcripts", f"{from_tenant}/{job_id}.r{n}.json.enc", job_id.bytes)
                )
            if job["previous_result_storage_uri"]:
                items.append(
                    Item(
                        "transcripts",
                        key_from_uri(job["previous_result_storage_uri"]),
                        job_id.bytes,
                        "transcription_jobs",
                        "previous_result_storage_uri",
                        job_id,
                    )
                )
    for raw in payload.get("audio_ids") or []:
        audio_id = UUID(raw)
        uri = await conn.fetchval("SELECT storage_uri FROM audio_files WHERE id = $1", audio_id)
        if not uri:
            continue
        # A recording's audio is sealed with its id; a dictation's with its session id.
        aad = audio_id.bytes if audio_id == job_audio or session_id is None else session_id.bytes
        items.append(Item("audio", key_from_uri(uri), aad, "audio_files", "storage_uri", audio_id))
    if job_id is not None:
        uri = await conn.fetchval(
            "SELECT result_storage_uri FROM transcription_jobs WHERE id = $1", job_id
        )
        if uri:
            items.append(
                Item(
                    "transcripts",
                    key_from_uri(uri),
                    job_id.bytes,
                    "transcription_jobs",
                    "result_storage_uri",
                    job_id,
                )
            )
    return items


_UPDATABLE = {
    ("audio_files", "storage_uri"),
    ("transcription_jobs", "result_storage_uri"),
    ("transcription_jobs", "previous_result_storage_uri"),
}


async def _point_row_at(conn: Any, item: Item, new_key: str) -> None:
    if item.table is None or item.column is None:
        return
    assert (item.table, item.column) in _UPDATABLE  # noqa: S101 — fixed vocabulary, never input
    uri = await conn.fetchval(
        f"SELECT {item.column} FROM {item.table} WHERE id = $1",  # noqa: S608
        item.row_id,
    )
    if uri and key_from_uri(uri) != new_key:
        await conn.execute(
            f"UPDATE {item.table} SET {item.column} = $2 WHERE id = $1",  # noqa: S608
            item.row_id,
            _uri_for(uri, new_key),
        )


async def rehome_one(
    *,
    store: Any,
    item: Item,
    from_tenant: UUID,
    to_tenant: UUID,
    point_row_at: Any,
) -> int:
    """Move one object; returns plaintext bytes written (0 when nothing had to be written)."""
    new_key = new_key_for(item.old_key, from_tenant=from_tenant, to_tenant=to_tenant)
    if new_key is None:
        return 0  # already named under the new workspace (a re-run after the row moved)
    written = 0
    old_exists = await store.exists(key=item.old_key)
    if old_exists and not await store.exists(key=new_key):
        plaintext = await store.get(key=item.old_key, tenant_id=from_tenant, aad=item.aad)
        await store.put(key=new_key, plaintext=plaintext, tenant_id=to_tenant, aad=item.aad)
        written = len(plaintext)
    if not await store.exists(key=new_key):
        if old_exists:
            raise RuntimeError("re-homed object did not verify")
        return 0  # never existed (a revision that was not made)
    await point_row_at(item, new_key)
    if old_exists:
        await store.delete(key=item.old_key)
    return written


async def handle_rehome(
    *,
    app_pool: Any,
    stores: dict[str, Any],
    audit_writer: Any,
    tenant_id: UUID,
    payload: dict[str, Any],
    enqueued_at: Any = None,
) -> dict[str, Any]:
    """One re-home, start to finish. Returns counts only."""
    started = time.monotonic()
    note_id = UUID(str(payload["note_id"]))
    from_tenant = UUID(str(payload["from_tenant_id"]))
    async with tenant_connection(app_pool, tenant_id) as conn:
        if await conn.fetchval("SELECT tenant_id FROM notes WHERE id = $1", note_id) is None:
            # Moved on again (or gone) before this ran; the newer move owns the media.
            return {"skipped": "note_not_here"}
        items = await plan(conn, from_tenant=from_tenant, payload=payload)

    total = 0
    for item in items:

        async def _point(it: Item, new_key: str) -> None:
            async with tenant_connection(app_pool, tenant_id) as c:
                await _point_row_at(c, it, new_key)

        total += await rehome_one(
            store=stores[item.store],
            item=item,
            from_tenant=from_tenant,
            to_tenant=tenant_id,
            point_row_at=_point,
        )

    async with tenant_connection(app_pool, tenant_id) as conn:
        await conn.execute(
            "UPDATE notes SET media_state = 'ready' WHERE id = $1 AND media_state <> 'ready'",
            note_id,
        )
    await audit_writer.write_event(
        tenant_id=tenant_id,
        kind=audit_kinds.NOTE_MEDIA_REHOMED,
        actor_sub=None,
        actor_role=None,
        target_kind="note",
        target_id=note_id,
        payload={"keys": len(items), "bytes": total},
        severity=Severity.INFO,
    )
    rehome_total.add(1, {"result": "done"})
    rehome_bytes.record(total)
    if enqueued_at is not None:
        rehome_seconds.record((datetime.now(UTC) - enqueued_at).total_seconds())
    logger.info(
        "note.rehome_done",
        extra={"note_id": str(note_id), "keys": len(items), "seconds": time.monotonic() - started},
    )
    return {"keys": len(items), "bytes": total}


async def mark_failed(
    *, app_pool: Any, audit_writer: Any, tenant_id: UUID, payload: dict[str, Any], error_kind: str
) -> None:
    """Dead: the note stays moved and readable; its transcript says it could not be moved."""
    note_id = UUID(str(payload["note_id"]))
    async with tenant_connection(app_pool, tenant_id) as conn:
        await conn.execute(
            "UPDATE notes SET media_state = 'failed' WHERE id = $1 AND media_state = 'rehoming'",
            note_id,
        )
    rehome_total.add(1, {"result": "dead"})
    await audit_writer.write_event(
        tenant_id=tenant_id,
        kind=audit_kinds.NOTE_MEDIA_REHOME_FAILED,
        actor_sub=None,
        actor_role=None,
        target_kind="note",
        target_id=note_id,
        payload={"error_kind": error_kind},
        severity=Severity.WARN,
    )
