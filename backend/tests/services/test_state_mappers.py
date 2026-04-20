from __future__ import annotations

from app.services import js_state_mapper
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


def test_map_network_payloads_to_fields_recovers_workday_job_detail_payload() -> None:
    mapped = map_network_payloads_to_fields(
        [
            {
                "url": "https://example.wd5.myworkdayjobs.com/wday/cxs/acme/External/job/123",
                "endpoint_type": "job_api",
                "endpoint_family": "workday",
                "body": {
                    "jobPostingInfo": {
                        "title": "Assembler",
                        "jobDescription": "<p>Build things.</p>",
                        "location": "Grafton, WI",
                        "postedOn": "Posted Today",
                        "timeType": "Full time",
                        "jobReqId": "REQ-100",
                        "externalUrl": "https://example.wd5.myworkdayjobs.com/en-US/External/job/123",
                    },
                    "hiringOrganization": {"name": "Acme Manufacturing"},
                },
            }
        ],
        surface="job_detail",
        page_url="https://example.wd5.myworkdayjobs.com/en-US/External/job/123",
    )

    assert mapped == [
        {
            "title": "Assembler",
            "company": "Acme Manufacturing",
            "location": "Grafton, WI",
            "apply_url": "https://example.wd5.myworkdayjobs.com/en-US/External/job/123",
            "url": "https://example.wd5.myworkdayjobs.com/en-US/External/job/123",
            "posted_date": "Posted Today",
            "job_type": "Full time",
            "job_id": "REQ-100",
            "description": "Build things.",
        }
    ]


