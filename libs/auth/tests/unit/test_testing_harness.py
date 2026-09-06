"""IDX-B2 F4 — the harness that replaces logging in through Keycloak.

The point of these tests is that the harness does not *bypass* anything.
A fixture that overrode `current_user` with a lambda would make every one
of these pass while the verifier was broken; these go through the real
`verify_token`, so a wrong audience, a wrong issuer, an expired token and
a forbidden claim all still fail.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest

from auth import Claims, verify_token
from auth.exceptions import ExpiredTokenError, InvalidAudienceError
from auth.testing import (
    auth_headers,
    install_test_issuer,
    mint_test_token,
    shared_issuer,
)
from auth.testing import (
    test_jwks_cache as make_jwks_cache,
)


class _State:
    """The shape every service in this fleet keeps its singletons in."""

    def __init__(self) -> None:
        self.jwks_cache = object()


def test_the_shared_issuer_generates_one_key_for_the_session() -> None:
    """A 2048-bit keygen per test would cost minutes across the fleet."""
    assert shared_issuer() is shared_issuer()
    first = time.perf_counter()
    mint_test_token()
    mint_test_token()
    # Two mints after warm-up must not be doing keygen work.
    assert time.perf_counter() - first < 1.0


async def test_a_minted_token_passes_the_real_verifier() -> None:
    issuer = shared_issuer()
    sub, tid = uuid4(), uuid4()
    token = mint_test_token(sub=sub, tid=tid, roles=["member"])

    claims = await verify_token(
        token,
        expected_audience=issuer.audience,
        expected_issuer=issuer.issuer,
        jwks_cache=make_jwks_cache(),
    )
    assert isinstance(claims, Claims)
    assert claims.sub == sub
    assert claims.tid == tid
    assert claims.roles == ["member"]


async def test_a_wrong_audience_is_still_rejected() -> None:
    """The harness signs; it does not excuse."""
    issuer = shared_issuer()
    token = mint_test_token(aud="somebody-else")
    with pytest.raises(InvalidAudienceError):
        await verify_token(
            token,
            expected_audience=issuer.audience,
            expected_issuer=issuer.issuer,
            jwks_cache=make_jwks_cache(),
        )


async def test_an_expired_token_is_still_rejected() -> None:
    issuer = shared_issuer()
    token = mint_test_token(ttl_seconds=-60)
    with pytest.raises(ExpiredTokenError):
        await verify_token(
            token,
            expected_audience=issuer.audience,
            expected_issuer=issuer.issuer,
            jwks_cache=make_jwks_cache(),
        )


async def test_a_token_can_be_minted_under_a_services_own_issuer() -> None:
    """Services verify `iss` against their own configured value.

    Without this the harness would sign perfectly good tokens that every
    service rejects — which looks exactly like a broken verifier.
    """
    service_issuer = "https://auth.example.test/realms/notes"
    token = mint_test_token(roles=["device"], iss=service_issuer)
    claims = await verify_token(
        token,
        expected_audience=shared_issuer().audience,
        expected_issuer=service_issuer,
        jwks_cache=shared_issuer().jwks_cache_for(service_issuer),
    )
    assert claims.roles == ["device"]


def test_installing_drops_a_stale_current_user_closure() -> None:
    """Services cache the built dependency; swapping only the cache would
    leave the old key in use and the test passing for the wrong reason."""
    state = _State()
    state._current_user_dep = object()  # type: ignore[attr-defined]
    install_test_issuer(state)
    assert not hasattr(state, "_current_user_dep")
    assert state.jwks_cache is not None


def test_auth_headers_is_a_bearer_header() -> None:
    headers = auth_headers(roles=["auditor"])
    assert set(headers) == {"Authorization"}
    assert headers["Authorization"].startswith("Bearer ey")


def test_extra_claims_reach_the_payload() -> None:
    """So a test can assert on `mfa`, a device role, or a bad claim."""
    from jose import jwt

    payload = jwt.get_unverified_claims(mint_test_token(mfa=True, roles=["device"]))
    assert payload["mfa"] is True
    assert payload["roles"] == ["device"]
