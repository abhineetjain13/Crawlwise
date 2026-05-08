from __future__ import annotations

from typing import Any

from app.services.field_value_core import text_or_none
from app.services.field_value_dom import dedupe_image_urls


def dedupe_primary_and_additional_images(record: dict[str, Any]) -> None:
    raw_additional_images = record.get("additional_images")
    additional_images = (
        list(raw_additional_images)
        if isinstance(raw_additional_images, (list, tuple, set))
        else (
            [raw_additional_images]
            if raw_additional_images not in (None, "", [], {})
            else []
        )
    )
    values: list[str] = []
    for raw_value in (record.get("image_url"), *additional_images):
        image = text_or_none(raw_value)
        if image:
            values.append(image)
    merged = dedupe_image_urls(values)
    if not merged:
        record.pop("image_url", None)
        record.pop("additional_images", None)
        return
    record["image_url"] = merged[0]
    if len(merged) > 1:
        record["additional_images"] = merged[1:]
        return
    record.pop("additional_images", None)
