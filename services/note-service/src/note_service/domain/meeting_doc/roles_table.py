"""Who each voice is to this recording, computed by code: one :class:`Speaker`
per diarizer label with its share, turns, introduction and role. The table only
ever holds labels that spoke; a name mentioned in facts is a subject, never a guest.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from .verify import Person, VerifiedFact
from .windows import Turn

NARRATOR: Final = "narrator"
HOST: Final = "host"
GUEST: Final = "guest"
INTERVIEWEE: Final = "interviewee"
# A guest or participant introduced as an expert.
EXPERT: Final = "expert"
PARTICIPANT: Final = "participant"
CLIP: Final = "clip"
ADVERT: Final = "advert"
ROLES: Final = (NARRATOR, HOST, EXPERT, GUEST, INTERVIEWEE, PARTICIPANT, CLIP, ADVERT)
# The order paragraph 1 lists who speaks.
ROLE_RANK: Final[dict[str, int]] = {
    HOST: 0,
    NARRATOR: 0,
    EXPERT: 1,
    GUEST: 2,
    INTERVIEWEE: 3,
    PARTICIPANT: 4,
}
_EXPERT_WORDS: Final = re.compile(
    r"\b(?:expert\w*|fachmann|fachfrau|analyst\w*|forscher\w*|wissenschaftler\w*"
    r"|professor\w*|researcher|scientist|specialist|spezialist\w*"
    r"|експерт\w*|аналітик\w*|дослідни\w*|науков\w*|професор\w*)",
    re.IGNORECASE,
)


def expert_introduction(person: Person | None) -> bool:
    """Introduced with an expert's role word (its role or organisation)."""
    if person is None:
        return False
    return bool(_EXPERT_WORDS.search(f"{person.role} {person.organisation} {person.qualifier}"))


CLIP_MAX_SHARE: Final = 0.05
CLIP_MAX_TURNS: Final = 2
GUEST_MIN_SHARE: Final = 0.15
GUEST_MIN_TURNS: Final = 3
HOSTING_FIRST_PERSON: Final = 0.3  # below: narrating; at or above: hosting
# Two voices this close in share, nobody introduced: both participants.
TIE_SHARE_RATIO: Final = 0.8
ADVERT_INSIDE: Final = 0.8  # share of a label's speech inside advert passages

# A voice that presents or narrates: these recording types.
BROADCAST: Final = frozenset({"podcast_broadcast", "lecture_webinar", "presentation_demo"})

_FIRST_PERSON: Final = re.compile(
    r"\b(?:ich|wir|mein\w*|unser\w*|I|I'm|I’m|we|my|our|я|ми|мій|моя|наш\w*)\b"
    r"|\b(?:ich finde|i think|я вважаю)\b",
    re.IGNORECASE,
)
_DEFAULT_NAME: Final = re.compile(
    r"(?i)^(?:speaker[ _]?\d+|unknown(?: speaker)?|sprecher(?:in)? \d+)$"
)


@dataclass(frozen=True, slots=True)
class Speaker:
    label: str
    share: float
    turns: int
    first_person_share: float
    role: str
    name: str | None = None  # a verified name: an introduction or a real speaker name
    introduced_as: Person | None = None


@dataclass
class RolesTable:
    speakers: dict[str, Speaker] = field(default_factory=dict)
    ambiguous: bool = False

    def role_of(self, label: str | None) -> str | None:
        speaker = self.speakers.get(label or "")
        return speaker.role if speaker else None

    def by_role(self, *roles: str) -> list[Speaker]:
        return [s for s in self.speakers.values() if s.role in roles]

    def as_stats(self) -> dict[str, str]:
        """Label → role: codes, no names."""
        return {label: s.role for label, s in sorted(self.speakers.items())}


def first_person(text: str) -> bool:
    return bool(_FIRST_PERSON.search(text))


def real_name(name: str | None) -> str | None:
    name = (name or "").strip()
    return name if name and not _DEFAULT_NAME.match(name) else None


def _inside(start: int, end: int, adverts: Sequence[tuple[int, int]]) -> int:
    return sum(max(0, min(end, b) - max(start, a)) for a, b in adverts)


