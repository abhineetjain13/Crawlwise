# Value normalization rules.
from __future__ import annotations

import re


def normalize_value(field_name: str, value: object) -> object:
    if isinstance(value, str):
        text = " ".join(value.split()).strip()
        if field_name in {"price", "sale_price"}:
            match = re.search(r"\d[\d,.]*", text)
            return match.group(0) if match else text
        return text
    return value
