"""PII / secret-safe logging filter: drop-list keys are deleted, mask-list keys become ``<redacted>``.

Exact key matching (substring matching would drop ``token_count``); free-form messages get only best-effort
JSON-fragment masking; recursion is capped at 10.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Drop list: values are removed entirely.
_DROP_NAMES: frozenset[str] = frozenset(
    {
        # Authentication / authorization
        "password",
        "passwd",
        "secret",
        "client_secret",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "cookie",
        "set-cookie",
        "session",
        "session_id",
        "session_token",
        "csrf_token",
        # Signup / verification
        "verify_url",
        "verification_code",
        "otp_code",
        # MFA / recovery
        "mfa_secret",
        "totp_secret",
        "recovery_code",
        "recovery_codes",
        "backup_codes",
        # Cryptographic material
        "private_key",
        "privatekey",
        "encryption_key",
        "kek",
        "dek",
        # User content (raw)
        "audio",
        "audio_data",
        "audio_content",
        "audio_bytes",
        "pcm",
        "transcript",
        "transcript_text",
        "transcription",
        "note",
        "note_body",
        # Speaker names are content
        "speaker_names",
        "name_candidates",
        "speaker_name_candidates",
        "local_speaker_name",
        # Invite context and the author's own notes are content too
        "attendee_names",
        "agenda_lines",
        "calendar_context",
        "user_notes",
        "my_notes",
        # Generic body / payload
        "body",
        "payload",
        "request_body",
        "response_body",
    }
)

# Mask list: values replaced with <redacted>.
_MASK_NAMES: frozenset[str] = frozenset(
    {
        # Generic PII
        "email",
        "email_address",
        "phone",
        "phone_number",
        "msisdn",
        "dob",
        "date_of_birth",
        "first_name",
        "last_name",
        "full_name",
        "address",
        "street_address",
        "ssn",
        "ipn",  # Ukrainian individual tax ID
        "drfo",  # Ukrainian state register identifier
        "passport_number",
    }
)

# Regex to redact JSON-style fragments inside string messages.
_JSON_FIELD_NAMES = sorted(_DROP_NAMES | _MASK_NAMES)
_JSON_PATTERN: re.Pattern[str] = re.compile(
    r'("(?:' + "|".join(re.escape(n) for n in _JSON_FIELD_NAMES) + r')"\s*:\s*)"(?:[^"\\]|\\.)*"',
    re.IGNORECASE,
)

# Value patterns, redacted whatever the field is called. Reserved for shapes that cannot occur
# legitimately in a log line (a pattern for something people type would redact real content).
_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # mdx_sk_<8 hex>_<43 url-safe chars> — see auth_service.domain.credentials
    re.compile(r"mdx_sk_[A-Za-z0-9]{4,16}_[A-Za-z0-9_\-]{20,}"),
)

_MASK_VALUE = "<redacted>"
_MAX_DEPTH = 10


def redact_values(text: str) -> str:
    """Mask any known secret shape inside a string."""
    for pattern in _VALUE_PATTERNS:
        text = pattern.sub(_MASK_VALUE, text)
    return text


def _classify(name: str) -> str:
    """Return ``'drop'``, ``'mask'`` or ``'keep'`` for ``name``."""
    lname = name.lower()
    if lname in _DROP_NAMES:
        return "drop"
    if lname in _MASK_NAMES:
        return "mask"
    return "keep"


def scrub(value: Any, depth: int = 0) -> Any:
    """Return a copy of ``value`` with PII / secrets removed or masked (pure; also used by structlog processors)."""
    if depth >= _MAX_DEPTH:
        return value
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                out[k] = scrub(v, depth + 1)
                continue
            verdict = _classify(k)
            if verdict == "drop":
                continue
            if verdict == "mask":
                out[k] = _MASK_VALUE
                continue
            out[k] = scrub(v, depth + 1)
        return out
    if isinstance(value, list):
        return [scrub(v, depth + 1) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub(v, depth + 1) for v in value)
    if isinstance(value, str):
        return redact_values(value)
    return value


def scrub_event_dict(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor adapter for ``scrub``."""
    return scrub(event_dict)  # type: ignore[no-any-return]


class PIISafeFilter(logging.Filter):
    """stdlib-logging filter that scrubs the log record before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        for attr, value in list(vars(record).items()):
            if attr.startswith("_") or attr in _STDLIB_RECORD_ATTRS:
                continue
            if not isinstance(attr, str):
                continue
            verdict = _classify(attr)
            if verdict == "drop":
                delattr(record, attr)
                continue
            if verdict == "mask":
                setattr(record, attr, _MASK_VALUE)
                continue
            if isinstance(value, (dict, list, tuple)):
                setattr(record, attr, scrub(value))

        if isinstance(record.args, dict):
            record.args = scrub(record.args)

        if isinstance(record.msg, str):
            record.msg = _JSON_PATTERN.sub(r'\1"<redacted>"', record.msg)

        return True


_STDLIB_RECORD_ATTRS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)
