"""Delete, visibility and sharing for one note (0016).

    GET    /v1/notes/{id}/sharing        who can see it, and the public link
    PUT    /v1/notes/{id}/visibility     private | workspace
    POST   /v1/notes/{id}/share          give a workspace member access (+ notify)
    POST   /v1/notes/{id}/share/email    mail the note to people, from the server
    DELETE /v1/notes/{id}/share/{sub}    take it back
    POST   /v1/notes/{id}/public-link    "anyone with the link" (idempotent)
    DELETE /v1/notes/{id}/public-link    revoke it
    POST   /v1/notes/{id}/links          a per-recipient link
    GET    /v1/notes/{id}/links          every live link on the note
    DELETE /v1/notes/{id}/links/{link}   revoke one
    DELETE /v1/notes/{id}/links          revoke them all
    DELETE /v1/notes/{id}                soft delete

Sharing with a member sends a content-free ``note.shared_with_you`` notification
(ADR-0031); non-members cannot be granted access. ``/share/email`` is the one
place a note's title and the sharer's words leave the system in an e-mail.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from audit import Severity
from auth import Claims
from db import tenant_connection
from note_models import NoteStatus
from notification_events import Category

from .. import audit_kinds
from ..adapters import share_mail_copy
from ..config import settings
from ..deps import get_state, requires
from ..domain import access, recipient_mail, share_email, share_links, sharing_policy
from ..domain import action_items_repository as items_repo
from ..domain import notes_repository as repo
from ..domain.branding import load_tenant_branding
from ..domain.share_tokens import hash_token, token_for
from ..notifications import emit_note_event
from ..share_metrics import links_created

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/notes", tags=["notes"])

Visibility = Literal["private", "workspace"]

# Public links do not expire by default.
_MAX_LINK_DAYS = 365


# ── Wire models ─────────────────────────────────────────────────────


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: UUID
    email: str
    display_name: str


ShareLinkKind = Literal["public", "recipient"]


class LinkView(BaseModel):
    """One share link. The token is returned only to people who may
    manage the note (every route here checks that); it never appears in
    audit or logs."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: ShareLinkKind
    # The sender's own name for the recipient. Empty for public links.
    label: str
    recipient_email: str | None
    token: str
    # SPA path; the client prefixes its own origin.
    path: str
    # Opaque referral code carried into /join?ref= (recipient links only).
    ref_code: str | None
    created_at: str
    expires_at: str | None
    view_count: int
    first_viewed_at: str | None
    last_viewed_at: str | None
    cta_clicked_at: str | None
    # Live responses (confirm/done/dispute/flag) from this link.
    response_count: int = 0
    delivery_status: Literal["not_sent", "sent", "failed", "suppressed"] = "not_sent"
    sent_at: str | None = None
    send_count: int = 0
    last_send_error: str = ""


class SharingView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    visibility: Visibility
    can_manage: bool
    can_delete: bool
    shared_with: list[Member]
    # The live public link, kept for clients that predate `links`.
    public_link: LinkView | None
    # Every live link, newest first — public and recipient.
    links: list[LinkView]
    # The workspace's effective rules, so clients can hide what the server would refuse.
    constraints: sharing_policy.Constraints


class VisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: Visibility


class ShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Loose shape check only; the real test is "is this a member".
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# Loose shape check: keeps nonsense and a header-injection newline out of the SMTP envelope.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ShareEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipients: list[str] = Field(min_length=1)
    # The sharer's own words, optional.
    message: str = Field(default="")
    # The sender's UI language: the recipient's is unknowable, this is the best guess.
    lang: str = Field(default=share_mail_copy.DEFAULT_LANG, max_length=16)
    # None → the deployment default, always clipped to the workspace ceiling.
    expires_in_days: int | None = Field(default=None, ge=1, le=365)

    @field_validator("recipients")
    @classmethod
    def _valid_addresses(cls, value: list[str]) -> list[str]:
        seen: set[str] = set()
        cleaned: list[str] = []
        for raw in value:
            address = raw.strip()
            if not _EMAIL_RE.match(address) or len(address) > 254:
                raise ValueError(f"{raw!r} is not an e-mail address")
            # Case-insensitive dedupe.
            key = address.lower()
            if key not in seen:
                seen.add(key)
                cleaned.append(address)
        return cleaned


class ShareEmailOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    # ``member``: granted access, mailed an app link; ``link``: mailed their own recipient link.
    access: Literal["member", "link"]
    # ``rejected``: the mailbox does not exist; ``failed``: worth trying again.
    status: Literal["sent", "rejected", "failed"]


class ShareEmailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sharing: SharingView
    results: list[ShareEmailOutcome]
    # Kept for older clients; always False now that outsiders get recipient links.
    public_link_created: bool = False


class PublicLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_in_days: int | None = Field(default=None, ge=1, le=_MAX_LINK_DAYS)


class CreateLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["recipient"] = "recipient"
    label: str = Field(min_length=1, max_length=120)
    recipient_email: str | None = Field(
        default=None, max_length=254, pattern=r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$"
    )
    # None → the deployment default (90 days).
    expires_in_days: int | None = Field(default=None, ge=1, le=_MAX_LINK_DAYS)
    # Create and mail in one call.
    send: bool = False
    personal_message: str = Field(default="", max_length=recipient_mail.MAX_PERSONAL_MESSAGE)
    lang: str = Field(default=share_mail_copy.DEFAULT_LANG, max_length=16)
    # Where the sender was when they made it — a funnel label, not data.
    source: Literal["dialog", "nudge", "native"] = "dialog"


class SendLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personal_message: str = Field(default="", max_length=recipient_mail.MAX_PERSONAL_MESSAGE)
    lang: str = Field(default=share_mail_copy.DEFAULT_LANG, max_length=16)


class DeletedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    deleted_at: str


# ── Helpers ─────────────────────────────────────────────────────────


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _link_view(link: repo.ShareLinkRow, *, response_count: int = 0) -> LinkView:
    token = token_for(link.id, key_hex=settings.share_link_hmac_key_hex)
    return LinkView(
        response_count=response_count,
        id=link.id,
        kind=link.kind,  # type: ignore[arg-type]
        label=link.label,
        recipient_email=link.recipient_email,
        token=token,
        path=f"/s/{token}",
        ref_code=link.ref_code,
        created_at=link.created_at.isoformat(),
        expires_at=_iso(link.expires_at),
        view_count=link.view_count,
        first_viewed_at=_iso(link.first_viewed_at),
        last_viewed_at=_iso(link.last_viewed_at),
        cta_clicked_at=_iso(link.cta_clicked_at),
        delivery_status=link.delivery_status,  # type: ignore[arg-type]
        sent_at=_iso(link.sent_at),
        send_count=link.send_count,
        last_send_error=link.last_send_error,
    )


async def _sharing_view(conn: object, note: repo.NoteRow, claims: Claims) -> SharingView:
    members = await repo.fetch_members(conn, subs=note.shared_with_ids)  # type: ignore[arg-type]
    links = await repo.list_live_share_links(conn, note_id=note.id)  # type: ignore[arg-type]
    manage = access.can_manage(note, claims)
    policy, _plan = await sharing_policy.load_policy(conn, tenant_id=claims.tid)  # type: ignore[arg-type]
    # Tokens are credentials: a reader who cannot manage sees that links exist, not what they are.
    views: list[LinkView] = []
    if manage and links:
        counts = await items_repo.live_response_counts_by_link(conn, note_id=note.id)  # type: ignore[arg-type]
        views = [_link_view(link, response_count=counts.get(link.id, 0)) for link in links]
    return SharingView(
        note_id=note.id,
        visibility=note.visibility,  # type: ignore[arg-type]
        can_manage=manage,
        can_delete=access.can_delete(note, claims),
        shared_with=[
            Member(sub=m.sub, email=m.email, display_name=m.display_name) for m in members
        ],
        public_link=next((v for v in views if v.kind == "public"), None),
        links=views,
        constraints=_constraints(policy),
    )


