"""Sprint TQ2 T1 — the worker plans the decode, for every backend.

Before TQ2 only the in-process engine ran VAD and per-run language
identification; the HTTP backends (``dev_mac_asr``, ``hf_eu_asr``) were
posted the whole file, silence and jingles included, in one language. Now
the worker runs VAD once, cuts speech runs (≤ 30 s, merged < 500 ms — the
engine's logic, moved here), identifies the recording's language and each
run's, and hands the backend a list of ``SpeechRun``s with an explicit
language each. The backend only decodes.

Language identification (Sprint I2 decision 4, ADR-0061 d4, moved here from
``inference.py``): a run of at least 2 s is decoded in another language
only when the identifier is sure of it (p ≥ 0.6), it is one we transcribe
(en/de/uk), and the recording's language is nearly excluded (≤ 0.2).

Who identifies:

- ``EngineLID`` — the in-process engine's own model (large-v3): unchanged
  behaviour for ``inproc_cpu_asr``.
- ``BackendLID`` — HTTP backends: the recording's language from the backend
  itself (one request on a 30 s speech sample, the production model
  decides, as it did when it was sent the whole file), each run's from a
  small local model (``MDX_ASR_LID_MODEL``, faster-whisper tiny baked in
  the CPU image; 0.2 s per run on CPU, measured 2026-09-30). Tiny is weak
  on Ukrainian (0.63 on clean uk speech), which the rule tolerates: a run
  switches only when the recording's language is ≤ 0.2, so a weak uk score
  keeps it in uk. When no local model loads, runs stay in the recording's
  language and ``diagnostics.language_id`` says ``unavailable``.

Also here: the non-speech regions the transcript marks (TQ2 T4).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

import numpy as np
from opentelemetry import metrics

from asr_models import AUTO_LANGUAGE, NoiseRegion
from models import SpeechRun

from . import vad as _vad
from .config import settings
from .vad import SpeechSegment

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
LANGUAGE_ID_SECONDS = 90
LANGUAGE_ID_WINDOWS = 3
LANGUAGE_ID_FALLBACK = "en"
BACKEND_LID_SECONDS = 30
# Sprint I2 T4: a VAD chunk at least this long gets its own language check;
# it is decoded in another language only when the detector is sure of the
# other one AND nearly excludes the recording's — a stray English word in a
# Ukrainian meeting must not flip the decoder chunk by chunk.
CHUNK_LID_MIN_MS = 2_000
# "Sure which": 0.6, not 0.8 — Ukrainian shares probability with Russian
# (measured 0.75 / 0.18 on clean Ukrainian speech, T7), and the second bar
# is what keeps a stray word from flipping. "Not the recording's": ≤ 0.2.
OTHER_LANGUAGE_MIN_PROB = 0.6
RECORDING_LANGUAGE_MAX_PROB = 0.2
# Only a language the product transcribes is decoded as "another language".
# Whisper's detector calls accented English "Welsh" now and then (T7,
# VoxConverse); decoding that as Welsh would replace speech with noise.
OTHER_LANGUAGES = frozenset({"en", "de", "uk"})

_meter = metrics.get_meter("mdx.asr.worker.lid")
_other_language_chunks = _meter.create_counter(
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
    if guess.probability < OTHER_LANGUAGE_MIN_PROB:
        return None
    if guess.probabilities.get(recording, 0.0) > RECORDING_LANGUAGE_MAX_PROB:
        return None
    return guess.language


def speech_sample(
    audio_pcm: np.ndarray, speech: Sequence[SpeechSegment], *, seconds: int
) -> np.ndarray:
    """The first ``seconds`` of *speech* (VAD runs concatenated, silence
    dropped) — what language identification listens to. Silence between
    turns would otherwise eat the detector's fixed 30 s windows."""
    budget = seconds * SAMPLE_RATE
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
        return audio_pcm[: seconds * SAMPLE_RATE]
    return np.concatenate(parts)


# ── Who identifies ───────────────────────────────────────────────────


class LanguageIdentifier(Protocol):
    source: Literal["engine", "local", "unavailable"]

    async def recording_language(self, sample: np.ndarray) -> LanguageGuess: ...

    async def run_language(self, pcm: np.ndarray) -> LanguageGuess | None: ...


class EngineLID:
    """The in-process engine's own detector (looked up at call time, so a
    test's stand-in on the engine is what answers)."""

    source: Literal["engine", "local", "unavailable"] = "engine"

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    async def recording_language(self, sample: np.ndarray) -> LanguageGuess:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._engine.detect_language, sample)

    async def run_language(self, pcm: np.ndarray) -> LanguageGuess | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._engine._detect_chunk_language, pcm)


_local_model: Any = None
_local_model_failed = False


def _load_local_model() -> Any:
    """The small faster-whisper model that identifies run languages for
    HTTP backends. Loaded once; a failure is remembered (the worker then
    decodes every run in the recording's language)."""
    global _local_model, _local_model_failed
    if _local_model is not None or _local_model_failed:
        return _local_model
    try:
        from faster_whisper import WhisperModel

        _local_model = WhisperModel(settings.asr_lid_model, device="cpu", compute_type="int8")
    except Exception as exc:  # noqa: BLE001 — no model means no run LID, not no transcript
        logger.warning(
            "asr.local_lid_unavailable",
            extra={"model": settings.asr_lid_model, "error_class": type(exc).__name__},
        )
        _local_model_failed = True
    return _local_model


