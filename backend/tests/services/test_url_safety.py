from __future__ import annotations

import socket

import pytest
from app.services.url_safety import (
    validate_public_target,
    validate_proxy_endpoint,
)


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


@pytest.mark.asyncio
async def test_validate_public_target_rejects_link_local_literal_ip():
    with pytest.raises(ValueError, match="non-public IP"):
        await validate_public_target("http://169.254.169.254/latest/meta-data")


@pytest.mark.asyncio
async def test_validate_public_target_rejects_cgnat_literal_ip():
    with pytest.raises(ValueError, match="non-public IP"):
        await validate_public_target("http://100.64.12.34/internal")


@pytest.mark.asyncio
async def test_validate_public_target_rejects_blocked_metadata_hostname():
    with pytest.raises(ValueError, match="Target host is not allowed"):
        await validate_public_target("http://metadata.google.internal/computeMetadata/v1/")


@pytest.mark.asyncio
async def test_validate_public_target_rejects_local_suffix_hostname():
    with pytest.raises(ValueError, match="Target host is not allowed"):
        await validate_public_target("http://printer.local/status")


@pytest.mark.asyncio
async def test_validate_public_target_accepts_public_literal_ip():
    target = await validate_public_target("https://93.184.216.34/product")

    assert target.hostname == "93.184.216.34"
    assert target.scheme == "https"
    assert target.port == 443
    assert target.resolved_ips == ("93.184.216.34",)
    assert target.dns_resolved is False
