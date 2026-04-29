from __future__ import annotations

from typing import Any


def finalize_listing_price_fields(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("price") in (None, "", [], {}):
        for fallback_field in ("sale_price", "original_price"):
            fallback_price = record.get(fallback_field)
            if fallback_price not in (None, "", [], {}):
                record["price"] = fallback_price
                break
    if record.get("price") in (None, "", [], {}) and record.get("currency") not in (
        None,
        "",
        [],
        {},
    ):
        record.pop("currency", None)
    return record
