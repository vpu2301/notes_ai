"""Managing credentials for non-human principals (IDX-B1b F3).

Two audiences, two gates:

* ``/admin/credentials`` — platform operators. There is no "platform
  owner" role in the matrix; the closest true thing is a ``tenant_admin``
  whose ``tid`` **is the platform tenant**, which is exactly what a
  platform operator is in this data model. Both conditions are checked.
* ``/tenants/{id}/devices`` — a workspace's own owners and admins,
  checked against their membership row.

IDX-B1 is meant to supply a `device.manage` policy for the second gate.
It has not been run, so the check here is the same explicit owner/admin
membership lookup IDX-A5 uses for admin MFA reset, and
``docs/auth/permissions.csv`` carries the `device.manage` row ready for
B1 to wire onto the policy engine. The behaviour is the pack's; only the
mechanism is interim.

Every mutating route requires recent auth. Creating a room credential
mints a secret that can upload recordings into a workspace, and rotating
or revoking one can take a room offline — an unlocked laptop must not be
enough for any of them.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims

from .. import audit_kinds
from ..config import settings
from ..deps import current_user
from ..domain.credential_repository import Credential
from ..domain.credential_service import (
    DEFAULT_ROTATION_TTL_SECONDS,
    CredentialError,
    CredentialService,
)
from ..domain.errors import ApiError
from ..domain.identity_repository import Identity
from .native_common import (
    as_problem,
    audit,
    current_identity,
    native_services,
    platform_tenant,
    recent_auth,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["credentials"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecretOut(_Strict):
    prefix: str
    expires_at: datetime | None
    created_at: datetime


class CredentialOut(_Strict):
    id: str
    kind: str
    tenant_id: str | None
    name: str
    roles: list[str]
    status: str
    last_used_at: datetime | None
    created_at: datetime
    secrets: list[SecretOut] = Field(default_factory=list)


class CreatedOut(_Strict):
    """The only response that ever carries a secret."""

    credential: CredentialOut
    secret: str


class RotatedOut(_Strict):
    secret: str
    old_expires_at: datetime


class CreateServiceIn(_Strict):
    kind: Literal["service", "device"] = "service"
    name: str = Field(min_length=1, max_length=120)
    # Only meaningful for kind="device": the pack's cut-down path, so an
    # operator can provision a room before the workspace routes exist.
    tenant_id: UUID | None = None


class CreateDeviceIn(_Strict):
    name: str = Field(min_length=1, max_length=120)


class RotateIn(_Strict):
    old_secret_ttl_s: int | None = None


def _out(credential: Credential, secrets: list[SecretOut] | None = None) -> CredentialOut:
    return CredentialOut(
        id=str(credential.id),
        kind=credential.kind,
        tenant_id=str(credential.tenant_id) if credential.tenant_id else None,
        name=credential.name,
        roles=list(credential.roles),
        status=credential.status,
        last_used_at=credential.last_used_at,
        created_at=credential.created_at,
        secrets=secrets or [],
    )


async def _svc() -> CredentialService:
    services = native_services()
    credentials: CredentialService | None = services.credentials
    if credentials is None:
        raise as_problem(ApiError("not_found", 404, detail="Not Found"))
    return credentials


async def platform_operator(
    claims: Annotated[Claims, Depends(current_user)],
) -> Claims:
    """A `tenant_admin` acting inside the platform tenant.

    Both halves are load-bearing. The role alone would let any workspace's
    admin mint platform-wide service credentials; the tenant alone would
    let any member of the platform tenant do it.
    """
    if str(claims.tid) != platform_tenant() or "tenant_admin" not in claims.roles:
        raise as_problem(ApiError("not_a_member", 403, detail="platform operators only"))
    return claims


async def _require_workspace_admin(identity: Identity, tenant_id: UUID) -> str:
    """The interim `device.manage` gate — owner or admin of THIS workspace."""
    services = native_services()
    for membership in await services.identities.list_memberships(identity.id):
        if membership.tenant_id == tenant_id:
            if membership.role in {"owner", "admin"}:
                return str(membership.role)
            break
    # 404, not 403: a workspace this person does not administer should not
    # be confirmed to exist by the error they get for asking.
    raise as_problem(ApiError("not_found", 404, detail="no such workspace"))


# ── operator surface ─────────────────────────────────────────────────────


@router.post(
    "/admin/credentials",
    response_model=CreatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(platform_operator), Depends(recent_auth)],
    summary="Create a service or device credential (platform operators)",
)
async def create_credential(
    body: CreateServiceIn,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> CreatedOut:
    svc = await _svc()
    try:
        created = await svc.create(
            kind=body.kind,
            tenant_id=body.tenant_id if body.kind == "device" else None,
            name=body.name,
            created_by=identity.id,
        )
    except CredentialError as exc:
        raise as_problem(exc) from exc
    await _audit_lifecycle(credential=created.credential, action="created", actor=identity.id)
    return CreatedOut(credential=_out(created.credential), secret=created.secret)


@router.get(
    "/admin/credentials",
    response_model=list[CredentialOut],
    dependencies=[Depends(platform_operator)],
    summary="List service credentials (never their secrets)",
)
async def list_credentials() -> list[CredentialOut]:
    svc = await _svc()
    out = []
    for credential in await svc.list_services():
        refs = await svc.secrets_of(credential.id)
        out.append(
            _out(
                credential,
                [
                    SecretOut(prefix=r.prefix, expires_at=r.expires_at, created_at=r.created_at)
                    for r in refs
                ],
            )
        )
    return out


@router.post(
    "/admin/credentials/{credential_id}/rotate",
    response_model=RotatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(platform_operator), Depends(recent_auth)],
    summary="Issue a second live secret; the old one expires later",
)
async def rotate_credential(
    credential_id: UUID,
    body: RotateIn,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> RotatedOut:
    svc = await _svc()
    try:
        secret, expires_at = await svc.rotate(credential_id, old_ttl_seconds=body.old_secret_ttl_s)
    except CredentialError as exc:
        raise as_problem(exc) from exc
    credential = await svc.get(credential_id)
    assert credential is not None
    await _audit_lifecycle(credential=credential, action="rotated", actor=identity.id)
    return RotatedOut(secret=secret, old_expires_at=expires_at)


@router.delete(
    "/admin/credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(platform_operator), Depends(recent_auth)],
    summary="Revoke a credential and every secret it holds",
)
async def revoke_credential(
    credential_id: UUID,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> Response:
    svc = await _svc()
    try:
        credential = await svc.revoke(credential_id)
    except CredentialError as exc:
        raise as_problem(exc) from exc
    await _audit_lifecycle(credential=credential, action="revoked", actor=identity.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── workspace surface ────────────────────────────────────────────────────


@router.post(
    "/tenants/{tenant_id}/devices",
    response_model=CreatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(recent_auth)],
    summary="Register a meeting-room capture device in this workspace",
)
async def create_device(
    tenant_id: UUID,
    body: CreateDeviceIn,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> CreatedOut:
    await _require_workspace_admin(identity, tenant_id)
    services = native_services()
    workspace = next(
        (
            m
            for m in await services.identities.list_memberships(identity.id)
            if m.tenant_id == tenant_id
        ),
        None,
    )
    if workspace is not None and workspace.kind == "personal":
        # A personal workspace has exactly one member and no meeting room.
        # Allowing it would create a credential nobody would ever deploy,
        # and a secret nobody would ever rotate.
        raise as_problem(
            ApiError(
                "personal_workspace",
                409,
                detail="a personal workspace cannot have room devices",
            )
        )
    svc = await _svc()
    try:
        created = await svc.create(
            kind="device", tenant_id=tenant_id, name=body.name, created_by=identity.id
        )
    except CredentialError as exc:
        raise as_problem(exc) from exc
    await _audit_lifecycle(credential=created.credential, action="created", actor=identity.id)
    return CreatedOut(credential=_out(created.credential), secret=created.secret)


@router.get(
    "/tenants/{tenant_id}/devices",
    response_model=list[CredentialOut],
    summary="List this workspace's capture devices",
)
async def list_devices(
    tenant_id: UUID,
    identity: Annotated[Identity, Depends(current_identity)],
) -> list[CredentialOut]:
    await _require_workspace_admin(identity, tenant_id)
    svc = await _svc()
    out = []
    for credential in await svc.list_devices(tenant_id):
        refs = await svc.secrets_of(credential.id)
        out.append(
            _out(
                credential,
                [
                    SecretOut(prefix=r.prefix, expires_at=r.expires_at, created_at=r.created_at)
                    for r in refs
                ],
            )
        )
    return out


@router.post(
    "/tenants/{tenant_id}/devices/{credential_id}/rotate",
    response_model=RotatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(recent_auth)],
    summary="Re-key a device without taking it offline",
)
async def rotate_device(
    tenant_id: UUID,
    credential_id: UUID,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> RotatedOut:
    await _require_workspace_admin(identity, tenant_id)
    svc = await _svc()
    await _device_of_tenant(svc, credential_id, tenant_id)
    try:
        secret, expires_at = await svc.rotate(
            credential_id, old_ttl_seconds=DEFAULT_ROTATION_TTL_SECONDS
        )
    except CredentialError as exc:
        raise as_problem(exc) from exc
    credential = await svc.get(credential_id)
    assert credential is not None
    await _audit_lifecycle(credential=credential, action="rotated", actor=identity.id)
    return RotatedOut(secret=secret, old_expires_at=expires_at)


@router.delete(
    "/tenants/{tenant_id}/devices/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(recent_auth)],
    summary="Revoke a device; its live token stops working immediately",
)
async def revoke_device(
    tenant_id: UUID,
    credential_id: UUID,
    identity: Annotated[Identity, Depends(current_identity)],
    claims: Annotated[Claims, Depends(current_user)],
) -> Response:
    await _require_workspace_admin(identity, tenant_id)
    svc = await _svc()
    await _device_of_tenant(svc, credential_id, tenant_id)
    try:
        credential = await svc.revoke(credential_id)
    except CredentialError as exc:
        raise as_problem(exc) from exc
    await _audit_lifecycle(credential=credential, action="revoked", actor=identity.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _device_of_tenant(
    svc: CredentialService, credential_id: UUID, tenant_id: UUID
) -> Credential:
    """404 for a credential that is not this workspace's device.

    The tenant is checked here rather than trusted from the path, so a
    workspace admin cannot rotate or revoke another workspace's room by
    guessing its id.
    """
    credential: Credential | None = await svc.get(credential_id)
    if credential is None or credential.kind != "device" or credential.tenant_id != tenant_id:
        raise as_problem(ApiError("not_found", 404, detail="no such device"))
    return credential


async def _audit_lifecycle(*, credential: Credential, action: str, actor: UUID) -> None:
    """`credential.created|rotated|revoked`, on the right chain.

    A device's lifecycle belongs to its workspace's audit trail — that is
    where somebody investigating a recording will look. A service
    credential has no workspace, so it goes to the platform tenant.
    """
    kind_map = {
        "created": audit_kinds.CREDENTIAL_CREATED,
        "rotated": audit_kinds.CREDENTIAL_ROTATED,
        "revoked": audit_kinds.CREDENTIAL_REVOKED,
    }
    await audit(
        tenant_id=credential.tenant_id or UUID(settings.auth_platform_tenant_id),
        kind=kind_map[action],
        payload={
            "credential_id": str(credential.id),
            "kind": credential.kind,
            "name": credential.name,
        },
        severity=Severity.SEC,
        actor_sub=actor,
        target_id=credential.id,
    )
