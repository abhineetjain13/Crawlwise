from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data
from app.services.config.runtime_settings import crawler_runtime_settings

_EXPORTS_PATH = Path(__file__).with_name("extraction_rules.exports.json")
_STATIC_EXPORTS = {
    name: value
    for name, value in load_export_data(str(_EXPORTS_PATH)).items()
    if not name.startswith("_")
}

for _name, _value in _STATIC_EXPORTS.items():
    globals()[_name] = _value

EXPORT_IMAGE_URL_SUFFIXES = tuple(CANDIDATE_IMAGE_FILE_EXTENSIONS)
BARE_HOST_URL_RE = re.compile(str(BARE_HOST_URL_PATTERN), re.I)
DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES = frozenset(
    {
        "description",
        "details",
        "normal",
        "overview",
        "product label",
        "product summary",
        "specifications",
    }
)
DETAIL_LOW_SIGNAL_TITLE_VALUES = frozenset(
    {
        "mens shoes",
        "men's shoes",
        "womens shoes",
        "women's shoes",
        "shoes",
    }
)
DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES = frozenset({"criteoproductrail"})
ORACLE_HCM_CX_CONFIG_RE = re.compile(
    r"(?:var\s+|window\.)?CX_CONFIG\s*=\s*(\{.*?\})\s*(?:;|</script>)",
    re.DOTALL,
)
ORACLE_HCM_SITE_PATH_RE = re.compile(
    r"/CandidateExperience/[^/?#]+/sites/([^/?#]+)(?:/|$)",
    re.IGNORECASE,
)
ORACLE_HCM_LANG_PATH_RE = re.compile(
    r"/CandidateExperience/([^/?#]+)/sites/",
    re.IGNORECASE,
)
ORACLE_HCM_JOB_PATH_RE = re.compile(
    r"/CandidateExperience/[^/?#]+/sites/[^/?#]+/job/([^/?#]+)(?:/|$)",
    re.IGNORECASE,
)
ORACLE_HCM_DEFAULT_FACETS = (
    "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;"
    "ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"
)
ORACLE_HCM_LOCATION_LIST_KEYS = (
    "workLocation",
    "otherWorkLocations",
    "secondaryLocations",
)
DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS = (
    r"\b(?:shipping|delivery|pickup|pick\s*up)\b.{0,80}\b(?:checkout|options?|available)\b",
    r"\bget\s+it\s+today\b.{0,120}\b(?:shipping|delivery|pickup|pick\s*up)\b",
)
DETAIL_CENT_PRICE_HOST_SUFFIXES = (
    "farfetch.com",
    "kith.com",
    "puma.com",
    "ssense.com",
)
VARIANT_SIZE_ALIAS_SUFFIXES = (" us",)
VARIANT_OPTION_VALUE_UI_NOISE_PHRASES = (
    "sign up",
    "updates and promotions",
)
DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS = frozenset(
    {
        "boot",
        "boots",
        "dress",
        "jacket",
        "oxford",
        "oxfords",
        "pants",
        "sandal",
        "sandals",
        "shirt",
        "shoe",
        "shoes",
        "sneaker",
        "sneakers",
        "t-shirt",
        "tee",
    }
)
DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS = frozenset(
    {
        "casual",
        "dress",
        "lace",
        "men",
        "mens",
        "shoe",
        "shoes",
        "the",
        "up",
        "with",
        "women",
        "womens",
    }
)
DETAIL_TITLE_DIMENSION_SIZE_PATTERN = r"\b\d{2,}(?:\.\d+)?\s*(?:\"|in\.?|inch|inches)"
DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX = 4
DETAIL_LONG_TEXT_SOURCE_RANKS = {
    "adapter": 0,
    "network_payload": 1,
    "dom_sections": 2,
    "selector_rule": 3,
    "dom_selector": 4,
    "json_ld": 5,
    "microdata": 6,
    "embedded_json": 7,
    "js_state": 8,
    "opengraph": 9,
    "dom_h1": 10,
    "dom_canonical": 11,
    "dom_images": 12,
    "dom_text": 13,
}
IMAGE_FIELDS = frozenset(IMAGE_FIELDS)
INTEGER_VALUE_FIELDS = frozenset(INTEGER_VALUE_FIELDS)
LONG_TEXT_FIELDS = frozenset(LONG_TEXT_FIELDS)
LISTING_PRICE_NODE_SELECTORS = (
    "[itemprop='price']",
    "[class*='price']",
    "[data-testid*='price']",
    "[data-price]",
    "[aria-label*='price']",
)
LISTING_PROMINENT_TITLE_TAGS = frozenset({"strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"})
JSON_RECORD_LIST_KEYS = (
    "data",
    "edges",
    "entries",
    "items",
    "jobs",
    "listings",
    "nodes",
    "posts",
    "products",
    "records",
    "results",
)
PERCENT_RE = re.compile(str(PERCENT_PATTERN))
PRICE_VALUE_FIELDS = frozenset(PRICE_VALUE_FIELDS)
SEMANTIC_SECTION_LABEL_SKIP_TOKENS = tuple(
    sorted(
        {
            *(str(token).lower() for token in (SEMANTIC_SECTION_NOISE.get("label_skip_tokens") or ())),
            "answer",
            "answers",
            "q&a",
            "question",
            "questions",
            "rating snapshot",
            "review",
            "reviews",
        }
    )
)
RATING_RE = re.compile(str(RATING_PATTERN), re.I)
REVIEW_COUNT_RE = re.compile(str(REVIEW_COUNT_PATTERN), re.I)
REVIEW_TITLE_RE = re.compile(str(REVIEW_TITLE_PATTERN), re.I)
STRUCTURED_MULTI_FIELDS = frozenset(STRUCTURED_MULTI_FIELDS)
STRUCTURED_OBJECT_FIELDS = frozenset(STRUCTURED_OBJECT_FIELDS)
STRUCTURED_OBJECT_LIST_FIELDS = frozenset(STRUCTURED_OBJECT_LIST_FIELDS)
URL_FIELDS = frozenset(URL_FIELDS)

