from __future__ import annotations

import ipaddress
import socket

import pytest
from app.services.url_safety import (
    _raise_if_non_public_ip,
    _resolve_host_ips,
    validate_proxy_endpoint,
)


@pytest.mark.asyncio
async def test_resolve_host_ips_retries_transient_dns_failure(monkeypatch):
    calls = {"count": 0}

    def _flaky_getaddrinfo(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise socket.gaierror("temporary dns failure")
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", _flaky_getaddrinfo)
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr("app.services.url_safety.asyncio.sleep", _sleep)

    assert await _resolve_host_ips("example.com", 443) == ["93.184.216.34"]
    assert calls["count"] == 2


def test_raise_if_non_public_ip_allows_ipv6_global_addresses():
    _raise_if_non_public_ip(ipaddress.ip_address("2606:2800:220:1:248:1893:25c8:1946"), "example.com")


@pytest.mark.asyncio
async def test_validate_proxy_endpoint_rejects_localhost():
    with pytest.raises(ValueError, match="Proxy host is not allowed"):
        await validate_proxy_endpoint("http://localhost:8080")


@pytest.mark.asyncio
async def test_validate_proxy_endpoint_rejects_private_literal_ip():
    with pytest.raises(ValueError, match="non-public IP"):
        await validate_proxy_endpoint("http://10.1.2.3:8080")


@pytest.mark.asyncio
async def test_validate_proxy_endpoint_accepts_public_proxy_hostname(monkeypatch):
    async def _resolve_public(_hostname: str, _port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr("app.services.url_safety._resolve_host_ips", _resolve_public)
    target = await validate_proxy_endpoint("http://proxy.example.com:8080")
    assert target.hostname == "proxy.example.com"
    assert target.port == 8080
