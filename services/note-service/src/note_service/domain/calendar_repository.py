"""``calendar_connections`` rows and the token envelope around them (0019).

Every read is scoped twice: RLS to the tenant (the connection is
tenant-scoped), and ``user_sub`` here — a connection is personal and a
colleague's rows never come back.

Tokens go through ``libs/crypto``'s envelope before they reach the row.
``token_blob`` is a self-describing JSON document (header fields +
base64 ciphertext) so a future key rotation can re-wrap in place.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from crypto import Envelope, EnvelopeBlob, EnvelopeFormatError

_BLOB_VERSION = 1
# Binds the ciphertext to its purpose so a blob lifted from another
# column would fail to decrypt even under the same tenant KEK.
_AAD = b"calendar_connections.token_blob"


@dataclass(frozen=True, slots=True)
class ConnectionRow:
    id: UUID
    tenant_id: UUID
    user_sub: UUID
    provider: str
    account_email: str
    token_blob: bytes
    token_expires_at: datetime | None
    scopes: tuple[str, ...]
    hidden_calendar_ids: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None
    needs_reauth: bool
    last_synced_at: datetime | None
    last_error: str | None
    # 0020: sha256 of a calendar link's URL (provider 'ics'); None for Google.
    feed_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class StoredTokens:
    access_token: str
    refresh_token: str | None


# ── Envelope (de)serialisation ───────────────────────────────────────


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text)


def encode_blob(blob: EnvelopeBlob) -> bytes:
    doc = {
        "v": _BLOB_VERSION,
        "version": blob.version,
        "algorithm": blob.algorithm,
        "tenant_id": str(blob.tenant_id),
        "master_key_id": blob.master_key_id,
        "iv": _b64(blob.iv),
        "tag": _b64(blob.tag),
        "wrapped_dek": _b64(blob.wrapped_dek),
        "dek_iv": _b64(blob.dek_iv),
        "dek_tag": _b64(blob.dek_tag),
        "ciphertext": _b64(blob.ciphertext),
    }
    return json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")


def decode_blob(raw: bytes) -> EnvelopeBlob:
    try:
        doc = json.loads(raw.decode("utf-8"))
        return EnvelopeBlob(
            ciphertext=_unb64(doc["ciphertext"]),
            iv=_unb64(doc["iv"]),
            tag=_unb64(doc["tag"]),
            wrapped_dek=_unb64(doc["wrapped_dek"]),
            dek_iv=_unb64(doc["dek_iv"]),
            dek_tag=_unb64(doc["dek_tag"]),
            tenant_id=UUID(doc["tenant_id"]),
            master_key_id=str(doc["master_key_id"]),
            algorithm=str(doc["algorithm"]),
            version=int(doc["version"]),
            extra_aad=_AAD,
        )
    except (UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise EnvelopeFormatError(f"calendar token blob is invalid: {exc}") from exc


async def seal_tokens(envelope: Envelope, *, tenant_id: UUID, tokens: StoredTokens) -> bytes:
    plaintext = json.dumps(
        {"access_token": tokens.access_token, "refresh_token": tokens.refresh_token},
        separators=(",", ":"),
    ).encode("utf-8")
    blob = await envelope.encrypt(plaintext, tenant_id=tenant_id, aad=_AAD)
    return encode_blob(blob)


async def open_tokens(envelope: Envelope, *, tenant_id: UUID, token_blob: bytes) -> StoredTokens:
    blob = decode_blob(token_blob)
    plaintext = await envelope.decrypt(blob, tenant_id=tenant_id, aad=_AAD)
    doc = json.loads(plaintext.decode("utf-8"))
    return StoredTokens(
        access_token=str(doc["access_token"]),
        refresh_token=str(doc["refresh_token"]) if doc.get("refresh_token") else None,
    )


async def seal_feed_url(envelope: Envelope, *, tenant_id: UUID, url: str) -> bytes:
    """0020: a calendar link's secret address, sealed like a token — the
    URL is the credential."""
    plaintext = json.dumps({"feed_url": url}, separators=(",", ":")).encode("utf-8")
    blob = await envelope.encrypt(plaintext, tenant_id=tenant_id, aad=_AAD)
    return encode_blob(blob)


async def open_feed_url(envelope: Envelope, *, tenant_id: UUID, token_blob: bytes) -> str:
    blob = decode_blob(token_blob)
    plaintext = await envelope.decrypt(blob, tenant_id=tenant_id, aad=_AAD)
    doc = json.loads(plaintext.decode("utf-8"))
    url = str(doc.get("feed_url") or "")
    if not url:
        raise EnvelopeFormatError("calendar link blob has no feed_url")
    return url


# ── Rows ─────────────────────────────────────────────────────────────

_COLUMNS = """
    id, tenant_id, user_sub, provider, account_email, token_blob,
    token_expires_at, scopes, hidden_calendar_ids, created_at, updated_at,
    revoked_at, needs_reauth, last_synced_at, last_error, feed_fingerprint
