"""Transcript metrics over a reference (``asr_gold``) and a duck-typed
``TranscriptionOutput``. Pure functions; ``asr_eval.py`` runs the backend.

Every value returned is a number, count or id; transcript text never leaves this
module except ``heard_forms``, which the harness writes only under ``scripts/eval/local/``.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from difflib import SequenceMatcher
from typing import Any

# ── Normalisation ────────────────────────────────────────────────────

LANGUAGES = ("de", "uk", "en")

# Verbatim-lite: hesitation sounds are not words; dropped on both sides.
FILLERS: dict[str, frozenset[str]] = {
    "de": frozenset({"äh", "ähm", "öh", "öhm", "ehm", "hm", "hmm", "mhm", "äääh", "ääh", "em"}),
    "en": frozenset({"uh", "um", "uhm", "umm", "er", "erm", "hmm", "hm", "mm", "mhm"}),
    "uk": frozenset({"е", "ем", "еее", "ее", "ем-м", "мм", "гм", "хм", "ммм"}),
}
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "′": "'", "‘": "'", "´": "'"})
# One spelling for word forms that differ only by grammatical case where the
# reference writes a sign ("%") and the speaker says a word.
_ALIASES = {
    "відсоток": "відсотків",
    "відсотка": "відсотків",
    "відсотки": "відсотків",
    "percents": "percent",
}
# Kept inside a token: letters, digits, the apostrophe (п'ять, don't) and a
# decimal point between digits. Everything else is a separator.
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[^\W\d_]+(?:'[^\W\d_]+)*", re.UNICODE)


def _numeric_formats(text: str, language: str) -> str:
    """Digit groups to one form: thousands separators out, decimal comma to
    a point, ``%`` to the word the language says."""
    if language == "de":
        text = re.sub(r"(?<=\d)\.(?=\d{3}(?!\d))", "", text)  # 1.000 → 1000
        text = re.sub(r"(?<=\d),(?=\d)", ".", text)  # 3,5 → 3.5
        text = text.replace("%", " prozent ").replace("€", " euro ")
    elif language == "en":
        text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)  # 1,000 → 1000
        text = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", text)  # 22nd → 22
        text = re.sub(r"\$\s?(\d[\d.]*)", r"\1 dollars ", text)  # $250 → 250 dollars
        text = re.sub(r"€\s?(\d[\d.]*)", r"\1 euros ", text)
        text = text.replace("%", " percent ")
    else:
        text = re.sub(r"(?<=\d)[   ](?=\d{3}(?!\d))", "", text)  # 10 000 → 10000
        text = re.sub(r"(?<=\d),(?=\d)", ".", text)
        # 22-го, 5-й, 3-є → 22, 5, 3: the ordinal ending written after digits.
        text = re.sub(r"(?<=\d)-(?:го|ге|гу|й|ий|ій|а|я|е|є|ї|му|ому|ої|ою|ти|х)\b", "", text)
        text = text.replace("%", " відсотків ")
    return text


def tokens(text: str, language: str | None) -> list[str]:
    """The normalised word tokens of ``text``. ``language`` is the language
    the text is in (``de``/``uk``/``en``; anything else gets the English
    rules minus the number words)."""
    lang = language if language in LANGUAGES else "en"
    t = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES).casefold()
    t = _numeric_formats(t, lang)
    # A hyphen between letters: German and Ukrainian compounds are one
    # word (E-Mail, будь-який); English hyphenation is two (twenty-two).
    joiner = " " if lang == "en" else ""
    t = re.sub(r"(?<=[^\W\d_])-(?=[^\W\d_])", joiner, t)
    toks = [m.group(0) for m in _TOKEN.finditer(t)]
    if language in LANGUAGES:
        toks = _numbers_to_digits(toks, lang)
    fillers = FILLERS.get(lang, frozenset())
    return [_ALIASES.get(x, x) for x in toks if x not in fillers]


def normalise(text: str, language: str | None) -> str:
    return " ".join(tokens(text, language))


# ── Number words → digits ────────────────────────────────────────────
# Not a full grammar; both sides pass through it, so an unknown form costs nothing.

_EN_UNITS = {
    "zero": 0, "oh": None, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_EN_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
_EN_ORD = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12, "thirteenth": 13, "fourteenth": 14, "fifteenth": 15,
    "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
    "twentieth": 20, "thirtieth": 30, "fortieth": 40, "fiftieth": 50,
    "sixtieth": 60, "seventieth": 70, "eightieth": 80, "ninetieth": 90,
    "hundredth": 100, "thousandth": 1000,
}  # fmt: skip

_DE_UNIT_MORPHS = [
    ("dreizehn", 13), ("vierzehn", 14), ("fünfzehn", 15), ("sechzehn", 16),
    ("siebzehn", 17), ("achtzehn", 18), ("neunzehn", 19), ("zwanzig", 20),
    ("dreißig", 30), ("dreissig", 30), ("vierzig", 40), ("fünfzig", 50),
    ("sechzig", 60), ("siebzig", 70), ("achtzig", 80), ("neunzig", 90),
    ("zwölf", 12), ("elf", 11), ("zehn", 10), ("null", 0), ("eins", 1),
    ("ein", 1), ("zwei", 2), ("zwo", 2), ("drei", 3), ("vier", 4), ("fünf", 5),
    ("sechs", 6), ("sieben", 7), ("acht", 8), ("neun", 9),
]  # fmt: skip
_DE_ORD_IRREGULAR = {"erst": 1, "dritt": 3, "siebt": 7, "acht": 8}
_DE_ORD_SUFFIX = re.compile(r"(?:s?te|s?ten|s?ter|s?tes|s?tem)$")
_DE_ARTICLES = frozenset({"ein", "eine", "einen", "einem", "einer", "eines"})

_UK_CARD: dict[str, int] = {}
for _forms, _v in (
    ("нуль нуля нулю", 0),
    ("один одна одне одного одному одній одним одною одної одні одних", 1),
    ("два дві двох двом двома", 2),
    ("три трьох трьом трьома", 3),
    ("чотири чотирьох чотирьом чотирма", 4),
    ("п'ять п'яти п'ятьох п'ятьом п'ятьма п'ятьома", 5),
    ("шість шести шістьох шістьом шістьма шістьома", 6),
    ("сім семи сімох сімом сьома сімома", 7),
    ("вісім восьми вісьмох вісьмом вісьма вісьмома", 8),
    ("дев'ять дев'яти дев'ятьох дев'ятьом дев'ятьма дев'ятьома", 9),
    ("десять десяти десятьох десятьом десятьма десятьома", 10),
    ("одинадцять одинадцяти одинадцятьма", 11),
    ("дванадцять дванадцяти дванадцятьма", 12),
    ("тринадцять тринадцяти тринадцятьма", 13),
    ("чотирнадцять чотирнадцяти чотирнадцятьма", 14),
    ("п'ятнадцять п'ятнадцяти п'ятнадцятьма", 15),
    ("шістнадцять шістнадцяти шістнадцятьма", 16),
    ("сімнадцять сімнадцяти сімнадцятьма", 17),
    ("вісімнадцять вісімнадцяти вісімнадцятьма", 18),
    ("дев'ятнадцять дев'ятнадцяти дев'ятнадцятьма", 19),
    ("двадцять двадцяти двадцятьма", 20),
    ("тридцять тридцяти тридцятьма", 30),
    ("сорок сорока", 40),
    ("п'ятдесят п'ятдесяти п'ятдесятьма", 50),
    ("шістдесят шістдесяти шістдесятьма", 60),
    ("сімдесят сімдесяти сімдесятьма", 70),
    ("вісімдесят вісімдесяти вісімдесятьма", 80),
    ("дев'яносто дев'яноста", 90),
    ("сто ста", 100),
    ("двісті двохсот двомстам двомастами", 200),
    ("триста трьохсот трьомстам трьомастами", 300),
    ("чотириста чотирьохсот чотирьомстам", 400),
    ("п'ятсот п'ятисот п'ятистам", 500),
    ("шістсот шестисот шестистам", 600),
    ("сімсот семисот семистам", 700),
    ("вісімсот восьмисот восьмистам", 800),
    ("дев'ятсот дев'ятисот дев'ятистам", 900),
):
    for _f in _forms.split():
        _UK_CARD[_f] = _v
_UK_THOUSAND = frozenset(["тисяча", "тисячі", "тисяч", "тисячу", "тисячею", "тисячам", "тисячами"])
_UK_ORD_STEMS = {
    "перш": 1, "друг": 2, "трет": 3, "четверт": 4, "п'ят": 5, "шост": 6,
    "сьом": 7, "восьм": 8, "дев'ят": 9, "десят": 10, "одинадцят": 11,
    "дванадцят": 12, "тринадцят": 13, "чотирнадцят": 14, "п'ятнадцят": 15,
    "шістнадцят": 16, "сімнадцят": 17, "вісімнадцят": 18, "дев'ятнадцят": 19,
    "двадцят": 20, "тридцят": 30, "сороков": 40, "п'ятдесят": 50,
    "шістдесят": 60, "сімдесят": 70, "вісімдесят": 80, "дев'яност": 90,
    "сот": 100, "тисячн": 1000,
}  # fmt: skip
_UK_ORD_END = re.compile(r"(?:ий|ій|ого|ому|ої|ою|ій|им|их|ими|ім|іх|іми|а|я|е|є|і|у|ю)$")


def _de_compound(word: str) -> int | None:
    """``zweiundzwanzig`` → 22, ``dreihundertfünfzig`` → 350,
    ``zweitausendsechsundzwanzig`` → 2026, ``zwanzigste`` → 20."""
    w = word
    ordinal = False
    for stem, value in _DE_ORD_IRREGULAR.items():
        if _DE_ORD_SUFFIX.sub("", w) in (stem, stem + "e") or w in (
            stem + s for s in ("e", "en", "er", "es", "em")
        ):
            return value
    stripped = _DE_ORD_SUFFIX.sub("", w)
    if stripped != w and stripped:
        w, ordinal = stripped, True
    total, current, pos = 0, 0, 0
    matched_any = False
    while pos < len(w):
        rest = w[pos:]
        if rest.startswith("tausend"):
            total += (current or 1) * 1000
            current, pos, matched_any = 0, pos + 7, True
            continue
        if rest.startswith("hundert"):
            current = (current or 1) * 100
            pos, matched_any = pos + 7, True
            continue
        if rest.startswith("und") and matched_any:
            pos += 3
            continue
        for morph, value in _DE_UNIT_MORPHS:
            if rest.startswith(morph):
                # "ein" + "und" + tens: units come before tens in German.
                nxt = rest[len(morph) :]
                if nxt.startswith("und"):
                    after = nxt[3:]
                    tens = next(
                        (
                            v
                            for m, v in _DE_UNIT_MORPHS
                            if after.startswith(m) and v >= 20 and v % 10 == 0
                        ),
                        None,
                    )
                    if tens is not None:
                        tm = next(
                            m for m, v in _DE_UNIT_MORPHS if after.startswith(m) and v == tens
                        )
                        current += value + tens
                        pos += len(morph) + 3 + len(tm)
                        matched_any = True
                        break
                current += value
                pos += len(morph)
                matched_any = True
                break
        else:
            return None
    if not matched_any:
        return None
    if ordinal and w in ("ein", "eins"):
        return None
    return total + current


def _parse_de(tok: str) -> int | None:
    if tok in _DE_ARTICLES:
        return None
    if tok.isdigit():
        return None
    value = _de_compound(tok)
    return value


def _numbers_to_digits(toks: list[str], language: str) -> list[str]:
    out: list[str] = []
    if language == "de":
        i = 0
        while i < len(toks):
            v = _parse_de(toks[i])
            # "drei komma fünf" → 3.5
            if (
                v is not None
                and i + 2 < len(toks)
                and toks[i + 1] == "komma"
                and _parse_de(toks[i + 2]) is not None
            ):
                out.append(f"{v}.{_parse_de(toks[i + 2])}")
                i += 3
                continue
            out.append(str(v) if v is not None else toks[i])
            i += 1
        return out
    if language == "en":
        return _en_numbers(toks)
    return _uk_numbers(toks)


def _en_numbers(toks: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t in _EN_ORD:
            out.append(str(_EN_ORD[t]))
            i += 1
            continue
        if (
            not (t in _EN_UNITS and _EN_UNITS[t] is not None)
            and t not in _EN_TENS
            and t
            not in (
                "hundred",
                "thousand",
            )
        ):
            out.append(t)
            i += 1
            continue
        if t in ("hundred", "thousand"):
            out.append(t)
            i += 1
            continue
        total, current, j, words = 0, 0, i, 0
        pure_small = True  # no hundred/thousand: a candidate year half
        while j < len(toks):
            w = toks[j]
            if w in _EN_UNITS and _EN_UNITS[w] is not None:
                u = _EN_UNITS[w]
                if current % 100 == 0 or (current % 100 >= 20 and current % 10 == 0 and u < 10):
                    if current % 100 != 0 and u >= 10:
                        break
                    current += u
                else:
                    break
            elif w in _EN_TENS:
                if current % 100 != 0:
                    break
                current += _EN_TENS[w]
            elif w in _EN_ORD and current % 100 >= 20 and current % 10 == 0 and _EN_ORD[w] < 10:
                current += _EN_ORD[w]
                j += 1
                words += 1
                break
            elif w == "hundred" and current:
                current *= 100
                pure_small = False
            elif w == "thousand" and (current or total):
                total += (current or 1) * 1000
                current = 0
                pure_small = False
            elif (
                w == "and"
                and not pure_small
                and j + 1 < len(toks)
                and (toks[j + 1] in _EN_UNITS or toks[j + 1] in _EN_TENS)
            ):
                pass
            else:
                break
            j += 1
            words += 1
        value = total + current
        # "twenty twenty-six", "nineteen ninety" — a year said in halves.
        if pure_small and 10 <= value <= 99 and j < len(toks):
            k = j
            nxt: list[str] = []
            while k < len(toks) and (toks[k] in _EN_UNITS or toks[k] in _EN_TENS) and len(nxt) < 2:
                nxt.append(toks[k])
                k += 1
            if nxt:
                second = _en_numbers(nxt)
                if len(second) == 1 and second[0].isdigit() and int(second[0]) < 100:
                    s = int(second[0])
                    out.append(str(value * 100 + s))
                    i = k
                    continue
        out.append(str(value))
        i = j if j > i else i + 1
    return out


def _uk_value(tok: str) -> tuple[int, bool] | None:
    """(value, is_ordinal)."""
    if tok in _UK_CARD:
        return _UK_CARD[tok], False
    for stem in sorted(_UK_ORD_STEMS, key=len, reverse=True):
        if tok.startswith(stem) and _UK_ORD_END.fullmatch(tok[len(stem) :] or "x"):
            return _UK_ORD_STEMS[stem], True
    return None


def _uk_numbers(toks: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(toks):
        if toks[i] in _UK_THOUSAND:
            out.append(toks[i])
            i += 1
            continue
        first = _uk_value(toks[i])
        if first is None:
            out.append(toks[i])
            i += 1
            continue
        total, current, j = 0, 0, i
        last_place = 10_000
        while j < len(toks):
            if toks[j] in _UK_THOUSAND:
                total += (current or 1) * 1000
                current, last_place = 0, 1000
                j += 1
                continue
            got = _uk_value(toks[j])
            if got is None:
                break
            v, is_ord = got
            place = 100 if v >= 100 else (10 if v >= 20 else 1)
            if place >= last_place or (
                place == 1 and current % 10 != 0 and current % 100 < 20 and current % 100
            ):
                break
            current += v
            last_place = place if v >= 20 or v >= 100 else 1
            j += 1
            if is_ord:
                break
        out.append(str(total + current))
        i = j if j > i else i + 1
    return out


# ── Hypothesis views ─────────────────────────────────────────────────


def _seg_language(seg: Any, recording_language: str | None) -> str | None:
    return getattr(seg, "language", None) or recording_language


def _hyp_words(hyp: Any) -> list[tuple[int, int, str, str | None]]:
    """``(start_ms, end_ms, text, language)`` per hypothesis word; a
    segment without word timings counts as one timed 'word' of its text."""
    out: list[tuple[int, int, str, str | None]] = []
    for seg in hyp.segments:
        lang = _seg_language(seg, hyp.language)
        if seg.words:
            out.extend((w.start_ms, w.end_ms, w.text, lang) for w in seg.words)
        elif seg.text.strip():
            out.append((seg.start_ms, seg.end_ms, seg.text, lang))
    return out


def _mid(start: int, end: int) -> int:
    return (start + end) // 2


def _inside(ms: int, regions: Sequence[dict[str, Any]]) -> bool:
    return any(r["start_ms"] <= ms < r["end_ms"] for r in regions)


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


# Non-speech that is not speech. An ad read is speech: transcribing it is
# right (TR-07 wants it marked, TR-02 does not count it).
HALLUCINATION_KINDS = frozenset({"music", "jingle", "silence", "noise"})


def _grouped_tokens(words: Iterable[tuple[int, int, str, str | None]]) -> list[str]:
    """Normalise consecutive words of one language together, so a number
    said across words ("twenty two") is parsed as one."""
    out: list[str] = []
    run: list[str] = []
    run_lang: str | None = None
    for _s, _e, text, lang in words:
        if run and lang != run_lang:
            out.extend(tokens(" ".join(run), run_lang))
            run = []
        run.append(text)
        run_lang = lang
    if run:
        out.extend(tokens(" ".join(run), run_lang))
    return out


# ── Metrics ──────────────────────────────────────────────────────────


def wer_counts(
    reference: Sequence[dict[str, Any]], hyp: Any, non_speech: Sequence[dict[str, Any]]
) -> dict[str, int]:
    """Word errors on speech regions: hypothesis words whose midpoint falls
    in a gold non-speech region are TR-02's business, not WER's."""
    import jiwer

    ref_toks: list[str] = []
    for seg in reference:
        ref_toks.extend(tokens(seg["text"], seg.get("language")))
    kept = [w for w in _hyp_words(hyp) if not _inside(_mid(w[0], w[1]), non_speech)]
    hyp_toks = _grouped_tokens(kept)
    if not ref_toks:
        return {
            "ref_words": 0,
            "hyp_words": len(hyp_toks),
            "sub": 0,
            "del": 0,
            "ins": len(hyp_toks),
            "hits": 0,
        }
    if not hyp_toks:
        return {
            "ref_words": len(ref_toks),
            "hyp_words": 0,
            "sub": 0,
            "del": len(ref_toks),
            "ins": 0,
            "hits": 0,
        }
    out = jiwer.process_words(" ".join(ref_toks), " ".join(hyp_toks))
    return {
        "ref_words": len(ref_toks),
        "hyp_words": len(hyp_toks),
        "sub": out.substitutions,
        "del": out.deletions,
        "ins": out.insertions,
        "hits": out.hits,
    }


def wer_of(counts: dict[str, int]) -> float | None:
    if not counts.get("ref_words"):
        return None
    return (counts["sub"] + counts["del"] + counts["ins"]) / counts["ref_words"]


def _window_tokens(hyp: Any, start_ms: int, end_ms: int, reach_ms: int) -> list[str]:
    words = [
        w
        for w in _hyp_words(hyp)
        if _overlap(w[0], w[1], start_ms - reach_ms, end_ms + reach_ms) > 0
        or (start_ms - reach_ms <= w[0] <= end_ms + reach_ms)
    ]
    return _grouped_tokens(words)


def _contains(haystack: list[str], needle: list[str]) -> bool:
    n = len(needle)
    if n == 0:
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


ENTITY_REACH_MS = 2000


def entity_errors(spans: dict[str, Any], hyp: Any, language: str) -> dict[str, int]:
    """Proper-noun spans whose normalised text (or an ``accept`` form) is not
    in the hypothesis within ±2 s."""
    total = wrong = 0
    for ent in spans.get("entities", []):
        total += 1
        lang = ent.get("language") or language
        window = _window_tokens(hyp, ent["start_ms"], ent["end_ms"], ENTITY_REACH_MS)
        forms = [ent["text"], *ent.get("accept", [])]
        if not any(_contains(window, tokens(f, lang)) for f in forms):
            wrong += 1
    return {"entities": total, "entities_wrong": wrong}


def number_date_errors(spans: dict[str, Any], hyp: Any, language: str) -> dict[str, int]:
    total = wrong = 0
    for item in spans.get("numbers", []):
        total += 1
        lang = item.get("language") or language
        window = _window_tokens(hyp, item["start_ms"], item["end_ms"], ENTITY_REACH_MS)
        forms = [item["text"], *item.get("accept", [])]
        if not any(_contains(window, tokens(f, lang)) for f in forms):
            wrong += 1
    return {"numbers": total, "numbers_wrong": wrong}


def _heard_as(window: list[str], canonical: list[str]) -> str | None:
    """The hypothesis n-gram that most resembles the canonical spelling, or
    ``None`` when nothing in reach is close (the mention was lost)."""
    if not window or not canonical:
        return None
    target = "".join(canonical)
    best, best_ratio = None, 0.0
    n0 = len(canonical)
    for n in {max(1, n0 - 1), n0, n0 + 1}:
        for i in range(len(window) - n + 1):
            gram = window[i : i + n]
            ratio = SequenceMatcher(None, "".join(gram), target).ratio()
            if ratio > best_ratio:
                best, best_ratio = " ".join(gram), ratio
    return best if best_ratio >= 0.5 else None


def entity_consistency(spans: dict[str, Any], hyp: Any, language: str) -> dict[str, Any]:
    """Per gold entity with >= 2 mentions: share heard as the majority spelling, and distinct
    spellings. ``heard_forms`` carries text and is for the local folder only.
    """
    mentions: dict[str, list[dict[str, Any]]] = {}
    for ent in spans.get("entities", []):
        mentions.setdefault(ent["text"], []).append(ent)
    per_entity: dict[str, dict[str, Any]] = {}
    for canonical, items in mentions.items():
        if len(items) < 2:
            continue
        lang = items[0].get("language") or language
        heard = [
            _heard_as(
                _window_tokens(hyp, e["start_ms"], e["end_ms"], ENTITY_REACH_MS),
                tokens(canonical, lang),
            )
            for e in items
        ]
        spellings = Counter(h for h in heard if h is not None)
        majority = spellings.most_common(1)[0][1] if spellings else 0
        per_entity[canonical] = {
            "mentions": len(items),
            "consistency": majority / len(items),
            "variants": len(spellings),
            "heard_forms": dict(spellings),
        }
    return per_entity


def hallucination(non_speech: Sequence[dict[str, Any]], hyp: Any) -> dict[str, float | int]:
    regions = [r for r in non_speech if r.get("kind") in HALLUCINATION_KINDS]
    ms = sum(r["end_ms"] - r["start_ms"] for r in regions)
    chars = sum(
        len("".join(text.split()))
        for s, e, text, _l in _hyp_words(hyp)
        if _inside(_mid(s, e), regions)
    )
    return {"nonspeech_ms": ms, "halluc_chars": chars}


def artefact_hits(hyp: Any, non_speech: Sequence[dict[str, Any]]) -> int:
    """Segments that are a known artefact phrase. An ``always`` phrase counts
    anywhere; an ``if_nonspeech`` one ("Vielen Dank.") only inside gold
    non-speech, where nobody said it."""
    from asr_models.artefacts import match_artefact

    hits = 0
    for seg in hyp.segments:
        phrase = match_artefact(seg.text)
        if phrase is None:
            continue
        if phrase.drop == "always" or _inside(_mid(seg.start_ms, seg.end_ms), non_speech):
            hits += 1
    return hits


UNEXPLAINED_GAP_MS = 3000


def coverage(hyp: Any) -> dict[str, int | None]:
    c = getattr(getattr(hyp, "diagnostics", None), "coverage", None)
    if c is None:
        return {"speech_ms": None, "transcribed_ms": None, "unexplained_gaps": None}
    unexplained = sum(
        1 for g in c.gaps if g.cause == "unknown" and g.end_ms - g.start_ms >= UNEXPLAINED_GAP_MS
    )
    return {
        "speech_ms": c.speech_ms,
        "transcribed_ms": c.transcribed_ms,
        "unexplained_gaps": unexplained,
    }


CODESWITCH_MIN_SHARE = 0.70


def codeswitch(
    reference: Sequence[dict[str, Any]], spans: dict[str, Any], hyp: Any
) -> dict[str, int]:
    """Gold code-switch regions with ≥ 70 % of their words present in the
    right language, and hypothesis segments whose language differs from the
    gold segment they overlap most."""
    regions = spans.get("code_switch", [])
    covered = 0
    words = _hyp_words(hyp)
    for r in regions:
        lang = r["language"]
        ref_toks: list[str] = []
        for seg in reference:
            if (
                _overlap(seg["start_ms"], seg["end_ms"], r["start_ms"], r["end_ms"]) > 0
                and seg.get("language", lang) == lang
            ):
                ref_toks.extend(tokens(seg["text"], lang))
        in_region = [
            w for w in words if _overlap(w[0], w[1], r["start_ms"] - 500, r["end_ms"] + 500) > 0
        ]
        hyp_toks = Counter(_grouped_tokens(in_region))
        if not ref_toks:
            continue
        present = sum(min(hyp_toks[t], n) for t, n in Counter(ref_toks).items())
        right_language = sum(1 for w in in_region if w[3] == lang) >= max(1, len(in_region) / 2)
        if present / len(ref_toks) >= CODESWITCH_MIN_SHARE and right_language:
            covered += 1
    translated = 0
    for seg in hyp.segments:
        if not seg.text.strip():
            continue
        best, best_ov = None, 0
        for ref in reference:
            ov = _overlap(seg.start_ms, seg.end_ms, ref["start_ms"], ref["end_ms"])
            if ov > best_ov:
                best, best_ov = ref, ov
        if (
            best is not None
            and best.get("language")
            and best["language"] != _seg_language(seg, hyp.language)
        ):
            translated += 1
    return {
        "codeswitch_regions": len(regions),
        "codeswitch_covered": covered,
        "translated_segments": translated,
    }


NONSPEECH_MARK_MIN_MS = 5000


def nonspeech_marked(non_speech: Sequence[dict[str, Any]], hyp: Any) -> dict[str, int]:
    """Gold non-speech regions >= 5 s half-covered by ``TranscriptionOutput.noise`` markers."""
    regions = [r for r in non_speech if r["end_ms"] - r["start_ms"] >= NONSPEECH_MARK_MIN_MS]
    markers = list(getattr(hyp, "noise", None) or [])
    marked = 0
    for r in regions:
        covered = sum(
            _overlap(_get(m, "start_ms"), _get(m, "end_ms"), r["start_ms"], r["end_ms"])
            for m in markers
        )
        if covered * 2 >= r["end_ms"] - r["start_ms"]:
            marked += 1
    content_lines = sum(
        1
        for seg in hyp.segments
        if seg.text.strip()
        and any(
            _overlap(seg.start_ms, seg.end_ms, r["start_ms"], r["end_ms"]) * 2
            > seg.end_ms - seg.start_ms
            for r in regions
            if r.get("kind") in HALLUCINATION_KINDS
        )
    )
    return {
        "nonspeech_regions": len(regions),
        "nonspeech_marked": marked,
        "nonspeech_content_lines": content_lines,
    }


def _get(item: Any, key: str) -> int:
    return int(item[key] if isinstance(item, dict) else getattr(item, key))


def _plain(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold()))


def word_timing(alignment: Sequence[dict[str, Any]] | None, hyp: Any) -> dict[str, Any]:
    """Start-time error of matched words against the forced alignment of the
    reference (TR-08), and hypothesis words without a usable timestamp."""
    missing = 0
    for seg in hyp.segments:
        if seg.text.strip() and not seg.words:
            missing += len(seg.text.split())
        missing += sum(1 for w in seg.words if w.end_ms < w.start_ms)
    if not alignment:
        return {"word_ts_errors_ms": [], "words_without_timestamps": missing}
    ref = [(_plain(a["text"]), a["start_ms"]) for a in alignment]
    hw = [(_plain(w.text), w.start_ms) for s in hyp.segments for w in s.words]
    ref = [r for r in ref if r[0]]
    hw = [h for h in hw if h[0]]
    sm = SequenceMatcher(None, [r[0] for r in ref], [h[0] for h in hw], autojunk=False)
    errors: list[int] = []
    for block in sm.get_matching_blocks():
        for k in range(block.size):
            errors.append(abs(ref[block.a + k][1] - hw[block.b + k][1]))
    return {"word_ts_errors_ms": errors, "words_without_timestamps": missing}


PUNCT_MIN_WORDS = 8
_SENTENCE_PUNCT = re.compile(r"[.?!…。]")


def punctuation(hyp: Any) -> dict[str, int]:
    long_segs = [s for s in hyp.segments if len(s.text.split()) >= PUNCT_MIN_WORDS]
    return {
        "long_segments": len(long_segs),
        "punctuated_segments": sum(1 for s in long_segs if _SENTENCE_PUNCT.search(s.text)),
    }


def merge_quality(plan: Any, spans: dict[str, Any]) -> dict[str, int]:
    """How the spelling overlay's clusters line up with gold: a cluster is a wrong merge when a
    rewritten occurrence falls on a gold entity whose name lacks the canonical spelling.
    """
    entities = spans.get("entities", [])
    applied = [p for p in plan.proposals if p.status == "accepted"]
    wrong = 0
    for p in applied:
        canonical = "".join(ch for ch in p.to_text.casefold() if ch.isalnum())
        for occ in p.occurrences:
            t = int(occ.get("t", -(10**9)))
            gold = next(
                (
                    e
                    for e in entities
                    if e["start_ms"] - ENTITY_REACH_MS <= t <= e["end_ms"] + ENTITY_REACH_MS
                ),
                None,
            )
            names = [gold["text"], *gold.get("accept", [])] if gold else []
            if gold and not any(
                canonical in "".join(ch for ch in n.casefold() if ch.isalnum()) for n in names
            ):
                wrong += 1
                break
    return {
        "clusters_applied": len(applied),
        "clusters_proposed": sum(1 for p in plan.proposals if p.status == "proposed"),
        "wrong_merges": wrong,
    }


# ── One recording, then a language ───────────────────────────────────


def score_recording(
    *,
    reference: Sequence[dict[str, Any]],
    spans: dict[str, Any],
    alignment: Sequence[dict[str, Any]] | None,
    hyp: Any,
    language: str,
    audio_seconds: float,
    wall_seconds: float,
) -> dict[str, Any]:
    """Counts for one recording (the aggregate is built from counts, not
    from per-file rates). Numbers only, except ``_local`` (heard forms)
    which the caller strips before writing the report."""
    non_speech = spans.get("non_speech", [])
    row: dict[str, Any] = {}
    row.update(wer_counts(reference, hyp, non_speech))
    row["wer"] = wer_of(row)
    row.update(entity_errors(spans, hyp, language))
    row.update(number_date_errors(spans, hyp, language))
    consistency = entity_consistency(spans, hyp, language)
    row["entity_consistency"] = (
        statistics.fmean(v["consistency"] for v in consistency.values()) if consistency else None
    )
    row["entity_variants_max"] = max((v["variants"] for v in consistency.values()), default=None)
    row["entity_groups"] = len(consistency)
    row.update(hallucination(non_speech, hyp))
    row["artefact_hits"] = artefact_hits(hyp, non_speech)
    row.update(coverage(hyp))
    row.update(codeswitch(reference, spans, hyp))
    row.update(nonspeech_marked(non_speech, hyp))
    timing = word_timing(alignment, hyp)
    errs = timing.pop("word_ts_errors_ms")
    row["words_without_timestamps"] = timing["words_without_timestamps"]
    row["word_ts_n"] = len(errs)
    row["word_ts_median_ms"] = statistics.median(errs) if errs else None
    row["word_ts_p90_ms"] = _percentile(errs, 0.9) if errs else None
    row.update(punctuation(hyp))
    row["audio_seconds"] = round(audio_seconds, 2)
    row["wall_seconds"] = round(wall_seconds, 2)
    row["rtf"] = round(wall_seconds / audio_seconds, 4) if audio_seconds else None
    row["_local"] = {
        "heard_forms": {k: v["heard_forms"] for k, v in consistency.items()},
        "word_ts_errors_ms": errs,
    }
    return row


def _percentile(values: Sequence[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


DIRECTIONAL_BELOW = 20
NOT_MEASURED_BELOW = 3


def aggregate(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The TR metrics over a set of recordings, micro-averaged from counts; every key maps to
    a taxonomy code (``tests/unit/test_notes_gates.py`` enforces it).
    """

    def total(key: str) -> float:
        return sum(r.get(key) or 0 for r in rows)

    errors = total("sub") + total("del") + total("ins")
    ts = [e for r in rows for e in r.get("_local", {}).get("word_ts_errors_ms", [])]
    consistency = [r["entity_consistency"] for r in rows if r.get("entity_consistency") is not None]
    rtfs = [r["rtf"] for r in rows if r.get("rtf") is not None]
    nonspeech_min = total("nonspeech_ms") / 60_000
    n = len(rows)
    return {
        "n": n,
        "directional": n < DIRECTIONAL_BELOW,
        "not_measured": n < NOT_MEASURED_BELOW,
        "wer": _ratio(errors, total("ref_words")),
        "entity_error_rate": _ratio(total("entities_wrong"), total("entities")),
        "entity_consistency": round(statistics.fmean(consistency), 4) if consistency else None,
        "entity_consistency_raw": round(statistics.fmean(raw), 4)
        if (
            raw := [
                r["entity_consistency_raw"]
                for r in rows
                if r.get("entity_consistency_raw") is not None
            ]
        )
        else None,
        "entity_error_rate_raw": _ratio(total("entities_wrong_raw"), total("entities")),
        "wrong_merges": int(total("wrong_merges")),
        "wrong_merges_per_10": round(10 * total("wrong_merges") / n, 2) if n else None,
        "clusters_applied": int(total("clusters_applied")),
        "clusters_proposed": int(total("clusters_proposed")),
        "entity_variants": max(
            (r["entity_variants_max"] for r in rows if r.get("entity_variants_max") is not None),
            default=None,
        ),
        "number_date_error_rate": _ratio(total("numbers_wrong"), total("numbers")),
        "halluc_chars_per_nonspeech_min": round(total("halluc_chars") / nonspeech_min, 3)
        if nonspeech_min
        else None,
        "artefact_hits": int(total("artefact_hits")),
        "speech_coverage": _ratio(total("transcribed_ms"), total("speech_ms")),
        "unexplained_gaps": int(total("unexplained_gaps")),
        "codeswitch_coverage": _ratio(total("codeswitch_covered"), total("codeswitch_regions")),
        "translated_segments": int(total("translated_segments")),
        "nonspeech_marked": _ratio(total("nonspeech_marked"), total("nonspeech_regions")),
        "nonspeech_content_lines": int(total("nonspeech_content_lines")),
        "word_ts_median_ms": statistics.median(ts) if ts else None,
        "word_ts_p90_ms": round(_percentile(ts, 0.9), 1) if ts else None,
        "words_without_timestamps": int(total("words_without_timestamps")),
        "punctuated_share": _ratio(total("punctuated_segments"), total("long_segments")),
        "rtf": _ratio(total("wall_seconds"), total("audio_seconds")),
        "rtf_p95": round(_percentile(rtfs, 0.95), 4) if rtfs else None,
        "seconds_per_audio_hour": round(total("wall_seconds") / (total("audio_seconds") / 3600), 1)
        if total("audio_seconds")
        else None,
    }
