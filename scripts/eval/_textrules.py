"""Text rules the notes scorer kept when Sprint R0 removed the writing path: how a quote
is compared, what a copied line is, when a line carries information. Eval only; the
service never imports this module.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from typing import Final

_ENGINE_SRC = Path(__file__).resolve().parents[2] / "services" / "note-service" / "src"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))

from note_service.domain import text as text_rules  # noqa: E402
from note_service.domain.action_items import _MONTHS, _RELATIVE, _WEEKDAYS  # noqa: E402

_PUNCT = re.compile(r"[^\w\s']", re.UNICODE)
_SPACE = re.compile(r"\s+")
_QUOTE_EDGE = "'\"“”„«».,;:!?"
FILLERS: Final[frozenset[str]] = frozenset(
    {
        "uh",
        "um",
        "erm",
        "er",
        "hmm",
        "hm",
        "mm",
        "mhm",
        "ah",
        "eh",
        "uh-huh",
        "äh",
        "ähm",
        "öh",
        "öhm",
        "mh",
        "е",
        "ем",
        "мм",
        "ммм",
        "хм",
        "е-е",
        "а-а",
    }
)


def normalise_quote(text: str) -> str:
    """Comparison form: NFKC, case-folded, punctuation dropped (apostrophes kept),
    fillers dropped, whitespace collapsed."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = folded.replace("’", "'").replace("‘", "'")
    kept = [tok for tok in _SPACE.split(folded) if tok.strip(_QUOTE_EDGE) not in FILLERS]
    tokens = _PUNCT.sub(" ", " ".join(kept)).split()
    return " ".join(tok for tok in tokens if tok not in FILLERS)


_TURN_HEADER: Final = re.compile(
    r"^\s*(?:\[\d*\]:?\s*[^\[\]():\n]{0,80}?\s*\(\d{0,2}:?\d{0,2}\)"
    r"|[^\[\]():\n]{1,40}?\s*\(\d{1,2}:\d{2}\)):\s*"
)


def strip_turn_header(text: str) -> str:
    """A line without an echoed transcript turn header."""
    return _TURN_HEADER.sub("", text, count=1).strip()


_SENTENCE: Final = re.compile(r"(?<=[.!?…])\s+")


def is_copied(text: str, quote: str) -> bool:
    """``text`` is the quote (or nearly all of it, or one of its sentences)."""
    claim = normalise_quote(text)
    if not claim:
        return False
    quote = strip_turn_header(quote)
    for part in (quote, *_SENTENCE.split(quote)):
        said = normalise_quote(part)
        if said and (claim == said or (claim in said and len(claim) >= 0.8 * len(said))):
            return True
    return False


NUMBER: Final = re.compile(r"\d[\d.,]*")
_DATE_WORDS: Final[frozenset[str]] = frozenset({*_MONTHS, *_WEEKDAYS, *_RELATIVE})


def has_date_word(text: str) -> bool:
    return any(w in _DATE_WORDS for w in normalise_quote(text).split())


# ── Does a line carry information ──────────────────────────────────

