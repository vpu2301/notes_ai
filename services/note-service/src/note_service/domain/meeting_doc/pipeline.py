"""Transcript in, document out.

    windows → extract (one model call each) → verify → merge
            → context (one model call) → reduce (two, in parallel) → render

The context pass reads the verified facts once and says what the
conversation was — its type, subject, themes, the facts a reader must
know first — before anything is written. Topics and summary are then
written about that conversation rather than about a pile of facts, and
the overview opens with a sentence a reader who was not there can use.

The shape is the sprint's architecture decision, and the reason for it is
in the middle of that line: **verify**. Every claim the model makes has to
survive a check against the words that were actually spoken before it can
reach a note. A window whose call fails is reported, not silently
dropped; a meeting where nothing verifies produces an empty document
rather than filler.

`run()` is used by the worker and, unchanged, by the eval harness — the
harness measures the production code or it measures nothing.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from . import merge as merge_rules
from . import prompts, render, roles, schema, types, verify, windows
from .verify import VerifiedFact
from .windows import Window

logger = logging.getLogger(__name__)

# One retry on a malformed answer; a second failure means this window is
# reported as failed rather than retried forever.
EXTRACT_ATTEMPTS = 2
# Output budgets are sized from the schema's own caps, not from a typical
# answer: a window may legally carry MAX_FACTS_PER_WINDOW facts of up to
# MAX_FACT_CHARS plus a 400-character quote each (~3 000 tokens), and a
# topics answer MAX_TOPICS × MAX_BULLETS_PER_TOPIC bullets. With 900 / 700
# a small model that used its allowance was cut off mid-JSON, the
# provider reported `context_exceeded`, and every window "failed" —
# the note stayed a bare transcript. Unused budget costs nothing.
EXTRACT_MAX_TOKENS = 3000
REDUCE_MAX_TOKENS = 2500


class ChatLike(Protocol):
    backend: str
    model_id: str

    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any] | None = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> Any: ...


@dataclass(slots=True)
class DocumentResult:
    """What one generation produced."""

    sections: list[render.RenderedSection] = field(default_factory=list)
    facts: list[VerifiedFact] = field(default_factory=list)
    windows_total: int = 0
    windows_done: int = 0
    windows_failed: int = 0
    """``[[start_ms, end_ms]]`` of the parts that could not be processed —
    so the note can say WHICH minutes are missing instead of apologising
    in general."""
    failed_ranges: list[list[int]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    backend: str | None = None
    model_id: str | None = None
    """Sprint 36 — carried items the recording says are done, and
    judgement values offered for a person to accept. Neither is a line
    of the document."""
    completions: list[VerifiedFact] = field(default_factory=list)
    judgements: list[VerifiedFact] = field(default_factory=list)
    """What the context pass understood — type, subject, themes, framing,
    key fact ids. Counts and short strings; no transcript."""
    brief: dict[str, Any] = field(default_factory=dict)
    """``[(start_ms, reason)]`` — passages the extractor set aside."""
    noise: list[tuple[int, str]] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return self.windows_failed > 0


async def run(
    result: dict[str, Any],
    *,
    provider: ChatLike,
    role_by_key: dict[str, str],
    language: str = "en",
    meeting_date: date | None = None,
    name_candidates: frozenset[str] = frozenset(),
    max_concurrency: int = 4,
    family: types.Family | None = None,
    carried: list[tuple[str, str]] | None = None,
    our_side: frozenset[str] = frozenset(),
    counterpart: str = "",
) -> DocumentResult:
    """Build a document from an ASR result.

    ``family`` (Sprint 36) decides which fact kinds this call may return
    and where each lands; ``carried`` is ``[(item_key, text)]`` for the
    items still open from the previous meeting, which the extractor may
    mark done — by their NUMBER in this list, never by free text.
    """
    family = family or types.FALLBACK
    kinds = types.fact_kinds(family)
    # `user_point` is the author's own; the engine never proposes one.
    offered = tuple(k for k in kinds if k != "user_point")
    if family.judgement_fields:
        offered = (*offered, schema.JUDGEMENT)
    carried = carried or []
    carried_keys = tuple(key for key, _ in carried)
    turns = windows.turns_from_result(result)
    built = windows.build_windows(turns)
    meeting_date = meeting_date or date.today()
    out = DocumentResult(
        windows_total=len(built), backend=provider.backend, model_id=provider.model_id
    )
    if not built:
        out.stats = {"reason": "empty_transcript"}
        return out

    stats = verify.VerifyStats()
    verified: list[VerifiedFact] = []
    flagged: list[tuple[int, int, str]] = []
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    extract_schema = schema.extract_schema(
        offered,
        judgement_fields=family.judgement_fields,
        carried_items=len(carried),
    )

    async def one(window: Window) -> tuple[Window, schema.ExtractOut | None]:
        async with semaphore:
            return window, await _extract(
                provider, window, language, extract_schema, carried=carried
            )

    for window, extracted in await asyncio.gather(*(one(w) for w in built)):
        if extracted is None:
            out.windows_failed += 1
            out.failed_ranges.append([window.start_ms, window.end_ms])
            continue
        out.windows_done += 1
        noise_turns = _noise_turns(extracted, window)
        flagged.extend(noise_turns)
        verified.extend(
            verify.verify_facts(
                extracted.facts,
                window=window,
                meeting_date=meeting_date,
                name_candidates=name_candidates,
                stats=stats,
                allowed_kinds=frozenset(offered),
                judgement_fields=frozenset(family.judgement_fields),
                carried_keys=carried_keys,
                our_side=our_side,
                noise_turns=frozenset(index for index, _ms, _reason in noise_turns),
            )
        )
    out.noise = sorted({(ms, reason) for _index, ms, reason in flagged})

    facts = merge_rules.merge_facts(verified)
    out.facts = facts
    # Completions and judgements are not lines of the document: one
    # ticks a carried item off, the other is offered under a field.
    document_facts = [f for f in facts if f.kind not in (schema.COMPLETION, schema.JUDGEMENT)]
    out.completions = [f for f in facts if f.kind == schema.COMPLETION]
    out.judgements = [f for f in facts if f.kind == schema.JUDGEMENT]

    topics: list[tuple[str, list[str], list[str]]] | None = None
    summary: list[str] | None = None
    brief: Brief | None = None
    if document_facts:
        # Understand the conversation first; then write topics and the
        # summary about it, side by side.
        brief = await _context(provider, document_facts, language)
        topics, summary = await asyncio.gather(
            _topics(provider, document_facts, language, brief=brief),
            _summary(provider, document_facts, language, brief=brief),
        )
    if brief is not None:
        out.brief = {
            "conversation_type": brief.conversation_type,
            "subject": brief.subject,
            "themes": brief.themes,
            "key_fact_ids": brief.key_fact_ids,
        }

    out.sections = render.render_sections(
        document_facts,
        role_by_key=role_by_key,
        topics=topics,
        summary=summary,
        kind_roles=kinds,
        language=language,
        counterpart=counterpart,
        framing=brief.framing if brief else "",
        key_fact_ids=brief.key_fact_ids if brief else None,
        noise=out.noise,
    )
    out.stats = {
        "facts_kept": stats.kept,
        "facts_dropped_quote": stats.dropped_quote,
        "facts_dropped_noise": stats.dropped_noise,
        "noise_passages": len(out.noise),
        "key_points": len(brief.key_fact_ids) if brief else 0,
        "facts_dropped_owner": stats.dropped_owner,
        "facts_downgraded": stats.downgraded,
        "numbers_removed": stats.numbers_removed,
        "invented_due": stats.invented_due,
        "facts_after_merge": len(facts),
        "prompt_version": prompts.PROMPT_VERSION,
        "section_hashes": section_hashes(out.sections),
    }
    return out


def section_hashes(sections: list[render.RenderedSection]) -> dict[str, str]:
    """``{section_key: sha256 of the text we wrote}``.

    The writer compares against these next time: a section whose text
    still equals what the last generation put there has not been touched
    by a person and may be rewritten. Anything else is the author's.
    """
    import hashlib

    return {s.section_key: hashlib.sha256(s.text.encode("utf-8")).hexdigest() for s in sections}


def _noise_turns(extracted: schema.ExtractOut, window: Window) -> list[tuple[int, int, str]]:
    """``[(turn index, start_ms, reason)]`` for the turns the extractor
    flagged — only ones that are in this window, only known reasons."""
    by_index = {t.index: t for t in window.turns}
    total_words = sum(len(t.text.split()) for t in window.turns) or 1
    out: list[tuple[int, int, str]] = []
    for flagged in extracted.noise:
        turn = by_index.get(flagged.turn)
        if turn is None or flagged.reason not in schema.NOISE_REASONS:
            continue
        # Noise is marginal by definition. A turn that is most of the
        # window IS the recording — an advertisement someone recorded is
        # still what they recorded — and a model that calls it background
        # would empty the note.
        if len(turn.text.split()) > total_words * schema.MAX_NOISE_SHARE:
            continue
        out.append((turn.index, turn.start_ms, flagged.reason))
    return out


@dataclass(slots=True)
class Brief:
    """The conversation as a whole, from the context pass."""

    conversation_type: str = ""
    subject: str = ""
    themes: list[str] = field(default_factory=list)
    framing: str = ""
    key_fact_ids: list[str] = field(default_factory=list)

    def block(self, language: str) -> str:
        return prompts.brief_block(
            conversation_type=self.conversation_type,
            subject=self.subject,
            themes=self.themes,
            key_fact_ids=self.key_fact_ids,
            language=language,
        )


# ── Model steps ─────────────────────────────────────────────────────


async def _extract(
    provider: ChatLike,
    window: Window,
    language: str,
    extract_schema: dict[str, Any] | None = None,
    *,
    carried: list[tuple[str, str]] | None = None,
) -> schema.ExtractOut | None:
    """One window. ``None`` when the model could not answer in shape."""
    prompt = prompts.extract_prompt(window.render(), language, carried=carried)
    system = prompts.extract_system(language)
    for attempt in range(EXTRACT_ATTEMPTS):
        try:
            answer = await provider.complete(
                prompt,
                extract_schema or schema.EXTRACT_SCHEMA,
                max_tokens=EXTRACT_MAX_TOKENS,
                temperature=0.0,
                system=system,
            )
            return schema.ExtractOut.model_validate_json(_json_of(answer))
        except Exception:  # noqa: BLE001 — one window must not stop a meeting
            if attempt + 1 >= EXTRACT_ATTEMPTS:
                logger.warning(
                    "meeting_doc.window_failed",
                    extra={"window": window.index},
                    exc_info=True,
                )
                return None
    return None


async def _context(provider: ChatLike, facts: list[VerifiedFact], language: str) -> Brief | None:
    """Read the facts as one conversation. Never sees the transcript.

    The framing sentence is the one line of the document that is written
    about the meeting rather than from a single fact, so it is checked the
    way a summary sentence is: every number in it must be in a fact.
    """
    if len(facts) < 3:
        return None
    block = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in facts])
    try:
        answer = await provider.complete(
            block,
            schema.REDUCE_CONTEXT_SCHEMA,
            max_tokens=REDUCE_MAX_TOKENS,
            temperature=0.0,
            system=prompts.context_system(language),
        )
        parsed = schema.ContextOut.model_validate_json(_json_of(answer))
    except Exception:  # noqa: BLE001
        logger.warning("meeting_doc.context_failed", exc_info=True)
        return None
    known = {f.item_key for f in facts}
    framing = parsed.framing.strip()
    if framing and not _numbers_supported(framing, facts):
        framing = ""
    return Brief(
        conversation_type=parsed.conversation_type.strip(),
        subject=parsed.subject.strip(),
        themes=[t.strip() for t in parsed.themes if t.strip()][: schema.MAX_THEMES],
        framing=framing,
        key_fact_ids=[i for i in dict.fromkeys(parsed.key_fact_ids) if i in known][
            : schema.MAX_KEY_POINTS
        ],
    )


def _with_brief(block: str, brief: Brief | None, language: str) -> str:
    context = brief.block(language) if brief else ""
    return f"{context}\n\n{block}" if context else block


async def _topics(
    provider: ChatLike,
    facts: list[VerifiedFact],
    language: str,
    *,
    brief: Brief | None = None,
) -> list[tuple[str, list[str], list[str]]] | None:
    """Cluster facts into topics. Never sees the transcript."""
    if len(facts) < schema.MIN_FACTS_FOR_TOPICS:
        # Too little to head: `render` writes one list, which is honest,
        # rather than inventing topics for a short conversation.
        return None
    block = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in facts])
    try:
        answer = await provider.complete(
            _with_brief(block, brief, language),
            schema.REDUCE_TOPICS_SCHEMA,
            max_tokens=REDUCE_MAX_TOKENS,
            temperature=0.0,
            system=prompts.topics_system(language),
        )
        parsed = schema.ReduceOut.model_validate_json(_json_of(answer))
    except Exception:  # noqa: BLE001
        logger.warning("meeting_doc.topics_failed", exc_info=True)
        return None

    known = {f.item_key for f in facts}
    out: list[tuple[str, list[str], list[str]]] = []
    for topic in parsed.topics:
        bullets = [
            b.text.strip()
            for b in topic.bullets
            # A bullet citing nothing we verified is a bullet the model
            # wrote from memory.
            if b.text.strip() and any(i in known for i in b.fact_ids)
        ]
        cited = [i for b in topic.bullets for i in b.fact_ids if i in known]
        cited += [i for i in topic.fact_ids if i in known]
        if topic.title.strip() and bullets:
            out.append((topic.title.strip(), bullets, list(dict.fromkeys(cited))))
    if len(out) < 2:
        return None
    return out[: schema.MAX_TOPICS]


async def _summary(
    provider: ChatLike,
    facts: list[VerifiedFact],
    language: str,
    *,
    brief: Brief | None = None,
) -> list[str] | None:
    block = prompts.facts_block([(f.item_key, f.kind, f.text, f.start_ms) for f in facts])
    try:
        answer = await provider.complete(
            _with_brief(block, brief, language),
            schema.REDUCE_SUMMARY_SCHEMA,
            max_tokens=REDUCE_MAX_TOKENS,
            temperature=0.0,
            system=prompts.summary_system(language),
        )
        parsed = schema.ReduceOut.model_validate_json(_json_of(answer))
    except Exception:  # noqa: BLE001
        logger.warning("meeting_doc.summary_failed", exc_info=True)
        return None

    by_id = {f.item_key: f for f in facts}
    out: list[str] = []
    for line in parsed.summary:
        sentence = line.sentence.strip()
        cited = [by_id[i] for i in line.fact_ids if i in by_id]
        if not sentence or not cited:
            # A sentence resting on nothing is the classic unsupported
            # summary line. Dropped, not softened.
            continue
        if not _numbers_supported(sentence, cited):
            continue
        out.append(sentence)
    return out[: schema.MAX_SUMMARY_SENTENCES] or None


def _numbers_supported(sentence: str, cited: list[VerifiedFact]) -> bool:
    """Every number in a summary sentence must be in a fact it cites."""
    said = " ".join(f"{f.text} {f.quote}" for f in cited)
    known = {n.replace(",", "").replace(".", "") for n in verify._NUMBER.findall(said)}
    for match in verify._NUMBER.findall(sentence):
        plain = match.replace(",", "").replace(".", "")
        if plain and plain not in known:
            return False
    return True


def _json_of(answer: Any) -> str:
    """The provider's text, whatever wrapper it came in."""
    text = getattr(answer, "text", answer)
    return text if isinstance(text, str) else str(text)


__all__ = ["DocumentResult", "run", "section_hashes", "roles"]
