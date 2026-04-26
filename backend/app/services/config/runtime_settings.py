from __future__ import annotations

import json
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
    surface_readiness_max_wait_ms: int | None = 6000
    surface_readiness_poll_ms: int = 250
    origin_warm_pause_ms: int | None = 500
    browser_error_retry_attempts: int = 1
    browser_error_retry_delay_ms: int = 1000
    browser_post_block_cooldown_ms: int = 500
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
    browser_capture_queue_join_timeout_ms: int = 2000
    browser_artifact_capture_timeout_ms: int = 4000
    browser_first_nav_pause_ms: int = 0
    platform_detection_html_search_limit: int = 500000
    browser_real_chrome_enabled: bool = True
    browser_real_chrome_executable_path: str = ""
    browser_real_chrome_force_headful: bool = True
    browser_real_chrome_native_context: bool = True
    browser_real_chrome_apply_stealth: bool = False
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
        if self.http_retry_backoff_base_ms < 0:
            raise ValueError("http_retry_backoff_base_ms must be >= 0")
        if self.http_retry_backoff_max_ms < self.http_retry_backoff_base_ms:
            raise ValueError(
                "http_retry_backoff_max_ms must be >= http_retry_backoff_base_ms"
            )
        if self.proxy_failure_cooldown_base_ms < 0:
            raise ValueError("proxy_failure_cooldown_base_ms must be >= 0")
        if self.proxy_failure_cooldown_max_ms < self.proxy_failure_cooldown_base_ms:
            raise ValueError(
                "proxy_failure_cooldown_max_ms must be >= proxy_failure_cooldown_base_ms"
            )
        if self.min_max_pages < 1:
            self.min_max_pages = 1
        if self.max_max_pages < self.min_max_pages:
            self.max_max_pages = self.min_max_pages
        if self.url_process_timeout_seconds <= 0:
            raise ValueError("url_process_timeout_seconds must be > 0")
        if self.url_process_timeout_buffer_seconds < 0:
            raise ValueError("url_process_timeout_buffer_seconds must be >= 0")
        if self.max_url_process_timeout_seconds <= 0:
            raise ValueError("max_url_process_timeout_seconds must be > 0")
        if self.browser_render_timeout_seconds <= 0:
            raise ValueError("browser_render_timeout_seconds must be > 0")
        if self.browser_capture_max_network_payloads <= 0:
            raise ValueError("browser_capture_max_network_payloads must be > 0")
        if self.browser_capture_max_network_payload_bytes <= 0:
            raise ValueError("browser_capture_max_network_payload_bytes must be > 0")
        if self.browser_capture_total_network_payload_bytes <= 0:
            raise ValueError("browser_capture_total_network_payload_bytes must be > 0")
        if self.browser_capture_read_timeout_seconds <= 0:
            raise ValueError("browser_capture_read_timeout_seconds must be > 0")
        if self.browser_capture_queue_join_timeout_ms <= 0:
            raise ValueError("browser_capture_queue_join_timeout_ms must be > 0")
        if self.browser_artifact_capture_timeout_ms <= 0:
            raise ValueError("browser_artifact_capture_timeout_ms must be > 0")
        if self.browser_post_block_cooldown_ms < 0:
            raise ValueError("browser_post_block_cooldown_ms must be >= 0")
        if self.browser_first_nav_pause_ms < 0:
            raise ValueError("browser_first_nav_pause_ms must be >= 0")
        if self.platform_detection_html_search_limit <= 0:
            raise ValueError("platform_detection_html_search_limit must be > 0")
        if self.browser_runtime_pool_max_entries <= 0:
            raise ValueError("browser_runtime_pool_max_entries must be > 0")
        if self.browser_runtime_pool_idle_ttl_seconds < 0:
            raise ValueError("browser_runtime_pool_idle_ttl_seconds must be >= 0")
        if self.browser_proxy_bridge_connect_timeout_seconds <= 0:
            raise ValueError(
                "browser_proxy_bridge_connect_timeout_seconds must be > 0"
            )
        if self.browser_proxy_bridge_auth_timeout_seconds <= 0:
            raise ValueError(
                "browser_proxy_bridge_auth_timeout_seconds must be > 0"
            )
        if self.browser_proxy_bridge_first_byte_timeout_seconds <= 0:
            raise ValueError(
                "browser_proxy_bridge_first_byte_timeout_seconds must be > 0"
            )
        if self.browser_identity_min_chrome_version <= 0:
            raise ValueError("browser_identity_min_chrome_version must be > 0")
        if (
            self.browser_capture_total_network_payload_bytes
            < self.browser_capture_max_network_payload_bytes
        ):
            raise ValueError(
                "browser_capture_total_network_payload_bytes must be >= browser_capture_max_network_payload_bytes"
            )
        if self.acquisition_artifact_ttl_seconds < 0:
            raise ValueError("acquisition_artifact_ttl_seconds must be >= 0")
        if self.acquisition_artifact_cleanup_interval_seconds < 0:
            raise ValueError(
                "acquisition_artifact_cleanup_interval_seconds must be >= 0"
            )
        if not 0.0 <= float(self.llm_confidence_threshold) <= 1.0:
            raise ValueError("llm_confidence_threshold must be between 0 and 1")
        if not 0.0 <= float(self.selector_self_heal_min_confidence) <= 1.0:
            raise ValueError("selector_self_heal_min_confidence must be between 0 and 1")
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


def build_chrome_runtime_init_script(*, chrome_runtime_version: str) -> str:
    return "\n".join(
        [
            "(() => {",
            f"  const chromeRuntimeVersion = {chrome_runtime_version!r};",
            "  globalThis.chrome = globalThis.chrome || {};",
            "  if (typeof window !== 'undefined') { window.chrome = window.chrome || globalThis.chrome; }",
            "  const chromeRoot = globalThis.chrome;",
            "  const buildEvent = () => ({ addListener() {}, addRules() {}, getRules() { return []; }, hasListener() { return false; }, hasListeners() { return false; }, removeListener() {}, removeRules() {} });",
            "  const buildPort = () => ({ name: '', sender: undefined, disconnect() {}, onDisconnect: buildEvent(), onMessage: buildEvent(), postMessage() {} });",
            "  const runtime = chromeRoot.runtime && typeof chromeRoot.runtime === 'object' ? chromeRoot.runtime : {};",
            "  const extensionId = typeof runtime.id === 'string' && runtime.id ? runtime.id : '';",
            "  const assignIfMissing = (key, value) => { if (!(key in runtime)) { runtime[key] = value; } };",
            "  assignIfMissing('OnInstalledReason', { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' });",
            "  assignIfMissing('OnRestartRequiredReason', { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' });",
            "  assignIfMissing('PlatformArch', { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' });",
            "  assignIfMissing('PlatformNaclArch', { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' });",
            "  assignIfMissing('PlatformOs', { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' });",
            "  assignIfMissing('RequestUpdateCheckStatus', { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' });",
            "  assignIfMissing('connect', () => buildPort());",
            "  assignIfMissing('getManifest', () => undefined);",
            "  assignIfMissing('getURL', (path = '') => extensionId ? `chrome-extension://${extensionId}/${String(path || '').replace(/^\\/+/, '')}` : '');",
            "  assignIfMissing('id', undefined);",
            "  assignIfMissing('onConnect', buildEvent());",
            "  assignIfMissing('onInstalled', buildEvent());",
            "  assignIfMissing('onMessage', buildEvent());",
            "  assignIfMissing('onMessageExternal', buildEvent());",
            "  assignIfMissing('onRestartRequired', buildEvent());",
            "  assignIfMissing('onStartup', buildEvent());",
            "  assignIfMissing('onSuspend', buildEvent());",
            "  assignIfMissing('requestUpdateCheck', (callback) => { const status = 'no_update'; if (typeof callback === 'function') { queueMicrotask(() => callback(status)); } return Promise.resolve(status); });",
            "  assignIfMissing('sendMessage', (...args) => { const callback = args.find((value) => typeof value === 'function'); if (callback) { queueMicrotask(() => callback()); } return Promise.resolve(); });",
            "  assignIfMissing('getPlatformInfo', (callback) => { const info = { os: 'win', arch: 'x86-64', nacl_arch: 'x86-64' }; if (typeof callback === 'function') { queueMicrotask(() => callback(info)); } return Promise.resolve(info); });",
            "  const navigationEntry = () => {",
            "    try {",
            "      const entries = globalThis.performance && typeof globalThis.performance.getEntriesByType === 'function' ? globalThis.performance.getEntriesByType('navigation') : [];",
            "      return Array.isArray(entries) && entries.length ? entries[0] : null;",
            "    } catch (_) {",
            "      return null;",
            "    }",
            "  };",
            "  runtime.csi = runtime.csi || (() => {",
            "    const timing = globalThis.performance && globalThis.performance.timing ? globalThis.performance.timing : null;",
            "    const pageT = timing ? Math.max(1, Date.now() - Number(timing.navigationStart || Date.now())) : 320;",
            "    return { onloadT: Math.max(1, pageT), pageT: Math.max(1, pageT), startE: timing ? Number(timing.navigationStart || Date.now()) : Date.now(), tran: 15 };",
            "  });",
            "  runtime.loadTimes = runtime.loadTimes || (() => {",
            "    const timing = globalThis.performance && globalThis.performance.timing ? globalThis.performance.timing : null;",
            "    const nav = navigationEntry();",
            "    const requestTime = timing ? Number(timing.navigationStart || Date.now()) / 1000 : Date.now() / 1000;",
            "    const finishDocumentLoadTime = nav && Number.isFinite(nav.domContentLoadedEventEnd) ? Math.max(0.2, Number(nav.domContentLoadedEventEnd) / 1000) : 0.275;",
            "    const finishLoadTime = nav && Number.isFinite(nav.loadEventEnd) ? Math.max(finishDocumentLoadTime, Number(nav.loadEventEnd) / 1000) : 0.395;",
            "    const firstPaintTime = nav && Number.isFinite(nav.responseEnd) ? Math.max(0.12, Number(nav.responseEnd) / 1000) : 0.14;",
            "    return {",
            "      commitLoadTime: firstPaintTime,",
            "      connectionInfo: 'h2',",
            "      finishDocumentLoadTime,",
            "      finishLoadTime,",
            "      firstPaintAfterLoadTime: 0,",
            "      firstPaintTime,",
            "      navigationType: 'Other',",
            "      npnNegotiatedProtocol: 'h2',",
            "      requestTime,",
            "      startLoadTime: requestTime,",
            "      wasAlternateProtocolAvailable: false,",
            "      wasFetchedViaSpdy: true,",
            "      wasNpnNegotiated: true,",
            "    };",
            "  });",
            "  try { Object.defineProperty(chromeRoot, 'runtime', { value: runtime, enumerable: true, configurable: true, writable: true }); } catch (_) { chromeRoot.runtime = runtime; }",
            "})();",
        ]
    )


