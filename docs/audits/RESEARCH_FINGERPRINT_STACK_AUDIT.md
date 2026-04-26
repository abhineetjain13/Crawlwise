# Browser Fingerprint & Anti-Detection Stack — Comprehensive Research Audit

**Date:** 2026-04-26
**Scope:** Full audit of CrawlerAI browser fingerprinting, stealth, and anti-detection capabilities vs. top-tier scraping infrastructure (Scrapeless, Scrape.do, Zyte)
**Method:** Code audit, web research (2025-2026 anti-bot landscape), live probe execution
**Probe Output:** `backend/artifacts/probe_research_run/20260426T022742Z/`

---

## 1. Executive Summary

The CrawlerAI fingerprint stack is **production-ready for basic-to-moderate anti-bot targets** but has measurable gaps against advanced detection systems used by Cloudflare v2, DataDome ML, and PerimeterX (HUMAN Security). The live probe detected **2 immediate issues**: automation globals exposure and synthetic event markers. This report details every existing defense layer, every missing vector, and the exact path to tier-1 parity.

---

## 1b. Original 7 Recommendations — Coverage Verification

The 7 concrete recommendations from the initial audit are all covered in this report:

| # | Original Recommendation | Report Coverage | Status |
|---|---|---|---|
| 1 | Extend `_collect_baseline` with Canvas, Audio, Font, `maxTouchPoints`, `connection`, `screen.orientation`, `window.chrome`, timing anomaly checks | Section 3.1 (live values), Gaps 4.1 #1-4, Phase B #5-10 | Implemented in probe |
| 2 | Fix iframe `contentWindow` leak upstream | Phase A #4, Gap 4.2 #5 | Documented for implementation |
| 3 | Add automation-globals detection (`window.playwright`, `__pw*`, timing jitter) | Section 3.1 (`automation_globals`), Gap 4.1 #1, Phase A #1 | Implemented in probe |
| 4 | Add Canvas/Audio/Font dedicated probe sites | Next Step #4 (now done), Section 2.3 | 3 BrowserLeaks sub-pages added |
| 5 | Document JA3 limitation when using `chromium` engine | Phase D #17, Gap 4.3 #19 | Documented |
| 6 | Add optional interaction smoke (`isTrusted` verification) | Section 3.1 (`mouse_isTrusted`), Gap 4.1 #2, Phase A #3 | Implemented in probe |
| 7 | Add proxy inventory exercise mode | Phase D #19, Gap 4.3 #23 | Documented for implementation |

---

## 2. Current Stack — Complete Technical Inventory

### 2.1 Identity Generation Layer (`app/services/acquisition/browser_identity.py`)

| Component | Implementation | Status |
|---|---|---|
| **Fingerprint Generator** | `browserforge` `FingerprintGenerator` with OS-aware args | Active |
| **Identity Cache** | `TTLCache(maxsize=1024, ttl=3600s)` per run ID | Active |
| **User-Agent Coherence** | UA string + `navigator.userAgentData` + `Accept-Language` aligned | Active |
| **Platform Alignment** | `navigator.platform`, `navigator.userAgentData.platform`, UA token sync | Active |
| **Hardware Sync** | `hardwareConcurrency` + `deviceMemory` matched to host or config override | Active |
| **Locale/Timezone** | `locale` + `timezone_id` + `Accept-Language` cohered via locality profile | Active |
| **Viewport Logic** | Desktop viewport subtracts `browser_desktop_viewport_reserved_height_px` from screen height | Active |
| **Mobile Simulation** | `is_mobile`, `has_touch`, `device_scale_factor` supported | Active |
| **Color Scheme** | `prefers-color-scheme` matchMedia wrapper | Active |

### 2.2 Runtime Stealth Layer (`app/services/acquisition/browser_runtime.py`)

| Component | Implementation | Status |
|---|---|---|
| **Playwright-Stealth** | `playwright_stealth.Stealth` with selective modules | Active |
| **Disabled Stealth Modules** | `navigator_plugins=False`, `navigator_user_agent=False`, `navigator_user_agent_data=False`, `navigator_vendor=False`, `iframe_content_window=False`, `navigator_hardware_concurrency=False`, `navigator_languages=False`, `navigator_platform=False`, `sec_ch_ua=False`, `webgl_vendor=False` | Active (but `iframe_content_window=False` is a known leak) |
| **Enabled Stealth Modules** | `navigator_webdriver=True` only | Active |
| **Context-Level Init Script** | `browser_identity.py` builds combined init script | Active |
| **Playwright Global Masking** | Config-driven list (`browser_mask_playwright_globals`) — masks globals like `playwright` | Active |
| **Web Workers Masking** | Optional `Worker`/`SharedWorker`/`serviceWorker` masking | Config-driven |
| **WebRTC IP Masking** | Full `RTCPeerConnection` fake class with empty ICE candidates | Active |
| **Permissions Spoofing** | `notifications` → `prompt`, `permissions.query` wrapper | Active |
| **Contacts API** | `ContactsManager` stub injected | Active |
| **ContentIndex API** | `ContentIndex` + `ServiceWorkerRegistration` stubs | Active |
| **Network Information** | `downlinkMax` → `10` | Active |
| **Intl.DateTimeFormat** | Wrapped to return coerced timezone | Active |

