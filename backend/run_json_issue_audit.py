from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_REQUIRED_FIELDS = (
    "url",
    "title",
    "price",
    "currency",
    "availability",
    "image_url",
)

OPTIONAL_SUSPECT_FIELDS = (
    "features",
    "variants",
    "description",
    "materials",
    "tags",
)

APPAREL_VARIANT_HINT_PATTERNS = (
    r"\b(shoe|sneaker|boot|shirt|hoodie|cap|dress|pants|trouser|jacket)\b",
    r"\b(twin|queen|king|xl|xxl|xxxl)\b",
)

NOISE_PATTERNS = (
    r"\bslide\s*\d+\s*of\s*\d+\b",
    r"\bshow\s+image\s*\d+\b",
    r"\b(previous|next)\b",
    r"\b(check\s+availability|compare|close)\b",
    r"\b(scroll\s+carousel|carousel)\b",
    r"\b(enlarge\s+product\s+preview|increase\s+quantity|decrease\s+quantity)\b",
    r"\b(search\s+field\s+icon|button\s+for\s+searching\s+by\s+scanning\s+a\s+barcode)\b",
    r"\b(cookie|privacy\s+policy|terms\s+of\s+service)\b",
)

AVAILABILITY_ALLOWED = {
    "in_stock",
    "out_of_stock",
    "limited_stock",
    "preorder",
    "backorder",
    "discontinued",
    "unknown",
}

SIZE_TOKEN_RE = re.compile(r"^(?:\d{1,2}(?:\.5)?|xxs|xs|s|m|l|xl|xxl|xxxl)$", re.I)
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
PRICE_RE = re.compile(r"^\d+(?:\.\d{1,2})?$")
URL_RE = re.compile(r"^https?://", re.I)
NOISE_RES = [re.compile(pattern, re.I) for pattern in NOISE_PATTERNS]
APPAREL_VARIANT_HINT_RES = [re.compile(pattern, re.I) for pattern in APPAREL_VARIANT_HINT_PATTERNS]


