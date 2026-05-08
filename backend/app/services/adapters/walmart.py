# Walmart platform adapter.
from __future__ import annotations

import json
from json import loads as parse_json
from urllib.parse import urljoin, urlparse

from app.services.adapters.base import AdapterResult, BaseAdapter, adapter_host_matches
from bs4 import BeautifulSoup


class WalmartAdapter(BaseAdapter):
    name = "walmart"
    domains = ["walmart.com", "walmart.ca"]

    async def can_handle(self, url: str, html: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower()
        return any(adapter_host_matches(host, domain) for domain in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        soup = BeautifulSoup(html, "html.parser")
        records = []
        # Walmart embeds __NEXT_DATA__ with product info
        next_data = self._get_next_data(soup)
        if surface in ("ecommerce_detail",):
            record = self._extract_detail(soup, next_data, url)
            if record:
                records.append(record)
        elif surface in ("ecommerce_listing",):
            records = self._extract_listing(next_data, url)
        return self._result(records)

    def _get_next_data(self, soup: BeautifulSoup) -> dict:
        node = soup.select_one("script#__NEXT_DATA__")
        if node and node.string:
            try:
                return parse_json(node.string)
            except json.JSONDecodeError:
                pass
        return {}

    def _extract_detail(
        self, soup: BeautifulSoup, next_data: dict, url: str
    ) -> dict | None:
        # Try __NEXT_DATA__ first
        props = next_data.get("props", {}).get("pageProps", {})
        initial_data = props.get("initialData", {}).get("data", {})
        product = initial_data.get("product", {})
        if product:
            price_info = product.get("priceInfo", {}).get("currentPrice", {})
            raw_price = price_info.get("price")
            availability = str(product.get("availabilityStatus") or "").strip()
            category_path = product.get("category", {}).get("path") or [{}]
            return {
                "title": product.get("name"),
                "brand": product.get("brand"),
                "price": str(raw_price) if raw_price is not None else None,
                "image_url": product.get("imageInfo", {}).get("thumbnailUrl"),
                "description": product.get("shortDescription"),
                "rating": product.get("averageRating"),
                "review_count": product.get("numberOfReviews"),
                "availability": availability.lower().replace(" ", "_") or None,
                "category": category_path[-1].get("name") if category_path else None,
                "url": url,
            }
        # Fallback to DOM
        title_el = soup.select_one("[itemprop='name'], h1")
        price_el = soup.select_one(
            "[itemprop='price'], [data-automation-id='product-price'] span"
        )
        if title_el:
            return {
                "title": title_el.get_text(strip=True),
                "price": price_el.get_text(strip=True) if price_el else None,
                "url": url,
            }
        return None

    def _extract_listing(self, next_data: dict, url: str) -> list[dict]:
        records = []
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        # Try __NEXT_DATA__ search results
        props = next_data.get("props", {}).get("pageProps", {})
        initial_data = props.get("initialData", {}).get("searchResult", {})
        items = initial_data.get("itemStacks", [{}])
        for stack in items if isinstance(items, list) else [items]:
            for item in stack.get("items", []):
                if item.get("__typename") != "Product":
                    continue
                price_info = item.get("priceInfo", {}).get("currentPrice", {})
                raw_price = price_info.get("price")
                canonical_url = str(item.get("canonicalUrl") or "").strip()
                records.append(
                    {
                        "title": item.get("name"),
                        "price": str(raw_price) if raw_price is not None else None,
                        "image_url": item.get("imageInfo", {}).get("thumbnailUrl"),
                        "url": urljoin(base_url, canonical_url),
                        "rating": item.get("averageRating"),
                        "review_count": item.get("numberOfReviews"),
                    }
                )
        return records
