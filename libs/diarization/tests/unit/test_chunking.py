"""Speech-region chunking (pure; shared by streaming and offline paths)."""

from __future__ import annotations

from diarization.chunking import chunk_spans


def test_chunks_splits_long_region_into_near_target_chunks() -> None:
    chunks = chunk_spans(0, 4000, 1200, 250)
    assert chunks == [(0, 1333), (1333, 2666), (2666, 4000)]
    assert all(hi - lo >= 250 for lo, hi in chunks)
    # Contiguous cover of the region.
    assert chunks[0][0] == 0 and chunks[-1][1] == 4000
    for (_, prev_hi), (lo, _) in zip(chunks, chunks[1:], strict=False):
        assert lo == prev_hi


def test_chunks_short_region_yields_nothing() -> None:
    assert chunk_spans(0, 200, 1200, 250) == []
    assert chunk_spans(1000, 1000, 1200, 250) == []


def test_chunks_region_between_min_and_target_is_single_chunk() -> None:
    assert chunk_spans(500, 1500, 1200, 250) == [(500, 1500)]
