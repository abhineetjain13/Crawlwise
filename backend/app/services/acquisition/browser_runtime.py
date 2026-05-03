from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import logging
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from app.core.config import settings
from app.services.acquisition.browser_capture import (
    _MAX_CAPTURED_NETWORK_PAYLOADS,
    BrowserNetworkCapture as _BrowserNetworkCapture,
    _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES,
    _NETWORK_CAPTURE_QUEUE_SIZE,
    _NETWORK_CAPTURE_WORKERS,
    capture_browser_screenshot,
    classify_network_endpoint,
    read_network_payload_body,
    should_capture_network_payload,
)
from app.services.acquisition.browser_detail import (
    accessibility_expand_candidates_impl,
    expand_all_interactive_elements,
    expand_detail_content_if_needed_impl,
    expand_interactive_elements_via_accessibility,
    interactive_candidate_snapshot,
    requested_field_tokens,
)
from app.services.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE as _CHROMIUM_BROWSER_ENGINE,
    PATCHRIGHT_BROWSER_ENGINE as _PATCHRIGHT_BROWSER_ENGINE,
    REAL_CHROME_BROWSER_ENGINE as _REAL_CHROME_BROWSER_ENGINE,
    browser_failure_kind as _browser_failure_kind,
    browser_launch_mode as _browser_launch_mode,
    browser_profile as _browser_profile,
    browser_profile_diagnostics as _browser_profile_diagnostics,
    build_browser_diagnostics_contract,
    build_failed_browser_diagnostics,
    launch_headless_for_engine as _launch_headless_for_engine,
    normalize_browser_engine as _normalize_browser_engine,
    use_native_real_chrome_context as _use_native_real_chrome_context,
)
from app.services.acquisition.browser_identity import (
    PlaywrightContextSpec,
    build_playwright_context_spec,
    clear_browser_identity_cache,
)
from app.services.acquisition.cookie_store import (
    load_storage_state_for_domain,
    load_storage_state_for_run,
    persist_storage_state_for_domain,
    persist_storage_state_for_run,
)
from app.services.acquisition.browser_page_flow import (
    BrowserFinalizeInput,
    append_readiness_probe,
    dismiss_safe_location_interstitial,
    finalize_browser_fetch,
    navigate_browser_page_impl,
    remaining_timeout_factory,
    resolve_browser_fetch_policy as resolve_browser_fetch_policy_impl,
    serialize_browser_page_content_impl,
    settle_browser_page_impl,
)
from app.services.acquisition.browser_proxy_bridge import (
    Socks5AuthBridge,
    parse_socks5_upstream_proxy,
)
from app.services.acquisition.browser_proxy_config import (
    build_browser_proxy_config as _build_browser_proxy_config,
    display_proxy as _display_proxy,
    normalized_proxy_value as _normalized_proxy_value,
)
from app.services.acquisition.browser_readiness import (
    classify_browser_outcome_impl,
    classify_low_content_reason_impl,
    probe_browser_readiness_impl,
    wait_for_listing_readiness_impl,
)
from app.services.acquisition.browser_recovery import (
    emit_browser_behavior_activity,
    recover_browser_challenge,
)
from app.services.acquisition.browser_stage_runner import (
    run_browser_stage as _run_browser_stage,
)
from app.services.acquisition.dom_runtime import get_page_html
from app.services.acquisition.runtime import (
    BlockPageClassification,
    NetworkPayloadReadResult,
    classify_blocked_page_async,
    copy_headers,
    PageFetchResult,
    is_blocked_html_async,
)
from app.services.acquisition.traversal import (
    count_listing_cards,
    execute_listing_traversal,
    recover_listing_page_content,
    should_run_traversal,
)
from app.services.config.extraction_rules import (
    BROWSER_DETAIL_EXPAND_KEYWORDS,
    BROWSER_DETAIL_READINESS_HINTS,
    DETAIL_EXPAND_KEYWORD_EXTENSIONS,
)
from app.services.config.browser_fingerprint_profiles import (
    NATIVE_REAL_CHROME_CONTEXT_OPTIONS,
    WARMUP_ELIGIBLE_BROWSER_REASONS,
    WARMUP_VENDOR_BLOCK_PREFIX,
)
from app.services.config.network_capture import (
    BLOCKED_BROWSER_RESOURCE_TYPES,
    BLOCKED_BROWSER_ROUTE_TOKENS,
    PROTECTED_CHALLENGE_ROUTE_TOKENS,
)
from app.services.config.runtime_settings import (
    crawler_runtime_settings,
    proxy_rotation_mode,
)
from app.services.config.selectors import CARD_SELECTORS
from app.services.domain_utils import normalize_domain
from app.services.field_value_core import clean_text
from app.services.platform_policy import resolve_listing_readiness_override

if TYPE_CHECKING:
    from patchright.async_api import Browser, BrowserContext, Playwright

logger = logging.getLogger(__name__)

_RUN_STORAGE_PERSIST_ATTR = "_crawler_persist_run_storage_state"
_DOMAIN_STORAGE_PERSIST_ATTR = "_crawler_persist_domain_storage_state"
_BROWSERFORGE_ACTIVE_ATTR = "_crawler_browserforge_active"
_BROWSER_PREFERRED_HOST_TTL_SECONDS = 1800.0
_BROWSER_PREFERRED_HOSTS: dict[str, float] = {}
_BROWSER_PREFERRED_HOST_SUCCESSES: dict[str, tuple[int, float]] = {}
_DIRECT_BROWSER_RUNTIMES: dict[str, SharedBrowserRuntime] = {}
_PROXIED_BROWSER_RUNTIMES: dict[tuple[str, str], SharedBrowserRuntime] = {}
_BROWSER_RUNTIME_LOCK = asyncio.Lock()
_POPUP_GUARD_TASKS: set[asyncio.Task[Any]] = set()
_DETAIL_EXPAND_KEYWORDS: dict[str, tuple[str, ...]] = {
    str(key): tuple(str(item) for item in list(value or []))
    for key, value in dict(BROWSER_DETAIL_EXPAND_KEYWORDS or {}).items()
}
_DETAIL_READINESS_HINTS: dict[str, tuple[str, ...]] = {
    str(key): tuple(str(item) for item in list(value or []))
    for key, value in dict(BROWSER_DETAIL_READINESS_HINTS or {}).items()
}
_AOM_EXPAND_ROLES = {"button", "tab"}


def _patchright_async_playwright_factory():
    from patchright.async_api import async_playwright as patchright_async_playwright

    return patchright_async_playwright


def patchright_browser_available() -> bool:
    if not bool(crawler_runtime_settings.browser_patchright_enabled):
        return False
    try:
        _patchright_async_playwright_factory()
    except Exception:
        return False
    return True


