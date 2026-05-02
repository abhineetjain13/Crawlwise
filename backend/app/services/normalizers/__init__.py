from __future__ import annotations

import ast
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.config.extraction_rules import AVAILABILITY_URL_MAP, CURRENCY_CODES
from app.services.config.field_mappings import (
    NORMALIZER_BOOLEAN_FIELDS,
    NORMALIZER_DECIMAL_FIELDS,
    NORMALIZER_INTEGER_FIELDS,
    NORMALIZER_LIST_TEXT_FIELDS,
)

_NUMERIC_TEXT_RE = re.compile(r"[-+]?\d[\d.,]*")
_CURRENCY_CODE_CONTEXT_PATTERN = (
    "|".join(
        re.escape(str(code).lower())
        for code in tuple(CURRENCY_CODES or ())
        if isinstance(code, str) and str(code).strip().lower() != "rs"
    )
    or r"(?!)"
)
_CURRENCY_CONTEXT_RE = re.compile(
    (
        r"[$€£¥₹]|(?:^|\b)(?:price|sale|now|from|starting(?:\s+at)?|mrp|msrp|cost|"
        rf"{_CURRENCY_CODE_CONTEXT_PATTERN}|rs\.?)\b"
    ),
    re.I,
)
_AVAILABILITY_TOKENS = {
    "in_stock": ("in stock", "instock", "available", "ready to ship"),
    "limited_stock": (
        "limited stock",
        "limitedstock",
        "low stock",
        "lowstock",
        "only",
        "left in stock",
    ),
    "out_of_stock": ("out of stock", "outofstock", "oos", "sold out", "unavailable"),
    "preorder": ("pre-order", "preorder", "backorder", "back-order"),
}


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_text_list(value: object) -> object:
    if isinstance(value, str):
        return _normalize_text(value)
    if not isinstance(value, (list, tuple, set)):
        return _normalize_text(value)
    rows: list[str] = []
    seen: set[str] = set()
    for part in value:
        cleaned = _normalize_text(part)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        rows.append(cleaned)
    return rows


def _normalize_bool(value: object) -> bool | str:
    if isinstance(value, bool):
        return value
    text = _normalize_text(value).lower()
    if text in {
        "true",
        "1",
        "yes",
        "remote",
        "fully remote",
        "work from home",
        "telecommute",
    }:
        return True
    if text in {"false", "0", "no", "onsite", "on site", "office"}:
        return False
    return _normalize_text(value)


def normalize_decimal_price(
    value: object,
    *,
    interpret_integral_as_cents: bool = False,
) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, bool):
        return None
    text = _normalize_text(value)
    if not text:
        return None
    if isinstance(value, str):
        stripped = _canonicalize_decimal_candidate(text)
        if stripped is None:
            return None
        if (
            not interpret_integral_as_cents
            and "." not in stripped
            and len(re.sub(r"\D+", "", stripped)) <= 3
            and _CURRENCY_CONTEXT_RE.search(text) is None
        ):
            return None
    match = _NUMERIC_TEXT_RE.search(text)
    if match is None:
        return None
    candidate = _canonicalize_decimal_candidate(match.group(0))
    if candidate is None:
        return None
    try:
        decimal = Decimal(candidate)
    except (InvalidOperation, ValueError):
        return None
    digit_count = sum(1 for char in candidate if char.isdigit())
    if interpret_integral_as_cents and "." not in candidate and digit_count >= 3:
        decimal = decimal / Decimal("100")
    return format(decimal, "f")


def _canonicalize_decimal_candidate(value: str) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    match = _NUMERIC_TEXT_RE.search(text)
    if match is None:
        return None
    candidate = match.group(0)
    if "," in candidate and "." in candidate:
        if candidate.rfind(",") > candidate.rfind("."):
            return candidate.replace(".", "").replace(",", ".")
        return candidate.replace(",", "")
    if "," in candidate:
        head, tail = candidate.rsplit(",", 1)
        if tail.isdigit() and len(tail) in {1, 2} and re.search(r"\d", head):
            return head.replace(",", "").replace(".", "") + "." + tail
        return candidate.replace(",", "")
    return candidate


def _normalize_int(value: object) -> int | str:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = _normalize_text(value)
    if not text:
        return ""
    match = _NUMERIC_TEXT_RE.search(text.replace(",", ""))
    if match is None:
        return ""
    try:
        return int(Decimal(match.group(0)))
    except (InvalidOperation, ValueError):
        return ""


def _normalize_availability(value: object) -> str:
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    text = _normalize_text(value)
    lowered = text.lower()
    mapped = (AVAILABILITY_URL_MAP or {}).get(lowered.rstrip("/"))
    if mapped:
        return str(mapped)
    normalized_enum = lowered.replace("-", "_").replace(" ", "_")
    if normalized_enum in _AVAILABILITY_TOKENS:
        return normalized_enum
    if lowered in {"true", "1", "yes"}:
        return "in_stock"
    if lowered in {"false", "0", "no"}:
        return "out_of_stock"
    flat_tokens = [
        (token, normalized)
        for normalized, tokens in _AVAILABILITY_TOKENS.items()
        for token in tokens
    ]
    flat_tokens.sort(key=lambda t: len(t[0]), reverse=True)
    for token, normalized in flat_tokens:
        if token in lowered:
            return normalized
    return text


def normalize_value(field_name: str, value: object) -> object:
    normalized_field = str(field_name or "").strip().lower()
    if value is None:
        return None
    if normalized_field == "barcode" and isinstance(value, str):
        parsed = _unwrap_singleton_literal_list(value)
        if parsed is not None:
            value = parsed
    if normalized_field in NORMALIZER_LIST_TEXT_FIELDS:
        return _normalize_text_list(value)
    if normalized_field in NORMALIZER_BOOLEAN_FIELDS:
        return _normalize_bool(value)
    if normalized_field == "availability":
        return _normalize_availability(value)
    if normalized_field == "rating":
        result = normalize_decimal_price(value)
        return _normalize_rating(result) if result is not None else ""
    if normalized_field in NORMALIZER_DECIMAL_FIELDS:
        if isinstance(value, str):
            trimmed = value.strip()
            if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", trimmed):
                candidate = _canonicalize_decimal_candidate(trimmed)
                if candidate is None:
                    return ""
                try:
                    return format(Decimal(candidate), "f")
                except (InvalidOperation, ValueError):
                    return ""
        result = normalize_decimal_price(value)
        return result if result is not None else ""
    if (
        normalized_field.endswith("_count")
        or normalized_field in NORMALIZER_INTEGER_FIELDS
    ):
        return _normalize_int(value)
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, list):
        return [
            normalize_value(normalized_field, item)
            for item in value
            if item not in (None, "", [], {})
        ]
    if isinstance(value, dict):
        return {
            str(key): normalize_value(str(key), item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, (bool, int, float)):
        return value
    return _normalize_text(value)


def _unwrap_singleton_literal_list(value: str) -> str | None:
    text = _normalize_text(value)
    if not text.startswith("[") or not text.endswith("]"):
        return None
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, (list, tuple)) or len(parsed) != 1:
        return None
    return _normalize_text(parsed[0])


def _normalize_rating(value: str) -> float | str:
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    quantized = decimal.quantize(Decimal("0.01"))
    normalized = float(quantized)
    return normalized


def normalize_record_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): (
            value if str(key).startswith("_") else normalize_value(str(key), value)
        )
        for key, value in dict(record or {}).items()
        if value not in (None, "", [], {})
    }