def _constraints(policy: sharing_policy.SharingPolicy) -> sharing_policy.Constraints:
    c = sharing_policy.constraints_of(policy)
    if not settings.external_sharing_enabled:
        # The deployment flag beats every workspace setting.
        c = c.model_copy(update={"external_links_enabled": False, "public_links_enabled": False})
    return c


def _refuse(code: str, detail: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, detail={"code": code, "detail": detail})


async def _policy_for(conn: object, claims: Claims) -> sharing_policy.SharingPolicy:
    policy, _plan = await sharing_policy.load_policy(conn, tenant_id=claims.tid)  # type: ignore[arg-type]
    return policy


def _require_external(policy: sharing_policy.SharingPolicy) -> None:
    if not settings.external_sharing_enabled or not policy.external_links_enabled:
        raise _refuse(
            "external_sharing_disabled", "external sharing is switched off for this workspace"
        )


def _require_public(policy: sharing_policy.SharingPolicy) -> None:
    if not settings.external_sharing_enabled or not policy.public_links_enabled:
        raise _refuse("public_links_disabled", "public links are switched off for this workspace")


def _label_from_email(address: str) -> str:
    """ "tom @ client.com" — what the sheet shows when no label was given."""
    local, _, domain = address.strip().partition("@")
    return f"{local} @ {domain}" if domain else address.strip()


def _link_created_payload(link: repo.ShareLinkRow, **extra: object) -> dict[str, object]:
    links_created.add(1, {"kind": link.kind})
    return {
        "link_id": str(link.id),
        "kind": link.kind,
        "expires_at": _iso(link.expires_at),
        "has_recipient_email": link.recipient_email is not None,
        **extra,
    }


async def _audit(claims: Claims, kind: str, note_id: UUID, payload: dict[str, object]) -> None:
    state = get_state()
    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        target_kind="note",
        target_id=note_id,
        payload=payload,
        severity=Severity.INFO,
    )


async def _grant_member(
    conn: object, note: repo.NoteRow, member_sub: UUID
) -> tuple[repo.NoteRow, bool]:
    """Give one member read access. Returns (note, newly_granted). Idempotent: re-sharing is a no-op."""
    if member_sub in note.shared_with_ids or access.is_author_team(note, member_sub):
        return note, False
    await repo.add_shared_with(conn, note_id=note.id, user_sub=member_sub)  # type: ignore[arg-type]
    refreshed = await repo.fetch_note(conn, note_id=note.id)  # type: ignore[arg-type]
    return (refreshed or note), True


async def _notify_shared(
    claims: Claims, note: repo.NoteRow, member_sub: UUID, sharer_display: str
) -> None:
    """The in-app + e-mail ping. Content-free by contract (ADR-0031)."""
    state = get_state()
    await _audit(
        claims, audit_kinds.NOTE_SHARED, note.id, {"with": str(member_sub), "via": "member"}
    )
    await emit_note_event(
        state.redis,
        category=Category.NOTE_SHARED_WITH_YOU,
        tenant_id=claims.tid,
        note_id=note.id,
        note_code=note.code,
        actor_user_id=claims.sub,
        # The recipient hint IS the sharee — nobody else is told.
        primary_author_id=member_sub,
        extra_payload={"shared_by_display": sharer_display},
    )


