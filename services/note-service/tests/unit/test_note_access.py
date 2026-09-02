"""0016 — who may see, share and delete a note."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from auth import Claims
from note_models import NoteStatus
from note_service.domain import access
from note_service.domain.notes_repository import NoteRow
from note_service.domain.search import SearchFilters, _access_clauses
from note_service.domain.share_tokens import hash_token, looks_like_token, token_for

AUTHOR = uuid4()
CO = uuid4()
SHAREE = uuid4()
STRANGER = uuid4()
ADMIN = uuid4()


def _claims(sub: UUID, *roles: str) -> Claims:
    return Claims(
        sub=sub,
        tid=uuid4(),
        roles=list(roles) or ["member"],
        sid="s",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _note(visibility: str = "private", shared: list[UUID] | None = None) -> NoteRow:
    now = datetime.now(UTC)
    return NoteRow(
        id=uuid4(),
        tenant_id=uuid4(),
        code="NOTE-2026-00001",
        status=NoteStatus.DRAFT,
        current_version_id=uuid4(),
        current_version_number=1,
        primary_author_id=AUTHOR,
        co_author_ids=[CO],
        title="t",
        created_at=now,
        updated_at=now,
        finalized_at=None,
        cancelled_at=None,
        visibility=visibility,
        shared_with_ids=shared or [],
    )


@pytest.mark.parametrize(
    ("who", "roles", "visibility", "shared", "expected"),
    [
        (AUTHOR, (), "private", [], True),
        (CO, (), "private", [], True),
        (SHAREE, (), "private", [SHAREE], True),
        (STRANGER, (), "private", [], False),
        (STRANGER, (), "workspace", [], True),
        (ADMIN, ("tenant_admin",), "private", [], True),
        (ADMIN, ("auditor",), "private", [], True),
    ],
)
def test_can_view(
    who: UUID, roles: tuple[str, ...], visibility: str, shared: list[UUID], expected: bool
) -> None:
    assert access.can_view(_note(visibility, shared), _claims(who, *roles)) is expected


def test_private_note_is_a_404_to_strangers_not_a_403() -> None:
    with pytest.raises(HTTPException) as exc:
        access.require_view(_note(), _claims(STRANGER))
    assert exc.value.status_code == 404


def test_sharee_can_read_but_not_manage() -> None:
    note = _note(shared=[SHAREE])
    claims = _claims(SHAREE)
    assert access.can_view(note, claims)
    assert not access.can_manage(note, claims)
    with pytest.raises(HTTPException) as exc:
        access.require_manage(note, claims)
    assert exc.value.status_code == 403


def test_co_author_manages_but_only_author_or_admin_deletes() -> None:
    note = _note()
    assert access.can_manage(note, _claims(CO))
    assert not access.can_delete(note, _claims(CO))
    assert access.can_delete(note, _claims(AUTHOR))
    assert access.can_delete(note, _claims(ADMIN, "tenant_admin"))
    assert not access.can_delete(note, _claims(ADMIN, "auditor"))


def test_search_clauses_hide_the_bin_and_private_notes() -> None:
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(viewer_sub=STRANGER), args)
    assert clauses[0] == "n.deleted_at IS NULL"
    assert "n.visibility = 'workspace'" in clauses[1]
    assert "ANY(n.shared_with_ids)" in clauses[1]
    assert args == [STRANGER]


def test_search_clauses_for_oversight_only_hide_the_bin() -> None:
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(viewer_sub=ADMIN, viewer_sees_all=True), args)
    assert clauses == ["n.deleted_at IS NULL"]
    assert args == []


def test_share_token_is_stable_per_link_and_key() -> None:
    link = uuid4()
    key = "00" * 32
    a = token_for(link, key_hex=key)
    assert a == token_for(link, key_hex=key)
    assert a != token_for(uuid4(), key_hex=key)
    assert a != token_for(link, key_hex="11" * 32)
    assert looks_like_token(a)
    assert not looks_like_token("../etc/passwd")
    assert not looks_like_token("short")
    assert len(hash_token(a)) == 64
