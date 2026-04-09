from __future__ import annotations

from app.services.extract.listing_extractor import _harvest_product_url_from_item


def test_harvest_product_url_from_template() -> None:
    item = {"sku": "849355_70", "urlTemplate": "/products/{sku}"}
    assert (
        _harvest_product_url_from_item(
            item, page_url="https://ar.puma.com/c/hombre"
        )
        == "https://ar.puma.com/products/849355_70"
    )


def test_harvest_nested_link_href() -> None:
    item = {
        "sku": "1",
        "link": {"href": "/p/one-tile", "title": "x"},
    }
    got = _harvest_product_url_from_item(item, page_url="https://example.com/list")
    assert got == "https://example.com/p/one-tile"
