# Product detail extraction — DOM sections, gallery, buy-box, product payloads.
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from app.services.config.extraction_rules import (
    CANDIDATE_NON_CONTENT_RICH_TEXT_TAGS,
    DIMENSION_KEYWORDS,
    SEMANTIC_AGGREGATE_SEPARATOR,
)
from app.services.config.extraction_rules import (
    LISTING_BUY_BOX_AVAILABILITY_PATTERN,
    LISTING_BUY_BOX_CURRENCY_SYMBOL_MAP,
    LISTING_BUY_BOX_HEADING_SCAN_TAGS,
    LISTING_BUY_BOX_HEADING_TEXTS,
    LISTING_BUY_BOX_PACK_SIZE_PATTERN,
    LISTING_BUY_BOX_PRICE_PATTERN,
    LISTING_BUY_BOX_REQUIRED_TOKENS,
    LISTING_BUY_BOX_SKU_PATTERN,
    LISTING_CARE_SECTION_LABEL,
    LISTING_MATERIALS_SECTION_LABEL,
    LISTING_PRODUCT_DETAIL_IMAGE_SOURCE_KEYS,
    LISTING_PRODUCT_DETAIL_LIST_SCAN_LIMIT,
    LISTING_PRODUCT_DETAIL_PRESENCE_ANY_KEYS,
    LISTING_PRODUCT_DETAIL_PRODUCT_BLOB_PATH,
    LISTING_PRODUCT_DETAIL_PROPS_PATH,
    LISTING_PRODUCT_DETAIL_REQUIRED_KEYS,
    LISTING_PRODUCT_DETAIL_TOP_LEVEL_PAYLOAD_KEYS,
    LISTING_STRUCTURED_SPEC_GROUP_LIMIT,
    LISTING_STRUCTURED_SPEC_GROUPS_KEY,
    LISTING_STRUCTURED_SPEC_ROW_LIMIT,
    LISTING_STRUCTURED_SPEC_SEARCH_MAX_DEPTH,
)
from app.services.requested_field_policy import normalize_requested_field
from app.services.extract.candidate_processing import (
    _coerce_scalar_for_dynamic_row,
    _contains_unresolved_template_value,
    _DYNAMIC_NUMERIC_FIELD_RE,
    _normalized_candidate_text,
    _parse_json_like_value,
    resolve_candidate_url as _resolve_candidate_url,
    normalize_html_rich_text as _normalize_html_rich_text,
)
from app.services.extract.field_classifier import (
    _dynamic_field_name_is_valid,
)


# ---------------------------------------------------------------------------
# Section content / rich text
# ---------------------------------------------------------------------------

def _section_content_text(node) -> str:
    if node is None:
        return ""
    if isinstance(node, Tag):
        return _rich_text_from_node(node).strip()
    html = node.decode_contents() if hasattr(node, "decode_contents") else str(node)
    return _normalize_html_rich_text(html).strip()


def _rich_text_from_node(node) -> str:
    if node is None:
        return ""
    if not isinstance(node, Tag):
        return _normalized_candidate_text(node)
    if node.name in CANDIDATE_NON_CONTENT_RICH_TEXT_TAGS:
        return ""

    if node.name in {"table", "tbody", "thead"}:
        rows: list[str] = []
        for tr in node.find_all("tr", recursive=False):
            cells = [
                _section_content_text(cell)
                for cell in tr.find_all(["th", "td"], recursive=False)
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(" | ".join(cells))
        return "\n".join(rows).strip()

    if node.name in {"ul", "ol"}:
        items = []
        for li in node.find_all("li", recursive=False):
            text = _section_content_text(li)
            if text:
                items.append(f"- {text}")
        return "\n".join(items).strip()

    if node.name == "li":
        parts = [
            _rich_text_from_node(child)
            if isinstance(child, Tag)
            else _normalized_candidate_text(child)
            for child in node.children
        ]
        return " ".join(part for part in parts if part).strip()

    block_names = {"p", "div", "section", "article", "details", "blockquote"}
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, Tag):
            child_text = _rich_text_from_node(child)
            if child_text:
                parts.append(child_text)
        else:
            text = _normalized_candidate_text(child)
            if text:
                parts.append(text)
    joiner = "\n\n" if node.name in block_names else "\n"
    rendered = joiner.join(part for part in parts if part).strip()
    if rendered:
        return rendered
    return _normalized_candidate_text(node.get_text(" ", strip=True))


