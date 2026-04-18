from __future__ import annotations

from app.services.js_state_mapper import map_js_state_to_fields
from app.services.network_payload_mapper import map_network_payloads_to_fields


def test_map_js_state_to_fields_recovers_next_data_shopify_product_fields() -> None:
    js_state_objects = {
        "__NEXT_DATA__": {
            "props": {
                "pageProps": {
                    "product": {
                        "id": 9001,
                        "title": "Trail Runner",
                        "vendor": "Acme Outdoors",
                        "handle": "trail-runner",
                        "body_html": "<p>Stable all-terrain shoe.</p>",
                        "product_type": "Shoes",
                        "currency": "USD",
                        "images": [
                            {"src": "https://cdn.example.com/products/trail-1.jpg"},
                            {"src": "https://cdn.example.com/products/trail-2.jpg"},
                        ],
                        "options": [{"name": "Color"}, {"name": "Size"}],
                        "variants": [
                            {
                                "id": 101,
                                "sku": "TRAIL-BLK-8",
                                "price": 9900,
                                "compare_at_price": 12900,
                                "available": True,
                                "inventory_quantity": 7,
                                "featured_image": {
                                    "src": "https://cdn.example.com/products/trail-black-8.jpg"
                                },
                                "option1": "Black",
                                "option2": "8",
                                "barcode": "1111111111111",
                            },
                            {
                                "id": 102,
                                "sku": "TRAIL-SND-9",
                                "price": 10900,
                                "compare_at_price": 13900,
                                "available": False,
                                "inventory_quantity": 0,
                                "featured_image": {
                                    "src": "https://cdn.example.com/products/trail-sand-9.jpg"
                                },
                                "option1": "Sand",
                                "option2": "9",
                                "barcode": "2222222222222",
                            },
                        ],
                    }
                }
            }
        }
    }

    mapped = map_js_state_to_fields(
        js_state_objects,
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/trail-runner?variant=102",
    )

    assert mapped["title"] == "Trail Runner"
    assert mapped["brand"] == "Acme Outdoors"
    assert mapped["vendor"] == "Acme Outdoors"
    assert mapped["handle"] == "trail-runner"
    assert mapped["description"] == "<p>Stable all-terrain shoe.</p>"
    assert mapped["product_id"] == 9001
    assert "category" not in mapped
    assert mapped["product_type"] == "Shoes"
    assert mapped["price"] == "109"
    assert mapped["original_price"] == "139"
    assert mapped["currency"] == "USD"
    assert mapped["availability"] == "out_of_stock"
    assert mapped["stock_quantity"] == 0
    assert mapped["sku"] == "TRAIL-SND-9"
    assert mapped["barcode"] == "2222222222222"
    assert mapped["color"] == "Sand"
    assert mapped["size"] == "9"
    assert mapped["image_url"] == "https://cdn.example.com/products/trail-sand-9.jpg"
    assert mapped["additional_images"] == [
        "https://cdn.example.com/products/trail-2.jpg"
    ]
    assert mapped["variant_count"] == 2
    assert mapped["available_sizes"] == ["8", "9"]
    assert mapped["option1_name"] == "color"
    assert mapped["option1_values"] == ["Black", "Sand"]
    assert mapped["option2_name"] == "size"
    assert mapped["option2_values"] == ["8", "9"]
    assert mapped["selected_variant"]["variant_id"] == "102"
    assert mapped["variants"][0]["variant_id"] == "101"
    assert mapped["variants"][1]["stock_quantity"] == 0
    assert (
        mapped["variants"][1]["url"]
        == "https://store.example.com/products/trail-runner?variant=102"
    )


