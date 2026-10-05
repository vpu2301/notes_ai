"""Template variables for account mail, computed at request time and frozen into the outbox row.

Only ``secret_fields`` carries a redeemable token, and only it is destroyed once sent.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Final
from urllib.parse import quote

from . import copy as copy_mod

# Shown when the request carries no usable User-Agent.
_UNKNOWN_CLIENT: Final[dict[str, str]] = {
    "en": "Unrecognised device",
    "de": "Unbekanntes Gerät",
    "uk": "Невідомий пристрій",
}

# Deliberately lossy User-Agent parsing: "Chrome on macOS", not a fingerprint.
_BROWSERS: Final[tuple[tuple[str, str], ...]] = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Chrome/", "Chrome"),
    ("Firefox/", "Firefox"),
    ("Safari/", "Safari"),
)
_PLATFORMS: Final[tuple[tuple[str, str], ...]] = (
    ("Windows", "Windows"),
    ("Macintosh", "macOS"),
    ("Mac OS X", "macOS"),
    ("Android", "Android"),
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Linux", "Linux"),
)

_ON: Final[dict[str, str]] = {"en": "on", "de": "auf", "uk": "на"}


def client_label(user_agent: str, lang: str) -> str:
    """A short, human-recognisable description of the requesting client."""
    ua = (user_agent or "").strip()
    if not ua:
        return _UNKNOWN_CLIENT.get(lang, _UNKNOWN_CLIENT["en"])
    browser = next((name for token, name in _BROWSERS if token in ua), "")
    platform = next((name for token, name in _PLATFORMS if token in ua), "")
    if browser and platform:
        return f"{browser} {_ON.get(lang, 'on')} {platform}"
    if browser or platform:
        return browser or platform
    return _UNKNOWN_CLIENT.get(lang, _UNKNOWN_CLIENT["en"])


def hash_ip(ip: str, *, salt: str) -> str:
    """Salted, 128-bit-truncated hash of a client IP (unsalted IPv4 hashes are brute-forceable)."""
    if not ip:
        return ""
    digest = hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()
    return digest[:32]


def _sanitise_base(base_url: str) -> str:
    return (base_url or "").rstrip("/")


def reset_url(*, app_base_url: str, token: str) -> str:
    """Deep link into the SPA's reset screen; the token rides in the fragment (never sent to servers or Referer)."""
    return f"{_sanitise_base(app_base_url)}/#/reset-password?token={quote(token, safe='')}"


def lockdown_url(*, app_base_url: str, token: str) -> str:
    """Deep link into the SPA's "that wasn't me" screen."""
    return f"{_sanitise_base(app_base_url)}/#/account-recovery?token={quote(token, safe='')}"


def privacy_url(*, app_base_url: str) -> str:
    return f"{_sanitise_base(app_base_url)}/#/legal/privacy"


def _base_fields(
    *,
    lang: str,
    email: str,
    display_name: str,
    user_agent: str,
    support_url: str,
    app_base_url: str,
) -> dict[str, Any]:
    return {
        "greeting": copy_mod.greeting(lang, display_name),
        "email": email,
        "client_label": client_label(user_agent, lang),
        "support_url": support_url,
        "privacy_url": privacy_url(app_base_url=app_base_url),
    }


def password_reset_fields(
    *,
    lang: str,
    email: str,
    display_name: str,
    user_agent: str,
    support_url: str,
    app_base_url: str,
    requested_at: Any,
    ttl_seconds: int,
) -> dict[str, Any]:
    """Non-secret variables for the reset mail. Safe to retain."""
    fields = _base_fields(
        lang=lang,
        email=email,
        display_name=display_name,
        user_agent=user_agent,
        support_url=support_url,
        app_base_url=app_base_url,
    )
    fields["requested_at"] = copy_mod.format_moment(requested_at, lang)
    fields["expiry_label"] = copy_mod.minutes_label(ttl_seconds, lang)
    return fields


def password_changed_fields(
    *,
    lang: str,
    email: str,
    display_name: str,
    user_agent: str,
    support_url: str,
    app_base_url: str,
    changed_at: Any,
    lockdown_ttl_seconds: int,
) -> dict[str, Any]:
    """Non-secret variables for the security notification."""
    fields = _base_fields(
        lang=lang,
        email=email,
        display_name=display_name,
        user_agent=user_agent,
        support_url=support_url,
        app_base_url=app_base_url,
    )
    fields["changed_at"] = copy_mod.format_moment(changed_at, lang)
    fields["lockdown_expiry_label"] = _days_label(lockdown_ttl_seconds, lang)
    return fields


def format_code(code: str) -> str:
    """``"482913"`` → ``"482 913"``: two groups read aloud far more reliably."""
    digits = "".join(ch for ch in code if ch.isdigit())
    return f"{digits[:3]} {digits[3:]}" if len(digits) == 6 else code


def auth_code_fields(
    *,
    lang: str,
    code: str,
    ttl_seconds: int,
    user_agent: str,
    requested_at: Any,
) -> dict[str, Any]:
    """Variables for the sign-in code mail: no address, no link, no support URL."""
    return {
        "greeting": copy_mod.greeting(lang),
        "code": format_code(code),
        "expiry_label": copy_mod.minutes_label(ttl_seconds, lang),
        "requested_at": copy_mod.format_moment(requested_at, lang),
        "client_label": client_label(user_agent, lang),
    }


def signin_url(*, app_base_url: str) -> str:
    """Where "sign in instead" points: the SPA's login page, never Keycloak's forms."""
    return f"{_sanitise_base(app_base_url)}/login"


