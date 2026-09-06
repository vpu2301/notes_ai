"""FND-1 contract: this service trusts a LIST of issuers, and only that list.

Generated from the template in :mod:`auth.contract`. Four cases, all in
process — no Keycloak, no auth-service, no database:

    (a) a Keycloak-shaped token   → accepted
    (b) a native-shaped token     → accepted
    (c) a third issuer's token    → rejected
    (d) alg=none / HS256-confusion→ rejected

The list under test is the one THIS service resolves from its own
settings, so the test fails if the service stops reading
``AUTH_ISSUERS_JSON`` or builds its JWKS cache from a different list than
its ``current_user`` dependency.
"""

from __future__ import annotations

import pytest
from autocomplete_service.config import settings
from autocomplete_service.main_deps import auth_issuers

from auth.contract import IssuerContract, assert_issuer_contract


async def test_trusts_both_configured_issuers_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = IssuerContract(audience=settings.auth_audience)
    monkeypatch.setattr(settings, "auth_issuers_json", contract.issuers_json)
    await assert_issuer_contract(contract, auth_issuers())


async def test_without_the_list_the_legacy_single_issuer_still_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-FND-1 deployment shape: three env vars, one issuer.

    This is what every service runs with until the fleet rollout, so it
    has to keep working byte for byte.
    """
    contract = IssuerContract(audience=settings.auth_audience)
    monkeypatch.setattr(settings, "auth_issuers_json", "")
    monkeypatch.setattr(settings, "auth_issuer", contract.keycloak_issuer)
    monkeypatch.setattr(settings, "auth_jwks_url", contract.configs[0].jwks_url)

    issuers = auth_issuers()
    assert [c.issuer for c in issuers] == [contract.keycloak_issuer]

    from auth import verify_token
    from auth.exceptions import InvalidIssuerError

    cache = contract.jwks_cache(issuers)
    claims = await verify_token(contract.keycloak_token(), issuers=issuers, jwks_cache=cache)
    assert claims.iss == contract.keycloak_issuer

    # The native issuer is not configured yet, so its token is a stranger.
    with pytest.raises(InvalidIssuerError):
        await verify_token(contract.native_token(), issuers=issuers, jwks_cache=cache)
