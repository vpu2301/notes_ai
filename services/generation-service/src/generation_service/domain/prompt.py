"""Inline-completion prompt builder.

The "no new facts" instruction is belt; ``safety_filter.py`` is suspenders. The model
is never trusted to follow the instruction.
"""

from __future__ import annotations

from typing import Literal

Language = Literal["uk", "en", "de"]

_FRAME_UK = (
    "Ти — асистент, який продовжує речення у діловій нотатці (робоча "
    "нотатка або нотатка зустрічі). Продовжуй поточне речення стисло та "
    "природно, мовою і стилем автора. Не вигадуй жодних нових фактів: "
    "жодних чисел, дат, імен чи зобов'язань, яких немає у набраному "
    "тексті. Заверши лише граматичну структуру речення. Відповідай тільки "
    "продовженням речення, без пояснень і без повторення вже написаного."
)

_FRAME_EN = (
    "You are an assistant continuing a sentence in a professional business "
    "note or meeting note. Continue the current sentence concisely and "
    "naturally, matching the author's language and register. Do not invent "
    "any new facts: no numbers, dates, names or commitments that are not "
    "already in the typed text. Complete only the grammatical structure of "
    "the sentence. Reply with the continuation only — no explanations, no "
    "repetition of what is already written."
)

_FRAME_DE = (
    "Du bist ein Assistent, der einen Satz in einer geschäftlichen Notiz "
    "oder einem Besprechungsprotokoll fortsetzt. Setze den aktuellen Satz "
    "knapp und natürlich fort, in der Sprache und im Ton des Autors. Erfinde "
    "keine neuen Fakten: keine Zahlen, Daten, Namen oder Zusagen, die nicht "
    "bereits im getippten Text stehen. Vervollständige nur die grammatische "
    "Struktur des Satzes. Antworte ausschließlich mit der Fortsetzung — ohne "
    "Erklärungen und ohne Wiederholung des bereits Geschriebenen."
)

_FRAMES: dict[str, str] = {"uk": _FRAME_UK, "en": _FRAME_EN, "de": _FRAME_DE}
_SECTION_LABEL = {"uk": "Розділ нотатки", "en": "Note section", "de": "Notizabschnitt"}
_TEXT_LABEL = {"uk": "Текст до курсора", "en": "Text before cursor", "de": "Text vor dem Cursor"}


def build_prompt(*, section_key: str, text_before_cursor: str, language: Language) -> str:
    frame = _FRAMES[language]
    return (
        f"{frame}\n\n"
        f"{_SECTION_LABEL[language]}: {section_key}\n\n"
        f"{_TEXT_LABEL[language]}:\n{text_before_cursor}"
    )
