"""Sprint-13 close-out guards: kind registration + metric-label discipline.

Two failure modes these catch:
- a kind emitted in code but absent from the catalogue (the catalogue
  stops being the source of truth the moment that happens);
- an option VALUE reaching a metric label. Option values are
  template-authored, so a label carrying them is unbounded cardinality
  AND tenant vocabulary in the metrics store. field_type only.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
_EVENT_KINDS = REPO / "docs" / "audit" / "event-kinds.md"
_NOTE_SRC = REPO / "services" / "note-service" / "src" / "note_service"
_NLP_SRC = REPO / "services" / "nlp-service" / "src" / "nlp_service"


# ── kind registration ───────────────────────────────────────────────


def _doc_or_skip() -> str:
    if not _EVENT_KINDS.exists():
        pytest.skip("docs/audit/event-kinds.md not present")
    doc = _EVENT_KINDS.read_text("utf-8")
    if "report-service" in doc or "report." in doc:
        pytest.skip("event-kinds.md not yet converted to note.* kinds")
    return doc


def test_every_note_service_audit_kind_is_documented() -> None:
    import note_service.audit_kinds as kinds_mod

    doc = _doc_or_skip()
    missing = [
        v
        for k, v in vars(kinds_mod).items()
        if not k.startswith("_") and isinstance(v, str) and "." in v and f"`{v}`" not in doc
    ]
    assert not missing, f"emitted kinds missing from event-kinds.md: {missing}"


def test_the_three_sprint_13_kinds_are_registered() -> None:
    doc = _doc_or_skip()
    for kind in (
        "note.field.extracted",
        "note.field.confirmed",
        "note.field.overridden",
    ):
        assert f"`{kind}`" in doc, kind


# ── metric-label discipline ─────────────────────────────────────────


def _counter_label_keys(path: Path, counter_names: set[str]) -> set[str]:
    """Static label keys passed to `.add(...)` on the named counters."""
    tree = ast.parse(path.read_text("utf-8"))
    # counter variable name → metric name
    var_to_metric: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if getattr(func, "attr", None) == "create_counter" and node.value.args:
                first = node.value.args[0]
                if isinstance(first, ast.Constant) and first.value in counter_names:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            var_to_metric[target.id] = first.value

    keys: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add":
            for arg in node.args[1:]:
                if isinstance(arg, ast.Dict):
                    keys.update(k.value for k in arg.keys if isinstance(k, ast.Constant))
    return keys


def test_quality_counters_label_only_by_field_type() -> None:
    keys = _counter_label_keys(
        _NOTE_SRC / "routers" / "notes_drafts.py",
        {"mdx_field_confirmed_total", "mdx_field_overridden_total"},
    )
    assert keys <= {"field_type"}, f"unexpected metric labels: {keys}"


def test_no_option_value_ever_reaches_a_metric_label() -> None:
    """The rule that keeps the pattern safe for future field types."""
    paths = [_NOTE_SRC / "routers" / "notes_drafts.py"]
    nlp_extraction = _NLP_SRC / "stages" / "field_extraction.py"
    if nlp_extraction.exists():
        paths.append(nlp_extraction)
    for path in paths:
        source = path.read_text("utf-8")
        for forbidden in ('"value"', '"selected"', '"section_key"', '"code"'):
            # These may appear in audit payloads (bounded, offline-analysed)
            # but never inside a metric .add(...) attribute dict.
            for call in re.findall(r"\.add\((.*?)\)\n", source, re.DOTALL):
                assert forbidden not in call, f"{path.name}: {forbidden} in a metric label"
