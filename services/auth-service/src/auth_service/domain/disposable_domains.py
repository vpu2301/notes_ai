"""Throwaway-mail domains signup quietly ignores (same 202, nothing created).

``MDX_DISPOSABLE_DOMAINS_FILE`` may add more (one per line, ``#`` comments).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BUNDLED: frozenset[str] = frozenset(
    {
        "10minutemail.com",
        "10minutemail.net",
        "20minutemail.com",
        "dispostable.com",
        "fakeinbox.com",
        "getnada.com",
        "guerrillamail.com",
        "guerrillamail.net",
        "guerrillamail.org",
        "mailinator.com",
        "maildrop.cc",
        "mailnesia.com",
        "mintemail.com",
        "mohmal.com",
        "sharklasers.com",
        "spamgourmet.com",
        "temp-mail.org",
        "tempmail.com",
        "tempmailo.com",
        "throwawaymail.com",
        "trashmail.com",
        "yopmail.com",
        "yopmail.fr",
    }
)


def load(path: str | None) -> frozenset[str]:
    """The bundled set plus the file's additions; an unreadable file is logged and ignored."""
    domains = set(BUNDLED)
    if path:
        try:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                value = line.split("#", 1)[0].strip().lower()
                if value:
                    domains.add(value)
        except OSError as exc:
            logger.warning("auth.signup.disposable_list_unreadable", extra={"error": str(exc)})
    return frozenset(domains)


def is_disposable(email: str, domains: frozenset[str]) -> bool:
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in domains
