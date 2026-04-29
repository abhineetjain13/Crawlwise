from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.acquisition_plan import AcquisitionPlan
from app.services.acquisition.acquirer import (
    AcquisitionRequest,
    AcquisitionResult,
    acquire,
)
from app.services.adapters.base import AdapterResult
from app.services.crawl_crud import create_crawl_run, get_run_logs, get_run_records
from app.services.pipeline.core import (
    _best_adapter_result,
    _empty_extraction_browser_retry_decision,
    _resolved_url_processing_config,
    apply_llm_fallback,
    process_single_url,
)
from app.services.pipeline.persistence import persist_acquisition_artifacts
from app.services.pipeline.types import URLProcessingConfig
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.robots_policy import RobotsPolicyResult
from sqlalchemy.ext.asyncio import AsyncSession


def _detail_html() -> str:
    return "<html><body><h1>Widget Prime</h1></body></html>"


def _listing_html() -> str:
    return "<html><body><h1>Empty category</h1></body></html>"


def _fake_acquire_result(
    request: AcquisitionRequest,
    *,
    html: str | None = None,
    method: str = "test",
    status_code: int = 200,
    final_url: str | None = None,
    **overrides,
) -> AcquisitionResult:
    return AcquisitionResult(
        request=request,
        final_url=final_url or request.url,
        html=_detail_html() if html is None else html,
        method=method,
        status_code=status_code,
        **overrides,
    )


async def _no_adapter(*_args, **_kwargs):
    return None


def test_best_adapter_result_deduplicates_unsourced_records() -> None:
    result = _best_adapter_result(
        [
            AdapterResult(
                records=[{"title": "Widget", "price": "$10"}],
                source_type="json",
                adapter_name="first",
            ),
            AdapterResult(
                records=[{"price": "$10", "title": "Widget"}],
                source_type="json",
                adapter_name="second",
            ),
        ]
    )

    assert result is not None
    assert result.records == [{"title": "Widget", "price": "$10"}]


def test_empty_extraction_retry_skips_static_detail_price_html() -> None:
    request = AcquisitionRequest(
        run_id=1,
        url="https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        plan=AcquisitionPlan(surface="ecommerce_detail"),
    )
    acquisition_result = AcquisitionResult(
        request=request,
        final_url=request.url,
        html="""
        <html>
          <body>
            <article class="product_page">
              <h1>A Light in the Attic</h1>
              <p class="price_color">£51.77</p>
            </article>
          </body>
        </html>
        """,
        method="curl_cffi",
        status_code=200,
    )

    decision = _empty_extraction_browser_retry_decision(
        acquisition_result,
        [],
        surface="ecommerce_detail",
        requested_fields=[],
        selector_rules=[],
    )

    assert decision == {
        "should_retry": False,
        "reason": "static_detail_extractable",
    }


@pytest.mark.asyncio
async def test_process_single_url_blocks_before_acquire_when_robots_disallows(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/private/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": True},
        },
    )

    async def _disallow(url: str, *, user_agent: str = "*") -> RobotsPolicyResult:
        del user_agent
        return RobotsPolicyResult(
            allowed=False,
            outcome="disallowed",
            robots_url="https://example.com/robots.txt",
        )

    async def _unexpected_acquire(request):
        raise AssertionError(f"acquire should not run for {request.url}")

    monkeypatch.setattr("app.services.pipeline.core.check_url_crawlability", _disallow)
    monkeypatch.setattr("app.services.pipeline.core.acquire", _unexpected_acquire)

    result = await process_single_url(db_session, run, run.url)
    logs = await get_run_logs(db_session, run.id)

    assert result.records == []
    assert result.verdict == "blocked"
    assert result.url_metrics["robots"]["allowed"] is False
    assert result.url_metrics["robots"]["outcome"] == "disallowed"
    assert [log.message for log in logs] == [
        "[ROBOTS] Blocked by robots.txt: https://example.com/private/widget-prime"
    ]


