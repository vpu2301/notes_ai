"""F1-02 — the last boundary before generated prose is written.

Every asserted line (overview sentences, bullets, sub-points, item lines) is checked
after composition, attribution patching and doclint's repairs, against the transcript
lines of the facts it cites — the original evidence, never an earlier paraphrase — by
the verification stage (05-prompt-instructions.md, verification). Supported stays. A
contradicted line with a proposed correction is checked once more with the correction
in its place. Anything else leaves the asserted prose: a line citing one fact falls back
to that fact's verified text, any other is kept for review with its sources.

Not claims: structure (headings, the code-built opening, presenters, quotes, figure
rows) and a line that is exactly a cited fact's text (that fact passed extraction's
check). Pure apart from the verifier calls; never touches a person's text.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

from . import doclint, prompts, roles, schema, windows
from .render import Line, RenderedSection
from .verify import _NUMBER, VerifiedFact
from .windows import Turn, Window

logger = logging.getLogger(__name__)

# Part of every cached verdict's key and of the generation's stats.
VERSION: Final = "2026-10-18.final-check"
STRUCTURAL: Final = frozenset({"heading", "framing", "presenter", "quote", "figure"})
BATCH: Final = 8
MAX_TOKENS: Final = 1_500
TIMEOUT_S: Final = 90.0
# Reserved for this check alone (extraction retries cannot spend it): a check round and a
# repair round per batch, capped. What the cap leaves unchecked is kept for review.
CALLS_MAX: Final = 16
EVIDENCE_TURNS_MAX: Final = 9
# A review row's flag, and the generation's incomplete reason.
FINAL_UNVERIFIED: Final = "final_unverified"

_MARKER: Final = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+")
_END: Final = ".!?…"


@dataclass(slots=True)
class Budget:
    """This check's calls: ``limit`` for the job, ``used`` so far."""

    limit: int
    used: int = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


@dataclass(frozen=True, slots=True)
class Rejected:
    """A generated line kept out of the asserted prose, offered for review with its sources."""

    section_key: str
    line: Line
    reason: str


@dataclass(frozen=True, slots=True)
class _Claim:
    at: tuple[int, int]
    marker: str
    body: str
    cited: tuple[VerifiedFact, ...]
    evidence: tuple[Turn, ...]
    quote: str


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return " ".join(text.split()).strip().rstrip(_END).casefold()


def split_marker(text: str) -> tuple[str, str]:
    """``("  - ", "the claim")``: the line's list marker (with its indent) and its body."""
    match = _MARKER.match(text)
    return (match.group(0), text[match.end() :].strip()) if match else ("", text.strip())


def evidence_of(
    cited: Sequence[VerifiedFact],
    facts: dict[str, VerifiedFact],
    windows_by_index: dict[int, Window],
) -> tuple[tuple[Turn, ...], str]:
    """The transcript lines behind ``cited`` (each fact's line and its neighbours, merged
    sources too) and their quotes. Empty when no line can be found."""
    sources = list(cited)
    for fact in cited:
        sources.extend(facts[k] for k in fact.also if k in facts)
    seen: set[tuple[int, int]] = set()
    turns: list[Turn] = []
    quotes: list[str] = []
    for fact in sources:
        window = windows_by_index.get(fact.window_index)
        if fact.quote and fact.quote not in quotes:
            quotes.append(fact.quote)
        if window is None:
            continue
        for turn in window.around(fact.line if fact.line is not None else fact.turn):
            if (turn.number, turn.start_ms) not in seen:
                seen.add((turn.number, turn.start_ms))
                turns.append(turn)
    turns.sort(key=lambda t: t.start_ms)
    return tuple(turns[:EVIDENCE_TURNS_MAX]), " / ".join(quotes)


def claims_of(
    sections: Sequence[RenderedSection],
    facts: dict[str, VerifiedFact],
    windows_by_index: dict[int, Window],
    tally: Counter[str],
) -> tuple[list[_Claim], dict[tuple[int, int], str]]:
    """``(claims to check, {position: reason}`` for asserted lines that cannot be checked)."""
    claims: list[_Claim] = []
    unsupported: dict[tuple[int, int], str] = {}
    for si, section in enumerate(sections):
        for li, line in enumerate(section.lines):
            marker, body = split_marker(line.text)
            if line.kind in STRUCTURAL or not any(ch.isalpha() for ch in body):
                tally["structural"] += 1
                continue
            tally["claims"] += 1
            cited = tuple(facts[i] for i in dict.fromkeys(line.fact_ids) if i in facts)
            if any(_norm(f.text) == _norm(body) for f in cited):
                tally["fact_text"] += 1
                continue
            turns, quote = evidence_of(cited, facts, windows_by_index)
            if not turns:
                tally["no_evidence"] += 1
                unsupported[(si, li)] = "no_evidence"
                continue
            claims.append(_Claim((si, li), marker, body, cited, turns, quote))
    return claims, unsupported