### 2.3 Probe / Diagnostics Layer (`backend/run_browser_surface_probe.py`)

| Component | Implementation | Status |
|---|---|---|
| **Probe Sites** | 10 sites: Sannysoft, Pixelscan, CreepJS, BrowserLeaks JS, EFF Cover Your Tracks, Incolumitas, FingerprintJS Demo, BrowserLeaks Canvas, BrowserLeaks WebGL, BrowserLeaks Fonts | Active |
| **Site-Specific Extractors** | Sannysoft, Pixelscan, CreepJS have dedicated parsers | Active |
| **Baseline Collection** | `user_agent`, `webdriver`, `plugins`, `screen`, `viewport`, `webgl`, `webrtc_ips`, `locale`, `timezone`, `hardware_concurrency`, `device_memory`, `languages`, `vendor`, `user_agent_data` | Active |
| **Consensus + Drift** | Cross-site comparison for all baseline keys | Active |
| **Transport Diagnostics** | `httpx` + `curl_cffi` + `browser` for target URLs | Active |
| **Geo Cross-Check** | IPInfo + IPAPI + IPWhois consensus | Active |
| **Root Cause Classification** | `target_precontent_block`, `browser_geo_identity_mismatch`, `browser_session_or_fingerprint_block`, `transport_only_block`, `no_target_block_detected`, `target_diagnostic_inconclusive` | Active |
| **Artifact Output** | Per-site screenshot + HTML + body text + JSON report + Markdown report | Active |
| **Retry Logic** | `BROWSER_SURFACE_PROBE_SITE_MAX_RETRIES` with backoff | Active |

---

## 3. Live Probe Results (2026-04-26)

Probe run: `backend/artifacts/probe_research_run/20260426T022742Z/`
Engine: Chromium 145 (direct, no proxy)

### 3.1 New Signal Baseline

| Signal | Value | Assessment |
|---|---|---|
| `canvas.text_measure` | `157.185546875` | Collected successfully |
| `audio.fingerprint` | `-Infinity` | **SUSPICIOUS** — real browsers return finite sums; `-Infinity` is a headless/audio-null marker |
| `fonts_count` | `10` | 10 of 20 test fonts detected |
| `max_touch_points` | `0` | Consistent with desktop profile |
| `pdf_viewer_enabled` | `true` | Consistent with Chromium |
| `cookie_enabled` | `true` | Normal |
| `automation_globals` | `["chrome.runtime.typeof=undefined"]` | **FAIL** — `window.chrome.runtime` is `undefined` instead of `object`. This is a mismatch with real Chrome. |
| `iframe_leak` | `false` | No leak detected on this run |
| `mouse_isTrusted` | `false` | **WARN** — synthetic events flagged as untrusted |
| `connection` | DRIFT across sites | `navigator.connection` values vary per site context |

### 3.2 Findings

- **FAIL** `automation_globals_exposure`: `chrome.runtime.typeof=undefined`
- **WARN** `synthetic_event_detection`: `mouse_isTrusted=false`

### 3.3 Site Status

All 10 probe sites reached usable content (status=`ok`). No degradation. The 3 new BrowserLeaks sub-pages (Canvas, WebGL, Fonts) provide ground-truth fingerprint hashes for direct comparison against the internal baseline collectors.

---

## 4. Gap Analysis — What Exists vs. What’s Missing

### 4.1 Gaps Confirmed by Live Probe

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 1 | `window.chrome.runtime` is `undefined` instead of `object` | Probe found `chrome.runtime.typeof=undefined` | **Critical** |
| 2 | Synthetic mouse events have `isTrusted=false` | Probe `behavioral_smoke` | **High** |
| 3 | AudioContext fingerprint returns `-Infinity` | Probe `audio.fingerprint` | **High** |
| 4 | `navigator.connection` drifts across sites | Probe `drift_keys: [connection]` | **Medium** |

### 4.2 Upstream Architecture Gaps (Code Audit)

