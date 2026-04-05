from __future__ import annotations

from bs4 import BeautifulSoup
import pytest

from app.schemas.selector import SelectorCreate, SelectorTestRequest
from app.services.selector_service import _normalize_selector_payload
from app.services.xpath_service import build_absolute_xpath, extract_selector_value


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


def test_extract_selector_value_supports_shadow_piercing_css_selector_syntax():
    html = """
    <html><body>
      <shop-price>
        <div data-shadow-dom-clone="true" hidden>
          <span class="price">$19.00</span>
        </div>
      </shop-price>
    </body></html>
    """

    value, count, selector_used = extract_selector_value(
        html,
        css_selector="shop-price >>> .price",
    )

    assert value == "$19.00"
    assert count == 1
    assert selector_used == "shop-price >>> .price"


def test_build_absolute_xpath_prefers_unique_id_anchor():
    soup = BeautifulSoup(
        "<html><body><section><h1 id='product-title'>Chair</h1></section></body></html>",
        "html.parser",
    )

    xpath = build_absolute_xpath(soup.select_one("#product-title"))

    assert xpath == "//h1[@id='product-title']"


def test_build_absolute_xpath_uses_relative_anchor_instead_of_full_dom_path():
    soup = BeautifulSoup(
        """
        <html><body>
          <main data-testid="product-page">
            <section><span class="price-value">$19</span></section>
          </main>
        </body></html>
        """,
        "html.parser",
    )

    xpath = build_absolute_xpath(soup.select_one(".price-value"))

    assert xpath is not None
    assert xpath.startswith("//main[@data-testid='product-page']/")
    assert "/html" not in xpath
