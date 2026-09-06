"""POST /auth/refresh, /auth/logout and /auth/token against `auth_sessions`.

The native half of IDX-A2's session surface, carried by IDX-M1 because
the Mac app's Keychain session is exactly a refresh token the server can
rotate — and until this router existed, nothing could. In native mode
these two paths replace the Keycloak-backed ones in `login.py`.

In `dual` mode (BE-2, ADR-0047) BOTH kinds of session are live at once
and this router is mounted FIRST, so `/auth/refresh` and `/auth/logout`
arrive here whoever they belong to. The routing rule is the token's own
shape: `nrt_`-prefixed (or otherwise opaque) → this service's store;
JWT-shaped → `login.py`'s Keycloak proxy, called directly.

The cookie name does not change for the dual period, and neither does
anything else a client can see. That is the point: a migration state that
needed a release of the web app, the Mac app and the iPhone app before it
could begin is not a migration state, it is a cut-over with extra steps.

Where the token travels is `X-Client-Type`'s decision, and it is the same
decision `/auth/email/verify` made when the session started
(`domain/transport.py`): a browser's refresh token is in the HttpOnly
`mdx_rt` cookie and is never in a body; a native client's is in the body
and never in a cookie. A request that carries both is served the body's
— it is the one the caller could only have got by being the client.

What this router owns, beyond calling the service:

* the cookie, in both directions (rotate it, clear it on the way out);
* the denylist. The session row stops the *next* refresh; the access
  token already minted stays signature-valid until `exp`, and only
  denylisting its `sid` closes that window. On a replay the whole
  identity is denylisted, because a replayed refresh token means the
  chain may be in hostile hands and the tokens it already bought are not
  worth guessing about;
* the audit trail, on the tenant the session belongs to.

`POST /auth/token` (IDX-M2) is the third: an access token for another of
the identity's workspaces. It is bearer-authenticated rather than
refresh-authenticated — the caller is a live client with a live session,
not one recovering from an expiry — and it returns no refresh token,
because switching rotates nothing.
"""

from __future__ import annotations

import logging
import time
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from audit import Severity
from auth import Claims, verify_token

from .. import audit_kinds, auth_metrics
from ..config import settings
from ..deps import current_user, get_state
from ..domain.errors import ApiError
from ..domain.session_service import RefreshReplayError, is_native_refresh_token
from ..domain.transport import TokenResponse, client_type_of, token_response
from ..main_deps import auth_issuers, native_issuer_config
from .native_common import as_problem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RefreshRequest(_Strict):
    """Native clients send their token here; browsers send nothing at all.

    Optional rather than required so one route serves both transports —
    a browser POSTing an empty body must not be answered 422 for
    declining to put its HttpOnly cookie in a field it cannot read.
    """

    refresh_token: str | None = Field(default=None, min_length=1, max_length=512)


class LogoutRequest(_Strict):
    refresh_token: str | None = Field(default=None, min_length=1, max_length=512)


class TokenRequest(_Strict):
    """Which workspace, and whether the person is *moving* there.

    `activate` defaults to true because the switcher is what this endpoint
    is for; a background upload finishing in the workspace it started in
    passes false so it does not move somebody's session out from under
    them (IDX-M2 D).
    """

    tenant_id: UUID
    activate: bool = True


