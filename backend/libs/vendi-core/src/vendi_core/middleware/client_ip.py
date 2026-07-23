"""CIDR-gated client IP resolution for X-Forwarded-For.

Reading X-Forwarded-For naively (e.g. ``xff.split(",")[0]``) lets any client
spoof its source IP — useful for forging audit-log entries or evading
rate-limits keyed on client IP. This helper closes the gap:

1. If the request's immediate peer is *not* in the configured trusted-proxy
   CIDR list, XFF is ignored (the peer is the truth).
2. If the peer is a trusted proxy, the first XFF entry is honored — but only
   after passing a strict shape check (rejects ``ip:port``, IPv6 zone IDs,
   hostnames, garbage).

Configure via ``app.state.trusted_proxies`` (tuple of CIDR strings, e.g.
``("172.16.0.0/12", "10.0.0.0/8")``). Empty tuple = fail-closed: always
return the peer.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache

from starlette.requests import Request


@lru_cache(maxsize=8)
def _parsed_trusted_networks(
    cidrs_tuple: tuple[str, ...],
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(c, strict=False) for c in cidrs_tuple)


def trusted_client_ip(request: Request, trusted_cidrs: tuple[str, ...]) -> str | None:
    peer = request.client.host if request.client else None
    if not peer:
        return None
    if not trusted_cidrs:
        return peer

    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer

    nets = _parsed_trusted_networks(trusted_cidrs)
    if not any(peer_ip in n for n in nets):
        return peer

    xff = request.headers.get("x-forwarded-for", "")
    validated = _validated_xff_entry(xff)
    return validated or peer


def _validated_xff_entry(xff: str) -> str | None:
    if not xff:
        return None
    first = xff.split(",")[0].strip()
    if not first:
        return None
    # IPv6 zone IDs (e.g. fe80::1%eth0) are not transport addresses.
    if "%" in first:
        return None
    # Heuristic: IPv4 with port (1.2.3.4:5678) — single colon AND dots present.
    if "." in first and first.count(":") == 1:
        return None
    try:
        ipaddress.ip_address(first)
    except ValueError:
        return None
    return first
