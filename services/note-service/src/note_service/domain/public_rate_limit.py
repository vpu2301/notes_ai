"""Abuse caps on the anonymous ``/v1/shared/*`` surface (Sprint 19).

Three fixed windows on ``libs/ratelimit``, each stopping a different thing:

* **per IP, per minute** — one host sweeping tokens, or scraping pages.
* **per link, per hour** — one leaked link being hammered from many hosts;
  the sender's revoke is the real fix, this keeps the box up meanwhile.
* **per IP on the CTA, per hour** — the redirect writes a row and an audit
  event; a loop of clicks must not become a loop of writes.

Fail-OPEN, like ``ClipRateLimiter``: the shared page is the product's
front door for people who have no account, and a Redis outage must not
turn every client-facing link into a 429. The degraded case is logged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

from ratelimit import FixedWindowLimiter, client_ip, parse_cidrs

from ..share_metrics import rate_limited

if TYPE_CHECKING:  # pragma: no cover
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class PublicRateLimiter:
    def __init__(
        self,
        redis: Redis,
        *,
        ip_per_minute: int,
        link_per_hour: int,
        cta_per_hour: int,
        trusted_proxy_cidrs: str = "",
        write_per_hour: int = 60,
    ) -> None:
        self._limiter = FixedWindowLimiter(redis, prefix="note:shared-rl")
        self._ip_per_minute = ip_per_minute
        self._link_per_hour = link_per_hour
        self._cta_per_hour = cta_per_hour
        self._write_per_hour = write_per_hour
        self._trusted = parse_cidrs(trusted_proxy_cidrs)

    def ip_of(self, request: Request) -> str:
        return client_ip(
            peer=request.client.host if request.client else None,
            forwarded_for=request.headers.get("x-forwarded-for"),
            trusted_proxies=self._trusted,
        )

    async def _check(self, scope: str, subject: str, *, limit: int, window: int) -> None:
        decision = await self._limiter.allow(
            scope, subject, limit=limit, window_seconds=window, fail_open=True
        )
        if decision.degraded:
            logger.warning("note.shared_rate_limit_degraded", extra={"scope": scope})
            return
        if not decision.allowed:
            rate_limited.add(1, {"scope": scope})
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "type": "urn:mdx:note:rate_limit:shared",
                    "code": "rate_limited",
                    "detail": "too many requests; try again shortly",
                    "scope": scope,
                    "limit": limit,
                },
                headers={"Retry-After": str(decision.retry_after)},
            )

    async def check_ip(self, request: Request) -> None:
        await self._check("ip", self.ip_of(request), limit=self._ip_per_minute, window=60)

    async def check_link(self, link_id: object) -> None:
        await self._check("link", str(link_id), limit=self._link_per_hour, window=3600)

    async def check_cta(self, request: Request) -> None:
        await self._check("cta", self.ip_of(request), limit=self._cta_per_hour, window=3600)

    async def check_write(self, link_id: object) -> None:
        """Sprint 20: responses and flags, per link per hour."""
        await self._check("write", str(link_id), limit=self._write_per_hour, window=3600)

    async def check_otp(self, link_id: object) -> None:
        """Sprint 23: verification codes, 3 per link per hour."""
        await self._check("otp", str(link_id), limit=3, window=3600)

    async def check_report(self, request: Request) -> None:
        """Sprint 23: abuse reports, 3 per IP per day."""
        await self._check("report", self.ip_of(request), limit=3, window=86_400)
