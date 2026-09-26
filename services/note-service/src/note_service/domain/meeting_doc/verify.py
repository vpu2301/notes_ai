"""Where a claim becomes a fact, or is dropped.

The model proposes; this module disposes, in code, with no model
involved. That is the whole architecture: a small model asked to
summarise an hour of talk will invent an owner, shift a number and turn a
proposal into a decision, and no amount of prompting reliably stops it.
So every claim must survive four checks against the transcript itself:

1. **The quote must be real.** Normalised, it has to be a substring of
   the turn it cites — or, failing that, of the window. No match, no
   fact. This is the check that makes every other feature honest: the
   evidence chip, the client version, the eval's citation precision.
2. **The owner must be somebody who was there** — a speaker, a name
   candidate, or a capitalised token in the window. A first-person
   commitment takes the quote's own speaker. "We should…" takes nobody.
   An owner we cannot place is cleared, never guessed.
3. **The date must have been said.** `due_text` has to occur in the turn.
   It is then parsed with the same date logic the action-item projection
   uses, anchored on the meeting's date. Unparsed text is KEPT as text —
   "by end of quarter" is useful even though it is not a date — but a
   date nobody said is never written.
4. **The numbers must match.** Every number in the fact's text has to
   occur in its quote or turn. A number that does not is removed from the
   text and the fact is flagged, because a wrong figure in a meeting note
   is worse than a missing one.
5. **The text must mean what the quote says** (Summary Engine v2, Q2).
   The restatement has to share enough content with the words behind it
   (:mod:`support`) and may not introduce a name they do not have. An
   action, a decision or a fact with a number that fails is dropped;
   anything else is kept and flagged.

And one check on what the model set aside: a line it calls noise is
excluded only when code agrees (:func:`confirm_noise`). The model's flag
alone is advisory.

Plus one judgement call, also in code: a decision nobody agreed to is a
proposal, and is downgraded to a key point.

Pure. Facts and windows in, verified facts out.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, time
from typing import Final

from ..action_items import (
    _EXTRA_WEEKDAYS,
    _MONTHS,
    _PAST_RELATIVE,
    _RELATIVE,
    _WEEKDAYS,
    item_key,
    normalise_text,
    parse_when,
)
from ..glossary import Term
from . import entities, schema, support
from .entities import Correction
from .windows import Turn, Window

# ── Flags a verified fact can carry ─────────────────────────────────

NUMBER_UNVERIFIED: Final = "number_unverified"
OWNER_INFERRED: Final = "owner_inferred"
NO_OWNER: Final = "no_owner"
DUE_UNPARSED: Final = "due_unparsed"
SPEAKER_UNNAMED: Final = "speaker_unnamed"
LOW_ASR_CONFIDENCE: Final = "low_asr_confidence"
# Sprint 36 — a commitment we could not attribute to either side.
SIDE_UNKNOWN: Final = "side_unknown"
# Q2 — the text says more than, or other than, its quote.
PARAPHRASE_UNSUPPORTED: Final = "paraphrase_unsupported"
# Q4 — a name in the line was respelled (the quote keeps what was heard);
# an opinion or forecast whose holder is not among the participants.
ENTITY_CORRECTED: Final = "entity_corrected"
ATTRIBUTION_MISSING: Final = "attribution_missing"
# F2 — the text is the quote (or nearly all of it); the line speaks as
# I / we / you. Either fact is evidence behind other lines, never a line.
COPIED: Final = "copied"
FIRST_PERSON: Final = "first_person"

# Why a fact was dropped — counted in metrics and in the eval, never shown.
DROPPED_QUOTE: Final = "dropped_quote"
DOWNGRADED: Final = "downgraded"
KEPT: Final = "kept"

# How far either side of a decision's quote to look for somebody agreeing.
AGREEMENT_WINDOW_TURNS: Final = 3

# Confidence, per the concept: an explicit commitment with a verified
# owner and date is not the same thing as a flagged guess.
CONF_EXPLICIT: Final = 1.0
CONF_INFERRED: Final = 0.7
CONF_FLAGGED: Final = 0.5


@dataclass(slots=True)
class VerifiedFact:
    kind: str
    text: str
    quote: str
    turn: int
    start_ms: int
    end_ms: int
    speaker_label: str | None
    speaker_name: str | None
    owner_label: str | None = None
    due_text: str | None = None
    due_date: date | None = None
    explicit: bool = False
    confidence: float = CONF_INFERRED
    flags: list[str] = field(default_factory=list)
    window_index: int = 0
    """Sprint 36 — for `completion`: the carried item's key this finishes.
    Resolved from the model's 1-based list position, never from text."""
    refers_to_key: str | None = None
    """For `judgement`: which typed field this is a suggestion for. The
    value is in `text`. Only ever OFFERED to a person."""
    judgement_field: str | None = None
    """"ours" | "theirs" | None — which side owns a commitment."""
    side: str | None = None
    """How sure the speaker was (``schema.CERTAINTIES``), as the model
    read it. Carried so a forecast can be labelled as one; nothing
    renders it yet."""
    certainty: str | None = None
    """The line (piece) the quote was found on; ``turn`` stays the
    original turn's index. Q2."""
    line: int | None = None
    """Q3 — the date expressions in the QUOTE, resolved against the
    recording day with the tense they were said in. An annotation: text
    and quote keep the spoken words."""
    mentions: tuple[DateMention, ...] = ()
    """Q4 — who holds the position (verified like an owner; the speaker for
    their own opinion), and the names respelled in ``text`` — never in
    ``quote``."""
    attributed_to: str | None = None
    corrections: tuple[Correction, ...] = ()
    """F2 — ``text`` is its quote copied: a real quote, kept to be cited,
    never rendered as a line of its own."""
    copied: bool = False

    @property
    def evidence_only(self) -> bool:
        """F2 — kept as evidence behind other lines, never a line itself:
        the text copies the transcript or speaks in its voice."""
        return self.copied or FIRST_PERSON in self.flags

    @property
    def salient(self) -> bool:
        """Q4 — carries something a reader looks for: a number, a date, or a
        person holding it. Such a fact is kept in the document whatever the
        reduce step chose to write about."""
        return bool(
            _NUMBER.search(self.text) or self.mentions or self.attributed_to or self.owner_label
        )

    @property
    def item_key(self) -> str:
        """The same hash the recipient loop, the corrections routes and
        the carried items use — one identity for a line, everywhere."""
        return item_key(normalise_text(self.text))


