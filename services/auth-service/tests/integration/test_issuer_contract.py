"""Issuer contract for auth-service, whose list is mode-derived (``main_deps.auth_issuers``).

keycloak → the configured list; dual → the configured list + its own native issuer (ADR-0047);
native → its own issuer only. The four contract cases run against the `dual` list.
"""

from __future__ import annotations

import pytest

from auth.contract import IssuerContract, assert_issuer_contract
from auth_service.config import settings
from auth_service.main_deps import auth_issuers, native_issuer_config


@pytest.fixture
def contract() -> IssuerContract:
    return IssuerContract(audience=settings.auth_audience)


def _configure(monkeypatch: pytest.MonkeyPatch, contract: IssuerContract, mode: str) -> None:
    monkeypatch.setattr(settings, "idp_mode", mode)
    monkeypatch.setattr(settings, "auth_issuer", contract.keycloak_issuer)
    monkeypatch.setattr(settings, "auth_jwks_url", contract.configs[0].jwks_url)
    monkeypatch.setattr(settings, "auth_issuer_url", contract.native_issuer)
    monkeypatch.setattr(settings, "auth_issuers_json", "")


async def test_dual_trusts_both_issuers_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, contract: IssuerContract
) -> None:
    _configure(monkeypatch, contract, "dual")
    await assert_issuer_contract(contract, auth_issuers())


def test_keycloak_mode_does_not_trust_the_native_issuer(
    monkeypatch: pytest.MonkeyPatch, contract: IssuerContract
) -> None:
    _configure(monkeypatch, contract, "keycloak")
    assert [c.issuer for c in auth_issuers()] == [contract.keycloak_issuer]


def test_native_mode_drops_keycloak(
    monkeypatch: pytest.MonkeyPatch, contract: IssuerContract
) -> None:
    """The cut-over's whole point: the old issuer stops opening doors."""
    _configure(monkeypatch, contract, "native")
    assert [c.issuer for c in auth_issuers()] == [contract.native_issuer]


def test_dual_does_not_duplicate_an_already_configured_native_issuer(
    monkeypatch: pytest.MonkeyPatch, contract: IssuerContract
) -> None:
    """AUTH_ISSUERS_JSON already names both; a third copy of ourselves would lose a JwksCache entry."""
    _configure(monkeypatch, contract, "dual")
    monkeypatch.setattr(settings, "auth_issuers_json", contract.issuers_json)
    names = [c.issuer for c in auth_issuers()]
    assert names == [contract.keycloak_issuer, contract.native_issuer]


def test_native_issuer_config_matches_the_published_jwks_path(
    monkeypatch: pytest.MonkeyPatch, contract: IssuerContract
) -> None:
    """The fleet trusts this URL before anything is served at it; a mismatch is an issuer with no fetchable key."""
    _configure(monkeypatch, contract, "dual")
    config = native_issuer_config()
    assert config.issuer == contract.native_issuer
    assert config.jwks_url == f"{contract.native_issuer}/.well-known/jwks.json"
