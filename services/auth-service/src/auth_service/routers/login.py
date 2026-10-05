"""POST /auth/login, /auth/refresh, /auth/logout proxied to Keycloak (keycloak/dual modes).

``X-Client-Type`` decides where the refresh token travels: HttpOnly cookie for
browsers, JSON body for native clients. A re-used refresh is audited as a replay.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import verify_token

from .. import audit_kinds, auth_metrics
from ..config import settings
from ..deps import get_state
from ..domain.transport import TokenResponse, client_type_of, token_response
from ..keycloak_client import KeycloakError
from ..main_deps import auth_issuers

# Shared with `session_native`: one declaration per instrument name.
_login_counter = auth_metrics.login_counter
_refresh_replay_counter = auth_metrics.refresh_replay_counter
_logout_counter = auth_metrics.logout_counter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RefreshRequest(_Strict):
    """Native clients send their token here; browsers send nothing at all.

    Optional rather than required so one route serves both transports —
    a browser POSTing an empty body must not be answered 422 for
    declining to put its HttpOnly cookie in a field it cannot read.

    The cap is 4096 rather than `session_native`'s 512: a Keycloak
    refresh token is a signed JWT carrying a realm's worth of claims, not
    the short opaque handle the native issuer mints.
    """

    refresh_token: str | None = Field(default=None, min_length=1, max_length=4096)


class LogoutRequest(_Strict):
    refresh_token: str | None = Field(default=None, min_length=1, max_length=4096)


def _presented_token(request: Request, body: RefreshRequest | LogoutRequest | None) -> str | None:
    """The body's token wins over the cookie."""
    if body is not None and body.refresh_token:
        return body.refresh_token
    return request.cookies.get(settings.auth_cookie_name)


async def _extract_credentials(request: Request) -> tuple[str, str, str | None]:
    """Credentials from a JSON body or a form (`email`/`username`, `password`, optional `otp`); 422 if missing."""
    content_type = request.headers.get("content-type", "")
    data: dict[str, Any]
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid JSON body") from exc
    else:
        form = await request.form()
        data = {k: v for k, v in form.items() if isinstance(v, str)}

    identifier = (data.get("email") or data.get("username") or "").strip()
    password = data.get("password") or ""
    otp = (data.get("otp") or "").strip() or None
    if not identifier or not password:
        raise HTTPException(
            status_code=422,
            detail="login requires `password` and one of `email`/`username`",
        )
    return identifier, password, otp


def _set_refresh_cookie(response: Response, refresh_token: str, max_age: int) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=refresh_token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,  # type: ignore[arg-type]
        path=settings.auth_cookie_path,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path=settings.auth_cookie_path,
    )


async def _verified_claims(state: Any, access_token: str, *, event: str) -> Any:
    """Claims of a token we just minted, or ``None`` if it will not verify (JWKS path broken; logged)."""
    try:
        return await verify_token(
            access_token,
            # The service's own issuer list, never a hard-wired issuer.
            issuers=auth_issuers(),
            jwks_cache=state.jwks_cache,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            event,
            extra={"error": str(exc), "error_class": type(exc).__name__},
        )
        return None


