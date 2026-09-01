"""choice / multi_choice extractor — the extraction-safety contract.

The negation guard and the short-token rule get the densest coverage
on purpose: a wrong auto-filled field is worse than an empty one, and
in Ukrainian the difference between "підписаний" and "не підписаний"
is one short token.
"""

from __future__ import annotations

import pytest

from nlp_service.pipeline.base import ChoiceOption
from nlp_service.stages.extractors.choice import (
    SHORT_TOKEN_EXACT_BELOW,
    _within_distance,
    choose,
    choose_multi,
    extract_choice,
    extract_multi_choice,
    match_options,
    tokenize,
)
from tests.fixtures.extraction_corpus_uk import (
    CHANNEL_CASES,
    CHANNEL_OPTIONS,
    SUBSCRIPTION_CASES,
    SUBSCRIPTION_OPTIONS,
)

THRESHOLD = 0.8


# ── the labeled corpus ──────────────────────────────────────────────


@pytest.mark.parametrize(("utterance", "expected", "why"), SUBSCRIPTION_CASES)
def test_subscription_corpus(utterance: str, expected: str | None, why: str) -> None:
    meta = extract_choice(utterance, SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
    actual = meta.selected if meta else None
    assert actual == expected, f"{why}: {utterance!r} → {actual!r}, expected {expected!r}"
    if meta is not None:
        assert meta.confidence >= THRESHOLD
        assert meta.source == "extracted"


@pytest.mark.parametrize(("utterance", "expected", "why"), CHANNEL_CASES)
def test_channel_corpus(utterance: str, expected: set[str] | None, why: str) -> None:
    meta = extract_multi_choice(utterance, CHANNEL_OPTIONS, threshold=THRESHOLD)
    actual = set(meta.selected) if meta else None
    assert actual == expected, f"{why}: {utterance!r} → {actual!r}, expected {expected!r}"


# ── negation guard (extraction safety) ──────────────────────────────


@pytest.mark.parametrize(
    "utterance",
    [
        "клієнт не підписаний",
        "клієнт не підписана",
        "не підписаний взагалі",
        "замовник ніколи не підписувався",
    ],
)
def test_negated_utterance_never_yields_current(utterance: str) -> None:
    """The single most important assertion in the suite."""
    meta = extract_choice(utterance, SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
    assert meta is None or meta.selected != "current", (
        f"{utterance!r} must never be read as an active subscription"
    )


@pytest.mark.parametrize("negator", ["не", "без", "заперечує", "немає", "no", "not", "denies"])
def test_every_negator_blocks_a_bare_alias(negator: str) -> None:
    options = (
        ChoiceOption(value="yes", label="підписаний", aliases=("підписаний",)),
        ChoiceOption(value="other", label="інше", aliases=("інше",)),
    )
    assert extract_choice(f"{negator} підписаний", options, threshold=THRESHOLD) is None


def test_negation_window_is_two_tokens() -> None:
    options = (
        ChoiceOption(value="yes", label="підписаний", aliases=("підписаний",)),
        ChoiceOption(value="other", label="інше", aliases=("інше",)),
    )
    # Inside the window → blocked.
    assert extract_choice("не зовсім підписаний", options, threshold=THRESHOLD) is None
    # Outside the window → not blocked (a distant negator is a different clause).
    assert (
        extract_choice("не має інших питань клієнт підписаний", options, threshold=THRESHOLD)
        is not None
    )


def test_phrase_carrying_its_own_negator_is_not_self_blocked() -> None:
    """ "не підписаний" as an alias must match; otherwise the negation
    guard would make negative options unfillable."""
    meta = extract_choice("клієнт не підписаний", SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
    assert meta is not None and meta.selected == "never"


# ── short-token guard ───────────────────────────────────────────────


def test_short_tokens_require_exact_match() -> None:
    """ "не" must not fuzzy-match "ні"/"на" — one edit apart, opposite
    or unrelated meaning."""
    options = (
        ChoiceOption(value="a", label="не так", aliases=("не так",)),
        ChoiceOption(value="b", label="інше", aliases=("інше",)),
    )
    assert extract_choice("ні так", options, threshold=THRESHOLD) is None
    assert extract_choice("на так", options, threshold=THRESHOLD) is None
    assert extract_choice("не так", options, threshold=THRESHOLD) is not None


@pytest.mark.parametrize(("a", "b"), [("не", "ні"), ("на", "не"), ("без", "біз"), ("рік", "ріка")])
def test_short_token_pairs_never_match(a: str, b: str) -> None:
    options = (
        ChoiceOption(value="x", label=b, aliases=(b,)),
        ChoiceOption(value="y", label="інше", aliases=("інше",)),
    )
    assert len(a) < SHORT_TOKEN_EXACT_BELOW or len(b) < SHORT_TOKEN_EXACT_BELOW
    assert extract_choice(a, options, threshold=THRESHOLD) is None


def test_long_tokens_do_tolerate_one_edit() -> None:
    options = (
        ChoiceOption(value="x", label="підписка", aliases=("підписка",)),
        ChoiceOption(value="y", label="інше", aliases=("інше",)),
    )
    assert extract_choice("підписк", options, threshold=THRESHOLD) is not None  # deletion
    assert extract_choice("підпискаа", options, threshold=THRESHOLD) is not None  # insertion
    assert extract_choice("підпіска", options, threshold=THRESHOLD) is not None  # substitution
    assert extract_choice("пдпспдп", options, threshold=THRESHOLD) is None  # too far


# ── ambiguity ───────────────────────────────────────────────────────


def test_two_options_above_threshold_yield_nothing() -> None:
    """Competing signals are not a coin flip."""
    result = choose("клієнт підписаний та не підписаний", SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
    assert result.meta is None
    assert result.outcome == "ambiguous"


def test_ambiguity_is_order_independent() -> None:
    """Determinism: reversing option order must not change the verdict."""
    text = "клієнт підписаний та не підписаний"
    forward = extract_choice(text, SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
    backward = extract_choice(text, tuple(reversed(SUBSCRIPTION_OPTIONS)), threshold=THRESHOLD)
    assert forward is None and backward is None


def test_outcome_labels_distinguish_empty_from_ambiguous() -> None:
    assert choose("нічого про це", SUBSCRIPTION_OPTIONS, threshold=THRESHOLD).outcome == "empty"
    assert (
        choose("клієнт підписаний", SUBSCRIPTION_OPTIONS, threshold=THRESHOLD).outcome == "filled"
    )


def test_overlapping_readings_are_not_ambiguity() -> None:
    """ "скасував підписку" contains a token that fuzzy-matches
    ``current``'s "підписка". Same words, two readings — the longer one
    wins; this must NOT be reported as a contradiction."""
    result = choose("скасував підписку", SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
    assert result.outcome == "filled"
    assert result.meta is not None and result.meta.selected == "former"
    assert [m.value for m in match_options("скасував підписку", SUBSCRIPTION_OPTIONS)] == ["former"]


def test_disjoint_contradiction_still_ambiguous() -> None:
    """The subsumption rule must not swallow genuine contradictions at
    different positions."""
    assert (
        choose(
            "підписаний та не підписаний окремо", SUBSCRIPTION_OPTIONS, threshold=THRESHOLD
        ).outcome
        == "ambiguous"
    )


def test_contrast_marker_cancels_negation() -> None:
    """ "каналів немає, окрім телефону" must surface the phone channel.
    Reading it as "no channels" would drop a positively named entry —
    the most dangerous error this extractor can make."""
    meta = extract_multi_choice(
        "каналів немає, окрім телефону", CHANNEL_OPTIONS, threshold=THRESHOLD
    )
    assert meta is not None and set(meta.selected) == {"phone"}


@pytest.mark.parametrize("marker", ["окрім", "крім", "але", "except", "but"])
def test_every_contrast_marker_shields_the_match(marker: str) -> None:
    options = (
        ChoiceOption(value="phone", label="телефон", aliases=("телефон",)),
        ChoiceOption(value="other", label="інше", aliases=("інше",)),
    )
    assert extract_choice(f"немає {marker} телефон", options, threshold=THRESHOLD) is not None
    # …and without the marker the negation still bites.
    assert extract_choice("немає телефон", options, threshold=THRESHOLD) is None


# ── multi_choice specifics ──────────────────────────────────────────


def test_none_known_dropped_when_a_positive_also_matches() -> None:
    meta = extract_multi_choice(
        "каналів немає, окрім телефону", CHANNEL_OPTIONS, threshold=THRESHOLD
    )
    assert meta is not None
    assert set(meta.selected) == {"phone"}


def test_none_known_survives_alone() -> None:
    meta = extract_multi_choice("канали не вказані", CHANNEL_OPTIONS, threshold=THRESHOLD)
    assert meta is not None and set(meta.selected) == {"none_known"}


def test_multi_choice_selection_is_deduped_and_deterministic() -> None:
    text = "канали телефон, телефон та смс"
    a = extract_multi_choice(text, CHANNEL_OPTIONS, threshold=THRESHOLD)
    b = extract_multi_choice(text, CHANNEL_OPTIONS, threshold=THRESHOLD)
    assert a is not None and b is not None
    assert a.selected == b.selected
    assert len(set(a.selected)) == len(a.selected)


def test_multi_choice_confidence_is_the_weakest_member() -> None:
    meta = extract_multi_choice(
        "зв'язок через імейл та телефон", CHANNEL_OPTIONS, threshold=THRESHOLD
    )
    assert meta is not None
    matches = match_options("зв'язок через імейл та телефон", CHANNEL_OPTIONS)
    weakest = min(m.confidence for m in matches if m.value in meta.selected)
    assert meta.confidence == pytest.approx(weakest)


# ── threshold behaviour ─────────────────────────────────────────────


def test_below_threshold_yields_nothing() -> None:
    options = (
        ChoiceOption(value="x", label="квартальна звітність", aliases=("квартальна звітність",)),
        ChoiceOption(value="y", label="інше", aliases=("інше",)),
    )
    # A near-miss scores below 0.99 but above 0.
    assert extract_choice("квартальна звітніст", options, threshold=0.99) is None


def test_exact_full_phrase_scores_one() -> None:
    options = (
        ChoiceOption(value="x", label="активний підписник", aliases=("активний підписник",)),
        ChoiceOption(value="y", label="інше", aliases=("інше",)),
    )
    meta = extract_choice("активний підписник", options, threshold=THRESHOLD)
    assert meta is not None and meta.confidence == 1.0


def test_longer_phrase_outranks_shorter_on_equal_tightness() -> None:
    matches = match_options("скасував підписку", SUBSCRIPTION_OPTIONS)
    assert matches[0].value == "former", [(m.value, m.confidence) for m in matches]


# ── purity / determinism ────────────────────────────────────────────


def test_repeated_calls_are_identical() -> None:
    for utterance, _, _ in SUBSCRIPTION_CASES:
        a = extract_choice(utterance, SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
        b = extract_choice(utterance, SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
        assert a == b


def test_options_are_not_mutated() -> None:
    before = tuple(SUBSCRIPTION_OPTIONS)
    extract_choice("клієнт підписаний", SUBSCRIPTION_OPTIONS, threshold=THRESHOLD)
    assert before == SUBSCRIPTION_OPTIONS


# ── helpers ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("підписка", "підписка", 0),
        ("підписка", "підписк", 1),
        ("підписка", "підпискаа", 1),
        ("підписка", "підпіска", 1),
        ("підписка", "телефони", None),
        ("а", "абвгд", None),
    ],
)
def test_within_distance(a: str, b: str, expected: int | None) -> None:
    assert _within_distance(a, b, 1) == expected


def test_tokenize_normalizes_and_splits() -> None:
    assert tokenize("Клієнт, НЕ підписаний!") == ["клієнт", "не", "підписаний"]
    assert tokenize("") == []
    assert tokenize("...") == []


def test_tokenize_keeps_apostrophes_inside_words() -> None:
    assert tokenize("п'ять років") == ["п'ять", "років"]


def test_empty_options_yield_nothing() -> None:
    assert extract_choice("клієнт підписаний", (), threshold=THRESHOLD) is None
    assert choose_multi("клієнт підписаний", (), threshold=THRESHOLD).meta is None
