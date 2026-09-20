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

Sprint 29: the batch worker talks to a :class:`Diarizer` (``protocol``) —
:class:`LegacyEcapaDiarizer` (the pipeline above), :class:`PyannoteDiarizer`
(community-1, ``pyannote_engine``) or :class:`HttpDiarizer` (the same
community-1 pipeline on a GPU endpoint, ``http_engine`` + ``wire``) —
all guarded by the engine-agnostic roster floor (``roster``).
"""

from .attribution import UNKNOWN, AttributionPolicy, SpeakerSegment, attribute_word
from .channels import ChannelActivity, analyse_channels, side_for_span
from .chunking import chunk_spans
from .clustering import ClusteringConfig, OnlineSpeakerClusterer
from .dual_channel import diarize_dual
from .embedder import EcapaEmbedder
from .engine import DiarizationEngine, DiarizationUnavailableError, LegacyEcapaDiarizer
from .http_engine import DiarizationRequestError, HttpDiarizer
from .integrity import ModelIntegrityError, sha256_file, verify_model_dir
from .offline import (
    ENGINE_ID,
    ENGINE_VERSION,
    ClusterStats,
    OfflineClusteringConfig,
    OfflineDiarization,
    OfflineDiarizationConfig,
    SpeakerTurn,
    cluster_embeddings,
    cluster_embeddings_with_stats,
    diarize_embeddings,
    diarize_offline,
    embed_chunks,
)
from .protocol import MAX_HINT, MIN_HINT, NO_HINTS, DiarizationHints, Diarizer, InvalidHintsError
from .pyannote_engine import PyannoteDiarizer
from .roster import CountConfidence, RosterGuardConfig, RosterOutcome, guard_roster
from .vad import SileroSegmenter
from .wire import (
    WirePayloadError,
    audio_seconds,
    decode_audio,
    encode_audio,
    from_payload,
    to_payload,
)

__all__ = [
    "AttributionPolicy",
    "ChannelActivity",
    "ClusterStats",
    "ClusteringConfig",
    "CountConfidence",
    "DiarizationEngine",
    "DiarizationHints",
    "DiarizationRequestError",
    "DiarizationUnavailableError",
    "Diarizer",
    "ENGINE_ID",
    "ENGINE_VERSION",
    "EcapaEmbedder",
    "HttpDiarizer",
    "InvalidHintsError",
    "LegacyEcapaDiarizer",
    "MAX_HINT",
    "MIN_HINT",
    "ModelIntegrityError",
    "NO_HINTS",
    "OfflineClusteringConfig",
    "OfflineDiarization",
    "OfflineDiarizationConfig",
    "OnlineSpeakerClusterer",
    "PyannoteDiarizer",
    "RosterGuardConfig",
    "RosterOutcome",
    "SileroSegmenter",
    "SpeakerSegment",
    "SpeakerTurn",
    "UNKNOWN",
    "WirePayloadError",
    "analyse_channels",
    "attribute_word",
    "audio_seconds",
    "chunk_spans",
    "cluster_embeddings",
    "cluster_embeddings_with_stats",
    "decode_audio",
    "diarize_dual",
    "diarize_embeddings",
    "diarize_offline",
    "embed_chunks",
    "encode_audio",
    "from_payload",
    "guard_roster",
    "sha256_file",
    "side_for_span",
    "to_payload",
    "verify_model_dir",
]