async def _audit_login(state: Any, *, claims: Any, kind: str, severity: Severity) -> None:
    """Audit a sign-in or rotation; skipped when the token did not verify (no tenant context)."""
    if claims is None:
        return

    await state.audit_writer.write_event(
        tenant_id=claims.tid,
        kind=kind,
        actor_sub=claims.sub,
        actor_role=(claims.roles[0] if claims.roles else None),
        payload={"sid": claims.sid},
        severity=severity,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange username + password for an access token",
)
async def login(request: Request, response: Response) -> TokenResponse:
    state = get_state()
    client_type = client_type_of(request)
    username, password, otp = await _extract_credentials(request)
    try:
        tok = await state.keycloak.password_grant(username=username, password=password)
    except KeycloakError as exc:
        body_obj = exc.body if isinstance(exc.body, dict) else {}
        kc_error = body_obj.get("error", "")
        kc_desc = body_obj.get("error_description", "")
        if "Account is not fully set up" in kc_desc or "account is locked" in kc_desc.lower():
            _login_counter.add(1, {"result": "locked"})
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"account locked: {kc_desc}",
            ) from exc
        # Keycloak answers a disabled (unverified signup) account with the same
        # `invalid_grant` as a wrong password; say "confirm your email" instead.
        # Not an enumeration leak: the branch only exists for an accepted credential.
        if await _is_unverified_signup(state, username):
            _login_counter.add(1, {"result": "email_not_verified"})
            await _audit_login_refused(state, username=username, reason="email_not_verified")
            refusal = HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="confirm your email address to finish signing up",
            )
            refusal.problem_extras = {"code": "email_not_verified"}  # type: ignore[attr-defined]
            raise refusal from exc

        _login_counter.add(1, {"result": "invalid_creds"})
        logger.info(
            "auth.login_failed",
            extra={
                "username_hash": _hash_for_log(username),
                "kc_error": kc_error,
                "kc_status": exc.status,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": 'Bearer realm="notes"'},
        ) from exc

    # Second factor: the token is NOT released until an enrolled user's TOTP
    # validates. This proxy is the enforcement point (ADR-0039).
    claims = await _verified_claims(state, tok.access_token, event="auth.login.verify_failed")
    await _enforce_totp_if_enrolled(state, claims=claims, otp=otp)

    if not client_type.native:
        # A native app gets the token in the body, never a cookie.
        _set_refresh_cookie(response, tok.refresh_token, tok.refresh_expires_in)
    _login_counter.add(1, {"result": "success"})

    await _audit_login(
        state,
        claims=claims,
        kind=audit_kinds.AUTH_LOGIN,
        severity=Severity.INFO,
    )

    return token_response(
        client_type=client_type,
        access_token=tok.access_token,
        expires_in=tok.expires_in,
        tenant_id=str(claims.tid) if claims is not None else "",
        roles=list(claims.roles) if claims is not None else [],
        refresh_token=tok.refresh_token,
        refresh_expires_in=tok.refresh_expires_in,
    )


async def _is_unverified_signup(state: Any, username: str) -> bool:
    """Is this address a signup that never confirmed? Best-effort: any failure falls through to the ordinary 401."""
    try:
        # `identities`, not `users`: there is no tenant in hand and `users` is RLS-scoped.
        # `email_verified_at IS NULL` is the marker.
        async with state.tenant_writer_pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT 1 FROM identities"
                " WHERE email = $1 AND email_verified_at IS NULL AND status = 'active'"
                " LIMIT 1",
                (username or "").strip().lower(),
            )
        return bool(row)
    except Exception:  # noqa: BLE001
        logger.warning("auth.login.unverified_lookup_failed")
        return False


async def _audit_login_refused(state: Any, *, username: str, reason: str) -> None:
    """A refusal on the platform tenant; the payload carries a hash, never the address."""
    try:
        await state.audit_writer.write_event(
            tenant_id=UUID(settings.auth_platform_tenant_id),
            kind="auth.login_refused",
            actor_sub=None,
            target_kind="user",
            target_id=None,
            payload={"reason": reason, "username_hash": _hash_for_log(username)},
            severity=Severity.WARN,
        )
    except Exception:  # noqa: BLE001
        logger.warning("auth.login.refusal_audit_failed")