# ── Quote matching ──────────────────────────────────────────────────

_PUNCT = re.compile(r"[^\w\s']", re.UNICODE)
_SPACE = re.compile(r"\s+")


# Sprint I3 T3: the fillers nlp-service hides from a conversation's displayed
# text (tests/fixtures/nlp/fillers.json). Dropped here too, so a quote taken
# from the displayed text still matches the raw one and vice versa.
FILLERS: Final[frozenset[str]] = frozenset(
    {
        "uh",
        "um",
        "erm",
        "er",
        "hmm",
        "hm",
        "mm",
        "mhm",
        "ah",
        "eh",
        "uh-huh",
        "äh",
        "ähm",
        "öh",
        "öhm",
        "mh",
        "е",
        "ем",
        "мм",
        "ммм",
        "хм",
        "е-е",
        "а-а",
    }
)
_QUOTE_EDGE = "'\"“”„«».,;:!?"


def normalise_quote(text: str) -> str:
    """The comparison form: NFKC, case-folded, punctuation dropped
    (apostrophes kept — "I'll" is not "Ill"), fillers dropped, whitespace
    collapsed.

    Mirrors ``scripts/eval/smoke_eval._quote`` so the harness and the
    pipeline agree about what counts as a match.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = folded.replace("’", "'").replace("‘", "'")
    # Hyphenated fillers ("uh-huh") are matched before punctuation goes.
    kept = [tok for tok in _SPACE.split(folded) if tok.strip(_QUOTE_EDGE) not in FILLERS]
    tokens = _PUNCT.sub(" ", " ".join(kept)).split()
    return " ".join(tok for tok in tokens if tok not in FILLERS)


def locate_quote(quote: str, window: Window, cited_line: int) -> Turn | None:
    """The line (piece) a quote actually came from, or None.

    The cited line is tried first — the model usually gets it right, and
    trusting it keeps the timestamp precise. Failing that, any line in
    the window: a model that cites line 7 for words said on line 8 is
    wrong about the number, not lying about the words — and the fact
    takes the timestamps of the piece that holds them.
    """
    # A small model copies the turn header — "[0] Speaker 1 (00:00): " —
    # into the quote as readily as into the text. The words after it are
    # what was said; the header is ours.
    needle = normalise_quote(strip_turn_header(quote))
    if len(needle.split()) < schema.MIN_QUOTE_WORDS:
        return None
    turn = window.turn(cited_line)
    if turn is not None and needle in normalise_quote(turn.text):
        return turn
    for candidate in window.turns:
        if needle in normalise_quote(candidate.text):
            return candidate
    return None


# ── Owners ──────────────────────────────────────────────────────────

# "I'll send it", "I will", "ich schicke", "я надішлю" — the speaker
# taking it on. Deliberately narrow: a false positive here puts a task on
# the wrong person's name.
_FIRST_PERSON = re.compile(
    r"\b(?:i'?ll|i will|i'?m going to|i can|i'?ve got|let me|"
    r"ich werde|ich mache|ich schicke|ich kümmere|"
    r"я зроблю|я надішлю|я візьму|я підготую)\b",
    re.IGNORECASE,
)
# "we should", "somebody needs to" — the room agreeing work exists.
_NO_TAKER = re.compile(
    r"\b(?:we should|we need to|someone should|somebody needs to|"
    r"wir sollten|man müsste|man sollte|"
    r"треба|потрібно|хтось має)\b",
    re.IGNORECASE,
)
_CAPITALISED = re.compile(r"\b([A-ZА-ЯІЇЄҐÄÖÜ][\w'’\-]{1,29})\b")


def resolve_owner(
    proposed: str | None,
    *,
    quote: str,
    turn: Turn,
    window: Window,
    name_candidates: frozenset[str] = frozenset(),
) -> tuple[str | None, bool, list[str]]:
    """``(owner, explicit, flags)``.

    Order matters. A first-person commitment is the strongest signal
    there is and beats whatever the model proposed; "we should" is the
    strongest signal that there is NO owner, and also beats it.
    """
    if _FIRST_PERSON.search(quote):
        speaker = turn.speaker_name or turn.speaker_label
        if turn.speaker_name:
            return turn.speaker_name, True, []
        # Someone took it on, but we do not know their name yet. Keep the
        # commitment, flag it, and let the author name the speaker.
        return speaker, True, [SPEAKER_UNNAMED]

    if _NO_TAKER.search(quote):
        return None, False, [NO_OWNER]

    if not proposed:
        return None, False, [NO_OWNER]

    candidate = " ".join(proposed.split())[:60]
    folded = candidate.casefold()
    known = {(t.speaker_name or "").casefold() for t in window.turns if t.speaker_name} | {
        n.casefold() for n in name_candidates
    }
    if folded in known:
        return candidate, False, [OWNER_INFERRED]

    # A capitalised token actually present in the window: people are
    # named in the third person all the time ("Tom will send it").
    present = {m.group(1).casefold() for m in _CAPITALISED.finditer(window.text)}
    if folded in present or all(part.casefold() in present for part in candidate.split()):
        return candidate, False, [OWNER_INFERRED]

    # Nobody by that name was in this window. Clearing beats guessing.
    return None, False, [NO_OWNER]


# ── Dates and numbers ───────────────────────────────────────────────

_NUMBER = re.compile(r"\d[\d.,]*")


def resolve_due(
    due_text: str | None, *, turn: Turn, meeting_date: date, quote: str = "", language: str = "en"
) -> tuple[str | None, date | None, list[str]]:
    """``(due_text, due_date, flags)`` — a date nobody said is never written.
    Resolved in the direction the quote was said in (Q3)."""
    if not due_text or not due_text.strip():
        return None, None, []
    text = " ".join(due_text.split())[:120]
    if normalise_quote(text) not in normalise_quote(turn.text):
        # The model produced a deadline that was not spoken.
        return None, None, []
    when = parse_when(text, anchor=meeting_date, direction=direction_of(quote, language, text))
    parsed = when.date if when else None
    return text, parsed, [] if parsed else [DUE_UNPARSED]


# ── Date mentions (Q3) ──────────────────────────────────────────────

# Words that put a date in the past when they stand near it. Within
# PAST_CUE_TOKENS of the date expression, not anywhere in the quote: "we
# had agreed to ship on Friday" is ambiguous, "am Montag gewesen" is not.
_PAST_CUES: Final[frozenset[str]] = frozenset(
    [
        "gewesen",
        "war",
        "waren",
        "hatte",
        "hatten",
        "gestern",
        "letzte",
        "letzten",
        "vergangene",
        "vergangenen",
        "was",
        "were",
        "had",
        "yesterday",
        "last",
        "ago",
        "був",
        "була",
        "було",
        "були",
        "минулого",
        "вчора",
        "учора",
    ]
)
PAST_CUE_TOKENS: Final = 6


@dataclass(frozen=True, slots=True)
class DateMention:
    """A date expression as it was said, and what it means."""

    text: str
    resolved: date
    time: time | None
    direction: str

    def iso(self) -> str:
        """``2026-09-23`` or ``2026-09-23T00:00`` — what the eval compares."""
        return self.resolved.isoformat() + (f"T{self.time:%H:%M}" if self.time else "")


def direction_of(quote: str, language: str = "en", expression: str | None = None) -> str:
    """``past`` when a past-tense cue stands within PAST_CUE_TOKENS of the
    date expression (anywhere in the quote when none is given), else
    ``future``."""
    words = normalise_quote(quote).split()
    if not words:
        return "future"
    if expression:
        target = normalise_quote(expression).split()
        at = next((i for i in range(len(words)) if words[i : i + len(target)] == target), None)
        if at is None:
            return "past" if _PAST_CUES & set(words) else "future"
        lo, hi = max(0, at - PAST_CUE_TOKENS), at + len(target) + PAST_CUE_TOKENS
        return "past" if _PAST_CUES & set(words[lo:hi]) else "future"
    return "past" if _PAST_CUES & set(words) else "future"


_PREPOSITIONS: Final[frozenset[str]] = frozenset(
    [
        "am",
        "bis",
        "on",
        "by",
        "until",
        "at",
        "seit",
        "ab",
        "vom",
        "zum",
        "у",
        "в",
        "до",
        "з",
        "next",
        "nächsten",
        "nächste",
        "kommenden",
    ]
)
_TIME_WORDS: Final[frozenset[str]] = frozenset(
    ["uhr", "h", "mitternacht", "midnight", "опівночі", "північ", "am", "pm", "o'clock"]
)
# "Guten Morgen" is a greeting, not tomorrow.
_NOT_A_DATE_AFTER: Final[dict[str, frozenset[str]]] = {
    "morgen": frozenset({"guten", "gut", "schönen", "heute"}),
}


def date_mentions(quote: str, *, meeting_date: date, language: str = "en") -> list[DateMention]:
    """Every date expression in ``quote`` that resolves, with its tense.
    The quote only: a fact's evidence is its words."""
    words = normalise_quote(quote).split()
    out: list[DateMention] = []
    used: set[int] = set()
    relative = sorted({*_RELATIVE, *_PAST_RELATIVE}, key=lambda p: -len(p.split()))
    weekdays = {*_WEEKDAYS, *_EXTRA_WEEKDAYS}

    def add(start: int, end: int) -> None:
        if any(i in used for i in range(start, end)):
            return
        # A preposition before and a clock time after belong to it.
        core = start
        if start > 0 and words[start - 1] in _PREPOSITIONS:
            start -= 1
        tail = end
        while tail < min(len(words), end + 3) and (
            words[tail].isdigit() or words[tail] in _TIME_WORDS
        ):
            tail += 1
        if tail > end and any(w in _TIME_WORDS for w in words[end:tail]):
            end = tail
        text = " ".join(words[start:end])
        direction = direction_of(quote, language, text)
        when = parse_when(text, anchor=meeting_date, direction=direction)
        if when is None and start < core:
            # "seit heute": the preposition belongs to the mention, not the date.
            when = parse_when(" ".join(words[core:end]), anchor=meeting_date, direction=direction)
        if when is None:
            return
        used.update(range(start, end))
        out.append(DateMention(text, when.date, when.time, when.direction))

    for i in range(len(words)):
        for phrase in relative:
            size = len(phrase.split())
            if " ".join(words[i : i + size]) == phrase:
                blockers = _NOT_A_DATE_AFTER.get(phrase, frozenset())
                if not (i > 0 and words[i - 1] in blockers):
                    add(i, i + size)
                break
        else:
            if words[i] in weekdays:
                add(i, i + 1)
            elif words[i].isdigit() and i + 1 < len(words) and words[i + 1] in _MONTHS:
                add(i, i + 2)
    return out


