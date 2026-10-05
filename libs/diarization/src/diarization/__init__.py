"""Speaker-diarization primitives: VAD → embeddings → clustering → attribution; three :class:`Diarizer` engines
(legacy ECAPA, pyannote community-1, HTTP) behind one roster guard. Labels are neutral SPEAKER_N, never an identity.
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
