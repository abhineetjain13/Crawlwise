from __future__ import annotations

import re
from decimal import Decimal
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
        "6 easy payments",
        "frequently bought together",
        "mens shoes",
        "men's shoes",
        "plp",
        "womens shoes",
        "women's shoes",
        "shoes",
    }
)
DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES = frozenset({"criteoproductrail"})
DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES = frozenset(
    {"brightcove video", "criteoproductrail", "default", "tag", "inline"}
)
DETAIL_ARTIFACT_IDENTIFIER_VALUES = frozenset(
    {"description", "details", "product details", "specification", "specifications"}
)
DETAIL_ARTIFACT_PRICE_VALUES = frozenset(
    {"free", "n/a", "na", "unavailable", "contact us"}
)
DETAIL_ARTIFACT_SKU_PREFIXES = ("copy-",)
DETAIL_CATEGORY_UI_TOKENS = frozenset(
    {
        "...",
        "all categories",
        "back",
        "best sellers",
        "home",
        "next",
        "previous",
        "view all",
        "···",
        "…",
    }
)
DETAIL_CATEGORY_LABEL_PREFIXES = ("shop by ",)
DETAIL_LONG_TEXT_UI_TAIL_PHRASES = (
    "show more",
    "more details",
    "learn more",
)
DETAIL_NOISE_PREFIXES = ("check the details", "product summary")
DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS = 4
DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS = 24
DETAIL_LONG_TEXT_MAX_SECTION_CHARS = 12000
DETAIL_MATERIALS_POLLUTION_TOKENS = ("care", "reviews")
DETAIL_GUIDE_GLOSSARY_TEXT_PATTERNS = (
    r"\b(?:regular|slim|relaxed)\s+fit\b.{0,240}\b(?:regular|slim|relaxed)\s+fit\b",
    r"\b(?:fabric|material)\s+glossary\b",
    r"\bthe\s+word\s+['\"][a-z -]+['\"]\s+originates\b",
)
DETAIL_GUIDE_GLOSSARY_HEADING_TOKENS = (
    "fabric",
    "fit",
    "glossary",
    "material",
    "materials",
    "size",
)
DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS = 3
DETAIL_LONG_TEXT_DISCLAIMER_PATTERNS = (
    r"\bbuy\s+now\s+with\s+free\s+shipping\b",
    r"\bbuyer\s+protection\s+guaranteed\b",
    r"\bwe\s+aim\s+to\s+show\s+you\s+accurate\s+product\s+information\b",
    r"\bshipping\s+and\s+returns?\b.{0,240}\b(?:orders?|privacy|policy|refunds?|returns?)\b",
    r"\bcookie\s+(?:notice|policy|preferences?)\b",
    r"\bprivacy\s+policy\b",
    # Audit 2026-05-03 3.2: Shipping/fulfillment status blurbs leaked into
    # Jordan 5 description. Context-bound so legitimate prose that mentions
    # tracking or shipping is not rejected.
    r"\btracking\s+status\s+reads\b",
    r"\border\s+is\s+shipped\b.{0,120}\b(?:tracking|email)\b",
    r"\blabel\s+created\b.{0,80}\b(?:tracking|carrier|status|shipping|hours)\b",
    # Audit 2026-05-03 3.3: Marketing banner openers like "(US) - only $35. Fast shipping..."
    r"\([A-Z]{2,4}\)\s*[-\u2013\u2014]\s*only\s+\$\d",
    # Audit 2026-05-03 3.4: SEO meta blurbs ("Shop the X at Brand today",
    # "Read customer reviews ... and discover more").
    r"\bshop\s+the\b.{0,160}\bat\s+\S+\s+today\b",
    r"\bread\s+customer\s+reviews?\b.{0,160}\b(?:discover|learn|and\s+more)\b",
)
DETAIL_COOKIE_DISCLOSURE_TEXT_PATTERNS = (
    r"\bcookie\s+name\s+is\s+associated\s+with\b",
    r"\bcookie\s+descriptions?\s+are\s+displayed\b",
    r"\bcookiepedia\b",
    r"\bpreference\s+center\b",
    r"\bcloudflare\s+bot\s+management\b",
    r"\bmicrosoft\s+clarity\b",
    r"\bdynatrace\b",
    r"\bcriteo\b",
    r"\bgoogle\s+adsense\b",
    r"\breal\s+time\s+bidding\b",
)
DETAIL_TRACKING_TOKEN_PATTERN = r"_[a-z][a-z0-9_]{2,}"
DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS = frozenset(
    {"discount", "false", "off", "on", "sale", "true"}
)
DETAIL_TEXT_SCOPE_SELECTORS = (
    _STATIC_EXPORTS.get("DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR", "main"),
    "main",
    "article",
    "[role='main']",
    "[class*='product-main' i]",
    "[class*='product-content' i]",
)
DETAIL_TEXT_SCOPE_PRIORITY_TOKENS = (
    "description",
    "detail",
    "pdp",
    "product",
)
DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS = (
    "also-viewed",
    "also viewed",
    "ask",
    "compare",
    "dialog",
    "disclaimer",
    "fit-guide",
    "fit guide",
    "lightbox",
    "modal",
    "newsletter",
    "overlay",
    "popup",
    "recommend",
    "related",
    "review",
    "similar",
    "shipping",
    "size-guide",
    "size guide",
    "sponsored",
    "you-may-also-like",
    "you may also like",
)
DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS = (
    "also-viewed",
    "also viewed",
    "customers",
    "recommend",
    "related",
    "similar",
    "sponsored",
)
DETAIL_TEXT_HIDDEN_STYLE_TOKENS = (
    "display:none",
    "display: none",
    "left:-9999",
    "left: -9999",
    "opacity:0",
    "opacity: 0",
    "top:-9999",
    "top: -9999",
    "visibility:hidden",
    "visibility: hidden",
)
DETAIL_VARIANT_CONTEXT_NOISE_TOKENS = (
    "account",
    "carousel",
    "cross-sell",
    "footer",
    "header",
    "newsletter",
    "promo",
    "promotion",
    "recommend",
    "related",
    "search",
    "signup",
    "upsell",
    "you may also like",
)
VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH = 6
DETAIL_VARIANT_SCOPE_SELECTOR = (
    "form[action*='cart' i], "
    "form[id*='product' i], "
    "form[class*='product' i], "
    "[data-product-form], "
    "[class*='product-form' i], "
    "[class*='product-info' i], "
    "[class*='product-detail' i], "
    "[class*='pdp' i], "
    "[class*='add-to-cart' i], "
    "[id*='add-to-cart' i]"
)
VARIANT_SCOPE_MAX_ROOTS = 4
DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA = 10.0
DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO = 0.1
DETAIL_PRICE_CENT_MAGNITUDE_RATIO = 100
DETAIL_PRICE_MAGNITUDE_EPSILON = 0.01
DETAIL_PRICE_COMPARISON_TOLERANCE = Decimal("0.01")
DETAIL_LOW_SIGNAL_PRICE_MAX = Decimal("1")
DETAIL_LOW_SIGNAL_PARENT_MIN = Decimal("10")
VARIANT_OPTION_LABEL_MAX_WORDS = 6
DETAIL_ORIGINAL_PRICE_SELECTORS = (
    *tuple(_STATIC_EXPORTS.get("DETAIL_ORIGINAL_PRICE_SELECTORS", ())),
    "s",
    "del",
    "[class*='compare' i][class*='price' i]",
    "[class*='regular' i][class*='price' i]",
    "[class*='original' i][class*='price' i]",
    "[class*='was' i][class*='price' i]",
    "[class*='old' i][class*='price' i]",
    "[class*='strike' i][class*='price' i]",
    "[data-testid*='regular-price' i]",
    "[data-testid*='original-price' i]",
    "[aria-label*='original price' i]",
    "[aria-label*='regular price' i]",
    "[aria-label*='was price' i]",
)
DETAIL_JSONLD_GRAPH_FIELDS = ("@graph",)
DETAIL_JSONLD_TYPE_FIELDS = ("@type",)
DETAIL_JSONLD_OFFER_FIELDS = ("offers", "offer")
DETAIL_JSONLD_PRICE_FIELDS = ("price", "lowPrice")
DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS = ("highPrice",)
DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS = ("priceSpecification",)
DETAIL_JSONLD_CURRENCY_FIELDS = ("priceCurrency", "currency")
DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS = (
    "afterpay",
    "affirm",
    "installment",
    "klarna",
    "monthly payment",
    "pay in",
    "payments of",
    "per month",
)
DETAIL_BREADCRUMB_ROOT_LABELS = frozenset(
    {"home", "shop", "store", "homepage", "frontpage", "index", "home page", "homepage home"}
)
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
DETAIL_BREADCRUMB_JSONLD_TYPES = frozenset({"breadcrumblist", "breadcrumb_list"})
DETAIL_BREADCRUMB_MIN_LABEL_LENGTH = 8
DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO = 0.92
STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT = 8
STRUCTURED_CANDIDATE_LIST_SLICE = 20
DETAIL_CATEGORY_SOURCE_RANKS = {
    "json_ld_breadcrumb": 1,
    "dom_breadcrumb": 2,
    "json_ld": 3,
    "microdata": 3,
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
DETAIL_IDENTITY_FIELDS = frozenset({"title", "image_url"})
VARIANT_FIELDS = frozenset({"variants"})
VARIANT_SIZE_ALIAS_SUFFIXES = (" us",)
VARIANT_OPTION_VALUE_UI_NOISE_PHRASES = (
    "sign up",
    "updates and promotions",
)
VARIANT_PLACEHOLDER_VALUES = frozenset(
    {"default title", "choose", "option", "select", "swatch"}
)
VARIANT_PLACEHOLDER_PREFIXES = ("please select", "open ")
SIZE_REJECT_TOKENS = frozenset(
    {
        "customer reviews",
        "description",
        "details",
        "overview",
        "photos",
        "questions & answers",
        "q&a",
        "ratings",
        "reviews",
        "shipping",
        "specifications",
        "verified purchases",
    }
)
PLACEHOLDER_IMAGE_URL_PATTERNS = (
    "via.placeholder.com",
    "placehold.co",
    "placeholder.com",
    "/1x1",
    "1x1.gif",
    "pixel.gif",
    "spacer.gif",
    "blank.gif",
    "transparent.gif",
    "clear.gif",
)
URL_CONCATENATION_SCHEME_PATTERN = r"https?:/+"
URL_CONCATENATION_ALLOWED_PREFIX_SEPARATORS = (
    " ",
    "\t",
    "\n",
    ",",
    ";",
    ")",
    "]",
    "}",
    ">",
)
OPTION_VALUE_NOISE_WORDS = ("popular", "sale", "discount", "off")
VARIANT_PROMO_NOISE_TOKENS = ("off", "discount", "promo")
TRACKING_STRIP_SURFACE_PREFIXES = ("ecommerce_", "job_")
MAX_TRACKING_KEY_LENGTH = 3
MAX_TRACKING_VALUE_LENGTH = 8
SCOPE_PRODUCT_CONTEXT_TOKENS = ("product", "detail", "pdp")
SCOPE_SCORE_MAIN_WEIGHT = 4000
SCOPE_SCORE_PRIORITY_WEIGHT = 2000
SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT = 1000
MAX_SELECTOR_MATCHES = 12
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
LONG_TEXT_FIELDS = frozenset(
    field_name
    for field_name in tuple(_LONG_TEXT_FIELDS_RAW or ())
    if str(field_name) != "features"
)
DETAIL_LONG_TEXT_RANK_FIELDS = frozenset({*LONG_TEXT_FIELDS, "features"})
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
STRUCTURED_MULTI_FIELDS = frozenset(
    {*tuple(_STRUCTURED_MULTI_FIELDS_RAW or ()), "features"}
)
STRUCTURED_OBJECT_FIELDS = frozenset(_STRUCTURED_OBJECT_FIELDS_RAW)
STRUCTURED_OBJECT_LIST_FIELDS = frozenset(_STRUCTURED_OBJECT_LIST_FIELDS_RAW)
URL_FIELDS = frozenset(_URL_FIELDS_RAW)

NON_PRODUCT_IMAGE_HINTS = tuple(
    dict.fromkeys(
        [
            *tuple(_STATIC_EXPORTS.get("NON_PRODUCT_IMAGE_HINTS", ())),
            "arrow",
            "blank",
            "default",
            "loading",
            "loding",
            "placeholder",
            "spinner",
            "via.placeholder.com",
            "white.svg",
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
NORMALIZER_AVAILABILITY_TOKENS = {
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
VARIANT_AXIS_ALLOWED_SINGLE_TOKENS = frozenset(
    {
        *VARIANT_OPTION_TEXT_FIELDS,
        "colour",
        "cup",
        "edition",
        "finish",
        "flavor",
        "flavour",
        "format",
        "fit",
        "memory",
        "model",
        "pack",
        "scent",
        "shade",
        "type",
        "weight",
    }
)
VARIANT_AXIS_GENERIC_TOKENS = frozenset(
    {
        "attribute",
        "choice",
        "dropdown",
        "option",
        "options",
        "select",
        "selected",
        "selector",
        "styledselect",
        "swatch",
        "variant",
        "variation",
    }
)
VARIANT_AXIS_TECHNICAL_PATTERNS = (
    r"^(?:option|options?|select|selector|dropdown|variant|variation|styledselect)[_\s-]*\d+$",
    r"^(?:variation|variant|option|attribute|selector|styledselect)(?:[_\s-]+(?:selector|select))?(?:[_\s-]*\d+)?$",
    r"^[a-z]*select\d+$",
)
VARIANT_QUANTITY_ATTR_TOKENS = frozenset(
    {
        "amount",
        "howmany",
        "item-count",
        "item_count",
        "number-of-items",
        "number_of_items",
        "quantity",
        "qty",
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
    "NORMALIZER_AVAILABILITY_TOKENS",
    "BARE_HOST_URL_RE",
    "DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS",
    "DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS",
    "DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS",
    "DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS",
    "DETAIL_GUIDE_GLOSSARY_TEXT_PATTERNS",
    "DETAIL_IDENTITY_FIELDS",
    "DETAIL_LONG_TEXT_RANK_FIELDS",
    "DETAIL_LONG_TEXT_SOURCE_RANKS",
    "DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES",
    "DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX",
    "DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES",
    "DETAIL_ARTIFACT_IDENTIFIER_VALUES",
    "DETAIL_ARTIFACT_PRICE_VALUES",
    "DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA",
    "DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO",
    "DETAIL_PRICE_CENT_MAGNITUDE_RATIO",
    "DETAIL_PRICE_COMPARISON_TOLERANCE",
    "DETAIL_LOW_SIGNAL_PRICE_MAX",
    "DETAIL_LOW_SIGNAL_PARENT_MIN",
    "DETAIL_PRICE_MAGNITUDE_EPSILON",
    "VARIANT_OPTION_LABEL_MAX_WORDS",
    "DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS",
    "DETAIL_JSONLD_CURRENCY_FIELDS",
    "DETAIL_JSONLD_GRAPH_FIELDS",
    "DETAIL_JSONLD_OFFER_FIELDS",
    "DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS",
    "DETAIL_JSONLD_PRICE_FIELDS",
    "DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS",
    "DETAIL_JSONLD_TYPE_FIELDS",
    "DETAIL_GUIDE_GLOSSARY_HEADING_TOKENS",
    "DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS",
    "DETAIL_LONG_TEXT_DISCLAIMER_PATTERNS",
    "DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS",
    "DETAIL_LONG_TEXT_MAX_SECTION_CHARS",
    "DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS",
    "DETAIL_NOISE_PREFIXES",
    "DETAIL_MATERIALS_POLLUTION_TOKENS",
    "DETAIL_TEXT_HIDDEN_STYLE_TOKENS",
    "DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS",
    "DETAIL_TEXT_SCOPE_PRIORITY_TOKENS",
    "DETAIL_TEXT_SCOPE_SELECTORS",
    "DETAIL_VARIANT_CONTEXT_NOISE_TOKENS",
    "DETAIL_VARIANT_SCOPE_SELECTOR",
    "VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH",
    "VARIANT_SCOPE_MAX_ROOTS",
    "DETAIL_LOW_SIGNAL_TITLE_VALUES",
    "DETAIL_BREADCRUMB_ROOT_LABELS",
    "DETAIL_BREADCRUMB_SELECTORS",
    "DETAIL_BREADCRUMB_CONTAINER_SELECTORS",
    "DETAIL_BREADCRUMB_LABEL_PREFIXES",
    "DETAIL_BREADCRUMB_JSONLD_TYPES",
    "DETAIL_BREADCRUMB_MIN_LABEL_LENGTH",
    "DETAIL_BREADCRUMB_SEPARATOR_LABELS",
    "DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO",
    "DETAIL_CATEGORY_SOURCE_RANKS",
    "STRUCTURED_CANDIDATE_LIST_SLICE",
    "STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT",
    "DETAIL_CATEGORY_LABEL_PREFIXES",
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
    "VARIANT_AXIS_ALLOWED_SINGLE_TOKENS",
    "VARIANT_AXIS_GENERIC_TOKENS",
    "VARIANT_AXIS_TECHNICAL_PATTERNS",
    "VARIANT_OPTION_VALUE_UI_NOISE_PHRASES",
    "VARIANT_PLACEHOLDER_PREFIXES",
    "VARIANT_PLACEHOLDER_VALUES",
    "VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS",
    "VARIANT_OPTION_TEXT_FIELDS",
    "VARIANT_QUANTITY_ATTR_TOKENS",
    "VARIANT_SIZE_ALIAS_SUFFIXES",
    "SIZE_REJECT_TOKENS",
    "PLACEHOLDER_IMAGE_URL_PATTERNS",
    "URL_CONCATENATION_ALLOWED_PREFIX_SEPARATORS",
    "URL_CONCATENATION_SCHEME_PATTERN",
]


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
