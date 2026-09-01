"""Typed finalize completeness (sprint 13, step 06).

Typed sections measure "filled" in ``field_specific_metadata``, not in
prose — each field type has its own rule.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from note_models import NoteContent, NoteSection
from note_service.domain.field_audit import diff_field_events
from note_service.domain.finalize_validator import validate_finalize
from template_models import ChoiceOption, FieldType, TemplateDefinition, TemplateSection


def _tpl(*sections: TemplateSection) -> TemplateDefinition:
    return TemplateDefinition(
        code="sales_call",
        name="Дзвінок із клієнтом",
        language="uk",
        category="sales",
        sections=sections,
    )


def _choice_section(required: bool = True) -> TemplateSection:
    return TemplateSection(
        id="deal_stage",
        name="Етап угоди",
        voice_aliases=("етап угоди",),
        required=required,
        field_type=FieldType.CHOICE,
        asr_prompt="етап угоди",
        options=(
            ChoiceOption(value="lead", label="Лід"),
            ChoiceOption(value="negotiation", label="Переговори"),
        ),
    )


def _numeric_section() -> TemplateSection:
    return TemplateSection(
        id="deal_value",
        name="Сума угоди",
        voice_aliases=("сума угоди",),
        field_type=FieldType.NUMERIC_WITH_UNIT,
        asr_prompt="сума угоди",
    )


def _date_section(field_type: FieldType = FieldType.DATE, min_chars: int = 0) -> TemplateSection:
    return TemplateSection(
        id="follow_up",
        name="Наступний контакт",
        voice_aliases=("наступний контакт",),
        field_type=field_type,
        asr_prompt="наступний контакт",
        min_chars=min_chars,
    )


def _content(*sections: NoteSection) -> NoteContent:
    return NoteContent(template_id=uuid4(), template_schema_version=1, sections=list(sections))


def _section(key: str, *, text: str = "", meta: dict[str, Any] | None = None) -> NoteSection:
    return NoteSection(
        section_key=key,
        text=text,
        field_specific_metadata=meta or {},
    )


def _codes(problems: list[Any]) -> list[str]:
    return [p.code for p in problems]


# ── the VERIFY trio ─────────────────────────────────────────────────


def test_required_choice_without_selection_blocks() -> None:
    problems = validate_finalize(
        content=_content(_section("deal_stage")),
        template=_tpl(_choice_section()),
    )
    assert _codes(problems) == ["choice_not_selected"]
    assert problems[0].section_key == "deal_stage"
    assert problems[0].reason == "choice_not_selected"


# ── the filled matrix ───────────────────────────────────────────────


@pytest.mark.parametrize("source", ["extracted", "manual"])
def test_choice_filled_by_either_source(source: str) -> None:
    meta: dict[str, Any] = {"selected": "lead", "source": source}
    if source == "extracted":
        meta["confidence"] = 0.9
    problems = validate_finalize(
        content=_content(_section("deal_stage", meta=meta)),
        template=_tpl(_choice_section()),
    )
    assert problems == []


def test_multi_choice_empty_selection_blocks() -> None:
    section = _choice_section()
    multi = section.model_copy(update={"field_type": FieldType.MULTI_CHOICE})
    problems = validate_finalize(
        content=_content(_section("deal_stage", meta={})),
        template=_tpl(multi),
    )
    assert _codes(problems) == ["choice_not_selected"]


def test_optional_typed_section_never_blocks() -> None:
    problems = validate_finalize(
        content=_content(_section("deal_stage")),
        template=_tpl(_choice_section(required=False)),
    )
    assert problems == []


def test_numeric_requires_both_value_and_unit() -> None:
    tpl = _tpl(_numeric_section())
    filled = _content(
        _section("deal_value", meta={"value": 25000.0, "unit": "USD", "source": "manual"})
    )
    assert validate_finalize(content=filled, template=tpl) == []

    no_unit = _content(_section("deal_value", meta={"value": 25000.0, "source": "manual"}))
    assert _codes(validate_finalize(content=no_unit, template=tpl)) == ["numeric_not_filled"]

    empty = _content(_section("deal_value"))
    assert _codes(validate_finalize(content=empty, template=tpl)) == ["numeric_not_filled"]


def test_date_requires_a_date() -> None:
    tpl = _tpl(_date_section())
    filled = _content(_section("follow_up", meta={"date": "2026-07-01", "source": "manual"}))
    assert validate_finalize(content=filled, template=tpl) == []
    assert _codes(validate_finalize(content=_content(_section("follow_up")), template=tpl)) == [
        "date_not_filled"
    ]


def test_date_with_note_also_applies_min_chars_to_the_prose() -> None:
    """The note IS content, so min_chars still governs it."""
    tpl = _tpl(_date_section(FieldType.DATE_WITH_NOTE, min_chars=10))
    short = _content(
        _section("follow_up", text="коротко", meta={"date": "2026-07-01", "source": "manual"})
    )
    assert "below_min_chars" in _codes(validate_finalize(content=short, template=tpl))
    ok = _content(
        _section(
            "follow_up",
            text="передзвонити наступного тижня після демо",
            meta={"date": "2026-07-01", "source": "manual"},
        )
    )
    assert validate_finalize(content=ok, template=tpl) == []


def test_free_text_sections_keep_sprint_08_behaviour() -> None:
    free = TemplateSection(
        id="summary",
        name="Підсумок",
        voice_aliases=("підсумок",),
        required=True,
        asr_prompt="підсумок",
        min_chars=20,
    )
    short = _content(_section("summary", text="мало"))
    assert _codes(validate_finalize(content=short, template=_tpl(free))) == ["below_min_chars"]
    missing = _content()
    assert _codes(validate_finalize(content=missing, template=_tpl(free))) == [
        "missing_required_section"
    ]


def test_typed_sections_never_emit_min_chars_or_required_empty() -> None:
    """A choice section has no prose, so the prose codes must not fire."""
    codes = _codes(
        validate_finalize(
            content=_content(_section("deal_stage")),
            template=_tpl(_choice_section()),
        )
    )
    assert "missing_required_section" not in codes
    assert "below_min_chars" not in codes


# ── audit signals: the content line ─────────────────────────────────


def _tpl_types() -> dict[str, str]:
    return {
        "deal_stage": "choice",
        "summary": "free_text",
    }


def test_confirming_an_extracted_choice_emits_confirmed() -> None:
    before = _content(
        _section("deal_stage", meta={"selected": "lead", "confidence": 0.9, "source": "extracted"})
    )
    after = _content(_section("deal_stage", meta={"selected": "lead", "source": "manual"}))
    events = diff_field_events(before=before, after=after, field_types=_tpl_types())
    assert [e.kind for e in events] == ["confirmed"]
    assert events[0].payload["selected"] == ["lead"]


def test_changing_an_extracted_choice_emits_overridden() -> None:
    before = _content(
        _section("deal_stage", meta={"selected": "lead", "confidence": 0.9, "source": "extracted"})
    )
    after = _content(_section("deal_stage", meta={"selected": "negotiation", "source": "manual"}))
    events = diff_field_events(before=before, after=after, field_types=_tpl_types())
    assert [e.kind for e in events] == ["overridden"]
    assert events[0].payload["selected"] == ["negotiation"]
    assert events[0].payload["was"] == ["lead"]


def test_free_text_override_carries_no_text() -> None:
    """THE CONTENT LINE: never record what prose an author wrote."""
    before = _content(
        _section(
            "summary",
            text="старий текст",
            meta={"selected": "x", "confidence": 0.9, "source": "extracted"},
        )
    )
    after = _content(
        _section(
            "summary",
            text="новий текст з приватними даними",
            meta={"selected": "y", "source": "manual"},
        )
    )
    events = diff_field_events(before=before, after=after, field_types=_tpl_types())
    for event in events:
        serialized = repr(event.payload)
        assert "текст" not in serialized, event.payload
        assert "приватними" not in serialized
        assert "selected" not in event.payload, "free_text is not a closed vocabulary"


def test_no_change_emits_nothing() -> None:
    content = _content(_section("deal_stage", meta={"selected": "lead", "source": "manual"}))
    assert diff_field_events(before=content, after=content, field_types=_tpl_types()) == []


def test_purely_extracted_write_emits_nothing() -> None:
    """The extractor filling a field is not an author action."""
    after = _content(
        _section("deal_stage", meta={"selected": "lead", "confidence": 0.9, "source": "extracted"})
    )
    assert diff_field_events(before=None, after=after, field_types=_tpl_types()) == []