def build_audio_fingerprint_init_script(*, audio_seed: int) -> str:
    return "\n".join(
        [
            "(() => {",
            f"  const audioSeed = {int(audio_seed)};",
            "  const wrapMethod = (target, key, builder) => { if (!target) { return; } const nativeMethod = target[key]; if (typeof nativeMethod !== 'function' || nativeMethod.__crawlerWrapped) { return; } const wrapped = builder(nativeMethod); try { Object.defineProperty(wrapped, '__crawlerWrapped', { value: true }); } catch (_) {} try { target[key] = wrapped; } catch (_) {} };",
            "  const fillFloatSpectrum = (array) => { for (let index = 0; index < array.length; index += 1) { array[index] = -72 + ((audioSeed + index * 13) % 36) * 0.85; } };",
            "  const fillFloatWaveform = (array) => { for (let index = 0; index < array.length; index += 1) { array[index] = Math.max(-1, Math.min(1, Math.sin((audioSeed + index * 5) / 13) * 0.125)); } };",
            "  const fillByteWaveform = (array) => { for (let index = 0; index < array.length; index += 1) { array[index] = 96 + ((audioSeed + index * 9) % 64); } };",
            "  const patchAnalyserTarget = (target) => {",
            "    wrapMethod(target, 'getFloatFrequencyData', (nativeMethod) => function getFloatFrequencyData(array) { nativeMethod.call(this, array); let hasFiniteValue = false; for (let index = 0; index < array.length; index += 1) { if (Number.isFinite(array[index])) { hasFiniteValue = true; array[index] += ((((audioSeed + index * 11) % 9) - 4) / 5000); } } if (!hasFiniteValue) { fillFloatSpectrum(array); } });",
            "    wrapMethod(target, 'getByteFrequencyData', (nativeMethod) => function getByteFrequencyData(array) { nativeMethod.call(this, array); let hasSignal = false; for (let index = 0; index < array.length; index += 1) { if ((array[index] || 0) > 0) { hasSignal = true; array[index] = Math.max(0, Math.min(255, array[index] + (((audioSeed + index * 5) % 3) - 1))); } } if (!hasSignal) { for (let index = 0; index < array.length; index += 1) { array[index] = 32 + ((audioSeed + index * 7) % 64); } } });",
            "    wrapMethod(target, 'getFloatTimeDomainData', (nativeMethod) => function getFloatTimeDomainData(array) { nativeMethod.call(this, array); let hasSignal = false; for (let index = 0; index < array.length; index += 1) { const value = Number(array[index] || 0); if (Math.abs(value) > 0.0001) { hasSignal = true; array[index] = Math.max(-1, Math.min(1, value + ((((audioSeed + index * 3) % 7) - 3) / 4096))); } } if (!hasSignal) { fillFloatWaveform(array); } });",
            "    wrapMethod(target, 'getByteTimeDomainData', (nativeMethod) => function getByteTimeDomainData(array) { nativeMethod.call(this, array); let hasSignal = false; for (let index = 0; index < array.length; index += 1) { const value = Number(array[index] || 0); if (value !== 0 && value !== 128) { hasSignal = true; array[index] = Math.max(0, Math.min(255, value + (((audioSeed + index * 7) % 5) - 2))); } } if (!hasSignal) { fillByteWaveform(array); } });",
            "  };",
            "  const patchAudioContextInstance = (context) => {",
            "    if (!context || typeof context !== 'object') {",
            "      return context;",
            "    }",
            "    wrapMethod(context, 'createAnalyser', (nativeMethod) => function createAnalyser(...args) { const analyser = nativeMethod.apply(this, args); if (analyser && typeof analyser === 'object') { patchAnalyserTarget(analyser); } return analyser; });",
            "    return context;",
            "  };",
            "  const wrapContextConstructor = (globalKey) => {",
            "    const NativeCtor = globalThis[globalKey];",
            "    if (typeof NativeCtor !== 'function' || NativeCtor.__crawlerWrappedCtor) {",
            "      return;",
            "    }",
            "    const WrappedCtor = new Proxy(NativeCtor, {",
            "      construct(target, args, newTarget) {",
            "        return patchAudioContextInstance(Reflect.construct(target, args, newTarget));",
            "      },",
            "    });",
            "    try { Object.defineProperty(WrappedCtor, '__crawlerWrappedCtor', { value: true }); } catch (_) {}",
            "    try { Object.defineProperty(WrappedCtor, 'prototype', { value: NativeCtor.prototype }); } catch (_) {}",
            "    try { Object.defineProperty(WrappedCtor, 'name', { value: NativeCtor.name, configurable: true }); } catch (_) {}",
            "    try { Object.defineProperty(WrappedCtor, 'toString', { value: NativeCtor.toString.bind(NativeCtor), configurable: true }); } catch (_) {}",
            "    try { globalThis[globalKey] = WrappedCtor; } catch (_) {}",
            "  };",
            "  wrapMethod(typeof AudioBuffer !== 'undefined' ? AudioBuffer.prototype : undefined, 'getChannelData', (nativeMethod) => function getChannelData(channel) { const values = nativeMethod.call(this, channel); if (!values || typeof values.length !== 'number' || values.length === 0) { return values; } const stride = Math.max(1, Math.floor(values.length / 32)); const clone = typeof values.slice === 'function' ? values.slice(0) : new Float32Array(values); for (let index = 0; index < clone.length; index += stride) { clone[index] = Math.max(-1, Math.min(1, clone[index] + ((((audioSeed + Number(channel || 0) * 19 + index * 7) % 17) - 8) / 32768))); } return clone; });",
            "  if (typeof AnalyserNode !== 'undefined' && AnalyserNode.prototype) { patchAnalyserTarget(AnalyserNode.prototype); }",
            "  const contextCtors = [['AudioContext', globalThis.AudioContext], ['OfflineAudioContext', globalThis.OfflineAudioContext], ['webkitAudioContext', globalThis.webkitAudioContext]];",
            "  for (const [globalKey, ContextCtor] of contextCtors) {",
            "    if (!ContextCtor || !ContextCtor.prototype) { continue; }",
            "    wrapMethod(ContextCtor.prototype, 'createAnalyser', (nativeMethod) => function createAnalyser(...args) { const analyser = nativeMethod.apply(this, args); if (analyser && typeof analyser === 'object') { patchAnalyserTarget(analyser); } return analyser; });",
            "    wrapContextConstructor(globalKey);",
            "  }",
            "})();",
        ]
    )


