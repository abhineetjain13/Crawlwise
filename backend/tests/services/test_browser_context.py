from __future__ import annotations

import asyncio
from uuid import uuid4
from types import SimpleNamespace

import pytest

from app.services import crawl_fetch_runtime
from app.models.crawl import DomainCookieMemory
from app.services.acquisition import browser_identity
from app.services.acquisition import browser_proxy_bridge
from app.services.acquisition import cookie_store
from app.services.acquisition import host_protection_memory
from app.services.acquisition import browser_runtime as acquisition_browser_runtime
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_utils import is_special_use_domain


def _context_spec(
    context_options: dict[str, object] | None = None,
    *,
    init_script: str | None = None,
) -> browser_identity.PlaywrightContextSpec:
    return browser_identity.PlaywrightContextSpec(
        context_options=dict(context_options or {}),
        init_script=init_script,
    )


def _make_fingerprint(
    *,
    screen: dict[str, object] | None = None,
    navigator: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
):
    default_user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    )
    navigator_data = {
        "userAgent": default_user_agent,
        "language": "en-US",
        "maxTouchPoints": 0,
        "userAgentData": {
            "brands": [{"brand": "Google Chrome", "version": "145"}],
            "mobile": False,
        },
        **dict(navigator or {}),
    }
    screen_data = {
        "width": 1440,
        "height": 900,
        "devicePixelRatio": 2,
        **dict(screen or {}),
    }
    header_data = {
        "User-Agent": navigator_data["userAgent"],
        "Accept": "text/html",
        "Accept-Language": "en-US;q=1.0",
        "sec-ch-ua": '"Google Chrome";v="145"',
        "Accept-Encoding": "gzip, br",
        "Sec-Fetch-Mode": "navigate",
        **dict(headers or {}),
    }
    return SimpleNamespace(
        screen=SimpleNamespace(**screen_data),
        navigator=SimpleNamespace(**navigator_data),
        headers=header_data,
    )


def test_build_playwright_context_options_uses_generated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = _make_fingerprint()

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )
    monkeypatch.setattr(browser_identity, "_get_localzone_name", lambda: "America/New_York")

    options = browser_identity.build_playwright_context_options()

    assert options["user_agent"].endswith("Chrome/145.0.0.0 Safari/537.36")
    assert options["viewport"] == {"width": 1440, "height": 800}
    assert options["locale"] == "en-US"
    assert options["device_scale_factor"] == 2.0
    assert options["has_touch"] is False
    assert options["is_mobile"] is False
    assert options["extra_http_headers"] == {
        "Accept": "text/html",
        "Accept-Language": "en-US;q=1.0",
        "sec-ch-ua": (
            '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-ch-ua-platform-version": '"15.0.0"',
        "sec-ch-ua-bitness": '"64"',
    }


def test_acquisition_package_exports_runtime_expand_function() -> None:
    from app.services import acquisition

    assert (
        acquisition.expand_all_interactive_elements
        is acquisition_browser_runtime.expand_all_interactive_elements
    )


def test_resolve_timezone_id_prefers_explicit_locality_timezone() -> None:
    assert (
        browser_identity._resolve_timezone_id(
            {
                "geo_country": "US",
                "timezone_id": "Asia/Calcutta",
            }
        )
        == "Asia/Kolkata"
    )


def test_create_browser_identity_keeps_desktop_viewport_shorter_than_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = _make_fingerprint(
        screen={"devicePixelRatio": 1.5},
        headers={"User-Agent": "", "sec-ch-ua": ""},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    identity = browser_identity.create_browser_identity()

    assert identity.viewport == {"width": 1440, "height": 800}
    assert identity.raw_fingerprint is not None
    assert identity.raw_fingerprint.screen.innerHeight == 800
    assert identity.raw_fingerprint.screen.height == 900
    assert identity.raw_fingerprint.screen.outerHeight == 888
    assert identity.raw_fingerprint.screen.availHeight == 800


def test_create_browser_identity_keeps_outer_height_below_screen_when_frame_saturates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = _make_fingerprint(
        screen={
            "width": 1366,
            "height": 768,
            "availWidth": 1366,
            "availHeight": 728,
            "devicePixelRatio": 1,
        },
        navigator={"userAgentData": {"brands": [], "mobile": False}},
        headers={"User-Agent": "", "sec-ch-ua": ""},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    identity = browser_identity.create_browser_identity()

    assert identity.viewport == {"width": 1366, "height": 728}
    assert identity.raw_fingerprint is not None
    assert identity.raw_fingerprint.screen.outerHeight == 767


def test_create_browser_identity_aligns_runtime_hardware_to_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = _make_fingerprint(
        screen={"devicePixelRatio": 1.25},
        navigator={
            "hardwareConcurrency": 20,
            "deviceMemory": 4,
            "userAgentData": {"brands": [], "mobile": False},
        },
        headers={"User-Agent": "", "sec-ch-ua": ""},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )
    monkeypatch.setattr(browser_identity._os, "cpu_count", lambda: 12)
    monkeypatch.setattr(
        browser_identity,
        "_host_total_memory_bytes",
        lambda: 16 * 1024**3,
    )

    identity = browser_identity.create_browser_identity()

    assert identity.raw_fingerprint is not None
    assert identity.raw_fingerprint.navigator.hardwareConcurrency == 12
    assert identity.raw_fingerprint.navigator.deviceMemory == 8.0


def test_create_browser_identity_aligns_platform_to_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = _make_fingerprint(
        screen={"devicePixelRatio": 1.25},
        navigator={
            "platform": "Linux x86_64",
            "userAgentData": {
                "brands": [{"brand": "Google Chrome", "version": "145"}],
                "mobile": False,
                "platform": "Linux",
            },
        },
        headers={"sec-ch-ua-platform": '"Linux"'},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    identity = browser_identity.create_browser_identity()

    assert identity.raw_fingerprint is not None
    assert identity.raw_fingerprint.navigator.platform == "Win32"
    assert identity.raw_fingerprint.navigator.userAgentData["platform"] == "Windows"
    assert identity.extra_http_headers["sec-ch-ua-platform"] == '"Windows"'
    assert identity.extra_http_headers["sec-ch-ua-platform-version"] == '"15.0.0"'
    assert identity.extra_http_headers["sec-ch-ua-bitness"] == '"64"'


def test_build_playwright_context_options_prefers_available_screen_height(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(
            width=1536,
            height=864,
            availWidth=1536,
            availHeight=816,
            devicePixelRatio=1.25,
        ),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={
                "brands": [{"brand": "Google Chrome", "version": "145"}],
                "mobile": False,
            },
        ),
        headers={"Accept": "text/html"},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    options = browser_identity.build_playwright_context_options()

    assert options["viewport"] == {"width": 1536, "height": 816}


def test_is_special_use_domain_ignores_ports() -> None:
    assert is_special_use_domain("localhost:3000") is True
    assert is_special_use_domain("http://localhost:3000/products/widget") is True


def test_build_playwright_context_options_keeps_security_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent="Mozilla/5.0 MobileTest/145.0",
            language="en-US",
            maxTouchPoints=5,
            userAgentData={"mobile": True},
        ),
        headers={"User-Agent": "Mozilla/5.0 MobileTest/145.0"},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    options = browser_identity.build_playwright_context_options()

    assert options["service_workers"] == "block"
    assert options["bypass_csp"] is False
    assert options["permissions"] == ["geolocation"]
    assert options["has_touch"] is True
    assert options["is_mobile"] is True


def test_build_playwright_context_options_disables_touch_for_desktop_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1536, height=864, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=5,
            userAgentData={"mobile": False},
        ),
        headers={"Accept": "text/html"},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )

    options = browser_identity.build_playwright_context_options()

    assert options["is_mobile"] is False
    assert options["has_touch"] is False


def test_build_playwright_context_options_repairs_incoherent_client_hints_after_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1366, height=768, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={
                "brands": [{"brand": "Brave", "version": "130"}],
                "mobile": False,
                "platform": "Windows",
                "uaFullVersion": "130.0.0.0",
            },
        ),
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html",
            "sec-ch-ua": '"Brave";v="130"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    )
    attempts = {"count": 0}

    def _generate():
        attempts["count"] += 1
        return bad_fingerprint

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=_generate),
    )

    options = browser_identity.build_playwright_context_options()

    assert attempts["count"] == 3
    assert options["user_agent"].endswith("Chrome/145.0.0.0 Safari/537.36")
    assert options["extra_http_headers"]["sec-ch-ua"] == (
        '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
    )
    assert options["extra_http_headers"]["sec-ch-ua-mobile"] == "?0"
    assert options["extra_http_headers"]["sec-ch-ua-platform"] == '"Windows"'
    assert options["extra_http_headers"]["sec-ch-ua-platform-version"] == '"15.0.0"'
    assert options["extra_http_headers"]["sec-ch-ua-bitness"] == '"64"'


