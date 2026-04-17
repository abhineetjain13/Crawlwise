from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from app.services.config.extraction_rules import EMPTY_SENTINEL_VALUES
from app.services.config.nested_field_rules import (
    NESTED_CATEGORY_KEYS,
    NESTED_CURRENCY_KEYS,
    NESTED_ORIGINAL_PRICE_KEYS,
    NESTED_PRICE_KEYS,
    NESTED_TEXT_KEYS,
    NESTED_URL_KEYS,
    PAGE_URL_CURRENCY_HINTS,
)
from app.services.field_alias_policy import field_allowed_for_surface

from . import (
    _extract_image_urls,
    extract_currency_hint,
    normalize_decimal_price,
    normalize_value,
    validate_value,
)

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
_DIMENSION_MEASUREMENT_RE = re.compile(
    r"(?i)\b(?:cm|mm|in|inch|inches|ft|oz|kg|g|lb|lbs|height|width|depth|length|diameter)\b|[0-9]\s*[x×]\s*[0-9]"
)
_SIZE_TOKEN_RE = re.compile(r"(?i)\b(?:eu[-\s]?)?\d{1,2}(?:\.\d+)?\b|\b(?:xs|s|m|l|xl|xxl|xxxl)\b")
_JOB_SURFACE_COMMERCE_FIELDS = (
    "price",
    "sale_price",
    "original_price",
    "currency",
    "image_url",
    "additional_images",
    "sku",
    "part_number",
    "brand",
    "availability",
    "rating",
    "review_count",
)
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


def canonical_listing_fields(surface: str, target_fields: set[str]) -> set[str]:
    allowed = set(_BASE_FIELDS)
    if _is_job_surface(surface):
        allowed.update(
            {
                "company",
                "location",
                "salary",
                "department",
                "job_id",
                "job_type",
                "posted_date",
            }
        )
    else:
        allowed.update({"price", "image_url", "brand", "color", "size"})
    allowed.update({field for field in target_fields if field})
    return allowed


def normalize_record_fields(
    record: dict[str, object],
    *,
    surface: str = "",
) -> dict[str, object]:
    normalized: dict[str, object] = {}
    normalized_surface = str(surface or "").strip().lower()

    for key, value in record.items():
        normalized_key = _normalize_committed_field_name(key)
        if not normalized_key:
            continue
        normalized_value = normalize_value(normalized_key, value)
        validated_value = validate_value(normalized_key, normalized_value)
        if validated_value in _EMPTY_VALUES:
            continue
        normalized[normalized_key] = validated_value

    if (
        normalized_surface != "job"
        and not normalized_surface.startswith("job_")
        and not str(normalized.get("currency") or "").strip()
    ):
        for field_name in ("price", "sale_price", "original_price", "salary"):
            currency_hint = extract_currency_hint(normalized.get(field_name))
            if currency_hint:
                normalized["currency"] = currency_hint
                break

    return normalized


def normalize_review_value(value: object) -> object | None:
    if value in _EMPTY_VALUES:
        return None
    if isinstance(value, (list, dict)):
        return value
    text = _clean_page_text(value)
    if not text or text.lower() in EMPTY_SENTINEL_VALUES:
        return None
    return text


def review_values_equal(left: object, right: object) -> bool:
    normalized_left = normalize_review_value(left)
    normalized_right = normalize_review_value(right)
    if normalized_left is None and normalized_right is None:
        return True
    if normalized_left is None or normalized_right is None:
        return False
    return normalized_left == normalized_right


def passes_detail_quality_gate(field_name: str, value: object) -> bool:
    if value in _EMPTY_VALUES:
        return False
    validated = validate_value(field_name, value)
    if validated in _EMPTY_VALUES:
        return False
    if isinstance(validated, str):
        text = " ".join(validated.split()).strip()
        return bool(text and text.lower() not in EMPTY_SENTINEL_VALUES)
    return True