def build_permissions_coherence_init_script(
    *,
    granted_permissions: tuple[str, ...],
) -> str:
    granted_set = {str(value).strip().lower() for value in granted_permissions if str(value).strip()}
    permission_defaults = {
        "notifications": crawler_runtime_settings.browser_permission_notifications_state,
        "camera": crawler_runtime_settings.browser_permission_camera_state,
        "microphone": crawler_runtime_settings.browser_permission_microphone_state,
        "geolocation": crawler_runtime_settings.browser_permission_geolocation_state,
    }
    permission_states = {
        name: ("granted" if name in granted_set else str(default))
        for name, default in permission_defaults.items()
    }
    media_devices = [
        {
            "deviceId": "",
            "groupId": "",
            "kind": "audioinput",
            "label": "Default Microphone" if permission_states["microphone"] == "granted" else "",
        },
        {
            "deviceId": "",
            "groupId": "",
            "kind": "audiooutput",
            "label": "Default Speakers",
        },
        {
            "deviceId": "",
            "groupId": "",
            "kind": "videoinput",
            "label": "Integrated Camera" if permission_states["camera"] == "granted" else "",
        },
    ]
    return "\n".join(
        [
            "(() => {",
            f"  const permissionStates = {json.dumps(permission_states, separators=(',', ':'))};",
            f"  const mediaDevicesPayload = {json.dumps(media_devices, separators=(',', ':'))};",
            "  const installDescriptor = (target, key, getter) => {",
            "    if (!target) {",
            "      return;",
            "    }",
            "    try {",
            "      Object.defineProperty(target, key, {",
            "        get: getter,",
            "        enumerable: false,",
            "        configurable: true,",
            "      });",
            "    } catch (_) {}",
            "  };",
            "  const buildPermissionStatus = (state) => ({",
            "    state,",
            "    onchange: null,",
            "    addEventListener() {},",
            "    removeEventListener() {},",
            "    dispatchEvent() { return true; },",
            "  });",
            "  try {",
            "    if (typeof Notification !== 'undefined') {",
            "      installDescriptor(Notification, 'permission', () => permissionStates.notifications || 'prompt');",
            "    }",
            "  } catch (_) {}",
            "  try {",
            "    const nativeQuery = Navigator.prototype.permissions?.query || navigator.permissions?.query?.bind(navigator.permissions);",
            "    if (nativeQuery) {",
            "      const wrappedQuery = async function query(permissionDesc) {",
            "        const name = String(permissionDesc && permissionDesc.name || '').toLowerCase();",
            "        if (Object.prototype.hasOwnProperty.call(permissionStates, name)) {",
            "          return buildPermissionStatus(permissionStates[name]);",
            "        }",
            "        return nativeQuery.call(this, permissionDesc);",
            "      };",
            "      if (navigator.permissions) {",
            "        navigator.permissions.query = wrappedQuery.bind(navigator.permissions);",
            "      }",
            "      try {",
            "        installDescriptor(Permissions.prototype, 'query', () => wrappedQuery);",
            "      } catch (_) {}",
            "    }",
            "  } catch (_) {}",
            "  try {",
            "    if (typeof MediaDeviceInfo === 'undefined') {",
            "      globalThis.MediaDeviceInfo = class MediaDeviceInfo {};",
            "    }",
            "    if (typeof navigator !== 'undefined' && navigator.mediaDevices) {",
            "      navigator.mediaDevices.enumerateDevices = async () => mediaDevicesPayload.map((device) => ({ ...device }));",
            "    } else {",
            "      installDescriptor(Navigator.prototype, 'mediaDevices', () => ({",
            "        enumerateDevices: async () => mediaDevicesPayload.map((device) => ({ ...device })),",
            "        getSupportedConstraints: () => ({}),",
            "      }));",
            "    }",
            "  } catch (_) {}",
            "  try {",
            "    if (typeof NetworkInformation !== 'undefined') {",
            "      installDescriptor(NetworkInformation.prototype, 'downlinkMax', () => 10);",
            "    }",
            "  } catch (_) {}",
            "  try {",
            "    if (typeof ContentIndex === 'undefined') {",
            "      globalThis.ContentIndex = class ContentIndex {",
            "        async add() { return undefined; }",
            "        async delete() { return undefined; }",
            "        async getAll() { return []; }",
            "      };",
            "    }",
            "    if (typeof ServiceWorkerRegistration === 'undefined') {",
            "      globalThis.ServiceWorkerRegistration = class ServiceWorkerRegistration {};",
            "    }",
            "    installDescriptor(ServiceWorkerRegistration.prototype, 'contentIndex', () => new ContentIndex());",
            "  } catch (_) {}",
            "  try {",
            "    if (typeof ContactsManager === 'undefined') {",
            "      globalThis.ContactsManager = class ContactsManager {",
            "        async getProperties() { return ['name', 'email', 'tel', 'address', 'icon']; }",
            "        async select() { return []; }",
            "      };",
            "    }",
            "    installDescriptor(Navigator.prototype, 'contacts', () => new ContactsManager());",
            "  } catch (_) {}",
            "})();",
        ]
    )