def test_build_playwright_context_options_replaces_malformed_client_hints_without_rejecting_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1366, height=768, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={
                "brands": [{"brand": "Google Chrome", "version": "145"}],
                "mobile": False,
                "platform": "Windows",
                "uaFullVersion": "145.0.0.0",
            },
        ),
        headers={
            "Accept": "text/html",
            "Accept-Language": "en-US;q=1.0",
            "sec-ch-ua": '"Google Chrome";v="145", "Chromium";v="145", "Not(A:Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )
    monkeypatch.setattr(browser_identity, "_get_localzone_name", lambda: "America/New_York")

    options = browser_identity.build_playwright_context_options()

    assert options["extra_http_headers"]["Accept-Language"] == "en-US;q=1.0"
    assert options["extra_http_headers"]["sec-ch-ua"] == (
        '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
    )
    assert options["extra_http_headers"]["sec-ch-ua-mobile"] == "?0"
    assert options["extra_http_headers"]["sec-ch-ua-platform"] == '"Windows"'
    assert options["extra_http_headers"]["sec-ch-ua-platform-version"] == '"15.0.0"'
    assert options["extra_http_headers"]["sec-ch-ua-bitness"] == '"64"'


def test_build_playwright_context_options_uses_configured_min_chrome_version(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(browser_identity_min_chrome_version=130)
    fingerprint = _make_fingerprint(
        screen={"width": 1366, "height": 768, "devicePixelRatio": 1},
        navigator={
            "userAgent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            "userAgentData": {
                "brands": [{"brand": "Google Chrome", "version": "129"}],
                "mobile": False,
                "platform": "Windows",
                "uaFullVersion": "129.0.0.0",
            },
        },
        headers={"User-Agent": "", "sec-ch-ua": ""},
    )
    attempts = {"count": 0}

    def _generate():
        attempts["count"] += 1
        return fingerprint

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=_generate),
    )

    options = browser_identity.build_playwright_context_options()

    assert attempts["count"] == 3
    assert options["user_agent"].endswith("Chrome/129.0.0.0 Safari/537.36")
    assert options["extra_http_headers"]["sec-ch-ua"] == (
        '"Not:A-Brand";v="99", "Google Chrome";v="129", "Chromium";v="129"'
    )


def test_build_playwright_context_options_aligns_user_agent_to_browser_major() -> None:
    identity = browser_identity.BrowserIdentity(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 768},
        extra_http_headers={
            "Accept": "text/html",
            "Accept-Language": "en-US;q=1.0",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="125", "Chromium";v="125"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
        locale="en-US",
        device_scale_factor=1.0,
        has_touch=False,
        is_mobile=False,
    )

    options = browser_identity.build_playwright_context_options(
        identity=identity,
        browser_major_version=145,
    )

    assert options["user_agent"].endswith("Chrome/145.0.0.0 Safari/537.36")
    assert options["extra_http_headers"]["sec-ch-ua"] == (
        '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
    )


def test_build_playwright_context_options_drops_stale_client_hint_headers() -> None:
    identity = browser_identity.BrowserIdentity(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 768},
        extra_http_headers={
            "Accept": "text/html",
            "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="125", "Chromium";v="125"',
            "sec-ch-ua-full-version": '"125.0.0.0"',
            "sec-ch-ua-platform": '"Windows"',
        },
        locale="en-US",
        device_scale_factor=1.0,
        has_touch=False,
        is_mobile=False,
    )

    options = browser_identity.build_playwright_context_options(
        identity=identity,
        browser_major_version=145,
    )

    assert "sec-ch-ua-full-version" not in options["extra_http_headers"]
    assert options["extra_http_headers"]["sec-ch-ua"] == (
        '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
    )


def test_align_raw_fingerprint_to_browser_major_falls_back_to_safe_shallow_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_fingerprint = SimpleNamespace(
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            userAgentData={
                "brands": [{"brand": "Google Chrome", "version": "125"}],
                "mobile": False,
                "platform": "Windows",
            },
        ),
        headers={
            "Accept": "text/html",
            "sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125"',
            "sec-ch-ua-platform": '"Windows"',
        },
    )

    def _raise_deepcopy(_value, _memo=None):
        raise RuntimeError("deepcopy boom")

    monkeypatch.setattr(browser_identity._copy, "deepcopy", _raise_deepcopy)

    aligned = browser_identity._align_raw_fingerprint_to_browser_major(
        raw_fingerprint,
        browser_major_version=145,
        is_mobile=False,
    )

    assert aligned is not raw_fingerprint
    assert raw_fingerprint.navigator.userAgent.endswith("Chrome/125.0.0.0 Safari/537.36")
    assert aligned.navigator.userAgent.endswith("Chrome/145.0.0.0 Safari/537.36")
    assert raw_fingerprint.headers["sec-ch-ua"] == (
        '"Google Chrome";v="125", "Chromium";v="125"'
    )
    assert aligned.headers["sec-ch-ua"] == (
        '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"'
    )


def test_align_raw_fingerprint_to_browser_major_returns_original_when_navigator_missing() -> None:
    raw_fingerprint = SimpleNamespace(
        navigator=None,
        headers={"sec-ch-ua": '"Google Chrome";v="125", "Chromium";v="125"'},
    )

    aligned = browser_identity._align_raw_fingerprint_to_browser_major(
        raw_fingerprint,
        browser_major_version=145,
        is_mobile=False,
    )

    assert aligned is raw_fingerprint


@pytest.mark.asyncio
async def test_read_socks5_response_rejects_unexpected_upstream_version() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(bytes([4, 0, 0, 1, 127, 0, 0, 1, 0, 80]))
    reader.feed_eof()

    with pytest.raises(ValueError, match="Unexpected upstream SOCKS response version"):
        await browser_proxy_bridge._read_socks5_response(reader)


@pytest.mark.asyncio
async def test_read_client_request_rejects_missing_no_auth_method() -> None:
    class _Writer:
        def __init__(self) -> None:
            self.data = bytearray()

        def write(self, data: bytes) -> None:
            self.data.extend(data)

        async def drain(self) -> None:
            return None

    reader = asyncio.StreamReader()
    reader.feed_data(bytes([5, 1, 2]))
    reader.feed_eof()
    writer = _Writer()

    with pytest.raises(ValueError, match="no-auth method"):
        await browser_proxy_bridge._read_client_request(reader, writer)

    assert bytes(writer.data) == bytes([5, 0xFF])


@pytest.mark.asyncio
async def test_socks5_auth_bridge_start_is_singleflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_calls = 0

    class _Socket:
        def getsockname(self):
            return ("127.0.0.1", 41001)

    class _Server:
        sockets = [_Socket()]

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def _fake_start_server(*_args, **_kwargs):
        nonlocal start_calls
        start_calls += 1
        await asyncio.sleep(0)
        return _Server()

    monkeypatch.setattr(browser_proxy_bridge.asyncio, "start_server", _fake_start_server)
    bridge = browser_proxy_bridge.Socks5AuthBridge(
        browser_proxy_bridge.Socks5UpstreamProxy(
            scheme="socks5",
            host="proxy.example",
            port=1080,
            username="user",
            password="pass",
        )
    )

    first, second = await asyncio.gather(bridge.start(), bridge.start())
    await bridge.close()

    assert first == second == "socks5://127.0.0.1:41001"
    assert start_calls == 1


