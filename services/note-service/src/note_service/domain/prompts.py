"""The prompt the note writer sends (Sprint P1, P2a): one system sentence in three
languages, a user message with the instructions (the workspace's saved text, else
``writer_templates/instructions.default.md``), the template and the transcript, a
continuation form for long recordings and the final merge. The rules live only in the
instructions text. ``PROMPT_VERSION`` changes whenever a text below or a file in
``writer_templates`` changes; ``fingerprint()`` is the hash a report pins.

Nothing here edits what the model writes; the texts are data.
"""

from __future__ import annotations

import hashlib
from typing import Final

PROMPT_VERSION: Final = "2026-10-21.2"

LANGUAGES: Final[tuple[str, ...]] = ("en", "de", "uk")
LANGUAGE_NAMES: Final[dict[str, str]] = {"en": "English", "de": "Deutsch", "uk": "українська"}

WRITER: Final[dict[str, str]] = {
    "en": (
        "You write the record of a recording for people who were not there. Follow the "
        "instructions, then the template, then write from the transcript. Write in {language}."
    ),
    "de": (
        "Du schreibst das Protokoll einer Aufnahme für Menschen, die nicht dabei waren. Folge "
        "den Anweisungen, dann der Vorlage, dann schreibe aus dem Transkript. Schreibe auf "
        "{language}."
    ),
    "uk": (
        "Ти пишеш запис розмови для людей, яких там не було. Дотримуйся вказівок, потім "
        "шаблону, потім пиши з транскрипту. Пиши {language}."
    ),
}

USER: Final[dict[str, str]] = {
    "en": (
        "{instructions}\n\n"
        "Template ({template_name}):\n{template}\n\n"
        "Transcript ({minutes} minutes, {speakers} speakers):\n{transcript}"
    ),
    "de": (
        "{instructions}\n\n"
        "Vorlage ({template_name}):\n{template}\n\n"
        "Transkript ({minutes} Minuten, {speakers} Sprechende):\n{transcript}"
    ),
    "uk": (
        "{instructions}\n\n"
        "Шаблон ({template_name}):\n{template}\n\n"
        "Транскрипт ({minutes} хвилин, {speakers} мовців):\n{transcript}"
    ),
}
UNKNOWN_DATE: Final[dict[str, str]] = {"en": "unknown", "de": "unbekannt", "uk": "невідома"}

