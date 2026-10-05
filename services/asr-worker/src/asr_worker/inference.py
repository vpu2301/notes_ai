"""Whisper inference engine wrapper.

``faster-whisper`` is the chosen backend (ADR-0009). The engine is
stateless across calls; ``transcribe`` is safe to call sequentially.
This file deliberately knows nothing about queues, DBs, or storage —
it transforms PCM in, segments + metadata out.

Optional imports: ``faster_whisper`` is a heavy dependency, not
installable on macOS arm64 hosts without coercing the wheel. The module
imports it lazily so the asr-service (which only imports the output
types) doesn't pay the cost.
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
    """The engine's VAD (Sprint F1): the ordinary pass, the leading pad and,
    when decision 4's condition holds, the floor pass on the mixdown."""
    return _vad.speech_runs(
        audio_pcm,
        pad_ms=settings.asr_vad_pad_ms,
        floor=settings.asr_vad_floor_enabled,
        floor_threshold=settings.asr_vad_floor_threshold,
        floor_max_speech_share=settings.asr_vad_floor_max_speech_share,
    ).runs


class TranscriptionCancelledError(_SeamCancelled):
    """The job was cancelled while inference was running.

    Not a failure: the user asked for it. The processor turns this
    into ``status='cancelled'`` rather than ``'failed'``, and no
    transcript is stored.
    """


logger = logging.getLogger(__name__)

# Sprint TQ2 T1: language identification and its rule moved to
# ``chunks.py`` (the worker plans runs for every backend). Re-exported here
# (``__all__``) for callers and tests that import them from the engine.
from .chunks import LANGUAGE_ID_FALLBACK as _LANGUAGE_ID_FALLBACK  # noqa: E402
from .chunks import LANGUAGE_ID_WINDOWS as _LANGUAGE_ID_WINDOWS  # noqa: E402
from .chunks import OTHER_LANGUAGES, EngineLID, LanguageGuess, other_language  # noqa: E402
from .chunks import plan as _plan  # noqa: E402
from .chunks import speech_sample as _speech_sample  # noqa: E402


@dataclass(slots=True)
class WindowResult:
    """One streaming-window inference outcome (sprint 04).

    Used by dictation-service's windower. Window-relative timestamps;
    the caller adds the window offset to land in session-absolute time.
    """

    segments: list[Segment]
    avg_logprob: float
    no_speech_prob: float
    infer_seconds: float