EVALUATIVE: Final[dict[str, frozenset[str]]] = {
    "en": frozenset(
        {
            "incredible",
            "amazing",
            "great",
            "nice",
            "impressive",
            "awesome",
            "cool",
            "interesting",
            "beautiful",
            "fantastic",
            "wonderful",
            "lovely",
            "stunning",
            "gorgeous",
            "perfect",
            "good",
            "excellent",
            "brilliant",
        }
    ),
    "de": frozenset(
        {
            "toll",
            "super",
            "beeindruckend",
            "spannend",
            "schön",
            "schöne",
            "schönes",
            "großartig",
            "fantastisch",
            "wunderbar",
            "klasse",
            "genial",
            "gut",
        }
    ),
    "uk": frozenset(
        {
            "чудовий",
            "чудова",
            "чудове",
            "круто",
            "крутий",
            "цікаво",
            "цікавий",
            "класно",
            "класний",
            "неймовірний",
            "неймовірно",
            "прекрасний",
            "гарний",
            "гарно",
            "супер",
        }
    ),
}
# Talk that fills time: never content, whatever the language of the line.
FILLER: Final[frozenset[str]] = frozenset(
    {
        "really",
        "actually",
        "basically",
        "literally",
        "like",
        "okay",
        "ok",
        "right",
        "yeah",
        "yes",
        "well",
        "um",
        "uh",
        "oh",
        "wow",
        "here",
        "there",
        "thing",
        "things",
        "stuff",
        "guys",
        "kind",
        "sort",
        "lot",
        "bit",
        "little",
        "again",
        "one",
        "ones",
        "halt",
        "eben",
        "genau",
        "echt",
        "wirklich",
        "sozusagen",
        "quasi",
        "ну",
        "от",
        "типу",
        "короче",
        "власне",
        "ось",
        "тут",
        "там",
        # the tails of "I'll", "we've", "they're" once the apostrophe splits them
        "ll",
        "ve",
        "re",
    }
)
# Below this many information tokens a line is chatter (tasks, decisions, numbers, names, dates exempt).
MIN_INFORMATION: Final = 4

_DIGITS: Final = re.compile(r"\d")


def information_tokens(text: str, language: str) -> list[str]:
    """The tokens that inform: numbers, names, and content words that are not function words, filler or judgement."""
    body = text_rules.body(text)
    names = {n.casefold() for n in text_rules.names_in(body)}
    stops = text_rules.stop_words(language) | text_rules.MERGE_STOP | FILLER
    judging = EVALUATIVE.get(language, frozenset()) | EVALUATIVE["en"]
    out: list[str] = []
    for word in text_rules._WORD.findall(text_rules.casefold(body)):
        if (
            _DIGITS.search(word)
            or word in names
            or len(word) > 1
            and word not in stops
            and word not in judging
        ):
            out.append(word)
    return out


def information_score(text: str, language: str) -> int:
    return len(information_tokens(text, language))


def carries_information(
    text: str, language: str, *, short_ok: bool = False, has_date: bool = False
) -> bool:
    """False for a ``no_information`` line: nothing informs, or it is short and
    judges ("This boat is incredible."). A short line that states something stays
    (the bare floor cost recall); ``short_ok`` kinds and lines with a number, name
    or date are never too short."""
    tokens = information_tokens(text, language)
    if not tokens:
        return False
    if len(tokens) >= MIN_INFORMATION or short_ok or has_date:
        return True
    body = text_rules.body(text)
    if _DIGITS.search(body) or text_rules.names_in(body):
        return True
    judging = EVALUATIVE.get(language, frozenset()) | EVALUATIVE["en"]
    return not any(w in judging for w in text_rules._WORD.findall(text_rules.casefold(body)))


# The speaker's own voice: at the start, or an unmistakable contraction anywhere.


# The recording-type labels the overview opened with (the ``p1_not_label`` assertion).
TYPE_LABELS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "meeting": "Meeting",
        "client_call": "Client call",
        "sales_call": "Sales call",
        "interview": "Interview",
        "one_on_one": "One-on-one",
        "podcast_broadcast": "Broadcast",
        "lecture_webinar": "Talk",
        "voice_memo": "Voice memo",
        "presentation_demo": "Presentation",
    },
    "de": {
        "meeting": "Besprechung",
        "client_call": "Kundengespräch",
        "sales_call": "Verkaufsgespräch",
        "interview": "Interview",
        "one_on_one": "Einzelgespräch",
        "podcast_broadcast": "Sendung",
        "lecture_webinar": "Vortrag",
        "voice_memo": "Sprachnotiz",
        "presentation_demo": "Präsentation",
    },
    "uk": {
        "meeting": "Зустріч",
        "client_call": "Розмова з клієнтом",
        "sales_call": "Продажний дзвінок",
        "interview": "Інтерв'ю",
        "one_on_one": "Розмова один на один",
        "podcast_broadcast": "Передача",
        "lecture_webinar": "Лекція",
        "voice_memo": "Голосова нотатка",
        "presentation_demo": "Презентація",
    },
}