"""


def _row(record: asyncpg.Record | dict[str, Any]) -> ConnectionRow:
    return ConnectionRow(
        id=record["id"],
        tenant_id=record["tenant_id"],
        user_sub=record["user_sub"],
        provider=record["provider"],
        account_email=record["account_email"],
        token_blob=bytes(record["token_blob"]),
        token_expires_at=record["token_expires_at"],
        scopes=tuple(record["scopes"] or ()),
        hidden_calendar_ids=tuple(record["hidden_calendar_ids"] or ()),
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        revoked_at=record["revoked_at"],
        needs_reauth=bool(record["needs_reauth"]),
        last_synced_at=record["last_synced_at"],
        last_error=record["last_error"],
        feed_fingerprint=record["feed_fingerprint"],
    )


async def list_live(conn: asyncpg.Connection, *, user_sub: UUID) -> list[ConnectionRow]:
    records = await conn.fetch(
        f"""
        SELECT {_COLUMNS}
        FROM calendar_connections
        WHERE user_sub = $1 AND revoked_at IS NULL
        ORDER BY created_at
        """,
        user_sub,
    )
    return [_row(r) for r in records]


async def fetch_live(
    conn: asyncpg.Connection, *, user_sub: UUID, connection_id: UUID
) -> ConnectionRow | None:
    record = await conn.fetchrow(
        f"""
        SELECT {_COLUMNS}
        FROM calendar_connections
        WHERE id = $1 AND user_sub = $2 AND revoked_at IS NULL
        """,
        connection_id,
        user_sub,
    )
    return _row(record) if record else None


async def upsert(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    user_sub: UUID,
    provider: str,
    account_email: str,
    token_blob: bytes,
    token_expires_at: datetime | None,
    scopes: tuple[str, ...],
) -> ConnectionRow:
    """Reconnecting an account that is already live replaces its tokens
    and keeps its calendar choices; a new account gets a fresh row."""
    record = await conn.fetchrow(
        f"""
        INSERT INTO calendar_connections
            (tenant_id, user_sub, provider, account_email, token_blob,
             token_expires_at, scopes)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (tenant_id, user_sub, provider, account_email)
            WHERE revoked_at IS NULL
        DO UPDATE SET
            token_blob = EXCLUDED.token_blob,
            token_expires_at = EXCLUDED.token_expires_at,
            scopes = EXCLUDED.scopes,
            needs_reauth = false,
            last_error = NULL,
            updated_at = now()
        RETURNING {_COLUMNS}
        """,
        tenant_id,
        user_sub,
        provider,
        account_email,
        token_blob,
        token_expires_at,
        list(scopes),
    )
    assert record is not None
    return _row(record)


async def insert_feed(
    conn: asyncpg.Connection,
    *,
    tenant_id: UUID,
    user_sub: UUID,
    label: str,
    token_blob: bytes,
    feed_fingerprint: str,
) -> ConnectionRow:
    """0020: a calendar link. The same URL added twice refreshes the
    existing row (label, sealed URL) and keeps its calendar choice."""
    record = await conn.fetchrow(
        f"""
        INSERT INTO calendar_connections
            (tenant_id, user_sub, provider, account_email, token_blob,
             scopes, feed_fingerprint)
        VALUES ($1, $2, 'ics', $3, $4, '{{}}', $5)
        ON CONFLICT (tenant_id, user_sub, feed_fingerprint)
            WHERE revoked_at IS NULL AND feed_fingerprint IS NOT NULL
        DO UPDATE SET
            account_email = EXCLUDED.account_email,
            token_blob = EXCLUDED.token_blob,
            needs_reauth = false,
            last_error = NULL,
            updated_at = now()
        RETURNING {_COLUMNS}
        """,
        tenant_id,
        user_sub,
        label,
        token_blob,
        feed_fingerprint,
    )
    assert record is not None
    return _row(record)


async def store_tokens(
    conn: asyncpg.Connection,
    *,
    connection_id: UUID,
    token_blob: bytes,
    token_expires_at: datetime | None,
) -> None:
    await conn.execute(
        """
        UPDATE calendar_connections
        SET token_blob = $2, token_expires_at = $3, needs_reauth = false,
            last_error = NULL, updated_at = now()
        WHERE id = $1
        """,
        connection_id,
        token_blob,
        token_expires_at,
    )


async def mark_synced(conn: asyncpg.Connection, *, connection_id: UUID) -> None:
    await conn.execute(
        """
        UPDATE calendar_connections
        SET last_synced_at = now(), last_error = NULL, updated_at = now()
        WHERE id = $1
        """,
        connection_id,
    )


async def mark_failed(
    conn: asyncpg.Connection, *, connection_id: UUID, error: str, needs_reauth: bool
) -> None:
    await conn.execute(
        """
        UPDATE calendar_connections
        SET last_error = $2, needs_reauth = needs_reauth OR $3, updated_at = now()
        WHERE id = $1
        """,
        connection_id,
        error[:200],
        needs_reauth,
    )


async def set_hidden_calendars(
    conn: asyncpg.Connection, *, connection_id: UUID, hidden: tuple[str, ...]
) -> None:
    await conn.execute(
        """
        UPDATE calendar_connections
        SET hidden_calendar_ids = $2, updated_at = now()
        WHERE id = $1
        """,
        connection_id,
        list(hidden),
    )


async def revoke(conn: asyncpg.Connection, *, connection_id: UUID) -> None:
    await conn.execute(
        """
        UPDATE calendar_connections
        SET revoked_at = now(), updated_at = now()
        WHERE id = $1 AND revoked_at IS NULL
        """,
        connection_id,
    )


def utcnow() -> datetime:
    return datetime.now(UTC)
