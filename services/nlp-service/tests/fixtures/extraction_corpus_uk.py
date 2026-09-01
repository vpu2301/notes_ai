"""Labeled uk utterance corpus for choice/multi_choice extraction.

The extraction-safety contract in data form. Each case is
``(utterance, expected_value_or_None, why)`` — ``None`` means the
extractor MUST leave the field empty (prose preserved). Every negation
case is a case where filling the field would invert the meaning of the
note.

The options model a CRM-style intake template (subscription status +
preferred contact channels) — the same linguistic shapes the extractor
must survive in any business template: negated aliases that are their
own option, gendered verb forms, multi-token agent nouns, and
one-character inflection drift.
"""

from __future__ import annotations

from nlp_service.pipeline.base import ChoiceOption

SUBSCRIPTION_OPTIONS: tuple[ChoiceOption, ...] = (
    ChoiceOption(
        value="never",
        label="не підписаний",
        aliases=(
            "не підписаний",
            "не підписана",
            "ніколи не підписувався",
            "ніколи не підписувалась",
            "заперечує підписку",
            "never subscribed",
            "not subscribed",
        ),
    ),
    ChoiceOption(
        value="current",
        label="підписаний",
        aliases=(
            "підписаний",
            "підписана",
            "підписка",
            "активний підписник",
            "продовжує підписку",
            "active subscriber",
            "subscribed",
        ),
    ),
    ChoiceOption(
        value="former",
        label="підписаний у минулому",
        aliases=(
            "скасував підписку",
            "скасувала підписку",
            "відписався",
            "відписалась",
            "колишній підписник",
            "раніше підписаний",
            "ex-subscriber",
            "former subscriber",
        ),
    ),
)

CHANNEL_OPTIONS: tuple[ChoiceOption, ...] = (
    ChoiceOption(
        value="none_known",
        label="канали не вказані",
        aliases=(
            "канали не вказані",
            "без каналів",
            "каналів немає",
            "no known channels",
        ),
    ),
    ChoiceOption(
        value="email",
        label="імейл",
        aliases=("імейл", "електронна пошта", "email"),
    ),
    ChoiceOption(
        value="messengers",
        label="месенджери",
        aliases=("месенджери", "телеграм", "вайбер", "messengers"),
    ),
    ChoiceOption(
        value="phone",
        label="телефон",
        aliases=("телефон", "phone"),
    ),
    ChoiceOption(
        value="sms",
        label="смс",
        aliases=("смс", "текстові повідомлення", "sms"),
    ),
)

# ── choice: subscription status ─────────────────────────────────────
# (utterance, expected value or None, why)
SUBSCRIPTION_CASES: list[tuple[str, str | None, str]] = [
    # -- straightforward fills
    ("клієнт підписаний", "current", "bare alias, exact"),
    ("клієнт підписана", "current", "bare alias, gendered form"),
    ("замовник активний підписник", "current", "multi-token alias"),
    ("клієнт продовжує підписку", "current", "multi-token alias"),
    ("клієнт не підписаний", "never", "negated alias is its own option"),
    ("клієнт не підписана", "never", "negated alias is its own option"),
    ("ніколи не підписувався", "never", "long negated alias"),
    ("заперечує підписку", "never", "denial phrasing"),
    ("скасував підписку минулого року", "former", "alias + trailing detail"),
    ("скасувала підписку торік", "former", "gendered form"),
    ("колишній підписник", "former", "noun phrase"),
    ("раніше підписаний, зараз ні", "former", "alias with trailing clause"),
    # -- inflection tolerance (Levenshtein ≤ 1 on long tokens)
    ("клієнт підписани", "current", "one-char truncation of підписаний"),
    ("замовник підписаня", "current", "one-char variant of підписана"),
    ("скасував підписку", "former", "exact multi-token"),
    # -- nothing said about the subscription
    ("обговорення бюджету на наступний тиждень", None, "unrelated content"),
    ("", None, "empty text"),
    ("рахунок на сто сорок гривень", None, "unrelated numeric content"),
    # -- garbled beyond tolerance
    ("клієнт пдпсн", None, "garble, distance > 1"),
    ("клієнт підпррр", None, "garble, distance > 1"),
    # -- negation guard: the safety core
    ("не підписник", None, "negator before a non-negated alias blocks it"),
    ("без підписки", None, "'без' blocks"),
    ("заперечує підписаний", None, "negator token before bare alias blocks"),
]

# ── multi_choice: contact channels ──────────────────────────────────
# (utterance, expected set or None, why)
CHANNEL_CASES: list[tuple[str, set[str] | None, str]] = [
    ("зв'язок через імейл", {"email"}, "single channel"),
    (
        "зв'язок через імейл, телефон та телеграм",
        {"email", "phone", "messengers"},
        "three channels in one utterance",
    ),
    ("канали не вказані", {"none_known"}, "explicit none"),
    ("без каналів", {"none_known"}, "short phrasing for none"),
    (
        "каналів немає, окрім телефону",
        {"phone"},
        "none_known dropped when a positive entry is also present",
    ),
    ("написати у вайбер", {"messengers"}, "alias of the messenger group"),
    ("відповів на електронну пошту", {"email"}, "inflected multi-token alias"),
    ("обговорили бюджет проєкту", None, "nothing channel-related"),
    ("", None, "empty text"),
]