def test_build_playwright_context_spec_masks_page_globals_for_non_browserforge_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeFingerprint:
        def dumps(self) -> str:
            return "{}"

    monkeypatch.setattr(
        browser_identity,
        "_BrowserforgeInjectFunction",
        lambda fingerprint: str(type(fingerprint).__name__),
    )

    spec = browser_identity.build_playwright_context_spec(
        identity=browser_identity.BrowserIdentity(
            user_agent="Mozilla/5.0 Chrome/145.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            extra_http_headers={},
            locale="en-US",
            device_scale_factor=1.0,
            has_touch=False,
            is_mobile=False,
            raw_fingerprint=_FakeFingerprint(),
        )
    )

    assert spec.init_script is not None
    assert "__pwInitScripts" in spec.init_script
    assert "__playwright__binding__" in spec.init_script
    assert "maskGlobal('Worker')" in spec.init_script
    assert "maskGlobal('SharedWorker')" in spec.init_script
    assert "Notification" in spec.init_script
    assert "contentIndex" in spec.init_script
    assert "downlinkMax" in spec.init_script
    assert "prefers-color-scheme" in spec.init_script


def test_build_playwright_context_spec_injects_runtime_hardware_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_identity._os, "cpu_count", lambda: 12)
    monkeypatch.setattr(
        browser_identity,
        "_host_total_memory_bytes",
        lambda: 16 * 1024**3,
    )

    spec = browser_identity.build_playwright_context_spec(
        identity=browser_identity.BrowserIdentity(
            user_agent="Mozilla/5.0 Chrome/145.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            extra_http_headers={},
            locale="en-US",
            device_scale_factor=1.0,
            has_touch=False,
            is_mobile=False,
            raw_fingerprint=SimpleNamespace(
                navigator=SimpleNamespace(
                    hardwareConcurrency=20,
                    deviceMemory=4,
                )
            ),
        )
    )

    assert spec.init_script is not None
    assert "const hardwareConcurrency = 12;" in spec.init_script
    assert "const deviceMemory = 8.0;" in spec.init_script


def test_build_playwright_context_spec_injects_chrome_runtime_and_audio_masks() -> None:
    spec = browser_identity.build_playwright_context_spec(
        identity=browser_identity.BrowserIdentity(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            locale="en-US",
            device_scale_factor=1.0,
            has_touch=False,
            is_mobile=False,
            raw_fingerprint=SimpleNamespace(
                navigator=SimpleNamespace(
                    hardwareConcurrency=8,
                    deviceMemory=8,
                )
            ),
        )
    )

    assert spec.init_script is not None
    assert "globalThis.chrome = globalThis.chrome || {};" in spec.init_script
    assert "OnInstalledReason" in spec.init_script
    assert "assignIfMissing('getManifest', () => undefined);" in spec.init_script
    assert "const extensionId = typeof runtime.id === 'string' && runtime.id ? runtime.id : '';" in spec.init_script
    assert "const audioSeed =" in spec.init_script
    assert "getFloatFrequencyData" in spec.init_script
    assert "getChannelData(channel)" in spec.init_script
    assert "getFloatTimeDomainData" in spec.init_script
    assert "getByteTimeDomainData" in spec.init_script
    assert "globalThis.OfflineAudioContext" in spec.init_script
    assert "const wrapContextConstructor = (globalKey) => {" in spec.init_script
    assert "return patchAudioContextInstance(Reflect.construct(target, args, newTarget));" in spec.init_script
    assert "getImageData" in spec.init_script
    assert "toDataURL" in spec.init_script
    assert "getParameter" in spec.init_script
    assert "readPixels" in spec.init_script
    assert "WEBGL_debug_renderer_info" in spec.init_script
    assert "runtime.csi = runtime.csi ||" in spec.init_script
    assert "runtime.loadTimes = runtime.loadTimes ||" in spec.init_script
    assert "installDescriptor(Navigator.prototype, 'keyboard', () => keyboard);" in spec.init_script
    assert "installDescriptor(Navigator.prototype, 'mediaCapabilities', () => mediaCapabilities);" in spec.init_script
    assert "installDescriptor(Navigator.prototype, 'gpu', () => gpu);" in spec.init_script


def test_build_playwright_context_spec_skips_legacy_init_script_for_patchright() -> None:
    spec = browser_identity.build_playwright_context_spec(
        identity=browser_identity.BrowserIdentity(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            locale="en-US",
            device_scale_factor=1.0,
            has_touch=False,
            is_mobile=False,
            raw_fingerprint=None,
        ),
        browser_engine="patchright",
    )

    assert spec.init_script is None


def test_playwright_identity_seed_is_stable_and_changes_with_identity() -> None:
    base_identity = browser_identity.BrowserIdentity(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 768},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        locale="en-US",
        device_scale_factor=1.0,
        has_touch=False,
        is_mobile=False,
        raw_fingerprint=SimpleNamespace(
            navigator=SimpleNamespace(
                hardwareConcurrency=8,
                deviceMemory=8,
            )
        ),
    )
    changed_identity = browser_identity.BrowserIdentity(
        user_agent=base_identity.user_agent,
        viewport={"width": 1440, "height": 900},
        extra_http_headers=base_identity.extra_http_headers,
        locale=base_identity.locale,
        device_scale_factor=base_identity.device_scale_factor,
        has_touch=base_identity.has_touch,
        is_mobile=base_identity.is_mobile,
        raw_fingerprint=base_identity.raw_fingerprint,
    )

    first_seed = browser_identity._playwright_identity_seed(base_identity)
    second_seed = browser_identity._playwright_identity_seed(base_identity)
    changed_seed = browser_identity._playwright_identity_seed(changed_identity)

    assert first_seed == second_seed
    assert first_seed != changed_seed


def test_build_playwright_context_options_aligns_auto_locality_to_system_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1440, height=900, devicePixelRatio=2),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={
                "brands": [{"brand": "Google Chrome", "version": "145"}],
                "mobile": False,
            },
        ),
        headers={"Accept": "text/html"},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )
    monkeypatch.setattr(browser_identity, "_get_localzone_name", lambda: "Asia/Calcutta")

    options = browser_identity.build_playwright_context_options(
        locality_profile={"geo_country": "auto", "language_hint": None}
    )

    assert options["locale"] == "en-IN"
    assert options["timezone_id"] == "Asia/Kolkata"
    assert options["extra_http_headers"]["Accept-Language"] == "en-IN,en;q=0.9"


def test_build_playwright_context_options_prefers_explicit_locality_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1440, height=900, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={"brands": [], "mobile": False},
        ),
        headers={"Accept": "text/html"},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )
    monkeypatch.setattr(browser_identity, "_get_localzone_name", lambda: "America/New_York")

    options = browser_identity.build_playwright_context_options(
        locality_profile={
            "geo_country": "IN",
            "language_hint": "en-IN",
        }
    )

    assert options["locale"] == "en-IN"
    assert options["timezone_id"] == "Asia/Kolkata"
    assert options["extra_http_headers"]["Accept-Language"] == "en-IN,en;q=0.9"


def test_build_playwright_context_options_uses_first_country_timezone_when_multiple_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = SimpleNamespace(
        screen=SimpleNamespace(width=1440, height=900, devicePixelRatio=1),
        navigator=SimpleNamespace(
            userAgent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            language="en-US",
            maxTouchPoints=0,
            userAgentData={"brands": [], "mobile": False},
        ),
        headers={"Accept": "text/html"},
    )

    monkeypatch.setattr(
        browser_identity,
        "_FINGERPRINT_GENERATOR",
        SimpleNamespace(generate=lambda: fingerprint),
    )
    monkeypatch.setattr(browser_identity, "_get_localzone_name", lambda: "Asia/Kolkata")

    options = browser_identity.build_playwright_context_options(
        locality_profile={
            "geo_country": "US",
            "language_hint": "en-US",
        }
    )

    assert options["timezone_id"] == "America/New_York"


def test_build_playwright_context_spec_masks_platform_in_init_script() -> None:
    spec = browser_identity.build_playwright_context_spec(
        identity=browser_identity.BrowserIdentity(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            locale="en-US",
            device_scale_factor=1.0,
            has_touch=False,
            is_mobile=False,
            raw_fingerprint=None,
        ),
        locality_profile={"geo_country": "US", "language_hint": "en-US"},
    )

    assert spec.init_script is not None
    assert "navigatorPlatform" in spec.init_script
    assert "uaPlatform" in spec.init_script


