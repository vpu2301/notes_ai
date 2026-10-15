"""Tenant (workspace) management.

Reads need a membership in the tenant; writes (except create) additionally need
it to be the caller's active tenant. Perms matrix = platform-role gate, membership
role = per-tenant gate on top.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

import asyncpg
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims
from auth.perms import can
from db import tenant_connection

from .. import audit_kinds, auth_metrics
from .. import tenants_repository as repo
from ..config import settings
from ..deps import current_user, get_state, requires, requires_mfa
from ..domain.errors import ApiError
from ..domain.identity_repository import platform_roles_for, primary_role
from ..domain.transport import TokenResponse
from ..notifications import emit_member_removed
from .native_common import as_problem, recent_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tenants", tags=["tenants"])

# Membership management roles (distinct from JWT platform roles).
MANAGEMENT_ROLES: frozenset[str] = frozenset({"owner", "admin", "member", "assistant", "viewer"})
MANAGER_ROLES: frozenset[str] = frozenset({"owner", "admin"})

_MAX_LOGO_BYTES = 2 * 1024 * 1024
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# ── Wire models ─────────────────────────────────────────────────────────


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantOut(_Strict):
    id: UUID
    name: str
    display_name: str
    legal_name: str
    slug: str | None
    locale: str
    timezone: str
    status: str
    is_active: bool
    logo_url: str
    has_logo: bool = False
    contact_email: str
    phone_number: str
    website: str
    address_line1: str
    address_line2: str
    postal_code: str
    city: str
    state_or_region: str
    country: str
    tax_id: str
    registration_number: str
    created_at: datetime
    updated_at: datetime
    my_role: str | None = None


class TenantSummary(_Strict):
    id: UUID
    name: str
    display_name: str
    slug: str | None
    status: str
    is_active: bool
    logo_url: str
    my_role: str
    # personal | team — clients label a personal workspace "Personal" whatever its name (W1).
    kind: str = "team"


class TenantListOut(_Strict):
    items: list[TenantSummary]


class TenantCreate(_Strict):
    name: str = Field(min_length=2, max_length=120)
    display_name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=120)
    legal_name: str = Field(default="", max_length=200)
    locale: str = Field(default="uk", max_length=16)
    timezone: str = Field(default="Europe/Kyiv", max_length=64)
    contact_email: str = Field(default="", max_length=320)
    phone_number: str = Field(default="", max_length=64)
    website: str = Field(default="", max_length=320)
    address_line1: str = Field(default="", max_length=200)
    address_line2: str = Field(default="", max_length=200)
    postal_code: str = Field(default="", max_length=32)
    city: str = Field(default="", max_length=120)
    state_or_region: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=120)
    tax_id: str = Field(default="", max_length=64)
    registration_number: str = Field(default="", max_length=64)


class TenantUpdate(_Strict):
    display_name: str | None = Field(default=None, max_length=200)
    legal_name: str | None = Field(default=None, max_length=200)
    slug: str | None = Field(default=None, max_length=120)
    locale: str | None = Field(default=None, max_length=16)
    timezone: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None
    logo_url: str | None = Field(default=None, max_length=320)
    contact_email: str | None = Field(default=None, max_length=320)
    phone_number: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=320)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=32)
    city: str | None = Field(default=None, max_length=120)
    state_or_region: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    tax_id: str | None = Field(default=None, max_length=64)
    registration_number: str | None = Field(default=None, max_length=64)


class MemberOut(_Strict):
    user_sub: UUID
    role: str
    status: str
    email: str | None = None
    display_name: str | None = None
    platform_role: str | None = None
    created_at: datetime
    updated_at: datetime
    # W2: set when the person left; the roster shows "Left" until the sweeper (30 days).
    left_at: datetime | None = None


class MemberListOut(_Strict):
    items: list[MemberOut]
    seat_meter: SeatMeter | None = None


class TenantCreateShort(_Strict):
    """Self-serve (W2): a name is all it takes; the long form stays for admin onboarding."""

    name: str = Field(min_length=1, max_length=80)


class DissolveRequest(_Strict):
    confirm_name: str = Field(min_length=1, max_length=200)


class DissolveOut(_Strict):
    status: str
    restore_until: datetime
    # The session moved to Personal (null when this session was elsewhere or cannot switch).
    token: TokenResponse | None = None


class LeaveOut(_Strict):
    # The session already moved to Personal; null only for a session that cannot switch.
    token: TokenResponse | None


class SeatMeter(_Strict):
    active: int
    limit: int | None


class MemberAdd(_Strict):
    user_sub: UUID | None = None
    email: str | None = Field(default=None, max_length=320)
    role: str = "viewer"


class MemberRoleUpdate(_Strict):
    role: str


class SwitchOut(_Strict):
    active_tenant: TenantSummary
    note: str


# ── Serialization ────────────────────────────────────────────────────────


def _tenant_out(row: asyncpg.Record, *, my_role: str | None = None) -> TenantOut:
    return TenantOut(
        id=row["id"],
        name=row["name"],
        display_name=row["display_name"],
        legal_name=row["legal_name"],
        slug=row["slug"],
        locale=row["locale"],
        timezone=row["timezone"],
        status=row["status"],
        is_active=row["is_active"],
        logo_url=row["logo_url"],
        has_logo=bool(row["logo_content_type"]),
        contact_email=row["contact_email"],
        phone_number=row["phone_number"],
        website=row["website"],
        address_line1=row["address_line1"],
        address_line2=row["address_line2"],
        postal_code=row["postal_code"],
        city=row["city"],
        state_or_region=row["state_or_region"],
        country=row["country"],
        tax_id=row["tax_id"],
        registration_number=row["registration_number"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        my_role=my_role,
    )


def _summary(row: asyncpg.Record, my_role: str) -> TenantSummary:
    return TenantSummary(
        id=row["id"],
        name=row["name"],
        display_name=row["display_name"],
        slug=row["slug"],
        status=row["status"],
        is_active=row["is_active"],
        logo_url=row["logo_url"],
        my_role=my_role,
        kind=row["kind"],
    )


def _member_out(row: asyncpg.Record) -> MemberOut:
    return MemberOut(
        user_sub=row["user_sub"],
        role=row["role"],
        status=row["status"],
        email=row["email"],
        display_name=row["display_name"],
        platform_role=primary_role(set(platform_roles_for(row["role"]))),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        left_at=row.get("left_at"),
    )


# ── Guards ───────────────────────────────────────────────────────────────


async def _my_membership_role(tenant_id: UUID, sub: UUID) -> str | None:
    """The caller's management role in ``tenant_id`` (writer pool: any tenant they belong to), or None."""
    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        m = await repo.get_membership(conn, tenant_id=tenant_id, user_sub=sub)
    return m["role"] if m is not None else None


