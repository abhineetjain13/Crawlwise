# Candidate value processing — coercion, sanitisation, finalization.
from __future__ import annotations

import json
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from json import loads as parse_json
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.services.config.extraction_rules import (
    CANDIDATE_ASSET_FILE_EXTENSIONS,
    CANDIDATE_COLOR_VARIANT_COUNT_PATTERN,
    CANDIDATE_DYNAMIC_NUMERIC_FIELD_PATTERN,
    CANDIDATE_TRACKING_PARAM_EXACT_KEYS,
    CANDIDATE_TRACKING_PARAM_PREFIXES,
    CANDIDATE_URL_ABSOLUTE_PREFIXES,
    CANDIDATE_URL_ALLOWED_SCHEMES,
    CURRENCY_CODES,
    CURRENCY_SYMBOL_MAP,
    FIELD_POLLUTION_RULES,
    GA_DATA_LAYER_KEYS,
    MAX_CANDIDATES_PER_FIELD,
    NORMALIZATION_SENTINEL_VALUES,
    SOURCE_RANKING,
)
from app.services.normalizers import (
    dispatch_string_field_coercer as _dispatch_normalizer_string_field_coercer,
    normalize_and_validate_value,
)
from app.services.extract.noise_policy import sanitize_detail_field_value

# ---------------------------------------------------------------------------
# Module-level constants and compiled regexes
# ---------------------------------------------------------------------------

def _build_salary_money_re() -> re.Pattern[str]:
    currency_symbols = sorted(
        {
            re.escape(str(symbol).strip())
            for symbol in CURRENCY_SYMBOL_MAP.keys()
            if str(symbol).strip()
        }
    )
    symbol_pattern = (
        "(?:" + "|".join(currency_symbols) + ")" if currency_symbols else r"[$€£₹]"
    )
    currency_codes = sorted(
        {
            re.escape(str(code).strip().upper())
            for code in CURRENCY_CODES
            if str(code).strip()
        }
    )
    code_pattern = (
        "(?:" + "|".join(currency_codes) + ")"
        if currency_codes
        else r"(?:USD|EUR|GBP|INR)"
    )
    pattern = (
        rf"(?<!\w)(?:{symbol_pattern}\s*\d[\d,.]*|"
        rf"\b{code_pattern}\s*\d[\d,.]*|"
        rf"\d[\d,.]*\s*{code_pattern}\b)"
    )
    return re.compile(pattern, re.IGNORECASE)


_SALARY_MONEY_RE = _build_salary_money_re()
_COLOR_VARIANT_COUNT_RE = re.compile(CANDIDATE_COLOR_VARIANT_COUNT_PATTERN, re.IGNORECASE)
_DYNAMIC_NUMERIC_FIELD_RE = re.compile(CANDIDATE_DYNAMIC_NUMERIC_FIELD_PATTERN)
_UNRESOLVED_TEMPLATE_VALUE_RE = re.compile(r"(\{\{.*?\}\}|\[\[.*?\]\]|<%.*?%>|\{%\s*.*?\s*%\}|\(\$[a-zA-Z0-9_]+\)|\$[a-zA-Z0-9_]+(?=/|$))")
_VARIANT_SELECTOR_PROMPT_RE = re.compile(
    r"^(?:select|choose|pick)\s+(?:a|an|the|your)?\s*"
    r"(?:size|sizes|color|colors|colour|colours|option|options|variant|variants|"
    r"style|styles|fit|fits|waist|length|width)\s*$",
    re.IGNORECASE,
)
_CROSSFIELD_VARIANT_VALUE_RE = re.compile(
    r"^(?:size|sizes|waist|length|width|fit|fits)\s*[:\-]?\s*"
    r"[A-Za-z0-9.+/-]{1,8}(?:\s*,\s*\.?)?$",
    re.IGNORECASE,
)
_RISKY_DETAIL_FIELDS = frozenset(
    {"title", "brand", "category", "availability", "color", "size", "features", "care"}
)
_DETAIL_FIELD_SOURCE_RANK_OVERRIDES: dict[str, dict[str, int]] = {
    "title": {
        "datalayer": 2,
        "microdata": 3,
        "selector": 8,
        "dom": 8,
        "open_graph": 7,
        "embedded_json": 8,
        "adapter": 10,
    },
    "brand": {"datalayer": 2, "hydrated_state": 8, "embedded_json": 8, "adapter": 10},
    "category": {
        "datalayer": 2,
        "text_pattern": 1,
        "json_ld": 6,
        "embedded_json": 8,
        "adapter": 10,
        "dom_breadcrumb": 7,
    },
    "availability": {"datalayer": 3, "embedded_json": 8, "adapter": 10},
    "color": {
        "text_pattern": 1,
        "semantic_section": 1,
        "semantic_spec": 3,
        "embedded_json": 8,
        "adapter": 10,
    },
    "size": {
        "text_pattern": 1,
        "semantic_section": 1,
        "semantic_spec": 4,
        "embedded_json": 8,
        "adapter": 10,
    },
}
_EMBEDDED_BLOB_PAYLOAD_KEY = "_blob_payload"
_EMBEDDED_BLOB_FAMILY_KEY = "_blob_family"
_EMBEDDED_BLOB_ORIGIN_KEY = "_blob_origin"

