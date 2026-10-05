"""Facts into the text of a document; deterministic, no model.

Actions use the `Owner: task — due` grammar `parse_action_lines` reads back; an
empty section is left blank, never filled. `user_notes` belongs to the author.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, time
from typing import Final

from .. import lines as line_rules
from . import roles, schema, support
from .verify import DateMention, Figure, Person, VerifiedFact, is_copied

_ECHOED_FACT: Final = re.compile(
    r"^\s*(?:\[\]\s*)?(?P<id>[0-9a-f]{16})\s*\([a-z_]+,\s*\d{1,2}:\d{2}\):\s*"
)
# Fact ids a small model writes into the prose as well as into `fact_ids`.
_INLINE_IDS: Final = re.compile(r"\s*\(?\b(?P<ids>[0-9a-f]{16}(?:\s*,\s*[0-9a-f]{16})*)\b\)?")


# Flat passive openers ("It was noted that"). Openers that carry certainty
# ("It was estimated that") are NOT here: stripping one would make an estimate a fact.
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


# Section keys for roles the template lacks. `action_items` is literal: the item
# projection, the recipient page and carry-over all read that key.
FALLBACK_KEYS: Final[dict[str, str]] = {
    roles.DECISIONS: "decisions",
    roles.ACTION_ITEMS: "action_items",
    roles.OPEN_QUESTIONS: "open_questions",
    roles.RISKS: "risks",
    roles.NEXT_MEETING: "next_meeting",
    roles.KEY_DATES: "key_dates",
    roles.SPECIFICATIONS: "specifications",
    roles.CONTACT: "call_to_action",
}
ROLE_LABELS: Final[dict[str, dict[str, str]]] = {
    "en": {
        roles.DECISIONS: "Decisions",
        roles.ACTION_ITEMS: "Action items",
        roles.OPEN_QUESTIONS: "Open questions",
        roles.RISKS: "Risks",
        roles.NEXT_MEETING: "Next meeting",
        roles.KEY_DATES: "Key dates",
        roles.SPECIFICATIONS: "Specifications",
        roles.CONTACT: "Contact",
    },
    "de": {
        roles.DECISIONS: "Entscheidungen",
        roles.ACTION_ITEMS: "Aufgaben",
        roles.OPEN_QUESTIONS: "Offene Fragen",
        roles.RISKS: "Risiken",
        roles.NEXT_MEETING: "Nächstes Treffen",
        roles.KEY_DATES: "Termine & Fristen",
        roles.SPECIFICATIONS: "Technische Daten",
        roles.CONTACT: "Kontakt",
    },
    "uk": {
        roles.DECISIONS: "Рішення",
        roles.ACTION_ITEMS: "Завдання",
        roles.OPEN_QUESTIONS: "Відкриті питання",
        roles.RISKS: "Ризики",
        roles.NEXT_MEETING: "Наступна зустріч",
        roles.KEY_DATES: "Дати та терміни",
        roles.SPECIFICATIONS: "Характеристики",
        roles.CONTACT: "Контакт",
    },
}


# A schema field name ("fact_ids:", "(fact ids") echoed into a line, whole or cut off.
_FIELD_LABEL: Final = re.compile(r"\s*[(\[]?\s*\bfact[_ ]?ids?\b\s*[:=]?\s*[)\]]?", re.IGNORECASE)


def strip_inline_ids(text: str) -> tuple[str, list[str]]:
    """The text without the fact ids the model wrote into it, and those ids (still citations)."""
    if _FIELD_LABEL.search(text):
        text = _FIELD_LABEL.sub(" ", text)
        text = " ".join(re.sub(r"\s+([.,;:!?])", r"\1", text).split())
        text = re.sub(r"([.,;:!?])\1+", r"\1", text)
    found: list[str] = []
    for match in _INLINE_IDS.finditer(text):
        found.extend(i.strip() for i in match.group("ids").split(","))
    if not found:
        return text, []
    cleaned = _INLINE_IDS.sub("", text)
    cleaned = re.sub(r"\s+([.,;:!?])", r"\1", cleaned)
    return " ".join(cleaned.split()), found


# A template without a section for the role does not receive those facts.
KIND_TO_ROLE: Final[dict[str, str]] = {
    schema.DECISION: roles.DECISIONS,
    schema.ACTION: roles.ACTION_ITEMS,
    schema.OPEN_QUESTION: roles.OPEN_QUESTIONS,
    schema.KEY_POINT: roles.TOPICS,
    schema.AGENDA_ITEM: roles.AGENDA,
    schema.RISK: roles.RISKS,
    schema.NEXT_MEETING: roles.NEXT_MEETING,
}

# Agenda items are only believable from the top of the meeting.
AGENDA_FROM_FIRST_WINDOWS: Final = 2

# A client call's actions read as two lists; an unknown side gets its own group, never guessed.
SIDE_HEADINGS: Final[dict[str, dict[str, str]]] = {
    "en": {"ours": "We do", "theirs": "{other} does", "unknown": "Still to assign"},
    "de": {"ours": "Wir übernehmen", "theirs": "{other} übernimmt", "unknown": "Noch zuzuordnen"},
    "uk": {"ours": "Ми робимо", "theirs": "{other} робить", "unknown": "Ще розподілити"},
}


# The eval scores lines by kind; every line carries a citation.
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
        # A quote sub-point, written by code from its fact.
        "quote",
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
    """One written line and the facts it rests on; ``text`` is exactly the section's line."""

    text: str
    kind: str
    fact_ids: tuple[str, ...] = ()
    """Q3 — the dates its facts' quotes mention, resolved with their tense."""
    dates: tuple[DateMention, ...] = ()
    """F2 — for a sub-point, the text of the bullet it sits under."""
    parent: str | None = None


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
    """``- Anna: send the pricing proposal — by Tuesday``; the owner is omitted when
    unplaced or a diarizer label ("Speaker 3"), never invented."""
    from .roles_table import real_name

    return "- " + line_rules.render_item(
        marker="",
        owner=real_name(fact.owner_label),
        body=editorial(fact.text),
        due_text=fact.due_text,
    )


