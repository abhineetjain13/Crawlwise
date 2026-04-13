from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from app.services.config.field_mappings import get_surface_field_aliases
from app.services.config.nested_field_rules import (
    NESTED_CATEGORY_KEYS,
    NESTED_CURRENCY_KEYS,
    NESTED_ORIGINAL_PRICE_KEYS,
    NESTED_PRICE_KEYS,
    NESTED_TEXT_KEYS,
    NESTED_URL_KEYS,
)
from app.services.extract.listing_card_extractor import (
    _harvest_product_url_from_item,
    _infer_currency_from_page_url,
    _normalize_listing_title_text,
)
from app.services.extract.listing_quality import (
    looks_like_transactional_url_for_listing,
)
from app.services.extract.shared_logic import (
    coerce_nested_text as _coerce_nested_text,
    extract_image_candidates as _extract_image_candidates,
    find_alias_values as _find_alias_values,
    resolve_slug_url,
)

_EMPTY_VALUES = (None, "", [], {})
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


def _normalize_generic_item(item: dict, surface: str, page_url: str) -> dict | None:
    if _looks_like_listing_variant_option(item, surface=surface):
        return None
    product_search_record = _normalize_product_search_item(item, page_url=page_url)
    if product_search_record:
        product_search_record["_raw_item"] = item
        return product_search_record

    record: dict = {}
    for canonical, aliases in get_surface_field_aliases(surface).items():
        values = [
            *_preferred_generic_item_values(item, canonical, surface=surface),
            *_find_alias_values(item, [canonical, *aliases], max_depth=4),
        ]
        for value in values:
            normalized = _normalize_listing_value(canonical, value, page_url=page_url)
            if normalized in _EMPTY_VALUES:
                continue
            record[canonical] = normalized
            break

    if record.get("image_url") in _EMPTY_VALUES and record.get("additional_images") not in _EMPTY_VALUES:
        image_candidates = [
            part.strip()
            for part in str(record["additional_images"]).split(",")
            if part.strip()
        ]
        if image_candidates:
            record["image_url"] = image_candidates[0]
            if len(image_candidates) > 1:
                record["additional_images"] = ", ".join(image_candidates[1:])
            else:
                record.pop("additional_images", None)

    raw_slug = item.get("slug")
    slug_url = ""
    if record.get("url") in _EMPTY_VALUES and raw_slug not in _EMPTY_VALUES:
        slug_url = resolve_slug_url(str(raw_slug), page_url=page_url)
        if slug_url:
            record["url"] = slug_url

    if "ecommerce" in str(surface or "").lower() and record.get("url") in _EMPTY_VALUES:
        harvested = _harvest_product_url_from_item(item, page_url=page_url)
        if harvested:
            record["url"] = harvested

    record = _apply_surface_record_contract(
        record,
        surface=surface,
        raw_item=item,
        page_url=page_url,
    )

    if (
        "job" not in str(surface or "").lower()
        and record.get("price") not in _EMPTY_VALUES
        and record.get("currency") in _EMPTY_VALUES
    ):
        inferred_currency = _infer_currency_from_page_url(page_url)
        if inferred_currency:
            record["currency"] = inferred_currency

    # Reuses the earlier _resolve_slug_url result instead of resolving twice.
    if (
        "ecommerce" in str(surface or "").lower()
        and record.get("url") in _EMPTY_VALUES
        and raw_slug in _EMPTY_VALUES
        and record.get("price") in _EMPTY_VALUES
    ):
        return None

    if record:
        record["_raw_item"] = item
    return record if record else None


def _apply_surface_record_contract(
    record: dict,
    *,
    surface: str,
    raw_item: dict | None = None,
    page_url: str = "",
) -> dict:
    if not record or "job" not in str(surface or "").lower():
        return record

    _promote_job_salary(record)
    _normalize_job_title(record)
    _fill_missing_job_identifier(record, raw_item or {})
    _fill_missing_job_urls(record, raw_item or {}, page_url=page_url)
    _strip_job_commerce_fields(record)
    return record


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


