"""`POST /v1/telemetry/client-events` (telemetry sprint 3): what the user saw, and when.

A batch of client events, each tagged with the recording (the ASR job id the client already
holds) and, if it knows it, the run. The server checks the caller may see the recording, stores
the receive time and a clock offset, ignores duplicates (first report wins) and recomputes the
run's user-visible timings. Content never travels here: events, times, ids and counts only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

import telemetry
from auth import Claims
from db import tenant_connection

from ..deps import get_state, requires

router = APIRouter(prefix="/v1/telemetry", tags=["telemetry"])

MAX_BATCH = 100
ClientName = Literal["web", "macos", "ios"]
EventName = Literal[
    "recording_stopped", "import_submitted", "upload_started", "upload_finished",
    "transcript_displayed", "speaker_labels_displayed", "notes_displayed", "error_shown",
]  # fmt: skip


class ClientEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID | None = None
    processing_run_id: UUID | None = None
    recording_id: UUID
    client: ClientName
    client_version: str = Field(max_length=64)
    event: EventName
    client_wall_utc: datetime
    client_monotonic_ns: int | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class ClientEventBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # When the client sent the batch: the clock offset is measured against it, so a batch
    # retried hours later does not read as hours of clock skew.
    sent_at: datetime | None = None
    events: list[ClientEventIn] = Field(max_length=MAX_BATCH)


class IngestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: int
    duplicates: int
    unresolved: int


async def _may_see(state: Any, claims: Claims, recording_id: UUID) -> bool:
    """The recording is in the caller's workspace (RLS) and the caller submitted it, or is a
    workspace admin."""
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        requester = await conn.fetchval(
            "SELECT requester_sub FROM transcription_jobs WHERE id = $1", recording_id
        )
    if requester is None:
        return False
    return str(requester) == str(claims.sub) or "tenant_admin" in (claims.roles or [])


@router.post("/client-events", response_model=IngestResult, status_code=status.HTTP_202_ACCEPTED)
async def ingest_client_events(
    body: Annotated[list[ClientEventIn] | ClientEventBatch, Body()],
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> IngestResult:
    batch = body if isinstance(body, ClientEventBatch) else ClientEventBatch(events=body)
    if len(batch.events) > MAX_BATCH:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="batch too large")
    state = get_state()
    store = telemetry.get_store()
    received = datetime.now(UTC)
    allowed: dict[UUID, bool] = {}
    accepted = duplicates = unresolved = 0
    touched: set[UUID] = set()
    for e in batch.events:
        if e.recording_id not in allowed:
            allowed[e.recording_id] = await _may_see(state, claims, e.recording_id)
        if not allowed[e.recording_id]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="recording not found")
        run_id = e.processing_run_id
        if run_id is not None and await store.run_recording(claims.tid, run_id) != e.recording_id:
            run_id = None  # a run of another recording: resolve instead of trusting it
        if run_id is None:
            run_id = await store.resolve_run(claims.tid, e.recording_id, e.event)
        if run_id is None:
            unresolved += 1  # no run (telemetry was off when it was processed): nothing to attach
            continue
        offset_ms = int((received - (batch.sent_at or e.client_wall_utc)).total_seconds() * 1000)
        record = telemetry.ClientEvent(
            event_id=e.event_id or uuid4(),
            processing_run_id=run_id,
            recording_id=e.recording_id,
            tenant_id=claims.tid,
            client=e.client,
            client_version=e.client_version,
            event=e.event,
            client_wall_utc=e.client_wall_utc,
            client_monotonic_ns=e.client_monotonic_ns,
            server_received_utc=received,
            estimated_clock_offset_ms=offset_ms,
            attributes=telemetry.redact(e.attributes),
        )
        if await store.add_client_event(record):
            accepted += 1
            touched.add(run_id)
        else:
            duplicates += 1
    for run_id in touched:
        await store.apply_client_timings(claims.tid, run_id)
    return IngestResult(accepted=accepted, duplicates=duplicates, unresolved=unresolved)
