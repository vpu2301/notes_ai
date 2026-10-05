"""Sprint F1 T5: the assertion vocabulary of ``tests/fixtures/eval/asr/``.

Shared by the CI regression test (``m12``, scripted engine),
``coverage_eval.py`` (``r02``, the real recording) and, from Sprint TQ1,
``asr_eval.py`` (``r03``/``r04`` on the gold set). Output is check names and
PASS/FAIL, never the text a check looks for beyond its own name.

Sprint TQ1 adds:

- ``must_not_contain`` — none of these strings (case-folded) anywhere in the
  transcript (T-INJ).
- ``entity_variants_max`` — ``{canonical: {"max": n, "heard_as": [...]}}``:
  at most ``n`` of the listed spellings occur (T-ENT). ``heard_as`` lists the
  spellings the audit saw, the canonical one included; without a reference
  this is how a raw transcript's variants are counted.
- ``expected_fail_until`` on any item — the sprint that is meant to fix it.
  A failure there is ``XFAIL`` and does not fail the run; a pass is
  ``XPASS`` and is reported, so the marker is removed.
- ``pending`` on a ``must_contain_before_ms`` item — its text and time come
  from the reference labelling (T2) and are not known yet: ``PENDING``.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

from asr_models import TranscriptionOutput

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "eval" / "asr"


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def load(name: str) -> dict[str, Any]:
    for path in (FIXTURES / f"{name}.json", FIXTURES / "assertions" / f"{name}.assertions.json"):
        if path.is_file():
            return json.loads(path.read_text("utf-8"))
    raise FileNotFoundError(name)


def _words_fold(text: str) -> str:
    """Folded text with punctuation as spaces, padded, for whole-word finds."""
    kept = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in _fold(text))
    return f" {' '.join(kept.split())} "


def statuses(assertions: dict[str, Any], output: TranscriptionOutput) -> list[tuple[str, str]]:
    """``[(check, PASS|FAIL|XFAIL|XPASS|PENDING)]`` for one transcript."""
    expected = expected_failures(assertions)
    out: list[tuple[str, str]] = []
    for name, ok in check(assertions, output):
        if name in expected:
            out.append((name, "XPASS" if ok else "XFAIL"))
        else:
            out.append((name, "PASS" if ok else "FAIL"))
    out.extend((name, "PENDING") for name in pending(assertions))
    return out


def expected_failures(assertions: dict[str, Any]) -> dict[str, str]:
    """Check name → the sprint meant to make it pass."""
    out: dict[str, str] = {}
    for k, item in enumerate(assertions.get("must_not_contain", [])):
        if isinstance(item, dict) and item.get("expected_fail_until"):
            out[f"must_not_contain[{k}]"] = item["expected_fail_until"]
    for canonical, item in (assertions.get("entity_variants_max") or {}).items():
        if item.get("expected_fail_until"):
            out[f"entity_variants_max[{canonical}]"] = item["expected_fail_until"]
    for k, item in enumerate(assertions.get("must_contain_before_ms", [])):
        if item.get("expected_fail_until"):
            out[f"must_contain_before_ms[{k}]"] = item["expected_fail_until"]
    return out


def pending(assertions: dict[str, Any]) -> list[str]:
    return [
        f"must_contain_before_ms[{k}]"
        for k, item in enumerate(assertions.get("must_contain_before_ms", []))
        if item.get("pending")
    ]


def check(assertions: dict[str, Any], output: TranscriptionOutput) -> list[tuple[str, bool]]:
    """``[(check, passed)]`` for one transcript. Pending items are skipped."""
    out: list[tuple[str, bool]] = []
    if "coverage_min_share" in assertions:
        c = output.diagnostics.coverage
        out.append(
            (
                f"coverage_share>={assertions['coverage_min_share']}",
                c is not None and c.share >= assertions["coverage_min_share"],
            )
        )
    for k, item in enumerate(assertions.get("must_contain_before_ms", [])):
        if item.get("pending"):
            continue
        needle = _fold(item["text"])
        early = _fold(" ".join(s.text for s in output.segments if s.start_ms < item["before_ms"]))
        out.append((f"must_contain_before_ms[{k}]", needle in early))
    whole = _words_fold(" ".join(s.text for s in output.segments))
    for k, item in enumerate(assertions.get("must_not_contain", [])):
        needle = item["text"] if isinstance(item, dict) else item
        out.append((f"must_not_contain[{k}]", _words_fold(needle) not in whole))
    for canonical, item in (assertions.get("entity_variants_max") or {}).items():
        found = {v for v in item["heard_as"] if _words_fold(v) in whole}
        out.append((f"entity_variants_max[{canonical}]", len(found) <= item["max"]))
    return out