async def _require_member(tenant_id: UUID, claims: Claims) -> str:
    role = await _my_membership_role(tenant_id, claims.sub)
    if role is None:
        # Never leak the existence of a tenant the caller cannot see.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    return role


async def manage_step_up(claims: Annotated[Claims, Depends(current_user)]) -> Claims:
    """Step-up for managing people (W2): MFA under Keycloak, a recent sign-in (300 s) in dual/native.

    MFA is optional for individuals, so requiring it would leave a free team unable to invite.
    """
    if settings.idp_mode == "keycloak":
        return await requires_mfa()(claims)
    return await recent_auth(claims)


def _require_active_tenant(tenant_id: UUID, claims: Claims) -> None:
    """Writes may only target the tenant the caller is authenticated into (the JWT is single-tenant)."""
    if tenant_id != claims.tid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "tenant management is scoped to your active tenant; "
                "switch to this tenant (and re-authenticate) before editing it"
            ),
        )


def _validate_slug(slug: str | None) -> None:
    if slug is not None and slug != "" and not _SLUG_RE.match(slug):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="slug must be lowercase alphanumeric with single hyphens (e.g. 'acme-inc')",
        )


# ── List / current / detail ──────────────────────────────────────────────


@router.get("", response_model=TenantListOut, summary="Tenants the caller belongs to")
async def list_tenants(claims: Annotated[Claims, Depends(current_user)]) -> TenantListOut:
    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, claims.tid) as conn:
        rows = await repo.list_tenants_for_user(conn, user_sub=claims.sub)
    return TenantListOut(items=[_summary(r, r["membership_role"]) for r in rows])


