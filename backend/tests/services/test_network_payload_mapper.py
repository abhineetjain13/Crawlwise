from __future__ import annotations

from app.services.network_payload_mapper import map_network_payloads_to_fields


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
