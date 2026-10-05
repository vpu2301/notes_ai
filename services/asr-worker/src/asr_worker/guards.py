"""Segment quality gates (G1 silence text, G2 loops, G3 low confidence, T3 artefacts).

Run after the decode for every backend. A segment VAD heard speech in is never
dropped by G1/G3/T3; a missing backend field skips that part of a gate and is counted
in ``diagnostics.gate_unavailable``. Gates off = ``dry_run`` records only.
Numbers and enum strings only reach diagnostics, logs and metrics.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from opentelemetry import metrics

from asr_models import (
    Diagnostics,
    DroppedSegment,
    KeptArtefact,
    Segment,
    SegmentDiagnostics,
    TranscriptionOutput,
)
from asr_models.artefacts import load_artefacts, match_artefact

from .config import settings
from .vad import SpeechSegment

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.asr.worker.guards")
_dropped_total = _meter.create_counter(
    "mdx_asr_guard_segments_dropped_total",
    description="Decoded segments a TQ2 quality gate removed (dry runs included), by reason",
    unit="1",
)
_artefact_total = _meter.create_counter(
    "mdx_asr_artefact_segments_total",
    description="Segments matching a known Whisper artefact phrase, by language and action",
    unit="1",
)

LOOP_MIN_N = 2
LOOP_MAX_N = 6
KEEP_REPETITIONS = 2


@dataclass
class GateResult:
    output: TranscriptionOutput
    # Ranges the second pass should decode again (G2).
    loop_ranges: list[tuple[int, int]] = field(default_factory=list)


def speech_share(start_ms: int, end_ms: int, speech: Sequence[SpeechSegment]) -> float:
    """Share of ``[start, end)`` VAD called speech; 1.0 for an empty span."""
    if end_ms <= start_ms:
        return 1.0
    covered = sum(max(0, min(end_ms, s.end_ms) - max(start_ms, s.start_ms)) for s in speech)
    return min(1.0, covered / (end_ms - start_ms))


def _diag_for(seg: Segment, diags: Sequence[SegmentDiagnostics]) -> SegmentDiagnostics | None:
    """The diagnostics entry overlapping this segment most."""
    if not diags:
        return None

    def overlap(d: SegmentDiagnostics) -> int:
        return min(seg.end_ms, d.end_ms) - max(seg.start_ms, d.start_ms)

    best = max(diags, key=overlap)
    if overlap(best) > 0 or best.start_ms <= seg.start_ms <= best.end_ms:
        return best
    return None


def _mean_word_prob(seg: Segment) -> float | None:
    if not seg.words:
        return None
    return sum(w.probability for w in seg.words) / len(seg.words)


def _norm(text: str) -> str:
    return " ".join("".join(ch for ch in text.casefold() if ch.isalnum() or ch.isspace()).split())


def loop_cut(tokens: Sequence[str], repeats: int) -> int | None:
    """First token to drop when a 2–6-gram repeats ``repeats`` times (two kept), else None."""
    norm = [_norm(t) for t in tokens]
    n_tok = len(norm)
    for n in range(LOOP_MIN_N, LOOP_MAX_N + 1):
        for i in range(0, n_tok - n * repeats + 1):
            gram = norm[i : i + n]
            if not any(gram):
                continue
            count = 1
            j = i + n
            while j + n <= n_tok and norm[j : j + n] == gram:
                count += 1
                j += n
            if count >= repeats:
                return i + n * KEEP_REPETITIONS
    return None


def _artefact_id(phrase: object) -> str:
    for k, p in enumerate(load_artefacts()):
        if p is phrase:
            return f"{p.language}:{k}"[:12]
    return "unknown"


def apply(output: TranscriptionOutput, speech: Sequence[SpeechSegment]) -> GateResult:
    """G1–G3 and the artefact rule on one decoded transcript."""
    enabled = settings.asr_gates_enabled
    dry = not enabled
    diags = output.diagnostics.segments
    unavailable: dict[str, int] = dict(output.diagnostics.gate_unavailable)
    unscored_words = unavailable.get("word_probability", 0) > 0
    dropped: list[DroppedSegment] = list(output.diagnostics.dropped_segments)
    kept_artefacts: list[KeptArtefact] = list(output.diagnostics.artefact_kept)
    loop_ranges: list[tuple[int, int]] = []
    out_segments: list[Segment] = []

    def record(
        seg: Segment, reason: str, d: SegmentDiagnostics | None, share: float, **kw: object
    ) -> None:
        dropped.append(
            DroppedSegment(
                start_ms=seg.start_ms,
                end_ms=max(seg.end_ms, seg.start_ms),
                reason=reason,  # type: ignore[arg-type]
                no_speech_prob=d.no_speech_prob if d else None,
                avg_logprob=d.avg_logprob if d else None,
                compression_ratio=d.compression_ratio if d else None,
                speech_share=round(share, 3),
                dry_run=dry,
                **kw,  # type: ignore[arg-type]
            )
        )
        _dropped_total.add(1, {"reason": reason, "dry_run": str(dry).lower()})

    previous_norm: str | None = None
    same_run = 0
    for seg in output.segments:
        d = _diag_for(seg, diags)
        share = speech_share(seg.start_ms, seg.end_ms, speech)
        nonspeech = share < settings.asr_gate_speech_share
        no_speech = d.no_speech_prob if d else None
        logprob = d.avg_logprob if d else None
        compression = d.compression_ratio if d else None
        for name, value in (
            ("no_speech_prob", no_speech),
            ("avg_logprob", logprob),
            ("compression_ratio", compression),
        ):
            if value is None:
                unavailable[name] = unavailable.get(name, 0) + 1

        # T3
        phrase = match_artefact(seg.text)
        if phrase is not None:
            ident = _artefact_id(phrase)
            if nonspeech or (
                no_speech is not None and no_speech >= settings.asr_gate_artefact_no_speech
            ):
                record(seg, "artefact", d, share, artefact=ident)
                _artefact_total.add(1, {"language": phrase.language, "action": "dropped"})
                if not enabled:
                    out_segments.append(seg)
                continue
            else:
                kept_artefacts.append(
                    KeptArtefact(
                        start_ms=seg.start_ms, end_ms=max(seg.end_ms, seg.start_ms), artefact=ident
                    )
                )
                _artefact_total.add(1, {"language": phrase.language, "action": "kept"})

        # G1; without a no_speech figure it rests on VAD alone.
        if nonspeech and (
            no_speech is None
            or (
                no_speech >= settings.asr_gate_no_speech
                and (logprob is None or logprob < settings.asr_gate_logprob)
            )
        ):
            record(seg, "no_speech", d, share)
            if not enabled:
                out_segments.append(seg)
            continue

        # G3; skipped when the backend gave no word probabilities (they read as 1.0).
        mean_prob = None if unscored_words else _mean_word_prob(seg)
        if (
            nonspeech
            and mean_prob is not None
            and mean_prob < settings.asr_gate_low_confidence
            and seg.end_ms - seg.start_ms < settings.asr_gate_low_confidence_max_ms
        ):
            record(seg, "low_confidence_nonspeech", d, share)
            if not enabled:
                out_segments.append(seg)
            continue

        # G2 — loops: identical segments in a row …
        norm = _norm(seg.text)
        same_run = same_run + 1 if norm and norm == previous_norm else 1
        previous_norm = norm
        if same_run > KEEP_REPETITIONS and _repeats_ahead(
            output.segments, seg, settings.asr_gate_loop_repeats
        ):
            record(seg, "loop", d, share)
            loop_ranges.append((seg.start_ms, seg.end_ms))
            if not enabled:
                out_segments.append(seg)
            continue
        # … a repeated n-gram inside one segment …
        tokens = [w.text for w in seg.words] if seg.words else seg.text.split()
        cut = loop_cut(tokens, settings.asr_gate_loop_repeats)
        if cut is not None and cut < len(tokens):
            if seg.words:
                tail_start = seg.words[cut].start_ms
                kept_words = seg.words[:cut]
                trimmed = seg.model_copy(
                    update={
                        "words": kept_words,
                        "text": " ".join(w.text for w in kept_words),
                        "end_ms": kept_words[-1].end_ms if kept_words else seg.start_ms,
                    }
                )
            else:
                tail_start = seg.start_ms
                trimmed = seg.model_copy(update={"text": " ".join(tokens[:cut])})
            tail = seg.model_copy(update={"start_ms": tail_start})
            record(tail, "loop", d, share)
            loop_ranges.append((seg.start_ms, seg.end_ms))
            out_segments.append(trimmed if enabled else seg)
            continue
        # … or only the decoder's own compression figure.
        if compression is not None and compression > settings.asr_gate_compression:
            loop_ranges.append((seg.start_ms, seg.end_ms))
        out_segments.append(seg)

    if dropped != list(output.diagnostics.dropped_segments):
        logger.info(
            "asr.guards",
            extra={
                "dropped": len(dropped) - len(output.diagnostics.dropped_segments),
                "artefacts_kept": len(kept_artefacts) - len(output.diagnostics.artefact_kept),
                "loops": len(loop_ranges),
                "dry_run": dry,
            },
        )
    diagnostics: Diagnostics = output.diagnostics.model_copy(
        update={
            "dropped_segments": dropped,
            "artefact_kept": kept_artefacts,
            "gate_unavailable": unavailable,
        }
    )
    final = output.model_copy(
        update={
            "segments": out_segments,
            "diagnostics": diagnostics,
        }
    )
    return GateResult(output=final, loop_ranges=loop_ranges if enabled else [])


def _repeats_ahead(segments: Sequence[Segment], seg: Segment, repeats: int) -> bool:
    """True when ``seg`` is in a run of at least ``repeats`` identical consecutive segments."""
    idx = next(k for k, s in enumerate(segments) if s is seg)
    norm = _norm(seg.text)
    lo = idx
    while lo > 0 and _norm(segments[lo - 1].text) == norm:
        lo -= 1
    hi = idx
    while hi + 1 < len(segments) and _norm(segments[hi + 1].text) == norm:
        hi += 1
    return hi - lo + 1 >= repeats
