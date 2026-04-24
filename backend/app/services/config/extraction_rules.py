from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.platform_policy import known_ats_domains

_EXPORTS_PATH = Path(__file__).with_name("extraction_rules.exports.json")


@lru_cache(maxsize=1)
def _static_exports() -> dict[str, Any]:
    return load_export_data(str(_EXPORTS_PATH))


def _acquisition_guard_export(rule_name: str) -> frozenset[object]:
    rules = _static_exports().get("ACQUISITION_GUARDS_RULES", {})
    values = rules.get(rule_name, []) if isinstance(rules, dict) else []
    return frozenset(
        values if isinstance(values, (list, tuple, set, frozenset)) else []
    )


_STATIC_EXPORTS = {
    name: value
    for name, value in _static_exports().items()
    if not name.startswith("_")
}
globals().update(_STATIC_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


LISTING_STRUCTURE_POSITIVE_HINTS = (
    "card",
    "item",
    "listing",
    "product",
    "result",
    "tile",
    "record",
    "entry",
)
LISTING_STRUCTURE_NEGATIVE_HINTS = (
    "nav",
    "menu",
    "header",
    "footer",
    "breadcrumb",
    "toolbar",
    "filter",
    "sort",
    "sidebar",
    "pagination",
)
LISTING_FALLBACK_CONTAINER_SELECTOR = "article, li, div, tr, section, [role='row']"
CURRENCY_ALIAS_PATTERNS: dict[str, str] = {
    r"\brs\.?\s*\d": "INR",
}
LISTING_UTILITY_TITLE_PATTERNS: tuple[str, ...] = (
    r"^\+?\s*(?:[$€£]|chf|usd|inr|rs\.?)?\s*[\d,.]+\s+shipping$",
    r"^(?:make offer\s*/\s*details|details\s*/\s*make offer)$",
    r"^(?:post a job|product help|product tips)$",
    # Bare "Product Name" can be a legitimate catalog title, so keep the utility pattern more specific.
    r"^\d[\d,\s]*\s+reviews?\s+given\s+by\s+verified\s+buyers$",
    r"^how posting dates work$",
    r"^download(?:\s+the)?\s+.+\s+app$",
    r"^shop all categories$",
    r"^(?:customer care|customer service|help|support|faq|about(?: us)?|returns?)$",
)
LISTING_UTILITY_TITLE_TOKENS: tuple[str, ...] = (
    "customer care",
    "customer service",
    "fundraising",
    "group ordering",
    "how posting dates work",
    "online stores",
    "post a job",
    "pro services",
    "product help",
    "product tips",
    "tips & advice",
    "tools & resources",
)
LISTING_UTILITY_URL_TOKENS: tuple[str, ...] = (
    "/about",
    "/account",
    "/categories",
    "/contact",
    "/customer-care",
    "/customer-service",
    "/employers/posts/new",
    "/faq",
    "/help",
    "://instagram.com",
    "/login",
    "/sign-in",
    "/sign_in",
    "/privacy",
    "/returns",
    "/savedsearches",
    "/shipping",
    "/support",
    "/terms",
    "/termsofuse",
    ".doc",
    ".docx",
    ".pdf",
)
JOB_LISTING_DETAIL_PATH_MARKERS: tuple[str, ...] = tuple(
    marker
    for marker in LISTING_DETAIL_PATH_MARKERS
    if any(
        token in marker
        for token in ("career", "job", "opening", "position", "posting")
    )
)

DYNAMIC_FIELD_NAME_MAX_TOKENS = crawler_runtime_settings.dynamic_field_name_max_tokens
KNOWN_ATS_PLATFORMS = known_ats_domains
MAX_CANDIDATES_PER_FIELD = crawler_runtime_settings.max_candidates_per_field
JOB_REDIRECT_SHELL_TITLES = _acquisition_guard_export("job_redirect_shell_titles")
JOB_REDIRECT_SHELL_CANONICAL_URLS = _acquisition_guard_export(
    "job_redirect_shell_canonical_urls"
)
JOB_REDIRECT_SHELL_HEADINGS = _acquisition_guard_export("job_redirect_shell_headings")
JOB_ERROR_PAGE_TITLES = _acquisition_guard_export("job_error_page_titles")
JOB_ERROR_PAGE_HEADINGS = _acquisition_guard_export("job_error_page_headings")

TITLE_PROMOTION_PREFIXES: tuple[str, ...] = (
    "buy ",
)
TITLE_PROMOTION_SUBSTRINGS: tuple[str, ...] = (
    "apparel for",
)
TITLE_PROMOTION_SEPARATOR: str = "|"
DETAIL_BRAND_SHELL_TITLE_TOKENS: tuple[str, ...] = (
    "lifewear",
    "official",
    "shop",
    "store",
)
DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES: tuple[str, ...] = (
    "best experience",
    "download our app",
    "shop on our app",
)
CROSS_LINK_CONTAINER_HINTS: tuple[str, ...] = (
    "cross-sell",
    "crosssell",
    "grid",
    "related",
    "recommend",
    "similar",
    "upsell",
    "widget",
)
PRODUCT_GALLERY_CONTEXT_HINTS: tuple[str, ...] = (
    "carousel",
    "gallery",
    "media",
    "pdp",
    "photo",
    "product",
    "slider",
    "thumb",
    "zoom",
)
NON_PRODUCT_IMAGE_HINTS: tuple[str, ...] = (
    "avatar",
    "badge",
    "blog",
    "brand",
    "breadcrumb",
    "discount",
    "flag",
    "icon",
    "loader",
    "location",
    "logo",
    "offer",
    "payment",
    "placeholder",
    "promo",
    "rating",
    "review",
    "social",
    "sprite",
)
NON_PRODUCT_PROVIDER_HINTS: tuple[str, ...] = (
    "affirm",
    "amex",
    "american express",
    "klarna",
    "mastercard",
    "paypal",
    "visa",
)
JS_STATE_NON_PRODUCT_IMAGE_HINTS: tuple[str, ...] = (
    "affirm",
    "amex",
    "bookmark",
    "color-swatches",
    "icon",
    "logo",
    "mastercard",
    "paypal",
    "swatch",
    "visa",
)
DETAIL_BLOCKED_TOKENS: tuple[str, ...] = (
    "add to cart",
    "add to bag",
    "bag",
    "buy now",
    "cart",
    "checkout",
    "login",
    "log in",
    "menu",
    "navigation",
    "shopping bag",
    "sign in",
    "sign up",
    "subscribe",
    "wishlist",
)
DETAIL_UTILITY_PATH_TOKENS: tuple[str, ...] = (
    "account",
    "cart",
    "faq",
    "faqs",
    "help",
    "login",
    "logout",
    "mywishlist",
    "returns",
    "search",
    "signin",
    "support",
    "wishlist",
)
DETAIL_NON_PAGE_FILE_EXTENSIONS: tuple[str, ...] = (
    ".avif",
    ".bmp",
    ".doc",
    ".docx",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".json",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".webm",
    ".webp",
    ".zip",
)
DETAIL_IRRELEVANT_JSON_LD_TYPES: tuple[str, ...] = (
    "audiobook",
    "audioobject",
    "breadcrumblist",
    "clip",
    "imageobject",
    "listitem",
    "mediaobject",
    "movie",
    "siteNavigationElement",
    "videoobject",
    "webpage",
    "website",
)
VARIANT_AXIS_LABEL_NOISE_TOKENS: tuple[str, ...] = (
    "answer",
    "answers",
    "delivery",
    "emi",
    "faq",
    "helpfulness",
    "language",
    "payment",
    "question",
    "questions",
    "rating",
    "ratings",
    "review",
    "reviews",
    "shipping",
    "translate",
    "translator",
    "warranty",
    "widget",
)
VARIANT_AXIS_LABEL_NOISE_PATTERNS: tuple[str, ...] = (
    r"\bq&a\b",
    r"\b\d+\s+answers?\b",
    r"\bask\s+a\s+question\b",
    r"\bcontent\s+helpfulness\b",
    r"\blanguage\s+translate\s+widget\b",
    r"\breport\s+this\s+answer\b",
)
VARIANT_GROUP_ATTR_NOISE_TOKENS: tuple[str, ...] = (
    "country-picker",
    "estimated-shipping-country",
    "report-item-choices",
    "shipping-country",
    "ship-to-country",
)
VARIANT_GROUP_ATTR_NOISE_PATTERNS: tuple[str, ...] = (
    r"\bchoose\s+a\s+reason\b",
    r"\bchoose\s+country\b",
    r"\bcountry\s+picker\b",
    r"\bestimated\s+shipping\s+country\b",
    r"\breport\s+item\b",
    r"\bship(?:ping)?\s+to\s+country\b",
    r"\bregions?\s+etsy\s+does\s+business\s+in\b",
)
VARIANT_COLOR_HINT_WORDS: tuple[str, ...] = (
    "beige",
    "black",
    "blue",
    "brown",
    "charcoal",
    "cream",
    "gold",
    "gray",
    "green",
    "grey",
    "ivory",
    "khaki",
    "maroon",
    "navy",
    "nude",
    "olive",
    "orange",
    "pearl",
    "pink",
    "purple",
    "red",
    "sand",
    "silver",
    "tan",
    "teal",
    "white",
    "yellow",
)
VARIANT_SIZE_VALUE_PATTERNS: tuple[str, ...] = (
    r"^(?:xxxs|xxs|xs|s|m|l|xl|xxl|xxxl)$",
    r"^\d+xl$",
    r"^(?:one|free|single)\s+size$",
    r"^(?:os|o/s)$",
    r"^(?:(?:eu|uk|us|cm|mm)[-\s]?)?\d{1,3}(?:/\d{1,3})?$",
    r"^\d+(?:\.\d+)?\s?(?:cm|mm|in\.?|inch|inches)$",
)
DETAIL_EXPAND_SELECTORS: tuple[str, ...] = (
    "summary",
    "details > summary",
    "[aria-expanded='false']",
    "button[aria-controls]",
    "[role='button'][aria-controls]",
    "[role='tab'][aria-controls]",
    "button",
    "[role='button']",
    "a",
)
DETAIL_EXPAND_KEYWORD_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "ecommerce": (
        "care",
        "composition",
        "materials",
        "measurements",
        "origin",
        "returns",
        "shipping",
        "size",
    ),
    "job": (),
}
SOURCE_PRIORITY: tuple[str, ...] = (
    "adapter",
    "network_payload",
    "json_ld",
    "microdata",
    "opengraph",
    "embedded_json",
    "js_state",
    "dom_h1",
    "dom_canonical",
    "selector_rule",
    "dom_selector",
    "dom_sections",
    "dom_images",
    "dom_text",
)
DETAIL_TITLE_SOURCE_RANKS: dict[str, int] = {
    "adapter": 0,
    "network_payload": 1,
    "json_ld": 2,
    "microdata": 3,
    "opengraph": 4,
    "embedded_json": 5,
    "js_state": 6,
    "dom_h1": 10,
    "dom_canonical": 11,
    "selector_rule": 12,
    "dom_selector": 13,
    "dom_sections": 14,
    "dom_images": 15,
    "dom_text": 16,
}
SURFACE_WEIGHTS: dict[str, dict[str, float]] = {
    "ecommerce_detail": {
        "title": 0.2,
        "price": 0.15,
        "brand": 0.1,
        "image_url": 0.1,
        "description": 0.1,
        "availability": 0.1,
        "variants": 0.15,
        "selected_variant": 0.1,
    },
    "job_detail": {
        "title": 0.2,
        "company": 0.1,
        "location": 0.1,
        "description": 0.1,
        "responsibilities": 0.15,
        "qualifications": 0.15,
        "apply_url": 0.1,
        "posted_date": 0.1,
    },
}
SOURCE_TIERS: dict[str, tuple[str, float]] = {
    "adapter": ("authoritative", 1.0),
    "network_payload": ("authoritative", 0.98),
    "js_state": ("structured", 0.92),
    "json_ld": ("structured", 0.9),
    "microdata": ("structured", 0.88),
    "opengraph": ("structured", 0.84),
    "embedded_json": ("structured", 0.84),
    "selector_rule": ("dom", 0.79),
    "dom_selector": ("dom", 0.78),
    "dom_sections": ("dom", 0.76),
    "dom_images": ("dom", 0.74),
    "dom_h1": ("dom", 0.7),
    "dom_canonical": ("dom", 0.72),
    "dom_text": ("text", 0.58),
    "llm_missing_field_extraction": ("llm", 0.55),
}
VARIANT_SELECT_GROUP_SELECTOR: str = (
    "select[data-option-name], select[data-option], select[name], "
    "select[id], select[aria-label]"
)
VARIANT_CHOICE_GROUP_SELECTOR: str = (
    "[data-option-name], [class*='swatch' i], "
    "[class*='color-selector' i], [class*='size-selector' i], "
    "[data-testid*='swatch' i], [role='radiogroup'], "
    "[data-qa-action='select-color'], [data-qa-action*='size-selector']"
)