# ── Hedges, first person, specificity (the scorer's copies of the old rules) ──

MODALITY_MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "de": (
        "wahrscheinlich", "vermutlich", "voraussichtlich", "geplant", "erwartet", "könnte",
        "dürfte", "laut", "schätzung", "geschätzt", "unbestätigt", "nicht bestätigt",
        "vorschlag", "vorgeschlagen", "vorwurf", "einschätzung", "prognose",
        "behauptung", "behauptet", "unbelegt", "nicht belegt", "widerlegt",
    ),
    "en": (
        "likely", "probably", "expected", "planned", "estimated", "estimate", "could",
        "may", "reportedly", "unconfirmed", "according to", "proposal", "proposed",
        "allegation", "alleged", "opinion", "forecast",
        "claim", "claims", "claimed", "unsubstantiated", "unproven", "refuted", "disproven",
    ),
    "uk": (
        "ймовірно", "очікується", "очікувано", "планується", "за словами", "за оцінками",
        "непідтверджено", "оцінка", "пропозиція", "запропоновано", "звинувачення", "думка",
        "прогноз", "твердження", "стверджує", "стверджується", "не підтверджено",
        "непідтвердженим", "спростовано",
    ),
}  # fmt: skip


_FIRST_PERSON_START: Final = re.compile(
    r"^(?:I|We|You|Let's|Let’s|I'm|I’m|We're|We’re|I'll|I’ll|We'll|We’ve|We've|I've|"
    r"Ich|Wir|Я|Ми)\b",
)
_FIRST_PERSON_ANY: Final = re.compile(
    r"(?:\bI'll\b|\bI’ll\b|\bwe'll\b|\bwe’ll\b|\byou guys\b|\bI am\b|\bI'm\b|\bI’m\b|"
    r"\bmy name\b|\bмене звати\b)",
    re.IGNORECASE,
)


def first_person(text: str, language: str = "en") -> bool:
    """The line speaks as I / we / you."""
    del language  # the patterns cover all three languages
    body = text_rules.body(text).strip().lstrip("\"'“„«")
    return bool(_FIRST_PERSON_START.match(body) or _FIRST_PERSON_ANY.search(body))


GENERIC_SUBJECTS: Final[frozenset[str]] = frozenset(
    {"menschen", "leute", "kamera", "kameras", "video", "videos", "rauch", "geräusch",
     "geräusche", "feuerball", "flammen", "straße", "straßen", "passanten", "zuschauer",
     "people", "camera", "cameras", "smoke", "sound", "sounds", "fireball",
     "flames", "crowd", "street", "streets", "passers",
     "люди", "камера", "відео", "дим", "звук", "звуки", "натовп", "вулиця", "полум'я"}
)  # fmt: skip
_QUOTED: Final = re.compile(r"[\"„“«»]([^\"„“«»]{2,60})[\"“”«»]")


def entities_in(text: str, language: str, known: frozenset[str] = frozenset()) -> list[str]:
    """Named things in a line: capitalised non-initial words (in German only known
    names) and acronyms; never a generic subject."""
    out: list[str] = []
    for name in text_rules.names_in(text):
        folded = name.casefold()
        if folded in GENERIC_SUBJECTS:
            continue
        acronym = len(name) > 1 and name.isupper()
        if language == "de" and not acronym and name not in known:
            continue
        out.append(name)
    return list(dict.fromkeys(out))


_DIGIT_NUMBER: Final = re.compile(r"\d+(?:[.,]\d+)*")


def specificity(
    text: str, language: str, *, known: frozenset[str] = frozenset(), has_date: bool = False
) -> int:
    """How checkable a line is: named things, digit numbers, a date, quoted terms. The old
    path also counted number words ("drei"); the scorer counts digits only since R0."""
    body = text_rules.body(text)
    return (
        len(entities_in(body, language, known))
        + len(_DIGIT_NUMBER.findall(body))
        + (1 if has_date else 0)
        + len(_QUOTED.findall(body))
    )
