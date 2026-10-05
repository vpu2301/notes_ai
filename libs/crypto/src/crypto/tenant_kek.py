"""Per-tenant KEK repository: one ``tenant_keks`` row per tenant, wrapped under the master, written only by the
``crypto_writer`` role (``app_role`` can only SELECT its own tenant's row). Plaintext is cached for a short TTL.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from uuid import UUID

import asyncpg

from .master import MASTER_KEY_SIZE_BYTES, MasterKeyProvider

logger = logging.getLogger(__name__)

# Short on purpose: absorbs burst load, not a key store. 60 s is the maximum.
_CACHE_TTL_SECONDS: float = 60.0


@dataclass(slots=True)
class _CachedKek:
    plaintext: bytes
    master_key_id: str
    cached_at: float


class TenantKekRepository:
    """Per-tenant KEK fetch / create with bounded plaintext caching (``crypto_writer`` pool)."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        master_key_provider: MasterKeyProvider,
        cache_ttl_seconds: float = _CACHE_TTL_SECONDS,
    ) -> None:
        self._pool = pool
        self._master = master_key_provider
        self._cache: dict[UUID, _CachedKek] = {}
        self._lock = asyncio.Lock()
        self._cache_ttl = cache_ttl_seconds

    def master_key_id_for(self, tenant_id: UUID) -> str:
        """The master_key_id the tenant's KEK is wrapped under; cache only, so ``get_or_create`` must run first."""
        entry = self._cache.get(tenant_id)
        if entry is None:
            raise KeyError(
                f"master_key_id requested for {tenant_id} before "
                "get_or_create was called; refusing to invent a value."
            )
        return entry.master_key_id

    def evict(self, tenant_id: UUID) -> None:
        """Drop the cached plaintext KEK (rotation, or to force a re-fetch)."""
        cached = self._cache.pop(tenant_id, None)
        if cached is not None:
            # Best-effort zero.
            cached.plaintext = b"\x00" * MASTER_KEY_SIZE_BYTES

    async def get_or_create(self, tenant_id: UUID) -> bytes:
        """The plaintext tenant KEK, created on first use; ephemeral — never log or persist, zero copies promptly."""
        cached = self._cache.get(tenant_id)
        now = time.monotonic()
        if cached is not None and now - cached.cached_at < self._cache_ttl:
            return cached.plaintext

        # Process-wide lock on miss; cross-process contention is handled by INSERT ... ON CONFLICT.
        async with self._lock:
            cached = self._cache.get(tenant_id)
            if cached is not None and now - cached.cached_at < self._cache_ttl:
                return cached.plaintext

            row = await self._fetch_or_insert(tenant_id)
            plaintext = await self._master.unwrap(row["kek_master_id"], bytes(row["wrapped_kek"]))
            if len(plaintext) != MASTER_KEY_SIZE_BYTES:
                raise RuntimeError(
                    f"tenant KEK is {len(plaintext)} bytes; expected "
                    f"{MASTER_KEY_SIZE_BYTES}. The wrapped row is corrupt."
                )
            self._cache[tenant_id] = _CachedKek(
                plaintext=plaintext,
                master_key_id=row["kek_master_id"],
                cached_at=time.monotonic(),
            )
            return plaintext

    async def _fetch_or_insert(self, tenant_id: UUID) -> asyncpg.Record:
        """Read the wrapped KEK row, INSERTing one on first use (ON CONFLICT DO NOTHING across processes)."""
        # Cross-tenant fetch is allowed only because crypto_writer is granted exactly that surface.
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT wrapped_kek, kek_master_id FROM tenant_keks WHERE tenant_id = $1",
                tenant_id,
            )
            if row is not None:
                return row

            plaintext_kek = os.urandom(MASTER_KEY_SIZE_BYTES)
            try:
                master_key_id, wrapped = await self._master.wrap(plaintext_kek)
            finally:
                plaintext_kek = b"\x00" * MASTER_KEY_SIZE_BYTES  # noqa: F841

            await conn.execute(
                """
                INSERT INTO tenant_keks (tenant_id, wrapped_kek, kek_master_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (tenant_id) DO NOTHING
                """,
                tenant_id,
                wrapped,
                master_key_id,
            )
            row = await conn.fetchrow(
                "SELECT wrapped_kek, kek_master_id FROM tenant_keks WHERE tenant_id = $1",
                tenant_id,
            )
            if row is None:  # pragma: no cover  — defensive
                raise RuntimeError(
                    f"tenant KEK row missing for {tenant_id} immediately "
                    "after INSERT — Postgres role lacks SELECT privilege?"
                )
            logger.info(
                "tenant_kek.created",
                extra={"tenant_id": str(tenant_id), "master_key_id": master_key_id},
            )
            return row