class WhisperEngine:
    """Lazily-loaded faster-whisper model.

    Instantiate once at process startup; reuse across jobs. The first
    ``transcribe`` after construction runs the warmup pass (5 s of
    silence) that JITs the CUDA kernels.
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._loaded = False
        self._warm = False
        self._warmup_seconds: float = 0.0
        # Sprint TQ1 T5: what the last ``_run_chunk`` decoded, the decoder's
        # own numbers per segment. Chunks run one at a time (each is awaited
        # before the next starts), so one slot is enough; a stand-in
        # ``_run_chunk`` in tests that never sets it records nothing.
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
        """Eagerly load the model.

        Synchronous because faster-whisper's loader holds the GIL and
        kicks off CUDA kernel compilation that doesn't yield. Call
        once from the worker's startup path.
        """
        if self._loaded:
            return
        # Engine selection (ADR-0021). Only faster_whisper is supported on the
        # streaming + confidence-span paths; a vLLM spike is gated behind an
        # ADR (Sprint B1 Day 3). Fail loud rather than silently load the wrong
        # backend.
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
                # Build-time provenance: which pinned repo@revision produced
                # the baked weights this process is loading (ADR-0021).
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
        # Synthetic warm-up on 5 s of silence: forces CUDA kernel JIT
        # and caches the audio frontend so the first real job's latency
        # isn't dominated by setup.
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
        """Run VAD + Whisper on the full audio.

        ``second_pass`` (Sprint F1, decision 3): ``audio_pcm`` is one speech
        run the first decode lost. It is decoded whole — no VAD, no language
        identification (``language`` is the recording's) — with no prompt,
        no conditioning and a beam of at least 5.

        ``audio_pcm`` is mono 16 kHz float32 in [-1, 1].
        Offloads the (blocking) Whisper call to a thread so the asyncio
        loop stays responsive — which is what makes ``should_cancel``
        possible: it is awaited between chunks, so a user who
        presses Cancel on a running job stops it rather than waiting for
        a transcript nobody will read. Raises :class:`TranscriptionCancelledError`
        when it returns true; without the callback the run is
        uninterruptible, which is what it used to be.
        """
        if not self._loaded:
            raise RuntimeError("WhisperEngine.load() must be called before transcribe()")
        t_start = time.monotonic()
        if second_pass:
            return await self._second_pass(audio_pcm, language=language, t_start=t_start)
        speech = detect_speech(audio_pcm)

        # Nothing to decode: say so with an empty transcript (the processor
        # files it as `no_speech`) instead of asking the language detector
        # and the decoder about audio VAD heard nothing in — that is the
        # path that turns a silent recording into a hallucinated one.
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

        # Sprint TQ2 T1: the plan (recording language, per-run language) is
        # the worker's shared chunker, asked with this engine's detector.
        # "auto" listens before deciding: the recording is decoded in the
        # language of its opening minutes, a run in another only when the
        # detector is sure of it (chunks.other_language).
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
        """Sprint TQ2 T1: decode the worker's planned runs, one faster-whisper
        call per run in the run's language (``group_seconds`` is the HTTP
        backends' concern). A run in another language comes back labelled —
        never translated into the recording's (ADR-0061 d6).

        Offloads each (blocking) call to a thread; ``should_cancel`` is
        awaited between runs, not inside one — a run is at most 30 s, and
        stopping mid-run would leave the model half-fed."""
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
        """Language identification on one chunk: one 30 s window, and an
        undecidable chunk answers with the recording's own language (an
        empty guess is never "another language")."""
        return self.detect_language(pcm, windows=1)

    def detect_language(
        self, pcm: np.ndarray, *, windows: int = _LANGUAGE_ID_WINDOWS
    ) -> LanguageGuess:
        """Identify the spoken language of ``pcm`` (mono 16 kHz float32).

        Blocking; call from an executor. Never raises: a detector that
        cannot decide — no audio, an exception, a code the output schema
        would reject — answers with the fallback so the job still produces
        a transcript rather than failing on the step meant to help it.
        """
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
        """Run inference on one streaming window (sprint 04 entry point).

        ``pcm`` is mono 16 kHz float32. Timestamps in the returned
        segments are window-relative (window-start = 0 ms); the caller
        adds the window's absolute offset.

        Unlike :meth:`transcribe`, this method is stateless: no VAD
        chunking, no aggregation. The dictation-service's windower owns
        the sliding-window state.
        """
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
            # Silence-only windows never reach the decoder, so they cannot
            # be hallucinated into text (see config for the measurements).
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
        # Use the worst no_speech_prob across segments so a tail-of-silence
        # high-prob segment isn't averaged away.
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
            # `task` is never "translate": a passage in another language is
            # decoded in that language (Sprint I2 T4), not rendered in this one.
            task="transcribe",
            **options,
        )
        out: list[Segment] = []
        for seg in result_segs:
            # Every decoded segment, before any guard looks at it (TQ1 T5).
            self._chunk_diagnostics.append(
                SegmentDiagnostics(
                    start_ms=int(seg.start * 1000) + offset_ms,
                    end_ms=max(int(seg.end * 1000), int(seg.start * 1000)) + offset_ms,
                    no_speech_prob=_float_or_none(getattr(seg, "no_speech_prob", None)),
                    avg_logprob=_float_or_none(getattr(seg, "avg_logprob", None)),
                    compression_ratio=_float_or_none(getattr(seg, "compression_ratio", None)),
                )
            )
            # Whisper's known failure with a prompt over non-speech (a
            # breath, a hum, room tone that passed VAD) is to write the
            # prompt back. A segment made only of the prompt's words that
            # the model itself rates as probably-not-speech is that, not
            # something anyone said; the same words with a low
            # no_speech_prob are speech and stay.
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
    """The vocabulary and context arguments of one batch-chunk decode
    (Sprint I2 T5/T7): the vocabulary as `initial_prompt` or as `hotwords`
    per `MDX_ASR_VOCABULARY_MODE`; `condition_on_previous_text` per
    `MDX_ASR_CONDITION_PREV` (ON by default since I2 T7 measured the
    punctuation cost of turning it off; it conditions within one ≤ 30 s run,
    never across runs — each run is its own faster-whisper call)."""
    options: dict[str, Any] = {"condition_on_previous_text": bool(settings.asr_condition_prev)}
    if settings.asr_vocabulary_mode == "hotwords":
        options["hotwords"] = prompt
        options["initial_prompt"] = None
    else:
        options["initial_prompt"] = prompt
    return options


def _probability_table(all_probs: object) -> dict[str, float]:
    """faster-whisper's ``[(code, prob), …]`` → ``{code: prob}``; anything
    else (an older API, a stub) is an empty table."""
    out: dict[str, float] = {}
    try:
        for code, prob in all_probs or ():  # type: ignore[union-attr]
            out[str(code).strip().lower()] = max(0.0, min(1.0, float(prob)))
    except (TypeError, ValueError):
        return {}
    return out


def _peak_gpu_mem_mb() -> int:
    """Best-effort GPU peak memory in MB.

    Uses ``torch.cuda.max_memory_allocated`` if torch + CUDA are present;
    returns 0 otherwise (CPU fallback, or no torch in the image).
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return 0
        peak_bytes = torch.cuda.max_memory_allocated()
        torch.cuda.reset_peak_memory_stats()
        return int(peak_bytes / (1024 * 1024))
    except Exception:
        return 0


# Above this the decoder itself says the window was probably not speech;
# faster-whisper's own gate (no_speech_threshold=0.6) does not fire when a
# prompt makes the echoed text high-probability, which is exactly this case.
_PROMPT_ECHO_NO_SPEECH_PROB = 0.5


def _prompt_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[^\W_]+", text.lower()) if w}


def _is_prompt_echo(text: str, prompt: str | None, no_speech_prob: float) -> bool:
    """True when ``text`` is nothing but words from ``prompt`` and the
    decoder rated the window as probably-not-speech."""
    if not prompt or no_speech_prob < _PROMPT_ECHO_NO_SPEECH_PROB:
        return False
    words = _prompt_words(text)
    return bool(words) and words <= _prompt_words(prompt)


def _combine_prompts(base: str | None, prev_text: str | None) -> str | None:
    """Join the vocabulary-hint prompt with the last-finalized text.

    Strips any Whisper special tokens (``<|...|>``) defensively. The
    caller is responsible for truncating prev_text to a token budget;
    here we just concatenate.
    """
    parts: list[str] = []
    if base:
        parts.append(re.sub(r"<\|[^|]+\|>", "", base).strip())
    if prev_text:
        parts.append(re.sub(r"<\|[^|]+\|>", "", prev_text).strip())
    text = " ".join(p for p in parts if p)
    return text or None


# Re-export so callers don't have to import vad themselves.
__all__ = [
    "OTHER_LANGUAGES",
    "LanguageGuess",
    "SpeechSegment",
    "WhisperEngine",
    "WindowResult",
    "_speech_sample",
    "other_language",
]