def build(
    turns: Sequence[Turn],
    introductions: Iterable[VerifiedFact] = (),
    recording_type: str | None = None,
    adverts: Sequence[tuple[int, int]] = (),
    *,
    broadcast: bool | None = None,
) -> RolesTable:
    """``broadcast`` — a voice presents or narrates here; by default from
    the recording type, else the family's (a walkthrough with no type)."""
    speech: dict[str, int] = {}
    count: dict[str, int] = {}
    first: dict[str, int] = {}
    in_advert: dict[str, int] = {}
    names: dict[str, str] = {}
    for turn in turns:
        label = turn.speaker_label or ""
        length = max(0, turn.end_ms - turn.start_ms)
        speech[label] = speech.get(label, 0) + length
        count[label] = count.get(label, 0) + 1
        first[label] = first.get(label, 0) + (1 if first_person(turn.text) else 0)
        in_advert[label] = in_advert.get(label, 0) + _inside(turn.start_ms, turn.end_ms, adverts)
        if label not in names and real_name(turn.speaker_name) and turn.speaker_name != label:
            names[label] = str(turn.speaker_name)
    content = {k: v - in_advert[k] for k, v in speech.items()}
    total = sum(max(0, v) for v in content.values()) or 1
    introduced = _introductions(introductions, turns, speech, count)

    table = RolesTable()
    ranked = sorted(
        (label for label in speech if label and _not_advert(label, speech, in_advert)),
        key=lambda label: content[label],
        reverse=True,
    )
    speaking = [
        label
        for label in ranked
        if label.upper() != "UNKNOWN"
        and not (content[label] / total < CLIP_MAX_SHARE and count[label] <= CLIP_MAX_TURNS)
    ]
    dominant = speaking[0] if speaking else None
    runner_up = speaking[1] if len(speaking) > 1 else None
    if (
        dominant
        and runner_up
        and content[runner_up] >= TIE_SHARE_RATIO * content[dominant]
        and not introduced
    ):
        table.ambiguous = True
    if broadcast is None:
        broadcast = (recording_type or "") in BROADCAST
    interview = recording_type == "interview"
    for label in speech:
        if not label:
            continue
        share = max(0, content[label]) / total
        fp = first[label] / count[label] if count[label] else 0.0
        person = introduced.get(label)
        if not _not_advert(label, speech, in_advert):
            role = ADVERT
        elif label not in speaking or label.upper() == "UNKNOWN":
            # The diarizer's catch-all is trailer voices and sound bites,
            # never a person taking part.
            role = CLIP
        elif table.ambiguous:
            role = PARTICIPANT
        elif label == dominant and (broadcast or interview):
            role = HOST if (fp >= HOSTING_FIRST_PERSON or interview) else NARRATOR
        elif person is not None and (share >= GUEST_MIN_SHARE or count[label] >= GUEST_MIN_TURNS):
            if expert_introduction(person):
                role = EXPERT
            else:
                role = INTERVIEWEE if interview else GUEST if broadcast else PARTICIPANT
        else:
            role = PARTICIPANT
        name = person.name if person is not None else names.get(label)
        table.speakers[label] = Speaker(
            label=label,
            share=round(share, 4),
            turns=count[label],
            first_person_share=round(fp, 4),
            role=role,
            name=name,
            introduced_as=person,
        )
    return table


def _not_advert(label: str, speech: dict[str, int], in_advert: dict[str, int]) -> bool:
    return not (speech[label] and in_advert[label] / speech[label] >= ADVERT_INSIDE)


def _introductions(
    facts: Iterable[VerifiedFact],
    turns: Sequence[Turn],
    speech: dict[str, int],
    count: dict[str, int],
) -> dict[str, Person]:
    """Label → the verified introduction that names it. A self-introduction
    names its own speaker; one speaker introducing another ("Das ist Felix",
    "with us today is …") names the next other voice that talks enough to
    be a guest."""
    out: dict[str, Person] = {}
    for fact in sorted(facts, key=lambda f: f.start_ms):
        person = fact.person
        if person is None or not fact.speaker_label:
            continue
        if person.self_introduction:
            out.setdefault(fact.speaker_label, person)
            continue
        for turn in turns:
            label = turn.speaker_label or ""
            if (
                turn.start_ms >= fact.start_ms
                and label
                and label != fact.speaker_label
                and label not in out
                and count.get(label, 0) >= GUEST_MIN_TURNS
            ):
                out[label] = person
                break
    return out


def standing(fact: VerifiedFact, table: RolesTable) -> str:
    """presenter/guest/clip for an introduction fact, read from the table."""
    person = fact.person
    if person is None:
        return "clip"
    for speaker in table.speakers.values():
        if speaker.introduced_as is person or (
            speaker.introduced_as is not None and speaker.introduced_as.name == person.name
        ):
            if speaker.role in (GUEST, INTERVIEWEE, EXPERT):
                return "guest"
            if speaker.role in (HOST, NARRATOR) and person.self_introduction:
                return "presenter"
    return "clip"