def decision_line(fact: VerifiedFact, language: str = "en") -> str:
    return f"- {patch_claim(editorial(fact.text), [fact], language)}"


def plain_line(fact: VerifiedFact, language: str = "en") -> str:
    return f"- {patch_claim(editorial(fact.text), [fact], language)}"


def patch_claim(
    text: str, facts: list[VerifiedFact], language: str = "en", *, paragraph: bool = False
) -> str:
    """A claim line names its holder (``… — laut Reinbold``) and its certainty
    (``Voraussichtlich: …``), by code from the fact's fields.

    ``paragraph``: a paragraph opening with ``<word>: `` reads as a transcript turn
    on every client, so it gets the dash form; bullets keep the colon.
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
        joiner = " —" if paragraph else ":"
        text = f"{phrases[fact.certainty]}{joiner} {text}"
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
    presenter_lines: bool = False,
    subject: str = "",
    figure_tables: bool = True,
    recording_names: frozenset[str] = frozenset(),
) -> list[RenderedSection]:
    """The document, as the sections the conversation had.

    ``gen:overview`` (no heading) carries framing and summary; each topic is
    ``gen:<slug>``; role kinds go to the template's section for the role or one of
    their own, only when non-empty. Nobody is listed as an attendee.

    ``topics`` is ``[(title, [(bullet text, fact ids)], fact ids)]`` (bare bullet
    strings accepted); ``summary`` is ``[(sentence, fact ids)]`` or bare strings;
    ``counters`` receives ``redundant_lines``.
    """
    keys_by_role: dict[str, list[str]] = {}
    for key, role in role_by_key.items():
        keys_by_role.setdefault(role, []).append(key)
    labels = ROLE_LABELS.get(language, ROLE_LABELS["en"])

    out: list[RenderedSection] = []

    def emit(role: str, text: str, used: list[VerifiedFact], lines: list[Line]) -> None:
        """Into the template's section for the role, else a section of its own."""
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

    # Evidence-only facts may be cited, never written.
    grouped: dict[str, list[VerifiedFact]] = {}
    for fact in facts:
        if not fact.evidence_only:
            grouped.setdefault(fact.kind, []).append(fact)

    # The family's extra kinds first, so a family's own mapping of a kind wins.
    extra = {
        k: r for k, r in (kind_roles or {}).items() if k not in KIND_TO_ROLE and k not in _F3_KINDS
    }
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

    # ── Contact: what the recording asks its audience to do; never an action item ──
    contact = grouped.get(schema.NEXT_STEP, [])
    if contact:
        emit(
            roles.CONTACT,
            "\n".join(plain_line(f, language) for f in contact),
            contact,
            [Line(plain_line(f, language), "next_step", (f.item_key,)) for f in contact],
        )

    # ── Key dates, from the dates the facts' quotes named ───────────
    dated = key_dates([f for f in facts if not f.evidence_only], meeting_date=meeting_date)
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
            # A generic kind already wrote here: append, do not replace.
            out[out.index(existing)] = RenderedSection(
                section_key=existing.section_key,
                role=role,
                text=f"{existing.text}\n{text}",
                facts=(*existing.facts, *owned),
                title=existing.title,
                lines=(*existing.lines, *owned_lines),
            )

    # ── Topics: one section each; none for a single-subject conversation ──
    key_facts = [by_id[i] for i in dict.fromkeys(key_fact_ids or []) if i in by_id]
    key_facts = [f for f in key_facts if f.kind not in (schema.COMPLETION, schema.JUDGEMENT)]

    # A bullet that says what a summary sentence already says is not written again.
    sentences: list[tuple[str, list[str]]] = []
    for entry in summary or []:
        sentence, cited_ids = (entry, []) if isinstance(entry, str) else entry
        written = editorial(strip_inline_ids(sentence)[0])
        own = list(dict.fromkeys([*cited_ids, *strip_inline_ids(sentence)[1]]))
        if written.strip():
            sentences.append((written, own))

    # Figures are written by code from their fields; a bullet that only restates them is dropped.
    figures = _merged_figures([f for f in facts if f.figure is not None])
    figure_ids = {i for group in figures for i in group.ids}
    figure_topic: dict[str, str] = {}
    for title, bullets, fact_ids in topics or []:
        cited_here = list(fact_ids)
        for entry in bullets:
            if not isinstance(entry, str):
                cited_here.extend(entry[1])
                kids: list[tuple[str, list[str]]] = list(entry[2]) if len(entry) > 2 else []
                for _kid, kid_ids in kids:
                    cited_here.extend(kid_ids)
        for fact_id in cited_here:
            if fact_id in figure_ids:
                figure_topic.setdefault(fact_id, title.strip())

    # A topic's figures count towards it being a topic.
    figures_by_title: dict[str, int] = {}
    for group in figures:
        home = next((figure_topic[i] for i in group.ids if i in figure_topic), None)
        if home is not None:
            figures_by_title[home] = figures_by_title.get(home, 0) + 1

    # One fact, once: already-rendered facts are not a bullet again.
    rendered: set[str] = {f.item_key for section in out for f in section.facts}
    redundant = 0
    drafts: list[tuple[str, list[Line], list[VerifiedFact], int]] = []
    for title, bullets, fact_ids in topics or []:
        if not title.strip():
            continue
        cited = [by_id[i] for i in fact_ids if i in by_id]
        topic_lines: list[Line] = []
        for entry in bullets:
            # ``(text, ids)``, ``(text, ids, [(child text, child ids)])``, or a bare
            # string citing the topic's facts.
            children: list[tuple[str, list[str]]] = []
            if isinstance(entry, str):
                bullet, own_ids = entry, list(fact_ids)
            else:
                bullet, own_ids = entry[0], list(entry[1])
                if len(entry) > 2:
                    children = list(entry[2])
            made = _bullet_text(bullet, own_ids, by_id)
            if made is None:
                continue
            bullet, own_facts = made
            if own_facts and all(f.item_key in figure_ids for f in own_facts):
                redundant += 1  # the figure lines say it, with the value as spoken
                continue
            ids = set(_ids(own_facts))
            # A parent already said takes its sub-points with it.
            if ids and (ids <= rendered or _said_by(bullet, ids, sentences, language)):
                redundant += 1
                continue
            rendered |= ids
            for fact in own_facts:
                if fact not in cited:
                    cited.append(fact)
            bullet = patch_claim(bullet.strip(), own_facts, language)
            parent_line = Line(f"- {bullet}", "bullet", _ids(own_facts))
            topic_lines.append(parent_line)
            for entry in children[:MAX_CHILDREN]:
                child_text, child_ids = entry[0], entry[1]
                if len(entry) > 2 and entry[2] == "quote":
                    # A quote sub-point: rendered from the fact's quote, never patched.
                    quoted = [by_id[i] for i in child_ids if i in by_id]
                    if not quoted:
                        continue
                    rendered |= set(_ids(quoted))
                    cited.extend(f for f in quoted if f not in cited)
                    topic_lines.append(
                        Line(f"  - {child_text}", "quote", _ids(quoted), parent=parent_line.text)
                    )
                    continue
                child = _bullet_text(child_text, child_ids, by_id)
                if child is None or not child[1]:
                    continue
                text, child_own = child
                rendered |= set(_ids(child_own))
                for fact in child_own:
                    if fact not in cited:
                        cited.append(fact)
                text = patch_claim(text.strip(), child_own, language)
                topic_lines.append(
                    Line(f"  - {text}", "bullet", _ids(child_own), parent=parent_line.text)
                )
        first = min((f.start_ms for f in cited), default=10**12)
        drafts.append((title.strip(), topic_lines, cited, first))

    # Recording order; a topic is two points or more, a lone bullet joins the one before.
    drafts.sort(key=lambda d: d[3])
    kept_topics: list[tuple[str, list[Line], list[VerifiedFact]]] = []
    orphans: list[Line] = []
    for title, topic_lines, cited, _first in drafts:
        points = sum(1 for line in topic_lines if line.parent is None)
        if points + figures_by_title.get(title, 0) >= MIN_BULLETS_PER_TOPIC:
            kept_topics.append((title, [*orphans, *topic_lines], cited))
            orphans = []
        elif topic_lines and kept_topics:
            prev_title, prev_lines, prev_cited = kept_topics[-1]
            kept_topics[-1] = (prev_title, [*prev_lines, *topic_lines], [*prev_cited, *cited])
        else:
            orphans.extend(topic_lines)
    # Bullets live only under headings; a lone bullet with no topic is left to the Detailed view.
    if kept_topics and orphans:
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

    # ── Figures ──────────────────────────────────────────────────────
    by_title = {section.title: n for n, section in enumerate(topic_sections)}
    homeless: list[_FigureGroup] = []
    placed: dict[int, list[_FigureGroup]] = {}
    for group in figures:
        home = next((figure_topic[i] for i in group.ids if i in figure_topic), None)
        if home is not None and home in by_title:
            placed.setdefault(by_title[home], []).append(group)
        else:
            homeless.append(group)
    # Topics with too few figures for a table pool them into one Specifications table.
    small = {i: g for i, g in placed.items() if len(g) < MIN_TABLE_FIGURES}
    pooled = [g for groups in small.values() for g in groups] + homeless
    if len(pooled) >= MIN_TABLE_FIGURES and small:
        for i in small:
            del placed[i]
        homeless = sorted(pooled, key=lambda g: g.facts[0].start_ms)
    # Figures form a block only in a demo/lecture or when measured; else they stay in statements.
    placed = {i: g for i, g in placed.items() if figure_tables or _measured(g)}
    if not (figure_tables or _measured(homeless)):
        homeless = []
    for index, groups in placed.items():
        section = topic_sections[index]
        text, figure_lines = _figure_block(groups, language)
        topic_sections[index] = replace(
            section,
            text=f"{section.text}\n\n{text}" if section.text else text,
            facts=(*section.facts, *(f for g in groups for f in g.facts)),
            lines=(*section.lines, *figure_lines),
        )
    if homeless:
        text, figure_lines = _figure_block(homeless, language)
        emit(roles.SPECIFICATIONS, text, [f for g in homeless for f in g.facts], figure_lines)

    # ── The opening block: no heading, two paragraphs of prose, never a list ──
    overview: list[tuple[str, list[Line]]] = []
    first_lines: list[Line] = []
    if framing.strip():
        framed = editorial(strip_inline_ids(framing)[0])
        first_lines.append(Line(framed, "framing", _ids(key_facts) or _ids(facts)))
    # Presenter/guest are named in the framing (compose.speakers_of); a "Gast: X"
    # paragraph would read as a transcript turn on every client.
    del presenter_lines
    if first_lines:
        overview.append(("\n".join(line.text for line in first_lines), first_lines))
    summary_lines: list[Line] = []
    for written, own in sentences:
        if own and all(i in figure_ids for i in own):
            redundant += 1  # the figures are written from their fields, with a source
            continue
        summary_lines.append(Line(written, "summary", tuple(own)))
    if summary_lines:
        overview.append(("\n".join(line.text for line in summary_lines), summary_lines))
    used: list[VerifiedFact] = []
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