_WEBGL_PROFILE_BY_PLATFORM: dict[str, dict[str, object]] = {
    "Windows": {
        "vendor": "Google Inc.",
        "renderer": "ANGLE (Intel, Intel(R) UHD Graphics 620 Direct3D11 vs_5_0 ps_5_0, D3D11)",
        "version": "WebGL 1.0 (OpenGL ES 2.0 Chromium)",
        "shading_language_version": "WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)",
        "max_texture_size": 16384,
        "max_renderbuffer_size": 16384,
        "max_cube_map_texture_size": 16384,
        "max_viewport_dims": [16384, 16384],
        "max_texture_image_units": 16,
        "max_combined_texture_image_units": 32,
        "max_vertex_texture_image_units": 16,
        "max_vertex_attribs": 16,
        "max_vertex_uniform_vectors": 1024,
        "max_fragment_uniform_vectors": 1024,
        "aliased_line_width_range": [1, 1],
        "aliased_point_size_range": [1, 1024],
        "max_anisotropy": 16,
        "supported_extensions": [
            "ANGLE_instanced_arrays",
            "EXT_blend_minmax",
            "EXT_color_buffer_half_float",
            "EXT_disjoint_timer_query",
            "EXT_frag_depth",
            "EXT_shader_texture_lod",
            "EXT_texture_filter_anisotropic",
            "OES_element_index_uint",
            "OES_standard_derivatives",
            "OES_texture_float",
            "OES_texture_float_linear",
            "OES_texture_half_float",
            "OES_texture_half_float_linear",
            "OES_vertex_array_object",
            "WEBGL_color_buffer_float",
            "WEBGL_compressed_texture_s3tc",
            "WEBGL_debug_renderer_info",
            "WEBGL_debug_shaders",
            "WEBGL_depth_texture",
            "WEBGL_draw_buffers",
            "WEBGL_lose_context",
        ],
    },
    "macOS": {
        "vendor": "Intel Inc.",
        "renderer": "Intel(R) Iris OpenGL Engine",
        "version": "WebGL 1.0 (OpenGL ES 2.0 Chromium)",
        "shading_language_version": "WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)",
        "max_texture_size": 16384,
        "max_renderbuffer_size": 16384,
        "max_cube_map_texture_size": 16384,
        "max_viewport_dims": [16384, 16384],
        "max_texture_image_units": 16,
        "max_combined_texture_image_units": 32,
        "max_vertex_texture_image_units": 16,
        "max_vertex_attribs": 16,
        "max_vertex_uniform_vectors": 1024,
        "max_fragment_uniform_vectors": 1024,
        "aliased_line_width_range": [1, 1],
        "aliased_point_size_range": [1, 511],
        "max_anisotropy": 16,
        "supported_extensions": [
            "EXT_blend_minmax",
            "EXT_color_buffer_half_float",
            "EXT_frag_depth",
            "EXT_shader_texture_lod",
            "EXT_texture_filter_anisotropic",
            "OES_element_index_uint",
            "OES_standard_derivatives",
            "OES_texture_float",
            "OES_texture_float_linear",
            "OES_texture_half_float",
            "OES_texture_half_float_linear",
            "OES_vertex_array_object",
            "WEBGL_color_buffer_float",
            "WEBGL_compressed_texture_s3tc",
            "WEBGL_debug_renderer_info",
            "WEBGL_debug_shaders",
            "WEBGL_depth_texture",
            "WEBGL_draw_buffers",
            "WEBGL_lose_context",
        ],
    },
    "Linux": {
        "vendor": "Google Inc.",
        "renderer": "ANGLE (Intel, Mesa Intel(R) UHD Graphics 620 (KBL GT2), OpenGL 4.6)",
        "version": "WebGL 1.0 (OpenGL ES 2.0 Chromium)",
        "shading_language_version": "WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)",
        "max_texture_size": 16384,
        "max_renderbuffer_size": 16384,
        "max_cube_map_texture_size": 16384,
        "max_viewport_dims": [16384, 16384],
        "max_texture_image_units": 16,
        "max_combined_texture_image_units": 32,
        "max_vertex_texture_image_units": 16,
        "max_vertex_attribs": 16,
        "max_vertex_uniform_vectors": 1024,
        "max_fragment_uniform_vectors": 1024,
        "aliased_line_width_range": [1, 1],
        "aliased_point_size_range": [1, 1024],
        "max_anisotropy": 16,
        "supported_extensions": [
            "ANGLE_instanced_arrays",
            "EXT_blend_minmax",
            "EXT_color_buffer_half_float",
            "EXT_frag_depth",
            "EXT_shader_texture_lod",
            "EXT_texture_filter_anisotropic",
            "OES_element_index_uint",
            "OES_standard_derivatives",
            "OES_texture_float",
            "OES_texture_float_linear",
            "OES_texture_half_float",
            "OES_texture_half_float_linear",
            "OES_vertex_array_object",
            "WEBGL_color_buffer_float",
            "WEBGL_compressed_texture_s3tc",
            "WEBGL_debug_renderer_info",
            "WEBGL_debug_shaders",
            "WEBGL_depth_texture",
            "WEBGL_draw_buffers",
            "WEBGL_lose_context",
        ],
    },
    "mobile": {
        "vendor": "Qualcomm",
        "renderer": "Adreno (TM) 640",
        "version": "WebGL 1.0 (OpenGL ES 2.0 Chromium)",
        "shading_language_version": "WebGL GLSL ES 1.0 (OpenGL ES GLSL ES 1.0 Chromium)",
        "max_texture_size": 8192,
        "max_renderbuffer_size": 8192,
        "max_cube_map_texture_size": 8192,
        "max_viewport_dims": [8192, 8192],
        "max_texture_image_units": 16,
        "max_combined_texture_image_units": 24,
        "max_vertex_texture_image_units": 16,
        "max_vertex_attribs": 16,
        "max_vertex_uniform_vectors": 256,
        "max_fragment_uniform_vectors": 224,
        "aliased_line_width_range": [1, 1],
        "aliased_point_size_range": [1, 511],
        "max_anisotropy": 8,
        "supported_extensions": [
            "EXT_blend_minmax",
            "EXT_color_buffer_half_float",
            "EXT_frag_depth",
            "EXT_shader_texture_lod",
            "EXT_texture_filter_anisotropic",
            "OES_element_index_uint",
            "OES_standard_derivatives",
            "OES_texture_float",
            "OES_texture_half_float",
            "OES_vertex_array_object",
            "WEBGL_color_buffer_float",
            "WEBGL_debug_renderer_info",
            "WEBGL_depth_texture",
            "WEBGL_draw_buffers",
            "WEBGL_lose_context",
        ],
    },
}

_FONT_ALLOWLIST_BY_PLATFORM: dict[str, tuple[str, ...]] = {
    "Windows": (
        "arial",
        "arial black",
        "bahnschrift",
        "calibri",
        "cambria",
        "candara",
        "comic sans ms",
        "consolas",
        "constantia",
        "corbel",
        "courier new",
        "franklin gothic medium",
        "gabriola",
        "georgia",
        "impact",
        "lucida console",
        "lucida sans unicode",
        "palatino linotype",
        "segoe print",
        "segoe script",
        "segoe ui",
        "segoe ui emoji",
        "tahoma",
        "times new roman",
        "trebuchet ms",
        "verdana",
    ),
    "macOS": (
        "american typewriter",
        "arial",
        "avenir",
        "avenir next",
        "baskerville",
        "courier",
        "courier new",
        "futura",
        "geneva",
        "georgia",
        "helvetica",
        "helvetica neue",
        "menlo",
        "monaco",
        "optima",
        "palatino",
        "san francisco",
        "sf pro display",
        "sf pro text",
        "times",
        "times new roman",
        "verdana",
    ),
    "Linux": (
        "arial",
        "cantarell",
        "dejavu sans",
        "dejavu sans mono",
        "dejavu serif",
        "droid sans",
        "free mono",
        "free sans",
        "free serif",
        "liberation mono",
        "liberation sans",
        "liberation serif",
        "noto color emoji",
        "noto sans",
        "noto sans mono",
        "noto serif",
        "ubuntu",
        "ubuntu mono",
        "verdana",
    ),
    "mobile": (
        "arial",
        "arial hebrew",
        "courier new",
        "droid sans",
        "georgia",
        "helvetica",
        "helvetica neue",
        "noto sans",
        "noto sans jp",
        "noto sans kr",
        "noto sans sc",
        "noto sans tc",
        "noto serif",
        "roboto",
        "roboto condensed",
        "roboto mono",
        "san francisco",
        "sf pro display",
        "sf pro text",
        "times new roman",
        "verdana",
    ),
}


