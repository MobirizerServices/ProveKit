"""Outbound URL guard (SSRF protection), enforced at every provider entry point.

Local mode (default): this is a dev tool that legitimately targets localhost and
private IPs, so those stay allowed — only the link-local block (incl. the
169.254.169.254 cloud-metadata endpoint) is refused.

Hosted mode (HOSTED=true): all private/reserved ranges are blocked, and hostnames
are DNS-resolved so a name pointing at an internal IP is caught too. A rebinding
server could still answer differently on the actual connect — pinning connections
through an egress proxy is the complete fix; accepted residual risk pre-GA.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from ..config import get_settings

_BLOCKED_HOSTS = {"metadata", "metadata.google.internal"}


class BlockedURL(ValueError):
    """Raised when an outbound URL targets a forbidden address."""


def _check_ip(ip, hosted: bool) -> None:
    if ip.is_link_local:
        raise BlockedURL("Link-local / metadata addresses are not allowed")
    if hosted and not ip.is_global:
        raise BlockedURL("Private / internal addresses are not allowed in hosted mode")


def guard_url(url: str) -> None:
    hosted = get_settings().hosted
    host = (urlparse(str(url)).hostname or "").lower()
    if not host:
        raise BlockedURL("URL has no host")
    if host in _BLOCKED_HOSTS:
        raise BlockedURL("Target host is not allowed")

    ip = None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass  # not a literal IP — a hostname
    if ip is not None:
        _check_ip(ip, hosted)
        return

    if hosted:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            raise BlockedURL(f"Cannot resolve host '{host}'")
        for info in infos:
            _check_ip(ipaddress.ip_address(info[4][0]), hosted)
