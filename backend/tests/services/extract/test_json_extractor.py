# Tests for JSON listing/detail extraction.
from __future__ import annotations

from app.services.extract.json_extractor import extract_json_detail, extract_json_listing


def test_extract_jobs_from_remotive_shape():
    """Remotive-style API response with 'jobs' array."""
    data = {
        "jobs": [
            {
                "title": "Backend Engineer",
                "company_name": "Acme",
                "url": "https://remotive.com/jobs/1",
                "candidate_required_location": "Worldwide",
                "salary": "$80k-$120k",
                "category": "Software Development",
            },
            {
                "title": "Frontend Developer",
                "company_name": "Beta Corp",
                "url": "https://remotive.com/jobs/2",
                "candidate_required_location": "US",
            },
        ]
    }
    records = extract_json_listing(data, "https://remotive.com/api")
    assert len(records) == 2
    assert records[0]["title"] == "Backend Engineer"
    assert records[0]["company"] == "Acme"
    assert records[1]["title"] == "Frontend Developer"


def test_extract_products_from_shopify_shape():
    """Shopify-style products.json response."""
    data = {
        "products": [
            {
                "title": "Cool Shirt",
                "vendor": "BrandX",
                "price": "29.99",
                "url": "/products/cool-shirt",
            },
            {
                "title": "Nice Pants",
                "vendor": "BrandY",
                "price": "49.99",
                "url": "/products/nice-pants",
            },
        ]
    }
    records = extract_json_listing(data, "https://store.com")
    assert len(records) == 2
    assert records[0]["title"] == "Cool Shirt"
    assert records[0]["brand"] == "BrandX"
    assert records[1]["url"] == "https://store.com/products/nice-pants"


def test_extract_from_top_level_array():
    """RemoteOK-style top-level array."""
    data = [
        {"position": "Engineer", "company": "X", "url": "/jobs/1"},
        {"position": "Designer", "company": "Y", "url": "/jobs/2"},
        {"position": "PM", "company": "Z", "url": "/jobs/3"},
    ]
    records = extract_json_listing(data, "https://remoteok.com")
    assert len(records) == 3
    assert records[0]["title"] == "Engineer"


def test_extract_nested_data_array():
    """API with nested data.items structure."""
    data = {
        "meta": {"total": 5},
        "data": {
            "items": [
                {"name": "Product A", "price": 10},
                {"name": "Product B", "price": 20},
                {"name": "Product C", "price": 30},
            ]
        }
    }
    records = extract_json_listing(data)
    assert len(records) == 3
    assert records[0]["title"] == "Product A"


def test_extract_json_detail():
    """Single product detail from JSON."""
    data = {
        "title": "Widget Pro",
        "price": "99.99",
        "brand": "WidgetCo",
        "description": "The best widget ever made.",
        "url": "/products/widget-pro",
    }
    records = extract_json_detail(data, "https://store.com")
    assert len(records) == 1
    assert records[0]["title"] == "Widget Pro"
    assert records[0]["price"] == "99.99"


def test_extract_json_detail_expands_job_sections():
    data = {
        "title": "Platform Engineer",
        "company_name": "Acme",
        "responsibilities": ["Build services", "Operate systems"],
        "qualifications": "5+ years Python",
    }
    records = extract_json_detail(data, "https://example.com/jobs/1")
    assert len(records) == 1
    assert records[0]["company"] == "Acme"
    assert "responsibilities" in records[0]
    assert "Build services" in records[0]["responsibilities"]


def test_empty_json_returns_empty():
    assert extract_json_listing({}) == []
    assert extract_json_listing([]) == []
    assert extract_json_detail({}) == []


def test_max_records_respected():
    data = [{"name": f"Item {i}", "price": i} for i in range(50)]
    records = extract_json_listing(data, max_records=5)
    assert len(records) == 5


def test_graphql_edges_pattern():
    """GraphQL-style edges/node response."""
    data = {
        "data": {
            "products": {
                "edges": [
                    {"node": {"name": "A", "price": 10}},
                    {"node": {"name": "B", "price": 20}},
                    {"node": {"name": "C", "price": 30}},
                ]
            }
        }
    }
    records = extract_json_listing(data)
    assert len(records) == 3


def test_extract_json_listing_preserves_original_raw_item_when_additional_images_is_a_list():
    data = {
        "products": [
            {
                "title": "Cool Shirt",
                "additional_images": [
                    {"src": "https://cdn.example.com/a.jpg"},
                    {"src": "https://cdn.example.com/b.jpg"},
                ],
                "price": "29.99",
            },
            {
                "title": "Nice Pants",
                "additional_images": [
                    {"src": "https://cdn.example.com/c.jpg"},
                ],
                "price": "49.99",
            },
        ]
    }

    records = extract_json_listing(data, "https://store.com")

    assert len(records) == 2
    assert records[0]["_raw_item"] is data["products"][0]
    assert records[0]["_raw_item"]["title"] == "Cool Shirt"
    assert isinstance(records[0]["_raw_item"]["additional_images"], list)
    assert records[0]["_raw_item"]["additional_images"][0]["src"] == "https://cdn.example.com/a.jpg"
