"""Numbers-only quality summary per job (``transcription_jobs.quality``).

No word, name or segment text ever reaches it; the unit test asserts this.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from asr_models import TranscriptionOutput

QUALITY_VERSION = 1
LOW_CONFIDENCE = 0.5


def _r(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(float(value), digits)


def summarize(output: TranscriptionOutput, *, audio_seconds: float) -> dict[str, Any]:
    """Content-free quality numbers for one transcript."""
    d = output.diagnostics
    md = output.metadata
    words = [w for s in output.segments for w in s.words]
    seg_ms = [max(0, s.end_ms - s.start_ms) for s in output.segments]
    total_ms = sum(seg_ms)
    weighted_conf = (
        sum(s.avg_confidence * ms for s, ms in zip(output.segments, seg_ms, strict=True)) / total_ms
        if total_ms
        else None
    )
    by_language: Counter[str] = Counter()
    for s, ms in zip(output.segments, seg_ms, strict=True):
        by_language[s.language or output.language] += ms
    coverage = d.coverage
    gaps: Counter[str] = Counter(g.cause for g in coverage.gaps) if coverage else Counter()
    noise_s: Counter[str] = Counter()
    for n in output.noise:
        noise_s[n.kind] += max(0, n.end_ms - n.start_ms) / 1000
    dropped = [x for x in d.dropped_segments if not x.dry_run]
    shadow = d.shadow
    return {
        "v": QUALITY_VERSION,
        "model": md.model,
        "audio_s": _r(audio_seconds, 1),
        "speech_s": _r(md.vad_seconds_speech, 1),
        "infer_s": _r(md.infer_seconds, 1),
        "rtf": _r(md.infer_seconds / audio_seconds if audio_seconds else None),
        "language": output.language,
        "language_detected": output.language_detected,
        "language_probability": _r(output.language_probability),
        "language_id": d.language_id,
        "language_share": (
            {k: _r(v / total_ms) for k, v in sorted(by_language.items())} if total_ms else {}
        ),
        "other_language_chunks": d.other_language_chunks,
        "segments": len(output.segments),
        "words": len(words),
        "avg_confidence": _r(weighted_conf),
        "low_confidence_word_share": (
            _r(sum(1 for w in words if w.probability < LOW_CONFIDENCE) / len(words))
            if words
            else None
        ),
        "coverage_share": _r(md.coverage_share),
        "gaps": dict(sorted(gaps.items())),
        "second_pass_chunks": d.second_pass.chunks,
        "second_pass_recovered_words": d.second_pass.recovered_words,
        "dropped": dict(sorted(Counter(x.reason for x in dropped).items())),
        "dropped_dry_run": sum(1 for x in d.dropped_segments if x.dry_run),
        "artefacts_kept": len(d.artefact_kept),
        "loops": dict(sorted(Counter(x.outcome for x in d.loops).items())),
        "backend_errors": len(d.backend_errors),
        "prompt_echo_spans": len(d.prompt_echo),
        "prompt_echo_segments_dropped": d.prompt_echo_segments_dropped,
        "noise_s": {k: _r(v, 1) for k, v in sorted(noise_s.items())},
        **speaker_numbers(output),
        "shadow": (
            {
                "backend": shadow.backend,
                "skipped": shadow.skipped,
                "word_disagreement": _r(shadow.word_disagreement),
                "name_forms_primary": shadow.name_forms_primary,
                "name_forms_shadow": shadow.name_forms_shadow,
                "rtf": _r(shadow.rtf),
            }
            if shadow
            else None
        ),
    }


def speaker_numbers(output: TranscriptionOutput) -> dict[str, Any]:
    """The part of the summary a speaker re-run changes."""
    diar = output.metadata.diarization
    return {
        "speakers": len(output.speakers),
        "diarization_unknown_share": _r(diar.unknown_share) if diar else None,
        "diarization_overlap_share": _r(diar.overlap_share) if diar else None,
    }
