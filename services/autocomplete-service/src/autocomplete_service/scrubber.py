"""PII scrubber for telemetry prefixes + phrase writes.

Scrub-before-store: telemetry rows are scrubbed BEFORE the buffer
accepts them, so raw prefixes never touch disk. Conservative: false
positives (over-scrubbing) are preferred over false negatives (PII
leak into telemetry).

Patterns redacted (generic — no locale-specific ID formats):
- Email (RFC-5322-lite).
- Credit-card-like sequences: 13-19 digits, optionally grouped by
  single spaces/dashes ("4111 1111 1111 1111").
- National-ID-like patterns: a standalone 1-3 letter prefix + 6-9
  digits (passport / ID-card shaped, any country).
- Phone numbers: "+" followed by 7-15 digits, or 3+ separator-broken
  digit groups ("050 123 45 67", "(044) 123-45-67").
- Long digit runs: any unbroken run of 7+ digits (covers unformatted
  phones, tax numbers, account numbers).

Known limitations: date-shaped strings with 2+-digit components
("01.02.2026") are eaten by the phone pattern — accepted over-scrub;
digit pairs like "2026 2027" (two groups only) are NOT caught.

Replacement: ``<redacted_PII>``.

Pattern set documented in ``docs/security/autocomplete-pii-scrubber.md``;
regex updates require privacy re-review.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

REDACTED: Final = "<redacted_PII>"

# Order matters: more-specific patterns first so they win the
# substitution (and keep the redaction counts attributed) before the
# generic digit_run sweep eats them.
_PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    # 13-19 digits, optional single space/dash between digits — catches
    # both "4111111111111111" and "4111 1111 1111 1111".
    ("card_like", re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?!\d)")),
    # Standalone 1-3 letter token + 6-9 digits ("AB 123456", "ABC1234567").
    # The \b keeps it from firing inside ordinary words.
    ("national_id", re.compile(r"\b[A-Za-z]{1,3}\s?\d{6,9}\b")),
    # "+" international form, or 3+ separator-broken groups. Contiguous
    # local numbers without "+" fall through to digit_run below.
    (
        "phone",
        re.compile(r"(?<![\d+])(?:\+\d{7,15}|\+?\(?\d{1,4}\)?(?:[ .-]\d{2,4}){2,5})(?!\d)"),
    ),
    # Catch-all: any unbroken run of 7+ digits (phones, tax/account
    # numbers, government IDs of any length).
    ("digit_run", re.compile(r"(?<!\d)\d{7,}(?!\d)")),
]


@dataclass(frozen=True, slots=True)
class ScrubResult:
    text: str
    redactions: dict[str, int]  # pattern_name → count


def scrub_prefix(text: str) -> ScrubResult:
    """Return (scrubbed_text, per-pattern redaction counts)."""
    counts: dict[str, int] = {}
    for name, pat in _PATTERNS:
        new_text, n = pat.subn(REDACTED, text)
        if n:
            counts[name] = n
            text = new_text
    return ScrubResult(text=text, redactions=counts)


def scrub_context(ctx: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in ctx.items():
        if isinstance(v, str):
            out[k] = scrub_prefix(v).text
        elif isinstance(v, Mapping):
            out[k] = scrub_context(v)
        else:
            out[k] = v
    return out


def contains_pii(text: str) -> list[str]:
    """Lightweight detector used by phrase-write rejection.

    Returns the list of pattern names that match (empty = clean).
    """
    found: list[str] = []
    for name, pat in _PATTERNS:
        if pat.search(text):
            found.append(name)
    return found