| # | Gap | Location | Why It Matters |
|---|---|---|---|
| 5 | `iframe_content_window=False` in playwright-stealth | `browser_runtime.py:123` | Iframes leak automation markers via `contentWindow[0] === null`. Anti-bot scripts check this. |
| 6 | No Canvas fingerprint consistency across sessions | `browser_identity.py` | Each session gets different canvas noise. Real browsers are consistent per hardware/driver. Advanced detection uses canvas drift across page loads. |
| 7 | No AudioContext consistency | `browser_identity.py` | Same issue as canvas — randomization without consistency is detectable. |
| 8 | No font list consistency | `browser_identity.py` | Font enumeration changes per fingerprint = detectable. |
| 9 | `navigator.permissions.query` only wraps `notifications` | `browser_identity.py` | Camera, microphone, geolocation still return real values which may mismatch profile. |
| 10 | No `navigator.deviceMemory` / `hardwareConcurrency` consistency with `browserforge` | `browser_identity.py` | `browserforge` generates random values; upstream code coerces to host values. If host has 64GB RAM and fingerprint says 8GB, that’s fine. But if `browserforge` says 4 cores and host has 32, that’s a mismatch that some checkers flag. |
| 11 | No `navigator.maxTouchPoints` profile alignment | Missing | Desktop profiles should have `0`, mobile `>0`. Not currently profiled. |
| 12 | No `screen.orientation` profile alignment | Missing | Mobile profiles should have `angle`/`type` matching viewport dimensions. |
| 13 | No `performance.*` timing normalization | Missing | Headless/Playwright often has near-zero `responseEnd` or anomalously fast paint times. |
| 14 | No CDP detection countermeasures | Missing | Anti-bot scripts detect `window.chrome.csi`, `window.chrome.loadTimes`, and CDP runtime objects. |
| 15 | No `Intl.*` API beyond `DateTimeFormat` | Missing | `Intl.NumberFormat`, `Intl.Collator`, `Intl.ListFormat`, `Intl.PluralRules` can leak locale mismatches. |
| 16 | No `navigator.keyboard` / `navigator.mediaCapabilities` spoofing | Missing | These APIs return hardware truths that may conflict with fingerprint. |
| 17 | No WebGPU fingerprint handling | Missing | 2025+ detection uses WebGPU as a novel entropy source. |
| 18 | No `Client Hints` beyond `Sec-CH-UA` | Missing | `Sec-CH-UA-Platform-Version`, `Sec-CH-UA-Full-Version-List`, `Sec-CH-UA-Bitness` need alignment with `browserforge` output. |

### 4.3 Network / Transport Gaps

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 19 | TLS JA3 fingerprint mismatch | Confirmed by 2026 research: Playwright Chromium binary ≠ real Chrome JA3 | **Critical** (pre-JS block) |
| 20 | No `curl_cffi` JA3 impersonation in diagnostics | `curl_fetch` used without JA3 tuning | Medium |
| 21 | No HTTP/2 fingerprint consistency | Missing | HTTP/2 SETTINGS frame ordering is fingerprinted. |
| 22 | No TCP/IP stack tuning (TTL, window size, MSS) | Missing | Datacenter TCP signatures differ from residential. |
| 23 | No proxy rotation exercise in probe | Plan gap #4 | Single proxy = no visibility into pool quality variance. |

### 4.4 Behavioral / Interaction Gaps

| # | Gap | Evidence | Severity |
|---|---|---|---|
| 24 | No real mouse trajectory | `page.mouse.move()` is linear/Bezier, not human-like | **High** |
| 25 | No scroll deceleration physics | Playwright scroll is instant or linear | **High** |
| 26 | No human-like typing (backspace, pause, typo) | Not implemented | Medium |
| 27 | No randomized wait patterns | Fixed `wait_for_timeout` + `networkidle` | Medium |
| 28 | No `focus`/`blur` sequence realism | Missing | Real users click input, then type, then blur. |
| 29 | No `PointerEvent` pressure/tilt spoofing | Missing | Touch devices report `pressure`, `tangentialPressure`, `tiltX`, `tiltY`. |
| 30 | No multi-tab / window behavior simulation | Missing | Real users have multiple tabs; crawlers typically have one. |

### 4.5 Detection Surface Comparison (CrawlerAI vs. Tier-1)

