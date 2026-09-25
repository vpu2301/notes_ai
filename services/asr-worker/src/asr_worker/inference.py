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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from opentelemetry import metrics

from asr_models import (
    AUTO_LANGUAGE,
    Diagnostics,
    Segment,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from models import TranscriptionCancelledError as _SeamCancelled

from .config import settings
from .vad import SpeechSegment, detect_speech


class TranscriptionCancelledError(_SeamCancelled):
    """The job was cancelled while inference was running.

    Not a failure: the user asked for it. The processor turns this
    into ``status='cancelled'`` rather than ``'failed'``, and no
    transcript is stored.
    """


logger = logging.getLogger(__name__)

# Language identification listens to the first speech in the recording.
# Whisper decides per 30 s window; three windows of speech is enough to
# outvote a greeting in another language without listening to the whole
# meeting first.
_LANGUAGE_ID_SECONDS = 90
_LANGUAGE_ID_WINDOWS = 3
# What the detector falls back to when it cannot decide at all (audio it
# could not read, or a detector error). English is the model's strongest
# language, so an undecidable recording is more likely to be usable there
# than under a guess.
_LANGUAGE_ID_FALLBACK = "en"
# Sprint I2 T4: a VAD chunk at least this long gets its own language check;
# it is decoded in another language only when the detector is sure of the
# other one AND nearly excludes the recording's — a stray English word in a
# Ukrainian meeting must not flip the decoder chunk by chunk.
_CHUNK_LID_MIN_MS = 2_000
# "Sure which": 0.6, not 0.8 — Ukrainian shares probability with Russian
# (measured 0.75 / 0.18 on clean Ukrainian speech, T7), and the second bar
# is what keeps a stray word from flipping. "Not the recording's": ≤ 0.2.
_OTHER_LANGUAGE_MIN_PROB = 0.6
_RECORDING_LANGUAGE_MAX_PROB = 0.2
# Only a language the product transcribes is decoded as "another language".
# Whisper's detector calls accented English "Welsh" now and then (T7,
# VoxConverse); decoding that as Welsh would replace speech with noise.
OTHER_LANGUAGES = frozenset({"en", "de", "uk"})

_lid_meter = metrics.get_meter("mdx.asr.worker.lid")
_other_language_chunks = _lid_meter.create_counter(
    "mdx_asr_other_language_chunks_total",
    description="VAD chunks decoded in another language than the recording (Sprint I2)",
    unit="1",
)


@dataclass(slots=True)
class LanguageGuess:
    """What language identification heard, and how sure it was."""

    language: str
    probability: float
    # Every language's probability from the same pass (empty on fallback).
    probabilities: dict[str, float] = field(default_factory=dict)


def other_language(guess: LanguageGuess, *, recording: str) -> str | None:
    """The language a chunk should be decoded in when it clearly is not the
    recording's — else None (decision 4 of Sprint I2)."""
    if guess.language == recording or guess.language not in OTHER_LANGUAGES:
        return None
    if guess.probability < _OTHER_LANGUAGE_MIN_PROB:
        return None
    if guess.probabilities.get(recording, 0.0) > _RECORDING_LANGUAGE_MAX_PROB:
        return None
    return guess.language


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
    ) -> TranscriptionOutput:
        """Run VAD + Whisper on the full audio.

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
        speech = detect_speech(audio_pcm)
        vad_seconds_speech = sum((s.end_ms - s.start_ms) / 1000.0 for s in speech)

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

        loop = asyncio.get_running_loop()

        # "auto": listen before deciding. The whole recording is decoded in
        # ONE language — the one the opening minutes are in — so a stray
        # English word in a Ukrainian meeting never flips the decoder
        # chunk by chunk.
        language_detected = False
        language_probability: float | None = None
        if language == AUTO_LANGUAGE:
            sample = _speech_sample(audio_pcm, speech, seconds=_LANGUAGE_ID_SECONDS)
            guess = await loop.run_in_executor(None, self.detect_language, sample)
            language, language_probability = guess.language, guess.probability
            language_detected = True

        segments_out: list[Segment] = []
        other_language_chunks = 0
        for s in speech:
            chunk = audio_pcm[
                int(s.start_ms * 16) : int(s.end_ms * 16)
            ]  # ms → samples (16 samples/ms @ 16kHz)
            if chunk.size == 0:
                continue
            # Between chunks, not inside one: a chunk is a VAD speech run,
            # short enough that the wait is bounded, and stopping mid-chunk
            # would leave the model half-fed.
            if should_cancel is not None and await should_cancel():
                raise TranscriptionCancelledError
            # Sprint I2 T4: a passage in another language is decoded in that
            # language and labelled — never translated into the recording's.
            chunk_language = language
            if settings.asr_chunk_language_id and chunk.size >= _CHUNK_LID_MIN_MS * 16:
                guess = await loop.run_in_executor(None, self._detect_chunk_language, chunk)
                other = other_language(guess, recording=language)
                if other is not None:
                    chunk_language = other
                    other_language_chunks += 1
                    _other_language_chunks.add(1)
                    logger.info(
                        "whisper.other_language_chunk",
                        extra={
                            "start_ms": s.start_ms,
                            "language": other,
                            "probability": round(guess.probability, 3),
                        },
                    )
            segs = await loop.run_in_executor(
                None,
                self._run_chunk,
                chunk,
                chunk_language,
                prompt,
                s.start_ms,
            )
            if chunk_language != language:
                segs = [seg.model_copy(update={"language": chunk_language}) for seg in segs]
            segments_out.extend(segs)

        infer_seconds = time.monotonic() - t_start
        meta = TranscriptionMetadata(
            model=settings.asr_model,
            vad_seconds_speech=vad_seconds_speech,
            infer_seconds=infer_seconds,
            gpu_seconds=infer_seconds if settings.asr_device == "cuda" else 0.0,
            peak_gpu_mem_mb=_peak_gpu_mem_mb(),
            beam_size=settings.asr_beam_size,
        )
        return TranscriptionOutput(
            language=language,
            language_detected=language_detected,
            language_probability=language_probability,
            segments=segments_out,
            metadata=meta,
            diagnostics=Diagnostics(other_language_chunks=other_language_chunks),
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
    ) -> list[Segment]:
        assert self._model is not None
        result_segs, _info = self._model.transcribe(
            chunk,
            language=language,
            word_timestamps=True,
            beam_size=settings.asr_beam_size,
            # `task` is never "translate": a passage in another language is
            # decoded in that language (Sprint I2 T4), not rendered in this one.
            task="transcribe",
            **chunk_decode_options(prompt),
        )
        out: list[Segment] = []
        for seg in result_segs:
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


def chunk_decode_options(prompt: str | None) -> dict[str, Any]:
    """The vocabulary and context arguments of one batch-chunk decode
    (Sprint I2 T5/T7): the vocabulary as `initial_prompt` or as `hotwords`
    per `MDX_ASR_VOCABULARY_MODE`; `condition_on_previous_text` per
    `MDX_ASR_CONDITION_PREV` (off by default — once the decoder echoes its
    prompt, the echo would become the next chunk's context)."""
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


def _speech_sample(
    audio_pcm: np.ndarray, speech: list[SpeechSegment], *, seconds: int
) -> np.ndarray:
    """The first ``seconds`` of *speech* (VAD runs concatenated, silence
    dropped) — what language identification listens to. Silence between
    turns would otherwise eat the detector's fixed 30 s windows."""
    budget = seconds * 16_000
    parts: list[np.ndarray] = []
    for s in speech:
        chunk = audio_pcm[int(s.start_ms * 16) : int(s.end_ms * 16)]
        if chunk.size == 0:
            continue
        parts.append(chunk[:budget])
        budget -= min(budget, chunk.size)
        if budget <= 0:
            break
    if not parts:
        # VAD found nothing; let the detector hear the raw head instead.
        return audio_pcm[: seconds * 16_000]
    return np.concatenate(parts)


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
__all__ = ["WhisperEngine", "WindowResult", "SpeechSegment"]
