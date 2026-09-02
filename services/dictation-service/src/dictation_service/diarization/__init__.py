"""Speaker diarization for conversation mode (sprint 14, ADR-0034).

Pipeline: Silero VAD segmentation → ECAPA-TDNN speaker embeddings →
online 2-speaker cosine clustering → word-level majority-overlap
attribution against Whisper word timings. Labels are anonymous S1/S2
proposals with confidence; UNKNOWN is emitted whenever the evidence is
ambiguous — never a guess. Display names are neutral SPEAKER_1..N
defaults plus the client-supplied mapping (`mapping.py`); there is no
server-side identity inference.

The reusable core (embedder, VAD, clustering, attribution, integrity,
engine lifecycle) lives in ``libs/diarization`` and is shared with the
batch worker's offline diarizer; this package keeps the streaming
session pieces — the per-session timeline (`stream.py`), the engine's
streaming factory (`engine.py`), and wire naming (`mapping.py`).
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
