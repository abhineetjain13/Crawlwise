from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from app.services.pipeline_config import DNS_RESOLUTION_RETRIES, DNS_RESOLUTION_RETRY_DELAY_MS

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PROXY_SCHEMES = {"http", "https", "socks5", "socks5h"}
_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
}
_BLOCKED_SUFFIXES = (".local",)
_CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")


@dataclass(frozen=True)
class ValidatedTarget:
    hostname: str
    scheme: str
    port: int
    resolved_ips: tuple[str, ...]
    dns_resolved: bool = True


async def ensure_public_crawl_targets(urls: Iterable[str]) -> None:
    seen: set[str] = set()
    for raw_url in urls:
        candidate = str(raw_url or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        await validate_public_target(candidate)


async def validate_public_target(url: str) -> ValidatedTarget:
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
        return ValidatedTarget(
            hostname=hostname,
            scheme=scheme,
            port=_target_port(parsed),
            resolved_ips=(hostname,),
            dns_resolved=False,
        )

    port = _target_port(parsed)
    try:
        resolved_ips = await _resolve_host_ips(hostname, port)
    except ValueError as exc:
        raise ValueError(
            f"Proxy host could not be resolved to a valid IP address: {hostname}"
        ) from exc
    validated_ips: list[str] = []
    for ip_text in resolved_ips:
        ip_value = _parse_ip(ip_text)
        if ip_value is None:
            continue
        _raise_if_non_public_ip(ip_value, hostname)
        validated_ips.append(ip_text)
    if not validated_ips:
        raise ValueError(f"Target host could not be resolved to a valid IP address: {hostname}")
    return ValidatedTarget(
        hostname=hostname,
        scheme=scheme,
        port=port,
        resolved_ips=tuple(validated_ips),
    )


async def validate_proxy_endpoint(proxy_url: str) -> ValidatedTarget:
    parsed = urlparse(str(proxy_url or "").strip())
    scheme = str(parsed.scheme or "").lower()
    if scheme not in _ALLOWED_PROXY_SCHEMES:
        raise ValueError(
            "Only http://, https://, socks5://, and socks5h:// proxy endpoints are allowed"
        )
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Proxy URL must include a hostname")
    if hostname in _BLOCKED_HOSTNAMES or any(
        hostname.endswith(suffix) for suffix in _BLOCKED_SUFFIXES
    ):
        raise ValueError(f"Proxy host is not allowed: {hostname}")

    literal_ip = _parse_ip(hostname)
    if literal_ip is not None:
        _raise_if_non_public_ip(literal_ip, hostname)
        return ValidatedTarget(
            hostname=hostname,
            scheme=scheme,
            port=_target_port(parsed),
            resolved_ips=(hostname,),
            dns_resolved=False,
        )

    port = _target_port(parsed)
    resolved_ips = await _resolve_host_ips(hostname, port)
    validated_ips: list[str] = []
    for ip_text in resolved_ips:
        ip_value = _parse_ip(ip_text)
        if ip_value is None:
            continue
        _raise_if_non_public_ip(ip_value, hostname)
        validated_ips.append(ip_text)
    if not validated_ips:
        raise ValueError(
            f"Proxy host could not be resolved to a valid IP address: {hostname}"
        )
    return ValidatedTarget(
        hostname=hostname,
        scheme=scheme,
        port=port,
        resolved_ips=tuple(validated_ips),
    )


async def _resolve_host_ips(hostname: str, port: int) -> list[str]:
    attempts = max(1, int(DNS_RESOLUTION_RETRIES) + 1)
    for attempt in range(1, attempts + 1):
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                port,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            )
            break
        except socket.gaierror as exc:
            if attempt < attempts:
                await asyncio.sleep(max(0, DNS_RESOLUTION_RETRY_DELAY_MS) / 1000)
                continue
            fallback = await _resolve_host_ips_via_nslookup(hostname)
            if fallback:
                return fallback
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


async def _resolve_host_ips_via_nslookup(hostname: str) -> list[str]:
    if hostname and hostname[0] == "-":
        raise ValueError(f"Target host is not allowed: {hostname}")
    resolved: list[str] = []
    seen: set[str] = set()
    for record_type in ("A", "AAAA"):
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                "nslookup",
                f"-type={record_type}",
                hostname,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        except asyncio.TimeoutError:
            if process is not None:
                process.kill()
                await process.wait()
            continue
        except OSError:
            continue
        output = "\n".join(
            part
            for part in (
                stdout.decode(errors="ignore") if stdout else "",
                stderr.decode(errors="ignore") if stderr else "",
            )
            if part
        )
        for ip_text in _parse_nslookup_addresses(output):
            if ip_text in seen:
                continue
            seen.add(ip_text)
            resolved.append(ip_text)
    return resolved


def _parse_nslookup_addresses(output: str) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    capture = False
    for raw_line in str(output or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        if lowered.startswith(("name:", "aliases:", "canonical name", "non-authoritative answer")):
            capture = True
        if not capture:
            continue
        for token in re.split(r"[\s,;]+", stripped):
            ip_value = _parse_ip(token.strip("[]"))
            if ip_value is None:
                continue
            normalized = ip_value.compressed
            if normalized in seen:
                continue
            seen.add(normalized)
            resolved.append(normalized)
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
    if (
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_reserved
        or (isinstance(ip_value, ipaddress.IPv4Address) and ip_value in _CGNAT_NETWORK)
    ):
        raise ValueError(f"Target host resolves to a non-public IP address: {host_label} -> {ip_value}")
    if ip_value.is_global:
        return
    raise ValueError(f"Target host resolves to a non-public IP address: {host_label} -> {ip_value}")


def _target_port(parsed) -> int:
    return int(parsed.port or _default_port(parsed.scheme))


def _default_port(scheme: str) -> int:
    normalized = str(scheme or "").lower()
    if normalized in {"socks5", "socks5h"}:
        return 1080
    return 443 if normalized == "https" else 80
