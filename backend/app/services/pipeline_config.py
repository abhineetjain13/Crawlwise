# Pipeline configuration — single source of truth for all extraction tuning.
#
# INVARIANT: No extraction code may hardcode field names, CSS selectors,
# collection keys, field aliases, or detection thresholds. Everything
# tunable lives here and is loaded from the knowledge_base JSON files
# at import time. Users can edit the JSON files to add fields, aliases,
# selectors, or adjust thresholds without touching Python code.
#
# This module is intentionally flat and import-cheap.  It reads JSON once
# at startup and exposes plain dicts/sets/lists.
from __future__ import annotations

import json
from pathlib import Path

_KB_DIR = Path(__file__).resolve().parents[1] / "data" / "knowledge_base"


def _load(filename: str, fallback: dict | list) -> dict | list:
    path = _KB_DIR / filename
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback


# ---------------------------------------------------------------------------
# 1. Canonical schemas — loaded from canonical_schemas.json
#    Users add/remove fields per surface via the review UI or by editing
#    the JSON directly.  Extraction code iterates these, never a hardcoded list.
# ---------------------------------------------------------------------------

CANONICAL_SCHEMAS: dict[str, list[str]] = _load("canonical_schemas.json", {})  # type: ignore[assignment]


def canonical_fields(surface: str) -> list[str]:
    return list(CANONICAL_SCHEMAS.get(surface, []))


# ---------------------------------------------------------------------------
# 2. Pipeline tuning — loaded from pipeline_tuning.json
#    Every threshold, timeout, and heuristic parameter that controls
#    acquisition, detection, and extraction behavior.
# ---------------------------------------------------------------------------

_TUNING: dict = _load("pipeline_tuning.json", {})  # type: ignore[assignment]
_EXTRACTION_RULES: dict = _load("extraction_rules.json", {})  # type: ignore[assignment]
_LLM_TUNING: dict = _load("llm_tuning.json", {})  # type: ignore[assignment]

# Acquisition
HTTP_TIMEOUT_SECONDS: int = _TUNING.get("http_timeout_seconds", 20)
IMPERSONATION_TARGET: str = _TUNING.get("impersonation_target", "chrome110")
HTTP_IMPERSONATION_PROFILES: tuple[str, ...] = tuple(
    profile for profile in _TUNING.get("http_impersonation_profiles", [IMPERSONATION_TARGET, "chrome131"])
    if str(profile).strip()
)
HTTP_STEALTH_IMPERSONATION_PROFILE: str = str(
    _TUNING.get(
        "http_stealth_impersonation_profile",
        HTTP_IMPERSONATION_PROFILES[-1] if HTTP_IMPERSONATION_PROFILES else IMPERSONATION_TARGET,
    )
)
BROWSER_FALLBACK_VISIBLE_TEXT_MIN: int = _TUNING.get("browser_fallback_visible_text_min", 500)
BROWSER_FALLBACK_VISIBLE_TEXT_RATIO_MAX: float = _TUNING.get("browser_fallback_visible_text_ratio_max", 0.02)
BROWSER_FALLBACK_HTML_SIZE_THRESHOLD: int = _TUNING.get("browser_fallback_html_size_threshold", 200000)
JS_GATE_PHRASES: list[str] = _TUNING.get("js_gate_phrases", [
    "enable javascript",
    "<noscript>",
])
DEFAULT_MAX_RECORDS: int = _TUNING.get("default_max_records", 100)
DEFAULT_SLEEP_MS: int = _TUNING.get("default_sleep_ms", 0)
MIN_REQUEST_DELAY_MS: int = _TUNING.get("min_request_delay_ms", 100)
DEFAULT_MAX_SCROLLS: int = _TUNING.get("default_max_scrolls", 10)
BATCH_URL_CONCURRENCY: int = _TUNING.get("batch_url_concurrency", 8)
WORKER_MAX_CONCURRENT_JOBS: int = _TUNING.get("worker_max_concurrent_jobs", 8)
WORKER_ORPHAN_RECOVERY_GRACE_SECONDS: int = _TUNING.get("worker_orphan_recovery_grace_seconds", 900)

