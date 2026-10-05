"""Stage 5: abbreviation policy from the per-request snapshot (tenant beats global).

Direction compact/expand/either; domain match beats 'all' beats NULL.
Word-boundary matching is mandatory (never "ІМ" inside "імпорт").
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from functools import lru_cache

from ..pipeline.base import (
    AbbreviationEntry,
    ProcessingContext,
    StageInput,
    StageOutput,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    pattern: re.Pattern[str]
    replacement: str
    domain: str | None


class AbbreviationStage:
    """Stage 5: abbreviation expansion/compaction."""

    name = "abbreviation"
    runs_on_partials: bool = False

    async def process(self, ctx: ProcessingContext, input: StageInput) -> StageOutput:
        t0 = time.monotonic()
        rules = _compile_rules(ctx)
        new_text = input.text
        applied = 0
        for rule in rules:
            new_text, n = rule.pattern.subn(rule.replacement, new_text)
            applied += n
        return StageOutput(
            text=new_text,
            words=input.words,
            confidence_spans=input.confidence_spans,
            voice_commands=input.voice_commands,
            operations=input.operations,
            warnings=input.warnings,
            metadata={
                self.name + ".latency_ms": (time.monotonic() - t0) * 1000.0,
                self.name + ".applied": applied,
                self.name + ".snapshot_fingerprint": ctx.abbreviation_snapshot.fingerprint,
            },
        )


def _compile_rules(ctx: ProcessingContext) -> tuple[_CompiledRule, ...]:
    """Compiled regex rules, tenant overrides first; memoized on the immutable snapshot."""
    return _compile_rules_cached(ctx.abbreviation_snapshot.entries, ctx.category)


@lru_cache(maxsize=256)
def _compile_rules_cached(
    entries: tuple[AbbreviationEntry, ...], category: str | None
) -> tuple[_CompiledRule, ...]:
    relevant: list[AbbreviationEntry] = []
    seen: set[tuple[str, str]] = set()
    sorted_entries = sorted(
        entries,
        key=lambda e: (
            0 if e.is_tenant_override else 1,
            0 if e.domain == category else (1 if e.domain == "all" else 2),
        ),
    )
    for e in sorted_entries:
        key = (e.expanded.lower(), e.abbreviated.lower())
        if key in seen:
            continue
        seen.add(key)
        relevant.append(e)

    rules: list[_CompiledRule] = []
    for e in relevant:
        if e.direction == "either":
            continue
        if e.direction == "compact":
            src, dst = e.expanded, e.abbreviated
        else:  # expand
            src, dst = e.abbreviated, e.expanded
        flags = 0 if e.case_sensitive else re.IGNORECASE
        # Word-boundary on both sides; the Unicode flag matters for Cyrillic.
        pattern = re.compile(
            r"(?<![\wА-ЯЁІЇЄҐа-яёіїєґ])" + re.escape(src) + r"(?![\wА-ЯЁІЇЄҐа-яёіїєґ])",
            flags | re.UNICODE,
        )
        rules.append(_CompiledRule(pattern=pattern, replacement=dst, domain=e.domain))
    return tuple(rules)
