from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

from app.models.crawl_settings import CrawlRunSettings
from app.services.acquisition_plan import AcquisitionPlan
from app.services.config._export_data import (
    EXPORT_PROVENANCE_KEY,
    load_export_data,
    main,
    validate_export_file,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.runtime_settings import CrawlerRuntimeSettings
from app.services.exceptions import CrawlerConfigurationError
from app.services.platform_policy import resolve_platform_runtime_policy
from collections import Counter
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


def test_static_config_exports_have_provenance() -> None:
    config_dir = Path(__file__).parents[2] / "app" / "services" / "config"
    for path in sorted(config_dir.glob("*.exports.json")):
        exports = load_export_data(str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert EXPORT_PROVENANCE_KEY in payload
        assert EXPORT_PROVENANCE_KEY not in exports
        validate_export_file(path)


def test_export_validator_main_returns_clean_error_for_bad_payload(tmp_path, capsys) -> None:
    bad_export = tmp_path / "broken.exports.json"
    bad_export.write_text(json.dumps({"CARD_SELECTORS": []}), encoding="utf-8")

    assert main([str(bad_export)]) == 1
    assert "_export_provenance" in capsys.readouterr().err


def test_location_interstitial_tokens_are_unique() -> None:
    config_dir = Path(__file__).parents[2] / "app" / "services" / "config"
    exports = load_export_data(str(config_dir / "selectors.exports.json"))

    for key in (
        "LOCATION_INTERSTITIAL_DISMISS_TEXT_TOKENS",
        "LOCATION_INTERSTITIAL_TEXT_TOKENS",
    ):
        values = [str(item) for item in list(exports[key] or [])]
        duplicates = {value: count for value, count in Counter(values).items() if count > 1}
        assert duplicates == {}


def test_extraction_rules_export_keys_cover_module_references() -> None:
    config_dir = Path(__file__).parents[2] / "app" / "services" / "config"
    module_path = config_dir / "extraction_rules.py"
    exports = load_export_data(str(config_dir / "extraction_rules.exports.json"))
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    referenced_keys = {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "_EXPORTS"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }

    assert referenced_keys
    assert referenced_keys <= set(exports)


def test_extraction_rules_exports_document_link_patterns_via___all__() -> None:
    extraction_rules = importlib.import_module("app.services.config.extraction_rules")

    assert "DETAIL_DOCUMENT_LINK_LABEL_PATTERNS" in extraction_rules.__all__


def test_crawl_run_settings_exposes_normalized_acquisition_plan() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "proxy_list": ["http://proxy-1", "http://proxy-2"],
            "advanced_enabled": True,
            "fetch_profile": {
                "traversal_mode": "paginate",
                "max_pages": "4",
                "max_scrolls": "2",
                "request_delay_ms": "500",
            },
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

    assert plan.max_pages == crawler_runtime_settings.default_max_pages
    assert plan.max_scrolls == crawler_runtime_settings.default_max_scrolls
    assert plan.max_records == crawler_runtime_settings.default_max_records
    assert plan.sleep_ms == crawler_runtime_settings.min_request_delay_ms
    assert settings.max_records() == crawler_runtime_settings.default_max_records


def test_runtime_settings_allow_zero_accessibility_snapshot_timeout() -> None:
    settings = CrawlerRuntimeSettings(browser_accessibility_snapshot_timeout_seconds=0)

    assert settings.browser_accessibility_snapshot_timeout_seconds == 0


def test_invalid_traversal_mode_raises_configuration_error() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "advanced_enabled": True,
            "traversal_mode": "totally_invalid_mode",
        }
    )

    with pytest.raises(CrawlerConfigurationError, match="Unsupported traversal_mode"):
        settings.traversal_mode()


def test_auto_traversal_requires_advanced_mode_flag_from_ui_runs() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "advanced_enabled": False,
            "fetch_profile": {
                "traversal_mode": "auto",
            },
        }
    )

    assert settings.traversal_mode() is None
    assert settings.normalized_for_storage()["fetch_profile"]["traversal_mode"] is None


def test_crawl_run_settings_preserves_advanced_mode_storage_contract() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "advanced_enabled": True,
            "advanced_mode": "view_all",
            "traversal_mode": "load_more",
        }
    )

    normalized = settings.normalized_for_storage()

    assert normalized["advanced_mode"] == "view_all"
    assert normalized["traversal_mode"] == "load_more"
    assert normalized["fetch_profile"]["traversal_mode"] == "load_more"


def test_crawl_run_settings_preserves_extra_proxy_profile_fields() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "proxy_profile": {
                "enabled": True,
                "proxy_list": ["http://proxy-1"],
                "rotation": "sticky",
                "region": "in",
            }
        }
    )

    normalized = settings.normalized_for_storage()

    assert normalized["proxy_profile"] == {
        "enabled": True,
        "proxy_list": ["http://proxy-1"],
        "rotation": "sticky",
        "region": "in",
    }


def test_crawl_run_settings_acquisition_profile_preserves_proxy_profile() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "proxy_profile": {
                "enabled": True,
                "proxy_list": ["http://proxy-1"],
                "rotation": "rotating",
                "region": "in",
            }
        }
    )

    profile = settings.acquisition_profile()

    assert profile["proxy_profile"] == {
        "enabled": True,
        "proxy_list": ["http://proxy-1"],
        "rotation": "rotating",
        "region": "in",
    }


def test_crawl_run_settings_acquisition_profile_keeps_disabled_proxy_profile() -> None:
    settings = CrawlRunSettings.from_value({})

    profile = settings.acquisition_profile()

    assert profile["proxy_profile"] == {
        "enabled": False,
        "proxy_list": [],
    }
    assert profile["locality_profile"] == {
        "geo_country": "auto",
        "language_hint": None,
        "currency_hint": None,
    }


def test_crawl_run_settings_infers_sticky_rotation_from_sessionized_proxy_username() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "proxy_profile": {
                "enabled": True,
                "proxy_list": [
                    "http://user-session-autozone123:pass@rp.scrapegw.com:6060"
                ],
            }
        }
    )

    profile = settings.proxy_profile()

    assert profile["rotation"] == "sticky"


def test_crawl_run_settings_does_not_store_inferred_proxy_rotation() -> None:
    settings = CrawlRunSettings.from_value(
        {
            "proxy_profile": {
                "enabled": True,
                "proxy_list": [
                    "http://user-session-autozone123:pass@rp.scrapegw.com:6060"
                ],
            }
        }
    )

    normalized = settings.normalized_for_storage()

    assert normalized["proxy_profile"] == {
        "enabled": True,
        "proxy_list": [
            "http://user-session-autozone123:pass@rp.scrapegw.com:6060"
        ],
    }


def test_platform_runtime_policy_does_not_force_browser_for_vendor_specific_domains() -> None:
    policy = resolve_platform_runtime_policy("https://www.autozone.com/")

    assert policy["requires_browser"] is False
