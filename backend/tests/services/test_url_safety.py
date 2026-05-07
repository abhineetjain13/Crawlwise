from __future__ import annotations

import socket

import pytest

from app.services import url_safety
from app.services.config.security_rules import (
    BLOCKED_HOSTNAMES,
    BLOCKED_IPS,
    CGNAT_NETWORK,
)


@pytest.fixture(autouse=True)
def _stub_public_dns_resolution():
    yield


@pytest.mark.asyncio
async def test_resolve_host_ips_falls_back_to_ipv4_after_unspec_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def _fake_getaddrinfo(hostname: str, port: int, family: int, socktype: int):
        del hostname, port, socktype
        calls.append(family)
        if family == socket.AF_UNSPEC:
            raise socket.gaierror(11001, "getaddrinfo failed")
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        _fake_getaddrinfo,
    )
    monkeypatch.setattr(
        "app.services.url_safety.dns_resolution_families",
        lambda: (socket.AF_UNSPEC, socket.AF_INET),
    )

    resolved = await url_safety._resolve_host_ips("example.com", 443)

    assert resolved == ["93.184.216.34"]
    assert calls == [socket.AF_UNSPEC, socket.AF_INET]


@pytest.mark.asyncio
async def test_validate_public_target_rejects_configured_blocked_hostname() -> None:
    blocked_hostname = next(iter(BLOCKED_HOSTNAMES))

    with pytest.raises(url_safety.SecurityError, match="Target host is not allowed"):
        await url_safety.validate_public_target(f"https://{blocked_hostname}/")


def test_raise_if_non_public_ip_rejects_configured_blocked_ip() -> None:
    blocked_ip = next(iter(BLOCKED_IPS))

    with pytest.raises(
        url_safety.SecurityError,
        match="Target host resolves to a blocked platform IP address",
    ):
        url_safety._raise_if_non_public_ip(blocked_ip, "blocked.example", "Target")


def test_raise_if_non_public_ip_rejects_cgnat_range() -> None:
    ip_value = next(CGNAT_NETWORK.hosts())

    with pytest.raises(
        url_safety.SecurityError,
        match="Target host resolves to a non-public IP address",
    ):
        url_safety._raise_if_non_public_ip(ip_value, "cgnat.example", "Target")


@pytest.mark.asyncio
async def test_validate_proxy_endpoint_uses_proxy_resolution_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _always_fail_getaddrinfo(hostname: str, port: int, family: int, socktype: int):
        del hostname, port, family, socktype
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(
        "app.services.url_safety.socket.getaddrinfo",
        _always_fail_getaddrinfo,
    )
    monkeypatch.setattr(
        "app.services.url_safety.dns_resolution_families",
        lambda: (socket.AF_UNSPEC,),
    )

    with pytest.raises(ValueError, match="Proxy host could not be resolved"):
        await url_safety.validate_proxy_endpoint("http://proxy.example:8080")