def check_numbers(text: str, *, quote: str, turn: Turn) -> tuple[str, list[str]]:
    """Every number in the text must have been said.

    A number that was not is REMOVED from the text rather than the whole
    fact being dropped: "they want it by the twentieth" is still worth
    having when the model hallucinated a price alongside it.
    """
    said = normalise_quote(f"{quote} {turn.text}")
    said_numbers = {n.replace(",", "").replace(".", "") for n in _NUMBER.findall(said)}
    flags: list[str] = []
    out = text
    for match in _NUMBER.findall(text):
        plain = match.replace(",", "").replace(".", "")
        if plain and plain not in said_numbers:
            out = out.replace(match, "").replace("  ", " ")
            flags.append(NUMBER_UNVERIFIED)
    return out.strip(), flags[:1]


# ── Decision vs proposal ────────────────────────────────────────────

# Words that commit, not words that keep a conversation going. "Yes",
# "okay", "passt" and "добре" used to be here; in an interview or a
# lively meeting they open half the turns ("Ja, aber…", "Okay, but…"),
# and every proposal near one became a decision.
_AGREEMENT = re.compile(
    r"\b(?:agreed|agree|deal|sounds good|let'?s do|let'?s go with|we'?ll go with|"
    r"fine by me|works for me|"
    r"einverstanden|abgemacht|machen wir|beschlossen|"
    r"домовились|погоджуюсь|вирішили)\b",
    re.IGNORECASE,
)
_DECIDED = re.compile(
    r"\b(?:we (?:have )?decided|it'?s decided|we'?re going with|final decision|"
    r"wir haben beschlossen|beschlossen|wir entscheiden uns|"
    r"ми вирішили|вирішили|ухвалили)\b",
    re.IGNORECASE,
)


