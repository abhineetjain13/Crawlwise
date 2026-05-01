from __future__ import annotations

import ipaddress
from typing import Final


ALLOWED_TARGET_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
ALLOWED_PROXY_SCHEMES: Final[frozenset[str]] = frozenset(
    {"http", "https", "socks5", "socks5h"}
)
BLOCKED_HOSTNAMES: Final[frozenset[str]] = frozenset(
    {
        "instance-data",
        "instance-data.ec2.internal",
        "localhost",
        "localhost.localdomain",
        "metadata.azure.internal",
        "metadata.google.internal",
    }
)
BLOCKED_HOST_SUFFIXES: Final[tuple[str, ...]] = (".local",)
CGNAT_NETWORK: Final[ipaddress.IPv4Network | ipaddress.IPv6Network] = (
    ipaddress.ip_network("100.64.0.0/10")
)
BLOCKED_IPS: Final[frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]] = (
    frozenset(
        {
            ipaddress.ip_address("168.63.129.16"),
            ipaddress.ip_address("169.254.169.254"),
        }
    )
)


__all__ = [
    "ALLOWED_PROXY_SCHEMES",
    "ALLOWED_TARGET_SCHEMES",
    "BLOCKED_HOSTNAMES",
    "BLOCKED_HOST_SUFFIXES",
    "BLOCKED_IPS",
    "CGNAT_NETWORK",
]