async def _enforce_totp_if_enrolled(state: Any, *, claims: Any, otp: str | None) -> None:
    """401 (``otp_required`` / ``otp_invalid``) when a TOTP-enrolled user's ``otp`` is missing or wrong."""
    if claims is None or not claims.mfa_enrolled:
        return

    def _reject(code: str, detail: str) -> HTTPException:
        _login_counter.add(1, {"result": code})
        exc = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": 'MFA realm="notes"'},
        )
        exc.problem_extras = {"code": code}  # type: ignore[attr-defined]
        return exc

    if not otp:
        raise _reject("otp_required", "TOTP code required for this account")

    from crypto import CryptoError, MasterKeyError

    from .. import totp as totp_mod
    from .mfa import ATTR_SECRET, _attr_first

    try:
        envelope = await state.get_envelope()
        rep = await state.keycloak.get_user(claims.sub)
        packed = _attr_first(rep, ATTR_SECRET)
        if packed is None:
            # Enrolled claim but no stored secret (half-reset): fail closed.
            raise _reject(
                "otp_unavailable",
                "MFA state is inconsistent; ask an administrator to reset MFA",
            )
        secret = await totp_mod.decrypt_secret(
            envelope, packed=packed, tenant_id=claims.tid, sub=claims.sub
        )
    except HTTPException:
        raise
    except (MasterKeyError, CryptoError, KeycloakError) as exc:
        logger.error(
            "auth.login.mfa_secret_unavailable",
            extra={"error": str(exc), "error_class": type(exc).__name__},
        )
        # Fail closed even when the secret store is down.
        raise _reject("otp_unavailable", "MFA verification unavailable; try again") from exc

    if not totp_mod.verify_code(secret, otp):
        raise _reject("otp_invalid", "invalid TOTP code")


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate the refresh token; return a new access token",
)
async def refresh(
    response: Response,
    request: Request,
    body: RefreshRequest | None = None,
) -> TokenResponse:
    state = get_state()
    client_type = client_type_of(request)
    refresh_token = _presented_token(request, body)
    if not refresh_token:
        # Distinct code: "you sent nothing" is a client bug, not an expiry.
        missing = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no refresh token was presented",
        )
        missing.problem_extras = {"code": "no_refresh_token"}  # type: ignore[attr-defined]
        raise missing

    try:
        tok = await state.keycloak.refresh(refresh_token=refresh_token)
    except KeycloakError as exc:
        body_obj = exc.body if isinstance(exc.body, dict) else {}
        kc_error = body_obj.get("error", "")
        kc_desc = body_obj.get("error_description", "")
        # Replay / invalid: a re-used refresh is a sec event (realm rotation is on).
        if kc_error == "invalid_grant" and _is_expired(refresh_token):
            # …unless it simply expired (same `invalid_grant` from Keycloak): not a replay.
            _clear_refresh_cookie(response)
            expired = HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="the session has expired",
            )
            expired.problem_extras = {"code": "session_expired"}  # type: ignore[attr-defined]
            raise expired from exc
        if kc_error == "invalid_grant":
            # Recover the sub from the unverified payload to audit + revoke.
            sub = _unverified_sub(refresh_token)
            tid = _unverified_tid(refresh_token)
            # Keycloak refresh tokens carry no `tid`; resolve it via SECURITY DEFINER `tenant_of_sub`.
            if tid is None and sub is not None:
                try:
                    tid = await state.app_pool.fetchval("SELECT public.tenant_of_sub($1)", sub)
                except Exception as resolve_exc:
                    logger.warning(
                        "auth.refresh_replay.tid_resolve_failed",
                        extra={"error": str(resolve_exc)},
                    )
            _refresh_replay_counter.add(1, {"tenant_id": str(tid) if tid else "unknown"})
            if tid is not None:
                try:
                    await state.audit_writer.write_event(
                        tenant_id=tid,
                        kind=audit_kinds.AUTH_REFRESH_REPLAY_DETECTED,
                        actor_sub=sub,
                        payload={"kc_error": kc_error, "kc_desc": kc_desc},
                        severity=Severity.SEC,
                    )
                except Exception as audit_exc:
                    logger.warning(
                        "audit.refresh_replay.write_failed",
                        extra={"error": str(audit_exc)},
                    )
            if sub is not None:
                try:
                    await state.keycloak.logout_user(sub)
                except Exception as logout_exc:
                    logger.warning(
                        "auth.refresh_replay.revoke_failed",
                        extra={"sub": str(sub), "error": str(logout_exc)},
                    )
                # A replayed refresh: kill every outstanding ACCESS token too.
                if state.denylist is not None:
                    try:
                        await state.denylist.revoke_sub(
                            str(sub),
                            ttl_seconds=settings.revoked_sub_ttl_seconds,
                        )
                        if tid is not None:
                            await state.audit_writer.write_event(
                                tenant_id=tid,
                                kind=audit_kinds.AUTH_SESSION_REVOKED,
                                actor_sub=sub,
                                payload={"reason": "refresh_replay"},
                                severity=Severity.SEC,
                            )
                    except Exception as push_exc:  # noqa: BLE001
                        logger.warning(
                            "auth.refresh_replay.denylist_push_failed",
                            extra={"error": str(push_exc)},
                        )
            _clear_refresh_cookie(response)
            replay_exc = HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="refresh token is no longer valid",
            )
            # Lets the SPA distinguish a replay (do NOT retry) from an expiry.
            replay_exc.problem_extras = {"code": "auth_refresh_replay"}  # type: ignore[attr-defined]
            raise replay_exc from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"identity provider error: {kc_desc or kc_error}",
        ) from exc

    if not client_type.native:
        _set_refresh_cookie(response, tok.refresh_token, tok.refresh_expires_in)
    _login_counter.add(1, {"result": "refresh"})
    claims = await _verified_claims(state, tok.access_token, event="auth.refresh.verify_failed")
    await _audit_login(
        state,
        claims=claims,
        kind=audit_kinds.AUTH_REFRESH,
        severity=Severity.INFO,
    )
    return token_response(
        client_type=client_type,
        access_token=tok.access_token,
        expires_in=tok.expires_in,
        tenant_id=str(claims.tid) if claims is not None else "",
        roles=list(claims.roles) if claims is not None else [],
        refresh_token=tok.refresh_token,
        refresh_expires_in=tok.refresh_expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke refresh token and clear cookie",
)
async def logout(
    request: Request,
    response: Response,
    body: LogoutRequest | None = None,
    authorization: Annotated[str | None, "Authorization"] = None,
) -> Response:
    """Revoke the refresh token, clear the cookie.

    If an ``Authorization: Bearer <access_token>`` header is also sent, the
    verified ``tid``/``sub`` are used to emit an ``auth.logout`` audit event.
    Refresh tokens deliberately don't carry the ``tid`` claim (Keycloak
    default), so without the access token we have no verified tenant
    context and skip the audit.
    """
    state = get_state()
    refresh_token = _presented_token(request, body)
    # Prefer the verified access token; the unverified refresh sub is for log correlation only.
    tid_for_audit = None
    sub_for_audit = None
    bearer_claims = None
    raw_auth = request.headers.get("Authorization", "") or (authorization or "")
    if raw_auth.startswith("Bearer "):
        try:
            claims = await verify_token(
                raw_auth[len("Bearer ") :],
                # In `dual` the bearer may be native, so verify against both issuers.
                issuers=auth_issuers(),
                jwks_cache=state.jwks_cache,
            )
            tid_for_audit = claims.tid
            sub_for_audit = claims.sub
            bearer_claims = claims
        except Exception as exc:
            logger.info("auth.logout.bearer_invalid", extra={"error": str(exc)})

    # The ACCESS token stays signature-valid until `exp`: denylist its sid (TTL = remaining lifetime).
    if bearer_claims is not None and state.denylist is not None:
        import time as _time

        ttl = max(int(bearer_claims.exp - _time.time()), 1)
        try:
            await state.denylist.revoke_sid(bearer_claims.sid, ttl_seconds=ttl)
            await state.audit_writer.write_event(
                tenant_id=bearer_claims.tid,
                kind=audit_kinds.AUTH_SESSION_REVOKED,
                actor_sub=bearer_claims.sub,
                payload={"reason": "logout", "sid": bearer_claims.sid},
                severity=Severity.INFO,
            )
        except Exception as push_exc:  # noqa: BLE001 — logout must still succeed
            logger.warning("auth.logout.denylist_push_failed", extra={"error": str(push_exc)})

    if refresh_token:
        try:
            await state.keycloak.logout(refresh_token=refresh_token)
        except KeycloakError as exc:
            # Already expired/revoked is fine (idempotent).
            logger.info(
                "auth.logout.kc_already_revoked",
                extra={"kc_status": exc.status},
            )

    if tid_for_audit is not None:
        try:
            await state.audit_writer.write_event(
                tenant_id=tid_for_audit,
                kind=audit_kinds.AUTH_LOGOUT,
                actor_sub=sub_for_audit,
                payload={},
                severity=Severity.INFO,
            )
        except Exception as audit_exc:
            logger.warning("audit.logout.write_failed", extra={"error": str(audit_exc)})

    _logout_counter.add(1)
    # Fresh response so FastAPI's merge with the injected `response` cannot lose the cookie deletion.
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(out)
    return out


