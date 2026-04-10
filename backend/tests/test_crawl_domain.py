from __future__ import annotations

from app.models.crawl import CrawlRun
from app.models.crawl_settings import normalize_crawl_settings
from app.services.crawl_state import CrawlStatus
from app.services.config.crawl_runtime import coerce_url_timeout_seconds


def test_crawl_run_exposes_status_and_settings_helpers() -> None:
    run = CrawlRun(
        user_id=1,
        run_type="crawl",
        url="https://example.com",
        surface="ecommerce_detail",
        status="running",
        settings={
            "urls": ["https://example.com/a", " https://example.com/b "],
            "proxy_list": ["http://proxy.example:8080", " "],
            "max_pages": "7",
            "max_records": "12",
            "max_scrolls": "4",
            "sleep_ms": "150",
            "advanced_enabled": True,
            "traversal_mode": "paginate",
        },
    )

    assert run.status_value == CrawlStatus.RUNNING
    assert run.is_active()
    assert not run.is_terminal()
    assert run.can_transition_to(CrawlStatus.PAUSED)

    settings_view = run.settings_view
    assert settings_view.urls() == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert settings_view.proxy_list() == ["http://proxy.example:8080"]
    assert settings_view.max_pages() == 7
    assert settings_view.max_records() == 12
    assert settings_view.max_scrolls() == 4
    assert settings_view.sleep_ms() == 150
    assert settings_view.traversal_mode() == "paginate"

    next_status = run.set_status(CrawlStatus.PAUSED)
    assert next_status == CrawlStatus.PAUSED
    assert run.status == CrawlStatus.PAUSED.value


def test_normalize_crawl_settings_preserves_unknown_keys_and_coerces_known_ones() -> None:
    normalized = normalize_crawl_settings(
        {
            "urls": ["https://example.com/a", "https://example.com/b"],
            "max_pages": "99",
            "max_records": "5",
            "max_scrolls": "3",
            "sleep_ms": "0",
            "advanced_enabled": True,
            "traversal_mode": "view_all",
            "custom_flag": "kept",
        }
    )

    assert normalized["urls"] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert normalized["max_pages"] == 20
    assert normalized["max_records"] == 5
    assert normalized["max_scrolls"] == 3
    assert normalized["sleep_ms"] == 100
    assert normalized["traversal_mode"] == "load_more"
    assert normalized["advanced_mode"] == "load_more"
    assert normalized["custom_flag"] == "kept"


def test_crawl_runtime_timeout_coercion_clamps_invalid_values() -> None:
    assert coerce_url_timeout_seconds("not-a-number") == 90.0
    assert coerce_url_timeout_seconds(-1) == 90.0
    assert coerce_url_timeout_seconds(1000) == 600.0
