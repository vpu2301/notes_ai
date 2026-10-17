"""W2 invitations (ADR-0070): grant only to the proven address, one live row, mail failure is visible."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from auth_service.domain.errors import ApiError
from auth_service.domain.identity_repository import Identity
from auth_service.domain.invitation_repository import hash_token
from auth_service.domain.invitation_service import InvitationService

TENANT = UUID("00000000-0000-0000-0000-0000000000aa")


def _identity(email: str) -> Identity:
    return Identity(
        id=uuid4(),
        email=email,
        email_verified_at=None,
        display_name=email.split("@")[0],
        status="active",
        mfa_enabled=False,
        has_password=False,
        last_tenant_id=None,
        failed_login_count=0,
        lock_count=0,
        locked_until=None,
        lock_notified_at=None,
        deletion_requested_at=None,
    )


class FakeRepo:
    """The SQL semantics the service relies on, in memory."""

    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}
        self.members: dict[tuple[UUID, str], str] = {}  # (tenant, email) -> status
        self.identities: dict[str, UUID] = {}

    def _status(self, r: dict[str, Any]) -> str:
        if r["accepted_at"]:
            return "accepted"
        if r["revoked_at"]:
            return "revoked"
        return "expired" if r["expires_at"] <= datetime.now(UTC) else "pending"

    def _view(self, r: dict[str, Any]) -> dict[str, Any]:
        return {**r, "status": self._status(r)}

    async def is_active_member(self, *, tenant_id: UUID, email: str) -> bool:
        return self.members.get((tenant_id, email)) == "active"

    async def upsert_live(self, **kw: Any) -> tuple[dict[str, Any], bool]:
        for r in self.rows.values():
            if (
                r["tenant_id"] == kw["tenant_id"]
                and r["email"] == kw["email"]
                and not r["accepted_at"]
                and not r["revoked_at"]
            ):
                r.update(token_hash=kw["token_hash"], expires_at=kw["expires_at"], role=kw["role"])
                return self._view(r), False
        row = {
            "id": uuid4(),
            "tenant_id": kw["tenant_id"],
            "email": kw["email"],
            "role": kw["role"],
            "invited_by": kw["invited_by"],
            "message": kw["message"],
            "lang": kw["lang"],
            "token_hash": kw["token_hash"],
            "expires_at": kw["expires_at"],
            "sent_count": 0,
            "last_sent_at": None,
            "accepted_at": None,
            "revoked_at": None,
            "created_at": datetime.now(UTC),
            "workspace_name": "Sunrise Studio",
            "workspace_kind": "team",
            "invited_by_display": "Anna",
            "note_id": kw.get("note_id"),
            "note_role": kw.get("note_role"),
        }
        self.rows[row["id"]] = row
        return self._view(row), True

    async def mark_sent(self, invitation_id: UUID) -> dict[str, Any]:
        r = self.rows[invitation_id]
        r["sent_count"] += 1
        return self._view(r)

    async def identity_id_for(self, email: str) -> UUID | None:
        return self.identities.get(email)

    async def personal_tenant_of(self, identity_id: UUID) -> UUID | None:
        return uuid4()

    async def find_live_by_token(self, token: str) -> dict[str, Any] | None:
        for r in self.rows.values():
            if r["token_hash"] == hash_token(token) and self._status(r) == "pending":
                return self._view(r)
        return None

    async def get_live_for_email(self, invitation_id: UUID, email: str) -> dict[str, Any] | None:
        r = self.rows.get(invitation_id)
        if r and r["email"] == email and self._status(r) == "pending":
            return self._view(r)
        return None

    async def list_live_for_email(self, email: str) -> list[dict[str, Any]]:
        return [
            self._view(r)
            for r in self.rows.values()
            if r["email"] == email and self._status(r) == "pending"
        ]

    async def accept(self, *, invitation_id: UUID, identity_id: UUID) -> Any:
        r = self.rows[invitation_id]
        if self._status(r) != "pending":
            return None
        r["accepted_at"] = datetime.now(UTC)
        key = (r["tenant_id"], r["email"])
        outcome = "already_member" if self.members.get(key) == "active" else "joined"
        self.members[key] = "active"
        return {"tenant_id": r["tenant_id"], "role": r["role"]}, outcome

    async def decline(self, *, invitation_id: UUID, email: str, identity_id: UUID) -> bool:
        r = self.rows.get(invitation_id)
        if not r or r["email"] != email or self._status(r) != "pending":
            return False
        r["revoked_at"] = datetime.now(UTC)
        return True


class FakeMailer:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail = fail

    async def send_invitation(self, *, to: str, lang: str, fields: dict[str, Any]) -> None:
        if self.fail:
            raise ConnectionError("relay down")
        self.sent.append({"to": to, **fields})


class Allow:
    async def allow(self, *a: Any, **kw: Any) -> Any:
        return type("D", (), {"allowed": True, "retry_after": 0, "degraded": False})()


@pytest.fixture
def svc() -> tuple[InvitationService, FakeRepo, FakeMailer, list[tuple[str, Any]]]:
    repo, mailer, events = FakeRepo(), FakeMailer(), []

    async def notify(event: str, **kw: Any) -> None:
        events.append((event, kw))

    service = InvitationService(
        repo=repo,  # type: ignore[arg-type]
        mailer=mailer,
        limiter=Allow(),
        app_base_url="https://app.example",
        notify=notify,
    )
    return service, repo, mailer, events


async def _invite(service: InvitationService, email: str = "Tom@Client.com", **kw: Any) -> Any:
    return await service.create(
        tenant_id=TENANT,
        workspace_kind=kw.get("kind", "team"),
        inviter=_identity("anna@acme.example"),
        email=email,
        role=kw.get("role", "member"),
        message="",
        lang="en",
    )


def _token(mailer: FakeMailer) -> str:
    return mailer.sent[-1]["invite_url"].rsplit("/", 1)[-1]


async def test_new_address_gets_a_row_and_a_mail_with_the_link(svc: Any) -> None:
    service, repo, mailer, events = svc
    result = await _invite(service)
    assert result.created and result.delivery == "sent" and not result.has_account
    assert result.invitation["email"] == "tom@client.com"
    assert mailer.sent[0]["workspace_name"] == "Sunrise Studio"
    # Only the hash is stored.
    (row,) = repo.rows.values()
    assert row["token_hash"] == hash_token(_token(mailer))
    assert events == []  # no account → no in-app notification


async def test_existing_account_is_also_notified(svc: Any) -> None:
    service, repo, _, events = svc
    repo.identities["tom@client.com"] = uuid4()
    result = await _invite(service)
    assert result.has_account
    assert [e for e, _ in events] == ["invited"]


async def test_re_inviting_resends_on_the_same_row(svc: Any) -> None:
    service, repo, mailer, _ = svc
    first = await _invite(service)
    old_token = _token(mailer)
    second = await _invite(service)
    assert not second.created
    assert len(repo.rows) == 1 and second.invitation["sent_count"] == 2
    # The old link stops working.
    with pytest.raises(ApiError) as exc:
        await service.lookup(old_token)
    assert exc.value.code == "invitation_not_found"
    assert first.invitation["id"] == second.invitation["id"]


async def test_active_member_and_personal_workspace_are_refused(svc: Any) -> None:
    service, repo, _, _ = svc
    repo.members[(TENANT, "tom@client.com")] = "active"
    with pytest.raises(ApiError) as exc:
        await _invite(service)
    assert (exc.value.code, exc.value.status_code) == ("already_member", 409)
    with pytest.raises(ApiError) as exc:
        await _invite(service, "x@y.example", kind="personal")
    assert (exc.value.code, exc.value.status_code) == ("personal_workspace", 422)


async def test_mail_failure_keeps_the_row_for_a_resend(svc: Any) -> None:
    service, repo, mailer, _ = svc
    mailer.fail = True
    result = await _invite(service)
    assert result.delivery == "queued_failed"
    assert result.invitation["sent_count"] == 0
    assert len(repo.rows) == 1


async def test_accept_needs_the_invited_address(svc: Any) -> None:
    service, repo, mailer, _ = svc
    await _invite(service)
    token = _token(mailer)
    with pytest.raises(ApiError) as exc:
        await service.accept_token(token, _identity("mallory@evil.example"))
    assert (exc.value.code, exc.value.status_code) == ("invitation_email_mismatch", 403)
    assert repo.members == {}

    accepted = await service.accept_token(token, _identity("tom@client.com"))
    assert accepted.tenant_id == TENANT and accepted.outcome == "joined"
    # A used link says nothing more than an unknown one.
    with pytest.raises(ApiError) as exc:
        await service.lookup(token)
    assert exc.value.code == "invitation_not_found"


async def test_unknown_expired_and_revoked_look_the_same(svc: Any) -> None:
    service, repo, mailer, _ = svc
    await _invite(service)
    (row,) = repo.rows.values()
    row["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    for token in (_token(mailer), "no-such-token"):
        with pytest.raises(ApiError) as exc:
            await service.lookup(token)
        assert (exc.value.code, exc.value.status_code) == ("invitation_not_found", 404)


async def test_sign_up_accepts_every_open_invitation(svc: Any) -> None:
    service, _, _, _ = svc
    await _invite(service)
    joined = await service.accept_all_open(_identity("tom@client.com"))
    assert [m.tenant_id for m in joined] == [TENANT]
    assert joined[0].role == "member"


async def test_decline_is_only_for_the_invited_address(svc: Any) -> None:
    service, repo, _, _ = svc
    result = await _invite(service)
    with pytest.raises(ApiError):
        await service.decline(result.invitation["id"], _identity("other@x.example"))
    assert await service.decline(result.invitation["id"], _identity("tom@client.com")) == TENANT


async def test_without_a_limiter_invitations_fail_closed(svc: Any) -> None:
    service, _, _, _ = svc
    service._limiter = None
    with pytest.raises(ApiError) as exc:
        await _invite(service)
    assert (exc.value.code, exc.value.status_code) == ("invite_unavailable", 503)


async def test_a_note_invitation_is_a_guest_with_a_note_role(svc: Any) -> None:
    service, repo, _, _ = svc
    note = uuid4()
    result = await service.create(
        tenant_id=TENANT,
        workspace_kind="team",
        inviter=_identity("anna@acme.example"),
        email="tom@client.com",
        role="guest",
        message="",
        lang="en",
        note_id=note,
        note_role="view",
    )
    assert result.created
    (row,) = repo.rows.values()
    assert row["role"] == "guest"


@pytest.mark.parametrize(
    ("role", "note_role"), [("guest", None), ("member", "view"), ("guest", "manage")]
)
async def test_note_invitations_need_guest_and_a_note_role(
    svc: Any, role: str, note_role: str | None
) -> None:
    service, _, _, _ = svc
    with pytest.raises(ApiError) as exc:
        await service.create(
            tenant_id=TENANT,
            workspace_kind="team",
            inviter=_identity("anna@acme.example"),
            email="tom@client.com",
            role=role,
            message="",
            lang="en",
            note_id=uuid4(),
            note_role=note_role,
        )
    assert exc.value.code == "invalid_role"


async def test_guest_alone_is_not_a_workspace_invitation(svc: Any) -> None:
    service, _, _, _ = svc
    with pytest.raises(ApiError) as exc:
        await _invite(service, role="guest")
    assert exc.value.code == "invalid_role"
