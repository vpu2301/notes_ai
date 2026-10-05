"""Issuer contract (ADR-0047): this service trusts a LIST of issuers, and only that list.

Template in :mod:`auth.contract`; the list under test is the one THIS service resolves.
"""

from __future__ import annotations

import pytest

from asr_service.config import settings
from asr_service.main_deps import auth_issuers
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
    """The single-issuer deployment shape: three env vars, one issuer."""
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