def build_canvas_fingerprint_init_script(*, canvas_seed: int) -> str:
    return "\n".join(
        [
            "(() => {",
            f"  const canvasSeed = {int(canvas_seed)} >>> 0;",
            "  if (typeof CanvasRenderingContext2D === 'undefined' || typeof HTMLCanvasElement === 'undefined') { return; }",
            "  const nativeGetImageData = CanvasRenderingContext2D.prototype.getImageData;",
            "  const nativePutImageData = CanvasRenderingContext2D.prototype.putImageData;",
            "  const nativeToDataURL = HTMLCanvasElement.prototype.toDataURL;",
            "  const nativeToBlob = HTMLCanvasElement.prototype.toBlob;",
            "  const clampByte = (value) => Math.max(0, Math.min(255, value));",
            "  const cloneImageData = (ctx, imageData) => {",
            "    try { return new ImageData(new Uint8ClampedArray(imageData.data), imageData.width, imageData.height); }",
            "    catch (_) { const clone = ctx.createImageData(imageData.width, imageData.height); clone.data.set(imageData.data); return clone; }",
            "  };",
            "  const channelDelta = (pixelIndex, channelIndex) => {",
            "    const raw = ((canvasSeed + pixelIndex * 13 + channelIndex * 7) % 7) - 3;",
            "    return raw === 0 ? 1 : raw;",
            "  };",
            "  const applyCanvasNoise = (imageData) => {",
            "    const data = imageData && imageData.data;",
            "    if (!data || !data.length) { return imageData; }",
            "    for (let offset = 0; offset < data.length; offset += 4) {",
            "      const pixelIndex = offset / 4;",
            "      if (((pixelIndex + canvasSeed) % 4) !== 0) { continue; }",
            "      data[offset] = clampByte(data[offset] + channelDelta(pixelIndex, 0));",
            "      data[offset + 1] = clampByte(data[offset + 1] + channelDelta(pixelIndex, 1));",
            "      data[offset + 2] = clampByte(data[offset + 2] + channelDelta(pixelIndex, 2));",
            "    }",
            "    return imageData;",
            "  };",
            "  const buildNoisedCanvas = (sourceCanvas) => {",
            "    const width = Number(sourceCanvas && sourceCanvas.width || 0);",
            "    const height = Number(sourceCanvas && sourceCanvas.height || 0);",
            "    if (width <= 0 || height <= 0) { return sourceCanvas; }",
            "    const sourceCtx = sourceCanvas.getContext('2d');",
            "    if (!sourceCtx || typeof nativeGetImageData !== 'function' || typeof nativePutImageData !== 'function') { return sourceCanvas; }",
            "    try {",
            "      const raw = nativeGetImageData.call(sourceCtx, 0, 0, width, height);",
            "      const noised = applyCanvasNoise(cloneImageData(sourceCtx, raw));",
            "      const clone = document.createElement('canvas');",
            "      clone.width = width;",
            "      clone.height = height;",
            "      const cloneCtx = clone.getContext('2d');",
            "      if (!cloneCtx) { return sourceCanvas; }",
            "      nativePutImageData.call(cloneCtx, noised, 0, 0);",
            "      return clone;",
            "    } catch (_) {",
            "      return sourceCanvas;",
            "    }",
            "  };",
            "  CanvasRenderingContext2D.prototype.getImageData = function getImageData(...args) {",
            "    const imageData = nativeGetImageData.apply(this, args);",
            "    return applyCanvasNoise(cloneImageData(this, imageData));",
            "  };",
            "  HTMLCanvasElement.prototype.toDataURL = function toDataURL(...args) {",
            "    return nativeToDataURL.apply(buildNoisedCanvas(this), args);",
            "  };",
            "  if (typeof nativeToBlob === 'function') {",
            "    HTMLCanvasElement.prototype.toBlob = function toBlob(callback, ...args) {",
            "      return nativeToBlob.call(buildNoisedCanvas(this), callback, ...args);",
            "    };",
            "  }",
            "})();",
        ]
    )


def build_webgl_fingerprint_init_script(
    *,
    platform_label: str,
    is_mobile: bool,
    webgl_seed: int,
) -> str:
    profile_key = "mobile" if is_mobile else platform_label
    profile = dict(
        _WEBGL_PROFILE_BY_PLATFORM.get(
            profile_key,
            _WEBGL_PROFILE_BY_PLATFORM["Windows"],
        )
    )
    return "\n".join(
        [
            "(() => {",
            f"  const webglSeed = {int(webgl_seed)} >>> 0;",
            f"  const profile = {json.dumps(profile, separators=(',', ':'))};",
            "  const DEBUG_RENDERER_INFO = { UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446 };",
            "  const ANISO = { MAX_TEXTURE_MAX_ANISOTROPY_EXT: 34047 };",
            "  const LOSE_CONTEXT = { loseContext() {}, restoreContext() {} };",
            "  const cloneValue = (value) => {",
            "    if (Array.isArray(value)) { return value.slice(); }",
            "    if (value instanceof Int32Array) { return new Int32Array(value); }",
            "    if (value instanceof Float32Array) { return new Float32Array(value); }",
            "    return value;",
            "  };",
            "  const applyPixelNoise = (pixels) => {",
            "    if (!pixels || typeof pixels.length !== 'number') { return; }",
            "    const byteStep = pixels.BYTES_PER_ELEMENT === 1 ? 4 : Math.max(4, pixels.BYTES_PER_ELEMENT * 4);",
            "    for (let offset = 0; offset < pixels.length; offset += byteStep) {",
            "      const pixelIndex = Math.floor(offset / byteStep);",
            "      if (((pixelIndex + webglSeed) % 4) !== 0) { continue; }",
            "      for (let channel = 0; channel < 3 && offset + channel < pixels.length; channel += 1) {",
            "        const delta = ((webglSeed + pixelIndex * 17 + channel * 11) % 7) - 3 || 1;",
            "        if (pixels.BYTES_PER_ELEMENT === 1) { pixels[offset + channel] = Math.max(0, Math.min(255, pixels[offset + channel] + delta)); }",
            "        else { pixels[offset + channel] = pixels[offset + channel] + (delta / 1024); }",
            "      }",
            "    }",
            "  };",
            "  const parameterOverrides = new Map([",
            "    [7936, profile.vendor],",
            "    [7937, profile.renderer],",
            "    [7938, profile.version],",
            "    [35724, profile.shading_language_version],",
            "    [37445, profile.vendor],",
            "    [37446, profile.renderer],",
            "    [3379, profile.max_texture_size],",
            "    [34024, profile.max_renderbuffer_size],",
            "    [34076, profile.max_cube_map_texture_size],",
            "    [3386, new Int32Array(profile.max_viewport_dims)],",
            "    [34930, profile.max_texture_image_units],",
            "    [35661, profile.max_combined_texture_image_units],",
            "    [35660, profile.max_vertex_texture_image_units],",
            "    [34921, profile.max_vertex_attribs],",
            "    [36347, profile.max_vertex_uniform_vectors],",
            "    [36349, profile.max_fragment_uniform_vectors],",
            "    [33902, new Float32Array(profile.aliased_line_width_range)],",
            "    [33901, new Float32Array(profile.aliased_point_size_range)],",
            "    [34047, profile.max_anisotropy],",
            "  ]);",
            "  const precisionFormats = new Map([",
            "    [36336, { rangeMin: 127, rangeMax: 127, precision: 8 }],",
            "    [36337, { rangeMin: 127, rangeMax: 127, precision: 10 }],",
            "    [36338, { rangeMin: 127, rangeMax: 127, precision: 23 }],",
            "    [36339, { rangeMin: 31, rangeMax: 30, precision: 0 }],",
            "    [36340, { rangeMin: 31, rangeMax: 30, precision: 0 }],",
            "    [36341, { rangeMin: 31, rangeMax: 30, precision: 0 }],",
            "  ]);",
            "  const patchPrototype = (prototype) => {",
            "    if (!prototype) { return; }",
            "    const nativeGetParameter = prototype.getParameter;",
            "    const nativeGetSupportedExtensions = prototype.getSupportedExtensions;",
            "    const nativeGetExtension = prototype.getExtension;",
            "    const nativeGetShaderPrecisionFormat = prototype.getShaderPrecisionFormat;",
            "    const nativeReadPixels = prototype.readPixels;",
            "    if (typeof nativeGetParameter === 'function') {",
            "      prototype.getParameter = function getParameter(pname) {",
            "        if (parameterOverrides.has(pname)) { return cloneValue(parameterOverrides.get(pname)); }",
            "        return nativeGetParameter.call(this, pname);",
            "      };",
            "    }",
            "    if (typeof nativeGetSupportedExtensions === 'function') {",
            "      prototype.getSupportedExtensions = function getSupportedExtensions() {",
            "        return Array.from(profile.supported_extensions);",
            "      };",
            "    }",
            "    if (typeof nativeGetExtension === 'function') {",
            "      prototype.getExtension = function getExtension(name) {",
            "        const normalized = String(name || '').trim();",
            "        if (normalized === 'WEBGL_debug_renderer_info') { return DEBUG_RENDERER_INFO; }",
            "        if (normalized === 'EXT_texture_filter_anisotropic' || normalized === 'MOZ_EXT_texture_filter_anisotropic' || normalized === 'WEBKIT_EXT_texture_filter_anisotropic') { return ANISO; }",
            "        if (normalized === 'WEBGL_lose_context') { return LOSE_CONTEXT; }",
            "        if (!profile.supported_extensions.includes(normalized)) { return null; }",
            "        return nativeGetExtension.call(this, name) || {};",
            "      };",
            "    }",
            "    if (typeof nativeGetShaderPrecisionFormat === 'function') {",
            "      prototype.getShaderPrecisionFormat = function getShaderPrecisionFormat(shaderType, precisionType) {",
            "        if (precisionFormats.has(precisionType)) { return { ...precisionFormats.get(precisionType) }; }",
            "        return nativeGetShaderPrecisionFormat.call(this, shaderType, precisionType);",
            "      };",
            "    }",
            "    if (typeof nativeReadPixels === 'function') {",
            "      prototype.readPixels = function readPixels(...args) {",
            "        const result = nativeReadPixels.apply(this, args);",
            "        const pixels = [...args].reverse().find((value) => value && typeof value === 'object' && ArrayBuffer.isView(value));",
            "        applyPixelNoise(pixels);",
            "        return result;",
            "      };",
            "    }",
            "  };",
            "  patchPrototype(globalThis.WebGLRenderingContext && globalThis.WebGLRenderingContext.prototype);",
            "  patchPrototype(globalThis.WebGL2RenderingContext && globalThis.WebGL2RenderingContext.prototype);",
            "})();",
        ]
    )


