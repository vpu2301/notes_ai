"""Name suggestions (Sprint 32 B-1): patterns per language + the rules
that keep them precise. Table-driven; no service, no network."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

from asr_service.domain.name_patterns import find_introductions
from asr_service.domain.name_suggestions import suggest

# ── Patterns ──────────────────────────────────────────────────────────

POSITIVES = [
    ("en", "Hi, this is Anna from Acme.", "Anna"),
    ("en", "Hello everyone, my name is Tom Berg and I lead sales.", "Tom Berg"),
    ("en", "I'm Olena, product.", "Olena"),
    ("en", "Good morning, Anna here.", "Anna"),
    ("en", "Mark speaking, can you hear me?", "Mark"),
    ("de", "Hallo, hier ist Jürgen vom Vertrieb.", "Jürgen"),
    ("de", "Ich bin Anna Keller aus Berlin.", "Anna Keller"),
    ("de", "Mein Name ist Özlem.", "Özlem"),
    ("de", "Guten Morgen, Stefan hier.", "Stefan"),
    ("uk", "Привіт, це Олена з маркетингу.", "Олена"),
    ("uk", "Мене звати Тарас Шевчук.", "Тарас Шевчук"),
    ("uk", "Добрий день, Ірина на зв'язку.", "Ірина"),
]

NEGATIVES = [
    ("en", "This is great, thanks."),
    ("en", "I'm sorry, I'm back now."),
    ("en", "It's Monday again."),
    ("en", "this is the plan we agreed on"),
    ("en", "I am happy with that."),
    ("de", "Ich bin müde."),
    ("de", "Ich bin gleich wieder da."),
    ("de", "Hier ist das Dokument."),
    ("uk", "Це добре."),
    ("uk", "Я тут."),
    ("uk", "Я вже готовий."),
]


@pytest.mark.parametrize(("lang", "text", "name"), POSITIVES)
def test_self_introductions_are_found(lang: str, text: str, name: str) -> None:
    assert name in [i.name for i in find_introductions(text, lang)]


@pytest.mark.parametrize(("lang", "text"), NEGATIVES)
def test_non_introductions_propose_nothing(lang: str, text: str) -> None:
    assert find_introductions(text, lang) == []


def test_an_unsupported_language_proposes_nothing() -> None:
    assert find_introductions("Je suis Anna.", "fr") == []


@pytest.mark.parametrize("lang", ["en", "de", "uk"])
def test_adversarial_text_is_fast(lang: str) -> None:
    """10 kB built to make a naive pattern backtrack: < 50 ms."""
    nasty = ("this is " + "Aaaa " * 2000 + "!") + ("ich bin " + "B-b'b " * 400) + "я " * 500

    t0 = time.perf_counter()
    find_introductions(nasty[:10_000], lang)
    assert time.perf_counter() - t0 < 0.05


# ── Suggestions ───────────────────────────────────────────────────────


@dataclass
class Turn:
    speaker: str | None
    text: str
    start_ms: int = 0
    end_ms: int = 5_000
    segment_indices: list[int] = field(default_factory=lambda: [0])

    @property
    def paragraphs(self) -> list[str]:
        return [self.text]


def _turns() -> list[Turn]:
    return [
        Turn("SPEAKER_1", "Okay, let's start.", 0, 5_000, [0]),
        Turn("SPEAKER_2", "Hi, this is Anna from Acme.", 14_000, 16_200, [1, 2]),
        Turn("SPEAKER_1", "Welcome, Anna.", 16_300, 17_000, [3]),
    ]


def test_an_introduction_matching_one_invitee_is_suggested_in_calendar_spelling() -> None:
    [s] = suggest(_turns(), language="en", candidates=["Anna Keller", "Tom Berg"], custom_names={})

    assert (s.label, s.name, s.source) == ("SPEAKER_2", "Anna Keller", "self_introduction")
    assert s.quote == "Hi, this is Anna from Acme."
    assert (s.start_ms, s.end_ms, s.segment_indices) == (14_000, 16_200, [1, 2])


def test_no_invitee_list_means_no_suggestions() -> None:
    assert suggest(_turns(), language="en", candidates=[], custom_names={}) == []


def test_a_name_not_among_the_invitees_is_not_suggested() -> None:
    assert suggest(_turns(), language="en", candidates=["Tom Berg"], custom_names={}) == []


def test_a_first_name_shared_by_two_invitees_is_not_suggested() -> None:
    assert (
        suggest(_turns(), language="en", candidates=["Anna Keller", "Anna Weber"], custom_names={})
        == []
    )


def test_two_speakers_claiming_one_invitee_get_nothing() -> None:
    turns = [*_turns(), Turn("SPEAKER_3", "And I'm Anna too.", 20_000, 21_000, [4])]

    assert suggest(turns, language="en", candidates=["Anna Keller"], custom_names={}) == []


def test_one_speaker_matching_two_invitees_gets_nothing() -> None:
    turns = [Turn("SPEAKER_2", "This is Anna. Well, this is Tom actually.", 0, 3_000, [0])]

    assert (
        suggest(turns, language="en", candidates=["Anna Keller", "Tom Berg"], custom_names={}) == []
    )


def test_named_speakers_used_names_and_dismissed_pairs_are_skipped() -> None:
    cands = ["Anna Keller", "Tom Berg"]

    assert (
        suggest(_turns(), language="en", candidates=cands, custom_names={"SPEAKER_2": "A."}) == []
    )
    assert (
        suggest(
            _turns(), language="en", candidates=cands, custom_names={"SPEAKER_1": "anna keller"}
        )
        == []
    )
    assert (
        suggest(
            _turns(),
            language="en",
            candidates=cands,
            custom_names={},
            dismissed=[("SPEAKER_2", "Anna Keller")],
        )
        == []
    )


def test_late_turns_past_the_first_two_are_not_scanned() -> None:
    turns = [
        Turn("SPEAKER_2", "Yes.", 0, 1_000, [0]),
        Turn("SPEAKER_2", "Right.", 2_000, 3_000, [1]),
        Turn("SPEAKER_2", "By the way, this is Anna.", 600_000, 601_000, [2]),
    ]

    assert suggest(turns, language="en", candidates=["Anna Keller"], custom_names={}) == []


def test_quotes_are_capped_at_160_characters_on_word_boundaries() -> None:
    long = "blah " * 60 + "this is Anna " + "and more words " * 30
    [s] = suggest(
        [Turn("SPEAKER_2", long, 0, 1, [0])], language="en", candidates=["Anna"], custom_names={}
    )

    assert len(s.quote) <= 160
    assert "Anna" in s.quote
    assert not s.quote.startswith(" ")


def test_german_and_ukrainian_suggestions() -> None:
    de = [Turn("SPEAKER_1", "Guten Tag, hier ist Jürgen.", 0, 1, [0])]
    uk = [Turn("SPEAKER_1", "Привіт, це Олена.", 0, 1, [0])]

    assert (
        suggest(de, language="de", candidates=["Jürgen Maier"], custom_names={})[0].name
        == "Jürgen Maier"
    )
    assert (
        suggest(uk, language="uk", candidates=["Олена Коваль"], custom_names={})[0].name
        == "Олена Коваль"
    )


# ── Review findings (Sprint 32) ───────────────────────────────────────


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("en", "Okay, is Anna here?"),
        ("en", "Let's wait, Anna speaking next."),
        ("de", "Weißt du, ob Anna hier ist?"),
        ("uk", "Його ім'я Олена."),
        ("uk", "Його імʼя Олена."),
    ],
)
def test_mentions_of_someone_else_are_not_introductions(lang: str, text: str) -> None:
    assert find_introductions(text, lang) == []


def test_apostrophe_variants_match_the_calendar_spelling() -> None:
    turns = [Turn("SPEAKER_1", "Привіт, це Дарʼя.", 0, 1, [0])]

    [s] = suggest(turns, language="uk", candidates=["Дар'я Коваленко"], custom_names={})
    assert s.name == "Дар'я Коваленко"


def test_first_name_uniqueness_counts_invitees_already_named() -> None:
    """Anna Keller already named; a second label saying "I'm Anna" could be
    an over-split Anna Keller — never offer Anna Schmidt."""
    turns = [Turn("SPEAKER_2", "I'm Anna.", 0, 1, [0])]

    assert (
        suggest(
            turns,
            language="en",
            candidates=["Anna Keller", "Anna Schmidt"],
            custom_names={"SPEAKER_1": "Anna Keller"},
        )
        == []
    )
    assert (
        suggest(
            turns,
            language="en",
            candidates=["Anna Keller"],
            custom_names={"SPEAKER_1": "Anna"},
        )
        == []
    ), "a typed first name takes that invitee"


def test_a_label_matching_two_invitees_still_claims_both() -> None:
    turns = [
        Turn("SPEAKER_1", "This is Anna. Well, this is Bob.", 0, 1, [0]),
        Turn("SPEAKER_2", "Hi, I'm Anna.", 2_000, 3_000, [1]),
    ]

    assert (
        suggest(turns, language="en", candidates=["Anna Keller", "Bob Stone"], custom_names={})
        == []
    )


# ── Sprint F3: what the person said they do ─────────────────────────


@pytest.mark.parametrize(
    ("text", "language", "name", "role"),
    [
        (
            "Thank you for watching. My name is Mitchell. I am a broker with Springbrook "
            "Marine Group, the Pardo dealer.",
            "en",
            "Mitchell",
            "I am a broker with Springbrook Marine Group, the Pardo dealer",
        ),
        ("Hi, I'm Anna from sales.", "en", "Anna", "from sales"),
        ("Hallo, ich bin Jonas von Acme.", "de", "Jonas", "von Acme"),
        ("Мене звати Олена, я з відділу продажів.", "uk", "Олена", "я з відділу продажів"),
        ("This is Tom.", "en", "Tom", None),
    ],
)
def test_the_role_clause_after_an_introduction_is_kept_verbatim(
    text: str, language: str, name: str, role: str | None
) -> None:
    from asr_service.domain.name_patterns import find_introductions

    [intro] = find_introductions(text, language)
    assert intro.name == name and intro.role_text == role
    if role is not None:
        assert role in text  # nothing inferred: a substring of what was said


def test_a_suggestion_carries_the_role_clause() -> None:
    turn = type(
        "T",
        (),
        {
            "speaker": "SPEAKER_1",
            "paragraphs": ["Hi everyone, I'm Anna from the sales team."],
            "start_ms": 0,
            "end_ms": 4_000,
            "segment_indices": [0],
        },
    )()
    [s] = suggest([turn], language="en", candidates=["Anna Keller"], custom_names={})
    assert s.role_text == "from the sales team"
