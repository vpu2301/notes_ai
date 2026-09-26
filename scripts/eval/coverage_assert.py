"""Sprint F1 T5: the assertion vocabulary of ``tests/fixtures/eval/asr/``.

Shared by the CI regression test (``m12``, scripted engine) and
``coverage_eval.py`` (``r02``, the real recording). Output is check names and
PASS/FAIL, never the text a check looks for beyond its own name.
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


def check(assertions: dict[str, Any], output: TranscriptionOutput) -> list[tuple[str, bool]]:
    """``[(check, passed)]`` for one transcript."""
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
        needle = _fold(item["text"])
        early = _fold(" ".join(s.text for s in output.segments if s.start_ms < item["before_ms"]))
        out.append((f"must_contain_before_ms[{k}]", needle in early))
    return out
