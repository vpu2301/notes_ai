"""Rendering is the content boundary; these assert the negative for the in-app path
the PII CI gate (email templates only) cannot cover.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from notification_events import Category, NotificationEvent
from notification_service.domain.render import (
    ALLOWED_PAYLOAD_KEYS,
    deep_link,
    render_body,
    render_title,
    safe_payload,
)

TENANT = uuid4()
SESSION = uuid4()
USER = uuid4()


def _dictation_event(**payload: object) -> NotificationEvent:
    return NotificationEvent(
        event_id=uuid4(),
        tenant_id=TENANT,
        category=Category.DICTATION_COMPLETED,
        actor_user_id=USER,
        resource_type="dictation_session",
        resource_id=SESSION,
        occurred_at=datetime.now(UTC),
        recipient_hints=(USER,),
        payload=payload,  # type: ignore[arg-type]
    )


def test_transcript_text_never_survives_into_a_rendered_row() -> None:
    """A producer that adds transcript text finds it silently dropped (allow-list, not scrubber)."""
    event = _dictation_event(
        duration_ms=42_000,
        segments=7,
        transcript="Acquisition of Ivanenko Ltd closes March 3rd, offer 2.1M",
        author_name="Ivanenko",
    )

    fields = safe_payload(event)

    assert fields == {"duration_ms": "42000", "segments": "7"}
    for leak in ("Ivanenko", "Acquisition", "2.1M"):
        assert leak not in render_title(event)
        assert leak not in render_body(event)
        assert leak not in str(fields)


def test_dictation_payload_allow_list_is_counts_only() -> None:
    assert ALLOWED_PAYLOAD_KEYS[Category.DICTATION_COMPLETED] == frozenset(
        {"duration_ms", "segments"}
    )


def test_dictation_deep_link_points_at_the_session() -> None:
    event = _dictation_event(duration_ms=1_000, segments=1)
    assert deep_link(event, base_url="https://app.example/") == (
        f"https://app.example/dictations/{SESSION}?ws={TENANT}"
    )


def test_transcription_failure_never_renders_the_error_detail() -> None:
    """`error_kind` is a closed vocabulary; `error_detail` is free text that may quote the transcript."""
    event = NotificationEvent(
        event_id=uuid4(),
        tenant_id=TENANT,
        category=Category.TRANSCRIPTION_FAILED,
        actor_user_id=USER,
        resource_type="transcription_job",
        resource_id=SESSION,
        occurred_at=datetime.now(UTC),
        recipient_hints=(USER,),
        payload={
            "error_kind": "corrupt_audio",
            "error_detail": "failed decoding ivanenko_1978-04-12.wav",
        },
    )

    assert safe_payload(event) == {"error_kind": "corrupt_audio"}
    assert "ivanenko" not in render_body(event)
    assert "1978-04-12" not in render_body(event)
    assert "corrupt_audio" in render_body(event)


def test_transcription_completion_never_renders_a_filename() -> None:
    """An upload named after a person is the obvious leak here."""
    event = NotificationEvent(
        event_id=uuid4(),
        tenant_id=TENANT,
        category=Category.TRANSCRIPTION_COMPLETED,
        actor_user_id=USER,
        resource_type="transcription_job",
        resource_id=SESSION,
        occurred_at=datetime.now(UTC),
        recipient_hints=(USER,),
        payload={
            "segments": 12,
            "duration_ms": 90_000,
            "language": "en",
            "model": "large-v3",
            "filename": "ivanenko_1978-04-12.wav",
        },
    )

    assert "filename" not in safe_payload(event)
    assert "ivanenko" not in render_title(event)
    assert "ivanenko" not in render_body(event)


@pytest.mark.parametrize("category", list(Category))
def test_every_category_renders_without_raising(category: Category) -> None:
    """`render_title`/`render_body` match on the enum and raise on a miss."""
    event = NotificationEvent(
        event_id=uuid4(),
        tenant_id=TENANT,
        category=category,
        actor_user_id=USER,
        resource_type="note",
        resource_id=uuid4(),
        occurred_at=datetime.now(UTC),
        recipient_hints=(USER,),
        payload={},
    )
    assert render_title(event)
    assert render_body(event)


# ── the MFA reminder ──


def _reminder_event(**payload: object) -> NotificationEvent:
    return NotificationEvent(
        event_id=uuid4(),
        tenant_id=TENANT,
        category=Category.SECURITY_MFA_REMINDER,
        actor_user_id=uuid4(),  # the reviewer
        resource_type="user",
        resource_id=USER,  # the subject
        occurred_at=datetime.now(UTC),
        recipient_hints=(USER,),
        payload=payload,  # type: ignore[arg-type]
    )


def test_the_reminder_names_a_role_and_never_a_person() -> None:
    """The reviewer's name is dropped: naming them turns a security ask into an interpersonal one."""
    event = _reminder_event(
        requested_by_role="auditor",
        reminder_count=2,
        requested_by_display="Oksana Auditor",
        subject_email="member@acme.example",
    )

    fields = safe_payload(event)
    assert fields == {"requested_by_role": "auditor", "reminder_count": "2"}
    for leak in ("Oksana", "member@acme.example"):
        assert leak not in render_title(event)
        assert leak not in render_body(event)


