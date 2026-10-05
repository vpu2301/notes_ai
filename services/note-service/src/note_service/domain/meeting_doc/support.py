"""What "supported" means: the ONE lexical definition shared by verify, pipeline
and the eval scorer (``scripts/eval/notes_scoring.py``).

Catches NEW content (a name, number or event not in the evidence) and copied
prompt examples; not an inverted relation built from the right words.
Pure. No logging: the inputs are content.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# ── Stop words ──────────────────────────────────────────────────────

# The merge step's list: a change here changes which facts count as the same fact.
MERGE_STOP: Final[frozenset[str]] = frozenset(
    # fmt: off
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "we",
        "will",
        "with",
        "der",
        "die",
        "das",
        "und",
        "den",
        "dem",
        "ein",
        "eine",
        "ist",
        "im",
        "zu",
        "von",
        "mit",
        "auf",
        "für",
        "і",
        "та",
        "в",
        "на",
        "з",
        "до",
        "що",
        "це",
        "як",
        "для",
    ]
    # fmt: on
)

# Per language, wider than MERGE_STOP: function words must not move a support ratio.
STOP_WORDS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset(
        # fmt: off
        [
            "a",
            "an",
            "and",
            "are",
            "as",
            "at",
            "be",
            "been",
            "being",
            "but",
            "by",
            "can",
            "could",
            "did",
            "do",
            "does",
            "for",
            "from",
            "had",
            "has",
            "have",
            "he",
            "her",
            "his",
            "if",
            "in",
            "into",
            "is",
            "it",
            "its",
            "may",
            "might",
            "more",
            "most",
            "no",
            "not",
            "of",
            "on",
            "or",
            "our",
            "she",
            "should",
            "so",
            "some",
            "such",
            "than",
            "that",
            "the",
            "their",
            "them",
            "then",
            "there",
            "these",
            "they",
            "this",
            "those",
            "to",
            "up",
            "us",
            "very",
            "was",
            "we",
            "were",
            "what",
            "when",
            "which",
            "who",
            "will",
            "with",
            "would",
            "you",
            "your",
            "also",
            "about",
            "all",
            "any",
            "only",
            "over",
            "out",
            "now",
            "just",
            "still",
        ]
        # fmt: on
    ),
    "de": frozenset(
        # fmt: off
        [
            "der",
            "die",
            "das",
            "den",
            "dem",
            "des",
            "ein",
            "eine",
            "einen",
            "einem",
            "einer",
            "eines",
            "und",
            "oder",
            "aber",
            "auch",
            "als",
            "am",
            "an",
            "auf",
            "aus",
            "bei",
            "bis",
            "da",
            "dass",
            "doch",
            "durch",
            "er",
            "es",
            "für",
            "hat",
            "haben",
            "hatte",
            "ich",
            "ihr",
            "im",
            "in",
            "ist",
            "ja",
            "kann",
            "man",
            "mit",
            "nach",
            "nicht",
            "noch",
            "nun",
            "nur",
            "ob",
            "sich",
            "sie",
            "sind",
            "so",
            "soll",
            "sollen",
            "um",
            "uns",
            "unter",
            "vom",
            "von",
            "vor",
            "war",
            "waren",
            "was",
            "wie",
            "wir",
            "wird",
            "werden",
            "wurde",
            "wurden",
            "zu",
            "zum",
            "zur",
            "über",
            "schon",
            "sehr",
            "wenn",
            "weil",
            "dann",
            "also",
            "dieser",
            "diese",
            "dieses",
            "diesen",
            "jetzt",
            "mal",
            "gibt",
            "sein",
            "seine",
            "ihre",
        ]
        # fmt: on
    ),
    "uk": frozenset(
        # fmt: off
        [
            "і",
            "й",
            "та",
            "а",
            "але",
            "в",
            "у",
            "на",
            "з",
            "із",
            "зі",
            "до",
            "для",
            "що",
            "це",
            "як",
            "є",
            "був",
            "була",
            "було",
            "були",
            "буде",
            "не",
            "ні",
            "же",
            "ж",
            "так",
            "то",
            "той",
            "та",
            "ті",
            "цей",
            "ця",
            "ці",
            "про",
            "по",
            "від",
            "за",
            "під",
            "над",
            "при",
            "через",
            "його",
            "її",
            "їх",
            "ми",
            "ви",
            "вони",
            "він",
            "вона",
            "воно",
            "я",
            "ти",
            "нас",
            "вас",
            "вже",
            "ще",
            "лише",
            "також",
            "які",
            "який",
            "яка",
            "яке",
            "щоб",
            "бо",
            "якщо",
            "коли",
            "тому",
            "дуже",
            "може",
        ]
        # fmt: on
    ),
}
_ALL_STOP: Final[frozenset[str]] = frozenset().union(*STOP_WORDS.values())

STEM: Final = 5
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
CAPITALISED: Final = re.compile(r"\b([A-ZА-ЯІЇЄҐÄÖÜ][\w'’\-]{1,29})\b")
# Before these a capital letter says nothing about being a name.
_OPENERS: Final = ".!?:;—–(\"'„«“‚"


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def merge_tokens(text: str) -> frozenset[str]:
    """The merge step's tokens."""
    return frozenset(w for w in _WORD.findall(_fold(text)) if len(w) > 1 and w not in MERGE_STOP)