def normalize_listing_record(
    record: dict,
    *,
    surface: str,
    page_url: str,
    target_fields: set[str],
) -> dict:
    allowed_fields = canonical_listing_fields(surface, target_fields)
    normalized: dict = {}
    interpret_integral_price_as_cents = _looks_like_shopify_money_record(record)

    for key, value in dict(record or {}).items():
        if str(key).startswith("_"):
            normalized[key] = value
            continue
        if key not in allowed_fields:
            continue
        cleaned = _normalize_output_field_value(
            key,
            value,
            page_url=page_url,
            interpret_integral_price_as_cents=interpret_integral_price_as_cents,
        )
        if cleaned in _EMPTY_VALUES:
            continue
        if _should_reject_text_value(key, cleaned):
            continue
        normalized[key] = cleaned

    normalized = apply_surface_record_contract(
        normalized,
        surface=surface,
        raw_item=record.get("_raw_item") if isinstance(record, dict) else None,
        page_url=page_url,
    )

    if _dimensions_duplicate_size(normalized.get("dimensions"), normalized.get("size")):
        normalized.pop("dimensions", None)

    return normalized


def apply_surface_record_contract(
    record: dict,
    *,
    surface: str,
    raw_item: dict | None = None,
    page_url: str = "",
) -> dict:
    if not record:
        return record
    if not _is_job_surface(surface):
        if record.get("price") not in _EMPTY_VALUES and record.get("currency") in _EMPTY_VALUES:
            inferred_currency = _infer_currency_from_page_url(page_url)
            if inferred_currency:
                record["currency"] = inferred_currency
        return record

    _promote_job_salary(record)
    _normalize_job_title(record)
    _fill_missing_job_identifier(record, raw_item or {})
    _fill_missing_job_urls(
        record,
        raw_item or {},
        page_url=str(record.get("_payload_url") or page_url),
    )
    _strip_job_commerce_fields(record)
    if record.get("category") in _EMPTY_VALUES and record.get("department") not in _EMPTY_VALUES:
        record["category"] = record["department"]
    return record


def normalize_listing_field_value(
    canonical: str,
    value: object,
    *,
    page_url: str,
) -> object | None:
    from app.services.extract.listing_quality import (
        looks_like_transactional_url_for_listing,
    )

    if value in _EMPTY_VALUES:
        return None
    if canonical == "url":
        if isinstance(value, list):
            valid_urls: list[str] = []
            for item in value:
                normalized_item = normalize_listing_field_value(
                    canonical,
                    item,
                    page_url=page_url,
                )
                text = str(normalized_item or "").strip()
                if text and not any(token in text for token in ("[{", "{", "[")):
                    valid_urls.append(text)
            deduped_urls = list(dict.fromkeys(valid_urls))
            return deduped_urls[0] if len(deduped_urls) == 1 else None
        resolved = _coerce_nested_text(value, keys=NESTED_URL_KEYS) if isinstance(value, dict) else value
        text = str(resolved or "").strip()
        if not text or any(token in text for token in ("[{", "{", "[")):
            return None
        if text and page_url and not text.startswith(("http://", "https://", "/")):
            parsed = urlparse(page_url)
            origin = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else page_url
            if "/" not in text or _looks_like_product_short_path(text):
                resolved_url = urljoin(origin, text)
                cleaned_url = _strip_tracking_query_params(str(resolved_url or ""))
                return None if looks_like_transactional_url_for_listing(cleaned_url) else cleaned_url
        resolved_url = urljoin(page_url, text) if text and page_url else text or None
        cleaned_url = _strip_tracking_query_params(str(resolved_url or ""))
        return None if looks_like_transactional_url_for_listing(cleaned_url) else cleaned_url
    if canonical == "image_url":
        images = _extract_image_urls(value, base_url=page_url)
        return images[0] if images else None
    if canonical == "additional_images":
        images = _extract_image_urls(value, base_url=page_url)
        if not images:
            return None
        return ", ".join(images[1:] if len(images) > 1 else images)
    if canonical in {"price", "sale_price"} and isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_PRICE_KEYS)
        return str(nested).strip() if nested not in _EMPTY_VALUES else None
    if canonical == "original_price" and isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_ORIGINAL_PRICE_KEYS)
        return str(nested).strip() if nested not in _EMPTY_VALUES else None
    if canonical == "currency" and isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_CURRENCY_KEYS)
        return str(nested).strip() if nested not in _EMPTY_VALUES else None
    if canonical in {"title", "brand"} and isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_TEXT_KEYS)
        return str(nested).strip() if nested not in _EMPTY_VALUES else None
    if canonical == "category" and isinstance(value, dict):
        nested = _coerce_nested_category(value)
        return nested or None
    if isinstance(value, list):
        scalar_values = []
        for item in value:
            normalized = normalize_listing_field_value(canonical, item, page_url=page_url)
            if normalized in _EMPTY_VALUES:
                continue
            scalar_values.append(str(normalized).strip())
        return ", ".join(scalar_values) if scalar_values else None
    if isinstance(value, dict):
        nested = _coerce_nested_text(value, keys=NESTED_TEXT_KEYS)
        if nested in _EMPTY_VALUES:
            return None
        return str(nested).strip()
    return str(value).strip() if isinstance(value, str) else value


