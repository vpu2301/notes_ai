"""Sprint 29 seam: hints, roster guard, legacy hint support, v2 adapter.

No torch, no pyannote: the legacy engine runs on synthetic embeddings and
the v2 adapter on a faked ``DiarizeOutput``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

from diarization import (
    UNKNOWN,
    DiarizationHints,
    DiarizationUnavailableError,
    Diarizer,
    InvalidHintsError,
    LegacyEcapaDiarizer,
    OfflineDiarizationConfig,
    PyannoteDiarizer,
    RosterGuardConfig,
    SpeakerSegment,
    diarize_embeddings,
    guard_roster,
)
from diarization.offline import OfflineClusteringConfig, cluster_embeddings_with_stats
from diarization.pyannote_engine import (
    OVERLAP_CONFIDENCE,
    PipelineResult,
    extract,
    to_diarization,
)

DIM = 8


def _voice(axis: int, n: int) -> list[np.ndarray]:
    """n chunks of one voice: unit vector on ``axis`` with small jitter on
    axes 6/7, so voices on different axes are near-orthogonal."""
    out = []
    for i in range(n):
        v = np.zeros(DIM)
        v[axis] = math.sqrt(0.95)
        v[6 + i % 2] = math.sqrt(0.05)
        out.append(v)
    return out


def _spans(n: int, chunk_ms: int = 1000) -> list[tuple[int, int]]:
    return [(i * chunk_ms, (i + 1) * chunk_ms) for i in range(n)]


# ── Hints ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "hints",
    [
        DiarizationHints(num_speakers=0),
        DiarizationHints(num_speakers=9),
        DiarizationHints(max_speakers=0),
        DiarizationHints(min_speakers=4, max_speakers=2),
    ],
)
def test_impossible_hints_are_rejected(hints: DiarizationHints) -> None:
    with pytest.raises(InvalidHintsError):
        hints.validated()


def test_an_exact_count_overrides_min_and_max() -> None:
    hints = DiarizationHints(num_speakers=4, max_speakers=3).validated()

    assert hints == DiarizationHints(num_speakers=4)
    assert hints.kind == "exact"
    assert DiarizationHints(max_speakers=3).kind == "max"
    assert DiarizationHints().kind == "none"


# ── Legacy engine honours hints ──────────────────────────────────────


def _four_voices() -> list[np.ndarray]:
    return _voice(0, 6) + _voice(1, 6) + _voice(2, 6) + _voice(3, 6)


def test_legacy_finds_four_voices_without_a_hint() -> None:
    labels, _, _ = cluster_embeddings_with_stats(_four_voices(), OfflineClusteringConfig())

    assert len({label for label in labels if label != UNKNOWN}) == 4


def test_legacy_with_num_speakers_2_returns_exactly_two_labels() -> None:
    labels, _, stats = cluster_embeddings_with_stats(
        _four_voices(), OfflineClusteringConfig(), num_speakers=2
    )

    assert len({label for label in labels if label != UNKNOWN}) == 2
    assert stats.clusters_raw == 2


def test_legacy_max_speakers_caps_the_roster() -> None:
    labels, _, _ = cluster_embeddings_with_stats(
        _four_voices(), OfflineClusteringConfig(), max_speakers=3
    )

    assert len({label for label in labels if label != UNKNOWN}) <= 3


def _noise() -> np.ndarray:
    v = np.zeros(DIM)
    v[5] = 1.0  # like nobody
    return v


def _two_voices_and_a_cough() -> list[np.ndarray]:
    a = _voice(0, 15)
    b = [
        0.25 * a[i] / np.linalg.norm(a[i]) + math.sqrt(1 - 0.0625) * v
        for i, v in enumerate(_voice(1, 15))
    ]
    return a + [_noise()] + b


@pytest.mark.parametrize("hint", [{"num_speakers": 2}, {"max_speakers": 2}])
def test_a_stray_chunk_never_takes_a_speaker_slot(hint: dict[str, int]) -> None:
    """Review finding: merge-until-k merged the two real voices and kept
    the cough. The count is of people; dust is scored, not counted."""
    vectors = _two_voices_and_a_cough()
    labels, _, _ = cluster_embeddings_with_stats(vectors, OfflineClusteringConfig(), **hint)

    a, cough, b = labels[:15], labels[15], labels[16:]
    assert len(set(a)) == 1 and len(set(b)) == 1
    assert a[0] != b[0] and UNKNOWN not in (a[0], b[0])
    assert cough not in (a[0], b[0]) or cough == UNKNOWN


def test_an_exact_count_above_what_the_audio_holds_invents_nobody() -> None:
    labels, _, _ = cluster_embeddings_with_stats(
        _voice(0, 6), OfflineClusteringConfig(), num_speakers=3
    )

    assert len({label for label in labels if label != UNKNOWN}) == 1


def test_diarize_embeddings_keeps_sprint28_roster_without_a_guard() -> None:
    vectors = _voice(0, 20) + _voice(1, 3)  # a 3-second voice
    diar = diarize_embeddings(
        _spans(len(vectors)), vectors, duration_ms=23_000, config=OfflineDiarizationConfig()
    )

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert diar.roster is not None and diar.roster.speakers_dissolved == 0
    assert diar.engine == "legacy-ecapa-ahc"


def test_legacy_diarizer_satisfies_the_protocol() -> None:
    engine = LegacyEcapaDiarizer(model_dir="/nonexistent")

    assert isinstance(engine, Diarizer)
    assert engine.ready is False


# ── Roster guard ──────────────────────────────────────────────────────


def _seg(label: str, start_s: float, end_s: float) -> SpeakerSegment:
    return SpeakerSegment(
        start_ms=int(start_s * 1000), end_ms=int(end_s * 1000), label=label, confidence=0.9
    )


def test_guard_dissolves_a_three_second_speaker_into_the_voice_it_resembles() -> None:
    segments = [_seg("A", 0, 60), _seg("B", 60, 63), _seg("C", 63, 120)]
    centroids = {
        "A": np.array([1.0, 0.0]),
        "B": np.array([0.9, 0.1]),  # sounds like A
        "C": np.array([0.0, 1.0]),
    }

    out = guard_roster(segments, config=RosterGuardConfig(), centroids=centroids)

    assert [s.label for s in out.segments] == ["A", "A", "C"]
    assert out.speakers_kept == 2
    assert out.speakers_dissolved == 1


def test_a_dissolved_speaker_nobody_resembles_becomes_unattributed() -> None:
    segments = [_seg("A", 0, 60), _seg("B", 60, 63), _seg("C", 63, 120)]
    centroids = {
        "A": np.array([1.0, 0.0, 0.0]),
        "B": np.array([0.0, 0.0, 1.0]),
        "C": np.array([0.0, 1.0, 0.0]),
    }

    out = guard_roster(segments, config=RosterGuardConfig(), centroids=centroids)

    assert out.segments[1].label == UNKNOWN
    assert out.segments[1].confidence == 0.0


def test_the_floor_is_off_when_a_person_stated_the_count() -> None:
    segments = [_seg("A", 0, 60), _seg("B", 60, 63), _seg("C", 63, 120)]

    out = guard_roster(segments, config=RosterGuardConfig(), hints=DiarizationHints(num_speakers=3))

    assert out.speakers_dissolved == 0
    assert out.count_confidence == "high"


def test_a_short_memo_keeps_its_one_voice() -> None:
    out = guard_roster([_seg("A", 0, 3), _seg("B", 3, 4)], config=RosterGuardConfig())

    assert out.speakers_kept == 1


@pytest.mark.parametrize(
    ("segments", "overlap", "reason"),
    [
        # B keeps 4 % of the speech: kept, but small.
        ([_seg("A", 0, 96), _seg("B", 96, 100)], [], "small_speaker"),
        # 3 s of 100 dissolved (≥ 2 %): something real may be gone.
        ([_seg("A", 0, 50), _seg("B", 50, 53), _seg("C", 53, 100)], [], "dissolved_speaker"),
        # 30 % of the speech overlaps.
        ([_seg("A", 0, 50), _seg("B", 50, 100)], [(10_000, 40_000)], "overlap"),
    ],
)
def test_count_confidence_is_low_for_a_shaky_roster(
    segments: list[SpeakerSegment], overlap: list[tuple[int, int]], reason: str
) -> None:
    out = guard_roster(
        segments, config=RosterGuardConfig(min_speaker_speech_ms=3500), overlap_ms=overlap
    )

    assert out.count_confidence == "low"
    assert reason in out.reasons


def test_count_confidence_is_high_for_a_clean_two_person_talk() -> None:
    out = guard_roster([_seg("A", 0, 50), _seg("B", 50, 100)], config=RosterGuardConfig())

    assert out.count_confidence == "high"
    assert out.reasons == ()


# ── v2 adapter (pyannote objects faked) ───────────────────────────────


def test_v2_maps_the_exclusive_timeline_and_marks_overlap_uncertain() -> None:
    result = PipelineResult(
        exclusive=[(0.0, 10.0, "SPEAKER_00"), (10.0, 20.0, "SPEAKER_01")],
        overlaps=[(9.0, 11.0)],
    )

    diar = to_diarization(
        result,
        duration_ms=20_000,
        hints=DiarizationHints(),
        roster=None,
        config=OfflineDiarizationConfig(),
        engine_version="community-1@test",
    )

    evidence = [(s.start_ms, s.end_ms, s.label, s.confidence) for s in diar.segments]
    assert evidence == [
        (0, 9000, "SPEAKER_1", 1.0),
        (9000, 10_000, "SPEAKER_1", OVERLAP_CONFIDENCE),
        (10_000, 11_000, "SPEAKER_2", OVERLAP_CONFIDENCE),
        (11_000, 20_000, "SPEAKER_2", 1.0),
    ]
    assert diar.overlap_ms == [(9000, 11_000)]
    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert diar.attribute(12_000, 13_000) == "SPEAKER_2"
    assert diar.engine == "pyannote-community-1"


def test_v2_labels_are_numbered_by_first_appearance() -> None:
    result = PipelineResult(
        exclusive=[(0.0, 30.0, "SPEAKER_03"), (30.0, 60.0, "SPEAKER_00")], overlaps=[]
    )

    diar = to_diarization(
        result,
        duration_ms=60_000,
        hints=DiarizationHints(),
        roster=None,
        config=OfflineDiarizationConfig(),
        engine_version="x",
    )

    assert diar.attribute(1000, 2000) == "SPEAKER_1"
    assert diar.attribute(40_000, 41_000) == "SPEAKER_2"


@dataclass
class _Seg:
    start: float
    end: float


class _Annotation:
    def __init__(self, tracks: list[tuple[float, float, str]], overlap: list[tuple[float, float]]):
        self._tracks = tracks
        self._overlap = overlap

    def itertracks(self, yield_label: bool = False):  # noqa: ANN201
        for start, end, label in self._tracks:
            yield _Seg(start, end), None, label

    def get_overlap(self) -> list[_Seg]:
        return [_Seg(a, b) for a, b in self._overlap]

    def labels(self) -> list[str]:
        return sorted({t[2] for t in self._tracks})


def _fake_output(embeddings: np.ndarray | None) -> SimpleNamespace:
    tracks = [(0.0, 60.0, "SPEAKER_00"), (60.0, 63.0, "SPEAKER_01"), (63.0, 120.0, "SPEAKER_02")]
    return SimpleNamespace(
        exclusive_speaker_diarization=_Annotation(tracks, []),
        speaker_diarization=_Annotation(tracks, []),
        speaker_embeddings=embeddings,
    )


def test_v2_embeddings_steer_the_guard_and_never_reach_the_result() -> None:
    embeddings = np.array([[1.0, 0.0], [0.95, 0.05], [0.0, 1.0]])
    result = extract(_fake_output(embeddings))

    diar = to_diarization(
        result,
        duration_ms=120_000,
        hints=DiarizationHints(),
        roster=RosterGuardConfig(),
        config=OfflineDiarizationConfig(),
        engine_version="x",
    )

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert diar.attribute(61_000, 62_000) == "SPEAKER_1"  # folded into the voice it matches
    assert diar.stats.clusters_dropped == 1
    # Nothing on the result carries a vector.
    for value in vars(diar).values():
        assert not isinstance(value, np.ndarray)
    assert "0.95" not in json.dumps([s.__dict__ for s in diar.segments])


def test_v2_drops_centroids_it_cannot_align_with_labels() -> None:
    result = extract(_fake_output(np.ones((2, 2))))  # 3 labels, 2 rows

    assert result.centroids is None


# ── v2 load guard ─────────────────────────────────────────────────────


async def test_v2_refuses_to_load_with_telemetry_enabled() -> None:
    engine = PyannoteDiarizer(
        model_dir="/nonexistent",
        environ={"PYANNOTE_METRICS_ENABLED": "true", "HF_HUB_OFFLINE": "1"},
    )

    with pytest.raises(DiarizationUnavailableError, match="telemetry_not_disabled"):
        await engine.ensure_loaded()
    assert engine.last_error == "telemetry_not_disabled"
    assert engine.ready is False


async def test_v2_refuses_to_load_when_telemetry_flag_is_unset() -> None:
    engine = PyannoteDiarizer(model_dir="/nonexistent", environ={"HF_HUB_OFFLINE": "1"})

    with pytest.raises(DiarizationUnavailableError, match="telemetry_not_disabled"):
        await engine.ensure_loaded()


async def test_v2_refuses_to_load_with_the_hub_online() -> None:
    engine = PyannoteDiarizer(
        model_dir="/nonexistent", environ={"PYANNOTE_METRICS_ENABLED": "false"}
    )

    with pytest.raises(DiarizationUnavailableError, match="hub_not_offline"):
        await engine.ensure_loaded()


async def test_v2_with_a_safe_environment_still_fails_closed_on_a_missing_model() -> None:
    engine = PyannoteDiarizer(
        model_dir="/nonexistent",
        environ={"PYANNOTE_METRICS_ENABLED": "false", "HF_HUB_OFFLINE": "1"},
        pins={"pytorch_model.bin": "0" * 64},
    )

    with pytest.raises(DiarizationUnavailableError):
        await engine.ensure_loaded()
    assert isinstance(engine, Diarizer)


async def test_v2_verifies_its_own_config_not_ecapas(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """community-1 ships config.yaml, not ECAPA's hyperparams.yaml: the
    integrity check must ask for the right file, and still fail closed."""
    from diarization.integrity import ModelIntegrityError, verify_model_dir

    (tmp_path / "config.yaml").write_text("pipeline: {}\n")
    assert verify_model_dir(tmp_path, pins={"config.yaml": ""}, required_files=("config.yaml",))
    with pytest.raises(ModelIntegrityError, match="hyperparams.yaml"):
        verify_model_dir(tmp_path, pins={})
    (tmp_path / "config.yaml").unlink()
    with pytest.raises(ModelIntegrityError, match="config.yaml"):
        verify_model_dir(tmp_path, pins={}, required_files=("config.yaml",))


def test_v2_with_an_exact_count_joins_a_split_voice() -> None:
    """Review finding: pyannote forces k clusters; one voice asked to be
    three comes back split. Same-voice labels are joined — fewer, never more."""
    same = np.array([1.0, 0.0, 0.0])
    result = PipelineResult(
        exclusive=[(0.0, 30.0, "S0"), (30.0, 60.0, "S1"), (60.0, 90.0, "S2")],
        overlaps=[],
        centroids={"S0": same, "S1": same * 0.98 + 0.02, "S2": np.array([0.0, 1.0, 0.0])},
    )

    diar = to_diarization(
        result,
        duration_ms=90_000,
        hints=DiarizationHints(num_speakers=3),
        roster=RosterGuardConfig(),
        config=OfflineDiarizationConfig(),
        engine_version="x",
    )

    assert diar.speakers == ["SPEAKER_1", "SPEAKER_2"]
    assert diar.attribute(40_000, 41_000) == "SPEAKER_1"


def test_v2_without_a_count_leaves_labels_to_pyannote() -> None:
    same = np.array([1.0, 0.0])
    result = PipelineResult(
        exclusive=[(0.0, 30.0, "S0"), (30.0, 60.0, "S1")],
        overlaps=[],
        centroids={"S0": same, "S1": same},
    )

    diar = to_diarization(
        result,
        duration_ms=60_000,
        hints=DiarizationHints(),
        roster=None,
        config=OfflineDiarizationConfig(),
        engine_version="x",
    )

    assert len(diar.speakers) == 2


def test_a_cap_above_what_the_engine_found_changes_nothing() -> None:
    """Sprint 30 C2: a calendar cap is a ceiling. On the gold replay the
    first version under-counted — it merged real voices to fit dust."""
    vectors = _two_voices_and_a_cough() + _voice(2, 10)
    plain, _, _ = cluster_embeddings_with_stats(vectors, OfflineClusteringConfig())

    capped, _, _ = cluster_embeddings_with_stats(vectors, OfflineClusteringConfig(), max_speakers=5)

    assert capped == plain