def is_copied(text: str, quote: str) -> bool:
    """The model put the quote (or nearly all of it) into `text`.

    A verbatim sentence is evidence, not a statement; under "Decisions"
    it reads as somebody's aside ("Man war sehr zögerlich…") filed as an
    outcome.
    """
    said, claim = normalise_quote(strip_turn_header(quote)), normalise_quote(text)
    if not claim or not said:
        return False
    return claim == said or (claim in said and len(claim) >= 0.8 * len(said))


def is_decision(quote: str, *, turn: Turn, window: Window) -> bool:
    """A decision is something the room agreed to.

    Either the words say so outright ("we decided"), or a DIFFERENT
    speaker agrees within a few turns. A proposal one person made and
    nobody answered is a key point — writing it under "Decisions" is how
    a meeting note becomes something the reader stops trusting.
    """
    if _DECIDED.search(quote):
        return True
    turns = list(window.turns)
    try:
        position = next(i for i, t in enumerate(turns) if t.index == turn.index)
    except StopIteration:
        return False

    # The commonest shape by far: Anna proposes, Tom says "agreed, let's
    # go with that". The agreement marker is in the QUOTE itself, and the
    # second speaker is the one being quoted. Looking only at other
    # turns would call this a proposal and file a real decision under
    # "Topics".
    if _AGREEMENT.search(quote):
        earlier = turns[max(0, position - AGREEMENT_WINDOW_TURNS) : position]
        if any(t.speaker_label != turn.speaker_label for t in earlier):
            return True

    lo = max(0, position - AGREEMENT_WINDOW_TURNS)
    hi = min(len(turns), position + AGREEMENT_WINDOW_TURNS + 1)
    for other in turns[lo:hi]:
        if other.index == turn.index:
            continue
        if other.speaker_label != turn.speaker_label and _AGREEMENT.search(other.text):
            return True
    return False


