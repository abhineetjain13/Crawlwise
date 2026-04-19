from __future__ import annotations

import socket
from typing import Literal

import httpx

from app.services.config.runtime_settings import crawler_runtime_settings

AddressFamilyPreference = Literal["auto", "ipv4", "ipv6"]

_IPV4_LOCAL_ADDRESS = "0.0.0.0"
_IPV6_LOCAL_ADDRESS = "::"


def address_family_preference() -> AddressFamilyPreference:
    value = str(
        getattr(
            crawler_runtime_settings,
            "network_address_family_preference",
            "auto",
        )
        or "auto"
    ).strip().lower()
    if value in {"ipv4", "ipv6"}:
        return value
    return "auto"


def dns_resolution_families() -> tuple[int, ...]:
    preference = address_family_preference()
    if preference == "ipv4":
        return (socket.AF_INET,)
    if preference == "ipv6":
        return (socket.AF_INET6,)
    return (socket.AF_UNSPEC, socket.AF_INET)


def build_async_http_client(
    *,
    follow_redirects: bool,
    timeout: float | httpx.Timeout,
    proxy: str | None = None,
    limits: httpx.Limits | None = None,
    force_ipv4: bool = False,
) -> httpx.AsyncClient:
    transport = _build_async_http_transport(
        proxy=proxy,
        limits=limits,
        force_ipv4=force_ipv4,
    )
    client_kwargs: dict[str, object] = {
        "follow_redirects": follow_redirects,
        "timeout": timeout,
    }
    if transport is not None:
        client_kwargs["transport"] = transport
    elif proxy is not None:
        client_kwargs["proxy"] = proxy
    return httpx.AsyncClient(**client_kwargs)


def should_retry_with_forced_ipv4(exc: BaseException) -> bool:
    if address_family_preference() != "auto":
        return False
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError)):
        return True
    if isinstance(exc, OSError):
        return True
    lowered = str(exc or "").lower()
    return any(
        marker in lowered
        for marker in (
            "getaddrinfo failed",
            "name or service not known",
            "nodename nor servname provided",
            "temporary failure in name resolution",
            "network is unreachable",
            "no route to host",
        )
    )


def _build_async_http_transport(
    *,
    proxy: str | None,
    limits: httpx.Limits | None,
    force_ipv4: bool,
) -> httpx.AsyncHTTPTransport | None:
    local_address = _local_address_for_http(force_ipv4=force_ipv4)
    if local_address is None and proxy is None and limits is None:
        return None
    return httpx.AsyncHTTPTransport(
        proxy=proxy,
        limits=limits or httpx.Limits(),
        local_address=local_address,
    )


def _local_address_for_http(*, force_ipv4: bool) -> str | None:
    if force_ipv4:
        return _IPV4_LOCAL_ADDRESS
    preference = address_family_preference()
    if preference == "ipv4":
        return _IPV4_LOCAL_ADDRESS
    if preference == "ipv6":
        return _IPV6_LOCAL_ADDRESS
    return None
