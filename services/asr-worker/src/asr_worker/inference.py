"""faster-whisper engine wrapper: PCM in, segments + metadata out.

``faster_whisper`` is imported lazily (heavy; asr-service only needs the output types).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from asr_models import (
    AUTO_LANGUAGE,
    Diagnostics,
    Segment,
    SegmentDiagnostics,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from models import SpeechRun
from models import TranscriptionCancelledError as _SeamCancelled

from . import vad as _vad
from .config import settings
from .vad import SpeechSegment


def detect_speech(audio_pcm: np.ndarray) -> list[SpeechSegment]:
    """The engine's VAD: ordinary pass, leading pad, floor pass when its condition holds."""
    return _vad.speech_runs(
        audio_pcm,
        pad_ms=settings.asr_vad_pad_ms,
        floor=settings.asr_vad_floor_enabled,
        floor_threshold=settings.asr_vad_floor_threshold,
        floor_max_speech_share=settings.asr_vad_floor_max_speech_share,
    ).runs


class TranscriptionCancelledError(_SeamCancelled):
    """Cancelled mid-inference; the processor files it as ``cancelled``, not ``failed``."""


logger = logging.getLogger(__name__)

# Language identification lives in ``chunks.py``; re-exported for callers and tests.
from .chunks import LANGUAGE_ID_FALLBACK as _LANGUAGE_ID_FALLBACK  # noqa: E402
from .chunks import LANGUAGE_ID_WINDOWS as _LANGUAGE_ID_WINDOWS  # noqa: E402
from .chunks import OTHER_LANGUAGES, EngineLID, LanguageGuess, other_language  # noqa: E402
from .chunks import plan as _plan  # noqa: E402
from .chunks import speech_sample as _speech_sample  # noqa: E402


@dataclass(slots=True)
class WindowResult:
    """One streaming-window outcome; timestamps are window-relative."""

    segments: list[Segment]
    avg_logprob: float
    no_speech_prob: float
    infer_seconds: float


