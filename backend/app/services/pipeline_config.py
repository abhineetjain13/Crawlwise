from __future__ import annotations

import re

from app.services.config.block_signatures import BLOCK_SIGNATURES
from app.services.config.extraction_rules import (
    COOKIE_POLICY as _COOKIE_POLICY,
    EXTRACTION_RULES as _EXTRACTION_RULES,
    HYDRATED_STATE_PATTERNS as _HYDRATED_STATE_PATTERNS,
    KNOWN_ATS_PLATFORMS as _KNOWN_ATS_PLATFORMS,
    LLM_TUNING as _LLM_TUNING,
    NORMALIZATION_RULES as _NORM_RULES,
    PIPELINE_TUNING as _TUNING,
    PLATFORM_BROWSER_POLICIES as _PLATFORM_BROWSER_POLICIES,
    SITE_POLICY_REGISTRY as _SITE_POLICY_REGISTRY,
    VERDICT_RULES as _VERDICT_RULES,
)
from app.services.config.field_mappings import (
    CANONICAL_SCHEMAS,
    COLLECTION_KEYS,
    FIELD_ALIASES as _FIELD_ALIASES_FILE,
    REQUESTED_FIELD_ALIASES as _REQUESTED_FIELD_ALIASES_FILE,
)
from app.services.config.selectors import (
    CARD_SELECTORS as _CARD_SELECTORS,
    CONSENT_SELECTORS as _CONSENT_SELECTORS,
    DISCOVERIST_SCHEMA as _DISCOVERIST_SCHEMA,
    DOM_PATTERNS as _DOM_PATTERNS,
    MARKDOWN_VIEW as _MARKDOWN_VIEW,
    PAGINATION_SELECTORS as _PAGINATION_SELECTORS,
    PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES as _PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES,
    PLATFORM_LISTING_READINESS_SELECTORS as _PLATFORM_LISTING_READINESS_SELECTORS,
    PLATFORM_LISTING_READINESS_URL_PATTERNS as _PLATFORM_LISTING_READINESS_URL_PATTERNS,
    REVIEW_CONTAINER_KEYS as _REVIEW_CONTAINER_KEYS,
)


def _compile_extraction_rule_pattern(
    pattern: object, *, setting_name: str
) -> re.Pattern[str]:
    raw_pattern = str(pattern or "").strip()
    if not raw_pattern:
        raise RuntimeError(
            f"Invalid empty regex for '{setting_name}' in extraction_rules.py"
        )
    try:
        return re.compile(raw_pattern, re.I)
    except re.error as exc:
        raise RuntimeError(
            f"Invalid regex '{raw_pattern}' for '{setting_name}' in extraction_rules.py"
        ) from exc


def _compile_extraction_rule_patterns(
    patterns: object, *, setting_name: str
) -> list[re.Pattern[str]]:
    compiled: list[re.Pattern[str]] = []
    normalized_patterns = patterns if isinstance(patterns, (list, tuple)) else []
    for pattern in normalized_patterns:
        compiled.append(
            _compile_extraction_rule_pattern(pattern, setting_name=setting_name)
        )
    return compiled


def _currency_symbol_class(symbol_map: dict[object, object]) -> str:
    symbols = sorted(
        {str(symbol).strip() for symbol in symbol_map.keys() if str(symbol).strip()}
    )
    if not symbols:
        return r"[$€£¥₹]"
    single_char_symbols = [symbol for symbol in symbols if len(symbol) == 1]
    multi_char_symbols = sorted(
        [symbol for symbol in symbols if len(symbol) > 1], key=len, reverse=True
    )
    if multi_char_symbols:
        alternates = [re.escape(symbol) for symbol in multi_char_symbols]
        if single_char_symbols:
            alternates.append(
                "[" + "".join(re.escape(symbol) for symbol in single_char_symbols) + "]"
            )
        return "(?:" + "|".join(alternates) + ")"
    return "[" + "".join(re.escape(symbol) for symbol in single_char_symbols) + "]"


def _currency_code_alternation(currency_codes: object) -> str:
    if not currency_codes:
        normalized_codes: list[object] | tuple[object, ...] | set[object] = []
    elif isinstance(currency_codes, str):
        normalized_codes = [currency_codes]
    elif isinstance(currency_codes, (list, tuple, set)):
        normalized_codes = currency_codes
    else:
        normalized_codes = [currency_codes]
    codes = sorted(
        {str(code).strip().upper() for code in normalized_codes if str(code).strip()}
    )
    if not codes:
        return r"[A-Z]{3}"
    return "(?:" + "|".join(re.escape(code) for code in codes) + ")"


