"""Chunking of VAD speech regions before embedding (shared helper).

Both the streaming diarizer (dictation-service) and the offline diarizer
split speech regions into near-equal ≤ ``target_ms`` chunks so every
embedding sees comparable evidence; a chunk shorter than ``min_ms``
carries too little voice to embed reliably.
"""

from __future__ import annotations


def chunk_spans(start_ms: int, end_ms: int, target_ms: int, min_ms: int) -> list[tuple[int, int]]:
    """Split [start, end) into near-equal chunks ≤ target, each ≥ min.
    A short trailing remainder is folded into the previous chunk."""
    total = end_ms - start_ms
    if total <= 0:
        return []
    if total <= target_ms:
        return [(start_ms, end_ms)] if total >= min_ms else []
    n = max(1, round(total / target_ms))
    size = total / n
    out: list[tuple[int, int]] = []
    for i in range(n):
        lo = start_ms + int(i * size)
        hi = start_ms + int((i + 1) * size) if i < n - 1 else end_ms
        out.append((lo, hi))
    return out