DYNAMIC_FIELD_NAME_MAX_TOKENS = crawler_runtime_settings.dynamic_field_name_max_tokens
MAX_CANDIDATES_PER_FIELD = crawler_runtime_settings.max_candidates_per_field

_EXTRA_EXPORTS = [
    "BARE_HOST_URL_RE",
    "DETAIL_CENT_PRICE_HOST_SUFFIXES",
    "DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS",
    "DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS",
    "DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS",
    "DETAIL_LONG_TEXT_SOURCE_RANKS",
    "DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES",
    "DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX",
    "DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES",
    "DETAIL_LOW_SIGNAL_TITLE_VALUES",
    "DETAIL_TITLE_DIMENSION_SIZE_PATTERN",
    "DYNAMIC_FIELD_NAME_MAX_TOKENS",
    "EXPORT_IMAGE_URL_SUFFIXES",
    "IMAGE_FIELDS",
    "INTEGER_VALUE_FIELDS",
    "JSON_RECORD_LIST_KEYS",
    "LISTING_PRICE_NODE_SELECTORS",
    "LISTING_PROMINENT_TITLE_TAGS",
    "LONG_TEXT_FIELDS",
    "MAX_CANDIDATES_PER_FIELD",
    "ORACLE_HCM_CX_CONFIG_RE",
    "ORACLE_HCM_DEFAULT_FACETS",
    "ORACLE_HCM_JOB_PATH_RE",
    "ORACLE_HCM_LANG_PATH_RE",
    "ORACLE_HCM_LOCATION_LIST_KEYS",
    "ORACLE_HCM_SITE_PATH_RE",
    "PERCENT_RE",
    "PRICE_VALUE_FIELDS",
    "RATING_RE",
    "REVIEW_COUNT_RE",
    "REVIEW_TITLE_RE",
    "SEMANTIC_SECTION_LABEL_SKIP_TOKENS",
    "STRUCTURED_MULTI_FIELDS",
    "STRUCTURED_OBJECT_FIELDS",
    "STRUCTURED_OBJECT_LIST_FIELDS",
    "URL_FIELDS",
    "VARIANT_OPTION_VALUE_UI_NOISE_PHRASES",
    "VARIANT_SIZE_ALIAS_SUFFIXES",
]


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