class Issue:
    def __init__(self, category: str, severity: str, field: str, message: str, evidence: Any = None):
        self.category = category
        self.severity = severity
        self.field = field
        self.message = message
        self.evidence = evidence

    def as_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "category": self.category,
            "severity": self.severity,
            "field": self.field,
            "message": self.message,
        }
        if self.evidence is not None:
            row["evidence"] = self.evidence
        return row


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _host_from_url(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_noise_text(text: str) -> bool:
    cleaned = _safe_str(text)
    if not cleaned:
        return False
    return any(rx.search(cleaned) for rx in NOISE_RES)


def _text_token_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", text or ""))


def _looks_price(value: Any) -> bool:
    text = _safe_str(value).replace(",", "")
    return bool(text and PRICE_RE.match(text))


def _looks_currency(value: Any) -> bool:
    return bool(CURRENCY_RE.match(_safe_str(value)))


def _variant_signature(variant: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    keys = [k for k in variant.keys() if k not in {"url", "image_url", "price", "currency", "availability", "sku", "barcode"}]
    parts = []
    for key in sorted(keys):
        parts.append((key, _safe_str(variant.get(key))))
    return tuple(parts)


def _is_variant_size_value(text: str) -> bool:
    value = _safe_str(text).lower()
    if not value:
        return False
    if SIZE_TOKEN_RE.match(value):
        return True
    if re.fullmatch(r"\d{1,2}(?:\.\d)?(?:w|m)?", value):
        return True
    if re.search(r"\b(oz|fl\.?\s*oz|ml|l|inch|in\.|cm|mm|pack)\b", value, re.I):
        return False
    if re.search(r"\b(queen|king|twin|full)\b", value, re.I):
        return True
    return False


def _find_missing_fields(record: dict[str, Any], issues: list[Issue]) -> None:
    for field in DEFAULT_REQUIRED_FIELDS:
        value = record.get(field)
        if value in (None, "", [], {}):
            issues.append(Issue("missing_fields", "high", field, f"missing or empty `{field}`"))
    if not any(_safe_str(record.get(key)) for key in ("sku", "barcode", "part_number")):
        issues.append(
            Issue(
                "missing_fields",
                "medium",
                "sku/barcode/part_number",
                "no core product identifier found",
            )
        )


def _find_incorrect_fields(record: dict[str, Any], issues: list[Issue]) -> None:
    url = _safe_str(record.get("url"))
    if url and not URL_RE.match(url):
        issues.append(Issue("incorrect_data", "high", "url", "url not http/https", url))

    price = record.get("price")
    if price not in (None, "") and not _looks_price(price):
        issues.append(Issue("incorrect_data", "high", "price", "price not numeric string", price))

    currency = record.get("currency")
    if currency not in (None, "") and not _looks_currency(currency):
        issues.append(Issue("incorrect_data", "medium", "currency", "currency not 3-letter ISO", currency))

    availability = _safe_str(record.get("availability")).lower()
    if availability and availability not in AVAILABILITY_ALLOWED:
        issues.append(
            Issue(
                "incorrect_data",
                "medium",
                "availability",
                "availability outside canonical set",
                availability,
            )
        )

    for key in ("price", "original_price", "sale_price"):
        value = record.get(key)
        if value in (None, ""):
            continue
        if _looks_price(value):
            try:
                if float(str(value).replace(",", "")) < 0:
                    issues.append(Issue("logical_errors", "high", key, "negative price", value))
            except ValueError:
                pass

    brand = _safe_str(record.get("brand"))
    if brand and re.search(r"[a-z]", brand) and brand == brand.lower() and len(brand) >= 4:
        issues.append(
            Issue(
                "incorrect_data",
                "low",
                "brand",
                "brand appears unnormalized lowercase",
                brand,
            )
        )

    color = _safe_str(record.get("color"))
    if color and re.fullmatch(r"\d{5,}", color):
        issues.append(
            Issue(
                "incorrect_data",
                "medium",
                "color",
                "color looks like numeric swatch/id, not human-readable value",
                color,
            )
        )

    size = _safe_str(record.get("size"))
    if size and re.fullmatch(r"\d(?:\.\d+)?", size) and len(_safe_list(record.get("variants"))) > 0:
        issues.append(
            Issue(
                "incorrect_data",
                "medium",
                "size",
                "size looks like selector index/default, not normalized size label",
                size,
            )
        )


def _find_pollution(record: dict[str, Any], issues: list[Issue]) -> None:
    for field in OPTIONAL_SUSPECT_FIELDS:
        value = record.get(field)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            if _is_noise_text(text):
                issues.append(Issue("polluted_data", "medium", field, "UI/control noise pattern in text", text[:200]))
            if field == "description":
                trailing = re.search(r"((?:\b\d{1,2}(?:\.5)?\b\s*){8,})$", text)
                if trailing:
                    issues.append(
                        Issue(
                            "polluted_data",
                            "medium",
                            field,
                            "description has trailing size-like numeric list",
                            trailing.group(1).strip()[:200],
                        )
                    )
                if re.search(r"read reviews and buy .* at target\. choose from", text, re.I):
                    issues.append(
                        Issue(
                            "polluted_data",
                            "medium",
                            field,
                            "description looks like generic SEO/storefront copy, not product detail",
                            text[:200],
                        )
                    )
            continue

        if isinstance(value, list):
            if not value:
                continue
            noisy_samples: list[str] = []
            tiny_token_ratio_hits = 0
            for item in value:
                item_text = _safe_str(item)
                if not item_text:
                    continue
                if _is_noise_text(item_text):
                    noisy_samples.append(item_text[:160])
                if field in {"features", "description"} and _text_token_count(item_text) <= 2:
                    tiny_token_ratio_hits += 1
            if noisy_samples:
                issues.append(
                    Issue(
                        "polluted_data",
                        "medium",
                        field,
                        "list contains UI/control noise tokens",
                        noisy_samples[:5],
                    )
                )
            if field == "features" and len(value) >= 8 and tiny_token_ratio_hits >= max(4, len(value) // 2):
                issues.append(
                    Issue(
                        "polluted_data",
                        "high",
                        field,
                        "features list dominated by tiny/noisy tokens",
                        {
                            "total_items": len(value),
                            "tiny_items": tiny_token_ratio_hits,
                        },
                    )
                )
            if field == "tags":
                noisy_tag_prefixes = (
                    "clearance_",
                    "dropship_",
                    "dtlrexclusive_",
                    "employeepromoexclude_",
                    "instoreonly_",
                    "lastsyncdatetime_",
                    "onlineonly_",
                    "promoexclude_",
                    "stylelimit_",
                    "unisexsizingeligible_",
                    "size_",
                    "stock_",
                    "sale_",
                )
                noisy_tags = [
                    _safe_str(item)
                    for item in value
                    if _safe_str(item).lower().startswith(noisy_tag_prefixes)
                ]
                if len(noisy_tags) >= 6:
                    issues.append(
                        Issue(
                            "polluted_data",
                            "high",
                            "tags",
                            "tags polluted by internal metadata tokens",
                            noisy_tags[:12],
                        )
                    )
                url_like_tags = [
                    _safe_str(item)
                    for item in value
                    if re.search(r"(?:^/shop/product/|https?://)", _safe_str(item), re.I)
                ]
                if len(url_like_tags) >= 3:
                    issues.append(
                        Issue(
                            "polluted_data",
                            "medium",
                            "tags",
                            "tags contain related-product URLs or links",
                            url_like_tags[:8],
                        )
                    )


def _normalized_image_key(url: str) -> str:
    text = _safe_str(url)
    if not text:
        return ""
    parsed = urlparse(text)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".lower()


def _find_image_issues(record: dict[str, Any], issues: list[Issue]) -> None:
    image_url = _safe_str(record.get("image_url"))
    additional = [_safe_str(item) for item in _safe_list(record.get("additional_images")) if _safe_str(item)]
    all_images = [item for item in [image_url, *additional] if item]
    if not all_images:
        return

    lowres_amazon = [url for url in all_images if "_AC_US40_" in url]
    if lowres_amazon and len(lowres_amazon) >= max(2, len(all_images) // 2):
        issues.append(
            Issue(
                "polluted_data",
                "high",
                "image_url/additional_images",
                "image set appears low-res thumbnail-only (Amazon _AC_US40_)",
                lowres_amazon[:4],
            )
        )

    if len(additional) >= 8:
        norm = [_normalized_image_key(url) for url in additional if _normalized_image_key(url)]
        if norm:
            unique = len(set(norm))
            duplicate_ratio = 1 - (unique / max(1, len(norm)))
            if duplicate_ratio >= 0.35:
                issues.append(
                    Issue(
                        "polluted_data",
                        "medium",
                        "additional_images",
                        "additional_images heavily duplicated across resized/query variants",
                        {"total": len(norm), "unique_base": unique},
                    )
                )


def _looks_like_variant_expected(record: dict[str, Any]) -> bool:
    host = _host_from_url(_safe_str(record.get("url")))
    if "discogs.com" in host:
        return False
    text = " ".join(
        [
            _safe_str(record.get("title")),
            _safe_str(record.get("category")),
            _safe_str(record.get("description"))[:600],
        ]
    )
    if any(rx.search(text) for rx in APPAREL_VARIANT_HINT_RES):
        return True
    url = _safe_str(record.get("url")).lower()
    if re.search(r"/(sneaker|shoe|footwear|apparel|clothing)/", url):
        return True
    host = _host_from_url(url)
    if host in {"www.goat.com", "stockx.com", "www.size.co.uk", "www.endclothing.com"}:
        return True
    desc = _safe_str(record.get("description"))
    if re.search(r"\b(size|sizes)\s*:\s*(?:please\s+select|[0-9xmsl])", desc, re.I):
        return True
    if re.search(r"((?:\b\d{1,2}(?:\.\d)?\b\s*){8,})$", desc):
        return True
    if _is_variant_size_value(_safe_str(record.get("size"))):
        return True
    return False


def _find_variant_issues(record: dict[str, Any], issues: list[Issue]) -> None:
    variants = _safe_list(record.get("variants"))
    variant_count = record.get("variant_count")

    if variant_count not in (None, ""):
        try:
            declared = int(str(variant_count))
            if declared != len(variants):
                issues.append(
                    Issue(
                        "logical_errors",
                        "medium",
                        "variant_count",
                        "variant_count mismatches variants length",
                        {"variant_count": declared, "actual": len(variants)},
                    )
                )
        except ValueError:
            issues.append(Issue("incorrect_data", "medium", "variant_count", "variant_count not int", variant_count))

    if not variants:
        if _looks_like_variant_expected(record):
            issues.append(
                Issue(
                    "incorrect_variants",
                    "high",
                    "variants",
                    "variants missing but product looks multi-variant",
                )
            )
        return

    if len(variants) >= 80:
        issues.append(Issue("incorrect_variants", "high", "variants", "suspiciously high variant volume", len(variants)))

    noisy_variant_rows = 0
    duplicate_signatures = 0
    seen_signatures: set[tuple[tuple[str, str], ...]] = set()

    for idx, variant in enumerate(variants):
        if not isinstance(variant, dict):
            issues.append(Issue("incorrect_variants", "high", "variants", f"variant index {idx} not object", variant))
            continue

        variant_url = _safe_str(variant.get("url"))
        if variant_url and not URL_RE.match(variant_url):
            issues.append(Issue("incorrect_variants", "medium", "variants.url", "variant url not http/https", variant_url))

        v_price = variant.get("price")
        if v_price not in (None, "") and not _looks_price(v_price):
            issues.append(Issue("incorrect_variants", "medium", "variants.price", "variant price not numeric", v_price))

        for key, value in variant.items():
            text = _safe_str(value)
            if not text:
                continue
            if _is_noise_text(text):
                noisy_variant_rows += 1
                break

        signature = _variant_signature(variant)
        if signature in seen_signatures and signature:
            duplicate_signatures += 1
        seen_signatures.add(signature)

    if noisy_variant_rows:
        sev = "high" if noisy_variant_rows >= max(3, len(variants) // 3) else "medium"
        issues.append(
            Issue(
                "incorrect_variants",
                sev,
                "variants",
                "variants contain UI/control noise values",
                {"noisy_variants": noisy_variant_rows, "total_variants": len(variants)},
            )
        )

    if duplicate_signatures >= max(2, len(variants) // 5):
        issues.append(
            Issue(
                "incorrect_variants",
                "medium",
                "variants",
                "many duplicate variant attribute signatures",
                {"duplicate_signatures": duplicate_signatures, "total_variants": len(variants)},
            )
        )


def _find_logical_errors(record: dict[str, Any], issues: list[Issue]) -> None:
    price = record.get("price")
    sale_price = record.get("sale_price")
    original_price = record.get("original_price")

    if _looks_price(price) and _looks_price(original_price):
        if float(str(price)) > float(str(original_price)):
            issues.append(
                Issue(
                    "logical_errors",
                    "medium",
                    "price/original_price",
                    "price greater than original_price",
                    {"price": price, "original_price": original_price},
                )
            )

    if _looks_price(price) and _looks_price(sale_price):
        if float(str(sale_price)) > float(str(price)):
            issues.append(
                Issue(
                    "logical_errors",
                    "low",
                    "sale_price/price",
                    "sale_price greater than price",
                    {"price": price, "sale_price": sale_price},
                )
            )

    title = _safe_str(record.get("title"))
    description = _safe_str(record.get("description"))
    if title and description and title.lower() == description.lower():
        issues.append(Issue("logical_errors", "low", "description", "description identical to title"))
    product_details = _safe_str(record.get("product_details"))
    if description and product_details and description[:200].lower() == product_details[:200].lower():
        issues.append(
            Issue(
                "logical_errors",
                "low",
                "description/product_details",
                "description and product_details look redundant",
            )
        )

    host = _host_from_url(_safe_str(record.get("url")))
    tags = [str(item) for item in _safe_list(record.get("tags"))]
    if "discogs.com" in host:
        discogs_noise = [
            token
            for token in tags
            if re.search(r"(labelrelationship|phonographic_copyright|published_by|distributed_by)", token, re.I)
        ]
        if discogs_noise:
            issues.append(
                Issue(
                    "logical_errors",
                    "high",
                    "url/tags",
                    "record likely non-ecommerce page misclassified as commerce product",
                    discogs_noise[:8],
                )
            )


def audit_record(record: dict[str, Any]) -> dict[str, Any]:
    issues: list[Issue] = []

    _find_missing_fields(record, issues)
    _find_incorrect_fields(record, issues)
    _find_pollution(record, issues)
    _find_image_issues(record, issues)
    _find_variant_issues(record, issues)
    _find_logical_errors(record, issues)

    url = _safe_str(record.get("url"))
    host = _host_from_url(url)

    severity_rank = {"high": 3, "medium": 2, "low": 1}
    max_severity = "none"
    for issue in issues:
        if severity_rank.get(issue.severity, 0) > severity_rank.get(max_severity, 0):
            max_severity = issue.severity

    category_counts = Counter(issue.category for issue in issues)

    return {
        "url": url,
        "host": host,
        "title": _safe_str(record.get("title")),
        "issue_count": len(issues),
        "max_severity": max_severity,
        "category_counts": dict(sorted(category_counts.items())),
        "issues": [issue.as_dict() for issue in issues],
    }


def _to_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            return [row for row in payload["results"] if isinstance(row, dict)]
        if isinstance(payload.get("records"), list):
            return [row for row in payload["records"] if isinstance(row, dict)]
        return [payload]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit crawler JSON output and emit agent-ready issue report.")
    parser.add_argument("--input", required=True, help="Path to JSON file.")
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory for markdown/json reports. Default: <input_dir>/agent_issue_reports",
    )
    parser.add_argument(
        "--fail-on",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="Exit non-zero if any record has severity >= fail-on.",
    )
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"input not found: {input_path}")

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    records = _to_records(payload)
    if not records:
        raise ValueError("no object records found in json")

    audited = [audit_record(record) for record in records]

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (
        Path(args.output_dir).resolve()
        if str(args.output_dir or "").strip()
        else (input_path.parent / "agent_issue_reports").resolve()
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"{stamp}__{input_path.stem}__issue_audit.json"
    generated_iso = datetime.now(UTC).isoformat()
    weighted_category_counts: Counter[str] = Counter()
    for row in audited:
        for key, value in dict(row["category_counts"]).items():
            weighted_category_counts[str(key)] += int(value)

    summary = {
        "source": str(input_path),
        "generated_at_utc": generated_iso,
        "record_count": len(audited),
        "records_with_issues": sum(1 for row in audited if row["issue_count"] > 0),
        "severity_counts": dict(sorted(Counter(row["max_severity"] for row in audited).items())),
        "category_counts": dict(sorted(weighted_category_counts.items())),
    }

    json_path.write_text(
        json.dumps({"summary": summary, "records": audited}, indent=2),
        encoding="utf-8",
    )

    print(f"Input: {input_path}")
    print(f"Records: {len(audited)}")
    print(f"With issues: {summary['records_with_issues']}")
    print(f"Severity counts: {summary['severity_counts']}")
    print(f"JSON report: {json_path}")

    threshold_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
    hit_rank = max(threshold_rank.get(row["max_severity"], 0) for row in audited)
    if hit_rank >= threshold_rank.get(args.fail_on, 0) and args.fail_on != "none":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
