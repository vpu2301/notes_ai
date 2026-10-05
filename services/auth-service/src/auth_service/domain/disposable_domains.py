"""Throwaway-mail domains signup quietly ignores (Sprint 21).

A bundled floor, not a service: the well-known providers whose whole
point is an address that stops existing in ten minutes. A signup from
one of these answers the same 202 as everything else and creates
nothing — the person would never receive the code anyway, and the
tenant row would be spam. ``MDX_DISPOSABLE_DOMAINS_FILE`` can point at a
longer list (one domain per line, ``#`` comments) for deployments that
keep one.
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
    """The bundled set plus whatever the file adds. A missing or
    unreadable file is logged and ignored — the floor still holds."""
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
