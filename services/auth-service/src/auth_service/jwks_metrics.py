"""Bridge ``JwksCache.metrics`` to OTel observable counters (names match the ``JwksCacheHitRatioLow`` alert)."""

from __future__ import annotations

from collections.abc import Iterable

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Meter, Observation

from auth import JwksCache


def instrument_jwks_cache(cache: JwksCache, *, meter: Meter | None = None) -> None:
    """Register observable counters reporting ``cache.metrics``; the meter is resolved at call time (tests inject one)."""
    m = meter or metrics.get_meter("mdx.auth.jwks")

    def _hits(_: CallbackOptions) -> Iterable[Observation]:
        return (Observation(cache.metrics.cache_hits),)

    def _misses(_: CallbackOptions) -> Iterable[Observation]:
        return (Observation(cache.metrics.cache_misses),)

    def _refresh_attempts(_: CallbackOptions) -> Iterable[Observation]:
        return (Observation(cache.metrics.refresh_attempts),)

    def _refresh_failures(_: CallbackOptions) -> Iterable[Observation]:
        return (Observation(cache.metrics.refresh_failures),)

    def _rate_limited(_: CallbackOptions) -> Iterable[Observation]:
        return (Observation(cache.metrics.rate_limited_refreshes),)

    m.create_observable_counter(
        "mdx_jwks_cache_hits_total",
        callbacks=[_hits],
        description="JWKS cache hits (kid served from a fresh cached document)",
        unit="1",
    )
    m.create_observable_counter(
        "mdx_jwks_cache_misses_total",
        callbacks=[_misses],
        description="JWKS cache misses that triggered an HTTP fetch",
        unit="1",
    )
    m.create_observable_counter(
        "mdx_jwks_refresh_attempts_total",
        callbacks=[_refresh_attempts],
        description="JWKS document refresh attempts (HTTP fetches initiated)",
        unit="1",
    )
    m.create_observable_counter(
        "mdx_jwks_refresh_failures_total",
        callbacks=[_refresh_failures],
        description="JWKS refresh attempts that failed to fetch or parse",
        unit="1",
    )
    m.create_observable_counter(
        "mdx_jwks_rate_limited_refreshes_total",
        callbacks=[_rate_limited],
        description="JWKS refreshes suppressed by the storm-prevention rate limit",
        unit="1",
    )