def _expand_salary_range_regex(rules: dict[str, object]) -> str:
    raw_pattern = str(rules.get("salary_range_regex") or "").strip()
    if not raw_pattern:
        raw_pattern = (
            r"(?:(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?\s*\d[\d,.]*[kKmMbB]?\s*"
            r"(?:[-–—]|to|until)\s*(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?\s*"
            r"\d[\d,.]*[kKmMbB]?\s*(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?"
            r"(?:\s*/\s*[a-zA-Z]+)?|(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)\s*"
            r"\d[\d,.]*[kKmMbB]?(?:\s*(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__))?"
            r"(?:\s*/\s*[a-zA-Z]+)?|\d[\d,.]*[kKmMbB]?(?:\s*(?:__CURRENCY_SYMBOL_CLASS__|"
            r"__CURRENCY_CODE_ALT__))?(?:\s*/\s*[a-zA-Z]+)?)"
        )
    expanded = raw_pattern.replace(
        "__CURRENCY_SYMBOL_CLASS__",
        _currency_symbol_class(dict(rules.get("currency_symbol_map", {}))),
    ).replace(
        "__CURRENCY_CODE_ALT__",
        _currency_code_alternation(rules.get("currency_codes", [])),
    )
    return expanded if expanded.startswith("(?i)") else f"(?i){expanded}"


def canonical_fields(surface: str) -> list[str]:
    return list(CANONICAL_SCHEMAS.get(surface, []))


PERFORMANCE_PROFILES = {
    "ULTRA_FAST": {
        "browser_fallback_visible_text_min": 1000,
        "challenge_wait_max_seconds": 3,
        "origin_warm_pause_ms": 0,
        "surface_readiness_max_wait_ms": 3000,
    },
    "BALANCED": {
        "browser_fallback_visible_text_min": 500,
        "challenge_wait_max_seconds": 7,
        "origin_warm_pause_ms": 500,
        "surface_readiness_max_wait_ms": 6000,
    },
    "STEALTH": {
        "browser_fallback_visible_text_min": 200,
        "challenge_wait_max_seconds": 15,
        "origin_warm_pause_ms": 2000,
        "surface_readiness_max_wait_ms": 15000,
    },
}

DEFAULT_PROFILE = _TUNING.get("performance_profile", "BALANCED")
_P = PERFORMANCE_PROFILES.get(DEFAULT_PROFILE, PERFORMANCE_PROFILES["BALANCED"])