@pytest.mark.asyncio
async def test_process_single_url_prefetch_only_returns_metrics_without_persisting_records(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return _fake_acquire_result(request)

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    result = await process_single_url(
        db_session,
        run,
        run.url,
        URLProcessingConfig(prefetch_only=True),
    )
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.records == []
    assert result.verdict == "success"
    assert result.url_metrics["record_count"] == 0
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
async def test_post_extraction_challenge_shell_retries_real_chrome(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://www.nike.com/t/widget",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )
    attempted_engines: list[str] = []
    hard_blocks: list[dict[str, object]] = []

    async def _fake_acquire(request: AcquisitionRequest) -> AcquisitionResult:
        forced_engine = str(
            request.acquisition_profile.get("forced_browser_engine") or "patchright"
        )
        attempted_engines.append(forced_engine)
        challenge = forced_engine == "patchright"
        return _fake_acquire_result(
            request,
            html=f"<html><body>{forced_engine}</body></html>",
            method="browser",
            blocked=False,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_engine": forced_engine,
                "browser_outcome": "usable_content",
                "challenge_evidence": ["strong:captcha", "provider:akamai"] if challenge else [],
                "challenge_provider_hits": ["akamai"] if challenge else [],
            },
        )

    def _fake_extract_records(html: str, *_args, **_kwargs):
        if "real_chrome" not in html:
            return []
        return [
            {
                "title": "Nike Widget",
                "url": "https://www.nike.com/t/widget",
                "price": "$50",
            }
        ]

    async def _fake_note_host_hard_block(value: str | None, **kwargs):
        hard_blocks.append({"value": value, **kwargs})

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", _fake_extract_records)
    monkeypatch.setattr(
        "app.services.pipeline.core.real_chrome_browser_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.note_host_hard_block",
        _fake_note_host_hard_block,
    )
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert attempted_engines == ["patchright", "real_chrome"]
    assert hard_blocks[0]["method"] == "browser:patchright"
    assert result.verdict == "success"
    assert total == 1
    assert rows[0].data["title"] == "Nike Widget"


@pytest.mark.asyncio
async def test_usable_detail_with_active_provider_evidence_does_not_retry_real_chrome(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://www.nike.com/t/widget",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )
    attempted_engines: list[str] = []

    async def _fake_acquire(request: AcquisitionRequest) -> AcquisitionResult:
        forced_engine = str(
            request.acquisition_profile.get("forced_browser_engine") or "patchright"
        )
        attempted_engines.append(forced_engine)
        return _fake_acquire_result(
            request,
            html="<html><body>Nike Widget</body></html>",
            method="browser",
            blocked=False,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_engine": forced_engine,
                "browser_outcome": "usable_content",
                "challenge_evidence": ["active_provider:akamai"],
                "challenge_provider_hits": ["akamai"],
            },
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *_args, **_kwargs: [
            {
                "title": "Nike Widget",
                "url": "https://www.nike.com/t/widget",
                "price": "$50",
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.real_chrome_browser_available",
        lambda: True,
    )
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)

    result = await process_single_url(db_session, run, run.url)

    assert attempted_engines == ["patchright"]
    assert result.verdict == "success"
    assert result.url_metrics["blocked"] is False
    assert result.url_metrics.get("failure_reason") is None


@pytest.mark.asyncio
async def test_patchright_challenge_shell_updates_host_memory(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://www.nike.com/t/widget",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )
    hard_blocks: list[dict[str, object]] = []

    async def _fake_acquire(request: AcquisitionRequest) -> AcquisitionResult:
        return _fake_acquire_result(
            request,
            html="<html><body>patchright</body></html>",
            method="browser",
            blocked=False,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_engine": "patchright",
                "browser_outcome": "usable_content",
                "challenge_evidence": ["strong:captcha", "provider:akamai"],
                "challenge_provider_hits": ["akamai"],
            },
        )

    async def _fake_note_host_hard_block(value: str | None, **kwargs):
        hard_blocks.append({"value": value, **kwargs})

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.real_chrome_browser_available",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.note_host_hard_block",
        _fake_note_host_hard_block,
    )
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)

    await process_single_url(db_session, run, run.url)

    assert hard_blocks
    assert hard_blocks[0]["method"] == "browser:patchright"


