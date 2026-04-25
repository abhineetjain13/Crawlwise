from __future__ import annotations

from pathlib import Path
import pytest

from app.services.acquisition import browser_identity
from app.services.acquisition import browser_runtime as acquisition_browser_runtime
import run_browser_surface_probe as probe


def _report(
    *,
    timezone: str = "Asia/Kolkata",
    locale: str = "en-US",
    user_agent: str = "Mozilla/5.0 Chrome/145.0.0.0 Safari/537.36",
    webdriver: bool = False,
    webrtc_ips: list[str] | None = None,
    screen_drift: bool = False,
    pixelscan_country: str = "India",
    extracted_versions: list[int] | None = None,
    webdriver_hits: list[str] | None = None,
    headless_hits: list[str] | None = None,
) -> dict[str, object]:
    extracted_versions = extracted_versions if extracted_versions is not None else [145]
    webdriver_hits = webdriver_hits if webdriver_hits is not None else []
    headless_hits = headless_hits if headless_hits is not None else []
    screen_a = {"width": 1920, "height": 1080}
    screen_b = {"width": 1600, "height": 900} if screen_drift else dict(screen_a)
    viewport_a = {"width": 1280, "height": 720}
    viewport_b = {"width": 1024, "height": 768} if screen_drift else dict(viewport_a)
    per_site = {
        "sannysoft": {
            "user_agent": user_agent,
            "webdriver": webdriver,
            "locale": locale,
            "languages": [locale],
            "timezone": timezone,
            "screen": screen_a,
            "viewport": viewport_a,
            "webrtc_ips": list(webrtc_ips or []),
        },
        "pixelscan": {
            "user_agent": user_agent,
            "webdriver": webdriver,
            "locale": locale,
            "languages": [locale],
            "timezone": timezone,
            "screen": screen_b,
            "viewport": viewport_b,
            "webrtc_ips": list(webrtc_ips or []),
        },
        "creepjs": {
            "user_agent": user_agent,
            "webdriver": webdriver,
            "locale": locale,
            "languages": [locale],
            "timezone": timezone,
            "screen": screen_a,
            "viewport": viewport_a,
            "webrtc_ips": list(webrtc_ips or []),
        },
    }
    return {
        "baseline": probe._consensus_baseline(per_site),
        "sites": {
            "sannysoft": {
                "extracted": {
                    "signal_versions": list(extracted_versions),
                    "webdriver_hits": list(webdriver_hits),
                }
            },
            "pixelscan": {
                "extracted": {
                    "signal_versions": list(extracted_versions),
                    "country_values": [pixelscan_country],
                    "ip_values": ["8.8.8.8"],
                }
            },
            "creepjs": {
                "extracted": {
                    "signal_versions": list(extracted_versions),
                    "headless_hits": list(headless_hits),
                    "keyword_hits": {
                        "webdriver": list(webdriver_hits),
                        "headless": list(headless_hits),
                    },
                }
            },
        },
        "target_diagnostics": [],
    }


def _finding_categories(report: dict[str, object]) -> set[str]:
    return {str(item.get("category")) for item in probe.build_findings(report)}


def _target_diagnostic(
    *,
    geo_country: str = "US",
    browser_blocked: bool = True,
    httpx_blocked: bool = True,
    curl_blocked: bool = True,
    browser_status_code: int = 429,
    transport_status_code: int = 429,
) -> dict[str, object]:
    return {
        "url": "https://www.chewy.com/b/dry-food-294",
        "host": "www.chewy.com",
        "geo": {
            "consensus": {
                "country": geo_country,
                "timezone": "America/New_York",
                "ip": "37.202.206.253",
            }
        },
        "httpx": {
            "status": "ok",
            "blocked": httpx_blocked,
            "status_code": transport_status_code,
            "classification": {
                "outcome": "rate_limited" if httpx_blocked else "ok",
                "header_vendor": "akamai" if httpx_blocked else None,
                "provider_hits": ["akamai"] if httpx_blocked else [],
            },
        },
        "curl_cffi": {
            "status": "ok",
            "blocked": curl_blocked,
            "status_code": transport_status_code,
            "classification": {
                "outcome": "rate_limited" if curl_blocked else "ok",
                "header_vendor": "akamai" if curl_blocked else None,
                "provider_hits": ["akamai"] if curl_blocked else [],
            },
        },
        "browser": {
            "status": "ok",
            "blocked": browser_blocked,
            "status_code": browser_status_code,
            "challenge_cookie_names": ["_abck"] if browser_blocked else [],
            "classification": {
                "outcome": "rate_limited" if browser_blocked else "ok",
                "header_vendor": "akamai" if browser_blocked else None,
                "provider_hits": ["akamai"] if browser_blocked else [],
            },
        },
    }


