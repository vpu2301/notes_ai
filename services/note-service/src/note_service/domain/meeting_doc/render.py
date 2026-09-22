"""Facts into the text of a document.

Deterministic and code-only: no model touches this step. Two consequences
worth stating, because they are the point of doing it here rather than
asking a model to "write it up":

* **Actions come out in the grammar the rest of the product reads.**
  `Owner: task — due` is exactly what `parse_action_lines` parses back,
  so a task written by the engine appears on the recipient's page, in the
  carried-over block and in the corrections routes with no extra work
  and no second parser to keep in step.
* **Empty means empty.** A section with no verified facts is left blank.
  Filler ("No decisions were recorded in this meeting.") reads as content,
  costs the reader attention, and is indistinguishable from a real result
  when you are skimming.

`user_notes` is never written here. It belongs to the author (Sprint 34).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from .. import lines as line_rules
from . import roles, schema
from .verify import VerifiedFact

_ECHOED_FACT: Final = re.compile(
    r"^\s*(?:\[\]\s*)?(?P<id>[0-9a-f]{16})\s*\([a-z_]+,\s*\d{1,2}:\d{2}\):\s*"
)
# "(d96df9628cf97a1b)", "(3d92…, 49dc…)" or a bare id, anywhere in a
# bullet or a summary sentence: a small model told to cite its facts
# writes the ids into the prose as well as into `fact_ids`.
_INLINE_IDS: Final = re.compile(r"\s*\(?\b(?P<ids>[0-9a-f]{16}(?:\s*,\s*[0-9a-f]{16})*)\b\)?")


# "It was noted that …" — the flat openers a model reaches for when told
# to be neutral. Removed; the point stands on its own. Openers that carry
# certainty ("It was estimated that", "es wurde geschätzt") are NOT here:
# stripping one would make an estimate a fact.
_FLAT_OPENER: Final = re.compile(
    r"^(?:it was (?:stated|noted|mentioned|established|determined|discussed|said|"
    r"explained|pointed out|highlighted|emphasi[sz]ed) that|"
    r"es wurde (?:gesagt|erwähnt|festgestellt|festgehalten|besprochen|diskutiert|"
    r"erklärt|betont|hervorgehoben)(?:,)? dass|"
    r"було (?:зазначено|сказано|встановлено|згадано|обговорено|пояснено|"
    r"підкреслено|наголошено),? що)\s+",
    re.IGNORECASE,
)


def editorial(text: str) -> str:
    """A line as an editor would leave it: no flat passive opener."""
    stripped = _FLAT_OPENER.sub("", text.strip(), count=1)
    if stripped != text.strip() and stripped:
        stripped = stripped[0].upper() + stripped[1:]
    return stripped


# Where an item kind lands when the template has no section for its
# role: a section of its own, with a heading in the notes' language.
# `action_items` is literal because the item projection, the recipient
# page and carry-over all read that key.
FALLBACK_KEYS: Final[dict[str, str]] = {
    roles.DECISIONS: "decisions",
    roles.ACTION_ITEMS: "action_items",
    roles.OPEN_QUESTIONS: "open_questions",
    roles.RISKS: "risks",
    roles.NEXT_MEETING: "next_meeting",
}
ROLE_LABELS: Final[dict[str, dict[str, str]]] = {
    "en": {
        roles.DECISIONS: "Decisions",
        roles.ACTION_ITEMS: "Action items",
        roles.OPEN_QUESTIONS: "Open questions",
        roles.RISKS: "Risks",
        roles.NEXT_MEETING: "Next meeting",
    },
    "de": {
        roles.DECISIONS: "Entscheidungen",
        roles.ACTION_ITEMS: "Aufgaben",
        roles.OPEN_QUESTIONS: "Offene Fragen",
        roles.RISKS: "Risiken",
        roles.NEXT_MEETING: "Nächstes Treffen",
    },
    "uk": {
        roles.DECISIONS: "Рішення",
        roles.ACTION_ITEMS: "Завдання",
        roles.OPEN_QUESTIONS: "Відкриті питання",
        roles.RISKS: "Ризики",
        roles.NEXT_MEETING: "Наступна зустріч",
    },
}

# The transcript note is rendered from a closed vocabulary, never from
# model prose: what the model may say about a turn is one of these words.
NOISE_LABELS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "background": "background speech",
        "other_language": "a passage in another language",
        "artifact": "a transcription artifact",
        "duplicate": "a duplicated passage",
        "unrelated": "an unrelated fragment",
    },
    "de": {
        "background": "Hintergrundgespräch",
        "other_language": "eine Passage in einer anderen Sprache",
        "artifact": "ein Transkriptionsartefakt",
        "duplicate": "eine doppelte Passage",
        "unrelated": "ein unzusammenhängendes Fragment",
    },
    "uk": {
        "background": "фонова мова",
        "other_language": "уривок іншою мовою",
        "artifact": "артефакт транскрипції",
        "duplicate": "повторений уривок",
        "unrelated": "непов'язаний фрагмент",
    },
}
_NOTE_TEMPLATE: Final[dict[str, str]] = {
    "en": "Transcript note: {what} at {when} was left out of these notes.",
    "de": "Hinweis zum Transkript: {what} bei {when} wurde nicht berücksichtigt.",
    "uk": "Примітка до стенограми: {what} о {when} не враховано.",
}
_AND: Final[dict[str, str]] = {"en": " and ", "de": " und ", "uk": " та "}
MAX_NOTED_PASSAGES: Final = 4


def transcript_note(noise: list[tuple[int, str]], *, language: str = "en") -> str:
    """One sentence naming the passages the extractor set aside, so the
    reader knows they are missing on purpose. Empty when nothing was."""
    if not noise:
        return ""
    lang = language if language in _NOTE_TEMPLATE else "en"
    labels = NOISE_LABELS[lang]
    passages = sorted({(ms, labels.get(reason, labels["unrelated"])) for ms, reason in noise})
    passages = passages[:MAX_NOTED_PASSAGES]
    what = ", ".join(dict.fromkeys(label for _, label in passages))
    times = [mmss(ms) for ms, _ in passages]
    when = _AND[lang].join([", ".join(times[:-1]), times[-1]]) if len(times) > 1 else times[0]
    return _NOTE_TEMPLATE[lang].format(what=what, when=when)


def strip_inline_ids(text: str) -> tuple[str, list[str]]:
    """The text without any fact ids the model wrote into it, and those
    ids — they are ours, so they still count as citations."""
    found: list[str] = []
    for match in _INLINE_IDS.finditer(text):
        found.extend(i.strip() for i in match.group("ids").split(","))
    if not found:
        return text, []
    cleaned = _INLINE_IDS.sub("", text)
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    return " ".join(cleaned.split()), found


# Which fact kind belongs in which role. A template that has no section
# with that role simply does not receive those facts.
KIND_TO_ROLE: Final[dict[str, str]] = {
    schema.DECISION: roles.DECISIONS,
    schema.ACTION: roles.ACTION_ITEMS,
    schema.OPEN_QUESTION: roles.OPEN_QUESTIONS,
    schema.KEY_POINT: roles.TOPICS,
    schema.AGENDA_ITEM: roles.AGENDA,
    schema.RISK: roles.RISKS,
    schema.NEXT_MEETING: roles.NEXT_MEETING,
}

# Agenda items are only believable from the top of the meeting: people
# say "let's talk about X" at the start, and something that sounds like
# an agenda item forty minutes in is usually just a topic.
AGENDA_FROM_FIRST_WINDOWS: Final = 2

# Sprint 36 — a client call's actions read as two lists, because the
# question a reader has is "what do I have to do". Headings are per
# language; a side we could not work out gets its own group rather than
# being guessed into one of the other two.
SIDE_HEADINGS: Final[dict[str, dict[str, str]]] = {
    "en": {"ours": "We do", "theirs": "{other} does", "unknown": "Still to assign"},
    "de": {"ours": "Wir übernehmen", "theirs": "{other} übernimmt", "unknown": "Noch zuzuordnen"},
    "uk": {"ours": "Ми робимо", "theirs": "{other} робить", "unknown": "Ще розподілити"},
}


@dataclass(frozen=True, slots=True)
class RenderedSection:
    section_key: str
    role: str
    text: str
    """The facts that produced it — what the sidecar rows are written from."""
    facts: tuple[VerifiedFact, ...] = field(default=())
    """The heading for a section the template does not name; None for a
    template section (named by the template) and for the unheaded
    opening block."""
    title: str | None = None


def mmss(ms: int) -> str:
    total = max(0, ms) // 1000
    return f"{total // 60:02d}:{total % 60:02d}"


def action_line(fact: VerifiedFact) -> str:
    """``- Anna: send the pricing proposal — by Tuesday``.

    The owner is omitted when we could not place one; an invented name
    would be worse than a task nobody is holding yet.
    """
    return "- " + line_rules.render_item(
        marker="", owner=fact.owner_label, body=editorial(fact.text), due_text=fact.due_text
    )


def decision_line(fact: VerifiedFact) -> str:
    return f"- {editorial(fact.text)}"


def plain_line(fact: VerifiedFact) -> str:
    return f"- {editorial(fact.text)}"


def render_sections(
    facts: list[VerifiedFact],
    *,
    role_by_key: dict[str, str],
    topics: list[tuple[str, list[str], list[str]]] | None = None,
    summary: list[str] | None = None,
    kind_roles: dict[str, str] | None = None,
    language: str = "en",
    counterpart: str = "",
    framing: str = "",
    key_fact_ids: list[str] | None = None,
    noise: list[tuple[int, str]] | None = None,
) -> list[RenderedSection]:
    """The document, as the sections the conversation had.

    Structure follows content, not the template. The opening block
    (``gen:overview``, no heading) carries the framing sentence, the
    summary, the key points and the transcript note. Each topic the
    reduce step found is a section of its own, ``gen:<slug>``, headed by
    the topic's title. Decisions, actions, open questions, risks and the
    next meeting go to the template's section for that role when it has
    one, else to a section of their own with a heading in the notes'
    language — and only when there is something to put there. Nothing is
    emitted for an empty text, and nobody is listed as an attendee:
    the roster is the transcript's.

    ``topics`` is ``[(title, bullet texts, fact ids)]``; ``summary`` its
    sentences; ``framing`` the context pass's opening sentence;
    ``key_fact_ids`` the facts a reader must know first; ``noise``
    ``[(start_ms, reason)]`` for the passages set aside. A meeting with
    one coherent subject gets no topic headings at all.
    """
    keys_by_role: dict[str, list[str]] = {}
    for key, role in role_by_key.items():
        keys_by_role.setdefault(role, []).append(key)
    labels = ROLE_LABELS.get(language, ROLE_LABELS["en"])

    out: list[RenderedSection] = []

    def emit(role: str, text: str, used: list[VerifiedFact]) -> None:
        """Into the template's section for the role, or a section of its
        own when the template has none and the role has a home."""
        if not text.strip():
            return
        key = (keys_by_role.get(role) or [None])[0]
        title: str | None = None
        if key is None:
            key = FALLBACK_KEYS.get(role)
            if key is None:
                return
            title = labels.get(role)
        out.append(
            RenderedSection(section_key=key, role=role, text=text, facts=tuple(used), title=title)
        )

    grouped: dict[str, list[VerifiedFact]] = {}
    for fact in facts:
        grouped.setdefault(fact.kind, []).append(fact)

    # Sprint 36: the family's extra kinds, each into the role its table
    # says. Handled before the generic kinds so a family that maps, say,
    # `risk` somewhere of its own wins.
    extra = {k: r for k, r in (kind_roles or {}).items() if k not in KIND_TO_ROLE}
    by_extra_role: dict[str, list[VerifiedFact]] = {}
    for kind, role in extra.items():
        for fact in grouped.get(kind, []):
            by_extra_role.setdefault(role, []).append(fact)

    by_id = {f.item_key: f for f in facts}

    # ── Agenda: only from the top of the meeting ────────────────────
    agenda = [
        f for f in grouped.get(schema.AGENDA_ITEM, []) if f.window_index < AGENDA_FROM_FIRST_WINDOWS
    ]
    if agenda:
        emit(roles.AGENDA, "\n".join(plain_line(f) for f in agenda), agenda)

    # ── Decisions ───────────────────────────────────────────────────
    decisions = grouped.get(schema.DECISION, [])
    if decisions:
        emit(roles.DECISIONS, "\n".join(decision_line(f) for f in decisions), decisions)

    # ── Actions, in the grammar the rest of the product reads ───────
    actions = [
        *grouped.get(schema.ACTION, []),
        *grouped.get("commitment_ours", []),
        *grouped.get("commitment_theirs", []),
    ]
    if actions:
        emit(
            roles.ACTION_ITEMS,
            action_text(actions, language=language, counterpart=counterpart),
            actions,
        )

    # ── Open questions ──────────────────────────────────────────────
    questions = grouped.get(schema.OPEN_QUESTION, [])
    if questions:
        emit(roles.OPEN_QUESTIONS, "\n".join(plain_line(f) for f in questions), questions)

    # ── Risks ───────────────────────────────────────────────────────
    risks = grouped.get(schema.RISK, [])
    if risks:
        emit(roles.RISKS, "\n".join(plain_line(f) for f in risks), risks)

    # ── Next meeting ────────────────────────────────────────────────
    nexts = grouped.get(schema.NEXT_MEETING, [])
    if nexts:
        emit(roles.NEXT_MEETING, "\n".join(plain_line(f) for f in nexts), nexts)

    # ── The family's own sections ───────────────────────────────────
    for role, owned in by_extra_role.items():
        if role in (roles.ACTION_ITEMS, roles.JUDGEMENT):
            continue  # actions are grouped above; judgements are never written
        existing = next((s for s in out if s.role == role), None)
        text = "\n".join(plain_line(f) for f in owned)
        if existing is None:
            emit(role, text, owned)
        else:
            # A generic kind already wrote here (a family that maps an
            # extra kind onto `risks` alongside `risk`). Append rather
            # than replace.
            out[out.index(existing)] = RenderedSection(
                section_key=existing.section_key,
                role=role,
                text=f"{existing.text}\n{text}",
                facts=(*existing.facts, *owned),
                title=existing.title,
            )

    # ── Topics: one section each, headed by what the conversation
    #    was about there. None for a single-subject conversation. ────
    key_facts = [by_id[i] for i in dict.fromkeys(key_fact_ids or []) if i in by_id]
    key_facts = [f for f in key_facts if f.kind not in (schema.COMPLETION, schema.JUDGEMENT)]
    topic_sections: list[RenderedSection] = []
    taken: set[str] = set(role_by_key)
    if topics:
        for title, bullets, fact_ids in topics:
            cited = [by_id[i] for i in fact_ids if i in by_id]
            lines: list[str] = []
            for bullet in bullets:
                bullet = editorial(bullet)
                # The reduce prompt lists facts as "id (kind, mm:ss): text"
                # and a small model may echo the whole line as a bullet.
                # The id is ours: swap in that fact's text and cite it.
                echoed = _ECHOED_FACT.match(bullet)
                if echoed is not None:
                    fact = by_id.get(echoed.group("id"))
                    bullet = fact.text if fact is not None else bullet[echoed.end() :]
                    if fact is not None and fact not in cited:
                        cited.append(fact)
                bullet, inline = strip_inline_ids(bullet)
                for fact_id in inline:
                    hit = by_id.get(fact_id)
                    if hit is not None and hit not in cited:
                        cited.append(hit)
                if bullet.strip():
                    lines.append(f"- {bullet.strip()}")
            if not lines or not title.strip():
                continue
            key = roles.generated_key(title, taken)
            taken.add(key)
            topic_sections.append(
                RenderedSection(
                    section_key=key,
                    role=roles.TOPICS,
                    text="\n".join(lines),
                    facts=tuple(cited),
                    title=title.strip(),
                )
            )

    # ── The opening block: no heading. It is the note. ──────────────
    overview: list[str] = []
    if framing.strip():
        overview.append(editorial(strip_inline_ids(framing)[0]))
    if summary:
        overview.extend(editorial(strip_inline_ids(s)[0]) for s in summary)
    used: list[VerifiedFact] = []
    if key_facts:
        overview.append("\n".join(plain_line(f) for f in key_facts))
        used.extend(key_facts)
    if not topic_sections:
        # Nothing to head: what the reduce step could not cluster (too
        # few facts, one subject, a failed call) reads as one list.
        rest = [f for f in grouped.get(schema.KEY_POINT, []) if f not in key_facts]
        if rest:
            overview.append("\n".join(plain_line(f) for f in rest))
            used.extend(rest)
    note = transcript_note(noise or [], language=language)
    if note and (overview or facts):
        overview.append(note)
    text = "\n\n".join(s for s in overview if s and s.strip())
    if text:
        out.insert(
            0,
            RenderedSection(
                section_key=roles.OVERVIEW_KEY, role=roles.SUMMARY, text=text, facts=tuple(used)
            ),
        )
    out.extend(topic_sections)
    return out


def action_text(actions: list[VerifiedFact], *, language: str = "en", counterpart: str = "") -> str:
    """One list, or two groups when the facts carry a side.

    The reader of a client note is asking "what do I have to do", and a
    single list of eight tasks does not answer it. A side nobody could
    work out gets its own group — visible, rather than guessed into
    somebody's column.
    """
    sided = [f for f in actions if f.side]
    if not sided:
        return "\n".join(action_line(f) for f in actions)

    headings = SIDE_HEADINGS.get(language, SIDE_HEADINGS["en"])
    other = counterpart or ("the client" if language == "en" else "")
    groups = [
        ("ours", headings["ours"], [f for f in actions if f.side == "ours"]),
        (
            "theirs",
            headings["theirs"].format(other=other).strip() or headings["unknown"],
            [f for f in actions if f.side == "theirs"],
        ),
        ("unknown", headings["unknown"], [f for f in actions if not f.side]),
    ]
    blocks = [
        f"### {title}\n" + "\n".join(action_line(f) for f in owned)
        for _, title, owned in groups
        if owned
    ]
    return "\n\n".join(blocks)


def attendees_from(facts: list[VerifiedFact]) -> list[str]:
    """The people we can name, in the order they first spoke.

    Only named speakers: "Speaker 2" in an attendee list is noise, and
    the roster UI is where a person gets named.
    """
    seen: dict[str, None] = {}
    for fact in sorted(facts, key=lambda f: f.start_ms):
        if fact.speaker_name and fact.speaker_name not in seen:
            seen[fact.speaker_name] = None
    return list(seen)