@router.get(
    "/current",
    response_model=TenantOut,
    summary="The caller's active tenant (from the JWT tid)",
)
async def current_tenant(
    claims: Annotated[Claims, Depends(requires("tenant.read", "tenant"))],
) -> TenantOut:
    state = get_state()
    async with tenant_connection(state.app_pool, claims.tid) as conn:
        row = await repo.get_tenant(conn, tenant_id=claims.tid)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    my_role = await _my_membership_role(claims.tid, claims.sub)
    return _tenant_out(row, my_role=my_role)


@router.get("/{tenant_id}", response_model=TenantOut, summary="Tenant profile / branding")
async def get_tenant(
    tenant_id: UUID,
    claims: Annotated[Claims, Depends(requires("tenant.read", "tenant"))],
) -> TenantOut:
    my_role = await _require_member(tenant_id, claims)
    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        row = await repo.get_tenant(conn, tenant_id=tenant_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    return _tenant_out(row, my_role=my_role)


# ── Create ───────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=TenantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a workspace: `{name}` for anyone signed in (self-serve), or the long admin form",
)
async def create_tenant(
    body: TenantCreateShort | TenantCreate,
    claims: Annotated[Claims, Depends(current_user)],
) -> TenantOut:
    if isinstance(body, TenantCreateShort):
        return await _create_self_serve(body, claims)
    # The long form is admin onboarding: the permission and MFA gates it always had.
    if not any(can(role, "tenant.create", "tenant") for role in claims.roles or ()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
    await requires_mfa()(claims)
    _validate_slug(body.slug)
    slug = body.slug or _slugify(body.name)
    state = get_state()
    try:
        async with tenant_connection(state.tenant_writer_pool, claims.tid) as conn:
            row = await repo.create_tenant(
                conn,
                name=body.name.strip(),
                display_name=body.display_name.strip(),
                slug=slug,
                legal_name=body.legal_name.strip(),
                locale=body.locale,
                timezone=body.timezone,
                contact_email=body.contact_email.strip(),
                phone_number=body.phone_number.strip(),
                website=body.website.strip(),
                address_line1=body.address_line1.strip(),
                address_line2=body.address_line2.strip(),
                postal_code=body.postal_code.strip(),
                city=body.city.strip(),
                state_or_region=body.state_or_region.strip(),
                country=body.country.strip(),
                tax_id=body.tax_id.strip(),
                registration_number=body.registration_number.strip(),
            )
            await repo.add_member(
                conn,
                tenant_id=row["id"],
                user_sub=claims.sub,
                role="owner",
                invited_by=claims.sub,
                status="active",
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a tenant with this name or slug already exists",
        ) from exc

    await _audit(
        claims,
        tenant_id=row["id"],
        kind=audit_kinds.TENANT_CREATED,
        target_id=row["id"],
        payload={"name": row["name"], "slug": slug},
        severity=Severity.SEC,
    )
    return _tenant_out(row, my_role="owner")


async def _create_self_serve(body: TenantCreateShort, claims: Claims) -> TenantOut:
    """W2: kind=team, plan=free, self_serve; `tenants.name` is UNIQUE, so it carries a short suffix."""
    display_name = body.name.strip()
    if not display_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="name is empty"
        )
    state = get_state()
    limiter = getattr(state, "limiter", None)
    if limiter is not None:
        decision = await limiter.allow(
            "tenant-create:identity", str(claims.sub), limit=10, window_seconds=86400
        )
        if not decision.allowed:
            raise as_problem(
                ApiError(
                    "rate_limited",
                    429,
                    detail="too many new workspaces today",
                    retry_after=decision.retry_after,
                )
            )
    identity = None
    services = getattr(state, "account_services", None)
    if services is not None:
        identity = await services.identities.get(claims.sub)
    base = _slugify(display_name)[:60] or "workspace"
    for _attempt in range(3):
        slug = f"{base}-{secrets.token_hex(3)}"
        try:
            async with tenant_connection(state.tenant_writer_pool, claims.tid) as conn:
                row = await repo.create_tenant(
                    conn,
                    name=slug,
                    display_name=display_name,
                    slug=slug,
                    locale=(identity.locale if identity else "en"),
                    timezone=(identity.timezone if identity else "UTC"),
                    plan="free",
                    signup_source="self_serve",
                    plan_limits=json.dumps(_free_limits()),
                )
                await repo.add_member(
                    conn,
                    tenant_id=row["id"],
                    user_sub=claims.sub,
                    role="owner",
                    invited_by=claims.sub,
                    status="active",
                )
            break
        except asyncpg.UniqueViolationError:
            continue
    else:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="could not name the workspace; try again"
        )
    auth_metrics.workspace_created_counter.add(1, {"source": "self_serve"})
    await _audit(
        claims,
        tenant_id=row["id"],
        kind=audit_kinds.TENANT_CREATED,
        target_id=row["id"],
        payload={"source": "self_serve", "kind": "team"},
        severity=Severity.SEC,
    )
    return _tenant_out(row, my_role="owner")


