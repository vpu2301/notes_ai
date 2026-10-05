"""Async JWKS cache with TTL, refresh-on-miss (synchronous, per-issuer lock) and a miss rate-limit against fetch storms."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .exceptions import JwksFetchError, KidNotFoundError


@dataclass(slots=True)
class _IssuerState:
    """One issuer's JWKS snapshot. ``last_miss_refresh_at`` is bumped only by a refresh that still missed the kid,
    so a legitimate rotation gets one refresh and later misses within the rate limit make no HTTP call."""

    jwks: dict[str, Any]
    fetched_at: float
    last_miss_refresh_at: float = 0.0


@dataclass(slots=True)
class JwksMetrics:
    """Counters exposed for observability."""

    cache_hits: int = 0
    cache_misses: int = 0
    refresh_attempts: int = 0
    refresh_failures: int = 0
    rate_limited_refreshes: int = 0


class JwksCache:
    """Async JWKS document cache keyed by issuer; unknown issuers are rejected before any HTTP call."""

    def __init__(
        self,
        *,
        issuer_to_url: Mapping[str, str],
        ttl_seconds: int = 300,
        refresh_rate_limit_seconds: int = 5,
        http_client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not issuer_to_url:
            raise ValueError("issuer_to_url must have at least one entry")
        self._issuer_to_url: dict[str, str] = dict(issuer_to_url)
        self._ttl = ttl_seconds
        self._rate_limit = refresh_rate_limit_seconds
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=5.0)
        self._clock = clock or time.monotonic
        self._state: dict[str, _IssuerState] = {}
        self._locks: dict[str, asyncio.Lock] = {iss: asyncio.Lock() for iss in self._issuer_to_url}
        self.metrics = JwksMetrics()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_key(self, issuer: str, kid: str) -> dict[str, Any]:
        """Return the JWK for ``kid``, refreshing if needed; KidNotFoundError / JwksFetchError otherwise."""
        if issuer not in self._issuer_to_url:
            raise KidNotFoundError(f"unknown issuer: {issuer!r}")

        state = self._state.get(issuer)
        now = self._clock()
        if state is not None and (now - state.fetched_at) <= self._ttl:
            key = _find_key(state.jwks, kid)
            if key is not None:
                self.metrics.cache_hits += 1
                return key

        async with self._locks[issuer]:
            state = self._state.get(issuer)
            now = self._clock()
            fresh = state is not None and (now - state.fetched_at) <= self._ttl

            if fresh:
                assert state is not None
                key = _find_key(state.jwks, kid)
                if key is not None:
                    self.metrics.cache_hits += 1
                    return key

                # Fresh cache, kid missing: rate-limit so a random kid cannot induce a fetch storm.
                if (now - state.last_miss_refresh_at) < self._rate_limit:
                    self.metrics.rate_limited_refreshes += 1
                    raise KidNotFoundError(
                        f"kid {kid!r} not in JWKS for issuer {issuer!r}; "
                        f"refresh suppressed by rate limit"
                    )
            self.metrics.cache_misses += 1
            self.metrics.refresh_attempts += 1
            url = self._issuer_to_url[issuer]
            attempt_at = self._clock()
            try:
                resp = await self._client.get(url)
                resp.raise_for_status()
                jwks_doc = resp.json()
            except Exception as exc:
                self.metrics.refresh_failures += 1
                raise JwksFetchError(f"failed to fetch JWKS from {url}: {exc}") from exc

            # Keep the previous miss timestamp so a TTL refresh doesn't unblock rate-limited misses.
            new_state = _IssuerState(jwks=jwks_doc, fetched_at=attempt_at)
            if state is not None:
                new_state.last_miss_refresh_at = state.last_miss_refresh_at

            key = _find_key(jwks_doc, kid)
            if key is None:
                new_state.last_miss_refresh_at = attempt_at
                self._state[issuer] = new_state
                raise KidNotFoundError(
                    f"kid {kid!r} not in JWKS for issuer {issuer!r} after refresh"
                )

            self._state[issuer] = new_state
            return key


def _find_key(jwks: Mapping[str, Any], kid: str) -> dict[str, Any] | None:
    keys = jwks.get("keys", [])
    if not isinstance(keys, list):
        return None
    for k in keys:
        if isinstance(k, dict) and k.get("kid") == kid:
            return k
    return None
