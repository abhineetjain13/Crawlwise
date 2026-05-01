from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_DIR = Path(__file__).resolve().parents[3]
_ENV_FILES = (str(_BACKEND_DIR.parent / ".env"), str(_BACKEND_DIR / ".env"))


def _settings_config(*, env_prefix: str) -> SettingsConfigDict:
    return SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix=env_prefix,
    )


PERFORMANCE_PROFILES: dict[str, dict[str, int]] = {
    "ULTRA_FAST": {
        "browser_fallback_visible_text_min": 1000,
        "challenge_wait_max_seconds": 3,
        "origin_warm_pause_ms": 0,
        "surface_readiness_max_wait_ms": 3000,
    },
    "BALANCED": {
        "browser_fallback_visible_text_min": 500,
        "challenge_wait_max_seconds": 15,
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
_PROFILE_CONTROLLED_FIELDS = (
    "browser_fallback_visible_text_min",
    "challenge_wait_max_seconds",
    "origin_warm_pause_ms",
    "surface_readiness_max_wait_ms",
)


def _coerce_float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value))


def _require_positive(name: str, value: object) -> None:
    if _coerce_float(value) <= 0:
        raise ValueError(f"{name} must be > 0")


def _require_non_negative(name: str, value: object) -> None:
    if _coerce_float(value) < 0:
        raise ValueError(f"{name} must be >= 0")


def _require_unit_interval(name: str, value: object) -> None:
    if not 0.0 <= _coerce_float(value) <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


