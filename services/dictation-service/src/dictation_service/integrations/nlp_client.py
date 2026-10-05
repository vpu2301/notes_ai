"""HTTP client to ``nlp-service``: one batch call at finalize; a timeout degrades to the raw transcript."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NlpClientConfig:
    base_url: str = "http://nlp-service:8000"
    timeout_seconds: float = 0.2


class NlpClient:
    """Async HTTP client with a small connection pool."""

    def __init__(
        self,
        *,
        config: NlpClientConfig,
        service_token: str | None = None,
    ) -> None:
        self._config = config
        self._service_token = service_token
        headers = {"Authorization": f"Bearer {service_token}"} if service_token else {}
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(connect=0.2, read=config.timeout_seconds, write=0.2, pool=0.2),
            headers=headers,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        )

    async def process_segments_batch(
        self,
        *,
        segments: list[dict[str, Any]],
        language: str,
        specialty: str | None = None,
        stages_disabled: list[str] | None = None,
        bearer: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """One batch call over committed segments (``BatchSegmentIn`` shape); None on any failure."""
        body: dict[str, Any] = {
            "segments": segments,
            "language": language,
            "specialty": specialty,
        }
        if stages_disabled:
            body["stages_disabled"] = sorted(stages_disabled)
        headers = {"Authorization": f"Bearer {bearer}"} if bearer else None
        effective_timeout = timeout if timeout is not None else self._config.timeout_seconds
        try:
            resp = await asyncio.wait_for(
                self._client.post("/nlp/process/batch", json=body, headers=headers),
                timeout=effective_timeout,
            )
        except (TimeoutError, httpx.TimeoutException):
            logger.info("nlp.batch_timeout", extra={"timeout_s": effective_timeout})
            return None
        except httpx.HTTPError as exc:
            logger.warning("nlp.batch_transport_error", extra={"error_class": type(exc).__name__})
            return None
        if resp.status_code != 200:
            logger.warning("nlp.batch_non_200", extra={"status": resp.status_code})
            return None
        return dict(resp.json())

    async def aclose(self) -> None:
        await self._client.aclose()
