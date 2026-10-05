"""Output safety filter: completions are linguistic, never factual.

Every money amount, percentage, date-like fragment or bare number in the completion
must appear verbatim in the typed text, otherwise the completion is dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# Order matters: specific classes first; `bare_number` is the catch-all.
# Digit run with optional thousands groups (space/NBSP/comma/dot) and decimals.
_AMOUNT = "\\d+(?:[ \u00a0,.]\\d{3})*(?:[.,]\\d+)?"
# Scale suffix: $1.2M, €50k, 3 млн грн.
_SCALE = r"(?:\s?(?:[kmb]|тис|млн|млрд)\.?)?"
_CURRENCY_SYM = r"[$€£₴]"
_CURRENCY_CODE = r"(?:USD|EUR|GBP|UAH|PLN|CHF|грн)"
_PATTERNS: Final[list[tuple[str, re.Pattern[str]]]] = [
    (
        "money",
        re.compile(
            rf"(?:{_CURRENCY_SYM}\s?{_AMOUNT}{_SCALE}"
            rf"|{_AMOUNT}{_SCALE}\s?(?:{_CURRENCY_CODE}\b|{_CURRENCY_SYM}))",
            re.IGNORECASE,
        ),
    ),
    (
        "percent",
        re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|percent\b|відсотк\w*|проц\w*)", re.IGNORECASE),
    ),
    ("date_like", re.compile(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b")),
    ("bare_number", re.compile(r"\d+(?:[.,]\d+)?")),
]


@dataclass(slots=True, frozen=True)
class FilterVerdict:
    allowed: bool
    reason: str | None = None  # pattern class that fired, for the metric label
    matched: str | None = None  # offending fragment (audit payload — closed class)


def check_completion(completion: str, *, text_before_cursor: str) -> FilterVerdict:
    """Every risky-value match in ``completion`` must be a verbatim
    substring of ``text_before_cursor`` — echoing back what the author
    already wrote is legitimate grammar; introducing anything numeric is not.
    """
    consumed: list[tuple[int, int]] = []
    for reason, pattern in _PATTERNS:
        for match in pattern.finditer(completion):
            span = match.span()
            # Already attributed to a more specific class.
            if any(span[0] >= s and span[1] <= e for s, e in consumed):
                continue
            if match.group(0) not in text_before_cursor:
                return FilterVerdict(allowed=False, reason=reason, matched=match.group(0))
            consumed.append(span)
    return FilterVerdict(allowed=True)
