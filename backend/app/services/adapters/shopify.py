# Shopify platform adapter.
from __future__ import annotations

import json
import re
from json import loads as parse_json
from urllib.parse import parse_qsl, urljoin, urlparse, urlsplit

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.acquisition.http_client import requests as curl_requests
from app.services.config.adapter_runtime_settings import (
    SHOPIFY_CATALOG_LIMIT,
    SHOPIFY_MAX_OPTION_AXIS_COUNT,
    SHOPIFY_REQUEST_TIMEOUT_SECONDS,
)
from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key,
    split_variant_axes,
)
from app.services.normalizers import normalize_decimal_price

_FETCH_ERRORS = (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError)


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
        embedded = self._extract_embedded_product(html, url)
        if embedded:
            records.extend(embedded)
        # Listing pages are usually best served by the public collection endpoint.
        # Detail pages can often be satisfied from embedded Shopify JSON without a network round-trip.
        if surface in ("ecommerce_listing", "ecommerce_detail") and (surface == "ecommerce_listing" or not records):
            api_records = await self.try_public_endpoint(
                url,
                html=html,
                surface=surface,
            )
            if api_records:
                records.extend(api_records)
        return AdapterResult(
            records=records,
            source_type="shopify_adapter",
            adapter_name=self.name,
        )

    async def try_public_endpoint(
        self,
        url: str,
        html: str = "",
        surface: str = "",
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        """Fetch Shopify product endpoint data.

        Listing pages use `/collections/<handle>/products.json` when possible so
        records stay scoped to the requested collection instead of the entire catalog.
        Detail pages use `/products/<handle>.js` to avoid returning unrelated products.
        """
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
                    f"{collection_handle}/products.json?limit={SHOPIFY_CATALOG_LIMIT}"
                )
            else:
                api_url = (
                    f"{parsed.scheme}://{parsed.netloc}/products.json"
                    f"?limit={SHOPIFY_CATALOG_LIMIT}"
                )
        try:
            data = await self._request_json_with_curl(
                curl_requests.get,
                api_url,
                proxy=proxy,
                timeout_seconds=SHOPIFY_REQUEST_TIMEOUT_SECONDS,
            )
            if data is None:
                return []
        except _FETCH_ERRORS:
            return []

        products = [data] if surface == "ecommerce_detail" else data.get("products", [])
        records = []
        for p in products:
            variants = p.get("variants", []) if isinstance(p.get("variants"), list) else []
            option_names = self._option_names(p.get("options"))
            normalized_variants = [
                normalized
                for variant in variants
                if isinstance(variant, dict)
                if (normalized := self._normalize_variant(
                    variant,
                    option_names=option_names,
                    scheme=parsed.scheme,
                    base_url=urljoin(url, f"/products/{p.get('handle', '')}"),
                ))
            ]
            normalized_variants = self._dedupe_variants(normalized_variants)
            selected_variant = self._select_shopify_variant(
                normalized_variants,
                base_url=url,
            )
            axes = self._variant_axes(normalized_variants)
            selectable_axes, single_value_attributes = self._split_selectable_axes(
                axes
            )
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
                "additional_images": ", ".join(images[1:]) if len(images) > 1 else None,
                "price": selected_variant.get("price") if isinstance(selected_variant, dict) else None,
                "original_price": selected_variant.get("original_price") if isinstance(selected_variant, dict) else None,
                "sku": selected_variant.get("sku") if isinstance(selected_variant, dict) else None,
                "availability": selected_variant.get("availability") if isinstance(selected_variant, dict) else None,
                "category": p.get("product_type"),
                "tags": p.get("tags", "").split(", ") if isinstance(p.get("tags"), str) else p.get("tags", []),
                "variants": normalized_variants,
                "variant_axes": selectable_axes,
                "selected_variant": selected_variant,
                "product_attributes": single_value_attributes or None,
            }
            if isinstance(selected_variant, dict):
                for field_name in ("color", "size"):
                    if selected_variant.get(field_name):
                        record[field_name] = selected_variant[field_name]
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
                meta = parse_json(match.group(1))
                product = meta.get("product", {})
                if product.get("title"):
                    option_names = self._option_names(product.get("options"))
                    normalized_variants = [
                        normalized
                        for variant in (product.get("variants") or [])
                        if isinstance(variant, dict)
                        if (normalized := self._normalize_variant(
                            variant,
                            option_names=option_names,
                            scheme=urlparse(url).scheme or "https",
                            base_url=url,
                        ))
                    ]
                    normalized_variants = self._dedupe_variants(normalized_variants)
                    selected_variant = self._select_shopify_variant(
                        normalized_variants,
                        base_url=url,
                    )
                    axes = self._variant_axes(normalized_variants)
                    selectable_axes, single_value_attributes = (
                        self._split_selectable_axes(axes)
                    )
                    selected_price = (
                        selected_variant.get("price")
                        if isinstance(selected_variant, dict)
                        else product.get("price")
                    )
                    records.append({
                        "title": product.get("title"),
                        "brand": product.get("vendor"),
                        "price": normalize_decimal_price(
                            selected_price,
                            interpret_integral_as_cents=True,
                        ),
                        "category": product.get("type"),
                        "variants": normalized_variants,
                        "variant_axes": selectable_axes,
                        "selected_variant": selected_variant,
                        "product_attributes": single_value_attributes or None,
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

    def _option_names(self, raw_options: object) -> list[str]:
        names: list[str] = []
        if isinstance(raw_options, list):
            for option in raw_options:
                if isinstance(option, str):
                    names.append(option)
                elif isinstance(option, dict):
                    label = option.get("name") or option.get("title")
                    if label:
                        names.append(str(label))
        return names

    def _normalize_variant(
        self,
        variant: dict,
        *,
        option_names: list[str],
        scheme: str,
        base_url: str,
    ) -> dict | None:
        row: dict[str, object] = {}
        if variant.get("id") not in (None, "", [], {}):
            row["variant_id"] = str(variant.get("id"))
            row["url"] = f"{base_url}{'&' if '?' in base_url else '?'}variant={row['variant_id']}"
        if variant.get("sku"):
            row["sku"] = variant.get("sku")
        price = normalize_decimal_price(
            variant.get("price"),
            interpret_integral_as_cents=True,
        )
        if price is not None:
            row["price"] = price
        original_price = normalize_decimal_price(
            variant.get("compare_at_price"),
            interpret_integral_as_cents=True,
        )
        if original_price is not None:
            row["original_price"] = original_price
        raw_available = variant.get("available")
        if raw_available is not None:
            if isinstance(raw_available, bool):
                available = raw_available
            elif isinstance(raw_available, str):
                available = raw_available.strip().lower() in {"true", "1", "yes"}
            elif isinstance(raw_available, (int, float)):
                available = raw_available != 0
            else:
                available = False
            row["available"] = available
            row["availability"] = "in_stock" if available else "out_of_stock"
        featured = self._normalize_url(self._image_src(variant.get("featured_image")), scheme)
        if featured:
            row["image_url"] = featured
        option_values: dict[str, str] = {}
        raw_options = variant.get("options") if isinstance(variant.get("options"), list) else []
        for index in range(1, SHOPIFY_MAX_OPTION_AXIS_COUNT + 1):
            axis_name = option_names[index - 1] if index - 1 < len(option_names) else f"option_{index}"
            axis_key = normalized_variant_axis_key(axis_name) or self._normalize_axis(axis_name)
            value = variant.get(f"option{index}")
            if value in (None, "", [], {}) and index - 1 < len(raw_options):
                value = raw_options[index - 1]
            if value in (None, "", [], {}):
                continue
            option_values[axis_key] = str(value)
            if axis_key in {"color", "size"}:
                row[axis_key] = str(value)
        if option_values:
            row["option_values"] = option_values
        return row or None

    def _variant_axes(self, variants: list[dict]) -> dict[str, list[str]]:
        axes: dict[str, list[str]] = {}
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            option_values = variant.get("option_values")
            if not isinstance(option_values, dict):
                continue
            for axis_name, value in option_values.items():
                cleaned = str(value or "").strip()
                if not cleaned:
                    continue
                axes.setdefault(str(axis_name), [])
                if cleaned not in axes[str(axis_name)]:
                    axes[str(axis_name)].append(cleaned)
        return axes

    def _dedupe_variants(self, variants: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen: dict[str, int] = {}
        for variant in variants:
            fingerprint = self._variant_fingerprint(variant)
            if fingerprint is None:
                deduped.append(dict(variant))
                continue
            existing_index = seen.get(fingerprint)
            if existing_index is None:
                seen[fingerprint] = len(deduped)
                deduped.append(dict(variant))
                continue
            current = deduped[existing_index]
            if len(variant.keys()) > len(current.keys()):
                merged = dict(variant)
                for key, value in current.items():
                    if merged.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
                        merged[key] = value
                deduped[existing_index] = merged
                continue
            for key, value in variant.items():
                if current.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
                    current[key] = value
        return deduped

    def _variant_fingerprint(self, variant: dict) -> str | None:
        variant_id = str(variant.get("variant_id") or "").strip()
        if variant_id:
            return f"id:{variant_id}"
        sku = str(variant.get("sku") or "").strip()
        option_values = variant.get("option_values")
        if sku and isinstance(option_values, dict) and option_values:
            return json.dumps({"sku": sku, "option_values": option_values}, sort_keys=True)
        if sku:
            return f"sku:{sku}"
        if isinstance(option_values, dict) and option_values:
            return json.dumps({"option_values": option_values}, sort_keys=True)
        return None

    def _split_selectable_axes(
        self, axes: dict[str, list[str]]
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        return split_variant_axes(
            axes,
            always_selectable_axes=frozenset({"size"}),
        )

    def _select_shopify_variant(
        self,
        variants: list[dict],
        *,
        base_url: str,
    ) -> dict | None:
        if not variants:
            return None
        parsed = urlsplit(str(base_url or "").strip())
        variant_id = next(
            (
                str(value).strip()
                for key, value in parse_qsl(parsed.query, keep_blank_values=False)
                if key == "variant" and str(value).strip()
            ),
            "",
        )
        if variant_id:
            matched_variant = next(
                (
                    row
                    for row in variants
                    if str(row.get("variant_id") or "").strip() == variant_id
                ),
                None,
            )
            if matched_variant is not None:
                return matched_variant
        return next((row for row in variants if row.get("available") is True), None) or variants[0]

    def _normalize_axis(self, value: object) -> str:
        normalized = normalized_variant_axis_key(value)
        if normalized:
            return normalized
        text = str(value or "").strip().lower().replace("&", " ")
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text or "option"
