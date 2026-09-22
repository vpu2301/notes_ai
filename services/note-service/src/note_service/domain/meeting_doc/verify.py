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

Plus one judgement call, also in code: a decision nobody agreed to is a
proposal, and is downgraded to a key point.

Pure. Facts and windows in, verified facts out.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from ..action_items import item_key, normalise_text, parse_due
from . import schema
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

    @property
    def item_key(self) -> str:
        """The same hash the recipient loop, the corrections routes and
        the carried items use — one identity for a line, everywhere."""
        return item_key(normalise_text(self.text))


# ── Quote matching ──────────────────────────────────────────────────

_PUNCT = re.compile(r"[^\w\s']", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise_quote(text: str) -> str:
    """The comparison form: NFKC, case-folded, punctuation dropped
    (apostrophes kept — "I'll" is not "Ill"), whitespace collapsed.

    Mirrors ``scripts/eval/smoke_eval._quote`` so the harness and the
    pipeline agree about what counts as a match.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = folded.replace("’", "'").replace("‘", "'")
    return _SPACE.sub(" ", _PUNCT.sub(" ", folded)).strip()


def locate_quote(quote: str, window: Window, cited_turn: int) -> Turn | None:
    """The turn a quote actually came from, or None.

    The cited turn is tried first — the model usually gets it right, and
    trusting it keeps the timestamp precise. Failing that, any turn in
    the window: a model that cites turn 7 for words said in turn 8 is
    wrong about the number, not lying about the words.
    """
    needle = normalise_quote(quote)
    if len(needle.split()) < schema.MIN_QUOTE_WORDS:
        return None
    turn = window.turn(cited_turn)
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
    due_text: str | None, *, turn: Turn, meeting_date: date
) -> tuple[str | None, date | None, list[str]]:
    """``(due_text, due_date, flags)`` — a date nobody said is never written."""
    if not due_text or not due_text.strip():
        return None, None, []
    text = " ".join(due_text.split())[:120]
    if normalise_quote(text) not in normalise_quote(turn.text):
        # The model produced a deadline that was not spoken.
        return None, None, []
    parsed = parse_due(text, anchor=meeting_date)
    return text, parsed, [] if parsed else [DUE_UNPARSED]


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
    said, claim = normalise_quote(quote), normalise_quote(text)
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
    noise_turns: frozenset[int] = frozenset(),
) -> list[VerifiedFact]:
    """One window's claims, checked. Anything that fails is dropped.

    ``allowed_kinds`` is the family's set (Sprint 36): a model that
    answers with a kind this family does not have is answering about a
    different document, and the fact is dropped rather than filed
    somewhere arbitrary.
    """
    stats = stats or VerifyStats()
    allowed = allowed_kinds or frozenset(schema.FACT_KINDS)
    out: list[VerifiedFact] = []
    for fact in facts:
        if fact.kind not in allowed or not fact.text.strip():
            stats.dropped_quote += 1
            continue
        turn = locate_quote(fact.quote, window, fact.turn)
        if turn is None:
            stats.dropped_quote += 1
            continue
        if turn.index in noise_turns:
            # The model said this turn is not the conversation, then
            # quoted it anyway. The flag wins: a fact from background
            # speech is worse than no fact.
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

        if kind == schema.DECISION and (
            not is_decision(fact.quote, turn=turn, window=window)
            or is_copied(fact.text, fact.quote)
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
                name_candidates=name_candidates,
            )
            if owner is None and fact.owner:
                stats.dropped_owner += 1
            due_text, due_date, due_flags = resolve_due(
                fact.due_text, turn=turn, meeting_date=meeting_date
            )
            if fact.due_text and due_text is None:
                stats.invented_due += 1

        side: str | None = None
        if kind in _SIDED_KINDS:
            side, side_flags = resolve_side(kind, owner, our_side=our_side)
            owner_flags = [*owner_flags, *side_flags]

        flags = [*number_flags, *owner_flags, *due_flags]
        out.append(
            VerifiedFact(
                kind=kind,
                text=text,
                quote=fact.quote.strip(),
                turn=turn.index,
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
            )
        )
        stats.kept += 1
    return out


# Kinds that carry an owner and a deadline like an action does.
_OWNED_KINDS: Final[frozenset[str]] = frozenset(
    {schema.ACTION, "commitment_ours", "commitment_theirs"}
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
    if NUMBER_UNVERIFIED in flags or LOW_ASR_CONFIDENCE in flags:
        return CONF_FLAGGED
    if explicit:
        return CONF_EXPLICIT
    return CONF_INFERRED
