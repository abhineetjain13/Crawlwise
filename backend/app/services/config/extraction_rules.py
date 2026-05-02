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

_CANDIDATE_IMAGE_FILE_EXTENSIONS = _STATIC_EXPORTS.get(
    "CANDIDATE_IMAGE_FILE_EXTENSIONS",
    (),
)
_BARE_HOST_URL_PATTERN = _STATIC_EXPORTS.get("BARE_HOST_URL_PATTERN", "")
_IMAGE_FIELDS_RAW = _STATIC_EXPORTS.get("IMAGE_FIELDS", ())
_INTEGER_VALUE_FIELDS_RAW = _STATIC_EXPORTS.get("INTEGER_VALUE_FIELDS", ())
_LONG_TEXT_FIELDS_RAW = _STATIC_EXPORTS.get("LONG_TEXT_FIELDS", ())
_PERCENT_PATTERN = _STATIC_EXPORTS.get("PERCENT_PATTERN", "")
_PRICE_VALUE_FIELDS_RAW = _STATIC_EXPORTS.get("PRICE_VALUE_FIELDS", ())
_SEMANTIC_SECTION_NOISE = _STATIC_EXPORTS.get("SEMANTIC_SECTION_NOISE", {})
_RATING_PATTERN = _STATIC_EXPORTS.get("RATING_PATTERN", "")
_REVIEW_COUNT_PATTERN = _STATIC_EXPORTS.get("REVIEW_COUNT_PATTERN", "")
_REVIEW_TITLE_PATTERN = _STATIC_EXPORTS.get("REVIEW_TITLE_PATTERN", "")
_STRUCTURED_MULTI_FIELDS_RAW = _STATIC_EXPORTS.get("STRUCTURED_MULTI_FIELDS", ())
_STRUCTURED_OBJECT_FIELDS_RAW = _STATIC_EXPORTS.get("STRUCTURED_OBJECT_FIELDS", ())
_STRUCTURED_OBJECT_LIST_FIELDS_RAW = _STATIC_EXPORTS.get(
    "STRUCTURED_OBJECT_LIST_FIELDS",
    (),
)
_URL_FIELDS_RAW = _STATIC_EXPORTS.get("URL_FIELDS", ())

