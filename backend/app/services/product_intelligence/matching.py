from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from app.services.field_value_core import infer_brand_from_product_url, infer_brand_from_title_marker
from app.services.config.product_intelligence import (
    BRAND_ALIAS_MAP,
    BRAND_DOMAIN_MAP,
    DEFAULT_SCORE_LABEL_HIGH,
    DEFAULT_SCORE_LABEL_LOW,
    DEFAULT_SCORE_LABEL_MEDIUM,
    DEFAULT_SCORE_LABEL_UNCERTAIN,
    MATCH_SCORE_WEIGHTS,
    PRIVATE_LABEL_BRANDS,
    SOURCE_AVAILABILITY_FIELDS,
    SOURCE_BRAND_FIELDS,
    SOURCE_CURRENCY_FIELDS,
    SOURCE_GTIN_FIELDS,
    SOURCE_IMAGE_FIELDS,
    SOURCE_MPN_FIELDS,
    SOURCE_PRICE_FIELDS,
    SOURCE_SKU_FIELDS,
    SOURCE_TITLE_FIELDS,
    SOURCE_TYPE_AUTHORITY_BONUS,
    SOURCE_URL_FIELDS,
    product_intelligence_settings,
)


def normalize_brand(value: object) -> str:
    text = _normalize_text(value)
    normalized = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return BRAND_ALIAS_MAP.get(normalized, normalized)


def is_private_label(brand: object) -> bool:
    return normalize_brand(brand) in PRIVATE_LABEL_BRANDS


def source_domain(url: object) -> str:
    try:
        host = urlsplit(str(url or "")).hostname or ""
    except ValueError:
        return ""
    return host.removeprefix("www.").lower()


def extract_product_snapshot(record: object) -> dict[str, object]:
    data = dict(record or {}) if isinstance(record, dict) else {}
    source_url = _first_present(data, SOURCE_URL_FIELDS)
    brand = _first_present(data, SOURCE_BRAND_FIELDS)
    title = _first_present(data, SOURCE_TITLE_FIELDS)
    price_value = _first_present(data, SOURCE_PRICE_FIELDS)
    if not str(brand or "").strip():
        brand = _infer_brand(source_url=source_url, title=title)
    price = _as_float(price_value)
    return {
        "title": str(title or "").strip(),
        "brand": str(brand or "").strip(),
        "normalized_brand": normalize_brand(brand),
        "price": price,
        "currency": str(_first_present(data, SOURCE_CURRENCY_FIELDS) or _currency_from_price(price_value) or "").strip(),
        "image_url": str(_first_present(data, SOURCE_IMAGE_FIELDS) or "").strip(),
        "url": str(source_url or "").strip(),
        "sku": str(_first_present(data, SOURCE_SKU_FIELDS) or "").strip(),
        "mpn": str(_first_present(data, SOURCE_MPN_FIELDS) or "").strip(),
        "gtin": str(_first_present(data, SOURCE_GTIN_FIELDS) or "").strip(),
        "availability": str(_first_present(data, SOURCE_AVAILABILITY_FIELDS) or "").strip(),
        "raw": data,
    }


def score_candidate(
    *,
    source: dict[str, object],
    candidate: dict[str, object],
    source_type: str,
) -> dict[str, object]:
    reasons: dict[str, object] = {}
    score = 0.0
    source_title = str(source.get("title") or "")
    candidate_title = str(candidate.get("title") or "")
    title_similarity = _title_similarity(source_title, candidate_title)
    score += title_similarity * MATCH_SCORE_WEIGHTS["title_similarity"]
    reasons["title_similarity"] = round(title_similarity, 4)

    source_brand = normalize_brand(source.get("brand"))
    candidate_brand = normalize_brand(candidate.get("brand"))
    brand_match = bool(source_brand and candidate_brand and source_brand == candidate_brand)
    if brand_match:
        score += MATCH_SCORE_WEIGHTS["brand_match"]
    reasons["brand_match"] = brand_match

    identifier_match = _identifier_match(source, candidate)
    if identifier_match:
        score += MATCH_SCORE_WEIGHTS["identifier_match"]
    reasons["identifier_match"] = identifier_match

    price_match = _price_within_band(source.get("price"), candidate.get("price"))
    if price_match:
        score += MATCH_SCORE_WEIGHTS["price_band"]
    reasons["price_band_match"] = price_match

    authority_bonus = min(
        float(SOURCE_TYPE_AUTHORITY_BONUS.get(str(source_type or ""), 0.0)),
        MATCH_SCORE_WEIGHTS["source_authority"],
    )
    score += authority_bonus
    reasons["source_authority_bonus"] = round(authority_bonus, 4)

    final_score = round(min(max(score, 0.0), 1.0), 4)
    return {
        "score": final_score,
        "label": score_label(final_score),
        "reasons": reasons,
    }


