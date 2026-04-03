from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlparse


_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
}
_BLOCKED_SUFFIXES = (".local",)


async def ensure_public_crawl_targets(urls: Iterable[str]) -> None:
    seen: set[str] = set()
    for raw_url in urls:
        candidate = str(raw_url or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        await validate_public_target(candidate)


async def validate_public_target(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    scheme = str(parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError("Only http:// and https:// targets are allowed")

    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Target URL must include a hostname")
    if hostname in _BLOCKED_HOSTNAMES or any(hostname.endswith(suffix) for suffix in _BLOCKED_SUFFIXES):
        raise ValueError(f"Target host is not allowed: {hostname}")

    literal_ip = _parse_ip(hostname)
    if literal_ip is not None:
        _raise_if_non_public_ip(literal_ip, hostname)
        return

    resolved_ips = await asyncio.to_thread(_resolve_host_ips, hostname, _default_port(parsed.scheme))
    if not resolved_ips:
        raise ValueError(f"Target host could not be resolved: {hostname}")
    for ip_text in resolved_ips:
        ip_value = _parse_ip(ip_text)
        if ip_value is None:
            continue
        _raise_if_non_public_ip(ip_value, hostname)


def _resolve_host_ips(hostname: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError(f"Target host could not be resolved: {hostname}") from exc

    resolved: list[str] = []
    seen: set[str] = set()
    for record in records:
        sockaddr = record[4]
        ip_text = str(sockaddr[0] or "").strip()
        if not ip_text or ip_text in seen:
            continue
        seen.add(ip_text)
        resolved.append(ip_text)
    return resolved


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _raise_if_non_public_ip(
    ip_value: ipaddress.IPv4Address | ipaddress.IPv6Address,
    host_label: str,
) -> None:
    if ip_value.is_global:
        return
    raise ValueError(f"Target host resolves to a non-public IP address: {host_label} -> {ip_value}")


def _default_port(scheme: str) -> int:
    return 443 if str(scheme or "").lower() == "https" else 80
