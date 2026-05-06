"""Public persisted/exported record policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from app.services.config._export_data import load_export_data
from app.services.config.field_mappings import (
    APPLY_URL_FIELD,
    CANONICAL_URL_FIELD,
    URL_FIELD,
    VARIANTS_FIELD,
)

_EXPORTS_PATH = Path(__file__).with_name("field_mappings.exports.json")
_STATIC_EXPORTS = load_export_data(str(_EXPORTS_PATH))

PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS: Mapping[str, Sequence[str]] = _STATIC_EXPORTS[
    "PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS"
]
PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS: tuple[str, ...] = _STATIC_EXPORTS[
    "PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS"
]
PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES: tuple[str, ...] = _STATIC_EXPORTS[
    "PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES"
]
PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS: tuple[str, ...] = _STATIC_EXPORTS[
    "PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS"
]
PUBLIC_RECORD_URL_MAX_LENGTH: int = _STATIC_EXPORTS["PUBLIC_RECORD_URL_MAX_LENGTH"]

PUBLIC_RECORD_CANONICAL_SURFACE = "ecommerce_detail"
PUBLIC_RECORD_CANONICAL_URL_FIELDS = frozenset(
    {APPLY_URL_FIELD, CANONICAL_URL_FIELD, URL_FIELD}
)
PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS = frozenset(
    {"page_markdown", "table_markdown", "record_type"}
)
PUBLIC_RECORD_MARKDOWN_HIDDEN_FIELDS = frozenset({"product_attributes", VARIANTS_FIELD})
PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS = frozenset({"tags"})
PUBLIC_RECORD_LEGACY_VARIANT_FIELDS = frozenset(
    {
        "selected_variant",
        "variant_axes",
        "available_sizes",
        "option1_name",
        "option1_values",
        "option2_name",
        "option2_values",
        "option_1_name",
        "option_1_value",
        "option_1_values",
        "option_2_name",
        "option_2_value",
        "option_2_values",
    }
)
PUBLIC_RECORD_BARCODE_LENGTHS = frozenset({8, 12, 13, 14})
PUBLIC_RECORD_BRAND_REGION_SUFFIX_TOKENS = frozenset(
    {
        "USA",
        "US",
        "UK",
        "EU",
        "EN",
        "CA",
        "AU",
        "IN",
        "UAE",
        "GCC",
        "GLOBAL",
        "INTL",
        "INTERNATIONAL",
        "OFFICIAL",
        "ONLINE",
        "STORE",
        "SHOP",
        "HOME",
        "WEBSITE",
    }
)
PUBLIC_RECORD_GENDER_TAXONOMY = MappingProxyType(
    {
        "men": "Men",
        "man": "Men",
        "male": "Men",
        "mens": "Men",
        "men's": "Men",
        "women": "Women",
        "woman": "Women",
        "female": "Women",
        "womens": "Women",
        "women's": "Women",
        "unisex": "Unisex",
        "uni": "Unisex",
        "kids": "Kids",
        "kid": "Kids",
        "children": "Kids",
        "child": "Kids",
        "boys": "Boys",
        "boy": "Boys",
        "girls": "Girls",
        "girl": "Girls",
    }
)
PUBLIC_RECORD_GENDER_REJECT_TOKENS = frozenset(
    {"default", "null", "na", "n/a", "none", "all", "other", ""}
)
PUBLIC_RECORD_IDENTITY_INTERNAL_TOKENS = frozenset(
    {
        "plp",
        "pdp",
        "specifications",
        "specification",
        "description",
        "details",
        "detail",
        "overview",
        "reviews",
        "review",
        "summary",
        "untitled",
    }
)
PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS = frozenset(
    {"brightcove", "video", "player", "iframe", "embed", "widget"}
)
PUBLIC_RECORD_SKU_DRAFT_PREFIX_PATTERN = r"^(?:copy|draft|tmp|temp|test)[-_]+"
