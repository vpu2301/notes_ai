"""Who a diarizer label is: a real name against a label, and the names people call
each other by (Task 4 address cues). Names speakers; writes nothing. Pure.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final

from .text import ALL_STOP, casefold

_DEFAULT_SPEAKER: Final = re.compile(
    r"(?i)^(?:speaker[ _]?\d+|unknown(?: speaker)?|sprecher(?:in)? \d+|SPEAKER_\d+)$"
)


def real_name(name: str | None) -> str | None:
    """A person's name — never a diarizer label, a default name or a bare number ("1")."""
    name = (name or "").strip()
    if not name or _DEFAULT_SPEAKER.match(name) or not any(ch.isalpha() for ch in name):
        return None
    return name


_SPEAKER_WORD: Final[dict[str, str]] = {"en": "Speaker", "de": "Sprecher/in", "uk": "Спікер"}
_SPEAKER_NUMBER: Final = re.compile(r"(?i)^(?:speaker[ _]?|sprecher(?:in)? |SPEAKER_)?(\d+)$")


# A label as a note shows it, in any of the three languages.
_SPEAKER_DISPLAY: Final = re.compile(r"(?i)^(?:speaker|sprecher/in|спікер) \d+$")


def speaker_label(raw: str | None) -> str | None:
    """A diarizer label in its canonical form (``"Speaker 3"``): ``SPEAKER_3``, ``Speaker 3``,
    ``Sprecher 3`` all map to it; a real name or nothing → None."""
    raw = (raw or "").strip()
    if not raw or real_name(raw):
        return None
    number = _SPEAKER_NUMBER.match(raw)
    return f"Speaker {int(number.group(1))}" if number else None


def is_speaker_label(actor: str | None) -> bool:
    """A canonical or localized label (``Speaker 3``, ``Sprecher/in 3``, ``Спікер 3``)."""
    return bool(actor) and (
        _SPEAKER_DISPLAY.match(actor.strip()) is not None
        or _DEFAULT_SPEAKER.match(actor.strip()) is not None
    )


def display_actor(actor: str | None, language: str) -> str | None:
    """The holder as written after "laut"/"according to": a real name whole (never cut
    to its last word), a numbered label localized ("Sprecher/in 1"), else None."""
    name = real_name(actor)
    if name:
        return name
    number = _SPEAKER_NUMBER.match((actor or "").strip())
    if number:
        return f"{_SPEAKER_WORD.get(language, _SPEAKER_WORD['en'])} {number.group(1)}"
    return None


_TITLE_WORDS: Final = (
    r"(?:Council\s?member|Councilwoman|Councilman|Council President|President|Vice President"
    r"|Chair(?:man|woman|person)?|Mayor|Senator|Representative|Commissioner|Director|Secretary"
    r"|Madam|Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Prof\.?|Professor"
    r"|Herr|Frau|Bürgermeister(?:in)?|Stadtrat|Stadträtin|Abgeordnete[rn]?"
    r"|пане|пан|пані|депутате|депутат|голово|голова|директоре|директор|професоре|професор|докторе|доктор)"
)
_CUE_NAME: Final = (
    rf"(?P<name>(?:{_TITLE_WORDS}\s+)?[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+(?:\s+[A-ZÄÖÜА-ЯІЇЄҐ][\w'’-]+){{0,2}})"
)
# The chair calling on somebody: the NEXT turn's voice is that person.
_CALL_ON: Final[dict[str, re.Pattern[str]]] = {
    "en": re.compile(
        rf"^{_CUE_NAME},\s+(?:will you|would you|could you|can you|please|you have the floor"
        r"|go ahead|the floor is yours|you're recognized|you are recognized|your motion)",
    ),
    "de": re.compile(
        rf"^{_CUE_NAME},\s+(?:bitte|Sie haben das Wort|würden Sie|könnten Sie|Sie sind dran)",
    ),
    "uk": re.compile(rf"^{_CUE_NAME},\s+(?:будь ласка|вам слово|прошу|ваша черга)"),
}
# Thanks after a turn: the PREVIOUS turn's voice is that person.
_THANKS: Final[dict[str, re.Pattern[str]]] = {
    "en": re.compile(rf"^(?:Thank you|Thanks),?\s+{_CUE_NAME}(?![\w'’-])"),
    "de": re.compile(rf"^(?:Vielen Dank|Danke(?: schön| sehr)?),?\s+{_CUE_NAME}(?![\w'’-])"),
    "uk": re.compile(rf"^(?:Дякую|Дякуємо|Щиро дякую),?\s+{_CUE_NAME}(?![\w'’-])"),
}
# A self-introduction: THIS turn's voice is that person.
_SELF: Final[dict[str, re.Pattern[str]]] = {
    "en": re.compile(
        rf"(?:^|[.!?]\s+|,\s+)(?:this is|my name is|I am|I'm)\s+{_CUE_NAME}"
        r"(?=\s+(?:from|with|of|and|here|speaking|calling)\b|\s*[,.;])",
        re.IGNORECASE,
    ),
    "de": re.compile(
        rf"(?:^|[.!?]\s+|,\s+)(?:ich bin|mein Name ist|hier ist|hier spricht)\s+{_CUE_NAME}"
        r"(?=\s+(?:von|vom|aus|und)\b|\s*[,.;])",
        re.IGNORECASE,
    ),
    "uk": re.compile(
        rf"(?:^|[.!?]\s+|,\s+)(?:мене звати|мене звуть|я|це)\s+{_CUE_NAME}"
        r"(?=\s+(?:з|із|від|і|та)\b|\s*[,.;])",
        re.IGNORECASE,
    ),
}
_NOT_A_NAME: Final[frozenset[str]] = frozenset(
    {"everyone", "everybody", "all", "guys", "folks", "again", "so", "very", "much", "sir",
     "you", "there", "here", "alle", "allen", "euch", "ihnen", "всім", "вам", "тут"}
)  # fmt: skip
CUE_APPLY_CONFIDENCE: Final = 0.8
CUE_CONFLICT_CONFIDENCE: Final = 0.7
CALL_ON_GAP_MS: Final = 2000


