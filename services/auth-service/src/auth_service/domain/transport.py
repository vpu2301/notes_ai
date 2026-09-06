"""Client-type transport for session responses (IDX-A2, F4).

``X-Client-Type: web | macos | ios`` decides where the refresh token
travels: web gets the HttpOnly ``mdx_rt`` cookie and no ``refresh_token``
in the body; native clients get it in the JSON body (they keep it in the
Keychain) and never a cookie. A missing or unknown header means ``web`` —
today's clients send nothing and must keep working.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

CLIENT_TYPE_HEADER = "X-Client-Type"


class ClientType(StrEnum):
    WEB = "web"
    MACOS = "macos"
    IOS = "ios"

    @property
    def native(self) -> bool:
        return self is not ClientType.WEB


def client_type_of(request: Request) -> ClientType:
    raw = (request.headers.get(CLIENT_TYPE_HEADER) or "").strip().lower()
    try:
        return ClientType(raw)
    except ValueError:
        return ClientType.WEB


class TokenResponse(BaseModel):
    """Superset of the pre-IDX ``LoginResponse`` — every old reader still parses it."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    expires_in: int
    token_type: str = "Bearer"
    tenant_id: str
    roles: list[str]
    # Native clients only; web responses omit both (the cookie carries the refresh).
    refresh_token: str | None = None
    refresh_expires_in: int | None = None


def token_response(
    *,
    client_type: ClientType,
    access_token: str,
    expires_in: int,
    tenant_id: str,
    roles: list[str],
    refresh_token: str,
    refresh_expires_in: int,
) -> TokenResponse:
    body = TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        tenant_id=tenant_id,
        roles=list(roles),
    )
    if client_type.native:
        return body.model_copy(
            update={"refresh_token": refresh_token, "refresh_expires_in": refresh_expires_in}
        )
    return body


# ── AuthResult (IDX-A3 F3) ───────────────────────────────────────────────


class IdentitySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    display_name: str = ""
    mfa_enabled: bool = False
    has_password: bool = False
    status: str = "active"


class MembershipSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    name: str
    kind: str  # personal | team
    role: str
    status: str


class AuthResult(TokenResponse):
    """What a sign-in attempt returns: the A2 token response plus who the
    person is and where they can go. Old clients keep reading the three
    top-level token fields and ignore the rest.

    The inherited token fields are re-declared with defaults because an
    ``mfa_required`` result is a real, successful 200 that carries no
    token — the first factor passed, the session has not started, and
    there is nothing honest to put in ``access_token``. Callers branch on
    ``status`` before reading it; ``AuthResult.authenticated`` always
    fills all four.
    """

    access_token: str = ""
    expires_in: int = 0
    tenant_id: str = ""
    roles: list[str] = Field(default_factory=list)

    status: Literal["authenticated", "mfa_required"] = "authenticated"
    is_new_identity: bool = False
    identity: IdentitySummary | None = None
    memberships: list[MembershipSummary] = Field(default_factory=list)
    default_tenant_id: str | None = None
    # mfa_required only (A5): the challenge to complete and the methods offered.
    challenge_id: str | None = None
    methods: list[str] | None = None
    # Set only when the sign-in spent a recovery code. Zero is the case
    # that matters: the person has just used their last way back in and
    # does not otherwise find out until the next time they need one.
    recovery_codes_left: int | None = None
    recovery_codes_exhausted: bool | None = None

    @classmethod
    def authenticated(
        cls,
        *,
        client_type: ClientType,
        access_token: str,
        expires_in: int,
        tenant_id: str,
        roles: list[str],
        refresh_token: str,
        refresh_expires_in: int,
        identity: IdentitySummary,
        memberships: list[MembershipSummary],
        is_new_identity: bool,
    ) -> AuthResult:
        base = token_response(
            client_type=client_type,
            access_token=access_token,
            expires_in=expires_in,
            tenant_id=tenant_id,
            roles=roles,
            refresh_token=refresh_token,
            refresh_expires_in=refresh_expires_in,
        )
        return cls(
            **base.model_dump(),
            status="authenticated",
            is_new_identity=is_new_identity,
            identity=identity,
            memberships=memberships,
            default_tenant_id=tenant_id,
        )

    @classmethod
    def mfa_required(cls, *, challenge_id: str, methods: list[str], expires_in: int) -> AuthResult:
        """The first factor passed; a second one is owed (IDX-A5 F3).

        Deliberately says nothing else — not the email, not the
        workspaces, not whether the identity was just created. All of
        that is on the far side of the second factor, and answering it
        here would make a stolen password a working directory lookup.
        """
        return cls(
            status="mfa_required",
            challenge_id=challenge_id,
            methods=methods,
            expires_in=expires_in,
        )
