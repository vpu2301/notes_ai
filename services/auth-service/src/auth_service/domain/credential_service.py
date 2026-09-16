"""The `client_credentials` grant and credential lifecycle (IDX-B1b F2/F4).

Two things here are unlike everything else in this program:

**The lock fails CLOSED.** Every other Redis-backed control in the estate
fails open, because locking people out of their own accounts because a
cache blinked is the worse failure. Not this one. The alternative here is
unlimited secret guessing at the rate limit's ceiling against a
credential that never gets tired, never notices, and holds a token for a
whole workspace's recordings. A room that cannot be verified as unlocked
waits and retries with backoff — which the devices already do for network
errors, so the degraded behaviour is one they are built for.

**A successful grant writes no audit row.** A single room fetches around
96 tokens a day. Recording each one would put a workspace's audit chain —
the thing an auditor reads to reconstruct what happened — several
thousand rows deep in "a device asked for a token and got one". Success
is a metric; failure is an audit row, because failure is the shape of
somebody guessing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from opentelemetry import metrics

from ..adapters.client_lock import LockUnavailableError
from . import credentials as cred
from .credential_repository import Credential, CredentialRepository, SecretRef
from .errors import ApiError
from .token_service import TokenService

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.auth")
_grant_counter = _meter.create_counter(
    "mdx_auth_client_credentials_total",
    description="client_credentials grants by kind and outcome",
    unit="1",
)
_lifecycle_counter = _meter.create_counter(
    "mdx_auth_credential_total",
    description="Credential lifecycle actions",
    unit="1",
)
_denylist_failed_counter = _meter.create_counter(
    "mdx_auth_denylist_push_failed_total",
    description="Revocations that failed to reach the session denylist",
    unit="1",
)

SCOPE_RATE = "client_token"

RATE_LIMIT = 60
RATE_WINDOW_SECONDS = 60
LOCK_THRESHOLD = 10
LOCK_WINDOW_SECONDS = 600
LOCK_SECONDS = 900

DEFAULT_ROTATION_TTL_SECONDS = 86_400  # 24 h
MAX_ROTATION_TTL_SECONDS = 604_800  # 7 d
MAX_LIVE_SECRETS = 2


class CredentialError(ApiError):
    """A refusal from the credential surface. See :class:`ApiError`.

    ``tripped_lock`` says this particular failure was the one that locked
    the client, so the route can write the `auth.client_locked` security
    event exactly once. It rides on the exception rather than on the
    service because the service is a shared singleton — an attribute
    there would be read by whichever request got there first.
    """

    tripped_lock: bool = False


class Limiter(Protocol):
    async def allow(
        self,
        scope: str,
        subject: str,
        *,
        limit: int,
        window_seconds: int,
        fail_open: bool = True,
        cost: int = 1,
    ) -> Any: ...


class Denylist(Protocol):
    async def revoke_sub(self, sub: str, *, ttl_seconds: int) -> None: ...


class ClientLock(Protocol):
    """See :mod:`auth_service.adapters.client_lock`. ``is_locked`` raises
    when the backend is unreachable — the caller must refuse, not allow."""

    async def is_locked(self, subject: str) -> bool: ...

    async def record_failure(self, subject: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class IssuedToken:
    access_token: str
    expires_in: int
    credential: Credential


@dataclass(frozen=True, slots=True)
class CreatedCredential:
    credential: Credential
    secret: str


class CredentialService:
    def __init__(
        self,
        *,
        repo: CredentialRepository,
        tokens: TokenService,
        limiter: Limiter | None,
        lock: ClientLock | None,
        denylist: Denylist | None,
        platform_tenant_id: UUID,
        revoked_ttl_seconds: int,
        clock: Any = None,
    ) -> None:
        self._repo = repo
        self._tokens = tokens
        self._limiter = limiter
        self._lock = lock
        self._denylist = denylist
        self._platform_tenant_id = platform_tenant_id
        self._revoked_ttl = revoked_ttl_seconds
        self._now = clock or (lambda: datetime.now(UTC))

    # ── the grant (F2) ───────────────────────────────────────────────

    async def issue_token(self, *, client_id: str, client_secret: str, ip: str) -> IssuedToken:
        """RFC 6749 §4.4. Every refusal answers the same `invalid_client`.

        One body for "no such client", "wrong secret", "revoked secret"
        and "revoked credential", because telling them apart would let
        somebody enumerate which rooms exist by their error messages.
        """
        subject = _subject(client_id)
        await self._check_locked(subject)
        await self._check_rate(subject)

        credential_id = _parse_uuid(client_id)
        if credential_id is None or not cred.looks_like_secret(client_secret):
            raise _invalid_client(
                await self._register_failure(
                    subject, client_id=client_id, ip=ip, reason="malformed"
                )
            )

        found = await self._repo.find_by_secret_hash(cred.secret_hash(client_secret))
        if found is None:
            raise _invalid_client(
                await self._register_failure(subject, client_id=client_id, ip=ip, reason="no_match")
            )

        credential, _secret_id = found
        # The secret resolved to *a* credential; it must be the one being
        # claimed. Without this, a valid secret for room A would open a
        # token for room B by simply changing the client_id.
        if credential.id != credential_id:
            raise _invalid_client(
                await self._register_failure(subject, client_id=client_id, ip=ip, reason="mismatch")
            )
        if not credential.active:
            raise _invalid_client(
                await self._register_failure(subject, client_id=client_id, ip=ip, reason="revoked")
            )

        minted = self._tokens.mint(
            identity_id=credential.id,
            # `Claims.sid` is required and a client credential has no
            # session, so the credential's own id stands in. That makes
            # `sid == sub`, which is honest (there is exactly one "session"
            # per credential, forever) and useful: a denylist push against
            # either key revokes the credential.
            session_id=str(credential.id),
            tenant_id=self._tid_for(credential),
            roles=credential.roles,
        )
        await self._repo.touch_used(credential.id)
        _grant_counter.add(1, {"kind": credential.kind, "result": "ok"})
        logger.info(
            "auth.client_credentials.issued",
            extra={"credential_id": str(credential.id), "kind": credential.kind},
        )
        return IssuedToken(
            access_token=minted.token,
            expires_in=minted.expires_in,
            credential=credential,
        )

    def _tid_for(self, credential: Credential) -> UUID:
        """The `tid` claim. Never taken from the request.

        A device's workspace comes from its row, so a room cannot ask to
        be somewhere else. A service credential has no workspace at all
        (migration 0026 forbids one), and ``Claims.tid`` is required — so
        it is minted against the platform tenant, which owns no customer
        data. A service token is therefore useless for reaching a
        customer's notes, which is the correct default for a principal
        nobody has scoped yet.
        """
        if credential.tenant_id is not None:
            return credential.tenant_id
        return self._platform_tenant_id

    async def _check_rate(self, subject: str) -> None:
        if self._limiter is None:
            return
        decision = await self._limiter.allow(
            SCOPE_RATE,
            subject,
            limit=RATE_LIMIT,
            window_seconds=RATE_WINDOW_SECONDS,
            fail_open=True,
        )
        if not decision.allowed:
            _grant_counter.add(1, {"kind": "unknown", "result": "rate_limited"})
            raise CredentialError(
                "client_rate_limited",
                429,
                detail="too many token requests",
                retry_after=decision.retry_after,
            )

    async def _check_locked(self, subject: str) -> None:
        """Fail CLOSED — see the module docstring.

        A client we cannot verify as unlocked is refused with 503 and a
        `Retry-After`, not let through. This is the one place in the
        program where availability yields to correctness.
        """
        if self._lock is None:
            return
        try:
            locked = await self._lock.is_locked(subject)
        except LockUnavailableError as exc:
            _grant_counter.add(1, {"kind": "unknown", "result": "locked"})
            raise CredentialError(
                "try_again",
                503,
                detail="cannot verify this client right now",
                retry_after=5,
            ) from exc
        if locked:
            _grant_counter.add(1, {"kind": "unknown", "result": "locked"})
            raise CredentialError(
                "client_locked",
                423,
                detail="too many failed attempts; this client is temporarily locked",
                retry_after=LOCK_SECONDS,
            )

    async def _register_failure(
        self, subject: str, *, client_id: str, ip: str, reason: str
    ) -> bool:
        """Count one wrong secret. True when this one tripped the lock."""
        _grant_counter.add(1, {"kind": "unknown", "result": "invalid"})
        logger.warning(
            "auth.client_credentials.failed",
            # `client_id` is an opaque UUID, never the secret. The reason
            # is for us; the client is told only `invalid_client`.
            extra={"client_id": client_id[:64], "reason": reason},
        )
        del ip  # hashed and recorded by the route's audit row, not here
        if self._lock is None:
            return False
        if await self._lock.record_failure(subject):
            logger.warning("auth.client_locked", extra={"client_id": client_id[:64]})
            return True
        return False

    # ── lifecycle (F3/F4) ────────────────────────────────────────────

    async def create(
        self,
        *,
        kind: str,
        tenant_id: UUID | None,
        name: str,
        created_by: UUID | None,
    ) -> CreatedCredential:
        if kind not in cred.ROLES_FOR_KIND:
            raise CredentialError("invalid_request", 400, detail=f"unknown kind {kind!r}")
        if kind == cred.KIND_DEVICE and tenant_id is None:
            raise CredentialError("invalid_request", 400, detail="a device belongs to a workspace")
        if kind == cred.KIND_SERVICE and tenant_id is not None:
            raise CredentialError(
                "invalid_request", 400, detail="a service credential has no workspace"
            )
        name = (name or "").strip()
        if not name:
            raise CredentialError("invalid_request", 400, detail="a name is required")

        secret = cred.generate_secret()
        credential = await self._repo.create(
            kind=kind,
            tenant_id=tenant_id,
            name=name,
            created_by=created_by,
            secret_hash=secret.hash_hex,
            secret_prefix=secret.prefix,
        )
        _lifecycle_counter.add(1, {"action": "created", "kind": kind})
        return CreatedCredential(credential=credential, secret=secret.value)

    async def rotate(
        self, credential_id: UUID, *, old_ttl_seconds: int | None = None
    ) -> tuple[str, datetime]:
        """Issue a second live secret. Returns ``(secret, old_expires_at)``."""
        credential = await self._repo.get(credential_id)
        if credential is None or not credential.active:
            raise CredentialError("not_found", 404, detail="no such credential")
        live = await self._repo.live_secrets(credential_id)
        if len(live) >= MAX_LIVE_SECRETS:
            # A third live secret would make "which one is deployed"
            # unanswerable, which is the state rotation exists to avoid.
            raise CredentialError(
                "rotation_in_progress",
                409,
                detail="this credential already has two live secrets",
            )
        ttl = old_ttl_seconds if old_ttl_seconds is not None else DEFAULT_ROTATION_TTL_SECONDS
        if not 0 < ttl <= MAX_ROTATION_TTL_SECONDS:
            raise CredentialError(
                "invalid_request",
                400,
                detail=f"old_secret_ttl_s must be between 1 and {MAX_ROTATION_TTL_SECONDS}",
            )
        secret = cred.generate_secret()
        expires_at = await self._repo.add_secret_and_expire_others(
            credential_id,
            secret_hash=secret.hash_hex,
            secret_prefix=secret.prefix,
            old_ttl_seconds=ttl,
        )
        _lifecycle_counter.add(1, {"action": "rotated", "kind": credential.kind})
        return secret.value, expires_at

    async def revoke(self, credential_id: UUID) -> Credential:
        credential = await self._repo.get(credential_id)
        if credential is None or not credential.active:
            raise CredentialError("not_found", 404, detail="no such credential")
        await self._repo.revoke(credential_id)
        # The database row stops the next grant; the denylist stops the
        # token already in the device's hands. Only both together make
        # revocation immediate (ADR-0040).
        if self._denylist is not None:
            try:
                await self._denylist.revoke_sub(str(credential_id), ttl_seconds=self._revoked_ttl)
            except Exception as exc:  # noqa: BLE001
                _denylist_failed_counter.add(1, {"key": "sub"})
                logger.error(
                    "auth.credential.denylist_push_failed",
                    extra={"credential_id": str(credential_id), "error_class": type(exc).__name__},
                )
        _lifecycle_counter.add(1, {"action": "revoked", "kind": credential.kind})
        return credential

    async def get(self, credential_id: UUID) -> Credential | None:
        return await self._repo.get(credential_id)

    async def list_devices(self, tenant_id: UUID) -> list[Credential]:
        return await self._repo.list_for_tenant(tenant_id)

    async def list_services(self) -> list[Credential]:
        return await self._repo.list_services()

    async def secrets_of(self, credential_id: UUID) -> list[SecretRef]:
        return await self._repo.live_secrets(credential_id)


def _invalid_client(tripped_lock: bool = False) -> CredentialError:
    exc = CredentialError("invalid_client", 401, detail="client authentication failed")
    exc.tripped_lock = tripped_lock
    return exc


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


def _subject(client_id: str) -> str:
    """The rate-limit / lock key. Bounded, so an attacker-chosen client_id
    cannot become an unbounded Redis key."""
    return (client_id or "unknown")[:64]
