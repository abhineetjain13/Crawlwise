# Base adapter interface for platform-specific extraction.
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.services.acquisition import HttpFetchResult, request_result, wait_for_host_slot
from app.services.platform_policy import detect_platform_family

from .types import AdapterRecords

logger = logging.getLogger(__name__)


@dataclass
class AdapterResult:
    """Structured data returned by a platform adapter."""

    records: AdapterRecords = field(default_factory=list)
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
    platform_family: str | None = None

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

    def _matches_platform_family(self, url: str, html: str) -> bool:
        expected_family = str(self.platform_family or "").strip().lower()
        if not expected_family:
            return False
        detected_family = str(detect_platform_family(url, html) or "").strip().lower()
        return detected_family == expected_family

    async def _request_result(
        self,
        url: str,
        *,
        expect_json: bool = False,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        data: Any | None = None,
        proxy: str | None = None,
        timeout_seconds: float | None = None,
    ) -> HttpFetchResult:
        if urlparse(str(url or "")).netloc:
            await wait_for_host_slot(url)
        return await request_result(
            url,
            proxy=proxy,
            expect_json=expect_json,
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
            expect_json=True,
        )
        if response.status_code != 200:
            return None
        return response.json_data if isinstance(response.json_data, (dict, list)) else None

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
        if urlparse(str(url or "")).netloc:
            await wait_for_host_slot(url)
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
            logger.debug(
                "Failed to decode adapter JSON response for %s via curl request helper",
                url,
                exc_info=True,
            )
            return None
