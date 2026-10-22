"""The single privacy boundary (STORAGE.md §5): everything stored passes through ``redact``.

Drops keys that name content or secrets, string values longer than 256 characters, the
userinfo of URLs, and home-directory user names in paths. Schema keys that contain one of the
words but carry numbers or enums are allowed explicitly.
"""

from __future__ import annotations

import re
from typing import Any

MAX_STRING = 256
_BLOCKED_KEY = re.compile(
    r"(?i)(text|transcript|prompt|content|name|token|secret|key|password|authorization|dsn|cookie)"
)
# Schema keys that match the pattern but hold counts, enums or model ids.
ALLOWED_KEYS: frozenset[str] = frozenset(
    {
        "input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens",
        "token_source", "token_accounting_note", "generation_tokens_per_second",
        "model_name", "queue_name", "model_kind", "prompt_chars", "completion_chars",
        "prompt_version", "prompt_fingerprint", "backend_name",
    }
)  # fmt: skip
_URL_USERINFO = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)[^/@\s]+@")
_HOME = re.compile(r"(/Users/|/home/)[^/\s]+")


def redact_string(value: str) -> str | None:
    """A string fit for storage, or ``None`` when it must be dropped."""
    if len(value) > MAX_STRING:
        return None
    value = _URL_USERINFO.sub(r"\g<scheme>", value)
    return _HOME.sub(r"\1<user>", value)


def key_allowed(key: str) -> bool:
    return key in ALLOWED_KEYS or key.startswith("_") or not _BLOCKED_KEY.search(key)


def redact(obj: Any) -> Any:
    """A redacted deep copy of ``obj`` (dicts, lists, tuples, scalars). Dropped string values
    become ``None``; dropped keys disappear."""
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            k = str(key)
            if not key_allowed(k):
                continue
            out[k] = redact(value)
        return out
    if isinstance(obj, list | tuple):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return redact_string(obj)
    if obj is None or isinstance(obj, bool | int | float):
        return obj
    # Anything else (UUID, datetime, Path, enum) is stored by its string form, redacted.
    return redact_string(str(obj))