@pytest.mark.asyncio
async def test_process_single_url_runs_adapter_against_browser_artifact_fragments(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://www.belk.com/home/",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False, "max_records": 10},
        },
    )

    fragment = """
    <article class="product-tile">
      <a href="/p/polo-ralph-lauren-slim-straight-jeans/123.html">
        <span class="product-name">Slim Straight Jeans</span>
      </a>
      <span class="product-brand">Polo Ralph Lauren</span>
      <span class="price">$89.50</span>
    </article>
    """

    async def _fake_acquire(request):
        return _fake_acquire_result(
            request,
            html="<html><body><h1>Home</h1></body></html>",
            method="browser",
            artifacts={"rendered_listing_fragments": [fragment]},
        )

    async def _fake_run_adapter(url, html, surface):
        if "product-tile" not in html:
            return None
        return AdapterResult(
            records=[
                {
                    "title": "Slim Straight Jeans",
                    "brand": "Polo Ralph Lauren",
                    "price": "89.50",
                    "url": "https://www.belk.com/p/polo-ralph-lauren-slim-straight-jeans/123.html",
                    "_source": "belk_adapter",
                }
            ],
            source_type="belk_adapter",
            adapter_name="belk",
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    def _fake_extract_records(*args, **kwargs):
        return list(kwargs.get("adapter_records") or [])

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/belk.html"

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _fake_run_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", _fake_extract_records)
    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert result.url_metrics["adapter_name"] == "belk"
    assert result.records[0]["brand"] == "Polo Ralph Lauren"


@pytest.mark.asyncio
async def test_process_single_url_prefers_richer_adapter_artifact_rows(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://www.belk.com/home/",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False, "max_records": 10},
        },
    )

    async def _fake_acquire(request):
        return _fake_acquire_result(
            request,
            html="<html><body>partial product-tile</body></html>",
            method="browser",
            artifacts={"rendered_listing_fragments": ["rich product-tile"]},
        )

    async def _fake_run_adapter(url, html, surface):
        del url, surface
        if "rich product-tile" in html:
            records = [
                {"title": "Rich One", "brand": "Brand", "url": "https://www.belk.com/p/1.html"},
                {"title": "Rich Two", "brand": "Brand", "url": "https://www.belk.com/p/2.html"},
            ]
        elif "partial product-tile" in html:
            records = [
                {"title": "Partial One", "url": "https://www.belk.com/p/1.html"},
            ]
        else:
            return None
        return AdapterResult(records=records, source_type="belk_adapter", adapter_name="belk")

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    def _fake_extract_records(*args, **kwargs):
        return list(kwargs.get("adapter_records") or [])

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/belk.html"

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _fake_run_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", _fake_extract_records)
    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert [record["title"] for record in result.records] == ["Rich One", "Rich Two"]


def test_url_processing_config_syncs_compatibility_fields_from_acquisition_plan() -> None:
    config = URLProcessingConfig.from_acquisition_plan(
        AcquisitionPlan(
            surface="job_listing",
            proxy_list=("http://proxy-1",),
            traversal_mode="paginate",
            max_pages=7,
            max_scrolls=3,
            max_records=11,
            sleep_ms=900,
        ),
        persist_logs=False,
    )

    assert config.proxy_list == ["http://proxy-1"]
    assert config.traversal_mode == "paginate"
    assert config.max_pages == 7
    assert config.max_scrolls == 3
    assert config.max_records == 11
    assert config.sleep_ms == 900
    assert config.persist_logs is False


def test_resolved_url_processing_config_handles_none_plan_limits() -> None:
    config = URLProcessingConfig.from_acquisition_plan(
        AcquisitionPlan(
            surface="ecommerce_detail",
            max_pages=None,  # type: ignore[arg-type]
            max_scrolls=None,  # type: ignore[arg-type]
            max_records=None,  # type: ignore[arg-type]
            sleep_ms=None,  # type: ignore[arg-type]
        )
    )

    resolved = _resolved_url_processing_config(
        config,
        surface="ecommerce_detail",
        proxy_list=[],
        traversal_mode=None,
        max_pages=4,
        max_scrolls=5,
        max_records=6,
        sleep_ms=7,
        update_run_state=True,
        persist_logs=True,
    )

    assert resolved.max_pages == crawler_runtime_settings.traversal_max_iterations_cap
    assert resolved.max_scrolls == crawler_runtime_settings.traversal_max_iterations_cap
    assert resolved.max_records == 6
    assert resolved.sleep_ms == 7


def test_resolved_url_processing_config_preserves_explicit_zero_sleep_ms() -> None:
    config = URLProcessingConfig.from_acquisition_plan(
        AcquisitionPlan(
            surface="ecommerce_listing",
            sleep_ms=0,
        )
    )

    resolved = _resolved_url_processing_config(
        config,
        surface="ecommerce_listing",
        proxy_list=[],
        traversal_mode=None,
        max_pages=4,
        max_scrolls=5,
        max_records=6,
        sleep_ms=25,
        update_run_state=True,
        persist_logs=True,
    )

    assert resolved.sleep_ms == 0


@pytest.mark.asyncio
async def test_acquire_normalizes_retry_reason_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_fetch_page(url: str, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return type(
            "_FetchResult",
            (),
            {
                "final_url": url,
                "html": "<html></html>",
                "method": "browser",
                "status_code": 200,
                "content_type": "text/html",
                "blocked": False,
                "headers": {},
            },
        )()

    monkeypatch.setattr("app.services.acquisition.acquirer.fetch_page", _fake_fetch_page)

    await acquire(
        AcquisitionRequest(
            run_id=1,
            url="https://example.com/category/widgets",
            plan=AcquisitionPlan(surface="ecommerce_listing", traversal_mode="paginate"),
            acquisition_profile={"prefer_browser": True, "retry_reason": "thin-listing retry"},
        )
    )

    assert captured["browser_reason"] == "thin-listing retry"
    assert captured["listing_recovery_mode"] == "thin_listing"


@pytest.mark.asyncio
async def test_process_single_url_marks_empty_listing_as_listing_detection_failed(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_listing_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.records == []
    assert result.verdict == "listing_detection_failed"
    assert result.url_metrics["record_count"] == 0
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
async def test_process_single_url_preserves_proxy_list_for_detail_surface(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {
                "respect_robots_txt": False,
                "proxy_enabled": True,
                "proxy_list": ["http://proxy-1"],
                "proxy_profile": {
                    "enabled": True,
                    "proxy_list": ["http://proxy-1"],
                },
            },
        },
    )
    captured_proxy_lists: list[list[str]] = []

    async def _fake_acquire(request):
        captured_proxy_lists.append(list(request.proxy_list))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [{"title": "Widget Prime"}])
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widget-prime.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert captured_proxy_lists == [["http://proxy-1"]]
    assert result.verdict == "success"