def _font_profile_key(*, platform_label: str, is_mobile: bool) -> str:
    return "mobile" if is_mobile else platform_label


def build_font_surface_init_script(
    *,
    platform_label: str,
    is_mobile: bool,
) -> str:
    profile_key = _font_profile_key(
        platform_label=platform_label,
        is_mobile=is_mobile,
    )
    allowed_fonts = tuple(
        _FONT_ALLOWLIST_BY_PLATFORM.get(
            profile_key,
            _FONT_ALLOWLIST_BY_PLATFORM["Windows"],
        )
    )
    return "\n".join(
        [
            "(() => {",
            f"  const allowedFonts = new Set({json.dumps(list(allowed_fonts), separators=(',', ':'))});",
            "  const genericFonts = new Set(['serif', 'sans-serif', 'monospace', 'system-ui', 'cursive', 'fantasy', 'math', 'emoji', 'fangsong', 'ui-serif', 'ui-sans-serif', 'ui-monospace', 'ui-rounded']);",
            "  const normalizeFontFamily = (value) => String(value || '').trim().replace(/^['\\\"]|['\\\"]$/g, '').trim().toLowerCase();",
            "  const extractFamilySegment = (value) => {",
            "    const raw = String(value || '').trim();",
            "    if (!raw) {",
            "      return raw;",
            "    }",
            "    const sizeMatch = raw.match(/(?:^|\\s)\\d+(?:\\.\\d+)?(?:px|pt|pc|em|rem|ex|ch|vh|vw|vmin|vmax|%)\\s*(?:\\/[^,\\s]+)?\\s*(.+)$/i);",
            "    return sizeMatch && sizeMatch[1] ? sizeMatch[1] : raw;",
            "  };",
            "  const sanitizeFamilies = (value) => {",
            "    const normalizedFamilies = extractFamilySegment(value).split(',').map(normalizeFontFamily).filter(Boolean);",
            "    const sanitized = [];",
            "    let fallbackGeneric = '';",
            "    for (const family of normalizedFamilies) {",
            "      if (genericFonts.has(family)) {",
            "        sanitized.push(family);",
            "        if (!fallbackGeneric) {",
            "          fallbackGeneric = family;",
            "        }",
            "        continue;",
            "      }",
            "      if (allowedFonts.has(family)) {",
            "        sanitized.push(family);",
            "      }",
            "    }",
            "    if (!fallbackGeneric) {",
            "      fallbackGeneric = 'sans-serif';",
            "    }",
            "    if (!sanitized.length) {",
            "      sanitized.push(fallbackGeneric);",
            "    }",
            "    if (!sanitized.some((family) => genericFonts.has(family))) {",
            "      sanitized.push(fallbackGeneric);",
            "    }",
            "    return sanitized;",
            "  };",
            "  const sanitizeFontFamilyValue = (value) => sanitizeFamilies(value).join(', ');",
            "  const sanitizeFontSpec = (fontSpec) => {",
            "    const raw = String(fontSpec || '').trim();",
            "    if (!raw) {",
            "      return raw;",
            "    }",
            "    const sizeMatch = raw.match(/(?:^|\\s)\\d+(?:\\.\\d+)?(?:px|pt|pc|em|rem|ex|ch|vh|vw|vmin|vmax|%)\\s*(?:\\/[^,\\s]+)?\\s*(.+)$/i);",
            "    if (!sizeMatch || !sizeMatch[1]) {",
            "      return sanitizeFontFamilyValue(raw);",
            "    }",
            "    const familySegment = sizeMatch[1];",
            "    const prefix = raw.slice(0, raw.length - familySegment.length);",
            "    return prefix + sanitizeFontFamilyValue(familySegment);",
            "  };",
            "  const rewriteStyleText = (value) => String(value || '')",
            "    .replace(/font-family\\s*:\\s*([^;]+)(;?)/gi, (_match, familyValue, suffix) => `font-family: ${sanitizeFontFamilyValue(familyValue)}${suffix || ''}`)",
            "    .replace(/(^|[;\\s])font\\s*:\\s*([^;]+)(;?)/gi, (_match, prefix, fontValue, suffix) => `${prefix}font: ${sanitizeFontSpec(fontValue)}${suffix || ''}`);",
            "  const installDescriptor = (target, key, getter) => {",
            "    if (!target) {",
            "      return;",
            "    }",
            "    try {",
            "      Object.defineProperty(target, key, {",
            "        get: getter,",
            "        enumerable: false,",
            "        configurable: true,",
            "      });",
            "    } catch (_) {}",
            "  };",
            "  const patchStyleDescriptor = (key, sanitizer) => {",
            "    if (typeof CSSStyleDeclaration === 'undefined' || !CSSStyleDeclaration.prototype) {",
            "      return;",
            "    }",
            "    const descriptor = Object.getOwnPropertyDescriptor(CSSStyleDeclaration.prototype, key);",
            "    if (!descriptor || typeof descriptor.set !== 'function') {",
            "      return;",
            "    }",
            "    try {",
            "      Object.defineProperty(CSSStyleDeclaration.prototype, key, {",
            "        get() {",
            "          return descriptor.get ? descriptor.get.call(this) : '';",
            "        },",
            "        set(value) {",
            "          return descriptor.set.call(this, sanitizer(value));",
            "        },",
            "        enumerable: descriptor.enumerable,",
            "        configurable: true,",
            "      });",
            "    } catch (_) {}",
            "  };",
            "  const patchCanvasFontDescriptor = (prototype) => {",
            "    if (!prototype) {",
            "      return;",
            "    }",
            "    const descriptor = Object.getOwnPropertyDescriptor(prototype, 'font');",
            "    if (!descriptor || typeof descriptor.set !== 'function') {",
            "      return;",
            "    }",
            "    try {",
            "      Object.defineProperty(prototype, 'font', {",
            "        get() {",
            "          return descriptor.get ? descriptor.get.call(this) : '';",
            "        },",
            "        set(value) {",
            "          return descriptor.set.call(this, sanitizeFontSpec(value));",
            "        },",
            "        enumerable: descriptor.enumerable,",
            "        configurable: true,",
            "      });",
            "    } catch (_) {}",
            "  };",
            "  try {",
            "    if (typeof CSSStyleDeclaration !== 'undefined' && CSSStyleDeclaration.prototype && typeof CSSStyleDeclaration.prototype.setProperty === 'function') {",
            "      const nativeSetProperty = CSSStyleDeclaration.prototype.setProperty;",
            "      CSSStyleDeclaration.prototype.setProperty = function setProperty(name, value, priority) {",
            "        const normalizedName = String(name || '').trim().toLowerCase();",
            "        if (normalizedName === 'font-family') {",
            "          return nativeSetProperty.call(this, name, sanitizeFontFamilyValue(value), priority);",
            "        }",
            "        if (normalizedName === 'font') {",
            "          return nativeSetProperty.call(this, name, sanitizeFontSpec(value), priority);",
            "        }",
            "        return nativeSetProperty.call(this, name, value, priority);",
            "      };",
            "    }",
            "  } catch (_) {}",
            "  patchStyleDescriptor('fontFamily', sanitizeFontFamilyValue);",
            "  patchStyleDescriptor('font', sanitizeFontSpec);",
            "  try {",
            "    if (typeof Element !== 'undefined' && Element.prototype && typeof Element.prototype.setAttribute === 'function') {",
            "      const nativeSetAttribute = Element.prototype.setAttribute;",
            "      Element.prototype.setAttribute = function setAttribute(name, value) {",
            "        if (String(name || '').trim().toLowerCase() === 'style') {",
            "          return nativeSetAttribute.call(this, name, rewriteStyleText(value));",
            "        }",
            "        return nativeSetAttribute.call(this, name, value);",
            "      };",
            "    }",
            "  } catch (_) {}",
            "  patchCanvasFontDescriptor(globalThis.CanvasRenderingContext2D && globalThis.CanvasRenderingContext2D.prototype);",
            "  patchCanvasFontDescriptor(globalThis.OffscreenCanvasRenderingContext2D && globalThis.OffscreenCanvasRenderingContext2D.prototype);",
            "  try {",
            "    if (typeof FontFaceSet !== 'undefined' && FontFaceSet.prototype && typeof FontFaceSet.prototype.check === 'function') {",
            "      const nativeCheck = FontFaceSet.prototype.check;",
            "      FontFaceSet.prototype.check = function check(fontSpec, text) {",
            "        const families = sanitizeFamilies(fontSpec);",
            "        if (!families.length) {",
            "          return nativeCheck.call(this, fontSpec, text);",
            "        }",
            "        for (const family of families) {",
            "          if (genericFonts.has(family)) {",
            "            continue;",
            "          }",
            "          if (!allowedFonts.has(family)) {",
            "            return false;",
            "          }",
            "        }",
            "        return nativeCheck.call(this, sanitizeFontSpec(fontSpec), text);",
            "      };",
            "    }",
            "  } catch (_) {}",
            "  try {",
            "    if (typeof document !== 'undefined' && document.fonts) {",
            "      installDescriptor(document.fonts, 'ready', () => Promise.resolve(document.fonts));",
            "    }",
            "  } catch (_) {}",
            "})();",
        ]
    )


