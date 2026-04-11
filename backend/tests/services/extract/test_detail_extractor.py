from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.extract.detail_extractor import (
    _build_dom_gallery_rows,
    _normalize_product_detail_payload,
    _rich_text_from_node,
)


def test_rich_text_from_node_does_not_double_count_nested_table_rows():
    soup = BeautifulSoup(
        """
        <table>
          <tr><td>Outer</td></tr>
          <tr>
            <td>
              <table>
                <tr><td>Inner</td></tr>
              </table>
            </td>
          </tr>
        </table>
        """,
        "html.parser",
    )

    assert _rich_text_from_node(soup.table) == "Outer\nInner"


def test_build_dom_gallery_rows_omits_additional_images_for_single_image():
    soup = BeautifulSoup(
        '<div class="primary-images"><img src="/images/main.jpg" /></div>',
        "html.parser",
    )

    rows = _build_dom_gallery_rows(soup, base_url="https://example.com/product")

    assert rows["image_url"][0]["value"] == "https://example.com/images/main.jpg"
    assert "additional_images" not in rows


def test_normalize_product_detail_payload_omits_primary_image_from_additional_images():
    record = _normalize_product_detail_payload(
        {
            "name": "Trail Shoe",
            "images": [{"largeUrl": "/images/main.jpg"}],
        },
        base_url="https://example.com/product",
    )

    assert record["image_url"] == "https://example.com/images/main.jpg"
    assert "additional_images" not in record


def test_normalize_product_detail_payload_resolves_sizing_chart_against_base_url():
    record = _normalize_product_detail_payload(
        {
            "name": "Trail Shoe",
            "sizingChart": {"label": "Sizing chart", "url": "/size-guide"},
        },
        base_url="https://example.com/product",
    )

    assert record["fit_and_sizing"] == "Sizing chart: https://example.com/size-guide"