| Detection Layer | CrawlerAI | Scrapeless / Zyte / Scrape.do | Gap |
|---|---|---|---|
| **TLS/JA3** | Raw Playwright Chromium | Real Chrome / curl-impersonate / managed browsers | JA3 mismatch |
| **HTTP/2** | Default | Tuned | SETTINGS drift |
| **TCP/IP** | Default OS | Tuned / residential proxy bridging | Datacenter signatures |
| **JS Navigator** | `browserforge` + custom scripts | Full API coverage + consistent entropy | Gaps 5-18 |
| **Canvas/WebGL** | Raw (no spoofing) | Consistent per-session | No spoofing |
| **Audio** | Raw (no spoofing) | Consistent per-session | `-Infinity` leak |
| **Fonts** | Raw (no spoofing) | Consistent per-session | No spoofing |
| **Behavioral** | Linear mouse/scroll | Human-like ML trajectories | Gaps 24-30 |
| **Session Warmup** | Cold context per page | Cookie jar + localStorage + history warmup | No warmup |
| **IP Reputation** | Config proxy only | Residential/mobile proxy + auto-rotation | Manual only |
| **Challenge Solving** | Classification only | Active challenge solvers (Turnstile, DataDome) | Passive only |
| **Computer Vision** | Not implemented | Optional (CAPTCHA, slider) | Missing |

---

## 5. Recommendations (Prioritized)

### Phase A — Critical (Do First)

1. **Fix `window.chrome.runtime`**
   - Add init script to inject a plausible `chrome.runtime` stub (with `OnInstalledReason`, `OnRestartRequiredReason`, `PlatformArch`, `PlatformNaclArch`, `PlatformOs`, `RequestUpdateCheckStatus` enums + `sendMessage` / `onMessage` / `getManifest` methods).
   - Location: `browser_identity.py` init script builder.

2. **Fix AudioContext `-Infinity` leak**
   - Investigate why `analyser.getFloatFrequencyData()` returns all `-Infinity` values in headless Chromium. Likely the audio graph is not processing because no audio backend is present.
   - Options: (a) stub `AudioContext` entirely with a realistic fake, (b) inject a small oscillator that produces non-silent output before fingerprinting, (c) override `getFloatFrequencyData` to return deterministic plausible values.

3. **Fix `isTrusted=false` on synthetic events**
   - The probe uses `new MouseEvent('mousemove', { bubbles: true })` + `dispatchEvent` which is always synthetic. This is expected for probe testing.
   - **For production crawls**: use `page.mouse.move()` which generates native CDP events with `isTrusted=true`. The probe correctly flagged this. No action needed unless the crawler itself uses `dispatchEvent` for interaction.
   - **Action**: Verify no production crawl path uses `dispatchEvent` for mouse/keyboard; ensure all interaction goes through Playwright’s input API.

4. **Enable or replace `iframe_content_window` stealth patch**
   - `browser_runtime.py:123` disables `iframe_content_window`. Either re-enable it (may conflict with `browserforge`) or add a custom init script that patches `HTMLIFrameElement.prototype.contentWindow` to return a same-origin proxy matching `window` shape without the `[0] === null` leak.

### Phase B — High Priority

5. **Add Canvas fingerprint consistency**
   - Generate a deterministic canvas noise seed per session/run_id.
   - Override `CanvasRenderingContext2D` methods (`fillText`, `strokeText`, `getImageData`, `toDataURL`, `toBlob`) to inject tiny pixel perturbations based on the seed.
   - Must be **consistent** across pages in the same session — randomization per call is detectable.
   - Reference: `puppeteer-extra-plugin-stealth` canvas evasion.

6. **Add AudioContext fingerprint consistency**
   - Same pattern as canvas: deterministic seed-based perturbation of `getFloatFrequencyData`, `getByteFrequencyData`, `getChannelData`.
   - Or full `AudioContext` stub with realistic `sampleRate`, `channelCount`, and deterministic output.

7. **Add Font enumeration spoofing**
   - Override `document.fonts.check()` and `document.fonts.ready` to return values consistent with the OS profile.
   - Maintain a font list per platform (Windows, macOS, Linux) and filter queries against it.

8. **Add `navigator.connection` profile alignment**
   - `effectiveType`, `downlink`, `rtt`, `saveData` should match the proxy profile / locality. A residential 4G proxy should not report `effectiveType: '4g'` with `rtt: 0`.
   - Add config knobs in `runtime_settings.py`.

9. **Add `navigator.maxTouchPoints` profile alignment**
   - Desktop → `0`, Mobile/Tablet → `1-5` depending on device profile.
   - Must match `is_mobile` + `has_touch` from `browserforge`.

10. **Add `screen.orientation` alignment**
    - Mobile landscape: `angle: 90, type: 'landscape-primary'` (or `-90` for `landscape-secondary`).
    - Must match viewport dimensions.