# ── helpers ─────────────────────────────────────────────────────────────


def _hash_for_log(value: str) -> str:
    """Stable short hash instead of the raw username."""
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _unverified_jwt_payload(token: str) -> dict[str, Any] | None:
    """Unverified JWT payload, ONLY to recover sub/tid for audit; never for authorisation."""
    import base64
    import json

    try:
        _, payload_b64, _ = token.split(".", 2)
    except ValueError:
        return None
    pad = "=" * (-len(payload_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_b64 + pad)
    except Exception:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_expired(token: str) -> bool:
    """Is this refresh token past its own ``exp``? (unverified; unreadable = not expired, i.e. the replay path)."""
    payload = _unverified_jwt_payload(token)
    if payload is None:
        return False
    exp = payload.get("exp")
    if not isinstance(exp, int | float):
        return False
    return exp <= time.time()


def _unverified_sub(token: str) -> Any:

    payload = _unverified_jwt_payload(token)
    if payload is None:
        return None
    sub_str = payload.get("sub")
    if not isinstance(sub_str, str):
        return None
    try:
        return UUID(sub_str)
    except ValueError:
        return None


def _unverified_tid(token: str) -> Any:
    from uuid import UUID

    payload = _unverified_jwt_payload(token)
    if payload is None:
        return None
    tid_str = payload.get("tid")
    if not isinstance(tid_str, str):
        return None
    try:
        return UUID(tid_str)
    except ValueError:
        return None