class WhisperEngine:
    """Lazily-loaded faster-whisper model; one per process, reused across jobs."""

    def __init__(self) -> None:
        self._model: Any | None = None
        self._loaded = False
        self._warm = False
        self._warmup_seconds: float = 0.0
        # Per-segment decoder numbers of the last ``_run_chunk``; chunks run one at a time.
        self._chunk_diagnostics: list[SegmentDiagnostics] = []

    def _take_chunk_diagnostics(
        self, language: str, *, second_pass: bool = False
    ) -> list[SegmentDiagnostics]:
        taken, self._chunk_diagnostics = self._chunk_diagnostics, []
        return [
            d.model_copy(update={"language": language, "second_pass": second_pass}) for d in taken
        ]

    @property
    def model_name(self) -> str:
        return settings.asr_model

    @property
    def warmup_seconds(self) -> float:
        return self._warmup_seconds

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Eagerly load the model (blocking: the loader holds the GIL)."""
        if self._loaded:
            return
        # Only faster_whisper is supported (ADR-0021); fail loud.
        if settings.asr_engine != "faster_whisper":
            raise RuntimeError(
                f"unsupported MD_ASR_ENGINE={settings.asr_engine!r}; "
                "only 'faster_whisper' is supported (see ADR-0021)"
            )
        from faster_whisper import WhisperModel  # local import

        device = settings.asr_device
        compute_type = settings.asr_compute_type
        logger.info(
            "whisper.loading",
            extra={
                "model": settings.asr_model,
                "device": device,
                "compute_type": compute_type,
                # Build-time provenance (ADR-0021).
                "engine": settings.asr_engine,
                "model_repo": settings.asr_model_repo,
                "model_revision": settings.asr_model_revision or "(unpinned)",
                "model_sha256": settings.asr_model_sha256 or "(unpinned)",
            },
        )
        t0 = time.monotonic()
        self._model = WhisperModel(
            settings.asr_model,
            device=device,
            compute_type=compute_type,
        )
        self._loaded = True
        # Warm-up on 5 s of silence: CUDA kernel JIT + audio frontend cache.
        silence = np.zeros(int(16_000 * 5), dtype=np.float32)
        try:
            _ = list(self._model.transcribe(silence, language="en", beam_size=1)[0])
        except Exception as exc:  # noqa: BLE001 — warm-up failure is non-fatal
            logger.warning(
                "whisper.warmup_failed",
                extra={"error": str(exc), "error_class": type(exc).__name__},
            )
        else:
            self._warm = True
        self._warmup_seconds = time.monotonic() - t0
        logger.info(
            "whisper.loaded",
            extra={"warmup_seconds": round(self._warmup_seconds, 2)},
        )

    async def transcribe(
        self,
        audio_pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        should_cancel: Callable[[], Awaitable[bool]] | None = None,
        second_pass: bool = False,
    ) -> TranscriptionOutput:
        """Run VAD + Whisper on the full audio (mono 16 kHz float32 in [-1, 1]).

        ``second_pass``: decode ``audio_pcm`` whole, no VAD/LID/prompt/conditioning.
        ``should_cancel`` is awaited between chunks and raises
        :class:`TranscriptionCancelledError`.
        """
        if not self._loaded:
            raise RuntimeError("WhisperEngine.load() must be called before transcribe()")
        t_start = time.monotonic()
        if second_pass:
            return await self._second_pass(audio_pcm, language=language, t_start=t_start)
        speech = detect_speech(audio_pcm)

        # No speech: empty transcript (`no_speech`), never a decode that could hallucinate.
        if not speech:
            return TranscriptionOutput(
                language=language if language != AUTO_LANGUAGE else _LANGUAGE_ID_FALLBACK,
                language_detected=False,
                language_probability=None,
                segments=[],
                metadata=TranscriptionMetadata(
                    model=settings.asr_model,
                    vad_seconds_speech=0.0,
                    infer_seconds=time.monotonic() - t_start,
                    gpu_seconds=0.0,
                    peak_gpu_mem_mb=_peak_gpu_mem_mb(),
                    beam_size=settings.asr_beam_size,
                ),
            )

        # Shared chunker with this engine's detector; "auto" decodes in the opening
        # minutes' language, a run in another only when the detector is sure.
        planned = await _plan(
            audio_pcm,
            speech,
            language=language,
            lid=EngineLID(self),
            should_cancel=should_cancel,
            cancelled=TranscriptionCancelledError,
        )
        output = await self.transcribe_runs(
            audio_pcm,
            planned.runs,
            language=planned.language,
            prompt=prompt,
            should_cancel=should_cancel,
        )
        return output.model_copy(
            update={
                "language_detected": planned.language_detected,
                "language_probability": planned.language_probability,
                "diagnostics": output.diagnostics.model_copy(
                    update={
                        "other_language_chunks": planned.other_language_runs,
                        "language_id": "engine",
                    }
                ),
                "metadata": output.metadata.model_copy(
                    update={
                        "vad_seconds_speech": sum((s.end_ms - s.start_ms) / 1000.0 for s in speech),
                        "infer_seconds": time.monotonic() - t_start,
                    }
                ),
            }
        )

    async def transcribe_runs(
        self,
        audio_pcm: np.ndarray,
        runs: Sequence[SpeechRun],
        *,
        language: str,
        prompt: str | None,
        should_cancel: Callable[[], Awaitable[bool]] | None = None,
        group_seconds: float = 300.0,
    ) -> TranscriptionOutput:
        """Decode planned runs, one call per run in its language, never translated (ADR-0061).

        ``should_cancel`` is awaited between runs, not inside one."""
        del group_seconds
        if not self._loaded:
            raise RuntimeError("WhisperEngine.load() must be called before transcribe_runs()")
        t_start = time.monotonic()
        loop = asyncio.get_running_loop()
        segments_out: list[Segment] = []
        seg_diagnostics: list[SegmentDiagnostics] = []
        for run in runs:
            chunk = audio_pcm[int(run.start_ms * 16) : int(run.end_ms * 16)]
            if chunk.size == 0:
                continue
            if should_cancel is not None and await should_cancel():
                raise TranscriptionCancelledError
            self._chunk_diagnostics = []
            segs = await loop.run_in_executor(
                None, self._run_chunk, chunk, run.language, prompt, run.start_ms
            )
            seg_diagnostics.extend(self._take_chunk_diagnostics(run.language))
            if run.language != language:
                segs = [seg.model_copy(update={"language": run.language}) for seg in segs]
            segments_out.extend(segs)
        infer_seconds = time.monotonic() - t_start
        return TranscriptionOutput(
            language=language,
            segments=segments_out,
            metadata=TranscriptionMetadata(
                model=settings.asr_model,
                vad_seconds_speech=sum(r.end_ms - r.start_ms for r in runs) / 1000.0,
                infer_seconds=infer_seconds,
                gpu_seconds=infer_seconds if settings.asr_device == "cuda" else 0.0,
                peak_gpu_mem_mb=_peak_gpu_mem_mb(),
                beam_size=settings.asr_beam_size,
            ),
            diagnostics=Diagnostics(segments=seg_diagnostics),
        )

    async def _second_pass(
        self, pcm: np.ndarray, *, language: str, t_start: float
    ) -> TranscriptionOutput:
        if language == AUTO_LANGUAGE:
            language = _LANGUAGE_ID_FALLBACK
        loop = asyncio.get_running_loop()
        segs: list[Segment] = []
        seg_diagnostics: list[SegmentDiagnostics] = []
        if pcm.size:
            self._chunk_diagnostics = []
            segs = await loop.run_in_executor(
                None, lambda: self._run_chunk(pcm, language, None, 0, second_pass=True)
            )
            seg_diagnostics = self._take_chunk_diagnostics(language, second_pass=True)
        infer_seconds = time.monotonic() - t_start
        beam = max(5, settings.asr_beam_size)
        return TranscriptionOutput(
            language=language,
            segments=segs,
            diagnostics=Diagnostics(segments=seg_diagnostics),
            metadata=TranscriptionMetadata(
                model=settings.asr_model,
                vad_seconds_speech=len(pcm) / 16_000,
                infer_seconds=infer_seconds,
                gpu_seconds=infer_seconds if settings.asr_device == "cuda" else 0.0,
                peak_gpu_mem_mb=_peak_gpu_mem_mb(),
                beam_size=beam,
            ),
        )

    def _detect_chunk_language(self, pcm: np.ndarray) -> LanguageGuess:
        """LID on one chunk (one 30 s window); undecidable = the recording's own language."""
        return self.detect_language(pcm, windows=1)

    def detect_language(
        self, pcm: np.ndarray, *, windows: int = _LANGUAGE_ID_WINDOWS
    ) -> LanguageGuess:
        """Identify the spoken language of ``pcm``. Blocking; never raises (falls back)."""
        assert self._model is not None
        if pcm.size == 0:
            return LanguageGuess(language=_LANGUAGE_ID_FALLBACK, probability=0.0)
        try:
            code, probability, all_probs = self._model.detect_language(
                pcm, language_detection_segments=windows
            )
        except Exception as exc:  # noqa: BLE001 — never let LID kill the job
            logger.warning(
                "whisper.language_id_failed",
                extra={"error": str(exc), "error_class": type(exc).__name__},
            )
            return LanguageGuess(language=_LANGUAGE_ID_FALLBACK, probability=0.0)
        code = str(code).strip().lower()
        if not (2 <= len(code) <= 3 and code.isalpha()):
            logger.warning("whisper.language_id_unusable", extra={"code": code})
            return LanguageGuess(language=_LANGUAGE_ID_FALLBACK, probability=0.0)
        guess = LanguageGuess(
            language=code,
            probability=max(0.0, min(1.0, float(probability))),
            probabilities=_probability_table(all_probs),
        )
        if windows != _LANGUAGE_ID_WINDOWS:
            return guess
        logger.info(
            "whisper.language_id",
            extra={"language": guess.language, "probability": round(guess.probability, 3)},
        )
        return guess

    async def transcribe_window(
        self,
        pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        prev_text: str | None = None,
    ) -> WindowResult:
        """Inference on one streaming window; timestamps window-relative, no VAD chunking."""
        if not self._loaded:
            raise RuntimeError("WhisperEngine.load() must be called before transcribe_window()")
        loop = asyncio.get_running_loop()
        t0 = time.monotonic()
        combined_prompt = _combine_prompts(prompt, prev_text)
        segs, avg_logprob, no_speech_prob = await loop.run_in_executor(
            None,
            self._run_window,
            pcm,
            language,
            combined_prompt,
        )
        return WindowResult(
            segments=segs,
            avg_logprob=avg_logprob,
            no_speech_prob=no_speech_prob,
            infer_seconds=time.monotonic() - t0,
        )

    def _run_window(
        self,
        pcm: np.ndarray,
        language: str,
        prompt: str | None,
    ) -> tuple[list[Segment], float, float]:
        assert self._model is not None
        vad_kwargs: dict[str, Any] = {}
        if settings.asr_streaming_vad_filter:
            # Silence-only windows never reach the decoder.
            vad_kwargs = {
                "vad_filter": True,
                "vad_parameters": {
                    "min_silence_duration_ms": settings.asr_streaming_vad_min_silence_ms,
                },
            }
        result_segs, _info = self._model.transcribe(
            pcm,
            language=language,
            initial_prompt=prompt,
            word_timestamps=True,
            beam_size=settings.asr_beam_size,
            condition_on_previous_text=False,  # caller owns context via prompt
            **vad_kwargs,
        )
        segments: list[Segment] = []
        logprobs: list[float] = []
        no_speech_probs: list[float] = []
        for seg in result_segs:
            words: list[WordTiming] = []
            if getattr(seg, "words", None):
                for w in seg.words:
                    words.append(
                        WordTiming(
                            text=w.word.strip(),
                            start_ms=int(w.start * 1000),
                            end_ms=int(w.end * 1000),
                            probability=float(getattr(w, "probability", 1.0)),
                        )
                    )
            avg_conf = float(sum(w.probability for w in words)) / len(words) if words else 0.5
            segments.append(
                Segment(
                    text=seg.text.strip(),
                    start_ms=int(seg.start * 1000),
                    end_ms=int(seg.end * 1000),
                    words=words,
                    avg_confidence=max(0.0, min(1.0, avg_conf)),
                )
            )
            logprobs.append(float(getattr(seg, "avg_logprob", -0.5)))
            no_speech_probs.append(float(getattr(seg, "no_speech_prob", 0.0)))
        avg_logprob = sum(logprobs) / len(logprobs) if logprobs else -1.0
        # Worst no_speech_prob, so a tail-of-silence segment isn't averaged away.
        worst_no_speech = max(no_speech_probs) if no_speech_probs else 1.0
        return segments, avg_logprob, worst_no_speech

    def _run_chunk(
        self,
        chunk: np.ndarray,
        language: str,
        prompt: str | None,
        offset_ms: int,
        *,
        second_pass: bool = False,
    ) -> list[Segment]:
        assert self._model is not None
        if second_pass:
            options: dict[str, Any] = {"initial_prompt": None, "condition_on_previous_text": False}
            beam = max(5, settings.asr_beam_size)
        else:
            options = chunk_decode_options(prompt)
            beam = settings.asr_beam_size
        result_segs, _info = self._model.transcribe(
            chunk,
            language=language,
            word_timestamps=True,
            beam_size=beam,
            # Never "translate": another language is decoded in that language.
            task="transcribe",
            **options,
        )
        out: list[Segment] = []
        for seg in result_segs:
            # Every decoded segment, before any guard looks at it.
            self._chunk_diagnostics.append(
                SegmentDiagnostics(
                    start_ms=int(seg.start * 1000) + offset_ms,
                    end_ms=max(int(seg.end * 1000), int(seg.start * 1000)) + offset_ms,
                    no_speech_prob=_float_or_none(getattr(seg, "no_speech_prob", None)),
                    avg_logprob=_float_or_none(getattr(seg, "avg_logprob", None)),
                    compression_ratio=_float_or_none(getattr(seg, "compression_ratio", None)),
                )
            )
            # Whisper writes the prompt back over non-speech; only-prompt words rated
            # probably-not-speech are that, not something anyone said.
            if _is_prompt_echo(seg.text, prompt, float(getattr(seg, "no_speech_prob", 0.0))):
                logger.info(
                    "whisper.prompt_echo_dropped",
                    extra={
                        "start_ms": int(seg.start * 1000) + offset_ms,
                        "no_speech_prob": round(float(seg.no_speech_prob), 3),
                    },
                )
                continue
            words: list[WordTiming] = []
            if getattr(seg, "words", None):
                for w in seg.words:
                    words.append(
                        WordTiming(
                            text=w.word.strip(),
                            start_ms=int(w.start * 1000) + offset_ms,
                            end_ms=int(w.end * 1000) + offset_ms,
                            probability=float(getattr(w, "probability", 1.0)),
                        )
                    )
            avg_conf = (
                float(sum(w.probability for w in words)) / len(words)
                if words
                else float(getattr(seg, "avg_logprob", -0.5) + 1.0) / 1.0
            )
            avg_conf = max(0.0, min(1.0, avg_conf))
            out.append(
                Segment(
                    text=seg.text.strip(),
                    start_ms=int(seg.start * 1000) + offset_ms,
                    end_ms=int(seg.end * 1000) + offset_ms,
                    words=words,
                    avg_confidence=avg_conf,
                )
            )
        return out


