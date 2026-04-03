from __future__ import annotations

import pytest

from app.schemas.selector import SelectorCreate, SelectorTestRequest
from app.services.selector_service import _normalize_selector_payload
from app.services.xpath_service import extract_selector_value


def test_selector_create_requires_one_selector():
    with pytest.raises(ValueError, match="At least one of css_selector, xpath, or regex is required"):
        SelectorCreate(domain="example.com", field_name="title")


def test_selector_test_request_requires_one_selector():
    with pytest.raises(ValueError, match="At least one of css_selector, xpath, or regex is required"):
        SelectorTestRequest(url="https://example.com")


def test_normalize_selector_payload_rejects_blank_domain():
    with pytest.raises(ValueError, match="domain is required"):
        _normalize_selector_payload({
            "domain": "   ",
            "field_name": "title",
            "css_selector": "h1",
        })


def test_normalize_selector_payload_rejects_blank_field_name():
    with pytest.raises(ValueError, match="field_name is required"):
        _normalize_selector_payload({
            "domain": "example.com",
            "field_name": "   ",
            "css_selector": "h1",
        })


def test_extract_selector_value_times_out_bad_regex(monkeypatch: pytest.MonkeyPatch):
    import app.services.xpath_service as xpath_service

    def _raise_timeout(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(xpath_service.regex_lib, "search", _raise_timeout)

    value, count, selector_used = extract_selector_value(
        "<html><body>Hello</body></html>",
        regex="(a+)+$",
    )

    assert value is None
    assert count == 0
    assert selector_used is None
