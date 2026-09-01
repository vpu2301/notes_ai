"""Output safety filter — completions are linguistic, never factual.

Sprint-15 rule: a completion may finish a sentence's grammar; it may
NOT supply a budget figure. Every money amount, percentage, date-like
fragment or bare number in the completion must appear VERBATIM in the
text the author already typed, otherwise the completion is dropped
(the endpoint answers 204 and audits ``layer_c.completion.filtered``).

Same regex-sweep family as the nlp-service numeric artifacts: match
classes are enumerated so the filter can report WHICH class fired
(metric label), and the catch-all bare-number pattern runs last so a
"$1,234.56" is reported as money, not as two bare numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# Order matters: specific classes first; `bare_number` is the catch-all.
# Amount: digit run with optional thousands groups (space/NBSP/comma/dot)
# and an optional decimal part — covers 1,234.56 / 1 200 / 1200.50.
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
            # A fragment already attributed to a more specific class (e.g. the
            # "1,234" inside an approved "$1,234.56") is not re-judged as a
            # bare number.
            if any(span[0] >= s and span[1] <= e for s, e in consumed):
                continue
            if match.group(0) not in text_before_cursor:
                return FilterVerdict(allowed=False, reason=reason, matched=match.group(0))
            consumed.append(span)
    return FilterVerdict(allowed=True)
