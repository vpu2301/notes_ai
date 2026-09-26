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
from dataclasses import dataclass, field, replace
from datetime import date, time
from typing import Final

from .. import lines as line_rules
from . import roles, schema, support
from .verify import DateMention, VerifiedFact

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
    roles.KEY_DATES: "key_dates",
}
ROLE_LABELS: Final[dict[str, dict[str, str]]] = {
    "en": {
        roles.DECISIONS: "Decisions",
        roles.ACTION_ITEMS: "Action items",
        roles.OPEN_QUESTIONS: "Open questions",
        roles.RISKS: "Risks",
        roles.NEXT_MEETING: "Next meeting",
        roles.KEY_DATES: "Key dates",
    },
    "de": {
        roles.DECISIONS: "Entscheidungen",
        roles.ACTION_ITEMS: "Aufgaben",
        roles.OPEN_QUESTIONS: "Offene Fragen",
        roles.RISKS: "Risiken",
        roles.NEXT_MEETING: "Nächstes Treffen",
        roles.KEY_DATES: "Termine & Fristen",
    },
    "uk": {
        roles.DECISIONS: "Рішення",
        roles.ACTION_ITEMS: "Завдання",
        roles.OPEN_QUESTIONS: "Відкриті питання",
        roles.RISKS: "Ризики",
        roles.NEXT_MEETING: "Наступна зустріч",
        roles.KEY_DATES: "Дати та терміни",
    },
}


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


# What a written line is. The eval scores lines by kind, and Q5 hangs a
# citation off every one of them.
LINE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "framing",
        "summary",
        "key_point",
        "bullet",
        "decision",
        "action",
        "question",
        "risk",
        "next_meeting",
        "agenda",
        "note",
        "heading",
    }
)
_LINE_KIND_OF_FACT: Final[dict[str, str]] = {
    schema.DECISION: "decision",
    schema.ACTION: "action",
    "commitment_ours": "action",
    "commitment_theirs": "action",
    schema.OPEN_QUESTION: "question",
    schema.RISK: "risk",
    schema.NEXT_MEETING: "next_meeting",
    schema.AGENDA_ITEM: "agenda",
}


@dataclass(frozen=True, slots=True)
class Line:
    """One written line and the facts it rests on.

    ``text`` is exactly a line of the section's text — never a second
    rendering of it — so what the eval scores is what the reader sees.
    """

    text: str
    kind: str
    fact_ids: tuple[str, ...] = ()
    """Q3 — the dates its facts' quotes mention, resolved with their tense."""
    dates: tuple[DateMention, ...] = ()


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
    """Every non-blank line of ``text``, in order, with its kind and the
    fact ids behind it."""
    lines: tuple[Line, ...] = field(default=())


def fact_line(fact: VerifiedFact, text: str) -> Line:
    """A line written from one fact."""
    return Line(
        text=text, kind=_LINE_KIND_OF_FACT.get(fact.kind, "key_point"), fact_ids=(fact.item_key,)
    )


def _ids(facts: list[VerifiedFact]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f.item_key for f in facts))


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


def decision_line(fact: VerifiedFact, language: str = "en") -> str:
    return f"- {patch_claim(editorial(fact.text), [fact], language)}"


def plain_line(fact: VerifiedFact, language: str = "en") -> str:
    return f"- {patch_claim(editorial(fact.text), [fact], language)}"


def patch_claim(text: str, facts: list[VerifiedFact], language: str = "en") -> str:
    """A record of an opinion, forecast, estimate, proposal or allegation
    says whose it is and that it is one (Q4) — in code, from the fact's own
    fields, never in words a model chose.

    * ``… — laut Reinbold`` / ``… (Vorschlag: Söder)`` when the holder is
      known and the line does not already name them;
    * ``Voraussichtlich: …`` when the line still carries no marker of its
      certainty (a holder's "laut" is one).
    """
    unsure = [f for f in facts if f.certainty in support.UNSURE_CERTAINTIES]
    if not unsure:
        return text
    fact = unsure[0]
    lang = language if language in support.CERTAINTY_PHRASES else "en"
    phrases = support.CERTAINTY_PHRASES[lang]
    actor = fact.attributed_to
    if actor and not support.names_actor(text, actor):
        last = actor.split()[-1]
        if fact.certainty == "proposal":
            text = f"{text} ({phrases['proposal']}: {last})"
        else:
            text = f"{text} — {support.ACCORDING_TO[lang]} {last}"
    if not support.has_marker(text, lang):
        text = f"{phrases[fact.certainty]}: {text}"
    return text


