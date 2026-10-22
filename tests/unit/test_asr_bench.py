"""tools/asr_bench (asr-perf-sprints Sprint A): CSV extraction from a stored run record and the
quality metrics on tiny synthetic transcripts."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "asr_bench"))
import bench  # noqa: E402
import quality  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "asr_bench" / "run_f2e27fc8.json"


@pytest.fixture
def export() -> dict:
    return json.loads(FIXTURE.read_text())


def test_row_from_a_stored_run(export: dict) -> None:
    row = bench.row_from_run(export)
    assert row["run_id"] == "f2e27fc8-efdc-4d1f-9ffe-ffcc13065477"
    assert row["excluded"] == ""
    assert (row["execution_mode"], row["device"], row["device_observation"]) == (
        "container",
        "cpu",
        "observed",
    )
    assert row["backend"] == "inproc_cpu_asr"
    assert row["compute_type"] == "int8"
    assert row["memory_total_bytes"] == 14636097536
    assert row["asr_primary_wall_seconds"] == pytest.approx(1503.859)
    assert row["asr_primary_rtf"] == pytest.approx(1503.859 / 900)
    # The fixture keeps 3 of the 54 checks.
    assert row["lid_call_count"] == 3
    assert row["lid_total_seconds"] == pytest.approx(30.1467, abs=1e-3)
    assert row["time_to_asr_start_seconds"] == pytest.approx(656.13, abs=0.01)
    # The redelivered pickup (2281 s) is not the run's queue wait.
    assert row["queue_wait_seconds"] == pytest.approx(21.8324)
    assert row["asr_model_startup_load_seconds"] == pytest.approx(24.349)
    assert row["diarization_infer_seconds"] == pytest.approx(113.8257)
    assert row["pipeline_wall_seconds"] == pytest.approx(2307.33719)
    assert row["rss_peak_bytes"] == 2451648512
    assert row["swap_delta_bytes"] == 1059717120 - 740835328


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"status": "partial"}, "status:partial"),
        ({"attempts": 3}, "attempt>1"),
        ({"concurrent_runs_at_start": 1}, "concurrent"),
    ],
)
def test_runs_that_never_enter_an_aggregate(export: dict, change: dict, reason: str) -> None:
    run = copy.deepcopy(export)
    run["processing_run"].update(change)
    assert bench.row_from_run(run)["excluded"] == reason


def test_csv_round_trip(tmp_path: Path, export: dict) -> None:
    path = tmp_path / "runs.csv"
    row = bench.row_from_run(export) | {"recording": "en-15m", "temp": "warm", "rep": 1}
    bench.append_csv(path, row)
    bench.append_csv(path, row)
    rows = bench.read_csv(path)
    assert len(rows) == 2
    assert bench.num(rows[0]["lid_call_count"]) == 3


def _seg(text, start, end, speaker, language=None, step=500):
    words = [
        {"text": w, "start_ms": start + i * step, "end_ms": start + (i + 1) * step}
        for i, w in enumerate(text.split())
    ]
    return {
        "text": text, "start_ms": start, "end_ms": end, "speaker": speaker,
        "language": language, "words": words,
    }  # fmt: skip


REF = {
    "language": "de",
    "segments": [
        _seg("wir treffen uns morgen früh", 0, 2500, "A"),
        _seg("let us meet tomorrow morning", 3000, 5500, "B", "en"),
        _seg("ja gut", 6000, 7000, "A"),
    ],
}


def test_identical_transcript_scores_perfect() -> None:
    q = quality.score(REF, REF, [{"start_s": 3.0, "end_s": 6.0, "lang": "en"}])
    assert q["wer"] == 0
    assert q["cer"] == 0
    assert q["ts_median_ms"] == 0
    assert q["speaker_agreement"] == 1.0
    assert q["hallucinated_segments"] == 0
    assert (q["switch_long"], q["switch_long_kept"], q["switch_long_recall"]) == (1, 1, 1.0)


def test_translated_passage_is_a_switch_failure() -> None:
    hyp = copy.deepcopy(REF)
    hyp["segments"][1] = _seg("treffen wir uns morgen früh", 3000, 5500, "B")
    q = quality.score(REF, hyp, [{"start_s": 3.0, "end_s": 6.0, "lang": "en"}])
    assert q["switch_long_recall"] == 0.0
    assert q["wer"] > 0


def test_dropped_short_passage_is_not_kept() -> None:
    hyp = copy.deepcopy(REF)
    del hyp["segments"][2]
    q = quality.score(REF, hyp, [{"start_s": 6.0, "end_s": 7.0, "lang": "de"}])
    assert (q["switch_short"], q["switch_short_kept"]) == (1, 0)


def test_speaker_labels_are_mapped_before_agreement() -> None:
    hyp = copy.deepcopy(REF)
    for seg, label in zip(hyp["segments"], ("S2", "S1", "S1"), strict=True):
        seg["speaker"] = label
    q = quality.score(REF, hyp)
    # Best mapping A→S2 (5 words) and B→S1 (5); "ja gut" (A, labelled S1) disagrees.
    assert q["speaker_agreement"] == pytest.approx(10 / 12)


def test_timestamp_shift_and_hallucinated_segment() -> None:
    hyp = copy.deepcopy(REF)
    for seg in hyp["segments"]:
        for w in seg["words"]:
            w["start_ms"] += 40
    hyp["segments"].append(_seg("danke fürs zuschauen", 20000, 21500, "A"))
    q = quality.score(REF, hyp)
    assert q["ts_median_ms"] == 40
    assert q["hallucinated_segments"] == 1