def stop_words(language: str) -> frozenset[str]:
    return STOP_WORDS.get(language) or _ALL_STOP


def _stem(word: str) -> str:
    return word[:STEM] if len(word) > STEM else word


def content_tokens(text: str, language: str) -> list[str]:
    """NFKC, case-folded, words over one character, stop words out, long
    words cut to a five-letter stem ("Lieferungen" → "liefe"), in order."""
    stops = stop_words(language) | MERGE_STOP
    return [_stem(w) for w in _WORD.findall(_fold(text)) if len(w) > 1 and w not in stops]


# A claim word sharing a run of this many letters with an evidence word counts
# as supported (German/Ukrainian compounds and inflections).
COMPOUND_MIN: Final = 6
# Line gate threshold per language. PROVISIONAL: calibrate with scripts/eval/support_calibration.py.
LINE_SUPPORT_BY_LANGUAGE: Final[dict[str, float]] = {"en": 0.5, "de": 0.4, "uk": 0.4}
LINE_SUPPORT_DEFAULT: Final = 0.5


def line_support_threshold(language: str) -> float:
    return LINE_SUPPORT_BY_LANGUAGE.get(language, LINE_SUPPORT_DEFAULT)


def _runs(word: str) -> set[str]:
    return {word[i : i + COMPOUND_MIN] for i in range(len(word) - COMPOUND_MIN + 1)}


def support_ratio(claim: str, evidence: str, language: str = "en") -> float:
    """Share of the claim's content words the evidence has (by stem or a
    :data:`COMPOUND_MIN` run); 1.0 for a claim with no content words."""
    stops = stop_words(language) | MERGE_STOP
    words = {w for w in _WORD.findall(_fold(claim)) if len(w) > 1 and w not in stops}
    claim_stems = {_stem(w): w for w in sorted(words)}
    if not claim_stems:
        return 1.0
    evidence_words = [w for w in _WORD.findall(_fold(evidence)) if len(w) > 1 and w not in stops]
    have = {_stem(w) for w in evidence_words}
    runs = set().union(*(_runs(w) for w in evidence_words)) if evidence_words else set()
    supported = sum(1 for stem, word in claim_stems.items() if stem in have or (_runs(word) & runs))
    return supported / len(claim_stems)


def _body(text: str) -> str:
    """A line without its list marker or heading hashes."""
    return re.sub(r"^\s*(?:#{1,6}\s+|[-*]\s+)", "", text)


def names_in(text: str) -> list[str]:
    """Capitalised non-initial tokens (German nouns included, compared by stem)."""
    body = _body(text)
    out: list[str] = []
    for match in CAPITALISED.finditer(body):
        before = body[: match.start()].rstrip()
        if not before or before[-1] in _OPENERS:
            continue
        out.append(match.group(1))
    return out