def _real_chrome_candidate_paths() -> tuple[str, ...]:
    configured = str(
        crawler_runtime_settings.browser_real_chrome_executable_path or ""
    ).strip()
    if configured:
        return (configured,)
    return (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/opt/google/chrome/chrome",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    )


def real_chrome_executable_path() -> str | None:
    if not crawler_runtime_settings.browser_real_chrome_enabled:
        return None
    for candidate in _real_chrome_candidate_paths():
        if Path(candidate).is_file():
            return candidate
    return None


def real_chrome_browser_available() -> bool:
    return real_chrome_executable_path() is not None


def _should_run_behavior_realism(engine: str) -> bool:
    if not bool(crawler_runtime_settings.browser_behavior_realism_enabled):
        return False
    normalized_engine = _normalize_browser_engine(engine)
    return normalized_engine == _REAL_CHROME_BROWSER_ENGINE or not bool(
        crawler_runtime_settings.browser_behavior_real_chrome_only
    )


def _resolve_browser_binary(engine: str) -> tuple[str | None, str]:
    normalized_engine = _normalize_browser_engine(engine)
    if normalized_engine == _PATCHRIGHT_BROWSER_ENGINE:
        return None, _PATCHRIGHT_BROWSER_ENGINE
    if normalized_engine == _CHROMIUM_BROWSER_ENGINE:
        return None, _PATCHRIGHT_BROWSER_ENGINE
    executable_path = real_chrome_executable_path()
    if executable_path is None:
        return None, _REAL_CHROME_BROWSER_ENGINE
    return executable_path, executable_path


def _async_playwright_manager_for_engine(engine: str):
    normalized_engine = _normalize_browser_engine(engine)
    if normalized_engine in {_PATCHRIGHT_BROWSER_ENGINE, _CHROMIUM_BROWSER_ENGINE}:
        try:
            return _patchright_async_playwright_factory()
        except Exception as exc:
            raise RuntimeError(
                "Patchright package is not available for browser runtime"
            ) from exc
    try:
        return _patchright_async_playwright_factory()
    except Exception as exc:
        raise RuntimeError(
            "Patchright package is not available for real_chrome browser runtime"
        ) from exc


class SharedBrowserRuntime:
    def __init__(
        self,
        *,
        max_contexts: int,
        launch_proxy: str | None = None,
        browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    ) -> None:
        self.max_contexts = max(1, int(max_contexts))
        self.browser_engine = _normalize_browser_engine(browser_engine)
        self.executable_path, self.browser_binary = _resolve_browser_binary(
            self.browser_engine
        )
        self.engine_available = bool(
            (
                self.browser_engine
                in {_PATCHRIGHT_BROWSER_ENGINE, _CHROMIUM_BROWSER_ENGINE}
                and patchright_browser_available()
            )
            or self.executable_path
        )
        self.launch_proxy = _normalized_proxy_value(launch_proxy)
        self.launch_proxy_config = _build_browser_proxy_config(self.launch_proxy)
        self._authenticated_socks5_proxy = parse_socks5_upstream_proxy(
            self.launch_proxy
        )
        self._socks5_auth_bridge: Socks5AuthBridge | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(self.max_contexts)
        self._lock = asyncio.Lock()
        self._counter_lock = asyncio.Lock()
        self._stats_lock = asyncio.Lock()
        self._active_contexts = 0
        self._queued_count = 0
        self._total_contexts_created = 0
        self._browser_launched_at: float = 0.0
        self._last_used_at: float = time.monotonic()

    def _should_recycle_browser(self) -> bool:
        if self._browser is None:
            return False
        if not getattr(self._browser, "is_connected", lambda: True)():
            return True
        max_contexts = int(crawler_runtime_settings.browser_max_contexts_before_recycle)
        if max_contexts > 0 and self._total_contexts_created >= max_contexts:
            return True
        max_lifetime = int(crawler_runtime_settings.browser_max_lifetime_seconds)
        if max_lifetime > 0 and self._browser_launched_at > 0:
            if time.monotonic() - self._browser_launched_at >= max_lifetime:
                return True
        return False

    async def _ensure(self) -> None:
        if self._browser is not None and not self._should_recycle_browser():
            return
        async with self._lock:
            if self._should_recycle_browser():
                logger.info(
                    "Recycling browser instance (contexts=%d, lifetime=%.0fs)",
                    self._total_contexts_created,
                    time.monotonic() - self._browser_launched_at
                    if self._browser_launched_at
                    else 0,
                )
                await self._close_locked()
            if self._browser is not None:
                return
            async_playwright = _async_playwright_manager_for_engine(self.browser_engine)
            self._playwright = await async_playwright().start()
            launch_args = [
                str(value).strip()
                for value in list(crawler_runtime_settings.browser_launch_args or ())
                if str(value).strip()
            ]
            launch_headless = _launch_headless_for_engine(self.browser_engine)
            if (
                launch_headless
                and bool(crawler_runtime_settings.browser_use_new_headless)
                and "--headless=new" not in launch_args
            ):
                launch_args.append("--headless=new")
                launch_headless = False
            launch_kwargs: dict[str, Any] = {
                "headless": launch_headless,
            }
            if launch_args:
                launch_kwargs["args"] = launch_args
            if self.browser_engine == _REAL_CHROME_BROWSER_ENGINE:
                if not self.executable_path:
                    raise RuntimeError(
                        "Real Chrome executable is not available for browser runtime"
                    )
                launch_kwargs["executable_path"] = self.executable_path
                launch_kwargs["ignore_default_args"] = ["--enable-automation"]
            launch_proxy_config = await self._launch_proxy_config_for_browser()
            if launch_proxy_config is not None:
                launch_kwargs["proxy"] = launch_proxy_config
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)
            self._browser_launched_at = time.monotonic()
            async with self._counter_lock:
                self._total_contexts_created = 0

    async def _recycle_after_driver_disconnect(self) -> None:
        async with self._lock:
            await self._close_locked()
        await self._ensure()

    async def _open_context_page(
        self,
        *,
        context_options: dict[str, Any],
        context_spec: PlaywrightContextSpec,
    ) -> tuple[BrowserContext, Any]:
        last_error: Exception | None = None
        for attempt in range(2):
            if self._browser is None:
                raise RuntimeError("Browser runtime failed to initialize")
            context: BrowserContext | None = None
            try:
                context = await self._browser.new_context(**cast(Any, context_options))
                init_script = str(context_spec.init_script or "").strip()
                setattr(context, _BROWSERFORGE_ACTIVE_ATTR, bool(init_script))
                if init_script:
                    await context.add_init_script(init_script)
                await _configure_context_routes(context)
                async with self._counter_lock:
                    self._total_contexts_created += 1
                page = await context.new_page()
                return context, page
            except Exception as exc:
                last_error = exc
                if context is not None:
                    await _close_browser_context_safely(context)
                if attempt >= 1 or _browser_failure_kind(exc) not in {
                    "browser_driver_closed",
                    "page_closed",
                }:
                    raise
                logger.warning(
                    "Browser runtime disconnected during context bootstrap; recycling runtime"
                )
                await self._recycle_after_driver_disconnect()
        if last_error is not None:
            raise last_error
        raise RuntimeError("Browser runtime failed to create page context")

    async def _launch_proxy_config_for_browser(self) -> dict[str, str] | None:
        if self.launch_proxy_config is None:
            return None
        if self._authenticated_socks5_proxy is None:
            return dict(self.launch_proxy_config)
        if self._socks5_auth_bridge is None:
            self._socks5_auth_bridge = Socks5AuthBridge(
                self._authenticated_socks5_proxy
            )
        bridge_proxy = await self._socks5_auth_bridge.start()
        bridge_proxy_config = _build_browser_proxy_config(bridge_proxy)
        if bridge_proxy_config is None:
            raise RuntimeError("SOCKS5 auth bridge failed to expose a browser proxy")
        return bridge_proxy_config

    def touch(self) -> None:
        self._last_used_at = time.monotonic()

    def idle_seconds(self) -> float:
        return max(0.0, time.monotonic() - self._last_used_at)

    def bridge_used(self) -> bool:
        return self._socks5_auth_bridge is not None

    def eviction_key(self) -> tuple[int, float]:
        snapshot = self.snapshot()
        return (
            _int_or_zero(snapshot.get("active")) + _int_or_zero(snapshot.get("queued")),
            self._last_used_at,
        )

    def _build_context_spec(
        self,
        *,
        run_id: int | None = None,
        locality_profile: dict[str, object] | None = None,
        inject_init_script: bool = False,
    ) -> PlaywrightContextSpec:
        if _use_native_real_chrome_context(self.browser_engine):
            from app.services.acquisition.browser_identity import playwright_masking_init_script

            return PlaywrightContextSpec(
                context_options=dict(NATIVE_REAL_CHROME_CONTEXT_OPTIONS),
                init_script=playwright_masking_init_script()
                if inject_init_script
                else None,
            )
        browser_major_version = None
        if self._browser is not None:
            raw_version = str(getattr(self._browser, "version", "") or "")
            try:
                browser_major_version = int(raw_version.split(".", 1)[0])
            except ValueError:
                browser_major_version = None
        spec = build_playwright_context_spec(
            run_id=run_id,
            browser_major_version=browser_major_version,
            locality_profile=locality_profile,
            browser_engine=self.browser_engine,
        )
        if inject_init_script:
            return spec
        return PlaywrightContextSpec(
            context_options=dict(spec.context_options),
            init_script=None,
        )

    def _build_context_options(
        self,
        *,
        run_id: int | None = None,
        locality_profile: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        return dict(
            self._build_context_spec(
                run_id=run_id,
                locality_profile=locality_profile,
            ).context_options
        )

    @asynccontextmanager
    async def page(
        self,
        *,
        proxy: str | None = None,
        run_id: int | None = None,
        domain: str | None = None,
        locality_profile: dict[str, object] | None = None,
        allow_storage_state: bool = True,
        inject_init_script: bool = False,
    ):
        normalized_proxy = _normalized_proxy_value(proxy)
        if self.launch_proxy is None:
            if normalized_proxy is not None:
                raise RuntimeError(
                    "Proxied browser pages require a launch-owned browser runtime"
                )
        elif normalized_proxy not in {None, self.launch_proxy}:
            raise RuntimeError("Browser runtime proxy does not match requested proxy")
        self.touch()
        await self._ensure()
        await self._update_queue_count(1)
        try:
            await self._semaphore.acquire()
        except Exception:
            await self._update_queue_count(-1)
            raise
        await self._update_queue_count(-1)
        if self._browser is None:
            self._semaphore.release()
            raise RuntimeError("Browser runtime failed to initialize")
        context: BrowserContext | None = None
        await self._update_active_contexts(1)
        try:
            context_spec = self._build_context_spec(
                run_id=run_id,
                locality_profile=locality_profile,
                inject_init_script=inject_init_script,
            )
            context_options = dict(context_spec.context_options)
            allow_domain_storage_state = bool(
                allow_storage_state
                and (
                    self.launch_proxy is None
                    or bool(
                        crawler_runtime_settings.browser_proxy_domain_storage_enabled
                    )
                )
            )
            if allow_storage_state:
                storage_state = await _load_storage_state_for_run(
                    run_id,
                    browser_engine=self.browser_engine,
                )
                if not storage_state and allow_domain_storage_state:
                    storage_state = await _load_storage_state_for_domain(
                        domain,
                        browser_engine=self.browser_engine,
                    )
                if storage_state:
                    context_options["storage_state"] = storage_state
            context, page = await self._open_context_page(
                context_options=context_options,
                context_spec=context_spec,
            )
            yield page
        finally:
            await self._update_active_contexts(-1)
            if context is not None:
                await _persist_context_storage_state(
                    context,
                    run_id=run_id,
                    domain=domain,
                    browser_engine=self.browser_engine,
                    persist_run_storage_state=bool(
                        getattr(context, _RUN_STORAGE_PERSIST_ATTR, True)
                    ),
                    persist_domain_storage_state=bool(
                        allow_domain_storage_state
                        and bool(getattr(context, _DOMAIN_STORAGE_PERSIST_ATTR, True))
                    ),
                    timeout_seconds=_browser_context_timeout_seconds(),
                )
                await _close_browser_context_safely(context)
            self._semaphore.release()

    async def close(self) -> None:
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        if self._browser is not None:
            try:
                await asyncio.wait_for(
                    self._browser.close(),
                    timeout=_browser_close_timeout_seconds(),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out closing browser runtime after %.1fs",
                    _browser_close_timeout_seconds(),
                )
            except Exception:
                logger.debug("Failed to close browser", exc_info=True)
        if self._playwright is not None:
            try:
                await asyncio.wait_for(
                    self._playwright.stop(),
                    timeout=_browser_close_timeout_seconds(),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out stopping playwright after %.1fs",
                    _browser_close_timeout_seconds(),
                )
            except Exception:
                logger.debug("Failed to stop playwright", exc_info=True)
        if self._socks5_auth_bridge is not None:
            try:
                await asyncio.wait_for(
                    self._socks5_auth_bridge.close(),
                    timeout=_browser_close_timeout_seconds(),
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Timed out closing SOCKS5 auth bridge after %.1fs",
                    _browser_close_timeout_seconds(),
                )
            except Exception:
                logger.debug("Failed to close SOCKS5 auth bridge", exc_info=True)
        self._browser = None
        self._playwright = None
        self._socks5_auth_bridge = None
        self._browser_launched_at = 0.0

    async def _update_active_contexts(self, delta: int) -> None:
        async with self._stats_lock:
            self._active_contexts = max(0, self._active_contexts + delta)

    async def _update_queue_count(self, delta: int) -> None:
        async with self._stats_lock:
            self._queued_count = max(0, self._queued_count + delta)

    def snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "ready": self._browser is not None,
            "size": self._active_contexts,
            "max_size": self.max_contexts,
            "active": self._active_contexts,
            "queued": self._queued_count,
            "capacity": self.max_contexts,
            "total_contexts_created": self._total_contexts_created,
            "browser_lifetime_seconds": int(
                time.monotonic() - self._browser_launched_at
            )
            if self._browser_launched_at
            else 0,
            "browser_engine": self.browser_engine,
            **_browser_profile_diagnostics(self.browser_engine),
            "bridge_used": self.bridge_used(),
        }
        return snapshot


