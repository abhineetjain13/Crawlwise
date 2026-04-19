from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.acquisition_plan import AcquisitionPlan
from app.services.acquisition.acquirer import AcquisitionRequest, AcquisitionResult
from app.services.crawl_crud import create_crawl_run, get_run_logs, get_run_records
from app.services.pipeline.core import _apply_llm_fallback, _process_single_url
from app.services.pipeline.persistence import persist_acquisition_artifacts
from app.services.pipeline.types import URLProcessingConfig
from app.services.robots_policy import RobotsPolicyResult
from sqlalchemy.ext.asyncio import AsyncSession


def _detail_html() -> str:
    return "<html><body><h1>Widget Prime</h1></body></html>"


def _listing_html() -> str:
    return "<html><body><h1>Empty category</h1></body></html>"


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

    result = await _process_single_url(db_session, run, run.url)
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
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)

    result = await _process_single_url(
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
    async def _no_adapter(*args, **kwargs):
        del args, kwargs
        return None

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)

    result = await _process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.records == []
    assert result.verdict == "listing_detection_failed"
    assert result.url_metrics["record_count"] == 0
    assert total == 0
    assert rows == []


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
    async def _no_adapter(*args, **kwargs):
        del args, kwargs
        return None

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
    monkeypatch.setattr("app.services.pipeline.core._apply_llm_fallback", _fake_llm)

    async def _persist_artifacts(**kwargs):
        del kwargs
        return "artifacts/widget-prime.html"

    monkeypatch.setattr(
        "app.services.pipeline.core.persist_acquisition_artifacts",
        _persist_artifacts,
    )

    result = await _process_single_url(db_session, run, run.url)
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
    assert run.summary_dict()["current_stage"] == "SAVE"
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

    async def _no_adapter(*args, **kwargs):
        del args, kwargs
        return None

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

    result = await _process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert len(acquire_calls) == 2
    assert acquire_calls[1]["prefer_browser"] is True
    assert result.verdict == "success"
    assert result.url_metrics["method"] == "browser"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


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
        "app.services.pipeline.core.extract_missing_fields",
        _fake_extract_missing_fields,
    )

    rows = await _apply_llm_fallback(
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

    async def _no_adapter(*args, **kwargs):
        del args, kwargs
        return None

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr(
        "app.services.pipeline.core.extract_missing_fields",
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

    result = await _process_single_url(db_session, run, run.url)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert result.records[0]["price"] == "19.99"
    assert total == 1
    assert rows[0].data["price"] == "19.99"


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

    async def _no_adapter(*args, **kwargs):
        del args, kwargs
        return None

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])

    await _process_single_url(db_session, run, run.url)

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

    async def _no_adapter(*args, **kwargs):
        del args, kwargs
        return None

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

    result = await _process_single_url(db_session, run, run.url)

    assert len(acquire_calls) == 1
    assert result.url_metrics["browser_attempted"] is True
    assert result.url_metrics["browser_outcome"] == "low_content_shell"


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

    async def _no_adapter(*args, **kwargs):
        del args, kwargs
        return None

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

    result = await _process_single_url(db_session, run, run.url)

    assert len(acquire_calls) == 1
    assert result.url_metrics["method"] == "curl_cffi"
    assert result.url_metrics["browser_attempted"] is True
    assert result.url_metrics["browser_outcome"] == "challenge_page"


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

    async def _no_adapter(*args, **kwargs):
        del args, kwargs
        return None

    async def _no_selector_rules(*args, **kwargs):
        del args, kwargs
        return []

    monkeypatch.setattr("app.services.pipeline.core.acquire", _fake_acquire)
    monkeypatch.setattr("app.services.pipeline.core.run_adapter", _no_adapter)
    monkeypatch.setattr("app.services.pipeline.core.load_domain_selector_rules", _no_selector_rules)
    monkeypatch.setattr("app.services.pipeline.core.extract_records", lambda *args, **kwargs: [])

    with pytest.raises(TimeoutError, match="browser retry timed out"):
        await _process_single_url(db_session, run, run.url)

    logs = await get_run_logs(db_session, run.id)
    artifact_dir = artifacts_dir / "runs" / str(run.id) / "pages"
    diagnostics_files = list(artifact_dir.glob("*.browser.json"))

    assert len(acquire_calls) == 2
    assert [log.message for log in logs] == [
        "[ROBOTS] Ignoring robots.txt for https://example.com/category/widgets",
        "[FETCH] Fetching https://example.com/category/widgets",
        "[EXTRACT] No records via curl_cffi; retrying browser render for https://example.com/category/widgets",
        "[EXTRACT] Browser retry failed for https://example.com/category/widgets: TimeoutError: browser retry timed out",
    ]
    assert len(diagnostics_files) == 0