def _probabilities(all_probs: object) -> dict[str, float]:
    out: dict[str, float] = {}
    try:
        for code, prob in cast(Iterable[Any], all_probs or ()):
            out[str(code).strip().lower()] = max(0.0, min(1.0, float(prob)))
    except (TypeError, ValueError):
        return {}
    return out


class BackendLID:
    """HTTP backends: the recording's language from the backend (the model
    that transcribes decides it), each run's from the local model."""

    def __init__(self, provider: Any) -> None:
        self._provider = provider
        self._local: Any = None
        self.source: Literal["engine", "local", "unavailable"] = "local"

    async def prepare(self) -> None:
        self._local = await asyncio.to_thread(_load_local_model)
        if self._local is None:
            self.source = "unavailable"

    async def recording_language(self, sample: np.ndarray) -> LanguageGuess:
        # The server decides from its first 30 s window; sending more only
        # costs decode time.
        out = await self._provider.transcribe(
            sample[: BACKEND_LID_SECONDS * SAMPLE_RATE], language=AUTO_LANGUAGE, prompt=None
        )
        if out.language_detected:
            prob = out.language_probability if out.language_probability is not None else 1.0
            return LanguageGuess(language=out.language, probability=prob)
        # Sprint TQ4: a backend with no language identification (Parakeet)
        # names none; the local model decides, among the languages we
        # transcribe when it is unsure (tiny reads clean Ukrainian at 0.63,
        # with Russian close behind).
        guess = await self.run_language(sample[: BACKEND_LID_SECONDS * SAMPLE_RATE])
        if guess is None:
            return LanguageGuess(language=LANGUAGE_ID_FALLBACK, probability=0.0)
        if guess.language not in OTHER_LANGUAGES and guess.probabilities:
            best = max(OTHER_LANGUAGES, key=lambda code: guess.probabilities.get(code, 0.0))
            return LanguageGuess(best, guess.probabilities.get(best, 0.0), guess.probabilities)
        return guess

    async def run_language(self, pcm: np.ndarray) -> LanguageGuess | None:
        if self._local is None:
            return None

        def detect() -> LanguageGuess | None:
            try:
                code, prob, all_probs = self._local.detect_language(
                    pcm, language_detection_segments=1
                )
            except Exception:  # noqa: BLE001 — an undecided run stays in the recording's language
                return None
            return LanguageGuess(
                language=str(code).strip().lower(),
                probability=max(0.0, min(1.0, float(prob))),
                probabilities=_probabilities(all_probs),
            )

        return await asyncio.to_thread(detect)


async def identifier_for(provider: Any) -> LanguageIdentifier:
    engine = getattr(provider, "engine", None)
    if engine is not None and hasattr(engine, "detect_language"):
        return EngineLID(engine)
    lid = BackendLID(provider)
    await lid.prepare()
    return lid


# ── The plan ─────────────────────────────────────────────────────────


@dataclass
class Plan:
    """What the worker hands the backend, and what it heard doing so."""

    language: str
    language_detected: bool
    language_probability: float | None
    runs: list[SpeechRun]
    other_language_runs: int
    language_id: Literal["engine", "local", "unavailable", "pinned"]
    speech_ms: int


async def plan(
    pcm: np.ndarray,
    speech: Sequence[SpeechSegment],
    *,
    language: str,
    lid: LanguageIdentifier,
    should_cancel: Callable[[], Awaitable[bool]] | None = None,
    cancelled: type[Exception] | None = None,
) -> Plan:
    """Speech runs (already capped at 30 s) → runs with a language each.

    ``language`` is the job's: ``auto`` asks the identifier about the first
    90 s of speech; a pinned language skips that step but every run is
    still checked for another language (a pinned German meeting can quote
    English)."""
    detected = False
    probability: float | None = None
    if language == AUTO_LANGUAGE:
        if speech:
            guess = await lid.recording_language(
                speech_sample(pcm, speech, seconds=LANGUAGE_ID_SECONDS)
            )
            language, probability, detected = guess.language, guess.probability, True
        else:
            language = LANGUAGE_ID_FALLBACK
    runs: list[SpeechRun] = []
    others = 0
    for s in speech:
        run_language = language
        chunk = pcm[int(s.start_ms * 16) : int(s.end_ms * 16)]
        if chunk.size == 0:
            continue
        if (
            settings.asr_chunk_language_id
            and lid.source != "unavailable"
            and chunk.size >= CHUNK_LID_MIN_MS * 16
        ):
            # Identification is the slow step (seconds per run on CPU with
            # the engine's own model): look at the cancel flag before it.
            if should_cancel is not None and await should_cancel():
                from models import TranscriptionCancelledError

                raise (cancelled or TranscriptionCancelledError)(
                    "cancel requested while planning runs"
                )
            run_guess = await lid.run_language(chunk)
            other = other_language(run_guess, recording=language) if run_guess is not None else None
            if other is not None:
                run_language = other
                others += 1
                _other_language_chunks.add(1)
                logger.info(
                    "whisper.other_language_chunk",
                    extra={
                        "start_ms": s.start_ms,
                        "language": other,
                        "probability": round(run_guess.probability, 3) if run_guess else None,
                    },
                )
        runs.append(
            SpeechRun(
                start_ms=s.start_ms,
                end_ms=s.end_ms,
                language=run_language,
                other_language=run_language != language,
            )
        )
    source: Literal["engine", "local", "unavailable", "pinned"] = lid.source
    return Plan(
        language=language,
        language_detected=detected,
        language_probability=probability,
        runs=runs,
        other_language_runs=others,
        language_id=source,
        speech_ms=sum(r.end_ms - r.start_ms for r in runs),
    )


