"""`GET /v1/admin/sharing/stats` — the workspace's loop, in counts (Sprint 22).

For whoever runs the workspace (`stats.read` on the tenant): how many
recipient links were made, sent, opened, acted on, how many recipients
clicked through or opted out, and who sends the most. Counts and the
senders' display names — no recipient address ever leaves this route.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from audit import Severity
from auth import Claims
from db import tenant_connection

from .. import audit_kinds
from ..deps import get_state, requires
from ..domain import notes_repository as repo
from ..domain import sharing_policy

router = APIRouter(prefix="/v1/admin/sharing", tags=["admin"])


class TopSender(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    links: int


class SharingStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: Literal[30, 90]
    links_created: int
    links_sent: int
    links_opened: int
    links_responded: int
    cta_clicks: int
    item_responses: int
    disputes: int
    opted_out: int
    dispute_rate: float
    top_senders: list[TopSender]


@router.get("/stats", response_model=SharingStats)
async def sharing_stats(
    claims: Annotated[Claims, Depends(requires("stats.read", "tenant"))],
    days: int = Query(default=30),
) -> SharingStats:
    if days not in (30, 90):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="days must be 30 or 90")
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        raw = await repo.sharing_stats(conn, days=days)
        senders = raw.pop("top_senders")
        members = await repo.fetch_members(conn, subs=[sub for sub, _ in senders])
    names = {m.sub: m.display_name for m in members}
    responses = int(raw["item_responses"])
    return SharingStats(
        days=days,  # type: ignore[arg-type]
        dispute_rate=(int(raw["disputes"]) / responses) if responses else 0.0,
        top_senders=[
            TopSender(display_name=names.get(sub, "A colleague"), links=n) for sub, n in senders
        ],
        **{k: int(v) for k, v in raw.items()},  # type: ignore[arg-type]
    )


# ── Sprint 23: the workspace's sharing policy ────────────────────────


class RevokeAllResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: int


async def _audit(
    claims: Claims, kind: str, payload: dict[str, object], target_id: UUID | None = None
) -> None:
    await get_state().audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note" if target_id else "tenant",
        target_id=target_id or claims.tid,
        payload=payload,
        severity=Severity.SEC,
    )


@router.get("/policy", response_model=sharing_policy.SharingPolicy)
async def get_policy(
    claims: Annotated[Claims, Depends(requires("stats.read", "tenant"))],
) -> sharing_policy.SharingPolicy:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        policy, _plan = await sharing_policy.load_policy(conn, tenant_id=claims.tid)
    return policy


@router.put("/policy", response_model=sharing_policy.SharingPolicy)
async def put_policy(
    body: sharing_policy.SharingPolicy,
    claims: Annotated[Claims, Depends(requires("tenant.update", "tenant"))],
) -> sharing_policy.SharingPolicy:
    """The whole policy, every time (the form sends what it shows). An
    admin switching product mail back on clears the abuse guard's mark;
    a free workspace may store `cta_enabled=false` but the page ignores
    it (G-1)."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        before, _plan = await sharing_policy.load_policy(conn, tenant_id=claims.tid)
        after = body.model_copy(
            update={
                "auto_disabled_reason": (
                    None if body.product_email_enabled else before.auto_disabled_reason
                )
            }
        )
        keys = sharing_policy.changed_keys(before, after)
        if keys:
            await sharing_policy.save_policy(conn, tenant_id=claims.tid, policy=after)
    if keys:
        await _audit(claims, audit_kinds.TENANT_SHARING_POLICY_CHANGED, {"changed_keys": keys})
    return after


@router.post("/revoke-all", response_model=RevokeAllResult)
async def revoke_all_external(
    claims: Annotated[Claims, Depends(requires("tenant.update", "tenant"))],
) -> RevokeAllResult:
    """Tightening the policy revokes nothing by itself; this is the
    explicit "and the links that already exist" — every live link in the
    workspace, public and recipient, audited per note."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note_ids = await repo.revoke_all_external_links(conn, actor_sub=claims.sub)
    for note_id in note_ids:
        await _audit(
            claims, audit_kinds.NOTE_LINK_REVOKED, {"revoked": "all", "reason": "policy"}, note_id
        )
    return RevokeAllResult(notes=len(note_ids))
