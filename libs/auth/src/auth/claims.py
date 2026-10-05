"""Strict claims model: ``extra="forbid"`` rejects injected claims; Keycloak's standard extras are allow-listed."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Claims(BaseModel):
    """The exact set of claims a libs/auth-verified token may carry.

    Adding a new claim is a deliberate decision: bump the schema, update
    the realm protocol mappers, and add a test that the new claim is parsed
    correctly. Unknown claim names are rejected.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    # ── Spec-required (security-bearing) ─────────────────────────────────
    sub: UUID
    tid: UUID
    roles: list[str]
    scope: str = ""
    mfa: bool = False
    # TOTP enrolment (Keycloak `mfa_enrolled` attribute); lets a gated route tell
    # "enrol first" (403) from "re-login with TOTP" (401).
    mfa_enrolled: bool = False
    sid: str
    iss: str
    aud: str | list[str]
    exp: int
    iat: int
    nbf: int | None = None

    # ── Standard Keycloak/OIDC built-ins, accepted and ignored ──────────
    jti: str | None = None
    typ: str | None = None
    azp: str | None = None
    auth_time: int | None = None
    acr: str | None = None
    session_state: str | None = None
    allowed_origins: list[str] | None = Field(default=None, alias="allowed-origins")

    # ── Profile/email scope claims (silently accepted when scope enabled) ─
    preferred_username: str | None = None
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    email: str | None = None
    email_verified: bool | None = None

    # ── Keycloak role mappers we don't use (`roles` is the canonical one) ─
    realm_access: dict[str, object] | None = None
    resource_access: dict[str, object] | None = None