def test_a_repeat_ask_reads_as_a_repeat_ask() -> None:
    once = render_body(_reminder_event(requested_by_role="auditor", reminder_count=1))
    twice = render_body(_reminder_event(requested_by_role="auditor", reminder_count=3))
    assert "asks again" not in once
    assert "asks again" in twice


def test_an_unknown_requester_role_degrades_to_prose_not_to_a_db_value() -> None:
    body = render_body(_reminder_event(requested_by_role="root", reminder_count=1))
    assert "root" not in body
    assert "security team" in body


def test_the_reminder_links_to_enrolment_and_carries_no_subject_id() -> None:
    """The link carries no subject id: enrolment acts on whoever is signed in."""
    link = deep_link(_reminder_event(requested_by_role="auditor"), base_url="https://app.example/")
    assert link == "https://app.example/mfa"
    assert str(USER) not in link


# ── workspace invitations and removals ──

INVITER = uuid4()
INVITEE = uuid4()
PERSONAL = uuid4()
INVITING = uuid4()
INVITATION = uuid4()

# What a careless producer might add; none of it may reach a rendered row.
_WORKSPACE_LEAKS = {
    "workspace_name": "Sunrise Studio",
    "inviter_name": "Anna Ivanenko",
    "invitee_email": "t.ivanenko@client.example",
    "message": "Welcome aboard, Petro",
}


def _workspace_event(
    category: Category,
    *,
    event_tenant: object,
    resource_type: str,
    resource_id: object,
    payload: dict[str, object],
) -> NotificationEvent:
    return NotificationEvent(
        event_id=uuid4(),
        tenant_id=event_tenant,  # type: ignore[arg-type]
        category=category,
        actor_user_id=INVITER,
        resource_type=resource_type,
        resource_id=resource_id,  # type: ignore[arg-type]
        occurred_at=datetime.now(UTC),
        recipient_hints=(INVITEE,),
        payload={**_WORKSPACE_LEAKS, **payload},  # type: ignore[arg-type]
    )


def _invited(**payload: object) -> NotificationEvent:
    return _workspace_event(
        Category.WORKSPACE_INVITED,
        event_tenant=PERSONAL,
        resource_type="workspace_invitation",
        resource_id=INVITATION,
        payload=payload,
    )


def _accepted(**payload: object) -> NotificationEvent:
    return _workspace_event(
        Category.WORKSPACE_INVITATION_ACCEPTED,
        event_tenant=INVITING,
        resource_type="workspace_membership",
        resource_id=INVITATION,
        payload=payload,
    )


def _removed(**payload: object) -> NotificationEvent:
    return _workspace_event(
        Category.WORKSPACE_MEMBER_REMOVED,
        event_tenant=PERSONAL,
        resource_type="workspace",
        resource_id=INVITING,
        payload=payload,
    )


@pytest.mark.parametrize(
    "event",
    [
        _invited(tenant_id=str(INVITING), invitation_id=str(INVITATION), role="member"),
        _accepted(invitation_id=str(INVITATION), role="admin"),
        _removed(tenant_id=str(INVITING)),
    ],
    ids=["invited", "accepted", "removed"],
)
def test_workspace_rows_carry_no_names_emails_or_workspace_names(event: NotificationEvent) -> None:
    fields = safe_payload(event)
    rendered = render_title(event) + render_body(event)
    assert set(fields) <= {"tenant_id", "invitation_id", "role"}
    for leak in ("Sunrise", "Anna", "Ivanenko", "client.example", "Petro", "@"):
        assert leak not in rendered
        assert leak not in str(fields)
    # Ids are pointers for the client, never prose.
    assert str(INVITING) not in rendered
    assert str(INVITATION) not in rendered


def test_the_invitation_names_the_role_in_words() -> None:
    event = _invited(tenant_id=str(INVITING), invitation_id=str(INVITATION), role="viewer")
    assert render_title(event) == "You're invited to a workspace"
    assert "as a viewer" in render_body(event)
    assert "Invitations" in render_body(event)