def new_names(claim: str, evidence: str, known: frozenset[str] = frozenset()) -> list[str]:
    """Capitalised non-initial tokens of ``claim`` that neither the evidence nor
    ``known`` has, by stem; in order, once each."""
    have = {_stem(w) for w in _WORD.findall(_fold(evidence))}
    have |= {_stem(w) for name in known for w in _WORD.findall(_fold(name))}
    out: list[str] = []
    for name in names_in(claim):
        words = [_stem(w) for w in _WORD.findall(_fold(name))]
        if words and not all(w in have for w in words) and name not in out:
            out.append(name)
    return out


# ── Language profile (for confirming an `other_language` flag) ──────

_CYRILLIC: Final = re.compile(r"[Ѐ-ӿ]")
_LATIN: Final = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
CYRILLIC_LANGUAGES: Final[frozenset[str]] = frozenset({"uk", "ru", "bg", "sr"})


def cyrillic_share(text: str) -> float:
    """Cyrillic letters ÷ (Cyrillic + Latin letters); 0.0 for no letters."""
    cyr = len(_CYRILLIC.findall(text))
    lat = len(_LATIN.findall(text))
    return cyr / (cyr + lat) if (cyr + lat) else 0.0


def stop_word_share(text: str, language: str) -> float:
    """Share of the words that are the language's stop words."""
    words = [w for w in _WORD.findall(_fold(text)) if len(w) > 0]
    if not words:
        return 0.0
    stops = STOP_WORDS.get(language)
    if not stops:
        return 1.0
    return sum(1 for w in words if w in stops) / len(words)


# ── Certainty in words ──────────────────────────────────────────────

# Words that already say a statement is not a plain fact; shared with the eval's hedge scorer.
MODALITY_MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "de": (
        "wahrscheinlich", "vermutlich", "voraussichtlich", "geplant", "erwartet", "könnte",
        "dürfte", "laut", "schätzung", "geschätzt", "unbestätigt", "nicht bestätigt",
        "vorschlag", "vorgeschlagen", "vorwurf", "einschätzung", "prognose",
    ),
    "en": (
        "likely", "probably", "expected", "planned", "estimated", "estimate", "could",
        "may", "reportedly", "unconfirmed", "according to", "proposal", "proposed",
        "allegation", "alleged", "opinion", "forecast",
    ),
    "uk": (
        "ймовірно", "очікується", "очікувано", "планується", "за словами", "за оцінками",
        "непідтверджено", "оцінка", "пропозиція", "запропоновано", "звинувачення", "думка",
        "прогноз",
    ),
}  # fmt: skip

# What code prepends to a hedged line that carries no marker of its own.
CERTAINTY_PHRASES: Final[dict[str, dict[str, str]]] = {
    "de": {
        "prediction": "Voraussichtlich", "estimate": "Schätzung", "proposal": "Vorschlag",
        "allegation": "Vorwurf", "opinion": "Einschätzung",
    },
    "en": {
        "prediction": "Expected", "estimate": "Estimate", "proposal": "Proposal",
        "allegation": "Allegation", "opinion": "Opinion",
    },
    "uk": {
        "prediction": "Очікувано", "estimate": "Оцінка", "proposal": "Пропозиція",
        "allegation": "Звинувачення", "opinion": "Думка",
    },
}  # fmt: skip

# The actor suffix: "— laut Reinbold", "(Vorschlag: Söder)".
ACCORDING_TO: Final[dict[str, str]] = {"de": "laut", "en": "according to", "uk": "за словами"}
UNSURE_CERTAINTIES: Final[frozenset[str]] = frozenset(
    {"opinion", "prediction", "estimate", "proposal", "allegation"}
)


def has_marker(text: str, language: str) -> bool:
    folded = _fold(text)
    markers = MODALITY_MARKERS.get(language) or MODALITY_MARKERS["en"]
    return any(re.search(rf"(?<!\w){re.escape(m)}(?!\w)", folded) for m in markers)


