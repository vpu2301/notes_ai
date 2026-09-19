"""`POST /auth/leads` — the shared page's fake door (Sprint 19).

A recipient of a shared note clicked "Create your own workspace free",
landed on `/join?ref=<code>` and left an address. No account is created
this sprint: the row IS the result, and the rate at which rows appear
per CTA click is the number Sprint 21 is gated on.

No authentication, no session, no mail. Two things the endpoint owes the
person and the product: the address goes into one table and nowhere
else (not the audit log, not a log line), and a repeat submit is not a
repeat lead. The e-mail is validated for shape only — nothing is sent to
it, so nothing needs proving.
"""

from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from audit import Severity
from ratelimit import FixedWindowLimiter, client_ip, parse_cidrs

from ..audit_kinds import LEAD_CAPTURED
from ..auth_metrics import leads_captured_counter
from ..config import settings
from ..deps import get_state
from ..domain import referrals

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/leads", tags=["auth"])

# Per IP per hour. Generous for a person, useless for a script.
_PER_IP_PER_HOUR = 20
# A ref code is 12 base32 characters (note-service share_links); a
# missing one is a public link's CTA and still a lead.
_REF_PATTERN = r"^[a-z2-7]{12}$"


class LeadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    ref: str | None = Field(default=None, pattern=_REF_PATTERN)
    # A checkbox on the page. Only `true` is accepted: an unchecked box
    # must be a refused request, not a stored lead with a false flag.
    consent: Literal[True]


class LeadAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"] = "accepted"


@router.post(
    "",
    response_model=LeadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Leave an e-mail address from the shared page's CTA",
)
async def capture_lead(body: LeadRequest, request: Request) -> LeadAccepted:
    state = get_state()
    redis = getattr(state, "_redis", None)
    if redis is not None:
        ip = client_ip(
            peer=request.client.host if request.client else None,
            forwarded_for=request.headers.get("x-forwarded-for"),
            trusted_proxies=parse_cidrs(settings.trusted_proxy_cidrs),
        )
        decision = await FixedWindowLimiter(redis, prefix="mdx:auth:rl").allow(
            "leads_ip", ip, limit=_PER_IP_PER_HOUR, window_seconds=3600, fail_open=True
        )
        if not decision.allowed:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail="too many requests; try again later",
                headers={"Retry-After": str(decision.retry_after)},
            )

    stored = await referrals.record_lead(
        state.tenant_writer_pool, ref_code=body.ref or "", email=str(body.email)
    )
    if stored:
        leads_captured_counter.add(1, {"ref_present": body.ref is not None})
        await state.audit_writer.write_event(
            tenant_id=UUID(settings.auth_platform_tenant_id),
            kind=LEAD_CAPTURED,
            actor_sub=None,
            actor_role=None,
            target_kind="user",
            target_id=None,
            payload={"ref_present": body.ref is not None},
            severity=Severity.INFO,
        )
    return LeadAccepted()
