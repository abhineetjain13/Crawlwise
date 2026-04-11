# Candidate extraction service — produces field candidates from all sources.
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import lru_cache
from json import loads as parse_json
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit

from app.services.config.field_mappings import (
    ECOMMERCE_ONLY_FIELDS,
    JOB_ONLY_FIELDS,
    REQUESTED_FIELD_ALIASES,
    get_surface_field_aliases,
)
from app.services.exceptions import ExtractionError, ExtractionParseError
from app.services.extract.signal_inventory import (
    build_signal_inventory,
    classify_page_type,
)
from app.services.extract.source_parsers import (
    parse_page_sources,
)
from app.services.knowledge_base.store import (
    get_canonical_fields,
    get_domain_mapping,
    get_selector_defaults,
)
from app.services.normalizers import (
    dispatch_string_field_coercer as _dispatch_normalizer_string_field_coercer,
)
from app.services.normalizers import (
    normalize_and_validate_value,
)
from app.services.config.extraction_rules import (
    CANDIDATE_ASSET_FILE_EXTENSIONS,
    CANDIDATE_AVAILABILITY_NOISE_PHRASES,
    CANDIDATE_AVAILABILITY_TOKENS,
    CANDIDATE_CATEGORY_NOISE_PHRASES,
    CANDIDATE_CATEGORY_TOKENS,
    CANDIDATE_COLOR_CSS_NOISE_TOKENS,
    CANDIDATE_COLOR_VARIANT_COUNT_PATTERN,
    CANDIDATE_CURRENCY_TOKENS,
    CANDIDATE_DEEP_ALIAS_LIST_SCAN_LIMIT,
    CANDIDATE_DESCRIPTION_FALLBACK_CONTENT_SELECTORS,
    CANDIDATE_DESCRIPTION_META_SELECTORS,
    CANDIDATE_DESCRIPTION_TOKENS,
    CANDIDATE_DYNAMIC_FIELD_NAME_HARD_REJECTS,
    CANDIDATE_DYNAMIC_FIELD_NAME_PATTERN,
    CANDIDATE_DYNAMIC_NUMERIC_FIELD_PATTERN,
    CANDIDATE_FIELD_GROUPS,
    CANDIDATE_IDENTIFIER_TOKENS,
    CANDIDATE_IMAGE_CANDIDATE_DICT_KEYS,
    CANDIDATE_IMAGE_COLLECTION_TOKENS,
    CANDIDATE_IMAGE_FILE_EXTENSIONS,
    CANDIDATE_IMAGE_NOISE_TOKENS,
    CANDIDATE_IMAGE_TOKENS,
    CANDIDATE_IMAGE_URL_HINT_TOKENS,
    CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT,
    CANDIDATE_NON_CONTENT_RICH_TEXT_TAGS,
    CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS,
    CANDIDATE_PLACEHOLDER_VALUES,
    CANDIDATE_PRICE_TOKENS,
    CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN,
    CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN,
    CANDIDATE_PROMO_ONLY_TITLE_PATTERN,
    CANDIDATE_RATING_TOKENS,
    CANDIDATE_REVIEW_COUNT_TOKENS,
    CANDIDATE_SALARY_TOKENS,
    CANDIDATE_SCRIPT_NOISE_PATTERN,
    CANDIDATE_TITLE_NOISE_PHRASES,
    CANDIDATE_TRACKING_PARAM_EXACT_KEYS,
    CANDIDATE_TRACKING_PARAM_PREFIXES,
    CANDIDATE_UI_ICON_TOKEN_PATTERN,
    CANDIDATE_UI_NOISE_PHRASES,
    CANDIDATE_UI_NOISE_TOKEN_PATTERN,
    CANDIDATE_URL_ABSOLUTE_PREFIXES,
    CANDIDATE_URL_ALLOWED_SCHEMES,
    CANDIDATE_URL_SUFFIXES,
    CURRENCY_CODES,
    CURRENCY_SYMBOL_MAP,
    DIMENSION_KEYWORDS,
    DOM_PATTERNS,
    DYNAMIC_FIELD_NAME_DROP_TOKENS,
    DYNAMIC_FIELD_NAME_MAX_TOKENS,
    DYNAMIC_FIELD_NAME_SCHEMA_NOISE_REGEXES,
    DYNAMIC_FIELD_NAME_TICKERLIKE_BLOCKLIST,
    FIELD_POLLUTION_RULES,
    GA_DATA_LAYER_KEYS,
    JSONLD_NON_PRODUCT_BLOCK_TYPES,
    JSONLD_STRUCTURAL_KEYS,
    JSONLD_TYPE_NOISE,
    MAX_CANDIDATES_PER_FIELD,
    NESTED_NON_PRODUCT_KEYS,
    PRODUCT_IDENTITY_FIELDS,
    SEMANTIC_AGGREGATE_SEPARATOR,
    SOURCE_RANKING,
)
from app.services.config.listing_heuristics import (
    LISTING_BUY_BOX_AVAILABILITY_PATTERN,
    LISTING_BUY_BOX_CURRENCY_SYMBOL_MAP,
    LISTING_BUY_BOX_HEADING_SCAN_TAGS,
    LISTING_BUY_BOX_HEADING_TEXTS,
    LISTING_BUY_BOX_PACK_SIZE_PATTERN,
    LISTING_BUY_BOX_PRICE_PATTERN,
    LISTING_BUY_BOX_REQUIRED_TOKENS,
    LISTING_BUY_BOX_SKU_PATTERN,
    LISTING_CARE_SECTION_LABEL,
    LISTING_DESCRIPTION_CANDIDATE_FIELDS,
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
from app.services.requested_field_policy import (
    expand_requested_fields,
    normalize_requested_field,
)
from app.services.semantic_detail_extractor import (
    extract_semantic_detail_data,
    resolve_requested_field_values,
)
from app.services.xpath_service import build_absolute_xpath, extract_selector_value
from bs4 import BeautifulSoup, Tag
from lxml import etree
from lxml import html as lxml_html

logger = logging.getLogger(__name__)
_MAX_REGEX_INPUT_LEN = 500

_UI_NOISE_TOKEN_RE = (
    re.compile(CANDIDATE_UI_NOISE_TOKEN_PATTERN, re.IGNORECASE)
    if CANDIDATE_UI_NOISE_TOKEN_PATTERN
    else None
)
_UI_ICON_TOKEN_RE = (
    re.compile(CANDIDATE_UI_ICON_TOKEN_PATTERN, re.IGNORECASE)
    if CANDIDATE_UI_ICON_TOKEN_PATTERN
    else None
)
_SCRIPT_NOISE_RE = (
    re.compile(CANDIDATE_SCRIPT_NOISE_PATTERN, re.IGNORECASE)
    if CANDIDATE_SCRIPT_NOISE_PATTERN
    else None
)
_PROMO_ONLY_TITLE_RE = (
    re.compile(CANDIDATE_PROMO_ONLY_TITLE_PATTERN, re.IGNORECASE)
    if CANDIDATE_PROMO_ONLY_TITLE_PATTERN
    else None
)
_NON_EMPTY_UI_NOISE_PHRASES = [
    phrase for phrase in CANDIDATE_UI_NOISE_PHRASES if phrase
]
_UI_NOISE_PHRASES_RE = (
    re.compile(
        r"\b(?:"
        + "|".join(re.escape(phrase) for phrase in _NON_EMPTY_UI_NOISE_PHRASES)
        + r")\b",
        re.IGNORECASE,
    )
    if _NON_EMPTY_UI_NOISE_PHRASES
    else None
)
_DYNAMIC_NUMERIC_FIELD_RE = re.compile(CANDIDATE_DYNAMIC_NUMERIC_FIELD_PATTERN)


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
_COLOR_VARIANT_COUNT_RE = re.compile(
    CANDIDATE_COLOR_VARIANT_COUNT_PATTERN, re.IGNORECASE
)
_UNRESOLVED_TEMPLATE_VALUE_RE = re.compile(r"\{[A-Za-z0-9_.-]+\}")
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
_TITLE_NOISE_PHRASES = tuple(CANDIDATE_TITLE_NOISE_PHRASES)
_CATEGORY_NOISE_PHRASES = tuple(CANDIDATE_CATEGORY_NOISE_PHRASES)
_AVAILABILITY_NOISE_PHRASES = tuple(CANDIDATE_AVAILABILITY_NOISE_PHRASES)
_GENERIC_SENTINEL_VALUES = {
    "object",
    "array",
    "boolean",
    "null",
    "none",
    "undefined",
    "unknown",
    "pending",
    "n/a",
    "na",
}
_RISKY_DETAIL_FIELDS = frozenset(
    {"title", "brand", "category", "availability", "color", "size"}
)
_DETAIL_FIELD_SOURCE_RANK_OVERRIDES: dict[str, dict[str, int]] = {
    "title": {"datalayer": 2, "embedded_json": 8, "adapter": 10},
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
_COMMON_DETAIL_REJECT_PHRASES = (
    "cookie",
    "privacy",
    "sign in",
    "log in",
    "my account",
    "analytics",
    "pageview",
    "gtm",
)
_DETAIL_FIELD_REJECT_PHRASES: dict[str, tuple[str, ...]] = {
    "title": ("add to cart", "shop now", "view cart", "menu"),
    "brand": ("home >", "home /", "policy"),
    "category": ("page type", "page category", "detail page"),
    "availability": ("add to cart", "choose options", "select options", "view details"),
    "color": ("add to cart", "choose options", "select options"),
    "size": ("select size", "choose size"),
}
_BREADCRUMB_STYLE_BRAND_RE = re.compile(r"\s(?:>|/)\s")
_EMBEDDED_BLOB_PAYLOAD_KEY = "_blob_payload"
_EMBEDDED_BLOB_FAMILY_KEY = "_blob_family"
_EMBEDDED_BLOB_ORIGIN_KEY = "_blob_origin"
_DYNAMIC_VARIANT_VALUE_FIELDS = frozenset(
    {"style", "styles", "xs", "s", "m", "l", "xl", "xxl", "xxxl", "onesize", "one_size"}
)
_PACK_STYLE_DYNAMIC_RE = re.compile(r"^pack_\d+$", re.IGNORECASE)


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
        if not cleaned or cleaned.lower() in _GENERIC_SENTINEL_VALUES:
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
        "dom_variant": 9,
        "shopify_content": 11,
        "structured_spec": 10,
        "dom_section": 10,
        "dom_gallery": 10,
        "shopify_variant": 10,
    }
    return max(
        int(
            overrides.get(
                part, source_ranking_overrides.get(part, SOURCE_RANKING.get(part, 0))
            )
        )
        for part in source_parts
    )


def _sanitize_detail_field_value(
    field_name: str, value: object
) -> tuple[object | None, str | None]:
    if field_name not in _RISKY_DETAIL_FIELDS or not isinstance(value, str):
        return value, None

    text = _normalized_candidate_text(value)
    if not text:
        return None, "empty_after_sanitization"
    lowered = text.casefold()
    reject_phrases = (
        *_COMMON_DETAIL_REJECT_PHRASES,
        *(_DETAIL_FIELD_REJECT_PHRASES.get(field_name) or ()),
    )
    if any(phrase in lowered for phrase in reject_phrases):
        return None, "detail_field_noise"
    if field_name == "brand" and _BREADCRUMB_STYLE_BRAND_RE.search(text):
        return None, "breadcrumb_like_brand"
    if field_name == "availability" and lowered in {
        "availability",
        "select size",
        "select color",
        "select colour",
    }:
        return None, "availability_shell_text"
    if field_name == "color" and len(text.split()) > 4:
        return None, "improbable_color_label"
    return text, None


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


def _dynamic_field_name_is_schema_slug_noise(normalized: str) -> bool:
    """Analytics / embedding / vendor keys (elp158, e150d_en, …)."""
    if normalized in DYNAMIC_FIELD_NAME_TICKERLIKE_BLOCKLIST:
        return True
    for pattern in DYNAMIC_FIELD_NAME_SCHEMA_NOISE_REGEXES:
        if pattern.search(normalized):
            return True
    return False


def _dynamic_value_is_bare_ticker_symbol(value: object) -> bool:
    """Drop dynamic rows whose value is only a ticker-like token (e.g. XRP)."""
    text = _normalized_candidate_text(value)
    if not text or len(text) > 6:
        return False
    if not re.fullmatch(r"[A-Za-z]{3,5}", text):
        return False
    return text.lower() in DYNAMIC_FIELD_NAME_TICKERLIKE_BLOCKLIST


def _dynamic_field_name_is_valid(normalized: str) -> bool:
    """Reject field names that are noise: single chars, sentence-like, or JSON-LD types."""
    if len(normalized) <= 1 or len(normalized) > 60:
        return False
    if not re.fullmatch(CANDIDATE_DYNAMIC_FIELD_NAME_PATTERN, normalized):
        return False
    if normalized in JSONLD_TYPE_NOISE:
        return False
    if normalized in _DYNAMIC_VARIANT_VALUE_FIELDS or _PACK_STYLE_DYNAMIC_RE.fullmatch(
        normalized
    ):
        return False
    if _dynamic_field_name_is_schema_slug_noise(normalized):
        return False
    tokens = [token for token in normalized.split("_") if token]
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        return False
    dropped_tokens = sum(
        1 for token in tokens if token in DYNAMIC_FIELD_NAME_DROP_TOKENS
    )
    if dropped_tokens >= 2 and dropped_tokens >= len(tokens) - 1:
        return False
    # 5+ underscores suggests a sentence heading, not a spec label
    if normalized.count("_") >= 5:
        return False
    return True


_DYNAMIC_FIELD_NAME_MAX_TOKENS = DYNAMIC_FIELD_NAME_MAX_TOKENS
_STRUCTURED_CANONICAL_ATTRIBUTE_KEYS = {
    "additional_images",
    "availability",
    "brand",
    "category",
    "color",
    "description",
    "features",
    "image_url",
    "materials",
    "original_price",
    "price",
    "product_attributes",
    "selected_variant",
    "size",
    "sku",
    "specifications",
    "variant_axes",
    "variants",
}
_TRUE_VARIANT_AXES = {"color", "size", "waist", "width", "length", "inseam"}
_HTML_LABEL_VALUE_FALLBACK_BLOCKED_FIELDS = frozenset(
    {"description", "features", "materials", "specifications", "product_attributes"}
)
_NOISY_PRODUCT_ATTRIBUTE_KEYS = frozenset(
    {
        "about",
        "about_us",
        "accessibility_statement",
        "contact",
        "contact_us",
        "customer_service",
        "faq",
        "faqs",
        "policies",
        "privacy",
        "privacy_policy",
        "return_policy",
        "returns",
        "shipping",
        "shipping_policy",
        "shopping_cart",
        "store_locations",
        "terms",
        "terms_policies",
    }
)
_NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES = (
    "loading... read more",
    "privacy policy",
    "terms of service",
    "shipping policy",
    "return policy",
    "request a catalog",
    "join our team",
    "account login",
    "store locations",
    "accessibility statement",
    "subscribe to our newsletter",
    "sign up for",
    "follow us on",
    "download our app",
    "manage preferences",
    "cookie settings",
    "do not sell my personal",
)
_NOISY_PRODUCT_ATTRIBUTE_LINK_TEXTS = (
    "gift cards",
    "press inquiries",
    "the gazette",
    "your privacy choices",
)
_CSS_NOISE_VALUE_RE = re.compile(CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN)
_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_RE = re.compile(
    CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN
)


def _canonical_structured_key(value: object) -> str:
    text = _normalized_candidate_text(value).lower()
    if text in {"color", "colour", "colors", "colours"}:
        return "color"
    if text in {"size", "sizes", "dimension", "dimensions"}:
        return "size"
    normalized = normalize_requested_field(text)
    if normalized in {"dimension", "dimensions"}:
        return "size"
    return normalized or text


def _collect_candidates(
    url: str,
    surface: str,
    html: str,
    soup: BeautifulSoup,
    tree,
    page_sources: dict,
    adapter_records: list[dict],
    network_payloads: list[dict],
    target_fields: list[str],
    canonical_target_fields: set[str],
    contract_by_field: dict,
    semantic: dict,
    label_value_text_sources: dict,
) -> dict[str, list[dict]]:
    """Gather candidate values using a Strategy iteration pattern (first-match wins).

    Implements extraction hierarchy with first-match wins:
    1. Extraction contract (XPath/Regex)
    2. Platform adapter
    3. dataLayer
    4. Network intercept
    5. JSON-LD
    6. Embedded JSON (Next.js, hydrated states)
    7. DOM selectors
    8. Semantic extraction
    9. Text patterns

    Returns: {field_name: [candidate_rows]}
    """
    candidates: dict[str, list[dict]] = {}
    domain = _domain(url)

    # Extract all page sources
    next_data = page_sources.get("next_data")
    hydrated_states = page_sources.get("hydrated_states") or []
    embedded_json = page_sources.get("embedded_json") or []
    open_graph = page_sources.get("open_graph") or {}
    json_ld = page_sources.get("json_ld") or []
    microdata = page_sources.get("microdata") or []
    datalayer = page_sources.get("datalayer") or {}

    semantic_sections = (
        semantic.get("sections") if isinstance(semantic.get("sections"), dict) else {}
    )
    semantic_specifications = (
        semantic.get("specifications")
        if isinstance(semantic.get("specifications"), dict)
        else {}
    )
    semantic_promoted = (
        semantic.get("promoted_fields")
        if isinstance(semantic.get("promoted_fields"), dict)
        else {}
    )

    for field_name in target_fields:
        rows: list[dict] = []

        # 1-2. Collect contract and adapter candidates, but do not short-circuit:
        # downstream arbitration must see all sources to choose the winner.
        _collect_contract_candidates(
            rows,
            field_name=field_name,
            tree=tree,
            html=html,
            contract_by_field=contract_by_field,
        )
        _collect_adapter_candidates(
            rows, field_name=field_name, adapter_records=adapter_records
        )

        # 3-6. Collect from ALL remaining structured sources so
        # _finalize_candidates can pick the highest-ranked candidate
        # via SOURCE_RANKING (e.g. json_ld=6 beats datalayer=2).
        _collect_jsonld_candidates(
            rows,
            field_name=field_name,
            json_ld=json_ld,
            base_url=url,
            surface=surface,
        )
        _collect_datalayer_candidates(rows, field_name=field_name, datalayer=datalayer)
        _collect_network_payload_candidates(
            rows,
            field_name=field_name,
            network_payloads=network_payloads,
            base_url=url,
            surface=surface,
        )
        _collect_structured_state_candidates(
            rows,
            field_name=field_name,
            next_data=next_data,
            hydrated_states=hydrated_states,
            embedded_json=embedded_json,
            network_payloads=network_payloads,
            base_url=url,
            surface=surface,
        )

        # 7. DOM selectors
        _collect_dom_and_meta_candidates(
            rows,
            field_name=field_name,
            html=html,
            soup=soup,
            domain=domain,
            microdata=microdata,
            open_graph=open_graph,
            base_url=url,
            surface=surface,
        )

        # 8. Semantic extraction
        if _is_semantic_requested_field(field_name, canonical_target_fields):
            semantic_rows = resolve_requested_field_values(
                [field_name],
                sections=semantic_sections,
                specifications=semantic_specifications,
                promoted_fields=semantic_promoted,
            )
            semantic_value = semantic_rows.get(field_name)
            if semantic_value not in (None, "", [], {}):
                rows.append({"value": semantic_value, "source": "semantic_section"})

        # 9. Text patterns
        if _is_semantic_requested_field(field_name, canonical_target_fields):
            text_value = _extract_label_value_from_text(
                field_name, label_value_text_sources, html, surface=surface
            )
            if text_value:
                rows.append({"value": text_value, "source": "text_pattern"})

        if rows:
            candidates[field_name] = rows

    return candidates


def _is_semantic_requested_field(
    field_name: str,
    canonical_target_fields: set[str],
) -> bool:
    return (
        field_name in canonical_target_fields or field_name in REQUESTED_FIELD_ALIASES
    )


def _collect_contract_candidates(
    rows: list[dict],
    *,
    field_name: str,
    tree,
    html: str,
    contract_by_field: dict,
) -> bool:
    contract_rule = contract_by_field.get(field_name)
    if not contract_rule:
        return False
    xpath_value = _extract_xpath_value(tree, contract_rule.get("xpath", ""))
    if xpath_value:
        rows.append(
            {
                "value": xpath_value,
                "source": "contract_xpath",
                "xpath": contract_rule.get("xpath"),
                "css_selector": None,
                "regex": None,
                "sample_value": xpath_value,
            }
        )
    regex_value = _extract_regex_value(html, contract_rule.get("regex", ""))
    if regex_value:
        rows.append(
            {
                "value": regex_value,
                "source": "contract_regex",
                "xpath": None,
                "css_selector": None,
                "regex": contract_rule.get("regex"),
                "sample_value": regex_value,
            }
        )
    return bool(rows)


def _collect_adapter_candidates(
    rows: list[dict],
    *,
    field_name: str,
    adapter_records: list[dict],
) -> bool:
    for record in adapter_records:
        if isinstance(record, dict) and field_name in record and record[field_name]:
            rows.append({"value": record[field_name], "source": "adapter"})
    return bool(rows)


def _collect_datalayer_candidates(
    rows: list[dict],
    *,
    field_name: str,
    datalayer: dict,
) -> bool:
    if datalayer and field_name in datalayer and datalayer[field_name]:
        rows.append({"value": datalayer[field_name], "source": "datalayer"})
    return bool(rows)


def _collect_network_payload_candidates(
    rows: list[dict],
    *,
    field_name: str,
    network_payloads: list[dict],
    base_url: str,
    surface: str,
) -> bool:
    for payload in network_payloads:
        if not isinstance(payload, dict):
            continue
        payload_url = str(payload.get("url") or "").lower()
        if _NETWORK_PAYLOAD_NOISE_URL_PATTERNS.search(payload_url):
            continue
        body = payload.get("body", {})
        if isinstance(body, (dict, list)):
            _append_source_candidates(
                rows,
                field_name,
                body,
                "network_intercept",
                base_url=base_url,
                surface=surface,
            )
    return bool(rows)


def _collect_jsonld_candidates(
    rows: list[dict],
    *,
    field_name: str,
    json_ld: list[dict],
    base_url: str,
    surface: str,
) -> bool:
    for payload in json_ld:
        if isinstance(payload, dict):
            if _should_skip_jsonld_block(payload, field_name):
                continue
            if not _payload_matches_page_scope(payload, base_url=base_url):
                continue
            _append_source_candidates(
                rows,
                field_name,
                payload,
                "json_ld",
                base_url=base_url,
                surface=surface,
            )
    return bool(rows)


def _collect_structured_state_candidates(
    rows: list[dict],
    *,
    field_name: str,
    next_data: dict | None,
    hydrated_states: list[dict],
    embedded_json: list[object],
    network_payloads: list[dict],
    base_url: str,
    surface: str,
) -> bool:
    for payload in embedded_json:
        if not _payload_matches_page_scope(payload, base_url=base_url):
            continue
        _append_source_candidates(
            rows,
            field_name,
            payload,
            "embedded_json",
            base_url=base_url,
            source_metadata=_embedded_blob_metadata(payload),
            surface=surface,
        )
    if next_data:
        if _payload_matches_page_scope(next_data, base_url=base_url):
            _append_source_candidates(
                rows,
                field_name,
                next_data,
                "next_data",
                base_url=base_url,
                surface=surface,
            )
    for state in hydrated_states:
        if _payload_matches_page_scope(state, base_url=base_url):
            _append_source_candidates(
                rows,
                field_name,
                state,
                "hydrated_state",
                base_url=base_url,
                surface=surface,
            )
    rows.extend(
        _structured_source_candidates(
            field_name,
            next_data=next_data,
            hydrated_states=hydrated_states,
            embedded_json=embedded_json,
            network_payloads=network_payloads,
            base_url=base_url,
        )
    )
    return bool(rows)


def _collect_dom_and_meta_candidates(
    rows: list[dict],
    *,
    field_name: str,
    html: str,
    soup: BeautifulSoup,
    domain: str,
    microdata: list[dict],
    open_graph: dict[str, object],
    base_url: str,
    surface: str,
) -> None:
    selectors = get_selector_defaults(domain, field_name)
    for selector in selectors:
        value, _, selector_used = extract_selector_value(
            html,
            css_selector=selector.get("css_selector"),
            xpath=selector.get("xpath"),
            regex=selector.get("regex"),
        )
        if value:
            rows.append(
                {
                    "value": value,
                    "source": "selector",
                    "xpath": selector.get("xpath"),
                    "css_selector": selector.get("css_selector"),
                    "regex": selector.get("regex"),
                    "sample_value": selector.get("sample_value") or value,
                    "selector_used": selector_used,
                    "status": selector.get("status") or "validated",
                }
            )
    dom_row = _dom_pattern(soup, field_name)
    if dom_row:
        rows.append(dom_row)
    for item in microdata:
        if isinstance(item, dict):
            _append_source_candidates(
                rows,
                field_name,
                item,
                "microdata",
                base_url=base_url,
                surface=surface,
            )
    if open_graph:
        _append_source_candidates(
            rows,
            field_name,
            open_graph,
            "open_graph",
            base_url=base_url,
            surface=surface,
        )
        if field_name == "company":
            site_name = open_graph.get("og:site_name")
            if site_name not in (None, "", [], {}):
                rows.append({"value": site_name, "source": "open_graph"})
    if field_name == "category":
        breadcrumb_category = _extract_breadcrumb_category(soup)
        if breadcrumb_category:
            rows.append({"value": breadcrumb_category, "source": "dom_breadcrumb"})


def _filter_candidates(
    candidates: dict[str, list[dict]], base_url: str
) -> dict[str, list[dict]]:
    """Apply quality filters to candidates.

    Filters:
    - Placeholder rejection (CANDIDATE_PLACEHOLDER_VALUES)
    - Noise removal (empty strings, null values)
    - URL validation (relative → absolute)
    - Field-specific validation (price format, image URLs)

    Returns: {field_name: [filtered_rows]}
    """
    filtered_candidates: dict[str, list[dict]] = {}

    for field_name, rows in candidates.items():
        filtered_rows = _finalize_candidate_rows(field_name, rows, base_url=base_url)
        if filtered_rows:
            filtered_candidates[field_name] = filtered_rows

    return filtered_candidates


def _finalize_candidates(
    candidates: dict[str, list[dict]],
    surface: str,
    url: str,
    semantic: dict,
    target_fields: set[str],
    canonical_target_fields: set[str],
    next_data: dict | None,
    hydrated_states: list[dict],
    embedded_json: list[dict],
    network_payloads: list[dict],
    soup: BeautifulSoup,
    adapter_records: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Deduplicate, rank, and prepare final output.

    - Take first valid candidate per field (first-match wins)
    - Apply domain field mappings
    - Build source trace
    - Add dynamic fields (product_attributes, additional_images)

    Returns: (candidates, source_trace)
    """

    # Choose the highest-ranked candidate per field via FieldDecisionEngine.
    from app.services.extract.field_decision import FieldDecisionEngine

    engine = FieldDecisionEngine(base_url=url)
    final_candidates: dict[str, list[dict]] = {}
    for field_name, rows in candidates.items():
        if rows:
            decision = engine.decide_from_rows(field_name, rows)
            if decision.accepted and decision.winning_row is not None:
                final_candidates[field_name] = [decision.winning_row]

    # Add dynamic fields from semantic and structured sources
    dynamic_rows = _build_dynamic_semantic_rows(
        semantic,
        surface=surface,
        allowed_fields=target_fields,
    )
    structured_sources = _structured_source_payloads(
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads,
        base_url=url,
    )
    structured_rows = _build_dynamic_structured_rows(
        surface=surface,
        structured_sources=structured_sources,
        allowed_fields=target_fields,
    )
    product_detail_rows = _build_product_detail_rows(
        soup,
        base_url=url,
        structured_sources=structured_sources,
    )
    platform_detail_rows = _build_platform_detail_rows(
        base_url=url,
        soup=soup,
        adapter_records=adapter_records or [],
    )
    variant_rows = _build_variant_rows(
        base_url=url,
        soup=soup,
        adapter_records=adapter_records or [],
        network_payloads=network_payloads,
        structured_sources=structured_sources,
    )

    # Merge dynamic rows
    merged_dynamic_rows: dict[str, list[dict]] = {}
    for field_name, rows in variant_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in structured_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in product_detail_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in platform_detail_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)
    for field_name, rows in dynamic_rows.items():
        merged_dynamic_rows.setdefault(field_name, []).extend(rows)

    # Add dynamic fields if not already present
    dynamic_override_fields = {
        "color",
        "size",
        "image_url",
        "additional_images",
        "category",
        "sku",
        "price",
        "original_price",
        "availability",
        "variants",
        "variant_axes",
        "selected_variant",
        "description",
        "features",
        "specifications",
        "product_attributes",
        "materials",
    }
    surface_name = str(surface or "").strip().lower()
    if surface_name in {"job_listing", "job_detail"}:
        surface_excluded_dynamic_fields = ECOMMERCE_ONLY_FIELDS
    elif surface_name in {"ecommerce_listing", "ecommerce_detail"}:
        surface_excluded_dynamic_fields = JOB_ONLY_FIELDS
    else:
        surface_excluded_dynamic_fields = frozenset()
    discovered_dynamic_fields: dict[str, object] = {}
    for field_name, rows in merged_dynamic_rows.items():
        if field_name in surface_excluded_dynamic_fields:
            continue
        filtered_rows = _finalize_candidate_rows(field_name, rows, base_url=url)
        if not filtered_rows:
            continue
        if (
            field_name not in canonical_target_fields
            and not _dynamic_field_name_is_valid(field_name)
        ):
            continue
        if (
            field_name not in canonical_target_fields
            and _dynamic_value_is_bare_ticker_symbol(filtered_rows[0].get("value"))
        ):
            continue
        normalized_value = _normalized_candidate_text(
            filtered_rows[0].get("value")
        ).casefold()
        if normalized_value in CANDIDATE_PLACEHOLDER_VALUES:
            continue
        if field_name not in canonical_target_fields:
            discovered_dynamic_fields[field_name] = filtered_rows[0].get("value")
            continue
        if field_name in final_candidates and field_name not in dynamic_override_fields:
            continue
        if field_name in final_candidates:
            decision = engine.decide_from_rows(
                field_name,
                [*final_candidates[field_name], *filtered_rows],
            )
            if decision.accepted and decision.winning_row is not None:
                final_candidates[field_name] = [decision.winning_row]
            continue
        final_candidates[field_name] = filtered_rows[:1]

    # Mirror image_url to additional_images if needed
    if (
        "additional_images" in target_fields
        and "additional_images" not in final_candidates
        and final_candidates.get("image_url")
    ):
        mirrored_rows = [
            {**row, "value": row.get("value")}
            for row in final_candidates["image_url"]
            if row.get("value") not in (None, "", [], {})
        ]
        if mirrored_rows:
            final_candidates["additional_images"] = mirrored_rows

    # Add product_attributes from semantic extraction to output
    if "detail" in str(surface or "").lower():
        specifications = semantic.get("specifications")
        if (
            "product_attributes" not in final_candidates
            and specifications
            and isinstance(specifications, dict)
            and specifications
        ):
            final_candidates["product_attributes"] = [
                {"value": specifications, "source": "semantic_specifications"}
            ]

    # Apply domain field mappings
    domain = _domain(url)
    mappings = get_domain_mapping(domain, surface)
    _reconcile_variant_bundle(final_candidates, base_url=url)
    _sync_selected_variant_root_fields(final_candidates)
    _sanitize_product_attributes(final_candidates)

    return final_candidates, {
        "candidates": dict(final_candidates),
        "discovered_data": {
            "discovered_fields": discovered_dynamic_fields,
        },
        "mapping_hint": mappings,
        "semantic": semantic,
    }


def _sync_selected_variant_root_fields(final_candidates: dict[str, list[dict]]) -> None:
    selected_rows = final_candidates.get("selected_variant")
    if not isinstance(selected_rows, list) or not selected_rows:
        return
    selected_row = selected_rows[0]
    selected_variant = (
        selected_row.get("value") if isinstance(selected_row, dict) else None
    )
    if not isinstance(selected_variant, dict):
        return
    source = (
        str(selected_row.get("source") or "selected_variant").strip()
        or "selected_variant"
    )
    for field_name in (
        "price",
        "original_price",
        "sku",
        "color",
        "size",
        "availability",
        "image_url",
    ):
        value = selected_variant.get(field_name)
        if value in (None, "", [], {}):
            continue
        final_candidates[field_name] = [{"value": value, "source": source}]


def _sanitize_structured_variant_output(
    final_candidates: dict[str, list[dict]],
) -> None:
    variant_axes_rows = final_candidates.get("variant_axes")
    if not isinstance(variant_axes_rows, list) or not variant_axes_rows:
        return
    axis_payload = (
        variant_axes_rows[0].get("value")
        if isinstance(variant_axes_rows[0], dict)
        else None
    )
    if not isinstance(axis_payload, dict):
        return
    cleaned_axes, moved_attributes = _split_variant_axes(axis_payload)
    if cleaned_axes:
        final_candidates["variant_axes"] = [
            {**variant_axes_rows[0], "value": cleaned_axes}
        ]
    else:
        final_candidates.pop("variant_axes", None)
    if moved_attributes:
        _merge_product_attributes_into_candidates(
            final_candidates,
            moved_attributes,
            source=str(variant_axes_rows[0].get("source") or "variant_axes").strip()
            or "variant_axes",
        )


def _merge_product_attributes_into_candidates(
    final_candidates: dict[str, list[dict]],
    attributes: dict[str, object],
    *,
    source: str,
) -> None:
    if not attributes:
        return
    merged: dict[str, object] = {}
    existing_rows = final_candidates.get("product_attributes")
    if isinstance(existing_rows, list) and existing_rows:
        current = (
            existing_rows[0].get("value")
            if isinstance(existing_rows[0], dict)
            else None
        )
        if isinstance(current, dict):
            merged.update(current)
    merged.update(attributes)
    final_candidates["product_attributes"] = [{"value": merged, "source": source}]


def _sanitize_product_attributes(final_candidates: dict[str, list[dict]]) -> None:
    product_rows = final_candidates.get("product_attributes")
    if not isinstance(product_rows, list) or not product_rows:
        return
    payload = (
        product_rows[0].get("value") if isinstance(product_rows[0], dict) else None
    )
    if not isinstance(payload, dict):
        final_candidates.pop("product_attributes", None)
        return
    sanitized = dict(payload)
    canonical_keys = {
        key
        for key in final_candidates.keys()
        if key in _STRUCTURED_CANONICAL_ATTRIBUTE_KEYS and key != "product_attributes"
    } | _STRUCTURED_CANONICAL_ATTRIBUTE_KEYS
    for key in list(sanitized.keys()):
        normalized_key = _canonical_structured_key(key)
        if normalized_key in canonical_keys:
            sanitized.pop(key, None)
            continue
        if _is_noisy_product_attribute_entry(
            normalized_key or str(key), sanitized.get(key)
        ):
            sanitized.pop(key, None)
    if sanitized:
        final_candidates["product_attributes"] = [
            {**product_rows[0], "value": sanitized}
        ]
    else:
        final_candidates.pop("product_attributes", None)


def _reconcile_variant_bundle(
    final_candidates: dict[str, list[dict]],
    *,
    base_url: str,
) -> None:
    variants_row = _first_candidate_row(final_candidates.get("variants"))
    selected_row = _first_candidate_row(final_candidates.get("selected_variant"))
    axes_row = _first_candidate_row(final_candidates.get("variant_axes"))

    variants = _normalized_variant_rows_payload(
        variants_row.get("value") if variants_row else None,
        base_url=base_url,
    )
    selected_variant = _normalized_selected_variant_payload(
        selected_row.get("value") if selected_row else None,
        base_url=base_url,
    )
    variant_axes = _normalized_variant_axes_payload(
        axes_row.get("value") if axes_row else None,
        base_url=base_url,
    )

    if variants:
        matched_index = (
            _find_matching_variant_index(variants, selected_variant)
            if selected_variant
            else -1
        )
        if selected_variant and matched_index >= 0:
            merged_selected = _merge_variant_records(variants[matched_index], selected_variant)
            variants[matched_index] = merged_selected
            selected_variant = merged_selected
        elif selected_variant and _is_meaningful_variant_record(selected_variant):
            variants.append(selected_variant)
        if selected_variant is None:
            selected_variant = _choose_default_variant(variants)

        raw_axis_values = _collect_variant_axis_values(variants)
        merged_axis_values = _merge_variant_axis_values(
            discovered_axes=raw_axis_values,
            declared_axes=variant_axes,
        )
        if merged_axis_values:
            variant_axes, variant_attributes = _split_variant_axes(merged_axis_values)
            if variant_axes:
                source = _row_source_label(variants_row, fallback="variants")
                final_candidates["variant_axes"] = [{"value": variant_axes, "source": source}]
            else:
                final_candidates.pop("variant_axes", None)
            if variant_attributes:
                _merge_product_attributes_into_candidates(
                    final_candidates,
                    variant_attributes,
                    source=_row_source_label(variants_row, fallback="variants"),
                )
        else:
            final_candidates.pop("variant_axes", None)

        final_candidates["variants"] = [
            {
                "value": variants,
                "source": _row_source_label(variants_row, fallback="variants"),
            }
        ]
        if selected_variant:
            final_candidates["selected_variant"] = [
                {
                    "value": selected_variant,
                    "source": _row_source_label(selected_row or variants_row, fallback="selected_variant"),
                }
            ]
        else:
            final_candidates.pop("selected_variant", None)
        return

    if selected_variant:
        final_candidates["selected_variant"] = [
            {
                "value": selected_variant,
                "source": _row_source_label(selected_row, fallback="selected_variant"),
            }
        ]
    else:
        final_candidates.pop("selected_variant", None)

    if variant_axes:
        cleaned_axes, moved_attributes = _split_variant_axes(variant_axes)
        if cleaned_axes:
            final_candidates["variant_axes"] = [
                {
                    "value": cleaned_axes,
                    "source": _row_source_label(axes_row, fallback="variant_axes"),
                }
            ]
        else:
            final_candidates.pop("variant_axes", None)
        if moved_attributes:
            _merge_product_attributes_into_candidates(
                final_candidates,
                moved_attributes,
                source=_row_source_label(axes_row, fallback="variant_axes"),
            )
    else:
        final_candidates.pop("variant_axes", None)


def _merge_variant_axis_values(
    *,
    discovered_axes: dict[str, list[str]],
    declared_axes: dict[str, list[str]],
) -> dict[str, list[str]]:
    if not discovered_axes:
        return dict(declared_axes)
    merged: dict[str, list[str]] = {
        axis_name: list(values) for axis_name, values in discovered_axes.items()
    }
    for axis_name, values in declared_axes.items():
        normalized_axis = _canonical_structured_key(axis_name)
        if not normalized_axis or normalized_axis not in discovered_axes:
            continue
        bucket = merged.setdefault(normalized_axis, [])
        for value in values:
            cleaned = _normalized_candidate_text(value)
            if cleaned and cleaned not in bucket:
                bucket.append(cleaned)
    return merged


def _first_candidate_row(rows: object) -> dict[str, object] | None:
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def _row_source_label(row: dict[str, object] | None, *, fallback: str) -> str:
    if not isinstance(row, dict):
        return fallback
    return str(row.get("source") or fallback).strip() or fallback


def _normalized_variant_rows_payload(
    value: object,
    *,
    base_url: str,
) -> list[dict[str, object]]:
    normalized = coerce_field_candidate_value("variants", value, base_url=base_url)
    if not isinstance(normalized, list):
        return []
    reconciled: list[dict[str, object]] = []
    seen: set[str] = set()
    for variant in normalized:
        if not _is_meaningful_variant_record(variant):
            continue
        fingerprint = _variant_record_fingerprint(variant)
        if fingerprint and fingerprint in seen:
            continue
        if fingerprint:
            seen.add(fingerprint)
        reconciled.append(dict(variant))
    return reconciled


def _normalized_selected_variant_payload(
    value: object,
    *,
    base_url: str,
) -> dict[str, object] | None:
    normalized = coerce_field_candidate_value("selected_variant", value, base_url=base_url)
    if not isinstance(normalized, dict) or not _is_meaningful_variant_record(normalized):
        return None
    return dict(normalized)


def _normalized_variant_axes_payload(
    value: object,
    *,
    base_url: str,
) -> dict[str, list[str]]:
    normalized = coerce_field_candidate_value("variant_axes", value, base_url=base_url)
    return normalized if isinstance(normalized, dict) else {}


def _is_meaningful_variant_record(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("variant_id") not in (None, "", [], {}):
        return True
    if value.get("sku") not in (None, "", [], {}):
        return True
    option_values = value.get("option_values")
    if isinstance(option_values, dict) and option_values:
        return True
    for key in ("color", "size", "price", "original_price", "availability", "image_url"):
        if value.get(key) not in (None, "", [], {}):
            return True
    return False


def _variant_record_fingerprint(value: dict[str, object]) -> str:
    variant_id = str(value.get("variant_id") or "").strip()
    if variant_id:
        return f"id:{variant_id}"
    sku = str(value.get("sku") or "").strip()
    option_values = value.get("option_values")
    if sku and isinstance(option_values, dict) and option_values:
        return json.dumps({"sku": sku, "option_values": option_values}, sort_keys=True, default=str)
    if sku:
        return f"sku:{sku}"
    if isinstance(option_values, dict) and option_values:
        return json.dumps({"option_values": option_values}, sort_keys=True, default=str)
    fallback = {
        key: value.get(key)
        for key in ("color", "size", "price", "original_price", "availability", "image_url")
        if value.get(key) not in (None, "", [], {})
    }
    return json.dumps(fallback, sort_keys=True, default=str) if fallback else ""


def _find_matching_variant_index(
    variants: list[dict[str, object]],
    selected_variant: dict[str, object] | None,
) -> int:
    if not selected_variant:
        return -1
    selected_fingerprint = _variant_record_fingerprint(selected_variant)
    if selected_fingerprint:
        for index, variant in enumerate(variants):
            if _variant_record_fingerprint(variant) == selected_fingerprint:
                return index
    selected_options = selected_variant.get("option_values")
    if isinstance(selected_options, dict) and selected_options:
        for index, variant in enumerate(variants):
            if variant.get("option_values") == selected_options:
                return index
    return -1


def _merge_variant_records(
    primary: dict[str, object],
    secondary: dict[str, object],
) -> dict[str, object]:
    merged = dict(primary)
    for key, value in secondary.items():
        if merged.get(key) in (None, "", [], {}) and value not in (None, "", [], {}):
            merged[key] = value
    if isinstance(primary.get("option_values"), dict) and isinstance(secondary.get("option_values"), dict):
        merged["option_values"] = {
            **primary["option_values"],
            **secondary["option_values"],
        }
    return merged


def _choose_default_variant(
    variants: list[dict[str, object]],
) -> dict[str, object] | None:
    if not variants:
        return None
    return next(
        (variant for variant in variants if variant.get("availability") == "in_stock"),
        variants[0],
    )


def _collect_variant_axis_values(
    variants: list[dict[str, object]],
) -> dict[str, list[str]]:
    axis_values: dict[str, list[str]] = {}
    for variant in variants:
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, value in option_values.items():
            normalized_axis = _canonical_structured_key(axis_name)
            cleaned_value = _normalized_candidate_text(value)
            if not normalized_axis or not cleaned_value:
                continue
            bucket = axis_values.setdefault(normalized_axis, [])
            if cleaned_value not in bucket:
                bucket.append(cleaned_value)
    return axis_values


def _is_noisy_product_attribute_entry(key: object, value: object) -> bool:
    normalized_key = normalize_requested_field(key)
    text_value = _normalized_candidate_text(value).lower()
    if not normalized_key or not text_value:
        return True
    if _PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_RE.fullmatch(normalized_key):
        return True
    if not re.search(r"[a-z]", normalized_key):
        return True
    if normalized_key in _NOISY_PRODUCT_ATTRIBUTE_KEYS:
        return True
    if normalized_key.startswith(("contact_", "customer_", "privacy_", "terms_")):
        return True
    if any(
        token in normalized_key.split("_")
        for token in CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS
    ):
        return True
    if any(phrase in text_value for phrase in _NOISY_PRODUCT_ATTRIBUTE_VALUE_PHRASES):
        return True
    if any(token in text_value for token in _NOISY_PRODUCT_ATTRIBUTE_LINK_TEXTS):
        return True
    if _CSS_NOISE_VALUE_RE.search(text_value):
        return True
    if (
        text_value.count("{") >= 1
        and text_value.count("}") >= 1
        and text_value.count(":") >= 3
    ):
        return True
    if text_value.count(" - ") >= 2:
        return True
    return False


def extract_candidates(
    url: str,
    surface: str,
    html: str,
    xhr_payloads: list[dict],
    additional_fields: list[str],
    extraction_contract: list[dict] | None = None,
    resolved_fields: list[str] | None = None,
    adapter_records: list[dict] | None = None,
    soup: "BeautifulSoup | None" = None,
) -> tuple[dict, dict]:
    """Extract candidate values for each target field.

    Sources are checked in deterministic priority order and every discovered
    value is preserved as its own candidate row.

    Args:
        soup: Optional pre-parsed BeautifulSoup object — avoids redundant
              CPU-heavy DOM parsing when the caller already has one.

    Returns:
        (candidates, source_trace) — candidates maps field -> list of {value, source}
    """
    try:
        if soup is None:
            soup = BeautifulSoup(html, "html.parser")
        page_sources = parse_page_sources(html, soup=soup)
        signal_inventory = build_signal_inventory(
            html,
            url,
            surface,
            soup=soup,
            page_sources=page_sources,
        )
        page_type = classify_page_type(signal_inventory)

        if "listing" in str(surface or "").lower():
            return {}, {
                "candidates": {},
                "mapping_hint": {},
                "semantic": {},
                "surface_gate": "listing",
                "page_type": page_type,
            }

        tree = _build_xpath_tree(html)
        adapter_records = _scope_adapter_records_for_url(url, adapter_records or [])
        network_payloads = xhr_payloads or []

        base_target_fields = set(resolved_fields or get_canonical_fields(surface))
        if str(surface or "").strip().lower() in {"job_listing", "job_detail"}:
            base_target_fields = set(get_canonical_fields(surface))
        target_fields = sorted(
            base_target_fields | set(expand_requested_fields(additional_fields))
        )

        contract_by_field = _index_extraction_contract(extraction_contract or [])
        semantic = extract_semantic_detail_data(
            html,
            requested_fields=sorted(target_fields),
            soup=soup,
            page_url=url,
            adapter_records=adapter_records,
        )
        semantic = _scoped_semantic_payload(
            semantic, url=url, adapter_records=adapter_records
        )
        label_value_text_sources = _build_label_value_text_sources(
            url=url,
            soup=soup,
            adapter_records=adapter_records,
            network_payloads=network_payloads,
            next_data=page_sources.get("next_data"),
            hydrated_states=page_sources.get("hydrated_states") or [],
            embedded_json=page_sources.get("embedded_json") or [],
            open_graph=page_sources.get("open_graph") or {},
            json_ld=page_sources.get("json_ld") or [],
            microdata=page_sources.get("microdata") or [],
        )

        canonical_target_fields = set(get_canonical_fields(surface))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionParseError(
            f"Failed to parse extracted content for {url}"
        ) from exc

    # Step 1: Collect all candidates from all sources
    candidates = _collect_candidates(
        url=url,
        surface=surface,
        html=html,
        soup=soup,
        tree=tree,
        page_sources=page_sources,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        target_fields=target_fields,
        canonical_target_fields=canonical_target_fields,
        contract_by_field=contract_by_field,
        semantic=semantic,
        label_value_text_sources=label_value_text_sources,
    )

    # Step 2: Filter candidates (remove placeholders, validate)
    candidates = _filter_candidates(candidates, base_url=url)

    # Step 3: Finalize candidates (deduplicate, add dynamic fields)
    return _finalize_candidates(
        candidates=candidates,
        surface=surface,
        url=url,
        semantic=semantic,
        target_fields=set(target_fields),
        canonical_target_fields=canonical_target_fields,
        next_data=page_sources.get("next_data"),
        hydrated_states=page_sources.get("hydrated_states") or [],
        embedded_json=page_sources.get("embedded_json") or [],
        network_payloads=network_payloads,
        soup=soup,
        adapter_records=adapter_records,
    )


def _scope_adapter_records_for_url(url: str, adapter_records: list[dict]) -> list[dict]:
    if not adapter_records:
        return []
    scoped: list[dict] = []
    current_url_key = _scoped_url_key(url)
    current_identifiers = _scoped_record_identifiers({"url": url})
    for record in adapter_records:
        if not isinstance(record, dict):
            continue
        record_url = str(record.get("url") or record.get("source_url") or "").strip()
        if (
            record_url
            and current_url_key
            and _scoped_url_key(record_url) != current_url_key
        ):
            continue
        record_identifiers = _scoped_record_identifiers(record)
        if (
            current_identifiers
            and record_identifiers
            and current_identifiers.isdisjoint(record_identifiers)
        ):
            continue
        scoped.append(record)
    return scoped


def _scoped_semantic_payload(
    semantic: dict,
    *,
    url: str,
    adapter_records: list[dict],
) -> dict:
    payload = semantic if isinstance(semantic, dict) else {}
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    if not scope:
        return payload
    if _scoped_url_key(scope.get("url")) not in {"", _scoped_url_key(url)}:
        return {
            "sections": {},
            "specifications": {},
            "promoted_fields": {},
            "coverage": {},
            "aggregates": {},
            "table_groups": [],
            "scope": scope,
        }
    scope_ids = {
        str(value).strip().lower()
        for value in (scope.get("product_ids") or [])
        if str(value).strip()
    }
    current_ids = _scoped_record_identifiers({"url": url})
    for record in adapter_records:
        current_ids.update(_scoped_record_identifiers(record))
    if scope_ids and current_ids and scope_ids.isdisjoint(current_ids):
        return {
            "sections": {},
            "specifications": {},
            "promoted_fields": {},
            "coverage": {},
            "aggregates": {},
            "table_groups": [],
            "scope": scope,
        }
    return payload


def _scoped_url_key(value: object) -> str:
    parsed = urlsplit(str(value or "").strip())
    if not parsed.netloc:
        return ""
    return f"{parsed.netloc.lower()}{parsed.path.rstrip('/').lower()}"


def _scoped_record_identifiers(record: dict[str, object]) -> set[str]:
    identifiers: set[str] = set()
    for key in ("sku", "product_id", "job_id", "variant_id", "id", "handle"):
        value = str(record.get(key) or "").strip().lower()
        if value:
            identifiers.add(value)
    record_url = str(record.get("url") or record.get("source_url") or "").strip()
    if record_url:
        scoped_url = _scoped_url_key(record_url)
        if scoped_url:
            identifiers.add(scoped_url)
        path_parts = [part for part in urlsplit(record_url).path.split("/") if part]
        if path_parts:
            identifiers.add(path_parts[-1].lower())
    return identifiers


def _extract_label_value_from_text(
    field_name: str,
    text_sources: list[str],
    html: str,
    *,
    surface: str = "",
) -> str | None:
    """Search description text and HTML-derived text from the raw HTML for label/value patterns."""
    label_variants = _label_value_variants(field_name, surface=surface)
    combined_text_sources = list(text_sources)
    if html and field_name not in _HTML_LABEL_VALUE_FALLBACK_BLOCKED_FIELDS:
        combined_text_sources.append(_normalize_html_rich_text(html))

    for text in combined_text_sources:
        for variant in label_variants:
            pattern = _label_value_pattern(variant)
            match = pattern.search(text)
            if match:
                value = match.group(1).strip().rstrip(".")
                if 1 < len(value) < 200:
                    return value

    return None


@lru_cache(maxsize=512)
def _label_value_pattern(variant: str) -> re.Pattern[str]:
    return re.compile(
        re.escape(variant) + r"\s*:\s*(.+?)(?=\s+[A-Za-z]+:|\s+\(|\n|$|[.]\s|\u2022)",
        re.IGNORECASE,
    )


def _label_value_variants(field_name: str, *, surface: str = "") -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()

    def _append(label: object) -> None:
        text = " ".join(str(label or "").replace("_", " ").split()).strip()
        lowered = text.lower()
        if not lowered or lowered in seen:
            return
        seen.add(lowered)
        variants.append(text)

    _append(field_name)
    for alias in get_surface_field_aliases(surface).get(field_name, []):
        _append(alias)
    for alias in REQUESTED_FIELD_ALIASES.get(field_name, []):
        _append(alias)
    return variants


def _dom_pattern(soup: BeautifulSoup, field_name: str) -> dict | None:
    """Try common DOM patterns for well-known fields."""
    selector_group = DOM_PATTERNS.get(field_name)
    if not selector_group:
        return None
    for selector in [
        part.strip() for part in str(selector_group).split(",") if part.strip()
    ]:
        node = soup.select_one(selector)
        if not node:
            continue
        value = _extract_dom_node_value(node, field_name)
        if not value:
            continue
        return {
            "value": value,
            "source": "dom",
            "xpath": build_absolute_xpath(node),
            "css_selector": selector,
            "regex": None,
            "sample_value": value,
        }
    return None


def _extract_dom_node_value(node, field_name: str) -> str | None:
    value: str | None = None
    if node.name == "meta":
        value = node.get("content", "")
    elif field_name == "availability" and node.get("href"):
        value = node.get("href", "")
    elif field_name in ("apply_url", "image_url", "url") and node.get("href"):
        value = node.get("href", "")
    elif field_name == "image_url" and node.get("src"):
        value = node.get("src", "")
    else:
        value = node.get("content") or node.get_text(" ", strip=True)
    cleaned = str(value or "").strip()
    return cleaned or None


def _finalize_candidate_rows(
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


def _normalized_candidate_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


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


def _normalize_html_rich_text(value: str) -> str:
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


def _field_name_preference(field_name: str, *, target_fields: set[str]) -> int:
    tokens = [token for token in str(field_name or "").split("_") if token]
    score = 100 if field_name in target_fields else 0
    score += max(0, 20 - len(tokens))
    if re.match(r"^\d", field_name):
        score -= 30
    if "price" in tokens and len(tokens) > 2:
        score -= 20
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        score -= 30
    score -= sum(5 for token in tokens if token in DYNAMIC_FIELD_NAME_DROP_TOKENS)
    return score


def _dynamic_field_name_is_noisy(field_name: str) -> bool:
    normalized = str(field_name or "").strip().lower()
    if not normalized:
        return True
    if re.match(r"^\d", normalized):
        return True
    tokens = [token for token in normalized.split("_") if token]
    if not tokens:
        return True
    if len(tokens) > _DYNAMIC_FIELD_NAME_MAX_TOKENS:
        return True
    noise_hits = sum(1 for token in tokens if token in DYNAMIC_FIELD_NAME_DROP_TOKENS)
    if noise_hits >= 2:
        return True
    if "price" in tokens and len(tokens) > 2:
        return True
    if _dynamic_field_name_is_schema_slug_noise(normalized):
        return True
    if normalized in CANDIDATE_DYNAMIC_FIELD_NAME_HARD_REJECTS:
        return True
    return False


def _should_skip_jsonld_block(payload: dict, field_name: str) -> bool:
    """Skip non-product JSON-LD blocks for product-identity fields."""
    if field_name not in PRODUCT_IDENTITY_FIELDS:
        return False
    raw_types = payload.get("@type")
    if raw_types is None:
        type_names: list[object] = []
    elif isinstance(raw_types, str):
        type_names = [raw_types]
    elif isinstance(raw_types, (list, tuple)):
        type_names = list(raw_types)
    else:
        type_names = [raw_types]
    lowered_types = [
        str(type_name or "").lower()
        for type_name in type_names
        if str(type_name or "").strip()
    ]
    return any(
        type_name in JSONLD_NON_PRODUCT_BLOCK_TYPES for type_name in lowered_types
    )


def _build_label_value_text_sources(
    *,
    url: str,
    soup: BeautifulSoup,
    adapter_records: list[dict],
    network_payloads: list[dict],
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    open_graph: dict[str, object],
    json_ld: list[dict],
    microdata: list[dict],
) -> list[str]:
    text_sources: list[str] = []
    seen: set[str] = set()

    def _append_text(value: object) -> None:
        normalized = _normalized_candidate_text(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        text_sources.append(normalized)

    for selector in CANDIDATE_DESCRIPTION_META_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            _append_text(node.get("content"))

    for desc_field in LISTING_DESCRIPTION_CANDIDATE_FIELDS:
        rows: list[dict] = []
        for record in adapter_records:
            if isinstance(record, dict) and record.get(desc_field):
                rows.append({"value": record[desc_field], "source": "adapter"})
        for payload in network_payloads:
            if not isinstance(payload, dict):
                continue
            payload_url = str(payload.get("url") or "").lower()
            if _NETWORK_PAYLOAD_NOISE_URL_PATTERNS.search(payload_url):
                continue
            body = payload.get("body", {})
            if isinstance(body, (dict, list)):
                _append_source_candidates(
                    rows, desc_field, body, "network_intercept", base_url=url
                )
        for state in hydrated_states:
            _append_source_candidates(
                rows, desc_field, state, "hydrated_state", base_url=url
            )
        for payload in embedded_json:
            _append_source_candidates(
                rows, desc_field, payload, "embedded_json", base_url=url
            )
        if open_graph:
            _append_source_candidates(
                rows, desc_field, open_graph, "open_graph", base_url=url
            )
        if next_data:
            _append_source_candidates(
                rows, desc_field, next_data, "next_data", base_url=url
            )
        for payload in json_ld:
            if isinstance(payload, dict):
                _append_source_candidates(
                    rows, desc_field, payload, "json_ld", base_url=url
                )
        for item in microdata:
            if isinstance(item, dict):
                _append_source_candidates(
                    rows, desc_field, item, "microdata", base_url=url
                )
        dom_row = _dom_pattern(soup, desc_field)
        if dom_row:
            rows.append(dom_row)
        for row in rows:
            _append_text(row.get("value"))

    for selector in CANDIDATE_DESCRIPTION_FALLBACK_CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node is not None:
            _append_text(node.get_text("\n", strip=True))
            break

    return text_sources


def _deep_get_all_aliases(
    data: object, field_name: str, *, surface: str = "", max_depth: int = 5
) -> list[object]:
    matches: list[object] = []
    alias_tokens = _field_alias_tokens(field_name, surface=surface)
    if not alias_tokens or max_depth <= 0:
        return matches

    def _collect(node: object, depth: int, parent_key: str = "") -> None:
        if depth <= 0 or node in (None, "", [], {}):
            return
        if isinstance(node, dict):
            for current_key, value in node.items():
                if current_key in JSONLD_STRUCTURAL_KEYS:
                    continue
                if _normalized_field_token(
                    current_key
                ) in alias_tokens and value not in (None, "", [], {}):
                    matches.append(value)
                # Don't recurse into non-product containers
                normalized_key = _normalized_field_token(current_key)
                if normalized_key in NESTED_NON_PRODUCT_KEYS:
                    continue
                _collect(value, depth - 1, parent_key=current_key)
        elif isinstance(node, list):
            for item in node[:CANDIDATE_DEEP_ALIAS_LIST_SCAN_LIMIT]:
                _collect(item, depth - 1, parent_key=parent_key)

    _collect(data, max_depth)
    return matches


def _append_source_candidates(
    rows: list[dict],
    field_name: str,
    payload: object,
    source: str,
    *,
    base_url: str = "",
    source_metadata: dict[str, object] | None = None,
    surface: str = "",
) -> None:
    actual_payload = _embedded_blob_payload(payload)
    # Skip brand/entity_name extraction from GA data layer — GA brand is the retailer's
    # name, not the product manufacturer. JSON-LD (rank 6) will supply the real brand.
    if _field_is_type(field_name, "entity_name") and _looks_like_ga_data_layer(
        actual_payload
    ):
        return
    for match in _deep_get_all_aliases(
        actual_payload,
        field_name,
        surface=surface,
    ):
        value = coerce_field_candidate_value(field_name, match, base_url=base_url)
        if value is not None:
            row = {"value": value, "source": source}
            if source_metadata:
                row.update(source_metadata)
            rows.append(row)


def _dispatch_string_field_coercer(
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


def _field_alias_tokens(field_name: str, *, surface: str = "") -> set[str]:
    aliases = [field_name, *get_surface_field_aliases(surface).get(field_name, [])]
    return {token for alias in aliases if (token := _normalized_field_token(alias))}


def _normalized_field_token(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


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


def _resolve_candidate_url(value: str, base_url: str) -> str:
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


def _extract_breadcrumb_category(soup: BeautifulSoup) -> str | None:
    selectors = (
        "nav[aria-label*='breadcrumb' i] a",
        ".breadcrumb a",
        "[class*='breadcrumb' i] a",
        "[itemtype*='BreadcrumbList'] [itemprop='name']",
    )
    parts: list[str] = []
    for selector in selectors:
        nodes = soup.select(selector)
        if not nodes:
            continue
        candidate_parts = [
            _normalized_candidate_text(node.get_text(" ", strip=True))
            for node in nodes
            if _normalized_candidate_text(node.get_text(" ", strip=True))
        ]
        if candidate_parts:
            parts = candidate_parts
            break
    if not parts:
        return None
    if parts and parts[0].lower() == "home":
        parts = parts[1:]
    title_text = _normalized_candidate_text(
        (
            soup.select_one("main h1")
            or soup.select_one("article h1")
            or soup.select_one("h1")
        ).get_text(" ", strip=True)
        if (
            soup.select_one("main h1")
            or soup.select_one("article h1")
            or soup.select_one("h1")
        )
        else ""
    )
    if parts and title_text and _breadcrumb_item_matches_title(parts[-1], title_text):
        parts = parts[:-1]
    if not parts:
        return None
    return " > ".join(parts)


def _breadcrumb_item_matches_title(item: str, title: str) -> bool:
    def _normalize(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
        return " ".join(normalized.split())

    normalized_item = _normalize(item)
    normalized_title = _normalize(title)
    if not normalized_item or not normalized_title:
        return False
    if normalized_item == normalized_title:
        return True
    if normalized_item in normalized_title or normalized_title in normalized_item:
        return True
    item_tokens = set(normalized_item.split())
    title_tokens = set(normalized_title.split())
    if not item_tokens or not title_tokens:
        return False
    overlap = len(item_tokens & title_tokens)
    return overlap >= max(2, min(len(item_tokens), len(title_tokens)))


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


def _extract_image_urls(value: object, *, base_url: str = "") -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        resolved = _resolve_candidate_url(candidate, base_url)
        if not resolved:
            return
        lowered = resolved.lower()
        path = urlparse(resolved).path.lower()
        if any(token in lowered for token in CANDIDATE_IMAGE_NOISE_TOKENS):
            return
        if not (
            path.endswith(CANDIDATE_IMAGE_FILE_EXTENSIONS)
            or re.search(r"/(?:webp|jpeg|jpg|png)$", path)
            or any(token in lowered for token in CANDIDATE_IMAGE_URL_HINT_TOKENS)
        ):
            return
        if resolved in seen:
            return
        seen.add(resolved)
        urls.append(resolved)

    def _collect(node: object) -> None:
        if node in (None, "", [], {}):
            return
        if isinstance(node, str):
            for part in re.split(r"\s*\|\s*|\s*,\s*(?=https?://|//|/)", node):
                cleaned = _normalized_candidate_text(part)
                if cleaned:
                    _append(cleaned)
            return
        if isinstance(node, dict):
            for key in CANDIDATE_IMAGE_CANDIDATE_DICT_KEYS:
                candidate = node.get(key)
                if isinstance(candidate, str):
                    _append(candidate)
            for item in list(node.values())[:CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT]:
                _collect(item)
            return
        if isinstance(node, list):
            for item in node[:CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT]:
                _collect(item)

    _collect(value)
    return urls


def _field_in_group(field_name: str, group_name: str) -> bool:
    return field_name in CANDIDATE_FIELD_GROUPS.get(group_name, set())


def _field_token(field_name: str) -> str:
    return _normalized_field_token(field_name)


def _field_has_any_token(field_name: str, tokens: tuple[str, ...]) -> bool:
    normalized = _field_token(field_name)
    return any(
        _normalized_field_token(token) in normalized for token in tokens if token
    )


_FIELD_TYPE_TOKENS: dict[str, tuple[str, ...]] = {
    "image_primary": CANDIDATE_IMAGE_TOKENS,
    "url": CANDIDATE_URL_SUFFIXES,
    "currency": CANDIDATE_CURRENCY_TOKENS,
    "numeric": CANDIDATE_PRICE_TOKENS,
    "salary": CANDIDATE_SALARY_TOKENS,
    "rating": CANDIDATE_RATING_TOKENS,
    "availability": CANDIDATE_AVAILABILITY_TOKENS,
    "category": CANDIDATE_CATEGORY_TOKENS,
    "description": CANDIDATE_DESCRIPTION_TOKENS,
    "identifier": CANDIDATE_IDENTIFIER_TOKENS,
    "image_collection": CANDIDATE_IMAGE_COLLECTION_TOKENS,
}


def _field_is_type(field_name: str, type_key: str) -> bool:
    normalized = _field_token(field_name)

    if type_key in {"color", "size"}:
        return _field_matches_exact_alias(normalized, type_key)
    if type_key in ("title", "job_text", "entity_name"):
        return _field_in_group(field_name, type_key)

    is_img_coll = _field_is_image_collection(field_name, normalized=normalized)
    if type_key == "image_collection":
        return is_img_coll

    is_img_prim = _field_is_primary_image(
        field_name,
        normalized=normalized,
        is_image_collection=is_img_coll,
    )
    if type_key == "image_primary":
        return is_img_prim

    if type_key == "url":
        return _field_is_url_type(
            field_name,
            normalized=normalized,
            is_primary_image=is_img_prim,
            is_image_collection=is_img_coll,
        )

    if type_key == "numeric":
        return _field_is_numeric_type(field_name)

    return _field_in_group(field_name, type_key) or _field_has_any_token(
        field_name, _FIELD_TYPE_TOKENS.get(type_key, ())
    )


def _field_matches_exact_alias(normalized: str, field_name: str) -> bool:
    return normalized in _field_alias_tokens(field_name)


def _field_is_image_collection(field_name: str, *, normalized: str) -> bool:
    return _field_in_group(field_name, "image_collection") or any(
        token in normalized for token in _FIELD_TYPE_TOKENS["image_collection"]
    )


def _field_is_primary_image(
    field_name: str,
    *,
    normalized: str,
    is_image_collection: bool,
) -> bool:
    return _field_in_group(field_name, "image_primary") or (
        not is_image_collection
        and _field_has_any_token(field_name, _FIELD_TYPE_TOKENS["image_primary"])
        and bool(normalized)
    )


def _field_is_url_type(
    field_name: str,
    *,
    normalized: str,
    is_primary_image: bool,
    is_image_collection: bool,
) -> bool:
    if is_primary_image or is_image_collection:
        return False
    return _field_in_group(field_name, "url") or any(
        normalized.endswith(_normalized_field_token(suffix))
        for suffix in _FIELD_TYPE_TOKENS["url"]
    )


def _field_is_numeric_type(field_name: str) -> bool:
    return (
        _field_in_group(field_name, "numeric")
        or _field_has_any_token(field_name, _FIELD_TYPE_TOKENS["numeric"])
        or _field_has_any_token(field_name, CANDIDATE_REVIEW_COUNT_TOKENS)
    )


def _strip_ui_noise(value: str) -> str:
    text = _normalized_candidate_text(value)
    if not text:
        return ""
    if _UI_ICON_TOKEN_RE:
        text = _UI_ICON_TOKEN_RE.sub(" ", text)
    if _UI_NOISE_TOKEN_RE:
        text = _UI_NOISE_TOKEN_RE.sub(" ", text)
    if _SCRIPT_NOISE_RE:
        text = _SCRIPT_NOISE_RE.sub(" ", text)
    if _UI_NOISE_PHRASES_RE:
        text = _UI_NOISE_PHRASES_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -|,:;/")
    return text


def _looks_like_variant_selector_text(value: str) -> bool:
    text = _normalized_candidate_text(value)
    if not text:
        return False
    return bool(
        _VARIANT_SELECTOR_PROMPT_RE.match(text)
        or _CROSSFIELD_VARIANT_VALUE_RE.match(text)
    )


def _normalize_color_candidate(value: str) -> str | None:
    cleaned = _strip_ui_noise(value)
    if not cleaned:
        return None
    if _looks_like_variant_selector_text(cleaned):
        return None
    lowered = cleaned.lower()
    if any(token in lowered for token in CANDIDATE_COLOR_CSS_NOISE_TOKENS):
        return None
    if any(marker in cleaned for marker in ("{", "}", ";")):
        return None
    if "colors" in cleaned.lower() and cleaned.split()[0].isdigit():
        return None
    # Reject JavaScript minified booleans/expressions: !1 (false), !0 (true)
    if re.search(r"!\d", cleaned):
        return None
    # Reject JS object shorthand patterns: key:value with non-alpha keys
    if re.search(r"(?<![A-Za-z ])\s*:\s*!", cleaned):
        return None
    cleaned = re.sub(r"(?i)^choose an option\b", "", cleaned).strip(" ,")
    cleaned = re.sub(r"(?i)\bclear\b$", "", cleaned).strip(" ,")
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    if len(cleaned) > 40:
        return None
    if len(cleaned.split()) > 6:
        return None
    lowered_clean = cleaned.lower()
    if any(phrase in lowered_clean for phrase in _AVAILABILITY_NOISE_PHRASES):
        return None
    return cleaned or None


def _structured_source_candidates(
    field_name: str,
    *,
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    network_payloads: list[dict],
    base_url: str = "",
) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    sources: list[tuple[str, object, dict[str, object]]] = _structured_source_payloads(
        next_data=next_data,
        hydrated_states=hydrated_states,
        embedded_json=embedded_json,
        network_payloads=network_payloads,
        base_url=base_url,
    )
    for source, payload, metadata in sources:
        value = _extract_structured_field_value(payload, field_name)
        normalized = _normalized_candidate_text(value)
        if not normalized or _contains_unresolved_template_value(normalized):
            continue
        key = (source, normalized)
        if key in seen:
            continue
        seen.add(key)
        row = {"value": value, "source": source}
        if metadata:
            row.update(metadata)
        rows.append(row)
    return rows


def _build_variant_rows(
    *,
    base_url: str,
    soup: BeautifulSoup,
    adapter_records: list[dict],
    network_payloads: list[dict],
    structured_sources: list[tuple[str, object, dict[str, object]]] | None = None,
) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    adapter_variant_rows = _build_adapter_variant_rows(adapter_records)
    if adapter_variant_rows:
        _merge_dynamic_row_map(rows, adapter_variant_rows)

    demandware_rows = _build_demandware_variant_rows(
        network_payloads,
        base_url=base_url,
    )
    if demandware_rows:
        _merge_dynamic_row_map(rows, demandware_rows)

    structured_rows = _build_structured_variant_rows(
        structured_sources or [],
        base_url=base_url,
    )
    if structured_rows:
        _merge_dynamic_row_map(rows, structured_rows)

    dom_rows = _build_dom_variant_rows(soup, base_url=base_url)
    if dom_rows:
        _merge_dynamic_row_map(rows, dom_rows)

    return rows


def _merge_dynamic_row_map(
    target: dict[str, list[dict]],
    source: dict[str, list[dict]],
) -> None:
    for field_name, field_rows in source.items():
        target.setdefault(field_name, []).extend(field_rows)


def _find_variant_adapter_record(
    adapter_records: list[dict],
) -> dict[str, object] | None:
    for record in adapter_records:
        if isinstance(record, dict) and isinstance(record.get("variants"), list):
            return record
    return None


def _build_adapter_variant_rows(
    adapter_records: list[dict],
) -> dict[str, list[dict]]:
    record = _find_variant_adapter_record(adapter_records)
    if not isinstance(record, dict):
        return {}
    rows: dict[str, list[dict]] = {}
    source = str(record.get("_source") or "adapter").strip() or "adapter"
    variants = record.get("variants")
    if isinstance(variants, list) and variants:
        rows["variants"] = [{"value": variants, "source": source}]
    axes = record.get("variant_axes")
    if isinstance(axes, dict) and axes:
        rows["variant_axes"] = [{"value": axes, "source": source}]
    selected_variant = record.get("selected_variant")
    if selected_variant:
        rows["selected_variant"] = [{"value": selected_variant, "source": source}]
        for field_name in (
            "color",
            "size",
            "sku",
            "price",
            "original_price",
            "availability",
            "image_url",
        ):
            value = selected_variant.get(field_name)
            if value not in (None, "", [], {}):
                rows.setdefault(field_name, []).append(
                    {"value": value, "source": source}
                )
    product_attributes = record.get("product_attributes")
    if isinstance(product_attributes, dict) and product_attributes:
        rows["product_attributes"] = [{"value": product_attributes, "source": source}]
    return rows


def _build_demandware_variant_rows(
    network_payloads: list[dict], *, base_url: str
) -> dict[str, list[dict]]:
    parsed_variants = _extract_demandware_variants_from_payloads(
        network_payloads,
        base_url=base_url,
    )
    if not parsed_variants:
        return {}

    source = "network_intercept"
    rows: dict[str, list[dict]] = {}
    variants = parsed_variants.get("variants")
    if isinstance(variants, list) and variants:
        rows["variants"] = [{"value": variants, "source": source}]
    selectable_axes = parsed_variants.get("variant_axes")
    if isinstance(selectable_axes, dict) and selectable_axes:
        rows["variant_axes"] = [{"value": selectable_axes, "source": source}]
    product_attributes = parsed_variants.get("product_attributes")
    if isinstance(product_attributes, dict) and product_attributes:
        rows["product_attributes"] = [{"value": product_attributes, "source": source}]
    selected_variant = parsed_variants.get("selected_variant")
    if isinstance(selected_variant, dict) and selected_variant:
        rows["selected_variant"] = [{"value": selected_variant, "source": source}]
        for field_name in (
            "color",
            "size",
            "sku",
            "price",
            "original_price",
            "availability",
            "image_url",
        ):
            value = selected_variant.get(field_name)
            if value not in (None, "", [], {}):
                rows.setdefault(field_name, []).append(
                    {"value": value, "source": source}
                )
    return rows


def _extract_demandware_variants_from_payloads(
    network_payloads: list[dict], *, base_url: str
) -> dict[str, object]:
    variants: list[dict[str, object]] = []
    axis_values: dict[str, list[str]] = {}
    seen_variants: set[str] = set()
    selected_variant: dict[str, object] | None = None
    selected_score = -1

    for payload in network_payloads:
        parsed = _parse_demandware_variation_payload(payload, base_url=base_url)
        if not parsed:
            continue
        candidate = parsed.get("selected_variant")
        if isinstance(candidate, dict) and candidate:
            fingerprint = json.dumps(candidate, sort_keys=True, default=str)
            if fingerprint not in seen_variants:
                seen_variants.add(fingerprint)
                variants.append(candidate)
        for axis_name, values in (parsed.get("axis_values") or {}).items():
            cleaned_axis = _canonical_structured_key(axis_name)
            if not cleaned_axis:
                continue
            target = axis_values.setdefault(cleaned_axis, [])
            for value in values:
                cleaned_value = _normalized_candidate_text(value)
                if cleaned_value and cleaned_value not in target:
                    target.append(cleaned_value)
        score = int(parsed.get("selection_score") or 0)
        if isinstance(candidate, dict) and candidate and score >= selected_score:
            selected_variant = candidate
            selected_score = score

    selectable_axes, product_attributes = _split_variant_axes(axis_values)
    result: dict[str, object] = {}
    if variants:
        result["variants"] = variants
    if selectable_axes:
        result["variant_axes"] = selectable_axes
    if product_attributes:
        result["product_attributes"] = product_attributes
    if selected_variant:
        result["selected_variant"] = selected_variant
    return result


def _parse_demandware_variation_payload(
    payload: dict[str, object], *, base_url: str
) -> dict[str, object] | None:
    if not isinstance(payload, dict):
        return None
    payload_url = str(payload.get("url") or "")
    if not _is_demandware_variation_payload_url(payload_url):
        return None
    body = payload.get("body")
    root = (
        body.get("product")
        if isinstance(body, dict) and isinstance(body.get("product"), dict)
        else body
    )
    if not isinstance(root, dict):
        return None
    variation_attributes = root.get("variationAttributes") or root.get(
        "variation_attributes"
    )
    if not isinstance(variation_attributes, list) or not variation_attributes:
        return None

    axis_values: dict[str, list[str]] = {}
    selected_values = _demandware_selected_values_from_url(payload_url)
    for attribute in variation_attributes:
        if not isinstance(attribute, dict):
            continue
        axis_name = _normalize_demandware_axis_name(attribute)
        if not axis_name:
            continue
        raw_values = attribute.get("values")
        if not isinstance(raw_values, list):
            continue
        for raw_value in raw_values:
            if not isinstance(raw_value, dict):
                continue
            display_value = _normalized_candidate_text(
                raw_value.get("displayValue")
                or raw_value.get("displayvalue")
                or raw_value.get("value")
                or raw_value.get("id")
            )
            if display_value:
                axis_values.setdefault(axis_name, [])
                if display_value not in axis_values[axis_name]:
                    axis_values[axis_name].append(display_value)
            if raw_value.get("selected") is True and display_value:
                selected_values[axis_name] = display_value

    selected_variant = _build_demandware_selected_variant(
        root,
        base_url=base_url,
        payload_url=payload_url,
        selected_values=selected_values,
    )
    if not selected_variant:
        return None
    return {
        "axis_values": axis_values,
        "selected_variant": selected_variant,
        "selection_score": _score_demandware_selected_variant(
            selected_variant,
            base_url=base_url,
            payload_url=payload_url,
        ),
    }


def _is_demandware_variation_payload_url(payload_url: str) -> bool:
    lowered = str(payload_url or "").lower()
    return (
        "product-variation" in lowered
        or "/product/variation" in lowered
        or ("dwvar_" in lowered and "variation" in lowered)
    )


def _normalize_demandware_axis_name(attribute: dict[str, object]) -> str:
    label = (
        attribute.get("id")
        or attribute.get("attributeId")
        or attribute.get("displayName")
        or attribute.get("name")
    )
    normalized = _canonical_structured_key(label)
    if normalized:
        return normalized
    text = _normalized_candidate_text(label).lower()
    if text in {"colour", "colors", "colours"}:
        return "color"
    if text == "sizes":
        return "size"
    return text


def _demandware_selected_values_from_url(payload_url: str) -> dict[str, str]:
    selected: dict[str, str] = {}
    parsed = urlsplit(str(payload_url or "").strip())
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if not key.lower().startswith("dwvar_"):
            continue
        axis_name = key.split("_")[-1]
        normalized_axis = _canonical_structured_key(axis_name)
        cleaned_value = _normalized_candidate_text(value)
        if normalized_axis and cleaned_value:
            selected[normalized_axis] = cleaned_value
    return selected


def _build_demandware_selected_variant(
    root: dict[str, object],
    *,
    base_url: str,
    payload_url: str,
    selected_values: dict[str, str],
) -> dict[str, object] | None:
    row: dict[str, object] = {}
    _append_demandware_variant_identity(row, root)
    resolved_url = _resolve_candidate_url(_demandware_variant_url(root, base_url), base_url)
    if resolved_url:
        row["url"] = resolved_url
    option_values = _selected_demandware_option_values(selected_values)
    if option_values:
        row["option_values"] = option_values
        _append_demandware_variant_option_fields(row, option_values)
    _append_demandware_variant_commerce_fields(row, root)
    image_url = _extract_demandware_image_url(root, base_url=payload_url or base_url)
    if image_url:
        row["image_url"] = image_url
    return row or None


def _append_demandware_variant_identity(
    row: dict[str, object], root: dict[str, object]
) -> None:
    variant_id = root.get("id") or root.get("productId") or root.get("pid") or root.get("sku")
    if variant_id in (None, "", [], {}):
        return
    row["variant_id"] = str(variant_id)
    row["sku"] = str(variant_id)


def _demandware_variant_url(root: dict[str, object], base_url: str) -> object:
    return root.get("selectedProductUrl") or root.get("selected_product_url") or base_url


def _selected_demandware_option_values(
    selected_values: dict[str, str]
) -> dict[str, str]:
    return {
        axis_name: value
        for axis_name, value in selected_values.items()
        if value not in (None, "", [], {})
    }


def _append_demandware_variant_option_fields(
    row: dict[str, object],
    option_values: dict[str, str],
) -> None:
    for axis_name in ("color", "size"):
        if option_values.get(axis_name):
            row[axis_name] = option_values[axis_name]


def _append_demandware_variant_commerce_fields(
    row: dict[str, object],
    root: dict[str, object],
) -> None:
    for field_name, value in (
        (
            "price",
            _extract_demandware_price(
                root.get("price"),
                preferred_keys=("sales", "sale", "current"),
            ),
        ),
        (
            "original_price",
            _extract_demandware_price(
                root.get("price"),
                preferred_keys=("list", "regular", "base", "strikeThrough"),
            ),
        ),
        ("availability", _extract_demandware_availability(root)),
    ):
        if value:
            row[field_name] = value


def _extract_demandware_price(
    value: object, *, preferred_keys: tuple[str, ...]
) -> str | None:
    if isinstance(value, (str, int, float)):
        return normalize_and_validate_value("price", value)
    if not isinstance(value, dict):
        return None
    for key in preferred_keys:
        candidate = value.get(key)
        if isinstance(candidate, dict):
            for nested_key in ("formatted", "value", "amount", "price"):
                normalized = normalize_and_validate_value(
                    "price", candidate.get(nested_key)
                )
                if normalized:
                    return normalized
        else:
            normalized = normalize_and_validate_value("price", candidate)
            if normalized:
                return normalized
    for nested_key in ("formatted", "value", "amount", "price"):
        normalized = normalize_and_validate_value("price", value.get(nested_key))
        if normalized:
            return normalized
    return None


def _extract_demandware_availability(root: dict[str, object]) -> str | None:
    for model in (
        root,
        root.get("availability"),
        root.get("availabilityModel"),
        root.get("availability_model"),
        root.get("inventory"),
        root.get("inventoryRecord"),
    ):
        if not isinstance(model, dict):
            continue
        for key in ("availability", "message", "status", "stockLevelStatus"):
            normalized = normalize_and_validate_value("availability", model.get(key))
            if normalized:
                return str(normalized)
        if any(
            model.get(key) is True
            for key in (
                "readyToOrder",
                "ready_to_order",
                "orderable",
                "available",
                "inStock",
            )
        ):
            return "in_stock"
        if any(
            model.get(key) is False
            for key in (
                "readyToOrder",
                "ready_to_order",
                "orderable",
                "available",
                "inStock",
            )
        ):
            return "out_of_stock"
        try:
            ats = model.get("ats") or model.get("stockLevel")
            if ats is not None and float(ats) > 0:
                return "in_stock"
            if ats is not None and float(ats) <= 0:
                return "out_of_stock"
        except (TypeError, ValueError):
            continue
    return None


def _extract_demandware_image_url(
    root: dict[str, object], *, base_url: str
) -> str | None:
    images = root.get("images")
    if isinstance(images, dict):
        for key in ("large", "medium", "small"):
            values = images.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict):
                    resolved = _resolve_candidate_url(item.get("url"), base_url)
                else:
                    resolved = _resolve_candidate_url(item, base_url)
                if resolved:
                    return resolved
    featured = root.get("image") or root.get("featuredImage")
    if isinstance(featured, dict):
        return _resolve_candidate_url(
            featured.get("url") or featured.get("src"), base_url
        )
    return _resolve_candidate_url(featured, base_url)


def _score_demandware_selected_variant(
    variant: dict[str, object], *, base_url: str, payload_url: str
) -> int:
    score = 0
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        score += len(option_values)
        score += _demandware_selected_option_query_score(
            option_values,
            base_url=base_url,
        )
    if variant.get("url") and _scoped_url_key(
        str(variant.get("url"))
    ) == _scoped_url_key(base_url):
        score += 5
    if variant.get("availability") == "in_stock":
        score += 1
    if _is_demandware_variation_payload_url(payload_url):
        score += 1
    return score


def _demandware_selected_option_query_score(
    option_values: dict[str, object],
    *,
    base_url: str,
) -> int:
    parsed_base = urlsplit(str(base_url or "").strip())
    base_query = dict(parse_qsl(parsed_base.query, keep_blank_values=False))
    base_pid = base_query.get("pid")
    if not base_pid:
        return 0
    score = 0
    for axis_name, value in option_values.items():
        key = f"dwvar_{base_pid}_{axis_name}"
        if str(base_query.get(key) or "").strip() == str(value).strip():
            score += 10
    return score


def _split_variant_axes(
    axis_values: dict[str, list[str]],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    selectable: dict[str, list[str]] = {}
    product_attributes: dict[str, str] = {}
    for axis_name, values in axis_values.items():
        cleaned_values = list(
            dict.fromkeys(
                _normalized_candidate_text(value)
                for value in values
                if _normalized_candidate_text(value)
            )
        )
        if len(cleaned_values) > 1 or axis_name in _TRUE_VARIANT_AXES:
            selectable[axis_name] = cleaned_values
        elif len(cleaned_values) == 1:
            product_attributes[axis_name] = cleaned_values[0]
    return selectable, product_attributes


def _variant_axis_name(button) -> str:
    raw_data_attr = _normalized_candidate_text(button.get("data-attr")).lower()
    if raw_data_attr in {"color", "colour"}:
        return "color"
    if raw_data_attr == "size":
        return "size"
    data_attr = normalize_requested_field(raw_data_attr)
    if data_attr:
        return data_attr
    class_names = " ".join(button.get("class", []))
    if "color-attribute" in class_names:
        return "color"
    if "size-attribute" in class_names:
        return "size"
    attr_blob = " ".join(
        filter(
            None,
            (
                class_names,
                str(button.get("id") or ""),
                str(button.get("data-testid") or ""),
                str(button.get("data-reactid") or ""),
            ),
        )
    ).lower()
    if "colour" in attr_blob or "color" in attr_blob or "swatch" in attr_blob:
        return "color"
    if "size" in attr_blob:
        return "size"
    aria_label = str(button.get("aria-label") or "").lower()
    if "color" in aria_label:
        return "color"
    if "size" in aria_label:
        return "size"
    attr_name = _normalized_candidate_text(
        button.get("name") or button.get("data-name")
    )
    normalized_attr_name = normalize_requested_field(attr_name)
    if normalized_attr_name:
        return normalized_attr_name
    return ""


def _variant_button_label(button, *, axis_name: str) -> str:
    for attr_name in (
        "data-size",
        "data-color",
        "data-colour",
        "data-value",
        "data-label",
        "data-name",
        "title",
        "value",
        "aria-label",
    ):
        label = _normalized_candidate_text(button.get(attr_name))
        if label:
            return label
    span = button.find(attrs={"data-displayvalue": True}) or button.find(
        attrs={"data-display-value": True}
    )
    if span:
        label = _normalized_candidate_text(
            span.get("data-displayvalue") or span.get("data-display-value")
        )
        if label:
            return label
    described = button.find("span", class_="description")
    if described:
        label = _normalized_candidate_text(described.get_text(" ", strip=True))
        if label:
            return label
    aria_label = _normalized_candidate_text(button.get("aria-label"))
    if aria_label.lower().startswith("select "):
        parts = aria_label.split(" ", 2)
        if len(parts) == 3:
            return parts[2].strip()
    text = _normalized_candidate_text(button.get_text(" ", strip=True))
    if text:
        return text
    return axis_name


def _variant_button_selected(button) -> bool:
    class_names = " ".join(button.get("class", []))
    if "selected" in class_names:
        return True
    if button.select_one(".selected"):
        return True
    assistive = button.select_one(".selected-assistive-text")
    if assistive:
        return (
            "selected"
            in _normalized_candidate_text(assistive.get_text(" ", strip=True)).lower()
        )
    return False


def _selected_dom_variant(
    base_url: str, *, selected_values: dict[str, str]
) -> dict[str, object] | None:
    if not selected_values:
        return None
    row: dict[str, object] = {"url": base_url}
    option_values = {
        axis_name: value for axis_name, value in selected_values.items() if value
    }
    row.update(option_values)
    if option_values:
        row["option_values"] = option_values
    return row


def _build_dom_variant_rows(
    soup: BeautifulSoup, *, base_url: str
) -> dict[str, list[dict]]:
    axis_values, selected_values = _extract_dom_variant_axes(soup)
    if not axis_values:
        return {}

    selectable_axes, product_attributes = _split_variant_axes(axis_values)
    rows: dict[str, list[dict]] = {}
    if selectable_axes:
        rows["variant_axes"] = [{"value": selectable_axes, "source": "dom_variant"}]
    if product_attributes:
        rows["product_attributes"] = [
            {"value": product_attributes, "source": "dom_variant"}
        ]

    selected_variant = _selected_dom_variant(base_url, selected_values=selected_values)
    if selected_variant:
        rows["selected_variant"] = [
            {"value": selected_variant, "source": "dom_variant"}
        ]

    return rows


def _build_structured_variant_rows(
    structured_sources: list[tuple[str, object, dict[str, object]]],
    *,
    base_url: str,
) -> dict[str, list[dict]]:
    parsed_variants = _extract_structured_variants_from_sources(
        structured_sources,
        base_url=base_url,
    )
    if not parsed_variants:
        return {}

    source = "structured_variant"
    rows: dict[str, list[dict]] = {}
    variants = parsed_variants.get("variants")
    if isinstance(variants, list) and variants:
        rows["variants"] = [{"value": variants, "source": source}]
    selectable_axes = parsed_variants.get("variant_axes")
    if isinstance(selectable_axes, dict) and selectable_axes:
        rows["variant_axes"] = [{"value": selectable_axes, "source": source}]
    product_attributes = parsed_variants.get("product_attributes")
    if isinstance(product_attributes, dict) and product_attributes:
        rows["product_attributes"] = [{"value": product_attributes, "source": source}]
    selected_variant = parsed_variants.get("selected_variant")
    if isinstance(selected_variant, dict) and selected_variant:
        rows["selected_variant"] = [{"value": selected_variant, "source": source}]
        for field_name in (
            "color",
            "size",
            "sku",
            "price",
            "original_price",
            "availability",
            "image_url",
        ):
            value = selected_variant.get(field_name)
            if value not in (None, "", [], {}):
                rows.setdefault(field_name, []).append(
                    {"value": value, "source": source}
                )
    return rows


def _extract_structured_variants_from_sources(
    structured_sources: list[tuple[str, object, dict[str, object]]],
    *,
    base_url: str,
) -> dict[str, object]:
    variants: list[dict[str, object]] = []
    axis_values: dict[str, list[str]] = {}
    seen_variants: set[str] = set()
    selected_variant: dict[str, object] | None = None
    selected_score = -1
    selection_hints = _structured_variant_selection_hints(base_url)

    for _source_name, payload, _metadata in structured_sources:
        for container in _iter_structured_variant_containers(payload):
            parsed = _parse_structured_variant_container(
                container,
                base_url=base_url,
                selection_hints=selection_hints,
            )
            if not parsed:
                continue
            for variant in parsed.get("variants") or []:
                if not isinstance(variant, dict):
                    continue
                fingerprint = json.dumps(variant, sort_keys=True, default=str)
                if fingerprint in seen_variants:
                    continue
                seen_variants.add(fingerprint)
                variants.append(variant)
            for axis_name, values in (parsed.get("axis_values") or {}).items():
                cleaned_axis = _canonical_structured_key(axis_name)
                if not cleaned_axis:
                    continue
                target = axis_values.setdefault(cleaned_axis, [])
                for value in values:
                    cleaned_value = _normalized_candidate_text(value)
                    if cleaned_value and cleaned_value not in target:
                        target.append(cleaned_value)
            score = int(parsed.get("selection_score") or 0)
            candidate = parsed.get("selected_variant")
            if isinstance(candidate, dict) and candidate and score >= selected_score:
                selected_variant = candidate
                selected_score = score

    selectable_axes, product_attributes = _split_variant_axes(axis_values)
    result: dict[str, object] = {}
    if variants:
        result["variants"] = variants
    if selectable_axes:
        result["variant_axes"] = selectable_axes
    if product_attributes:
        result["product_attributes"] = product_attributes
    if selected_variant:
        result["selected_variant"] = selected_variant
    return result


def _iter_structured_variant_containers(
    payload: object,
    *,
    max_depth: int = 8,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    seen_objects: set[int] = set()
    seen_strings: set[str] = set()

    def walk(node: object, depth: int) -> None:
        if depth < 0 or node in (None, "", [], {}):
            return
        if isinstance(node, dict):
            node_id = id(node)
            if node_id in seen_objects:
                return
            seen_objects.add(node_id)
            if _looks_like_structured_variant_container(node):
                results.append(node)
            for value in node.values():
                walk(value, depth - 1)
            return
        if isinstance(node, list):
            for item in node[:200]:
                walk(item, depth - 1)
            return
        if not isinstance(node, str):
            return
        parsed = _parse_json_like_value(node)
        if not isinstance(parsed, (dict, list)):
            return
        cache_key = str(node[:500])
        if cache_key in seen_strings:
            return
        seen_strings.add(cache_key)
        walk(parsed, depth - 1)

    walk(payload, max_depth)
    return results


def _looks_like_structured_variant_container(payload: dict[str, object]) -> bool:
    variations = payload.get("variations")
    if not isinstance(variations, list) or not variations:
        return False
    dict_variations = [item for item in variations[:20] if isinstance(item, dict)]
    if not dict_variations:
        return False
    return any(
        key in payload
        for key in ("colors", "name", "id", "product", "orderable", "configureID")
    ) or any(
        any(
            token in variation
            for token in (
                "variantId",
                "id",
                "sku",
                "ean",
                "colorValue",
                "colorName",
                "price",
                "salePrice",
            )
        )
        for variation in dict_variations
    )


def _parse_structured_variant_container(
    payload: dict[str, object],
    *,
    base_url: str,
    selection_hints: dict[str, str],
) -> dict[str, object] | None:
    variations = payload.get("variations")
    if not isinstance(variations, list) or not variations:
        return None

    axis_values: dict[str, list[str]] = {}
    for color_name in _structured_color_axis_values(payload.get("colors")):
        axis_values.setdefault("color", [])
        if color_name not in axis_values["color"]:
            axis_values["color"].append(color_name)

    parsed_variants: list[dict[str, object]] = []
    selected_variant: dict[str, object] | None = None
    selected_score = -1
    for item in variations:
        if not isinstance(item, dict):
            continue
        variant = _build_structured_variant_row(
            item,
            base_url=base_url,
            selection_hints=selection_hints,
        )
        if not variant:
            continue
        parsed_variants.append(variant)
        option_values = variant.get("option_values")
        if isinstance(option_values, dict):
            for axis_name, value in option_values.items():
                cleaned_axis = _canonical_structured_key(axis_name)
                cleaned_value = _normalized_candidate_text(value)
                if not cleaned_axis or not cleaned_value:
                    continue
                target = axis_values.setdefault(cleaned_axis, [])
                if cleaned_value not in target:
                    target.append(cleaned_value)
        score = _score_structured_selected_variant(
            variant,
            raw_variant=item,
            base_url=base_url,
            selection_hints=selection_hints,
        )
        if score >= selected_score:
            selected_variant = variant
            selected_score = score

    if not parsed_variants:
        return None
    return {
        "variants": parsed_variants,
        "axis_values": axis_values,
        "selected_variant": selected_variant,
        "selection_score": selected_score,
    }


def _structured_color_axis_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    colors: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _normalized_candidate_text(
            item.get("name")
            or item.get("label")
            or item.get("colorName")
            or item.get("displayValue")
        )
        if name and name not in colors:
            colors.append(name)
    return colors


def _structured_variant_selection_hints(base_url: str) -> dict[str, str]:
    hints: dict[str, str] = {}
    parsed = urlsplit(str(base_url or "").strip())
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        normalized_key = normalize_requested_field(key)
        cleaned_value = _normalized_candidate_text(value)
        if not normalized_key or not cleaned_value:
            continue
        if normalized_key in {"swatch", "color", "colour"}:
            hints["color"] = cleaned_value
        elif normalized_key == "size":
            hints["size"] = cleaned_value
        elif normalized_key in {"variant", "variant_id", "sku", "pid", "vid", "id"}:
            hints["variant_id"] = cleaned_value
    return hints


def _build_structured_variant_row(
    payload: dict[str, object],
    *,
    base_url: str,
    selection_hints: dict[str, str],
) -> dict[str, object] | None:
    row: dict[str, object] = {}
    variant_id = _normalized_candidate_text(
        payload.get("variantId")
        or payload.get("ean")
        or payload.get("sku")
        or payload.get("id")
    )
    if variant_id:
        row["variant_id"] = variant_id
        row["sku"] = variant_id

    option_values = _structured_variant_option_values(payload)
    if option_values:
        row["option_values"] = option_values
        for axis_name in ("color", "size"):
            if option_values.get(axis_name):
                row[axis_name] = option_values[axis_name]

    url = _structured_variant_url(payload, base_url=base_url, selection_hints=selection_hints)
    if url:
        row["url"] = url

    price = normalize_and_validate_value(
        "price",
        payload.get("salePrice") or payload.get("price"),
    )
    if price:
        row["price"] = price
    original_price = normalize_and_validate_value(
        "price",
        payload.get("listPrice")
        or payload.get("originalPrice")
        or payload.get("compareAtPrice")
        or payload.get("compare_at_price"),
    )
    if original_price:
        row["original_price"] = original_price
    availability = _structured_variant_availability(payload)
    if availability:
        row["availability"] = availability
    image_url = _structured_variant_image_url(payload, base_url=base_url)
    if image_url:
        row["image_url"] = image_url
    return row or None


def _structured_variant_option_values(payload: dict[str, object]) -> dict[str, str]:
    option_values: dict[str, str] = {}
    raw_option_values = payload.get("option_values") or payload.get("optionValues")
    if isinstance(raw_option_values, dict):
        for key, value in raw_option_values.items():
            axis_name = _canonical_structured_key(key)
            cleaned_value = _normalized_candidate_text(value)
            if axis_name and cleaned_value:
                option_values[axis_name] = cleaned_value
    for axis_name, raw_value in (
        ("color", payload.get("colorName") or payload.get("color") or payload.get("colour")),
        ("size", payload.get("sizeName") or payload.get("size") or payload.get("displaySize")),
        ("waist", payload.get("waist")),
        ("length", payload.get("length")),
        ("width", payload.get("width")),
    ):
        cleaned_value = _normalized_candidate_text(raw_value)
        if cleaned_value:
            option_values[axis_name] = cleaned_value
    return option_values


def _structured_variant_url(
    payload: dict[str, object],
    *,
    base_url: str,
    selection_hints: dict[str, str],
) -> str | None:
    for field_name in ("url", "href", "permalink", "link"):
        resolved = _resolve_candidate_url(payload.get(field_name), base_url)
        if resolved:
            return resolved
    if not base_url:
        return None
    parsed = urlsplit(str(base_url or "").strip())
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "swatch" in query:
        swatch_value = _normalized_candidate_text(payload.get("colorValue"))
        if swatch_value:
            query["swatch"] = swatch_value
    elif selection_hints.get("color") and payload.get("colorValue"):
        query["color"] = _normalized_candidate_text(payload.get("colorValue"))
    encoded_query = urlencode(query, doseq=True)
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, encoded_query, parsed.fragment)
    )


def _structured_variant_availability(payload: dict[str, object]) -> str | None:
    for field_name in ("availability", "stockLevelStatus", "stock_status", "status"):
        normalized = normalize_and_validate_value("availability", payload.get(field_name))
        if normalized:
            return str(normalized)
    if any(payload.get(key) is True for key in ("orderable", "available", "inStock")):
        return "in_stock"
    if any(payload.get(key) is False for key in ("orderable", "available", "inStock")):
        return "out_of_stock"
    return None


def _structured_variant_image_url(
    payload: dict[str, object], *, base_url: str
) -> str | None:
    for field_name in ("preview", "image", "image_url", "imageUrl"):
        value = payload.get(field_name)
        if isinstance(value, dict):
            resolved = _resolve_candidate_url(
                value.get("href") or value.get("url") or value.get("src"),
                base_url,
            )
        else:
            resolved = _resolve_candidate_url(value, base_url)
        if resolved:
            return resolved
    images = payload.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict):
                resolved = _resolve_candidate_url(
                    item.get("href") or item.get("url") or item.get("src"),
                    base_url,
                )
            else:
                resolved = _resolve_candidate_url(item, base_url)
            if resolved:
                return resolved
    return None


def _score_structured_selected_variant(
    variant: dict[str, object],
    *,
    raw_variant: dict[str, object],
    base_url: str,
    selection_hints: dict[str, str],
) -> int:
    score = 0
    option_values = variant.get("option_values")
    if isinstance(option_values, dict):
        for axis_name, selected_value in selection_hints.items():
            option_value = _normalized_candidate_text(option_values.get(axis_name))
            if option_value and option_value.casefold() == selected_value.casefold():
                score += 10
    raw_color_value = _normalized_candidate_text(raw_variant.get("colorValue"))
    if raw_color_value and selection_hints.get("color"):
        if raw_color_value.casefold() == selection_hints["color"].casefold():
            score += 12
    for key in ("variant_id", "sku"):
        value = _normalized_candidate_text(variant.get(key))
        if value and selection_hints.get("variant_id"):
            if value.casefold() == selection_hints["variant_id"].casefold():
                score += 12
    if variant.get("availability") == "in_stock":
        score += 1
    if variant.get("url") and _scoped_url_key(str(variant.get("url"))) == _scoped_url_key(base_url):
        score += 5
    return score


def _extract_dom_variant_axes(
    soup: BeautifulSoup,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    axis_values: dict[str, list[str]] = {}
    selected_values: dict[str, str] = {}

    for select in soup.find_all("select"):
        if not isinstance(select, Tag) or _is_inside_site_chrome(select):
            continue
        axis_name = _variant_axis_name(select) or _variant_axis_name_from_context(select)
        if not axis_name:
            continue
        for option in select.find_all("option"):
            label = _variant_button_label(option, axis_name=axis_name)
            if not _dom_variant_value_is_valid(label, axis_name=axis_name):
                continue
            values = axis_values.setdefault(axis_name, [])
            if label not in values:
                values.append(label)
            if option.has_attr("selected"):
                selected_values[axis_name] = label

    candidate_nodes = soup.select(
        ",".join(
            (
                "[data-size]",
                "[data-color]",
                "[data-colour]",
                "[data-attr]",
                "[data-value]",
                "[role='radio']",
                "[role='option']",
                "button",
                "label",
                "li",
                "div",
            )
        )
    )
    for node in candidate_nodes:
        if not isinstance(node, Tag) or _is_inside_site_chrome(node):
            continue
        if not _looks_like_dom_variant_button(node):
            continue
        axis_name = _variant_axis_name(node) or _variant_axis_name_from_context(node)
        if not axis_name:
            continue
        label = _variant_button_label(node, axis_name=axis_name)
        if not _dom_variant_value_is_valid(label, axis_name=axis_name):
            continue
        values = axis_values.setdefault(axis_name, [])
        if label not in values:
            values.append(label)
        if _variant_button_selected(node):
            selected_values[axis_name] = label

    for axis_name, values in axis_values.items():
        if axis_name in selected_values:
            continue
        if values:
            selected_values[axis_name] = values[0]

    return axis_values, selected_values


def _variant_axis_name_from_context(node: Tag) -> str:
    candidates = [
        node.get("aria-label"),
        node.get("title"),
        node.get("name"),
        node.get("id"),
        " ".join(node.get("class", [])),
    ]
    for candidate in candidates:
        axis_name = _normalized_variant_axis_token(candidate)
        if axis_name:
            return axis_name

    for sibling in list(node.previous_siblings)[:4]:
        if not isinstance(sibling, Tag):
            continue
        axis_name = _normalized_variant_axis_token(sibling.get_text(" ", strip=True))
        if axis_name:
            return axis_name

    parent = node.parent
    steps = 0
    while isinstance(parent, Tag) and steps < 4:
        axis_name = _normalized_variant_axis_token(
            " ".join(
                filter(
                    None,
                    (
                        parent.get("aria-label"),
                        parent.get("title"),
                        parent.get("id"),
                        " ".join(parent.get("class", [])),
                    ),
                )
            )
        )
        if axis_name:
            return axis_name
        heading = parent.find(["legend", "label", "h2", "h3", "h4", "p", "span"])
        if isinstance(heading, Tag):
            axis_name = _normalized_variant_axis_token(
                heading.get_text(" ", strip=True)
            )
            if axis_name:
                return axis_name
        parent = parent.parent
        steps += 1
    return ""


def _normalized_variant_axis_token(value: object) -> str:
    text = _normalized_candidate_text(value).lower()
    if not text:
        return ""
    if any(token in text for token in ("size", "fit")):
        return "size"
    if any(token in text for token in ("color", "colour", "swatch")):
        return "color"
    return ""


def _looks_like_dom_variant_button(node: Tag) -> bool:
    if node.name not in {"button", "option", "label", "li"}:
        direct_children = node.find_all(["button", "option", "label", "li"], recursive=False)
        if direct_children:
            return False
    attr_blob = " ".join(
        filter(
            None,
            (
                str(node.get("aria-label") or ""),
                str(node.get("title") or ""),
                str(node.get("name") or ""),
                str(node.get("id") or ""),
                " ".join(node.get("class", [])),
            ),
        )
    ).lower()
    if any(
        token in attr_blob
        for token in ("size", "color", "colour", "swatch", "variant", "option")
    ):
        return True
    return any(
        node.has_attr(attr_name)
        for attr_name in (
            "data-size",
            "data-color",
            "data-colour",
            "data-attr",
            "data-value",
        )
    )


def _dom_variant_value_is_valid(value: str, *, axis_name: str) -> bool:
    text = _normalized_candidate_text(value)
    if not text:
        return False
    lowered = text.casefold()
    if lowered in {"select size", "choose size", "size", "select color", "color"}:
        return False
    if _VARIANT_SELECTOR_PROMPT_RE.match(text):
        return False
    if axis_name == "size" and re.fullmatch(r"[A-Za-z0-9.+/-]{1,8}", text):
        return True
    return len(text.split()) <= 5


def _build_dynamic_semantic_rows(
    semantic: dict,
    *,
    surface: str = "",
    allowed_fields: set[str] | None = None,
) -> dict[str, list[dict]]:
    specifications = (
        semantic.get("specifications")
        if isinstance(semantic.get("specifications"), dict)
        else {}
    )
    aggregates = (
        semantic.get("aggregates")
        if isinstance(semantic.get("aggregates"), dict)
        else {}
    )
    table_groups = (
        semantic.get("table_groups")
        if isinstance(semantic.get("table_groups"), list)
        else []
    )
    rows: dict[str, list[dict]] = {}

    for field_name, value in specifications.items():
        normalized = normalize_requested_field(field_name)
        if (
            not normalized
            or value in (None, "", [], {})
            or _DYNAMIC_NUMERIC_FIELD_RE.fullmatch(normalized)
        ):
            continue
        if normalized in JSONLD_TYPE_NOISE:
            continue
        if not _dynamic_field_name_is_valid(normalized):
            continue
        coerced = _coerce_scalar_for_dynamic_row(value)
        if coerced is None:
            continue
        rows.setdefault(normalized, []).append(
            {"value": coerced, "source": "semantic_spec"}
        )

    for group in table_groups:
        if not isinstance(group, dict):
            continue
        group_label = _normalized_candidate_text(
            group.get("title")
        ) or _normalized_candidate_text(group.get("caption"))
        for row in group.get("rows") or []:
            if not isinstance(row, dict):
                continue
            normalized = normalize_requested_field(
                row.get("normalized_key") or row.get("label")
            )
            display_label = _normalized_candidate_text(row.get("label")) or normalized
            value = row.get("value")
            if (
                not normalized
                or value in (None, "", [], {})
                or _DYNAMIC_NUMERIC_FIELD_RE.fullmatch(normalized)
            ):
                continue
            if not _dynamic_field_name_is_valid(normalized):
                continue
            coerced = _coerce_scalar_for_dynamic_row(value)
            if coerced is None:
                continue
            target_fields = [normalized]
            if normalized == "dimensions" and display_label.casefold() == "size":
                target_fields.append("size")
            for target_field in target_fields:
                rows.setdefault(target_field, []).append(
                    {
                        "value": coerced,
                        "source": "semantic_spec",
                        "display_label": display_label,
                        "group_label": group_label or None,
                        "href": _normalized_candidate_text(row.get("href")) or None,
                        "preserve_visible": bool(row.get("preserve_visible")),
                        "row_index": row.get("row_index"),
                        "table_index": group.get("table_index"),
                    }
                )

    # Only emit specification/dimension aggregates when the semantic extractor
    # found real spec entries (tables, dl, data-attributes). Skip phantom
    # aggregates built from inline label/value guesses on JS-shell pages.
    spec_entry_count = len(specifications)
    for aggregate_field in ("specifications", "dimensions"):
        value = aggregates.get(aggregate_field)
        if value in (None, "", [], {}):
            continue
        if aggregate_field == "specifications" and str(
            surface or ""
        ).lower().startswith("job_"):
            continue
        if aggregate_field in {"specifications", "dimensions"} and spec_entry_count < 2:
            continue
        coerced_agg = _coerce_scalar_for_dynamic_row(value)
        if coerced_agg is None:
            continue
        rows.setdefault(aggregate_field, []).append(
            {"value": coerced_agg, "source": "semantic_spec"}
        )

    feature_value = aggregates.get("features")
    if feature_value not in (None, "", [], {}):
        coerced_features = _coerce_scalar_for_dynamic_row(feature_value)
        if coerced_features is not None:
            rows.setdefault("features", []).append(
                {
                    "value": coerced_features,
                    "source": "semantic_section",
                }
            )
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
    rows: dict[str, list[dict]] = {}
    shopify_product = _find_variant_adapter_record(adapter_records)
    if shopify_product:
        _merge_dynamic_row_map(
            rows,
            _build_shopify_content_rows(shopify_product, base_url=base_url),
        )
    _merge_dynamic_row_map(rows, _build_dom_section_rows(soup))
    _merge_dynamic_row_map(rows, _build_dom_gallery_rows(soup, base_url=base_url))
    return rows


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
        for tr in node.find_all("tr", recursive=True):
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


def _build_dom_section_rows(soup: BeautifulSoup) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}

    product_attributes: dict[str, object] = {}
    for header_text, content_text in _iter_dom_sections(soup):
        normalized_header = normalize_requested_field(header_text)
        if not normalized_header or not content_text:
            continue
        if _is_noisy_product_attribute_entry(normalized_header, content_text):
            continue
        if normalized_header in {"description", "summary", "overview"}:
            rows.setdefault("description", []).append(
                {"value": content_text, "source": "dom_section"}
            )
            continue
        if normalized_header in {
            "details",
            "specifications",
            "product_details",
            "technical_details",
        }:
            rows.setdefault("specifications", []).append(
                {"value": content_text, "source": "dom_section"}
            )
            product_attributes.setdefault(normalized_header, content_text)
            continue
        if normalized_header in {"features", "key_features", "highlights"}:
            rows.setdefault("features", []).append(
                {"value": content_text, "source": "dom_section"}
            )
            continue
        if normalized_header in {
            "materials",
            "material_composition",
            "fabric",
            "composition",
        }:
            rows.setdefault("materials", []).append(
                {"value": content_text, "source": "dom_section"}
            )
        product_attributes.setdefault(normalized_header, content_text)

    if product_attributes:
        rows.setdefault("product_attributes", []).append(
            {"value": product_attributes, "source": "dom_section"}
        )
    return rows


_SITE_CHROME_ANCESTORS = frozenset({"footer", "nav", "header", "aside"})


def _is_inside_site_chrome(node: Tag) -> bool:
    for ancestor in node.parents:
        if not isinstance(ancestor, Tag):
            continue
        if ancestor.name in _SITE_CHROME_ANCESTORS:
            return True
    return False


def _iter_dom_sections(soup: BeautifulSoup) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _append(header: str, content: str) -> None:
        normalized_header = _normalized_candidate_text(header)
        normalized_content = _normalized_candidate_text(content)
        if not normalized_header or not normalized_content:
            return
        key = (normalized_header.casefold(), normalized_content.casefold())
        if key in seen:
            return
        seen.add(key)
        sections.append((normalized_header, content.strip()))

    for details in soup.find_all("details"):
        if not isinstance(details, Tag) or _is_inside_site_chrome(details):
            continue
        summary = details.find("summary")
        if not isinstance(summary, Tag):
            continue
        body_parts = [
            _section_content_text(child)
            for child in details.children
            if child is not summary and isinstance(child, Tag)
        ]
        _append(
            _normalized_candidate_text(summary.get_text(" ", strip=True)),
            "\n\n".join(part for part in body_parts if part),
        )

    for node in soup.select(
        "[data-tab], [data-tab-content], [data-panel], [role='tabpanel']"
    ):
        if not isinstance(node, Tag):
            continue
        if _is_inside_site_chrome(node):
            continue
        label = _normalized_candidate_text(
            node.get("data-tab")
            or node.get("data-title")
            or node.get("aria-label")
            or (
                node.find_previous(["button", "h2", "h3", "h4"]).get_text(
                    " ", strip=True
                )
                if node.find_previous(["button", "h2", "h3", "h4"])
                else ""
            )
        )
        _append(label, _section_content_text(node))

    for heading in soup.find_all(["h2", "h3", "h4", "h5"]):
        if not isinstance(heading, Tag):
            continue
        if _is_inside_site_chrome(heading):
            continue
        header = _normalized_candidate_text(heading.get_text(" ", strip=True))
        if not header:
            continue
        content = _collect_heading_section_content(heading)
        _append(header, content)

    return sections


def _collect_heading_section_content(heading: Tag) -> str:
    parts: list[str] = []
    for sibling in tuple(getattr(heading, "next_siblings", ())):
        if not isinstance(sibling, Tag):
            continue
        if sibling.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            break
        text = _section_content_text(sibling)
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def _collect_non_empty_section_text(nodes: object) -> list[str]:
    parts: list[str] = []
    for node in list(nodes or []):
        if not isinstance(node, Tag):
            continue
        text = _section_content_text(node)
        if text:
            parts.append(text)
    return parts


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
    rows["additional_images"] = [
        {
            "value": ", ".join(image_urls[1:] if len(image_urls) > 1 else image_urls),
            "source": "dom_gallery",
        }
    ]
    return rows


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
        record["additional_images"] = ", ".join(
            images[1:] if len(images) > 1 else images
        )

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

    fit_text = _product_detail_fit_and_sizing(detail)
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


def _product_detail_fit_and_sizing(detail: dict) -> str | None:
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
            _normalized_candidate_text(sizing_chart.get("url")), base_url=""
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


def _extract_structured_field_value(payload: object, field_name: str) -> str | None:
    spec_map = _extract_structured_spec_map(payload)
    if not spec_map:
        return None
    if field_name == "specifications":
        return (
            SEMANTIC_AGGREGATE_SEPARATOR.join(
                f"{label}: {value}" for label, value in spec_map.items()
            )
            or None
        )
    if field_name == "dimensions":
        dimension_pairs = [
            f"{label}: {value}"
            for label, value in spec_map.items()
            if any(token in label.lower() for token in DIMENSION_KEYWORDS)
        ]
        return SEMANTIC_AGGREGATE_SEPARATOR.join(dimension_pairs) or None
    return spec_map.get(normalize_requested_field(field_name)) or spec_map.get(
        field_name
    )


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


_NETWORK_PAYLOAD_NOISE_URL_PATTERNS = re.compile(
    r"geolocation|geoip|geo/|/geo\b|"
    r"\banalytics\b|tracking|telemetry|"
    r"klarna\.com|affirm\.com|afterpay\.com|"
    r"olapic-cdn\.com|"
    r"livechat|zendesk\.com|intercom\.io|"
    r"facebook\.com|google-analytics|googletagmanager|"
    r"sentry\.io|datadome|px\.ads|"
    r"cdn-cgi/|captcha",
    re.IGNORECASE,
)


def _structured_source_payloads(
    *,
    next_data: object,
    hydrated_states: list[object],
    embedded_json: list[object],
    network_payloads: list[dict],
    base_url: str = "",
) -> list[tuple[str, object, dict[str, object]]]:
    sources: list[tuple[str, object, dict[str, object]]] = []
    if _payload_matches_page_scope(next_data, base_url=base_url):
        sources.append(("next_data", next_data, {}))
    sources.extend(
        ("hydrated_state", payload, {})
        for payload in hydrated_states
        if _payload_matches_page_scope(payload, base_url=base_url)
    )
    sources.extend(
        (
            "embedded_json",
            _embedded_blob_payload(payload),
            _embedded_blob_metadata(payload),
        )
        for payload in embedded_json
        if _payload_matches_page_scope(payload, base_url=base_url)
    )
    for payload in network_payloads:
        if not isinstance(payload, dict):
            continue
        payload_url = str(payload.get("url") or "").lower()
        if _NETWORK_PAYLOAD_NOISE_URL_PATTERNS.search(payload_url):
            continue
        if _payload_matches_page_scope(payload.get("body"), base_url=base_url):
            sources.append(("network_intercept", payload.get("body"), {}))
    return sources


def _payload_matches_page_scope(payload: object, *, base_url: str) -> bool:
    if not base_url or payload in (None, "", [], {}):
        return True
    page_scope = _scoped_url_key(base_url)
    page_tokens = _page_scope_tokens(base_url)
    urls, handles = _payload_scope_hints(payload)
    normalized_urls = {_scoped_url_key(url) for url in urls if _scoped_url_key(url)}
    normalized_handles = {
        normalize_requested_field(handle) or str(handle).strip().lower()
        for handle in handles
        if str(handle).strip()
    }
    if normalized_urls:
        if page_scope in normalized_urls:
            return True
        if any(
            token and any(token in scoped_url for scoped_url in normalized_urls)
            for token in page_tokens
        ):
            return True
        return False
    if normalized_handles:
        return any(token in normalized_handles for token in page_tokens if token)
    return True


def _page_scope_tokens(base_url: str) -> set[str]:
    parsed = urlsplit(str(base_url or "").strip())
    tokens = {
        normalize_requested_field(part) or part.lower()
        for part in parsed.path.split("/")
        if part and part not in {"products", "product", "collections"}
    }
    return {token for token in tokens if token}


def _payload_scope_hints(
    payload: object, *, max_depth: int = 4
) -> tuple[set[str], set[str]]:
    urls: set[str] = set()
    handles: set[str] = set()
    if max_depth <= 0 or payload in (None, "", [], {}):
        return urls, handles
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized_key = normalize_requested_field(key)
            if isinstance(value, str):
                cleaned = str(value).strip()
                if normalized_key and normalized_key.endswith("url") and cleaned:
                    urls.add(cleaned)
                if (
                    normalized_key
                    in {"handle", "slug", "product_handle", "product_slug"}
                    and cleaned
                ):
                    handles.add(cleaned)
            child_urls, child_handles = _payload_scope_hints(
                value, max_depth=max_depth - 1
            )
            urls.update(child_urls)
            handles.update(child_handles)
    elif isinstance(payload, list):
        for item in payload[:LISTING_PRODUCT_DETAIL_LIST_SCAN_LIMIT]:
            child_urls, child_handles = _payload_scope_hints(
                item, max_depth=max_depth - 1
            )
            urls.update(child_urls)
            handles.update(child_handles)
    return urls, handles


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


def _contains_unresolved_template_value(value: object) -> bool:
    text = _normalized_candidate_text(value)
    if not text:
        return False
    return bool(_UNRESOLVED_TEMPLATE_VALUE_RE.search(text))


def _domain(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc.lower() or parsed.path.lower()


def _build_xpath_tree(document_html: str):
    try:
        return lxml_html.fromstring(document_html)
    except (etree.ParserError, ValueError):
        return None


def _index_extraction_contract(extraction_contract: list[dict]) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in extraction_contract:
        field_name = str(row.get("field_name", "")).strip()
        if field_name and field_name not in indexed:
            indexed[field_name] = row
    return indexed


def _extract_xpath_value(tree, xpath: str) -> str | None:
    if tree is None or not xpath.strip():
        return None
    try:
        results = tree.xpath(xpath)
    except etree.XPathError:
        return None
    if not results:
        return None
    first = results[0]
    if isinstance(first, str):
        return first.strip() or None
    if hasattr(first, "text_content"):
        value = first.text_content().strip()
        return value or None
    value = str(first).strip()
    return value or None


def _extract_regex_value(document_html: str, pattern: str) -> str | None:
    if not pattern.strip():
        return None
    try:
        match = re.search(pattern, document_html, re.DOTALL)
    except re.error:
        return None
    if not match:
        return None
    if match.groups():
        return next((group for group in match.groups() if group), None)
    return match.group(0)
