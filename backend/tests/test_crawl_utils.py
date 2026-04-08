# Tests for crawl_utils module
import pytest

from app.services.crawl_utils import (
    collect_target_urls,
    normalize_committed_field_name,
    normalize_target_url,
    parse_csv_urls,
    resolve_traversal_mode,
    validate_extraction_contract,
)


class TestNormalizeTargetUrl:
    def test_basic_url(self):
        assert normalize_target_url("https://example.com") == "https://example.com"
    
    def test_url_with_spaces(self):
        assert normalize_target_url("https://example.com /path") == "https://example.com/path"
    
    def test_url_with_html_entities(self):
        assert normalize_target_url("https://example.com?q=hello&amp;world") == "https://example.com?q=hello&world"
    
    def test_empty_string(self):
        assert normalize_target_url("") == ""
    
    def test_none_value(self):
        assert normalize_target_url(None) == ""


class TestParseCsvUrls:
    def test_single_url(self):
        csv = "https://example.com"
        assert parse_csv_urls(csv) == ["https://example.com"]
    
    def test_multiple_urls(self):
        csv = "https://example.com\nhttps://test.com"
        assert parse_csv_urls(csv) == ["https://example.com", "https://test.com"]
    
    def test_with_header(self):
        csv = "URL\nhttps://example.com\nhttps://test.com"
        assert parse_csv_urls(csv) == ["https://example.com", "https://test.com"]
    
    def test_empty_lines(self):
        csv = "https://example.com\n\nhttps://test.com"
        assert parse_csv_urls(csv) == ["https://example.com", "https://test.com"]
    
    def test_non_url_lines_skipped(self):
        csv = "https://example.com\ninvalid\nhttps://test.com"
        assert parse_csv_urls(csv) == ["https://example.com", "https://test.com"]


class TestCollectTargetUrls:
    def test_single_url_from_payload(self):
        payload = {"url": "https://example.com"}
        settings = {}
        assert collect_target_urls(payload, settings) == ["https://example.com"]
    
    def test_urls_array_from_payload(self):
        payload = {"urls": ["https://example.com", "https://test.com"]}
        settings = {}
        assert collect_target_urls(payload, settings) == ["https://example.com", "https://test.com"]
    
    def test_urls_from_settings(self):
        payload = {}
        settings = {"urls": ["https://example.com"]}
        assert collect_target_urls(payload, settings) == ["https://example.com"]
    
    def test_deduplication(self):
        payload = {"url": "https://example.com", "urls": ["https://example.com", "https://test.com"]}
        settings = {}
        result = collect_target_urls(payload, settings)
        assert result == ["https://example.com", "https://test.com"]
    
    def test_csv_content(self):
        payload = {}
        settings = {"csv_content": "https://example.com\nhttps://test.com"}
        assert collect_target_urls(payload, settings) == ["https://example.com", "https://test.com"]
    
    def test_combined_sources(self):
        payload = {"url": "https://example.com"}
        settings = {"urls": ["https://test.com"], "csv_content": "https://another.com"}
        result = collect_target_urls(payload, settings)
        assert result == ["https://example.com", "https://test.com", "https://another.com"]


class TestResolveTraversalMode:
    def test_auto_mode_maps_to_none(self):
        settings = {"traversal_mode": "auto"}
        assert resolve_traversal_mode(settings) is None

    def test_auto_mode_preserved_when_advanced_enabled(self):
        settings = {"traversal_mode": "auto", "advanced_enabled": True}
        assert resolve_traversal_mode(settings) == "auto"
    
    def test_valid_pagination_mode(self):
        settings = {"traversal_mode": "pagination"}
        assert resolve_traversal_mode(settings) == "paginate"
    
    def test_valid_infinite_scroll_mode(self):
        settings = {"traversal_mode": "infinite_scroll"}
        assert resolve_traversal_mode(settings) == "scroll"

    def test_valid_load_more_mode(self):
        settings = {"traversal_mode": "load_more"}
        assert resolve_traversal_mode(settings) == "load_more"

    def test_view_all_alias_maps_to_load_more(self):
        settings = {"traversal_mode": "view_all"}
        assert resolve_traversal_mode(settings) == "load_more"

    def test_advanced_mode_alias_supported(self):
        settings = {"advanced_mode": "paginate"}
        assert resolve_traversal_mode(settings) == "paginate"
    
    def test_invalid_mode(self):
        settings = {"traversal_mode": "invalid"}
        assert resolve_traversal_mode(settings) is None
    
    def test_empty_mode(self):
        settings = {"traversal_mode": ""}
        assert resolve_traversal_mode(settings) is None
    
    def test_none_settings(self):
        assert resolve_traversal_mode(None) is None
    
    def test_case_insensitive(self):
        settings = {"traversal_mode": "PAGINATE"}
        assert resolve_traversal_mode(settings) == "paginate"


class TestNormalizeCommittedFieldName:
    def test_simple_name(self):
        assert normalize_committed_field_name("price") == "price"
    
    def test_camel_case(self):
        assert normalize_committed_field_name("productName") == "product_name"
    
    def test_spaces(self):
        assert normalize_committed_field_name("product name") == "product_name"
    
    def test_special_characters(self):
        assert normalize_committed_field_name("product-name!") == "product_name"
    
    def test_multiple_underscores(self):
        assert normalize_committed_field_name("product___name") == "product_name"
    
    def test_leading_trailing_underscores(self):
        assert normalize_committed_field_name("_product_name_") == "product_name"
    
    def test_empty_string(self):
        assert normalize_committed_field_name("") == ""
    
    def test_uppercase(self):
        assert normalize_committed_field_name("PRODUCT_NAME") == "product_name"


class TestValidateExtractionContract:
    def test_valid_contract(self):
        contract = [
            {"field_name": "title", "xpath": "//h1", "regex": ""},
            {"field_name": "price", "xpath": "//span[@class='price']", "regex": r"\d+\.\d+"},
        ]
        # Should not raise
        validate_extraction_contract(contract)
    
    def test_missing_field_name(self):
        contract = [{"field_name": "", "xpath": "//h1"}]
        with pytest.raises(ValueError, match="field_name is required"):
            validate_extraction_contract(contract)
    
    def test_invalid_xpath(self):
        contract = [{"field_name": "title", "xpath": "//h1["}]
        with pytest.raises(ValueError, match="invalid XPath"):
            validate_extraction_contract(contract)
    
    def test_invalid_regex(self):
        contract = [{"field_name": "price", "xpath": "", "regex": "[invalid("}]
        with pytest.raises(ValueError, match="invalid regex"):
            validate_extraction_contract(contract)
    
    def test_empty_contract(self):
        # Should not raise
        validate_extraction_contract([])
    
    def test_multiple_errors(self):
        contract = [
            {"field_name": "", "xpath": "//h1"},
            {"field_name": "price", "xpath": "//span["},
        ]
        with pytest.raises(ValueError) as exc_info:
            validate_extraction_contract(contract)
        # Should contain both errors
        assert "field_name is required" in str(exc_info.value)
        assert "invalid XPath" in str(exc_info.value)
