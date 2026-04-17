from __future__ import annotations

from app.services.discover.network_inventory import collect_network_payload_candidates
from app.services.discover.state_inventory import (
    discover_listing_items,
    map_state_fields,
)


def test_map_state_fields_uses_glom_spec_for_ecommerce_detail():
    payload = {
        "props": {
            "pageProps": {
                "product": {
                    "name": "Spec Mapped Widget",
                    "vendor": "Acme",
                    "priceRange": {
                        "minVariantPrice": {
                            "amount": "19.99",
                            "currencyCode": "USD",
                        }
                    },
                }
            }
        }
    }

    mapped = map_state_fields(payload, surface="ecommerce_detail")

    assert mapped == {
        "title": "Spec Mapped Widget",
        "brand": "Acme",
        "price": "19.99",
        "currency": "USD",
    }


def test_discover_listing_items_prefers_declared_glom_collection_paths():
    payload = {
        "props": {
            "pageProps": {
                "initialState": {
                    "search": {
                        "results": {
                            "products": [
                                {"title": "Deep Product A", "url": "/p/a"},
                                {"title": "Deep Product B", "url": "/p/b"},
                            ]
                        }
                    }
                }
            }
        }
    }

    items = discover_listing_items(
        payload,
        surface="ecommerce_listing",
        max_depth=8,
    )

    assert [item["title"] for item in items] == ["Deep Product A", "Deep Product B"]


def test_collect_network_payload_candidates_uses_jmespath_specs_for_saashr():
    rows = collect_network_payload_candidates(
        "title",
        payloads=[
            {
                "url": "https://secure7.saashr.com/ta/rest/ui/recruitment/companies/1/job-requisitions/2",
                "body": {
                    "job_title": "Case Manager",
                    "job_description": "<p>Community-based case management.</p>",
                },
            }
        ],
        surface="job_detail",
        page_url="https://secure7.saashr.com/ta/1.careers?ShowJob=2",
    )

    assert rows == [
        {
            "value": "Case Manager",
            "source": "saashr_detail",
            "payload_url": "https://secure7.saashr.com/ta/rest/ui/recruitment/companies/1/job-requisitions/2",
        }
    ]

