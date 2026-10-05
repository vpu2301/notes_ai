"""Streaming speaker diarization for conversation mode (ADR-0034).

Core lives in ``libs/diarization``; this package keeps the per-session
timeline, the streaming engine factory and wire naming.
"""

from diarization.attribution import AttributionPolicy, SpeakerSegment, attribute_word
from diarization.clustering import ClusteringConfig, OnlineSpeakerClusterer
from diarization.embedder import EcapaEmbedder
from diarization.vad import SileroSegmenter

from .mapping import SpeakerMapping, SpeakerNaming, default_name
from .stream import DiarizationConfig, DiarizationStream

__all__ = [
    "AttributionPolicy",
    "ClusteringConfig",
    "DiarizationConfig",
    "DiarizationStream",
    "EcapaEmbedder",
    "OnlineSpeakerClusterer",
    "SileroSegmenter",
    "SpeakerMapping",
    "SpeakerNaming",
    "SpeakerSegment",
    "attribute_word",
    "default_name",
]