@pytest.mark.asyncio
async def test_process_single_url_repairs_missing_proxy_list_from_run_settings_when_config_is_skinny(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {
                "respect_robots_txt": False,
                "proxy_enabled": True,
                "proxy_list": ["http://proxy-1"],
                "proxy_profile": {
                    "enabled": True,
                    "proxy_list": ["http://proxy-1"],
                },
            },
        },
    )
    captured_proxy_lists: list[list[str]] = []

    async def _fake_acquire(request):
        captured_proxy_lists.append(list(request.proxy_list))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [{"title": "Widget Prime"}])

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widget-prime.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(
        db_session,
        run,
        run.url,
        URLProcessingConfig.from_acquisition_plan(AcquisitionPlan(surface="ecommerce_detail")),
    )

    assert captured_proxy_lists == [["http://proxy-1"]]
    assert result.verdict == "success"


@pytest.mark.asyncio
async def test_process_single_url_does_not_duplicate_block_warning_after_browser_event(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        await request.on_event(
            "warning",
            f"Acquisition detected rate limiting or bot protection for {request.url}",
        )
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>challenge shell</body></html>",
            method="browser",
            status_code=200,
            blocked=False,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_outcome": "challenge_page",
                "challenge_provider_hits": ["datadome"],
                "challenge_evidence": ["provider:datadome"],
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    await process_single_url(db_session, run, run.url)
    logs = await get_run_logs(db_session, run.id)
    warning_messages = [
        log.message
        for log in logs
        if log.level == "warning"
        and "Acquisition detected rate limiting or bot protection" in log.message
    ]

    assert warning_messages == [
        "Acquisition detected rate limiting or bot protection for https://example.com/category/widgets"
    ]


@pytest.mark.asyncio
async def test_process_single_url_persists_detail_records_after_self_heal_and_llm_fallback(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False, "llm_enabled": True},
            "additional_fields": ["price"],
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    async def _fake_self_heal(session, **kwargs):
        del session
        record = dict(kwargs["records"][0])
        record["title"] = "Widget Prime (self-healed)"
        record["_self_heal"] = {"mode": "selector_synthesis", "triggered": True}
        return [record], list(kwargs["selector_rules"])

    async def _fake_llm(session, *, records, **kwargs):
        del session, kwargs
        record = dict(records[0])
        record["price"] = "19.99"
        return [record]

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [{"title": "Widget Prime", "_source": "extraction"}],
    )
    monkeypatch.setattr("app.services.pipeline.core.apply_selector_self_heal", _fake_self_heal)
    monkeypatch.setattr("app.services.pipeline.core.apply_llm_fallback", _fake_llm)

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widget-prime.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.verdict == "success"
    assert result.records == [
        {
            "title": "Widget Prime (self-healed)",
            "_source": "extraction",
            "_self_heal": {"mode": "selector_synthesis", "triggered": True},
            "price": "19.99",
        }
    ]
    assert run.summary_dict()["current_stage"] == "PERSIST"
    assert total == 1
    assert rows[0].data == {"title": "Widget Prime (self-healed)", "price": "19.99"}
    assert rows[0].raw_html_path == "artifacts/widget-prime.html"


@pytest.mark.asyncio
async def test_process_single_url_retries_with_browser_after_empty_non_browser_extraction(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )
    acquire_calls: list[dict[str, object]] = []

    async def _fake_acquire(request):
        acquire_calls.append(dict(request.acquisition_profile))
        if request.acquisition_profile.get("prefer_browser"):
            return AcquisitionResult(
                request=request,
                final_url=request.url,
                html="<html><body>browser</body></html>",
                method="browser",
                status_code=200,
            )
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>http</body></html>",
            method="curl_cffi",
            status_code=200,
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    def _extract_records(html, *args, **kwargs):
        del args, kwargs
        if "browser" in html:
            return [{"title": "Widget Prime", "url": "https://example.com/products/widget-prime"}]
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", _extract_records)
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert len(acquire_calls) == 2
    assert acquire_calls[1]["prefer_browser"] is True
    assert result.verdict == "success"
    assert result.url_metrics["method"] == "browser"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