async def _ensure_public_link(
    conn: object, claims: Claims, note_id: UUID
) -> tuple[repo.ShareLinkRow, bool]:
    """The live link for a note, minting one if there is none. Returns (link, created); idempotent."""
    link = await repo.fetch_live_share_link(conn, note_id=note_id)  # type: ignore[arg-type]
    if link is not None:
        return link, False
    _require_public(await _policy_for(conn, claims))
    link_id = uuid4()
    link = await repo.create_share_link(
        conn,  # type: ignore[arg-type]
        link_id=link_id,
        tenant_id=claims.tid,
        note_id=note_id,
        token_hash=hash_token(token_for(link_id, key_hex=settings.share_link_hmac_key_hex)),
        created_by=claims.sub,
        expires_at=None,
    )
    return link, True


# ── Routes ──────────────────────────────────────────────────────────


@router.get("/{note_id}/sharing", response_model=SharingView)
async def get_sharing(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        return await _sharing_view(conn, note, claims)


@router.put("/{note_id}/visibility", response_model=SharingView)
async def set_visibility(
    note_id: UUID,
    body: VisibilityRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        previous = note.visibility
        if previous != body.visibility:
            await repo.set_visibility(conn, note_id=note_id, visibility=body.visibility)
            note = await repo.fetch_note(conn, note_id=note_id) or note
        view = await _sharing_view(conn, note, claims)
    if previous != body.visibility:
        await _audit(
            claims,
            audit_kinds.NOTE_VISIBILITY_CHANGED,
            note_id,
            {"from": previous, "to": body.visibility},
        )
    return view


@router.post("/{note_id}/share", response_model=SharingView)
async def share_with_member(
    note_id: UUID,
    body: ShareRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        member = await repo.find_member_by_email(conn, email=str(body.email))
        if member is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "not_a_member",
                    "detail": "nobody in your workspace has that e-mail address",
                },
            )
        note, granted = await _grant_member(conn, note, member.sub)
        # The sharer's name for the notification — a person, not a sub.
        (me,) = await repo.fetch_members(conn, subs=[claims.sub]) or [None]
        view = await _sharing_view(conn, note, claims)

    if granted:
        await _notify_shared(claims, note, member.sub, me.display_name if me else "A colleague")
    return view


@router.post("/{note_id}/share/email", response_model=ShareEmailResponse)
async def share_by_email(
    note_id: UUID,
    body: ShareEmailRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> ShareEmailResponse:
    """Mail the note to the people the sharer named, from the server.

    Two kinds of recipient, one button. A workspace member is granted
    access and mailed a link to the note in the app; anybody else gets
    their own recipient link (minted here, one per address, reused when
    it already exists) so the sender can see who opened it and turn one
    off without the others. The mail says plainly that anyone holding
    the link can read it.

    Sending is per-recipient and never raises: one dead address must not
    swallow the four mails that would have arrived. The response says
    what happened to each one so the sender can fix a typo rather than
    wonder.
    """
    state = get_state()
    max_recipients = settings.share_email_max_recipients
    if len(body.recipients) > max_recipients:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"at most {max_recipients} recipients per send",
        )
    message = body.message.strip()[: settings.share_email_max_message_chars]
    lang = share_mail_copy.normalize_lang(body.lang)

    allowed, retry_after = await state.share_email_rate_limiter.check(
        user_id=claims.sub, cost=len(body.recipients)
    )
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="share e-mail rate limit reached",
            headers={"Retry-After": str(retry_after)},
        )

    base = settings.app_base_url.rstrip("/")
    granted: list[UUID] = []
    recipients: list[share_email.Recipient] = []
    created_links: list[repo.ShareLinkRow] = []
    outsider_links: dict[str, repo.ShareLinkRow] = {}

    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        (me,) = await repo.fetch_members(conn, subs=[claims.sub]) or [None]
        policy = await _policy_for(conn, claims)

        for address in body.recipients:
            member = await repo.find_member_by_email(conn, email=address)
            if member is not None:
                note, newly = await _grant_member(conn, note, member.sub)
                if newly:
                    granted.append(member.sub)
                recipients.append(
                    share_email.Recipient(
                        email=address,
                        access=share_mail_copy.ACCESS_MEMBER,
                        link_url=f"{base}/notes/{note_id}",
                    )
                )
                continue
            _require_external(policy)
            link, created = await share_links.create_recipient_link(
                conn,
                note=note,
                claims=claims,
                request=share_links.RecipientLinkRequest(
                    label=_label_from_email(address),
                    recipient_email=address,
                    expires_in_days=min(
                        body.expires_in_days or settings.recipient_link_default_days,
                        policy.max_link_days,
                    ),
                ),
                key_hex=settings.share_link_hmac_key_hex,
            )
            if created:
                created_links.append(link)
            outsider_links[address.lower()] = link
            token = token_for(link.id, key_hex=settings.share_link_hmac_key_hex)
            recipients.append(
                share_email.Recipient(
                    email=address,
                    access=share_mail_copy.ACCESS_LINK,
                    link_url=f"{base}/s/{token}",
                )
            )

        view = await _sharing_view(conn, note, claims)

    sharer_name = (me.display_name if me else "") or "A colleague"
    sharer_email = me.email if me else ""
    shared_at = datetime.now(UTC)

    # Outside the connection block: a slow relay must not hold a pooled DB connection.
    outcomes = await share_email.send_many(
        state.email_provider,
        recipients,
        lang=lang,
        sharer_name=sharer_name,
        sharer_email=sharer_email,
        note_title=note.title,
        message=message,
        shared_at=shared_at,
        timeout_seconds=settings.share_email_timeout_s,
    )

    if outsider_links:
        # Record the outcome on each link, then re-read the view.
        async with tenant_connection(state.app_pool, claims.tid) as conn:
            for o in outcomes:
                link = outsider_links.get(o.email.lower())
                if link is not None:
                    await repo.record_send_outcome(
                        conn,
                        link_id=link.id,
                        status="sent" if o.status == "sent" else "failed",
                        error_class="" if o.status == "sent" else o.status,
                    )
            view = await _sharing_view(conn, note, claims)
    for link in created_links:
        await _audit(
            claims, audit_kinds.NOTE_LINK_CREATED, note_id, _link_created_payload(link, via="email")
        )
    for member_sub in granted:
        await _notify_shared(claims, note, member_sub, sharer_name)
    await _audit(
        claims,
        audit_kinds.NOTE_LINK_EMAILED,
        note_id,
        {
            # Counts and outcomes, never the addresses.
            "recipients": len(recipients),
            "members": sum(1 for r in recipients if r.access == share_mail_copy.ACCESS_MEMBER),
            "sent": sum(1 for o in outcomes if o.status == "sent"),
            "failed": sum(1 for o in outcomes if o.status != "sent"),
            "had_message": bool(message),
        },
    )

    return ShareEmailResponse(
        sharing=view,
        results=[
            ShareEmailOutcome(email=o.email, access=o.access, status=o.status)  # type: ignore[arg-type]
            for o in outcomes
        ],
    )