# ── Non-speech markers (TQ2 T4) ──────────────────────────────────────

NONSPEECH_MIN_MS = 5_000
SILENCE_MAX_DBFS = _vad.FLOOR_MIN_NON_SPEECH_DBFS  # −45 dBFS, the floor pass's measure
# Median spectral flatness below this reads as tonal (music); above, as
# broadband (noise). Speech-free by construction — VAD heard none here.
MUSIC_MAX_FLATNESS = 0.3
_FRAME = 1024  # 64 ms at 16 kHz


def _dbfs(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0
    return float(20.0 * np.log10(max(rms, 1e-10)))


def _median_flatness(x: np.ndarray) -> float:
    n = x.shape[0] // _FRAME
    if n == 0:
        return 1.0
    frames = x[: n * _FRAME].reshape(n, _FRAME).astype(np.float64) * np.hanning(_FRAME)
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2 + 1e-12
    flat = np.exp(np.mean(np.log(power), axis=1)) / np.mean(power, axis=1)
    # Frames of digital silence say nothing about the character of the sound.
    loud = np.sqrt(np.mean(frames**2, axis=1)) > 10 ** (SILENCE_MAX_DBFS / 20)
    return float(np.median(flat[loud])) if loud.any() else 1.0


def classify_region(x: np.ndarray) -> Literal["music", "silence", "noise"]:
    """Silence by level (≤ −45 dBFS, the floor pass's measure); above that,
    music when the spectrum is tonal (median flatness < 0.3), else noise.
    Deliberately simple and recorded as such (TQ2 T4)."""
    if _dbfs(x) <= SILENCE_MAX_DBFS:
        return "silence"
    return "music" if _median_flatness(x) < MUSIC_MAX_FLATNESS else "noise"


_LEVEL_FRAME_MS = 1000


def _split_by_level(x: np.ndarray, start_ms: int) -> list[tuple[int, int, bool]]:
    """``(start, end, silent)`` pieces of one non-speech stretch, per 1 s
    level: music followed by a silent tail is two regions, not one."""
    step = _LEVEL_FRAME_MS * 16
    labels = [
        _dbfs(x[i : i + step]) <= SILENCE_MAX_DBFS for i in range(0, max(1, x.shape[0]), step)
    ]
    pieces: list[list[int | bool]] = []
    for k, silent in enumerate(labels):
        t0 = start_ms + k * _LEVEL_FRAME_MS
        t1 = min(start_ms + (k + 1) * _LEVEL_FRAME_MS, start_ms + x.shape[0] // 16)
        if pieces and pieces[-1][2] == silent:
            pieces[-1][1] = t1
        else:
            pieces.append([t0, t1, silent])
    # A piece too short to mark joins the one before it (or after, first).
    merged: list[list[int | bool]] = []
    for p in pieces:
        if merged and int(p[1]) - int(p[0]) < NONSPEECH_MIN_MS:
            merged[-1][1] = p[1]
        else:
            merged.append(p)
    if len(merged) > 1 and int(merged[0][1]) - int(merged[0][0]) < NONSPEECH_MIN_MS:
        merged[1][0] = merged[0][0]
        merged.pop(0)
    return [(int(a), int(b), bool(c)) for a, b, c in merged]


def nonspeech_regions(pcm: np.ndarray, speech: Sequence[SpeechSegment]) -> list[NoiseRegion]:
    """Stretches of at least 5 s with no VAD speech — before the first run,
    between runs, after the last — split where the level changes between
    silence and sound, each with a kind."""
    total_ms = int(pcm.shape[0] / SAMPLE_RATE * 1000)
    edges = [0]
    for s in sorted(speech, key=lambda r: r.start_ms):
        edges += [s.start_ms, s.end_ms]
    edges.append(total_ms)
    out: list[NoiseRegion] = []
    for start, end in zip(edges[::2], edges[1::2], strict=False):
        if end - start < NONSPEECH_MIN_MS:
            continue
        for a, b, _silent in _split_by_level(pcm[start * 16 : end * 16], start):
            if b - a < NONSPEECH_MIN_MS:
                continue
            out.append(
                NoiseRegion(start_ms=a, end_ms=b, kind=classify_region(pcm[a * 16 : b * 16]))
            )
    return out