def build_navigator_coherence_init_script(
    *,
    platform_label: str,
    is_mobile: bool,
    viewport_width: int,
    viewport_height: int,
) -> str:
    connection_profile = {
        "effectiveType": crawler_runtime_settings.browser_connection_effective_type,
        "downlink": float(crawler_runtime_settings.browser_connection_downlink_mbps),
        "downlinkMax": float(
            crawler_runtime_settings.browser_connection_downlink_max_mbps
        ),
        "rtt": int(crawler_runtime_settings.browser_connection_rtt_ms),
        "saveData": bool(crawler_runtime_settings.browser_connection_save_data),
        "type": str(crawler_runtime_settings.browser_connection_type or "wifi"),
    }
    orientation_angle = 90 if int(viewport_width) > int(viewport_height) else 0
    orientation_type = (
        "landscape-primary"
        if int(viewport_width) > int(viewport_height)
        else "portrait-primary"
    )
    max_touch_points = (
        max(1, int(crawler_runtime_settings.browser_mobile_max_touch_points))
        if is_mobile
        else 0
    )
    return "\n".join(
        [
            "(() => {",
            f"  const connectionProfile = {json.dumps(connection_profile, separators=(',', ':'))};",
            f"  const maxTouchPoints = {int(max_touch_points)};",
            f"  const orientationAngle = {int(orientation_angle)};",
            f"  const orientationType = {json.dumps(orientation_type)};",
            "  const installDescriptor = (target, key, getter) => {",
            "    if (!target) {",
            "      return;",
            "    }",
            "    try {",
            "      Object.defineProperty(target, key, {",
            "        get: getter,",
            "        enumerable: false,",
            "        configurable: true,",
            "      });",
            "    } catch (_) {}",
            "  };",
            "  const connection = {",
            "    ...connectionProfile,",
            "    onchange: null,",
            "    addEventListener() {},",
            "    removeEventListener() {},",
            "    dispatchEvent() { return true; },",
            "  };",
            "  const keyboardLayoutEntries = [['Backquote', '`'], ['Digit1', '1'], ['KeyA', 'a'], ['Space', ' ']];",
            "  const buildKeyboard = () => {",
            "    const keyboard = {",
            "      getLayoutMap() { return Promise.resolve(new Map(keyboardLayoutEntries)); },",
            "      lock() { return Promise.resolve(); },",
            "      unlock() {},",
            "      addEventListener() {},",
            "      removeEventListener() {},",
            "      dispatchEvent() { return true; },",
            "    };",
            "    try {",
            "      if (typeof Keyboard !== 'undefined' && Keyboard.prototype) {",
            "        Object.setPrototypeOf(keyboard, Keyboard.prototype);",
            "      }",
            "    } catch (_) {}",
            "    return keyboard;",
            "  };",
            "  const buildMediaCapabilities = () => {",
            "    const normalizeMediaSupport = (config) => ({",
            "      supported: Boolean(config && typeof config === 'object'),",
            "      smooth: true,",
            "      powerEfficient: false,",
            "      keySystemAccess: null,",
            "      configuration: config && typeof config === 'object' ? config : undefined,",
            "    });",
            "    const mediaCapabilities = {",
            "      decodingInfo(config) { return Promise.resolve(normalizeMediaSupport(config)); },",
            "      encodingInfo(config) { return Promise.resolve(normalizeMediaSupport(config)); },",
            "    };",
            "    try {",
            "      if (typeof MediaCapabilities !== 'undefined' && MediaCapabilities.prototype) {",
            "        Object.setPrototypeOf(mediaCapabilities, MediaCapabilities.prototype);",
            "      }",
            "    } catch (_) {}",
            "    return mediaCapabilities;",
            "  };",
            "  const buildGpu = () => {",
            "    const gpu = {",
            "      wgslLanguageFeatures: new Set(),",
            "      requestAdapter() { return Promise.resolve(null); },",
            "      getPreferredCanvasFormat() { return 'bgra8unorm'; },",
            "    };",
            "    try {",
            "      if (typeof GPU !== 'undefined' && GPU.prototype) {",
            "        Object.setPrototypeOf(gpu, GPU.prototype);",
            "      }",
            "    } catch (_) {}",
            "    return gpu;",
            "  };",
            "  const keyboard = buildKeyboard();",
            "  const mediaCapabilities = buildMediaCapabilities();",
            "  const gpu = buildGpu();",
            "  try {",
            "    if (typeof NetworkInformation !== 'undefined' && NetworkInformation.prototype) {",
            "      Object.setPrototypeOf(connection, NetworkInformation.prototype);",
            "    }",
            "  } catch (_) {}",
            "  installDescriptor(Navigator.prototype, 'connection', () => connection);",
            "  installDescriptor(Navigator.prototype, 'mozConnection', () => connection);",
            "  installDescriptor(Navigator.prototype, 'webkitConnection', () => connection);",
            "  installDescriptor(Navigator.prototype, 'maxTouchPoints', () => maxTouchPoints);",
            "  installDescriptor(Navigator.prototype, 'keyboard', () => keyboard);",
            "  installDescriptor(Navigator.prototype, 'mediaCapabilities', () => mediaCapabilities);",
            "  installDescriptor(Navigator.prototype, 'gpu', () => gpu);",
            "  const buildOrientation = () => {",
            "    let nativeOrientation = null;",
            "    try { nativeOrientation = typeof screen !== 'undefined' ? screen.orientation : null; } catch (_) {}",
            "    if (nativeOrientation && typeof nativeOrientation === 'object') {",
            "      const wrapped = Object.create(Object.getPrototypeOf(nativeOrientation) || Object.prototype);",
            "      installDescriptor(wrapped, 'angle', () => orientationAngle);",
            "      installDescriptor(wrapped, 'type', () => orientationType);",
            "      installDescriptor(wrapped, 'onchange', () => nativeOrientation.onchange || null);",
            "      wrapped.addEventListener = (...args) => nativeOrientation.addEventListener ? nativeOrientation.addEventListener(...args) : undefined;",
            "      wrapped.removeEventListener = (...args) => nativeOrientation.removeEventListener ? nativeOrientation.removeEventListener(...args) : undefined;",
            "      wrapped.dispatchEvent = (...args) => nativeOrientation.dispatchEvent ? nativeOrientation.dispatchEvent(...args) : true;",
            "      wrapped.lock = (...args) => nativeOrientation.lock ? nativeOrientation.lock(...args) : Promise.resolve(orientationType);",
            "      wrapped.unlock = (...args) => nativeOrientation.unlock ? nativeOrientation.unlock(...args) : undefined;",
            "      return wrapped;",
            "    }",
            "    return {",
            "      angle: orientationAngle,",
            "      type: orientationType,",
            "      onchange: null,",
            "      addEventListener() {},",
            "      removeEventListener() {},",
            "      dispatchEvent() { return true; },",
            "      lock() { return Promise.resolve(orientationType); },",
            "      unlock() {},",
            "    };",
            "  };",
            "  const orientation = buildOrientation();",
            "  if (typeof Screen !== 'undefined' && Screen.prototype) {",
            "    installDescriptor(Screen.prototype, 'orientation', () => orientation);",
            "  } else if (typeof screen !== 'undefined') {",
            "    installDescriptor(screen, 'orientation', () => orientation);",
            "  }",
            "})();",
        ]
    )


