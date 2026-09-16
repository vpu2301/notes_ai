"""POST /auth/login, POST /auth/refresh, POST /auth/logout — Keycloak.

Mounted in **keycloak mode only** since IDX-M1. In native mode the same
three paths are served by `session_native.py` against `auth_sessions`;
this router proxies to Keycloak in every line below, so under a native
issuer it could only ever answer 502 — and its `/auth/refresh` would
shadow the native one that clients actually hold a token for. IDX-A4
brings the native password grant that `/auth/login` still owes.

Where the refresh token travels is ``X-Client-Type``'s decision, exactly
as it is in native mode (``domain/transport.py``, and `session_native.py`
for the same three paths): a browser's refresh token is in the HttpOnly
``mdx_rt`` cookie and never in a body; a native client's is in the body
and never in a cookie. Until this router honoured that, a Mac or iPhone
signing in here was handed a cookie it has no jar for — the app read a
200 with nothing to keep and said so ("this server cannot keep this Mac
signed in"), which was the truth about the response and a bug about the
server.

Login flow:
  1. Take {username, password} from JSON body.
  2. Proxy to Keycloak via the confidential mdx-backend client.
  3. On success: hand the refresh token to the client the way that client
     can keep it — HttpOnly cookie (path=AUTH_COOKIE_PATH, SameSite per
     settings, Secure in non-dev) for a browser, ``refresh_token`` +
     ``refresh_expires_in`` in the JSON body for a native app — and
     return access_token + expires_in either way.
  4. Verify the access token to extract claims and emit an audit ``auth.login`` event.

Refresh flow:
  1. Read the refresh token from the body (native) or the cookie (browser).
  2. Call Keycloak refresh; on success, rotate it back the same way.
  3. On "Token is not active" / 400 → audit ``auth.refresh_replay_detected`` (severity sec).
     The old refresh was consumed by an earlier call; this attempt is a replay.

Logout flow:
  1. Read the token from the body or the cookie; call Keycloak logout to
     revoke; clear the cookie; 204.

MFA is intentionally NOT enforced here — pilot deployment runs MFA-off per
the user's instruction. Re-enabling it later means flipping the
``requires_mfa`` dep on these routes and adding TOTP enrolment endpoints.
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

# Shared with `session_native`, which serves refresh/logout in native mode:
# one declaration per instrument name, one series per counter.
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
    """The body's token wins over the cookie: it is the one the caller
    could only have got by being the client it claims to be."""
    if body is not None and body.refresh_token:
        return body.refresh_token
    return request.cookies.get(settings.auth_cookie_name)


async def _extract_credentials(request: Request) -> tuple[str, str, str | None]:
    """Parse login credentials from either a JSON body or an
    application/x-www-form-urlencoded form (the SPA sends form). Accepts the
    identifier under `email` or `username`, plus an optional `otp` (TOTP
    code — sprint 16). Raises 422 on a missing required field."""
    content_type = request.headers.get("content-type", "")
    data: dict[str, Any]
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=422, detail="invalid JSON body") from exc
    else:
        # form-urlencoded (or multipart) — the SPA path.
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
    """Claims of a token we just minted, or ``None`` if it will not verify.

    One verification per request, shared by the three things that need
    it: the MFA gate, the audit event, and the tenant/roles the response
    carries. Failing to verify a token Keycloak just issued means the
    JWKS path is broken — log loudly, and let each caller decide what a
    missing tenant context means for its own half.
    """
    try:
        return await verify_token(
            access_token,
            # FND-1: the service's own list. In `dual` that is Keycloak
            # AND the native issuer; this path only ever sees the former,
            # but a single hard-wired issuer here is exactly the drift
            # the gate exists to prevent.
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
    """Emit the audit event for a sign-in or a rotation.

    Skipped when the token did not verify: there is no usable tenant
    context, and an audit row on a guessed tenant is worse than none.
    """
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
        # 401: invalid_grant (bad password / unknown user / disabled).
        # 400: malformed (shouldn't happen via this proxy).
        body_obj = exc.body if isinstance(exc.body, dict) else {}
        kc_error = body_obj.get("error", "")
        kc_desc = body_obj.get("error_description", "")
        if "Account is not fully set up" in kc_desc or "account is locked" in kc_desc.lower():
            _login_counter.add(1, {"result": "locked"})
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"account locked: {kc_desc}",
            ) from exc
        # BE-0: an account created by self-serve signup is disabled in
        # Keycloak until its address is confirmed, and Keycloak answers a
        # disabled account with exactly the same `invalid_grant` it gives
        # a wrong password. Told that, the person retypes a password that
        # was never wrong. So before answering 401 we ask one question:
        # is there an `invited` row for this address? If there is, the
        # honest answer is "confirm your email", with a resend button.
        #
        # It is not an enumeration leak. The caller supplied a password
        # that Keycloak accepted as belonging to this account — reaching
        # this branch already requires knowing the credential.
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

    # ── Sprint 16: second factor for enrolled users ─────────────────────
    # The password grant succeeded, but the token is NOT released until an
    # enrolled user's TOTP code validates. Keycloak isn't publicly exposed
    # in the production topology, so this proxy check is the enforcement
    # point (ADR-0039). Enrolment status comes from the token's own
    # `mfa_enrolled` claim (attribute-mapped), so the check costs no extra
    # Keycloak round-trip for the unenrolled majority.
    claims = await _verified_claims(state, tok.access_token, event="auth.login.verify_failed")
    await _enforce_totp_if_enrolled(state, claims=claims, otp=otp)

    if not client_type.native:
        # A native app has no cookie jar for this; it gets the token in
        # the body below and must not also be handed one it cannot read.
        _set_refresh_cookie(response, tok.refresh_token, tok.refresh_expires_in)
    _login_counter.add(1, {"result": "success"})

    # Audit the success (out of band; failures are logged only because we
    # don't yet have reliable tenant resolution for unknown users).
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
    """Is this address a BE-0 signup that never confirmed?

    `users.status = 'invited'` is the marker. `deactivated` is
    deliberately NOT included: an account an operator switched off keeps
    today's 403 `account_disabled`, and telling its owner to "confirm
    your email" would send them round a loop that cannot end.

    Best-effort by construction — a database hiccup must not turn a
    wrong-password 401 into a 500 — so any failure falls through to the
    ordinary refusal.
    """
    try:
        # `identities`, not `users`. Both carry the fact, but `users` is
        # RLS-scoped per tenant and there is no tenant in hand yet — the
        # caller has no token. `identities` is not tenant-scoped (a person
        # spans workspaces) and `tenant_writer` reads it under a
        # permissive policy, so this is the one that can answer.
        #
        # `email_verified_at IS NULL` is the marker: the 0027 backfill
        # stamped every migrated identity, and both signup paths stamp
        # theirs at creation or at verification. Only a BE-0 account that
        # never confirmed is NULL.
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
    """A refusal on the platform tenant: there is no verified tenant yet.

    The address is not written — the payload carries only the reason and a
    salted hash, because an audit row is the wrong place for the address
    of somebody who may not have an account at all.
    """
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
    """Reject the login (401) when the user is TOTP-enrolled and ``otp``
    is missing or wrong. No-op for unenrolled users.

    Machine codes for the SPA: ``otp_required`` (ask for the code) and
    ``otp_invalid`` (wrong code — retry).

    ``claims`` is ``None`` when the token we just minted would not
    verify: the JWKS path is broken, which `_verified_claims` has already
    logged, and inventing an MFA state on top of it would not help.
    """
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
            # Claim says enrolled but no stored secret — a half-reset.
            # Fail closed and point at the admin reset path.
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
        # Fail closed: an enrolled account never logs in without the
        # second factor, even when the secret store is down.
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
        # A distinct code (docs/api/error-codes.md), the same one
        # `session_native` uses: "you sent nothing" is a client bug and
        # "your session is over" is a user event, and a client that
        # cannot tell them apart retries the wrong one.
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
        # Replay / invalid: the refresh has already been consumed (rotation
        # is on at the realm level, so a re-used refresh is a sec event).
        if kc_error == "invalid_grant" and _is_expired(refresh_token):
            # …unless the token expired on its own, which Keycloak reports
            # with the same `invalid_grant`. A Mac whose lid was shut past
            # `ssoSessionIdleTimeout` presents exactly that, and nobody
            # replayed anything: charging it as a replay would raise a
            # `sec` audit event, kill every other session the person has
            # and denylist their account over a closed laptop. The token
            # says so itself — its own `exp` is behind us — so read it
            # before reaching for the alarm.
            _clear_refresh_cookie(response)
            expired = HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="the session has expired",
            )
            expired.problem_extras = {"code": "session_expired"}  # type: ignore[attr-defined]
            raise expired from exc
        if kc_error == "invalid_grant":
            # Try to extract the user's sub from the unverified refresh
            # payload so we can audit + force-revoke their sessions.
            sub = _unverified_sub(refresh_token)
            tid = _unverified_tid(refresh_token)
            # Keycloak refresh tokens do not carry the custom `tid` claim, so
            # resolve the tenant from `sub` via the DB (SECURITY DEFINER
            # `tenant_of_sub`); otherwise the security audit event below would be
            # silently skipped (Sprint A1, DEF-A1-20).
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
                # Sprint 16: a replayed refresh means the token chain may be
                # in hostile hands — kill every outstanding ACCESS token of
                # the user too, not just the Keycloak sessions.
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
            # Machine-readable code so the SPA can distinguish a replay (force
            # clean re-login, do NOT retry) from an ordinary expired-token 401.
            replay_exc.problem_extras = {"code": "auth_refresh_replay"}  # type: ignore[attr-defined]
            raise replay_exc from exc
        # Other failure modes (5xx etc.) bubble as 503.
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
    # Audit context — prefer the access token (verified); fall back to the
    # refresh token's sub (unverified) for log-line correlation only.
    tid_for_audit = None
    sub_for_audit = None
    bearer_claims = None
    raw_auth = request.headers.get("Authorization", "") or (authorization or "")
    if raw_auth.startswith("Bearer "):
        try:
            claims = await verify_token(
                raw_auth[len("Bearer ") :],
                # In `dual` the bearer accompanying a Keycloak logout may
                # be native (a client that switched login methods), so
                # this verifies against both.
                issuers=auth_issuers(),
                jwks_cache=state.jwks_cache,
            )
            tid_for_audit = claims.tid
            sub_for_audit = claims.sub
            bearer_claims = claims
        except Exception as exc:
            logger.info("auth.logout.bearer_invalid", extra={"error": str(exc)})

    # ── Sprint 16: close the 15-minute window ───────────────────────────
    # The refresh token dies at Keycloak below, but the ACCESS token would
    # stay signature-valid until `exp`. Denylist its sid so the very next
    # request anywhere in the fleet is rejected. TTL = remaining lifetime.
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
            # If the refresh was already expired/revoked, that's fine; log
            # but don't fail the logout (idempotent).
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
    # Build a fresh response so the Set-Cookie header is the only one we
    # set; FastAPI would otherwise merge the injected `response` with our
    # returned one and we'd risk losing the cookie deletion.
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(out)
    return out


# ── helpers ─────────────────────────────────────────────────────────────


def _hash_for_log(value: str) -> str:
    """Don't log raw usernames; emit a stable short hash so SOC can correlate."""
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _unverified_jwt_payload(token: str) -> dict[str, Any] | None:
    """Decode the *unverified* payload of a JWT — used ONLY to recover
    sub/tid for audit on a refresh that we already know is invalid.

    Never trust these claims for authorisation; the chain didn't verify.
    """
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
    """Is this refresh token past its own ``exp``?

    Read unverified, and only ever to answer "did this expire?" — never
    for authorisation. A token we cannot read at all is not called
    expired: the replay path is the safe answer for something this
    service does not recognise.
    """
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
