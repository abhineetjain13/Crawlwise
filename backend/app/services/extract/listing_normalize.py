from __future__ import annotations

import re
from urllib.parse import urljoin

from app.services.normalizers import normalize_value, validate_value

_EMPTY_VALUES = (None, "", [], {})
_LABEL_ONLY_VALUES = {
    "color",
    "colors",
    "size",
    "sizes",
    "choose size",
    "choose color",
    "select size",
    "select color",
    "select option",
}
_NAVIGATION_VALUES = {
    "previous image",
    "next image",
    "previous",
    "next",
    "view color",
}
_VARIANT_COUNT_RE = re.compile(r"^\(?\d+\)?(?:\s+)?(?:colors?|sizes?)?$", re.I)
_DIMENSION_MEASUREMENT_RE = re.compile(r"(?i)\b(?:cm|mm|in|inch|inches|ft|oz|kg|g|lb|lbs|height|width|depth|length|diameter)\b|[0-9]\s*[x×]\s*[0-9]")
_SIZE_TOKEN_RE = re.compile(r"(?i)\b(?:eu[-\s]?)?\d{1,2}(?:\.\d+)?\b|(?:xs|s|m|l|xl|xxl|xxxl)\b")

_BASE_FIELDS = {
    "title",
    "url",
    "apply_url",
    "image_url",
    "additional_images",
    "price",
    "sale_price",
    "original_price",
    "currency",
    "brand",
    "sku",
    "part_number",
    "color",
    "size",
    "availability",
    "rating",
    "review_count",
    "description",
    "category",
    "company",
    "location",
    "salary",
    "department",
    "job_id",
    "job_type",
    "posted_date",
    "dimensions",
    "slug",
    "id",
    "materials",
}


def _is_job_surface(surface: str) -> bool:
    normalized = str(surface or "").strip().lower()
    return normalized == "job" or normalized.startswith("job_")


def canonical_listing_fields(surface: str, target_fields: set[str]) -> set[str]:
    allowed = set(_BASE_FIELDS)
    if _is_job_surface(surface):
        allowed.update({"company", "location", "salary", "department", "job_id", "job_type", "posted_date"})
    else:
        allowed.update({"price", "image_url", "brand", "color", "size"})
    allowed.update({field for field in target_fields if field})
    return allowed


def normalize_listing_record(
    record: dict,
    *,
    surface: str,
    page_url: str,
    target_fields: set[str],
) -> dict:
    allowed_fields = canonical_listing_fields(surface, target_fields)
    normalized: dict = {}

    for key, value in dict(record or {}).items():
        if str(key).startswith("_"):
            normalized[key] = value
            continue
        if key not in allowed_fields:
            continue
        cleaned = _normalize_field_value(key, value, page_url=page_url)
        if cleaned in _EMPTY_VALUES:
            continue
        if _should_reject_text_value(key, cleaned):
            continue
        normalized[key] = cleaned

    if _is_job_surface(surface):
        normalized.pop("currency", None)
        normalized.pop("image_url", None)
        normalized.pop("additional_images", None)
        if normalized.get("price") not in _EMPTY_VALUES and normalized.get("salary") in _EMPTY_VALUES:
            normalized["salary"] = normalized.pop("price")
        for field_name in ("price", "sale_price", "original_price", "brand", "color", "size", "sku", "part_number", "availability", "rating", "review_count", "discount_amount", "discount_percentage"):
            normalized.pop(field_name, None)

    # Drop dimensions if it duplicates size
    if _dimensions_duplicate_size(normalized.get("dimensions"), normalized.get("size")):
        normalized.pop("dimensions", None)

    return normalized


def _normalize_field_value(field_name: str, value: object, *, page_url: str) -> object:
    if value in _EMPTY_VALUES:
        return None
    if field_name in {"url", "apply_url", "image_url"}:
        text = str(value).strip()
        return urljoin(page_url, text) if text and page_url else text
    if field_name == "additional_images":
        if isinstance(value, (list, tuple, set)):
            parts = [
                urljoin(page_url, str(part).strip()) if page_url else str(part).strip()
                for part in value
                if str(part).strip()
            ]
        else:
            parts = [
                urljoin(page_url, str(part).strip()) if page_url else str(part).strip()
                for part in str(value).split(",")
                if str(part).strip()
            ]
        deduped = list(dict.fromkeys(parts))
        return ", ".join(deduped)
    if field_name in {"price", "sale_price", "original_price", "salary", "review_count", "rating"}:
        if isinstance(value, str):
            return " ".join(value.split()).strip()
        return value
    normalized = normalize_value(field_name, value)
    return validate_value(field_name, normalized)


def _should_reject_text_value(field_name: str, value: object) -> bool:
    text = " ".join(str(value or "").split()).strip().lower()
    if not text:
        return True
    if text in _LABEL_ONLY_VALUES or text in _NAVIGATION_VALUES:
        return True
    if field_name in {"color", "size"} and _VARIANT_COUNT_RE.fullmatch(text):
        return True
    return False


def _dimensions_duplicate_size(dimensions: object, size: object) -> bool:
    dimensions_text = " ".join(str(dimensions or "").split()).strip()
    size_text = " ".join(str(size or "").split()).strip()
    if not dimensions_text or not size_text:
        return False
    if dimensions_text == size_text:
        return True
    if _DIMENSION_MEASUREMENT_RE.search(dimensions_text):
        return False

    dimension_tokens = _normalized_size_tokens(dimensions_text)
    size_tokens = _normalized_size_tokens(size_text)
    if not dimension_tokens or not size_tokens:
        return False
    overlap = len(dimension_tokens & size_tokens)
    baseline = max(len(dimension_tokens), len(size_tokens))
    return baseline > 0 and (overlap / baseline) >= 0.8


def _normalized_size_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for match in _SIZE_TOKEN_RE.finditer(value or ""):
        token = match.group(0).strip().lower().replace(" ", "")
        token = token.replace("eu", "eu-") if token.startswith("eu") and "-" not in token else token
        tokens.add(token)
    return tokens