async def _configure_context_routes(context: Any) -> None:
    try:
        await context.route("**/*", _block_unneeded_route)
    except Exception:
        logger.debug("Failed to install browser request blocking", exc_info=True)


async def _block_unneeded_route(route: Any) -> None:
    request = getattr(route, "request", None)
    resource_type = str(getattr(request, "resource_type", "") or "").lower()
    request_url = str(getattr(request, "url", "") or "").lower()
    if any(token in request_url for token in PROTECTED_CHALLENGE_ROUTE_TOKENS):
        try:
            await route.continue_()
            return
        except Exception:
            logger.debug(
                "Browser request continue failed for protected challenge url=%s",
                request_url,
                exc_info=True,
            )
            return
    should_abort = resource_type in BLOCKED_BROWSER_RESOURCE_TYPES or any(
        token in request_url for token in BLOCKED_BROWSER_ROUTE_TOKENS
    )
    if should_abort:
        try:
            await route.abort()
            return
        except Exception:
            logger.debug(
                "Browser request abort failed for resource_type=%s url=%s; attempting continue",
                resource_type,
                request_url,
                exc_info=True,
            )
            try:
                await route.continue_()
                return
            except Exception:
                logger.debug(
                    "Browser request continue failed after abort failure for resource_type=%s url=%s",
                    resource_type,
                    request_url,
                    exc_info=True,
                )
                return
    try:
        await route.continue_()
    except Exception:
        logger.debug(
            "Browser request continue failed for resource_type=%s url=%s",
            resource_type,
            request_url,
            exc_info=True,
        )


@asynccontextmanager
async def temporary_browser_page(
    *,
    proxy: str,
    run_id: int | None = None,
    domain: str | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    locality_profile: dict[str, object] | None = None,
    allow_storage_state: bool = True,
):
    runtime = await get_browser_runtime(proxy=proxy, browser_engine=browser_engine)
    async with runtime.page(
        run_id=run_id,
        domain=domain,
        locality_profile=locality_profile,
        allow_storage_state=allow_storage_state,
    ) as page:
        yield page


