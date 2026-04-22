from __future__ import annotations

from app.services.network_payload_mapper import (
    _looks_like_job_api,
    _looks_like_product_api,
    _infer_surface_from_body,
    map_network_payloads_to_fields,
)


def test_map_network_payloads_to_fields_preserves_greenhouse_job_detail() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "body": {
                    "title": "Manager, Engineering",
                    "company_name": "Greenhouse",
                    "location": {"name": "Ontario"},
                    "absolute_url": "https://job-boards.greenhouse.io/greenhouse/jobs/7704699",
                    "first_published": "2026-04-09T10:05:53-04:00",
                    "updated_at": "2026-04-10T10:05:53-04:00",
                    "content": (
                        "<p>Lead analytics engineering.</p>"
                        "<h2>What you'll do</h2><p>Lead and mentor engineers.</p>"
                    ),
                }
            }
        ],
        surface="job_detail",
        page_url="https://job-boards.greenhouse.io/greenhouse/jobs/7704699",
    )

    assert rows == [
        {
            "title": "Manager, Engineering",
            "company": "Greenhouse",
            "location": "Ontario",
            "apply_url": "https://job-boards.greenhouse.io/greenhouse/jobs/7704699",
            "posted_date": "2026-04-09T10:05:53-04:00",
            "updated_at": "2026-04-10T10:05:53-04:00",
            "responsibilities": "Lead and mentor engineers.",
            "description": "Lead analytics engineering. What you'll do Lead and mentor engineers.",
            "url": "https://job-boards.greenhouse.io/greenhouse/jobs/7704699",
        }
    ]


def test_map_network_payloads_to_fields_maps_generic_job_detail_payload() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "body": {
                    "job": {
                        "name": "Late Fallback Title",
                        "company": {"name": "Late Co"},
                    },
                    "posting": {
                        "title": "Senior Platform Engineer",
                        "organization": {"name": "Acme Hiring"},
                        "locations": [{"name": "Remote - India"}],
                        "applyUrl": "https://jobs.example.com/apply/platform-engineer",
                        "datePosted": "2026-04-18",
                        "updatedAt": "2026-04-19",
                        "description": (
                            "<p>Build platform systems.</p>"
                            "<h2>Qualifications</h2><p>Python and SQL.</p>"
                        ),
                    },
                }
            }
        ],
        surface="job_detail",
        page_url="https://jobs.example.com/platform-engineer",
    )

    assert rows == [
        {
            "title": "Senior Platform Engineer",
            "company": "Acme Hiring",
            "location": "Remote - India",
            "apply_url": "https://jobs.example.com/apply/platform-engineer",
            "posted_date": "2026-04-18",
            "updated_at": "2026-04-19",
            "qualifications": "Python and SQL.",
            "description": "Build platform systems. Qualifications Python and SQL.",
            "url": "https://jobs.example.com/apply/platform-engineer",
        }
    ]


def test_map_network_payloads_to_fields_maps_generic_ecommerce_first_non_empty_paths() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "body": {
                    "title": "Too Late Root Title",
                    "product": {"title": ""},
                    "item": {
                        "name": "Commuter Backpack",
                        "brand": {"name": "Urban Carry"},
                        "vendor": {"name": "Urban Carry Direct"},
                        "sku": "CB-001",
                        "price": {"current": "89.50", "currency": "USD"},
                        "availability": "In Stock",
                        "images": [
                            {"src": "https://cdn.example.com/bag-1.jpg"},
                            {"src": "https://cdn.example.com/bag-2.jpg"},
                        ],
                        "description": "Weather resistant pack",
                        "type": "Bags",
                        "url": "https://store.example.com/products/commuter-backpack",
                    },
                }
            }
        ],
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack",
    )

    assert rows == [
        {
            "title": "Commuter Backpack",
            "brand": "Urban Carry",
            "vendor": "Urban Carry Direct",
            "sku": "CB-001",
            "price": "89.50",
            "currency": "USD",
            "availability": "In Stock",
            "image_url": "https://cdn.example.com/bag-1.jpg",
            "additional_images": [
                "https://cdn.example.com/bag-1.jpg",
                "https://cdn.example.com/bag-2.jpg",
            ],
            "description": "Weather resistant pack",
            "category": "Bags",
            "url": "https://store.example.com/products/commuter-backpack",
        }
    ]


