"""Plain-text helpers shared by the service and the eval scorer: comment hygiene, the
comparable form of a sentence (``fold``), and the lexical rules the scorer and the
item writer agree on (stop words, content tokens, support ratio, new names). Pure.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final

_URL_RE: Final = re.compile(r"https?://|www\.", re.IGNORECASE)
_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_comment(
    value: str | None, *, max_len: int = 280, allow_links: bool = False
) -> str | None:
    """Strip control characters and surrounding blanks; ``None`` when nothing is left.

    Raises ``ValueError`` when the text is longer than ``max_len`` or, unless
    ``allow_links``, contains a link. The text is stored and shown as plain text.
    """
    if value is None:
        return None
    cleaned = _CONTROL_RE.sub("", value).strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise ValueError(f"comment is longer than {max_len} characters")
    if not allow_links and _URL_RE.search(cleaned):
        raise ValueError("no_links_in_comment")
    return cleaned


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
ALL_STOP: Final[frozenset[str]] = frozenset().union(*STOP_WORDS.values())

STEM: Final = 5
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
CAPITALISED: Final = re.compile(r"\b([A-ZА-ЯІЇЄҐÄÖÜ][\w'’\-]{1,29})\b")
# Before these a capital letter says nothing about being a name.
_OPENERS: Final = ".!?:;—–(\"'„«“‚"


def casefold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def stop_words(language: str) -> frozenset[str]:
    return STOP_WORDS.get(language) or ALL_STOP


def _stem(word: str) -> str:
    return word[:STEM] if len(word) > STEM else word


def content_tokens(text: str, language: str) -> list[str]:
    """NFKC, case-folded, words over one character, stop words out, long
    words cut to a five-letter stem ("Lieferungen" → "liefe"), in order."""
    stops = stop_words(language) | MERGE_STOP
    return [_stem(w) for w in _WORD.findall(casefold(text)) if len(w) > 1 and w not in stops]


# A claim word sharing a run of this many letters with an evidence word counts
# as supported (German/Ukrainian compounds and inflections).
COMPOUND_MIN: Final = 6
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
    words = {w for w in _WORD.findall(casefold(claim)) if len(w) > 1 and w not in stops}
    claim_stems = {_stem(w): w for w in sorted(words)}
    if not claim_stems:
        return 1.0
    evidence_words = [w for w in _WORD.findall(casefold(evidence)) if len(w) > 1 and w not in stops]
    have = {_stem(w) for w in evidence_words}
    runs = set().union(*(_runs(w) for w in evidence_words)) if evidence_words else set()
    supported = sum(1 for stem, word in claim_stems.items() if stem in have or (_runs(word) & runs))
    return supported / len(claim_stems)


def body(text: str) -> str:
    """A line without its list marker or heading hashes."""
    return re.sub(r"^\s*(?:#{1,6}\s+|[-*]\s+)", "", text)


def names_in(text: str) -> list[str]:
    """Capitalised non-initial tokens (German nouns included, compared by stem)."""
    bare = body(text)
    out: list[str] = []
    for match in CAPITALISED.finditer(bare):
        before = bare[: match.start()].rstrip()
        if not before or before[-1] in _OPENERS:
            continue
        out.append(match.group(1))
    return out


def new_names(claim: str, evidence: str, known: frozenset[str] = frozenset()) -> list[str]:
    """Capitalised non-initial tokens of ``claim`` that neither the evidence nor
    ``known`` has, by stem; in order, once each."""
    have = {_stem(w) for w in _WORD.findall(casefold(evidence))}
    have |= {_stem(w) for name in known for w in _WORD.findall(casefold(name))}
    out: list[str] = []
    for name in names_in(claim):
        words = [_stem(w) for w in _WORD.findall(casefold(name))]
        if words and not all(w in have for w in words) and name not in out:
            out.append(name)
    return out


# ── The comparable form of a sentence (the scorers' one normaliser) ──

NORMALIZER_VERSION: Final = "fold-1"
FOLD_COMPOUND_MIN: Final = 5

_VERBS: dict[str, tuple[str, ...]] = {
    "en": (
        "said", "says", "say", "warned", "warns", "warn", "added", "adds", "add", "expects",
        "expected", "expect", "believes", "believe", "claims", "claimed", "claim", "proposes",
        "proposed", "propose", "reported", "reports", "report", "estimates", "estimated",
        "estimate", "thinks", "think", "argues", "argued", "argue", "also said", "also say",
        "also claims", "also claim",
    ),
    "de": (
        "sagte", "sagt", "warnte", "erwartet", "meint", "meinte", "behauptet", "behauptete",
        "berichtete", "berichtet", "schätzt", "schlägt vor", "schlug vor", "fügte hinzu",
        "glaubt", "ergänzte", "zufolge",
    ),
    "uk": (
        "сказав", "сказала", "каже", "попередив", "попередила", "очікує", "вважає",
        "стверджує", "пропонує", "повідомив", "повідомила", "оцінює", "додав", "додала",
    ),
}  # fmt: skip
_ACCORDING: dict[str, tuple[str, ...]] = {
    "en": ("according to",),
    "de": ("laut", "nach angaben von", "nach einschätzung von"),
    "uk": ("за словами", "на думку"),
}
_FOLD_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_FOLD_WORD = re.compile(r"[\w]+", re.UNICODE)


def _plain(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _holder_pattern(holders: Iterable[str]) -> str | None:
    forms: set[str] = set()
    for holder in holders:
        name = _plain(holder or "")
        if not name:
            continue
        forms.add(re.escape(name))
        last = name.split()[-1]
        if len(last) >= 3:
            # The last word and its inflections (Quills, Квілла): a short stem suffix.
            forms.add(re.escape(last[: max(3, len(last) - 1)]) + r"\w{0,3}")
        if name.startswith(("the ", "die ", "der ", "den ", "das ")):
            forms.add(re.escape(name.split(" ", 1)[1]))
    return "|".join(sorted(forms, key=len, reverse=True)) if forms else None


def fold(text: str, language: str, *, holders: set[str] | frozenset[str] = frozenset()) -> str:
    """The comparable form of ``text``: lower-cased, punctuation stripped, no reporting
    clause or holder suffix of a known holder."""
    lang = language if language in _VERBS else "en"
    out = _plain(text)
    who = _holder_pattern(holders)
    if who:
        # Up to two inflected name words before the form that matched ("Марека Квілла").
        who = rf"(?:[\w-]+\s+){{0,2}}(?:{who})"
        verbs = "|".join(re.escape(v) for v in _VERBS[lang])
        # Trailing suffix: "— according to X", "— laut X", "(Vorschlag: X)".
        according = "|".join(re.escape(a) for a in _ACCORDING[lang])
        out = re.sub(rf"\s*[—–-]\s*(?:{according})\s+(?:{who})\s*[.!?]?\s*$", "", out)
        out = re.sub(
            rf"\s*\((?:vorschlag|proposal|пропозиція):\s*(?:{who})\)\s*[.!?]?\s*$", "", out
        )
        # Leading clause: "X said that ", "X sagte, dass ", "X zufolge ", "according to X, ".
        out = re.sub(rf"^(?:{who})\s+(?:{verbs})\s*,?\s*(?:that|dass|що)?\s*,?\s*", "", out)
        out = re.sub(rf"^(?:{who})\s+zufolge\s*,?\s*", "", out)
        out = re.sub(rf"^(?:{according})\s+(?:{who})\s*,?\s*", "", out)
        # The continuation forms: "they also said that ", "they expect that ".
        out = re.sub(
            rf"^(?:they|he|she|er|sie|він|вона)\s+(?:{verbs})\s*,?\s*(?:that|dass|що)?\s*,?\s*",
            "",
            out,
        )
    out = _FOLD_PUNCT.sub(" ", out)
    return " ".join(out.split())


def _token_matches(want: str, have: str) -> bool:
    if want == have:
        return True
    short, long_ = (want, have) if len(want) <= len(have) else (have, want)
    return len(short) >= FOLD_COMPOUND_MIN and long_.endswith(short)


def contains(
    text: str, needle: str, language: str, *, holders: set[str] | frozenset[str] = frozenset()
) -> bool:
    """``needle`` is in ``text`` once both are folded: every needle token, in order, matched
    by equality or the compound rule against consecutive text tokens."""
    want = _FOLD_WORD.findall(fold(needle, language, holders=holders))
    have = _FOLD_WORD.findall(fold(text, language, holders=holders))
    if not want:
        return False
    for start in range(len(have) - len(want) + 1):
        if all(_token_matches(w, have[start + k]) for k, w in enumerate(want)):
            return True
    return False