async def _evict_idle_browser_runtimes_locked() -> None:
    idle_ttl_seconds = max(
        0, int(crawler_runtime_settings.browser_runtime_pool_idle_ttl_seconds)
    )
    max_entries = max(1, int(crawler_runtime_settings.browser_runtime_pool_max_entries))
    pools = (
        ("direct", _DIRECT_BROWSER_RUNTIMES),
        ("proxied", _PROXIED_BROWSER_RUNTIMES),
    )
    candidates: list[tuple[str, str | tuple[str, str], SharedBrowserRuntime]] = []
    for pool_name, pool in pools:
        for key, runtime in list(pool.items()):
            active_and_queued, _last_used = runtime.eviction_key()
            if active_and_queued > 0:
                continue
            if idle_ttl_seconds > 0 and runtime.idle_seconds() >= idle_ttl_seconds:
                if pool_name == "direct":
                    normalized_key: str | tuple[str, str] = str(key)
                elif isinstance(key, tuple) and len(key) == 2:
                    normalized_key = (str(key[0]), str(key[1]))
                else:
                    continue
                candidates.append((pool_name, normalized_key, runtime))
    while sum(len(pool) for _pool_name, pool in pools) - len(candidates) >= max_entries:
        candidate_keys = {(pool_name, key) for pool_name, key, _runtime in candidates}
        remaining: list[tuple[str, str | tuple[str, str], SharedBrowserRuntime]] = []
        for pool_name, pool in pools:
            for key, runtime in list(pool.items()):
                if runtime.eviction_key()[0] != 0:
                    continue
                normalized_remaining_key: str | tuple[str, str]
                if pool_name == "direct":
                    normalized_remaining_key = str(key)
                elif isinstance(key, tuple) and len(key) == 2:
                    normalized_remaining_key = (str(key[0]), str(key[1]))
                else:
                    continue
                if (pool_name, normalized_remaining_key) in candidate_keys:
                    continue
                remaining.append((pool_name, normalized_remaining_key, runtime))
        if not remaining:
            break
        remaining.sort(key=lambda item: item[2].eviction_key())
        candidates.append(remaining[0])
    for pool_name, key, runtime in candidates:
        if pool_name == "direct":
            _DIRECT_BROWSER_RUNTIMES.pop(str(key), None)
        else:
            proxied_key = key if isinstance(key, tuple) and len(key) == 2 else None
            if proxied_key is not None:
                _PROXIED_BROWSER_RUNTIMES.pop(proxied_key, None)
        await runtime.close()


async def get_browser_runtime(
    *,
    proxy: str | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
) -> SharedBrowserRuntime:
    global _DIRECT_BROWSER_RUNTIMES, _PROXIED_BROWSER_RUNTIMES
    normalized_proxy = _normalized_proxy_value(proxy)
    normalized_engine = _normalize_browser_engine(browser_engine)
    if normalized_proxy is None:
        runtime = _DIRECT_BROWSER_RUNTIMES.get(normalized_engine)
        if runtime is not None:
            runtime.touch()
            return runtime
    else:
        runtime = _PROXIED_BROWSER_RUNTIMES.get((normalized_engine, normalized_proxy))
        if runtime is not None:
            runtime.touch()
            return runtime
    async with _BROWSER_RUNTIME_LOCK:
        if normalized_proxy is None:
            runtime = _DIRECT_BROWSER_RUNTIMES.get(normalized_engine)
            if runtime is None:
                await _evict_idle_browser_runtimes_locked()
                runtime = SharedBrowserRuntime(
                    max_contexts=settings.browser_pool_size,
                    browser_engine=normalized_engine,
                )
                _DIRECT_BROWSER_RUNTIMES[normalized_engine] = runtime
            runtime.touch()
            return runtime
        await _evict_idle_browser_runtimes_locked()
        runtime = _PROXIED_BROWSER_RUNTIMES.get((normalized_engine, normalized_proxy))
        if runtime is None:
            runtime = SharedBrowserRuntime(
                max_contexts=settings.browser_pool_size,
                launch_proxy=normalized_proxy,
                browser_engine=normalized_engine,
            )
            _PROXIED_BROWSER_RUNTIMES[(normalized_engine, normalized_proxy)] = runtime
        runtime.touch()
        return runtime


async def shutdown_browser_runtime() -> None:
    global _DIRECT_BROWSER_RUNTIMES, _PROXIED_BROWSER_RUNTIMES
    async with _BROWSER_RUNTIME_LOCK:
        runtimes = [
            runtime
            for runtime in (
                *_DIRECT_BROWSER_RUNTIMES.values(),
                *_PROXIED_BROWSER_RUNTIMES.values(),
            )
            if runtime is not None
        ]
        _DIRECT_BROWSER_RUNTIMES = {}
        _PROXIED_BROWSER_RUNTIMES = {}
    for runtime in runtimes:
        await runtime.close()
    clear_browser_identity_cache()


def shutdown_browser_runtime_sync() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(shutdown_browser_runtime())
        return
    try:
        loop_thread_id = getattr(loop, "_thread_id")
    except Exception:
        loop_thread_id = None
    if loop_thread_id is not None and loop_thread_id != threading.get_ident():
        future = asyncio.run_coroutine_threadsafe(shutdown_browser_runtime(), loop)
        try:
            future.result(timeout=_browser_shutdown_timeout_seconds())
        except concurrent.futures.TimeoutError:
            logger.warning("Timed out waiting for browser runtime shutdown to complete")
        except Exception:
            logger.exception("Browser runtime shutdown task failed")
        return
    # When called from the event loop thread, waiting synchronously would deadlock
    # the loop, so shutdown remains best-effort and logs completion asynchronously.
    task = loop.create_task(shutdown_browser_runtime())
    task.add_done_callback(_log_shutdown_task_result)


def browser_runtime_snapshot() -> dict[str, int | bool]:
    runtimes = [
        runtime
        for runtime in (
            *_DIRECT_BROWSER_RUNTIMES.values(),
            *_PROXIED_BROWSER_RUNTIMES.values(),
        )
        if runtime is not None
    ]
    if not runtimes:
        max_size = max(1, int(settings.browser_pool_size))
        return {
            "ready": False,
            "size": 0,
            "max_size": max_size,
            "active": 0,
            "queued": 0,
            "capacity": max_size,
        }
    snapshots = [runtime.snapshot() for runtime in runtimes]
    max_size = sum(
        _snapshot_count(snapshot, "max_size", "capacity") for snapshot in snapshots
    )
    capacity = sum(
        _snapshot_count(snapshot, "capacity", "max_size") for snapshot in snapshots
    )
    return {
        "ready": any(bool(snapshot.get("ready")) for snapshot in snapshots),
        "size": sum(_int_or_zero(snapshot.get("size")) for snapshot in snapshots),
        "max_size": max_size,
        "active": sum(_int_or_zero(snapshot.get("active")) for snapshot in snapshots),
        "queued": sum(_int_or_zero(snapshot.get("queued")) for snapshot in snapshots),
        "capacity": capacity,
        "total_contexts_created": sum(
            _int_or_zero(snapshot.get("total_contexts_created"))
            for snapshot in snapshots
        ),
        "browser_lifetime_seconds": max(
            _int_or_zero(snapshot.get("browser_lifetime_seconds"))
            for snapshot in snapshots
        ),
    }


def _log_shutdown_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        logger.debug("Browser runtime shutdown task was cancelled")
    except Exception:
        logger.exception("Browser runtime shutdown task failed")


async def _persist_context_storage_state(
    context: Any,
    *,
    run_id: int | None,
    domain: str | None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    persist_run_storage_state: bool = True,
    persist_domain_storage_state: bool = True,
    timeout_seconds: float | None = None,
) -> None:
    normalized_domain = str(domain or "").strip()
    if run_id is None and not normalized_domain:
        return
    storage_state_fn = getattr(context, "storage_state", None)
    if storage_state_fn is None:
        return
    resolved_timeout_seconds = max(
        0.1,
        float(
            timeout_seconds
            if timeout_seconds is not None
            else _browser_context_timeout_seconds()
        ),
    )
    try:
        storage_state = await asyncio.wait_for(
            storage_state_fn(),
            timeout=resolved_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out capturing browser storage state for run_id=%s domain=%s after %.1fs",
            run_id,
            normalized_domain or None,
            resolved_timeout_seconds,
        )
        return
    except Exception:
        logger.debug(
            "Failed to capture browser storage state for run_id=%s",
            run_id,
            exc_info=True,
        )
        return
    if run_id is not None and persist_run_storage_state:
        try:
            await _persist_storage_state_for_run(
                run_id,
                storage_state,
                browser_engine=browser_engine,
            )
        except Exception:
            logger.error(
                "Failed to persist browser storage state for run_id=%s",
                run_id,
                exc_info=True,
            )
    if normalized_domain and persist_domain_storage_state:
        try:
            await _persist_storage_state_for_domain(
                normalized_domain,
                storage_state,
                browser_engine=browser_engine,
            )
        except Exception:
            logger.error(
                "Failed to persist browser storage state for domain=%s",
                normalized_domain,
                exc_info=True,
            )