def names_actor(text: str, actor: str) -> bool:
    """Whether ``text`` names ``actor``, by the last word of the name."""
    last = actor.split()[-1] if actor.split() else ""
    return (
        bool(last) and re.search(rf"(?<!\w){re.escape(_fold(last))}(?!\w)", _fold(text)) is not None
    )


# ── Does a line carry information, and whose voice is it in ────────

# Words that judge instead of inform. A capitalised non-initial use is a name ("Nice") and counts.
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
    body = _body(text)
    names = {n.casefold() for n in names_in(body)}
    stops = stop_words(language) | MERGE_STOP | FILLER
    judging = EVALUATIVE.get(language, frozenset()) | EVALUATIVE["en"]
    out: list[str] = []
    for word in _WORD.findall(_fold(body)):
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
    body = _body(text)
    if _DIGITS.search(body) or names_in(body):
        return True
    judging = EVALUATIVE.get(language, frozenset()) | EVALUATIVE["en"]
    return not any(w in judging for w in _WORD.findall(_fold(body)))


# The speaker's own voice: at the start, or an unmistakable contraction anywhere.
_FIRST_PERSON_START: Final = re.compile(
    r"^(?:I|We|You|Let's|Let’s|I'm|I’m|We're|We’re|I'll|I’ll|We'll|We’ve|We've|I've|"
    r"Ich|Wir|Я|Ми)\b",
)
_FIRST_PERSON_ANY: Final = re.compile(
    r"(?:\bI'll\b|\bI’ll\b|\bwe'll\b|\bwe’ll\b|\byou guys\b|\bI am\b|\bI'm\b|\bI’m\b|"
    r"\bmy name\b|\bмене звати\b)",
    re.IGNORECASE,
)
# Dropping one of these is the only rewrite code makes of a model's line.
_MECHANICAL_OPENER: Final = re.compile(r"^(?:So|Again|Also)\s*,\s*", re.IGNORECASE)


def mechanical_third_person(text: str) -> str | None:
    """``text`` without a leading "So," / "Again," / "Also,", or None without one."""
    body = text.strip()
    match = _MECHANICAL_OPENER.match(body)
    if match is None:
        return None
    rest = body[match.end() :].lstrip()
    if not rest:
        return None
    return rest[0].upper() + rest[1:]


def first_person(text: str, language: str = "en") -> bool:
    """The line speaks as I / we / you."""
    del language  # the patterns cover all three languages
    body = _body(text).strip().lstrip("\"'“„«")
    return bool(_FIRST_PERSON_START.match(body) or _FIRST_PERSON_ANY.search(body))


# ── What is specific, what is scenery ───────────────────────────────

# Scene and perception verbs (stems, case-folded).
SCENE_VERBS: Final[dict[str, tuple[str, ...]]] = {
    "de": ("seh", "sieht", "sah", "gesehen", "zeig", "gezeigt", "film", "gefilmt", "hör",
           "gehört", "schau", "steig", "stieg", "entsteh", "entstand", "brenn", "explodier"),
    "en": ("see", "sees", "saw", "seen", "show", "shows", "shown", "film", "filmed", "hear",
           "heard", "look", "looks", "rise", "rises", "rising", "appear", "appears", "burn",
           "explod"),
    "uk": ("бач", "бачи", "показ", "зніма", "знято", "чут", "чуємо", "дивит", "підніма",
           "з'являє", "горить", "вибух"),
}  # fmt: skip
# Subjects that are nobody in particular.
GENERIC_SUBJECTS: Final[frozenset[str]] = frozenset(
    {"menschen", "leute", "kamera", "kameras", "video", "videos", "rauch", "geräusch",
     "geräusche", "feuerball", "flammen", "straße", "straßen", "passanten", "zuschauer",
     "people", "camera", "cameras", "smoke", "sound", "sounds", "fireball",
     "flames", "crowd", "street", "streets", "passers",
     "люди", "камера", "відео", "дим", "звук", "звуки", "натовп", "вулиця", "полум'я"}
)  # fmt: skip
RECORDING_NAME_MIN: Final = 3
_QUOTED: Final = re.compile(r"[\"„“«»]([^\"„“«»]{2,60})[\"“”«»]")