class CrawlerRuntimeSettings(BaseSettings):
    """Typed env-backed runtime settings for acquisition, browser, and crawl flow."""

    model_config = _settings_config(env_prefix="CRAWLER_RUNTIME_")

    performance_profile: Literal["ULTRA_FAST", "BALANCED", "STEALTH"] = "BALANCED"
    http_timeout_seconds: int = 20
    acquisition_attempt_timeout_seconds: int = 90
    curl_impersonate_target: str = "chrome131"
    force_httpx: bool = False
    http_user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    browser_fallback_visible_text_min: int | None = 500
    browser_fallback_visible_text_ratio_max: float = 0.02
    browser_fallback_html_size_threshold: int = 200000
    js_gate_phrases: list[str] = Field(
        default_factory=lambda: ["enable javascript", "<noscript>"]
    )
    default_max_records: int = 100
    default_max_pages: int = 5
    min_max_pages: int = 1
    max_max_pages: int = 20
    default_sleep_ms: int = 0
    min_request_delay_ms: int = 100
    default_max_scrolls: int = 10
    schema_max_age_days: int = 30
    listing_fallback_fragment_limit: int = 200
    auto_detect_surface: bool = False
    batch_url_concurrency: int = 8
    url_batch_concurrency: int = 4
    url_process_timeout_seconds: float = 90.0
    url_process_timeout_buffer_seconds: float = 15.0
    max_url_process_timeout_seconds: float = 600.0
    worker_max_concurrent_jobs: int = 8
    worker_orphan_recovery_grace_seconds: int = 900
    long_run_threshold_seconds: int = 30 * 60
    max_duration_sample_size: int = 1000
    stalled_run_threshold_seconds: int = 2 * 60
    records_read_retry_attempts: int = 1
    records_read_retry_delay_ms: int = 150
    max_candidates_per_field: int = 5
    dynamic_field_name_max_tokens: int = 7
    accordion_expand_max: int = 20
    accordion_expand_wait_ms: int = 500
    detail_expand_max_interactions: int = 6
    detail_expand_click_timeout_ms: int = 1000
    detail_expand_visibility_timeout_ms: int = 250
    block_min_html_length: int = 100
    block_low_content_text_max: int = 500
    block_low_content_script_min: int = 3
    block_low_content_link_max: int = 3
    listing_min_items: int = 2
    card_autodetect_min_siblings: int = 3
    json_max_search_depth: int = 5
    max_json_recursion_depth: int = 8
    js_shell_min_content_len: int = 100000
    js_shell_visible_ratio_max: float = 0.15
    js_shell_min_script_count: int = 2
    detail_field_signal_min_count: int = 2
    network_payload_signature_min_match: int = 3
    structured_source_generic_assignment_max_script_chars: int = 250000
    structured_source_generic_assignment_max_matches_per_script: int = 24
    http_retry_status_codes: list[int] = Field(
        default_factory=lambda: [403, 429, 502, 503, 504]
    )
    http_max_retries: int = 2
    http_retry_backoff_base_ms: int = 400
    http_retry_backoff_max_ms: int = 3000
    proxy_failure_cooldown_base_ms: int = 1000
    proxy_failure_cooldown_max_ms: int = 15000
    proxy_failure_backoff_max_exponent: int = 8
    proxy_failure_state_ttl_seconds: int = 3600
    proxy_failure_state_max_entries: int = 1024
    dns_resolution_retries: int = 1
    dns_resolution_retry_delay_ms: int = 250
    network_address_family_preference: Literal["auto", "ipv4", "ipv6"] = "auto"
    acquire_host_min_interval_ms: int = 250
    protected_host_additional_interval_ms: int = 2000
    pacing_host_cache_max_entries: int = 1024
    pacing_host_cache_ttl_seconds: int = 3600
    browser_first_host_block_threshold: int = 2
    stealth_prefer_ttl_hours: int = 24
    challenge_wait_max_seconds: int | None = 15
    challenge_poll_interval_ms: int = 1000
    challenge_activity_mouse_steps: int = 12
    challenge_activity_edge_padding_px: int = 48
    challenge_activity_jitter_moves: int = 4
    challenge_activity_jitter_delta_px: int = 100
    challenge_activity_pause_min_ms: int = 50
    challenge_activity_pause_jitter_ms: int = 150
    challenge_activity_scroll_px: int = 120
    browser_behavior_realism_enabled: bool = True
    browser_behavior_real_chrome_only: bool = True
    browser_behavior_scroll_steps: int = 3
    browser_behavior_scroll_min_px: int = 90
    browser_behavior_scroll_max_px: int = 260
    browser_behavior_pause_min_ms: int = 80
    browser_behavior_pause_jitter_ms: int = 220
    browser_behavior_typing_min_delay_ms: int = 35
    browser_behavior_typing_jitter_ms: int = 95
    surface_readiness_max_wait_ms: int | None = 6000
    surface_readiness_poll_ms: int = 250
    origin_warm_pause_ms: int | None = 500
    browser_error_retry_attempts: int = 1
    browser_error_retry_delay_ms: int = 1000
    browser_post_block_cooldown_ms: int = 500
    low_quality_browser_retry_methods: tuple[str, ...] = ("curl_cffi", "httpx")
    browser_navigation_networkidle_timeout_ms: int = 30000
    browser_navigation_load_timeout_ms: int = 15000
    browser_navigation_domcontentloaded_timeout_ms: int = 15000
    browser_navigation_optimistic_wait_ms: int = 3000
    browser_spa_implicit_networkidle_timeout_ms: int = 6000
    browser_navigation_min_commit_wait_ms: int = 8000
    browser_navigation_min_final_commit_timeout_ms: int = 15000
    browser_capture_max_network_payloads: int = 25
    browser_capture_max_network_payload_bytes: int = 3000000
    browser_capture_total_network_payload_bytes: int = 12000000
    browser_capture_read_timeout_seconds: float = 5.0
    browser_accessibility_snapshot_timeout_seconds: float = 0.5
    browser_capture_queue_join_timeout_ms: int = 2000
    browser_artifact_capture_timeout_ms: int = 4000
    crawl_event_counter_ttl_seconds: int = 86400
    browser_first_nav_pause_ms: int = 0
    platform_detection_html_search_limit: int = 500000
    browser_real_chrome_enabled: bool = True
    browser_real_chrome_executable_path: str = ""
    browser_real_chrome_force_headful: bool = True
    browser_real_chrome_native_context: bool = True
    browser_patchright_enabled: bool = True
    browser_launch_args: tuple[str, ...] = (
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
    )
    browser_use_new_headless: bool = True
    browser_runtime_pool_max_entries: int = 8
    browser_runtime_pool_idle_ttl_seconds: int = 300
    browser_proxy_bridge_connect_timeout_seconds: float = 10.0
    browser_proxy_bridge_auth_timeout_seconds: float = 10.0
    browser_proxy_bridge_first_byte_timeout_seconds: float = 15.0
    browser_proxy_domain_storage_enabled: bool = False
    browser_http_handoff_enabled: bool = True
    browser_http_handoff_cookie_engines: tuple[str, ...] = (
        "real_chrome",
        "patchright",
    )
    proxy_rotation_sticky_tokens: tuple[str, ...] = ("sticky", "session", "affinity")
    proxy_rotation_rotating_tokens: tuple[str, ...] = ("rotating", "rotate", "random")
    proxy_sticky_username_markers: tuple[str, ...] = ("-session-", "session-")
    proxy_session_rewrite_enabled_keys: tuple[str, ...] = (
        "session_rewrite_enabled",
        "sessionize_per_run",
    )
    browser_context_permissions: tuple[str, ...] = ("geolocation",)
    browser_mask_playwright_globals: tuple[str, ...] = (
        "__pwInitScripts",
        "__playwright__binding__",
        "_playwrightInstance",
    )
    browser_disable_web_workers: bool = True
    browser_mask_webrtc_local_ips: bool = True
    browser_connection_effective_type: Literal["slow-2g", "2g", "3g", "4g"] = "4g"
    browser_connection_downlink_mbps: float = 4.5
    browser_connection_downlink_max_mbps: float = 10.0
    browser_connection_rtt_ms: int = 75
    browser_connection_type: str = "wifi"
    browser_connection_save_data: bool = False
    browser_mobile_max_touch_points: int = 5
    browser_permission_notifications_state: Literal["granted", "denied", "prompt"] = "prompt"
    browser_permission_camera_state: Literal["granted", "denied", "prompt"] = "prompt"
    browser_permission_microphone_state: Literal["granted", "denied", "prompt"] = "prompt"
    browser_permission_geolocation_state: Literal["granted", "denied", "prompt"] = "prompt"
    fingerprint_browser: str = "chrome"
    fingerprint_os: tuple[str, ...] = ("windows", "macos", "linux")
    fingerprint_device: str = "desktop"
    fingerprint_locale: str = "en-US"
    fingerprint_color_scheme: str = "dark"
    fingerprint_timezone_id: str = ""
    fingerprint_locale_auto_align_timezone_region: bool = True
    fingerprint_hardware_concurrency: int = 0
    fingerprint_device_memory_gb: float = 0.0
    browser_identity_min_chrome_version: int = 120
    browser_identity_cache_max_entries: int = 1024
    browser_identity_cache_ttl_seconds: int = 3600
    browser_desktop_viewport_reserved_height_px: int = 100
    browser_desktop_window_frame_width_px: int = 16
    browser_desktop_window_frame_height_px: int = 88
    browser_readiness_visible_text_min: int = 120
    interruptible_wait_poll_ms: int = 250
    cooperative_sleep_poll_ms: int = 250
    selector_regex_timeout_seconds: float = 0.05
    browser_shutdown_timeout_seconds: float = 10.0
    traversal_locator_visible_timeout_ms: int = 250
    traversal_scroll_into_view_timeout_ms: int = 2000
    traversal_cookie_consent_visible_timeout_ms: int = 200
    traversal_cookie_consent_click_timeout_ms: int = 1000
    pagination_navigation_timeout_ms: int = 20000
    pagination_page_size_anomaly_ratio: int = 5
    pagination_post_click_timeout_ms: int = 1500
    pagination_post_click_domcontentloaded_timeout_ms: int = 5000
    pagination_post_click_poll_ms: int = 250
    pagination_post_click_settle_timeout_ms: int = 3000
    listing_readiness_max_wait_ms: int = 6000
    listing_readiness_poll_ms: int = 500
    detail_expand_max_elapsed_ms: int = 2500
    detail_expand_max_per_selector: int = 4
    detail_aom_expand_max_interactions: int = 6
    detail_aom_expand_max_elapsed_ms: int = 1500
    scroll_wait_min_ms: int = 1500
    load_more_wait_min_ms: int = 2000
    traversal_max_iterations_cap: int = 50
    traversal_fragment_max_bytes: int = 200000
    traversal_min_settle_wait_ms: int = 500
    traversal_settle_networkidle_timeout_ms: int = 4000
    traversal_weak_progress_streak_max: int = 2
    listing_recovery_enabled: bool = True
    listing_recovery_min_records_threshold: int = 5
    listing_recovery_min_populated_fields_per_record: float = 3.0
    listing_recovery_max_actions: int = 3
    listing_recovery_post_action_wait_ms: int = 1500
    rendered_listing_card_capture_limit: int = 48
    traversal_active_scrollable_threshold_px: int = 150
    traversal_active_scrollable_bonus: int = 10
    traversal_active_link_weight: int = 2
    traversal_active_target_label_max_len: int = 120
    traversal_click_timeout_ms: int = 3000
    traversal_force_probe_min_advance_px: int = 600
    infinite_scroll_container_overflow_threshold_px: int = 500
    infinite_scroll_tall_page_ratio: int = 3
    infinite_scroll_positive_signal_min: int = 2
    cookie_consent_prewait_ms: int = 400
    cookie_consent_postclick_wait_ms: int = 600
    shadow_dom_flatten_max_hosts: int = 100
    browser_context_timeout_ms: int = 15000
    browser_new_page_timeout_ms: int = 10000
    browser_close_timeout_ms: int = 5000
    browser_render_timeout_seconds: float = 30.0
    browser_max_contexts_before_recycle: int = 200
    browser_max_lifetime_seconds: int = 1800
    iframe_promotion_max_candidates: int = 2
    browser_preference_min_successes: int = 2
    acquisition_artifact_ttl_seconds: int = 86400
    acquisition_artifact_cleanup_interval_seconds: int = 300
    llm_direct_record_extraction_min_records: int = 3
    llm_direct_record_extraction_min_populated_fields_per_record: float = 3.0
    llm_confidence_threshold: float = 0.55
    selector_self_heal_enabled: bool = False
    selector_self_heal_min_confidence: float = 0.55
    selector_self_heal_cache_enabled: bool = False
    selector_synthesis_max_html_chars: int = 200000
    raw_json_surface_field_overlap_ratio: float = 0.25
    raw_json_surface_field_overlap_absolute: int = 2
    low_quality_browser_retry_min_remaining_seconds: float = 85.0
    acquisition_contract_stale_failure_threshold: int = 2
    detail_max_variant_axes: int = 3
    detail_max_variant_rows: int = 100
    detail_max_variant_matrix_cells: int = 200
    listing_candidate_strong_score_threshold: int = 18
    robots_cache_size: int = 512
    robots_cache_ttl: float = 3600.0
    robots_fetch_user_agent: str = "CrawlerAI"

    @model_validator(mode="after")
    def _apply_profile_defaults(self) -> CrawlerRuntimeSettings:
        explicitly_set = set(self.model_fields_set)
        profile = PERFORMANCE_PROFILES.get(
            self.performance_profile, PERFORMANCE_PROFILES["BALANCED"]
        )
        for field_name in _PROFILE_CONTROLLED_FIELDS:
            if (
                self.performance_profile != "BALANCED"
                and field_name not in explicitly_set
            ) or getattr(self, field_name) is None:
                setattr(self, field_name, profile[field_name])

        self.worker_orphan_recovery_grace_seconds = max(
            int(self.worker_orphan_recovery_grace_seconds), 60
        )
        if self.max_url_process_timeout_seconds < self.url_process_timeout_seconds:
            raise ValueError(
                "max_url_process_timeout_seconds must be >= url_process_timeout_seconds"
            )
        _require_non_negative("http_retry_backoff_base_ms", self.http_retry_backoff_base_ms)
        if self.http_retry_backoff_max_ms < self.http_retry_backoff_base_ms:
            raise ValueError(
                "http_retry_backoff_max_ms must be >= http_retry_backoff_base_ms"
            )
        _require_non_negative(
            "proxy_failure_cooldown_base_ms",
            self.proxy_failure_cooldown_base_ms,
        )
        if self.proxy_failure_cooldown_max_ms < self.proxy_failure_cooldown_base_ms:
            raise ValueError(
                "proxy_failure_cooldown_max_ms must be >= proxy_failure_cooldown_base_ms"
            )
        if self.min_max_pages < 1:
            self.min_max_pages = 1
        if self.max_max_pages < self.min_max_pages:
            self.max_max_pages = self.min_max_pages
        for field_name in (
            "url_process_timeout_seconds",
            "max_url_process_timeout_seconds",
            "browser_render_timeout_seconds",
            "browser_capture_max_network_payloads",
            "browser_capture_max_network_payload_bytes",
            "browser_capture_total_network_payload_bytes",
            "browser_capture_read_timeout_seconds",
            "browser_capture_queue_join_timeout_ms",
            "browser_artifact_capture_timeout_ms",
        ):
            _require_positive(field_name, getattr(self, field_name))
        for field_name in (
            "url_process_timeout_buffer_seconds",
            "browser_post_block_cooldown_ms",
            "browser_first_nav_pause_ms",
            "browser_accessibility_snapshot_timeout_seconds",
        ):
            _require_non_negative(field_name, getattr(self, field_name))
        self.browser_behavior_scroll_steps = max(
            0, int(self.browser_behavior_scroll_steps)
        )
        self.browser_behavior_scroll_min_px = max(
            0, int(self.browser_behavior_scroll_min_px)
        )
        self.browser_behavior_scroll_max_px = max(
            self.browser_behavior_scroll_min_px,
            int(self.browser_behavior_scroll_max_px),
        )
        self.browser_behavior_pause_min_ms = max(
            0, int(self.browser_behavior_pause_min_ms)
        )
        self.browser_behavior_pause_jitter_ms = max(
            0, int(self.browser_behavior_pause_jitter_ms)
        )
        self.browser_behavior_typing_min_delay_ms = max(
            0, int(self.browser_behavior_typing_min_delay_ms)
        )
        self.browser_behavior_typing_jitter_ms = max(
            0, int(self.browser_behavior_typing_jitter_ms)
        )
        for field_name in (
            "platform_detection_html_search_limit",
            "browser_runtime_pool_max_entries",
            "browser_proxy_bridge_connect_timeout_seconds",
            "browser_proxy_bridge_auth_timeout_seconds",
            "browser_proxy_bridge_first_byte_timeout_seconds",
            "browser_identity_min_chrome_version",
        ):
            _require_positive(field_name, getattr(self, field_name))
        _require_non_negative(
            "browser_runtime_pool_idle_ttl_seconds",
            self.browser_runtime_pool_idle_ttl_seconds,
        )
        if (
            self.browser_capture_total_network_payload_bytes
            < self.browser_capture_max_network_payload_bytes
        ):
            raise ValueError(
                "browser_capture_total_network_payload_bytes must be >= browser_capture_max_network_payload_bytes"
            )
        for field_name in (
            "acquisition_artifact_ttl_seconds",
            "acquisition_artifact_cleanup_interval_seconds",
        ):
            _require_non_negative(field_name, getattr(self, field_name))
        _require_unit_interval("llm_confidence_threshold", self.llm_confidence_threshold)
        _require_unit_interval(
            "selector_self_heal_min_confidence",
            self.selector_self_heal_min_confidence,
        )
        for field_name in (
            "detail_max_variant_axes",
            "detail_max_variant_rows",
            "detail_max_variant_matrix_cells",
        ):
            _require_positive(field_name, getattr(self, field_name))
        return self

    def coerce_url_timeout_seconds(self, value: object) -> float:
        try:
            timeout = float(str(value))
        except (TypeError, ValueError):
            return float(self.url_process_timeout_seconds)
        if timeout <= 0:
            return float(self.url_process_timeout_seconds)
        return min(timeout, float(self.max_url_process_timeout_seconds))

    def default_url_process_timeout_seconds(self) -> float:
        timeout = self.coerce_url_timeout_seconds(self.url_process_timeout_seconds)
        acquisition_timeout = max(0.0, float(self.acquisition_attempt_timeout_seconds))
        buffer_seconds = max(0.0, float(self.url_process_timeout_buffer_seconds))
        if acquisition_timeout <= 0:
            return timeout
        return min(
            max(timeout, acquisition_timeout + buffer_seconds),
            float(self.max_url_process_timeout_seconds),
        )



crawler_runtime_settings = CrawlerRuntimeSettings()


def proxy_rotation_mode(proxy_profile: dict[str, object] | None) -> str | None:
    if not isinstance(proxy_profile, dict):
        return None
    normalized = str(proxy_profile.get("rotation") or "").strip().lower()
    if not normalized:
        return None
    if normalized in set(crawler_runtime_settings.proxy_rotation_sticky_tokens or ()):
        return "sticky"
    if normalized in set(crawler_runtime_settings.proxy_rotation_rotating_tokens or ()):
        return "rotating"
    return normalized