def _numbers_said(text: str, claim: _Claim) -> bool:
    """Every number in a proposed correction is in the evidence it was checked against."""
    said = " ".join([claim.quote, *(t.text for t in claim.evidence)])
    known = {n.replace(",", "").replace(".", "") for n in _NUMBER.findall(said)}
    return all(
        not plain or plain in known
        for plain in (n.replace(",", "").replace(".", "") for n in _NUMBER.findall(text))
    )


async def _verdicts(
    verifier: Any,
    claims: list[_Claim],
    *,
    system: str,
    version: str,
    cache: dict[str, tuple[str, str | None]],
    budget: Budget,
    tally: Counter[str],
) -> dict[int, tuple[str, str | None]]:
    """``{claim index: (verdict, correction)}``; cached by claim text, evidence and the
    verifier's version. A failed, timed-out, malformed or unbudgeted batch decides nothing."""
    out: dict[int, tuple[str, str | None]] = {}
    keys = [
        f"{_sha(c.body)}:{_sha(chr(10).join(map(windows.render_line, c.evidence)) + c.quote)}:{version}"
        for c in claims
    ]
    todo: dict[str, int] = {}
    for n, key in enumerate(keys):
        if key in cache:
            out[n] = cache[key]
            tally["cached"] += 1
        else:
            todo.setdefault(key, n)
    pending = list(todo.items())
    for at in range(0, len(pending), BATCH):
        batch = pending[at : at + BATCH]
        if not budget.take():
            tally["budget"] += len(batch)
            continue
        ids = [f"c{n}" for n in range(1, len(batch) + 1)]
        items = [
            (
                cid,
                claims[n].body,
                claims[n].quote,
                [windows.render_line(t) for t in claims[n].evidence],
            )
            for cid, (_key, n) in zip(ids, batch, strict=True)
        ]
        tally["sent"] += len(batch)
        try:
            answer = await asyncio.wait_for(
                verifier.complete(
                    prompts.meaning_check_prompt(items),
                    schema.meaning_check_schema(len(batch)),
                    max_tokens=MAX_TOKENS,
                    temperature=0.0,
                    system=system,
                ),
                timeout=TIMEOUT_S,
            )
            text = getattr(answer, "text", answer)
            parsed = schema.MeaningCheckOut.model_validate_json(
                text if isinstance(text, str) else str(text)
            )
        except TimeoutError:
            tally["timeout"] += len(batch)
            logger.warning("meeting_doc.final_check_timeout", extra={"claims": len(batch)})
            continue
        except Exception:  # noqa: BLE001 — the lines stay out of the prose, kept for review
            tally["unavailable"] += len(batch)
            logger.warning("meeting_doc.final_check_failed", exc_info=True)
            continue
        if sorted(c.claim_id for c in parsed.checks) != sorted(ids):
            tally["malformed"] += len(batch)
            continue
        for given in parsed.checks:
            key, n = batch[ids.index(given.claim_id)]
            shown = {t.number for t in claims[n].evidence}
            try:
                cited = {int(e) for e in given.evidence_ids}
            except ValueError:
                cited = {-1}
            if not cited <= shown:
                tally["foreign_lines"] += 1
                continue
            found = (given.verdict, (given.corrected_claim or "").strip() or None)
            cache[key] = found
            out[n] = found
    # Identical claims on identical evidence share one verdict.
    for n, key in enumerate(keys):
        if n not in out and key in cache:
            out[n] = cache[key]
    return out


def verifier_version(verifier: Any, system: str) -> str:
    """What a cached verdict is only valid for: this check, the prompt version, the
    verifier's backend and model, and the exact system text (a profile's included)."""
    return _sha(
        "|".join(
            (
                VERSION,
                prompts.PROMPT_VERSION,
                str(getattr(verifier, "backend", "")),
                str(getattr(verifier, "model_id", "")),
                system,
            )
        )
    )[:24]


def _as_line(claim: _Claim, body: str, kind: str) -> str:
    body = body.strip()
    if kind == "summary" and not claim.marker:
        return body if body.endswith(tuple(_END)) else f"{body}."
    return f"{claim.marker}{body.rstrip('.')}"


