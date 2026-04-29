# Base adapter interface for platform-specific extraction.
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.services.acquisition import HttpFetchResult, request_result, wait_for_host_slot
from app.services.platform_policy import detect_platform_family

from .types import AdapterRecords

logger = logging.getLogger(__name__)


def selectolax_node_text(node: object, *, separator: str = "") -> str:
    if node is None:
        return ""
    text_fn = getattr(node, "text", None)
    if not callable(text_fn):
        return ""
    try:
        if separator:
            return str(text_fn(separator=separator, strip=True) or "")
        return str(text_fn(strip=True) or "")
    except Exception:
        return ""


def selectolax_node_attr(node: object, name: str) -> str | None:
    if node is None:
        return None
    raw_attrs = getattr(node, "attributes", {}) or {}
    attrs = raw_attrs if isinstance(raw_attrs, Mapping) else {}
    value = attrs.get(name)
    if value is None:
        return None
    return str(value).strip() or None


def adapter_host_matches(host: str, expected: str) -> bool:
    normalized_host = str(host or "").strip().lower()
    normalized_expected = str(expected or "").strip().lower()
    return normalized_host == normalized_expected or normalized_host.endswith(
        f".{normalized_expected}"
    )


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

    def normalize_acquisition_url(self, url: str | None) -> str | None:
        return url

    def _result(
        self,
        records: AdapterRecords,
        *,
        source_type: str | None = None,
    ) -> AdapterResult:
        return AdapterResult(
            records=records,
            source_type=source_type or f"{self.name}_adapter",
            adapter_name=self.name,
        )

    def _is_detail_surface(self, surface: str | None) -> bool:
        return "detail" in str(surface or "").strip().lower()

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
        return (
            response.json_data if isinstance(response.json_data, (dict, list)) else None
        )

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
