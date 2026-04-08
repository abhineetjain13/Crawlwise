from __future__ import annotations

import asyncio
import ipaddress
import socket

import pytest
from app.services.url_safety import (
    _parse_nslookup_addresses,
    _raise_if_non_public_ip,
    _resolve_host_ips,
    _resolve_host_ips_via_nslookup,
    validate_proxy_endpoint,
)


def test_parse_nslookup_addresses_ignores_dns_server_address():
    output = """
Server:  dsldevice.lan
Address:  192.168.1.1

Name:    shops.myshopify.com
Addresses:  2620:127:f00f:e::
\t  23.227.38.74
Aliases:  www.allbirds.com

Non-authoritative answer:
"""

    assert _parse_nslookup_addresses(output) == ["2620:127:f00f:e::", "23.227.38.74"]


@pytest.mark.asyncio
async def test_resolve_host_ips_falls_back_to_nslookup(monkeypatch):
    def _raise_gaierror(*args, **kwargs):
        raise socket.gaierror("dns failure")

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", _raise_gaierror)
    class DummyProcess:
        def __init__(self, stdout: bytes = b"", stderr: bytes = b"", *, returncode: int = 0):
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = returncode

        async def communicate(self):
            return (self.stdout, self.stderr)

    async def _create_subprocess_exec(*args, **kwargs):
        return DummyProcess(
            stdout=b"""
Server:  dsldevice.lan
Address:  192.168.1.1

Name:    world.openfoodfacts.org
Address:  213.36.253.214
""",
        )

    monkeypatch.setattr(
        "app.services.url_safety.asyncio.create_subprocess_exec",
        _create_subprocess_exec,
    )

    assert await _resolve_host_ips("world.openfoodfacts.org", 443) == ["213.36.253.214"]


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
async def test_resolve_host_ips_nslookup_timeout_kills_process(monkeypatch):
    def _raise_gaierror(*args, **kwargs):
        raise socket.gaierror("dns failure")

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", _raise_gaierror)

    class DummyProcess:
        def __init__(self):
            self.returncode = None
            self.killed = False
            self.waited = False

        async def communicate(self):
            await asyncio.sleep(0)
            return (b"", b"")

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            return self.returncode

    processes: list[DummyProcess] = []

    async def _create_subprocess_exec(*args, **kwargs):
        process = DummyProcess()
        processes.append(process)
        return process

    async def _timeout(*args, **kwargs):
        if args and hasattr(args[0], "close"):
            args[0].close()
        raise asyncio.TimeoutError

    monkeypatch.setattr("app.services.url_safety.asyncio.create_subprocess_exec", _create_subprocess_exec)
    monkeypatch.setattr("app.services.url_safety.asyncio.wait_for", _timeout)

    assert await _resolve_host_ips_via_nslookup("example.com") == []
    assert processes
    assert all(process.killed and process.waited for process in processes)


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