def _free_limits() -> dict[str, int]:
    from ..main_deps import _free_limits as free_limits

    return free_limits()


# ── Update ───────────────────────────────────────────────────────────────


@router.patch(
    "/{tenant_id}",
    response_model=TenantOut,
    summary="Update tenant profile / branding / contact fields",
    dependencies=[Depends(requires_mfa())],
)
async def update_tenant(
    tenant_id: UUID,
    body: TenantUpdate,
    claims: Annotated[Claims, Depends(requires("tenant.update", "tenant"))],
) -> TenantOut:
    _require_active_tenant(tenant_id, claims)
    my_role = await _require_member(tenant_id, claims)
    _require_manager(my_role)
    _validate_slug(body.slug)

    fields: dict[str, Any] = body.model_dump(exclude_unset=True)
    # Keep ``status`` in sync with ``is_active`` (active ⇄ suspended).
    if "is_active" in fields:
        fields["status"] = "active" if fields["is_active"] else "suspended"
    if "status" in fields:
        await _refuse_personal_status_change(tenant_id)
    for key in (
        "display_name",
        "legal_name",
        "contact_email",
        "phone_number",
        "website",
        "address_line1",
        "address_line2",
        "postal_code",
        "city",
        "state_or_region",
        "country",
        "tax_id",
        "registration_number",
        "slug",
    ):
        if key in fields and isinstance(fields[key], str):
            fields[key] = fields[key].strip()

    changed = sorted(body.model_dump(exclude_unset=True).keys())
    state = get_state()
    try:
        async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
            row = await repo.update_tenant(conn, tenant_id=tenant_id, fields=fields)
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="name or slug already in use"
        ) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    await _audit(
        claims,
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_UPDATED,
        target_id=tenant_id,
        payload={"fields": changed},
        severity=Severity.INFO,
    )
    return _tenant_out(row, my_role=my_role)


async def _refuse_personal_status_change(tenant_id: UUID) -> None:
    """A personal workspace is never suspended or dissolved (W1); renaming it stays allowed."""
    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        row = await repo.get_tenant(conn, tenant_id=tenant_id)
    if row is not None and row["kind"] == "personal":
        raise as_problem(
            ApiError(
                "personal_workspace",
                409,
                detail="a personal workspace cannot be suspended or dissolved",
            )
        )


# ── Logo ─────────────────────────────────────────────────────────────────