EXPORT_IMAGE_URL_SUFFIXES = tuple(_CANDIDATE_IMAGE_FILE_EXTENSIONS)
BARE_HOST_URL_RE = re.compile(str(_BARE_HOST_URL_PATTERN), re.I)
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
        "frequently bought together",
        "mens shoes",
        "men's shoes",
        "womens shoes",
        "women's shoes",
        "shoes",
    }
)
DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES = frozenset({"criteoproductrail"})
DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA = 10.0
DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO = 0.1
DETAIL_BREADCRUMB_ROOT_LABELS = frozenset({"home", "shop", "store"})
DETAIL_BREADCRUMB_SELECTORS = (
    "[aria-label*='breadcrumb' i] li",
    "[class*='breadcrumb' i] li",
    "[aria-label*='breadcrumb' i] a",
    "[class*='breadcrumb' i] a",
)
DETAIL_BREADCRUMB_CONTAINER_SELECTORS = (
    "[aria-label*='breadcrumb' i]",
    "[class*='breadcrumb' i]",
)
DETAIL_BREADCRUMB_SEPARATOR_LABELS = frozenset({">", "/", "\\", "|", "›", "»", "→"})
DETAIL_BREADCRUMB_LABEL_PREFIXES = ("shop all ",)
DETAIL_CATEGORY_SOURCE_RANKS = {
    "dom_breadcrumb": 1,
    "json_ld": 2,
    "microdata": 2,
    "adapter": 3,
    "network_payload": 4,
    "js_state": 5,
    "dom_selector": 6,
}
DETAIL_GENDER_TERMS = {
    "women": ("women", "womens", "women's", "woman", "ladies", "female"),
    "men": ("men", "mens", "men's", "man", "male"),
    "girls": ("girls", "girl"),
    "boys": ("boys", "boy"),
    "unisex": (
        "unisex",
        "all gender",
        "all-gender",
        "gender neutral",
        "gender-neutral",
    ),
}
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
DETAIL_IDENTITY_FIELDS = frozenset({"title", "image_url"})
VARIANT_FIELDS = frozenset({"variants", "selected_variant"})
VARIANT_SIZE_ALIAS_SUFFIXES = (" us",)
VARIANT_OPTION_VALUE_UI_NOISE_PHRASES = (
    "sign up",
    "updates and promotions",
)
OPTION_VALUE_NOISE_WORDS = ("popular", "sale", "discount", "off")
DETAIL_IDENTITY_STOPWORDS = frozenset(
    {
        "and",
        "buy",
        "fit",
        "for",
        "men",
        "online",
        "oversized",
        "product",
        "products",
        "shirt",
        "shirts",
        "souled",
        "store",
        "tee",
        "tees",
        "the",
        "tshirt",
        "tshirts",
        "women",
    }
)
DETAIL_GENERIC_TERMINAL_TOKENS = frozenset(
    {
        "color",
        "colors",
        "detail",
        "dp",
        "job",
        "jobs",
        "p",
        "product",
        "productpage",
        "products",
        "release",
        "size",
        "sizes",
        "style",
        "styles",
        "variant",
        "variants",
        "width",
        "widths",
    }
)
JOB_LISTING_DETAIL_ROOT_MARKERS = frozenset(
    {"job", "jobs", "opening", "position", "posting", "career", "careers"}
)
DETAIL_IDENTITY_CODE_MIN_LENGTH = 8
REMOTE_BOOLEAN_TRUE_TOKENS = frozenset(
    {"true", "1", "yes", "remote", "fully remote", "work from home", "telecommute"}
)
REMOTE_BOOLEAN_FALSE_TOKENS = frozenset(
    {"false", "0", "no", "onsite", "on site", "office"}
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
IMAGE_FIELDS = frozenset(_IMAGE_FIELDS_RAW)
INTEGER_VALUE_FIELDS = frozenset(_INTEGER_VALUE_FIELDS_RAW)
LONG_TEXT_FIELDS = frozenset(_LONG_TEXT_FIELDS_RAW)
LISTING_PRICE_NODE_SELECTORS = (
    "[itemprop='price']",
    "[class*='price']",
    "[data-testid*='price']",
    "[data-price]",
    "[aria-label*='price']",
)
LISTING_PROMINENT_TITLE_TAGS = frozenset(
    {"strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"}
)
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
PERCENT_RE = re.compile(str(_PERCENT_PATTERN))
PRICE_VALUE_FIELDS = frozenset(_PRICE_VALUE_FIELDS_RAW)
SEMANTIC_SECTION_LABEL_SKIP_TOKENS = tuple(
    sorted(
        {
            *(
                str(token).lower()
                for token in (_SEMANTIC_SECTION_NOISE.get("label_skip_tokens") or ())
            ),
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
RATING_RE = re.compile(str(_RATING_PATTERN), re.I)
REVIEW_COUNT_RE = re.compile(str(_REVIEW_COUNT_PATTERN), re.I)
REVIEW_TITLE_RE = re.compile(str(_REVIEW_TITLE_PATTERN), re.I)
STRUCTURED_MULTI_FIELDS = frozenset(_STRUCTURED_MULTI_FIELDS_RAW)
STRUCTURED_OBJECT_FIELDS = frozenset(_STRUCTURED_OBJECT_FIELDS_RAW)
STRUCTURED_OBJECT_LIST_FIELDS = frozenset(_STRUCTURED_OBJECT_LIST_FIELDS_RAW)
URL_FIELDS = frozenset(_URL_FIELDS_RAW)

NON_PRODUCT_IMAGE_HINTS = tuple(
    dict.fromkeys(
        [
            *tuple(_STATIC_EXPORTS.get("NON_PRODUCT_IMAGE_HINTS", ())),
            "arrow",
            "loading",
            "loding",
            "spinner",
        ]
    )
)
PAGE_URL_CURRENCY_HINTS_RAW = {
    **dict(_STATIC_EXPORTS.get("PAGE_URL_CURRENCY_HINTS_RAW", {})),
    "firstcry.com/": "INR",
}
AVAILABILITY_URL_MAP = {
    "https://schema.org/instock": "in_stock",
    "http://schema.org/instock": "in_stock",
    "schema.org/instock": "in_stock",
    "instock": "in_stock",
    "https://schema.org/outofstock": "out_of_stock",
    "http://schema.org/outofstock": "out_of_stock",
    "schema.org/outofstock": "out_of_stock",
    "outofstock": "out_of_stock",
    "https://schema.org/limitedavailability": "limited_stock",
    "http://schema.org/limitedavailability": "limited_stock",
    "schema.org/limitedavailability": "limited_stock",
    "limitedavailability": "limited_stock",
    "https://schema.org/preorder": "pre_order",
    "http://schema.org/preorder": "pre_order",
    "schema.org/preorder": "pre_order",
    "preorder": "pre_order",
}
VARIANT_OPTION_TEXT_FIELDS = frozenset(
    {
        "color",
        "condition",
        "material",
        "size",
        "storage",
        "style",
    }
)
VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS = (
    r"[$€£¥₹]\s*\d",
    r"\b\d[\d.,]*\s*(?:usd|eur|gbp|inr|aud|cad|ars)\b",
    r"\b(?:popular|sale|discount|off|sold out|unavailable|left in stock)\b",
)

DYNAMIC_FIELD_NAME_MAX_TOKENS = crawler_runtime_settings.dynamic_field_name_max_tokens
MAX_CANDIDATES_PER_FIELD = crawler_runtime_settings.max_candidates_per_field

_EXTRA_EXPORTS = [
    "AVAILABILITY_URL_MAP",
    "BARE_HOST_URL_RE",
    "DETAIL_CENT_PRICE_HOST_SUFFIXES",
    "DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS",
    "DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS",
    "DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS",
    "DETAIL_IDENTITY_FIELDS",
    "DETAIL_LONG_TEXT_SOURCE_RANKS",
    "DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES",
    "DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX",
    "DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES",
    "DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA",
    "DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO",
    "DETAIL_LOW_SIGNAL_TITLE_VALUES",
    "DETAIL_BREADCRUMB_ROOT_LABELS",
    "DETAIL_BREADCRUMB_SELECTORS",
    "DETAIL_BREADCRUMB_CONTAINER_SELECTORS",
    "DETAIL_BREADCRUMB_LABEL_PREFIXES",
    "DETAIL_BREADCRUMB_SEPARATOR_LABELS",
    "DETAIL_CATEGORY_SOURCE_RANKS",
    "DETAIL_GENDER_TERMS",
    "DETAIL_GENERIC_TERMINAL_TOKENS",
    "DETAIL_IDENTITY_CODE_MIN_LENGTH",
    "DETAIL_TITLE_DIMENSION_SIZE_PATTERN",
    "DETAIL_IDENTITY_STOPWORDS",
    "DYNAMIC_FIELD_NAME_MAX_TOKENS",
    "EXPORT_IMAGE_URL_SUFFIXES",
    "IMAGE_FIELDS",
    "INTEGER_VALUE_FIELDS",
    "JSON_RECORD_LIST_KEYS",
    "JOB_LISTING_DETAIL_ROOT_MARKERS",
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
    "OPTION_VALUE_NOISE_WORDS",
    "REMOTE_BOOLEAN_FALSE_TOKENS",
    "REMOTE_BOOLEAN_TRUE_TOKENS",
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
    "VARIANT_FIELDS",
    "VARIANT_OPTION_VALUE_UI_NOISE_PHRASES",
    "VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS",
    "VARIANT_OPTION_TEXT_FIELDS",
    "VARIANT_SIZE_ALIAS_SUFFIXES",
]


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