def test_build_playwright_context_spec_injects_navigator_coherence_bundle() -> None:
    spec = browser_identity.build_playwright_context_spec(
        identity=browser_identity.BrowserIdentity(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            locale="en-US",
            device_scale_factor=1.0,
            has_touch=False,
            is_mobile=False,
            raw_fingerprint=None,
        ),
        locality_profile={"geo_country": "US", "language_hint": "en-US"},
    )

    assert spec.init_script is not None
    assert "connectionProfile" in spec.init_script
    assert "Navigator.prototype, 'connection'" in spec.init_script
    assert "Navigator.prototype, 'maxTouchPoints'" in spec.init_script
    assert "Screen.prototype, 'orientation'" in spec.init_script
    assert "const buildOrientation = () => {" in spec.init_script
    assert "nativeOrientation.lock ? nativeOrientation.lock(...args)" in spec.init_script
    assert "FontFaceSet.prototype.check" in spec.init_script
    assert "CSSStyleDeclaration.prototype.setProperty" in spec.init_script
    assert "Element.prototype.setAttribute" in spec.init_script
    assert "document.fonts, 'ready'" in spec.init_script
    assert "patchIntlConstructor('NumberFormat'" in spec.init_script
    assert "patchIntlConstructor('PluralRules'" in spec.init_script
    assert "permissionStates" in spec.init_script
    assert "enumerateDevices = async" in spec.init_script
    assert "const maxTouchPoints = 0;" in spec.init_script
    assert '"portrait-primary"' not in spec.init_script


def test_build_playwright_context_spec_sets_mobile_touch_points_and_orientation() -> None:
    spec = browser_identity.build_playwright_context_spec(
        identity=browser_identity.BrowserIdentity(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Mobile Safari/537.36"
            ),
            viewport={"width": 390, "height": 844},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            locale="en-US",
            device_scale_factor=3.0,
            has_touch=True,
            is_mobile=True,
            raw_fingerprint=None,
        ),
        locality_profile={"geo_country": "US", "language_hint": "en-US"},
    )

    assert spec.init_script is not None
    assert "const maxTouchPoints = 5;" in spec.init_script
    assert 'const orientationType = "portrait-primary";' in spec.init_script


def test_build_playwright_context_spec_masks_webrtc_candidates() -> None:
    spec = browser_identity.build_playwright_context_spec(
        identity=browser_identity.BrowserIdentity(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/145.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            locale="en-US",
            device_scale_factor=1.0,
            has_touch=False,
            is_mobile=False,
            raw_fingerprint=None,
        ),
        locality_profile={"geo_country": "US", "language_hint": "en-US"},
    )

    assert spec.init_script is not None
    assert "MaskedRTCPeerConnection" in spec.init_script
    assert "addTrack(track)" in spec.init_script
    assert "getSenders() { return this._senders.slice(); }" in spec.init_script
    assert "createOffer() { return Promise.resolve({ type: 'offer'" in spec.init_script
    assert "generateCertificate = () => Promise.resolve({})" in spec.init_script


def test_normalize_timezone_id_rejects_invalid_timezone() -> None:
    assert browser_identity._normalize_timezone_id("Not/AZone") is None
    assert browser_identity._normalize_timezone_id("Asia/Calcutta") == "Asia/Kolkata"


def test_fingerprint_generator_rebuilds_when_runtime_settings_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = []

    class _FakeGenerator:
        def __init__(self, *, browser, os, device, locale) -> None:
            del os
            constructed.append((tuple(browser), tuple(device), tuple(locale)))

        def generate(self):
            return SimpleNamespace(
                screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1),
                navigator=SimpleNamespace(
                    userAgent="Mozilla/5.0 Chrome/145.0.0.0",
                    language="en-US",
                    maxTouchPoints=0,
                    userAgentData={"brands": [], "mobile": False},
                ),
                headers={"Accept": "text/html"},
            )

    monkeypatch.setattr(browser_identity, "FingerprintGenerator", _FakeGenerator)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR", None)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR_CONFIG", None)
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_browser",
        ["chrome"],
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_device",
        ["desktop"],
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_locale",
        ["en-US"],
    )

    browser_identity._fingerprint_generator()
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_browser",
        ["firefox"],
    )
    browser_identity._fingerprint_generator()

    assert constructed == [
        (("chrome",), ("desktop",), ("en-US",)),
        (("firefox",), ("desktop",), ("en-US",)),
    ]


def test_fingerprint_generator_normalizes_default_string_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = []

    class _FakeGenerator:
        def __init__(self, *, browser, os, device, locale) -> None:
            del os
            constructed.append((tuple(browser), tuple(device), tuple(locale)))

        def generate(self):
            return SimpleNamespace(
                screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1),
                navigator=SimpleNamespace(
                    userAgent="Mozilla/5.0 Chrome/145.0.0.0",
                    language="en-US",
                    maxTouchPoints=0,
                    userAgentData={"brands": [], "mobile": False},
                ),
                headers={"Accept": "text/html"},
            )

    monkeypatch.setattr(browser_identity, "FingerprintGenerator", _FakeGenerator)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR", None)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR_CONFIG", None)
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_browser",
        "chrome",
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_device",
        "desktop",
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_locale",
        "en-US",
    )

    browser_identity._fingerprint_generator()

    assert constructed == [(("chrome",), ("desktop",), ("en-US",))]


def test_fingerprint_generator_ignores_mapping_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = []

    class _FakeGenerator:
        def __init__(self, *, browser, os, device, locale) -> None:
            del os
            constructed.append((tuple(browser), tuple(device), tuple(locale)))

        def generate(self):
            return SimpleNamespace(
                screen=SimpleNamespace(width=1280, height=720, devicePixelRatio=1),
                navigator=SimpleNamespace(
                    userAgent="Mozilla/5.0 Chrome/145.0.0.0",
                    language="en-US",
                    maxTouchPoints=0,
                    userAgentData={"brands": [], "mobile": False},
                ),
                headers={"Accept": "text/html"},
            )

    monkeypatch.setattr(browser_identity, "FingerprintGenerator", _FakeGenerator)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR", None)
    monkeypatch.setattr(browser_identity, "_FINGERPRINT_GENERATOR_CONFIG", None)
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_browser",
        {"chrome": True},
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_device",
        {"desktop": True},
    )
    monkeypatch.setattr(
        browser_identity.crawler_runtime_settings,
        "fingerprint_locale",
        {"en-US": True},
    )

    browser_identity._fingerprint_generator()

    assert constructed == [((), (), ())]


def test_coherent_sec_ch_headers_accepts_tuple_brand_entries() -> None:
    headers = browser_identity._coherent_sec_ch_headers(
        {
            "brands": (
                {"brand": "Chromium", "version": "145"},
                {"brand": "Google Chrome", "version": "145"},
            ),
            "mobile": False,
            "platform": "Windows",
            "platformVersion": "15.0.0",
            "bitness": "64",
        }
    )

    assert headers["sec-ch-ua"] == (
        '"Chromium";v="145", "Google Chrome";v="145"'
    )
    assert headers["sec-ch-ua-mobile"] == "?0"
    assert headers["sec-ch-ua-platform"] == '"Windows"'
    assert headers["sec-ch-ua-platform-version"] == '"15.0.0"'
    assert headers["sec-ch-ua-bitness"] == '"64"'


@pytest.mark.asyncio
async def test_load_storage_state_for_run_ignores_invalid_run_id() -> None:
    assert await cookie_store.load_storage_state_for_run("invalid") is None