HTTP_TIMEOUT_SECONDS = _TUNING.get("http_timeout_seconds", 20)
ACQUISITION_ATTEMPT_TIMEOUT_SECONDS = _TUNING.get(
    "acquisition_attempt_timeout_seconds", 90
)
IMPERSONATION_TARGET = _TUNING.get("impersonation_target", "chrome131")
HTTP_IMPERSONATION_PROFILES = _TUNING.get(
    "http_impersonation_profiles", ["chrome110", "chrome116", "chrome123", "chrome131"]
)
HTTP_STEALTH_IMPERSONATION_PROFILE = _TUNING.get(
    "http_stealth_impersonation_profile", "chrome131"
)
SITE_POLICY_REGISTRY = _SITE_POLICY_REGISTRY
BROWSER_FIRST_DOMAINS = sorted(
    domain
    for domain, policy in SITE_POLICY_REGISTRY.items()
    if isinstance(policy, dict) and bool(policy.get("browser_first"))
)
PLATFORM_BROWSER_FIRST = set(_PLATFORM_BROWSER_POLICIES.get("browser_first", []))
KNOWN_ATS_PLATFORMS = list(_KNOWN_ATS_PLATFORMS)
BROWSER_FALLBACK_VISIBLE_TEXT_MIN = _TUNING.get(
    "browser_fallback_visible_text_min", _P["browser_fallback_visible_text_min"]
)
BROWSER_FALLBACK_VISIBLE_TEXT_RATIO_MAX = _TUNING.get(
    "browser_fallback_visible_text_ratio_max", 0.02
)
BROWSER_FALLBACK_HTML_SIZE_THRESHOLD = _TUNING.get(
    "browser_fallback_html_size_threshold", 200000
)
JS_GATE_PHRASES = _TUNING.get("js_gate_phrases", ["enable javascript", "<noscript>"])
DEFAULT_MAX_RECORDS = _TUNING.get("default_max_records", 100)
DEFAULT_SLEEP_MS = _TUNING.get("default_sleep_ms", 0)
MIN_REQUEST_DELAY_MS = _TUNING.get("min_request_delay_ms", 100)
DEFAULT_MAX_SCROLLS = _TUNING.get("default_max_scrolls", 10)
BATCH_URL_CONCURRENCY = _TUNING.get("batch_url_concurrency", 8)
WORKER_MAX_CONCURRENT_JOBS = _TUNING.get("worker_max_concurrent_jobs", 8)
WORKER_ORPHAN_RECOVERY_GRACE_SECONDS = max(
    _TUNING.get("worker_orphan_recovery_grace_seconds", 900), 60
)
# Minimum 60s grace period prevents premature job reclamation on transient delays
MAX_CANDIDATES_PER_FIELD = _TUNING.get("max_candidates_per_field", 5)
DYNAMIC_FIELD_NAME_MAX_TOKENS = _TUNING.get("dynamic_field_name_max_tokens", 7)
ACCORDION_EXPAND_MAX = _TUNING.get("accordion_expand_max", 20)
ACCORDION_EXPAND_WAIT_MS = _TUNING.get("accordion_expand_wait_ms", 500)
BLOCK_MIN_HTML_LENGTH = _TUNING.get("block_min_html_length", 100)
BLOCK_LOW_CONTENT_TEXT_MAX = _TUNING.get("block_low_content_text_max", 500)
BLOCK_LOW_CONTENT_SCRIPT_MIN = _TUNING.get("block_low_content_script_min", 3)
BLOCK_LOW_CONTENT_LINK_MAX = _TUNING.get("block_low_content_link_max", 3)
LISTING_MIN_ITEMS = _TUNING.get("listing_min_items", 2)
CARD_AUTODETECT_MIN_SIBLINGS = _TUNING.get("card_autodetect_min_siblings", 3)
JSON_MAX_SEARCH_DEPTH = _TUNING.get("json_max_search_depth", 5)
MAX_JSON_RECURSION_DEPTH = _TUNING.get("max_json_recursion_depth", 8)
HTTP_RETRY_STATUS_CODES = _TUNING.get("http_retry_status_codes", [403, 429, 503])
HTTP_MAX_RETRIES = _TUNING.get("http_max_retries", 2)
HTTP_RETRY_BACKOFF_BASE_MS = _TUNING.get("http_retry_backoff_base_ms", 400)
HTTP_RETRY_BACKOFF_MAX_MS = _TUNING.get("http_retry_backoff_max_ms", 3000)
PROXY_FAILURE_COOLDOWN_BASE_MS = _TUNING.get("proxy_failure_cooldown_base_ms", 1000)
PROXY_FAILURE_COOLDOWN_MAX_MS = _TUNING.get("proxy_failure_cooldown_max_ms", 15000)
DNS_RESOLUTION_RETRIES = _TUNING.get("dns_resolution_retries", 1)
DNS_RESOLUTION_RETRY_DELAY_MS = _TUNING.get("dns_resolution_retry_delay_ms", 250)
ACQUIRE_HOST_MIN_INTERVAL_MS = _TUNING.get("acquire_host_min_interval_ms", 250)
PACING_HOST_CACHE_MAX_ENTRIES = _TUNING.get("pacing_host_cache_max_entries", 1024)
PACING_HOST_CACHE_TTL_SECONDS = _TUNING.get("pacing_host_cache_ttl_seconds", 3600)
STEALTH_PREFER_TTL_HOURS = _TUNING.get("stealth_prefer_ttl_hours", 24)
CHALLENGE_WAIT_MAX_SECONDS = _TUNING.get(
    "challenge_wait_max_seconds", _P["challenge_wait_max_seconds"]
)
CHALLENGE_POLL_INTERVAL_MS = _TUNING.get("challenge_poll_interval_ms", 1000)
SURFACE_READINESS_MAX_WAIT_MS = _TUNING.get(
    "surface_readiness_max_wait_ms", _P["surface_readiness_max_wait_ms"]
)
SURFACE_READINESS_POLL_MS = _TUNING.get("surface_readiness_poll_ms", 500)
ORIGIN_WARM_PAUSE_MS = _TUNING.get("origin_warm_pause_ms", _P["origin_warm_pause_ms"])
BROWSER_ERROR_RETRY_ATTEMPTS = _TUNING.get("browser_error_retry_attempts", 1)
BROWSER_ERROR_RETRY_DELAY_MS = _TUNING.get("browser_error_retry_delay_ms", 1000)
BROWSER_NAVIGATION_NETWORKIDLE_TIMEOUT_MS = _TUNING.get(
    "browser_navigation_networkidle_timeout_ms", 30000
)
BROWSER_NAVIGATION_LOAD_TIMEOUT_MS = _TUNING.get(
    "browser_navigation_load_timeout_ms", 15000
)
BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS = _TUNING.get(
    "browser_navigation_domcontentloaded_timeout_ms", 15000
)
BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS = _TUNING.get(
    "browser_navigation_optimistic_wait_ms", 3000
)
INTERRUPTIBLE_WAIT_POLL_MS = _TUNING.get("interruptible_wait_poll_ms", 250)
PAGINATION_NAVIGATION_TIMEOUT_MS = _TUNING.get(
    "pagination_navigation_timeout_ms", 20000
)
LISTING_READINESS_MAX_WAIT_MS = _TUNING.get("listing_readiness_max_wait_ms", 12000)
LISTING_READINESS_POLL_MS = _TUNING.get("listing_readiness_poll_ms", 500)
SCROLL_WAIT_MIN_MS = _TUNING.get("scroll_wait_min_ms", 1500)
LOAD_MORE_WAIT_MIN_MS = _TUNING.get("load_more_wait_min_ms", 2000)
COOKIE_CONSENT_PREWAIT_MS = _TUNING.get("cookie_consent_prewait_ms", 400)
COOKIE_CONSENT_POSTCLICK_WAIT_MS = _TUNING.get("cookie_consent_postclick_wait_ms", 600)
SHADOW_DOM_FLATTEN_MAX_HOSTS = _TUNING.get("shadow_dom_flatten_max_hosts", 100)