def test_map_network_payloads_to_fields_prioritizes_late_high_signal_job_payloads() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://jobs.example.com/api/bootstrap.json",
                "endpoint_type": "generic_json",
                "endpoint_family": "generic",
                "body": {
                    "posting": {
                        "title": "Fallback Platform Engineer",
                        "description": "<p>Fallback description.</p>",
                    }
                },
            },
            {
                "url": "https://boards.greenhouse.io/v1/boards/acme/jobs/1234",
                "endpoint_type": "job_api",
                "endpoint_family": "greenhouse",
                "body": {
                    "title": "Senior Platform Engineer",
                    "company_name": "Acme Hiring",
                    "location": {"name": "Remote - India"},
                    "absolute_url": "https://jobs.example.com/platform-engineer",
                    "first_published": "2026-04-18",
                    "content": "<p>Build platform systems.</p>",
                },
            },
        ],
        surface="job_detail",
        page_url="https://jobs.example.com/platform-engineer",
    )

    assert rows[0]["title"] == "Senior Platform Engineer"
    assert rows[0]["company"] == "Acme Hiring"


def test_map_network_payloads_to_fields_prioritizes_late_high_signal_product_payloads() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://store.example.com/bootstrap.json",
                "endpoint_type": "generic_json",
                "endpoint_family": "generic",
                "body": {
                    "item": {
                        "name": "Fallback Backpack",
                        "price": {"current": "79.50"},
                    }
                },
            },
            {
                "url": "https://store.example.com/products/commuter-backpack.js",
                "endpoint_type": "product_api",
                "endpoint_family": "shopify",
                "body": {
                    "product": {
                        "title": "Commuter Backpack",
                        "brand": {"name": "Urban Carry"},
                        "vendor": {"name": "Urban Carry Direct"},
                        "sku": "CB-001",
                        "price": {"current": "89.50", "currency": "USD"},
                        "availability": "In Stock",
                        "images": [{"src": "https://cdn.example.com/bag-1.jpg"}],
                    }
                },
            },
        ],
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack",
    )

    assert rows[0]["title"] == "Commuter Backpack"
    assert rows[0]["price"] == "89.50"


# ------------------------------------------------------------------
# Ghost-routing tests
# ------------------------------------------------------------------


def test_looks_like_product_api_detects_product_payload() -> None:
    assert _looks_like_product_api({
        "price": "29.99",
        "sku": "ABC-123",
        "name": "Widget",
        "description": "A fine widget",
    })


def test_looks_like_product_api_rejects_insufficient_keys() -> None:
    assert not _looks_like_product_api({
        "price": "29.99",
        "sku": "ABC-123",
    })


def test_looks_like_job_api_detects_job_payload() -> None:
    assert _looks_like_job_api({
        "title": "Engineer",
        "description": "Build things",
        "location": "Remote",
        "company": "Acme",
    })


def test_looks_like_job_api_rejects_insufficient_keys() -> None:
    assert not _looks_like_job_api({
        "title": "Engineer",
        "description": "Build things",
    })


def test_looks_like_product_api_rejects_non_dict() -> None:
    assert not _looks_like_product_api("not a dict")
    assert not _looks_like_product_api([1, 2, 3])


def test_looks_like_job_api_rejects_non_dict() -> None:
    assert not _looks_like_job_api(None)


