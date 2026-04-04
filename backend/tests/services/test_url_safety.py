from __future__ import annotations

import socket
import subprocess

from app.services.url_safety import _parse_nslookup_addresses, _resolve_host_ips


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


def test_resolve_host_ips_falls_back_to_nslookup(monkeypatch):
    def _raise_gaierror(*args, **kwargs):
        raise socket.gaierror("dns failure")

    monkeypatch.setattr("app.services.url_safety.socket.getaddrinfo", _raise_gaierror)
    monkeypatch.setattr(
        "app.services.url_safety.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="""
Server:  dsldevice.lan
Address:  192.168.1.1

Name:    world.openfoodfacts.org
Address:  213.36.253.214
""",
            stderr="",
        ),
    )

    assert _resolve_host_ips("world.openfoodfacts.org", 443) == ["213.36.253.214"]


def test_resolve_host_ips_retries_transient_dns_failure(monkeypatch):
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
    monkeypatch.setattr("app.services.url_safety.time.sleep", lambda _seconds: None)

    assert _resolve_host_ips("example.com", 443) == ["93.184.216.34"]
    assert calls["count"] == 2