@pytest.mark.asyncio
async def test_load_storage_state_for_run_scopes_by_browser_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        browser_engine="chromium",
    )
    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "real-chrome-session",
                    "value": "2",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        browser_engine="real_chrome",
    )

    chromium_state = await cookie_store.load_storage_state_for_run(
        77,
        browser_engine="chromium",
    )
    real_chrome_state = await cookie_store.load_storage_state_for_run(
        77,
        browser_engine="real_chrome",
    )

    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert real_chrome_state == {
        "cookies": [
            {
                "name": "real-chrome-session",
                "value": "2",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
async def test_persist_storage_state_for_run_replaces_existing_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "stale",
                    "value": "1",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "old", "value": "1"}],
                }
            ],
        },
    )
    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "fresh",
                    "value": "2",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "new", "value": "2"}],
                }
            ],
        },
    )

    assert await cookie_store.load_storage_state_for_run(77) == {
        "cookies": [
            {
                "name": "fresh",
                "value": "2",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [
            {
                "origin": "https://example.com",
                "localStorage": [{"name": "new", "value": "2"}],
            }
        ],
    }


@pytest.mark.asyncio
async def test_shared_browser_runtime_passes_generated_context_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    created_pages: list[object] = []
    routed_patterns: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del handler
            routed_patterns.append(pattern)

        async def new_page(self):
            page = object()
            created_pages.append(page)
            return page

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(
            {
                "user_agent": "Mozilla/5.0 Runtime/145.0",
                "viewport": {"width": 1600, "height": 900},
                "extra_http_headers": {"Accept": "text/html"},
                "locale": "en-US",
                "device_scale_factor": 1.0,
                "has_touch": False,
                "is_mobile": False,
                "service_workers": "block",
                "bypass_csp": False,
            }
        ),
    )

    async with runtime.page() as page:
        assert page in created_pages

    assert captured_kwargs == [
        {
            "user_agent": "Mozilla/5.0 Runtime/145.0",
            "viewport": {"width": 1600, "height": 900},
            "extra_http_headers": {"Accept": "text/html"},
            "locale": "en-US",
            "device_scale_factor": 1.0,
            "has_touch": False,
            "is_mobile": False,
            "service_workers": "block",
            "bypass_csp": False,
        }
    ]
    assert routed_patterns == ["**/*"]


@pytest.mark.asyncio
async def test_shared_browser_runtime_applies_init_script_without_stealth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_scripts: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            init_scripts.append(script)

        async def new_page(self):
            return SimpleNamespace(context=self)

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(init_script="window.__browserforge = true;"),
    )

    async with runtime.page(inject_init_script=True):
        pass

    assert init_scripts == ["window.__browserforge = true;"]


@pytest.mark.asyncio
async def test_shared_browser_runtime_uses_native_context_for_real_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return SimpleNamespace(context=self)

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "_resolve_browser_binary",
        lambda _engine: ("C:/Chrome/chrome.exe", "C:/Chrome/chrome.exe"),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec({"user_agent": "Mozilla/5.0 Runtime/145.0"}),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_real_chrome_native_context",
        True,
    )
    runtime = acquisition_browser_runtime.SharedBrowserRuntime(
        max_contexts=1,
        browser_engine="real_chrome",
    )
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    async with runtime.page():
        pass

    assert captured_kwargs == [{}]


@pytest.mark.asyncio
async def test_shared_browser_runtime_skips_init_script_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_scripts: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def add_init_script(self, script: str) -> None:
            init_scripts.append(script)

        async def new_page(self):
            return SimpleNamespace(context=self)

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(init_script="window.__browserforge = true;"),
    )
    async with runtime.page():
        pass

    assert init_scripts == []


@pytest.mark.asyncio
async def test_shared_browser_runtime_uses_socks5_auth_bridge_and_keeps_context_proxy_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_launch_kwargs: list[dict[str, object]] = []
    captured_context_kwargs: list[dict[str, object]] = []
    bridge_start_calls: list[str] = []
    bridge_close_calls: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_context_kwargs.append(kwargs)
            return FakeContext()

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            captured_launch_kwargs.append(kwargs)
            return FakeBrowser()

        async def stop(self) -> None:
            return None

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    class FakeBridge:
        def __init__(self, upstream) -> None:
            self.upstream = upstream

        async def start(self) -> str:
            bridge_start_calls.append(
                f"{self.upstream.scheme}://{self.upstream.username}:***@{self.upstream.host}:{self.upstream.port}"
            )
            return "socks5://127.0.0.1:8899"

        async def close(self) -> None:
            bridge_close_calls.append("closed")

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(acquisition_browser_runtime, "Socks5AuthBridge", FakeBridge)
    monkeypatch.setattr(
        "patchright.async_api.async_playwright",
        lambda: FakePlaywrightManager(),
    )

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(
        max_contexts=1,
        launch_proxy="socks5://user-name:pass-word@31.58.9.4:6077",
    )

    async with runtime.page():
        pass

    assert captured_launch_kwargs == [
        {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--headless=new",
            ],
            "proxy": {
                "server": "socks5://127.0.0.1:8899",
            },
        }
    ]
    assert captured_context_kwargs == [{}]
    assert bridge_start_calls == ["socks5://user-name:***@31.58.9.4:6077"]
    await runtime.close()
    assert bridge_close_calls == ["closed"]


@pytest.mark.asyncio
async def test_shared_browser_runtime_launches_http_proxy_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_launch_kwargs: list[dict[str, object]] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            captured_launch_kwargs.append(kwargs)
            return FakeBrowser()

        async def stop(self) -> None:
            return None

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        "patchright.async_api.async_playwright",
        lambda: FakePlaywrightManager(),
    )

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(
        max_contexts=1,
        launch_proxy="http://user-name:pass-word@31.58.9.4:6077",
    )

    async with runtime.page():
        pass

    assert captured_launch_kwargs == [
        {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--headless=new",
            ],
            "proxy": {
                "server": "http://31.58.9.4:6077",
                "username": "user-name",
                "password": "pass-word",
            },
        }
    ]


@pytest.mark.asyncio
async def test_shared_browser_runtime_launches_real_chrome_headful_for_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_launch_kwargs: list[dict[str, object]] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            captured_launch_kwargs.append(kwargs)
            return FakeBrowser()

        async def stop(self) -> None:
            return None

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "_resolve_browser_binary",
        lambda _engine: ("C:/Chrome/chrome.exe", "C:/Chrome/chrome.exe"),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_real_chrome_force_headful",
        True,
    )
    monkeypatch.setattr(
        "patchright.async_api.async_playwright",
        lambda: FakePlaywrightManager(),
    )

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(
        max_contexts=1,
        browser_engine="real_chrome",
    )

    async with runtime.page():
        pass

    assert captured_launch_kwargs == [
        {
            "headless": False,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            ],
            "executable_path": "C:/Chrome/chrome.exe",
        }
    ]


def test_display_proxy_masks_authenticated_proxy_credentials() -> None:
    assert acquisition_browser_runtime._display_proxy(
        "http://user-name:pass-word@31.58.9.4:6077"
    ) == "http://***:***@31.58.9.4:6077"


@pytest.mark.asyncio
async def test_block_unneeded_route_allows_fonts_and_protected_challenge_urls() -> None:
    events: list[str] = []

    class FakeRoute:
        def __init__(self, *, resource_type: str, url: str) -> None:
            self.request = SimpleNamespace(resource_type=resource_type, url=url)

        async def abort(self) -> None:
            events.append(f"abort:{self.request.resource_type}:{self.request.url}")

        async def continue_(self) -> None:
            events.append(f"continue:{self.request.resource_type}:{self.request.url}")

    await acquisition_browser_runtime._block_unneeded_route(
        FakeRoute(
            resource_type="font",
            url="https://www.autozone.com/assets/fonts/site-font.woff2",
        )
    )
    await acquisition_browser_runtime._block_unneeded_route(
        FakeRoute(
            resource_type="script",
            url="https://geo.captcha-delivery.com/captcha/?initialCid=abc",
        )
    )

    assert events == [
        "continue:font:https://www.autozone.com/assets/fonts/site-font.woff2",
        "continue:script:https://geo.captcha-delivery.com/captcha/?initialCid=abc",
    ]


