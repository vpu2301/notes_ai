"""OIDC discovery + JWKS for the native issuer (IDX-A2, G; FND-1).

Mounted in every mode. Discovery describes an issuer, so in ``keycloak``
mode — where there is no native issuer — it answers 503.

The JWKS endpoint does not, and that is deliberate. FND-1 configures the
whole fleet with this URL *before* auth-service has a signing key, so for
the length of that rollout the honest answer is an empty key set:
``{"keys": []}`` is a valid JWKS document, every service's cache accepts
it, and a token claiming this issuer fails ``kid_not_found`` rather than
crashing a verifier. A 404 here would make the rollout unverifiable — the
operator could not tell "not deployed yet" from "misconfigured URL"
without reading logs on eight services.

The JWKS never carries private members — the key set exposes ``public_jwk``
alone, and a unit test asserts the served document has no ``d/p/q/dp/dq/qi``.
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
        # Empty but valid: this deployment does not mint yet. See the
        # module docstring — the fleet is pointed here first, on purpose.
        _jwks_requests.add(1)
        response.headers["Cache-Control"] = "public, max-age=60"
        return {"keys": []}
    doc = keys.jwks(access_ttl_seconds=settings.auth_access_ttl_seconds)
    for key in doc["keys"]:
        assert not (PRIVATE_JWK_MEMBERS & key.keys()), "JWKS must never carry private members"
    _jwks_requests.add(1)
    response.headers["Cache-Control"] = "public, max-age=300"
    return doc
