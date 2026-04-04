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

# Acquisition
HTTP_TIMEOUT_SECONDS: int = _TUNING.get("http_timeout_seconds", 20)
IMPERSONATION_TARGET: str = _TUNING.get("impersonation_target", "chrome110")
BROWSER_FALLBACK_VISIBLE_TEXT_MIN: int = _TUNING.get("browser_fallback_visible_text_min", 500)
JS_GATE_PHRASES: list[str] = _TUNING.get("js_gate_phrases", [
    "enable javascript",
    "<noscript>",
])
DEFAULT_MAX_RECORDS: int = _TUNING.get("default_max_records", 100)
DEFAULT_SLEEP_MS: int = _TUNING.get("default_sleep_ms", 0)
MIN_REQUEST_DELAY_MS: int = _TUNING.get("min_request_delay_ms", 100)

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
MAX_JSON_RECURSION_DEPTH: int = _TUNING.get("max_json_recursion_depth", 4)

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
ORIGIN_WARM_PAUSE_MS: int = _TUNING.get("origin_warm_pause_ms", 2000)
BROWSER_ERROR_RETRY_ATTEMPTS: int = _TUNING.get("browser_error_retry_attempts", 1)
BROWSER_ERROR_RETRY_DELAY_MS: int = _TUNING.get("browser_error_retry_delay_ms", 1000)

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

CARD_SELECTORS_COMMERCE: list[str] = _CARD_SELECTORS.get("ecommerce", [])
CARD_SELECTORS_JOBS: list[str] = _CARD_SELECTORS.get("jobs", [])


# ---------------------------------------------------------------------------
# 7. Normalization rules — loaded from normalization_rules.json
#    Field-specific normalization behavior (e.g., price fields get numeric
#    extraction).  Users can add new price-like fields or change the regex.
# ---------------------------------------------------------------------------

_NORM_RULES: dict = _load("normalization_rules.json", {})  # type: ignore[assignment]

PRICE_FIELDS: set[str] = set(_NORM_RULES.get("price_fields", ["price", "sale_price"]))
PRICE_REGEX: str = _NORM_RULES.get("price_regex", r"\d[\d,.]*")


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

if not COOKIE_CONSENT_SELECTORS:
    COOKIE_CONSENT_SELECTORS = [
        "button#onetrust-accept-btn-handler",
        "button#CybotCookiebotDialogBodyUnderlayAccept",
        "[aria-label='Accept Cookies']",
        "[aria-label='Accept all']",
        "button:has-text('Accept All')",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept')",
        "button:has-text('I Accept')",
        "button:has-text('Agree')",
        ".cookie-consent-accept",
        "#cookieConsentAccept",
        ".fc-button.fc-cta-accept",
        ".fc-primary-button",
    ]


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
