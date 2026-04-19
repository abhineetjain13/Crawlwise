from __future__ import annotations

import socket

import pytest

from app.services import url_safety


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
