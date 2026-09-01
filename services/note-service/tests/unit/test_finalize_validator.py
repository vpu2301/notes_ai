"""Finalize validator coverage."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from note_models import NoteContent, NoteSection
from note_service.domain.finalize_validator import validate_finalize


def _template(sections):
    return SimpleNamespace(sections=[SimpleNamespace(**s) for s in sections])


def _content(sections=()):
    return NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        sections=[NoteSection(section_key=k, text=t) for (k, t) in sections],
    )


def test_missing_required_section_flagged():
    tpl = _template([{"key": "agenda", "required": True, "min_chars": 0}])
    c = _content()
    problems = validate_finalize(content=c, template=tpl)
    assert any(p.code == "missing_required_section" for p in problems)


def test_below_min_chars_flagged():
    tpl = _template([{"key": "agenda", "required": True, "min_chars": 20}])
    c = _content(sections=[("agenda", "short")])
    problems = validate_finalize(content=c, template=tpl)
    assert any(p.code == "below_min_chars" for p in problems)


def test_required_section_with_content_passes():
    tpl = _template([{"key": "agenda", "required": True, "min_chars": 0}])
    c = _content(sections=[("agenda", "roadmap review and hiring plan")])
    assert validate_finalize(content=c, template=tpl) == []


def test_optional_section_empty_not_flagged():
    tpl = _template([{"key": "agenda", "required": False, "min_chars": 0}])
    c = _content()
    assert validate_finalize(content=c, template=tpl) == []


def test_problem_reason_normalised():
    tpl = _template([{"key": "agenda", "required": True, "min_chars": 0}])
    c = _content()
    problem = next(
        p
        for p in validate_finalize(content=c, template=tpl)
        if p.code == "missing_required_section"
    )
    assert problem.reason == "required_empty"
    assert problem.section_key == "agenda"
