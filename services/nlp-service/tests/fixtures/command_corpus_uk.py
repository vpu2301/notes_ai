"""Labeled TP/FP corpus for the voice-command matcher, measured twice in `test_command_corpus.py`.

`POSITIVES` must produce the given intent; `NEGATIVES` (ordinary prose) must produce no command.
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
