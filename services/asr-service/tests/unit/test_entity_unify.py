"""Sprint TQ3 T1 — one name, one spelling: the unifier's rules.

Fixtures are spellings between neutral common words — no transcript text.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from asr_models import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_service.domain import entity_unify as eu

REPO = Path(__file__).resolve().parents[4]


def _seg(i: int, text: str) -> Segment:
    t = i * 10_000
    words = []
    for w in text.split():
        words.append(WordTiming(text=w, start_ms=t, end_ms=t + 300, probability=0.9))
        t += 400
    return Segment(text=text, start_ms=i * 10_000, end_ms=t, words=words, avg_confidence=0.9)


def _out(lines: list[str], language: str = "de") -> TranscriptionOutput:
    return TranscriptionOutput(
        language=language,
        segments=[_seg(i, line) for i, line in enumerate(lines)],
        metadata=TranscriptionMetadata(
            model="t", vad_seconds_speech=0, infer_seconds=0, beam_size=1
        ),
    )


# The r04 subject heard five ways (TQ1 reference), each between common words.
R04 = [
    "und dann Handala und",
    "und dann Handala und",
    "und dann Handala und",
    "und dann Handala und",
    "und dann Handala und",
    "und dann Handela und",
    "und dann Handela und",
    "und dann Andala und",
    "und dann Hand aller und",
    "und dann Handler und",
]


def _by_text(result: eu.PlanResult) -> dict[str, eu.Proposal]:
    return {p.to_text: p for p in result.proposals}


def test_the_r04_variants_become_one_accepted_cluster_from_the_majority() -> None:
    result = eu.plan(_out(R04), language="de")
    (p,) = result.proposals
    assert (p.to_text, p.source, p.status) == ("Handala", "majority", "accepted")
    assert p.confidence >= 0.8
    assert set(p.from_forms) == {"Handela", "Andala", "Hand aller"}
    assert "Handler" not in p.from_forms, "a common word needs a glossary or calendar source"


def test_handler_joins_only_when_the_glossary_says_so() -> None:
    result = eu.plan(_out(R04), language="de", glossary=[("Handala", ["Handler"])])
    (p,) = result.proposals
    assert (p.to_text, p.source, p.status) == ("Handala", "glossary", "accepted")
    assert set(p.from_forms) == {"Handela", "Andala", "Hand aller", "Handler"}


def test_two_attendees_who_sound_alike_are_never_merged() -> None:
    lines = ["und dann Müller und"] * 2 + ["und dann Miller und"] * 2 + ["und dann Mueller und"]
    result = eu.plan(_out(lines), language="de", attendees=["Anna Müller", "Anna Miller"])
    texts = {p.to_text for p in result.proposals}
    assert "Miller" not in {f for p in result.proposals for f in p.from_forms}
    assert "Müller" not in {f for p in result.proposals for f in p.from_forms}
    # "Mueller" is close to both: within the margin, it joins neither.
    assert texts <= {"Müller", "Miller"}


def test_a_common_word_canonical_without_a_glossary_is_proposed_not_applied() -> None:
    lines = ["und dann Bilder und"] * 4 + ["und dann Bildar und"] * 2
    result = eu.plan(_out(lines), language="de")
    for p in result.proposals:
        if p.to_text == "Bilder":
            assert p.status == "proposed"
    applied = eu.apply(
        _out(lines),
        [
            eu.Applied(p.to_text, p.from_forms, p.occurrences)
            for p in result.proposals
            if p.status == "accepted"
        ],
    )
    assert "Bildar" in " ".join(s.text for s in applied.segments)


def test_inflections_are_not_variants() -> None:
    lines = ["und dann Lagersystem und"] * 3 + ["und dann Lagersystems und"] * 2
    assert eu.plan(_out(lines), language="de").proposals == []
    uk = ["і тоді Петро і"] * 3 + ["і тоді Петра і"] * 2
    assert eu.plan(_out(uk, "uk"), language="uk").proposals == []


def test_a_role_word_is_never_a_canonical() -> None:
    lines = ["und dann Moderator und"] * 3 + ["und dann Moderater und"] * 2
    assert all(
        p.to_text.casefold() != "moderator" for p in eu.plan(_out(lines), language="de").proposals
    )


def test_numbers_are_never_touched() -> None:
    lines = ["und dann 1969 und"] * 3 + ["und dann 1968 und"] * 2
    assert eu.plan(_out(lines), language="de").proposals == []


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Олександр", "Александр"),
        ("Київ", "Киев"),
        ("Шевченко", "Шевченка"),
        ("Зеленський", "Зеленский"),
        ("Харків", "Харьков"),
    ],
)
def test_ukrainian_romanisation_keys_agree(a: str, b: str) -> None:
    assert eu.phonetic_key(a, "uk") == eu.phonetic_key(b, "uk")


def test_koelner_phonetik() -> None:
    assert eu.koelner("Müller") == eu.koelner("Mueller") == "657"
    assert eu.koelner("Handala") == eu.koelner("Andala")
    assert eu.koelner("Wikipedia") == "3412"


def test_apply_leaves_the_artefact_untouched_and_reverts_on_reject() -> None:
    out = _out(R04)
    before = hashlib.sha256(out.model_dump_json().encode()).hexdigest()
    (p,) = eu.plan(out, language="de").proposals
    applied = eu.apply(out, [eu.Applied(p.to_text, p.from_forms, p.occurrences)])
    assert hashlib.sha256(out.model_dump_json().encode()).hexdigest() == before
    text = [s.text for s in applied.segments]
    assert text[5] == "und dann Handala und" and text[8] == "und dann Handala und"
    assert applied.segments[8].words[2].text == "Handala"
    assert (applied.segments[8].words[2].start_ms, applied.segments[8].words[2].end_ms) == (
        80_800,
        81_500,
    )
    # Rejected = not passed: the original spellings come back on the next read.
    assert [s.text for s in eu.apply(out, []).segments] == [s.text for s in out.segments]


def test_an_occurrence_follows_its_word_when_segments_are_split_differently() -> None:
    out = _out(R04)
    (p,) = eu.plan(out, language="de").proposals
    # A re-label splits segment 5 in two; indices move, times do not.
    seg = out.segments[5]
    first = seg.model_copy(
        update={"words": seg.words[:2], "text": "und dann", "end_ms": seg.words[1].end_ms}
    )
    second = seg.model_copy(
        update={"words": seg.words[2:], "text": "Handela und", "start_ms": seg.words[2].start_ms}
    )
    split = out.model_copy(
        update={"segments": [*out.segments[:5], first, second, *out.segments[6:]]}
    )
    applied = eu.apply(split, [eu.Applied(p.to_text, p.from_forms, p.occurrences)])
    assert applied.segments[6].text == "Handala und"


def test_to_text_validation() -> None:
    assert eu.valid_to_text("Peter Welchering")
    assert eu.valid_to_text("O'Brien")
    assert not eu.valid_to_text("<b>x</b>")
    assert not eu.valid_to_text("x" * 81)
    assert not eu.valid_to_text("Ann\u0007a")
    assert not eu.valid_to_text("")


def test_role_words_match_the_shared_fixture() -> None:
    fixture = json.loads((REPO / "tests/fixtures/glossary/role_words.json").read_text("utf-8"))
    expected = {w for words in fixture["role_words"].values() for w in words}
    assert expected == eu.ROLE_WORDS
