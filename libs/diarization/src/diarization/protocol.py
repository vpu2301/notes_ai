"""The diarizer seam: every engine yields chunk-level :class:`SpeakerSegment` evidence in an :class:`OfflineDiarization`.

``num_speakers`` is a person's stated count and wins; ``max_speakers`` is a cap. An engine may return fewer, never more.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

    from .offline import OfflineDiarization

# Eight matches the roster cap of both engines and the API's 1..8 range.
MIN_HINT = 1
MAX_HINT = 8


class InvalidHintsError(ValueError):
    """Hints that cannot describe a recording (0 people, min above max)."""


@dataclass(frozen=True)
class DiarizationHints:
    num_speakers: int | None = None  # exact, from a person
    min_speakers: int | None = None
    max_speakers: int | None = None  # cap, e.g. from the calendar

    def validated(self) -> DiarizationHints:
        """Range-check (1..8, ``min <= max``); ``num_speakers`` overrides min/max rather than being checked against them."""
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
    # Remote engine down → the job completes without speakers and offers a re-run; in-process failure fails the job.
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
