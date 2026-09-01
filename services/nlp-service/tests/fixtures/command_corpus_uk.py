"""Labeled TP/FP corpus for the voice-command matcher.

**As-built note.** The original gate suite
(`tests/unit/test_voice_command_matcher.py`) exercises pause,
confidence, edit-distance and ambiguity individually — valuable, but it
reports no precision number, so "targets still hold" had nothing to
measure against.

This file is that corpus, built so the seeding of the typed-field
command specs can be shown not to degrade matching. It is measured
twice in `test_command_corpus.py`: once with the base catalogue alone
(the BASELINE) and once with the typed-field commands added (the
AFTER). Both must hit 100% on these cases; the point is that the two
runs are compared, so any future spec that starts eating ordinary
prose fails loudly.

`POSITIVES` — an utterance that MUST produce the given intent.
`NEGATIVES` — ordinary prose that must produce NO command at all. The
negatives are the ones that matter: a false positive silently deletes
words from a note.
"""

from __future__ import annotations

# (spoken words, expected intent or None, why)
POSITIVES: list[tuple[list[str], str, str]] = [
    # ── base catalogue commands ────────────────────────────────────
    (["новий", "абзац"], "newparagraph", "canonical two-word command"),
    (["крапка"], "period", "single-word punctuation"),
    (["кома"], "comma", "single-word punctuation"),
    (["знак", "питання"], "question_mark", "two-word punctuation"),
    (["зберегти", "чернетку"], "save_draft", "editor command"),
    (["скасувати", "останнє"], "undo_last", "editor command"),
    (["кінець", "диктування"], "stop_dictation", "session command"),
    (["тире"], "dash", "single-word punctuation"),
    (["двокрапка"], "colon", "single-word punctuation"),
    (["новий", "рядок"], "newline", "two-word command"),
    # ── typed-field commands ───────────────────────────────────────
    (["обрати", "підписана"], "choice.set", "set by alias"),
    (["вибрати", "підписана"], "choice.set", "alternate head"),
    (["встановити", "не", "підписаний"], "choice.set", "multi-word option"),
    (["обрати", "не", "підписаний"], "choice.set", "negated option name"),
    (["додати", "імейл"], "choice.add", "multi_choice add"),
    (["прибрати", "імейл"], "choice.remove", "multi_choice remove"),
    (["видалити", "телефон"], "choice.remove", "alternate remove head"),
]

# Ordinary prose that must NEVER trigger a command. Several deliberately
# contain command HEADS in ordinary Ukrainian usage — that is the whole
# point: "обрати" is a perfectly normal verb.
NEGATIVES: list[tuple[list[str], str]] = [
    (["клієнту", "складно", "обрати", "зручний", "тариф"], "'обрати' as ordinary verb"),
    (["важко", "вибрати", "оптимальну", "пропозицію"], "'вибрати' as ordinary verb"),
    (["рекомендовано", "додати", "розділ", "до", "звіту"], "'додати' as ordinary verb"),
    (["слід", "прибрати", "надмірне", "навантаження"], "'прибрати' as ordinary verb"),
    (["потрібно", "видалити", "дублікати"], "'видалити' as ordinary action"),
    (["встановити", "пріоритет", "поки", "неможливо"], "command heads inside prose"),
    (["зауваження", "щодо", "головного", "розділу"], "plain business prose"),
    (["бюджет", "проєкту", "стабільний"], "plain business prose"),
    (["клієнт", "підписаний", "багато", "років"], "option name without a command head"),
    (["зв'язок", "через", "імейл"], "option name without a command head"),
    (["призначено", "новий", "термін"], "'новий' without its command partner"),
    (["огляд", "без", "зауважень"], "plain business prose"),
]