def test_map_js_state_to_fields_recovers_generic_nextjs_product_payload_without_schema_bleed() -> None:
    mapped = map_js_state_to_fields(
        {
            "__NEXT_DATA__": {
                "props": {
                    "pageProps": {
                        "initialData": {
                            "product": {
                                "id": "prod_42",
                                "name": "Commuter Backpack",
                                "vendor": "Urban Carry",
                                "handle": "commuter-backpack",
                                "description": "Weather resistant pack",
                                "category": "Travel Gear",
                                "type": "Backpacks",
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
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack",
    )

    assert mapped["title"] == "Commuter Backpack"
    assert mapped["category"] == "Travel Gear"
    assert mapped["product_type"] == "Backpacks"
    assert mapped["sku"] == "CB-001"
    assert mapped["image_url"] == "https://store.example.com/images/commuter-1.jpg"


def test_map_js_state_to_fields_recovers_nuxt_array_payload_variant() -> None:
    mapped = map_js_state_to_fields(
        {
            "__NUXT_DATA__": [
                {
                    "data": {
                        "product": {
                            "id": "sku-123",
                            "name": "Commuter Backpack",
                            "vendor": {"name": "Urban Carry"},
                            "handle": "commuter-backpack",
                            "description": "Weather resistant pack",
                            "category": "Travel Gear",
                            "product_type": "Backpacks",
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
            ]
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack",
    )

    assert mapped["title"] == "Commuter Backpack"
    assert mapped["category"] == "Travel Gear"
    assert mapped["product_type"] == "Backpacks"
    assert mapped["availability"] == "in_stock"
    assert mapped["image_url"] == "https://store.example.com/images/commuter-1.jpg"


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


def test_map_js_state_to_fields_uses_platform_owned_job_detail_selector_config() -> None:
    mapped = map_js_state_to_fields(
        {
            "__remixContext": {
                "state": {
                    "loaderData": {
                        "routes/$url_token_.jobs_.$job_post_id": {
                            "jobPost": {
                                "title": "Manager, Engineering",
                                "company_name": "Greenhouse",
                                "job_post_location": "Ontario",
                                "public_url": "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699",
                                "published_at": "2026-04-09T10:05:53-04:00",
                                "content": (
                                    "<p>Lead the reporting and analytics engineering domain.</p>"
                                    "<h2>What you’ll do</h2><ul><li>Lead and mentor engineers.</li></ul>"
                                    "<h2>You should have</h2><ul><li>5+ years of engineering experience.</li></ul>"
                                ),
                            }
                        }
                    }
                }
            }
        },
        surface="job_detail",
        page_url="https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699",
    )

    assert mapped["title"] == "Manager, Engineering"
    assert mapped["company"] == "Greenhouse"
    assert mapped["location"] == "Ontario"
    assert (
        mapped["apply_url"]
        == "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699"
    )
    assert mapped["posted_date"] == "2026-04-09T10:05:53-04:00"
    assert "Lead and mentor engineers." in mapped["responsibilities"]
    assert "5+ years of engineering experience." in mapped["qualifications"]
    assert (
        mapped["url"]
        == "https://job-boards.greenhouse.io/greenhouse/jobs/7704699?gh_jid=7704699"
    )


def test_map_js_state_to_fields_rejects_dict_tags_from_promotional_ui() -> None:
    js_state_objects = {
        "__NEXT_DATA__": {
            "props": {
                "pageProps": {
                    "product": {
                        "id": 9002,
                        "title": "Maternity Jean",
                        "vendor": "Hatch",
                        "handle": "the-relaxed-wide-leg-maternity-jean-1",
                        "body_html": "<p>Comfortable maternity denim.</p>",
                        "product_type": "Jeans",
                        "currency": "USD",
                        "tags": {
                            "button": "Add",
                            "freeGiftHint": "Free gift",
                            "freeGiftWarning": "Add gift to cart to proceed to checkout",
                            "goalReached": "Congrats - all tiers unlocked!",
                            "rewardName1": "20% off",
                            "rewardName2": "25% off",
                            "rewardName3": "30% off",
                        },
                        "variants": [
                            {
                                "id": 201,
                                "sku": "HJ-BLU-28",
                                "price": 19800,
                                "compare_at_price": 24800,
                                "available": True,
                                "option1": "Blue",
                                "option2": "28",
                            }
                        ],
                        "options": [{"name": "Color"}, {"name": "Size"}],
                        "images": [
                            {"src": "https://cdn.example.com/jean-1.jpg"},
                        ],
                    }
                }
            }
        }
    }
    mapped = map_js_state_to_fields(
        js_state_objects,
        surface="ecommerce_detail",
        page_url="https://www.hatchcollection.com/products/the-relaxed-wide-leg-maternity-jean-1",
    )
    assert mapped.get("title") == "Maternity Jean"
    assert mapped.get("tags") is None


def test_map_product_payload_tolerates_product_glom_failures(
    monkeypatch,
) -> None:
    original_glom = js_state_mapper.glom

    def _fake_glom(target, spec, default=None):
        if spec is js_state_mapper.PRODUCT_FIELD_SPEC:
            raise RuntimeError("boom")
        return original_glom(target, spec, default=default)

    monkeypatch.setattr(js_state_mapper, "glom", _fake_glom)

    mapped = js_state_mapper._map_product_payload(
        {"id": "prod-1", "variants": []},
        page_url="https://store.example.com/products/commuter-backpack",
        category_fallback_from_type=False,
    )

    assert mapped == {}


def test_normalize_variant_tolerates_non_dict_glom_result(
    monkeypatch,
) -> None:
    original_glom = js_state_mapper.glom

    def _fake_glom(target, spec, default=None):
        if spec is js_state_mapper._VARIANT_FIELD_SPEC:
            return None
        return original_glom(target, spec, default=default)

    monkeypatch.setattr(js_state_mapper, "glom", _fake_glom)

    mapped = js_state_mapper._normalize_variant(
        {"id": "sku-123"},
        option_names=[],
        page_url="https://store.example.com/products/commuter-backpack",
        interpret_integral_as_cents=False,
    )

    assert mapped == {
        "variant_id": "sku-123",
        "url": "https://store.example.com/products/commuter-backpack?variant=sku-123",
    }