def _float_or_none(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN is not a number worth storing


def chunk_decode_options(prompt: str | None) -> dict[str, Any]:
    """Vocabulary (`initial_prompt` or `hotwords`) and conditioning options for one chunk decode."""
    options: dict[str, Any] = {"condition_on_previous_text": bool(settings.asr_condition_prev)}
    if settings.asr_vocabulary_mode == "hotwords":
        options["hotwords"] = prompt
        options["initial_prompt"] = None
    else:
        options["initial_prompt"] = prompt
    return options


def _probability_table(all_probs: object) -> dict[str, float]:
    """faster-whisper's ``[(code, prob), …]`` → ``{code: prob}``; anything else is empty."""
    out: dict[str, float] = {}
    try:
        for code, prob in all_probs or ():  # type: ignore[union-attr]
            out[str(code).strip().lower()] = max(0.0, min(1.0, float(prob)))
    except (TypeError, ValueError):
        return {}
    return out


def _peak_gpu_mem_mb() -> int:
    """Best-effort GPU peak memory in MB; 0 without torch + CUDA."""
    try:
        import torch

        if not torch.cuda.is_available():
            return 0
        peak_bytes = torch.cuda.max_memory_allocated()
        torch.cuda.reset_peak_memory_stats()
        return int(peak_bytes / (1024 * 1024))
    except Exception:
        return 0


# faster-whisper's own no_speech gate (0.6) does not fire when a prompt makes echoed
# text high-probability.
_PROMPT_ECHO_NO_SPEECH_PROB = 0.5


def _prompt_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W_]+", text.lower()) if w}


def _is_prompt_echo(text: str, prompt: str | None, no_speech_prob: float) -> bool:
    """True when ``text`` is only prompt words and the window rated probably-not-speech."""
    if not prompt or no_speech_prob < _PROMPT_ECHO_NO_SPEECH_PROB:
        return False
    words = _prompt_words(text)
    return bool(words) and words <= _prompt_words(prompt)


def _combine_prompts(base: str | None, prev_text: str | None) -> str | None:
    """Join the vocabulary prompt with the last-finalized text; strips ``<|...|>`` tokens."""
    parts: list[str] = []
    if base:
        parts.append(re.sub(r"<\|[^|]+\|>", "", base).strip())
    if prev_text:
        parts.append(re.sub(r"<\|[^|]+\|>", "", prev_text).strip())
    text = " ".join(p for p in parts if p)
    return text or None


__all__ = [
    "OTHER_LANGUAGES",
    "LanguageGuess",
    "SpeechSegment",
    "WhisperEngine",
    "WindowResult",
    "_speech_sample",
    "other_language",
]