@pytest.mark.asyncio
async def test_process_single_url_persists_listing_page_source_separately_from_record_url(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>listing</body></html>",
            method="browser",
            status_code=200,
            browser_diagnostics={"browser_attempted": True},
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [
            {
                "title": "Widget Prime",
                "source_url": "https://example.com/category/widgets",
                "url": "https://example.com/products/widget-prime",
                "_source": "dom_listing",
            }
        ],
    )
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.verdict == "success"
    assert total == 1
    assert rows[0].source_url == "https://example.com/category/widgets"
    assert rows[0].data["url"] == "https://example.com/products/widget-prime"
    assert "page_markdown" not in (rows[0].raw_data or {})


@pytest.mark.asyncio
async def test_process_single_url_log_uses_generic_extraction_label_when_no_adapter_matches(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>listing</body></html>",
            method="browser",
            status_code=200,
            browser_diagnostics={"browser_attempted": True},
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [
            {
                "title": "Widget Prime",
                "source_url": "https://example.com/category/widgets",
                "url": "https://example.com/products/widget-prime",
                "_source": "dom_listing",
            }
        ],
    )
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    await process_single_url(db_session, run, run.url)
    logs = await get_run_logs(db_session, run.id)

    assert any(
        log.message == "Extracted 1 records using generic extraction path"
        for log in logs
    )


@pytest.mark.asyncio
async def test_process_single_url_skips_duplicate_run_identity_records_during_persistence(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body><h1>Widget Prime</h1></body></html>",
            method="browser",
            status_code=200,
            browser_diagnostics={"browser_attempted": True},
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [
            {
                "title": "Widget Prime",
                "source_url": "https://example.com/products/widget-prime",
                "url": "https://example.com/products/widget-prime",
                "_source": "json_ld",
            }
        ],
    )
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widget-prime.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    first = await process_single_url(db_session, run, run.url)
    second = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert len(first.records) == 1
    assert len(second.records) == 1
    assert total == 1
    assert rows[0].data["url"] == "https://example.com/products/widget-prime"


@pytest.mark.asyncio
async def test_process_single_url_offloads_extract_records_to_thread(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )
    to_thread_calls: list[str] = []

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    async def _fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append(getattr(func, "__name__", type(func).__name__))
        return func(*args, **kwargs)

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.asyncio.to_thread", _fake_to_thread)

    result = await process_single_url(db_session, run, run.url)

    assert result.verdict == "success"
    assert "extract_records" in to_thread_calls


@pytest.mark.asyncio
async def test_process_single_url_keeps_platform_family_separate_from_adapter_provenance(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widget-prime.html"

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.detect_platform_family", lambda *args, **kwargs: "shopify")
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [{"title": "Widget Prime", "_source": "extraction"}],
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert result.url_metrics["adapter_name"] is None
    assert result.url_metrics["platform_family"] == "shopify"


@pytest.mark.asyncio
async def test_apply_llm_fallback_re_normalizes_llm_values_before_return(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime?utm_source=mail",
            "surface": "ecommerce_detail",
            "settings": {"llm_enabled": True},
            "additional_fields": ["review_count", "availability"],
        },
    )

    async def _fake_extract_missing_fields(*args, **kwargs):
        del args, kwargs
        return (
            {
                "review_count": "1,234 reviews",
                "availability": "In Stock",
                "url": "https://example.com/products/widget-prime?utm_source=mail",
            },
            None,
        )

    monkeypatch.setattr(
        "app.services.pipeline.direct_record_fallback.extract_missing_fields",
        _fake_extract_missing_fields,
    )

    rows = await apply_llm_fallback(
        db_session,
        run=run,
        page_url="https://example.com/products/widget-prime?utm_source=mail",
        html=_detail_html(),
        records=[
            {
                "title": "Widget Prime",
                "source_url": "https://example.com/products/widget-prime?utm_source=mail",
                "url": "https://example.com/products/widget-prime?utm_source=mail",
                "_source": "json_ld",
                "_field_sources": {"title": ["json_ld"]},
                "_confidence": {"score": 0.1},
                "_self_heal": {"enabled": False, "triggered": False},
            }
        ],
    )

    assert rows[0]["review_count"] == 1234
    assert rows[0]["availability"] == "in_stock"
    assert rows[0]["url"] == "https://example.com/products/widget-prime"
    assert rows[0]["source_url"] == "https://example.com/products/widget-prime"
    assert rows[0]["_field_sources"]["review_count"] == ["llm_missing_field_extraction"]
    assert rows[0]["_self_heal"]["mode"] == "missing_field_extraction"


