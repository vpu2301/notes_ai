"""Best-effort PII redaction for search snippets.

Note content sometimes carries personal identifiers in section bodies
(full names, national id numbers, birth dates). When a snippet is
returned to a user who is NOT an author of the note, redact these
patterns. When the viewer is primary_author / co_author, return
unredacted.

The redactor is intentionally conservative: it is the second line of
defence behind the role check.
"""

from __future__ import annotations

import re
from typing import Final

# 10-digit national id / tax number.
_NATIONAL_ID_RE: Final = re.compile(r"\b\d{10}\b")
# Three-word capitalised full-name pattern (uk/en).
_FULL_NAME_RE: Final = re.compile(
    r"\b([А-ЩЬЮЯҐЄІЇA-Z][а-щьюяґєіїa-z]{1,})\s+"
    r"([А-ЩЬЮЯҐЄІЇA-Z][а-щьюяґєіїa-z]{1,})\s+"
    r"([А-ЩЬЮЯҐЄІЇA-Z][а-щьюяґєіїa-z]{1,})\b",
    re.UNICODE,
)
# ISO date or "12.05.1980" style — only redact full-year dates that look
# like birthdates. Best-effort.
_DOB_LIKE_RE: Final = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{4}\b")


def redact_snippet(text: str) -> str:
    text = _NATIONAL_ID_RE.sub("[redacted-id]", text)
    text = _FULL_NAME_RE.sub("[redacted-name]", text)
    text = _DOB_LIKE_RE.sub("[redacted-date]", text)
    return text


def is_author_team(
    *, viewer_user_id, primary_author_id, co_author_ids, viewer_roles: list[str]
) -> bool:
    """Author-team check used to bypass snippet redaction.

    Only the note's authors see unredacted snippets — a role-wide
    redaction bypass would hand a whole tenant's personal data to
    anyone holding that role, which is the exact thing the check
    exists to prevent.
    """
    if viewer_user_id == primary_author_id:
        return True
    return viewer_user_id in (co_author_ids or [])
