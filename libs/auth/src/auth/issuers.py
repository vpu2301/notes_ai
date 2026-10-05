"""The list of issuers a service trusts (ADR-0047): ``AUTH_ISSUERS_JSON``, else the legacy single-issuer vars.

A token is verified against the entry matching its ``iss`` and that entry only; no match is rejected before any key lookup.
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
    """``AUTH_ISSUERS_JSON`` is malformed: a startup failure, never a silent fallback to the legacy vars."""


@dataclass(frozen=True, slots=True)
class IssuerConfig:
    """One trusted issuer; ``audience`` is per issuer, not fleet-wide."""

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
            raise IssuerConfigError(
                f"AUTH_ISSUERS_JSON[{index}] has unknown keys: {sorted(unknown)}"
            )
        missing = {"issuer", "jwks_url", "audience"} - set(entry)
        if missing:
            raise IssuerConfigError(f"AUTH_ISSUERS_JSON[{index}] is missing: {sorted(missing)}")
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
    """``issuers_json`` when set, else a one-element list from the legacy values."""
    if issuers_json and issuers_json.strip():
        return parse_issuers_json(issuers_json)
    return [IssuerConfig(issuer=issuer, jwks_url=jwks_url, audience=audience)]


def issuer_url_map(issuers: Sequence[IssuerConfig]) -> dict[str, str]:
    """``{issuer: jwks_url}`` — what :class:`auth.jwks.JwksCache` is built from."""
    return {config.issuer: config.jwks_url for config in issuers}