@router.put(
    "/{tenant_id}/logo",
    response_model=TenantOut,
    summary="Upload or replace the tenant logo (multipart image, ≤2MB)",
    dependencies=[Depends(requires_mfa())],
)
async def upload_logo(
    tenant_id: UUID,
    claims: Annotated[Claims, Depends(requires("tenant.update", "tenant"))],
    file: Annotated[UploadFile | None, File()] = None,
    logo_url: Annotated[str | None, Form()] = None,
) -> TenantOut:
    _require_active_tenant(tenant_id, claims)
    my_role = await _require_member(tenant_id, claims)
    _require_manager(my_role)

    if file is None and not logo_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide an image `file` or a `logo_url`",
        )

    logo_bytes: bytes | None = None
    content_type = ""
    if file is not None:
        content_type = file.content_type or ""
        if not content_type.startswith("image/"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="logo must be an image/* file",
            )
        logo_bytes = await file.read()
        if len(logo_bytes) > _MAX_LOGO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="logo exceeds the 2MB limit",
            )

    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        row = await repo.set_logo(
            conn,
            tenant_id=tenant_id,
            logo_bytes=logo_bytes,
            logo_content_type=content_type,
            logo_url=(logo_url or "").strip(),
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    await _audit(
        claims,
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_LOGO_UPDATED,
        target_id=tenant_id,
        payload={"inline": logo_bytes is not None, "size_bytes": len(logo_bytes or b"")},
        severity=Severity.INFO,
    )
    return _tenant_out(row, my_role=my_role)


@router.get(
    "/{tenant_id}/logo",
    summary="Fetch the tenant logo bytes (for branding / PDF preview)",
    responses={200: {"content": {"image/*": {}}}},
)
async def get_logo(
    tenant_id: UUID,
    claims: Annotated[Claims, Depends(requires("tenant.read", "tenant"))],
) -> Response:
    await _require_member(tenant_id, claims)
    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        logo = await repo.get_logo(conn, tenant_id=tenant_id)
    if logo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no logo set")
    data, content_type = logo
    return Response(
        content=data, media_type=content_type, headers={"Cache-Control": "private, max-age=300"}
    )


# ── Members ──────────────────────────────────────────────────────────────


@router.get(
    "/{tenant_id}/members",
    response_model=MemberListOut,
    summary="List the tenant's members",
)
async def list_members(
    tenant_id: UUID,
    claims: Annotated[Claims, Depends(requires("tenant.read", "tenant"))],
) -> MemberListOut:
    await _require_member(tenant_id, claims)
    state = get_state()
    # Writer pool so cross-tenant members resolve.
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        rows = await repo.list_members(conn, tenant_id=tenant_id)
        active, seat_limit = await repo.seat_meter(conn, tenant_id=tenant_id)
    return MemberListOut(
        items=[_member_out(r) for r in rows],
        seat_meter=SeatMeter(active=active, limit=seat_limit),
    )


@router.post(
    "/{tenant_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Link a principal to the tenant with a management role",
    dependencies=[Depends(manage_step_up)],
)
async def add_member(
    tenant_id: UUID,
    body: MemberAdd,
    claims: Annotated[Claims, Depends(requires("tenant.manage_members", "tenant"))],
) -> MemberOut:
    _require_active_tenant(tenant_id, claims)
    _require_manager(await _require_member(tenant_id, claims))
    _validate_management_role(body.role)

    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        user_sub = body.user_sub
        if user_sub is None and body.email and settings.idp_mode != "keycloak":
            # W2: people are brought in by invitation; nobody is added silently by address.
            raise as_problem(
                ApiError("use_invitations", 409, detail="invite people by e-mail instead")
            )
        if user_sub is None:
            if not body.email:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="provide a `user_sub` or an `email`",
                )
            user_sub = await repo.resolve_sub_by_email(
                conn, tenant_id=tenant_id, email=body.email.strip()
            )
            if user_sub is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="no user with that email in this tenant; add by user_sub instead",
                )
        try:
            member = await repo.add_member(
                conn,
                tenant_id=tenant_id,
                user_sub=user_sub,
                role=body.role,
                invited_by=claims.sub,
                status="active",
            )
        except asyncpg.UniqueViolationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="this user is already a member of the tenant",
            ) from exc

    await _audit(
        claims,
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_MEMBER_ADDED,
        target_id=user_sub,
        payload={"role": body.role},
        severity=Severity.SEC,
    )
    return MemberOut(
        user_sub=member["user_sub"],
        role=member["role"],
        status=member["status"],
        created_at=member["created_at"],
        updated_at=member["updated_at"],
    )