def render_sections(
    facts: list[VerifiedFact],
    *,
    role_by_key: dict[str, str],
    topics: list[tuple[str, list[str] | list[tuple[str, list[str]]], list[str]]] | None = None,
    summary: list[str] | list[tuple[str, list[str]]] | None = None,
    kind_roles: dict[str, str] | None = None,
    language: str = "en",
    counterpart: str = "",
    framing: str = "",
    key_fact_ids: list[str] | None = None,
    counters: dict[str, int] | None = None,
    meeting_date: date | None = None,
) -> list[RenderedSection]:
    """The document, as the sections the conversation had.

    Structure follows content, not the template. The opening block
    (``gen:overview``, no heading) carries the framing sentence and the
    summary — and, when there are no topics, the facts as one list. Each topic the
    reduce step found is a section of its own, ``gen:<slug>``, headed by
    the topic's title. Decisions, actions, open questions, risks and the
    next meeting go to the template's section for that role when it has
    one, else to a section of their own with a heading in the notes'
    language — and only when there is something to put there. Nothing is
    emitted for an empty text, and nobody is listed as an attendee:
    the roster is the transcript's.

    ``topics`` is ``[(title, [(bullet text, its fact ids)], fact ids)]``
    (a bare bullet string is still accepted); ``summary`` its sentences,
    each ``(sentence, fact ids)`` or a bare string; ``framing`` the context pass's opening sentence;
    ``key_fact_ids`` the facts a reader must know first; ``counters``
    receives ``redundant_lines``. A meeting with one coherent subject gets
    no topic headings at all. What was left out of the notes is not written
    here: it is ``excluded_ranges`` on the generation, for the client.
    """
    keys_by_role: dict[str, list[str]] = {}
    for key, role in role_by_key.items():
        keys_by_role.setdefault(role, []).append(key)
    labels = ROLE_LABELS.get(language, ROLE_LABELS["en"])

    out: list[RenderedSection] = []

    def emit(role: str, text: str, used: list[VerifiedFact], lines: list[Line]) -> None:
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
            RenderedSection(
                section_key=key,
                role=role,
                text=text,
                facts=tuple(used),
                title=title,
                lines=tuple(lines),
            )
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
        emit(
            roles.AGENDA,
            "\n".join(plain_line(f, language) for f in agenda),
            agenda,
            [fact_line(f, plain_line(f, language)) for f in agenda],
        )

    # ── Decisions ───────────────────────────────────────────────────
    decisions = grouped.get(schema.DECISION, [])
    if decisions:
        emit(
            roles.DECISIONS,
            "\n".join(decision_line(f, language) for f in decisions),
            decisions,
            [fact_line(f, decision_line(f, language)) for f in decisions],
        )

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
            action_lines(actions, language=language, counterpart=counterpart),
        )

    # ── Open questions ──────────────────────────────────────────────
    questions = grouped.get(schema.OPEN_QUESTION, [])
    if questions:
        emit(
            roles.OPEN_QUESTIONS,
            "\n".join(plain_line(f, language) for f in questions),
            questions,
            [fact_line(f, plain_line(f, language)) for f in questions],
        )

    # ── Risks ───────────────────────────────────────────────────────
    risks = grouped.get(schema.RISK, [])
    if risks:
        emit(
            roles.RISKS,
            "\n".join(plain_line(f, language) for f in risks),
            risks,
            [fact_line(f, plain_line(f, language)) for f in risks],
        )

    # ── Next meeting ────────────────────────────────────────────────
    nexts = grouped.get(schema.NEXT_MEETING, [])
    if nexts:
        emit(
            roles.NEXT_MEETING,
            "\n".join(plain_line(f, language) for f in nexts),
            nexts,
            [fact_line(f, plain_line(f, language)) for f in nexts],
        )

    # ── Key dates (Q5): what the recording scheduled or set a deadline
    #    for, from the dates its facts' quotes named. ──────────────────
    dated = key_dates(facts, meeting_date=meeting_date)
    if dated:
        date_lines = [
            Line(
                f"- {format_when(when, clock, language)} — {editorial(fact.text)}",
                "date",
                (fact.item_key,),
                (mention,) if mention else (),
            )
            for when, clock, fact, mention in dated
        ]
        emit(
            roles.KEY_DATES,
            "\n".join(line.text for line in date_lines),
            [fact for _w, _c, fact, _m in dated],
            date_lines,
        )

    # ── The family's own sections ───────────────────────────────────
    for role, owned in by_extra_role.items():
        if role in (roles.ACTION_ITEMS, roles.JUDGEMENT):
            continue  # actions are grouped above; judgements are never written
        existing = next((s for s in out if s.role == role), None)
        text = "\n".join(plain_line(f, language) for f in owned)
        owned_lines = [fact_line(f, plain_line(f, language)) for f in owned]
        if existing is None:
            emit(role, text, owned, owned_lines)
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
                lines=(*existing.lines, *owned_lines),
            )

    # ── Topics: one section each, headed by what the conversation
    #    was about there. None for a single-subject conversation. ────
    key_facts = [by_id[i] for i in dict.fromkeys(key_fact_ids or []) if i in by_id]
    key_facts = [f for f in key_facts if f.kind not in (schema.COMPLETION, schema.JUDGEMENT)]

    # The summary sentences, as written, with what they cite — a bullet
    # that says what a sentence already says is not written again (Q3).
    sentences: list[tuple[str, list[str]]] = []
    for entry in summary or []:
        sentence, cited_ids = (entry, []) if isinstance(entry, str) else entry
        written = editorial(strip_inline_ids(sentence)[0])
        own = list(dict.fromkeys([*cited_ids, *strip_inline_ids(sentence)[1]]))
        if written.strip():
            sentences.append((written, own))

    # One fact, once (Q3): what a decision, task or question section
    # already carries, and what an earlier topic already said, is not a
    # bullet again.
    rendered: set[str] = {f.item_key for section in out for f in section.facts}
    redundant = 0
    drafts: list[tuple[str, list[Line], list[VerifiedFact], int]] = []
    for title, bullets, fact_ids in topics or []:
        if not title.strip():
            continue
        cited = [by_id[i] for i in fact_ids if i in by_id]
        topic_lines: list[Line] = []
        for entry in bullets:
            # A bullet is ``(text, its fact ids)``; a bare string is the
            # older shape and cites the topic's facts.
            bullet, own_ids = (entry, list(fact_ids)) if isinstance(entry, str) else entry
            own = [by_id[i] for i in own_ids if i in by_id]
            bullet = editorial(bullet)
            # The reduce prompt lists facts as "id (kind, mm:ss): text" and
            # a small model may echo the whole line as a bullet. The id is
            # ours: swap in that fact's text and cite it.
            echoed = _ECHOED_FACT.match(bullet)
            if echoed is not None:
                fact = by_id.get(echoed.group("id"))
                bullet = fact.text if fact is not None else bullet[echoed.end() :]
                if fact is not None and fact not in own:
                    own.append(fact)
            bullet, inline = strip_inline_ids(bullet)
            for fact_id in inline:
                hit = by_id.get(fact_id)
                if hit is not None and hit not in own:
                    own.append(hit)
            if not bullet.strip():
                continue
            ids = set(_ids(own))
            if ids and (ids <= rendered or _said_by(bullet, ids, sentences, language)):
                redundant += 1
                continue
            rendered |= ids
            for fact in own:
                if fact not in cited:
                    cited.append(fact)
            bullet = patch_claim(bullet.strip(), own, language)
            topic_lines.append(Line(f"- {bullet}", "bullet", _ids(own)))
        first = min((f.start_ms for f in cited), default=10**12)
        drafts.append((title.strip(), topic_lines, cited, first))

    # A recording is read in its order (Q3), and a topic is two points or
    # more: a lone bullet joins the topic before it.
    drafts.sort(key=lambda d: d[3])
    kept_topics: list[tuple[str, list[Line], list[VerifiedFact]]] = []
    orphans: list[Line] = []
    for title, topic_lines, cited, _first in drafts:
        if len(topic_lines) >= MIN_BULLETS_PER_TOPIC:
            kept_topics.append((title, [*orphans, *topic_lines], cited))
            orphans = []
        elif topic_lines and kept_topics:
            prev_title, prev_lines, prev_cited = kept_topics[-1]
            kept_topics[-1] = (prev_title, [*prev_lines, *topic_lines], [*prev_cited, *cited])
        else:
            orphans.extend(topic_lines)
    if len(kept_topics) < 2:
        # One subject is no subject heading: everything reads as one list.
        orphans = [*orphans, *(line for _t, lines_, _c in kept_topics for line in lines_)]
        kept_topics = []
    elif orphans:
        title, lines_, cited = kept_topics[-1]
        kept_topics[-1] = (title, [*lines_, *orphans], cited)
        orphans = []

    topic_sections: list[RenderedSection] = []
    taken: set[str] = set(role_by_key)
    for title, topic_lines, cited in kept_topics:
        key = roles.generated_key(title, taken)
        taken.add(key)
        topic_sections.append(
            RenderedSection(
                section_key=key,
                role=roles.TOPICS,
                text="\n".join(line.text for line in topic_lines),
                facts=tuple({f.item_key: f for f in cited}.values()),
                title=title,
                lines=tuple(topic_lines),
            )
        )

    # ── The opening block: no heading. It is the note. ──────────────
    # Framing and summary. The facts themselves live in their topics; with
    # no topics they are one list here — key facts first. Nothing else:
    # what was left out of the notes is data for the client (Q3), never a
    # paragraph a renderer could mistake for somebody speaking.
    overview: list[tuple[str, list[Line]]] = []
    if framing.strip():
        framed = editorial(strip_inline_ids(framing)[0])
        # The framing is written about the conversation, from the facts
        # the context pass named as the ones to know first.
        overview.append((framed, [Line(framed, "framing", _ids(key_facts) or _ids(facts))]))
    for written, own in sentences:
        overview.append((written, [Line(written, "summary", tuple(own))]))
    used: list[VerifiedFact] = []
    if not topic_sections:
        listed = [*key_facts]
        listed += [f for f in grouped.get(schema.KEY_POINT, []) if f not in listed]
        in_sections = {f.item_key for section in out for f in section.facts}
        listed = [f for f in listed if f.item_key not in in_sections]
        list_lines = [Line(plain_line(f, language), "key_point", (f.item_key,)) for f in listed]
        # A bullet left over from a dissolved topic says a listed fact again
        # when every fact it cites is already on the list: once is enough.
        # A listed fact a summary sentence already says (same fact, mostly
        # the same words) is not listed again — rule 2, applied to the list.
        said = [
            line
            for line in list_lines
            if _said_by(line.text, set(line.fact_ids), sentences, language)
        ]
        redundant += len(said)
        list_lines = [line for line in list_lines if line not in said]
        listed_ids = {f.item_key for f in listed} | in_sections
        for line in orphans:
            if line.fact_ids and set(line.fact_ids) <= listed_ids:
                redundant += 1
                continue
            list_lines.append(line)
        if list_lines:
            overview.append(("\n".join(line.text for line in list_lines), list_lines))
            used.extend(listed)
    if counters is not None:
        counters["redundant_lines"] = counters.get("redundant_lines", 0) + redundant
    kept = [(block, block_lines) for block, block_lines in overview if block and block.strip()]
    text = "\n\n".join(block for block, _ in kept)
    if text:
        out.insert(
            0,
            RenderedSection(
                section_key=roles.OVERVIEW_KEY,
                role=roles.SUMMARY,
                text=text,
                facts=tuple(used),
                lines=tuple(line for _, block_lines in kept for line in block_lines),
            ),
        )
    out.extend(topic_sections)
    return [_with_dates(section, by_id) for section in out]