def test_build_findings_flags_timezone_country_mismatch() -> None:
    categories = _finding_categories(
        _report(
            timezone="Asia/Kolkata",
            pixelscan_country="United States",
        )
    )
    assert "timezone_country_mismatch" in categories


def test_build_findings_flags_locale_and_ua_drift() -> None:
    categories = _finding_categories(
        _report(
            locale="en-US",
            pixelscan_country="India",
            extracted_versions=[146],
        )
    )
    assert "locale_region_drift" in categories
    assert "ua_version_drift" in categories


def test_build_findings_surfaces_webdriver_headless_and_webrtc() -> None:
    categories = _finding_categories(
        _report(
            webdriver_hits=["WebDriver (New) present (failed)"],
            headless_hits=["headless 33%"],
            webrtc_ips=["8.8.8.8"],
        )
    )
    assert "webdriver_exposure" in categories
    assert "headless_leakage" in categories
    assert "webrtc_leakage" in categories


def test_build_findings_flags_screen_and_viewport_drift() -> None:
    categories = _finding_categories(_report(screen_drift=True))
    assert "screen_viewport_drift" in categories


def test_build_findings_flags_target_precontent_block() -> None:
    report = _report(timezone="America/New_York", locale="en-US", pixelscan_country="United States")
    report["target_diagnostics"] = [_target_diagnostic()]
    categories = _finding_categories(report)
    assert "target_precontent_block" in categories


def test_build_findings_flags_browser_geo_identity_mismatch() -> None:
    report = _report(timezone="Asia/Kolkata", locale="en-IN", pixelscan_country="India")
    report["target_diagnostics"] = [
        _target_diagnostic(
            geo_country="US",
            browser_blocked=True,
            httpx_blocked=False,
            curl_blocked=False,
            browser_status_code=403,
            transport_status_code=200,
        )
    ]
    categories = _finding_categories(report)
    assert "browser_geo_identity_mismatch" in categories


def test_validated_target_url_rejects_non_http_and_local_targets() -> None:
    for url in ("file:///etc/passwd", "http://localhost/admin", "http://127.0.0.1/admin"):
        with pytest.raises(ValueError):
            probe._validated_target_url(url)


def test_geo_payload_from_text_accepts_alternate_provider_shapes() -> None:
    payload = probe._geo_payload_from_text(
        '{"ip":"8.8.8.8","country_code":"US","regionName":"California",'
        '"timezone":{"id":"America/Los_Angeles"},"connection":{"org":"Google"}}'
    )

    assert payload["country"] == "US"
    assert payload["region"] == "California"
    assert payload["timezone"] == "America/Los_Angeles"
    assert payload["org"] == "Google"


