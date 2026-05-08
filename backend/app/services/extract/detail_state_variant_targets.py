from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.services.extract.shared_variant_logic import (
    normalized_variant_axis_key,
    variant_option_value_is_noise,
)
from app.services.field_value_core import absolute_url, object_dict, text_or_none


def state_variant_targets(
    js_state_objects: dict[str, Any] | None,
    *,
    page_url: str,
) -> tuple[
    dict[str, dict[str, dict[str, object]]],
    dict[tuple[tuple[str, str], ...], dict[str, object]],
]:
    axis_targets: dict[str, dict[str, dict[str, object]]] = {}
    combo_targets: dict[tuple[tuple[str, str], ...], dict[str, object]] = {}
    if not isinstance(js_state_objects, dict):
        return axis_targets, combo_targets
    mapping_row_id_keys = (
        "productId",
        "product_id",
        "variantId",
        "variant_id",
        "sku",
        "id",
    )
    url_keys = ("url", "href", "productUrl", "product_url", "targetUrl", "target_url")
    for payload in iter_variant_mapping_payloads(js_state_objects):
        raw_options = payload.get("options")
        if not isinstance(raw_options, list):
            continue
        option_definitions: list[dict[str, object]] = []
        for option in raw_options:
            if not isinstance(option, dict):
                continue
            axis_field = text_or_none(
                option.get("id") or option.get("key") or option.get("name")
            )
            axis_key = normalized_variant_axis_key(option.get("label") or axis_field)
            option_list = (
                option.get("optionList")
                if isinstance(option.get("optionList"), list)
                else None
            )
            if not axis_field or not axis_key or not option_list:
                continue
            value_by_id: dict[str, str] = {}
            for item in option_list:
                if not isinstance(item, dict):
                    continue
                option_id = text_or_none(item.get("id") or item.get("value"))
                option_value = text_or_none(
                    item.get("title") or item.get("label") or item.get("value")
                )
                if (
                    option_id
                    and option_value
                    and not variant_option_value_is_noise(option_value)
                ):
                    value_by_id[option_id] = option_value
            if value_by_id:
                option_definitions.append(
                    {
                        "axis_field": axis_field,
                        "axis_key": axis_key,
                        "value_by_id": value_by_id,
                    }
                )
        if not option_definitions:
            continue
        mapping_lists = [
            item
            for item in payload.values()
            if isinstance(item, list)
            and item
            and all(isinstance(row, dict) for row in item)
        ]
        for mapping_rows in mapping_lists:
            for mapping_row in mapping_rows:
                option_values: dict[str, str] = {}
                for option_definition in option_definitions:
                    axis_field = str(option_definition["axis_field"])
                    axis_key = str(option_definition["axis_key"])
                    mapping_value_by_id = object_dict(
                        option_definition.get("value_by_id")
                    )
                    option_id = text_or_none(mapping_row.get(axis_field))
                    mapped_option_value = mapping_value_by_id.get(option_id or "")
                    if mapped_option_value:
                        option_values[axis_key] = str(mapped_option_value)
                if not option_values:
                    continue
                row_metadata: dict[str, object] = {}
                explicit_url = next(
                    (
                        text_or_none(mapping_row.get(key))
                        for key in url_keys
                        if text_or_none(mapping_row.get(key))
                    ),
                    None,
                )
                if explicit_url:
                    row_metadata["url"] = absolute_url(page_url, explicit_url)
                for key in mapping_row_id_keys:
                    raw_value = text_or_none(mapping_row.get(key))
                    if not raw_value:
                        continue
                    row_metadata.setdefault("variant_id", raw_value)
                    if "url" not in row_metadata:
                        inferred_url = variant_query_url(
                            page_url,
                            query_key=key,
                            query_value=raw_value,
                        )
                        if inferred_url:
                            row_metadata["url"] = inferred_url
                    break
                if not row_metadata:
                    continue
                if len(option_values) == 1:
                    axis_key, option_value = next(iter(option_values.items()))
                    axis_targets.setdefault(axis_key, {}).setdefault(
                        option_value, {}
                    ).update(row_metadata)
                combo_targets[tuple(sorted(option_values.items()))] = row_metadata
    return axis_targets, combo_targets


def variant_query_url(
    page_url: str, *, query_key: str, query_value: str
) -> str | None:
    normalized_key = text_or_none(query_key)
    normalized_value = text_or_none(query_value)
    if not normalized_key or not normalized_value:
        return None
    parsed = urlsplit(str(page_url or "").strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != normalized_key
    ]
    query_pairs.append((normalized_key, normalized_value))
    return urlunsplit(parsed._replace(query=urlencode(query_pairs, doseq=True)))


def iter_variant_mapping_payloads(
    value: Any, *, depth: int = 0, limit: int = 8
) -> list[dict[str, Any]]:
    if depth > limit:
        return []
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("options"), list):
            matches.append(value)
        for item in value.values():
            matches.extend(
                iter_variant_mapping_payloads(item, depth=depth + 1, limit=limit)
            )
    elif isinstance(value, list):
        for item in value[:25]:
            matches.extend(
                iter_variant_mapping_payloads(item, depth=depth + 1, limit=limit)
            )
    return matches
