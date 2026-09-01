"""PII redactor coverage."""

from __future__ import annotations

from uuid import uuid4

from note_service.domain.pii_redactor import is_author_team, redact_snippet


def test_national_id_redacted():
    out = redact_snippet("контрагент, податковий номер 1234567890, підписав угоду")
    assert "1234567890" not in out
    assert "[redacted-id]" in out


def test_dob_like_redacted():
    out = redact_snippet("дата народження 12.05.1980")
    assert "12.05.1980" not in out
    assert "[redacted-date]" in out


def test_full_name_redacted_cyrillic():
    out = redact_snippet("зустріч провів Іваненко Петро Сергійович сьогодні")
    assert "Іваненко" not in out
    assert "[redacted-name]" in out


def test_author_team_primary_author():
    uid = uuid4()
    assert is_author_team(
        viewer_user_id=uid,
        primary_author_id=uid,
        co_author_ids=[],
        viewer_roles=["member"],
    )


def test_author_team_co_author():
    primary = uuid4()
    viewer = uuid4()
    assert is_author_team(
        viewer_user_id=viewer,
        primary_author_id=primary,
        co_author_ids=[viewer],
        viewer_roles=["member"],
    )


def test_tenant_admin_is_not_treated_as_team():
    """No role-wide redaction bypass: a tenant_admin who is not an author
    of the note sees the redacted snippet like anyone else. A role-wide
    bypass would quietly grant, over every note at once, exactly the
    visibility the redaction exists to limit."""
    viewer = uuid4()
    other = uuid4()
    assert not is_author_team(
        viewer_user_id=viewer,
        primary_author_id=other,
        co_author_ids=[],
        viewer_roles=["tenant_admin"],
    )


def test_random_member_not_on_team():
    viewer = uuid4()
    other = uuid4()
    assert not is_author_team(
        viewer_user_id=viewer,
        primary_author_id=other,
        co_author_ids=[],
        viewer_roles=["member"],
    )
