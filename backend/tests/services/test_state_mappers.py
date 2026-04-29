from __future__ import annotations

from app.services import js_state_mapper
from app.services.js_state_mapper import map_configured_state_payload, map_js_state_to_fields
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


def test_map_js_state_to_fields_uses_variation_attribute_display_names() -> None:
    mapped = map_js_state_to_fields(
        {
            "mobify-data": {
                "product": {
                    "id": "2078471",
                    "name": "Terminal Roamer Pants",
                    "brand": "Columbia",
                    "currency": "USD",
                    "price": 60,
                    "variationAttributes": [
                        {
                            "id": "color",
                            "name": "Color",
                            "values": [
                                {"value": "019", "name": "Cool Grey"},
                                {"value": "023", "name": "City Grey"},
                            ],
                        },
                        {
                            "id": "size",
                            "name": "Size",
                            "values": [
                                {"value": "S", "name": "S"},
                                {"value": "M", "name": "M"},
                            ],
                        },
                    ],
                    "variants": [
                        {
                            "id": "195980349741",
                            "sku": "195980349741",
                            "variationValues": {"color": "019", "size": "S"},
                        },
                        {
                            "id": "195980349888",
                            "sku": "195980349888",
                            "variationValues": {"color": "023", "size": "M"},
                        },
                    ],
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://www.columbia.com/p/mens-pfg-terminal-roamer-stretch-pants-2078471.html?color=019&size=S",
    )

    assert mapped["color"] == "Cool Grey"
    assert mapped["variant_axes"]["color"] == ["Cool Grey", "City Grey"]
    assert mapped["selected_variant"]["option_values"] == {
        "color": "Cool Grey",
        "size": "S",
    }


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


def test_map_js_state_to_fields_ignores_header_payment_state_before_real_product() -> None:
    js_state_objects = {
        "__INITIAL_STATE__": {
            "header": {
                "paymentMethods": {
                    "title": "We accept",
                    "images": [
                        {"src": "https://cdn.example.com/assets/amex.svg"},
                        {"src": "https://cdn.example.com/assets/paypal.svg"},
                    ],
                }
            },
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
            },
        }
    }

    mapped = map_js_state_to_fields(
        js_state_objects,
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack",
    )

    assert mapped["title"] == "Commuter Backpack"
    assert mapped["image_url"] == "https://store.example.com/images/commuter-1.jpg"
    assert mapped["additional_images"] == [
        "https://store.example.com/images/commuter-2.jpg"
    ]


def test_map_js_state_to_fields_does_not_merge_variants_from_different_product_identity() -> None:
    js_state_objects = {
        "__INITIAL_STATE__": {
            "catalog": {
                "selected": {
                    "product": {
                        "id": "sku-123",
                        "name": "Commuter Backpack",
                        "handle": "commuter-backpack",
                        "price": "89.50",
                    }
                }
            }
        },
        "__NEXT_DATA__": {
            "props": {
                "pageProps": {
                    "product": {
                        "id": "sku-999",
                        "title": "Trail Runner",
                        "handle": "trail-runner",
                        "variants": [
                            {"id": 101, "price": 9900, "option1": "Black"},
                            {"id": 102, "price": 10900, "option1": "Sand"},
                        ],
                    }
                }
            }
        },
    }

    mapped = map_js_state_to_fields(
        js_state_objects,
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/commuter-backpack",
    )

    assert mapped["product_id"] == "sku-123"
    assert mapped.get("variants") in (None, [])


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


def test_map_js_state_to_fields_prefers_richer_nested_product_payload_for_variant_recovery() -> None:
    mapped = map_js_state_to_fields(
        {
            "__INITIAL_STATE__": {
                "navigation": {
                    "landing": {
                        "title": "iPhone",
                        "id": "landing-node",
                        "url": "/en-us/l/iphone/landing-node",
                    }
                },
                "pdp": {
                    "product": {
                        "id": "phone-14-128",
                        "name": "iPhone 14",
                        "brand": {"name": "Apple"},
                        "description": "Refurbished iPhone 14 with warranty.",
                        "price": "399.00",
                        "currency": "USD",
                        "image": [
                            "https://cdn.example.com/iphone-14-front.jpg",
                            "https://cdn.example.com/iphone-14-back.jpg",
                        ],
                        "variants": [
                            {
                                "id": "good-128",
                                "storage": "128 GB",
                                "condition": "Good",
                                "price": "399.00",
                                "currency": "USD",
                                "availability": "In Stock",
                            },
                            {
                                "id": "excellent-128",
                                "storage": "128 GB",
                                "condition": "Excellent",
                                "price": "459.00",
                                "currency": "USD",
                                "availability": "In Stock",
                            },
                        ],
                    }
                },
            }
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/iphone-14?variant=excellent-128",
    )

    assert mapped["title"] == "iPhone 14"
    assert mapped["brand"] == "Apple"
    assert mapped["price"] == "459.00"
    assert mapped["image_url"] == "https://cdn.example.com/iphone-14-front.jpg"
    assert mapped["additional_images"] == ["https://cdn.example.com/iphone-14-back.jpg"]
    assert mapped["variant_axes"] == {"condition": ["Good", "Excellent"]}
    assert mapped["variant_count"] == 2
    assert mapped["selected_variant"]["variant_id"] == "excellent-128"
    assert mapped["selected_variant"]["option_values"] == {
        "storage": "128 GB",
        "condition": "Excellent",
    }


def test_map_js_state_to_fields_backfills_richer_variant_state_from_later_same_product_object() -> None:
    mapped = map_js_state_to_fields(
        {
            "__STATE_A__": {
                "product": {
                    "id": "prod-1",
                    "name": "Dress",
                    "price": "99.95",
                    "currency": "USD",
                    "variants": [
                        {
                            "id": "v1",
                            "size": "2",
                            "price": "99.95",
                            "available": False,
                        },
                        {
                            "id": "v2",
                            "size": "4",
                            "price": "99.95",
                            "available": False,
                        },
                    ],
                }
            },
            "__STATE_B__": {
                "product": {
                    "id": "prod-1",
                    "name": "Dress",
                    "variants": [
                        {
                            "id": "v1",
                            "size": "2",
                            "price": "99.95",
                            "available": True,
                            "inventory_quantity": 5,
                            "compare_at_price": "119.95",
                        },
                        {
                            "id": "v2",
                            "size": "4",
                            "price": "99.95",
                            "available": True,
                            "inventory_quantity": 6,
                            "compare_at_price": "119.95",
                        },
                    ],
                }
            },
        },
        surface="ecommerce_detail",
        page_url="https://example.com/p/dress?variant=v1",
    )

    assert mapped["availability"] == "in_stock"
    assert mapped["stock_quantity"] == 5
    assert mapped["original_price"] == "119.95"
    assert mapped["selected_variant"]["variant_id"] == "v1"
    assert mapped["selected_variant"]["availability"] == "in_stock"
    assert mapped["selected_variant"]["stock_quantity"] == 5
    assert mapped["selected_variant"]["original_price"] == "119.95"
    assert mapped["variants"][0]["availability"] == "in_stock"
    assert mapped["variants"][0]["stock_quantity"] == 5
    assert mapped["variants"][0]["original_price"] == "119.95"
    assert mapped["variants"][1]["availability"] == "in_stock"
    assert mapped["variants"][1]["stock_quantity"] == 6


def test_map_js_state_to_fields_prefers_preloaded_state_product_over_app_banner_payload() -> None:
    mapped = map_js_state_to_fields(
        {
            "__PRELOADED_STATE__": {
                "appBanner": {
                    "name": "UNIQLO - LifeWear",
                    "title": "UNIQLO - LifeWear",
                    "description": "Shop on our app for the best experience",
                    "buttonText": "Open app",
                    "buttonLink": "/app",
                    "appIcon": "https://cdn.example.com/assets/app-icon.png",
                },
                "entity": {
                    "pdpEntity": {
                        "E474244-000-01": {
                            "product": {
                                "name": "AIRism Cotton Crew Neck T-Shirt",
                                "productId": "E474244-000",
                                "productType": "innerwear",
                                "prices": {
                                    "base": {"currency": {"code": "INR"}, "value": 990},
                                    "promo": {"currency": {"code": "INR"}, "value": 390},
                                },
                                "colors": [
                                    {"name": "OLIVE"},
                                    {"name": "BLACK"},
                                ],
                                "sizes": [
                                    {"name": "S"},
                                    {"name": "M"},
                                    {"name": "L"},
                                ],
                                "images": {
                                    "main": {
                                        "57": {
                                            "image": "https://cdn.example.com/products/airism-olive-main.jpg"
                                        }
                                    },
                                    "sub": [
                                        {
                                            "image": "https://cdn.example.com/products/airism-detail-1.jpg"
                                        },
                                        {
                                            "image": "https://cdn.example.com/products/airism-detail-2.jpg"
                                        },
                                    ],
                                },
                            }
                        }
                    }
                },
            }
        },
        surface="ecommerce_detail",
        page_url="https://www.uniqlo.com/in/en/products/E474244-000/01",
    )

    assert mapped["title"] == "AIRism Cotton Crew Neck T-Shirt"
    assert mapped["product_id"] == "E474244-000"
    assert mapped["product_type"] == "innerwear"
    assert mapped["price"] == "390"
    assert mapped["original_price"] == "990"
    assert mapped["currency"] == "INR"
    assert mapped["image_url"] == "https://cdn.example.com/products/airism-olive-main.jpg"
    assert mapped["additional_images"] == [
        "https://cdn.example.com/products/airism-detail-1.jpg",
        "https://cdn.example.com/products/airism-detail-2.jpg",
    ]


def test_map_js_state_to_fields_recovers_direct_grade_and_storage_axes_from_variants() -> None:
    mapped = map_js_state_to_fields(
        {
            "__INITIAL_STATE__": {
                "product": {
                    "id": "console-1tb",
                    "name": "Game Console",
                    "variants": [
                        {
                            "id": "fair-512",
                            "grade": "Fair",
                            "storage": "512 GB",
                            "price": "249.00",
                            "currency": "USD",
                        },
                        {
                            "id": "good-1tb",
                            "grade": "Good",
                            "storage": "1 TB",
                            "price": "299.00",
                            "currency": "USD",
                        },
                    ],
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/game-console?variant=good-1tb",
    )

    assert mapped["title"] == "Game Console"
    assert mapped["price"] == "299.00"
    assert mapped["variant_axes"] == {
        "grade": ["Fair", "Good"],
        "storage": ["512 GB", "1 TB"],
    }
    assert mapped["variant_count"] == 2
    assert mapped["selected_variant"]["option_values"] == {
        "grade": "Good",
        "storage": "1 TB",
    }


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


def test_configured_state_payload_merges_later_root_fields() -> None:
    mapped = map_configured_state_payload(
        {
            "first": {"title": "Platform Engineer"},
            "second": {"company_name": "Acme"},
        },
        root_paths=[["first"], ["second"]],
        field_paths={
            "title": [["title"]],
            "company": [["company_name"]],
        },
    )

    assert mapped == {"title": "Platform Engineer", "company": "Acme"}


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


def test_map_product_payload_uses_configured_jmespaths_when_glom_fails(
    monkeypatch,
) -> None:
    original_glom = js_state_mapper.glom

    def _fake_glom(target, spec, default=None):
        if spec is js_state_mapper.PRODUCT_FIELD_SPEC:
            raise RuntimeError("boom")
        return original_glom(target, spec, default=default)

    monkeypatch.setattr(js_state_mapper, "glom", _fake_glom)

    mapped = js_state_mapper._map_product_payload(
        {
            "name": "Config Mapped Pack",
            "vendor": {"name": "Urban Carry"},
            "price": "89.50",
            "variants": [],
        },
        page_url="https://store.example.com/products/config-mapped-pack",
        category_fallback_from_type=False,
        field_jmespaths={
            "title": ["title", "name"],
            "brand": ["brand.name", "brand", "vendor.name", "vendor"],
            "price": ["price"],
        },
    )

    assert mapped == {
        "title": "Config Mapped Pack",
        "brand": "Urban Carry",
        "price": "89.50",
    }


def test_map_product_payload_normalizes_raw_price_fallbacks() -> None:
    mapped = js_state_mapper._map_product_payload(
        {
            "id": "prod-1",
            "variants": [],
            "prices": {
                "currentPrice": "$129.50",
                "initialPrice": {"value": 149},
            },
        },
        page_url="https://store.example.com/products/commuter-backpack",
        category_fallback_from_type=False,
    )

    assert mapped["price"] == "129.50"
    assert mapped["original_price"] == "149"


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


def test_normalize_variant_does_not_use_product_id_as_variant_id() -> None:
    mapped = js_state_mapper._normalize_variant(
        {"productId": "prod-1"},
        option_names=[],
        page_url="https://store.example.com/products/commuter-backpack",
        interpret_integral_as_cents=False,
    )

    assert mapped == {"sku": "prod-1"}


def test_map_js_state_to_fields_uses_selected_options_and_skips_marketing_axis_names() -> None:
    mapped = map_js_state_to_fields(
        {
            "__NEXT_DATA__": {
                "props": {
                    "pageProps": {
                        "product": {
                            "id": "leggings-1",
                            "title": "Everyday Seamless Leggings",
                            "vendor": "Gym Co",
                            "price": "58.00",
                            "currency": "USD",
                            "options": [
                                {"name": "Soft Fabric"},
                                {"name": "High Waisted"},
                            ],
                            "variants": [
                                {
                                    "id": "black-s",
                                    "available": True,
                                    "selectedOptions": [
                                        {"name": "Color", "value": "Black"},
                                        {"name": "Size", "value": "S"},
                                    ],
                                },
                                {
                                    "id": "black-m",
                                    "available": True,
                                    "selectedOptions": [
                                        {"name": "Color", "value": "Black"},
                                        {"name": "Size", "value": "M"},
                                    ],
                                },
                            ],
                        }
                    }
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/everyday-seamless-leggings?variant=black-s",
    )

    assert mapped["variant_axes"] == {"size": ["S", "M"]}
    assert mapped["selected_variant"]["option_values"] == {
        "color": "Black",
        "size": "S",
    }
    assert mapped["selected_variant"]["price"] == "58.00"
    assert "soft_fabric" not in mapped["variant_axes"]
    assert "high_waisted" not in mapped["variant_axes"]


def test_map_js_state_to_fields_reads_nested_variant_price_objects() -> None:
    mapped = map_js_state_to_fields(
        {
            "__NEXT_DATA__": {
                "props": {
                    "pageProps": {
                        "product": {
                            "id": "runner-1",
                            "title": "Tree Runner",
                            "vendor": "Allbirds",
                            "price": {"amount": "100.00", "currencyCode": "USD"},
                            "options": [
                                {"name": "Color"},
                                {"name": "Size"},
                            ],
                            "variants": [
                                {
                                    "id": "jet-black-8",
                                    "available": True,
                                    "price": {"amount": "100.00", "currencyCode": "USD"},
                                    "selectedOptions": [
                                        {"name": "Color", "value": "Jet Black"},
                                        {"name": "Size", "value": "8"},
                                    ],
                                },
                                {
                                    "id": "jet-black-9",
                                    "available": True,
                                    "priceV2": {"amount": "100.00", "currencyCode": "USD"},
                                    "selectedOptions": [
                                        {"name": "Color", "value": "Jet Black"},
                                        {"name": "Size", "value": "9"},
                                    ],
                                },
                            ],
                        }
                    }
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/tree-runner?variant=jet-black-8",
    )

    assert mapped["price"] == "100.00"
    assert mapped["selected_variant"]["price"] == "100.00"
    assert mapped["selected_variant"]["currency"] == "USD"
    assert mapped["variants"][0]["price"] == "100.00"
    assert mapped["variants"][1]["price"] == "100.00"


def test_map_js_state_to_fields_reads_nested_variant_original_price_objects() -> None:
    mapped = map_js_state_to_fields(
        {
            "__NEXT_DATA__": {
                "props": {
                    "pageProps": {
                        "product": {
                            "id": "runner-1",
                            "title": "Tree Runner",
                            "options": [{"name": "Size"}],
                            "variants": [
                                {
                                    "id": "runner-8",
                                    "compare_at_price": {"amount": "120.00", "currencyCode": "USD"},
                                    "selectedOptions": [{"name": "Size", "value": "8"}],
                                },
                                {
                                    "id": "runner-9",
                                    "compareAtPrice": {"amount": "130.00", "currencyCode": "USD"},
                                    "selectedOptions": [{"name": "Size", "value": "9"}],
                                },
                            ],
                        }
                    }
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/tree-runner?variant=runner-9",
    )

    assert mapped["selected_variant"]["original_price"] == "130.00"
    assert mapped["variants"][0]["original_price"] == "120.00"
    assert mapped["variants"][1]["original_price"] == "130.00"


def test_map_js_state_to_fields_reads_current_price_style_product_fields() -> None:
    mapped = map_js_state_to_fields(
        {
            "__NEXT_DATA__": {
                "props": {
                    "pageProps": {
                        "product": {
                            "id": "af1-1",
                            "title": "Air Force 1",
                            "brand": "Nike",
                            "prices": {
                                "currency": "USD",
                                "currentPrice": 115,
                                "initialPrice": 130,
                            },
                            "options": [{"name": "Size"}],
                            "variants": [
                                {
                                    "id": "size-6",
                                    "available": True,
                                    "selectedOptions": [{"name": "Size", "value": "6"}],
                                },
                                {
                                    "id": "size-7",
                                    "available": False,
                                    "selectedOptions": [{"name": "Size", "value": "7"}],
                                },
                            ],
                        }
                    }
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://store.example.com/products/air-force-1?variant=size-6",
    )

    assert mapped["price"] == "USD 115"
    assert mapped["original_price"] == "USD 130"
    assert mapped["currency"] == "USD"
    assert mapped["selected_variant"]["price"] == "USD 115"
