"""The shadow script reads transcript text: it may print counts only (Sprint 32 B-7)."""

from __future__ import annotations

import ast
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ops" / "name_suggestion_shadow.py"

_spec = importlib.util.spec_from_file_location("name_suggestion_shadow", SCRIPT)
assert _spec is not None and _spec.loader is not None
shadow = importlib.util.module_from_spec(_spec)
sys.modules["name_suggestion_shadow"] = shadow
_spec.loader.exec_module(shadow)


def test_the_only_output_call_is_the_counts_emitter() -> None:
    tree = ast.parse(SCRIPT.read_text())
    outputs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            if name in {"print", "write", "info", "debug", "warning", "error", "exception", "log"}:
                outputs.append(node)
    assert len(outputs) == 1, "exactly one output call (the counts emitter)"
    emitter = next(
        f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef) and f.name == "_emit"
    )
    assert any(n is outputs[0] for n in ast.walk(emitter)), "and it lives in _emit()"
    text = SCRIPT.read_text()
    assert "getLogger" not in text, "no logger of its own"
    assert "logging.disable(logging.CRITICAL)" in text, "library logging silenced"


@dataclass
class S:
    label: str
    name: str


def test_scoring_compares_only_names_people_chose() -> None:
    counts = shadow.score(
        [S("SPEAKER_1", "Anna Keller"), S("SPEAKER_2", "Tom Berg"), S("SPEAKER_3", "Olena")],
        names={"SPEAKER_1": "anna  keller", "SPEAKER_2": "Thomas", "SPEAKER_3": "Olena"},
        sources={"SPEAKER_1": "picklist", "SPEAKER_2": "typed", "SPEAKER_3": "channel"},
    )

    assert counts == {"offered": 3, "agree": 1, "disagree": 1, "unnamed": 1}