def recording_names(texts: list[str], minimum: int = RECORDING_NAME_MIN) -> frozenset[str]:
    """Capitalised words said at least ``minimum`` times inside a sentence; German
    nouns qualify too, the callers exclude the generic ones."""
    counts: dict[str, int] = {}
    for text in texts:
        for name in names_in(text):
            counts[name] = counts.get(name, 0) + 1
    return frozenset(n for n, c in counts.items() if c >= minimum)


def entities_in(text: str, language: str, known: frozenset[str] = frozenset()) -> list[str]:
    """Named things in a line: capitalised non-initial words (in German only known
    names) and acronyms; never a generic subject."""
    out: list[str] = []
    for name in names_in(text):
        folded = name.casefold()
        if folded in GENERIC_SUBJECTS:
            continue
        acronym = len(name) > 1 and name.isupper()
        if language == "de" and not acronym and name not in known:
            continue
        out.append(name)
    return list(dict.fromkeys(out))


def descriptive(
    text: str, language: str, *, known: frozenset[str] = frozenset(), has_date: bool = False
) -> bool:
    """A scene: a perception/scene verb, a generic subject, no named thing, number or date."""
    body = _body(text)
    if has_date or _DIGITS.search(body):
        return False
    if evaluative(body, language):
        return True
    if entities_in(body, language, known):
        return False
    words = _WORD.findall(_fold(body))
    stems = SCENE_VERBS.get(language, ()) + SCENE_VERBS["en"]
    verb = any(w.startswith(stem) for w in words for stem in stems)
    subject = any(w in GENERIC_SUBJECTS for w in words)
    return verb and subject


# An evaluation with no claim after it teaches the note nothing checkable.
EVALUATIVE_STEMS: Final[dict[str, tuple[str, ...]]] = {
    "en": ("unusual", "interesting", "special", "remarkable", "impressive", "incredible",
           "fascinating", "amazing", "strange", "extraordinary", "notable", "unique"),
    "de": ("ungewöhnlich", "interessant", "besonder", "bemerkenswert", "beeindruckend",
           "unglaublich", "faszinierend", "erstaunlich", "außergewöhnlich", "spannend",
           "merkwürdig", "einzigartig"),
    "uk": ("незвичайн", "цікав", "особлив", "вражаюч", "дивовижн", "дивн", "унікальн"),
}  # fmt: skip
# What follows an evaluation when it says something.
_CLAIM_FOLLOWS: Final = re.compile(
    r",\s*(?:weil|da|dass|der|die|das|denn|which|who|that|because|since|бо|який|яка|яке|що)\b"
    r"|\b(?:because|weil|denn|тому що)\b|[:—]",
    re.IGNORECASE,
)


def evaluative(text: str, language: str) -> bool:
    words = _WORD.findall(_fold(_body(text)))
    stems = EVALUATIVE_STEMS.get(language, ()) + EVALUATIVE_STEMS["en"]
    if not any(w.startswith(stem) for w in words for stem in stems):
        return False
    return not _CLAIM_FOLLOWS.search(text)


def specificity(
    text: str, language: str, *, known: frozenset[str] = frozenset(), has_date: bool = False
) -> int:
    """How checkable a line is: named things, numbers, a date, quoted terms."""
    from . import numbers

    body = _body(text)
    # An article is not a count ("ein Feuerball"); digits always are.
    counted = numbers.digit_numbers(body) + [
        n for n in numbers.number_words(body, language) if n != 1
    ]
    return (
        len(entities_in(body, language, known))
        + len(counted)
        + (1 if has_date else 0)
        + len(_QUOTED.findall(body))
    )


# ── Subjects ────────────────────────────────────────────────────────