# Extraction tuning
MAX_CANDIDATES_PER_FIELD: int = _TUNING.get("max_candidates_per_field", 5)
DYNAMIC_FIELD_NAME_MAX_TOKENS: int = _TUNING.get("dynamic_field_name_max_tokens", 7)
ACCORDION_EXPAND_MAX: int = _TUNING.get("accordion_expand_max", 20)
ACCORDION_EXPAND_WAIT_MS: int = _TUNING.get("accordion_expand_wait_ms", 500)

# Blocked-page detection
BLOCK_MIN_HTML_LENGTH: int = _TUNING.get("block_min_html_length", 100)
BLOCK_LOW_CONTENT_TEXT_MAX: int = _TUNING.get("block_low_content_text_max", 500)
BLOCK_LOW_CONTENT_SCRIPT_MIN: int = _TUNING.get("block_low_content_script_min", 3)
BLOCK_LOW_CONTENT_LINK_MAX: int = _TUNING.get("block_low_content_link_max", 3)

# Listing detection
LISTING_MIN_ITEMS: int = _TUNING.get("listing_min_items", 2)
CARD_AUTODETECT_MIN_SIBLINGS: int = _TUNING.get("card_autodetect_min_siblings", 3)

# JSON extraction
JSON_MAX_SEARCH_DEPTH: int = _TUNING.get("json_max_search_depth", 5)
MAX_JSON_RECURSION_DEPTH: int = _TUNING.get("max_json_recursion_depth", 8)

# HTTP provider (Phase 1 hardening)
HTTP_RETRY_STATUS_CODES: list[int] = _TUNING.get("http_retry_status_codes", [403, 429, 503])
HTTP_MAX_RETRIES: int = _TUNING.get("http_max_retries", 2)
HTTP_RETRY_BACKOFF_BASE_MS: int = _TUNING.get("http_retry_backoff_base_ms", 400)
HTTP_RETRY_BACKOFF_MAX_MS: int = _TUNING.get("http_retry_backoff_max_ms", 3000)
DNS_RESOLUTION_RETRIES: int = _TUNING.get("dns_resolution_retries", 1)
DNS_RESOLUTION_RETRY_DELAY_MS: int = _TUNING.get("dns_resolution_retry_delay_ms", 250)
ACQUIRE_HOST_MIN_INTERVAL_MS: int = _TUNING.get("acquire_host_min_interval_ms", 250)
PACING_HOST_CACHE_MAX_ENTRIES: int = _TUNING.get("pacing_host_cache_max_entries", 1024)
PACING_HOST_CACHE_TTL_SECONDS: int = _TUNING.get("pacing_host_cache_ttl_seconds", 3600)
STEALTH_PREFER_TTL_HOURS: int = _TUNING.get("stealth_prefer_ttl_hours", 24)

# Browser runtime (Phase 2 hardening)
CHALLENGE_WAIT_MAX_SECONDS: int = _TUNING.get("challenge_wait_max_seconds", 12)
CHALLENGE_POLL_INTERVAL_MS: int = _TUNING.get("challenge_poll_interval_ms", 2000)
SURFACE_READINESS_MAX_WAIT_MS: int = _TUNING.get("surface_readiness_max_wait_ms", 12000)
SURFACE_READINESS_POLL_MS: int = _TUNING.get("surface_readiness_poll_ms", 500)
ORIGIN_WARM_PAUSE_MS: int = _TUNING.get("origin_warm_pause_ms", 2000)
BROWSER_ERROR_RETRY_ATTEMPTS: int = _TUNING.get("browser_error_retry_attempts", 1)
BROWSER_ERROR_RETRY_DELAY_MS: int = _TUNING.get("browser_error_retry_delay_ms", 1000)
BROWSER_NAVIGATION_NETWORKIDLE_TIMEOUT_MS: int = _TUNING.get("browser_navigation_networkidle_timeout_ms", 30000)
BROWSER_NAVIGATION_LOAD_TIMEOUT_MS: int = _TUNING.get("browser_navigation_load_timeout_ms", 15000)
BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS: int = _TUNING.get("browser_navigation_domcontentloaded_timeout_ms", 15000)
BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS: int = _TUNING.get("browser_navigation_optimistic_wait_ms", 3000)
INTERRUPTIBLE_WAIT_POLL_MS: int = _TUNING.get("interruptible_wait_poll_ms", 250)
PAGINATION_NAVIGATION_TIMEOUT_MS: int = _TUNING.get("pagination_navigation_timeout_ms", 20000)
LISTING_READINESS_MAX_WAIT_MS: int = _TUNING.get("listing_readiness_max_wait_ms", 12000)
LISTING_READINESS_POLL_MS: int = _TUNING.get("listing_readiness_poll_ms", 500)
SCROLL_WAIT_MIN_MS: int = _TUNING.get("scroll_wait_min_ms", 1500)
LOAD_MORE_WAIT_MIN_MS: int = _TUNING.get("load_more_wait_min_ms", 2000)
COOKIE_CONSENT_PREWAIT_MS: int = _TUNING.get("cookie_consent_prewait_ms", 400)
COOKIE_CONSENT_POSTCLICK_WAIT_MS: int = _TUNING.get("cookie_consent_postclick_wait_ms", 600)
SHADOW_DOM_FLATTEN_MAX_HOSTS: int = _TUNING.get("shadow_dom_flatten_max_hosts", 100)