def _bullet_text(
    text: str, own_ids: list[str], by_id: dict[str, VerifiedFact]
) -> tuple[str, list[VerifiedFact]] | None:
    """A model-written bullet, cleaned, with the facts it cites; None for an empty
    line, an echoed evidence-only fact, or a copy of a cited quote."""
    own = [by_id[i] for i in own_ids if i in by_id]
    bullet = editorial(text)
    # A small model may echo the prompt's "id (kind, mm:ss): text" line: swap in the fact.
    echoed = _ECHOED_FACT.match(bullet)
    if echoed is not None:
        fact = by_id.get(echoed.group("id"))
        if fact is not None and fact.evidence_only:
            return None
        bullet = fact.text if fact is not None else bullet[echoed.end() :]
        if fact is not None and fact not in own:
            own.append(fact)
    bullet, inline = strip_inline_ids(bullet)
    for fact_id in inline:
        hit = by_id.get(fact_id)
        if hit is not None and hit not in own:
            own.append(hit)
    if not bullet.strip():
        return None
    if any(is_copied(bullet, f.quote) for f in own):
        return None
    return bullet, own


# Sub-points per bullet, one level deep.
MAX_CHILDREN: Final = 3

# ── Figures, presenter ─────────────────────────────────────────────

_F3_KINDS: Final = frozenset({schema.FIGURE, schema.INTRODUCTION, schema.NEXT_STEP})
# From this many figures on, one subject's figures are a table.
MIN_TABLE_FIGURES: Final = 3
FIGURE_CONFLICT: Final = "figure_conflict"
_TABLE_HEAD: Final[dict[str, tuple[str, str]]] = {
    "en": ("Quantity", "Value"),
    "de": ("Größe", "Wert"),
    "uk": ("Величина", "Значення"),
}
PRESENTER_LABELS: Final[dict[str, tuple[str, str, str]]] = {
    # (presenter, somebody introduced, "with" between role and organisation)
    "en": ("Presenter", "Introduced", "with"),
    "de": ("Präsentiert von", "Vorgestellt", "bei"),
    "uk": ("Ведучий", "Представлено", "—"),
}
# A speaker with turns of their own who is not the recording's voice.
GUEST_LABELS: Final[dict[str, str]] = {"en": "Guest", "de": "Gast", "uk": "Гість"}


