"""HTTP client to ``nlp-service`` for batch enrichment."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NlpBatchClientConfig:
    base_url: str = "http://nlp-service:8000"
    timeout_seconds: float = 10.0


class NlpBatchClient:
    def __init__(
        self,
        *,
        config: NlpBatchClientConfig,
        service_token: str | None = None,
    ) -> None:
        self._config = config
        headers = {"Authorization": f"Bearer {service_token}"} if service_token else {}
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(
                connect=1.0,
                read=config.timeout_seconds,
                write=1.0,
                pool=1.0,
            ),
            headers=headers,
        )

    async def process_segments(
        self,
        *,
        tenant_id: UUID,
        segments: list[dict[str, Any]],
        language: str,
        specialty: str | None = None,
        reference_date: date | None = None,
        authorization: str | None = None,
        stages_disabled: list[str] | None = None,
        conversation: bool = False,
    ) -> dict[str, Any] | None:
        # Forward the end-user's bearer: nlp-service tenant-scopes the call itself.
        headers = {"Authorization": authorization} if authorization else None
        body: dict[str, Any] = {
            "segments": segments,
            "language": language,
            "specialty": specialty,
            "reference_date": (reference_date.isoformat() if reference_date else None),
        }
        if stages_disabled:
            body["stages_disabled"] = sorted(set(stages_disabled))
        if conversation:
            # Fillers and repeats hidden from the displayed text.
            body["conversation"] = True
        try:
            resp = await self._client.post("/nlp/process/batch", json=body, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning(
                "nlp_batch.transport_error",
                extra={"error_class": type(exc).__name__, "error": str(exc)},
            )
            return None
        if resp.status_code != 200:
            logger.warning(
                "nlp_batch.non_200",
                extra={"status": resp.status_code, "body": resp.text[:200]},
            )
            return None
        return resp.json()  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        await self._client.aclose()
