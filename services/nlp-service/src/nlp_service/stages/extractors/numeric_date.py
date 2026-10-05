"""numeric_with_unit / date binders: pick from normalizer artifacts, never re-parse.

Several candidates and no way to choose ⇒ empty field, prose preserved.
"""

from __future__ import annotations

from typing import Final

from note_models import DateMeta, NumericMeta

from ...pipeline.base import DateArtifact, NumericArtifact, TemplateSection
from .choice import tokenize

# Confidence constants (ADR-0032). LABELLED is above the 0.8 threshold (a
# section label sat next to the value); SOLE sits exactly at it so a clean
# single-measurement section binds.
LABELLED_CONFIDENCE: Final = 0.9
SOLE_CONFIDENCE: Final = 0.8
DATE_CONFIDENCE: Final = 0.9

# Tokens around a value scanned for the section's label.
LABEL_WINDOW: Final = 4


def _label_tokens(section: TemplateSection) -> set[str]:
    """The words that would mark a value as belonging to this section."""
    tokens: set[str] = set(tokenize(section.name))
    for alias in section.aliases:
        tokens.update(tokenize(alias))
    # Very short tokens are noise as labels.
    return {t for t in tokens if len(t) >= 4}


def _label_distance(text: str, artifact: NumericArtifact, labels: set[str]) -> int | None:
    """Token distance to the nearest section label (nearest wins; an exact tie stays ambiguous)."""
    if not labels:
        return None
    tokens = tokenize(text)
    value_tokens = tokenize(artifact.value)
    if not value_tokens:
        return None
    positions = [i for i, t in enumerate(tokens) if t == value_tokens[0]]
    if not positions:
        return None
    best: int | None = None
    for position in positions:
        for index, token in enumerate(tokens):
            if index == position or token not in labels:
                continue
            distance = abs(index - position)
            if distance <= LABEL_WINDOW and (best is None or distance < best):
                best = distance
    return best


def bind_numeric(
    text: str,
    artifacts: tuple[NumericArtifact, ...],
    section: TemplateSection,
    *,
    threshold: float,
) -> NumericMeta | None:
    """Bind one measurement to a ``numeric_with_unit`` section.

    Labelled nearby ⇒ LABELLED_CONFIDENCE; exactly one unit-bearing value ⇒
    SOLE_CONFIDENCE; several unlabelled or no unit ⇒ empty (never guess a unit).
    """
    with_units = [a for a in artifacts if a.unit]
    if not with_units:
        return None

    labels = _label_tokens(section)
    scored = [(a, _label_distance(text, a, labels)) for a in with_units]
    labelled = sorted(((a, d) for a, d in scored if d is not None), key=lambda pair: pair[1])

    if labelled and (len(labelled) == 1 or labelled[0][1] < labelled[1][1]):
        chosen, confidence = labelled[0][0], LABELLED_CONFIDENCE
    elif labelled:
        return None  # two labels equidistant — genuinely ambiguous
    elif len(with_units) == 1:
        chosen, confidence = with_units[0], SOLE_CONFIDENCE
    else:
        return None  # several unlabelled candidates

    if confidence < threshold:
        return None
    return NumericMeta(
        value=float(chosen.value.replace(",", ".")),
        unit=chosen.unit,
        confidence=confidence,
        source="extracted",
    )


def bind_date(
    artifacts: tuple[DateArtifact, ...],
    *,
    threshold: float,
) -> DateMeta | None:
    """Bind one ISO date to a ``date`` / ``date_with_note`` section; several dates ⇒ empty."""
    if len(artifacts) != 1:
        return None
    if threshold > DATE_CONFIDENCE:
        return None
    return DateMeta(
        date=artifacts[0].iso,
        confidence=DATE_CONFIDENCE,
        source="extracted",
    )
