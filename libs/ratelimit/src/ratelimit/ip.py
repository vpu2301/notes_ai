"""Client IP for rate-limit keys: the peer, unless it is a trusted proxy, then the rightmost untrusted
``X-Forwarded-For`` hop (a client-written header is never reached unless every hop before it is trusted).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def parse_cidrs(raw: str | Iterable[str]) -> list[Network]:
    """``"10.0.0.0/8, 172.16.0.0/12"`` → networks. Bare addresses become /32 or /128."""
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    out: list[Network] = []
    for item in items:
        value = item.strip()
        if value:
            out.append(ipaddress.ip_network(value, strict=False))
    return out


def _is_trusted(addr: str, trusted: Sequence[Network]) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in trusted)


def client_ip(
    *,
    peer: str | None,
    forwarded_for: str | None,
    trusted_proxies: Sequence[Network] = (),
) -> str:
    """Resolve the address a rate-limit key should be built from."""
    if not peer:
        return "unknown"
    if not trusted_proxies or not _is_trusted(peer, trusted_proxies) or not forwarded_for:
        return peer
    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop, trusted_proxies):
            try:
                return str(ipaddress.ip_address(hop))
            except ValueError:
                return "unknown"  # a forged, unparsable hop: bucket it, don't crash
    return peer
