"""The list of issuers a service trusts (FND-1, ADR-0047 / ADR-IDX-09).

Until this module existed, every service verified against exactly one
issuer: three strings in its settings (``AUTH_ISSUER``, ``AUTH_JWKS_URL``,
``AUTH_AUDIENCE``) threaded straight into :func:`auth.verify_token`. That
made the Keycloak → native cut-over a single instant for the whole fleet:
the moment auth-service starts signing with a different ``iss``, every
token already in a browser tab is rejected by every service.

An issuer *list* turns that instant into a period. During the bounded
``dual`` window (ADR-0047) the fleet trusts Keycloak's issuer and
auth-service's own; a token is verified against the entry whose
``issuer`` matches its ``iss`` claim, **and against that entry only** —
selecting a config never relaxes it. An ``iss`` matching no entry is
rejected before any key lookup.

The same mechanism is what makes issuer rotation possible at all, so it
outlives the dual period.

Configuration::

    AUTH_ISSUERS_JSON='[{"issuer":"https://kc/realms/notes",
                         "jwks_url":"https://kc/realms/notes/protocol/openid-connect/certs",
                         "audience":"mdx-api"},
                        {"issuer":"https://auth.example.com",
                         "jwks_url":"https://auth.example.com/.well-known/jwks.json",
                         "audience":"mdx-api"}]'

When it is absent or empty, ``AUTH_ISSUER`` / ``AUTH_JWKS_URL`` /
``AUTH_AUDIENCE`` build a one-element list — bit for bit the behaviour
every service had before this module.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "IssuerConfig",
    "IssuerConfigError",
    "issuer_url_map",
    "issuers_from_env",
    "parse_issuers_json",
]


class IssuerConfigError(ValueError):
    """``AUTH_ISSUERS_JSON`` is malformed.

    Deliberately a startup failure rather than a fallback to the legacy
    single-issuer vars: a typo that silently drops the second issuer
    would look exactly like a working deployment until the first native
    token arrives, which is the worst possible time to find out.
    """


@dataclass(frozen=True, slots=True)
class IssuerConfig:
    """One trusted issuer: who signs, where its keys are, what ``aud`` it uses.

    ``audience`` is per issuer rather than fleet-wide because it is the
    only thing standing between "this token was minted for our API" and
    "this token was minted by the same IdP for something else". Two
    issuers that happen to share an audience today may not tomorrow.
    """

    issuer: str
    jwks_url: str
    audience: str

    def __post_init__(self) -> None:
        for field_name in ("issuer", "jwks_url", "audience"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise IssuerConfigError(f"issuer entry has an empty {field_name}")


def parse_issuers_json(raw: str) -> list[IssuerConfig]:
    """Parse ``AUTH_ISSUERS_JSON`` into configs, or raise :class:`IssuerConfigError`."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IssuerConfigError(f"AUTH_ISSUERS_JSON is not valid JSON: {exc}") from exc

    if not isinstance(parsed, list) or not parsed:
        raise IssuerConfigError("AUTH_ISSUERS_JSON must be a non-empty JSON array")

    configs: list[IssuerConfig] = []
    for index, entry in enumerate(parsed):
        if not isinstance(entry, dict):
            raise IssuerConfigError(f"AUTH_ISSUERS_JSON[{index}] is not an object")
        unknown = set(entry) - {"issuer", "jwks_url", "audience"}
        if unknown:
            # A misspelt key would otherwise become a silently missing
            # field with a confusing "empty audience" error.
            raise IssuerConfigError(
                f"AUTH_ISSUERS_JSON[{index}] has unknown keys: {sorted(unknown)}"
            )
        missing = {"issuer", "jwks_url", "audience"} - set(entry)
        if missing:
            raise IssuerConfigError(
                f"AUTH_ISSUERS_JSON[{index}] is missing: {sorted(missing)}"
            )
        try:
            configs.append(
                IssuerConfig(
                    issuer=entry["issuer"],
                    jwks_url=entry["jwks_url"],
                    audience=entry["audience"],
                )
            )
        except IssuerConfigError as exc:
            raise IssuerConfigError(f"AUTH_ISSUERS_JSON[{index}]: {exc}") from exc

    seen: set[str] = set()
    for config in configs:
        if config.issuer in seen:
            # Two entries for one `iss` means one of them is dead config
            # that nobody will notice is dead.
            raise IssuerConfigError(f"AUTH_ISSUERS_JSON has duplicate issuer {config.issuer!r}")
        seen.add(config.issuer)
    return configs


def issuers_from_env(
    issuers_json: str | None,
    *,
    issuer: str,
    jwks_url: str,
    audience: str,
) -> list[IssuerConfig]:
    """The trusted-issuer list for a service, from either configuration style.

    ``issuers_json`` wins when it is set. Otherwise the three legacy
    values build the one-element list — the pre-FND-1 behaviour, so a
    deployment that sets nothing new keeps working unchanged.
    """
    if issuers_json and issuers_json.strip():
        return parse_issuers_json(issuers_json)
    return [IssuerConfig(issuer=issuer, jwks_url=jwks_url, audience=audience)]


def issuer_url_map(issuers: Sequence[IssuerConfig]) -> dict[str, str]:
    """``{issuer: jwks_url}`` — what :class:`auth.jwks.JwksCache` is built from."""
    return {config.issuer: config.jwks_url for config in issuers}