def _preferred_generic_item_values(
    item: dict,
    canonical: str,
    surface: str = "",
) -> list[object]:
    if canonical == "title":
        preferred_keys = (
            "name",
            "title",
            "productName",
            "product_name",
            "headline",
            "job_title",
        )
        return [item[key] for key in preferred_keys if key in item and item[key] not in _EMPTY_VALUES]
    if canonical == "location" and "job" in str(surface or "").lower():
        preferred_values: list[object] = []
        direct_location = item.get("location")
        if direct_location not in _EMPTY_VALUES:
            preferred_values.append(direct_location)
        locations = item.get("locations")
        if isinstance(locations, list):
            for location in locations:
                if isinstance(location, dict) and location.get("name") not in _EMPTY_VALUES:
                    preferred_values.append(location["name"])
                    break
                if location not in _EMPTY_VALUES:
                    preferred_values.append(location)
                    break
        return preferred_values
    if canonical == "url":
        preferred_keys = (
            "product_full_url",
            "product_short_url",
            "productUrl",
            "product_url",
            "detailUrl",
            "detail_url",
            "applyUrl",
            "apply_url",
            "url",
            "href",
        )
        return [item[key] for key in preferred_keys if key in item and item[key] not in _EMPTY_VALUES]
    if canonical == "image_url":
        preferred_keys = (
            "imageUrl",
            "image_url",
            "primaryImage",
            "primary_image",
            "product_images",
        )
        return [item[key] for key in preferred_keys if key in item and item[key] not in _EMPTY_VALUES]
    if canonical == "job_id" and "job" in str(surface or "").lower():
        preferred_keys = (
            "jobId",
            "job_id",
            "jobID",
            "requisitionId",
            "requisition_id",
            "reqId",
            "req_id",
            "postingId",
            "posting_id",
            "openingId",
            "opening_id",
            "id",
        )
        return [item[key] for key in preferred_keys if key in item and item[key] not in _EMPTY_VALUES]
    if canonical == "category" and "job" in str(surface or "").lower():
        preferred_keys = ("jobCategoryName", "jobCategory", "categoryName", "category")
        return [item[key] for key in preferred_keys if key in item and item[key] not in _EMPTY_VALUES]
    if canonical == "posted_date" and "job" in str(surface or "").lower():
        preferred_keys = ("postedDate", "PostedDate", "publishDate", "datePosted")
        return [item[key] for key in preferred_keys if key in item and item[key] not in _EMPTY_VALUES]
    if canonical == "description" and "job" in str(surface or "").lower():
        preferred_keys = ("briefDescription", "BriefDescription", "description", "summary")
        return [item[key] for key in preferred_keys if key in item and item[key] not in _EMPTY_VALUES]
    return []


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
    return _default_job_detail_url_synthesis(item, page_url=page_url)