if HTTP_RETRY_BACKOFF_BASE_MS < 0:
    raise ValueError("pipeline_tuning.json:http_retry_backoff_base_ms must be >= 0")
if HTTP_RETRY_BACKOFF_MAX_MS < HTTP_RETRY_BACKOFF_BASE_MS:
    raise ValueError(
        "pipeline_tuning.json:http_retry_backoff_max_ms must be >= http_retry_backoff_base_ms"
    )

# ---------------------------------------------------------------------------
# 3. Field aliases — loaded from field_aliases.json
#    Maps canonical field names to known API/JSON key aliases.
#    Used by both json_extractor and listing_extractor.
#    Users can add aliases for new APIs without touching code.
# ---------------------------------------------------------------------------

FIELD_ALIASES: dict[str, list[str]] = _EXTRACTION_RULES.get("field_aliases", _load("field_aliases.json", {}))  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 4. Collection keys — loaded from collection_keys.json
#    Known JSON keys that hold the main data array in API responses.
#    Used by both json_extractor and listing_extractor.
# ---------------------------------------------------------------------------

COLLECTION_KEYS: list[str] = _load("collection_keys.json", [])  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 5. DOM fallback patterns — loaded from dom_patterns.json
#    CSS selectors used as last-resort DOM extraction for known field types.
#    Adapters have their own selectors; these are the generic fallbacks.
# ---------------------------------------------------------------------------

DOM_PATTERNS: dict[str, str] = _EXTRACTION_RULES.get("dom_patterns", _load("dom_patterns.json", {}))  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 6. Card selectors — loaded from card_selectors.json
#    CSS selectors for detecting repeating listing cards by surface type.
# ---------------------------------------------------------------------------

_CARD_SELECTORS: dict = _load("card_selectors.json", {})  # type: ignore[assignment]
_PAGINATION_SELECTORS: dict = _load("pagination_selectors.json", {})  # type: ignore[assignment]

CARD_SELECTORS_COMMERCE: list[str] = _CARD_SELECTORS.get("ecommerce", [])
CARD_SELECTORS_JOBS: list[str] = _CARD_SELECTORS.get("jobs", [])
PAGINATION_NEXT_SELECTORS: list[str] = _PAGINATION_SELECTORS.get("next_page", [])
LOAD_MORE_SELECTORS: list[str] = _PAGINATION_SELECTORS.get("load_more", [])


# ---------------------------------------------------------------------------
# 7. Normalization rules — loaded from normalization_rules.json
#    Field-specific normalization behavior (e.g., price fields get numeric
#    extraction).  Users can add new price-like fields or change the regex.
# ---------------------------------------------------------------------------

_NORM_RULES: dict = _load("normalization_rules.json", {})  # type: ignore[assignment]

