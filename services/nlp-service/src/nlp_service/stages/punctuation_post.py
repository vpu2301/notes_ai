"""Deterministic post-edits applied after punctuation (model or fallback)."""

from __future__ import annotations

import re

# Units dictated after numbers, lowercase canonical form.
_UNITS_UK = {
    "мг",
    "мл",
    "см",
    "м",
    "мм",
    "кг",
    "г",
    "л",
    "мкг",
    "мкл",
    "ммоль",
    "од",
    "хв",
    "сек",
}
_UNITS_EN = {
    "mg",
    "ml",
    "cm",
    "mm",
    "kg",
    "g",
    "l",
    "ug",
    "mcg",
    "mmol",
    "iu",
    "bpm",
}
_UNITS_DE = {
    "mg",
    "ml",
    "cm",
    "mm",
    "kg",
    "g",
    "l",
    "µg",
    "mcg",
    "mmol",
    "bpm",
}
# "IE" is deliberately absent from the German set: it is written upper-case.
_UNITS_BY_LANGUAGE = {"uk": _UNITS_UK, "en": _UNITS_EN, "de": _UNITS_DE}
_COMPOUND_UK = ["мм рт. ст.", "кг/м²", "м²", "г/л", "мг/кг"]
_COMPOUND_EN = ["mm hg", "mmhg", "kg/m²", "m²", "g/l", "mg/kg"]


def capitalize_first_letter(text: str) -> str:
    """Capitalize the first alphabetic character."""
    s = text.lstrip()
    if not s:
        return text
    return text[: len(text) - len(s)] + s[0].upper() + s[1:]


_SENTENCE_END = re.compile(r"([.!?])\s+([a-zäöüßа-яёіїєґ])", re.IGNORECASE | re.UNICODE)


def capitalize_post_punctuation(text: str) -> str:
    """After . ! ? + whitespace, force the next letter to uppercase."""

    def _up(match: re.Match[str]) -> str:
        return match.group(1) + " " + match.group(2).upper()

    return _SENTENCE_END.sub(_up, text)


_NUMBER_FOLLOWED_BY_WORD = re.compile(
    r"(\d+(?:[.,]\d+)?)\s+([A-Za-zÄÖÜäöüßА-Яа-яЁёІіЇїЄєҐґ]+)",
    re.UNICODE,
)


def lowercase_units_after_numbers(text: str, language: str) -> str:
    """Force a known unit after a number to its lowercase form (``"120 МГ"`` → ``"120 мг"``)."""
    units = _UNITS_BY_LANGUAGE.get(language, _UNITS_EN)

    def _conv(match: re.Match[str]) -> str:
        num, word = match.group(1), match.group(2)
        lc = word.lower()
        if lc in units:
            return f"{num} {lc}"
        return match.group(0)

    return _NUMBER_FOLLOWED_BY_WORD.sub(_conv, text)


_DOUBLES = re.compile(r"([.!?,])\s*\1+")


def strip_double_punctuation(text: str) -> str:
    """Collapse doubled punctuation (chunk boundaries, fallback period)."""
    return _DOUBLES.sub(r"\1", text)
