"""FND-1: a service trusts a LIST of issuers, and nothing beyond it.

The table in the sprint brief, one test per row. The negative cases carry
the weight here: a multi-issuer verifier that got selection wrong would
accept a token signed by anyone who can name a trusted `iss`, which is
worse than the single-issuer verifier it replaces.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx
import pytest

from auth.claims import Claims
from auth.exceptions import (
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
    KidNotFoundError,
)
from auth.issuers import (
    IssuerConfig,
    IssuerConfigError,
    issuer_url_map,
    issuers_from_env,
    parse_issuers_json,
)
from auth.jwks import JwksCache
from auth.testing import TestIssuer, multi_issuer_jwks_cache
from auth.verifier import verify_token

from ..conftest import AUDIENCE, ISSUER

# asyncio_mode = auto (pyproject); the sync config tests below would warn
# under a module-level asyncio mark.

KEYCLOAK = "https://kc.test.invalid/realms/notes"
NATIVE = "https://auth.test.invalid"
THIRD = "https://evil.test.invalid"


# ── configuration ────────────────────────────────────────────────────────


def test_legacy_env_vars_build_a_one_element_list() -> None:
    issuers = issuers_from_env(
        None, issuer=ISSUER, jwks_url="https://kc/certs", audience=AUDIENCE
    )
    assert issuers == [
        IssuerConfig(issuer=ISSUER, jwks_url="https://kc/certs", audience=AUDIENCE)
    ]


def test_empty_issuers_json_falls_back_to_legacy_vars() -> None:
    # An unset env var arrives as "" through pydantic, not None.
    assert issuers_from_env(
        "   ", issuer=ISSUER, jwks_url="https://kc/certs", audience=AUDIENCE
    ) == [IssuerConfig(issuer=ISSUER, jwks_url="https://kc/certs", audience=AUDIENCE)]


def test_issuers_json_wins_over_legacy_vars() -> None:
    raw = json.dumps(
        [
            {"issuer": KEYCLOAK, "jwks_url": f"{KEYCLOAK}/certs", "audience": "mdx-api"},
            {"issuer": NATIVE, "jwks_url": f"{NATIVE}/.well-known/jwks.json", "audience": "mdx-api"},
        ]
    )
    issuers = issuers_from_env(raw, issuer=ISSUER, jwks_url="ignored", audience="ignored")
    assert [c.issuer for c in issuers] == [KEYCLOAK, NATIVE]
    assert issuer_url_map(issuers) == {
        KEYCLOAK: f"{KEYCLOAK}/certs",
        NATIVE: f"{NATIVE}/.well-known/jwks.json",
    }


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",
        "[]",
        '[{"issuer": "https://a", "jwks_url": "https://a/j"}]',  # no audience
        '[{"issuer": "", "jwks_url": "https://a/j", "audience": "mdx-api"}]',
        '[{"issuer": "https://a", "jwks_url": "https://a/j", "audience": "x", "typo": 1}]',
        '[{"issuer": "https://a", "jwks_url": "https://a/j", "audience": "x"},'
        ' {"issuer": "https://a", "jwks_url": "https://b/j", "audience": "x"}]',  # duplicate
    ],
)
def test_malformed_issuers_json_is_a_startup_failure(raw: str) -> None:
    # Never a silent fallback: a dropped second issuer looks like a healthy
    # deployment until the first native token arrives.
    with pytest.raises(IssuerConfigError):
        parse_issuers_json(raw)


# ── verification against a list ──────────────────────────────────────────


@pytest.fixture
def keycloak_key() -> TestIssuer:
    return TestIssuer(issuer=KEYCLOAK)


@pytest.fixture
def native_key() -> TestIssuer:
    return TestIssuer(issuer=NATIVE)


@pytest.fixture
def two_issuers(
    keycloak_key: TestIssuer, native_key: TestIssuer
) -> tuple[list[IssuerConfig], JwksCache]:
    configs = [keycloak_key.config(), native_key.config()]
    cache = multi_issuer_jwks_cache([(configs[0], keycloak_key), (configs[1], native_key)])
    return configs, cache


async def test_one_element_list_matches_legacy_behaviour(
    mint_token: Callable[..., str], jwks_cache: JwksCache
) -> None:
    token = mint_token()
    legacy = await verify_token(
        token, expected_audience=AUDIENCE, expected_issuer=ISSUER, jwks_cache=jwks_cache
    )
    listed = await verify_token(
        token,
        issuers=[IssuerConfig(issuer=ISSUER, jwks_url="unused", audience=AUDIENCE)],
        jwks_cache=jwks_cache,
    )
    assert isinstance(legacy, Claims)
    assert legacy.model_dump() == listed.model_dump()


async def test_token_from_either_issuer_is_accepted(
    two_issuers: tuple[list[IssuerConfig], JwksCache],
    keycloak_key: TestIssuer,
    native_key: TestIssuer,
) -> None:
    configs, cache = two_issuers
    for key in (keycloak_key, native_key):
        claims = await verify_token(key.mint(), issuers=configs, jwks_cache=cache)
        assert claims.iss == key.issuer


async def test_jwks_is_fetched_only_from_the_matching_url(
    keycloak_key: TestIssuer, native_key: TestIssuer
) -> None:
    configs = [keycloak_key.config(), native_key.config()]
    requested: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == configs[0].jwks_url:
            return httpx.Response(200, json=keycloak_key.jwks_document())
        if str(request.url) == configs[1].jwks_url:
            return httpx.Response(200, json=native_key.jwks_document())
        return httpx.Response(404, json={"error": "not found"})

    cache = JwksCache(
        issuer_to_url=issuer_url_map(configs),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)),
    )

    await verify_token(native_key.mint(), issuers=configs, jwks_cache=cache)
    # The Keycloak document is never fetched to verify a native token —
    # a verifier that fetched both would leak the fact that a native
    # token exists to the issuer it does not belong to, and would make
    # every verify wait on the slower of two IdPs.
    assert requested == [configs[1].jwks_url]


async def test_unknown_issuer_is_rejected_before_any_fetch(
    two_issuers: tuple[list[IssuerConfig], JwksCache],
) -> None:
    configs, cache = two_issuers
    third = TestIssuer(issuer=THIRD)
    with pytest.raises(InvalidIssuerError):
        await verify_token(third.mint(), issuers=configs, jwks_cache=cache)
    assert cache.metrics.refresh_attempts == 0


async def test_third_issuer_signature_under_a_trusted_name_is_rejected(
    two_issuers: tuple[list[IssuerConfig], JwksCache],
) -> None:
    """The attack the issuer list must not open: a real signature, a borrowed name.

    Selecting a config by the unverified `iss` is only safe because the
    selected config's JWKS is then the *only* source of keys. A token
    signed by a key nobody published, claiming to be from a trusted
    issuer, must fail on the key lookup.
    """
    configs, cache = two_issuers
    stranger = TestIssuer(issuer=NATIVE)  # right name, wrong key
    with pytest.raises(KidNotFoundError):
        await verify_token(stranger.mint(), issuers=configs, jwks_cache=cache)


async def test_audience_is_taken_from_the_selected_entry_only(
    keycloak_key: TestIssuer, native_key: TestIssuer
) -> None:
    """Two issuers, two audiences: neither one's audience opens the other."""
    configs = [
        keycloak_key.config(audience="mdx-api"),
        native_key.config(audience="mdx-internal"),
    ]
    cache = multi_issuer_jwks_cache([(configs[0], keycloak_key), (configs[1], native_key)])

    await verify_token(native_key.mint(aud="mdx-internal"), issuers=configs, jwks_cache=cache)
    with pytest.raises(InvalidAudienceError):
        await verify_token(native_key.mint(aud="mdx-api"), issuers=configs, jwks_cache=cache)