PRICE_FIELDS: set[str] = set(_NORM_RULES.get("price_fields", ["price", "sale_price"]))
PRICE_REGEX: str = _NORM_RULES.get("price_regex", r"\d[\d,.]*")
SALARY_FIELDS: set[str] = set(_NORM_RULES.get("salary_fields", ["salary", "compensation"]))
SALARY_RANGE_REGEX: str = _NORM_RULES.get(
    "salary_range_regex",
    r"(?:(?:[$€£₹]|(?i:USD|EUR|GBP|INR))?\s*\d[\d,.]*[kKmMbB]?\s*(?:[-–—]|to|until)\s*(?:[$€£₹]|(?i:USD|EUR|GBP|INR))?\s*\d[\d,.]*[kKmMbB]?\s*(?:[$€£₹]|(?i:USD|EUR|GBP|INR))?(?:\s*/\s*[a-zA-Z]+)?|(?:[$€£₹]|(?i:USD|EUR|GBP|INR))\s*\d[\d,.]*[kKmMbB]?(?:\s*(?:[$€£₹]|(?i:USD|EUR|GBP|INR)))?(?:\s*/\s*[a-zA-Z]+)?|\d[\d,.]*[kKmMbB]?(?:\s*(?:[$€£₹]|(?i:USD|EUR|GBP|INR)))?(?:\s*/\s*[a-zA-Z]+)?)",
)
CURRENCY_CODES: set[str] = set(_NORM_RULES.get("currency_codes", []))
CURRENCY_SYMBOL_MAP: dict[str, str] = dict(_NORM_RULES.get("currency_symbol_map", {}))
COLOR_NOISE_TOKENS: tuple[str, ...] = tuple(_NORM_RULES.get("color_noise_tokens", []))
SIZE_NOISE_TOKENS: tuple[str, ...] = tuple(_NORM_RULES.get("size_noise_tokens", []))
PAGE_URL_CURRENCY_HINTS: dict[str, str] = dict(_NORM_RULES.get("page_url_currency_hints", {}))
_NESTED_OBJECT_KEYS: dict = _NORM_RULES.get("nested_object_keys", {})  # type: ignore[assignment]
NESTED_TEXT_KEYS: tuple[str, ...] = tuple(_NESTED_OBJECT_KEYS.get("text_fields", ["name", "label", "title", "text", "value", "content", "description", "alt"]))
NESTED_URL_KEYS: tuple[str, ...] = tuple(_NESTED_OBJECT_KEYS.get("url_fields", ["href", "url", "link", "canonical_url"]))
NESTED_PRICE_KEYS: tuple[str, ...] = tuple(_NESTED_OBJECT_KEYS.get("price_fields", ["specialValue", "currentValue", "special", "current", "price", "amount", "value", "lowPrice", "minPrice", "displayPrice", "formattedPrice"]))
NESTED_ORIGINAL_PRICE_KEYS: tuple[str, ...] = tuple(_NESTED_OBJECT_KEYS.get("original_price_fields", ["compareAtPrice", "compare_at_price", "listPrice", "regularPrice", "wasPrice", "originalPrice", "maxPrice", "currentValue", "price"]))
NESTED_CURRENCY_KEYS: tuple[str, ...] = tuple(_NESTED_OBJECT_KEYS.get("currency_fields", ["currency", "currencyCode", "priceCurrency", "currency_code"]))
NESTED_CATEGORY_KEYS: tuple[str, ...] = tuple(_NESTED_OBJECT_KEYS.get("category_fields", ["name", "path", "pathEn", "breadcrumb", "categoryPath"]))


# ---------------------------------------------------------------------------
# 8. Verdict core fields — loaded from verdict_rules.json
#    The minimum field set that must be present for a "success" verdict
#    per surface type.  Users can adjust quality gates per vertical.
# ---------------------------------------------------------------------------

_VERDICT_RULES: dict = _load("verdict_rules.json", {})  # type: ignore[assignment]

VERDICT_CORE_FIELDS_DETAIL: set[str] = set(_VERDICT_RULES.get("detail_core_fields", ["title", "price", "brand"]))
VERDICT_CORE_FIELDS_LISTING: set[str] = set(_VERDICT_RULES.get("listing_core_fields", ["title"]))


# ---------------------------------------------------------------------------
# 8b. Requested field aliases — loaded from requested_field_aliases.json
#     Maps semantic detail fields to synonymous labels and section headings.
# ---------------------------------------------------------------------------

REQUESTED_FIELD_ALIASES: dict[str, list[str]] = _EXTRACTION_RULES.get("requested_field_aliases", _load("requested_field_aliases.json", {}))  # type: ignore[assignment]

