"""OIDC discovery + JWKS for the native issuer, mounted in every mode.

Discovery answers 503 in keycloak mode; JWKS answers ``{"keys": []}`` (valid,
cacheable) so the fleet can be pointed here before there is a key. Never private members.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Response, status
from opentelemetry import metrics

from ..config import settings
from ..deps import get_state

_meter = metrics.get_meter("mdx.auth")
_jwks_requests = _meter.create_counter(
    "mdx_auth_jwks_requests_total",
    description="JWKS document requests served by the native issuer",
    unit="1",
)

router = APIRouter(tags=["issuer"])

PRIVATE_JWK_MEMBERS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})


def _issuer_or_503() -> Any:
    state = get_state()
    token_service = getattr(state, "token_service", None)
    if token_service is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="native issuer is not configured"
        )
    return token_service


@router.get("/.well-known/openid-configuration", summary="OIDC discovery for the native issuer")
async def openid_configuration() -> dict[str, Any]:
    token_service = _issuer_or_503()
    issuer = token_service.issuer.rstrip("/")
    return {
        "issuer": token_service.issuer,
        "jwks_uri": f"{issuer}/.well-known/jwks.json",
        "token_endpoint": f"{issuer}/auth/refresh",
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@router.get("/.well-known/jwks.json", summary="Public signing keys (active + not yet retired)")
async def jwks(response: Response) -> dict[str, Any]:
    state = get_state()
    keys = getattr(state, "signing_keys", None)
    if keys is None:
        # Empty but valid: this deployment does not mint yet.
        _jwks_requests.add(1)
        response.headers["Cache-Control"] = "public, max-age=60"
        return {"keys": []}
    doc = keys.jwks(access_ttl_seconds=settings.auth_access_ttl_seconds)
    for key in doc["keys"]:
        assert not (PRIVATE_JWK_MEMBERS & key.keys()), "JWKS must never carry private members"
    _jwks_requests.add(1)
    response.headers["Cache-Control"] = "public, max-age=300"
    return doc
