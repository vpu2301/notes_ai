"""``AuditVerifier``: replay a tenant's chain (one query per range; the caller chunks long chains) and report the
first divergence as ``gap``, ``prev_hash_mismatch`` or ``payload_hash_mismatch``. Never modifies state.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

import asyncpg

from .canonical import canonicalize
from .writer import GENESIS_PREV_HASH

logger = logging.getLogger(__name__)


class DivergenceReason(StrEnum):
    GAP = "gap"
    PREV_HASH_MISMATCH = "prev_hash_mismatch"
    PAYLOAD_HASH_MISMATCH = "payload_hash_mismatch"


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Outcome of a chain walk: ``last_seq``/``last_hash`` when ok, else the first divergence and its diagnosis."""

    ok: bool
    tenant_id: UUID
    from_seq: int
    to_seq: int | None
    events_checked: int
    last_seq: int | None = None
    last_hash: bytes | None = None
    first_divergence_seq: int | None = None
    divergence_reason: DivergenceReason | None = None
    expected_hash: bytes | None = None
    actual_hash: bytes | None = None


class AuditVerifier:
    """Walk a tenant's audit chain and assert hash continuity (``pool`` needs SELECT on ``audit.events``)."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def verify_chain(
        self,
        tenant_id: UUID,
        *,
        from_seq: int = 1,
        to_seq: int | None = None,
    ) -> VerificationReport:
        if from_seq < 1:
            raise ValueError("from_seq must be ≥ 1")
        if to_seq is not None and to_seq < from_seq:
            raise ValueError("to_seq must be ≥ from_seq")

        async with self._pool.acquire() as conn, conn.transaction(readonly=True):
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))

            if to_seq is None:
                rows = await conn.fetch(
                    """
                        SELECT seq, payload_jcs::text AS payload_jcs,
                               prev_hash, payload_hash
                        FROM audit.events
                        WHERE tenant_id = $1 AND seq >= $2
                        ORDER BY seq
                        """,
                    tenant_id,
                    from_seq,
                )
            else:
                rows = await conn.fetch(
                    """
                        SELECT seq, payload_jcs::text AS payload_jcs,
                               prev_hash, payload_hash
                        FROM audit.events
                        WHERE tenant_id = $1 AND seq BETWEEN $2 AND $3
                        ORDER BY seq
                        """,
                    tenant_id,
                    from_seq,
                    to_seq,
                )

        if not rows:
            return VerificationReport(
                ok=True,
                tenant_id=tenant_id,
                from_seq=from_seq,
                to_seq=to_seq,
                events_checked=0,
            )

        if from_seq == 1:
            running = GENESIS_PREV_HASH
        else:
            running = await self._fetch_prev_hash_seed(tenant_id, from_seq)

        events_checked = 0
        expected_seq = from_seq

        for row in rows:
            seq = int(row["seq"])

            if seq != expected_seq:
                return VerificationReport(
                    ok=False,
                    tenant_id=tenant_id,
                    from_seq=from_seq,
                    to_seq=to_seq,
                    events_checked=events_checked,
                    first_divergence_seq=expected_seq,
                    divergence_reason=DivergenceReason.GAP,
                )

            stored_prev = (
                bytes(row["prev_hash"]) if row["prev_hash"] is not None else GENESIS_PREV_HASH
            )

            if stored_prev != running:
                return VerificationReport(
                    ok=False,
                    tenant_id=tenant_id,
                    from_seq=from_seq,
                    to_seq=to_seq,
                    events_checked=events_checked,
                    first_divergence_seq=seq,
                    divergence_reason=DivergenceReason.PREV_HASH_MISMATCH,
                    expected_hash=running,
                    actual_hash=stored_prev,
                )

            payload_dict: Any = json.loads(row["payload_jcs"])
            jcs_bytes = canonicalize(payload_dict)
            expected_payload_hash = hashlib.sha256(running + jcs_bytes).digest()
            stored_payload_hash = bytes(row["payload_hash"])

            if expected_payload_hash != stored_payload_hash:
                return VerificationReport(
                    ok=False,
                    tenant_id=tenant_id,
                    from_seq=from_seq,
                    to_seq=to_seq,
                    events_checked=events_checked,
                    first_divergence_seq=seq,
                    divergence_reason=DivergenceReason.PAYLOAD_HASH_MISMATCH,
                    expected_hash=expected_payload_hash,
                    actual_hash=stored_payload_hash,
                )

            running = stored_payload_hash
            events_checked += 1
            expected_seq += 1

        return VerificationReport(
            ok=True,
            tenant_id=tenant_id,
            from_seq=from_seq,
            to_seq=to_seq,
            events_checked=events_checked,
            last_seq=expected_seq - 1,
            last_hash=running,
        )

    async def _fetch_prev_hash_seed(self, tenant_id: UUID, from_seq: int) -> bytes:
        """Seed the running hash from the row before ``from_seq`` (in a transaction, since set_config is transaction-local)."""
        async with self._pool.acquire() as conn, conn.transaction(readonly=True):
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
            row = await conn.fetchrow(
                """
                    SELECT payload_hash FROM audit.events
                    WHERE tenant_id = $1 AND seq = $2
                    """,
                tenant_id,
                from_seq - 1,
            )
        if row is None:
            # Missing seed row: treat as genesis so the walker's first comparison surfaces the break.
            return GENESIS_PREV_HASH
        return bytes(row["payload_hash"])
