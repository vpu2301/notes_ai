"""Vault KV-v2 secret fetch for system HMAC keys at startup; fail-closed, no in-process re-fetch."""

from __future__ import annotations

from typing import Any

from .exceptions import MasterKeyError


async def fetch_kv_secrets(
    *,
    addr: str,
    token: object,
    path: str,
    mount: str = "secret",
    timeout_seconds: float = 5.0,
) -> dict[str, str]:
    """The ``data.data`` mapping of a KV-v2 secret; :class:`MasterKeyError` on any failure (fail-closed)."""
    import httpx

    from .master import _reveal

    token_value = _reveal(token)
    if not token_value:
        raise MasterKeyError("Vault token is empty; cannot fetch KV secrets")

    url = f"{addr.rstrip('/')}/v1/{mount.strip('/')}/data/{path.strip('/')}"
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.get(url, headers={"X-Vault-Token": token_value})
    except httpx.HTTPError as exc:
        raise MasterKeyError(
            f"Vault KV unreachable at {addr} ({type(exc).__name__}). "
            "See docs/runbooks/kms.md § vault-unreachable."
        ) from exc
    if resp.status_code != 200:
        raise MasterKeyError(
            f"Vault KV read {path!r} returned {resp.status_code}: {resp.text[:200]}"
        )
    payload: Any = resp.json()
    data = payload.get("data", {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data:
        raise MasterKeyError(f"Vault KV secret {path!r} is empty or malformed")
    out: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(v, str):
            raise MasterKeyError(f"Vault KV secret {path!r} field {k!r} is not a string")
        out[k] = v
    return out