@pytest.mark.asyncio
async def test_process_single_url_applies_llm_fallback_when_confidence_score_is_non_numeric(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"llm_enabled": True},
            "additional_fields": ["price"],
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    async def _fake_extract_missing_fields(*args, **kwargs):
        del args, kwargs
        return {"price": "19.99"}, None

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr(
        "app.services.pipeline.direct_record_fallback.extract_missing_fields",
        _fake_extract_missing_fields,
    )
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr(
        "app.services.pipeline.core.load_domain_selector_rules",
        _no_selector_rules,
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [
            {
                "title": "Widget Prime",
                "_confidence": {"score": "not-a-number"},
                "_self_heal": {},
            }
        ],
    )
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widget-prime.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.records[0]["price"] == "19.99"
    assert total == 1
    assert rows[0].data["price"] == "19.99"


@pytest.mark.asyncio
async def test_process_single_url_strips_schema_type_mismatches_during_normalization(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widget-prime.html"

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr(
        "app.services.pipeline.core.load_domain_selector_rules",
        _no_selector_rules,
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [
            {
                "title": "Widget Prime",
                "price": {"amount": "19.99"},
                "variants": "not-a-list",
                "_source": "adapter",
            }
        ],
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)
    logs = await get_run_logs(db_session, run.id)

    assert result.records == [{"title": "Widget Prime", "_source": "adapter"}]
    assert total == 1
    assert rows[0].data == {"title": "Widget Prime"}
    assert any(
        "Schema validation cleaned record 1" in log.message for log in logs
    )


@pytest.mark.asyncio
async def test_process_single_url_persists_browser_diagnostics_and_screenshot_artifacts(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )
    artifacts_dir = tmp_path / "artifacts"
    staged_screenshot = tmp_path / "browser-screenshot.png"
    staged_screenshot.write_bytes(b"fake-png")
    monkeypatch.setattr("app.services.artifact_store.settings.artifacts_dir", artifacts_dir)

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><head><title>Access denied</title></head><body>captcha datadome</body></html>",
            method="browser",
            status_code=403,
            blocked=True,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_reason": "http-escalation",
                "browser_outcome": "challenge_page",
                "html_bytes": 82,
                "phase_timings_ms": {"navigation": 1200},
                "challenge_evidence": ["captcha", "datadome"],
            },
            artifacts={"browser_screenshot_path": str(staged_screenshot)},
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])

    await process_single_url(db_session, run, run.url)

    artifact_dir = artifacts_dir / "runs" / str(run.id) / "pages"
    diagnostics_files = list(artifact_dir.glob("*.browser.json"))
    screenshot_files = list(artifact_dir.glob("*.browser.png"))

    assert len(diagnostics_files) == 1
    assert len(screenshot_files) == 1
    assert not staged_screenshot.exists()

    diagnostics_payload = json.loads(diagnostics_files[0].read_text(encoding="utf-8"))
    assert diagnostics_payload["browser_outcome"] == "challenge_page"
    assert diagnostics_payload["browser_reason"] == "http-escalation"
    assert diagnostics_payload["artifact_paths"]["html"].endswith(".html")
    assert diagnostics_payload["artifact_paths"]["screenshot"].endswith(".png")