_CANDIDATE_CLEANUP: dict = _EXTRACTION_RULES.get("candidate_cleanup", {})  # type: ignore[assignment]
CANDIDATE_PLACEHOLDER_VALUES: set[str] = set(_CANDIDATE_CLEANUP.get("placeholder_values", ["-", "—", "--", "n/a", "na", "none", "null", "undefined"]))
CANDIDATE_GENERIC_CATEGORY_VALUES: set[str] = set(_CANDIDATE_CLEANUP.get("generic_category_values", ["detail-page", "detail_page", "product", "page", "pdp"]))
CANDIDATE_GENERIC_TITLE_VALUES: set[str] = set(_CANDIDATE_CLEANUP.get("generic_title_values", ["chrome", "firefox", "safari", "edge", "home"]))
CANDIDATE_TITLE_NOISE_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_CLEANUP.get("title_noise_tokens", []))
GA_DATA_LAYER_KEYS: frozenset[str] = frozenset(_CANDIDATE_CLEANUP.get("ga_data_layer_keys", []))
_CANDIDATE_FIELD_GROUPS: dict = _CANDIDATE_CLEANUP.get("field_groups", {})  # type: ignore[assignment]
CANDIDATE_FIELD_GROUPS: dict[str, set[str]] = {
    str(group): {str(field) for field in fields}
    for group, fields in _CANDIDATE_FIELD_GROUPS.items()
    if isinstance(fields, list)
}
_CANDIDATE_FIELD_NAME_PATTERNS: dict = _CANDIDATE_CLEANUP.get("field_name_patterns", {})  # type: ignore[assignment]
CANDIDATE_URL_SUFFIXES: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("url_suffixes", ["_url", "url", "_link", "link", "_href", "href"]))
CANDIDATE_IMAGE_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("image_tokens", ["image", "images", "gallery", "photo", "thumbnail", "hero"]))
CANDIDATE_CURRENCY_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("currency_tokens", ["currency"]))
CANDIDATE_PRICE_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("price_tokens", ["price", "amount", "cost"]))
CANDIDATE_SALARY_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("salary_tokens", ["salary", "pay", "rate", "compensation"]))
CANDIDATE_RATING_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("rating_tokens", ["rating", "score"]))
CANDIDATE_REVIEW_COUNT_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("review_count_tokens", ["review_count", "reviews", "rating_count"]))
CANDIDATE_AVAILABILITY_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("availability_tokens", ["availability", "stock"]))
CANDIDATE_CATEGORY_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("category_tokens", ["category", "department", "breadcrumb"]))
CANDIDATE_DESCRIPTION_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("description_tokens", ["description", "summary", "overview", "details"]))
CANDIDATE_IDENTIFIER_TOKENS: tuple[str, ...] = tuple(_CANDIDATE_FIELD_NAME_PATTERNS.get("identifier_tokens", ["sku", "id", "code", "vin", "mpn"]))
CANDIDATE_UI_NOISE_PHRASES: tuple[str, ...] = tuple(_CANDIDATE_CLEANUP.get("ui_noise_phrases", []))
CANDIDATE_UI_NOISE_TOKEN_PATTERN: str = str(_CANDIDATE_CLEANUP.get("ui_noise_token_pattern", r"\b[a-z]+_[a-z0-9_]+\b"))
CANDIDATE_UI_ICON_TOKEN_PATTERN: str = str(_CANDIDATE_CLEANUP.get("ui_icon_token_pattern", r"(corporate_fare|bar_chart|home_pin|location_on|travel_explore|business_center|storefront|schedule|payments|school|work)(?=[A-Z]|\b)|place(?=[A-Z])"))
CANDIDATE_SCRIPT_NOISE_PATTERN: str = str(_CANDIDATE_CLEANUP.get("script_noise_pattern", r"\b(?:imageloader|document\.getelementbyid|fallback-image)\b"))
CANDIDATE_PROMO_ONLY_TITLE_PATTERN: str = str(_CANDIDATE_CLEANUP.get("promo_only_title_pattern", r"^(?:[-–—]?\s*)?(?:\d{1,3}%\s*(?:off)?|sale|new(?:\s+in)?|view\s*\d+|best seller|top seller)\s*$"))
_INTELLIGENCE_CLEANUP: dict = _EXTRACTION_RULES.get("intelligence_cleanup", {})  # type: ignore[assignment]
INTELLIGENCE_FIELD_NOISE_TOKENS: set[str] = set(_INTELLIGENCE_CLEANUP.get("field_noise_tokens", []))
INTELLIGENCE_VALUE_NOISE_PHRASES: tuple[str, ...] = tuple(_INTELLIGENCE_CLEANUP.get("value_noise_phrases", []))
_LISTING_EXTRACTION_RULES: dict = _EXTRACTION_RULES.get("listing_extraction", {})  # type: ignore[assignment]
LISTING_DETAIL_PATH_MARKERS: tuple[str, ...] = tuple(_LISTING_EXTRACTION_RULES.get("detail_path_markers", []))
LISTING_SWATCH_CONTAINER_SELECTORS: tuple[str, ...] = tuple(_LISTING_EXTRACTION_RULES.get("swatch_container_selectors", []))
LISTING_IMAGE_EXCLUDE_TOKENS: tuple[str, ...] = tuple(_LISTING_EXTRACTION_RULES.get("image_exclude_tokens", []))
LISTING_COLOR_ACTION_VALUES: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("color_action_values", []))
LISTING_COLOR_ACTION_PREFIXES: tuple[str, ...] = tuple(_LISTING_EXTRACTION_RULES.get("color_action_prefixes", []))
LISTING_FILTER_OPTION_KEYS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("filter_option_keys", []))
LISTING_MINIMAL_VISUAL_FIELDS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("minimal_visual_fields", []))
LISTING_PRODUCT_SIGNAL_FIELDS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("product_signal_fields", []))
LISTING_JOB_SIGNAL_FIELDS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("job_signal_fields", []))
LISTING_NON_LISTING_PATH_TOKENS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("non_listing_path_tokens", []))
LISTING_HUB_PATH_SEGMENTS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("hub_path_segments", []))
LISTING_WEAK_METADATA_FIELDS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("weak_metadata_fields", []))
LISTING_FACET_QUERY_KEYS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("facet_query_keys", []))
LISTING_FACET_PATH_FRAGMENTS: tuple[str, ...] = tuple(_LISTING_EXTRACTION_RULES.get("facet_path_fragments", []))
LISTING_CATEGORY_PATH_MARKERS: frozenset[str] = frozenset(_LISTING_EXTRACTION_RULES.get("category_path_markers", []))
_ACQUISITION_GUARDS: dict = _EXTRACTION_RULES.get("acquisition_guards", {})  # type: ignore[assignment]
JOB_REDIRECT_SHELL_TITLES: frozenset[str] = frozenset(_ACQUISITION_GUARDS.get("job_redirect_shell_titles", []))
JOB_REDIRECT_SHELL_CANONICAL_URLS: frozenset[str] = frozenset(_ACQUISITION_GUARDS.get("job_redirect_shell_canonical_urls", []))
JOB_REDIRECT_SHELL_HEADINGS: frozenset[str] = frozenset(_ACQUISITION_GUARDS.get("job_redirect_shell_headings", []))
JOB_ERROR_PAGE_TITLES: frozenset[str] = frozenset(_ACQUISITION_GUARDS.get("job_error_page_titles", []))
JOB_ERROR_PAGE_HEADINGS: frozenset[str] = frozenset(_ACQUISITION_GUARDS.get("job_error_page_headings", []))