async def validate(
    sections: Sequence[RenderedSection],
    *,
    facts: Sequence[VerifiedFact],
    windows_by_index: dict[int, Window],
    verifier: Any,
    language: str,
    task: prompts.Task,
    cache: dict[str, tuple[str, str | None]],
    tally: Counter[str],
) -> tuple[list[RenderedSection], list[Rejected]]:
    """The sections with every asserted line supported (or repaired and supported again,
    or fallen back to its one fact's text), and the lines kept out for review."""
    started = time.monotonic()
    by_id = {f.item_key: f for f in facts}
    claims, outcome = claims_of(sections, by_id, windows_by_index, tally)
    rewrites: dict[tuple[int, int], str] = {}
    budget = Budget(min(CALLS_MAX, 2 * math.ceil(len(claims) / BATCH)))
    system = prompts.meaning_check_system(language, task=task)
    version = verifier_version(verifier, system)
    found = await _verdicts(
        verifier, claims, system=system, version=version, cache=cache, budget=budget, tally=tally
    )
    repairs: list[tuple[int, _Claim]] = []
    for n, claim in enumerate(claims):
        verdict, corrected = found.get(n, ("undecided", None))
        tally[verdict] += 1
        if verdict == schema.SUPPORTED:
            continue
        if verdict == schema.CONTRADICTED and corrected:
            if _numbers_said(corrected, claim):
                repairs.append((n, replace(claim, body=corrected)))
                continue
            tally["repair_number"] += 1
        outcome[claim.at] = verdict
    again = await _verdicts(
        verifier,
        [c for _n, c in repairs],
        system=system,
        version=version,
        cache=cache,
        budget=budget,
        tally=tally,
    )
    for m, (_n, repaired) in enumerate(repairs):
        if again.get(m, ("undecided", None))[0] == schema.SUPPORTED:
            tally["repaired"] += 1
            si, li = repaired.at
            rewrites[repaired.at] = _as_line(repaired, repaired.body, sections[si].lines[li].kind)
        else:
            tally["repair_rejected"] += 1
            outcome[repaired.at] = "repair_rejected"
    # A line resting on one fact falls back to that fact's own (verified) text.
    claim_at = {c.at: c for c in claims}
    for at in list(outcome):
        held = claim_at.get(at)
        if held is None or len(held.cited) != 1 or held.cited[0].evidence_only:
            continue
        si, li = at
        rewrites[at] = _as_line(held, held.cited[0].text, sections[si].lines[li].kind)
        del outcome[at]
        tally["restored"] += 1
    out, rejected = _apply(sections, rewrites, outcome)
    tally["unverified"] += len(rejected)
    tally["calls"] += budget.used
    tally["latency_ms"] += int((time.monotonic() - started) * 1000)
    return out, rejected


def _apply(
    sections: Sequence[RenderedSection],
    rewrites: dict[tuple[int, int], str],
    dropped: dict[tuple[int, int], str],
) -> tuple[list[RenderedSection], list[Rejected]]:
    """Rewrites and drops applied; a dropped bullet's sub-points move up a level (its
    quotes go with it); a topic left with nothing asserted goes."""
    out: list[RenderedSection] = []
    rejected: list[Rejected] = []
    for si, section in enumerate(sections):
        if not any((si, li) in rewrites or (si, li) in dropped for li in range(len(section.lines))):
            out.append(section)
            continue
        lines: list[Line] = []
        renamed: dict[str, str] = {}
        gone: set[str] = set()
        for li, line in enumerate(section.lines):
            promoted = line.parent is not None and line.parent in gone
            if promoted:
                if line.kind == "quote":
                    continue
                line = replace(line, text=f"- {split_marker(line.text)[1]}", parent=None)
            elif line.parent is not None and line.parent in renamed:
                line = replace(line, parent=renamed[line.parent])
            if (si, li) in dropped:
                rejected.append(Rejected(section.section_key, line, dropped[(si, li)]))
                gone.add(section.lines[li].text)
                continue
            if (si, li) in rewrites:
                text = rewrites[(si, li)]
                if promoted:
                    text = f"- {split_marker(text)[1]}"
                renamed[section.lines[li].text] = text
                if any(x.text == text for x in lines):
                    continue
                line = replace(line, text=text)
            lines.append(line)
        asserted = [ln for ln in lines if ln.kind not in STRUCTURAL]
        if not asserted and roles.is_generated(section.section_key):
            continue
        out.append(replace(section, lines=tuple(lines), text=doclint.text_of(section, lines)))
    return out, rejected


def review_line(rejected: Rejected) -> Line:
    """The rejected line as stored for review: its own words, its citations."""
    return replace(rejected.line, text=split_marker(rejected.line.text)[1], parent=None)