@pytest.mark.asyncio
async def test_persist_acquisition_artifacts_treats_none_artifacts_as_empty_mapping(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr("app.services.artifact_store.settings.artifacts_dir", artifacts_dir)

    acquisition_result = AcquisitionResult(
        request=AcquisitionRequest(
            run_id=7,
            url="https://example.com/products/widget-prime",
            plan=AcquisitionPlan(surface="ecommerce_detail"),
        ),
        final_url="https://example.com/products/widget-prime",
        html="<html><body>Widget Prime</body></html>",
        method="browser",
        status_code=200,
        browser_diagnostics={"browser_attempted": True},
        artifacts=None,
    )

    raw_html_path = await persist_acquisition_artifacts(
        run_id=7,
        acquisition_result=acquisition_result,
        browser_attempted=True,
        screenshot_required=True,
    )

    assert raw_html_path.endswith(".html")
    assert acquisition_result.browser_diagnostics["artifact_paths"]["screenshot"] is None


@pytest.mark.asyncio
async def test_process_single_url_does_not_retry_browser_after_empty_browser_acquisition(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )
    acquire_calls: list[dict[str, object]] = []

    async def _fake_acquire(request):
        acquire_calls.append(dict(request.acquisition_profile))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>browser</body></html>",
            method="browser",
            status_code=200,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_reason": "http-escalation",
                "browser_outcome": "low_content_shell",
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert len(acquire_calls) == 1
    assert result.url_metrics["browser_attempted"] is True
    assert result.url_metrics["browser_outcome"] == "low_content_shell"
    assert result.verdict == "listing_detection_failed"


@pytest.mark.asyncio
async def test_process_single_url_skips_llm_on_low_content_browser_listing(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False, "llm_enabled": True},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><head><title>Belk Spa</title></head><body>Be Right Back!</body></html>",
            method="browser",
            status_code=200,
            page_markdown="# Belk Spa\n\nBe Right Back!",
            browser_diagnostics={
                "browser_attempted": True,
                "browser_reason": "http-escalation",
                "browser_outcome": "low_content_shell",
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    async def _unexpected_direct_llm(*args, **kwargs):
        del args, kwargs
        raise AssertionError("low-content browser result must not run direct LLM fallback")

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.services.pipeline.core.apply_direct_record_llm_fallback_impl", _unexpected_direct_llm)
    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.records == []
    assert result.verdict == "listing_detection_failed"
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
async def test_process_single_url_does_not_use_direct_llm_as_primary_listing_extractor(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False, "llm_enabled": True},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body><main>Category shell</main></body></html>",
            method="browser",
            status_code=200,
            page_markdown="# Widgets\n\nCategory shell",
            browser_diagnostics={
                "browser_attempted": True,
                "browser_reason": "http-escalation",
                "browser_outcome": "usable_content",
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    async def _unexpected_resolve_run_config(*args, **kwargs):
        del args, kwargs
        raise AssertionError("empty listing must not ask LLM to invent records")

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])
    monkeypatch.setattr("app.services.pipeline.core.resolve_run_config", _unexpected_resolve_run_config)
    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.records == []
    assert result.verdict == "listing_detection_failed"
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
async def test_process_single_url_ignores_extracted_placeholder_records_from_low_content_browser_page(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/for-sale/mixer-truck",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><head><title>JavaScript is disabled</title></head><body><h1>JavaScript is disabled</h1></body></html>",
            method="browser",
            status_code=200,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_reason": "http-escalation",
                "browser_outcome": "low_content_shell",
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [{"title": "JavaScript is disabled", "_source": "extraction"}],
    )
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/mixer-truck.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.records == []
    assert result.verdict == "blocked"
    assert result.url_metrics["browser_outcome"] == "low_content_shell"
    assert result.url_metrics["failure_reason"] == "challenge_shell"
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
async def test_process_single_url_does_not_retry_browser_after_prior_challenge_attempt(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )
    acquire_calls: list[dict[str, object]] = []

    async def _fake_acquire(request):
        acquire_calls.append(dict(request.acquisition_profile))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>http</body></html>",
            method="curl_cffi",
            status_code=200,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_reason": "http-escalation",
                "browser_outcome": "challenge_page",
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert len(acquire_calls) == 1
    assert result.url_metrics["method"] == "curl_cffi"
    assert result.url_metrics["blocked"] is True
    assert result.url_metrics["browser_attempted"] is True
    assert result.url_metrics["browser_outcome"] == "challenge_page"
    assert result.verdict == "blocked"


@pytest.mark.asyncio
async def test_process_single_url_marks_low_content_listing_with_challenge_signals_as_blocked(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>challenge shell</body></html>",
            method="browser",
            status_code=200,
            blocked=False,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_reason": "http-escalation",
                "browser_outcome": "low_content_shell",
                "challenge_provider_hits": ["datadome"],
                "challenge_evidence": ["provider:datadome"],
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert result.records == []
    assert result.url_metrics["blocked"] is True
    assert result.url_metrics["browser_outcome"] == "low_content_shell"
    assert result.verdict == "blocked"


@pytest.mark.asyncio
async def test_process_single_url_rejects_detail_non_detail_seed_with_failure_reason(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/search?q=widget",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>search</body></html>",
            method="browser",
            status_code=200,
            blocked=False,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_outcome": "usable_content",
                "readiness_probes": [{"is_ready": True}],
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [
            {"title": "Search Results", "url": "https://example.com/search?q=widget"}
        ],
    )
    monkeypatch.setattr(
        "app.services.pipeline.core.detail_record_rejection_reason",
        lambda *args, **kwargs: "non_detail_seed",
    )

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert result.records == []
    assert result.verdict == "empty"
    assert result.url_metrics["failure_reason"] == "non_detail_seed"
    assert result.url_metrics["record_count"] == 0


@pytest.mark.asyncio
async def test_process_single_url_rejects_detail_challenge_shell_and_marks_blocked(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>challenge</body></html>",
            method="browser",
            status_code=200,
            blocked=False,
            browser_diagnostics={
                "browser_attempted": True,
                "browser_reason": "vendor-block:datadome",
                "browser_outcome": "usable_content",
                "challenge_evidence": ["strong:captcha", "provider:datadome"],
                "challenge_provider_hits": ["datadome"],
                "readiness_probes": [{"is_ready": False}],
            },
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [
            {
                "title": "Sorry, you have been blocked",
                "url": "https://example.com/products/widget-prime",
            }
        ],
    )

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)
    logs = await get_run_logs(db_session, run.id)

    assert result.records == []
    assert result.verdict == "blocked"
    assert result.url_metrics["failure_reason"] == "challenge_shell"
    assert result.url_metrics["blocked"] is True
    assert [log.message for log in logs] == [
        "[ROBOTS] Ignoring robots.txt for https://example.com/products/widget-prime",
        "Extraction yielded 0 records (generic extraction path)",
        "Rejected detail extraction for https://example.com/products/widget-prime: challenge_shell",
    ]


@pytest.mark.asyncio
async def test_process_single_url_raises_when_browser_retry_fails(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr("app.services.artifact_store.settings.artifacts_dir", artifacts_dir)
    acquire_calls: list[dict[str, object]] = []

    async def _fake_acquire(request):
        acquire_calls.append(dict(request.acquisition_profile))
        if request.acquisition_profile.get("prefer_browser"):
            raise TimeoutError("browser retry timed out")
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>http</body></html>",
            method="curl_cffi",
            status_code=200,
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])

    with pytest.raises(TimeoutError, match="browser retry timed out"):
        await process_single_url(db_session, run, run.url)

    logs = await get_run_logs(db_session, run.id)
    artifact_dir = artifacts_dir / "runs" / str(run.id) / "pages"
    diagnostics_files = list(artifact_dir.glob("*.browser.json"))

    assert len(acquire_calls) == 2
    assert [log.message for log in logs] == [
        "[ROBOTS] Ignoring robots.txt for https://example.com/category/widgets",
        "Acquired payload via curl_cffi (status=200)",
        "Extraction yielded 0 records (generic extraction path)",
        "No records via curl_cffi; retrying browser render for https://example.com/category/widgets",
        "Browser retry failed for https://example.com/category/widgets: TimeoutError: browser retry timed out",
    ]
    assert len(diagnostics_files) == 0