# ---------------------------------------------------------------------------
# Core text normalisation (foundation — used by everything else in this module)
# ---------------------------------------------------------------------------


def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


# ---------------------------------------------------------------------------
# Scalar coercion and source ranking
# ---------------------------------------------------------------------------


def _coerce_scalar_for_dynamic_row(value: object) -> str | int | float | None:
    """Allow only displayable scalars for dynamic / intelligence rows (no raw JSON blobs)."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, dict):
        return None
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            inner = _coerce_scalar_for_dynamic_row(item)
            if inner is None:
                continue
            parts.append(str(inner))
        if not parts:
            return None
        joined = "; ".join(parts)
        return joined if joined else None
    if isinstance(value, str):
        cleaned = _normalized_candidate_text(value)
        if not cleaned or cleaned.lower() in NORMALIZATION_SENTINEL_VALUES:
            return None
        return cleaned
    if isinstance(value, (int, float)):
        return value
    return None


def candidate_source_rank(field_name: str, source: object) -> int:
    normalized_source = str(source or "").strip()
    if not normalized_source:
        return 0
    source_parts = [
        part.strip() for part in normalized_source.split(",") if part.strip()
    ]
    if not source_parts:
        return 0
    overrides = _DETAIL_FIELD_SOURCE_RANK_OVERRIDES.get(field_name, {})
    source_ranking_overrides = {
        "adapter": 12,
        "saashr_detail": 12,
        "dom_variant": 9,
        "shopify_content": 11,
        "structured_spec": 10,
        "dom_section": 10,
        "dom_gallery": 10,
        "shopify_variant": 10,
    }
    ranks = []
    for part in source_parts:
        rank = int(overrides.get(part, source_ranking_overrides.get(part, SOURCE_RANKING.get(part, 0))))
        if rank == 0 and "adapter" in part:
            rank = 12
        ranks.append(rank)
    return max(ranks) if ranks else 0


# ---------------------------------------------------------------------------
# Detail field sanitisation
# ---------------------------------------------------------------------------


def _sanitize_detail_field_value(
    field_name: str, value: object
) -> tuple[object | None, str | None]:
    if field_name not in _RISKY_DETAIL_FIELDS or not isinstance(value, str):
        return value, None
    return sanitize_detail_field_value(field_name, value)


# ---------------------------------------------------------------------------
# Data-layer / embedded blob helpers
# ---------------------------------------------------------------------------


def _looks_like_ga_data_layer(payload: object) -> bool:
    """Return True if the payload looks like a Google Analytics data layer push."""
    if not isinstance(payload, dict):
        return False
    return bool(GA_DATA_LAYER_KEYS & set(payload.keys()))


def _embedded_blob_payload(payload: object) -> object:
    if isinstance(payload, dict) and _EMBEDDED_BLOB_PAYLOAD_KEY in payload:
        return payload.get(_EMBEDDED_BLOB_PAYLOAD_KEY)
    return payload


def _embedded_blob_metadata(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    family = payload.get(_EMBEDDED_BLOB_FAMILY_KEY)
    origin = payload.get(_EMBEDDED_BLOB_ORIGIN_KEY)
    metadata: dict[str, object] = {}
    if family:
        metadata["blob_family"] = family
    if origin:
        metadata["blob_origin"] = origin
    return metadata


# ---------------------------------------------------------------------------
# Template value detection
# ---------------------------------------------------------------------------


def _contains_unresolved_template_value(value: object) -> bool:
    text = _normalized_candidate_text(value)
    if not text:
        return False
    return bool(_UNRESOLVED_TEMPLATE_VALUE_RE.search(text))


# ---------------------------------------------------------------------------
# Candidate value fingerprinting and deduplication helpers
# ---------------------------------------------------------------------------


def _candidate_value_fingerprint(value: object) -> str:
    if isinstance(value, (dict, list)):
        return _comparable_candidate_value(value)
    return _normalized_candidate_text(value).casefold()


def _preferred_display_candidate_value(existing: object, candidate: object) -> object:
    if _display_candidate_priority(candidate) > _display_candidate_priority(existing):
        return candidate
    return existing


def _display_candidate_priority(value: object) -> tuple[int, int]:
    text = _normalized_candidate_text(value)
    if not text:
        return (0, 0)
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return (1, len(text))
    has_lower = any(ch.islower() for ch in letters)
    has_upper = any(ch.isupper() for ch in letters)
    if has_lower and has_upper:
        return (4, len(text))
    if has_lower:
        return (3, len(text))
    if has_upper:
        return (2, len(text))
    return (1, len(text))


def _source_labels(row: dict) -> list[str]:
    raw_sources = row.get("sources")
    if isinstance(raw_sources, list):
        labels = [str(source or "").strip() for source in raw_sources]
    else:
        labels = [
            part.strip() for part in str(row.get("source") or "candidate").split(",")
        ]
    cleaned = [label for label in labels if label]
    return cleaned or ["candidate"]


def _normalized_candidate_value(value: object) -> object | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        cleaned = _normalized_candidate_text(value)
        return cleaned or None
    if isinstance(value, (int, float)):
        return value
    return None


def _comparable_candidate_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, sort_keys=True, default=str)
        except TypeError:
            return _normalized_candidate_text(value)
    text = _normalized_candidate_text(value)
    if not text:
        return ""
    lowered = text.lower()
    if re.fullmatch(r"[$€£₹]?\s*\d[\d,]*(?:\.\d+)?", lowered):
        return re.sub(r"[^\d.]+", "", lowered)
    return lowered


# ---------------------------------------------------------------------------
# Public candidate processing: sanitize, coerce, finalize
# ---------------------------------------------------------------------------


def sanitize_field_value(field_name: str, value: object) -> object | None:
    sanitized, _reason = sanitize_field_value_with_reason(field_name, value)
    return sanitized


def sanitize_field_value_with_reason(
    field_name: str, value: object
) -> tuple[object | None, str | None]:
    """Apply config-driven noise phrase filtering for string candidates."""
    if not isinstance(value, str):
        return value, None
    text = _normalized_candidate_text(value)
    if not text:
        return None, "empty_after_sanitization"
    rules = FIELD_POLLUTION_RULES.get(field_name) or {}
    reject_phrases = [
        str(item).strip().casefold()
        for item in rules.get("reject_phrases", [])
        if str(item).strip()
    ]
    lowered = text.casefold()
    if any(phrase in lowered for phrase in reject_phrases):
        return None, "field_pollution_rule"
    return _sanitize_detail_field_value(field_name, text)


def finalize_candidate_row(
    field_name: str, row: dict, *, base_url: str = ""
) -> tuple[object | None, str | None]:
    value = coerce_field_candidate_value(
        field_name, row.get("value"), base_url=base_url
    )
    value = _normalize_embedded_cents_value(field_name, row, value)
    if value in (None, "", [], {}):
        return None, "empty_after_normalization"
    if isinstance(value, bool):
        return None, "invalid_boolean"
    if isinstance(value, str) and _contains_unresolved_template_value(value):
        return None, "unresolved_template_value"
    value, rejection_reason = sanitize_field_value_with_reason(field_name, value)
    if value in (None, "", [], {}):
        return None, rejection_reason or "sanitizer_rejected"
    return value, None


def _normalize_embedded_cents_value(
    field_name: str,
    row: dict,
    value: object,
) -> object:
    if field_name not in {"price", "original_price"}:
        return value
    if str(row.get("blob_family") or "").strip().lower() != "product_json":
        return value
    if isinstance(value, int):
        cents_value = value
    elif isinstance(value, str) and re.fullmatch(r"\d{4,}", value.strip()):
        try:
            cents_value = int(value.strip())
        except ValueError:
            return value
    else:
        return value
    try:
        normalized = (Decimal(cents_value) / Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, ValueError):
        return value
    return format(normalized, "f")


def normalize_html_rich_text(value: str) -> str:
    text = str(value or "")
    if "<" not in text or ">" not in text:
        return _normalized_candidate_text(text)
    soup = BeautifulSoup(text, "html.parser")
    block_tags = list(soup.find_all(name=["p", "li", "br", "div"]))
    for tag in block_tags:
        tag.insert_before("\n")
    rendered = soup.get_text(" ", strip=False)
    rendered = re.sub(r"[ \t]+", " ", rendered)
    rendered = re.sub(r" *\n+ *", "\n", rendered)
    rendered = re.sub(r"\n{3,}", "\n\n", rendered)
    lines = []
    for raw_line in rendered.splitlines():
        line = _normalized_candidate_text(raw_line)
        if not line:
            continue
        if line.startswith(("-", "*")):
            line = f"• {line[1:].strip()}"
        lines.append(line)
    return "\n".join(lines).strip()


def finalize_candidate_rows(
    field_name: str, rows: list[dict], *, base_url: str = ""
) -> list[dict]:
    filtered: list[dict] = []
    filtered_index: dict[str, int] = {}
    for row in rows:
        value, _reason = finalize_candidate_row(
            field_name,
            row,
            base_url=base_url,
        )
        if value in (None, "", [], {}):
            continue
        source_parts = _source_labels(row)
        source = ", ".join(source_parts)
        normalized = _candidate_value_fingerprint(value)
        if normalized in filtered_index:
            existing = filtered[filtered_index[normalized]]
            sources = list(existing.get("sources") or [])
            for source_part in source_parts:
                if source_part not in sources:
                    sources.append(source_part)
            existing["sources"] = sources
            existing["source"] = ", ".join(sources)
            preferred_value = _preferred_display_candidate_value(
                existing.get("value"), value
            )
            if preferred_value != existing.get("value"):
                existing["value"] = preferred_value
            for metadata_key, metadata_value in row.items():
                if metadata_key in {"value", "source", "sources"}:
                    continue
                if existing.get(metadata_key) in (
                    None,
                    "",
                    [],
                    {},
                ) and metadata_value not in (None, "", [], {}):
                    existing[metadata_key] = metadata_value
            continue
        filtered_index[normalized] = len(filtered)
        filtered.append(
            {**row, "value": value, "source": source, "sources": source_parts}
        )
    if len(filtered) > MAX_CANDIDATES_PER_FIELD:
        filtered = filtered[:MAX_CANDIDATES_PER_FIELD]
    return filtered


# ---------------------------------------------------------------------------
# String field coercion (dispatch → normalizer)
# ---------------------------------------------------------------------------


def dispatch_string_field_coercer(
    field_name: str, value: str, *, base_url: str
) -> object | None:
    return _dispatch_normalizer_string_field_coercer(
        field_name, value, base_url=base_url
    )


def coerce_field_candidate_value(
    field_name: str, value: object, *, base_url: str = ""
) -> object | None:
    return normalize_and_validate_value(field_name, value, base_url=base_url)


def _pick_best_nested_candidate(field_name: str, values: list[object]) -> object | None:
    rows = [
        {"value": value, "source": "nested"}
        for value in values
        if value not in (None, "", [], {})
    ]
    if not rows:
        return None
    return rows[0]["value"]


def _parse_json_like_value(value: str) -> dict | list | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if candidate.endswith(";"):
        candidate = candidate[:-1].rstrip()
    if candidate[:1] not in "{[":
        return None
    try:
        parsed = parse_json(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def resolve_candidate_url(value: str, base_url: str) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    if candidate.startswith("//"):
        resolved = f"https:{candidate}"
        resolved = _strip_tracking_query_params(resolved)
        return "" if _looks_like_asset_url(resolved) else resolved
    if candidate.startswith(CANDIDATE_URL_ABSOLUTE_PREFIXES):
        normalized = _strip_tracking_query_params(candidate)
        return "" if _looks_like_asset_url(normalized) else normalized
    if candidate.startswith("/"):
        resolved = urljoin(base_url, candidate) if base_url else candidate
        resolved = _strip_tracking_query_params(resolved)
        return "" if _looks_like_asset_url(resolved) else resolved
    resolved = (
        urljoin(base_url, candidate)
        if re.search(r"^[A-Za-z0-9][^ ]*/[^ ]+$", candidate) and base_url
        else ""
    )
    resolved = _strip_tracking_query_params(resolved) if resolved else ""
    return "" if _looks_like_asset_url(resolved) else resolved


# ---------------------------------------------------------------------------
# URL helpers (used by resolve_candidate_url and dom_extraction)
# ---------------------------------------------------------------------------


def _strip_tracking_query_params(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme not in CANDIDATE_URL_ALLOWED_SCHEMES or not parsed.netloc:
        return str(url or "").strip()
    filtered_query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key
        and (
            (key_lower := key.lower()) not in CANDIDATE_TRACKING_PARAM_EXACT_KEYS
            and not key_lower.startswith(CANDIDATE_TRACKING_PARAM_PREFIXES)
        )
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(filtered_query, doseq=True),
            parsed.fragment,
        )
    )


def _looks_like_asset_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path.lower()
    return path.endswith(CANDIDATE_ASSET_FILE_EXTENSIONS)