@router.patch(
    "/{tenant_id}/members/{sub}",
    response_model=MemberOut,
    summary="Change a member's management role",
    dependencies=[Depends(manage_step_up)],
)
async def update_member(
    tenant_id: UUID,
    sub: UUID,
    body: MemberRoleUpdate,
    claims: Annotated[Claims, Depends(requires("tenant.manage_members", "tenant"))],
) -> MemberOut:
    _require_active_tenant(tenant_id, claims)
    my_role = await _require_member(tenant_id, claims)
    _require_manager(my_role)
    _validate_management_role(body.role)

    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        existing = await repo.get_membership(conn, tenant_id=tenant_id, user_sub=sub)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
        _require_owner_for_owners(my_role, existing["role"], body.role)
        # Never leave a tenant ownerless.
        if existing["role"] == "owner" and body.role != "owner":
            remaining = await repo.count_active_owners(conn, tenant_id=tenant_id, exclude_sub=sub)
            if remaining == 0:
                raise as_problem(
                    ApiError("last_owner", 409, detail="cannot demote the last owner of the tenant")
                )
        member = await repo.update_member_role(
            conn, tenant_id=tenant_id, user_sub=sub, role=body.role
        )

    await _audit(
        claims,
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_MEMBER_ROLE_CHANGED,
        target_id=sub,
        payload={"old_role": existing["role"], "new_role": body.role},
        severity=Severity.SEC,
    )
    assert member is not None
    return MemberOut(
        user_sub=member["user_sub"],
        role=member["role"],
        status=member["status"],
        created_at=member["created_at"],
        updated_at=member["updated_at"],
    )


@router.delete(
    "/{tenant_id}/members/me",
    response_model=LeaveOut,
    summary='Leave this workspace (your row is kept as "Left" for 30 days); you land in Personal',
)
async def leave_workspace(
    tenant_id: UUID,
    claims: Annotated[Claims, Depends(current_user)],
) -> LeaveOut:
    my_role = await _require_member(tenant_id, claims)
    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        tenant = await repo.get_tenant(conn, tenant_id=tenant_id)
        if tenant is not None and tenant["kind"] == "personal":
            raise as_problem(
                ApiError("personal_workspace", 409, detail="nobody leaves their personal workspace")
            )
        if my_role == "owner":
            others = await repo.count_active_owners(
                conn, tenant_id=tenant_id, exclude_sub=claims.sub
            )
            if others == 0:
                raise as_problem(
                    ApiError(
                        "last_owner", 409, detail="make someone else an owner before you leave"
                    )
                )
        await repo.leave(conn, tenant_id=tenant_id, user_sub=claims.sub)
    auth_metrics.member_left_counter.add(1)
    await _audit(
        claims,
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_MEMBER_LEFT,
        target_id=claims.sub,
        payload={"role": my_role},
        severity=Severity.SEC,
    )
    # Only the workspace this session is in moves it; leaving another one changes nothing here.
    token = await _move_to_personal(claims) if claims.tid == tenant_id else None
    return LeaveOut(token=token)


