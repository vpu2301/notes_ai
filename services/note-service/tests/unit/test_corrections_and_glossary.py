"""Sprint 35: the line splitter, the glossary rules, and the boundary the
shared page must never cross.

The router-level correction tests live in ``test_notes_corrections.py``;
everything here is pure or is a schema assertion.
"""

from __future__ import annotations

import pytest

from note_service.domain import glossary as rules
from note_service.domain import lines

# ── The shared line model ───────────────────────────────────────────

SECTION = "- Anna: send the pricing proposal — by Tuesday\n\n- Tom: book the room\n1. Ship it"


def test_a_section_splits_into_lines_with_their_markers() -> None:
    out = lines.split_section(SECTION)
    assert [line.marker for line in out] == ["- ", "- ", "1. "]
    assert out[0].content == "Anna: send the pricing proposal — by Tuesday"
    assert [line.index for line in out] == [0, 1, 2]


def test_blank_lines_and_bare_markers_are_not_lines() -> None:
    assert lines.split_section("\n\n  \n-\n2.\n") == []


def test_the_key_ignores_the_owner_and_the_due_date() -> None:
    # This is the whole architecture decision: a correction changes who
    # owns a line and when it is due WITHOUT detaching its history.
    original = lines.key_of("Anna: send the pricing proposal — by Tuesday")
    assert original == lines.key_of("Tom: send the pricing proposal — by Friday")
    assert original == lines.key_of("send the pricing proposal")


def test_the_key_changes_when_the_body_changes() -> None:
    # Also correct: the line now says something else, so it is the
    # author's statement and no longer the one the evidence was for.
    assert lines.key_of("Anna: send the pricing proposal") != lines.key_of(
        "Anna: send the contract"
    )


def test_the_key_survives_bullets_case_and_spacing() -> None:
    assert lines.key_of("Send  the   deck.") == lines.key_of("send the deck")


def test_a_line_is_found_by_its_key_wherever_it_moved() -> None:
    key = lines.split_section(SECTION)[1].key
    moved = "Some other text\n\n- Tom: book the room"
    assert lines.find(moved, key) is not None


def test_render_puts_the_grammar_back_and_leaves_the_body_alone() -> None:
    rendered = lines.render_item(
        marker="- ", owner="Tom", body="send the pricing proposal", due_text="Friday"
    )
    assert rendered == "- Tom: send the pricing proposal — Friday"
    # And it round-trips to the same key.
    assert lines.key_of(lines.strip_marker(rendered)[1]) == lines.key_of(
        "Anna: send the pricing proposal — by Tuesday"
    )


def test_replacing_a_line_leaves_every_other_byte_alone() -> None:
    key = lines.split_section(SECTION)[1].key
    out = lines.replace_line(SECTION, key, "- Ida: book the room")
    assert out is not None
    assert out.splitlines()[0] == "- Anna: send the pricing proposal — by Tuesday"
    assert out.splitlines()[1] == ""  # the blank line is structure, kept
    assert "- Ida: book the room" in out


def test_removing_a_line_does_not_leave_a_hole() -> None:
    key = lines.split_section(SECTION)[0].key
    out = lines.replace_line(SECTION, key, None)
    assert out == "- Tom: book the room\n1. Ship it"


def test_an_unknown_key_is_reported_rather_than_silently_ignored() -> None:
    assert lines.replace_line(SECTION, "0000000000000000", None) is None


def test_parts_split_owner_body_and_due() -> None:
    parts = lines.parts("Anna: send the pricing proposal — by Tuesday")
    assert parts.owner == "Anna"
    assert parts.body == "send the pricing proposal"
    assert parts.due_text == "Tuesday"


# ── Glossary rules ──────────────────────────────────────────────────


def test_a_term_is_normalised_not_mangled() -> None:
    assert rules.clean_term("  John   Mayer ") == "John Mayer"


@pytest.mark.parametrize("bad", ["a", "x" * 81, "  "])
def test_terms_outside_the_size_rules_are_refused(bad: str) -> None:
    with pytest.raises(rules.GlossaryError):
        rules.clean_term(bad)


