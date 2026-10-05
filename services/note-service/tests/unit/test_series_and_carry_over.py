"""Series and carry-over (Sprint 36).

Two things are being pinned here: that "still open from last time" is a
deterministic join and not a guess, and that it can never reach into a
note the author is not allowed to read.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from auth import Claims
from note_models import NoteContent, NoteSection, NoteStatus
from note_service.domain import carry_over
from note_service.domain.meeting_doc import series
from note_service.domain.meeting_doc import types as meeting_types

AUTHOR = UUID("11111111-1111-1111-1111-111111111111")
COLLEAGUE = UUID("44444444-4444-4444-4444-444444444444")
TENANT = UUID("22222222-2222-2222-2222-222222222222")


# ── Which meetings are the same meeting ─────────────────────────────


def test_a_recurring_event_is_one_series() -> None:
    first, source = series.series_key({"ical_uid": "abc@google.com"})
    second, _ = series.series_key({"ical_uid": "ABC@google.com"})
    assert first == second
    assert source == series.CALENDAR_UID


def test_the_calendar_uid_wins_over_the_title() -> None:
    # A renamed meeting, a moved slot and a changed guest list are all
    # the same series when the invite says so.
    with_uid, source = series.series_key(
        {"ical_uid": "abc@google.com", "attendee_names": ["Tom"], "title": "Weekly"}
    )
    renamed, _ = series.series_key(
        {"ical_uid": "abc@google.com", "attendee_names": ["Anna", "Ida"], "title": "Sync"}
    )
    assert with_uid == renamed
    assert source == series.CALENDAR_UID


def test_a_title_and_its_people_are_a_series_when_there_is_no_invite() -> None:
    key, source = series.series_key(
        {"attendee_names": ["Tom", "Anna"]}, title="Acme <> Us — Weekly"
    )
    same, _ = series.series_key({"attendee_names": ["anna", "TOM"]}, title="acme us weekly")
    assert key == same
    assert source == series.TITLE_ATTENDEES


def test_the_same_title_with_different_people_is_a_different_series() -> None:
    """ "Weekly sync" with three different clients is three series."""
    acme, _ = series.series_key({"attendee_names": ["Tom"]}, title="Weekly sync with the client")
    other, _ = series.series_key({"attendee_names": ["Ida"]}, title="Weekly sync with the client")
    assert acme != other


@pytest.mark.parametrize("title", ["Catch-up", "Meeting", "Sync", "Jour fixe", "зустріч"])
def test_a_generic_title_is_not_evidence_of_a_series(title: str) -> None:
    assert series.series_key({"attendee_names": ["Tom"]}, title=title) == (None, None)


def test_a_title_with_nobody_named_is_not_a_series() -> None:
    assert series.series_key({}, title="Acme Weekly") == (None, None)
    assert series.series_key(None, title="Acme Weekly") == (None, None)


def test_the_key_is_a_hash_and_carries_no_content() -> None:
    key, _ = series.series_key({"ical_uid": "acme-renewal-2026@acme.example"})
    assert key is not None
    assert len(key) == 32
    for secret in ("acme", "renewal", "example"):
        assert secret not in key


# ── What gets carried ───────────────────────────────────────────────


def _item(text: str, key: str, status: str = "open", owner: str | None = "Tom") -> SimpleNamespace:
    return SimpleNamespace(
        item_key=key, text=text, owner_label=owner, due_text="the 20th", status=status
    )


def test_only_the_open_items_come_forward() -> None:
    carried = carry_over.carried_from(
        [
            _item("send the brand assets", "k1"),
            _item("sign the contract", "k2", status="done"),
            _item("confirm the budget", "k3"),
            _item("cancel the trial", "k4", status="dropped"),
        ]
    )
    assert [c.item_key for c in carried] == ["k1", "k3"]


def test_the_block_is_capped_so_it_stays_a_reminder() -> None:
    many = [_item(f"task {i}", f"k{i}") for i in range(40)]
    assert len(carry_over.carried_from(many)) == carry_over.MAX_CARRIED


def test_a_carried_item_keeps_the_previous_notes_key() -> None:
    """That key is what keeps the recipient's confirmation on the meeting
    where the task was agreed reachable."""
    carried = carry_over.carried_from([_item("send the assets", "prev-key-1")])
    assert carried[0].item_key == "prev-key-1"


def test_the_block_renders_as_check_items_under_the_meetings_date() -> None:
    block = carry_over.render_block(
        carry_over.carried_from([_item("send the brand assets", "k1")]),
        date(2026, 9, 12),
    )
    assert block.splitlines()[0] == "## Still open from 12 Sep"
    assert block.splitlines()[1] == "- [ ] Tom: send the brand assets — the 20th"


def test_a_done_item_renders_ticked() -> None:
    items = carry_over.apply_states(
        carry_over.carried_from([_item("send the assets", "k1")]),
        {"k1": {"state": carry_over.DONE_MENTIONED, "done_quote": "we sent them Monday"}},
    )
    block = carry_over.render_block(items, date(2026, 9, 12))
    assert "- [x] " in block
    assert items[0].is_done


def test_a_dropped_item_leaves_the_block() -> None:
    items = carry_over.apply_states(
        carry_over.carried_from([_item("send the assets", "k1"), _item("call back", "k2")]),
        {"k1": {"state": carry_over.DROPPED}},
    )
    block = carry_over.render_block(items, date(2026, 9, 12))
    assert "send the assets" not in block
    assert "call back" in block


def test_nothing_open_means_no_block_at_all() -> None:
    assert carry_over.render_block([], date(2026, 9, 12)) == ""
    everything_done = carry_over.apply_states(
        carry_over.carried_from([_item("send the assets", "k1")]),
        {"k1": {"state": carry_over.DROPPED}},
    )
    assert carry_over.render_block(everything_done, date(2026, 9, 12)) == ""


def test_the_heading_follows_the_meetings_language() -> None:
    assert carry_over.heading(date(2026, 9, 12), language="de").startswith("Noch offen")
    assert carry_over.heading(date(2026, 9, 12), language="uk").startswith("Ще відкрито")
    # A language we have no wording for reads in English rather than
    # showing the author a format placeholder.
    assert carry_over.heading(date(2026, 9, 12), language="pl").startswith("Still open")


# ── The visibility rule (ADR-0057) ──────────────────────────────────


def _claims(sub: UUID = AUTHOR) -> Claims:
    return Claims(
        sub=sub,
        tid=TENANT,
        roles=["member"],
        sid="s",
        iss="i",
        aud="mdx",
        exp=9_999_999_999,
        iat=1,
    )


def _note(visibility: str, author: UUID, shared: list[UUID] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=TENANT,
        status=NoteStatus.DRAFT,
        primary_author_id=author,
        co_author_ids=[],
        shared_with_ids=shared or [],
        visibility=visibility,
        deleted_at=None,
    )


def test_a_colleagues_private_note_is_never_carried_from() -> None:
    """RLS scopes to the TENANT, and a colleague's private 1:1 is inside
    my tenant — so the tenant boundary is not the boundary here."""
    from note_service.domain import access

    theirs = _note("private", COLLEAGUE)
    assert not access.can_view(theirs, _claims())
    mine = _note("private", AUTHOR)
    assert access.can_view(mine, _claims())
    shared_with_me = _note("private", COLLEAGUE, shared=[AUTHOR])
    assert access.can_view(shared_with_me, _claims())
    workspace = _note("workspace", COLLEAGUE)
    assert access.can_view(workspace, _claims())


# ── The block lands in the right place ──────────────────────────────


def test_the_block_goes_above_this_meetings_own_actions() -> None:
    from note_service.domain.series_service import _with_block

    content = NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        sections=[
            NoteSection(section_key="discussion", text="talked"),
            NoteSection(section_key="action_items", text="- Anna: send the deck"),
        ],
    )
    out = _with_block(content, "## Still open from 12 Sep\n- [ ] Tom: send the assets")
    actions = next(s for s in out.sections if s.section_key == "action_items")
    assert actions.text.startswith("## Still open")
    # What was already owed, then what was just agreed.
    assert actions.text.index("Still open") < actions.text.index("Anna: send the deck")
    assert "- Anna: send the deck" in actions.text


def test_a_template_without_an_actions_section_is_left_alone() -> None:
    from note_service.domain.series_service import _with_block

    content = NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        sections=[NoteSection(section_key="summary", text="talked")],
    )
    assert _with_block(content, "## Still open") == content


# ── The client-call family ──────────────────────────────────────────


def test_the_client_call_family_exists_and_may_be_shared() -> None:
    family = meeting_types.family_for_template("client_call_de")
    assert family.meeting_type == "client"
    assert meeting_types.supports_client_version(family)
    # The two things a generic template has nowhere to put.
    kinds = meeting_types.fact_kinds(family)
    assert kinds["client_request"] == meeting_types.REQUESTS
    assert kinds["commitment_ours"] == meeting_types.ACTION_ITEMS
    assert kinds["commitment_theirs"] == meeting_types.ACTION_ITEMS


def test_what_a_buyer_objected_to_is_ours_not_theirs() -> None:
    sales = meeting_types.family_for_template("sales_call")
    assert meeting_types.is_internal_kind(sales, "objection")
    assert meeting_types.is_internal_kind(sales, "competitor_mention")
    assert meeting_types.is_internal_kind(sales, "budget_timeline")
    assert not meeting_types.is_internal_kind(sales, "decision")


def test_the_scratchpad_is_internal_in_every_family() -> None:
    for family in meeting_types.FAMILIES:
        assert meeting_types.is_internal_kind(family, "user_point")
        assert meeting_types.is_internal_kind(family, "judgement")


def test_a_longer_family_prefix_wins() -> None:
    assert meeting_types.family_for_template("client_call_uk").meeting_type == "client"
    assert meeting_types.family_for_template("one_on_one_de").meeting_type == "one_on_one"
    assert meeting_types.family_for_template(None).meeting_type == "auto"
