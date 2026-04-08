# Strategy pattern for URL acquisition to break down the monolithic _process_single_url function.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRun


@dataclass
class AcquisitionContext:
    """Context object passed to acquisition strategies."""

    session: AsyncSession
    run: CrawlRun
    url: str
    url_index: int
    total_urls: int
    requested_fields: list[str]
    surface: str
    settings: dict[str, Any]
    profile: dict[str, Any]


@dataclass
class AcquisitionStrategyResult:
    """Result from an acquisition strategy execution."""

    success: bool
    records: list[dict]
    verdict: str
    method: str
    content_type: str | None = None
    diagnostics: dict[str, Any] | None = None
    error: str | None = None
    url_metrics: dict[str, Any] | None = None


class AcquisitionStrategy(ABC):
    """Base class for URL acquisition strategies."""

    @abstractmethod
    async def can_handle(self, context: AcquisitionContext) -> bool:
        """Determine if this strategy can handle the given URL/context."""
        pass

    @abstractmethod
    async def acquire(self, context: AcquisitionContext) -> AcquisitionStrategyResult:
        """Execute the acquisition strategy."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for logging."""
        pass


class JsonApiStrategy(AcquisitionStrategy):
    """Strategy for acquiring data from JSON API endpoints."""

    @property
    def name(self) -> str:
        return "json_api"

    async def can_handle(self, context: AcquisitionContext) -> bool:
        """JSON APIs are detected by URL patterns or explicit configuration."""
        url_lower = context.url.lower()
        # Check if URL suggests JSON API
        if any(pattern in url_lower for pattern in ["/api/", ".json", "/v1/", "/v2/"]):
            return True
        # Check if settings explicitly request JSON
        if context.settings.get("force_json"):
            return True
        return False

    async def acquire(self, context: AcquisitionContext) -> AcquisitionStrategyResult:
        """Acquire data from JSON API endpoint."""
        # Import here to avoid circular dependencies
        from app.services.acquisition.acquirer import acquire
        from app.services.extract.json_extractor import (
            extract_json_listing,
            extract_json_detail,
        )

        # Acquire the JSON response
        acq_result = await acquire(
            url=context.url,
            profile=context.profile,
            surface=context.surface,
        )

        if not acq_result.success:
            return AcquisitionStrategyResult(
                success=False,
                records=[],
                verdict="error",
                method=acq_result.method,
                content_type=acq_result.content_type,
                error=acq_result.error,
                diagnostics=acq_result.diagnostics,
            )

        # Extract records from JSON
        if context.surface in {"ecommerce", "jobs", "real_estate"}:
            records = extract_json_listing(
                acq_result.json_data,
                surface=context.surface,
                requested_fields=context.requested_fields,
            )
        else:
            detail = extract_json_detail(
                acq_result.json_data,
                requested_fields=context.requested_fields,
            )
            records = [detail] if detail else []

        verdict = "success" if records else "empty"
        return AcquisitionStrategyResult(
            success=True,
            records=records,
            verdict=verdict,
            method=acq_result.method,
            content_type=acq_result.content_type,
            diagnostics=acq_result.diagnostics,
        )


class HtmlScrapingStrategy(AcquisitionStrategy):
    """Strategy for acquiring data from HTML pages via HTTP."""

    @property
    def name(self) -> str:
        return "html_scraping"

    async def can_handle(self, context: AcquisitionContext) -> bool:
        """HTML scraping is the default fallback strategy."""
        return True

    async def acquire(self, context: AcquisitionContext) -> AcquisitionStrategyResult:
        """Acquire data from HTML page."""
        # Import here to avoid circular dependencies
        from app.services.acquisition.acquirer import acquire
        from app.services.acquisition.blocked_detector import detect_blocked_page
        from app.services.extract.listing_extractor import extract_listing_records

        # Acquire the HTML response
        acq_result = await acquire(
            url=context.url,
            profile=context.profile,
            surface=context.surface,
        )

        if not acq_result.success:
            return AcquisitionStrategyResult(
                success=False,
                records=[],
                verdict="error",
                method=acq_result.method,
                content_type=acq_result.content_type,
                error=acq_result.error,
                diagnostics=acq_result.diagnostics,
            )

        # Check if page is blocked
        if detect_blocked_page(acq_result.html, context.url):
            return AcquisitionStrategyResult(
                success=False,
                records=[],
                verdict="blocked",
                method=acq_result.method,
                content_type=acq_result.content_type,
                diagnostics=acq_result.diagnostics,
            )

        # Extract records from HTML
        records = extract_listing_records(
            html=acq_result.html,
            page_url=context.url,
            surface=context.surface,
            requested_fields=context.requested_fields,
        )

        verdict = "success" if records else "empty"

        return AcquisitionStrategyResult(
            success=True,
            records=records,
            verdict=verdict,
            method=acq_result.method,
            content_type=acq_result.content_type,
            diagnostics=acq_result.diagnostics,
        )


class BrowserRenderingStrategy(AcquisitionStrategy):
    """Strategy for acquiring data using Playwright browser rendering (fallback for blocked/JS-heavy pages)."""

    @property
    def name(self) -> str:
        return "browser_rendering"

    async def can_handle(self, context: AcquisitionContext) -> bool:
        """Browser rendering is used as a fallback when HTTP fails."""
        # This strategy is invoked explicitly, not via can_handle
        return False

    async def acquire(self, context: AcquisitionContext) -> AcquisitionStrategyResult:
        """Acquire data using Playwright browser."""
        # Import here to avoid circular dependencies
        from app.services.acquisition.browser_client import acquire_with_browser
        from app.services.extract.listing_extractor import extract_listing_records

        # Acquire using browser
        acq_result = await acquire_with_browser(
            url=context.url,
            surface=context.surface,
            settings=context.settings,
        )

        if not acq_result.success:
            return AcquisitionStrategyResult(
                success=False,
                records=[],
                verdict="error",
                method="browser",
                error=acq_result.error,
                diagnostics=acq_result.diagnostics,
            )

        # Extract records from rendered HTML
        records = extract_listing_records(
            html=acq_result.html,
            page_url=context.url,
            surface=context.surface,
            requested_fields=context.requested_fields,
        )

        verdict = "success" if records else "empty"

        return AcquisitionStrategyResult(
            success=True,
            records=records,
            verdict=verdict,
            method="browser",
            diagnostics=acq_result.diagnostics,
        )


# Strategy selector


async def select_acquisition_strategy(
    context: AcquisitionContext,
) -> AcquisitionStrategy:
    """Select the appropriate acquisition strategy based on context."""
    strategies = [
        JsonApiStrategy(),
        HtmlScrapingStrategy(),  # Default fallback
    ]

    for strategy in strategies:
        if await strategy.can_handle(context):
            return strategy

    # Should never reach here since HtmlScrapingStrategy always returns True
    return HtmlScrapingStrategy()