@pytest.mark.parametrize("bad", ["John‮Mayer", "John\u0000", "Jo​hn Mayer"])
def test_control_and_bidi_characters_are_refused_not_stripped(bad: str) -> None:
    # A term is shown in three clients and injected into a prompt. One
    # that needed stripping is not the term the person typed.
    with pytest.raises(rules.GlossaryError):
        rules.clean_term(bad)


def test_heard_as_is_deduplicated_capped_and_never_the_term_itself() -> None:
    out = rules.clean_heard_as(
        ["Jon Meyer", "jon meyer", "John Mayer", *[f"Variant {i}" for i in range(12)]],
        term="John Mayer",
    )
    assert out[0] == "Jon Meyer"
    assert "John Mayer" not in out
    assert len(out) == rules.MAX_HEARD_AS


def test_one_bad_variant_does_not_cost_the_good_ones() -> None:
    assert rules.clean_heard_as(["Jon\u0000", "Jon Meyer"], term="John Mayer") == ["Jon Meyer"]


def _terms() -> list[rules.Term]:
    return [
        rules.Term("John Mayer", "person", ("Jon Meyer", "John Meyer")),
        rules.Term("Contoso", "company", ("Con Tozo",)),
        rules.Term("Klarnote", "product", ()),
    ]


def test_the_hint_is_only_the_right_spellings() -> None:
    hint = rules.hint_text(_terms())
    assert hint == "John Mayer, Contoso, Klarnote"
    # Teaching the transcriber the WRONG spellings would do the opposite
    # of what the hint is for.
    assert "Jon Meyer" not in hint


def test_the_hint_is_truncated_at_a_term_boundary() -> None:
    hint = rules.hint_text(_terms(), limit=20)
    assert hint == "John Mayer, Contoso"
    assert not hint.endswith(",")


def test_an_owner_that_is_a_known_mishearing_is_canonicalised() -> None:
    assert rules.canonical_owner("Jon Meyer", _terms()) == "John Mayer"
    assert rules.canonical_owner("  john mayer ", _terms()) == "John Mayer"


def test_a_partial_match_is_a_different_person_not_a_mishearing() -> None:
    assert rules.canonical_owner("Jonathan Pryce", _terms()) == "Jonathan Pryce"


def test_only_people_canonicalise_owners() -> None:
    assert rules.canonical_owner("Con Tozo", _terms()) == "Con Tozo"


def test_the_prompt_carries_only_the_terms_that_were_spoken() -> None:
    window = "so con tozo wants the klarnote rollout by March"
    found = rules.terms_in(window, _terms())
    assert [t.term for t in found] == ["Contoso", "Klarnote"]


def test_the_prompt_block_is_data_and_names_its_spellings() -> None:
    block = rules.prompt_block(_terms()[:1])
    assert block.startswith("Known names and terms (spell exactly):")
    assert "- John Mayer (heard as: Jon Meyer, John Meyer)" in block
    assert rules.prompt_block([]) == ""


# ── The boundary: the shared page never shows evidence ──────────────


def test_the_shared_page_has_no_quote_timestamp_or_speaker_field() -> None:
    """Evidence is transcript. The recipient page's rule is that it shows
    the note and nothing under it — no transcript, no audio, no speakers.
    This is that rule as a test, so a future field cannot cross it by
    accident."""
    from note_service.routers.shared_public import (
        SharedItem,
        SharedNoteView,
        SharedSection,
    )

    forbidden = {
        "quote",
        "quotes",
        "evidence",
        "start_ms",
        "end_ms",
        "speaker",
        "speaker_label",
        "speaker_name",
        "turn_hint",
        "transcript",
        "audio",
        "clip_id",
        "flags",
        "origin",
        "confidence",
    }
    for model in (SharedNoteView, SharedSection, SharedItem):
        leaked = forbidden & set(model.model_fields)
        assert not leaked, f"{model.__name__} would expose {sorted(leaked)} to a recipient"
