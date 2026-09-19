"""The markdown-lite layer under the exported PDF.

A generated meeting note arrives as bullets, numbered decisions and
checkbox action items. These assert it lands in the document as real
block structure — and that nothing a note can contain escapes the
escaping.
"""

from __future__ import annotations

import pytest

from note_service.domain.pdf import (
    MAX_SECTION_LENGTH,
    RenderInput,
    _clamp,
    _format_date,
    _humanize,
    _looks_opaque,
    _prepare_sections,
)
from note_service.domain.pdf_richtext import render_rich_text


def test_paragraphs_are_paragraphs() -> None:
    out = render_rich_text("First line\nsoft wrapped.\n\nSecond block.")
    assert out == "<p>First line soft wrapped.</p><p>Second block.</p>"


def test_speaker_turns_are_labelled() -> None:
    out = render_rich_text(
        "Anna: we ship Friday.\n\nTom Client: fine by me.\n\nhttp://x: not a turn"
    )
    assert out == (
        '<p class="turn"><span class="speaker">Anna</span> we ship Friday.</p>'
        '<p class="turn"><span class="speaker">Tom Client</span> fine by me.</p>'
        "<p>http://x: not a turn</p>"
    )


def test_a_long_lead_is_not_a_speaker() -> None:
    out = render_rich_text("One two three four five: not a label")
    assert out == "<p>One two three four five: not a label</p>"


def test_bullets_become_a_list() -> None:
    out = render_rich_text("- one\n- two\n* three")
    assert out == "<ul><li>one</li><li>two</li><li>three</li></ul>"


def test_ordered_list() -> None:
    out = render_rich_text("1. first\n2) second")
    assert out == "<ol><li>first</li><li>second</li></ol>"


def test_checkboxes_get_a_drawn_box() -> None:
    out = render_rich_text("- [ ] open task\n- [x] done task")
    assert 'class="checklist"' in out
    assert '<span class="box"></span>' in out
    assert '<span class="box done"></span>' in out
    assert "[ ]" not in out and "[x]" not in out


def test_inline_emphasis_and_code() -> None:
    out = render_rich_text("**Retention.** it is `flat` and *slipping*")
    assert '<strong class="lead">Retention.</strong>' in out
    assert "<code>flat</code>" in out
    assert "<em>slipping</em>" in out
    assert "**" not in out


def test_headings_never_collide_with_the_document_chrome() -> None:
    """A ``#`` inside a section body must not produce an <h1>/<h2>: those
    belong to the title and the section heading."""
    out = render_rich_text("# Top\n\n## Next\n\n### Deep")
    assert "<h1" not in out and "<h2" not in out
    assert "<h3>Top</h3>" in out
    assert "<h4>Deep</h4>" in out


def test_quote_and_rule() -> None:
    out = render_rich_text("> quoted\n> still quoted\n\n---")
    assert "<blockquote>quoted still quoted</blockquote>" in out
    assert '<hr class="rule" />' in out


def test_pipe_table() -> None:
    out = render_rich_text("| Owner | Due |\n| --- | --- |\n| Data | 15 Sep |")
    assert "<th>Owner</th><th>Due</th>" in out
    assert "<td>Data</td><td>15 Sep</td>" in out
    assert "|" not in out


def test_list_continuation_stays_in_its_item() -> None:
    out = render_rich_text("- first item\n  continued here\n- second")
    assert "<li>first item continued here</li>" in out


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        "**<b onclick='x'>bold</b>**",
        "`</style><script>x</script>`",
    ],
)
def test_html_is_escaped_before_any_markup(hostile: str) -> None:
    out = render_rich_text(hostile)
    assert "<script" not in out
    assert "<img" not in out
    assert "onerror" not in out or "&" in out  # only ever as escaped text
    assert "&lt;" in out


def test_empty_input() -> None:
    assert render_rich_text("") == ""
    assert render_rich_text("   \n\n  ") == ""


# ── the pieces around the renderer ──────────────────────────────────


def test_humanize_section_keys() -> None:
    assert _humanize("action_items") == "Action items"
    assert _humanize("next-steps") == "Next steps"
    assert _humanize("openQuestions") == "Open questions"


def test_opaque_author_is_recognised() -> None:
    assert _looks_opaque("7f3c1e9a-2b4d-4c8e-9a1f-6d5b0e2c7a13")
    assert not _looks_opaque("Dana Okafor")


def test_dates_are_printed_not_dumped() -> None:
    assert _format_date("2026-09-04T14:32:00+00:00", "en") == "4 September 2026, 14:32"
    assert _format_date("2026-09-04T14:32:00+00:00", "de") == "4. September 2026, 14:32"
    assert _format_date("2026-09-04T14:32:00+00:00", "uk") == "4 вересня 2026, 14:32"
    # Unparseable input degrades to the raw string rather than raising.
    assert _format_date("whenever", "en") == "whenever"
    assert _format_date("", "en") == ""


def test_section_bodies_are_not_truncated_at_metadata_length() -> None:
    """Regression: bodies used to be clamped to the 500-char field limit,
    which cut a real meeting note off mid-sentence."""
    body = "word " * 400  # 2000 chars
    payload = RenderInput(
        title="t",
        code="N-1",
        issuer_name="iss",
        primary_author_full_name="",
        co_author_names=[],
        sections=[{"section_key": "summary", "text": body}],
        finalized_at="",
        section_names={"summary": "Summary"},
    )
    (section,) = _prepare_sections(payload)
    assert section["name"] == "Summary"
    assert len(section["html"]) > 1900
    assert "…" not in section["html"]


def test_a_hostile_body_is_still_bounded() -> None:
    payload = RenderInput(
        title="t",
        code="N-1",
        issuer_name="iss",
        primary_author_full_name="",
        co_author_names=[],
        sections=[{"section_key": "summary", "text": "x" * (MAX_SECTION_LENGTH + 10_000)}],
        finalized_at="",
    )
    (section,) = _prepare_sections(payload)
    assert len(section["html"]) < MAX_SECTION_LENGTH + 100
    assert section["html"].endswith("…</p>")


def test_empty_sections_are_dropped() -> None:
    payload = RenderInput(
        title="t",
        code="N-1",
        issuer_name="iss",
        primary_author_full_name="",
        co_author_names=[],
        sections=[
            {"section_key": "summary", "text": "  "},
            {"section_key": "decisions", "text": "kept"},
        ],
        finalized_at="",
    )
    assert [s["name"] for s in _prepare_sections(payload)] == ["Decisions"]


def test_clamp_marks_where_it_cut() -> None:
    assert _clamp("abc", 10) == "abc"
    assert _clamp("abcdef", 3) == "abc…"
    assert _clamp(None) == ""