def _clean_identifier(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _default_job_detail_url_synthesis(item: dict, *, page_url: str) -> str:
    job_id = _extract_generic_job_identifier(item)
    if not job_id:
        return ""
    parsed = urlparse(str(page_url or "").strip())
    hostname = str(parsed.hostname or "").lower()
    if "saashr.com" in hostname:
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        path = parsed.path or ""
        if "/ta/rest/ui/recruitment/companies/" in path and "/job-requisitions" in path:
            company_code = path.split("/ta/rest/ui/recruitment/companies/", 1)[1].split("/", 1)[0]
            if company_code.startswith("%7C"):
                company_code = company_code[3:]
            path = f"/ta/{company_code}.careers" if company_code else path
        if ".careers" in path and {"ein_id", "career_portal_id"} <= set(params):
            params["ShowJob"] = job_id
            return parsed._replace(path=path, query=urlencode(params)).geturl()
    return ""


def _looks_like_listing_variant_option(item: dict, *, surface: str) -> bool:
    if "ecommerce" not in str(surface or "").lower():
        return False
    if any(
        item.get(key) not in _EMPTY_VALUES
        for key in ("name", "title", "productName", "product_name", "headline")
    ):
        return False

    detail_link = item.get("detailPageLink")
    detail_href = detail_link.get("href") if isinstance(detail_link, dict) else ""
    variant_label = str(
        item.get("label")
        or item.get("labelEn")
        or item.get("labelFr")
        or item.get("color")
        or item.get("colorName")
        or ""
    ).strip()
    variant_id = str(
        item.get("skuId") or item.get("commercialCode") or item.get("twelvenc") or ""
    ).strip()
    image = item.get("image")
    image_src = image.get("src") if isinstance(image, dict) else str(image or "")
    has_swatch_image = "color-swatches" in str(image_src or "").lower()
    has_assets = isinstance(item.get("assets"), list) and bool(item.get("assets"))
    has_price = item.get("price") not in _EMPTY_VALUES

    return bool(detail_href and variant_label and variant_id and has_price and (has_swatch_image or has_assets))


def _normalize_product_search_item(item: dict, *, page_url: str) -> dict | None:
    attributes = item.get("attributes")
    if not _is_product_search_item(item, attributes):
        return None

    record = _product_search_base_record(item, page_url=page_url)
    _append_product_search_images(record, item, page_url=page_url)
    _append_product_search_attributes(record, attributes)
    return _compact_product_search_record(record)


def _is_product_search_item(item: dict, attributes: object) -> bool:
    typename = str(item.get("__typename") or "").strip()
    product_number = str(item.get("productNumber") or item.get("productKey") or "").strip()
    name = str(item.get("name") or "").strip()
    return typename == "Product" and bool(product_number) and bool(name) and isinstance(attributes, list)


def _product_search_base_record(item: dict, *, page_url: str) -> dict[str, object]:
    return {
        "title": str(item.get("name") or "").strip(),
        "sku": str(item.get("productNumber") or item.get("productKey") or "").strip(),
        "description": str(item.get("description") or "").strip() or None,
        "brand": _nested_name(item.get("brand")) or None,
        "url": _product_search_detail_url(item, page_url=page_url) or None,
    }


def _append_product_search_images(
    record: dict[str, object],
    item: dict,
    *,
    page_url: str,
) -> None:
    image_candidates = _extract_image_candidates(
        _product_search_images(item),
        page_url=page_url,
    )
    if not image_candidates:
        return
    record["image_url"] = image_candidates[0]
    if len(image_candidates) > 1:
        record["additional_images"] = ", ".join(image_candidates[1:])


def _append_product_search_attributes(
    record: dict[str, object],
    attributes: list[object],
) -> None:
    attribute_values = _product_search_attribute_map(attributes)
    dimensions = _product_search_dimensions(attributes)
    for field_name, value in (
        ("materials", attribute_values.get("material")),
        ("dimensions", dimensions),
        ("size", attribute_values.get("packaging")),
    ):
        if value:
            record[field_name] = value


def _compact_product_search_record(record: dict[str, object]) -> dict | None:
    compacted = {key: value for key, value in record.items() if value not in _EMPTY_VALUES}
    return compacted or None


def _product_search_detail_url(item: dict, *, page_url: str) -> str:
    page_origin = ""
    parsed = urlparse(page_url)
    if parsed.scheme and parsed.netloc:
        page_origin = f"{parsed.scheme}://{parsed.netloc}"
    for candidate in (item.get("url"), item.get("productUrl"), item.get("href")):
        text = str(candidate or "").strip()
        if text:
            return urljoin(page_url, text) if page_origin else text

    brand_key = ""
    brand = item.get("brand")
    if isinstance(brand, dict):
        brand_key = str(brand.get("key") or brand.get("erpKey") or brand.get("name") or "").strip().lower()
    product_key = str(item.get("productKey") or item.get("productNumber") or "").strip().lower()
    if not page_origin or not brand_key or not product_key:
        return ""
    locale_match = re.search(r"/([A-Za-z]{2})/([A-Za-z]{2})/", page_url)
    locale_prefix = f"/{locale_match.group(1)}/{locale_match.group(2)}" if locale_match else ""
    return f"{page_origin}{locale_prefix}/product/{brand_key}/{product_key}"


def _product_search_images(item: dict) -> list[dict | str]:
    images = item.get("images")
    if not isinstance(images, list):
        return []
    normalized: list[dict | str] = []
    for image in images:
        if isinstance(image, dict):
            normalized.append(
                {
                    "url": image.get("largeUrl")
                    or image.get("mediumUrl")
                    or image.get("smallUrl")
                    or image.get("url"),
                }
            )
        elif isinstance(image, str):
            normalized.append(image)
    return normalized


def _product_search_attribute_map(attributes: list[object]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        label = str(attribute.get("label") or "").strip().lower()
        values = attribute.get("values")
        if not label or not isinstance(values, list):
            continue
        normalized_values = [
            " ".join(str(value or "").replace("&#160;", " ").split()).strip()
            for value in values
            if str(value or "").strip()
        ]
        if normalized_values:
            mapped[label] = " | ".join(normalized_values)
    return mapped


def _product_search_dimensions(attributes: list[object]) -> str:
    dimension_rows: list[str] = []
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        label = " ".join(
            str(attribute.get("label") or "").replace("&#160;", " ").split()
        ).strip()
        values = attribute.get("values")
        if not label or not isinstance(values, list):
            continue
        if not re.search(
            r"(?:\b(?:o\.d\.|i\.d\.|height|width|depth|diameter|length|thread|size)\b|×)",
            label,
            re.I,
        ):
            continue
        normalized_values = [
            " ".join(str(value or "").replace("&#160;", " ").split()).strip()
            for value in values
            if str(value or "").strip()
        ]
        if normalized_values:
            dimension_rows.append(f"{label}: {' | '.join(normalized_values)}")
    return " | ".join(dimension_rows)


def _normalize_listing_value(canonical: str, value: object, *, page_url: str) -> object | None:
    if value in _EMPTY_VALUES:
        return None
    if canonical == "url":
        if isinstance(value, list):
            valid_urls: list[str] = []
            for item in value:
                normalized_item = _normalize_listing_value(canonical, item, page_url=page_url)
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
                return None if looks_like_transactional_url_for_listing(resolved_url) else resolved_url
        resolved_url = urljoin(page_url, text) if text and page_url else text or None
        return None if looks_like_transactional_url_for_listing(str(resolved_url or "")) else resolved_url
    if canonical == "image_url":
        images = _extract_image_candidates(value, page_url=page_url)
        return images[0] if images else None
    if canonical == "additional_images":
        images = _extract_image_candidates(value, page_url=page_url)
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
            normalized = _normalize_listing_value(canonical, item, page_url=page_url)
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


def _looks_like_product_short_path(value: str) -> bool:
    return bool(
        re.match(r"^p(?:/|[.-])[A-Za-z0-9][A-Za-z0-9._/-]*$", str(value or "").strip(), re.I)
    )


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


def _nested_name(obj: object) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return obj.get("name") or ""
    return ""