__all__ = sorted(
    [
        *_STATIC_EXPORTS.keys(),
        "CROSS_LINK_CONTAINER_HINTS",
        "DETAIL_BLOCKED_TOKENS",
        "DETAIL_EXPAND_KEYWORD_EXTENSIONS",
        "DETAIL_EXPAND_SELECTORS",
        "DETAIL_IRRELEVANT_JSON_LD_TYPES",
        "DETAIL_NON_PAGE_FILE_EXTENSIONS",
        "DETAIL_UTILITY_PATH_TOKENS",
        "DETAIL_TITLE_SOURCE_RANKS",
        "DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES",
        "DETAIL_BRAND_SHELL_TITLE_TOKENS",
        "DYNAMIC_FIELD_NAME_MAX_TOKENS",
        "JOB_ERROR_PAGE_HEADINGS",
        "JOB_ERROR_PAGE_TITLES",
        "JOB_LISTING_DETAIL_PATH_MARKERS",
        "JOB_REDIRECT_SHELL_CANONICAL_URLS",
        "JOB_REDIRECT_SHELL_HEADINGS",
        "JOB_REDIRECT_SHELL_TITLES",
        "JS_STATE_NON_PRODUCT_IMAGE_HINTS",
        "KNOWN_ATS_PLATFORMS",
        "LISTING_FALLBACK_CONTAINER_SELECTOR",
        "LISTING_STRUCTURE_NEGATIVE_HINTS",
        "LISTING_STRUCTURE_POSITIVE_HINTS",
        "LISTING_UTILITY_TITLE_PATTERNS",
        "LISTING_UTILITY_TITLE_TOKENS",
        "LISTING_UTILITY_URL_TOKENS",
        "MAX_CANDIDATES_PER_FIELD",
        "NON_PRODUCT_IMAGE_HINTS",
        "NON_PRODUCT_PROVIDER_HINTS",
        "PRODUCT_GALLERY_CONTEXT_HINTS",
        "SOURCE_PRIORITY",
        "SOURCE_TIERS",
        "SURFACE_WEIGHTS",
        "TITLE_PROMOTION_PREFIXES",
        "TITLE_PROMOTION_SEPARATOR",
        "TITLE_PROMOTION_SUBSTRINGS",
        "VARIANT_AXIS_LABEL_NOISE_PATTERNS",
        "VARIANT_AXIS_LABEL_NOISE_TOKENS",
        "VARIANT_GROUP_ATTR_NOISE_PATTERNS",
        "VARIANT_GROUP_ATTR_NOISE_TOKENS",
        "VARIANT_CHOICE_GROUP_SELECTOR",
        "VARIANT_COLOR_HINT_WORDS",
        "VARIANT_SIZE_VALUE_PATTERNS",
        "VARIANT_SELECT_GROUP_SELECTOR",
    ]
)