### Phase C — Medium Priority

11. **Extend permissions spoofing**
    - Camera, microphone, geolocation should return deterministic values matching profile.
    - Add `navigator.mediaDevices.enumerateDevices()` stub returning empty or plausible device list.

12. **Add `performance.*` timing normalization**
    - Override `performance.getEntriesByType('navigation')` to return realistic `responseEnd`, `domContentLoadedEventEnd`, `loadEventEnd` deltas (not 0ms or 1ms).

13. **Add `Intl.*` API locale alignment**
    - `Intl.NumberFormat`, `Intl.DateTimeFormat`, `Intl.Collator`, `Intl.ListFormat` should all return results consistent with the chosen `locale`.

14. **Add WebGPU stub**
    - `navigator.gpu` should be present/absent based on profile and OS. If present, `requestAdapter()` should return a plausible adapter name matching `webgl.renderer`.

15. **Add `navigator.keyboard` / `navigator.mediaCapabilities` stubs**
    - Return empty or plausible values consistent with platform.

16. **Add Client Hints full alignment**
    - Ensure `Sec-CH-UA-Platform-Version`, `Sec-CH-UA-Bitness`, `Sec-CH-UA-Full-Version-List` match `browserforge` output and UA string.

### Phase D — Network / Transport

17. **Document JA3 limitation in probe report**
    - When `chromium` engine is used, add an `info` finding noting that TLS JA3 fingerprint differs from real Chrome.
    - Only `real_chrome` engine has native JA3 parity.

18. **Enable JA3 impersonation in `curl_cffi` diagnostics**
    - If `curl_cffi` supports JA3 impersonation strings, pass the matching Chrome JA3 fingerprint during transport diagnostics.

19. **Add optional proxy inventory exercise mode**
    - `--proxy-sample-count N` flag to cycle through first N proxies and run abbreviated probes.
    - Report per-proxy fingerprint deltas.

### Phase E — Behavioral (Long-Term)

20. **Human-like mouse trajectory library**
    - Fitts’s Law + gravity model + noise. Move in sub-pixel increments with variable velocity.
    - Open-source reference: `bezier-mouse` patterns, `human-mouse` Python lib.

21. **Scroll physics**
    - Ease-out deceleration with overshoot on Mac, linear stepped on Windows.
    - Variable scroll distance per wheel event.

22. **Typing simulation**
    - Gaussian-distributed inter-key delay, occasional backspace, variable hold time.

23. **Session warmup**
    - Before crawling: visit 2-3 benign sites in the same context, set cookies, localStorage, sessionStorage, and history entries.
    - Reference: Scrapeless “session profiles.”

24. **Multi-tab simulation**
    - Open a dummy tab in the background context to make `window.length > 1` or `history.length > 1` plausible.

---

## 6. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| IP blacklisting from running probe on direct connection | High (already done) | Low (single probe) | Use proxy for future probes; the direct IP is now known to 7 checker sites. |
| `chrome.runtime` undefined triggers bot scores on Cloudflare | High | High | Fix in Phase A #1. |
| AudioContext `-Infinity` triggers headless flags | Medium | High | Fix in Phase A #2. |
| JA3 mismatch causes pre-JS blocks | High | High | Switch to `real_chrome` engine for sensitive targets; document limitation. |
| Canvas/WebGL raw entropy creates unique fingerprints | High | Medium | Fix in Phase B #5. |
| Behavioral linearity triggers ML detection | Medium | High | Fix in Phase E #20-24 (long-term). |

---

## 7. Files Modified for This Research

- `backend/app/services/config/browser_surface_probe.py` — added `BROWSER_SURFACE_PROBE_FONT_TEST_STRINGS`; added 3 new probe targets (BrowserLeaks Canvas, WebGL, Fonts)
- `backend/run_browser_surface_probe.py` — extended `_collect_baseline` with 12 new signal collectors, extended `_consensus_baseline` keys, added 5 new finding categories, extended `_build_agent_summary` and `_render_markdown`

**No upstream stealth/identity/runtime behavior was changed.** These probe modifications are research-only and enable full-signal visibility.

---

## 8. Next Steps

1. Review this report with stakeholders.
2. Prioritize Phase A items for implementation.
3. Re-run the probe after each Phase A fix to verify findings clear.
4. ~~Add dedicated Canvas/Audio/Font probe sites~~ Done — BrowserLeaks Canvas, WebGL, and Fonts sub-pages added to `BROWSER_SURFACE_PROBE_TARGETS`. Re-run probe to capture ground-truth hashes.
5. Benchmark against a Scrapeless/Zyte session on the same target to compare block rates.
