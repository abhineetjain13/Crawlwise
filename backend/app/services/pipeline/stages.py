"""Concrete pipeline stage implementations.

Each stage is a lightweight class with a single ``async execute(ctx)`` method
that reads from and writes to the shared :class:`PipelineContext`.

Stages are composed by :class:`PipelineRunner` (see ``runner.py``) and
replace the monolithic inline logic that previously lived in
``_process_single_url``.
"""

from __future__ import annotations

import logging
import re
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

from app.services.publish import (
    build_url_metrics as _build_url_metrics,
)
from app.services.publish.verdict import VERDICT_LISTING_FAILED
from bs4 import BeautifulSoup
from sqlalchemy import delete

from .pipeline_config import PIPELINE_CONFIG
from .runtime_helpers import STAGE_ANALYZE, STAGE_FETCH, log_event, set_stage
from .types import PipelineContext
from .utils import _elapsed_ms, parse_html
from app.services.discover import parse_page_sources_async
if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _canonical_listing_path(value: str) -> str:
    path = urlparse(str(value or "").strip()).path.lower().rstrip("/")
    return re.sub(r"\.(?:html?|php|aspx?)$", "", path)


def _url_path_tokens(value: str) -> set[str]:
    path = urlparse(str(value or "").strip()).path.lower()
    return {
        token
        for token in re.split(r"[^a-z0-9]+", path)
        if len(token) >= 3 and token not in PIPELINE_CONFIG.listing_path_token_stopwords
    }


def _looks_like_detail_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    if any(
        marker in lowered
        for marker in ("/p/", "/p.", "/product/", "/products/", "/dp/", "/item/", "/buy")
    ):
        return True
    segments = [segment for segment in urlparse(lowered).path.split("/") if segment]
    return any(segment.startswith("p.") for segment in segments)


def _discover_child_listing_candidate(html: str, *, page_url: str) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    return _discover_child_listing_candidate_from_soup(soup, page_url=page_url)


def _discover_child_listing_candidate_from_soup(
    soup: BeautifulSoup,
    *,
    page_url: str,
) -> str | None:
    page = urlparse(page_url)
    page_host = str(page.netloc or "").strip().lower()
    if not page_host:
        return None
    page_tokens = _url_path_tokens(page_url)
    page_path = page.path.rstrip("/")
    page_path_canonical = _canonical_listing_path(page_url)
    candidates: dict[str, int] = {}
    for anchor in soup.select("a[href]"):
        raw_href = str(anchor.get("href") or "").strip()
        if not raw_href or raw_href.startswith("#"):
            continue
        href = urljoin(page_url, raw_href)
        parsed = urlparse(href)
        host = str(parsed.netloc or "").strip().lower()
        if host != page_host:
            continue
        normalized_href = parsed._replace(fragment="", query="").geturl().rstrip("/")
        candidate_path_canonical = _canonical_listing_path(normalized_href)
        if (
            not normalized_href
            or normalized_href == page_url.rstrip("/")
            or candidate_path_canonical == page_path_canonical
        ):
            continue
        if _looks_like_detail_url(normalized_href):
            continue
        candidate_tokens = _url_path_tokens(normalized_href)
        if not candidate_tokens:
            continue
        shared = len(candidate_tokens & page_tokens)
        if shared <= 0:
            continue
        text = " ".join(anchor.get_text(" ", strip=True).split()).lower()
        if text and any(token in text for token in PIPELINE_CONFIG.listing_promotion_text_noise):
            continue
        score = shared * 5
        if parsed.path.rstrip("/").startswith(page_path):
            score += 2
        if len(candidate_tokens) > len(page_tokens):
            score += 1
        if any(hint in text for hint in PIPELINE_CONFIG.listing_promotion_text_hints):
            score += 3
        if any(
            token in candidate_tokens
            for token in PIPELINE_CONFIG.listing_promotion_penalty_tokens
        ):
            score -= 2
        if score >= 5:
            candidates[normalized_href] = max(score, candidates.get(normalized_href, 0))
    if not candidates:
        return None
    ranked = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] <= ranked[1][1]:
        return None
    return ranked[0][0]


