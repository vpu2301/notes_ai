"""Who may see, comment on, edit, share and delete a note (0016, W3 G-1 matrix)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from auth import Claims
from note_models import NoteStatus
from note_service.domain import access, sharing_policy
from note_service.domain import visibility as visibility_defaults
from note_service.domain.notes_repository import NoteRow
from note_service.domain.search import SearchFilters, _access_clauses
from note_service.domain.share_tokens import hash_token, looks_like_token, token_for

AUTHOR = uuid4()
CO = uuid4()
EDITOR = uuid4()
COMMENTER = uuid4()
VIEWER_COLLAB = uuid4()
STRANGER = uuid4()
ADMIN = uuid4()
SOMEONE = uuid4()

# Per-note grants. The collaborators are guests here, so visibility adds nothing and
# the cell shows the grant alone; "max(role, workspace grant)" has its own test below.
COLLABORATORS = {EDITOR: "edit", COMMENTER: "comment", VIEWER_COLLAB: "view"}


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


def _note(
    visibility: str = "private",
    collaborators: dict[UUID, str] | None = None,
    *,
    transcript_shared: bool = False,
) -> NoteRow:
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
        collaborators=dict(COLLABORATORS if collaborators is None else collaborators),
        transcript_shared=transcript_shared,
    )


# ── The G-1 matrix ──────────────────────────────────────────────────

PERSONAS: dict[str, Claims] = {
    "author": _claims(AUTHOR, "member"),
    "co_author": _claims(CO, "member"),
    "edit_collaborator": _claims(EDITOR, "guest"),
    "comment_collaborator": _claims(COMMENTER, "guest"),
    "view_collaborator": _claims(VIEWER_COLLAB, "guest"),
    "member": _claims(SOMEONE, "member"),
    "viewer": _claims(SOMEONE, "viewer"),
    "guest": _claims(SOMEONE, "guest"),
    "admin": _claims(ADMIN, "tenant_admin", "member"),
    "auditor": _claims(ADMIN, "auditor"),
    # Holds no workspace role that reads notes and no grant.
    "stranger": _claims(STRANGER, "service"),
}

# persona → (level on a private note, level on a workspace note)
EXPECTED_LEVEL: dict[str, tuple[str | None, str | None]] = {
    "author": ("manage", "manage"),
    "co_author": ("manage", "manage"),
    "edit_collaborator": ("edit", "edit"),
    "comment_collaborator": ("comment", "comment"),
    "view_collaborator": ("view", "view"),
    "member": (None, "edit"),
    "viewer": (None, "comment"),
    "guest": (None, None),
    "admin": ("manage", "manage"),
    "auditor": ("view", "view"),  # oversight read, nothing more
    "stranger": (None, None),
}

# Delete is the primary author's or an admin's, never a co-author's.
CAN_DELETE = {"author", "admin"}

_RANK = {None: 0, "view": 1, "comment": 2, "edit": 3, "manage": 4}


def _cells() -> list[tuple[str, str, str, bool]]:
    cells: list[tuple[str, str, str, bool]] = []
    for persona, (private, workspace) in EXPECTED_LEVEL.items():
        for visibility, lvl in (("private", private), ("workspace", workspace)):
            rank = _RANK[lvl]
            expected = {
                "view": rank >= 1,
                "comment": rank >= 2,
                "edit": rank >= 3,
                "manage": rank == 4,
                "delete": persona in CAN_DELETE,
                "transcript": rank >= 3,
                "transcript_shared": rank >= 1,
            }
            cells.extend((persona, visibility, action, ok) for action, ok in expected.items())
    return cells


_CHECK = {
    "view": access.can_view,
    "comment": access.can_comment,
    "edit": access.can_edit,
    "manage": access.can_manage,
    "delete": access.can_delete,
    "transcript": access.can_read_transcript,
    "transcript_shared": access.can_read_transcript,
}


@pytest.mark.parametrize(("persona", "visibility", "action", "expected"), _cells())
def test_matrix(persona: str, visibility: str, action: str, expected: bool) -> None:
    note = _note(visibility, transcript_shared=action == "transcript_shared")
    assert _CHECK[action](note, PERSONAS[persona]) is expected


@pytest.mark.parametrize("persona", sorted(EXPECTED_LEVEL))
@pytest.mark.parametrize("visibility", ["private", "workspace"])
def test_level_per_persona(persona: str, visibility: str) -> None:
    private, workspace = EXPECTED_LEVEL[persona]
    expected = private if visibility == "private" else workspace
    assert access.level(_note(visibility), PERSONAS[persona]) == expected


def test_collaborator_on_a_workspace_note_gets_the_higher_of_role_and_grant() -> None:
    note = _note("workspace", {SOMEONE: "view"})
    # A member with a `view` grant still edits a workspace note …
    assert access.level(note, _claims(SOMEONE, "member")) == "edit"
    # … a viewer with an `edit` grant edits, though visibility alone gives comment.
    note = _note("workspace", {SOMEONE: "edit"})
    assert access.level(note, _claims(SOMEONE, "viewer")) == "edit"
    # On a private note the grant is all there is.
    assert access.level(_note("private", {SOMEONE: "view"}), _claims(SOMEONE, "member")) == "view"


def test_level_of_matches_level_on_plain_fields() -> None:
    note = _note("workspace")
    for claims in PERSONAS.values():
        assert access.level_of(
            primary_author_id=note.primary_author_id,
            co_author_ids=note.co_author_ids,
            visibility=note.visibility,
            collaborator=note.collaborators.get(claims.sub),
            claims=claims,
        ) == access.level(note, claims)


def test_guest_is_only_a_guest_without_another_role() -> None:
    assert access.is_guest(_claims(SOMEONE, "guest"))
    assert not access.is_guest(_claims(SOMEONE, "guest", "member"))
    assert not access.is_guest(_claims(SOMEONE, "member"))


def test_shared_with_ids_no_longer_grants_anything() -> None:
    """W3: access reads `collaborators`; the deprecated array is ignored."""
    note = _note(collaborators={})
    note.shared_with_ids = [SOMEONE]
    assert not access.can_view(note, _claims(SOMEONE, "member"))


# ── The guards: 404 for unseen, 403 insufficient_role for seen-but-not-allowed ──


@pytest.mark.parametrize(
    "guard", [access.require_view, access.require_comment, access.require_edit]
)
def test_unseen_is_a_404_never_a_403(guard) -> None:  # noqa: ANN001
    with pytest.raises(HTTPException) as exc:
        guard(_note(), _claims(STRANGER, "member"))
    assert exc.value.status_code == 404


def test_missing_note_is_a_404() -> None:
    with pytest.raises(HTTPException) as exc:
        access.require_edit(None, _claims(AUTHOR))
    assert exc.value.status_code == 404


@pytest.mark.parametrize(
    ("persona", "guard", "required"),
    [
        ("view_collaborator", access.require_comment, "comment"),
        ("view_collaborator", access.require_edit, "edit"),
        ("comment_collaborator", access.require_edit, "edit"),
        ("edit_collaborator", access.require_manage, "manage"),
        ("auditor", access.require_comment, "comment"),
    ],
)
def test_seen_but_not_allowed_is_403_insufficient_role(persona: str, guard, required: str) -> None:  # noqa: ANN001
    with pytest.raises(HTTPException) as exc:
        guard(_note(), PERSONAS[persona])
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "insufficient_role"
    assert exc.value.detail["required"] == required


def test_allowed_guards_return_the_note() -> None:
    note = _note("workspace")
    assert access.require_edit(note, PERSONAS["member"]) is note
    assert access.require_comment(note, PERSONAS["viewer"]) is note
    assert access.require_manage(note, PERSONAS["co_author"]) is note


def test_transcript_not_shared_is_a_404_not_a_403() -> None:
    note = _note()
    with pytest.raises(HTTPException) as exc:
        access.require_transcript(note, PERSONAS["view_collaborator"])
    assert exc.value.status_code == 404
    shared = _note(transcript_shared=True)
    assert access.require_transcript(shared, PERSONAS["view_collaborator"]) is shared
    # Turning it on never reaches someone who cannot see the note.
    with pytest.raises(HTTPException) as exc:
        access.require_transcript(shared, PERSONAS["guest"])
    assert exc.value.status_code == 404


def test_co_author_manages_but_only_author_or_admin_deletes() -> None:
    note = _note()
    assert access.can_manage(note, _claims(CO))
    assert not access.can_delete(note, _claims(CO))
    with pytest.raises(HTTPException) as exc:
        access.require_delete(note, _claims(CO))
    assert exc.value.status_code == 403
    assert access.can_delete(note, _claims(AUTHOR))
    assert access.can_delete(note, _claims(ADMIN, "tenant_admin"))
    assert not access.can_delete(note, _claims(ADMIN, "auditor"))


def test_reads_as_collaborator_needs_no_purpose() -> None:
    note = _note("workspace")
    assert access.reads_as_collaborator(note, PERSONAS["view_collaborator"])
    assert access.reads_as_collaborator(note, PERSONAS["co_author"])
    # A member reading a workspace note is an oversight read and must say why.
    assert not access.reads_as_collaborator(note, PERSONAS["member"])


# ── Search clauses (B-3) ────────────────────────────────────────────


def test_search_clauses_hide_the_bin_and_private_notes() -> None:
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(viewer_sub=STRANGER), args)
    assert clauses[0] == "n.deleted_at IS NULL"
    assert "n.visibility = 'workspace'" in clauses[1]
    assert "EXISTS (SELECT 1 FROM note_collaborators c" in clauses[1]
    assert "shared_with_ids" not in " ".join(clauses)
    assert args == [STRANGER]


def test_search_clauses_for_oversight_only_hide_the_bin() -> None:
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(viewer_sub=ADMIN, viewer_sees_all=True), args)
    assert clauses == ["n.deleted_at IS NULL"]


def test_search_as_guest_sees_only_its_grants() -> None:
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(viewer_sub=SOMEONE, viewer_guest=True), args)
    assert clauses == [
        "n.deleted_at IS NULL",
        "EXISTS (SELECT 1 FROM note_collaborators c WHERE c.note_id = n.id AND c.user_sub = $1)",
    ]
    # No workspace visibility and no authorship for a guest.
    assert "visibility" not in " ".join(clauses)
    assert "primary_author_id" not in " ".join(clauses)
    assert args == [SOMEONE]


def test_search_as_guest_scope_mine_is_empty_by_construction() -> None:
    """Guest + scope=mine = granted AND authored; a guest authors nothing here."""
    args: list[object] = []
    clauses = _access_clauses(
        SearchFilters(viewer_sub=SOMEONE, viewer_guest=True, scope="mine"), args
    )
    assert any(c.startswith("EXISTS (SELECT 1 FROM note_collaborators") for c in clauses)
    assert "(n.primary_author_id = $1 OR $1 = ANY(n.co_author_ids))" in clauses


def test_search_scope_mine_adds_the_author_clause() -> None:
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(viewer_sub=SOMEONE, scope="mine"), args)
    assert clauses[-1] == "(n.primary_author_id = $1 OR $1 = ANY(n.co_author_ids))"


def test_search_scope_shared_with_me_is_visible_but_not_mine() -> None:
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(viewer_sub=SOMEONE, scope="shared_with_me"), args)
    # Visible (workspace, or granted) …
    assert "n.visibility = 'workspace'" in clauses[1]
    assert "note_collaborators" in clauses[1]
    # … and not authored by me.
    assert clauses[-1] == "NOT (n.primary_author_id = $1 OR $1 = ANY(n.co_author_ids))"


def test_search_author_filter_is_part_of_the_shared_clauses() -> None:
    """exact_total uses the same clauses, so the author filter now counts too."""
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(viewer_sub=SOMEONE, author_id=AUTHOR), args)
    assert "(n.primary_author_id = $1 OR $1 = ANY(n.co_author_ids))" in clauses
    assert args == [AUTHOR, SOMEONE]


def test_search_author_filter_applies_without_a_viewer() -> None:
    args: list[object] = []
    clauses = _access_clauses(SearchFilters(author_id=AUTHOR), args)
    assert "(n.primary_author_id = $1 OR $1 = ANY(n.co_author_ids))" in clauses


# ── Default visibility (B-9) ────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "kw", "expected"),
    [
        ("team", {"meeting_type": "client"}, "workspace"),
        ("team", {"template_code": "client_call_v1"}, "workspace"),
        ("team", {"meeting_type": "auto"}, "workspace"),
        ("team", {"meeting_type": "one_on_one"}, "private"),
        ("team", {"template_code": "one_on_one_v1"}, "private"),
        ("team", {"meeting_type": "interview"}, "private"),
        ("team", {"template_code": "voice_memo_v1"}, "private"),
        ("personal", {"meeting_type": "client"}, "private"),
        ("personal", {"template_code": "client_call_v1"}, "private"),
    ],
)
def test_default_for(kind: str, kw: dict[str, str], expected: str) -> None:
    assert visibility_defaults.default_for(kind, **kw) == expected


class _TemplateConn:
    def __init__(self, code: str | None) -> None:
        self.code = code
        self.queries: list[str] = []

    async def fetchval(self, query: str, *args: object) -> str | None:
        self.queries.append(query)
        return self.code


@pytest.mark.parametrize(
    ("kind", "code", "meeting_type", "expected", "reads_template"),
    [
        ("team", "client_call_v1", None, "workspace", True),
        ("team", "one_on_one_v1", None, "private", True),
        ("team", "client_call_v1", "one_on_one", "private", False),
        ("personal", "client_call_v1", None, "private", False),
    ],
)
async def test_default_for_new_note(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    code: str,
    meeting_type: str | None,
    expected: str,
    reads_template: bool,
) -> None:
    async def _kind(conn, *, tenant_id):  # noqa: ANN001
        return kind

    monkeypatch.setattr(sharing_policy, "tenant_kind", _kind)
    conn = _TemplateConn(code)
    got = await visibility_defaults.default_for_new_note(
        conn, tenant_id=uuid4(), template_id=uuid4(), meeting_type=meeting_type
    )
    assert got == expected
    assert bool(conn.queries) is reads_template


# ── Share tokens ────────────────────────────────────────────────────


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