async def _load_storage_state_for_run(
    run_id: int | None,
    *,
    browser_engine: str,
) -> dict[str, object] | None:
    return await load_storage_state_for_run(
        run_id,
        browser_engine=browser_engine,
    )


async def _load_storage_state_for_domain(
    domain: str | None,
    *,
    browser_engine: str,
) -> dict[str, object] | None:
    return await load_storage_state_for_domain(
        domain,
        browser_engine=browser_engine,
    )


async def _persist_storage_state_for_run(
    run_id: int | None,
    storage_state,
    *,
    browser_engine: str,
) -> None:
    await persist_storage_state_for_run(
        run_id,
        storage_state,
        browser_engine=browser_engine,
    )


async def _persist_storage_state_for_domain(
    domain: str | None,
    storage_state,
    *,
    browser_engine: str,
) -> bool:
    return await persist_storage_state_for_domain(
        domain,
        storage_state,
        browser_engine=browser_engine,
    )


def _mark_storage_state_persist_policy(
    page: Any,
    *,
    persist_run_storage_state: bool,
    persist_domain_storage_state: bool,
) -> None:
    context = getattr(page, "context", None)
    if callable(context):
        try:
            context = context()
        except Exception:
            return
    if context is None:
        return
    with suppress(Exception):
        setattr(context, _RUN_STORAGE_PERSIST_ATTR, persist_run_storage_state)
    with suppress(Exception):
        setattr(context, _DOMAIN_STORAGE_PERSIST_ATTR, persist_domain_storage_state)


def _browser_context_timeout_seconds() -> float:
    return max(
        0.1,
        float(crawler_runtime_settings.browser_context_timeout_ms) / 1000,
    )


def _browser_close_timeout_seconds() -> float:
    return max(
        0.1,
        float(crawler_runtime_settings.browser_close_timeout_ms) / 1000,
    )


def _browser_shutdown_timeout_seconds() -> float:
    try:
        return max(
            0.1, float(crawler_runtime_settings.browser_shutdown_timeout_seconds)
        )
    except (TypeError, ValueError):
        logger.warning(
            "Invalid browser_shutdown_timeout_seconds=%r; using 10.0s",
            crawler_runtime_settings.browser_shutdown_timeout_seconds,
        )
        return 10.0


async def _close_browser_context_safely(context: Any) -> None:
    try:
        await asyncio.wait_for(
            context.close(),
            timeout=_browser_close_timeout_seconds(),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out closing browser context after %.1fs",
            _browser_close_timeout_seconds(),
        )
    except asyncio.CancelledError:
        logger.warning("Browser context close was cancelled")
    except Exception:
        logger.debug("Failed to close browser context", exc_info=True)


def _build_payload_capture(*, surface: str) -> _BrowserNetworkCapture:
    return _BrowserNetworkCapture(
        surface=surface,
        should_capture_payload=should_capture_network_payload,
        classify_endpoint=classify_network_endpoint,
        read_payload_body=read_network_payload_body,
    )


def _normalize_surface(surface: str | None) -> str:
    return str(surface or "").strip().lower()