@pytest.mark.asyncio
async def test_process_single_url_persists_live_acquisition_events(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )

    async def _fake_acquire(request):
        assert request.on_event is not None
        await request.on_event("info", "Detected listing layout, pagination: scroll")
        await request.on_event("info", "Scroll 1/3 - 24 -> 48 records")
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body>browser</body></html>",
            method="browser",
            status_code=200,
            browser_diagnostics={"browser_attempted": True},
        )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_records",
        lambda *args, **kwargs: [
            {
                "title": "Widget Prime",
                "url": "https://example.com/products/widget-prime",
            }
        ],
    )
    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    await process_single_url(db_session, run, run.url)
    logs = await get_run_logs(db_session, run.id)

    assert [log.message for log in logs] == [
        "[ROBOTS] Ignoring robots.txt for https://example.com/category/widgets",
        "Detected listing layout, pagination: scroll",
        "Scroll 1/3 - 24 -> 48 records",
        "Extracted 1 records using generic extraction path",
        "Normalized 1 record(s) for persistence",
        "Persisted 1 record(s) for https://example.com/category/widgets",
    ]


@pytest.mark.asyncio
async def test_extract_records_for_acquisition_recovers_from_zero_record_traversal_using_full_rendered_html(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
            "settings": {"respect_robots_txt": False},
        },
    )
    acquisition = AcquisitionResult(
        request=AcquisitionRequest(
            run_id=run.id,
            url=run.url,
            plan=AcquisitionPlan(surface="ecommerce_listing"),
        ),
        final_url=run.url,
        html="<html><body>traversal fragment</body></html>",
        method="browser",
        status_code=200,
        artifacts={"full_rendered_html": "<html><body>full rendered listing</body></html>"},
        browser_diagnostics={
            "browser_attempted": True,
            "requested_traversal_mode": "paginate",
            "selected_traversal_mode": "paginate",
            "traversal_activated": True,
            "pages_advanced": 1,
            "traversal_progress_events": 1,
            "traversal_stop_reason": "paginate_no_progress",
        },
    )

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    async def _fake_acquire(request):
        del request
        return acquisition

    def _extract_records(html, *args, **kwargs):
        del args, kwargs
        if "full rendered listing" in html:
            return [{"title": "Widget Prime", "url": "https://example.com/products/widget-prime"}]
        return []

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widgets.html"

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", _extract_records)
    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await process_single_url(db_session, run, run.url)

    assert result.records == [
        {"title": "Widget Prime", "url": "https://example.com/products/widget-prime"}
    ]
    assert acquisition.html == "<html><body>full rendered listing</body></html>"
    assert acquisition.artifacts["traversal_composed_html"] == "<html><body>traversal fragment</body></html>"
    assert result.url_metrics["traversal_fallback_used"] is True
    assert result.url_metrics["traversal_fallback_recovered"] is True
    assert result.url_metrics["traversal_fallback_record_count"] == 1

