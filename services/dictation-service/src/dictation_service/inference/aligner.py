"""Levenshtein word alignment of consecutive overlap regions; keeps the higher-probability word."""

from __future__ import annotations

from dataclasses import dataclass

from asr_models import WordTiming


@dataclass(frozen=True, slots=True)
class AlignResult:
    """Aligned merge of two overlap regions."""

    merged: list[WordTiming]
    boundary_uncertainty: float  # 0.0 = identical, 1.0 = no overlap


def align_overlap(
    prev: list[WordTiming],
    curr: list[WordTiming],
    *,
    keep_threshold: float = 0.3,
) -> AlignResult:
    """Merge two overlap-region word lists.

    Aligned pairs keep the higher probability (ties to ``curr``); unaligned
    words survive iff probability > ``keep_threshold``.
    """
    if not prev and not curr:
        return AlignResult(merged=[], boundary_uncertainty=0.0)

    prev_strs = [w.text.lower() for w in prev]
    curr_strs = [w.text.lower() for w in curr]

    dist = normalized_levenshtein(prev_strs, curr_strs)

    ops = _backtrace_alignment(prev_strs, curr_strs)
    merged: list[WordTiming] = []
    for op, i, j in ops:
        if op == "match" or op == "sub":
            # Aligned pair — pick the higher-confidence one.
            p, c = prev[i], curr[j]
            if c.probability >= p.probability:
                merged.append(c)
            else:
                merged.append(p)
        elif op == "ins":
            # Only in curr.
            if curr[j].probability >= keep_threshold:
                merged.append(curr[j])
        elif op == "del":
            # Only in prev.
            if prev[i].probability >= keep_threshold:
                merged.append(prev[i])
    return AlignResult(merged=merged, boundary_uncertainty=dist)


def normalized_levenshtein(a: list[str], b: list[str]) -> float:
    """Word-level edit distance / max(len(a), len(b))."""
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        return 0.0
    if n == 0 or m == 0:
        return 1.0
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        curr = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[m] / max(n, m)


def _backtrace_alignment(a: list[str], b: list[str]) -> list[tuple[str, int, int]]:
    """Alignment ops as ``(op, i, j)`` in forward order; -1 index for pure insert/delete."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,  # delete
                dp[i][j - 1] + 1,  # insert
                dp[i - 1][j - 1] + cost,  # match / sub
            )

    ops: list[tuple[str, int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and a[i - 1] == b[j - 1] and dp[i][j] == dp[i - 1][j - 1]:
            ops.append(("match", i - 1, j - 1))
            i -= 1
            j -= 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            ops.append(("sub", i - 1, j - 1))
            i -= 1
            j -= 1
        elif j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            ops.append(("ins", -1, j - 1))
            j -= 1
        else:
            ops.append(("del", i - 1, -1))
            i -= 1
    ops.reverse()
    return ops