def _mapping_value(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _snapshot_count(snapshot: dict[str, object], *keys: str) -> int:
    for key in keys:
        value = snapshot.get(key)
        if value is not None:
            return _int_or_zero(value)
    return 0


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    normalized = str(value or "").strip()
    if not normalized:
        return 0
    try:
        return int(normalized)
    except (TypeError, ValueError):
        return 0


def _proxy_requires_fresh_browser_state(
    proxy_profile: dict[str, object] | None,
) -> bool:
    return proxy_rotation_mode(proxy_profile) == "rotating"


def _surface_supports_origin_warmup(surface: str) -> bool:
    normalized_surface = _normalize_surface(surface)
    return "detail" in normalized_surface


def _browser_proxy_mode(
    *,
    proxy: str | None,
    proxied_page_factory,
) -> str:
    if not proxy:
        return "direct"
    if proxied_page_factory is temporary_browser_page:
        return "launch"
    return "page"


def _network_payload_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


async def _resolve_runtime_provider(
    runtime_provider,
    *,
    browser_engine: str,
    proxy: str | None = None,
):
    if proxy is not None and _callable_accepts_keyword(runtime_provider, "proxy"):
        return await runtime_provider(proxy=proxy, browser_engine=browser_engine)
    return await runtime_provider(browser_engine=browser_engine)


def _callable_accepts_keyword(candidate: Any, keyword: str) -> bool:
    try:
        parameters = inspect.signature(candidate).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        or (
            parameter.kind
            in {inspect.Parameter.KEYWORD_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
            and parameter.name == keyword
        )
        for parameter in parameters
    )


def _resolve_proxied_page_factory(
    proxied_page_factory,
    *,
    proxy: str,
    run_id: int | None,
    domain: str | None,
    browser_engine: str,
    locality_profile: dict[str, object] | None,
    allow_storage_state: bool,
):
    return proxied_page_factory(
        proxy=proxy,
        run_id=run_id,
        domain=domain,
        browser_engine=browser_engine,
        locality_profile=locality_profile,
        allow_storage_state=allow_storage_state,
    )


async def browser_fetch(
    url: str,
    timeout_seconds: float,
    *,
    run_id: int | None = None,
    proxy: str | None = None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    browser_reason: str | None = None,
    escalation_lane: str | None = None,
    host_policy_snapshot: dict[str, object] | None = None,
    proxy_profile: dict[str, object] | None = None,
    locality_profile: dict[str, object] | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    requested_fields: list[str] | None = None,
    listing_recovery_mode: str | None = None,
    capture_page_markdown: bool = True,
    capture_screenshot: bool = False,
    max_pages: int = 1,
    max_scrolls: int = 1,
    max_records: int | None = None,
    on_event=None,
    runtime_provider=get_browser_runtime,
    proxied_page_factory=temporary_browser_page,
    blocked_html_checker=is_blocked_html_async,
) -> PageFetchResult:
    normalized_domain = normalize_domain(url)
    normalized_engine = _normalize_browser_engine(browser_engine)
    resolved_proxy_rotation_mode = proxy_rotation_mode(proxy_profile)
    phase_timings_ms: dict[str, int] = {}
    runtime_engine = normalized_engine
    runtime_binary = normalized_engine
    # Rotating proxies must not reuse cookies/localStorage from a prior IP identity.
    allow_storage_state = not _proxy_requires_fresh_browser_state(proxy_profile)
    browser_proxy_mode = _browser_proxy_mode(
        proxy=proxy,
        proxied_page_factory=proxied_page_factory,
    )
    runtime_bridge_used = browser_proxy_mode == "page"
    runtime: SharedBrowserRuntime | None = None
    payload_capture = None
    popup_guard_registrations: list[tuple[Any, str, Any]] = []
    try:
        if proxy:
            if proxied_page_factory is temporary_browser_page:
                runtime = await _resolve_runtime_provider(
                    runtime_provider,
                    browser_engine=normalized_engine,
                    proxy=proxy,
                )
                page_context = runtime.page(
                    run_id=run_id,
                    domain=normalized_domain,
                    locality_profile=locality_profile,
                    allow_storage_state=allow_storage_state,
                )
            else:
                page_context = _resolve_proxied_page_factory(
                    proxied_page_factory,
                    proxy=proxy,
                    run_id=run_id,
                    domain=normalized_domain,
                    browser_engine=normalized_engine,
                    locality_profile=locality_profile,
                    allow_storage_state=allow_storage_state,
                )
        else:
            runtime = await _resolve_runtime_provider(
                runtime_provider,
                browser_engine=normalized_engine,
            )
            page_context = runtime.page(
                run_id=run_id,
                domain=normalized_domain,
                locality_profile=locality_profile,
                allow_storage_state=allow_storage_state,
            )
        async with page_context as page:
            runtime_engine = (
                str(getattr(runtime, "browser_engine", "") or "").strip().lower()
                if runtime is not None
                else ""
            ) or normalized_engine
            runtime_binary = (
                str(getattr(runtime, "browser_binary", "") or "").strip()
                if runtime is not None
                else ""
            ) or runtime_engine
            bridge_flag = (
                getattr(runtime, "bridge_used", None) if runtime is not None else None
            )
            runtime_bridge_used = (
                bool(bridge_flag()) if callable(bridge_flag) else False
            )
            await _emit_browser_event(
                on_event,
                "info",
                (
                    f"Launched {_browser_launch_mode(runtime_engine)} browser "
                    f"({runtime_engine}, profile: {_browser_profile(runtime_engine)}, "
                    f"proxy: {_display_proxy(proxy)}, binary: {runtime_binary})"
                ),
            )
            if resolved_proxy_rotation_mode == "rotating":
                await _emit_browser_event(
                    on_event,
                    "info",
                    "Rotating proxy profile detected; skipping origin warmup",
                )
            started_at = time.perf_counter()
            _remaining = remaining_timeout_factory(started_at + float(timeout_seconds))
            normalized_surface = _normalize_surface(surface)
            payload_capture = _build_payload_capture(surface=normalized_surface)
            payload_capture.attach(page)
            traversal_active, readiness_policy, readiness_override = (
                resolve_browser_fetch_policy_impl(
                    url=url,
                    surface=normalized_surface,
                    traversal_mode=traversal_mode,
                    should_run_traversal=should_run_traversal,
                )
            )
            try:
                pre_nav_pause_ms = max(
                    0, int(crawler_runtime_settings.browser_first_nav_pause_ms)
                )
                if pre_nav_pause_ms > 0 and normalized_surface.startswith("ecommerce_"):
                    await page.wait_for_timeout(pre_nav_pause_ms)
                await _maybe_warm_origin_before_navigation(
                    page,
                    url=url,
                    surface=normalized_surface,
                    browser_engine=runtime_engine,
                    browser_reason=browser_reason,
                    proxy_profile=proxy_profile,
                    timeout_seconds=_remaining(),
                    phase_timings_ms=phase_timings_ms,
                )
                popup_guard_registrations = _install_popup_guard(
                    page, on_event=on_event
                )
                response, navigation_strategy = await _run_browser_stage(
                    stage="navigation",
                    page=page,
                    timeout_seconds=_remaining(),
                    phase_timings_ms=phase_timings_ms,
                    operation=lambda: _navigate_browser_page(
                        page,
                        url=url,
                        timeout_seconds=_remaining(),
                        phase_timings_ms=phase_timings_ms,
                        readiness_policy=readiness_policy,
                    ),
                )
                page_title = ""
                try:
                    page_title = clean_text(await page.title())
                except Exception:
                    page_title = ""
                await _emit_browser_event(
                    on_event,
                    "info",
                    (
                        f"Page loaded in {phase_timings_ms.get('navigation', 0)}ms"
                        + (f' - title="{page_title}"' if page_title else "")
                    ),
                )
                interstitial_started_at = time.perf_counter()
                interstitial_diagnostics = await dismiss_safe_location_interstitial(
                    page
                )
                phase_timings_ms["interstitial_dismissal"] = _elapsed_ms(
                    interstitial_started_at
                )
                if interstitial_diagnostics.get("status") == "dismissed":
                    await _emit_browser_event(
                        on_event,
                        "info",
                        (
                            "Dismissed location interstitial via "
                            f"{interstitial_diagnostics.get('selector')}"
                        ),
                    )
                behavior_diagnostics: dict[str, object] = {}
                if _should_run_behavior_realism(runtime_engine):
                    behavior_started_at = time.perf_counter()
                    behavior_diagnostics = await emit_browser_behavior_activity(page)
                    phase_timings_ms["behavior_realism"] = _elapsed_ms(
                        behavior_started_at
                    )
                (
                    current_probe,
                    readiness_probes,
                    networkidle_timed_out,
                    networkidle_skip_reason,
                    readiness_diagnostics,
                    expansion_diagnostics,
                ) = await _run_browser_stage(
                    stage="settle",
                    page=page,
                    timeout_seconds=_remaining(),
                    phase_timings_ms=phase_timings_ms,
                    operation=lambda: _settle_browser_page(
                        page,
                        url=url,
                        surface=normalized_surface,
                        requested_fields=requested_fields,
                        timeout_seconds=_remaining(),
                        readiness_override=readiness_override,
                        readiness_policy=readiness_policy,
                        phase_timings_ms=phase_timings_ms,
                    ),
                )
                (
                    html,
                    traversal_result,
                    rendered_html,
                    listing_recovery_diagnostics,
                    page_markdown,
                ) = await _run_browser_stage(
                    stage="serialize",
                    page=page,
                    timeout_seconds=max(
                        _remaining(),
                        float(
                            crawler_runtime_settings.browser_capture_read_timeout_seconds
                        ),
                    ),
                    phase_timings_ms=phase_timings_ms,
                    operation=lambda: _serialize_browser_page_content(
                        page,
                        surface=normalized_surface,
                        traversal_mode=traversal_mode,
                        listing_recovery_mode=listing_recovery_mode,
                        traversal_active=traversal_active,
                        timeout_seconds=_remaining(),
                        max_pages=max_pages,
                        max_scrolls=max_scrolls,
                        max_records=max_records,
                        capture_page_markdown=capture_page_markdown,
                        phase_timings_ms=phase_timings_ms,
                        on_event=on_event,
                    ),
                )
                finalized = await _run_browser_stage(
                    stage="finalize",
                    page=page,
                    timeout_seconds=max(
                        _remaining(),
                        float(
                            crawler_runtime_settings.browser_capture_read_timeout_seconds
                        ),
                    ),
                    phase_timings_ms=phase_timings_ms,
                    operation=lambda: finalize_browser_fetch(
                        BrowserFinalizeInput(
                            page=page,
                            url=url,
                            surface=normalized_surface,
                            browser_reason=browser_reason,
                            on_event=on_event,
                            response=response,
                            navigation_strategy=navigation_strategy,
                            readiness_probes=readiness_probes,
                            networkidle_timed_out=networkidle_timed_out,
                            networkidle_skip_reason=networkidle_skip_reason,
                            readiness_policy=readiness_policy,
                            readiness_diagnostics=readiness_diagnostics,
                            expansion_diagnostics=expansion_diagnostics,
                            listing_recovery_diagnostics=listing_recovery_diagnostics,
                            payload_capture=payload_capture,
                            html=html,
                            traversal_result=traversal_result,
                            rendered_html=rendered_html,
                            page_markdown=page_markdown,
                            interstitial_diagnostics=interstitial_diagnostics,
                            phase_timings_ms=phase_timings_ms,
                            started_at=started_at,
                            capture_screenshot=bool(capture_screenshot),
                        ),
                        blocked_html_checker=blocked_html_checker,
                        classify_blocked_page_async=classify_blocked_page_async,
                        classify_low_content_reason=classify_low_content_reason,
                        classify_browser_outcome=classify_browser_outcome,
                        capture_browser_screenshot=capture_browser_screenshot,
                        emit_browser_event=_emit_browser_event,
                        elapsed_ms=_elapsed_ms,
                    ),
                )
                finalized_status_code = finalized.get("status_code", 0)
                finalized_platform_family = (
                    str(finalized.get("platform_family") or "").strip() or None
                )
                finalized_diagnostics = _mapping_value(finalized.get("diagnostics"))
                diagnostics = build_browser_diagnostics_contract(
                    diagnostics={
                        **finalized_diagnostics,
                        "bridge_used": runtime_bridge_used,
                        "browser_proxy_mode": browser_proxy_mode,
                        "escalation_lane": str(escalation_lane or "").strip().lower()
                        or None,
                        "host_policy_snapshot": dict(host_policy_snapshot or {}),
                        "proxy_rotation_mode": resolved_proxy_rotation_mode,
                        "browser_state_reuse_allowed": allow_storage_state,
                        "behavior_realism": dict(behavior_diagnostics),
                    },
                    browser_reason=browser_reason,
                    browser_outcome=str(
                        finalized_diagnostics.get("browser_outcome") or ""
                    ),
                    browser_engine=runtime_engine,
                    browser_binary=runtime_binary,
                )
                _mark_storage_state_persist_policy(
                    page,
                    persist_run_storage_state=allow_storage_state
                    and not bool(finalized["blocked"]),
                    persist_domain_storage_state=allow_storage_state
                    and not bool(finalized["blocked"]),
                )
                return PageFetchResult(
                    url=url,
                    final_url=page.url,
                    html=html,
                    status_code=int(str(finalized_status_code or 0)),
                    method="browser",
                    content_type=str(finalized["content_type"]),
                    blocked=bool(finalized["blocked"]),
                    platform_family=finalized_platform_family,
                    headers=copy_headers(finalized.get("page_headers")),
                    network_payloads=_network_payload_rows(
                        finalized.get("network_payloads")
                    ),
                    browser_diagnostics=diagnostics,
                    artifacts=_mapping_value(finalized.get("artifacts")),
                    page_markdown=str(finalized.get("page_markdown") or ""),
                )
            finally:
                _remove_popup_guard(popup_guard_registrations)
                if payload_capture is not None:
                    await payload_capture.close(page)
    except Exception as exc:
        setattr(exc, "browser_proxy_mode", browser_proxy_mode)
        setattr(
            exc,
            "browser_phase_timings_ms",
            dict(locals().get("phase_timings_ms") or {}),
        )
        setattr(
            exc,
            "browser_diagnostics",
            build_failed_browser_diagnostics(
                browser_reason=browser_reason,
                exc=exc,
                proxy=proxy,
                browser_engine=runtime_engine,
                browser_binary=runtime_binary,
                bridge_used=runtime_bridge_used,
                escalation_lane=escalation_lane,
                host_policy_snapshot=host_policy_snapshot,
            ),
        )
        raise


async def _maybe_warm_origin_before_navigation(
    page: Any,
    *,
    url: str,
    surface: str,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    browser_reason: str | None,
    proxy_profile: dict[str, object] | None,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
) -> None:
    normalized_surface = str(surface or "").strip().lower()
    if not _surface_supports_origin_warmup(normalized_surface):
        return
    if _proxy_requires_fresh_browser_state(proxy_profile):
        return
    reason = str(browser_reason or "").strip().lower()
    if not (
        reason in WARMUP_ELIGIBLE_BROWSER_REASONS
        or reason.startswith(WARMUP_VENDOR_BLOCK_PREFIX)
    ):
        return
    warm_pause_ms = max(0, int(crawler_runtime_settings.origin_warm_pause_ms or 0))
    if warm_pause_ms <= 0:
        return
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return
    warm_url = f"{parsed.scheme}://{parsed.netloc}/"
    if warm_url.rstrip("/") == str(url or "").strip().rstrip("/"):
        return
    warm_budget_ms = min(
        int(max(0.1, float(timeout_seconds)) * 1000),
        int(crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms),
    )
    if warm_budget_ms < 750:
        return
    started_at = time.perf_counter()
    context = getattr(page, "context", None)
    if callable(context):
        with suppress(Exception):
            context = context()
    new_page = getattr(context, "new_page", None)
    if not callable(new_page):
        logger.debug(
            "Skipping origin warmup for %s because page context cannot spawn a sibling page",
            url,
        )
        return
    warm_page = None
    try:
        warm_page = await new_page()
        warm_response = await warm_page.goto(
            warm_url,
            wait_until="domcontentloaded",
            timeout=warm_budget_ms,
        )
        warm_phase_timings_ms: dict[str, int] = {}
        await recover_browser_challenge(
            warm_page,
            url=warm_url,
            response=warm_response,
            timeout_seconds=max(1.0, warm_budget_ms / 1000),
            phase_timings_ms=warm_phase_timings_ms,
            challenge_wait_max_seconds=min(
                max(
                    0.0, float(crawler_runtime_settings.challenge_wait_max_seconds or 0)
                ),
                max(1.0, warm_budget_ms / 1000),
            ),
            challenge_poll_interval_ms=int(
                crawler_runtime_settings.challenge_poll_interval_ms
            ),
            navigation_timeout_ms=warm_budget_ms,
            elapsed_ms=_elapsed_ms,
            classify_blocked_page=classify_blocked_page_async,
            get_page_html=get_page_html,
        )
        if _should_run_behavior_realism(browser_engine):
            warm_behavior_started_at = time.perf_counter()
            await emit_browser_behavior_activity(warm_page)
            phase_timings_ms["origin_warmup_behavior"] = _elapsed_ms(
                warm_behavior_started_at
            )
        await warm_page.wait_for_timeout(min(warm_pause_ms, warm_budget_ms))
        if warm_phase_timings_ms.get("challenge_wait"):
            phase_timings_ms["origin_warmup_challenge_wait"] = int(
                warm_phase_timings_ms["challenge_wait"]
            )
        if warm_phase_timings_ms.get("challenge_retry"):
            phase_timings_ms["origin_warmup_challenge_retry"] = int(
                warm_phase_timings_ms["challenge_retry"]
            )
    except Exception:
        logger.debug("Origin warmup failed for %s", url, exc_info=True)
    finally:
        if warm_page is not None:
            close_page = getattr(warm_page, "close", None)
            if callable(close_page):
                with suppress(Exception):
                    await close_page()
        phase_timings_ms["origin_warmup"] = _elapsed_ms(started_at)


async def _navigate_browser_page(
    page: Any,
    *,
    url: str,
    timeout_seconds: float,
    phase_timings_ms: dict[str, int],
    readiness_policy: dict[str, object] | None = None,
):
    return await navigate_browser_page_impl(
        page,
        url=url,
        timeout_seconds=timeout_seconds,
        phase_timings_ms=phase_timings_ms,
        readiness_policy=readiness_policy,
        crawler_runtime_settings=crawler_runtime_settings,
        elapsed_ms=_elapsed_ms,
    )


async def _settle_browser_page(
    page: Any,
    *,
    url: str,
    surface: str,
    requested_fields: list[str] | None,
    timeout_seconds: float,
    readiness_override: dict[str, object] | None,
    readiness_policy: dict[str, object],
    phase_timings_ms: dict[str, int],
):
    return await settle_browser_page_impl(
        page,
        url=url,
        surface=surface,
        requested_fields=requested_fields,
        timeout_seconds=timeout_seconds,
        readiness_override=readiness_override,
        readiness_policy=readiness_policy,
        phase_timings_ms=phase_timings_ms,
        crawler_runtime_settings=crawler_runtime_settings,
        probe_browser_readiness=probe_browser_readiness,
        wait_for_listing_readiness=wait_for_listing_readiness,
        expand_detail_content_if_needed=expand_detail_content_if_needed,
        append_readiness_probe=append_readiness_probe,
        elapsed_ms=_elapsed_ms,
    )


async def _serialize_browser_page_content(
    page: Any,
    *,
    surface: str | None,
    traversal_mode: str | None,
    listing_recovery_mode: str | None,
    traversal_active: bool,
    timeout_seconds: float,
    max_pages: int,
    max_scrolls: int,
    max_records: int | None,
    capture_page_markdown: bool,
    phase_timings_ms: dict[str, int],
    on_event=None,
):
    return await serialize_browser_page_content_impl(
        page,
        surface=surface,
        traversal_mode=traversal_mode,
        listing_recovery_mode=listing_recovery_mode,
        traversal_active=traversal_active,
        timeout_seconds=timeout_seconds,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        capture_page_markdown=capture_page_markdown,
        phase_timings_ms=phase_timings_ms,
        execute_listing_traversal=execute_listing_traversal,
        recover_listing_page_content=recover_listing_page_content,
        elapsed_ms=_elapsed_ms,
        on_event=on_event,
    )


async def wait_for_listing_readiness(
    page: Any,
    page_url: str,
    *,
    override: dict[str, object] | None = None,
) -> dict[str, object]:
    override = override or resolve_listing_readiness_override(page_url)
    return await _wait_for_listing_readiness(page, override=override)


async def _wait_for_listing_readiness(
    page: Any,
    *,
    override: dict[str, object] | None,
) -> dict[str, object]:
    return await wait_for_listing_readiness_impl(page, override=override)


async def probe_browser_readiness(
    page: Any,
    *,
    url: str,
    surface: str,
    listing_override: dict[str, object] | None = None,
    html: str | None = None,
) -> dict[str, object]:
    return await probe_browser_readiness_impl(
        page,
        url=url,
        surface=surface,
        listing_override=listing_override,
        html=html,
        detail_readiness_hint_count=detail_readiness_hint_count,
    )


async def listing_card_signal_count(page: Any, *, surface: str) -> int:
    selector_group = (
        "jobs" if str(surface or "").strip().lower().startswith("job_") else "ecommerce"
    )
    selectors = (
        CARD_SELECTORS.get(selector_group) if isinstance(CARD_SELECTORS, dict) else []
    )
    normalized_selectors = [
        str(selector).strip()
        for selector in list(selectors or [])
        if str(selector).strip()
    ]
    if not normalized_selectors:
        return 0
    return await count_listing_cards(
        page,
        surface=surface,
    )


def detail_readiness_hint_count(surface: str, visible_text: str) -> int:
    lowered_surface = str(surface or "").strip().lower()
    if "ecommerce" in lowered_surface:
        hints = _DETAIL_READINESS_HINTS["ecommerce"]
    elif "job" in lowered_surface:
        hints = _DETAIL_READINESS_HINTS["job"]
    else:
        hints = ()
    return sum(1 for hint in hints if hint in visible_text)


async def expand_detail_content_if_needed(
    page: Any,
    *,
    surface: str,
    readiness_probe: dict[str, object],
    requested_fields: list[str] | None = None,
) -> dict[str, object]:
    return await expand_detail_content_if_needed_impl(
        page,
        surface=surface,
        readiness_probe=readiness_probe,
        requested_fields=requested_fields,
        expand_all_interactive_elements=expand_all_interactive_elements,
        probe_browser_readiness=probe_browser_readiness,
        expand_interactive_elements_via_accessibility=expand_interactive_elements_via_accessibility,
    )


def accessibility_expand_candidates(
    snapshot: dict[str, object] | None,
    *,
    surface: str,
    requested_fields: list[str] | None = None,
) -> list[tuple[str, str]]:
    return accessibility_expand_candidates_impl(
        snapshot,
        surface=surface,
        requested_fields=requested_fields,
        aom_expand_roles=_AOM_EXPAND_ROLES,
        detail_expansion_keywords=detail_expansion_keywords,
    )


def detail_expansion_keywords(
    surface: str,
    *,
    requested_fields: list[str] | None = None,
) -> tuple[str, ...]:
    lowered = str(surface or "").strip().lower()
    if "ecommerce" in lowered:
        base_keywords = _DETAIL_EXPAND_KEYWORDS["ecommerce"]
        extended_keywords = DETAIL_EXPAND_KEYWORD_EXTENSIONS["ecommerce"]
    elif "job" in lowered:
        base_keywords = _DETAIL_EXPAND_KEYWORDS["job"]
        extended_keywords = DETAIL_EXPAND_KEYWORD_EXTENSIONS["job"]
    else:
        base_keywords = ()
        extended_keywords = ()
    dynamic_keywords = requested_field_tokens(requested_fields)
    keywords = [*base_keywords]
    if dynamic_keywords or not list(requested_fields or []):
        keywords.extend(extended_keywords)
    if dynamic_keywords:
        keywords.extend(dynamic_keywords)
    return tuple(dict.fromkeys(keywords))


def classify_browser_outcome(
    *,
    html: str,
    html_bytes: int,
    blocked: bool,
    block_classification: BlockPageClassification | None = None,
    traversal_result: Any = None,
) -> str:
    classification = block_classification or BlockPageClassification(
        blocked=blocked,
        outcome="challenge_page" if blocked else "ok",
    )
    return classify_browser_outcome_impl(
        html=html,
        html_bytes=html_bytes,
        blocked=blocked,
        block_classification=classification,
        traversal_result=traversal_result,
        looks_like_low_content_shell=looks_like_low_content_shell,
    )


def looks_like_low_content_shell(html: str, *, html_bytes: int) -> bool:
    return classify_low_content_reason(html, html_bytes=html_bytes) is not None


def classify_low_content_reason(html: str, *, html_bytes: int) -> str | None:
    return classify_low_content_reason_impl(html, html_bytes=html_bytes)


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


async def _emit_browser_event(on_event, level: str, message: str) -> None:
    if on_event is None:
        return
    try:
        await on_event(level, message)
    except Exception:
        logger.debug("Browser event callback failed", exc_info=True)


def _install_popup_guard(page: Any, *, on_event=None) -> list[tuple[Any, str, Any]]:
    context = getattr(page, "context", None)
    if callable(context):
        with suppress(Exception):
            context = context()
    if context is None:
        return []

    def _handle_context_page(candidate: Any) -> None:
        if candidate is page:
            return
        _schedule_popup_close(candidate, on_event=on_event)

    emitter_on = getattr(context, "on", None)
    if not callable(emitter_on):
        return []
    emitter_on("page", _handle_context_page)
    return [(context, "page", _handle_context_page)]


def _remove_popup_guard(registrations: list[tuple[Any, str, Any]]) -> None:
    for emitter, event_name, callback in registrations:
        remove_listener = getattr(emitter, "remove_listener", None)
        if callable(remove_listener):
            with suppress(Exception):
                remove_listener(event_name, callback)
                continue
        off = getattr(emitter, "off", None)
        if callable(off):
            with suppress(Exception):
                off(event_name, callback)


def _schedule_popup_close(page: Any, *, on_event=None) -> None:
    task = asyncio.create_task(_close_unexpected_popup(page, on_event=on_event))
    _POPUP_GUARD_TASKS.add(task)
    task.add_done_callback(_POPUP_GUARD_TASKS.discard)


async def _close_unexpected_popup(page: Any, *, on_event=None) -> None:
    popup_url = str(getattr(page, "url", "") or "").strip() or "about:blank"
    close_page = getattr(page, "close", None)
    if not callable(close_page):
        return
    with suppress(Exception):
        await close_page()
        await _emit_browser_event(
            on_event,
            "info",
            f"Closed unexpected popup page: {popup_url}",
        )


__all__ = [
    "SharedBrowserRuntime",
    "_MAX_CAPTURED_NETWORK_PAYLOADS",
    "_MAX_CAPTURED_NETWORK_PAYLOAD_BYTES",
    "_NETWORK_CAPTURE_QUEUE_SIZE",
    "_NETWORK_CAPTURE_WORKERS",
    "NetworkPayloadReadResult",
    "browser_fetch",
    "build_browser_diagnostics_contract",
    "browser_runtime_snapshot",
    "build_failed_browser_diagnostics",
    "capture_browser_screenshot",
    "classify_network_endpoint",
    "classify_browser_outcome",
    "expand_all_interactive_elements",
    "interactive_candidate_snapshot",
    "get_browser_runtime",
    "looks_like_low_content_shell",
    "patchright_browser_available",
    "read_network_payload_body",
    "real_chrome_browser_available",
    "real_chrome_executable_path",
    "should_capture_network_payload",
    "shutdown_browser_runtime",
    "shutdown_browser_runtime_sync",
    "temporary_browser_page",
]