def test_infer_surface_prefers_product_when_ambiguous() -> None:
    body = {
        "title": "Widget",
        "price": "29.99",
        "sku": "W-001",
        "description": "A product",
        "company": "MegaCorp",
    }
    assert _infer_surface_from_body(body) == "ecommerce_detail"


def test_infer_surface_returns_job_when_job_signature_stronger() -> None:
    body = {
        "title": "Senior Engineer",
        "description": "Build things",
        "location": "Berlin",
        "company": "Acme",
        "apply_url": "https://acme.com/apply",
        "salary": "100k",
    }
    assert _infer_surface_from_body(body) == "job_detail"


def test_infer_surface_returns_none_for_unrecognised_payload() -> None:
    assert _infer_surface_from_body({"foo": 1, "bar": 2}) is None


def test_ghost_route_captures_unconfigured_product_payload() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://custom-spa.example.com/api/v2/item/42",
                "endpoint_type": "generic_json",
                "endpoint_family": "custom",
                "body": {
                    "name": "Artisan Candle",
                    "price": "18.00",
                    "sku": "AC-99",
                    "description": "Hand-poured soy candle",
                    "brand": "Lumière",
                    "availability": "InStock",
                    "currency": "EUR",
                },
            }
        ],
        surface="ecommerce_detail",
        page_url="https://custom-spa.example.com/item/42",
    )
    assert len(rows) >= 1
    record = rows[0]
    assert record.get("title") == "Artisan Candle"
    assert record.get("price") == "18.00"
    assert record.get("sku") == "AC-99"


def test_ghost_route_captures_unconfigured_job_payload() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://react-spa.example.com/api/career/55",
                "endpoint_type": "generic_json",
                "endpoint_family": "custom",
                "body": {
                    "title": "Frontend Engineer",
                    "description": "Build React apps",
                    "location": "London",
                    "company": "StartupCo",
                    "apply_url": "https://react-spa.example.com/apply/55",
                    "salary": "£70k",
                },
            }
        ],
        surface="job_detail",
        page_url="https://react-spa.example.com/careers/55",
    )
    assert len(rows) >= 1
    record = rows[0]
    assert record.get("title") == "Frontend Engineer"
    assert record.get("company") == "StartupCo"


def test_ghost_route_fallback_when_spec_fails_to_match() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://weird-spa.example.com/data",
                "endpoint_type": "generic_json",
                "endpoint_family": "unknown",
                "body": {
                    "name": "Ghost Product",
                    "price": "42.00",
                    "sku": "GP-01",
                    "description": "Caught by ghost routing",
                },
            }
        ],
        surface="ecommerce_detail",
        page_url="https://weird-spa.example.com/item/gp-01",
    )
    assert len(rows) >= 1
    assert rows[0].get("title") == "Ghost Product"


def test_ghost_route_skips_non_matching_payload() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://example.com/api/config",
                "endpoint_type": "generic_json",
                "body": {"theme": "dark", "locale": "en-US"},
            }
        ],
        surface="ecommerce_detail",
        page_url="https://example.com",
    )
    assert rows == []


def test_ghost_route_works_on_surface_with_no_specs() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://example.com/api/product",
                "body": {
                    "name": "Unconfigured Surface Product",
                    "price": "15.00",
                    "sku": "US-01",
                    "description": "No spec for this surface",
                },
            }
        ],
        surface="automobile_detail",
        page_url="https://example.com/car/xyz",
    )
    assert len(rows) >= 1
    assert rows[0].get("title") == "Unconfigured Surface Product"


def test_ghost_route_rejects_navigation_payloads_with_price_like_noise() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://example.com/api/menu",
                "endpoint_type": "generic_json",
                "body": {
                    "menu": {
                        "items": [
                            {
                                "label": "Sale",
                                "href": "/sale",
                                "price": "19.99",
                            },
                            {
                                "label": "New In",
                                "href": "/new-in",
                                "price": "29.99",
                            },
                        ]
                    },
                    "footer": {"links": [{"label": "Contact", "href": "/contact"}]},
                },
            }
        ],
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget",
    )

    assert rows == []


