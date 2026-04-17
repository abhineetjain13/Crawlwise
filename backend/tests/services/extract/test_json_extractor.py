import math
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


def test_extract_products_from_nested_shopify_shape():
    data = {
        "products": [
            {
                "title": "Cool Shirt",
                "vendor": "BrandX",
                "handle": "cool-shirt",
                "variants": [{"price": "29.99"}],
                "images": [
                    {"src": "https://cdn.store.com/a.jpg"},
                    {"src": "https://cdn.store.com/b.jpg"},
                ],
            }
        ]
    }

    records = extract_json_listing(data, "https://store.com/products.json")

    assert len(records) == 1
    assert records[0]["price"] == "29.99"
    assert records[0]["image_url"] == "https://cdn.store.com/a.jpg"
    assert records[0]["url"] == "https://store.com/products/cool-shirt"


def test_extract_products_derives_url_from_slug_without_treating_slug_as_url_alias():
    data = {
        "products": [
            {
                "title": "Gloss",
                "slug": "nykaa-cosmetics-x-naagin-hot-sauce-plumping-lip-gloss/p/22062112",
            }
        ]
    }

    records = extract_json_listing(data, "https://www.nykaa.com/makeup/c/12")

    assert len(records) == 1
    assert "slug" not in records[0]
    assert records[0]["url"] == "https://www.nykaa.com/nykaa-cosmetics-x-naagin-hot-sauce-plumping-lip-gloss/p/22062112"


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


def test_extract_json_listing_does_not_drop_fields_when_requested_fields_is_empty():
    data = {
        "products": [
            {"title": "Widget", "price": 12.5, "brand": "Acme"},
        ]
    }

    records = extract_json_listing(
        data,
        "https://example.com/products",
        requested_fields=[],
    )

    assert len(records) == 1
    assert records[0]["title"] == "Widget"
    assert math.isclose(records[0]["price"], 12.5, rel_tol=1e-09, abs_tol=1e-09)


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


def test_extract_from_drinks_collection_key():
    """API response with 'drinks' wrapper key and standard field names."""
    data = {
        "drinks": [
            {
                "name": "Margarita",
                "category": "Ordinary Drink",
                "description": "Rub rim of cocktail glass with lime...",
                "image": "https://example.com/margarita.jpg",
            },
            {
                "name": "Blue Margarita",
                "category": "Ordinary Drink",
                "description": "Rub rim of glass with lime...",
                "image": "https://example.com/blue-margarita.jpg",
            },
        ]
    }
    records = extract_json_listing(data)
    assert len(records) == 2
    assert records[0]["title"] == "Margarita"


def test_extract_from_nonstandard_field_names_fallback():
    """APIs with non-standard field names (e.g. strDrink) should still produce records."""
    data = {
        "drinks": [
            {"strDrink": "Margarita", "strCategory": "Ordinary Drink"},
            {"strDrink": "Blue Margarita", "strCategory": "Ordinary Drink"},
        ]
    }
    records = extract_json_listing(data)
    assert len(records) == 2
    assert records[0]["strDrink"] == "Margarita"


def test_extract_from_books_collection_key():
    """API response with 'books' wrapper key."""
    data = {
        "books": [
            {"title": "Clean Code", "price": 29.99},
            {"title": "Pragmatic Programmer", "price": 39.99},
        ]
    }
    records = extract_json_listing(data)
    assert len(records) == 2
    assert records[0]["title"] == "Clean Code"


def test_extract_jobs_from_unknown_ats_collection_key():
    data = {
        "payload": {
            "jobPostingPreviews": [
                {
                    "jobId": "62197",
                    "jobTitle": "Senior Data Engineer",
                    "companyName": "Acme",
                    "jobLocation": "Remote",
                    "salaryDisplay": "$140k-$180k",
                    "applyUrl": "https://example.com/jobs/62197",
                },
                {
                    "jobId": "62198",
                    "jobTitle": "Platform Engineer",
                    "companyName": "Acme",
                    "jobLocation": "Austin, TX",
                    "applyUrl": "https://example.com/jobs/62198",
                },
            ]
        }
    }

    records = extract_json_listing(data, "https://example.com/careers")

    assert len(records) == 2
    assert records[0]["title"] == "Senior Data Engineer"
    assert records[0]["job_id"] == "62197"
    assert records[0]["salary"] == "$140k-$180k"
    assert records[0]["apply_url"] == "https://example.com/jobs/62197"
    assert "sku" not in records[0]


def test_extract_json_listing_prefers_job_contract_over_generic_id_aliases():
    data = {
        "job_requisitions": [
            {
                "id": "REQ-77",
                "title": "Site Reliability Engineer",
                "company_name": "Example Corp",
                "location": "Remote",
                "url": "/jobs/req-77",
            }
        ]
    }

    records = extract_json_listing(data, "https://example.com/jobs")

    assert len(records) == 1
    assert records[0]["job_id"] == "REQ-77"
    assert records[0]["apply_url"] == "https://example.com/jobs/req-77"
    assert "sku" not in records[0]


def test_extract_json_listing_does_not_restore_fields_removed_by_job_contract():
    data = {
        "job_requisitions": [
            {
                "id": "REQ-77",
                "title": "Site Reliability Engineer",
                "company_name": "Example Corp",
                "location": "Remote",
                "url": "/jobs/req-77",
                "sku": "SKU-77",
                "brand": "Example Corp",
            }
        ]
    }

    records = extract_json_listing(data, "https://example.com/jobs")

    assert len(records) == 1
    assert records[0]["job_id"] == "REQ-77"
    assert "sku" not in records[0]
    assert "brand" not in records[0]