# ── The pass itself ─────────────────────────────────────────────────


@dataclass(slots=True)
class VerifyStats:
    kept: int = 0
    dropped_quote: int = 0
    """Facts quoted from a turn the extractor flagged as not part of the
    conversation (background speech, another language, an artifact)."""
    dropped_noise: int = 0
    dropped_owner: int = 0
    downgraded: int = 0
    numbers_removed: int = 0
    invented_due: int = 0
    """Q2 — facts whose text did not mean what their quote said: dropped
    (an action, a decision, a number) or kept and flagged."""
    dropped_paraphrase: int = 0
    flagged_paraphrase: int = 0
    """Q4 — names respelled by source, marked "(?)", and attributions."""
    corrected: dict[str, int] = field(default_factory=dict)
    marked: int = 0
    attribution_model: int = 0
    attribution_speaker: int = 0
    attribution_missing: int = 0
    """Facts whose text repeats a prompt example (Q1): the model copied
    its instructions, not the recording."""
    dropped_example: int = 0
    """F2 — facts whose text is their quote (kept as evidence only); facts
    that inform nobody (dropped, not stored); facts in the transcript's
    voice (evidence only) and the openers code dropped to fix one."""
    copied: int = 0
    dropped_no_information: int = 0
    dropped_first_person: int = 0
    third_person_fixed: int = 0


# The window shows each turn as "[3] Anna (00:12): …". A small model
# sometimes copies that header — often with the numbers left blank,
# "[] Anna (:): …" — into `text`, which is meant to be the claim alone.
_TURN_HEADER: Final = re.compile(r"^\s*\[\d*\]\s*[^\[\]():\n]{0,80}?\s*\(\d{0,2}:?\d{0,2}\):\s*")


def strip_turn_header(text: str) -> str:
    """A fact's text without an echoed transcript turn header."""
    return _TURN_HEADER.sub("", text, count=1).strip()


