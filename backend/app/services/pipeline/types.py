"""Typed data objects for pipeline boundaries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Acquisition outcome classification
# ---------------------------------------------------------------------------


class AcquisitionOutcome(StrEnum):
    """Typed classification of how acquisition resolved a URL.

    Replaces inferring the outcome from scattered diagnostic booleans
    (``method``, ``curl_needs_browser``, ``browser_attempted``,
    ``promoted_source_used``, etc.).
    """

    direct_html = "direct_html"
    """curl_cffi returned usable HTML directly."""

    browser_rendered = "browser_rendered"
    """Playwright rendered the page (escalated from curl or browser-first)."""

    promoted_source = "promoted_source"
    """Promoted iframe/embed source fetched via curl."""

    promoted_source_browser = "promoted_source_browser"
    """Promoted source fetched via curl returned a shell; browser rendered it."""

    json_response = "json_response"
    """Target returned a JSON API response (no HTML extraction needed)."""

    blocked = "blocked"
    """Anti-bot / challenge page detected."""

    js_shell = "js_shell"
    """JS shell detected but browser escalation not attempted or failed."""

    empty = "empty"
    """No content returned from any acquisition method."""

    error = "error"
    """Acquisition raised an unrecoverable exception."""

if TYPE_CHECKING:
    from bs4 import BeautifulSoup
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.crawl import CrawlRun
    from app.services.acquisition import AcquisitionRequest, AcquisitionResult
    from app.services.publish.record_persistence import ExtractionRecordWriter


# ---------------------------------------------------------------------------
# Existing pipeline boundary types (preserved verbatim)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class URLProcessingResult:
    """Typed result from processing a single URL through the pipeline.

    Replaces the raw ``(list[dict], str, dict)`` tuple that previously leaked
    internal structure across the orchestration boundary.

    Supports tuple destructuring (``records, verdict, metrics = result``) for
    backward compatibility with tests and existing call sites.
    """

    records: list[dict] = field(default_factory=list)
    verdict: str = ""
    url_metrics: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator:
        return iter((self.records, self.verdict, self.url_metrics))

    def __len__(self) -> int:
        return 3


@dataclass(slots=True)
class URLProcessingConfig:
    """Typed configuration for a single URL processing invocation.

    Groups the settings that were previously passed as 8+ positional
    parameters to ``_process_single_url``.
    """

    proxy_list: list[str] = field(default_factory=list)
    traversal_mode: str | None = None
    max_pages: int = 5
    max_scrolls: int = 3
    max_records: int = 100
    sleep_ms: int = 0
    update_run_state: bool = True
    persist_logs: bool = True
    prefetch_only: bool = False
    record_writer: "ExtractionRecordWriter | None" = None


# ---------------------------------------------------------------------------
# Pipeline stage protocol & context (Phase 2 — Pipeline Decomposition)
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    """Mutable state carried through the pipeline stage chain.

    Each stage reads from and writes to this context rather than accepting
    or returning ad-hoc dicts / tuples.
    """

    # -- Immutable inputs (set once at pipeline start) --
    session: "AsyncSession"
    run: "CrawlRun"
    url: str
    config: URLProcessingConfig
    acquisition_request: "AcquisitionRequest"
    additional_fields: list[str] = field(default_factory=list)
    extraction_contract: list[dict] = field(default_factory=list)
    is_listing: bool = False
    surface: str = ""

    # -- Pipeline control --
    update_run_state: bool = True
    persist_logs: bool = True
    checkpoint: Callable[[], Awaitable[None]] | None = None
    record_writer: "ExtractionRecordWriter | None" = None

    # -- Mutable state populated by stages --
    acquisition_result: "AcquisitionResult | None" = None
    acquisition_ms: int = 0
    soup: "BeautifulSoup | None" = None
    page_sources: dict[str, Any] = field(default_factory=dict)
    adapter_result: Any = None
    adapter_records: list[dict] = field(default_factory=list)
    url_metrics: dict[str, Any] = field(default_factory=dict)

    # -- Extraction output --
    records: list[dict] = field(default_factory=list)
    verdict: str = ""

    def to_result(self) -> URLProcessingResult:
        """Convert the final context state into a ``URLProcessingResult``."""
        return URLProcessingResult(
            records=self.records,
            verdict=self.verdict,
            url_metrics=self.url_metrics,
        )


@runtime_checkable
class PipelineStage(Protocol):
    """Protocol for a single pipeline processing stage.

    Each stage receives the full ``PipelineContext`` and can read / mutate it.
    Stages are executed in order by ``PipelineRunner``.
    """

    async def execute(self, ctx: PipelineContext) -> None:
        """Run this stage, reading from and writing to *ctx*."""
        ...


# ---------------------------------------------------------------------------
# Extraction result boundary types (Phase 3 — Typed Contracts)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExtractionResult:
    """Typed output from an extraction pass (listing or detail).

    Replaces raw ``list[dict]`` returns from extraction functions.
    Supports tuple destructuring for backward compatibility.
    """

    records: list[dict] = field(default_factory=list)
    verdict: str = ""
    winning_sources: dict[str, str] = field(default_factory=dict)
    field_coverage: dict[str, Any] = field(default_factory=dict)

    def __iter__(self) -> Iterator:
        return iter((self.records, self.verdict))

    def __len__(self) -> int:
        return 2

    def __bool__(self) -> bool:
        return bool(self.records)


@dataclass(slots=True)
class AcquisitionMetrics:
    """Typed acquisition-phase metrics — replaces raw ``url_metrics`` dict
    for the acquisition portion of pipeline telemetry.
    """

    acquisition_ms: int = 0
    method: str = ""
    browser_attempted: bool = False
    browser_used: bool = False
    challenge_state: str = "none"
    traversal_attempted: bool = False
    traversal_mode_used: str | None = None
    traversal_pages_collected: int = 0
    traversal_stop_reason: str | None = None
    content_type: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for backward-compatible merging."""
        return {k: v for k, v in self.__dict__.items() if v not in (None, False, 0, "")}