PRONOUN_SUBJECTS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({"he", "she", "it", "they", "him", "her", "his", "their", "them"}),
    "de": frozenset({"er", "sie", "es", "ihm", "ihn", "ihr", "sein", "seine", "ihre"}),
    "uk": frozenset({"він", "вона", "воно", "вони", "його", "її", "їх", "йому", "їй"}),
}
# "Es gibt …", "It is …": an expletive, not a subject.
EXPLETIVE_NEXT: Final = frozenset(
    {"gibt", "ist", "war", "sind", "waren", "geht", "wird", "is", "was", "has", "seems"}
)
_CONNECTIVE_LEAD: Final = re.compile(r"^[^—]{1,20}—\s+")
_DEFAULT_SPEAKER: Final = re.compile(
    r"(?i)^(?:speaker[ _]?\d+|unknown(?: speaker)?|sprecher(?:in)? \d+|SPEAKER_\d+)$"
)


def pronoun_initial(text: str, language: str) -> bool:
    """The sentence's subject is a bare pronoun (after a connective)."""
    words = _CONNECTIVE_LEAD.sub("", _body(text).strip()).split()
    if not words:
        return False
    first = words[0].strip(",.;:\"'„“«").casefold()
    following = words[1].casefold() if len(words) > 1 else ""
    pronouns = PRONOUN_SUBJECTS.get(language, PRONOUN_SUBJECTS["en"])
    return first in pronouns and not (first in ("es", "it") and following in EXPLETIVE_NEXT)


def real_name(name: str | None) -> str | None:
    """A person's name — never a diarizer label or a default name."""
    name = (name or "").strip()
    return name if name and not _DEFAULT_SPEAKER.match(name) else None


_CAPITAL_RUN: Final = re.compile(
    r"(?<![\w-])[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+(?:\s+[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+)+"
)


def capital_runs(text: str) -> list[str]:
    """Two or more capitalised words in a row; a sentence's first word never counts."""
    out = []
    for match in _CAPITAL_RUN.finditer(text):
        words = match.group(0).split()
        before = text[: match.start()].rstrip()
        if not before or before[-1] in _OPENERS:
            words = words[1:]
        if len(words) >= 2:
            out.append(" ".join(words))
    return out


# Which of the recording's frequent capitalised words are names.
_DETERMINERS: Final[dict[str, frozenset[str]]] = {
    "de": frozenset({
        "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem", "einer",
        "eines", "kein", "keine", "diese", "dieser", "dieses", "diesen", "jede", "jeder",
        "jedes", "alle", "viele", "mehr", "wenige", "zwei", "drei", "unsere", "seine", "ihre",
        "im", "am", "zum", "zur", "vom", "beim",
    }),
}  # fmt: skip
NOUN_SHARE: Final = 0.5
_ADJECTIVE_END: Final = re.compile(r"(?:en|er|es|em|e)$")


def proper_names(texts: list[str], candidates: frozenset[str], language: str) -> frozenset[str]:
    """In German a frequent capitalised word is a name only when it mostly stands
    without an article or determiner; other languages: the candidates as they are."""
    determiners = _DETERMINERS.get(language)
    if not determiners:
        return candidates
    after: dict[str, int] = {}
    seen: dict[str, int] = {}
    for text in texts:
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            words = _WORD.findall(sentence)
            for k, word in enumerate(words):
                # A sentence's first word is capitalised anyway: it says nothing.
                if k == 0 or word not in candidates:
                    continue
                seen[word] = seen.get(word, 0) + 1
                before = words[k - 1]
                # A noun's company: an article, determiner, number or inflected adjective.
                if (
                    before.casefold() in determiners
                    or before.isdigit()
                    or (before.islower() and _ADJECTIVE_END.search(before))
                ):
                    after[word] = after.get(word, 0) + 1
    acronyms = {n for n in candidates if len(n) > 1 and n.isupper()}
    return (
        frozenset(n for n in candidates if seen.get(n) and after.get(n, 0) / seen[n] < NOUN_SHARE)
        | acronyms
    )