def verify_facts(
    facts: list[schema.Fact],
    *,
    window: Window,
    meeting_date: date,
    name_candidates: frozenset[str] = frozenset(),
    stats: VerifyStats | None = None,
    allowed_kinds: frozenset[str] | None = None,
    judgement_fields: frozenset[str] = frozenset(),
    carried_keys: tuple[str, ...] = (),
    our_side: frozenset[str] = frozenset(),
    noise_lines: frozenset[int] = frozenset(),
    language: str = "en",
    glossary: tuple[Term, ...] = (),
) -> list[VerifiedFact]:
    """One window's claims, checked. Anything that fails is dropped.

    ``allowed_kinds`` is the family's set (Sprint 36): a model that
    answers with a kind this family does not have is answering about a
    different document, and the fact is dropped rather than filed
    somewhere arbitrary.

    ``noise_lines`` are the CONFIRMED exclusions (:func:`confirm_noise`),
    never the model's raw flags.
    """
    # Imported here: prompts builds its phrase set with this module's
    # normaliser, so a top-level import would be circular.
    from .prompts import echoes_example

    stats = stats or VerifyStats()
    allowed = allowed_kinds or frozenset(schema.FACT_KINDS)
    out: list[VerifiedFact] = []
    for fact in facts:
        if fact.kind not in allowed or not fact.text.strip():
            stats.dropped_quote += 1
            continue
        if echoes_example(fact.text):
            stats.dropped_example += 1
            continue
        turn = locate_quote(fact.quote, window, fact.turn)
        if turn is None:
            stats.dropped_quote += 1
            continue
        if turn.number in noise_lines:
            # Code confirmed this line is not the conversation, and the
            # model quoted it anyway. A fact from background speech is
            # worse than no fact.
            stats.dropped_noise += 1
            continue

        kind = fact.kind

        # A judgement suggestion is only ever a suggestion, and only for
        # a field this family actually has. It is never written to the
        # field: a person accepts it, or it stays a row nobody acted on.
        judgement_field: str | None = None
        if kind == schema.JUDGEMENT:
            if not fact.field or fact.field not in judgement_fields:
                stats.dropped_quote += 1
                continue
            judgement_field = fact.field

        # A completion may only point at an item we already had, by its
        # position in the list the prompt was given.
        refers_to_key: str | None = None
        if kind == schema.COMPLETION:
            index = (fact.refers_to or 0) - 1
            if not (0 <= index < len(carried_keys)):
                stats.dropped_quote += 1
                continue
            refers_to_key = carried_keys[index]

        # F2 — a copy is evidence, not a statement, whatever its kind. A
        # copied decision is not a decision (it is somebody's words filed
        # as an outcome) and is also not rendered.
        copied = is_copied(fact.text, fact.quote)
        if kind == schema.DECISION and (
            not is_decision(fact.quote, turn=turn, window=window) or copied
        ):
            kind = schema.KEY_POINT
            stats.downgraded += 1

        text, number_flags = check_numbers(
            strip_turn_header(fact.text), quote=fact.quote, turn=turn
        )
        if not text:
            stats.dropped_quote += 1
            continue
        if number_flags:
            stats.numbers_removed += 1

        # F2 — information is checked in code. A remark that informs nobody
        # ("This boat is incredible.") is not a fact and not evidence of one.
        if not support.carries_information(
            text,
            language,
            short_ok=kind in _SHORT_KINDS,
            has_date=_has_date_word(text),
        ):
            stats.dropped_no_information += 1
            continue
        voice_flags: list[str] = []
        if not copied and kind not in _TASK_KINDS:
            fixed = support.mechanical_third_person(text)
            if fixed is not None:
                text = fixed
                stats.third_person_fixed += 1
            if support.first_person(text, language):
                voice_flags = [FIRST_PERSON]
                stats.dropped_first_person += 1
        if copied:
            stats.copied += 1

        # Q4, tier (a): names the workspace knows, spelled its way — in the
        # text only. The quote keeps what the transcriber heard.
        people = frozenset(
            {t.speaker_name for t in window.turns if t.speaker_name}
            | set(name_candidates)
            | {g.term for g in glossary if g.kind == "person"}
        )
        text, corrections, marked = _correct(text, glossary, people, stats)

        # The restatement must mean what was said: enough shared content,
        # and no name the words behind it do not have.
        said = f"{fact.quote} {turn.text}"
        known = people | {g.term for g in glossary} | {c.canonical for c in corrections}
        paraphrase_flags: list[str] = []
        if support.support_ratio(text, said, language) < MIN_TEXT_SUPPORT or support.new_names(
            text, said, known
        ):
            if kind in _STRICT_KINDS or _NUMBER.search(text):
                stats.dropped_paraphrase += 1
                continue
            paraphrase_flags = [PARAPHRASE_UNSUPPORTED]
            stats.flagged_paraphrase += 1

        owner: str | None = None
        explicit = False
        owner_flags: list[str] = []
        due_text: str | None = None
        due_date: date | None = None
        due_flags: list[str] = []
        if kind in _OWNED_KINDS:
            owner, explicit, owner_flags = resolve_owner(
                fact.owner,
                quote=fact.quote,
                turn=turn,
                window=window,
                name_candidates=people,
            )
            if owner is None and fact.owner:
                stats.dropped_owner += 1
            owner, owner_fixes, _ = _correct(owner, glossary, people, stats)
            corrections = [*corrections, *owner_fixes]
            due_text, due_date, due_flags = resolve_due(
                fact.due_text,
                turn=turn,
                meeting_date=meeting_date,
                quote=fact.quote,
                language=language,
            )
            if fact.due_text and due_text is None:
                stats.invented_due += 1

        side: str | None = None
        if kind in _SIDED_KINDS:
            side, side_flags = resolve_side(kind, owner, our_side=our_side)
            owner_flags = [*owner_flags, *side_flags]

        # Who holds it. Accepted by the owner rule; a person's own opinion
        # or forecast is theirs; a clip's speaker is not a participant.
        attributed, attribution_flags = _attribute(fact, turn, window, people, stats)
        attributed, actor_fixes, _ = _correct(attributed, glossary, people, stats)
        corrections = [*corrections, *actor_fixes]

        flags = [
            *number_flags,
            *paraphrase_flags,
            *owner_flags,
            *due_flags,
            *attribution_flags,
            *voice_flags,
        ]
        if copied:
            flags.append(COPIED)
        if corrections:
            flags.append(ENTITY_CORRECTED)
        out.append(
            VerifiedFact(
                kind=kind,
                text=text,
                quote=fact.quote.strip(),
                turn=turn.index,
                line=turn.number,
                mentions=tuple(
                    date_mentions(fact.quote, meeting_date=meeting_date, language=language)
                ),
                start_ms=turn.start_ms,
                end_ms=turn.end_ms,
                speaker_label=turn.speaker_label,
                speaker_name=turn.speaker_name,
                owner_label=owner,
                due_text=due_text,
                due_date=due_date,
                explicit=explicit,
                confidence=_confidence(explicit, flags),
                flags=flags,
                window_index=window.index,
                refers_to_key=refers_to_key,
                judgement_field=judgement_field,
                side=side,
                certainty=fact.certainty,
                attributed_to=attributed,
                corrections=tuple(corrections),
                copied=copied,
            )
        )
        stats.kept += 1
    return out