def _collect_non_empty_section_text(nodes: object) -> list[str]:
    parts: list[str] = []
    for node in list(nodes or []):
        if not isinstance(node, Tag):
            continue
        text = _section_content_text(node)
        if text:
            parts.append(text)
    return parts


# ---------------------------------------------------------------------------
# DOM gallery
# ---------------------------------------------------------------------------

def _build_dom_gallery_rows(
    soup: BeautifulSoup, *, base_url: str
) -> dict[str, list[dict]]:
    image_urls: list[str] = []
    seen: set[str] = set()
    for node in soup.select(
        ".primary-images img[src], .primary-images-main img[src], img[itemprop='image'][src]"
    ):
        resolved = _resolve_candidate_url(node.get("src", ""), base_url)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        image_urls.append(resolved)
    if not image_urls:
        return {}
    rows: dict[str, list[dict]] = {
        "image_url": [{"value": image_urls[0], "source": "dom_gallery"}]
    }
    if len(image_urls) > 1:
        rows["additional_images"] = [
            {
                "value": ", ".join(image_urls[1:]),
                "source": "dom_gallery",
            }
        ]
    return rows


# ---------------------------------------------------------------------------
# Shopify content rows
# ---------------------------------------------------------------------------

def _build_shopify_content_rows(
    product: dict[str, object], *, base_url: str
) -> dict[str, list[dict]]:
    del base_url
    content = (
        product.get("content") or product.get("description") or product.get("body_html")
    )
    if not isinstance(content, str) or not content.strip():
        return {}

    soup = BeautifulSoup(content, "html.parser")
    paragraphs = _collect_non_empty_section_text(list(soup.find_all("p")))
    bullets = _collect_non_empty_section_text(list(soup.find_all("li")))

    rows: dict[str, list[dict]] = {}
    if paragraphs:
        rows.setdefault("description", []).append(
            {"value": paragraphs[0], "source": "shopify_content"}
        )
    if bullets:
        rows.setdefault("features", []).append(
            {
                "value": "\n".join(f"- {item}" for item in bullets),
                "source": "shopify_content",
            }
        )

    product_attributes: dict[str, object] = {}
    materials_value = ""
    for bullet in bullets:
        label_match = re.match(
            r"^(?P<label>[A-Za-z][A-Za-z0-9 /'&-]{1,40})\s*:\s*(?P<value>.+)$", bullet
        )
        if label_match:
            label = normalize_requested_field(label_match.group("label"))
            value = _normalized_candidate_text(label_match.group("value"))
            if label and value:
                product_attributes[label] = value
            continue
        lowered = bullet.lower()
        if not materials_value and (
            "%" in bullet
            or any(
                token in lowered
                for token in (
                    "cotton",
                    "polyester",
                    "elastane",
                    "nylon",
                    "wool",
                    "linen",
                )
            )
        ):
            materials_value = bullet
            product_attributes.setdefault("materials", bullet)
            continue
        if lowered.startswith("style "):
            product_attributes.setdefault("style", bullet.split(" ", 1)[1].strip())
            continue
        if lowered.startswith("model is "):
            product_attributes.setdefault("model", bullet)

    if materials_value:
        rows.setdefault("materials", []).append(
            {"value": materials_value, "source": "shopify_content"}
        )
    if product_attributes:
        rows.setdefault("product_attributes", []).append(
            {"value": product_attributes, "source": "shopify_content"}
        )
    return rows