@dataclass(slots=True)
class _FigureGroup:
    """One figure as written: the facts that said it (duplicates merged)."""

    facts: list[VerifiedFact]

    @property
    def figure(self) -> Figure:
        figure = self.facts[0].figure
        assert figure is not None
        return figure

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(f.item_key for f in self.facts)


def _merged_figures(facts: list[VerifiedFact]) -> list[_FigureGroup]:
    """In speech order. The same name with the same value is one figure;
    the same name with another value is two figures, each flagged."""
    groups: list[_FigureGroup] = []
    for fact in sorted(facts, key=lambda f: f.start_ms):
        fig = fact.figure
        assert fig is not None
        same = next(
            (
                g
                for g in groups
                if g.figure.name.casefold() == fig.name.casefold()
                and g.figure.value == fig.value
                and g.figure.unit.casefold() == fig.unit.casefold()
            ),
            None,
        )
        if same is not None:
            same.facts.append(fact)
            continue
        groups.append(_FigureGroup([fact]))
    names: dict[str, list[_FigureGroup]] = {}
    for group in groups:
        names.setdefault(group.figure.name.casefold(), []).append(group)
    for clash in names.values():
        if len(clash) > 1:
            for group in clash:
                for fact in group.facts:
                    if FIGURE_CONFLICT not in fact.flags:
                        fact.flags.append(FIGURE_CONFLICT)
    return groups


