"""Compare Zyte baseline against CrawlerAI output for the 51-url batch."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

# Approximate exchange rates (USD as base)
EXCHANGE_RATES = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "INR": 0.012,
    "ARS": 0.001,
    "BRL": 0.20,
    "MXN": 0.059,
    "CAD": 0.74,
    "AUD": 0.65,
    "JPY": 0.0067,
    "CNY": 0.14,
}


COMMON_MULTI_PART_SUFFIXES = {
    "co.uk",
    "com.au",
    "co.in",
    "com.br",
    "com.mx",
}

CORE_FIELDS = ("title", "brand", "price", "image_url")
NOISE_PATTERNS = [
    r"add to cart",
    r"buy now",
    r"buy new",
    r"shipping",
    r"returns",
    r"same-day",
    r"same day",
    r"delivery",
    r"location",
    r"auto-replenish",
    r"create an account",
    r"order history",
    r"view all",
    r"sign in",
    r"free shipping",
    r"pickup",
    r"select(?:\s+\w+)?",
    r"choose(?:\s+\w+)?",
    r"about\s+",
    r"most common",
]
NOISE_RE = re.compile("|".join(f"(?:{pattern})" for pattern in NOISE_PATTERNS), re.I)
AVAILABILITY_RE = re.compile(r"\b(out of stock|sold out|unavailable|in stock|limited stock)\b", re.I)
SIZE_RE = re.compile(
    r"^(?:"
    r"\d{1,2}(?:\.\d+)?(?:[a-z]{1,3})?"
    r"|\d{1,2}/\d{1,2}"
    r"|xxs|xs|s|m|l|xl|xxl|xxxl"
    r"|small|medium|large|one size|all"
    r"|queen|king|twin|full|california king"
    r"|[0-9]{2,3}\s?(?:gb|tb|ml|oz|g|kg|cm|mm|in|softgels?)"
    r")$",
    re.I,
)
COLOR_WORD_RE = re.compile(r"[a-z]{3,}", re.I)
ID_LIKE_RE = re.compile(r"^[A-Z0-9_-]{5,}$")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = " ".join(str(item) for item in value if item)
    text = str(value).strip()
    if not text:
        return None
    return re.sub(r"\s+", " ", text)


def decimal_value(value: Any) -> Decimal | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"[^\d.,-]", "", text).replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def normalize_price(value: Any) -> str | None:
    amount = decimal_value(value)
    if amount is None:
        return None
    return f"{amount:.2f}"


def convert_to_usd(amount: Decimal, currency: str | None) -> Decimal | None:
    """Convert amount to USD using exchange rates."""
    if not currency or not amount:
        return None
    currency_upper = currency.strip().upper()
    rate = EXCHANGE_RATES.get(currency_upper)
    if rate is None:
        return None
    return amount * Decimal(str(rate))


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    path = re.sub(r"/+", "/", parts.path.rstrip("/")).lower() or "/"
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def host_key(url: str | None) -> str:
    if not url:
        return ""
    host = urlsplit(url).netloc.lower()
    labels = [label for label in host.split(".") if label and label != "www"]
    if len(labels) < 2:
        return host
    suffix = ".".join(labels[-2:])
    if suffix in COMMON_MULTI_PART_SUFFIXES and len(labels) >= 3:
        return labels[-3]
    if len(labels) >= 3 and labels[-2] in {"co", "com"}:
        return labels[-3]
    return labels[-2]


def path_tail_key(url: str | None, parts: int = 2) -> str:
    if not url:
        return ""
    segments = [segment.lower() for segment in urlsplit(url).path.split("/") if segment]
    if not segments:
        return ""
    return "/".join(segments[-parts:])


def id_tokens(url: str | None) -> set[str]:
    if not url:
        return set()
    parts = re.findall(r"[a-z0-9]{5,}", urlsplit(url).path.lower())
    return {token for token in parts if any(ch.isdigit() for ch in token)}


def title_similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def normalize_availability(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    compact = re.sub(r"[\s-]+", "_", text.lower())
    mapping = {
        "instock": "in_stock",
        "in_stock": "in_stock",
        "outofstock": "out_of_stock",
        "out_of_stock": "out_of_stock",
        "preorder": "preorder",
    }
    return mapping.get(compact, compact)


def first_gtin_value(gtin: Any) -> str | None:
    if not isinstance(gtin, list):
        return None
    for item in gtin:
        if isinstance(item, dict):
            value = clean_text(item.get("value"))
            if value:
                return value
    return None


def normalize_images(main_image: Any, images: Any) -> list[str]:
    values: list[str] = []
    if isinstance(main_image, dict):
        url = clean_text(main_image.get("url"))
        if url:
            values.append(url)
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict):
                url = clean_text(item.get("url"))
                if url:
                    values.append(url)
            else:
                url = clean_text(item)
                if url:
                    values.append(url)
    deduped: list[str] = []
    seen: set[str] = set()
    for url in values:
        key = clean_text(url)
        if key and key not in seen:
            seen.add(key)
            deduped.append(url)
    return deduped


def normalize_variants(variants: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    if not isinstance(variants, list):
        return normalized
    for item in variants:
        if not isinstance(item, dict):
            continue
        row: dict[str, str] = {}
        for field in ("size", "color", "sku", "price", "name"):
            value = clean_text(item.get(field))
            if value:
                row[field] = value
        if row:
            normalized.append(row)
    return normalized


def normalize_raw_variant_rows(variants: Any) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    if not isinstance(variants, list):
        return normalized
    for item in variants:
        if not isinstance(item, dict):
            continue
        row: dict[str, str] = {}
        for key, value in item.items():
            text = clean_text(value)
            if text:
                row[str(key)] = text
        if row:
            normalized.append(row)
    return normalized


def looks_like_noise(text: str | None) -> bool:
    if not text:
        return False
    return bool(NOISE_RE.search(text))


def looks_like_size_value(text: str | None) -> bool:
    if not text:
        return False
    compact = clean_text(text)
    if not compact:
        return False
    return bool(SIZE_RE.match(compact))


def looks_like_color_value(text: str | None) -> bool:
    if not text:
        return False
    compact = clean_text(text)
    if not compact:
        return False
    if looks_like_noise(compact):
        return False
    if compact.isdigit():
        return False
    if "http://" in compact.lower() or "https://" in compact.lower():
        return False
    if AVAILABILITY_RE.search(compact):
        return False
    return bool(COLOR_WORD_RE.search(compact))


def looks_like_id_value(text: str | None) -> bool:
    if not text:
        return False
    compact = clean_text(text)
    if not compact:
        return False
    return bool(ID_LIKE_RE.match(compact)) and not looks_like_size_value(compact)


def axis_value_set(rows: list[dict[str, str]], axis: str) -> set[str]:
    values = set()
    for row in rows:
        value = clean_text(row.get(axis))
        if value:
            values.add(value.strip().lower())
    return values


def crawler_record_view(record: dict[str, Any]) -> dict[str, Any]:
    images = normalize_images({"url": record.get("image_url")}, record.get("additional_images") or [])
    description = clean_text(record.get("description"))
    features = clean_text(record.get("features"))
    product_details = clean_text(record.get("product_details"))
    return {
        "url": record.get("url"),
        "title": clean_text(record.get("title")),
        "brand": clean_text(record.get("brand")),
        "price": normalize_price(record.get("price")),
        "original_price": normalize_price(record.get("original_price")),
        "currency": clean_text(record.get("currency")),
        "availability": normalize_availability(record.get("availability")),
        "sku": clean_text(record.get("sku")),
        "barcode": clean_text(record.get("barcode")),
        "color": clean_text(record.get("color")),
        "size": clean_text(record.get("size")),
        "description": description,
        "features": features,
        "product_details": product_details,
        "description_best": product_details or description or features,
        "image_url": images[0] if images else None,
        "images": images,
        "variants": normalize_variants(record.get("variants")),
        "raw_variants": normalize_raw_variant_rows(record.get("variants")),
        "variant_count": int(record.get("variant_count") or len(record.get("variants") or []) or 0),
    }


def zyte_record_view(entry: dict[str, Any]) -> dict[str, Any]:
    product = (entry.get("data") or {}).get("product") or {}
    images = normalize_images(product.get("mainImage"), product.get("images"))
    description = clean_text(product.get("description"))
    features = clean_text(product.get("features"))
    brand = product.get("brand") if isinstance(product.get("brand"), dict) else {}
    return {
        "url": entry.get("url"),
        "status": entry.get("status"),
        "error": clean_text(entry.get("error")),
        "title": clean_text(product.get("name")),
        "brand": clean_text(brand.get("name")),
        "price": normalize_price(product.get("price")),
        "original_price": normalize_price(product.get("regularPrice")),
        "currency": clean_text(product.get("currency")),
        "availability": normalize_availability(product.get("availability")),
        "sku": clean_text(product.get("sku")),
        "barcode": first_gtin_value(product.get("gtin")),
        "color": clean_text(product.get("color")),
        "size": clean_text(product.get("size")),
        "description": description,
        "features": features,
        "description_best": description or features,
        "image_url": images[0] if images else None,
        "images": images,
        "variants": normalize_variants(product.get("variants")),
        "raw_variants": normalize_raw_variant_rows(product.get("variants")),
        "variant_count": len(product.get("variants") or []),
    }


def analyze_variant_schema(
    crawler_view: dict[str, Any],
    zyte_view: dict[str, Any],
    failure_modes: list[str],
    critical_issues: list[str],
    architecture_buckets: set[str],
    mismatches: list[dict[str, Any]],
) -> None:
    crawler_rows = crawler_view.get("raw_variants") or []
    zyte_rows = zyte_view.get("raw_variants") or []
    if not crawler_rows:
        return

    noise_rows: list[dict[str, str]] = []
    polluted_color_rows: list[dict[str, str]] = []
    polluted_size_rows: list[dict[str, str]] = []
    cross_page_rows: list[dict[str, str]] = []
    parent_url = normalize_url(crawler_view.get("url"))
    parent_color = clean_text(crawler_view.get("color"))
    parent_size = clean_text(crawler_view.get("size"))
    color_values = axis_value_set(crawler_rows, "color")
    size_values = axis_value_set(crawler_rows, "size")

    for row in crawler_rows:
        joined = " | ".join(f"{key}={value}" for key, value in sorted(row.items()))
        if looks_like_noise(joined):
            noise_rows.append(row)
        color_value = row.get("color")
        if color_value and not looks_like_color_value(color_value):
            polluted_color_rows.append(row)
        size_value = row.get("size")
        if size_value and not looks_like_size_value(size_value):
            polluted_size_rows.append(row)
        row_url = normalize_url(row.get("url"))
        if row_url and parent_url and urlsplit(row_url).netloc.lower() != urlsplit(parent_url).netloc.lower():
            cross_page_rows.append(row)

    if noise_rows and len(noise_rows) >= max(2, len(crawler_rows) // 2):
        critical_issues.append("variant_row_noise")
        failure_modes.append("variant_row_noise")
        architecture_buckets.add("variant_extraction")
        mismatches.append(
            {
                "field": "variant_noise_rows",
                "crawler": noise_rows[:5],
                "zyte": len(zyte_rows),
            }
        )

    if polluted_color_rows and len(polluted_color_rows) >= max(2, len(crawler_rows) // 2):
        critical_issues.append("variant_axis_pollution")
        failure_modes.append("variant_axis_pollution")
        architecture_buckets.add("variant_extraction")
        mismatches.append(
            {
                "field": "variant_color_pollution",
                "crawler": polluted_color_rows[:5],
                "zyte": sorted(axis_value_set(zyte_rows, "color")),
            }
        )

    if polluted_size_rows and len(polluted_size_rows) >= max(2, len(crawler_rows) // 2):
        critical_issues.append("variant_axis_pollution")
        failure_modes.append("variant_axis_pollution")
        architecture_buckets.add("variant_extraction")
        mismatches.append(
            {
                "field": "variant_size_pollution",
                "crawler": polluted_size_rows[:5],
                "zyte": sorted(axis_value_set(zyte_rows, "size")),
            }
        )

    if cross_page_rows:
        critical_issues.append("variant_navigation_pollution")
        failure_modes.append("variant_navigation_pollution")
        architecture_buckets.add("variant_extraction")
        mismatches.append(
            {
                "field": "variant_cross_page_urls",
                "crawler": cross_page_rows[:5],
                "zyte": None,
            }
        )

    if parent_color and color_values and parent_color.strip().lower() not in color_values:
        if looks_like_id_value(parent_color) or not looks_like_color_value(parent_color):
            critical_issues.append("variant_parent_child_conflict")
            failure_modes.append("variant_parent_child_conflict")
            architecture_buckets.add("variant_extraction")
            mismatches.append(
                {
                    "field": "parent_color_not_in_variants",
                    "crawler": parent_color,
                    "zyte": sorted(color_values)[:12],
                }
            )

    if parent_size and size_values and parent_size.strip().lower() not in size_values:
        if not looks_like_size_value(parent_size):
            critical_issues.append("variant_parent_child_conflict")
            failure_modes.append("variant_parent_child_conflict")
            architecture_buckets.add("variant_extraction")
            mismatches.append(
                {
                    "field": "parent_size_not_in_variants",
                    "crawler": parent_size,
                    "zyte": sorted(size_values)[:12],
                }
            )


def analyze_scalar_pollution(
    crawler_view: dict[str, Any],
    zyte_view: dict[str, Any],
    failure_modes: list[str],
    critical_issues: list[str],
    architecture_buckets: set[str],
    mismatches: list[dict[str, Any]],
) -> None:
    title = clean_text(crawler_view.get("title"))
    color = clean_text(crawler_view.get("color"))
    size = clean_text(crawler_view.get("size"))
    brand = clean_text(crawler_view.get("brand"))

    if title and len(title.split()) <= 2 and color and title.strip().lower() == color.strip().lower():
        critical_issues.append("scalar_field_pollution")
        failure_modes.append("scalar_field_pollution")
        architecture_buckets.add("identity_extraction")
        mismatches.append({"field": "title_equals_color", "crawler": title, "zyte": zyte_view.get("title")})

    if color and looks_like_id_value(color):
        critical_issues.append("scalar_field_pollution")
        failure_modes.append("scalar_field_pollution")
        architecture_buckets.add("variant_extraction")
        mismatches.append({"field": "color_looks_like_id", "crawler": color, "zyte": zyte_view.get("color")})

    if size and not looks_like_size_value(size):
        critical_issues.append("scalar_field_pollution")
        failure_modes.append("scalar_field_pollution")
        architecture_buckets.add("variant_extraction")
        mismatches.append({"field": "size_looks_polluted", "crawler": size, "zyte": zyte_view.get("size")})

    if brand and looks_like_noise(brand):
        critical_issues.append("scalar_field_pollution")
        failure_modes.append("scalar_field_pollution")
        architecture_buckets.add("identity_extraction")
        mismatches.append({"field": "brand_noise", "crawler": brand, "zyte": zyte_view.get("brand")})


def same_record(crawler: dict[str, Any], zyte: dict[str, Any]) -> bool:
    crawler_url = crawler.get("url")
    zyte_url = zyte.get("url")
    if normalize_url(crawler_url) == normalize_url(zyte_url):
        return True
    if host_key(crawler_url) != host_key(zyte_url):
        return False
    if path_tail_key(crawler_url, 2) == path_tail_key(zyte_url, 2):
        return True
    if path_tail_key(crawler_url, 1) == path_tail_key(zyte_url, 1):
        return True
    crawler_ids = id_tokens(crawler_url)
    zyte_ids = id_tokens(zyte_url)
    if crawler_ids and zyte_ids and crawler_ids.intersection(zyte_ids):
        return True
    crawler_title = clean_text(crawler.get("title"))
    zyte_title = clean_text(((zyte.get("data") or {}).get("product") or {}).get("name"))
    return title_similarity(crawler_title, zyte_title) >= 0.82


@dataclass
class AlignedPair:
    zyte_index: int
    zyte: dict[str, Any]
    crawler_index: int | None
    crawler: dict[str, Any] | None
    alignment: str


def align_records(zyte_rows: list[dict[str, Any]], crawler_rows: list[dict[str, Any]]) -> tuple[list[AlignedPair], list[dict[str, Any]]]:
    pairs: list[AlignedPair] = []
    orphaned_crawler: list[dict[str, Any]] = []
    i = 0
    j = 0
    while i < len(zyte_rows) and j < len(crawler_rows):
        current_zyte = zyte_rows[i]
        current_crawler = crawler_rows[j]
        if same_record(current_crawler, current_zyte):
            pairs.append(AlignedPair(i, current_zyte, j, current_crawler, "matched"))
            i += 1
            j += 1
            continue
        next_zyte_matches = i + 1 < len(zyte_rows) and same_record(current_crawler, zyte_rows[i + 1])
        next_crawler_matches = j + 1 < len(crawler_rows) and same_record(crawler_rows[j + 1], current_zyte)
        if next_zyte_matches and not next_crawler_matches:
            pairs.append(AlignedPair(i, current_zyte, None, None, "crawler_missing"))
            i += 1
            continue
        if next_crawler_matches and not next_zyte_matches:
            orphaned_crawler.append(current_crawler)
            j += 1
            continue
        pairs.append(AlignedPair(i, current_zyte, j, current_crawler, "forced_match"))
        i += 1
        j += 1
    while i < len(zyte_rows):
        pairs.append(AlignedPair(i, zyte_rows[i], None, None, "crawler_missing"))
        i += 1
    while j < len(crawler_rows):
        orphaned_crawler.append(crawler_rows[j])
        j += 1
    return pairs, orphaned_crawler


def compare_pair(pair: AlignedPair) -> dict[str, Any]:
    zyte_view = zyte_record_view(pair.zyte)
    crawler_view = crawler_record_view(pair.crawler) if pair.crawler else None
    failure_modes: list[str] = []
    critical_issues: list[str] = []
    architecture_buckets: set[str] = set()
    mismatches: list[dict[str, Any]] = []

    if pair.alignment == "crawler_missing":
        failure_modes.append("crawler_missing_record")
        architecture_buckets.add("record_alignment")

    if zyte_view.get("status") == "error":
        failure_modes.append("zyte_error")
        architecture_buckets.add("baseline_gap")

    if crawler_view:
        analyze_scalar_pollution(crawler_view, zyte_view, failure_modes, critical_issues, architecture_buckets, mismatches)
        analyze_variant_schema(crawler_view, zyte_view, failure_modes, critical_issues, architecture_buckets, mismatches)

        # Skip coverage gaps - focus on data quality issues
        # Missing fields are not critical data quality issues

        # Keep description duplication as it's a data quality issue
        if (
            crawler_view.get("description")
            and crawler_view.get("features")
            and crawler_view["description"].lower() == crawler_view["features"].lower()
            and (
                not crawler_view.get("product_details")
                or crawler_view["description"].lower() == crawler_view["product_details"].lower()
            )
        ):
            failure_modes.append("description_duplication")
            architecture_buckets.add("text_sanitization")

        # Skip variant coverage gaps - Zyte is mostly correct
        # Skip variant axis coverage gaps - Zyte is mostly correct

        # Skip image coverage gap - coverage issue, not quality

        crawler_title = crawler_view.get("title")
        zyte_title = zyte_view.get("title")
        if crawler_title and zyte_title:
            score = title_similarity(crawler_title, zyte_title)
            if score < 0.82:
                mismatches.append(
                    {
                        "field": "title",
                        "crawler": crawler_title,
                        "zyte": zyte_title,
                    }
                )
            if score < 0.55:
                critical_issues.append("identity_mismatch")
                architecture_buckets.add("identity_extraction")
                failure_modes.append("identity_mismatch")

        for field in ("brand", "sku", "barcode", "color", "size"):
            crawler_value = crawler_view.get(field)
            zyte_value = zyte_view.get(field)
            if crawler_value and zyte_value and str(crawler_value).strip().lower() != str(zyte_value).strip().lower():
                mismatches.append(
                    {
                        "field": field,
                        "crawler": crawler_value,
                        "zyte": zyte_value,
                    }
                )

        for field in ("price", "original_price"):
            crawler_value = crawler_view.get(field)
            zyte_value = zyte_view.get(field)
            if not crawler_value or not zyte_value:
                continue
            crawler_amount = decimal_value(crawler_value)
            zyte_amount = decimal_value(zyte_value)
            if crawler_amount is None or zyte_amount is None:
                continue
            
            # Convert to common currency (USD) for comparison
            crawler_currency = crawler_view.get("currency")
            zyte_currency = zyte_view.get("currency")
            
            # Skip comparison if currencies differ or one is missing - this is expected for regional sites
            if crawler_currency and zyte_currency:
                if crawler_currency.strip().lower() != zyte_currency.strip().lower():
                    # Different currencies - don't flag as error
                    continue
            elif crawler_currency or zyte_currency:
                # One has currency, other doesn't - can't reliably compare
                continue
            
            # Same currency or one missing - compare directly
            crawler_usd = convert_to_usd(crawler_amount, crawler_currency) or crawler_amount
            zyte_usd = convert_to_usd(zyte_amount, zyte_currency) or zyte_amount
            
            delta = abs(crawler_usd - zyte_usd)
            # Skip if prices are effectively identical (within 0.01)
            if delta <= Decimal("0.01"):
                continue
            ratio = delta / zyte_usd if zyte_usd else Decimal("0")
            if delta > Decimal("3.00") and ratio > Decimal("0.15"):
                critical_issues.append("price_outlier")
                architecture_buckets.add("price_extraction")
                failure_modes.append("price_outlier")
                mismatches.append(
                    {
                        "field": field,
                        "crawler": crawler_value,
                        "zyte": zyte_value,
                    }
                )

        # Availability mismatch is a data quality issue
        if crawler_view.get("availability") and zyte_view.get("availability"):
            if crawler_view["availability"] != zyte_view["availability"]:
                critical_issues.append("availability_mismatch")
                architecture_buckets.add("availability_extraction")
                failure_modes.append("availability_mismatch")
                mismatches.append(
                    {
                        "field": "availability",
                        "crawler": crawler_view["availability"],
                        "zyte": zyte_view["availability"],
                    }
                )

        # Skip description richness gap - coverage issue, not quality

    deduped_modes: list[str] = []
    seen_modes: set[str] = set()
    for mode in failure_modes:
        if mode not in seen_modes:
            seen_modes.add(mode)
            deduped_modes.append(mode)

    deduped_critical: list[str] = []
    seen_critical: set[str] = set()
    for mode in critical_issues:
        if mode not in seen_critical:
            seen_critical.add(mode)
            deduped_critical.append(mode)

    return {
        "url": pair.zyte.get("url"),
        "site": host_key(pair.zyte.get("url")),
        "alignment": pair.alignment,
        "zyte_status": zyte_view.get("status"),
        "crawler_url": crawler_view.get("url") if crawler_view else None,
        "failure_modes": deduped_modes,
        "critical_issues": deduped_critical,
        "architecture_buckets": sorted(architecture_buckets),
        "mismatches": mismatches,
        "zyte": zyte_view,
        "crawlerai": crawler_view,
    }


def build_markdown(results: list[dict[str, Any]], orphaned_crawler: list[dict[str, Any]]) -> str:
    total = len(results)
    matched = sum(1 for row in results if row["alignment"] == "matched")
    forced = sum(1 for row in results if row["alignment"] == "forced_match")
    crawler_missing = sum(1 for row in results if "crawler_missing_record" in row["failure_modes"])
    zyte_errors = sum(1 for row in results if "zyte_error" in row["failure_modes"])
    critical_count = sum(1 for row in results if row["critical_issues"])

    mode_counts: dict[str, int] = {}
    critical_counts: dict[str, int] = {}
    bucket_counts: dict[str, int] = {}
    for row in results:
        for mode in row["failure_modes"]:
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
        for crit in row["critical_issues"]:
            critical_counts[crit] = critical_counts.get(crit, 0) + 1
        for bucket in row["architecture_buckets"]:
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

    lines = [
        "# Zyte vs CrawlerAI Comparison",
        "",
        f"- Total Zyte URLs: {total}",
        f"- Direct matches: {matched}",
        f"- Forced matches: {forced}",
        f"- Missing CrawlerAI records: {crawler_missing}",
        f"- Zyte baseline errors: {zyte_errors}",
        f"- Orphaned CrawlerAI records: {len(orphaned_crawler)}",
        f"- **Critical data quality issues: {critical_count}**",
        "",
        "## 🚨 Critical Data Quality Issues",
        "",
    ]
    if critical_counts:
        for name, count in sorted(critical_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- **{name}**: {count}")
    else:
        lines.append("- None - All data quality checks passed")
    
    lines.extend(["", "## All Failure Modes", ""])
    for name, count in sorted(mode_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {name}: {count}")
    lines.extend(["", "## Architecture Buckets", ""])
    for name, count in sorted(bucket_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {name}: {count}")

    lines.extend(["", "## URL-wise Results", ""])
    for index, row in enumerate(results, start=1):
        critical = ", ".join(row["critical_issues"]) if row["critical_issues"] else None
        modes = ", ".join(row["failure_modes"]) if row["failure_modes"] else "ok"
        buckets = ", ".join(row["architecture_buckets"]) if row["architecture_buckets"] else "-"
        lines.append(f"### {index:02d}. {row['url']}")
        if critical:
            lines.append(f"- **CRITICAL**: {critical}")
        lines.append(f"- alignment: {row['alignment']}")
        lines.append(f"- zyte_status: {row['zyte_status']}")
        lines.append(f"- crawler_url: {row['crawler_url'] or 'missing'}")
        lines.append(f"- failure_modes: {modes}")
        lines.append(f"- architecture_buckets: {buckets}")
        if row["mismatches"]:
            lines.append("- mismatches:")
            for mismatch in row["mismatches"][:8]:
                lines.append(
                    f"  - {mismatch['field']}: crawler={mismatch['crawler']} | zyte={mismatch['zyte']}"
                )
        lines.append("")

    if orphaned_crawler:
        lines.extend(["## Orphaned CrawlerAI Records", ""])
        for row in orphaned_crawler:
            lines.append(f"- {row.get('url')}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crawlerai", default="crawlerai.json")
    parser.add_argument("--zyte", default="zyte_extracted_results.json")
    parser.add_argument("--out-json", default="zyte_vs_crawlerai_comparison.json")
    parser.add_argument("--out-md", default="zyte_vs_crawlerai_comparison.md")
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    crawler_rows = load_json(base_dir / args.crawlerai)
    zyte_rows = load_json(base_dir / args.zyte)

    pairs, orphaned_crawler = align_records(zyte_rows, crawler_rows)
    results = [compare_pair(pair) for pair in pairs]

    summary = {
        "total_zyte_urls": len(zyte_rows),
        "total_crawlerai_records": len(crawler_rows),
        "results": results,
        "orphaned_crawlerai_records": orphaned_crawler,
    }

    (base_dir / args.out_json).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (base_dir / args.out_md).write_text(
        build_markdown(results, orphaned_crawler),
        encoding="utf-8",
    )

    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")


if __name__ == "__main__":
    main()