def test_an_unknown_role_degrades_to_prose_not_to_a_db_value() -> None:
    invited = render_body(_invited(role="owner"))
    accepted = render_body(_accepted(role="owner"))
    assert "owner" not in invited
    assert "owner" not in accepted
    assert accepted == "A new member joined."


def test_the_acceptance_names_the_role() -> None:
    event = _accepted(invitation_id=str(INVITATION), role="admin")
    assert render_title(event) == "Your invitation was accepted"
    assert render_body(event) == "A new member joined as an admin."


def test_the_removal_reassures_about_other_workspaces() -> None:
    event = _removed(tenant_id=str(INVITING))
    assert render_title(event) == "You were removed from a workspace"
    assert render_body(event) == "Your notes in your other workspaces are unaffected."


def test_the_invitation_links_to_the_account_wide_inbox() -> None:
    """The invitee is not a member yet, so neither workspace id rides along."""
    link = deep_link(_invited(), base_url="https://app.example/")
    assert link == "https://app.example/invitations"


def test_the_acceptance_links_to_members_in_the_inviting_workspace() -> None:
    link = deep_link(_accepted(), base_url="https://app.example/")
    assert link == f"https://app.example/settings/members?ws={INVITING}"


def test_the_removal_links_home_and_names_no_workspace() -> None:
    """The workspace can no longer be opened; linking into it would only 403."""
    link = deep_link(_removed(), base_url="https://app.example/")
    assert link == "https://app.example"
    assert str(INVITING) not in link
    assert str(PERSONAL) not in link


# ── W3: comments and per-note access ────────────────────────────────

NOTE = uuid4()
_NOTE_LEAKS = {
    "body": "acquisition closes March 3",
    "commenter_name": "Anna Ivanenko",
    "anchor_key": "salary review",
    "title": "Ivanenko deal",
}


def _note_event(category: Category, **payload: object) -> NotificationEvent:
    return NotificationEvent(
        event_id=uuid4(),
        tenant_id=TENANT,
        category=category,
        actor_user_id=USER,
        resource_type="note",
        resource_id=NOTE,
        occurred_at=datetime.now(UTC),
        recipient_hints=(uuid4(),),
        payload={"note_code": "N-2026-0042", **_NOTE_LEAKS, **payload},  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    "event",
    [
        _note_event(Category.NOTE_COMMENTED, anchor_kind="section"),
        _note_event(Category.NOTE_ACCESS_CHANGED, role="edit"),
        _note_event(Category.NOTE_ACCESS_CHANGED),
        _note_event(Category.NOTE_SHARED_WITH_YOU, role="comment", shared_by_display="Anna"),
    ],
    ids=["commented", "access-changed", "access-revoked", "shared-with-role"],
)
def test_note_collaboration_rows_carry_no_body_key_or_title(event: NotificationEvent) -> None:
    fields = safe_payload(event)
    rendered = render_title(event) + render_body(event)
    assert set(fields) <= {"note_code", "anchor_kind", "role", "shared_by_display"}
    for leak in ("March 3", "Ivanenko", "salary", "deal"):
        assert leak not in rendered
        assert leak not in str(fields)
    assert "N-2026-0042" in rendered


def test_a_comment_names_where_not_what() -> None:
    event = _note_event(Category.NOTE_COMMENTED, anchor_kind="item")
    assert render_title(event) == "New comment on note N-2026-0042"
    assert render_body(event) == (
        "Someone commented on an item of note N-2026-0042. Open the note to read it."
    )
    assert deep_link(event, base_url="https://app.example") == (
        f"https://app.example/notes/{NOTE}?ws={TENANT}"
    )


def test_access_change_and_revocation_read_differently() -> None:
    changed = _note_event(Category.NOTE_ACCESS_CHANGED, role="comment")
    assert render_title(changed) == "Your access to note N-2026-0042 changed"
    assert render_body(changed) == "You can now comment on note N-2026-0042."
    revoked = _note_event(Category.NOTE_ACCESS_CHANGED)
    assert render_title(revoked) == "Your access to note N-2026-0042 was removed"
    assert render_body(revoked) == "You no longer have access to note N-2026-0042."
    # An unknown role is not echoed; it reads as a removal rather than a DB value.
    odd = _note_event(Category.NOTE_ACCESS_CHANGED, role="manage")
    assert "manage" not in render_title(odd) + render_body(odd)


def test_a_share_names_the_role_when_given() -> None:
    event = _note_event(Category.NOTE_SHARED_WITH_YOU, role="view", shared_by_display="Anna")
    assert render_body(event) == "Anna gave you access to note N-2026-0042. You can view it."
    legacy = _note_event(Category.NOTE_SHARED_WITH_YOU, shared_by_display="Anna")
    assert render_body(legacy) == "Anna gave you access to note N-2026-0042."
