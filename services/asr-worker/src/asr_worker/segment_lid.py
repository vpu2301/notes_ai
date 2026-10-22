"""Segment-level language check (Sprint B3 T2).

Chunk LID cannot see a 12-second clip inside a 30-second run. After the decode, a
segment whose words are mostly another language's (a lexical test, free) or whose
``avg_logprob`` sits far below the recording's median (then the identifier names the
language) is decoded again in that language over its own audio span, and the decoder's
own ``avg_logprob`` decides which decode stays — never the lexical test alone, so a
German sentence full of English product names keeps its German decode. A segment whose
own words are the other language's keeps that label whichever decode stays.

A decoder pinned to one language also writes *nothing* for a clip in another: the words
before and after it come back and the clip leaves no segment. So a word-free stretch of
at least ``segment_lid_min_ms`` inside a speech run is identified too, and decoded in the
language the identifier is sure of. Runs for pinned languages too. Numbers only in
diagnostics and logs.
"""

from __future__ import annotations

import asyncio
import logging
import re
import statistics
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from uuid import UUID

import numpy as np
from opentelemetry import metrics

import telemetry
from asr_models import Diagnostics, Segment, SegmentDiagnostics, TranscriptionOutput
from asr_models.output import SegmentLanguage
from models import ProviderError

from . import chunks, guards
from . import coverage as cov
from .config import settings
from .vad import SpeechSegment

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.asr.worker.segment_lid")
_suspects_total = _meter.create_counter(
    "mdx_asr_segment_lid_suspects_total",
    description="Decoded segments decoded again in another language (Sprint B3), by trigger",
    unit="1",
)
_switched_total = _meter.create_counter(
    "mdx_asr_segment_lid_switched_total",
    description="Segments whose other-language decode was kept (Sprint B3)",
    unit="1",
)

# A segment this far (nats) below the recording's median avg_logprob is a suspect.
LOGPROB_BELOW_MEDIAN = 0.5
# A decode of a word-free stretch is kept at this avg_logprob or above (a sure decode).
GAP_MIN_LOGPROB = -1.0
# Fewer language markers than this say nothing about a segment.
MIN_MARKERS = 3
# Adjacent suspects of one language closer than this are decoded as one span.
JOIN_GAP_MS = 500
PAD_MS = 100

_WORD = re.compile(r"[^\W\d_]+")
_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_GERMAN_LETTERS = re.compile(r"[äöüßÄÖÜ]")
# Function words that are one language's and not another of ours ("in", "was", "an",
# "will", "her", "die" are left out because German and English share them).
EN_FUNCTION = frozenset(
    [
        "the",
        "of",
        "to",
        "and",
        "or",
        "but",
        "is",
        "are",
        "were",
        "be",
        "been",
        "it",
        "this",
        "that",
        "these",
        "those",
        "we",
        "you",
        "they",
        "he",
        "she",
        "not",
        "no",
        "as",
        "his",
        "their",
        "our",
        "your",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "would",
        "can",
        "could",
        "should",
        "about",
        "into",
        "than",
        "then",
        "there",
        "here",
        "what",
        "which",
        "who",
        "when",
        "where",
        "how",
        "with",
        "from",
        "by",
        "for",
        "on",
        "at",
    ]
)
DE_FUNCTION = frozenset(
    [
        "der",
        "das",
        "den",
        "dem",
        "des",
        "ein",
        "eine",
        "einen",
        "einem",
        "einer",
        "eines",
        "und",
        "oder",
        "aber",
        "nicht",
        "ist",
        "sind",
        "wird",
        "werden",
        "wurde",
        "ich",
        "du",
        "er",
        "sie",
        "es",
        "wir",
        "ihr",
        "auch",
        "noch",
        "schon",
        "nur",
        "sehr",
        "mit",
        "von",
        "zu",
        "zum",
        "zur",
        "auf",
        "aus",
        "bei",
        "nach",
        "für",
        "über",
        "unter",
        "vor",
        "wenn",
        "dass",
        "weil",
        "als",
        "wie",
        "hier",
        "dort",
        "dann",
        "doch",
        "mal",
        "jetzt",
        "haben",
        "hat",
        "hatte",
        "kann",
        "können",
        "muss",
        "soll",
        "mehr",
        "kein",
        "keine",
        "im",
        "ins",
        "diese",
        "dieser",
        "dieses",
        "sich",
    ]
)