def _measured(groups: list[_FigureGroup]) -> bool:
    """≥ 3 figures with ≥ 2 distinct quantity names that carry a unit."""
    named = {g.figure.name.casefold() for g in groups if g.figure.unit}
    return len(groups) >= MIN_TABLE_FIGURES and len(named) >= 2


def _has_date(text: str) -> bool:
    from .verify import _has_date_word

    return _has_date_word(text)


def _cell(text: str) -> str:
    return text.replace("|", "/").strip()


def _figure_block(groups: list[_FigureGroup], language: str) -> tuple[str, list[Line]]:
    """A table from :data:`MIN_TABLE_FIGURES` on, else bullets. Every row
    and bullet cites the facts behind it; the table head cites nothing."""
    if len(groups) >= MIN_TABLE_FIGURES:
        head_q, head_v = _TABLE_HEAD.get(language, _TABLE_HEAD["en"])
        lines = [
            Line(f"| {head_q} | {head_v} |", "heading"),
            Line("|---|---|", "heading"),
        ]
        for group in groups:
            fig = group.figure
            lines.append(
                Line(f"| {_cell(fig.name)} | {_cell(fig.value_text)} |", "figure", group.ids)
            )
    else:
        lines = [
            Line(f"- {group.figure.name}: {group.figure.value_text}", "figure", group.ids)
            for group in groups
        ]
    return "\n".join(line.text for line in lines), lines


