# Shopify platform adapter.
from __future__ import annotations

import json
import re
from json import loads as parse_json
import math
from urllib.parse import parse_qsl, urljoin, urlparse, urlsplit

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
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
        # Listing pages are best served by the public collection endpoint.
        # Detail pages still probe the public endpoint to enrich the embedded
        # payload with the fuller Shopify product object.
        if surface in ("ecommerce_listing", "ecommerce_detail"):
            api_records = await self.try_public_endpoint(
                url,
                html=html,
                surface=surface,
            )
            if api_records:
                if surface == "ecommerce_detail" and records:
                    records = [self._merge_product_records(records[0], api_records[0])]
                else:
                    records = api_records
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
            try:
                data = await self._request_json(
                    api_url,
                    proxy=proxy,
                    timeout_seconds=adapter_runtime_settings.shopify_request_timeout_seconds,
                )
            except _FETCH_ERRORS:
                return []
            if not isinstance(data, dict):
                return []
            products = [data]
        else:
            collection_handle = self._extract_collection_handle(parsed.path)
            api_path = (
                f"/collections/{collection_handle}/products.json"
                if collection_handle
                else "/products.json"
            )
            products: list[dict] = []
            max_pages = max(
                1,
                math.ceil(
                    adapter_runtime_settings.shopify_max_products
                    / adapter_runtime_settings.shopify_catalog_limit
                ),
            )
            for page in range(1, max_pages + 1):
                api_url = (
                    f"{parsed.scheme}://{parsed.netloc}{api_path}"
                    f"?limit={adapter_runtime_settings.shopify_catalog_limit}&page={page}"
                )
                try:
                    data = await self._request_json(
                        api_url,
                        proxy=proxy,
                        timeout_seconds=adapter_runtime_settings.shopify_request_timeout_seconds,
                    )
                except _FETCH_ERRORS:
                    break
                if not isinstance(data, dict):
                    break
                batch = data.get("products", [])
                if not isinstance(batch, list) or not batch:
                    break
                products.extend(product for product in batch if isinstance(product, dict))
                if (
                    len(products) >= adapter_runtime_settings.shopify_max_products
                    or len(batch) < adapter_runtime_settings.shopify_catalog_limit
                ):
                    break

        return [
            self._build_product_record(product, page_url=url, surface=surface)
            for product in products[: adapter_runtime_settings.shopify_max_products]
            if isinstance(product, dict)
        ]

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
        pattern = r"var\s+meta\s*=\s*(\{.*?\});"
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
                        if (
                            normalized := self._normalize_variant(
                                variant,
                                option_names=option_names,
                                scheme=urlparse(url).scheme or "https",
                                base_url=url,
                            )
                        )
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
                    records.append(
                        {
                            "title": product.get("title"),
                            "brand": product.get("vendor"),
                            "vendor": product.get("vendor"),
                            "price": normalize_decimal_price(
                                selected_price,
                                interpret_integral_as_cents=True,
                            ),
                            "category": product.get("type"),
                            "product_type": product.get("type"),
                            "product_id": str(product.get("id"))
                            if product.get("id") not in (None, "", [], {})
                            else None,
                            "variants": normalized_variants,
                            "variant_axes": selectable_axes,
                            "selected_variant": selected_variant,
                            "product_attributes": single_value_attributes or None,
                        }
                    )
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
            row["url"] = (
                f"{base_url}{'&' if '?' in base_url else '?'}variant={row['variant_id']}"
            )
        if variant.get("sku"):
            row["sku"] = variant.get("sku")
        if variant.get("barcode"):
            row["barcode"] = variant.get("barcode")
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
        featured = self._normalize_url(
            self._image_src(variant.get("featured_image")), scheme
        )
        if featured:
            row["image_url"] = featured
        option_values: dict[str, str] = {}
        raw_options = (
            variant.get("options") if isinstance(variant.get("options"), list) else []
        )
        for index in range(
            1,
            adapter_runtime_settings.shopify_max_option_axis_count + 1,
        ):
            axis_name = (
                option_names[index - 1]
                if index - 1 < len(option_names)
                else f"option_{index}"
            )
            axis_key = normalized_variant_axis_key(axis_name) or self._normalize_axis(
                axis_name
            )
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

    def _build_product_record(
        self,
        product: dict,
        *,
        page_url: str,
        surface: str,
    ) -> dict:
        parsed = urlparse(page_url)
        variants = (
            product.get("variants", []) if isinstance(product.get("variants"), list) else []
        )
        option_names = self._option_names(product.get("options"))
        product_url = urljoin(page_url, f"/products/{product.get('handle', '')}")
        normalized_variants = [
            normalized
            for variant in variants
            if isinstance(variant, dict)
            if (
                normalized := self._normalize_variant(
                    variant,
                    option_names=option_names,
                    scheme=parsed.scheme,
                    base_url=product_url,
                )
            )
        ]
        normalized_variants = self._dedupe_variants(normalized_variants)
        selected_variant = self._select_shopify_variant(
            normalized_variants,
            base_url=page_url,
        )
        axes = self._variant_axes(normalized_variants)
        selectable_axes, single_value_attributes = self._split_selectable_axes(axes)
        images = [
            image_url
            for img in product.get("images", [])
            if (
                image_url := self._normalize_url(self._image_src(img), parsed.scheme)
            )
        ]
        raw_tags = product.get("tags")
        tags = (
            [token for token in (item.strip() for item in raw_tags.strip().split(",")) if token]
            if isinstance(raw_tags, str) and raw_tags.strip()
            else ([] if isinstance(raw_tags, str) else product.get("tags", []))
        )
        record = {
            "title": product.get("title"),
            "brand": product.get("vendor"),
            "description": product.get("body_html", ""),
            "url": product_url,
            "image_url": images[0] if images else None,
            "additional_images": ", ".join(images[1:]) if len(images) > 1 else None,
            "price": selected_variant.get("price")
            if isinstance(selected_variant, dict)
            else None,
            "original_price": selected_variant.get("original_price")
            if isinstance(selected_variant, dict)
            else None,
            "sku": selected_variant.get("sku")
            if isinstance(selected_variant, dict)
            else None,
            "availability": selected_variant.get("availability")
            if isinstance(selected_variant, dict)
            else None,
            "category": product.get("product_type"),
            "tags": tags,
            "variants": normalized_variants,
            "variant_axes": selectable_axes,
            "selected_variant": selected_variant,
            "product_attributes": single_value_attributes or None,
        }
        if isinstance(selected_variant, dict):
            for field_name in ("color", "size", "barcode"):
                if selected_variant.get(field_name):
                    record[field_name] = selected_variant[field_name]
        if surface == "ecommerce_detail":
            size_values = selectable_axes.get("size") if isinstance(selectable_axes, dict) else None
            ordered_axes: list[tuple[str, list[str]]] = []
            seen_axis_names: set[str] = set()
            for option_name in option_names:
                axis_key = normalized_variant_axis_key(option_name) or self._normalize_axis(
                    option_name
                )
                axis_values = selectable_axes.get(axis_key)
                if axis_key and isinstance(axis_values, list) and axis_values:
                    ordered_axes.append((axis_key, axis_values))
                    seen_axis_names.add(axis_key)
            for axis_name, axis_values in selectable_axes.items():
                if axis_name in seen_axis_names or not axis_values:
                    continue
                ordered_axes.append((axis_name, axis_values))
            record.update(
                {
                    "vendor": product.get("vendor"),
                    "product_type": product.get("product_type"),
                    "product_id": str(product.get("id"))
                    if product.get("id") not in (None, "", [], {})
                    else None,
                    "handle": product.get("handle"),
                    "variant_count": len(normalized_variants) or len(variants) or None,
                    "created_at": product.get("created_at"),
                    "updated_at": product.get("updated_at"),
                    "published_at": product.get("published_at"),
                    "image_count": len(images) or None,
                    "available_sizes": ", ".join(size_values[:20]) if size_values else None,
                }
            )
            if len(ordered_axes) > 0:
                record["option1_name"] = ordered_axes[0][0]
                record["option1_values"] = ", ".join(ordered_axes[0][1])
            if len(ordered_axes) > 1:
                record["option2_name"] = ordered_axes[1][0]
                record["option2_values"] = ", ".join(ordered_axes[1][1])
        return record

    def _merge_product_records(self, primary: dict, fallback: dict) -> dict:
        merged = dict(primary)
        for key, value in fallback.items():
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
                continue
            if (
                isinstance(merged.get(key), dict)
                and isinstance(value, dict)
                and value
            ):
                nested = dict(value)
                nested.update(
                    {
                        nested_key: nested_value
                        for nested_key, nested_value in merged[key].items()
                        if nested_value not in (None, "", [], {})
                    }
                )
                merged[key] = nested
        return merged

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
                    if merged.get(key) in (None, "", [], {}) and value not in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        merged[key] = value
                deduped[existing_index] = merged
                continue
            for key, value in variant.items():
                if current.get(key) in (None, "", [], {}) and value not in (
                    None,
                    "",
                    [],
                    {},
                ):
                    current[key] = value
        return deduped

    def _variant_fingerprint(self, variant: dict) -> str | None:
        variant_id = str(variant.get("variant_id") or "").strip()
        if variant_id:
            return f"id:{variant_id}"
        sku = str(variant.get("sku") or "").strip()
        option_values = variant.get("option_values")
        if sku and isinstance(option_values, dict) and option_values:
            return json.dumps(
                {"sku": sku, "option_values": option_values}, sort_keys=True
            )
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
        return (
            next((row for row in variants if row.get("available") is True), None)
            or variants[0]
        )

    def _normalize_axis(self, value: object) -> str:
        normalized = normalized_variant_axis_key(value)
        if normalized:
            return normalized
        text = str(value or "").strip().lower().replace("&", " ")
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text or "option"