def markers(text: str) -> dict[str, int]:
    """How many tokens of ``text`` mark each of our languages."""
    counts = {"en": 0, "de": 0, "uk": 0}
    for token in _WORD.findall(text):
        low = token.casefold()
        if _CYRILLIC.search(low):
            counts["uk"] += 1
        elif low in EN_FUNCTION:
            counts["en"] += 1
        elif low in DE_FUNCTION or _GERMAN_LETTERS.search(token):
            counts["de"] += 1
    return counts


def lexical_language(text: str, *, recording: str, share: float) -> str | None:
    """The other language whose markers make up ``share`` of the language markers in
    ``text`` (at least ``MIN_MARKERS`` of them), else None."""
    counts = markers(text)
    own = counts.get(recording, 0)
    others = [code for code in sorted(chunks.OTHER_LANGUAGES) if code != recording]
    best = max(others, key=lambda code: counts[code])
    foreign = counts[best]
    if foreign < MIN_MARKERS or foreign / (foreign + own) < share:
        return None
    return best


@dataclass
class _Suspect:
    start_ms: int
    end_ms: int
    language: str
    trigger: str  # "lexical" | "logprob" | "gap"
    indices: list[int] = field(default_factory=list)


def uncovered(
    speech: Sequence[SpeechSegment], segments: Sequence[Segment], *, min_ms: int
) -> list[tuple[int, int]]:
    """Stretches of at least ``min_ms`` inside a speech run that no word (or wordless
    segment) covers: what a pinned decoder left out."""
    covered: list[tuple[int, int]] = []
    for seg in segments:
        if seg.words:
            covered.extend((w.start_ms, w.end_ms) for w in seg.words)
        else:
            covered.append((seg.start_ms, seg.end_ms))
    covered.sort()
    out: list[tuple[int, int]] = []
    for run in speech:
        cursor = run.start_ms
        for a, b in covered:
            if b <= cursor or a >= run.end_ms:
                continue
            if a - cursor >= min_ms:
                out.append((cursor, a))
            cursor = max(cursor, b)
        if run.end_ms - cursor >= min_ms:
            out.append((cursor, run.end_ms))
    return out


def _weighted_logprob(diags: Sequence[SegmentDiagnostics]) -> float | None:
    """Duration-weighted mean avg_logprob; None when any entry lacks one."""
    total = 0.0
    weight = 0.0
    for d in diags:
        if d.avg_logprob is None:
            return None
        w = max(1, d.end_ms - d.start_ms)
        total += d.avg_logprob * w
        weight += w
    return total / weight if weight else None


