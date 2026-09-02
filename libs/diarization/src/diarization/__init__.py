"""libs/diarization — speaker-diarization primitives shared across services.

Pipeline pieces: Silero VAD segmentation → ECAPA-TDNN speaker embeddings
→ deterministic cosine clustering (online 2-slot for live sessions,
agglomerative N-speaker for batch, ADR-0045) → majority-overlap
attribution. Labels are anonymous S1/S2 proposals with confidence;
UNKNOWN whenever the evidence is ambiguous — never a guess. Outward
labels are always neutral SPEAKER_1..N; there is no identity inference.

Consumers:
- dictation-service builds its per-session streaming timeline on the
  embedder/segmenter/clusterer (its stream + wire mapping stay there);
- asr-worker runs :func:`diarize_offline` over a whole recording for
  diarized batch jobs (Ambient Capture v1).

Model weights are baked at ``/opt/models/ecapa`` in prod images and
verified against pinned digests at load time (``integrity``); dev boxes
prepare the same dir via ``make prepare-ecapa``.
"""

from .attribution import UNKNOWN, AttributionPolicy, SpeakerSegment, attribute_word
from .chunking import chunk_spans
from .clustering import ClusteringConfig, OnlineSpeakerClusterer
from .embedder import EcapaEmbedder
from .engine import DiarizationEngine, DiarizationUnavailableError
from .integrity import ModelIntegrityError, sha256_file, verify_model_dir
from .offline import (
    OfflineClusteringConfig,
    OfflineDiarization,
    OfflineDiarizationConfig,
    SpeakerTurn,
    cluster_embeddings,
    diarize_offline,
)
from .vad import SileroSegmenter

__all__ = [
    "UNKNOWN",
    "AttributionPolicy",
    "ClusteringConfig",
    "DiarizationEngine",
    "DiarizationUnavailableError",
    "EcapaEmbedder",
    "ModelIntegrityError",
    "OfflineClusteringConfig",
    "OfflineDiarization",
    "OfflineDiarizationConfig",
    "OnlineSpeakerClusterer",
    "SileroSegmenter",
    "SpeakerSegment",
    "SpeakerTurn",
    "attribute_word",
    "chunk_spans",
    "cluster_embeddings",
    "diarize_offline",
    "sha256_file",
    "verify_model_dir",
]