@router.post(
    "/{tenant_id}/dissolve",
    response_model=DissolveOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Dissolve an empty team workspace (owner; type its name). Restorable for 30 days",
    dependencies=[Depends(manage_step_up)],
)
async def dissolve_workspace(
    tenant_id: UUID,
    body: DissolveRequest,
    claims: Annotated[Claims, Depends(current_user)],
) -> DissolveOut:
    my_role = await _require_member(tenant_id, claims)
    if my_role != "owner":
        raise as_problem(ApiError("owner_only", 403, detail="only an owner can dissolve"))
    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        tenant = await repo.get_tenant(conn, tenant_id=tenant_id)
        if tenant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
        if tenant["kind"] == "personal":
            raise as_problem(
                ApiError(
                    "personal_workspace", 409, detail="a personal workspace is never dissolved"
                )
            )
        typed = body.confirm_name.strip().casefold()
        if typed not in {tenant["display_name"].strip().casefold(), tenant["name"].casefold()}:
            raise as_problem(
                ApiError("confirm_name_mismatch", 422, detail="type the workspace name to confirm")
            )
        if await repo.count_other_active_members(conn, tenant_id=tenant_id, user_sub=claims.sub):
            raise as_problem(
                ApiError("has_other_members", 409, detail="remove the other members first")
            )
        await repo.dissolve(conn, tenant_id=tenant_id)
    revoked = 0
    service = getattr(state, "invitation_service", None)
    if service is not None:
        revoked = await service.revoke_all_for_tenant(tenant_id, actor=claims.sub)
    auth_metrics.workspace_dissolved_counter.add(1)
    await _audit(
        claims,
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_DISSOLVED,
        target_id=tenant_id,
        payload={"revoked_invitations": revoked},
        severity=Severity.SEC,
    )
    # Other sessions heal to Personal on their next refresh; do it now for this one.
    token = await _move_to_personal(claims) if claims.tid == tenant_id else None
    return DissolveOut(
        status="dissolved", restore_until=datetime.now(UTC) + timedelta(days=30), token=token
    )


async def _move_to_personal(claims: Claims) -> TokenResponse | None:
    """Switch this session to the caller's Personal workspace; None if it cannot (Keycloak-era)."""
    state = get_state()
    sessions = getattr(state, "session_service", None)
    services = getattr(state, "account_services", None)
    if sessions is None or services is None:
        return None
    memberships = await services.identities.list_memberships(claims.sub)
    personal = next((m for m in memberships if m.kind == "personal"), None)
    if personal is None:
        return None
    try:
        switched = await sessions.switch_tenant(
            session_id=UUID(claims.sid),
            identity_id=claims.sub,
            tenant_id=personal.tenant_id,
            activate=True,
        )
    except (ApiError, ValueError, TypeError) as exc:
        logger.info("tenant.move_to_personal_skipped", extra={"error_class": type(exc).__name__})
        return None
    return TokenResponse(
        access_token=switched.access_token,
        expires_in=switched.expires_in,
        tenant_id=str(switched.tenant_id),
        roles=switched.roles,
    )


@router.delete(
    "/{tenant_id}/members/{sub}",
    status_code=status.HTTP_200_OK,
    summary="Remove a member from the tenant",
    dependencies=[Depends(manage_step_up)],
)
async def remove_member(
    tenant_id: UUID,
    sub: UUID,
    claims: Annotated[Claims, Depends(requires("tenant.manage_members", "tenant"))],
) -> dict[str, Any]:
    _require_active_tenant(tenant_id, claims)
    my_role = await _require_member(tenant_id, claims)
    _require_manager(my_role)

    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        existing = await repo.get_membership(conn, tenant_id=tenant_id, user_sub=sub)
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
        _require_owner_for_owners(my_role, existing["role"], None)
        if existing["role"] == "owner":
            remaining = await repo.count_active_owners(conn, tenant_id=tenant_id, exclude_sub=sub)
            if remaining == 0:
                raise as_problem(
                    ApiError("last_owner", 409, detail="cannot remove the last owner of the tenant")
                )
        await repo.remove_member(conn, tenant_id=tenant_id, user_sub=sub)

    await _notify_removed(tenant_id=tenant_id, removed=sub, actor=claims.sub)
    await _audit(
        claims,
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_MEMBER_REMOVED,
        target_id=sub,
        payload={"role": existing["role"]},
        severity=Severity.SEC,
    )
    return {"tenant_id": str(tenant_id), "user_sub": str(sub), "removed": True}