if HTTP_RETRY_BACKOFF_BASE_MS < 0:
    raise ValueError("pipeline_tuning.py:http_retry_backoff_base_ms must be >= 0")
if HTTP_RETRY_BACKOFF_MAX_MS < HTTP_RETRY_BACKOFF_BASE_MS:
    raise ValueError(
        "pipeline_tuning.py:http_retry_backoff_max_ms must be >= http_retry_backoff_base_ms"
    )
if PROXY_FAILURE_COOLDOWN_BASE_MS < 0:
    raise ValueError("pipeline_tuning.py:proxy_failure_cooldown_base_ms must be >= 0")
if PROXY_FAILURE_COOLDOWN_MAX_MS < PROXY_FAILURE_COOLDOWN_BASE_MS:
    raise ValueError(
        "pipeline_tuning.py:proxy_failure_cooldown_max_ms must be >= proxy_failure_cooldown_base_ms"
    )

_FIELD_ALIASES_LEGACY = _EXTRACTION_RULES.get("field_aliases", {})
FIELD_ALIASES = {**_FIELD_ALIASES_LEGACY, **_FIELD_ALIASES_FILE}
DOM_PATTERNS = _EXTRACTION_RULES.get("dom_patterns", _DOM_PATTERNS)
CARD_SELECTORS_COMMERCE = _CARD_SELECTORS.get("ecommerce", [])
CARD_SELECTORS_JOBS = _CARD_SELECTORS.get("jobs", [])
PAGINATION_NEXT_SELECTORS = _PAGINATION_SELECTORS.get("next_page", [])
LOAD_MORE_SELECTORS = _PAGINATION_SELECTORS.get("load_more", [])
PLATFORM_LISTING_READINESS_SELECTORS = dict(_PLATFORM_LISTING_READINESS_SELECTORS)
PLATFORM_LISTING_READINESS_URL_PATTERNS = {
    str(platform_family): [list(group) for group in groups]
    for platform_family, groups in _PLATFORM_LISTING_READINESS_URL_PATTERNS.items()
}
PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES = dict(
    _PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES
)
PRICE_FIELDS = set(_NORM_RULES.get("price_fields", ["price", "sale_price"]))
PRICE_REGEX = _NORM_RULES.get("price_regex", r"\d[\d,.]*")
SALARY_FIELDS = set(_NORM_RULES.get("salary_fields", ["salary", "compensation"]))
SALARY_RANGE_REGEX = _expand_salary_range_regex(_NORM_RULES)
CURRENCY_CODES = set(_NORM_RULES.get("currency_codes", []))
CURRENCY_SYMBOL_MAP = dict(_NORM_RULES.get("currency_symbol_map", {}))
COLOR_NOISE_TOKENS = tuple(_NORM_RULES.get("color_noise_tokens", []))
SIZE_NOISE_TOKENS = tuple(_NORM_RULES.get("size_noise_tokens", []))
PAGE_URL_CURRENCY_HINTS = dict(_NORM_RULES.get("page_url_currency_hints", {}))
_NESTED_OBJECT_KEYS = _NORM_RULES.get("nested_object_keys", {})
NESTED_TEXT_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "text_fields",
        ["name", "label", "title", "text", "value", "content", "description", "alt"],
    )
)
NESTED_URL_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get("url_fields", ["href", "url", "link", "canonical_url"])
)
NESTED_PRICE_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "price_fields",
        [
            "specialValue",
            "currentValue",
            "special",
            "current",
            "price",
            "amount",
            "value",
            "lowPrice",
            "minPrice",
            "displayPrice",
            "formattedPrice",
        ],
    )
)
NESTED_ORIGINAL_PRICE_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "original_price_fields",
        [
            "compareAtPrice",
            "compare_at_price",
            "listPrice",
            "regularPrice",
            "wasPrice",
            "originalPrice",
            "maxPrice",
            "currentValue",
            "price",
        ],
    )
)
NESTED_CURRENCY_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "currency_fields",
        ["currency", "currencyCode", "priceCurrency", "currency_code"],
    )
)
NESTED_CATEGORY_KEYS = tuple(
    _NESTED_OBJECT_KEYS.get(
        "category_fields", ["name", "path", "pathEn", "breadcrumb", "categoryPath"]
    )
)
VERDICT_CORE_FIELDS_DETAIL = set(
    _VERDICT_RULES.get("detail_core_fields", ["title", "price", "brand"])
)
VERDICT_CORE_FIELDS_LISTING = set(_VERDICT_RULES.get("listing_core_fields", ["title"]))
REQUESTED_FIELD_ALIASES = _EXTRACTION_RULES.get(
    "requested_field_aliases", _REQUESTED_FIELD_ALIASES_FILE
)
_CANDIDATE_CLEANUP = _EXTRACTION_RULES.get("candidate_cleanup", {})
CANDIDATE_PLACEHOLDER_VALUES = set(
    _CANDIDATE_CLEANUP.get(
        "placeholder_values", ["-", "—", "--", "n/a", "na", "none", "null", "undefined"]
    )
)
CANDIDATE_GENERIC_CATEGORY_VALUES = set(
    _CANDIDATE_CLEANUP.get(
        "generic_category_values",
        ["detail-page", "detail_page", "product", "page", "pdp"],
    )
)
CANDIDATE_GENERIC_TITLE_VALUES = set(
    _CANDIDATE_CLEANUP.get(
        "generic_title_values", ["chrome", "firefox", "safari", "edge", "home"]
    )
)
CANDIDATE_TITLE_NOISE_TOKENS = tuple(_CANDIDATE_CLEANUP.get("title_noise_tokens", []))
GA_DATA_LAYER_KEYS = frozenset(_CANDIDATE_CLEANUP.get("ga_data_layer_keys", []))
_CANDIDATE_FIELD_GROUPS = _CANDIDATE_CLEANUP.get("field_groups", {})
CANDIDATE_FIELD_GROUPS = {
    str(group): {str(field) for field in fields}
    for group, fields in _CANDIDATE_FIELD_GROUPS.items()
    if isinstance(fields, list)
}
_CANDIDATE_FIELD_NAME_PATTERNS = _CANDIDATE_CLEANUP.get("field_name_patterns", {})
CANDIDATE_URL_SUFFIXES = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "url_suffixes", ["_url", "url", "_link", "link", "_href", "href"]
    )
)
CANDIDATE_IMAGE_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "image_tokens", ["image", "images", "gallery", "photo", "thumbnail", "hero"]
    )
)
CANDIDATE_CURRENCY_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get("currency_tokens", ["currency"])
)
CANDIDATE_PRICE_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get("price_tokens", ["price", "amount", "cost"])
)
CANDIDATE_SALARY_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "salary_tokens", ["salary", "pay", "rate", "compensation"]
    )
)
CANDIDATE_RATING_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get("rating_tokens", ["rating", "score"])
)
CANDIDATE_REVIEW_COUNT_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "review_count_tokens", ["review_count", "reviews", "rating_count"]
    )
)
CANDIDATE_AVAILABILITY_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get("availability_tokens", ["availability", "stock"])
)
CANDIDATE_CATEGORY_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "category_tokens", ["category", "department", "breadcrumb"]
    )
)
CANDIDATE_DESCRIPTION_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "description_tokens", ["description", "summary", "overview", "details"]
    )
)
CANDIDATE_IDENTIFIER_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "identifier_tokens", ["sku", "id", "code", "vin", "mpn"]
    )
)
CANDIDATE_UI_NOISE_PHRASES = tuple(_CANDIDATE_CLEANUP.get("ui_noise_phrases", []))
CANDIDATE_UI_NOISE_TOKEN_PATTERN = str(
    _CANDIDATE_CLEANUP.get("ui_noise_token_pattern", r"\b[a-z]+_[a-z0-9_]+\b")
)
CANDIDATE_UI_ICON_TOKEN_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "ui_icon_token_pattern",
        r"\b(corporate_fare|bar_chart|home_pin|location_on|travel_explore|business_center|storefront|schedule|payments|school|work|place)\b",
    )
)
CANDIDATE_SCRIPT_NOISE_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "script_noise_pattern",
        r"\b(?:imageloader|document\.getelementbyid|fallback-image)\b",
    )
)
CANDIDATE_PROMO_ONLY_TITLE_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "promo_only_title_pattern",
        r"^(?:[-–—]?\s*)?(?:\d{1,3}%\s*(?:off)?|sale|new(?:\s+in)?|view\s*\d+|best seller|top seller)\s*$",
    )
)
_DISCOVERED_FIELD_CLEANUP = _EXTRACTION_RULES.get("discovered_field_cleanup", {})
DISCOVERED_FIELD_NOISE_TOKENS = set(
    _DISCOVERED_FIELD_CLEANUP.get("field_noise_tokens", [])
)
DISCOVERED_VALUE_NOISE_PHRASES = tuple(
    _DISCOVERED_FIELD_CLEANUP.get("value_noise_phrases", [])
)
_LISTING_EXTRACTION_RULES = _EXTRACTION_RULES.get("listing_extraction", {})
LISTING_DETAIL_PATH_MARKERS = tuple(
    _LISTING_EXTRACTION_RULES.get("detail_path_markers", [])
)
LISTING_SWATCH_CONTAINER_SELECTORS = tuple(
    _LISTING_EXTRACTION_RULES.get("swatch_container_selectors", [])
)
LISTING_IMAGE_EXCLUDE_TOKENS = tuple(
    _LISTING_EXTRACTION_RULES.get("image_exclude_tokens", [])
)
LISTING_COLOR_ACTION_VALUES = frozenset(
    _LISTING_EXTRACTION_RULES.get("color_action_values", [])
)
LISTING_COLOR_ACTION_PREFIXES = tuple(
    _LISTING_EXTRACTION_RULES.get("color_action_prefixes", [])
)
LISTING_FILTER_OPTION_KEYS = frozenset(
    _LISTING_EXTRACTION_RULES.get("filter_option_keys", [])
)
LISTING_MINIMAL_VISUAL_FIELDS = frozenset(
    _LISTING_EXTRACTION_RULES.get("minimal_visual_fields", [])
)
LISTING_PRODUCT_SIGNAL_FIELDS = frozenset(
    _LISTING_EXTRACTION_RULES.get("product_signal_fields", [])
)
LISTING_JOB_SIGNAL_FIELDS = frozenset(
    _LISTING_EXTRACTION_RULES.get("job_signal_fields", [])
)
LISTING_NON_LISTING_PATH_TOKENS = frozenset(
    _LISTING_EXTRACTION_RULES.get("non_listing_path_tokens", [])
)
LISTING_HUB_PATH_SEGMENTS = frozenset(
    _LISTING_EXTRACTION_RULES.get("hub_path_segments", [])
)
LISTING_WEAK_METADATA_FIELDS = frozenset(
    _LISTING_EXTRACTION_RULES.get("weak_metadata_fields", [])
)
LISTING_FACET_QUERY_KEYS = frozenset(
    _LISTING_EXTRACTION_RULES.get("facet_query_keys", [])
)
LISTING_FACET_PATH_FRAGMENTS = tuple(
    _LISTING_EXTRACTION_RULES.get("facet_path_fragments", [])
)
LISTING_CATEGORY_PATH_MARKERS = frozenset(
    _LISTING_EXTRACTION_RULES.get("category_path_markers", [])
)
_ACQUISITION_GUARDS = _EXTRACTION_RULES.get("acquisition_guards", {})
JOB_REDIRECT_SHELL_TITLES = frozenset(
    _ACQUISITION_GUARDS.get("job_redirect_shell_titles", [])
)
JOB_REDIRECT_SHELL_CANONICAL_URLS = frozenset(
    _ACQUISITION_GUARDS.get("job_redirect_shell_canonical_urls", [])
)
JOB_REDIRECT_SHELL_HEADINGS = frozenset(
    _ACQUISITION_GUARDS.get("job_redirect_shell_headings", [])
)
JOB_ERROR_PAGE_TITLES = frozenset(_ACQUISITION_GUARDS.get("job_error_page_titles", []))
JOB_ERROR_PAGE_HEADINGS = frozenset(
    _ACQUISITION_GUARDS.get("job_error_page_headings", [])
)
_SEMANTIC_DETAIL_RULES = _EXTRACTION_RULES.get("semantic_detail", {})
SECTION_SKIP_PATTERNS = tuple(
    _SEMANTIC_DETAIL_RULES.get(
        "section_skip_patterns",
        ["add to cart", "buy now", "checkout", "login", "sign in", "subscribe"],
    )
)
SECTION_ANCESTOR_STOP_TAGS = set(
    _SEMANTIC_DETAIL_RULES.get(
        "section_ancestor_stop_tags", ["footer", "header", "nav", "aside", "form"]
    )
)
SECTION_ANCESTOR_STOP_TOKENS = set(
    _SEMANTIC_DETAIL_RULES.get(
        "section_ancestor_stop_tokens",
        [
            "footer",
            "header",
            "nav",
            "menu",
            "newsletter",
            "breadcrumbs",
            "breadcrumb",
            "cookie",
            "consent",
        ],
    )
)
SPEC_LABEL_BLOCK_PATTERNS = tuple(
    _SEMANTIC_DETAIL_RULES.get(
        "spec_label_block_patterns",
        [
            "play video",
            "watch video",
            "video",
            "learn more",
            "add to cart",
            "buy now",
            "primary guide",
            "guide",
            "discount",
        ],
    )
)
SPEC_DROP_LABELS = set(
    _SEMANTIC_DETAIL_RULES.get("spec_drop_labels", ["qty", "quantity", "details"])
)
FEATURE_SECTION_ALIASES = set(
    _SEMANTIC_DETAIL_RULES.get(
        "feature_section_aliases",
        ["features", "feature", "highlights", "key_features", "key features"],
    )
)
DIMENSION_KEYWORDS = tuple(
    _SEMANTIC_DETAIL_RULES.get(
        "dimension_keywords",
        [
            "width",
            "height",
            "depth",
            "length",
            "diameter",
            "weight",
            "dimensions",
            "size",
            "measurement",
            "measurements",
        ],
    )
)
SEMANTIC_AGGREGATE_SEPARATOR = str(
    _SEMANTIC_DETAIL_RULES.get("aggregate_separator", " | ")
)
HYDRATED_STATE_PATTERNS = list(_HYDRATED_STATE_PATTERNS)
_BLOCK_SIG = BLOCK_SIGNATURES
BLOCK_PHRASES = _BLOCK_SIG.get("phrases", [])
PROVIDER_MARKERS = _BLOCK_SIG.get("provider_markers", [])
BLOCK_ACTIVE_PROVIDER_MARKERS = _BLOCK_SIG.get("active_provider_markers", [])
BLOCK_CDN_PROVIDER_MARKERS = _BLOCK_SIG.get("cdn_provider_markers", [])
BLOCK_BROWSER_CHALLENGE_STRONG_MARKERS = _BLOCK_SIG.get(
    "browser_challenge_strong_markers", {}
)
BLOCK_BROWSER_CHALLENGE_WEAK_MARKERS = _BLOCK_SIG.get(
    "browser_challenge_weak_markers", {}
)
BLOCK_TITLE_REGEXES = _BLOCK_SIG.get("title_regexes", [])
COOKIE_CONSENT_SELECTORS = list(_CONSENT_SELECTORS)
COOKIE_POLICY = dict(_COOKIE_POLICY)
REVIEW_CONTAINER_KEYS = set(_REVIEW_CONTAINER_KEYS)
MARKDOWN_VIEW = dict(_MARKDOWN_VIEW)
DISCOVERIST_SCHEMA = tuple(_DISCOVERIST_SCHEMA)
JSONLD_STRUCTURAL_KEYS = frozenset(
    _EXTRACTION_RULES.get(
        "jsonld_structural_keys",
        ["@type", "@context", "@id", "@graph", "@vocab", "@list", "@set"],
    )
)
JSONLD_NON_PRODUCT_BLOCK_TYPES = frozenset(
    _EXTRACTION_RULES.get(
        "jsonld_non_product_block_types",
        [
            "organization",
            "website",
            "webpage",
            "breadcrumblist",
            "searchaction",
            "sitenavigationelement",
            "imageobject",
            "videoobject",
            "faqpage",
            "howto",
            "person",
            "localbusiness",
            "store",
        ],
    )
)
PRODUCT_IDENTITY_FIELDS = frozenset(
    _EXTRACTION_RULES.get(
        "product_identity_fields",
        [
            "title",
            "price",
            "sale_price",
            "original_price",
            "brand",
            "description",
            "sku",
            "image_url",
            "additional_images",
            "availability",
            "category",
        ],
    )
)
NESTED_NON_PRODUCT_KEYS = frozenset(
    _EXTRACTION_RULES.get(
        "nested_non_product_keys",
        [
            "review",
            "reviews",
            "aggregaterating",
            "aggregate_rating",
            "author",
            "publisher",
            "creator",
            "contributor",
            "breadcrumb",
            "breadcrumblist",
            "itemlistelement",
            "potentialaction",
            "mainentityofpage",
        ],
    )
)
JSONLD_TYPE_NOISE = set(_EXTRACTION_RULES.get("jsonld_type_noise", []))
DYNAMIC_FIELD_NAME_DROP_TOKENS = set(
    _EXTRACTION_RULES.get("dynamic_field_name_drop_tokens", [])
)
SOURCE_RANKING = _EXTRACTION_RULES.get("source_ranking", {})
FIELD_POLLUTION_RULES = _EXTRACTION_RULES.get("field_pollution_rules", {})
LLM_HTML_SNIPPET_MAX_CHARS = _LLM_TUNING.get("html_snippet_max_chars", 12000)
LLM_EXISTING_VALUES_MAX_CHARS = _LLM_TUNING.get("existing_values_max_chars", 2400)
LLM_CANDIDATE_EVIDENCE_MAX_CHARS = _LLM_TUNING.get(
    "candidate_evidence_max_chars", 16000
)
LLM_DISCOVERED_SOURCES_MAX_CHARS = _LLM_TUNING.get(
    "discovered_sources_max_chars", 15000
)
LLM_CLEAN_CANDIDATE_TEXT_LIMIT = _LLM_TUNING.get("clean_candidate_text_limit", 1200)
LLM_GROQ_MAX_TOKENS = _LLM_TUNING.get("groq_max_tokens", 1200)
LLM_GROQ_TEMPERATURE = _LLM_TUNING.get("groq_temperature", 0.1)
LLM_ANTHROPIC_MAX_TOKENS = _LLM_TUNING.get("anthropic_max_tokens", 3000)
LLM_ANTHROPIC_TEMPERATURE = _LLM_TUNING.get("anthropic_temperature", 0.1)
LLM_NVIDIA_MAX_TOKENS = _LLM_TUNING.get("nvidia_max_tokens", 1200)
LLM_NVIDIA_TEMPERATURE = _LLM_TUNING.get("nvidia_temperature", 0.1)
_NOISE = _EXTRACTION_RULES.get("listing_noise_filters", {})
LISTING_NAVIGATION_TITLE_HINTS = frozenset(_NOISE.get("navigation_title_hints", []))
LISTING_MERCHANDISING_TITLE_PREFIXES = tuple(
    _NOISE.get("merchandising_title_prefixes", [])
)
LISTING_EDITORIAL_TITLE_PATTERNS = _compile_extraction_rule_patterns(
    _NOISE.get("editorial_title_patterns", []),
    setting_name="listing_noise_filters.editorial_title_patterns",
)
LISTING_ALT_TEXT_TITLE_PATTERN = (
    _compile_extraction_rule_pattern(
        _NOISE["alt_text_title_pattern"],
        setting_name="listing_noise_filters.alt_text_title_pattern",
    )
    if _NOISE.get("alt_text_title_pattern")
    else None
)
LISTING_WEAK_TITLES = frozenset(_NOISE.get("weak_listing_titles", []))