def _cue_name(match: re.Match[str]) -> str | None:
    name = " ".join(match.group("name").split())
    words = [w.casefold().strip(".,") for w in name.split()]
    if not words or all(w in _NOT_A_NAME or w in ALL_STOP for w in words):
        return None
    return name if real_name(name) else None


def address_cues(turns: Sequence[Any], language: str) -> list[dict[str, Any]]:
    """``[{label, name, confidence, evidence_turn, pattern}]`` — who a diarizer label is,
    from three ways people address each other: the chair calling somebody on (the next
    turn, 0.9 when it starts within 2 s, else 0.75), thanks after a turn (the previous
    turn, 0.8) and a self-introduction (this turn, 0.7). Suggestions only; the caller
    resolves conflicts and decides what is applied."""
    lang = language if language in _CALL_ON else "en"
    out: list[dict[str, Any]] = []

    def cue(
        label: str | None, name: str | None, confidence: float, turn: Any, pattern: str
    ) -> None:
        if label and name:
            out.append(
                {
                    "label": label,
                    "name": name,
                    "confidence": confidence,
                    "evidence_turn": getattr(turn, "number", None),
                    "pattern": pattern,
                }
            )

    for i, turn in enumerate(turns):
        text = " ".join(str(turn.text).split())
        if not text:
            continue
        match = _CALL_ON[lang].match(text)
        if match and i + 1 < len(turns):
            after = turns[i + 1]
            if after.speaker_label and after.speaker_label != turn.speaker_label:
                gap = int(after.start_ms) - int(turn.end_ms)
                cue(
                    after.speaker_label,
                    _cue_name(match),
                    0.9 if gap <= CALL_ON_GAP_MS else 0.75,
                    turn,
                    "call_on",
                )
        match = _THANKS[lang].match(text)
        if match and i > 0:
            before = turns[i - 1]
            if before.speaker_label and before.speaker_label != turn.speaker_label:
                cue(before.speaker_label, _cue_name(match), 0.8, turn, "thanks")
        match = _SELF[lang].search(text[:300])
        if match:
            cue(turn.speaker_label, _cue_name(match), 0.7, turn, "self")
    return out


def resolve_cues(cues: Sequence[dict[str, Any]]) -> tuple[dict[str, tuple[str, float]], int]:
    """``({label: (name, confidence)}, conflicts)``: per label the best-supported name; a
    label with two different names (by last word) at ≥ 0.7 gets none and counts a conflict."""
    by_label: dict[str, dict[str, tuple[str, float]]] = {}
    for c in cues:
        key = casefold(str(c["name"]).split()[-1])
        best = by_label.setdefault(str(c["label"]), {})
        current = best.get(key)
        if current is None or float(c["confidence"]) > current[1]:
            best[key] = (str(c["name"]), float(c["confidence"]))
    names: dict[str, tuple[str, float]] = {}
    conflicts = 0
    for label, candidates in by_label.items():
        strong = [v for v in candidates.values() if v[1] >= CUE_CONFLICT_CONFIDENCE]
        if len(strong) > 1:
            conflicts += 1
            continue
        names[label] = max(candidates.values(), key=lambda v: v[1])
    return names, conflicts
