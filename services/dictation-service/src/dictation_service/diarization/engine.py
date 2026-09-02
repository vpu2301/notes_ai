"""Streaming seam over the shared diarization engine (libs/diarization).

The engine lifecycle (lazy locked load, pinned-digest verification,
warmup, readiness reporting) was hoisted to ``diarization.engine`` for
reuse by the batch worker; what stays here is the dictation-specific
surface: the conversation-mode disabled message and the per-session
:class:`DiarizationStream` factory (the stream owns mutable clustering
state and lives in this service — the lib knows nothing about sessions).
"""

from __future__ import annotations

from diarization.engine import DiarizationEngine as SharedDiarizationEngine
from diarization.engine import DiarizationUnavailableError

from .stream import DiarizationConfig, DiarizationStream

__all__ = ["DiarizationEngine", "DiarizationUnavailableError"]


class DiarizationEngine(SharedDiarizationEngine):
    def __init__(
        self,
        *,
        model_dir: str,
        device: str = "cpu",
        enabled: bool = True,
        pins: dict[str, str] | None = None,
        model_repo: str = "",
        model_revision: str = "",
    ) -> None:
        super().__init__(
            model_dir=model_dir,
            device=device,
            enabled=enabled,
            pins=pins,
            model_repo=model_repo,
            model_revision=model_revision,
            disabled_reason="conversation mode disabled (MDX_CONVERSATION_ENABLED)",
        )

    @property
    def ready_for_conversation(self) -> bool:
        """True iff this worker can take a conversation session RIGHT NOW.

        Readiness gates on this: a worker advertising conversation capacity
        with a cold diarizer would pay weight-loading on the first window
        and blow the latency budget (sprint-14 deployment).
        """
        return self.ready

    def new_stream(self, config: DiarizationConfig | None = None) -> DiarizationStream:
        # Property access raises DiarizationUnavailableError when the
        # engine is not loaded — same fail-loud contract as before.
        return DiarizationStream(
            embedder=self.embedder,
            segmenter=self.segmenter,
            config=config,
        )
