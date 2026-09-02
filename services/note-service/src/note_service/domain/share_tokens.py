"""Public share-link tokens (0016).

A token is *derived* from the link row's id with a server-side HMAC key
rather than generated and stored: the database holds only a hash, so a
leaked dump does not yield working links, yet the service can always
show the author their current link again without keeping the secret
around. Rotating the key invalidates every link at once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from uuid import UUID


def token_for(link_id: UUID, *, key_hex: str) -> str:
    digest = hmac.new(bytes.fromhex(key_hex), link_id.bytes, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


def looks_like_token(token: str) -> bool:
    return 40 <= len(token) <= 64 and all(c.isalnum() or c in "-_" for c in token)
