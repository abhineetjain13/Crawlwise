from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlparse

from app.services.config.security_rules import (
    ALLOWED_PROXY_SCHEMES,
    ALLOWED_TARGET_SCHEMES,
    BLOCKED_HOSTNAMES,
    BLOCKED_HOST_SUFFIXES,
    BLOCKED_IPS,
    CGNAT_NETWORK,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.network_resolution import dns_resolution_families


class SecurityError(ValueError):
    """Raised when a URL is rejected for security policy reasons (SSRF guard,
    blocked hostname/IP, non-public resolution). Subclasses ValueError so
    existing `except ValueError` callers continue to work; security-aware
    callers can catch SecurityError specifically to distinguish SSRF
    rejections from generic input-validation failures."""


@dataclass(frozen=True)
class ValidatedTarget:
    hostname: str
    scheme: str
    port: int
    resolved_ips: tuple[str, ...]
    dns_resolved: bool = True


async def ensure_public_crawl_targets(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_url in urls:
        candidate = str(raw_url or "").strip()
        if not candidate:
            continue
        result = await validate_public_target(candidate)
        normalized_url = _rebuild_url(candidate, result)
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        normalized.append(normalized_url)
    return normalized


async def validate_public_target(url: str) -> ValidatedTarget:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ALLOWED_TARGET_SCHEMES:
        if not scheme and raw and not raw.startswith(("/", "#")):
            raw = f"https://{raw}"
            parsed = urlparse(raw)
            scheme = "https"
        else:
            raise ValueError("Only http:// and https:// targets are allowed")

    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Target URL must include a hostname")
    return await _validate_endpoint_host(
        hostname=hostname,
        scheme=scheme,
        port=_target_port(parsed),
        label="Target",
        unresolved_detail="Target host could not be resolved to a valid IP address",
        wrap_resolution_error=True,
    )


async def validate_proxy_endpoint(proxy_url: str) -> ValidatedTarget:
    parsed = urlparse(str(proxy_url or "").strip())
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ALLOWED_PROXY_SCHEMES:
        raise ValueError(
            "Only http://, https://, socks5://, and socks5h:// proxy endpoints are allowed"
        )
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Proxy URL must include a hostname")
    return await _validate_endpoint_host(
        hostname=hostname,
        scheme=scheme,
        port=_target_port(parsed),
        label="Proxy",
        unresolved_detail="Proxy host could not be resolved to a valid IP address",
        wrap_resolution_error=False,
    )


async def _validate_endpoint_host(
    *,
    hostname: str,
    scheme: str,
    port: int,
    label: str,
    unresolved_detail: str,
    wrap_resolution_error: bool,
) -> ValidatedTarget:
    _raise_if_blocked_hostname(hostname, label)
    literal_ip = _parse_ip(hostname)
    if literal_ip is not None:
        _raise_if_non_public_ip(literal_ip, hostname, label)
        return ValidatedTarget(
            hostname=hostname,
            scheme=scheme,
            port=port,
            resolved_ips=(hostname,),
            dns_resolved=False,
        )

    try:
        resolved_ips = await _resolve_host_ips(hostname, port, label=label)
    except ValueError as exc:
        if not wrap_resolution_error:
            raise
        raise ValueError(f"{unresolved_detail}: {hostname}") from exc
    validated_ips: list[str] = []
    for ip_text in resolved_ips:
        ip_value = _parse_ip(ip_text)
        if ip_value is None:
            continue
        _raise_if_non_public_ip(ip_value, hostname, label)
        validated_ips.append(ip_text)
    if not validated_ips:
        raise ValueError(f"{unresolved_detail}: {hostname}")
    return ValidatedTarget(
        hostname=hostname,
        scheme=scheme,
        port=port,
        resolved_ips=tuple(validated_ips),
    )


async def _resolve_host_ips(hostname: str, port: int, *, label: str = "Target") -> list[str]:
    attempts = max(1, int(crawler_runtime_settings.dns_resolution_retries) + 1)
    families = dns_resolution_families()
    records: list[
        tuple[
            socket.AddressFamily,
            socket.SocketKind,
            int,
            str,
            tuple[str, int] | tuple[str, int, int, int],
        ]
    ] | None = None
    last_error: socket.gaierror | None = None
    for attempt in range(1, attempts + 1):
        for family in families:
            try:
                raw_records = await asyncio.to_thread(
                    socket.getaddrinfo,
                    hostname,
                    port,
                    family,
                    socket.SOCK_STREAM,
                )
                records = cast(
                    list[
                        tuple[
                            socket.AddressFamily,
                            socket.SocketKind,
                            int,
                            str,
                            tuple[str, int] | tuple[str, int, int, int],
                        ]
                    ],
                    raw_records,
                )
                break
            except socket.gaierror as exc:
                last_error = exc
                continue
        if records is not None:
            break
        if attempt < attempts:
            await asyncio.sleep(
                max(0, crawler_runtime_settings.dns_resolution_retry_delay_ms) / 1000
            )
            continue
        raise ValueError(f"{label} host could not be resolved: {hostname}") from last_error

    resolved: list[str] = []
    seen: set[str] = set()
    if records is None:
        return resolved
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


def _raise_if_blocked_hostname(hostname: str, label: str) -> None:
    if hostname in BLOCKED_HOSTNAMES or any(
        hostname.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES
    ):
        raise SecurityError(f"{label} host is not allowed: {hostname}")


def _raise_if_non_public_ip(
    ip_value: ipaddress.IPv4Address | ipaddress.IPv6Address,
    host_label: str,
    label: str,
) -> None:
    if ip_value in BLOCKED_IPS:
        raise SecurityError(
            f"{label} host resolves to a blocked platform IP address: {host_label} -> {ip_value}"
        )
    if (
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_reserved
        or (isinstance(ip_value, ipaddress.IPv4Address) and ip_value in CGNAT_NETWORK)
    ):
        raise SecurityError(
            f"{label} host resolves to a non-public IP address: {host_label} -> {ip_value}"
        )
    if ip_value.is_global:
        return
    raise SecurityError(
        f"{label} host resolves to a non-public IP address: {host_label} -> {ip_value}"
    )


def _rebuild_url(original: str, target: ValidatedTarget) -> str:
    parsed = urlparse(original)
    if parsed.scheme:
        return original
    reconstructed = f"{target.scheme}://{original}"
    reparsed = urlparse(reconstructed)
    port_suffix = ""
    if reparsed.port is None and target.port != _default_port(target.scheme):
        port_suffix = f":{target.port}"
    hostname = reparsed.hostname or ""
    if ":" in hostname:  # IPv6 address
        hostname = f"[{hostname}]"
    netloc = hostname + port_suffix
    return reparsed._replace(scheme=target.scheme, netloc=netloc).geturl()

def _target_port(parsed) -> int:
    return int(parsed.port or _default_port(parsed.scheme))


def _default_port(scheme: str) -> int:
    normalized = str(scheme or "").lower()
    if normalized in {"socks5", "socks5h"}:
        return 1080
    return 443 if normalized == "https" else 80
