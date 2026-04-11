from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.adapters.base import AdapterResult
from tests.support import manifest as _sources


def html_page(*fragments: str) -> str:
    return "<html><body>" + "".join(fragments) + "</body></html>"


def job_card(
    *,
    href: str,
    title: str,
    company: str | None = None,
    location: str | None = None,
    salary: str | None = None,
) -> str:
    parts = [
        '<div class="job-card">',
        f'<a href="{href}">',
        f"<h3>{title}</h3>",
    ]
    if company is not None:
        parts.append(f'<div class="company">{company}</div>')
    if location is not None:
        parts.append(f'<div class="location">{location}</div>')
    if salary is not None:
        parts.append(f'<div class="salary">{salary}</div>')
    parts.append("</a></div>")
    return "".join(parts)


def product_card(
    *,
    href: str,
    title: str | None = None,
    price: str | int | None = None,
    image_src: str | None = None,
    image_alt: str | None = None,
) -> str:
    parts = ['<div class="product-card">', f'<a href="{href}">']
    if image_src is not None:
        alt_text = image_alt if image_alt is not None else (title or "")
        parts.append(f'<img src="{image_src}" alt="{alt_text}" />')
    if title is not None:
        parts.append(f"<h3>{title}</h3>")
    parts.append("</a>")
    if price is not None:
        parts.append(f'<span class="price">{price}</span>')
    parts.append("</div>")
    return "".join(parts)


def food_processor_listing_html() -> str:
    cards = [
        {
            "title": "13-Cup Food Processor",
            "href": "/countertop-appliances/food-processors/processors/p.one.html",
            "image_src": "https://images.example.com/one.jpg",
            "price": 179.99,
        },
        {
            "title": "9-Cup Food Processor Plus",
            "href": "/countertop-appliances/food-processors/processors/p.two.html",
            "image_src": "https://images.example.com/two.jpg",
            "price": 149.99,
        },
    ]
    return html_page(
        *(
            product_card(
                href=card["href"],
                title=card["title"],
                price=f'${card["price"]:.2f}',
                image_src=card["image_src"],
            )
            for card in cards
        )
    )


def query_state_manifest(items: Sequence[dict[str, Any]], *, query_key: Sequence[str] = ("KA_CUSTOM_PRODUCT_LISTING",)) -> dict:
    return _sources(
        json_ld=[],
        next_data={
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "queryKey": list(query_key),
                                "state": {
                                    "data": {
                                        "items": [dict(item) for item in items],
                                    }
                                },
                            }
                        ]
                    }
                }
            }
        },
        _hydrated_states=[],
        network_payloads=[],
    )


def adapter_result(adapter_name: str, records: Sequence[dict[str, Any]]) -> AdapterResult:
    return AdapterResult(adapter_name=adapter_name, records=[dict(record) for record in records])


def adapter_manifest(records: Sequence[dict[str, Any]]) -> dict:
    return _sources(adapter_data=[dict(record) for record in records])


def item_list_manifest(items: Sequence[dict[str, Any]]) -> dict:
    return _sources(
        json_ld=[
            {
                "@type": "ItemList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "item": dict(item),
                    }
                    for item in items
                ],
            }
        ]
    )


def next_data_manifest(items: Sequence[dict[str, Any]]) -> dict:
    return _sources(
        next_data={
            "props": {
                "pageProps": {
                    "dehydratedState": {
                        "queries": [
                            {
                                "state": {
                                    "data": {
                                        "items": [dict(item) for item in items],
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
    )