def test_ghost_route_rejects_listing_envelope_for_detail_surface() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://api.example.com/products?page=1",
                "endpoint_type": "generic_json",
                "body": {
                    "current_page": 1,
                    "data": [
                        {
                            "id": "prod-1",
                            "name": "Combination Pliers",
                            "description": "Listing summary for pliers.",
                            "price": "14.15",
                            "brand": "ForgeFlex Tools",
                            "image": "https://cdn.example.com/pliers.jpg",
                            "url": "https://example.com/product/prod-1",
                        },
                        {
                            "id": "prod-2",
                            "name": "Bolt Cutters",
                            "description": "Listing summary for cutters.",
                            "price": "24.99",
                            "brand": "ForgeFlex Tools",
                            "image": "https://cdn.example.com/cutters.jpg",
                            "url": "https://example.com/product/prod-2",
                        },
                    ],
                },
            }
        ],
        surface="ecommerce_detail",
        page_url="https://example.com/#/product/short-fragment",
    )

    assert rows == []


def test_ghost_route_maps_vtex_style_product_payload_with_requested_custom_fields() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://india.whirlpool.in/productBySKU/1506",
                "endpoint_type": "generic_json",
                "body": {
                    "ProductName": "Vitamagic Pro 192L 3 Star Radiant Steel Auto Defrost Single Door Refrigerator - Radiant Steel-Y",
                    "BrandName": "Whirlpool",
                    "ImageUrl": "https://whirlpoolindia.vteximg.com.br/arquivos/ids/175375-55-55/fridge.jpg",
                    "DetailUrl": "/vitamagic-pro-192l-3-star-radiant-steel-auto-defrost-single-door-refrigerator-radiant-steel-y/p",
                    "ProductSpecifications": [
                        {
                            "FieldName": "Capacity(L)",
                            "FieldValues": ["192 L"],
                        },
                        {
                            "FieldName": "Energy Rating",
                            "FieldValues": ["3 Star"],
                        },
                        {
                            "FieldName": "Special Features",
                            "FieldValues": ["Auto Defrost Technology"],
                        },
                    ],
                },
            }
        ],
        surface="ecommerce_detail",
        page_url="https://india.whirlpool.in/vitamagic-pro-192l-3-star-radiant-steel-auto-defrost-single-door-refrigerator-radiant-steel-y/p?sc=1",
        requested_fields=["capacity", "energy_rating"],
    )

    assert rows == [
        {
            "title": "Vitamagic Pro 192L 3 Star Radiant Steel Auto Defrost Single Door Refrigerator - Radiant Steel-Y",
            "brand": "Whirlpool",
            "image_url": "https://whirlpoolindia.vteximg.com.br/arquivos/ids/175375-55-55/fridge.jpg",
            "url": "https://india.whirlpool.in/vitamagic-pro-192l-3-star-radiant-steel-auto-defrost-single-door-refrigerator-radiant-steel-y/p",
            "capacity": "192 L",
            "energy_rating": "3 Star",
            "features": "Auto Defrost Technology",
        }
    ]


def test_ghost_route_rejects_product_payload_whose_url_does_not_match_current_detail_page() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "url": "https://india.whirlpool.in/api/catalog",
                "endpoint_type": "generic_json",
                "body": {
                    "ProductName": "Refrigerators",
                    "BrandName": "Whirlpool",
                    "DetailUrl": "/refrigerators",
                    "Price": "16690",
                    "Description": "Home Care Plan - Annual Maintenance Contract 1 Year",
                },
            }
        ],
        surface="ecommerce_detail",
        page_url="https://india.whirlpool.in/vitamagic-pro-192l-3-star-radiant-steel-auto-defrost-single-door-refrigerator-radiant-steel-y/p?sc=1",
        requested_fields=["capacity"],
    )

    assert rows == []