@pytest.mark.asyncio
async def test_build_report_uses_runtime_page_init_script_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    init_scripts: list[str] = []

    class FakePage:
        def __init__(self) -> None:
            self.url = "https://bot.sannysoft.com/"
            self._evaluate_payloads = [
                {
                    "user_agent": "Mozilla/5.0 Chrome/145.0.0.0 Safari/537.36",
                    "user_agent_data": None,
                    "webdriver": False,
                    "locale": "en-US",
                    "languages": ["en-US"],
                    "timezone": "UTC",
                    "platform": "Win32",
                    "vendor": "Google Inc.",
                    "plugins_count": 5,
                    "plugin_names": ["PDF Viewer"],
                    "hardware_concurrency": 8,
                    "device_memory": 8,
                    "screen": {"width": 1920, "height": 1080},
                    "viewport": {"width": 1280, "height": 720},
                    "webgl": {"vendor": "Google", "renderer": "ANGLE"},
                    "webrtc_ips": [],
                    "timestamp": "2026-04-24T00:00:00Z",
                },
                {
                    "line_count": 1,
                    "lines": ["WebDriver passed"],
                    "rows": [{"label": "WebDriver (New)", "value": "missing"}],
                    "has_creep_object": False,
                    "has_fingerprint_object": False,
                },
            ]

        async def goto(self, *_args, **_kwargs) -> None:
            return None

        async def wait_for_load_state(self, *_args, **_kwargs) -> None:
            return None

        async def wait_for_timeout(self, *_args, **_kwargs) -> None:
            return None

        async def evaluate(self, *_args, **_kwargs):
            return self._evaluate_payloads.pop(0)

        async def content(self) -> str:
            return "<html><body>ok</body></html>"

        async def screenshot(self, *, path: str, **_kwargs) -> None:
            Path(path).write_bytes(b"png")

        async def title(self) -> str:
            return "Sannysoft"

    class FakeContext:
        async def route(self, *_args, **_kwargs) -> None:
            return None

        async def add_init_script(self, script: str) -> None:
            init_scripts.append(script)

        async def new_page(self):
            return FakePage()

        async def close(self) -> None:
            return None

    class FakeBrowser:
        async def new_context(self, **_kwargs):
            return FakeContext()

    runtime = acquisition_browser_runtime.SharedBrowserRuntime(max_contexts=1)
    runtime._browser = FakeBrowser()
    runtime._playwright = object()

    async def _fake_runtime_provider(*, proxy: str | None = None, browser_engine: str = "chromium"):
        del proxy, browser_engine
        return runtime

    async def _noop_stealth(_target) -> None:
        return None

    monkeypatch.setattr(
        acquisition_browser_runtime,
        "build_playwright_context_spec",
        lambda **_: browser_identity.PlaywrightContextSpec(
            context_options={
                "user_agent": "Mozilla/5.0 Chrome/145.0.0.0 Safari/537.36",
                "viewport": {"width": 1280, "height": 720},
                "extra_http_headers": {},
                "locale": "en-US",
                "device_scale_factor": 1.0,
                "has_touch": False,
                "is_mobile": False,
                "service_workers": "block",
                "bypass_csp": False,
            },
            init_script="window.__fingerprint = true;",
        ),
    )
    monkeypatch.setattr(acquisition_browser_runtime, "_STEALTH_APPLIER", _noop_stealth)
    monkeypatch.setattr(
        probe,
        "BROWSER_SURFACE_PROBE_TARGETS",
        (
            {
                "id": "sannysoft",
                "label": "Sannysoft",
                "url": "https://bot.sannysoft.com/",
            },
        ),
    )

    await probe.build_report(
        runtime_source=probe.RuntimeSource(
            source_kind="direct",
            run_id=None,
            identity_run_id=123,
            proxy_list=[],
            proxy_profile={},
            locality_profile={"geo_country": "auto", "language_hint": None, "currency_hint": None},
            selected_proxy=None,
            selected_proxy_index=None,
            browser_engine="chromium",
        ),
        report_dir=tmp_path,
        runtime_provider=_fake_runtime_provider,
    )

    assert init_scripts == ["window.__fingerprint = true;"]


@pytest.mark.asyncio
async def test_build_report_keeps_partial_report_when_site_context_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeRuntime:
        def page(self, **_kwargs):
            class _Context:
                async def __aenter__(self):
                    raise RuntimeError("context failed")

                async def __aexit__(self, *_args):
                    return None

            return _Context()

        def snapshot(self) -> dict[str, object]:
            return {"ready": True}

    async def _fake_runtime_provider(*, proxy: str | None = None, browser_engine: str = "chromium"):
        del proxy, browser_engine
        return FakeRuntime()

    monkeypatch.setattr(
        probe,
        "BROWSER_SURFACE_PROBE_TARGETS",
        (
            {
                "id": "sannysoft",
                "label": "Sannysoft",
                "url": "https://bot.sannysoft.com/",
            },
        ),
    )
    monkeypatch.setattr(probe, "BROWSER_SURFACE_PROBE_SITE_MAX_RETRIES", 0)
    monkeypatch.setattr(probe, "BROWSER_SURFACE_PROBE_REQUEST_DELAY_MS", 0)

    report = await probe.build_report(
        runtime_source=probe.RuntimeSource(
            source_kind="direct",
            run_id=None,
            identity_run_id=123,
            proxy_list=[],
            proxy_profile={},
            locality_profile={"geo_country": "auto", "language_hint": None, "currency_hint": None},
            selected_proxy=None,
            selected_proxy_index=None,
            browser_engine="chromium",
        ),
        report_dir=tmp_path,
        runtime_provider=_fake_runtime_provider,
    )

    assert report["metadata"]["degraded"] is True
    assert report["sites"]["sannysoft"]["site_status"] == "failed"
    assert "probe_site_failure" in {
        finding["category"] for finding in report["findings"]
    }


