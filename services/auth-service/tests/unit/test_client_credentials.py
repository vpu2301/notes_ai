"""IDX-B1b — client secrets, and what a non-human token must look like.

The claims-parity test in here is the sprint's load-bearing one, and it
does **not** assert byte-parity with a live Keycloak token. It cannot:
a real ``room-device-demo`` token captured from the dev realm is
*rejected* by ``libs/auth.Claims`` on four counts (no ``sid``, plus
``client_id``/``clientHost``/``clientAddress`` which the model forbids).
The captured payload is checked in below so that claim is verifiable
rather than asserted, and parity is measured against the shape the fleet
actually accepts — same ``sub``/``tid``/``roles``/``aud``, and a token
that ``Claims`` will parse.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from jose import jwt

from auth import Claims
from auth_service.domain import credentials as cred
from auth_service.domain.signing_keys import KeySet
from auth_service.domain.token_service import TokenService

DEV_KEYS = Path(__file__).resolve().parents[4] / "infra" / "dev" / "auth-signing-dev.json"

# Captured from the dev realm on 2026-09-05:
#   curl -d grant_type=client_credentials -d client_id=room-device-demo \
#        -d client_secret=dev-room-device-secret \
#        http://localhost:8088/realms/notes/protocol/openid-connect/token
# Trimmed to the claim set; values that change per issuance are marked.
KEYCLOAK_DEVICE_TOKEN = {
    "acr": "1",
    "aud": "mdx-api",
    "azp": "room-device-demo",
    "clientAddress": "172.19.0.1",
    "clientHost": "172.19.0.1",
    "client_id": "room-device-demo",
    "email_verified": False,
    "exp": 1788635347,
    "iat": 1788634447,
    "iss": "http://localhost:8088/realms/notes",
    "jti": "40ec508a-f5c4-42b2-b579-0af9824b53f8",
    "preferred_username": "service-account-room-device-demo",
    "realm_access": {"roles": ["device"]},
    "roles": ["device"],
    "scope": "profile email",
    "sub": "ba56d4f8-3c24-4736-a6c5-a50276b6f6c9",
    "tid": "00000000-0000-0000-0000-00000000000a",
    "typ": "Bearer",
}


# ── secret format ────────────────────────────────────────────────────────


def test_a_secret_is_tagged_prefixed_and_full_entropy() -> None:
    s = cred.generate_secret()
    assert s.value.startswith(cred.TAG)
    assert s.value.split("_")[2] == s.prefix
    assert len(s.prefix) == cred.PREFIX_LEN
    # 32 bytes → 43 url-safe characters.
    body = s.value[len(cred.TAG) + cred.PREFIX_LEN + 1 :]
    assert len(body) == 43
    assert cred.looks_like_secret(s.value)


def test_two_secrets_never_collide() -> None:
    values = {cred.generate_secret().value for _ in range(200)}
    assert len(values) == 200


def test_the_hash_covers_the_whole_string_so_a_prefix_cannot_be_swapped() -> None:
    """``mdx_sk_AAAA_<body>`` and ``mdx_sk_BBBB_<body>`` are different secrets."""
    s = cred.generate_secret()
    swapped = s.value.replace(s.prefix, "deadbeef", 1)
    assert swapped != s.value
    assert cred.secret_hash(swapped) != s.hash_hex


def test_comparison_is_constant_time_and_correct() -> None:
    s = cred.generate_secret()
    assert cred.hashes_match(s.hash_hex, cred.secret_hash(s.value))
    assert not cred.hashes_match(s.hash_hex, cred.secret_hash(s.value + "x"))


@pytest.mark.parametrize("bad", ["", "short", "hunter2", "x" * 500, "mdx_sk_" + "y" * 300])
def test_an_out_of_range_secret_is_rejected_before_the_database(bad: str) -> None:
    """The shape check exists so an attacker-chosen megabyte never becomes
    a megabyte-wide index probe."""
    assert not cred.looks_like_secret(bad)


def test_the_legacy_dev_secret_still_reaches_the_hash_comparison() -> None:
    """The check is a length bound, not a format.

    Requiring the `mdx_sk_` tag would mean every dev config had to change
    on the day the token endpoint moved — and would hand an attacker a
    free oracle: any string without the tag would skip the comparison
    entirely and answer faster.
    """
    assert cred.looks_like_secret("dev-room-device-secret")
    assert cred.looks_like_secret("dev-secret-change-in-prod-mdx-backend")


def test_roles_are_fixed_per_kind() -> None:
    assert cred.roles_for("device") == ["device"]
    assert cred.roles_for("service") == ["service"]
    with pytest.raises(ValueError):
        cred.roles_for("admin")


def test_the_role_map_matches_the_migrations_check_constraint() -> None:
    """The API refuses a bad combination with a 400 rather than letting
    Postgres refuse it with a 500 — so the two must agree."""
    sql = (
        Path(__file__).resolve().parents[4]
        / "infra"
        / "postgres"
        / "migrations"
        / "0026_service_credentials.sql"
    ).read_text()
    # Whitespace-normalised: the assertion is that the two agree, not that
    # the SQL is aligned a particular way.
    normalised = " ".join(sql.split())
    for kind, roles in cred.ROLES_FOR_KIND.items():
        assert f"kind = '{kind}' AND roles = ARRAY['{roles[0]}']" in normalised


# ── claims parity ────────────────────────────────────────────────────────


def test_the_captured_keycloak_device_token_is_rejected_by_claims() -> None:
    """The finding this sprint is built around, pinned as a test.

    Ambient capture through a Keycloak room device does not work today —
    `POST /asr/jobs` runs `requires("asr.write", …)` → `current_user` →
    `Claims(**payload)`, and this payload fails it. B1b does not merely
    preserve the device path; it is the first time that path can work.
    """
    with pytest.raises(Exception) as excinfo:
        Claims(**KEYCLOAK_DEVICE_TOKEN)
    message = str(excinfo.value)
    assert "sid" in message
    for forbidden in ("client_id", "clientHost", "clientAddress"):
        assert forbidden in message


def test_a_native_device_token_carries_the_same_identity_and_parses() -> None:
    keys = KeySet.from_json(DEV_KEYS.read_text())
    tokens = TokenService(
        keys=keys,
        issuer="http://localhost:8000",
        audience="mdx-api",
        access_ttl_seconds=900,
    )
    credential_id = uuid4()
    tenant_id = KEYCLOAK_DEVICE_TOKEN["tid"]

    minted = tokens.mint(
        identity_id=credential_id,
        session_id=str(credential_id),
        tenant_id=UUID(str(tenant_id)),
        roles=["device"],
    )
    payload = jwt.get_unverified_claims(minted.token)

    # The three claims that decide what a device may do are identical in
    # kind to Keycloak's, and `aud` matches so the fleet's verifier accepts.
    assert payload["roles"] == KEYCLOAK_DEVICE_TOKEN["roles"] == ["device"]
    assert payload["tid"] == KEYCLOAK_DEVICE_TOKEN["tid"]
    assert payload["aud"] == KEYCLOAK_DEVICE_TOKEN["aud"] == "mdx-api"
    assert payload["typ"] == KEYCLOAK_DEVICE_TOKEN["typ"] == "Bearer"
    assert payload["sub"] == str(credential_id)

    # ...and unlike the Keycloak token, this one is something the fleet
    # can actually parse.
    claims = Claims(**payload)
    assert claims.roles == ["device"]
    assert str(claims.tid) == tenant_id
    # `sid` stands in as the credential id: there is exactly one "session"
    # per credential, forever, and a denylist push on either key kills it.
    assert claims.sid == str(credential_id) == str(claims.sub)
    assert claims.mfa is False


def test_a_native_token_carries_no_keycloak_only_claims() -> None:
    keys = KeySet.from_json(DEV_KEYS.read_text())
    tokens = TokenService(keys=keys, issuer="http://i", audience="mdx-api", access_ttl_seconds=900)
    cid = uuid4()
    payload = jwt.get_unverified_claims(
        tokens.mint(
            identity_id=cid,
            session_id=str(cid),
            tenant_id=uuid4(),
            roles=["service"],
        ).token
    )
    for junk in (
        "clientHost",
        "clientAddress",
        "client_id",
        "preferred_username",
        "realm_access",
        "resource_access",
        "email_verified",
        "acr",
    ):
        assert junk not in payload, f"{junk} is Keycloak bookkeeping, not our contract"


def test_the_token_has_no_refresh_companion() -> None:
    """A machine holding its own secret can ask again whenever it likes."""
    from auth_service.routers.oauth import TokenGrantResponse

    fields = set(TokenGrantResponse.model_fields)
    assert fields == {"access_token", "token_type", "expires_in"}
    assert "refresh_token" not in fields


# ── the leak-scanning tag ────────────────────────────────────────────────


def test_a_secret_is_redacted_wherever_it_appears_in_a_log(caplog) -> None:
    """Key-based redaction cannot catch a secret interpolated into a message."""
    from observability import scrub
    from observability.pii_filter import redact_values

    secret = cred.generate_secret().value
    assert secret not in redact_values(f"configured client with {secret}")
    assert secret not in json.dumps(scrub({"some_unpredicted_field": f"value={secret}", "n": 1}))
    del caplog


def test_the_prefix_alone_is_safe_to_show() -> None:
    """It identifies which of two live secrets is deployed, and nothing else."""
    s = cred.generate_secret()
    assert cred.prefix_of(s.value) == s.prefix
    assert s.prefix in s.value
    # Knowing the prefix must not help: the entropy is all in the body.
    assert len(s.value) - len(s.prefix) > 50
    assert cred.prefix_of("not-ours") == ""


def test_expiry_and_ttl_bounds_are_the_documented_ones() -> None:
    from auth_service.domain import credential_service as cs

    assert cs.DEFAULT_ROTATION_TTL_SECONDS == 86_400
    assert cs.MAX_ROTATION_TTL_SECONDS == 604_800
    assert cs.MAX_LIVE_SECRETS == 2
    assert (cs.LOCK_THRESHOLD, cs.LOCK_WINDOW_SECONDS, cs.LOCK_SECONDS) == (10, 600, 900)