def _correct(
    text: str | None, glossary: tuple[Term, ...], people: frozenset[str], stats: VerifyStats
) -> tuple[str | None, list[Correction], set[str]]:
    """Tier (a) on one string, counted."""
    fixed, applied, marked = entities.correct(text, glossary=glossary, known_people=people)
    for correction in applied:
        stats.corrected[correction.source] = stats.corrected.get(correction.source, 0) + 1
    stats.marked += len(marked)
    return fixed, applied, marked


def accept_name(proposed: str | None, *, window: Window, known: frozenset[str]) -> str | None:
    """A name somebody holds a position under — accepted by the owner rule:
    a speaker, a known person, or a capitalised word said in this window."""
    if not proposed or not proposed.strip():
        return None
    candidate = " ".join(proposed.split())[:60]
    folded = candidate.casefold()
    if folded in {k.casefold() for k in known}:
        return candidate
    present = {m.group(1).casefold() for m in _CAPITALISED.finditer(window.text)}
    if all(part.casefold() in present for part in candidate.split()):
        return candidate
    return None


def _attribute(
    fact: schema.Fact, turn: Turn, window: Window, people: frozenset[str], stats: VerifyStats
) -> tuple[str | None, list[str]]:
    """``(attributed_to, flags)``."""
    actor = accept_name(fact.attributed_to, window=window, known=people)
    if actor:
        stats.attribution_model += 1
        return actor, []
    if fact.certainty not in support.UNSURE_CERTAINTIES:
        return None, []
    if turn.clip or not turn.speaker_name:
        # Quoted, not present — or not named yet. No actor is invented.
        stats.attribution_missing += 1
        return None, [ATTRIBUTION_MISSING]
    stats.attribution_speaker += 1
    return turn.speaker_name, []


# Kinds that carry an owner and a deadline like an action does.
_OWNED_KINDS: Final[frozenset[str]] = frozenset(
    {schema.ACTION, "commitment_ours", "commitment_theirs"}
)
# Below this share of its content in the quote and turn, a fact's text is
# saying something else (Q2). Set so a real paraphrase passes — "The current
# timeline may not support the launch" from "worried we won't be ready by
# the launch" is 0.4 — and a line about something else does not.
MIN_TEXT_SUPPORT: Final = 0.34
# Kinds a reader acts on: a paraphrase of one that its words do not carry
# is dropped, not flagged.
_STRICT_KINDS: Final[frozenset[str]] = frozenset(
    {schema.DECISION, schema.ACTION, "commitment_ours", "commitment_theirs"}
)

# F2 — short by nature: a task or a decision needs no four content words,
# nor does a completion tick or a judgement value.
_SHORT_KINDS: Final[frozenset[str]] = _STRICT_KINDS | {schema.COMPLETION, schema.JUDGEMENT}
# Phrased in the speaker's voice by nature ("We should update the deck"):
# a task keeps its wording; the first-person rule is for statements.
_TASK_KINDS: Final[frozenset[str]] = frozenset(
    {schema.ACTION, "commitment_ours", "commitment_theirs", schema.COMPLETION, schema.JUDGEMENT}
)

# Kinds that belong to one side of the table.
_SIDED_KINDS: Final[frozenset[str]] = frozenset({"commitment_ours", "commitment_theirs"})

OURS: Final = "ours"
THEIRS: Final = "theirs"


def resolve_side(
    kind: str, owner: str | None, *, our_side: frozenset[str]
) -> tuple[str | None, list[str]]:
    """Which side of the table owns a commitment.

    The owner's name decides it, not the kind the model chose: a model
    that labels a task `commitment_ours` when the client took it on has
    guessed, and the names are evidence. When the name is not one we
    know, the side is UNKNOWN and flagged — a task filed under the wrong
    side of a client note is worse than one filed under neither.
    """
    if owner and our_side and owner.casefold() in our_side:
        return OURS, []
    if owner and our_side:
        return THEIRS, []
    # No roster to compare against: fall back to what the model said,
    # and say that we are not sure.
    if kind == "commitment_ours":
        return OURS, [SIDE_UNKNOWN] if not our_side else []
    if kind == "commitment_theirs":
        return THEIRS, [SIDE_UNKNOWN] if not our_side else []
    return None, [SIDE_UNKNOWN]


def _confidence(explicit: bool, flags: list[str]) -> float:
    if NUMBER_UNVERIFIED in flags or LOW_ASR_CONFIDENCE in flags or PARAPHRASE_UNSUPPORTED in flags:
        return CONF_FLAGGED
    if explicit:
        return CONF_EXPLICIT
    return CONF_INFERRED


