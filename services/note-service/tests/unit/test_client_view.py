"""The client version: what may leave the workspace, and what may not.

These are disclosure tests. They exist because the shared page and the
PDF used to render whatever sections a note had — which, once Sprint 34
gave every template a `user_notes` section, meant the author's private
in-meeting scratchpad went to recipients.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from note_models import NoteContent, NoteSection
from note_service.domain import client_view, lines
from note_service.domain.meeting_doc import types

TRANSCRIPT = "Tom: we can send the assets Monday.\n\nAnna: perfect.\n\nTom: agreed."


def _content(**sections: str) -> NoteContent:
    return NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        title="Acme weekly",
        sections=[NoteSection(section_key=k, text=v) for k, v in sections.items()],
    )


def _client(content: NoteContent, template: str = "client_call") -> client_view.ClientDocument:
    return client_view.build(content, family=types.family_for_template(template))


def _text(doc: client_view.ClientDocument) -> str:
    return "\n".join(s.text for s in doc.sections)


# ── The things that must never get out ──────────────────────────────


def test_the_authors_scratchpad_never_reaches_a_client() -> None:
    doc = _client(
        _content(
            user_notes="ask about budget\nTom is stalling",
            decisions="- Ship on the 20th",
        )
    )
    assert "budget" not in _text(doc)
    assert "stalling" not in _text(doc)
    assert [s.section_key for s in doc.sections] == ["decisions"]
    assert "user_notes" in doc.hidden_sections


def test_the_transcript_never_reaches_a_client() -> None:
    doc = _client(_content(transcript=TRANSCRIPT, decisions="- Ship on the 20th"))
    assert "we can send the assets" not in _text(doc)


def test_a_transcript_hiding_in_a_prose_section_is_still_a_transcript() -> None:
    """`from-transcript` drops the whole recording into the first prose
    section — usually `discussion`. Trusting section KEYS alone would hand
    a recipient the entire meeting under a friendly heading."""
    doc = _client(_content(discussion=TRANSCRIPT))
    assert doc.is_empty
    assert "discussion" in doc.hidden_sections


def test_real_discussion_prose_still_reaches_the_client() -> None:
    # The rule is "no transcript", not "no discussion" — dropping the
    # section wholesale would gut every note people share today.
    doc = _client(_content(discussion="We agreed the rollout needs two more weeks."))
    assert "two more weeks" in _text(doc)


def test_a_line_marked_internal_is_dropped_and_its_mark_never_renders() -> None:
    doc = _client(_content(action_items="- (internal) push them on price\n- Anna: send the deck"))
    assert "push them on price" not in _text(doc)
    assert "internal" not in _text(doc).lower()
    assert "Anna: send the deck" in _text(doc)
    assert doc.hidden_lines == 1


@pytest.mark.parametrize("mark", ["(internal)", "(Intern)", "[internal]", "(внутрішнє)"])
def test_the_mark_is_recognised_in_the_languages_people_type_in(mark: str) -> None:
    doc = _client(_content(decisions=f"- {mark} our floor is 40k\n- Ship on the 20th"))
    assert "40k" not in _text(doc)
    assert "Ship on the 20th" in _text(doc)


def test_a_section_whose_every_line_is_internal_disappears() -> None:
    doc = _client(_content(decisions="- (internal) our floor is 40k"))
    assert doc.is_empty
    assert "decisions" in doc.hidden_sections


def test_a_role_nobody_listed_is_internal_by_omission() -> None:
    # A template we have never seen cannot smuggle a section out by
    # naming it something new: the role list is an allow-list.
    doc = _client(_content(objections="- too expensive", decisions="- Ship it"))
    assert "too expensive" not in _text(doc)
    doc = _client(_content(some_future_section="secret", decisions="- Ship it"))
    assert "secret" not in _text(doc)


# ── Families with no client ─────────────────────────────────────────


@pytest.mark.parametrize("template", ["one_on_one", "one_on_one_de", "interview_debrief_uk"])
def test_a_one_to_one_and_an_interview_have_no_client_version(template: str) -> None:
    """Building one would be building a way to send a colleague's
    performance conversation, or a candidate's assessment, outside the
    workspace."""
    doc = _client(_content(decisions="- Promote in Q1", summary="Good year"), template)
    assert doc.is_empty


def test_those_families_are_private_by_default() -> None:
    for template in ("one_on_one", "interview_debrief"):
        assert types.family_for_template(template).default_visibility == "private"
    assert types.family_for_template("client_call").default_visibility == "workspace"


# ── Shape ───────────────────────────────────────────────────────────


def test_sections_come_out_in_the_order_a_client_reads_them() -> None:
    doc = _client(
        _content(
            action_items="- Anna: send the deck",
            summary="We agreed the scope.",
            next_meeting="- 3 October",
            decisions="- Ship on the 20th",
            attendees="Anna, Tom",
        )
    )
    assert [s.role for s in doc.sections] == [
        types.SUMMARY,
        types.ATTENDEES,
        types.DECISIONS,
        types.ACTION_ITEMS,
        types.NEXT_MEETING,
    ]


def test_an_unknown_template_falls_back_safely() -> None:
    # A failed family lookup must still exclude the scratchpad: the
    # safety property cannot depend on resolving the family.
    doc = client_view.build(
        _content(user_notes="ask about budget", decisions="- Ship it"),
        family=types.family_for_template(None),
    )
    assert "budget" not in _text(doc)
    assert "Ship it" in _text(doc)


def test_blank_lines_between_kept_lines_survive() -> None:
    text, dropped = client_view.public_text("- one\n\n- two")
    assert text == "- one\n\n- two"
    assert dropped == 0


def test_marking_a_line_internal_does_not_change_its_identity() -> None:
    """The toggle has to be safe to use: a line's evidence, its recipient
    responses and its correction history all hang off its key."""
    plain = "- Anna: send the deck"
    marked = lines.mark_internal(plain, internal=True)
    assert lines.split_section(marked)[0].key == lines.split_section(plain)[0].key
    assert lines.mark_internal(marked, internal=False) == plain


# ── Sprint 36: internal by KIND, not only by the author's mark ──────


def test_a_line_the_engine_marked_internal_never_reaches_a_client() -> None:
    """The author should not have to notice that an "objection" is not
    something to send the person who raised it."""
    from note_service.domain import lines

    content = _content(
        decisions="- Ship on the 20th",
        objections="- the price is too high",
        action_items="- Anna: send the deck\n- push them on price",
    )
    internal = frozenset({lines.key_of("push them on price")})
    doc = client_view.build(
        content, family=types.family_for_template("sales_call"), internal_keys=internal
    )
    text = _text(doc)
    assert "push them on price" not in text
    assert "Anna: send the deck" in text
    assert doc.hidden_lines == 1


def test_an_engine_marked_line_counts_as_hidden_like_a_typed_mark() -> None:
    from note_service.domain import lines

    content = _content(decisions="- our floor is 40k")
    doc = client_view.build(
        content,
        family=types.family_for_template("client_call"),
        internal_keys=frozenset({lines.key_of("our floor is 40k")}),
    )
    assert doc.is_empty
    assert "decisions" in doc.hidden_sections


def test_what_a_buyer_objected_to_is_internal_in_a_sales_call() -> None:
    sales = types.family_for_template("sales_call")
    for kind in ("objection", "competitor_mention", "budget_timeline"):
        assert types.is_internal_kind(sales, kind)
    # …but what was DECIDED is not.
    assert not types.is_internal_kind(sales, "decision")


def test_a_judgement_is_internal_in_every_family() -> None:
    for family in types.FAMILIES:
        assert types.is_internal_kind(family, "judgement")