def _looks_like_category_tile_listing(records: list[dict]) -> bool:
    if len(records) < 2:
        return False
    tile_hints = 0
    for record in records:
        public_fields = {
            key: value
            for key, value in dict(record or {}).items()
            if not str(key).startswith("_") and value not in (None, "", [], {})
        }
        if not public_fields or not public_fields.get("url"):
            return False
        if set(public_fields) & PIPELINE_CONFIG.listing_tile_strong_fields:
            return False
        if any(field not in PIPELINE_CONFIG.listing_tile_allowed_fields for field in public_fields):
            return False
        url_value = str(public_fields.get("url") or "").strip()
        if not url_value or _looks_like_detail_url(url_value):
            return False
        title_value = str(public_fields.get("title") or "").strip().lower()
        image_value = str(public_fields.get("image_url") or "").strip().lower()
        if (
            image_value.startswith("data:image/")
            or "icon" in title_value
            or url_value.rstrip("/").endswith("/see-all")
            or "/all-" in url_value
        ):
            tile_hints += 1
    return tile_hints >= max(1, len(records) // 2)


async def _discard_listing_records_for_sources(
    ctx: PipelineContext,
    *,
    source_urls: set[str],
) -> None:
    from app.models.crawl import CrawlRecord

    normalized_source_urls = {str(source_url or "").strip() for source_url in source_urls}
    normalized_source_urls = {source_url for source_url in normalized_source_urls if source_url}
    if not normalized_source_urls:
        return

    await ctx.session.execute(
        delete(CrawlRecord).where(
            CrawlRecord.run_id == ctx.run.id,
            CrawlRecord.source_url.in_(sorted(normalized_source_urls)),
        )
    )
    record_writer = ctx.record_writer
    if record_writer is not None and hasattr(record_writer, "records"):
        record_writer.records[:] = [
            record
            for record in record_writer.records
            if not (
                getattr(record, "run_id", None) == ctx.run.id
                and getattr(record, "source_url", None) in normalized_source_urls
            )
        ]
    await ctx.session.flush()


# ---------------------------------------------------------------------------
# Stage 1: Acquisition
# ---------------------------------------------------------------------------


class AcquireStage:
    """Fetch the target URL via the acquisition waterfall (curl → Playwright)."""

    async def execute(self, ctx: PipelineContext) -> None:
        from . import core as pipeline_core

        if ctx.update_run_state:
            await set_stage(ctx.session, ctx.run, STAGE_FETCH)
        if ctx.persist_logs:
            await log_event(ctx.session, ctx.run.id, "info", f"[FETCH] Fetching {ctx.url}")

        if ctx.acquisition_result is None:
            started_at = time.perf_counter()
            ctx.acquisition_result = await pipeline_core.acquire(
                request=ctx.acquisition_request
            )
            ctx.acquisition_ms = _elapsed_ms(started_at)
        ctx.url_metrics = _build_url_metrics(
            ctx.acquisition_result, requested_fields=ctx.additional_fields
        )
        ctx.url_metrics["acquisition_ms"] = ctx.acquisition_ms

        # Log traversal progress
        if ctx.persist_logs and ctx.url_metrics.get("traversal_attempted"):
            _t_mode = (
                ctx.url_metrics.get("traversal_mode_used")
                or ctx.config.traversal_mode
                or "?"
            )
            _t_pages = ctx.url_metrics.get("traversal_pages_collected", 0)
            _t_stop = ctx.url_metrics.get("traversal_stop_reason") or "unknown"
            _t_fallback = ctx.url_metrics.get("traversal_fallback_used", False)
            _t_ms = ctx.url_metrics.get("browser_traversal_ms", 0)
            _t_msg = (
                f"[TRAVERSAL] mode={_t_mode}, pages_collected={_t_pages}, "
                f"stop_reason={_t_stop}, time={_t_ms}ms"
            )
            if _t_fallback:
                _t_msg += " (fallback to single-page)"
            await log_event(ctx.session, ctx.run.id, "info", _t_msg)


# ---------------------------------------------------------------------------
# Stage 2a: HTML Parse (single parse, shared soup)
# ---------------------------------------------------------------------------


class ParseStage:
    """Parse HTML into BeautifulSoup once, offloaded to thread pool."""

    async def execute(self, ctx: PipelineContext) -> None:
        acq = ctx.acquisition_result
        assert acq is not None
        html = acq.html
        if html and acq.content_type != "json":
            ctx.soup = await parse_html(html)
            ctx.page_sources = await parse_page_sources_async(html, soup=ctx.soup)


# ---------------------------------------------------------------------------
# Stage 2b: Adapter Execution
# ---------------------------------------------------------------------------


class AdapterStage:
    """Run domain-matched platform adapters against the acquired HTML."""

    async def execute(self, ctx: PipelineContext) -> None:
        from . import core as pipeline_core

        acq = ctx.acquisition_result
        assert acq is not None
        if acq.content_type == "json":
            return
        if ctx.adapter_result is not None or ctx.adapter_records:
            return
        if acq.adapter_records:
            ctx.adapter_records = list(acq.adapter_records)
            ctx.adapter_result = SimpleNamespace(
                records=ctx.adapter_records,
                adapter_name=acq.adapter_name,
                source_type=acq.adapter_source_type,
            )
            return
        html = acq.html
        ctx.adapter_result = await pipeline_core.run_adapter(ctx.url, html, ctx.surface)
        ctx.adapter_records = ctx.adapter_result.records if ctx.adapter_result else []

        if ctx.update_run_state:
            await set_stage(ctx.session, ctx.run, STAGE_ANALYZE)
        if ctx.persist_logs:
            await log_event(
                ctx.session, ctx.run.id, "info", "[ANALYZE] Extracting candidates"
            )


# ---------------------------------------------------------------------------
# Stage 3: Extraction (delegates to existing _extract_listing / _extract_detail)
# ---------------------------------------------------------------------------


class ExtractStage:
    """Delegates to the appropriate extraction path based on surface/content type."""

    async def execute(self, ctx: PipelineContext) -> None:
        from .detail_flow import (
            extract_detail_from_context,
            process_json_response_from_context,
        )
        from .listing_flow import extract_listing, extract_listing_from_context

        acq = ctx.acquisition_result
        assert acq is not None

        # JSON path
        if acq.content_type == "json" and acq.json_data is not None:
            if ctx.persist_logs:
                await log_event(
                    ctx.session,
                    ctx.run.id,
                    "info",
                    "[ANALYZE] JSON-first path — API response detected",
                )
            extraction_started = time.perf_counter()
            result = await process_json_response_from_context(ctx)
            result.url_metrics["extraction_ms"] = _elapsed_ms(extraction_started)
            ctx.records = result.records
            ctx.verdict = result.verdict
            ctx.url_metrics = result.url_metrics
            return

        html = acq.html
        if ctx.update_run_state:
            await set_stage(ctx.session, ctx.run, STAGE_ANALYZE)
        if ctx.persist_logs:
            await log_event(
                ctx.session,
                ctx.run.id,
                "info",
                f"[ANALYZE] Enumerating sources (method={acq.method})",
            )

        if ctx.is_listing:
            extraction_started = time.perf_counter()
            result = await extract_listing_from_context(ctx)
            result.url_metrics["extraction_ms"] = _elapsed_ms(extraction_started)
            ctx.records = result.records
            ctx.verdict = result.verdict
            ctx.url_metrics = result.url_metrics
        else:
            extraction_started = time.perf_counter()
            result = await extract_detail_from_context(ctx)
            result.url_metrics["extraction_ms"] = _elapsed_ms(extraction_started)
            ctx.records = result.records
            ctx.verdict = result.verdict
            ctx.url_metrics = result.url_metrics


# ---------------------------------------------------------------------------
# Stage 3.5: Listing Browser Retry
# ---------------------------------------------------------------------------


class ListingBrowserRetryStage:
    """If listing extraction failed on curl, retry with browser rendering."""

    async def execute(self, ctx: PipelineContext) -> None:
        from app.services.acquisition import AcquisitionRequest

        from . import core as pipeline_core
        from .listing_flow import extract_listing

        acq = ctx.acquisition_result
        assert acq is not None

        if not ctx.is_listing:
            return
        if acq.method != "curl_cffi":
            return
        child_listing_url = (
            _discover_child_listing_candidate_from_soup(ctx.soup, page_url=ctx.url)
            if ctx.soup is not None
            else _discover_child_listing_candidate(acq.html or "", page_url=ctx.url)
        )
        category_tile_listing = _looks_like_category_tile_listing(ctx.records)
        promote_child_listing = bool(child_listing_url) and (
            ctx.verdict == VERDICT_LISTING_FAILED
            or category_tile_listing
        )
        if promote_child_listing:
            promotion_reason = (
                "Listing extraction returned category-tile records; promoting to a deeper same-host child listing"
                if ctx.records
                else "Listing shell matched a deeper same-host category candidate"
            )
            if ctx.persist_logs:
                await log_event(
                    ctx.session,
                    ctx.run.id,
                    "info",
                    f"[ANALYZE] {promotion_reason}; retrying on {child_listing_url}",
                )
            assert child_listing_url is not None
            child_request = AcquisitionRequest(
                run_id=ctx.acquisition_request.run_id,
                url=child_listing_url,
                proxy_list=list(ctx.acquisition_request.proxy_list),
                surface=ctx.acquisition_request.surface,
                traversal_mode=ctx.acquisition_request.traversal_mode,
                max_pages=ctx.acquisition_request.max_pages,
                max_scrolls=ctx.acquisition_request.max_scrolls,
                sleep_ms=ctx.acquisition_request.sleep_ms,
                requested_fields=list(ctx.acquisition_request.requested_fields),
                requested_field_selectors=dict(ctx.acquisition_request.requested_field_selectors),
                acquisition_profile=dict(ctx.acquisition_request.acquisition_profile),
                checkpoint=ctx.acquisition_request.checkpoint,
            )
            promoted_started = time.perf_counter()
            promoted_acq = await pipeline_core.acquire(request=child_request)
            promoted_retry_ms = _elapsed_ms(promoted_started)
            promoted_metrics = _build_url_metrics(
                promoted_acq,
                requested_fields=ctx.additional_fields,
            )
            promoted_metrics["acquisition_ms"] = promoted_retry_ms
            promoted_metrics["listing_child_promotion"] = True
            promoted_metrics["listing_child_promotion_url"] = child_listing_url
            promoted_metrics["listing_child_parent_url"] = ctx.url
            promoted_adapter_result = await pipeline_core.run_adapter(
                child_listing_url,
                promoted_acq.html,
                ctx.surface,
            )
            promoted_adapter_records = (
                promoted_adapter_result.records if promoted_adapter_result else []
            )
            promoted_result = await extract_listing(
                ctx.session,
                ctx.run,
                child_listing_url,
                promoted_acq.html,
                promoted_acq,
                promoted_adapter_result,
                promoted_adapter_records,
                ctx.additional_fields,
                ctx.surface,
                ctx.config.max_records,
                promoted_metrics,
                update_run_state=ctx.update_run_state,
                persist_logs=ctx.persist_logs,
                record_writer=ctx.record_writer,
            )
            promoted_result.url_metrics["listing_child_promotion"] = True
            promoted_result.url_metrics["listing_child_promotion_url"] = child_listing_url
            promoted_result.url_metrics["listing_child_parent_url"] = ctx.url
            if promoted_result.records:
                ctx.records = promoted_result.records
                ctx.verdict = promoted_result.verdict
                ctx.url_metrics = promoted_result.url_metrics
                return
            if category_tile_listing:
                if ctx.persist_logs:
                    await log_event(
                        ctx.session,
                        ctx.run.id,
                        "warning",
                        "[ANALYZE] Child listing promotion produced 0 records from category-tile results; forcing browser retry",
                    )
                source_urls = {
                    str(record.get("source_url") or record.get("url") or ctx.url).strip()
                    for record in ctx.records
                    if isinstance(record, dict)
                }
                source_urls.add(str(ctx.url or "").strip())
                await _discard_listing_records_for_sources(ctx, source_urls=source_urls)
                ctx.records = []
                ctx.verdict = VERDICT_LISTING_FAILED

        if ctx.verdict != VERDICT_LISTING_FAILED:
            return
        existing_metrics = dict(ctx.url_metrics or {})
        if bool(existing_metrics.get("browser_attempted")):
            if ctx.persist_logs:
                await log_event(
                    ctx.session,
                    ctx.run.id,
                    "warning",
                    "[ANALYZE] Listing extraction failed after curl and a prior browser attempt; skipping duplicate browser retry",
                )
            return

        if ctx.persist_logs:
            await log_event(
                ctx.session,
                ctx.run.id,
                "info",
                "[ANALYZE] Listing extraction was weak/empty on curl_cffi — retrying with browser rendering",
            )

        browser_retry_started = time.perf_counter()
        browser_acq = await pipeline_core.acquire(
            request=ctx.acquisition_request.with_profile_updates(prefer_browser=True),
        )
        browser_retry_ms = _elapsed_ms(browser_retry_started)
        browser_html = browser_acq.html
        original_metrics = dict(existing_metrics)
        ctx.acquisition_ms += browser_retry_ms
        retry_metrics = _build_url_metrics(
            browser_acq,
            requested_fields=ctx.additional_fields,
        )
        retry_metrics["acquisition_ms"] = browser_retry_ms
        merged_retry_metrics = dict(original_metrics)
        merged_retry_metrics["acquisition_ms"] = ctx.acquisition_ms
        merged_retry_metrics["original_url_metrics"] = original_metrics
        merged_retry_metrics["retry_url_metrics"] = retry_metrics
        browser_adapter_result = await pipeline_core.run_adapter(
            ctx.url,
            browser_html,
            ctx.surface,
        )
        browser_adapter_records = (
            browser_adapter_result.records if browser_adapter_result else []
        )

        extraction_started = time.perf_counter()
        result = await extract_listing(
            ctx.session,
            ctx.run,
            ctx.url,
            browser_html,
            browser_acq,
            browser_adapter_result,
            browser_adapter_records,
            ctx.additional_fields,
            ctx.surface,
            ctx.config.max_records,
            merged_retry_metrics,
            update_run_state=ctx.update_run_state,
            persist_logs=ctx.persist_logs,
            record_writer=ctx.record_writer,
        )
        result.url_metrics["listing_browser_retry"] = True
        result.url_metrics["listing_browser_retry_method"] = browser_acq.method
        result.url_metrics["listing_browser_retry_acquisition_ms"] = browser_retry_ms
        result.url_metrics["original_url_metrics"] = original_metrics
        result.url_metrics["retry_url_metrics"] = retry_metrics
        result.url_metrics["acquisition_ms"] = ctx.acquisition_ms
        result.url_metrics["extraction_ms"] = _elapsed_ms(extraction_started)
        ctx.records = result.records
        ctx.verdict = result.verdict
        ctx.url_metrics = result.url_metrics
