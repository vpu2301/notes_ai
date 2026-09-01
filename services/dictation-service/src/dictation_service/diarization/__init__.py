"""Speaker diarization for conversation mode (sprint 14, ADR-0034).

Pipeline: Silero VAD segmentation → ECAPA-TDNN speaker embeddings →
online 2-speaker cosine clustering → word-level majority-overlap
attribution against Whisper word timings. Labels are anonymous S1/S2
proposals with confidence; UNKNOWN is emitted whenever the evidence is
ambiguous — never a guess. Display names are neutral SPEAKER_1..N
defaults plus the client-supplied mapping (`mapping.py`); there is no
server-side identity inference.
"""

from .attribution import AttributionPolicy, attribute_word
from .clustering import ClusteringConfig, OnlineSpeakerClusterer
from .embedder import EcapaEmbedder
from .mapping import SpeakerMapping, SpeakerNaming, default_name
from .stream import DiarizationConfig, DiarizationStream, SpeakerSegment
from .vad import SileroSegmenter

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