def build_intl_coherence_init_script(
    *,
    locale: str,
    timezone_id: str | None,
) -> str:
    return "\n".join(
        [
            "(() => {",
            f"  const locale = {json.dumps(locale)};",
            f"  const timezoneId = {json.dumps(timezone_id)};",
            "  const shouldInjectLocale = (value) => {",
            "    if (value === undefined || value === null || value === '') {",
            "      return true;",
            "    }",
            "    return Array.isArray(value) && value.length === 0;",
            "  };",
            "  const nativeLocaleOrFallback = (value) => {",
            "    const normalized = String(value || '').trim();",
            "    return normalized || locale;",
            "  };",
            "  const patchIntlConstructor = (name, resolvedOptionsPatch) => {",
            "    const NativeCtor = Intl[name];",
            "    if (typeof NativeCtor !== 'function' || !NativeCtor.prototype || typeof NativeCtor.prototype.resolvedOptions !== 'function') {",
            "      return;",
            "    }",
            "    const nativeResolvedOptions = NativeCtor.prototype.resolvedOptions;",
            "    const PatchedCtor = function IntlConstructor(...args) {",
            "      const normalizedArgs = [...args];",
            "      if (shouldInjectLocale(normalizedArgs[0])) {",
            "        normalizedArgs[0] = locale;",
            "      }",
            "      const formatter = new NativeCtor(...normalizedArgs);",
            "      return new Proxy(formatter, {",
            "        get(target, prop, receiver) {",
            "          if (prop === 'resolvedOptions') {",
            "            return () => ({",
            "              ...nativeResolvedOptions.call(target),",
            "              ...resolvedOptionsPatch(target, nativeResolvedOptions),",
            "            });",
            "          }",
            "          return Reflect.get(target, prop, receiver);",
            "        },",
            "      });",
            "    };",
            "    for (const key of [...Object.getOwnPropertyNames(NativeCtor), ...Object.getOwnPropertySymbols(NativeCtor)]) {",
            "      if (key === 'prototype') {",
            "        continue;",
            "      }",
            "      try {",
            "        const descriptor = Object.getOwnPropertyDescriptor(NativeCtor, key);",
            "        if (!descriptor) {",
            "          continue;",
            "        }",
            "        if (typeof descriptor.value === 'function') {",
            "          descriptor.value = descriptor.value.bind(NativeCtor);",
            "        }",
            "        Object.defineProperty(PatchedCtor, key, descriptor);",
            "      } catch (_) {}",
            "    }",
            "    try {",
            "      Object.defineProperty(PatchedCtor, 'prototype', { value: NativeCtor.prototype });",
            "    } catch (_) {",
            "      PatchedCtor.prototype = NativeCtor.prototype;",
            "    }",
            "    try {",
            "      Object.defineProperty(PatchedCtor, 'toString', {",
            "        value: NativeCtor.toString.bind(NativeCtor),",
            "        configurable: true,",
            "      });",
            "    } catch (_) {}",
            "    Intl[name] = PatchedCtor;",
            "  };",
            "  patchIntlConstructor('DateTimeFormat', (target, resolvedOptions) => ({",
            "    locale: nativeLocaleOrFallback(resolvedOptions.call(target).locale),",
            "    ...(timezoneId ? { timeZone: timezoneId } : {}),",
            "  }));",
            "  patchIntlConstructor('NumberFormat', (target, resolvedOptions) => ({ locale: nativeLocaleOrFallback(resolvedOptions.call(target).locale) }));",
            "  patchIntlConstructor('Collator', (target, resolvedOptions) => ({ locale: nativeLocaleOrFallback(resolvedOptions.call(target).locale) }));",
            "  patchIntlConstructor('ListFormat', (target, resolvedOptions) => ({ locale: nativeLocaleOrFallback(resolvedOptions.call(target).locale) }));",
            "  patchIntlConstructor('PluralRules', (target, resolvedOptions) => ({ locale: nativeLocaleOrFallback(resolvedOptions.call(target).locale) }));",
            "})();",
        ]
    )


def build_performance_coherence_init_script() -> str:
    return "\n".join(
        [
            "(() => {",
            "  if (typeof Performance === 'undefined' || !Performance.prototype || typeof Performance.prototype.getEntriesByType !== 'function') {",
            "    return;",
            "  }",
            "  const nativeGetEntriesByType = Performance.prototype.getEntriesByType;",
            "  const monotonic = (previous, candidate, step) => {",
            "    const value = Number.isFinite(candidate) ? Number(candidate) : previous + step;",
            "    return Math.max(previous + step, value);",
            "  };",
            "  const normalizeNavigationEntry = (entry) => {",
            "    if (!entry || typeof entry !== 'object') {",
            "      return entry;",
            "    }",
            "    const fetchStart = Math.max(0.8, Number(entry.fetchStart) || 0.8);",
            "    const domainLookupStart = monotonic(fetchStart, entry.domainLookupStart, 0.4);",
            "    const domainLookupEnd = monotonic(domainLookupStart, entry.domainLookupEnd, 2.5);",
            "    const connectStart = monotonic(domainLookupEnd, entry.connectStart, 0.5);",
            "    const secureConnectionStart = monotonic(connectStart, entry.secureConnectionStart, 0.5);",
            "    const connectEnd = monotonic(secureConnectionStart, entry.connectEnd, 4.5);",
            "    const requestStart = monotonic(connectEnd, entry.requestStart, 1.8);",
            "    const responseStart = monotonic(requestStart, entry.responseStart, 65);",
            "    const responseEnd = monotonic(responseStart, entry.responseEnd, 38);",
            "    const domInteractive = monotonic(responseEnd, entry.domInteractive, 80);",
            "    const domContentLoadedEventStart = monotonic(domInteractive, entry.domContentLoadedEventStart, 18);",
            "    const domContentLoadedEventEnd = monotonic(domContentLoadedEventStart, entry.domContentLoadedEventEnd, 12);",
            "    const loadEventStart = monotonic(domContentLoadedEventEnd, entry.loadEventStart, 70);",
            "    const loadEventEnd = monotonic(loadEventStart, entry.loadEventEnd, 12);",
            "    const overrides = {",
            "      startTime: 0,",
            "      fetchStart,",
            "      domainLookupStart,",
            "      domainLookupEnd,",
            "      connectStart,",
            "      secureConnectionStart,",
            "      connectEnd,",
            "      requestStart,",
            "      responseStart,",
            "      responseEnd,",
            "      domInteractive,",
            "      domContentLoadedEventStart,",
            "      domContentLoadedEventEnd,",
            "      loadEventStart,",
            "      loadEventEnd,",
            "      duration: loadEventEnd,",
            "    };",
            "    return new Proxy(entry, {",
            "      get(target, prop, receiver) {",
            "        if (prop in overrides) {",
            "          return overrides[prop];",
            "        }",
            "        if (prop === 'toJSON') {",
            "          return () => ({ ...(typeof target.toJSON === 'function' ? target.toJSON() : {}), ...overrides });",
            "        }",
            "        return Reflect.get(target, prop, receiver);",
            "      },",
            "    });",
            "  };",
            "  Performance.prototype.getEntriesByType = function getEntriesByType(type) {",
            "    const entries = nativeGetEntriesByType.call(this, type);",
            "    if (String(type || '').toLowerCase() !== 'navigation' || !Array.isArray(entries)) {",
            "      return entries;",
            "    }",
            "    return entries.map(normalizeNavigationEntry);",
            "  };",
            "})();",
        ]
    )


crawler_runtime_settings = CrawlerRuntimeSettings()