_ARTICLE: Final = re.compile(r"^(?:a|an|the|ein|eine|einen|der|die|das)\s+", re.IGNORECASE)


def presenter_text(person: Person, language: str = "en") -> str:
    """ "Presenter: Mitchell, broker with Springbrook Marine Group" from the verified fields."""
    label_self, label_other, joiner = PRESENTER_LABELS.get(language, PRESENTER_LABELS["en"])
    role = _ARTICLE.sub("", person.role).strip()
    org = person.organisation.strip()
    joiner = person.joiner or joiner
    what = f"{role} {joiner} {org}" if role and org else (role or org)
    text = person.name + (f", {what}" if what else "")
    qualifier = _ARTICLE.sub("", person.qualifier).strip()
    if qualifier:
        text += f" ({qualifier})"
    if person.standing == "guest":
        return f"{GUEST_LABELS.get(language, GUEST_LABELS['en'])}: {text}"
    return f"{label_self if person.self_introduction else label_other}: {text}"


def _presenter_lines(facts: list[VerifiedFact], language: str) -> list[Line]:
    """The first self-introduction is the presenter; anybody else a
    speaker introduced gets an "Introduced" line. Once per name."""
    out: list[Line] = []
    seen: set[str] = set()
    presenter = False
    for fact in sorted(facts, key=lambda f: f.start_ms):
        person = fact.person
        if person is None or person.name.casefold() in seen or person.standing == "clip":
            continue
        if person.self_introduction and person.standing == "presenter" and presenter:
            continue
        seen.add(person.name.casefold())
        presenter = presenter or (person.self_introduction and person.standing == "presenter")
        out.append(Line(presenter_text(person, language), "presenter", (fact.item_key,)))
    return out


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
    """``[(date, time, fact, mention)]``, one per distinct date and time, in order,
    from the quotes' dates and resolved due dates; not the recording day, not past events."""
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
    """Every line carries the dates its facts mention; an annotation, never a rewrite."""
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
    """One list, or two groups when the facts carry a side; an unknown side is its own group."""
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
    """Named speakers only, in the order they first spoke."""
    seen: dict[str, None] = {}
    for fact in sorted(facts, key=lambda f: f.start_ms):
        if fact.speaker_name and fact.speaker_name not in seen:
            seen[fact.speaker_name] = None
    return list(seen)