# ── Switch active tenant ─────────────────────────────────────────────────


@router.post(
    "/{tenant_id}/switch",
    response_model=SwitchOut,
    summary="Select the caller's active tenant (must be a member)",
)
async def switch_tenant(
    tenant_id: UUID,
    claims: Annotated[Claims, Depends(current_user)],
) -> SwitchOut:
    """Validate that the caller may act as ``tenant_id`` and record the switch.

    NOTE: the access token's ``tid`` — which drives RLS — is issued by
    Keycloak and is single-tenant in the pilot. A full switch therefore
    requires the SPA to obtain a token re-scoped to ``tenant_id`` (future
    Keycloak per-tenant identity work). This endpoint is the authorization
    gate + audit hook for that flow, and returns the selected tenant so the
    SPA can update its active-tenant UI immediately.
    """
    my_role = await _require_member(tenant_id, claims)
    state = get_state()
    async with tenant_connection(state.tenant_writer_pool, tenant_id) as conn:
        row = await repo.get_tenant(conn, tenant_id=tenant_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    await _audit(
        claims,
        tenant_id=tenant_id,
        kind=audit_kinds.TENANT_SWITCHED,
        target_id=tenant_id,
        payload={"from": str(claims.tid), "to": str(tenant_id)},
        severity=Severity.INFO,
    )
    note = (
        "active tenant selected"
        if tenant_id == claims.tid
        else "re-authenticate to obtain a token scoped to this tenant before accessing its data"
    )
    return SwitchOut(active_tenant=_summary(row, my_role), note=note)


# ── helpers ──────────────────────────────────────────────────────────────


async def _notify_removed(*, tenant_id: UUID, removed: UUID, actor: UUID) -> None:
    """W2: the removed person hears about it in their Personal workspace (best-effort)."""
    state = get_state()
    services = getattr(state, "account_services", None)
    if services is None:
        return
    try:
        memberships = await services.identities.list_memberships(removed)
        personal = next((m for m in memberships if m.kind == "personal"), None)
        if personal is not None:
            await emit_member_removed(
                state.notification_bus,
                personal_tenant_id=personal.tenant_id,
                workspace_id=tenant_id,
                removed=removed,
                actor=actor,
            )
    except Exception as exc:  # noqa: BLE001 — the removal is committed
        logger.warning(
            "tenant.member_removed_notify_failed", extra={"error_class": type(exc).__name__}
        )


def _require_owner_for_owners(my_role: str, target_role: str, new_role: str | None) -> None:
    """Only an owner changes, removes or creates an owner (W2/WEB): an admin manages everyone else."""
    if my_role != "owner" and "owner" in (target_role, new_role):
        raise as_problem(
            ApiError("owner_only", 403, detail="only an owner can change an owner's membership")
        )


def _require_manager(role: str) -> None:
    if role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"membership role {role!r} may not manage this tenant (owner/admin only)",
        )


def _validate_management_role(role: str) -> None:
    if role not in MANAGEMENT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"role must be one of {sorted(MANAGEMENT_ROLES)}",
        )


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "tenant"


async def _audit(
    claims: Claims,
    *,
    tenant_id: UUID,
    kind: str,
    target_id: UUID,
    payload: dict[str, Any],
    severity: Severity,
) -> None:
    state = get_state()
    try:
        await state.audit_writer.write_event(
            tenant_id=tenant_id,
            kind=kind,
            actor_sub=claims.sub,
            actor_role=(claims.roles[0] if claims.roles else None),
            target_kind="tenant",
            target_id=str(target_id),
            payload=payload,
            severity=severity,
        )
    except Exception as exc:  # pragma: no cover - audit must never break the write
        logger.warning("tenant.audit_write_failed", extra={"kind": kind, "error": str(exc)})