# ── Noise, confirmed by code (Q2) ───────────────────────────────────


@dataclass(frozen=True, slots=True)
class Exclusion:
    """A line left out of the notes, with a reason from the closed
    vocabulary. Timestamps and a word — never text."""

    line: int
    start_ms: int
    end_ms: int
    reason: str


# A "background"/"artifact"/"unrelated" piece longer than this is content.
MAX_EXCLUDED_MS: Final = 10_000
MAX_EXCLUDED_WORDS: Final = 12
# Of speech time, per generation: above it, only exclusions code can
# prove (another language, a duplicate) stand.
MAX_EXCLUDED_SHARE: Final = 0.02
DUPLICATE_JACCARD: Final = 0.9
MIN_OTHER_LANGUAGE_WORDS: Final = 20
MIN_STOP_WORD_SHARE: Final = 0.03
PROVABLE_REASONS: Final[frozenset[str]] = frozenset({"other_language", "duplicate"})

_DATE_WORDS: Final[frozenset[str]] = frozenset({*_MONTHS, *_WEEKDAYS, *_RELATIVE})


def _has_date_word(text: str) -> bool:
    return any(w in _DATE_WORDS for w in normalise_quote(text).split())


def _is_other_language(text: str, language: str) -> bool:
    if len(text.split()) < MIN_OTHER_LANGUAGE_WORDS:
        return False
    share = support.cyrillic_share(text)
    cyrillic_expected = language in support.CYRILLIC_LANGUAGES
    if cyrillic_expected and share < 0.5:
        return True
    if not cyrillic_expected and share > 0.5:
        return True
    return support.stop_word_share(text, language) < MIN_STOP_WORD_SHARE


def _is_marginal(piece: Turn) -> bool:
    """Short, wordless and without anything a reader could need: no
    number, no date, no name."""
    return (
        piece.end_ms - piece.start_ms <= MAX_EXCLUDED_MS
        and len(piece.text.split()) <= MAX_EXCLUDED_WORDS
        and not any(ch.isdigit() for ch in piece.text)
        and not _has_date_word(piece.text)
        and not support.names_in(piece.text)
    )


def confirm_noise(
    flags: list[tuple[int, str]],
    *,
    window: Window,
    language: str,
    seen_pieces: tuple[str, ...] = (),
) -> tuple[list[Exclusion], list[str]]:
    """``(confirmed exclusions, advisory reasons)`` for one window's flags.

    The model may say "this line is not the conversation"; code checks the
    claim against what it can see, and excludes only what passes. A flag
    that does not pass its reason's rule is advisory: counted, never acted
    on. ``seen_pieces`` are texts from before this window (the previous
    window's lines), for the duplicate rule. Pure.
    """
    confirmed: list[Exclusion] = []
    advisory: list[str] = []
    order = [t.number for t in window.turns]
    total_words = sum(len(t.text.split()) for t in window.turns) or 1
    done: set[int] = set()
    for number, reason in flags:
        piece = window.turn(number)
        if piece is None or reason not in schema.NOISE_REASONS or number in done:
            continue
        done.add(number)
        if len(piece.text.split()) > total_words * schema.MAX_NOISE_SHARE:
            # Noise is marginal by definition (ADR-0059's rule, Q6). A line
            # that is most of the window IS the recording — an advertisement
            # someone recorded is still what they recorded.
            ok = False
        elif reason == "other_language":
            # Sprint I2: the ASR's own per-segment language is the rule; the
            # script/stop-word heuristic stays for older artifacts without it.
            ok = (
                piece.language != language
                if piece.language
                else _is_other_language(piece.text, language)
            )
        elif reason == "duplicate":
            earlier = [t.text for t in window.turns if order.index(t.number) < order.index(number)]
            mine = support.merge_tokens(piece.text)
            ok = bool(mine) and any(
                _jaccard(mine, support.merge_tokens(other)) >= DUPLICATE_JACCARD
                for other in (*seen_pieces, *earlier)
            )
        else:
            ok = _is_marginal(piece)
        if ok:
            confirmed.append(Exclusion(piece.number, piece.start_ms, piece.end_ms, reason))
        else:
            advisory.append(reason)
    return confirmed, advisory


def cap_exclusions(exclusions: list[Exclusion], *, speech_ms: int) -> tuple[list[Exclusion], int]:
    """``(what stands, how many were overridden)``. When the confirmed
    exclusions add up to more than ``MAX_EXCLUDED_SHARE`` of the speech, a
    bad run is silencing the recording: only what code can prove — another
    language, a duplicate — stays out."""
    total = sum(max(0, e.end_ms - e.start_ms) for e in exclusions)
    if speech_ms <= 0 or total <= MAX_EXCLUDED_SHARE * speech_ms:
        return exclusions, 0
    kept = [e for e in exclusions if e.reason in PROVABLE_REASONS]
    return kept, len(exclusions) - len(kept)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0