async def rediscover(
    provider: object,
    pcm: np.ndarray,
    output: TranscriptionOutput,
    *,
    speech: Sequence[SpeechSegment],
    deadline: float,
    should_cancel: Callable[[], Awaitable[bool]] | None,
    job_id: UUID,
) -> TranscriptionOutput:
    """Suspect segments decoded again in the other language; the surer decode stays."""
    recording = output.language
    diags = list(output.diagnostics.segments)
    stats = SegmentLanguage(segments=len(output.segments))
    logprobs = [d.avg_logprob for d in diags if d.avg_logprob is not None]
    median = statistics.median(logprobs) if logprobs else None
    min_ms = settings.asr_segment_lid_min_ms
    share = settings.asr_segment_lid_foreign_share

    suspects: list[_Suspect] = []
    lid = None
    for k, seg in enumerate(output.segments):
        if seg.language and seg.language != recording:
            continue  # chunk LID already decoded it in its own language
        if seg.end_ms - seg.start_ms < min_ms or not seg.text.strip():
            continue
        language = lexical_language(seg.text, recording=recording, share=share)
        trigger = "lexical"
        if language is None:
            d = guards._diag_for(seg, diags)
            if (
                median is None
                or d is None
                or d.avg_logprob is None
                or d.avg_logprob >= median - LOGPROB_BELOW_MEDIAN
            ):
                continue
            if lid is None:
                lid = await chunks.identifier_for(provider)
            if lid.source == "unavailable":
                continue
            guess = await lid.run_language(pcm[seg.start_ms * 16 : seg.end_ms * 16])
            language = (
                chunks.other_language(guess, recording=recording) if guess is not None else None
            )
            if language is None:
                continue
            trigger = "logprob"
        last = suspects[-1] if suspects else None
        if (
            last is not None
            and last.language == language
            and last.indices[-1] == k - 1
            and seg.start_ms - last.end_ms <= JOIN_GAP_MS
        ):
            last.end_ms = seg.end_ms
            last.indices.append(k)
        else:
            suspects.append(_Suspect(seg.start_ms, seg.end_ms, language, trigger, [k]))
    # Stretches the pinned decoder wrote nothing for (B3: the clip that left no segment).
    for start_ms, end_ms in uncovered(speech, output.segments, min_ms=min_ms):
        if lid is None:
            lid = await chunks.identifier_for(provider)
        if lid.source == "unavailable":
            break
        guess = await lid.run_language(pcm[start_ms * 16 : end_ms * 16])
        language = chunks.other_language(guess, recording=recording) if guess is not None else None
        if language is None:
            continue
        suspects.append(_Suspect(start_ms, end_ms, language, "gap"))
    suspects.sort(key=lambda s: s.start_ms)
    if not suspects:
        return output.model_copy(
            update={
                "diagnostics": output.diagnostics.model_copy(update={"segment_language": stats})
            }
        )

    segments = list(output.segments)
    replaced: set[int] = set()
    fresh_all: list[Segment] = []
    fresh_diags_all: list[SegmentDiagnostics] = []
    dropped = list(output.diagnostics.dropped_segments)
    stale_diags: list[SegmentDiagnostics] = []
    relabel: dict[int, str] = {}
    for suspect in suspects:
        stats.suspects += 1
        counter = "gaps" if suspect.trigger == "gap" else suspect.trigger
        setattr(stats, counter, getattr(stats, counter) + 1)
        _suspects_total.add(1, {"trigger": suspect.trigger, "language": suspect.language})
        originals = [segments[k] for k in suspect.indices]
        original_diags = [guards._diag_for(seg, diags) for seg in originals]
        gap = suspect.trigger == "gap"
        original_lp = (
            _weighted_logprob([d for d in original_diags if d is not None])
            if originals and all(d is not None for d in original_diags)
            else None
        )
        if suspect.trigger == "lexical":
            # The words themselves are the other language's: the label holds whichever
            # decode stays below.
            for k in suspect.indices:
                relabel[k] = suspect.language
        if original_lp is None and not gap:
            stats.unavailable += 1
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 1.0:
            stats.skipped += 1
            continue
        slice_start = max(0, suspect.start_ms - PAD_MS)
        span = pcm[slice_start * 16 : (suspect.end_ms + PAD_MS) * 16]
        recovery = _recovery(provider, suspect.trigger, len(span) / 16_000)
        try:
            async with recovery:
                t_rec = time.monotonic()
                second = await asyncio.wait_for(
                    provider.transcribe(  # type: ignore[attr-defined]
                        span,
                        language=suspect.language,
                        prompt=None,
                        should_cancel=should_cancel,
                        second_pass=True,
                    ),
                    timeout=remaining,
                )
                recovery.set("wall_seconds", round(time.monotonic() - t_rec, 4))
        except (TimeoutError, ProviderError) as exc:
            logger.warning(
                "asr.segment_lid_failed",
                extra={
                    "job_id": str(job_id),
                    "start_ms": suspect.start_ms,
                    "error_class": type(exc).__name__,
                },
            )
            stats.skipped += 1
            continue
        fresh_lp = _weighted_logprob(second.diagnostics.segments)
        if fresh_lp is None:
            stats.unavailable += 1
            continue
        fresh = [
            seg.model_copy(update={"language": suspect.language, "speaker": None})
            for seg in cov.shift(second.segments, slice_start)
        ]
        fresh_diags = [
            d.model_copy(
                update={
                    "start_ms": d.start_ms + slice_start,
                    "end_ms": d.end_ms + slice_start,
                    "language": suspect.language,
                }
            )
            for d in second.diagnostics.segments
        ]
        # The other-language decode goes through the same gates.
        regated = guards.apply(
            second.model_copy(
                update={"segments": fresh, "diagnostics": Diagnostics(segments=fresh_diags)}
            ),
            speech,
        )
        fresh = list(regated.output.segments)
        if not any(seg.text.strip() for seg in fresh):
            continue
        if gap:
            # Nothing to compare with: a decode no worse than the recording's own, less
            # the margin, is speech the pinned decoder left out.
            floor = (median - LOGPROB_BELOW_MEDIAN) if median is not None else GAP_MIN_LOGPROB
            if fresh_lp < min(floor, GAP_MIN_LOGPROB):
                continue
        elif original_lp is None or fresh_lp <= original_lp:
            continue
        stats.switched += 1
        _switched_total.add(1, {"language": suspect.language})
        replaced.update(suspect.indices)
        fresh_all.extend(fresh)
        fresh_diags_all.extend(fresh_diags)
        dropped.extend(regated.output.diagnostics.dropped_segments)
        stale_diags.extend(d for d in original_diags if d is not None)
        logger.info(
            "asr.segment_language_switched",
            extra={
                "job_id": str(job_id),
                "start_ms": suspect.start_ms,
                "end_ms": suspect.end_ms,
                "language": suspect.language,
                "trigger": suspect.trigger,
                "logprob_before": round(original_lp, 3) if original_lp is not None else None,
                "logprob_after": round(fresh_lp, 3),
            },
        )

    for k, language in relabel.items():
        if k not in replaced:
            segments[k] = segments[k].model_copy(update={"language": language})
            stats.relabelled += 1
    kept = [seg for k, seg in enumerate(segments) if k not in replaced]
    final_segments = sorted([*kept, *fresh_all], key=lambda s: (s.start_ms, s.end_ms))
    stale = {id(d) for d in stale_diags}
    final_diags = sorted(
        [*(d for d in diags if id(d) not in stale), *fresh_diags_all],
        key=lambda d: (d.start_ms, d.second_pass),
    )
    logger.info(
        "asr.segment_language",
        extra={"job_id": str(job_id), **stats.model_dump()},
    )
    diagnostics = output.diagnostics.model_copy(
        update={
            "segments": final_diags,
            "dropped_segments": dropped,
            "segment_language": stats,
        }
    )
    return output.model_copy(update={"segments": final_segments, "diagnostics": diagnostics})


def _recovery(provider: object, trigger: str, seconds: float) -> telemetry.Span:
    """A segment re-decoded in another language: an ``asr_recovery`` span. It relabels rather
    than recovers lost speech, so ``recovered_words`` is not applicable."""
    s = telemetry.span("asr_recovery", "asr.segment_language")
    s.update(
        trigger_reason=f"segment_language.{trigger}",
        attempt=1,
        audio_reprocessed_seconds=round(seconds, 3),
        backend=settings.asr_backend,
        model=getattr(provider, "model_name", None),
    )
    s.missing("recovered_words", "not_applicable")
    s.missing("device", "unavailable")
    telemetry.add_audio_processed(seconds)
    return s
