"""Minting a per-recipient share link (0035, Sprint 19).

A link can be created for any live note — the note is a living document
and the page always shows its current text (Sprint 23's "what changed"
tells the recipient when it moved).
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from auth import Claims

from . import notes_repository as repo
from .share_tokens import hash_token, token_for


@dataclass(frozen=True, slots=True)
class RecipientLinkRequest:
    label: str
    recipient_email: str | None
    expires_in_days: int


def normalise_email(value: str | None) -> str | None:
    cleaned = (value or "").strip().lower()
    return cleaned or None


def new_ref_code() -> str:
    """12 base32 characters from 8 random bytes. Opaque: it pre-fills
    referral attribution and nothing else, so it carries no tenant or
    note information a reader could learn from."""
    return base64.b32encode(secrets.token_bytes(8)).decode("ascii").rstrip("=").lower()[:12]


async def create_recipient_link(
    conn: object,
    *,
    note: repo.NoteRow,
    claims: Claims,
    request: RecipientLinkRequest,
    key_hex: str,
) -> tuple[repo.ShareLinkRow, bool]:
    """Mint a recipient link, or hand back the live one already minted
    for the same address. Returns (link, created)."""
    email = normalise_email(request.recipient_email)
    if email is not None:
        existing = await repo.find_live_recipient_link(
            conn,  # type: ignore[arg-type]
            note_id=note.id,
            recipient_email=email,
        )
        if existing is not None:
            return existing, False

    link_id = uuid4()
    link = await repo.create_share_link(
        conn,  # type: ignore[arg-type]
        link_id=link_id,
        tenant_id=claims.tid,
        note_id=note.id,
        token_hash=hash_token(token_for(link_id, key_hex=key_hex)),
        created_by=claims.sub,
        expires_at=datetime.now(UTC) + timedelta(days=request.expires_in_days),
        kind="recipient",
        label=request.label.strip(),
        recipient_email=email,
        ref_code=new_ref_code(),
    )
    return link, True


def link_belongs_to(link: repo.ShareLinkRow | None, note_id: UUID) -> repo.ShareLinkRow | None:
    """A link id is only meaningful together with its note id (B-9 IDOR)."""
    if link is None or link.note_id != note_id:
        return None
    return link