@pytest.mark.asyncio
async def test_shared_browser_runtime_reuses_run_storage_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    persisted_states: list[tuple[int, dict[str, object]]] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "next-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            }

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )

    async def _fake_load_storage_state_for_run(run_id: int | None, **_kwargs):
        del _kwargs
        assert run_id == 77
        return {
            "cookies": [
                {
                    "name": "dd_session",
                    "value": "existing-cookie",
                    "domain": ".etsy.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://www.etsy.com",
                    "localStorage": [
                        {"name": "consent", "value": "accepted"},
                    ],
                }
            ],
        }

    async def _fake_persist_storage_state_for_run(
        run_id: int | None,
        storage_state: dict[str, object],
        **_kwargs,
    ) -> None:
        del _kwargs
        assert run_id == 77
        persisted_states.append((int(run_id), dict(storage_state)))

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "load_storage_state_for_run",
        _fake_load_storage_state_for_run,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "persist_storage_state_for_run",
        _fake_persist_storage_state_for_run,
    )

    async with runtime.page(run_id=77):
        pass

    assert captured_kwargs == [
        {
            "storage_state": {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "existing-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            }
        }
    ]
    assert persisted_states == [
        (
            77,
            {
                "cookies": [
                    {
                        "name": "dd_session",
                        "value": "next-cookie",
                        "domain": ".etsy.com",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": "https://www.etsy.com",
                        "localStorage": [
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            },
        )
    ]


@pytest.mark.asyncio
async def test_shared_browser_runtime_skips_storage_state_reuse_when_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )

    async def _boom(*args, **kwargs):
        raise AssertionError(f"storage state should not load: {args} {kwargs}")

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "load_storage_state_for_run",
        _boom,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "load_storage_state_for_domain",
        _boom,
    )

    async with runtime.page(
        run_id=77,
        domain="example.com",
        allow_storage_state=False,
    ):
        pass

    assert captured_kwargs == [{}]


@pytest.mark.asyncio
async def test_shared_browser_runtime_skips_domain_storage_for_proxied_runtime_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: list[dict[str, object]] = []
    domain_load_calls: list[str | None] = []
    domain_persist_calls: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            captured_kwargs.append(kwargs)
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(
        max_contexts=1,
        launch_proxy="http://proxy-one",
    )
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )

    async def _load_run(run_id: int | None, **_kwargs):
        del run_id, _kwargs
        return None

    async def _load_domain(domain: str | None, **_kwargs):
        del _kwargs
        domain_load_calls.append(domain)
        return {"cookies": [], "origins": []}

    async def _persist_domain(domain: str, storage_state: dict[str, object], **_kwargs) -> None:
        del storage_state, _kwargs
        domain_persist_calls.append(domain)

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "load_storage_state_for_run",
        _load_run,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "load_storage_state_for_domain",
        _load_domain,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "persist_storage_state_for_domain",
        _persist_domain,
    )

    async with runtime.page(run_id=77, domain="example.com"):
        pass

    assert captured_kwargs == [{}]
    assert domain_load_calls == []
    assert domain_persist_calls == []


@pytest.mark.asyncio
async def test_shared_browser_runtime_suppresses_storage_state_persist_failures(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    async def _boom(*args, **kwargs) -> None:
        del args, kwargs
        raise RuntimeError("boom")
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "persist_storage_state_for_run",
        _boom,
    )
    async def _no_state(run_id: int | None, **_kwargs):
        del run_id, _kwargs
        return None
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "load_storage_state_for_run",
        _no_state,
    )

    with caplog.at_level("ERROR", logger=acquisition_browser_runtime.logger.name):
        async with runtime.page(run_id=77):
            pass

    assert any(
        "Failed to persist browser storage state for run_id=77" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_shared_browser_runtime_bounds_hung_context_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocker = asyncio.Event()

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def storage_state(self) -> dict[str, object]:
            await blocker.wait()
            return {"cookies": [], "origins": []}

        async def close(self) -> None:
            await blocker.wait()

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_context_timeout_ms",
        50,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_close_timeout_ms",
        50,
    )

    with caplog.at_level("WARNING", logger=acquisition_browser_runtime.logger.name):
        async with asyncio.timeout(0.5):
            async with runtime.page(
                run_id=77,
                domain="example.com",
                allow_storage_state=False,
            ):
                pass

    assert any(
        "Timed out capturing browser storage state" in record.message
        for record in caplog.records
    )
    assert any(
        (
            "Timed out closing browser context" in record.message
            or "Browser context close was cancelled" in record.message
        )
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_shared_browser_runtime_close_bounds_hung_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    blocker = asyncio.Event()

    class FakeBrowser:
        async def close(self) -> None:
            await blocker.wait()

    class FakePlaywright:
        async def stop(self) -> None:
            await blocker.wait()

    class FakeBridge:
        async def close(self) -> None:
            await blocker.wait()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = FakePlaywright()
    runtime._socks5_auth_bridge = FakeBridge()

    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_close_timeout_ms",
        50,
    )

    with caplog.at_level("WARNING", logger=acquisition_browser_runtime.logger.name):
        async with asyncio.timeout(0.5):
            await runtime.close()

    assert runtime._browser is None
    assert runtime._playwright is None
    assert runtime._socks5_auth_bridge is None
    assert any(
        "Timed out closing browser runtime" in record.message
        for record in caplog.records
    )
    assert any(
        "Timed out stopping playwright" in record.message
        for record in caplog.records
    )
    assert any(
        "Timed out closing SOCKS5 auth bridge" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_persist_context_storage_state_normalizes_domain_before_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        async def storage_state(self) -> dict[str, object]:
            return {"cookies": [], "origins": []}

    persisted_domains: list[str] = []

    async def _persist_domain(domain: str, storage_state: dict[str, object], **_kwargs) -> None:
        del storage_state, _kwargs
        persisted_domains.append(domain)

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "persist_storage_state_for_domain",
        _persist_domain,
    )

    await acquisition_browser_runtime._persist_context_storage_state(
        FakeContext(),
        run_id=None,
        domain="  example.com  ",
    )

    assert persisted_domains == ["example.com"]


@pytest.mark.asyncio
async def test_persist_context_storage_state_skips_domain_persist_when_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        async def storage_state(self) -> dict[str, object]:
            return {
                "cookies": [
                    {
                        "name": "session",
                        "value": "abc",
                        "domain": ".example.com",
                        "path": "/",
                    }
                ],
                "origins": [],
            }

    persisted_domains: list[str] = []

    async def _persist_domain(domain: str, storage_state: dict[str, object], **_kwargs) -> None:
        del storage_state, _kwargs
        persisted_domains.append(domain)

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "persist_storage_state_for_domain",
        _persist_domain,
    )

    await acquisition_browser_runtime._persist_context_storage_state(
        FakeContext(),
        run_id=None,
        domain="example.com",
        persist_domain_storage_state=False,
    )

    assert persisted_domains == []


@pytest.mark.asyncio
async def test_persist_context_storage_state_skips_run_persist_when_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeContext:
        async def storage_state(self) -> dict[str, object]:
            return {
                "cookies": [
                    {
                        "name": "session",
                        "value": "abc",
                        "domain": ".example.com",
                        "path": "/",
                    }
                ],
                "origins": [],
            }

    persisted_run_ids: list[int] = []

    async def _persist_run(run_id: int | None, storage_state: dict[str, object], **_kwargs) -> None:
        del storage_state, _kwargs
        persisted_run_ids.append(int(run_id or 0))

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "persist_storage_state_for_run",
        _persist_run,
    )

    await acquisition_browser_runtime._persist_context_storage_state(
        FakeContext(),
        run_id=77,
        domain=None,
        persist_run_storage_state=False,
    )

    assert persisted_run_ids == []


@pytest.mark.asyncio
async def test_shared_browser_runtime_snapshot_tracks_queue_without_private_semaphore_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **kwargs):
            del kwargs
            return FakeContext()

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )

    async def _hold_page() -> None:
        async with runtime.page():
            entered.set()
            await release.wait()

    first = asyncio.create_task(_hold_page())
    await entered.wait()
    second = asyncio.create_task(_hold_page())
    await asyncio.sleep(0)

    snapshot = runtime.snapshot()

    assert snapshot["active"] == 1
    assert snapshot["queued"] == 1

    release.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_shared_browser_runtime_recycles_browser_without_deadlocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_events: list[str] = []
    new_events: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            new_events.append("context_closed")

    class FakeBrowser:
        def __init__(self, events: list[str]) -> None:
            self._events = events

        def is_connected(self) -> bool:
            return True

        async def new_context(self, **kwargs):
            del kwargs
            self._events.append("new_context")
            return FakeContext()

        async def close(self) -> None:
            self._events.append("browser_closed")

    class FakePlaywrightInstance:
        def __init__(self, events: list[str]) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)
            self._events = events

        async def _launch(self, **kwargs):
            del kwargs
            self._events.append("launched")
            return FakeBrowser(self._events)

        async def stop(self) -> None:
            self._events.append("playwright_stopped")

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance(new_events)

    class OldPlaywright:
        async def stop(self) -> None:
            old_events.append("playwright_stopped")

    runtime = crawl_fetch_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser(old_events)
    runtime._playwright = OldPlaywright()
    runtime._browser_launched_at = 1.0
    runtime._total_contexts_created = 1

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_max_contexts_before_recycle",
        1,
    )
    monkeypatch.setattr("patchright.async_api.async_playwright", lambda: FakePlaywrightManager())

    async with asyncio.timeout(1):
        async with runtime.page():
            pass

    assert old_events == ["browser_closed", "playwright_stopped"]
    assert new_events == ["launched", "new_context", "context_closed"]