_SEMANTIC_DETAIL_RULES: dict = _EXTRACTION_RULES.get("semantic_detail", {})  # type: ignore[assignment]
SECTION_SKIP_PATTERNS: tuple[str, ...] = tuple(_SEMANTIC_DETAIL_RULES.get("section_skip_patterns", ["add to cart", "buy now", "checkout", "login", "sign in", "subscribe"]))
SECTION_ANCESTOR_STOP_TAGS: set[str] = set(_SEMANTIC_DETAIL_RULES.get("section_ancestor_stop_tags", ["footer", "header", "nav", "aside", "form"]))
SECTION_ANCESTOR_STOP_TOKENS: set[str] = set(_SEMANTIC_DETAIL_RULES.get("section_ancestor_stop_tokens", ["footer", "header", "nav", "menu", "newsletter", "breadcrumbs", "breadcrumb", "cookie", "consent"]))
SPEC_LABEL_BLOCK_PATTERNS: tuple[str, ...] = tuple(_SEMANTIC_DETAIL_RULES.get("spec_label_block_patterns", ["play video", "watch video", "video", "learn more", "add to cart", "buy now", "primary guide", "guide", "discount"]))
SPEC_DROP_LABELS: set[str] = set(_SEMANTIC_DETAIL_RULES.get("spec_drop_labels", ["qty", "quantity", "details"]))
FEATURE_SECTION_ALIASES: set[str] = set(_SEMANTIC_DETAIL_RULES.get("feature_section_aliases", ["features", "feature", "highlights", "key_features", "key features"]))
DIMENSION_KEYWORDS: tuple[str, ...] = tuple(_SEMANTIC_DETAIL_RULES.get("dimension_keywords", ["width", "height", "depth", "length", "diameter", "weight", "dimensions", "size", "measurement", "measurements"]))
SEMANTIC_AGGREGATE_SEPARATOR: str = str(_SEMANTIC_DETAIL_RULES.get("aggregate_separator", " | "))