def _service() -> Any:
    """The wired :class:`SessionService`, or 404 when this deployment has none.

    404 rather than 503, the posture the other native routers take: a
    deployment running under Keycloak should look like one that has no
    such endpoint. (It does have one — `login.py`'s — but that router is
    mounted in the other mode, so this branch is unreachable there.)
    """
    service = getattr(get_state(), "session_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return service


def _presented_token(request: Request, body: RefreshRequest | LogoutRequest | None) -> str | None:
    if body is not None and body.refresh_token:
        return body.refresh_token
    return request.cookies.get(settings.auth_cookie_name)


def _belongs_to_keycloak(presented: str | None) -> bool:
    """Should this request be served by `login.py` instead?

    Only ever true in `dual`. In `keycloak` mode this router is not
    mounted; in `native` mode Keycloak no longer holds sessions, and a
    JWT-shaped refresh token arriving after the cut-over is a stale
    credential that must be refused, not proxied to an issuer that is out
    of the token path.
    """
    if settings.idp_mode != "dual" or not presented:
        return False
    return not is_native_refresh_token(presented)


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
    response.delete_cookie(key=settings.auth_cookie_name, path=settings.auth_cookie_path)


async def _audit(
    *,
    tenant_id: UUID,
    kind: str,
    payload: dict[str, Any],
    severity: Severity,
    actor_sub: UUID | None = None,
) -> None:
    """Best-effort audit; never fails the operation it describes."""
    state = get_state()
    try:
        await state.audit_writer.write_event(
            tenant_id=tenant_id,
            kind=kind,
            actor_sub=actor_sub,
            payload=payload,
            severity=severity,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "auth.session.audit_write_failed",
            extra={"kind": kind, "error_class": type(exc).__name__},
        )


async def _bearer_claims(authorization: str | None) -> Claims | None:
    """Verified claims of an accompanying access token, or None.

    Logout takes one so it can denylist the `sid` it is ending. It is
    never *required*: a client whose access token has already expired is
    exactly the client that most needs its refresh token revoked.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None
    state = get_state()
    try:
        return await verify_token(
            authorization[len("Bearer ") :],
            # FND-1: both issuers during `dual`, so a logout can denylist
            # the `sid` of whichever kind of session is ending.
            issuers=auth_issuers(),
            jwks_cache=state.jwks_cache,
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("auth.logout.bearer_invalid", extra={"error_class": type(exc).__name__})
        return None


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate the refresh token; return a new access token",
)
async def refresh(
    request: Request, response: Response, body: RefreshRequest | None = None
) -> TokenResponse:
    presented = _presented_token(request, body)
    if _belongs_to_keycloak(presented):
        # Called, not redirected: the caller's cookie, headers and body
        # are already here, and a 307 would make every client re-send a
        # credential across a hop for no gain.
        from .login import refresh as keycloak_refresh

        return await keycloak_refresh(response, request, body)  # type: ignore[arg-type]

    service = _service()
    client_type = client_type_of(request)
    if not presented:
        # A distinct code (docs/api/error-codes.md): "you sent nothing" is
        # a client bug, "your session is over" is a user event, and a
        # client that cannot tell them apart retries the wrong one.
        _clear_refresh_cookie(response)
        raise as_problem(ApiError("no_refresh_token", 401, detail="no refresh token was presented"))

    try:
        rotated = await service.refresh(
            refresh_token=presented,
            ip=request.client.host if request.client else "",
        )
    except RefreshReplayError as exc:
        await _on_replay(exc)
        _clear_refresh_cookie(response)
        raise as_problem(exc) from exc
    except ApiError as exc:
        _clear_refresh_cookie(response)
        raise as_problem(exc) from exc

    if not client_type.native:
        _set_refresh_cookie(response, rotated.refresh_token, rotated.refresh_expires_in)
    auth_metrics.login_counter.add(1, {"result": "refresh"})
    await _audit(
        tenant_id=rotated.tenant_id,
        kind=audit_kinds.AUTH_REFRESH,
        payload={"sid": str(rotated.session_id), "client_type": str(client_type)},
        severity=Severity.INFO,
        actor_sub=rotated.identity_id,
    )
    return token_response(
        client_type=client_type,
        access_token=rotated.access_token,
        expires_in=rotated.expires_in,
        tenant_id=str(rotated.tenant_id),
        roles=rotated.roles,
        refresh_token=rotated.refresh_token,
        refresh_expires_in=rotated.refresh_expires_in,
    )


async def _on_replay(exc: RefreshReplayError) -> None:
    """A retired token, presented late: revoke everything it could buy.

    The session is already revoked by the service (that is the half that
    must happen inside the same read the detection came from). What is
    left is the blast radius: every access token of this identity, on the
    denylist, and a `sec`-severity line in the audit trail — this is the
    one auth event that is anomalous by definition.
    """
    state = get_state()
    auth_metrics.refresh_replay_counter.add(1, {"tenant_id": str(exc.tenant_id)})
    await _audit(
        tenant_id=exc.tenant_id,
        kind=audit_kinds.AUTH_REFRESH_REPLAY_DETECTED,
        payload={"sid": str(exc.session_id), "identity_id": str(exc.identity_id)},
        severity=Severity.SEC,
        actor_sub=exc.identity_id,
    )
    if state.denylist is None:
        return
    try:
        await state.denylist.revoke_sub(
            str(exc.identity_id), ttl_seconds=settings.revoked_sub_ttl_seconds
        )
        await _audit(
            tenant_id=exc.tenant_id,
            kind=audit_kinds.AUTH_SESSION_REVOKED,
            payload={"reason": "refresh_replay", "identity_id": str(exc.identity_id)},
            severity=Severity.SEC,
            actor_sub=exc.identity_id,
        )
    except Exception as push_exc:  # noqa: BLE001
        logger.warning(
            "auth.refresh_replay.denylist_push_failed",
            extra={"error_class": type(push_exc).__name__},
        )


@router.post(
    "/token",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="An access token for another of my workspaces",
)
async def token(
    body: TokenRequest,
    claims: Annotated[Claims, Depends(current_user)],
) -> TokenResponse:
    """Re-scope this session to `tenant_id`, or just borrow a token for it.

    The `tid` claim is what every service in the fleet filters rows by, so
    this is the only path on which it changes — and it changes only after
    the membership has been re-read from the database. A token minted here
    is worth exactly what the caller's membership is worth at this moment,
    not what it was worth when they signed in.

    Native sessions only. See `_refuse_legacy_session`.
    """
    _refuse_legacy_session(claims)
    service = _service()
    session_id = _session_id(claims)
    try:
        switched = await service.switch_tenant(
            session_id=session_id,
            identity_id=claims.sub,
            tenant_id=body.tenant_id,
            activate=body.activate,
        )
    except ApiError as exc:
        auth_metrics.token_switch_counter.add(1, {"result": exc.code})
        raise as_problem(exc) from exc

    auth_metrics.token_switch_counter.add(1, {"result": "success"})
    if switched.activated:
        await _audit(
            tenant_id=switched.tenant_id,
            kind=audit_kinds.AUTH_TENANT_SWITCHED,
            payload={
                "sid": str(session_id),
                "from_tenant_id": str(claims.tid),
                "to_tenant_id": str(switched.tenant_id),
            },
            severity=Severity.INFO,
            actor_sub=claims.sub,
        )
    # No refresh token and no cookie: nothing rotated, and the session's
    # one credential is still the one the client already holds.
    return TokenResponse(
        access_token=switched.access_token,
        expires_in=switched.expires_in,
        tenant_id=str(switched.tenant_id),
        roles=switched.roles,
    )


def _refuse_legacy_session(claims: Claims) -> None:
    """`409 legacy_session` when the caller's token came from Keycloak.

    Recorded up front in ADR-0047 as the one capability the `dual` period
    splits by token origin. Switching workspace means minting an access
    token for a different `tid`, and auth-service cannot sign a Keycloak
    token — it does not have Keycloak's key, and asking Keycloak for one
    would mean teaching it about our tenant model on the way out the door.

    A distinct code rather than a 401 because nothing is wrong with the
    session: it is valid, it just cannot do this one thing. Clients hide
    the workspace switcher for these sessions instead of letting the tap
    earn a 409 (docs/api/error-codes.md).
    """
    if settings.idp_mode != "dual":
        return
    if claims.iss == native_issuer_config().issuer:
        return
    raise as_problem(
        ApiError(
            "legacy_session",
            409,
            detail=(
                "this session was issued by the previous identity provider and "
                "cannot switch workspace; sign in with an emailed code to switch"
            ),
        )
    )


def _session_id(claims: Claims) -> UUID:
    """The `sid` as a session row id.

    A Keycloak-era token carries a `sid` that is not a UUID and cannot
    name a row here; it is not a session this service can re-scope.
    """
    try:
        return UUID(claims.sid)
    except (ValueError, AttributeError) as exc:
        raise as_problem(
            ApiError("session_revoked", 401, detail="this session cannot be verified")
        ) from exc


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End this session",
)
async def logout(
    request: Request,
    body: LogoutRequest | None = None,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Response:
    """Revoke the session behind the refresh token. Always 204.

    Idempotent by construction: a token that resolves to nothing is a
    session that is already over, and telling the caller so would only
    describe somebody else's account.
    """
    presented = _presented_token(request, body)
    if _belongs_to_keycloak(presented):
        from .login import logout as keycloak_logout

        out = Response(status_code=status.HTTP_204_NO_CONTENT)
        return await keycloak_logout(request, out, body, authorization)  # type: ignore[arg-type]

    service = _service()
    claims = await _bearer_claims(authorization)
    state = get_state()

    ended = await service.revoke(refresh_token=presented) if presented else None

    # Close the access token's remaining life. Preferring the bearer's own
    # `sid` matters when the two disagree: the caller is signing *this*
    # client out, and that is the token in this client's memory.
    sid = claims.sid if claims is not None else (str(ended.session_id) if ended else None)
    if sid is not None and state.denylist is not None:
        ttl = (
            max(int(claims.exp - time.time()), 1)
            if claims is not None
            else settings.auth_access_ttl_seconds
        )
        try:
            await state.denylist.revoke_sid(sid, ttl_seconds=ttl)
        except Exception as exc:  # noqa: BLE001 — logout must still succeed
            logger.warning(
                "auth.logout.denylist_push_failed", extra={"error_class": type(exc).__name__}
            )

    tenant_id = ended.tenant_id if ended else (claims.tid if claims is not None else None)
    if tenant_id is not None:
        await _audit(
            tenant_id=tenant_id,
            kind=audit_kinds.AUTH_LOGOUT,
            payload={"sid": sid} if sid else {},
            severity=Severity.INFO,
            actor_sub=ended.identity_id if ended else (claims.sub if claims else None),
        )
    auth_metrics.logout_counter.add(1)

    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(out)
    return out