@pytest.mark.asyncio
async def test_acquisition_shared_browser_runtime_recycles_after_driver_closed_on_new_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_events: list[str] = []
    new_events: list[str] = []

    class FakeContext:
        async def route(self, pattern: str, handler) -> None:
            del pattern, handler
            return None

        async def new_page(self):
            return object()

        async def close(self) -> None:
            new_events.append("context_closed")

    class DeadBrowser:
        def is_connected(self) -> bool:
            return True

        async def new_context(self, **kwargs):
            del kwargs
            raise Exception("Browser.new_context: Connection closed while reading from the driver")

        async def close(self) -> None:
            old_events.append("browser_closed")

    class FreshBrowser:
        def is_connected(self) -> bool:
            return True

        async def new_context(self, **kwargs):
            del kwargs
            new_events.append("new_context")
            return FakeContext()

        async def close(self) -> None:
            new_events.append("browser_closed")

    class FakePlaywrightInstance:
        def __init__(self) -> None:
            self.chromium = SimpleNamespace(launch=self._launch)

        async def _launch(self, **kwargs):
            del kwargs
            new_events.append("launched")
            return FreshBrowser()

        async def stop(self) -> None:
            old_events.append("playwright_stopped")

    class FakePlaywrightManager:
        async def start(self) -> FakePlaywrightInstance:
            return FakePlaywrightInstance()

    class OldPlaywright:
        async def stop(self) -> None:
            old_events.append("playwright_stopped")

    runtime = acquisition_browser_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = DeadBrowser()
    runtime._playwright = OldPlaywright()
    runtime._browser_launched_at = 1.0

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "build_playwright_context_spec",
        lambda **_: _context_spec(),
    )
    monkeypatch.setattr(
        acquisition_browser_runtime,
        "_patchright_async_playwright_factory",
        lambda: (lambda: FakePlaywrightManager()),
    )

    async with runtime.page():
        pass

    assert old_events == ["browser_closed", "playwright_stopped"]
    assert new_events == ["launched", "new_context", "context_closed"]

def test_browser_runtime_snapshot_reports_runtime_capacity_without_host_cache() -> None:
    snapshot = crawl_fetch_runtime.browser_runtime_snapshot()

    assert "preferred_hosts" not in snapshot
    assert "capacity" in snapshot


def test_real_chrome_candidate_paths_include_common_platform_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_real_chrome_executable_path",
        "",
    )

    candidates = acquisition_browser_runtime._real_chrome_candidate_paths()

    assert "/usr/bin/google-chrome" in candidates
    assert "/opt/google/chrome/chrome" in candidates
    assert "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" in candidates


def test_real_chrome_browser_available_requires_enabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        False,
    )

    assert acquisition_browser_runtime.real_chrome_browser_available() is False


@pytest.mark.asyncio
async def test_get_browser_runtime_evicts_idle_proxied_runtime_when_pool_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str | None, str]] = []
    closed: list[tuple[str | None, str]] = []

    class FakeRuntime:
        def __init__(self, *, max_contexts: int, launch_proxy: str | None = None, browser_engine: str = "chromium") -> None:
            del max_contexts
            self.launch_proxy = launch_proxy
            self.browser_engine = browser_engine
            self.browser_binary = browser_engine
            self._last_used_at = 0.0
            created.append((launch_proxy, browser_engine))

        def touch(self) -> None:
            self._last_used_at += 1

        def idle_seconds(self) -> float:
            return 999.0

        def bridge_used(self) -> bool:
            return False

        def eviction_key(self) -> tuple[int, float]:
            return (0, self._last_used_at)

        def snapshot(self) -> dict[str, int | bool | str]:
            return {"active": 0, "queued": 0, "ready": False, "browser_engine": self.browser_engine}

        async def close(self) -> None:
            closed.append((self.launch_proxy, self.browser_engine))

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "SharedBrowserRuntime",
        FakeRuntime,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_max_entries",
        1,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_idle_ttl_seconds",
        0,
    )

    await acquisition_browser_runtime.shutdown_browser_runtime()
    first = await acquisition_browser_runtime.get_browser_runtime(
        proxy="http://proxy-one",
        browser_engine="chromium",
    )
    second = await acquisition_browser_runtime.get_browser_runtime(
        proxy="http://proxy-two",
        browser_engine="real_chrome",
    )

    assert first is not second
    assert created == [
        ("http://proxy-one", "chromium"),
        ("http://proxy-two", "real_chrome"),
    ]
    assert closed == [("http://proxy-one", "chromium")]
    await acquisition_browser_runtime.shutdown_browser_runtime()


@pytest.mark.asyncio
async def test_get_browser_runtime_evicts_idle_direct_runtime_when_pool_is_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[tuple[str | None, str]] = []
    closed: list[tuple[str | None, str]] = []

    class FakeRuntime:
        def __init__(self, *, max_contexts: int, launch_proxy: str | None = None, browser_engine: str = "chromium") -> None:
            del max_contexts
            self.launch_proxy = launch_proxy
            self.browser_engine = browser_engine
            self.browser_binary = browser_engine
            self._last_used_at = 0.0
            created.append((launch_proxy, browser_engine))

        def touch(self) -> None:
            self._last_used_at += 1

        def idle_seconds(self) -> float:
            return 999.0

        def eviction_key(self) -> tuple[int, float]:
            return (0, self._last_used_at)

        def snapshot(self) -> dict[str, int | bool | str]:
            return {"active": 0, "queued": 0, "ready": False, "browser_engine": self.browser_engine}

        async def close(self) -> None:
            closed.append((self.launch_proxy, self.browser_engine))

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "SharedBrowserRuntime",
        FakeRuntime,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_max_entries",
        1,
    )
    monkeypatch.setattr(
        acquisition_browser_runtime.crawler_runtime_settings,
        "browser_runtime_pool_idle_ttl_seconds",
        0,
    )

    await acquisition_browser_runtime.shutdown_browser_runtime()
    first = await acquisition_browser_runtime.get_browser_runtime(browser_engine="chromium")
    second = await acquisition_browser_runtime.get_browser_runtime(browser_engine="real_chrome")

    assert first is not second
    assert created == [(None, "chromium"), (None, "real_chrome")]
    assert closed == [(None, "chromium")]
    await acquisition_browser_runtime.shutdown_browser_runtime()


@pytest.mark.asyncio
async def test_persist_storage_state_for_domain_commits_owned_session(db_session) -> None:
    domain = f"owned-session-{uuid4().hex}.example.com"
    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
    )

    rows = await cookie_store.list_domain_cookie_memory(domain)

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == domain


@pytest.mark.asyncio
async def test_persist_storage_state_for_domain_persists_test_domains(db_session) -> None:
    domain = f"owned-session-{uuid4().hex}.example.test"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(domain, session=db_session)

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == domain
    assert loaded is not None


@pytest.mark.asyncio
async def test_persist_storage_state_for_domain_strips_null_bytes(db_session) -> None:
    domain = f"null-byte-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc\x00def",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [
                        {"name": "cart", "value": '{"id":"123\x00"}'},
                    ],
                }
            ],
        },
        session=db_session,
    )

    loaded = await cookie_store.load_storage_state_for_domain(domain, session=db_session)

    assert saved is True
    assert loaded is not None
    assert loaded["cookies"][0]["value"] == "abcdef"
    assert loaded["origins"][0]["localStorage"][0]["value"] == '{"id":"123"}'


