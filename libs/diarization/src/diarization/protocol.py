"""The diarizer seam (Sprint 29).

The batch worker calls one function and keeps its word-level attribution
unchanged because every engine is reduced to the structure that code
already consumes: chunk-level :class:`SpeakerSegment` evidence wrapped in
an :class:`OfflineDiarization`. One protocol, two implementations in this
library (legacy ECAPA + agglomeration, pyannote community-1) — not a
generic model backend.

Hints are how a person's knowledge reaches the engine. ``num_speakers`` is
a count someone stated ("there were 2 of us") and wins over everything the
engine would decide on its own; ``max_speakers`` is a cap (Sprint 30 fills
it from the calendar). An engine may return FEWER speakers than asked —
one voice in the recording stays one voice — but never invents one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

    from .offline import OfflineDiarization

# What a person may state. Eight matches the roster cap of both engines
# and the 1..8 range the API validates.
MIN_HINT = 1
MAX_HINT = 8


class InvalidHintsError(ValueError):
    """Hints that cannot describe a recording (0 people, min above max)."""


@dataclass(frozen=True)
class DiarizationHints:
    num_speakers: int | None = None  # exact, from a person
    min_speakers: int | None = None
    max_speakers: int | None = None  # cap, e.g. from the calendar (Sprint 30)

    def validated(self) -> DiarizationHints:
        """Range-check and normalise: every value 1..8, ``min <= max``.

        ``num_speakers`` is the strongest statement there is, so it
        overrides min/max rather than being checked against them — a
        calendar cap of 3 does not veto a person saying "there were 4".
        """
        for name in ("num_speakers", "min_speakers", "max_speakers"):
            value = getattr(self, name)
            if value is not None and not MIN_HINT <= value <= MAX_HINT:
                raise InvalidHintsError(f"{name}={value} is outside {MIN_HINT}..{MAX_HINT}")
        if self.num_speakers is not None:
            return DiarizationHints(num_speakers=self.num_speakers)
        if (
            self.min_speakers is not None
            and self.max_speakers is not None
            and self.min_speakers > self.max_speakers
        ):
            raise InvalidHintsError(
                f"min_speakers={self.min_speakers} exceeds max_speakers={self.max_speakers}"
            )
        return self

    @property
    def exact(self) -> bool:
        return self.num_speakers is not None

    @property
    def kind(self) -> str:
        """Audit vocabulary: ``exact`` | ``max`` | ``none`` — never the numbers."""
        if self.num_speakers is not None:
            return "exact"
        if self.max_speakers is not None or self.min_speakers is not None:
            return "max"
        return "none"


NO_HINTS = DiarizationHints()


@runtime_checkable
class Diarizer(Protocol):
    """What the worker holds. Built once per process, loaded lazily."""

    # "legacy-ecapa-ahc" | "pyannote-community-1" | "http:<backend>"
    engine: str
    # Model revision / package version; lands in ``DiarizationStats``.
    engine_version: str
    # True when the engine runs on another host (shape B, ADR-0052). The
    # worker reads it to decide what a failure means: an in-process
    # engine that cannot load is a broken deployment and fails the job,
    # while a remote one that is down must not cost the user a
    # transcript — the job completes without speakers and offers a re-run.
    remote: bool

    @property
    def ready(self) -> bool: ...

    @property
    def last_error(self) -> str | None: ...

    async def ensure_loaded(self) -> None:
        """Load (once); raise ``DiarizationUnavailableError`` when it cannot."""
        ...

    def diarize(
        self, pcm: np.ndarray, sample_rate_hz: int, *, hints: DiarizationHints
    ) -> OfflineDiarization:
        """Diarize a whole 16 kHz mono recording. Blocking — run it off-loop."""
        ...
