# Base adapter interface for platform-specific extraction.
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.services.acquisition import HttpFetchResult, request_result, wait_for_host_slot
from app.services.config.crawl_runtime import ACQUIRE_HOST_MIN_INTERVAL_MS


@dataclass
class AdapterResult:
    """Structured data returned by a platform adapter."""

    records: list[dict] = field(default_factory=list)
    source_type: str = "adapter"
    adapter_name: str = ""


class BaseAdapter(ABC):
    """All platform adapters implement this interface.

    Adapters are called during the ANALYZE stage and return structured
    records extracted from platform-specific API endpoints or embedded
    data structures.  They are separate from the generic DOM/selector
    extraction pipeline.
    """

    name: str = "base"

    # Domains this adapter handles.  Checked by the registry.
    domains: list[str] = []

    @abstractmethod
    async def can_handle(self, url: str, html: str) -> bool:
        """Return True if this adapter should run for the given URL/HTML."""
        ...

    @abstractmethod
    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        """Extract structured records from the page.

        ``surface`` is the user-declared surface type so the adapter can
        tailor its output (e.g. listing vs detail fields).
        """
        ...

    async def _request_result(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        data: Any | None = None,
        proxy: str | None = None,
        timeout_seconds: float | None = None,
    ) -> HttpFetchResult:
        hostname = str(urlparse(str(url or "")).hostname or "").strip().lower()
        if hostname:
            await wait_for_host_slot(hostname, ACQUIRE_HOST_MIN_INTERVAL_MS)
        return await request_result(
            url,
            proxy=proxy,
            method=method,
            headers=headers,
            json_body=json_body,
            data=data,
            timeout_seconds=timeout_seconds,
        )

    async def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        data: Any | None = None,
        proxy: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict | list | None:
        response = await self._request_result(
            url,
            method=method,
            headers=headers,
            json_body=json_body,
            data=data,
            proxy=proxy,
            timeout_seconds=timeout_seconds,
        )
        if response.status_code != 200:
            return None
        return response.json_data

    async def _request_text(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        data: Any | None = None,
        proxy: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        response = await self._request_result(
            url,
            method=method,
            headers=headers,
            json_body=json_body,
            data=data,
            proxy=proxy,
            timeout_seconds=timeout_seconds,
        )
        if response.status_code != 200:
            return ""
        return str(response.text or "")

    async def _request_json_with_curl(
        self,
        request_callable,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        data: Any | None = None,
        proxy: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict | list | None:
        hostname = str(urlparse(str(url or "")).hostname or "").strip().lower()
        if hostname:
            await wait_for_host_slot(hostname, ACQUIRE_HOST_MIN_INTERVAL_MS)
        kwargs: dict[str, Any] = {}
        if headers:
            kwargs["headers"] = headers
        if json_body is not None:
            kwargs["json"] = json_body
        if data is not None:
            kwargs["data"] = data
        if proxy:
            kwargs["proxy"] = proxy
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        response = await asyncio.to_thread(request_callable, url, **kwargs)
        if int(getattr(response, "status_code", 0) or 0) != 200:
            return None
        parser = getattr(response, "json", None)
        if not callable(parser):
            return None
        try:
            return parser()
        except Exception:
            return None
