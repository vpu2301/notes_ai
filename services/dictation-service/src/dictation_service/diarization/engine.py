"""Streaming seam over libs/diarization: the per-session :class:`DiarizationStream` factory."""

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
        """True iff this worker can take a conversation session right now (readiness gates on it)."""
        return self.ready

    def new_stream(self, config: DiarizationConfig | None = None) -> DiarizationStream:
        # Property access raises DiarizationUnavailableError when not loaded.
        return DiarizationStream(
            embedder=self.embedder,
            segmenter=self.segmenter,
            config=config,
        )