def _strip_tracking_query_params(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if not parsed.query:
        return parsed.geturl()
    kept_items = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = str(key or "").strip().lower()
        if lowered.startswith("utm_") or lowered.startswith("a_ajs_"):
            continue
        if lowered in {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid"}:
            continue
        kept_items.append((key, value))
    return parsed._replace(query=urlencode(kept_items, doseq=True)).geturl()


def normalize_ld_item(item: dict, surface: str, page_url: str) -> dict | None:
    record: dict = {}
    record["title"] = _normalize_listing_title_text(item.get("name") or "")

    url = item.get("url") or ""
    if url and page_url:
        url = urljoin(page_url, url)
    record["url"] = url

    images = _extract_image_urls(item.get("image"), base_url=page_url)
    if images:
        record["image_url"] = images[0]
        if len(images) > 1:
            record["additional_images"] = ", ".join(images[1:])

    if "ecommerce" in surface:
        offers = item.get("offers", {})
        if isinstance(offers, list) and offers:
            offers = offers[0]
        if isinstance(offers, dict):
            record["price"] = _first_present(
                offers.get("price"),
                offers.get("lowPrice"),
                "",
            )
            record["currency"] = offers.get("priceCurrency") or ""
            record["availability"] = offers.get("availability") or ""
        record["brand"] = _nested_name(item.get("brand"))
        record["sku"] = item.get("sku") or ""
        record["part_number"] = item.get("mpn") or item.get("partNumber") or ""
        record["description"] = item.get("description") or ""
        record["rating"] = _nested_value(item.get("aggregateRating"), "ratingValue")

    if "job" in surface:
        record["company"] = _nested_name(item.get("hiringOrganization"))
        location = item.get("jobLocation")
        if isinstance(location, dict):
            address = location.get("address", {})
            if isinstance(address, dict):
                record["location"] = (
                    address.get("addressLocality") or address.get("name") or ""
                )
            else:
                record["location"] = str(address)
        elif isinstance(location, str):
            record["location"] = location
        salary = item.get("baseSalary")
        if isinstance(salary, dict):
            val = salary.get("value", {})
            if isinstance(val, dict):
                min_val = val.get("minValue")
                max_val = val.get("maxValue")
                if min_val not in (None, "") and max_val not in (None, ""):
                    record["salary"] = f"{min_val}-{max_val}"
                elif min_val not in (None, ""):
                    record["salary"] = str(min_val)
                elif max_val not in (None, ""):
                    record["salary"] = str(max_val)
                else:
                    record["salary"] = ""
            else:
                record["salary"] = str(val)
        elif salary:
            record["salary"] = str(salary)
        record["description"] = item.get("description") or ""
        record["category"] = item.get("employmentType") or ""

    record = apply_surface_record_contract(
        {key: value for key, value in record.items() if value not in _EMPTY_VALUES},
        surface=surface,
        raw_item=item,
        page_url=page_url,
    )
    if record:
        record["_raw_item"] = item
    return record if record else None


def _is_job_surface(surface: str) -> bool:
    normalized = str(surface or "").strip().lower()
    return normalized == "job" or normalized.startswith("job_")


def _normalize_shopify_money_value(
    field_name: str,
    value: object,
    *,
    interpret_integral_as_cents: bool,
) -> object:
    if field_name not in {"price", "sale_price", "original_price"}:
        return value
    if not interpret_integral_as_cents:
        return value
    normalized = normalize_decimal_price(
        value,
        interpret_integral_as_cents=interpret_integral_as_cents,
    )
    return normalized if normalized is not None else value


def _normalize_output_field_value(
    field_name: str,
    value: object,
    *,
    page_url: str,
    interpret_integral_price_as_cents: bool,
) -> object:
    if value in _EMPTY_VALUES:
        return None
    cleaned = normalize_listing_field_value(field_name, value, page_url=page_url)
    if cleaned in _EMPTY_VALUES:
        return None
    cleaned = _normalize_shopify_money_value(
        field_name,
        cleaned,
        interpret_integral_as_cents=interpret_integral_price_as_cents,
    )
    if field_name in {"url", "apply_url", "image_url"}:
        text = str(cleaned).strip()
        return urljoin(page_url, text) if text and page_url else text
    if field_name == "additional_images":
        if isinstance(cleaned, (list, tuple, set)):
            parts = [
                urljoin(page_url, str(part).strip()) if page_url else str(part).strip()
                for part in cleaned
                if str(part).strip()
            ]
        else:
            parts = [
                urljoin(page_url, str(part).strip()) if page_url else str(part).strip()
                for part in str(cleaned).split(",")
                if str(part).strip()
            ]
        deduped = list(dict.fromkeys(parts))
        return ", ".join(deduped)
    if field_name in {"price", "sale_price", "original_price", "salary", "review_count", "rating"}:
        if isinstance(cleaned, str):
            return " ".join(cleaned.split()).strip()
        return cleaned
    normalized_value = normalize_value(field_name, cleaned, base_url=page_url)
    return validate_value(field_name, normalized_value)


def _looks_like_shopify_money_record(record: dict) -> bool:
    raw_item = record.get("_raw_item") if isinstance(record, dict) else None
    source = str(record.get("_source") or "").strip().lower() if isinstance(record, dict) else ""
    if not isinstance(raw_item, dict):
        return "shopify" in source
    shopify_keys = {
        "compare_at_price",
        "featured_image",
        "handle",
        "price_max",
        "price_min",
        "product_type",
        "shopify_id",
        "variants",
    }
    return bool(shopify_keys & set(raw_item))


def _normalize_committed_field_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    normalized = re.sub(r"\s+", "_", text.lower())
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def _clean_page_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\u00a0", " ")).strip()


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


def _coerce_nested_text(value: dict, *, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        nested = value.get(key)
        if nested not in _EMPTY_VALUES:
            return nested
    return None


def _coerce_nested_category(value: dict) -> str:
    for key in NESTED_CATEGORY_KEYS:
        nested = value.get(key)
        if isinstance(nested, list):
            parts = [str(part).strip() for part in nested if str(part).strip()]
            if parts:
                return " | ".join(parts)
        if nested not in _EMPTY_VALUES:
            return str(nested).strip()
    return ""


def _promote_job_salary(record: dict) -> None:
    if record.get("price") not in _EMPTY_VALUES and record.get("salary") in _EMPTY_VALUES:
        record["salary"] = record.pop("price")


def _normalize_job_title(record: dict) -> None:
    if not record.get("title"):
        return
    normalized_title = _normalize_listing_title_text(record.get("title"))
    if normalized_title:
        record["title"] = normalized_title


def _fill_missing_job_identifier(record: dict, raw_item: dict) -> None:
    if record.get("job_id") not in _EMPTY_VALUES:
        return
    inferred_job_id = _extract_generic_job_identifier(raw_item)
    if inferred_job_id:
        record["job_id"] = inferred_job_id


def _fill_missing_job_urls(record: dict, raw_item: dict, *, page_url: str) -> None:
    if record.get("url") not in _EMPTY_VALUES:
        return
    synthesized_url = _synthesize_job_detail_url(raw_item, page_url=page_url)
    if synthesized_url:
        record["url"] = synthesized_url
        record.setdefault("apply_url", synthesized_url)


def _strip_job_commerce_fields(record: dict) -> None:
    for commerce_field in _JOB_SURFACE_COMMERCE_FIELDS:
        record.pop(commerce_field, None)


def _extract_generic_job_identifier(item: dict) -> str:
    if not isinstance(item, dict):
        return ""
    for key in (
        "Id",
        "jobId",
        "job_id",
        "jobID",
        "OpportunityId",
        "opportunityId",
        "requisitionId",
        "requisition_id",
        "RequisitionNumber",
        "reqId",
        "req_id",
        "postingId",
        "posting_id",
        "openingId",
        "opening_id",
        "id",
    ):
        value = item.get(key)
        if value not in _EMPTY_VALUES:
            return " ".join(str(value).split()).strip()
    return ""


def _synthesize_job_detail_url(item: dict, *, page_url: str) -> str:
    if not isinstance(item, dict):
        return ""
    job_id = _extract_generic_job_identifier(item)
    if not job_id:
        return ""
    parsed = urlparse(str(page_url or "").strip())
    hostname = str(parsed.hostname or "").lower()
    if "saashr.com" not in hostname:
        return ""
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    path = parsed.path or ""
    if "/ta/rest/ui/recruitment/companies/" in path and "/job-requisitions" in path:
        company_code = path.split("/ta/rest/ui/recruitment/companies/", 1)[1].split("/", 1)[0]
        if company_code.startswith("%7C"):
            company_code = company_code[3:]
        path = f"/ta/{company_code}.careers" if company_code else path
    if ".careers" not in path or {"ein_id", "career_portal_id"} - set(params):
        return ""
    params["ShowJob"] = job_id
    return parsed._replace(path=path, query=urlencode(params)).geturl()


def _looks_like_product_short_path(value: str) -> bool:
    return bool(
        re.match(r"^p(?:/|[.-])[A-Za-z0-9][A-Za-z0-9._/-]*$", str(value or "").strip(), re.I)
    )


def _normalize_listing_title_text(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    text = re.sub(r"\s+([,;:/|])", r"\1", text)
    text = re.sub(r"([(/])\s+", r"\1", text)
    text = re.sub(r"\s+([)])", r"\1", text)
    text = re.sub(r"\s*[,;/|:-]+\s*$", "", text).strip()
    return text


def _infer_currency_from_page_url(page_url: str) -> str:
    raw_page_url = str(page_url or "").strip()
    if not raw_page_url:
        return ""
    url_path = urlparse(raw_page_url).path.lower()
    if not url_path:
        return ""
    for pattern, currency in PAGE_URL_CURRENCY_HINTS.items():
        if pattern.search(url_path):
            return currency
    return ""


def _first_present(*values: object) -> object:
    for value in values:
        if value not in _EMPTY_VALUES:
            return value
    return ""


def _nested_name(obj: object) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return obj.get("name") or ""
    return ""


def _nested_value(obj: object, key: str) -> str:
    if isinstance(obj, dict):
        return str(obj.get(key, ""))
    return ""
