"""Structured artifacts the normalizer stages report about their own output.

Read with the normalizer's own canonical vocabulary so the binder never
re-derives numerals or dates (a test asserts it carries no vocabulary).
"""

from __future__ import annotations

import re
from typing import Final

from ..pipeline.base import DateArtifact, NumericArtifact

# ``YYYY-MM-DD`` — the only date form the date normalizer emits.
_ISO_DATE_RE: Final = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def numeric_artifacts_from_output(
    normalized_text: str,
    *,
    decimal_separator: str,
    canonical_units: frozenset[str],
) -> tuple[NumericArtifact, ...]:
    """Measurements the number normalizer wrote: digits optionally followed by a canonical unit."""
    tokens = normalized_text.split()
    # Longest first so multi-token units match before their prefixes.
    units_by_len = sorted(canonical_units, key=lambda u: -len(u.split()))

    number_re = re.compile(rf"^\d+(?:{re.escape(decimal_separator)}\d+)?$")
    artifacts: list[NumericArtifact] = []
    for index, token in enumerate(tokens):
        stripped = token.rstrip(",;:.")
        if not number_re.match(stripped):
            continue
        unit = ""
        rendered = stripped
        remainder = " ".join(tokens[index + 1 :])
        for candidate in units_by_len:
            if remainder == candidate or remainder.startswith(candidate + " "):
                unit = candidate
                rendered = f"{stripped} {candidate}"
                break
        artifacts.append(
            NumericArtifact(
                value=stripped,
                unit=unit,
                rendered=rendered,
                token_index=index,
            )
        )
    return tuple(artifacts)


def date_artifacts_from_output(normalized_text: str) -> tuple[DateArtifact, ...]:
    """ISO dates the date normalizer wrote; never resolves anything itself."""
    return tuple(
        DateArtifact(iso=match.group(1), char_index=match.start())
        for match in _ISO_DATE_RE.finditer(normalized_text)
    )
