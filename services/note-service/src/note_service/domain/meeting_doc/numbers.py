"""Numbers as they are said (Sprint F3, T1).

Sprint G0 switched the post-processor's number normalisation off for
conversations, so a conversation's transcript says "eighteen and a half",
"just under three hundred", "achthundert", "півтора". A figure is verified
against its quote, and "check_numbers" asks whether every number in a
fact was said — both have to read numbers written as words, not only
digits.

:func:`numbers_in` returns every number in a text — digits and words — as a
:class:`~decimal.Decimal`. :func:`parse_value` reads one value the model
wrote ("18.5", "1,200", "eighteen and a half"). Pure; en, de, uk.

Coverage, stated so nobody assumes more: cardinals up to the millions,
decimals said with "point"/"Komma"/"кома", "a half" / "and a half" /
"quarter(s)" / "three quarters", German compounds ("einundzwanzig",
"achtzehneinhalb", "zweitausendfünfhundert"), Ukrainian cardinals in their
common forms and "півтора". Ordinals and years-as-words are not numbers
here.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Final

_WORD: Final = re.compile(r"[^\W_]+(?:['’ʼ][^\W_]+)?", re.UNICODE)
# 1,200 · 1.200 (German thousands) · 18.5 · 18,5
_DIGITS: Final = re.compile(r"\d+(?:[.,]\d+)*")

HALF: Final = Decimal("0.5")

# ── English ─────────────────────────────────────────────────────────

_EN_UNITS: Final[dict[str, int]] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
_EN_SCALES: Final[dict[str, int]] = {"hundred": 100, "thousand": 1_000, "million": 1_000_000}

# ── German ──────────────────────────────────────────────────────────

_DE_UNITS: Final[dict[str, int]] = {
    "null": 0, "ein": 1, "eins": 1, "eine": 1, "einen": 1, "zwei": 2, "zwo": 2, "drei": 3,
    "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwölf": 12, "dreizehn": 13, "vierzehn": 14, "fünfzehn": 15, "sechzehn": 16,
    "siebzehn": 17, "achtzehn": 18, "neunzehn": 19, "zwanzig": 20, "dreißig": 30,
    "dreissig": 30, "vierzig": 40, "fünfzig": 50, "sechzig": 60, "siebzig": 70,
    "achtzig": 80, "neunzig": 90,
}  # fmt: skip
_DE_SCALES: Final[dict[str, int]] = {"hundert": 100, "tausend": 1_000}
_DE_MILLION: Final = ("millionen", "million")

# ── Ukrainian ───────────────────────────────────────────────────────

_UK_UNITS: Final[dict[str, int]] = {
    "нуль": 0, "один": 1, "одна": 1, "одне": 1, "одну": 1, "два": 2, "дві": 2, "три": 3,
    "чотири": 4, "п'ять": 5, "шість": 6, "сім": 7, "вісім": 8, "дев'ять": 9, "десять": 10,
    "одинадцять": 11, "дванадцять": 12, "тринадцять": 13, "чотирнадцять": 14,
    "п'ятнадцять": 15, "шістнадцять": 16, "сімнадцять": 17, "вісімнадцять": 18,
    "дев'ятнадцять": 19, "двадцять": 20, "тридцять": 30, "сорок": 40, "п'ятдесят": 50,
    "шістдесят": 60, "сімдесят": 70, "вісімдесят": 80, "дев'яносто": 90,
    "сто": 100, "двісті": 200, "триста": 300, "чотириста": 400, "п'ятсот": 500,
    "шістсот": 600, "сімсот": 700, "вісімсот": 800, "дев'ятсот": 900,
}  # fmt: skip
_UK_SCALES: Final[dict[str, int]] = {
    "тисяча": 1_000, "тисячі": 1_000, "тисяч": 1_000, "тисячу": 1_000,
    "мільйон": 1_000_000, "мільйони": 1_000_000, "мільйонів": 1_000_000,
}  # fmt: skip

_POINT: Final = frozenset({"point", "komma", "кома", "цілих"})
_FILLER: Final = frozenset({"and", "und", "і", "й"})


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return text.replace("’", "'").replace("ʼ", "'")


def _de_compound(word: str) -> Decimal | None:
    """One German number word, compounds included: "einundzwanzig",
    "achthundertfünfzig", "zweitausendfünfhundert", "achtzehneinhalb"."""
    if not word:
        return None
    half = Decimal(0)
    if word.endswith("einhalb") and word != "einhalb":
        word, half = word[: -len("einhalb")], HALF
    if word in ("anderthalb", "eineinhalb"):
        return Decimal("1.5")
    value = _de_int(word)
    return None if value is None else Decimal(value) + half


def _de_int(word: str) -> int | None:
    if word in _DE_UNITS:
        return _DE_UNITS[word]
    for scale_word, scale in (("tausend", 1_000), ("hundert", 100)):
        if scale_word in word:
            head, _, tail = word.partition(scale_word)
            left = 1 if head in ("", "ein", "eins") else _de_int(head)
            right = 0 if tail == "" else _de_int(tail)
            if left is None or right is None:
                return None
            return left * scale + right
    if "und" in word:
        unit, _, tens = word.partition("und")
        u, t = _DE_UNITS.get(unit), _DE_UNITS.get(tens)
        if u is not None and t is not None and 1 <= u <= 9 and t >= 20 and t % 10 == 0:
            return t + u
    return None


def _en_word(word: str) -> tuple[str, int] | None:
    """("unit"|"scale", value) for one English word ("twenty-one" split before)."""
    if word in _EN_UNITS:
        return "unit", _EN_UNITS[word]
    if word in _EN_SCALES:
        return "scale", _EN_SCALES[word]
    return None


def _uk_word(word: str) -> tuple[str, int] | None:
    if word in _UK_UNITS:
        return "unit", _UK_UNITS[word]
    if word in _UK_SCALES:
        return "scale", _UK_SCALES[word]
    return None


def _de_word(word: str) -> tuple[str, Decimal] | None:
    if word in _DE_MILLION:
        return "scale", Decimal(1_000_000)
    value = _de_compound(word)
    if value is None:
        return None
    return "unit", value


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for word in _WORD.findall(_fold(text).replace("-", " ")):
        out.append(word)
    return out


def number_words(text: str, language: str = "en") -> list[Decimal]:
    """Every number spelled out in ``text``, in order."""
    lang = (language or "en")[:2]
    words = _tokens(text)
    out: list[Decimal] = []
    i = 0
    while i < len(words):
        value, used = _read(words, i, lang)
        if used:
            out.append(value)
            i += used
        else:
            i += 1
    return out


def _lookup(word: str, lang: str) -> tuple[str, Decimal] | None:
    if lang == "de":
        return _de_word(word)
    table = _uk_word(word) if lang == "uk" else _en_word(word)
    if table is None and lang not in ("en", "uk"):
        table = _en_word(word)
    return None if table is None else (table[0], Decimal(table[1]))


def _read(words: list[str], start: int, lang: str) -> tuple[Decimal, int]:
    """One spelled-out number starting at ``words[start]``: (value, words used)."""
    # "a half", "half a" (en); "півтора" (uk)
    word = words[start]
    if lang == "uk" and word in ("півтора", "півтори"):
        return Decimal("1.5"), 1
    if lang == "en" and word == "half":
        return HALF, 1
    if lang == "en" and word == "a" and start + 1 < len(words) and words[start + 1] == "half":
        return HALF, 2
    total = Decimal(0)
    current = Decimal(0)
    used = 0
    seen = False
    i = start
    while i < len(words):
        w = words[i]
        hit = _lookup(w, lang)
        if hit is not None:
            kind, value = hit
            if kind == "unit":
                current += value
            else:
                current = (current or Decimal(1)) * value
                if value >= 1_000:
                    total += current
                    current = Decimal(0)
            seen = True
            i += 1
            used = i - start
            continue
        # "one hundred and five", "zwei und zwanzig": a joiner between parts
        if seen and w in _FILLER and i + 1 < len(words) and _lookup(words[i + 1], lang):
            i += 1
            continue
        break
    if not seen:
        return Decimal(0), 0
    value = total + current
    i = start + used
    # Decimal part: "eighteen point five", "achtzehn Komma fünf"
    if i + 1 < len(words) and words[i] in _POINT:
        digits = []
        j = i + 1
        while j < len(words):
            hit = _lookup(words[j], lang)
            if hit is None or hit[0] != "unit" or hit[1] > 9:
                break
            digits.append(str(int(hit[1])))
            j += 1
        if digits:
            value = Decimal(f"{int(value)}.{''.join(digits)}")
            used = j - start
            i = j
    # Fractions after the number: "and a half", "з половиною", "and three quarters"
    tail = words[i : i + 4]
    if lang == "en":
        if tail[:3] == ["and", "a", "half"]:
            return value + HALF, used + 3
        if tail[:3] == ["and", "a", "quarter"]:
            return value + Decimal("0.25"), used + 3
        if tail[:3] == ["and", "three", "quarters"]:
            return value + Decimal("0.75"), used + 3
    if lang == "uk" and tail[:2] == ["з", "половиною"]:
        return value + HALF, used + 2
    if lang == "de" and tail[:1] == ["einhalb"]:
        return value + HALF, used + 1
    return value, used


def _digits_value(raw: str) -> Decimal | None:
    """ "1,200" → 1200 · "1.200" → 1200 · "18.5" / "18,5" → 18.5."""
    parts = re.split(r"[.,]", raw)
    try:
        if len(parts) == 1:
            return Decimal(raw)
        # Groups of exactly three after the first: thousands separators.
        if all(len(p) == 3 for p in parts[1:]) and len(parts[0]) <= 3:
            return Decimal("".join(parts))
        if len(parts) == 2:
            return Decimal(f"{parts[0]}.{parts[1]}")
    except InvalidOperation:
        return None
    return None


def digit_numbers(text: str) -> list[Decimal]:
    out: list[Decimal] = []
    for raw in _DIGITS.findall(text):
        value = _digits_value(raw)
        if value is not None:
            out.append(value)
    return out


def numbers_in(text: str, language: str = "en") -> list[Decimal]:
    """Every number in ``text``: digits and words, normalised."""
    return [*digit_numbers(text), *number_words(text, language)]


def parse_value(value: str, language: str = "en") -> Decimal | None:
    """One value as the model wrote it: digits, words, or both ("18.5",
    "just under three hundred"). None when it holds no number or more
    than one."""
    found = numbers_in(value, language)
    if not found:
        return None
    distinct = set(found)
    return found[0] if len(distinct) == 1 else None


def said(value: Decimal, text: str, language: str = "en") -> bool:
    """``value`` occurs in ``text`` as digits or as words."""
    return any(n == value for n in numbers_in(text, language))


def display(value: Decimal) -> str:
    """18.50 → "18.5", 300 → "300", 1200 → "1,200"."""
    normal = value.normalize()
    if normal == normal.to_integral_value():
        return f"{int(normal):,}"
    return format(normal, "f")