# ---------------------------------------------------------------------------
# Product detail payload
# ---------------------------------------------------------------------------

def _find_product_detail_payload(payload: object) -> dict | None:
    if payload in (None, "", [], {}):
        return None
    if isinstance(payload, str):
        parsed = _parse_json_like_value(payload)
        if isinstance(parsed, (dict, list)):
            return _find_product_detail_payload(parsed)
        return None
    if isinstance(payload, dict):
        props_key = (
            LISTING_PRODUCT_DETAIL_PROPS_PATH[0]
            if LISTING_PRODUCT_DETAIL_PROPS_PATH
            else "props"
        )
        page_props_key = (
            LISTING_PRODUCT_DETAIL_PROPS_PATH[1]
            if len(LISTING_PRODUCT_DETAIL_PROPS_PATH) > 1
            else "pageProps"
        )
        data_key = (
            LISTING_PRODUCT_DETAIL_PROPS_PATH[2]
            if len(LISTING_PRODUCT_DETAIL_PROPS_PATH) > 2
            else "data"
        )
        detail_key = (
            LISTING_PRODUCT_DETAIL_PROPS_PATH[3]
            if len(LISTING_PRODUCT_DETAIL_PROPS_PATH) > 3
            else "getProductDetail"
        )
        props = payload.get(props_key)
        if isinstance(props, dict):
            page_props = props.get(page_props_key)
            if isinstance(page_props, dict):
                data = page_props.get(data_key)
                if isinstance(data, dict) and isinstance(data.get(detail_key), dict):
                    return data[detail_key]
                product_blob_key = (
                    LISTING_PRODUCT_DETAIL_PRODUCT_BLOB_PATH[-1]
                    if LISTING_PRODUCT_DETAIL_PRODUCT_BLOB_PATH
                    else "product"
                )
                product_blob = page_props.get(product_blob_key)
                if isinstance(product_blob, str):
                    parsed_product = _parse_json_like_value(product_blob)
                    if isinstance(parsed_product, dict):
                        return parsed_product
                if isinstance(page_props.get(product_blob_key), dict):
                    return page_props[product_blob_key]
        detail_top_level_key = (
            LISTING_PRODUCT_DETAIL_TOP_LEVEL_PAYLOAD_KEYS[0]
            if LISTING_PRODUCT_DETAIL_TOP_LEVEL_PAYLOAD_KEYS
            else "getProductDetail"
        )
        if isinstance(payload.get(detail_top_level_key), dict):
            return payload[detail_top_level_key]
        required_keys = set(LISTING_PRODUCT_DETAIL_REQUIRED_KEYS)
        if required_keys.issubset(payload.keys()):
            return payload
        if set(LISTING_PRODUCT_DETAIL_PRESENCE_ANY_KEYS) & set(payload.keys()):
            return payload
        for value in payload.values():
            found = _find_product_detail_payload(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload[:LISTING_PRODUCT_DETAIL_LIST_SCAN_LIMIT]:
            found = _find_product_detail_payload(item)
            if found:
                return found
    return None


def _normalize_product_detail_payload(
    detail: dict, *, base_url: str
) -> dict[str, object]:
    from app.services.extract.service import _extract_image_urls

    record: dict[str, object] = {}
    title = _normalized_candidate_text(detail.get("name"))
    if title:
        record["title"] = title
    material_ids = detail.get("materialIds")
    material_skus = (
        [
            _normalized_candidate_text(item)
            for item in material_ids
            if _normalized_candidate_text(item)
        ]
        if isinstance(material_ids, list)
        else []
    )
    sku = (
        material_skus[0]
        if material_skus
        else _normalized_candidate_text(
            detail.get("productNumber") or detail.get("productKey")
        )
    )
    if sku:
        record["sku"] = sku
    brand = detail.get("brand")
    if isinstance(brand, dict):
        brand_name = _normalized_candidate_text(brand.get("name"))
        if brand_name:
            record["brand"] = brand_name
    description = _normalized_candidate_text(detail.get("description"))
    if description:
        record["description"] = description
    synonyms = detail.get("synonyms")
    if isinstance(synonyms, list):
        values = [
            _normalized_candidate_text(item)
            for item in synonyms
            if _normalized_candidate_text(item)
        ]
        if values:
            record["synonyms"] = " | ".join(dict.fromkeys(values))

    images: list[str] = []
    for image_key in LISTING_PRODUCT_DETAIL_IMAGE_SOURCE_KEYS:
        images = _extract_image_urls(detail.get(image_key), base_url=base_url)
        if images:
            break
    if images:
        record["image_url"] = images[0]
        additional_images = images[1:]
        if additional_images:
            record["additional_images"] = ", ".join(additional_images)

    attributes = detail.get("attributes")
    if isinstance(attributes, list):
        attr_map = _normalize_product_detail_attributes(attributes)
        if attr_map.get("material"):
            record["materials"] = attr_map["material"]
        if attr_map.get("packaging"):
            record["size"] = attr_map["packaging"]
            record["pack_size"] = attr_map["packaging"]
        dimensions = _product_detail_dimensions(attr_map)
        if dimensions:
            record["dimensions"] = dimensions
    features_text = _product_detail_features(detail.get("features"))
    feature_tile_text = _product_detail_feature_tiles(
        ((detail.get("centreSectionTemplate") or {}).get("featureTiles"))
        if isinstance(detail.get("centreSectionTemplate"), dict)
        else None
    )
    if features_text and feature_tile_text:
        record["features"] = (
            f"{features_text}{SEMANTIC_AGGREGATE_SEPARATOR}{feature_tile_text}"
        )
    elif features_text:
        record["features"] = features_text
    elif feature_tile_text:
        record["features"] = feature_tile_text

    fit_text = _product_detail_fit_and_sizing(detail, base_url=base_url)
    if fit_text:
        record["fit_and_sizing"] = fit_text

    materials_and_care = _product_detail_materials_and_care(detail)
    if materials_and_care:
        record["materials_and_care"] = materials_and_care
    return record


def _normalize_product_detail_attributes(attributes: list[object]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        label = normalize_requested_field(attribute.get("label"))
        values = attribute.get("values")
        if not label or not isinstance(values, list):
            continue
        normalized_values = []
        for value in values:
            cleaned = _normalized_candidate_text(str(value).replace("&#160;", " "))
            if cleaned:
                normalized_values.append(cleaned)
        if normalized_values:
            mapped[label] = " | ".join(dict.fromkeys(normalized_values))
    return mapped


def _product_detail_dimensions(attr_map: dict[str, str]) -> str | None:
    rows: list[str] = []
    for label, value in attr_map.items():
        if (
            any(token in label.lower() for token in DIMENSION_KEYWORDS)
            or "thread" in label.lower()
        ):
            rows.append(f"{label.replace('_', ' ')}: {value}")
    return SEMANTIC_AGGREGATE_SEPARATOR.join(rows) if rows else None


def _product_detail_features(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    sections: list[str] = []
    for row in value[:12]:
        if not isinstance(row, dict):
            continue
        label = _normalized_candidate_text(row.get("label"))
        bullet_rows = row.get("value")
        bullets: list[str] = []
        for item in bullet_rows if isinstance(bullet_rows, list) else []:
            if isinstance(item, str):
                cleaned = _normalize_html_rich_text(item)
            else:
                cleaned = _normalized_candidate_text(item)
            if cleaned:
                bullets.append(cleaned)
        if not bullets:
            continue
        if label:
            sections.append(
                f"{label}:{SEMANTIC_AGGREGATE_SEPARATOR}"
                + SEMANTIC_AGGREGATE_SEPARATOR.join(f"- {item}" for item in bullets)
            )
        else:
            sections.append(
                SEMANTIC_AGGREGATE_SEPARATOR.join(f"- {item}" for item in bullets)
            )
    return SEMANTIC_AGGREGATE_SEPARATOR.join(sections) if sections else None


def _product_detail_feature_tiles(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    rows: list[str] = []
    for tile in value[:12]:
        if not isinstance(tile, dict):
            continue
        title = _normalized_candidate_text(tile.get("title") or tile.get("name"))
        description = _normalized_candidate_text(tile.get("description"))
        if title and description:
            rows.append(f"{title}: {description}")
        elif description:
            rows.append(description)
    return SEMANTIC_AGGREGATE_SEPARATOR.join(dict.fromkeys(rows)) if rows else None


def _product_detail_fit_and_sizing(detail: dict, *, base_url: str) -> str | None:
    rows: list[str] = []
    widgets = detail.get("bigWidgets")
    if isinstance(widgets, list):
        for widget in widgets[:12]:
            if not isinstance(widget, dict):
                continue
            label = _normalized_candidate_text(widget.get("label"))
            widget_type = _normalized_candidate_text(widget.get("type"))
            html = _normalize_html_rich_text(str(widget.get("html") or ""))
            html = _normalized_candidate_text(html)
            if (
                any(
                    token in f"{label} {widget_type}".lower()
                    for token in ("fit", "size", "sizing")
                )
                and html
            ):
                rows.append(f"{label}: {html}" if label else html)
    customer_tip = ""
    customer_tips = detail.get("customerTips")
    if isinstance(customer_tips, dict):
        customer_tip = _normalized_candidate_text(customer_tips.get("value"))
    if customer_tip:
        rows.append(f"Product tip: {customer_tip}")
    sizing_chart = detail.get("sizingChart")
    if isinstance(sizing_chart, dict):
        label = _normalized_candidate_text(sizing_chart.get("label"))
        url = _resolve_candidate_url(
            _normalized_candidate_text(sizing_chart.get("url")), base_url=base_url
        )
        if label and url:
            rows.append(f"{label}: {url}")
        elif label:
            rows.append(label)
    size = detail.get("size")
    if isinstance(size, dict):
        size_value = _normalized_candidate_text(size.get("value"))
        if size_value:
            rows.append(f"Size: {size_value}")
    return (
        SEMANTIC_AGGREGATE_SEPARATOR.join(dict.fromkeys(row for row in rows if row))
        or None
    )


def _product_detail_materials_and_care(detail: dict) -> str | None:
    rows: list[str] = []
    materials = [
        _normalized_candidate_text(item)
        for item in (
            detail.get("materials") if isinstance(detail.get("materials"), list) else []
        )
        if _normalized_candidate_text(item)
    ]
    if materials:
        rows.append(LISTING_MATERIALS_SECTION_LABEL)
        rows.extend(f"- {item}" for item in materials)
    care = [
        _normalized_candidate_text(item)
        for item in (
            detail.get("careInstructions")
            if isinstance(detail.get("careInstructions"), list)
            else []
        )
        if _normalized_candidate_text(item)
    ]
    if care:
        rows.append(LISTING_CARE_SECTION_LABEL)
        rows.extend(f"- {item}" for item in care)
    return SEMANTIC_AGGREGATE_SEPARATOR.join(rows) if rows else None


# ---------------------------------------------------------------------------
# Buy-box extraction
# ---------------------------------------------------------------------------

def _extract_buy_box_candidates(soup: BeautifulSoup) -> dict[str, str]:
    heading = next(
        (
            node
            for node in list(soup.find_all(list(LISTING_BUY_BOX_HEADING_SCAN_TAGS)))
            if _normalized_candidate_text(node.get_text(" ", strip=True)).lower()
            in LISTING_BUY_BOX_HEADING_TEXTS
        ),
        None,
    )
    if heading is None:
        return {}

    container = heading.parent
    text = ""
    while container is not None:
        text = _normalized_candidate_text(container.get_text(" ", strip=True))
        if any(token in text for token in LISTING_BUY_BOX_REQUIRED_TOKENS):
            break
        container = container.parent
    if not text:
        return {}

    normalized_text = re.sub(r"\s+", " ", text)
    candidates: dict[str, str] = {}
    pack_match = re.search(LISTING_BUY_BOX_PACK_SIZE_PATTERN, normalized_text, re.I)
    if pack_match:
        pack_value = _normalized_candidate_text(pack_match.group("value"))
        if pack_value:
            candidates["pack_size"] = pack_value
            candidates.setdefault("size", pack_value)
    sku_match = re.search(LISTING_BUY_BOX_SKU_PATTERN, normalized_text, re.I)
    if sku_match:
        candidates["sku"] = _normalized_candidate_text(sku_match.group("value"))
    availability_match = re.search(
        LISTING_BUY_BOX_AVAILABILITY_PATTERN, normalized_text, re.I
    )
    if availability_match:
        availability = _normalized_candidate_text(availability_match.group("value"))
        if availability:
            candidates["availability"] = availability
    else:
        # Fallback for when "Price" is not the next token
        alt_match = re.search(
            r"Availability\s+(?P<value>.+?)(?:\s+[A-Z][a-z]+|$)", normalized_text, re.I
        )
        if alt_match:
            candidates["availability"] = _normalized_candidate_text(
                alt_match.group("value")
            )
    price_match = re.search(LISTING_BUY_BOX_PRICE_PATTERN, normalized_text)
    if price_match:
        price_text = _normalized_candidate_text(price_match.group("value"))
        if price_text:
            candidates["price"] = price_text
            symbol = price_text[0]
            candidates["currency"] = LISTING_BUY_BOX_CURRENCY_SYMBOL_MAP.get(symbol, "")
    return {key: value for key, value in candidates.items() if value}


# ---------------------------------------------------------------------------
# Structured field value / spec map
# ---------------------------------------------------------------------------

def _find_key_values(payload: object, key: str, *, max_depth: int) -> list[object]:
    if max_depth <= 0 or payload in (None, "", [], {}):
        return []
    matches: list[object] = []
    if isinstance(payload, dict):
        for current_key, value in payload.items():
            if current_key == key:
                matches.append(value)
            matches.extend(_find_key_values(value, key, max_depth=max_depth - 1))
    elif isinstance(payload, list):
        for item in payload[:LISTING_PRODUCT_DETAIL_LIST_SCAN_LIMIT]:
            matches.extend(_find_key_values(item, key, max_depth=max_depth - 1))
    return matches


def _extract_structured_spec_map(payload: object) -> dict[str, str]:
    groups = _find_key_values(
        payload,
        LISTING_STRUCTURED_SPEC_GROUPS_KEY,
        max_depth=LISTING_STRUCTURED_SPEC_SEARCH_MAX_DEPTH,
    )
    structured: dict[str, str] = {}
    for group in groups:
        if not isinstance(group, list):
            continue
        for entry in group[:LISTING_STRUCTURED_SPEC_GROUP_LIMIT]:
            if not isinstance(entry, dict):
                continue
            specs = entry.get("specifications")
            if not isinstance(specs, list):
                continue
            for row in specs[:LISTING_STRUCTURED_SPEC_ROW_LIMIT]:
                if not isinstance(row, dict):
                    continue
                title = normalize_requested_field(
                    _normalized_candidate_text(row.get("title"))
                )
                content = _normalize_html_rich_text(str(row.get("content") or ""))
                if (
                    not title
                    or not content
                    or _contains_unresolved_template_value(content)
                ):
                    continue
                structured.setdefault(title, content)
    return structured


def _build_dynamic_semantic_rows(
    semantic: dict,
    *,
    surface: str = "",
    allowed_fields: set[str] | None = None,
) -> dict[str, list[dict]]:
    del allowed_fields
    semantic_rows = (
        semantic.get("semantic_rows") if isinstance(semantic.get("semantic_rows"), dict) else {}
    )
    if not semantic_rows:
        return {}

    rows: dict[str, list[dict]] = {}
    skip_spec_aggregate = str(surface or "").lower().startswith("job_")
    for field_name, field_rows in semantic_rows.items():
        if skip_spec_aggregate and field_name == "specifications":
            continue
        if not isinstance(field_rows, list):
            continue
        copied_rows = [dict(row) for row in field_rows if isinstance(row, dict)]
        if copied_rows:
            rows[field_name] = copied_rows
    return rows


def _build_dynamic_structured_rows(
    *,
    surface: str = "",
    structured_sources: list[tuple[str, object, dict[str, object]]],
    allowed_fields: set[str] | None = None,
) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for source, payload, metadata in structured_sources:
        spec_map = _extract_structured_spec_map(payload)
        if not spec_map:
            continue
        spec_lines = [f"{label}: {value}" for label, value in spec_map.items()]
        if spec_lines and not str(surface or "").lower().startswith("job_"):
            row = {
                "value": SEMANTIC_AGGREGATE_SEPARATOR.join(spec_lines),
                "source": "structured_spec",
            }
            if metadata:
                row.update(metadata)
            rows.setdefault("specifications", []).append(row)
            rows.setdefault("product_attributes", []).append(
                {
                    **metadata,
                    "value": spec_map,
                    "source": "structured_spec",
                }
            )
        dimension_lines = [
            f"{label}: {value}"
            for label, value in spec_map.items()
            if any(token in label.lower() for token in DIMENSION_KEYWORDS)
        ]
        if dimension_lines:
            row = {
                "value": SEMANTIC_AGGREGATE_SEPARATOR.join(dimension_lines),
                "source": "structured_spec",
            }
            if metadata:
                row.update(metadata)
            rows.setdefault("dimensions", []).append(row)
        for field_name, value in spec_map.items():
            normalized = normalize_requested_field(field_name)
            if not normalized or _DYNAMIC_NUMERIC_FIELD_RE.fullmatch(normalized):
                continue
            if not _dynamic_field_name_is_valid(normalized):
                continue
            coerced = _coerce_scalar_for_dynamic_row(value)
            if coerced is None:
                continue
            row = {"value": coerced, "source": source}
            if metadata:
                row.update(metadata)
            rows.setdefault(normalized, []).append(row)
    return rows


def _build_product_detail_rows(
    soup: BeautifulSoup,
    *,
    base_url: str,
    structured_sources: list[tuple[str, object, dict[str, object]]],
) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for source, payload, metadata in structured_sources:
        detail = _find_product_detail_payload(payload)
        if not isinstance(detail, dict):
            continue
        for field_name, value in _normalize_product_detail_payload(
            detail, base_url=base_url
        ).items():
            coerced = _coerce_scalar_for_dynamic_row(value)
            if coerced is None:
                continue
            normalized_source = "product_detail" if field_name == "sku" else source
            row = {"value": coerced, "source": normalized_source}
            if metadata:
                row.update(metadata)
            rows.setdefault(field_name, []).append(row)

    for field_name, value in _extract_buy_box_candidates(soup).items():
        rows.setdefault(field_name, []).append(
            {"value": value, "source": "dom_buy_box"}
        )
    return rows


def _build_platform_detail_rows(
    *,
    base_url: str,
    soup: BeautifulSoup,
    adapter_records: list[dict],
) -> dict[str, list[dict]]:
    from app.services.extract.variant_builder import (
        _find_variant_adapter_record,
        _merge_dynamic_row_map,
    )

    rows: dict[str, list[dict]] = {}
    shopify_product = _find_variant_adapter_record(adapter_records)
    if shopify_product:
        _merge_dynamic_row_map(
            rows,
            _build_shopify_content_rows(shopify_product, base_url=base_url),
        )
    _merge_dynamic_row_map(rows, _build_dom_gallery_rows(soup, base_url=base_url))
    return rows