async def test_alg_none_is_rejected(
    two_issuers: tuple[list[IssuerConfig], JwksCache], native_key: TestIssuer
) -> None:
    configs, cache = two_issuers
    import base64

    def _seg(obj: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    now = int(time.time())
    unsigned = (
        _seg({"alg": "none", "typ": "JWT", "kid": native_key.kid})
        + "."
        + _seg({"iss": NATIVE, "aud": AUDIENCE, "exp": now + 900})
        + "."
    )
    with pytest.raises(InvalidTokenError):
        await verify_token(unsigned, issuers=configs, jwks_cache=cache)


async def test_hs256_signed_with_the_public_key_is_rejected(
    two_issuers: tuple[list[IssuerConfig], JwksCache], native_key: TestIssuer
) -> None:
    """The algorithm-confusion classic: sign HS256 with the RSA public key."""
    from jose import jwt as jose_jwt

    configs, cache = two_issuers
    now = int(time.time())
    forged = jose_jwt.encode(
        {"iss": NATIVE, "aud": AUDIENCE, "sub": "x", "exp": now + 900},
        json.dumps(native_key.public_jwk),
        algorithm="HS256",
        headers={"kid": native_key.kid},
    )
    with pytest.raises(InvalidTokenError):
        await verify_token(forged, issuers=configs, jwks_cache=cache)


async def test_kid_miss_on_issuer_two_does_not_evict_issuer_one(
    keycloak_key: TestIssuer, native_key: TestIssuer
) -> None:
    configs = [keycloak_key.config(), native_key.config()]
    cache = multi_issuer_jwks_cache([(configs[0], keycloak_key), (configs[1], native_key)])

    await verify_token(keycloak_key.mint(), issuers=configs, jwks_cache=cache)
    fetches_after_warm = cache.metrics.refresh_attempts

    rogue = TestIssuer(issuer=NATIVE)
    with pytest.raises(KidNotFoundError):
        await verify_token(rogue.mint(), issuers=configs, jwks_cache=cache)

    # Issuer 1 still answers from cache: the miss cost one fetch against
    # issuer 2 and nothing at all against issuer 1.
    hits_before = cache.metrics.cache_hits
    await verify_token(keycloak_key.mint(), issuers=configs, jwks_cache=cache)
    assert cache.metrics.cache_hits == hits_before + 1
    assert cache.metrics.refresh_attempts == fetches_after_warm + 1


async def test_empty_jwks_for_issuer_two_leaves_issuer_one_working(
    keycloak_key: TestIssuer, native_key: TestIssuer
) -> None:
    """The FND-1 → BE-2 window: auth-service publishes `{"keys": []}`.

    An empty JWKS is a valid document. The fleet is deployed with both
    issuers configured BEFORE auth-service has a signing key, so this is
    the state every service runs in for the length of that rollout.
    """
    configs = [keycloak_key.config(), native_key.config()]
    cache = multi_issuer_jwks_cache([(configs[0], keycloak_key), (configs[1], None)])

    claims = await verify_token(keycloak_key.mint(), issuers=configs, jwks_cache=cache)
    assert claims.iss == KEYCLOAK

    with pytest.raises(KidNotFoundError):
        await verify_token(native_key.mint(), issuers=configs, jwks_cache=cache)