# ---------------------------------------------------------------------------
# 8c. Hydrated state script markers — loaded from hydrated_state_patterns.json
#     Used by discovery to detect inline app state beyond __NEXT_DATA__.
#     Includes site-specific lowercase sentinels such as ``__myx`` because
#     some frameworks expose them with exact casing (for example Myntra's
#     ``window.__myx`` bootstrap payload).
# ---------------------------------------------------------------------------

HYDRATED_STATE_PATTERNS: list[str] = _load("hydrated_state_patterns.json", [])  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 9. Block detection signatures — loaded from block_signatures.json
#    Deterministic phrases and provider markers for blocked-page detection.
# ---------------------------------------------------------------------------

_BLOCK_SIG: dict = _load("block_signatures.json", {})  # type: ignore[assignment]

BLOCK_PHRASES: list[str] = _BLOCK_SIG.get("phrases", [
    "access denied",
    "access to this page has been denied",
    "robot or human",
    "are you a robot",
    "are you human",
    "please verify you are a human",
    "verify you are human",
    "complete the security check",
    "please complete the captcha",
    "enable javascript to view",
    "enable javascript and cookies",
    "you have been blocked",
    "this request was blocked",
    "sorry, you have been blocked",
    "checking your browser",
    "checking if the site connection is secure",
    "just a moment",
    "attention required",
    "pardon our interruption",
    "please turn javascript on",
    "why do i have to complete a captcha",
])

PROVIDER_MARKERS: list[str] = _BLOCK_SIG.get("provider_markers", [
    "perimeterx",
    "px-captcha",
    "cloudflare",
    "cf-challenge",
    "cf-browser-verification",
    "akamai",
    "akamaized",
    "datadome",
    "dd-modal",
    "kasada",
    "incapsula",
    "distil",
    "shape security",
    "hcaptcha",
    "recaptcha",
    "g-recaptcha",
    "funcaptcha",
    "arkose",
])
BLOCK_ACTIVE_PROVIDER_MARKERS: list[dict[str, str]] = _BLOCK_SIG.get("active_provider_markers", [])  # type: ignore[assignment]
BLOCK_CDN_PROVIDER_MARKERS: list[dict[str, str]] = _BLOCK_SIG.get("cdn_provider_markers", [])  # type: ignore[assignment]
BLOCK_BROWSER_CHALLENGE_STRONG_MARKERS: dict[str, str] = _BLOCK_SIG.get("browser_challenge_strong_markers", {})  # type: ignore[assignment]
BLOCK_BROWSER_CHALLENGE_WEAK_MARKERS: dict[str, str] = _BLOCK_SIG.get("browser_challenge_weak_markers", {})  # type: ignore[assignment]

BLOCK_TITLE_REGEXES: list[str] = _BLOCK_SIG.get("title_regexes", [
    r"access\s+denied",
    r"robot\s+or\s+human",
    r"just\s+a\s+moment",
    r"attention\s+required",
    r"you\s+have\s+been\s+blocked",
    r"security\s+check",
    r"pardon\s+our\s+interruption",
])


# ---------------------------------------------------------------------------
# 10. Cookie consent selectors — loaded from consent_selectors.json
#     CSS selectors for dismissing cookie banners.
# ---------------------------------------------------------------------------

COOKIE_CONSENT_SELECTORS: list[str] = _load("consent_selectors.json", [])  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 11. Cookie persistence policy — loaded from cookie_policy.json
#     Controls which cookies may be reused between runs. Defaults are
#     intentionally conservative: challenge/anti-bot cookies are never
#     persisted and session cookies are runtime-only unless explicitly enabled.
# ---------------------------------------------------------------------------