def test_map_js_state_to_fields_recovers_existing_state_product_fields() -> None:
    js_state_objects = {
        "__INITIAL_STATE__": {
            "catalog": {
                "selected": {
                    "product": {
                        "id": "sku-123",
                        "name": "Commuter Backpack",
                        "vendor": {"name": "Urban Carry"},
                        "handle": "commuter-backpack",
                        "description": "Weather resistant pack",
                        "type": "Bags",
                        "price": "89.50",
                        "sku": "CB-001",
                        "availability": "In Stock",
                        "image": [
                            "/images/commuter-1.jpg",
                            "/images/commuter-2.jpg",
                        ],
                    }
                }
            }
        }
    }

    mapped = map_js_state_to_fields(
        js_state_objects,
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack",
    )

    assert mapped["title"] == "Commuter Backpack"
    assert mapped["brand"] == "Urban Carry"
    assert mapped["vendor"] == "Urban Carry"
    assert mapped["handle"] == "commuter-backpack"
    assert mapped["description"] == "Weather resistant pack"
    assert mapped["product_id"] == "sku-123"
    assert "category" not in mapped
    assert mapped["product_type"] == "Bags"
    assert mapped["price"] == "89.50"
    assert mapped["sku"] == "CB-001"
    assert mapped["availability"] == "in_stock"
    assert mapped["image_url"] == "https://store.example.com/images/commuter-1.jpg"
    assert mapped["additional_images"] == [
        "https://store.example.com/images/commuter-2.jpg"
    ]


def test_map_js_state_to_fields_replaces_existing_variant_query_parameter() -> None:
    mapped = map_js_state_to_fields(
        {
            "__INITIAL_STATE__": {
                "product": {
                    "name": "Commuter Backpack",
                    "variants": [
                        {
                            "id": "sku-123",
                            "available": True,
                        }
                    ],
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack?ref=hero&variant=old",
    )

    assert (
        mapped["variants"][0]["url"]
        == "https://store.example.com/products/commuter-backpack?ref=hero&variant=sku-123"
    )


def test_map_js_state_to_fields_keeps_ambiguous_availability_neutral() -> None:
    mapped = map_js_state_to_fields(
        {
            "__INITIAL_STATE__": {
                "product": {
                    "name": "Commuter Backpack",
                    "variants": [
                        {
                            "id": "sku-123",
                            "available": 2,
                        }
                    ],
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack",
    )

    assert "availability" not in mapped["variants"][0]


def test_job_detail_mappers_keep_shared_html_section_behavior() -> None:
    description_html = (
        "<p>Lead platform delivery.</p>"
        "<h2>What you'll do</h2><ul><li>Ship backend systems.</li></ul>"
        "<h2>You should have</h2><ul><li>Python experience.</li></ul>"
        "<h2>Benefits</h2><p>Remote-first.</p>"
        "<h3>Skills</h3><p>Clear writing.</p>"
    )

    js_mapped = map_js_state_to_fields(
        {
            "__remixContext": {
                "state": {
                    "loaderData": {
                        "routes/$url_token_.jobs_.$job_post_id": {
                            "jobPost": {
                                "title": "Platform Engineer",
                                "company_name": "Acme",
                                "job_post_location": "Remote",
                                "public_url": "https://jobs.example.com/platform-engineer",
                                "published_at": "2026-04-10",
                                "content": description_html,
                            }
                        }
                    }
                }
            }
        },
        surface="job_detail",
        page_url="https://jobs.example.com/platform-engineer",
    )
    network_rows = map_network_payloads_to_fields(
        [
            {
                "body": {
                    "title": "Platform Engineer",
                    "company_name": "Acme",
                    "location": {"name": "Remote"},
                    "absolute_url": "https://jobs.example.com/platform-engineer",
                    "first_published": "2026-04-10",
                    "updated_at": "2026-04-12",
                    "content": description_html,
                }
            }
        ],
        surface="job_detail",
        page_url="https://jobs.example.com/platform-engineer",
    )

    assert js_mapped["responsibilities"] == "Ship backend systems."
    assert js_mapped["qualifications"] == "Python experience."
    assert js_mapped["benefits"] == "Remote-first."
    assert js_mapped["skills"] == "Clear writing."
    assert js_mapped["description"] == (
        "Lead platform delivery. What you'll do Ship backend systems. "
        "You should have Python experience. Benefits Remote-first. "
        "Skills Clear writing."
    )
    assert network_rows == [
        {
            "title": "Platform Engineer",
            "company": "Acme",
            "location": "Remote",
            "apply_url": "https://jobs.example.com/platform-engineer",
            "posted_date": "2026-04-10",
            "updated_at": "2026-04-12",
            "responsibilities": "Ship backend systems.",
            "qualifications": "Python experience.",
            "benefits": "Remote-first.",
            "skills": "Clear writing.",
            "description": js_mapped["description"],
            "url": "https://jobs.example.com/platform-engineer",
        }
    ]
