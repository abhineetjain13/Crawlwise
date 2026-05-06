from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any

from app.services.config._export_data import load_export_data
from app.services.config.variant_policy import (
    AXIS_NAME_ALIASES,
    PUBLIC_VARIANT_AXIS_FIELDS,
)
from app.services.config.runtime_settings import crawler_runtime_settings

_EXPORTS_PATH = Path(__file__).with_name("extraction_rules.exports.json")
_STATIC_EXPORTS = {
    name: value
    for name, value in load_export_data(str(_EXPORTS_PATH)).items()
    if not name.startswith("_")
}
for _name, _value in _STATIC_EXPORTS.items():
    if _name.isidentifier() and _name not in globals():
        globals()[_name] = _value

HYDRATED_STATE_PATTERNS = tuple(
    dict.fromkeys(
        value
        for value in _STATIC_EXPORTS.get("HYDRATED_STATE_PATTERNS", ())
        if str(value).strip()
    )
)
SHIPPING_DATE_FIELD = "shipping_date"
SPECIAL_DAYS_FIELD = "special_days"
IS_AVAILABLE_FIELD = "is_available"
IS_INVENTORY_ONLY_FIELD = "is_inventory_only"
SHIPPING_INVENTORY_PAYLOAD_HINT_FIELDS = frozenset(
    {
        SHIPPING_DATE_FIELD,
        SPECIAL_DAYS_FIELD,
        IS_AVAILABLE_FIELD,
        IS_INVENTORY_ONLY_FIELD,
    }
)
ECOMMERCE_DESCRIPTION_BLOCK_LIMIT = 40
DETAIL_PAYLOAD_LIST_LIMIT = 50
LISTING_VISUAL_PRICE_REGEX_PATTERN = r"(?:₹|Rs\.?|INR|\$|€|£)\s?[\d,.]+"
TRACKING_PIXEL_PATTERNS = (
    "facebook.com/tr?",
    "facebook.com/tr&id=",
    "/tr?id=",
    "doubleclick",
    "googletagmanager",
    "google-analytics",
    "pixel",
)
DETAIL_SURFACE_KEYWORD = "detail"
ECOMMERCE_DETAIL_SURFACE = "ecommerce_detail"
VARIANT_AXIS_EXCLUDED_SINGLE_TOKENS = frozenset({"color", "colour", "fit", "size"})
VARIANT_COLOR_AXIS_TOKENS = frozenset({"color", "colour"})
VARIANT_SIZE_AXIS_TOKENS = frozenset({"fit", "size"})
VARIANT_DESCENDANT_SCAN_LIMIT = 24
VARIANT_SIBLING_SEARCH_DEPTH = 4
VARIANT_SELECT_OPTION_SCAN_LIMIT = 24
VARIANT_SEQUENTIAL_INTEGER_MIN_RUN = 5
VARIANT_SELECT_GROUP_MAX = 4
VARIANT_CHOICE_GROUP_MAX = 8
HASH_LINK_SELECTOR = "a[href^='#']"
VARIANT_SWATCH_BUTTON_SELECTOR = (
    "button[class*='swatch' i], button[class*='color-option' i],"
    " button[class*='color-selector' i], button[class*='size-option' i],"
    " button[class*='size-selector' i], button[class*='variant' i],"
    " button[data-option], button[data-value], a[class*='swatch' i],"
    " div[class*='swatch' i], div[role='radio'],"
    " [data-testid*='variants-selector' i]"
)
VARIANT_SWATCH_BUTTON_LIMIT = 20
VARIANT_SWATCH_PARENT_DEPTH = 6
VARIANT_MATCHING_INPUT_LIMIT = 12
BROWSER_REQUESTED_DETAIL_SELECTOR_PRIORITY = (
    HASH_LINK_SELECTOR,
    "[role='tab'][aria-controls]",
    "button[aria-controls]",
    "[role='button'][aria-controls]",
    "[aria-expanded='false']",
    "summary",
    "details > summary",
    "button",
    "[role='button']",
    "a",
)
BROWSER_REQUESTED_DETAIL_GENERIC_TOGGLE_LABELS = frozenset(
    {
        "details",
        "description",
        "product details",
        "specification",
        "specifications",
        "materials",
        "materials and care",
    }
)