COOKIE_POLICY: dict = _load("cookie_policy.json", {})  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 12. Review container keys — structural metadata keys to filter from
#     discovered_fields in the review UI.
# ---------------------------------------------------------------------------

REVIEW_CONTAINER_KEYS: set[str] = set(_load("review_container_keys.json", []))  # type: ignore[assignment]

if not REVIEW_CONTAINER_KEYS:
    REVIEW_CONTAINER_KEYS = {
        "adapter_data", "network_payloads", "next_data", "json_ld",
        "microdata", "tables", "content_type", "source",
        "is_blocked", "reason", "provider",
    }


# ---------------------------------------------------------------------------
# 13. Extraction structural rules — loaded from extraction_rules.json
#     JSON-LD filtering, source ranking, and dynamic field noise control.
# ---------------------------------------------------------------------------

JSONLD_STRUCTURAL_KEYS: frozenset[str] = frozenset(_EXTRACTION_RULES.get("jsonld_structural_keys", ["@type", "@context", "@id", "@graph", "@vocab", "@list", "@set"]))
JSONLD_NON_PRODUCT_BLOCK_TYPES: frozenset[str] = frozenset(_EXTRACTION_RULES.get("jsonld_non_product_block_types", [
    "organization", "website", "webpage", "breadcrumblist",
    "searchaction", "sitenavigationelement", "imageobject",
    "videoobject", "faqpage", "howto", "person",
    "localbusiness", "store",
]))
PRODUCT_IDENTITY_FIELDS: frozenset[str] = frozenset(_EXTRACTION_RULES.get("product_identity_fields", [
    "title", "price", "sale_price", "original_price", "brand",
    "description", "sku", "image_url", "additional_images",
    "availability", "category",
]))
NESTED_NON_PRODUCT_KEYS: frozenset[str] = frozenset(_EXTRACTION_RULES.get("nested_non_product_keys", [
    "review", "reviews", "aggregaterating", "aggregate_rating",
    "author", "publisher", "creator", "contributor",
    "breadcrumb", "breadcrumblist", "itemlistelement",
    "potentialaction", "mainentityofpage",
]))
JSONLD_TYPE_NOISE: set[str] = set(_EXTRACTION_RULES.get("jsonld_type_noise", []))
DYNAMIC_FIELD_NAME_DROP_TOKENS: set[str] = set(_EXTRACTION_RULES.get("dynamic_field_name_drop_tokens", []))
SOURCE_RANKING: dict[str, int] = _EXTRACTION_RULES.get("source_ranking", {})


# ---------------------------------------------------------------------------
# 14. LLM request tuning — loaded from llm_tuning.json
#     Prompt truncation limits and provider request params.
# ---------------------------------------------------------------------------

LLM_HTML_SNIPPET_MAX_CHARS: int = _LLM_TUNING.get("html_snippet_max_chars", 12000)
LLM_EXISTING_VALUES_MAX_CHARS: int = _LLM_TUNING.get("existing_values_max_chars", 2400)
LLM_CANDIDATE_EVIDENCE_MAX_CHARS: int = _LLM_TUNING.get("candidate_evidence_max_chars", 16000)
LLM_DISCOVERED_SOURCES_MAX_CHARS: int = _LLM_TUNING.get("discovered_sources_max_chars", 15000)
LLM_CLEAN_CANDIDATE_TEXT_LIMIT: int = _LLM_TUNING.get("clean_candidate_text_limit", 1200)
LLM_GROQ_MAX_TOKENS: int = _LLM_TUNING.get("groq_max_tokens", 1200)
LLM_GROQ_TEMPERATURE: float = _LLM_TUNING.get("groq_temperature", 0.1)
LLM_ANTHROPIC_MAX_TOKENS: int = _LLM_TUNING.get("anthropic_max_tokens", 3000)
LLM_ANTHROPIC_TEMPERATURE: float = _LLM_TUNING.get("anthropic_temperature", 0.1)
LLM_NVIDIA_MAX_TOKENS: int = _LLM_TUNING.get("nvidia_max_tokens", 1200)
LLM_NVIDIA_TEMPERATURE: float = _LLM_TUNING.get("nvidia_temperature", 0.1)
