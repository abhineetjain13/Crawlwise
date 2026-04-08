from __future__ import annotations

from urllib.parse import urlparse

_EMPTY_VALUES = (None, "", [], {})
_STRONG_IDENTITY_FIELDS = ("job_id", "sku", "part_number", "id", "url", "apply_url")
_LONG_TEXT_FIELDS = {"description", "company", "location", "salary", "department"}


def strong_identity_key(record: dict) -> str:
    for field_name in _STRONG_IDENTITY_FIELDS:
        value = str(record.get(field_name) or "").strip()
        if not value:
            continue
        if field_name in {"url", "apply_url"}:
            parsed = urlparse(value)
            normalized = parsed._replace(fragment="").geturl().lower()
            return f"url:{normalized}"
        if field_name in {"sku", "id"}:
            return f"item:{value.lower()}"
        return f"{field_name}:{value.lower()}"
    return ""


def choose_primary_record_set(
    record_sets: dict[str, list[dict]],
    *,
    surface: str,
) -> tuple[str, list[dict]]:
    best_label = ""
    best_records: list[dict] = []
    best_score: tuple[int, int, int, int] = (0, 0, 0, 0)
    is_job_surface = "job" in str(surface or "").lower()

    for label, records in record_sets.items():
        if not records:
            continue
        strong_count = sum(1 for record in records if strong_identity_key(record))
        title_count = sum(1 for record in records if record.get("title") not in _EMPTY_VALUES)
        link_count = sum(
            1
            for record in records
            if record.get("url") not in _EMPTY_VALUES
            or record.get("apply_url") not in _EMPTY_VALUES
        )
        if is_job_surface:
            surface_count = sum(
                1
                for record in records
                if record.get("company") not in _EMPTY_VALUES
                or record.get("salary") not in _EMPTY_VALUES
            )
        else:
            surface_count = sum(
                1
                for record in records
                if record.get("price") not in _EMPTY_VALUES
                or record.get("image_url") not in _EMPTY_VALUES
            )
        score = (strong_count, surface_count, title_count, link_count)
        if score > best_score:
            best_label = label
            best_records = records
            best_score = score
    return best_label, best_records


def merge_record_sets_on_identity(
    primary_records: list[dict],
    supplemental_sets: list[list[dict]],
) -> list[dict]:
    merged = [dict(record) for record in primary_records]
    by_key = {
        strong_identity_key(record): index
        for index, record in enumerate(merged)
        if strong_identity_key(record)
    }
    if not by_key:
        return merged

    for records in supplemental_sets:
        for record in records:
            key = strong_identity_key(record)
            if not key:
                continue
            index = by_key.get(key)
            if index is None:
                continue
            merged[index] = merge_listing_record(merged[index], record)
    return merged


def merge_listing_record(base: dict, incoming: dict) -> dict:
    merged = dict(base)
    for key, value in incoming.items():
        if key.startswith("_"):
            if key == "_source":
                merged["_source"] = _merge_source_labels(merged.get("_source"), value)
            elif key not in merged and value not in _EMPTY_VALUES:
                merged[key] = value
            continue
        if _should_prefer_listing_value(key, merged.get(key), value):
            merged[key] = value
    return merged


def _should_prefer_listing_value(field_name: str, current: object, candidate: object) -> bool:
    if candidate in _EMPTY_VALUES:
        return False
    if current in _EMPTY_VALUES:
        return True
    if field_name in _LONG_TEXT_FIELDS:
        return len(str(candidate)) > len(str(current))
    if field_name == "additional_images":
        current_count = len([part for part in str(current).split(",") if part.strip()])
        candidate_count = len([part for part in str(candidate).split(",") if part.strip()])
        return candidate_count > current_count
    return False


def _merge_source_labels(*values: object) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in str(value or "").replace("+", "|").split("|"):
            label = part.strip()
            if not label or label in seen:
                continue
            seen.add(label)
            labels.append(label)
    return " + ".join(labels)