def extract_serpapi_snapshot(
    payload: dict[str, object] | None,
    *,
    url: str,
    domain: str,
) -> dict[str, object]:
    data = dict(payload or {})
    raw_value = data.get("raw")
    raw_data = raw_value if isinstance(raw_value, dict) else {}
    merged = {**raw_data, **data}
    price_value = _first_present(merged, ("extracted_price", "price"))
    description = _first_present(merged, ("description", "snippet"))
    brand = _infer_brand(
        source_url=url,
        title=merged.get("title"),
        domain=domain,
        snippet=merged.get("snippet"),
        source=merged.get("source"),
    )
    return {
        "title": str(merged.get("title") or "").strip(),
        "brand": brand,
        "normalized_brand": normalize_brand(brand),
        "price": _as_float(price_value),
        "currency": _currency_from_price(price_value),
        "description": str(description or "").strip(),
        "image_url": str(_first_present(merged, ("thumbnail", "image", "favicon")) or "").strip(),
        "url": str(url or merged.get("link") or "").strip(),
        "sku": "",
        "mpn": "",
        "gtin": "",
        "availability": str(merged.get("availability") or "").strip(),
        "snippet": str(merged.get("snippet") or "").strip(),
        "source": str(merged.get("source") or merged.get("displayed_link") or domain or "").strip(),
        "raw": data,
    }


def build_serpapi_intelligence(
    *,
    source: dict[str, object],
    candidate_payload: dict[str, object] | None,
    candidate_url: str,
    candidate_domain: str,
    source_type: str,
) -> dict[str, object]:
    canonical = extract_serpapi_snapshot(
        candidate_payload,
        url=candidate_url,
        domain=candidate_domain,
    )
    deterministic = score_candidate(
        source=source,
        candidate=canonical,
        source_type=source_type,
    )
    return {
        "canonical_record": canonical,
        "confidence_score": deterministic["score"],
        "confidence_label": deterministic["label"],
        "score_reasons": deterministic["reasons"],
        "cleanup_source": "deterministic_serpapi",
        "llm_enrichment": {"requested": False, "applied": False},
    }


def score_label(score: float) -> str:
    if score >= 0.85:
        return DEFAULT_SCORE_LABEL_HIGH
    if score >= 0.60:
        return DEFAULT_SCORE_LABEL_MEDIUM
    if score >= 0.40:
        return DEFAULT_SCORE_LABEL_LOW
    return DEFAULT_SCORE_LABEL_UNCERTAIN


def _first_present(data: dict[str, object], fields: tuple[str, ...]) -> object:
    for field in fields:
        value = data.get(field)
        if value not in (None, "", [], {}):
            return value
    return None


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _infer_brand(
    *,
    source_url: object,
    title: object,
    domain: object = "",
    snippet: object = "",
    source: object = "",
) -> str:
    known_brand = _infer_known_brand(domain, source_url, title, snippet, source)
    if known_brand:
        return known_brand
    marker_brand = infer_brand_from_title_marker(title)
    if marker_brand:
        return marker_brand
    return infer_brand_from_product_url(url=str(source_url or ""), title=title) or ""


def _infer_known_brand(*values: object) -> str:
    haystack = " ".join(str(value or "") for value in values).casefold().replace("-", " ")
    normalized = re.sub(r"[^a-z0-9]+", " ", haystack)
    compact = re.sub(r"[^a-z0-9]+", "", haystack)
    known_brands = {*BRAND_ALIAS_MAP.values(), *BRAND_ALIAS_MAP.keys(), *BRAND_DOMAIN_MAP.keys()}
    for brand in sorted(known_brands, key=len, reverse=True):
        normalized_brand = brand.replace("-", " ")
        compact_brand = re.sub(r"[^a-z0-9]+", "", normalized_brand)
        if re.search(rf"\b{re.escape(normalized_brand)}\b", normalized) or (
            len(compact_brand) >= 5 and compact_brand in compact
        ):
            return BRAND_ALIAS_MAP.get(brand, brand)
    return ""


def _title_similarity(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    sequence = SequenceMatcher(None, " ".join(sorted(left_tokens)), " ".join(sorted(right_tokens))).ratio()
    return max(overlap, sequence)


def _token_set(value: object) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").casefold())
        if len(token) > 1
    }


def _identifier_match(source: dict[str, object], candidate: dict[str, object]) -> bool:
    for key in ("gtin", "mpn", "sku"):
        left = str(source.get(key) or "").strip().casefold()
        right = str(candidate.get(key) or "").strip().casefold()
        if left and right and left == right:
            return True
    return False


def _price_within_band(left: object, right: object) -> bool:
    left_price = _as_float(left)
    right_price = _as_float(right)
    if left_price is None or right_price is None or left_price <= 0 or right_price <= 0:
        return False
    return abs(left_price - right_price) / left_price <= product_intelligence_settings.price_band_ratio


def _as_float(value: object) -> float | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^0-9.,]+", "", str(value))
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = f"{head}.{tail}" if 1 <= len(tail) <= 3 else text.replace(",", "")
    text = re.sub(r"[^0-9.]+", "", text)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _currency_from_price(value: object) -> str:
    text = str(value or "")
    if "$" in text:
        return "USD"
    if "€" in text:
        return "EUR"
    if "£" in text:
        return "GBP"
    return ""
