from __future__ import annotations

import importlib

import pytest


def _reload_runtime_modules():
    runtime_settings = importlib.reload(
        importlib.import_module("app.services.config.runtime_settings")
    )
    crawl_runtime = importlib.reload(
        importlib.import_module("app.services.config.crawl_runtime")
    )
    return runtime_settings, crawl_runtime


def test_runtime_settings_respect_env_overrides(monkeypatch):
    monkeypatch.setenv("CRAWLER_RUNTIME_HTTP_TIMEOUT_SECONDS", "41")
    monkeypatch.setenv("CRAWLER_RUNTIME_DEFAULT_MAX_PAGES", "9")
    monkeypatch.setenv("CRAWLER_RUNTIME_URL_PROCESS_TIMEOUT_SECONDS", "33")
    monkeypatch.setenv("CRAWLER_RUNTIME_MAX_URL_PROCESS_TIMEOUT_SECONDS", "88")

    _, crawl_runtime = _reload_runtime_modules()

    assert crawl_runtime.HTTP_TIMEOUT_SECONDS == 41
    assert crawl_runtime.DEFAULT_MAX_PAGES == 9
    assert crawl_runtime.URL_PROCESS_TIMEOUT_SECONDS == 33.0
    assert crawl_runtime.MAX_URL_PROCESS_TIMEOUT_SECONDS == 88.0
    assert crawl_runtime.coerce_url_timeout_seconds("999") == 88.0


def test_runtime_settings_apply_performance_profile_defaults(monkeypatch):
    monkeypatch.setenv("CRAWLER_RUNTIME_PERFORMANCE_PROFILE", "STEALTH")
    monkeypatch.delenv("CRAWLER_RUNTIME_BROWSER_FALLBACK_VISIBLE_TEXT_MIN", raising=False)
    monkeypatch.delenv("CRAWLER_RUNTIME_CHALLENGE_WAIT_MAX_SECONDS", raising=False)
    monkeypatch.delenv("CRAWLER_RUNTIME_ORIGIN_WARM_PAUSE_MS", raising=False)
    monkeypatch.delenv("CRAWLER_RUNTIME_SURFACE_READINESS_MAX_WAIT_MS", raising=False)

    _, crawl_runtime = _reload_runtime_modules()

    assert crawl_runtime.BROWSER_FALLBACK_VISIBLE_TEXT_MIN == 200
    assert crawl_runtime.CHALLENGE_WAIT_MAX_SECONDS == 15
    assert crawl_runtime.ORIGIN_WARM_PAUSE_MS == 2000
    assert crawl_runtime.SURFACE_READINESS_MAX_WAIT_MS == 15000


def test_runtime_settings_reject_invalid_retry_bounds(monkeypatch):
    monkeypatch.setenv("CRAWLER_RUNTIME_HTTP_RETRY_BACKOFF_BASE_MS", "500")
    monkeypatch.setenv("CRAWLER_RUNTIME_HTTP_RETRY_BACKOFF_MAX_MS", "100")

    try:
        with pytest.raises(ValueError, match="http_retry_backoff_max_ms must be >= http_retry_backoff_base_ms"):
            importlib.reload(
                importlib.import_module("app.services.config.runtime_settings")
            )
    finally:
        monkeypatch.undo()
        importlib.reload(importlib.import_module("app.services.config.runtime_settings"))
        importlib.reload(importlib.import_module("app.services.config.crawl_runtime"))


def test_runtime_settings_preserve_previous_runtime_defaults(monkeypatch):
    monkeypatch.delenv("CRAWLER_RUNTIME_CHALLENGE_WAIT_MAX_SECONDS", raising=False)
    monkeypatch.delenv("CRAWLER_RUNTIME_SURFACE_READINESS_MAX_WAIT_MS", raising=False)
    monkeypatch.delenv("CRAWLER_RUNTIME_SURFACE_READINESS_POLL_MS", raising=False)
    monkeypatch.delenv("CRAWLER_RUNTIME_ORIGIN_WARM_PAUSE_MS", raising=False)
    monkeypatch.delenv("CRAWLER_RUNTIME_BROWSER_NAVIGATION_LOAD_TIMEOUT_MS", raising=False)
    monkeypatch.delenv(
        "CRAWLER_RUNTIME_BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS",
        raising=False,
    )
    monkeypatch.delenv("CRAWLER_RUNTIME_LISTING_READINESS_MAX_WAIT_MS", raising=False)

    _, crawl_runtime = _reload_runtime_modules()

    assert crawl_runtime.CHALLENGE_WAIT_MAX_SECONDS == 7
    assert crawl_runtime.SURFACE_READINESS_MAX_WAIT_MS == 6000
    assert crawl_runtime.SURFACE_READINESS_POLL_MS == 250
    assert crawl_runtime.ORIGIN_WARM_PAUSE_MS == 500
    assert crawl_runtime.BROWSER_NAVIGATION_LOAD_TIMEOUT_MS == 15000
    assert crawl_runtime.BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS == 15000
    assert crawl_runtime.LISTING_READINESS_MAX_WAIT_MS == 6000


def test_runtime_settings_expose_new_acquisition_and_traversal_tunables(monkeypatch):
    monkeypatch.setenv("CRAWLER_RUNTIME_IFRAME_PROMOTION_MAX_CANDIDATES", "5")
    monkeypatch.setenv("CRAWLER_RUNTIME_BROWSER_PREFERENCE_MIN_SUCCESSES", "4")
    monkeypatch.setenv("CRAWLER_RUNTIME_TRAVERSAL_MAX_ITERATIONS_CAP", "77")
    monkeypatch.setenv("CRAWLER_RUNTIME_PAGINATION_POST_CLICK_TIMEOUT_MS", "2100")
    monkeypatch.setenv("CRAWLER_RUNTIME_ACQUISITION_ARTIFACT_TTL_SECONDS", "7200")
    monkeypatch.setenv(
        "CRAWLER_RUNTIME_ACQUISITION_ARTIFACT_CLEANUP_INTERVAL_SECONDS",
        "45",
    )

    _, crawl_runtime = _reload_runtime_modules()

    assert crawl_runtime.IFRAME_PROMOTION_MAX_CANDIDATES == 5
    assert crawl_runtime.BROWSER_PREFERENCE_MIN_SUCCESSES == 4
    assert crawl_runtime.TRAVERSAL_MAX_ITERATIONS_CAP == 77
    assert crawl_runtime.PAGINATION_POST_CLICK_TIMEOUT_MS == 2100
    assert crawl_runtime.ACQUISITION_ARTIFACT_TTL_SECONDS == 7200
    assert crawl_runtime.ACQUISITION_ARTIFACT_CLEANUP_INTERVAL_SECONDS == 45