@router.delete("/{note_id}/share/{user_sub}", response_model=SharingView)
async def unshare_member(
    note_id: UUID,
    user_sub: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        if user_sub in note.shared_with_ids:
            await repo.remove_shared_with(conn, note_id=note_id, user_sub=user_sub)
            note = await repo.fetch_note(conn, note_id=note_id) or note
        view = await _sharing_view(conn, note, claims)
    await _audit(claims, audit_kinds.NOTE_UNSHARED, note_id, {"with": str(user_sub)})
    return view


@router.post("/{note_id}/public-link", response_model=SharingView)
async def create_public_link(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
    body: PublicLinkRequest | None = None,
) -> SharingView:
    """Idempotent: a note has at most one live link, and asking again
    returns it rather than minting a second."""
    state = get_state()
    created = False
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        link = await repo.fetch_live_share_link(conn, note_id=note_id)
        if link is None:
            policy = await _policy_for(conn, claims)
            _require_public(policy)
            link_id = uuid4()
            expires = None
            if body is not None and body.expires_in_days is not None:
                days = min(body.expires_in_days, policy.max_link_days)
                expires = datetime.now(UTC) + timedelta(days=days)
            link = await repo.create_share_link(
                conn,
                link_id=link_id,
                tenant_id=claims.tid,
                note_id=note_id,
                token_hash=hash_token(token_for(link_id, key_hex=settings.share_link_hmac_key_hex)),
                created_by=claims.sub,
                expires_at=expires,
            )
            created = True
        view = await _sharing_view(conn, note, claims)
    if created:
        await _audit(claims, audit_kinds.NOTE_LINK_CREATED, note_id, _link_created_payload(link))
    return view


@router.delete("/{note_id}/public-link", response_model=SharingView)
async def revoke_public_link(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> SharingView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        revoked = await repo.revoke_share_links(conn, note_id=note_id, actor_sub=claims.sub)
        view = await _sharing_view(conn, note, claims)
    if revoked:
        await _audit(claims, audit_kinds.NOTE_LINK_REVOKED, note_id, {"revoked": revoked})
    return view


# ── Per-recipient links ─────────────────────────────────────────────


@router.post(
    "/{note_id}/links",
    response_model=LinkView,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "A live link for that recipient e-mail already exists."},
    },
)
async def create_recipient_link(
    note_id: UUID,
    body: CreateLinkRequest,
    response: Response,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> LinkView:
    """Mint a link for one recipient. Idempotent per e-mail address: a
    second call for the same address answers 200 with the existing link
    rather than minting one the sheet cannot tell apart."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        policy = await _policy_for(conn, claims)
        _require_external(policy)
        request = share_links.RecipientLinkRequest(
            label=body.label,
            recipient_email=body.recipient_email,
            # The workspace's ceiling clips, never refuses.
            expires_in_days=min(
                body.expires_in_days or settings.recipient_link_default_days, policy.max_link_days
            ),
        )
        link, created = await share_links.create_recipient_link(
            conn,
            note=note,
            claims=claims,
            request=request,
            key_hex=settings.share_link_hmac_key_hex,
        )
    if created:
        await _audit(
            claims,
            audit_kinds.NOTE_LINK_CREATED,
            note_id,
            _link_created_payload(link, source=body.source),
        )
    else:
        response.status_code = status.HTTP_200_OK
    if body.send:
        link = await _send_recipient_link(
            claims, note, link, personal_message=body.personal_message, lang=body.lang
        )
    return _link_view(link)


async def _send_recipient_link(
    claims: Claims,
    note: repo.NoteRow,
    link: repo.ShareLinkRow,
    *,
    personal_message: str,
    lang: str,
) -> repo.ShareLinkRow:
    """Mail one recipient link inline: 422 unmailable, 409 opted out, 429 over the
    cap; the outcome is recorded on the link either way."""
    state = get_state()
    if link.kind != "recipient" or not link.recipient_email:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "no_recipient_email",
                "detail": "add the recipient's e-mail address to send the link",
            },
        )
    if note.status == NoteStatus.CANCELLED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="the note is cancelled")
    address = link.recipient_email
    resend = link.send_count > 0
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        policy = await _policy_for(conn, claims)
        if not policy.product_email_enabled:
            raise _refuse(
                "product_email_disabled",
                "sending from the product is switched off for this workspace; copy the link instead",
            )
        if await repo.is_share_mail_suppressed(conn, email_hash=recipient_mail.email_hash(address)):
            await repo.record_send_outcome(conn, link_id=link.id, status="suppressed")
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "recipient_opted_out",
                    "detail": "this recipient asked not to receive e-mails; copy the link instead",
                },
            )
        await state.share_mail_caps.check(
            link_id=link.id, user_sub=claims.sub, tenant_id=claims.tid
        )
        branding = await load_tenant_branding(conn, tenant_id=str(claims.tid))
        (me,) = await repo.fetch_members(conn, subs=[claims.sub]) or [None]

    sharer_name = (me.display_name if me else "") or "A colleague"
    issuer = branding.issuer_name if branding.issuer_name != "—" else settings.pdf_issuer_name
    # Outside the connection: a slow relay must not hold a pooled connection.
    outcome = await recipient_mail.send_link(
        state.email_provider,
        link=link,
        to_address=address,
        sharer_name=sharer_name,
        # Replies go to the sender, or the workspace's contact address.
        reply_to=(me.email if me else "") or branding.contact_email,
        issuer_name=issuer,
        personal_message=personal_message,
        lang=lang,
    )
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        updated = await repo.record_send_outcome(
            conn, link_id=link.id, status=outcome.status, error_class=outcome.error_class
        )
    await _audit(
        claims,
        audit_kinds.NOTE_LINK_SENT,
        note.id,
        {"link_id": str(link.id), "resend": resend, "outcome": outcome.status},
    )
    return updated or link


@router.post("/{note_id}/links/{link_id}/send", response_model=LinkView)
async def send_link(
    note_id: UUID,
    link_id: UUID,
    body: SendLinkRequest,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> LinkView:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        link = share_links.link_belongs_to(
            await repo.fetch_share_link(conn, link_id=link_id), note_id
        )
    if link is None or link.revoked_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="link not found")
    return _link_view(
        await _send_recipient_link(
            claims, note, link, personal_message=body.personal_message, lang=body.lang
        )
    )


@router.get("/{note_id}/links", response_model=list[LinkView])
async def list_links(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> list[LinkView]:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_view(await repo.fetch_note(conn, note_id=note_id), claims)
        return (await _sharing_view(conn, note, claims)).links


@router.delete("/{note_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_link(
    note_id: UUID,
    link_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> Response:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        revoked = await repo.revoke_share_link(
            conn, note_id=note_id, link_id=link_id, actor_sub=claims.sub
        )
    if not revoked:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="link not found")
    await _audit(
        claims, audit_kinds.NOTE_LINK_REVOKED, note_id, {"revoked": 1, "link_id": str(link_id)}
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{note_id}/links", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_links(
    note_id: UUID,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> Response:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        access.require_manage(await repo.fetch_note(conn, note_id=note_id), claims)
        revoked = await repo.revoke_share_links(conn, note_id=note_id, actor_sub=claims.sub)
    if revoked:
        await _audit(claims, audit_kinds.NOTE_LINK_REVOKED, note_id, {"revoked": revoked})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sharing/constraints", response_model=sharing_policy.Constraints)
async def sharing_constraints(
    claims: Annotated[Claims, Depends(requires("note.read", "note"))],
) -> sharing_policy.Constraints:
    """The workspace's effective sharing rules, for any member's client
    (Sprint 23)."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        return _constraints(await _policy_for(conn, claims))


@router.delete("/{note_id}", response_model=DeletedResponse)
async def delete_note(
    note_id: UUID,
    request: Request,
    claims: Annotated[Claims, Depends(requires("note.write", "note"))],
) -> DeletedResponse:
    """Soft delete. The note leaves every list and read path and its
    public links stop working; the row and its versions are kept."""
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        note = access.require_delete(await repo.fetch_note(conn, note_id=note_id), claims)
        await repo.soft_delete_note(conn, note_id=note_id, actor_sub=claims.sub)
    deleted_at = datetime.now(UTC)
    await _audit(
        claims,
        audit_kinds.NOTE_DELETED,
        note_id,
        {
            "code": note.code,
            "status": note.status.value,
            "user_agent": request.headers.get("user-agent", "")[:120],
        },
    )
    return DeletedResponse(id=note_id, deleted_at=deleted_at.isoformat())