# A bullet restating a summary sentence: same facts, mostly same words.
SAID_BY_SENTENCE_JACCARD: Final = 0.6
MIN_BULLETS_PER_TOPIC: Final = 2


def _said_by(
    bullet: str, ids: set[str], sentences: list[tuple[str, list[str]]], language: str
) -> bool:
    """Whether a summary sentence already says this bullet: it cites every
    fact the bullet does, and shares most of its words."""
    mine = set(support.content_tokens(bullet, language))
    for sentence, cited in sentences:
        if not ids <= set(cited):
            continue
        theirs = set(support.content_tokens(sentence, language))
        union = mine | theirs
        if union and len(mine & theirs) / len(union) >= SAID_BY_SENTENCE_JACCARD:
            return True
    return False


def key_dates(
    facts: list[VerifiedFact], *, meeting_date: date | None = None
) -> list[tuple[date, time | None, VerifiedFact, DateMention | None]]:
    """``[(date, time, fact, mention)]``, one per distinct date and time, in
    order — what the recording scheduled or set a deadline for.

    From the dates the facts' QUOTES named (Q3) and from resolved due
    dates. Not the recording day itself (every "heute" would be a key date)
    and not a past event ("am Montag … gewesen"): a reader looks here for
    what is coming. An unparsed phrase ("Ende des Jahres") is not a date."""
    seen: dict[tuple[date, time | None], tuple[VerifiedFact, DateMention | None]] = {}
    for fact in sorted(facts, key=lambda f: f.start_ms):
        found: list[tuple[date, time | None, DateMention | None]] = [
            (m.resolved, m.time, m) for m in fact.mentions if m.direction != "past"
        ]
        if fact.due_date and not any(d == fact.due_date for d, _t, _m in found):
            found.append((fact.due_date, None, None))
        for when, clock, mention in found:
            if meeting_date is not None and when == meeting_date and clock is None:
                continue
            if meeting_date is not None and when < meeting_date:
                continue
            seen.setdefault((when, clock), (fact, mention))
    return [
        (when, clock, fact, mention)
        for (when, clock), (fact, mention) in sorted(
            seen.items(), key=lambda item: (item[0][0], item[0][1] or time(0, 0))
        )
    ]