@pytest.mark.asyncio
async def test_persist_storage_state_for_domain_keeps_engine_specific_rows(db_session) -> None:
    domain = f"engine-scoped-{uuid4().hex}.example.com"

    chromium_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="chromium",
    )
    real_chrome_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "real-chrome-session",
                    "value": "2",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="real_chrome",
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    chromium_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="chromium",
    )
    real_chrome_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="real_chrome",
    )

    assert chromium_saved is True
    assert real_chrome_saved is True
    assert len(rows) == 2
    assert {str(row["browser_engine"]) for row in rows} == {"chromium", "real_chrome"}
    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert real_chrome_state == {
        "cookies": [
            {
                "name": "real-chrome-session",
                "value": "2",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
async def test_persist_storage_state_for_domain_persists_localhost_with_port(db_session) -> None:
    domain = "http://localhost:3000/products/widget"

    saved = await cookie_store.persist_storage_state_for_domain(
        domain,
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": "localhost",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory("localhost:3000", session=db_session)
    all_rows = await cookie_store.list_domain_cookie_memory(session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain("localhost:3000", session=db_session)

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["domain"] == "localhost:3000"
    assert any(row["domain"] == "localhost:3000" for row in all_rows)
    assert loaded is not None


@pytest.mark.asyncio
async def test_persist_storage_state_for_domain_accepts_iterable_storage_rows(
    db_session,
) -> None:
    domain = f"iterable-state-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": (
                {
                    "name": "session",
                    "value": "abc",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ),
            "origins": (
                {
                    "origin": f"https://{domain}",
                    "localStorage": (
                        {"name": "consent", "value": "accepted"},
                    ),
                },
            ),
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(domain, session=db_session)

    assert saved is True
    assert len(rows) == 1
    assert rows[0]["cookie_count"] == 1
    assert rows[0]["origin_count"] == 1
    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "abc",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [
            {
                "origin": f"https://{domain}",
                "localStorage": [
                    {"name": "consent", "value": "accepted"},
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_export_cookie_header_for_domain_dedupes_cookie_names(
    db_session,
) -> None:
    domain = f"handoff-cookie-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "root",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "session",
                    "value": "product",
                    "domain": f".{domain}",
                    "path": "/products",
                },
                {
                    "name": "_px3",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "consent",
                    "value": "yes",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [{"name": "consent", "value": "accepted"}],
                }
            ],
        },
        session=db_session,
        browser_engine="real_chrome",
    )

    header = await cookie_store.export_cookie_header_for_domain(
        f"https://{domain}/products/widget",
        session=db_session,
        browser_engine="real_chrome",
    )

    assert saved is True
    assert header == "session=product; consent=yes"


@pytest.mark.asyncio
async def test_export_cookie_header_for_domain_does_not_match_path_prefixes(
    db_session,
) -> None:
    domain = f"path-prefix-{uuid4().hex}.example.com"

    await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/foo",
        {
            "cookies": [
                {
                    "name": "prefix-only",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/foo",
                },
                {
                    "name": "nested",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/foo/bar",
                },
            ],
            "origins": [],
        },
        session=db_session,
    )

    header = await cookie_store.export_cookie_header_for_domain(
        f"https://{domain}/foobar",
        session=db_session,
    )

    assert header is None


@pytest.mark.asyncio
async def test_persist_storage_state_for_domain_keeps_patchright_isolated(
    db_session,
) -> None:
    domain = f"patchright-engine-{uuid4().hex}.example.com"

    chromium_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="chromium",
    )
    patchright_saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "patchright-session",
                    "value": "2",
                    "domain": f".{domain}",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        browser_engine="patchright",
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    chromium_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="chromium",
    )
    patchright_state = await cookie_store.load_storage_state_for_domain(
        domain,
        session=db_session,
        browser_engine="patchright",
    )

    assert chromium_saved is True
    assert patchright_saved is True
    assert len(rows) == 2
    assert {str(row["browser_engine"]) for row in rows} == {"chromium", "patchright"}
    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert patchright_state == {
        "cookies": [
            {
                "name": "patchright-session",
                "value": "2",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
async def test_load_host_protection_policy_tracks_patchright_as_browser_lane(
    db_session,
) -> None:
    url = f"https://patchright-policy-{uuid4().hex}.example.com/products/widget"

    blocked_policy = await host_protection_memory.note_host_hard_block(
        url,
        method="browser:patchright",
        session=db_session,
    )
    success_policy = await host_protection_memory.note_host_usable_fetch(
        url,
        method="browser:patchright",
        session=db_session,
    )

    assert blocked_policy.request_blocked is False
    assert blocked_policy.patchright_blocked is True
    assert blocked_policy.last_block_method == "browser:patchright"
    assert success_policy.patchright_success is True


@pytest.mark.asyncio
async def test_load_storage_state_for_domain_filters_existing_challenge_state(
    db_session,
) -> None:
    domain = f"poisoned-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            domain=domain,
            storage_state={
                "cookies": [
                    {
                        "name": "_pxvid",
                        "value": "challenge",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    {
                        "name": "session",
                        "value": "safe",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    {
                        "name": "datadome",
                        "value": "challenge-token",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    {
                        "name": "analytics",
                        "value": "bot_management:captcha",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                ],
                "origins": [
                    {
                        "origin": f"https://{domain}",
                        "localStorage": [
                            {"name": "PXapp_px_hvd", "value": "challenge"},
                            {"name": "safe-key", "value": "datadome blocked"},
                            {"name": "consent", "value": "accepted"},
                        ],
                    }
                ],
            },
            state_fingerprint="poisoned",
        )
    )
    await db_session.commit()

    loaded = await cookie_store.load_storage_state_for_domain(domain, session=db_session)

    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "safe",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [
            {
                "origin": f"https://{domain}",
                "localStorage": [
                    {"name": "consent", "value": "accepted"},
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_list_domain_cookie_memory_counts_stored_entries(db_session) -> None:
    domain = f"stored-count-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            domain=domain,
            storage_state={
                "cookies": [
                    {
                        "name": "session",
                        "value": "safe",
                        "domain": f".{domain}",
                        "path": "/",
                    },
                    "legacy-cookie-row",
                ],
                "origins": [
                    {"origin": f"https://{domain}", "localStorage": []},
                    "legacy-origin-row",
                ],
            },
            state_fingerprint="stored-count",
        )
    )
    await db_session.commit()

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)

    assert rows[0]["cookie_count"] == 2
    assert rows[0]["origin_count"] == 2


@pytest.mark.asyncio
async def test_persist_storage_state_for_domain_rejects_challenge_only_state(
    db_session,
) -> None:
    domain = f"challenge-only-{uuid4().hex}.example.com"

    saved = await cookie_store.persist_storage_state_for_domain(
        f"https://{domain}/products/widget",
        {
            "cookies": [
                {
                    "name": "_px2",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "pxcts",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
                {
                    "name": "datadome",
                    "value": "challenge",
                    "domain": f".{domain}",
                    "path": "/",
                },
            ],
            "origins": [
                {
                    "origin": f"https://{domain}",
                    "localStorage": [
                        {"name": "PXapp_px_fp", "value": "challenge"},
                        {"name": "safe-key", "value": "captcha page"},
                    ],
                }
            ],
        },
        session=db_session,
    )

    rows = await cookie_store.list_domain_cookie_memory(domain, session=db_session)
    loaded = await cookie_store.load_storage_state_for_domain(domain, session=db_session)

    assert saved is False
    assert rows == []
    assert loaded is None


@pytest.mark.asyncio
async def test_load_storage_state_for_domain_keeps_origin_when_local_storage_filters_empty(
    db_session,
) -> None:
    domain = f"origin-shell-{uuid4().hex}.example.com"
    db_session.add(
        DomainCookieMemory(
            domain=domain,
            storage_state={
                "cookies": [
                    {
                        "name": "session",
                        "value": "safe",
                        "domain": f".{domain}",
                        "path": "/",
                    }
                ],
                "origins": [
                    {
                        "origin": f"https://{domain}",
                        "localStorage": [
                            {"name": "PXapp_px_fp", "value": "challenge"},
                        ],
                    }
                ],
            },
            state_fingerprint="origin-shell",
        )
    )
    await db_session.commit()

    loaded = await cookie_store.load_storage_state_for_domain(domain, session=db_session)

    assert loaded == {
        "cookies": [
            {
                "name": "session",
                "value": "safe",
                "domain": f".{domain}",
                "path": "/",
            }
        ],
        "origins": [
            {
                "origin": f"https://{domain}",
                "localStorage": [],
            }
        ],
    }