@pytest.mark.asyncio
async def test_build_report_keeps_invalid_target_urls_as_failed_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeRuntime:
        def snapshot(self) -> dict[str, object]:
            return {"ready": True}

    async def _fake_runtime_provider(*, proxy: str | None = None, browser_engine: str = "chromium"):
        del proxy, browser_engine
        return FakeRuntime()

    async def _fake_target_diagnostic(*args, **kwargs):
        del args, kwargs
        return _target_diagnostic(browser_blocked=False, httpx_blocked=False, curl_blocked=False)

    monkeypatch.setattr(probe, "BROWSER_SURFACE_PROBE_TARGETS", ())
    monkeypatch.setattr(probe, "_run_target_diagnostic", _fake_target_diagnostic)

    report = await probe.build_report(
        runtime_source=probe.RuntimeSource(
            source_kind="direct",
            run_id=None,
            identity_run_id=123,
            proxy_list=[],
            proxy_profile={},
            locality_profile={"geo_country": "auto", "language_hint": None, "currency_hint": None},
            selected_proxy=None,
            selected_proxy_index=None,
            browser_engine="chromium",
        ),
        report_dir=tmp_path,
        target_urls=["http://localhost/admin", "https://www.chewy.com/b/dry-food-294"],
        runtime_provider=_fake_runtime_provider,
    )

    assert [item["url"] for item in report["target_diagnostics"]] == [
        "http://localhost/admin",
        "https://www.chewy.com/b/dry-food-294",
    ]
    assert report["target_diagnostics"][0]["browser"]["status"] == "failed"
    assert "target URL host must not be local" in report["target_diagnostics"][0]["browser"]["error"]
    assert report["target_diagnostics"][1]["browser"]["status"] == "ok"


@pytest.mark.asyncio
async def test_build_report_keeps_partial_target_diagnostics_when_one_target_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeRuntime:
        def snapshot(self) -> dict[str, object]:
            return {"ready": True}

    async def _fake_runtime_provider(*, proxy: str | None = None, browser_engine: str = "chromium"):
        del proxy, browser_engine
        return FakeRuntime()

    async def _fake_target_diagnostic(_runtime, *, url: str, **_kwargs):
        if url.endswith("/broken"):
            raise RuntimeError("target fetch failed")
        return _target_diagnostic(
            browser_blocked=False,
            httpx_blocked=False,
            curl_blocked=False,
        )

    monkeypatch.setattr(probe, "BROWSER_SURFACE_PROBE_TARGETS", ())
    monkeypatch.setattr(probe, "_run_target_diagnostic", _fake_target_diagnostic)

    report = await probe.build_report(
        runtime_source=probe.RuntimeSource(
            source_kind="direct",
            run_id=None,
            identity_run_id=123,
            proxy_list=[],
            proxy_profile={},
            locality_profile={"geo_country": "auto", "language_hint": None, "currency_hint": None},
            selected_proxy=None,
            selected_proxy_index=None,
            browser_engine="chromium",
        ),
        report_dir=tmp_path,
        target_urls=["https://example.com/broken", "https://www.chewy.com/b/dry-food-294"],
        runtime_provider=_fake_runtime_provider,
    )

    assert [item["url"] for item in report["target_diagnostics"]] == [
        "https://example.com/broken",
        "https://www.chewy.com/b/dry-food-294",
    ]
    assert report["target_diagnostics"][0]["browser"]["status"] == "failed"
    assert "RuntimeError: target fetch failed" in report["target_diagnostics"][0]["browser"]["error"]
    assert report["target_diagnostics"][1]["browser"]["status"] == "ok"
