"""HTTP client to ``note-service`` — draft creation on conversation
finalize (sprint 14).

The sprint-08 hand-off is explicit: conversation sessions create drafts
through the EXISTING ``POST /v1/notes`` — no parallel write path.
Draft creation is an *action* in note-service's domain, so it goes
over HTTP with the caller's own bearer (the repo's cross-service
pattern), never a shared service identity: note-service enforces
``note.write`` on the actual author.

Failure policy mirrors the NLP client: never fail the finalize — the
transcript is already persisted; a missed draft is a
``conversation.draft.create_failed`` audit row and the user can create
the note from the session later.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NoteClientConfig:
    base_url: str = "http://note-service:8000"
    timeout_seconds: float = 5.0


@dataclass(frozen=True, slots=True)
class DraftResult:
    note_id: str
    code: str
    version_id: str


class NoteClient:
    def __init__(self, *, config: NoteClientConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(
                connect=1.0,
                read=config.timeout_seconds,
                write=1.0,
                pool=1.0,
            ),
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=4),
        )

    async def create_draft(
        self,
        *,
        bearer: str,
        body: dict[str, Any],
    ) -> DraftResult | None:
        """POST /v1/notes with the caller's bearer. None on any failure."""
        try:
            resp = await asyncio.wait_for(
                self._client.post(
                    "/v1/notes",
                    json=body,
                    headers={"Authorization": f"Bearer {bearer}"},
                ),
                timeout=self._config.timeout_seconds + 1.0,
            )
        except (TimeoutError, httpx.HTTPError) as exc:
            logger.warning("note.draft_transport_error", extra={"error_class": type(exc).__name__})
            return None
        if resp.status_code != 201:
            logger.warning(
                "note.draft_non_201",
                extra={"status": resp.status_code, "body": resp.text[:512]},
            )
            return None
        doc = resp.json()
        return DraftResult(
            note_id=str(doc.get("id", "")),
            code=str(doc.get("code", "")),
            version_id=str(doc.get("version_id", "")),
        )

    async def aclose(self) -> None:
        await self._client.aclose()