def format_when(when: date, clock: time | None, language: str) -> str:
    """``23.09.2026 00:00`` (de, uk) / ``2026-09-23 00:00`` (en)."""
    day = when.isoformat() if language == "en" else when.strftime("%d.%m.%Y")
    return f"{day} {clock:%H:%M}" if clock else day


def _with_dates(section: RenderedSection, by_id: dict[str, VerifiedFact]) -> RenderedSection:
    """Every line carries the dates its facts mention (Q3). The text is
    not touched: a date is an annotation, never a rewrite."""
    lines = tuple(
        replace(
            line,
            dates=tuple(
                dict.fromkeys(m for i in line.fact_ids if i in by_id for m in by_id[i].mentions)
            ),
        )
        for line in section.lines
    )
    return replace(section, lines=lines)


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


def action_lines(
    actions: list[VerifiedFact], *, language: str = "en", counterpart: str = ""
) -> list[Line]:
    """:func:`action_text`, line by line — the same grouping, the same
    headings, in the same order."""
    sided = [f for f in actions if f.side]
    if not sided:
        return [fact_line(f, action_line(f)) for f in actions]
    headings = SIDE_HEADINGS.get(language, SIDE_HEADINGS["en"])
    other = counterpart or ("the client" if language == "en" else "")
    groups = [
        (headings["ours"], [f for f in actions if f.side == "ours"]),
        (
            headings["theirs"].format(other=other).strip() or headings["unknown"],
            [f for f in actions if f.side == "theirs"],
        ),
        (headings["unknown"], [f for f in actions if not f.side]),
    ]
    out: list[Line] = []
    for title, owned in groups:
        if not owned:
            continue
        out.append(Line(f"### {title}", "heading", _ids(owned)))
        out.extend(fact_line(f, action_line(f)) for f in owned)
    return out


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