_EXTRACTION_RULES_RAW = _STATIC_EXPORTS.get("EXTRACTION_RULES", {})
EXTRACTION_RULES = (
    dict(_EXTRACTION_RULES_RAW) if isinstance(_EXTRACTION_RULES_RAW, dict) else {}
)

_CANDIDATE_IMAGE_FILE_EXTENSIONS = _STATIC_EXPORTS.get(
    "CANDIDATE_IMAGE_FILE_EXTENSIONS", ()
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
    "STRUCTURED_OBJECT_LIST_FIELDS", ()
)
_URL_FIELDS_RAW = _STATIC_EXPORTS.get("URL_FIELDS", ())


def _string_frozenset(value: object) -> frozenset[str]:
    values: Iterable[object]
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Mapping):
        values = value.keys()
    elif isinstance(value, Iterable):
        values = value
    else:
        return frozenset()
    return frozenset(str(item).strip() for item in values if str(item).strip())


CDN_IMAGE_QUERY_PARAMS = _string_frozenset(
    _STATIC_EXPORTS.get("CDN_IMAGE_QUERY_PARAMS", ())
) | frozenset(
    {
        "fit",
        "fmt",
        "h",
        "height",
        "hei",
        "imwidth",
        "odnbg",
        "odnheight",
        "odnwidth",
        "op_sharpen",
        "qlt",
        "quality",
        "v",
        "w",
        "wid",
        "width",
    }
)

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
        # Tab/nav strip text leak when extractor hits the tab shell, not content (Canon DQ-6).
        "overview specs specifications compatibility resources support software",
        "overview specs compatibility resources support software",
        "overview specifications compatibility resources support software",
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
        # Generic gender-plus-category title leak when real title selector fails (LUISAVIAROMA DQ-9).
        "kids boys",
        "kids girls",
        "kids boy",
        "kids girl",
        "boys kids",
        "girls kids",
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
CATEGORY_PLACEHOLDER_VALUES = frozenset({"category", "categories", "uncategorized"})
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
        "shop by material",
        "shop by brand",
    }
)
DETAIL_CATEGORY_LABEL_PREFIXES = ("shop by ",)
DETAIL_LONG_TEXT_UI_TAIL_PHRASES = (
    "show more",
    "more details",
    "learn more",
)
DETAIL_LONG_TEXT_TRUNCATED_TAIL_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
DETAIL_VARIANT_SIZE_SEQUENCE_MIN_COUNT = 5
DETAIL_LEGAL_TAIL_PATTERNS = {
    "contains": (
        "product safety",
        "powered by product details have been supplied by the manufacturer",
    ),
    "digit_contains": ("customer service", "contact "),
    "all_contains": (("privacy", "policy"),),
    "exact": ("view more",),
}
LONG_TEXT_MIN_WORDS = 3
LONG_TEXT_MAX_WORDS = 14
TOKEN_MIN_LEN_DISTINCTIVE = 5
TOKEN_MIN_LEN_CHUNK = 4
LONG_TEXT_PREFIXES = ("official ", "shop for ")
DETAIL_NOISE_PREFIXES = (
    "buy ",
    "check the details",
    "discover ",
    "product summary",
    "shop for ",
    "shop the ",
)
DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS = 4
DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS = 24
DETAIL_LONG_TEXT_MAX_SECTION_CHARS = 12000
DETAIL_MATERIALS_POLLUTION_TOKENS = ("care", "reviews")
DETAIL_GUIDE_GLOSSARY_TEXT_PATTERNS = (
    r"\b(?:regular|slim|relaxed)\s+fit\b.{0,240}\b(?:regular|slim|relaxed)\s+fit\b",
    r"\b(?:fabric|material)\s+glossary\b",
    r"\bthe\s+word\s+['\"][a-z -]+['\"]\s+originates\b",
    r"\b(?:find|select)\s+your\s+(?:shade|size|color)\b",
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
    r"\bshipping\s+statuses?\s+can\s+remain\b",
    # Audit 2026-05-03 3.3: Marketing banner openers like "(US) - only $35. Fast shipping..."
    r"\([A-Z]{2,4}\)\s*[-\u2013\u2014]\s*only\s+\$\d",
    r"\bfast\s+shipping\s+on\s+latest\b",
    # Audit 2026-05-03 3.4: SEO meta blurbs ("Shop the X at Brand today",
    # "Read customer reviews ... and discover more").
    r"\bshop\s+the\b.{0,160}\bat\s+\S+\s+today\b",
    r"\bread\s+customer\s+reviews?\b.{0,160}\b(?:discover|learn|and\s+more)\b",
    r"\bwas\s+this\s+product\s+information\s+helpful\b",
    r"\bwrite\s+a\s+review\b",
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
SMALL_NUMERIC_PATTERN = r"\d{1,2}"
TRACKING_PIXEL_PATTERN = r"_[a-z]+"
COLOR_KEYWORD_PATTERN = r"\b(?:color|colour|black|blue|brown|green|grey|gray|orange|pink|purple|red|white|yellow)\b"
GIF_BASE64_PREFIX = "r0lgodlh"
URL_DETECTION_TOKENS = ("g_auto", "f_auto", "q_auto", "c_fill")
YEAR_SLUG_PATTERN = r"(?:19|20)\d{2}"
PRODUCT_SLUG_MIN_TERMINAL_TOKENS = 3
GENDER_ARTIFACT_WORDS = ("men", "mens", "women", "womens", "boys", "girls")
GENDER_ARTIFACT_PATTERN = r"\b(?:men|mens|women|womens|boys|girls)['’]?\s+{candidate}\b"
GENDER_KEYWORD_TOKENS = frozenset(GENDER_ARTIFACT_WORDS)
GENDER_POSSESSIVE_PATTERN = r"\b(?:men|women|boys|girls)['’]?s\b"
STANDARD_SIZE_VALUES = frozenset({"xs", "s", "m", "l", "xl", "xxl", "xxxl"})
VARIANT_TITLE_STOPWORDS = frozenset(
    {"and", "for", "the", "with", "size", "color", "colour", "variant"}
)
DEFAULT_DETAIL_MAX_VARIANT_ROWS = 1
FALLBACK_MAX_VARIANT_ROWS = 100
DOM_VARIANT_GROUP_LIMIT = 4
UNRESOLVED_TEMPLATE_URL_TOKENS = (
    "url_to_",
    "{{",
    "}}",
    "{$",
    "%%",
    "[[",
    "]]",
)
DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS = frozenset(
    {"discount", "false", "off", "on", "sale", "true"}
)
AVAILABILITY_IN_STOCK = "in_stock"
AVAILABILITY_OUT_OF_STOCK = "out_of_stock"
MATERIAL_KEYWORDS = frozenset(
    {
        "cotton",
        "leather",
        "linen",
        "nylon",
        "polyamide",
        "polyester",
        "rubber",
        "spandex",
        "wool",
    }
)
ORG_SUFFIXES = frozenset({"co", "company", "corp", "inc", "llc", "ltd", "se"})
NOISY_PRODUCT_ATTRIBUTE_KEYS = frozenset(
    tuple(_STATIC_EXPORTS.get("NOISY_PRODUCT_ATTRIBUTE_KEYS", ()) or ())
) | frozenset(
    {
        "availability",
        "available",
        AVAILABILITY_IN_STOCK,
        AVAILABILITY_OUT_OF_STOCK,
        "stock_status",
    }
)
DETAIL_TEXT_SCOPE_SELECTORS = tuple(
    dict.fromkeys(
        (
            _STATIC_EXPORTS.get("DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR", "main"),
            "main",
            "article",
            "[role='main']",
            "[class*='product-main' i]",
            "[class*='product-content' i]",
        )
    )
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
    "complete-the-look",
    "complete the look",
    "customers",
    "people-also-bought",
    "people also bought",
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
    "modal",
    "promo",
    "promotion",
    "recommend",
    "related",
    "search",
    "signup",
    "upsell",
    "you may also like",
    "sort by",
    "filter by",
    "results",
    "report",
)
VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH = 6
# Used when runtime config is invalid; 3 keeps noise pruning local to variant UI.
VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK = 3
# Last-resort parse default after configured depth and fallback both fail.
VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT = (
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK
)
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
DETAIL_PARENT_VARIANT_PRICE_RATIO_MIN = Decimal("0.5")
DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX = Decimal("2")
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
    {
        "home",
        "shop",
        "store",
        "homepage",
        "frontpage",
        "index",
        "home page",
        "homepage home",
    }
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
DETAIL_BREADCRUMB_NOISE_ICON_PATTERNS = (r"\barrow-right(?:-[a-z]+)?\b",)
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
DETAIL_NOISE_SECTION_SELECTORS = (
    "[id*='recently-viewed']",
    "[class*='recently-viewed']",
    "[id*='similar-products']",
    "[class*='similar-products']",
    "[id*='recommendations']",
    "[class*='recommendations']",
    "[id*='people-also-bought']",
    "[class*='people-also-bought']",
    ".upsell",
    ".related-products",
)
DETAIL_IDENTITY_FIELDS = frozenset({"title", "image_url"})
VARIANT_FIELDS = frozenset({"variants"})
VARIANT_SIZE_ALIAS_SUFFIXES = (" us",)
VARIANT_OPTION_VALUE_UI_NOISE_PHRASES = (
    "sign up",
    "updates and promotions",
    # Add-to-cart / add-to-bag call-to-action captured as a variant option
    # (LEGO, REI, Sweetwater — DQ-2 / 2026-05-04 gemini audit).
    "add to cart",
    "add to bag",
    "add to basket",
    "add a lifetime membership to cart",
    # Wishlist / account plumbing strings leaking in as variant labels.
    "account.wishlist",
    "notinlist",
    # Cart/quantity controls picked up as size values.
    "increment quantity",
    "decrement quantity",
    # Payment buttons/badges misclassified as dropdown/radio choices.
    "apple pay",
    "google pay",
    "paypal",
    "shop pay",
    # Fulfillment / shipping banners leaking into variants.
    "pickup unavailable",
    "pickup not available",
    # Marketing / guarantee badges mis-classified as variant axes
    # (ROAM Luggage — DQ-2).
    "change size",
    "features",
    "lifetime warranty",
    "free trial",
    "day free trial",
    "size and weight",
    "see all",
    "view market data",
    "sell now for",
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
        "sort by",
        "filter by",
        "price",
        "quantity",
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
IMAGE_PATH_TOKENS = (
    "/image/",
    "/images/",
    "/media/",
    "/picture",
    "/is/image/",
    "/cdn/",
)
IMAGE_FAMILY_NOISE_TOKENS = frozenset(
    {
        "assets",
        "cdn",
        "crop",
        "detail",
        "editorial",
        "file",
        "files",
        "height",
        "hero",
        "hover",
        "image",
        "images",
        "main",
        "media",
        "picture",
        "product",
        "products",
        "public",
        "shop",
        "square",
        "standard",
        "width",
    }
)
WAF_QUEUE_PATTERNS = (
    r"\bsorry for the wait\b",
    r"\bplease wait while we verify\b",
    r"\bwe need to verify\b",
    r"\bjust a moment while we\b",
    r"\bqueue-it\b",
    r"^please wait\b",
    r"\byou are in a virtual queue\b",
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
VARIANT_CHOICE_OPTION_SELECTOR = (
    "option, [role='radio'], [role='option'], button, "
    "input[type='radio'], input[type='checkbox']"
)
VARIANT_CHOICE_OPTION_LIMIT = 24
VARIANT_CHOICE_CONTAINER_OPTION_LIMIT = 24
VARIANT_CHOICE_CONTAINER_SELECT_LIMIT = 8
VARIANT_CHOICE_CONTAINER_GROUP_LIMIT = 12
VARIANT_CHOICE_CONTAINER_MIN_DISTINCT_NAMES = 2
FEATURE_SECTION_SELECTORS = (
    "[data-section='features']",
    ".features",
    ".product-features",
    "#features",
    "#features_section",
)
DETAIL_MATERIALS_ZERO_PERCENT_PATTERN = r"\b0\s*%"
FEATURE_ROW_NOISE_PATTERNS = (
    r"^(?:key\s+)?features?(?:\s*&\s*benefits?)?$",
    r"^(?:see|show)\s+more\s+(?:key\s+)?features?(?:\s*&\s*benefits?)?$",
)
DETAIL_BRACKET_PROSE_MIN_WORDS = 5
PRICE_SOURCE_KEY_FIELDS = frozenset(
    {"price", "sale_price", "original_price", "compare_at_price"}
)
CANONICAL_PRICE_FIELDS = frozenset({"price", "sale_price", "original_price"})
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
JOB_POSTING_PATH_MARKERS = tuple(
    dict.fromkeys(
        (
            *tuple(_STATIC_EXPORTS.get("JOB_LISTING_DETAIL_PATH_MARKERS", ()) or ()),
            "/career/",
            "/careers/",
            "/opening/",
            "/openings/",
            "/position/",
            "/positions/",
            "/posting/",
            "/postings/",
            "/requisition/",
            "/requisitions/",
            "/role/",
            "/roles/",
            "/vacancy/",
            "/vacancies/",
        )
    )
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
LISTING_CHROME_TEXT_LIMIT = 800
# Path prefixes that indicate a category/collection listing page (not a
# product detail page).  When both the listing page URL and a candidate URL
# share one of these prefixes the candidate is a sibling category link and
# should be treated as structural navigation, not a product record.
LISTING_CATEGORY_PATH_PREFIXES = (
    "/c/",
    "/category/",
    "/categories/",
    "/collection/",
    "/collections/",
    "/catalog/",
    "/browse/",
    "/plp/",
    "/clp/",
)
LISTING_CATEGORY_PATH_SEGMENTS = frozenset({"productlist"})
LISTING_PRODUCT_DETAIL_ID_RE = re.compile(
    r"(?:^|[/?#&])(?:id(?:=|%3d))?[a-z0-9_-]*\d{4,}[a-z0-9_-]*-product(?:$|[/?#&])",
    re.I,
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
_detail_expand_selectors_base = tuple(
    _STATIC_EXPORTS.get("DETAIL_EXPAND_SELECTORS", ()) or ()
)
_detail_expand_selectors_ordered: list[str] = []
_detail_expand_anchor_inserted = False
for _selector in _detail_expand_selectors_base:
    if _selector == "button" and not _detail_expand_anchor_inserted:
        _detail_expand_selectors_ordered.append(HASH_LINK_SELECTOR)
        _detail_expand_anchor_inserted = True
    _detail_expand_selectors_ordered.append(str(_selector))
if not _detail_expand_anchor_inserted:
    _detail_expand_selectors_ordered.append(HASH_LINK_SELECTOR)
DETAIL_EXPAND_SELECTORS = tuple(dict.fromkeys(_detail_expand_selectors_ordered))
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
VARIANT_AXIS_ALIASES = {
    **dict(_STATIC_EXPORTS.get("VARIANT_AXIS_ALIASES", {})),
    **dict(AXIS_NAME_ALIASES),
    "part_or_kit": "bundle_type",
    "style_and_size": "size",
}
VARIANT_CHOICE_GROUP_SELECTOR = ", ".join(
    dict.fromkeys(
        (
            *(
                str(value).strip()
                for value in str(
                    _STATIC_EXPORTS.get("VARIANT_CHOICE_GROUP_SELECTOR", "")
                ).split(",")
                if str(value).strip()
            ),
            "[data-testid*='variants-selector' i]",
            "[class*='selectable-container' i]",
        )
    )
)
VARIANT_SIZE_VALUE_PATTERNS = tuple(
    dict.fromkeys(
        (
            *tuple(_STATIC_EXPORTS.get("VARIANT_SIZE_VALUE_PATTERNS", ()) or ()),
            r"^\d+(?:\.\d+)?/\d+(?:\.\d+)?\s+us\s+\(\d+\s+eu\)$",
        )
    )
)
VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS = tuple(
    dict.fromkeys(
        (
            *(
                str(value).strip()
                for value in tuple(
                    _STATIC_EXPORTS.get(
                        "VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS", ()
                    )
                    or ()
                )
                if str(value).strip()
            ),
            r"^\s*option\s+",
            r"\s+(?:not\s+)?selected\s*$",
        )
    )
)
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
VARIANT_OPTION_TEXT_FIELDS = frozenset(PUBLIC_VARIANT_AXIS_FIELDS)
VARIANT_AXIS_ALLOWED_SINGLE_TOKENS = frozenset(
    {
        *VARIANT_OPTION_TEXT_FIELDS,
        "arms",
        "back",
        "band",
        "base",
        "bundle_type",
        "carat",
        "clarity",
        "colour",
        "commitment_period",
        "configuration",
        "connectivity",
        "count",
        "cup",
        "cut",
        "dimensions",
        "edition",
        "engraving",
        "fabric_grade",
        "finish",
        "fit",
        "flavor",
        "flavour",
        "format",
        "frame",
        "frequency",
        "gemstone",
        "height",
        "leg_finish",
        "length",
        "load_rating",
        "material",
        "material_composition",
        "memory",
        "metal",
        "model",
        "pack",
        "pattern",
        "personalization",
        "plug_type",
        "scent",
        "seat_count",
        "setting",
        "shade",
        "shape",
        "skin_type",
        "spf_rating",
        "state",
        "stone",
        "storage",
        "storage_capacity",
        "support",
        "thread_size",
        "tier",
        "tilt",
        "tolerance_level",
        "type",
        "usage_limit",
        "voltage",
        "volume",
        "weight",
        "width",
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
    "AVAILABILITY_IN_STOCK",
    "AVAILABILITY_OUT_OF_STOCK",
    "AVAILABILITY_URL_MAP",
    "NORMALIZER_AVAILABILITY_TOKENS",
    "BARE_HOST_URL_RE",
    "CATEGORY_PLACEHOLDER_VALUES",
    "COLOR_KEYWORD_PATTERN",
    "DEFAULT_DETAIL_MAX_VARIANT_ROWS",
    "FALLBACK_MAX_VARIANT_ROWS",
    "DOM_VARIANT_GROUP_LIMIT",
    "DETAIL_BRACKET_PROSE_MIN_WORDS",
    "DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS",
    "DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS",
    "DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS",
    "DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS",
    "DETAIL_GUIDE_GLOSSARY_TEXT_PATTERNS",
    "DETAIL_IDENTITY_FIELDS",
    "DETAIL_LONG_TEXT_RANK_FIELDS",
    "DETAIL_LONG_TEXT_SOURCE_RANKS",
    "DETAIL_LONG_TEXT_TRUNCATED_TAIL_TOKENS",
    "DETAIL_VARIANT_SIZE_SEQUENCE_MIN_COUNT",
    "DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES",
    "DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX",
    "DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES",
    "DETAIL_ARTIFACT_IDENTIFIER_VALUES",
    "DETAIL_ARTIFACT_PRICE_VALUES",
    "DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA",
    "DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO",
    "DETAIL_PRICE_CENT_MAGNITUDE_RATIO",
    "DETAIL_PRICE_COMPARISON_TOLERANCE",
    "DETAIL_PARENT_VARIANT_PRICE_RATIO_MIN",
    "DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX",
    "DETAIL_LOW_SIGNAL_PRICE_MAX",
    "DETAIL_LOW_SIGNAL_PARENT_MIN",
    "DETAIL_PRICE_MAGNITUDE_EPSILON",
    "VARIANT_OPTION_LABEL_MAX_WORDS",
    "VARIANT_TITLE_STOPWORDS",
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
    "DETAIL_LEGAL_TAIL_PATTERNS",
    "LONG_TEXT_MIN_WORDS",
    "LONG_TEXT_MAX_WORDS",
    "TOKEN_MIN_LEN_DISTINCTIVE",
    "TOKEN_MIN_LEN_CHUNK",
    "LONG_TEXT_PREFIXES",
    "DETAIL_MATERIALS_ZERO_PERCENT_PATTERN",
    "DETAIL_NOISE_PREFIXES",
    "DETAIL_NOISE_SECTION_SELECTORS",
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
    "DETAIL_BREADCRUMB_NOISE_ICON_PATTERNS",
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
    "FEATURE_SECTION_SELECTORS",
    "FEATURE_ROW_NOISE_PATTERNS",
    "GIF_BASE64_PREFIX",
    "GENDER_KEYWORD_TOKENS",
    "GENDER_ARTIFACT_PATTERN",
    "GENDER_POSSESSIVE_PATTERN",
    "IMAGE_FIELDS",
    "IMAGE_FAMILY_NOISE_TOKENS",
    "IMAGE_PATH_TOKENS",
    "INTEGER_VALUE_FIELDS",
    "JSON_RECORD_LIST_KEYS",
    "JOB_LISTING_DETAIL_ROOT_MARKERS",
    "JOB_POSTING_PATH_MARKERS",
    "LISTING_CHROME_TEXT_LIMIT",
    "LISTING_PRICE_NODE_SELECTORS",
    "LISTING_PROMINENT_TITLE_TAGS",
    "LISTING_CATEGORY_PATH_PREFIXES",
    "LISTING_CATEGORY_PATH_SEGMENTS",
    "LISTING_PRODUCT_DETAIL_ID_RE",
    "LONG_TEXT_FIELDS",
    "MAX_CANDIDATES_PER_FIELD",
    "MATERIAL_KEYWORDS",
    "ORACLE_HCM_CX_CONFIG_RE",
    "ORACLE_HCM_DEFAULT_FACETS",
    "ORACLE_HCM_JOB_PATH_RE",
    "ORACLE_HCM_LANG_PATH_RE",
    "ORACLE_HCM_LOCATION_LIST_KEYS",
    "ORACLE_HCM_SITE_PATH_RE",
    "OPTION_VALUE_NOISE_WORDS",
    "ORG_SUFFIXES",
    "REMOTE_BOOLEAN_FALSE_TOKENS",
    "REMOTE_BOOLEAN_TRUE_TOKENS",
    "PERCENT_RE",
    "PRICE_VALUE_FIELDS",
    "PRICE_SOURCE_KEY_FIELDS",
    "CANONICAL_PRICE_FIELDS",
    "CDN_IMAGE_QUERY_PARAMS",
    "RATING_RE",
    "REVIEW_COUNT_RE",
    "REVIEW_TITLE_RE",
    "SHIPPING_INVENTORY_PAYLOAD_HINT_FIELDS",
    "SHIPPING_DATE_FIELD",
    "SPECIAL_DAYS_FIELD",
    "IS_AVAILABLE_FIELD",
    "IS_INVENTORY_ONLY_FIELD",
    "SEMANTIC_SECTION_LABEL_SKIP_TOKENS",
    "STRUCTURED_MULTI_FIELDS",
    "STRUCTURED_OBJECT_FIELDS",
    "STRUCTURED_OBJECT_LIST_FIELDS",
    "ECOMMERCE_DESCRIPTION_BLOCK_LIMIT",
    "URL_FIELDS",
    "VARIANT_FIELDS",
    "VARIANT_CHOICE_OPTION_SELECTOR",
    "VARIANT_CHOICE_OPTION_LIMIT",
    "VARIANT_CHOICE_CONTAINER_OPTION_LIMIT",
    "VARIANT_CHOICE_CONTAINER_SELECT_LIMIT",
    "VARIANT_CHOICE_CONTAINER_GROUP_LIMIT",
    "VARIANT_CHOICE_CONTAINER_MIN_DISTINCT_NAMES",
    "VARIANT_AXIS_ALIASES",
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
    "SMALL_NUMERIC_PATTERN",
    "TRACKING_PIXEL_PATTERN",
    "URL_CONCATENATION_ALLOWED_PREFIX_SEPARATORS",
    "URL_CONCATENATION_SCHEME_PATTERN",
    "URL_DETECTION_TOKENS",
    "YEAR_SLUG_PATTERN",
    "PRODUCT_SLUG_MIN_TERMINAL_TOKENS",
    "GENDER_ARTIFACT_WORDS",
    "STANDARD_SIZE_VALUES",
    "UNRESOLVED_TEMPLATE_URL_TOKENS",
    "VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT",
    "VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK",
    "DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS",
    "NOISY_PRODUCT_ATTRIBUTE_KEYS",
    "WAF_QUEUE_PATTERNS",
]


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
