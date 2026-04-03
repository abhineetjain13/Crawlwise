# Shopify platform adapter.
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from app.services.adapters.base import AdapterResult, BaseAdapter

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


class ShopifyAdapter(BaseAdapter):
    name = "shopify"
    domains: list[str] = []  # any domain can be Shopify; detected by signals

    async def can_handle(self, url: str, html: str) -> bool:
        signals = [
            "Shopify.theme" in html,
            "cdn.shopify.com" in html,
            '"shopify"' in html.lower(),
            "myshopify.com" in url,
        ]
        return any(signals)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        records: list[dict] = []
        # Use endpoint data when it is specific to the requested page type.
        if surface in ("ecommerce_listing", "ecommerce_detail"):
            api_records = await self._try_products_json(url, surface)
            if api_records:
                records.extend(api_records)
        # Also try embedded JSON-LD (Shopify puts product data there)
        embedded = self._extract_embedded_product(html, url)
        if embedded:
            records.extend(embedded)
        return AdapterResult(
            records=records,
            source_type="shopify_adapter",
            confidence=0.95,
            adapter_name=self.name,
        )

    async def _try_products_json(self, url: str, surface: str) -> list[dict]:
        """Fetch Shopify product endpoint data.

        Listing pages use `/collections/<handle>/products.json` when possible so
        records stay scoped to the requested collection instead of the entire catalog.
        Detail pages use `/products/<handle>.js` to avoid returning unrelated products.
        """
        if curl_requests is None:
            return []
        parsed = urlparse(url)
        if surface == "ecommerce_detail":
            handle = self._extract_product_handle(parsed.path)
            if not handle:
                return []
            api_url = f"{parsed.scheme}://{parsed.netloc}/products/{handle}.js"
        else:
            collection_handle = self._extract_collection_handle(parsed.path)
            if collection_handle:
                api_url = (
                    f"{parsed.scheme}://{parsed.netloc}/collections/"
                    f"{collection_handle}/products.json?limit=250"
                )
            else:
                api_url = f"{parsed.scheme}://{parsed.netloc}/products.json?limit=250"
        try:
            resp = curl_requests.get(api_url, impersonate="chrome110", timeout=10)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

        products = [data] if surface == "ecommerce_detail" else data.get("products", [])
        records = []
        for p in products:
            variant = p.get("variants", [{}])[0] if p.get("variants") else {}
            images = [
                image_url
                for img in p.get("images", [])
                if (image_url := self._normalize_url(self._image_src(img), parsed.scheme))
            ]
            record = {
                "title": p.get("title"),
                "brand": p.get("vendor"),
                "description": p.get("body_html", ""),
                "url": urljoin(url, f"/products/{p.get('handle', '')}"),
                "image_url": images[0] if images else None,
                "image_urls": images,
                "price": self._normalize_price(variant.get("price")),
                "sku": variant.get("sku"),
                "availability": "in_stock" if variant.get("available") else "out_of_stock",
                "category": p.get("product_type"),
                "tags": p.get("tags", "").split(", ") if isinstance(p.get("tags"), str) else p.get("tags", []),
            }
            records.append(record)
        return records

    def _extract_product_handle(self, path: str) -> str | None:
        match = re.search(r"/products/([^/?#]+)", path)
        return match.group(1) if match else None

    def _extract_collection_handle(self, path: str) -> str | None:
        match = re.search(r"/collections/([^/?#]+)", path)
        return match.group(1) if match else None

    def _extract_embedded_product(self, html: str, url: str) -> list[dict]:
        """Extract product data from Shopify's embedded JSON in <script> tags."""
        records = []
        # Look for ShopifyAnalytics.meta or similar
        pattern = r'var\s+meta\s*=\s*(\{.*?\});'
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                meta = json.loads(match.group(1))
                product = meta.get("product", {})
                if product.get("title"):
                    records.append({
                        "title": product.get("title"),
                        "brand": product.get("vendor"),
                        "price": self._normalize_price(product.get("price")),
                        "category": product.get("type"),
                    })
            except (json.JSONDecodeError, TypeError):
                pass
        return records

    def _image_src(self, image: object) -> str | None:
        if isinstance(image, str):
            return image or None
        if isinstance(image, dict):
            return image.get("src") or image.get("url") or None
        return None

    def _normalize_url(self, value: str | None, scheme: str) -> str | None:
        if not value:
            return None
        if value.startswith("//"):
            return f"{scheme}:{value}"
        return value

    def _normalize_price(self, value: object) -> str | int | float | None:
        if isinstance(value, int):
            return f"{value / 100:.2f}"
        return value
