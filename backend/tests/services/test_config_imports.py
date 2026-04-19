from __future__ import annotations

import importlib

from app.models.crawl_settings import CrawlRunSettings
from app.services.acquisition_plan import AcquisitionPlan
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.exceptions import CrawlerConfigurationError
from app.services.pipeline.pipeline_config import PipelineDefaults
from app.services.platform_policy import resolve_platform_runtime_policy
import pytest


def test_static_config_exports_remain_import_stable() -> None:
    selectors = importlib.import_module("app.services.config.selectors")
    field_mappings = importlib.import_module("app.services.config.field_mappings")
    original_card_selectors = selectors.CARD_SELECTORS
    original_canonical_schemas = field_mappings.CANONICAL_SCHEMAS

    selectors_reloaded = importlib.reload(selectors)
    field_mappings_reloaded = importlib.reload(field_mappings)

    assert "CARD_SELECTORS" in selectors_reloaded.__all__
    assert selectors_reloaded.CARD_SELECTORS == original_card_selectors
    assert selectors_reloaded.CARD_SELECTORS

    assert "CANONICAL_SCHEMAS" in field_mappings_reloaded.__all__
    assert field_mappings_reloaded.CANONICAL_SCHEMAS == original_canonical_schemas
    assert "job_detail" in field_mappings_reloaded.CANONICAL_SCHEMAS


def test_crawl_run_settings_exposes_normalized_acquisition_plan() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "proxy_list": ["http://proxy-1", "http://proxy-2"],
            "max_pages": "4",
            "max_scrolls": "2",
            "sleep_ms": "500",
            "advanced_enabled": True,
            "traversal_mode": "paginate",
        }
    )

    plan = settings.acquisition_plan(surface="job_listing", max_records=9)

    assert plan.surface == "job_listing"
    assert plan.proxy_list == ("http://proxy-1", "http://proxy-2")
    assert plan.traversal_mode == "paginate"
    assert plan.max_pages == 4
    assert plan.max_scrolls == 2
    assert plan.max_records == 9
    assert plan.sleep_ms == 500


def test_runtime_backed_defaults_remain_single_source_of_truth() -> None:
    plan = AcquisitionPlan(surface="job_listing")
    settings = CrawlRunSettings.from_value({})

    assert PipelineDefaults.MAX_PAGES == crawler_runtime_settings.default_max_pages
    assert PipelineDefaults.MAX_SCROLLS == crawler_runtime_settings.default_max_scrolls
    assert PipelineDefaults.MAX_RECORDS == crawler_runtime_settings.default_max_records
    assert PipelineDefaults.SLEEP_MS == crawler_runtime_settings.default_sleep_ms
    assert plan.max_pages == crawler_runtime_settings.default_max_pages
    assert plan.max_scrolls == crawler_runtime_settings.default_max_scrolls
    assert plan.max_records == crawler_runtime_settings.default_max_records
    assert settings.max_records() == crawler_runtime_settings.default_max_records


def test_invalid_traversal_mode_raises_configuration_error() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "advanced_enabled": True,
            "traversal_mode": "totally_invalid_mode",
        }
    )

    with pytest.raises(CrawlerConfigurationError, match="Unsupported traversal_mode"):
        settings.traversal_mode()


def test_platform_runtime_policy_does_not_force_browser_for_vendor_specific_domains() -> None:
    policy = resolve_platform_runtime_policy("https://www.autozone.com/")

    assert policy["requires_browser"] is False