def signup_verify_fields(
    *,
    lang: str,
    code: str,
    ttl_seconds: int,
    user_agent: str,
    requested_at: Any,
) -> dict[str, Any]:
    """Variables for the signup confirmation mail: a code, not a link (mail scanners open links)."""
    return {
        "greeting": copy_mod.greeting(lang),
        "code": format_code(code),
        "expiry_label": copy_mod.minutes_label(ttl_seconds, lang),
        "requested_at": copy_mod.format_moment(requested_at, lang),
        "client_label": client_label(user_agent, lang),
    }


def signup_exists_fields(
    *,
    lang: str,
    app_base_url: str,
    user_agent: str,
    requested_at: Any,
) -> dict[str, Any]:
    """Variables for the "you already have an account" mail: a link, no code."""
    return {
        "greeting": copy_mod.greeting(lang),
        "signin_url": signin_url(app_base_url=app_base_url),
        "requested_at": copy_mod.format_moment(requested_at, lang),
        "client_label": client_label(user_agent, lang),
    }


def change_password_url(*, app_base_url: str) -> str:
    """The SPA's change-password screen. Not Keycloak's account console."""
    return f"{_sanitise_base(app_base_url)}/settings/password"


def concierge_welcome_fields(
    *,
    lang: str,
    display_name: str,
    temporary_password: str,
    app_base_url: str,
    created_at: Any,
) -> dict[str, Any]:
    """Variables for the concierge mail: the only set carrying a live credential, sent inline and never stored."""
    return {
        "greeting": copy_mod.greeting(lang, display_name),
        "temporary_password": temporary_password,
        "change_password_url": change_password_url(app_base_url=app_base_url),
        "created_at": copy_mod.format_moment(created_at, lang),
    }


def auth_locked_fields(*, lang: str, locked_until: Any) -> dict[str, Any]:
    """Variables for the temporary-lock notice."""
    return {
        "greeting": copy_mod.greeting(lang),
        "locked_until": copy_mod.format_moment(locked_until, lang),
    }


def _days_label(seconds: int, lang: str) -> str:
    """ "7 days" / "7 Tage" / "7 днів"."""
    days = max(1, round(seconds / 86400))
    if lang == "de":
        return f"{days} Tag" if days == 1 else f"{days} Tage"
    if lang == "uk":
        tail_two = days % 100
        tail_one = days % 10
        if 11 <= tail_two <= 14:
            word = "днів"
        elif tail_one == 1:
            word = "день"
        elif 2 <= tail_one <= 4:
            word = "дні"
        else:
            word = "днів"
        return f"{days} {word}"
    return f"{days} day" if days == 1 else f"{days} days"


def reset_secret_fields(*, app_base_url: str, token: str) -> dict[str, Any]:
    """The token-bearing half. Cleared the moment the mail is sent."""
    return {"reset_url": reset_url(app_base_url=app_base_url, token=token)}


def lockdown_secret_fields(*, app_base_url: str, token: str) -> dict[str, Any]:
    return {"lockdown_url": lockdown_url(app_base_url=app_base_url, token=token)}


def text_values(
    kind: str, lang: str, fields: dict[str, Any], secrets: dict[str, Any]
) -> dict[str, str]:
    """Flatten both halves into the ``str.format`` inputs; ``client_line`` is computed here, not stored."""
    merged: dict[str, str] = {k: str(v) for k, v in {**fields, **secrets}.items()}
    label = merged.get("client_label", "")
    unknown = set(_UNKNOWN_CLIENT.values())
    merged["client_line"] = copy_mod.client_line(lang, "" if label in unknown else label)
    return merged


_EMAIL_RE: Final = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def looks_like_email(value: str) -> bool:
    """Cheap shape check so the rate-limit key cannot be an unbounded attacker-chosen string (not validation)."""
    return bool(_EMAIL_RE.match((value or "").strip()))


# ── account notices ──────────────────────────────────────────────────


def mask_email(address: str) -> str:
    """``ada.lovelace@example.com`` → ``a***e@example.com`` (the reader may not be who made the change)."""
    local, _, domain = (address or "").partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        return f"{local[:1]}***@{domain}"
    return f"{local[0]}***{local[-1]}@{domain}"


def mfa_enabled_fields(*, lang: str, changed_at: Any) -> dict[str, Any]:
    return {
        "greeting": copy_mod.greeting(lang),
        "changed_at": copy_mod.format_moment(changed_at, lang),
    }


def mfa_disabled_fields(*, lang: str, changed_at: Any, by_admin: bool) -> dict[str, Any]:
    return {
        "greeting": copy_mod.greeting(lang),
        "changed_at": copy_mod.format_moment(changed_at, lang),
        "by_line": copy_mod.mfa_disabled_by_line(lang, by_admin=by_admin),
    }


def recovery_code_used_fields(*, lang: str, remaining: int, used_at: Any) -> dict[str, Any]:
    return {
        "greeting": copy_mod.greeting(lang),
        "remaining_label": copy_mod.recovery_remaining_label(remaining, lang),
        "used_at": copy_mod.format_moment(used_at, lang),
    }


def email_changed_fields(
    *,
    lang: str,
    new_email: str,
    revert_url: str,
    revert_ttl_seconds: int,
    changed_at: Any,
) -> dict[str, Any]:
    return {
        "greeting": copy_mod.greeting(lang),
        "new_email_masked": mask_email(new_email),
        "revert_url": revert_url,
        "revert_expiry_label": copy_mod.hours_label(revert_ttl_seconds, lang),
        "changed_at": copy_mod.format_moment(changed_at, lang),
    }


def account_deletion_fields(*, lang: str, purge_on: Any, requested_at: Any) -> dict[str, Any]:
    return {
        "greeting": copy_mod.greeting(lang),
        "purge_on": copy_mod.format_moment(purge_on, lang),
        "requested_at": copy_mod.format_moment(requested_at, lang),
    }