CONTINUATION: Final[dict[str, str]] = {
    "en": (
        "The note so far:\n{note}\n\n"
        "Continue the note from the transcript below; add to existing sections where the "
        "topic continues, open new sections only from the template.\n\n"
        "Transcript ({minutes} minutes, continued):\n{transcript}"
    ),
    "de": (
        "Die Notiz bisher:\n{note}\n\n"
        "Setze die Notiz aus dem Transkript unten fort; ergänze bestehende Abschnitte, wo das "
        "Thema weitergeht, eröffne neue Abschnitte nur aus der Vorlage.\n\n"
        "Transkript ({minutes} Minuten, Fortsetzung):\n{transcript}"
    ),
    "uk": (
        "Нотатка досі:\n{note}\n\n"
        "Продовж нотатку за транскриптом нижче; доповнюй наявні розділи там, де тема триває, "
        "відкривай нові розділи лише з шаблону.\n\n"
        "Транскрипт ({minutes} хвилин, продовження):\n{transcript}"
    ),
}
MERGE: Final[dict[str, str]] = {
    "en": (
        "Here are the parts of the note written per window. Write the single final note in "
        "the template's order, merging sections with the same heading, keeping every "
        "timestamp.\n\nTemplate ({template_name}):\n{template}\n\n{parts}"
    ),
    "de": (
        "Hier sind die je Abschnitt der Aufnahme geschriebenen Teile der Notiz. Schreibe die "
        "eine endgültige Notiz in der Reihenfolge der Vorlage, führe Abschnitte mit gleicher "
        "Überschrift zusammen und behalte jede Zeitangabe.\n\nVorlage ({template_name}):\n"
        "{template}\n\n{parts}"
    ),
    "uk": (
        "Ось частини нотатки, написані по вікнах запису. Напиши одну остаточну нотатку в "
        "порядку шаблону, об'єднуючи розділи з однаковим заголовком і зберігаючи кожну "
        "позначку часу.\n\nШаблон ({template_name}):\n{template}\n\n{parts}"
    ),
}
# P3 — the optional check call: which numbered lines the transcript does not support.
CHECK: Final[dict[str, str]] = {
    "en": (
        "You check the record of a recording against the transcript it was written from. "
        "The record's lines are numbered. Name the lines the transcript does not support: a "
        "claim nobody made, a number, name, date or identifier that differs, something stated "
        "more firmly than it was said, or words given to the wrong person. Give one short "
        "reason per line, in the record's language. A line the transcript supports is not "
        "listed. A reporting clause that names who said something is not a new claim. Judge "
        "only; never rewrite a line. Answer as JSON: "
        '{"unsupported": [{"line": <number>, "reason": "<why>"}]}.'
    ),
    "de": (
        "Du prüfst das Protokoll einer Aufnahme gegen das Transkript, aus dem es geschrieben "
        "wurde. Die Zeilen des Protokolls sind nummeriert. Nenne die Zeilen, die das Transkript "
        "nicht stützt: eine Behauptung, die niemand aufgestellt hat, eine abweichende Zahl, ein "
        "abweichender Name, ein abweichendes Datum oder eine abweichende Kennung, etwas "
        "Bestimmteres als gesagt, oder Worte der falschen Person zugeschrieben. Gib je Zeile "
        "einen kurzen Grund in der Sprache des Protokolls. Eine gestützte Zeile wird nicht "
        "genannt. Eine Redeeinleitung, die nennt, wer etwas gesagt hat, ist keine neue "
        "Behauptung. Nur urteilen; nie eine Zeile umschreiben. Antworte als JSON: "
        '{"unsupported": [{"line": <Nummer>, "reason": "<Grund>"}]}.'
    ),
    "uk": (
        "Ти перевіряєш запис розмови за транскриптом, з якого його написано. Рядки запису "
        "пронумеровано. Назви рядки, яких транскрипт не підтверджує: твердження, якого ніхто "
        "не робив; число, ім'я, дату чи ідентифікатор, що відрізняються; щось сказане "
        "упевненіше, ніж було; слова, приписані не тій особі. На кожен рядок — одна коротка "
        "причина мовою запису. Підтверджений рядок не називай. Вступ, що називає, хто щось "
        "сказав, — не нове твердження. Лише оцінюй; ніколи не переписуй рядок. Відповідай у "
        'JSON: {"unsupported": [{"line": <номер>, "reason": "<чому>"}]}.'
    ),
}
CHECK_USER: Final[dict[str, str]] = {
    "en": "Record:\n{lines}\n\nTranscript:\n{transcript}",
    "de": "Protokoll:\n{lines}\n\nTranskript:\n{transcript}",
    "uk": "Запис:\n{lines}\n\nТранскрипт:\n{transcript}",
}

PART_HEADER: Final[dict[str, str]] = {
    "en": "--- part {n} of {total} ---",
    "de": "--- Teil {n} von {total} ---",
    "uk": "--- частина {n} з {total} ---",
}
# The one line code writes into a note: the merge failed and the parts follow in order.
MERGE_FAILED: Final[dict[str, str]] = {
    "en": "(merge failed — parts in order)",
    "de": "(Zusammenführung fehlgeschlagen — Teile in Reihenfolge)",
    "uk": "(об'єднання не вдалося — частини по порядку)",
}


def language_of(code: str | None) -> str:
    return code if code in LANGUAGES else "en"


def fingerprint() -> str:
    """sha256 over every text above and the files in ``writer_templates`` (a template or
    default-instructions change is a prompt change), so a report pins what was sent."""
    from importlib import resources

    folder = resources.files(__package__).joinpath("writer_templates")
    templates = "\n".join(
        f"{entry.name}:{entry.read_text('utf-8')}"
        for entry in sorted(folder.iterdir(), key=lambda e: e.name)
        if entry.name.endswith(".md")
    )
    blob = (
        templates
        + "\n"
        + "\n".join(
            f"{name}:{lang}:{text}"
            for name, table in (
                ("writer", WRITER),
                ("user", USER),
                ("continuation", CONTINUATION),
                ("merge", MERGE),
                ("unknown_date", UNKNOWN_DATE),
                ("part", PART_HEADER),
                ("merge_failed", MERGE_FAILED),
                ("check", CHECK),
                ("check_user", CHECK_USER),
            )
            for lang, text in sorted(table.items())
        )
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
