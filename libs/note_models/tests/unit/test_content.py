"""Pydantic validation tests for the NoteContent shape."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from note_models import (
    NoteContent,
    NoteSection,
    canonical_content_bytes,
    rendered_text_from_content,
)


def _minimal_content() -> NoteContent:
    return NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        title="Weekly sync — platform team",
        sections=[
            NoteSection(section_key="agenda", text="Q3 roadmap review"),
            NoteSection(section_key="decisions", text="ship the beta on Friday"),
        ],
    )


def test_minimal_content_roundtrips() -> None:
    c = _minimal_content()
    obj = c.model_dump(mode="json")
    c2 = NoteContent.model_validate(obj)
    assert c == c2


def test_section_keys_must_be_unique() -> None:
    with pytest.raises(ValidationError):
        NoteContent(
            template_id=uuid4(),
            template_schema_version=1,
            sections=[
                NoteSection(section_key="x", text="a"),
                NoteSection(section_key="x", text="b"),
            ],
        )


def test_extra_keys_rejected() -> None:
    obj = {
        "template_id": str(uuid4()),
        "template_schema_version": 1,
        "title": "",
        "sections": [],
        "unknown_key": "explode",
    }
    with pytest.raises(ValidationError):
        NoteContent.model_validate(obj)


def test_canonical_bytes_are_deterministic() -> None:
    c = _minimal_content()
    a = canonical_content_bytes(c)
    b = canonical_content_bytes(c)
    assert a == b
    # Key order in source JSON must not change canonical output.
    raw1 = c.model_dump(mode="json")
    shuffled = {k: raw1[k] for k in sorted(raw1.keys(), reverse=True)}
    c2 = NoteContent.model_validate(shuffled)
    assert canonical_content_bytes(c2) == a


def test_canonical_bytes_change_with_content() -> None:
    c1 = _minimal_content()
    c2 = NoteContent.model_validate(json.loads(canonical_content_bytes(c1)))
    c2.sections[0].text = "different"
    assert canonical_content_bytes(c2) != canonical_content_bytes(c1)


def test_rendered_text_concatenates_sections_with_section_keys() -> None:
    c = _minimal_content()
    rt = rendered_text_from_content(c)
    assert "Weekly sync — platform team" in rt
    assert "agenda" in rt
    assert "Q3 roadmap review" in rt
    assert "decisions" in rt
    assert "ship the beta on Friday" in rt


def test_rendered_text_skips_empty_sections() -> None:
    c = NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        title="t",
        sections=[
            NoteSection(section_key="empty", text=""),
            NoteSection(section_key="present", text="content"),
        ],
    )
    rt = rendered_text_from_content(c)
    assert "empty" not in rt
    assert "present" in rt


def test_a_section_title_is_optional_and_round_trips() -> None:
    content = NoteContent.model_validate(
        {
            "template_id": "70cd91de-82b0-48e5-81ce-dcc01e0a2297",
            "template_schema_version": 1,
            "sections": [
                {"section_key": "gen:overview", "text": "An interview about the club."},
                {"section_key": "gen:transfers", "title": "Transfer strategy", "text": "- one"},
            ],
        }
    )
    assert content.sections[0].title is None
    assert content.sections[1].title == "Transfer strategy"
    assert NoteContent.model_validate(content.model_dump(mode="json")) == content


def test_canonical_bytes_carry_a_title_only_when_there_is_one() -> None:
    from note_models import canonical_content_bytes

    base = {
        "template_id": "70cd91de-82b0-48e5-81ce-dcc01e0a2297",
        "template_schema_version": 1,
        "sections": [{"section_key": "notes", "text": "x"}],
    }
    without = canonical_content_bytes(NoteContent.model_validate(base))
    sections = without.split(b'"sections":')[1].split(b'],')[0]
    assert b"title" not in sections
    titled = dict(base, sections=[{"section_key": "gen:a", "title": "A", "text": "x"}])
    assert b'"title":"A"' in canonical_content_bytes(NoteContent.model_validate(titled))


def test_rendered_text_prefers_the_title_over_the_key() -> None:
    content = NoteContent.model_validate(
        {
            "template_id": "70cd91de-82b0-48e5-81ce-dcc01e0a2297",
            "template_schema_version": 1,
            "sections": [{"section_key": "gen:transfers", "title": "Transfer strategy", "text": "- one"}],
        }
    )
    assert rendered_text_from_content(content) == "Transfer strategy\n- one"
