# Browser Fingerprint & Anti-Detection Stack Audit

**Date:** 2026-04-26  
**Scope:** browser fingerprint surface, transport posture, and hard-target acquisition behavior  
**Method:** code audit, live probe runs, targeted Desertcart acceptance verification  
**Latest Chromium Probe:** `backend/artifacts/probe_followup_chromium/20260426T063426Z/`  
**Latest Real Chrome Probe:** `backend/artifacts/probe_followup_real_chrome/20260426T063426Z/`  
**Latest Desertcart Acceptance Run:** `backend/artifacts/test_sites_acceptance/20260426T060111Z__full_pipeline__test_sites_tail.json`

---

## 1. Executive Summary

CrawlerAI is now in a good state on the browser fingerprint layer and has a working real-browser fallback for protected ecommerce detail pages.

Current state:

- Chromium probe: **0 FAIL / 0 WARN / 1 INFO** (`chromium_ja3_limitation`)
- Real Chrome probe: **0 FAIL / 0 WARN / 1 INFO** (`no_risky_drift_detected`)
- BrowserLeaks Fonts now reports a small masked inventory instead of the prior large real inventory
- Desertcart detail now passes end to end in the full pipeline with **1 record**
- Chromium and `real_chrome` storage state are now persisted in isolated lanes, so cookies/localStorage do not bleed across profiles
- Browser diagnostics and URL metrics now persist explicit lane identity instead of relying on generic `browser` labels

Important conclusion from live testing:

- JA3 alone was **not** the full Desertcart root cause
- extra wait time alone was **not** the root cause
- managed `real_chrome` with full browser shaping still blocked on Desertcart detail
- `real_chrome` with a **native context + headful launch** cleared the Cloudflare wait challenge and produced a successful crawl

Real Chrome fallback now uses the local Chrome binary by default when available:

- Windows default path: `C:\Program Files\Google\Chrome\Application\chrome.exe`
- Override: `CRAWLER_RUNTIME_BROWSER_REAL_CHROME_EXECUTABLE_PATH`

Main remaining gaps:

- Chromium transport still has Playwright JA3 / JA4 / HTTP2 / HTTP3 / TCP drift
- behavioral realism is still basic
- there is still no active challenge solver / CV flow

---

## 2. Parameter / Signal Inventory

Status legend: **✅ Implemented** | **⚠️ Partial** | **❌ Missing**

### 2.1 Navigator Identity

| Signal | Implementation | Status |
|---|---|---|
| `navigator.userAgent` | `browserforge` generated + coherence repair | ✅ |
| `navigator.userAgentData` | Coherent brands/fullVersionList/mobile + high-entropy repair | ⚠️ |
| `navigator.platform` | Coerced to match UA token | ✅ |
| `navigator.hardwareConcurrency` | Host-coerced to match fingerprint | ✅ |
| `navigator.deviceMemory` | Host-coerced to match fingerprint | ✅ |
| `navigator.maxTouchPoints` | Init-script injected | ✅ |
| `navigator.language` / `languages` | Locality-aligned | ✅ |
| `navigator.connection` | Stable stubbed profile | ✅ |
| `navigator.permissions.query` | Wrapped for `notifications`, `camera`, `microphone`, `geolocation` | ✅ |
| `navigator.mediaDevices.enumerateDevices()` | Stubbed plausible device list | ✅ |
| `navigator.keyboard` | Stubbed with stable `getLayoutMap` / `lock` / `unlock` shape | ✅ |
| `navigator.mediaCapabilities` | Stubbed with stable `decodingInfo` / `encodingInfo` responses | ✅ |
| `navigator.gpu` | Stubbed with stable WebGPU surface and null adapter fallback | ✅ |

### 2.2 Screen / Viewport

| Signal | Implementation | Status |
|---|---|---|
| `screen.width/height/availWidth/availHeight` | `browserforge` + viewport harmonization | ✅ |
| `screen.colorDepth` / `pixelDepth` | `browserforge` generated | ✅ |
| `window.devicePixelRatio` | `browserforge` generated | ✅ |
| `screen.orientation` | Init-script injected from viewport geometry | ✅ |
| `window.outerWidth` / `outerHeight` | Coerced to match screen | ✅ |
| `window.innerWidth` / `innerHeight` | Coerced viewport | ✅ |

### 2.3 Automation Globals / CDP Surface

| Signal | Implementation | Status |
|---|---|---|
| `window.chrome.runtime` | Full stub with enums + methods | ✅ |
| `window.chrome.csi` | Plausible stub | ✅ |
| `window.chrome.loadTimes` | Plausible stub | ✅ |
| `window.playwright` / `__pw*` | Config-driven masking | ✅ |
| `window.cdc_*` | Stealth layer coverage | ✅ |
| `navigator.webdriver` | `false` via stealth / probe clean | ✅ |

### 2.4 Canvas / WebGL / Audio

| Signal | Implementation | Status |
|---|---|---|
| Canvas image data / data URL / blob | Deterministic seed-based noise | ✅ |
| WebGL parameter / extension / pixel reads | Profile-consistent spoofing + deterministic noise | ✅ |
| Audio frequency data | Deterministic perturbation | ✅ |
| Audio time-domain data | Deterministic perturbation | ✅ |
| `AudioBuffer.getChannelData` | Deterministic perturbation | ✅ |
| `OfflineAudioContext` constructor | Constructor path wrapped so direct instances inherit analyser masking | ✅ |

### 2.5 Fonts

| Signal | Implementation | Status |
|---|---|---|
| `document.fonts.check()` | Allowlist filter injected | ✅ |
| `document.fonts.ready` | Resolved promise override injected | ✅ |
| CSS font-family writes | Allowlist sanitization on `setProperty`, descriptors, `setAttribute('style')` | ✅ |
| Canvas font assignments | Sanitized on context `font` setter | ✅ |
| Font metric / width-based enumeration | Probe now reports masked small inventory (`Fonts count: 10`) | ✅ |

### 2.6 Iframes / Workers / WebRTC

| Signal | Implementation | Status |
|---|---|---|
| `iframe.contentWindow` leak | `iframe_content_window=True` in stealth | ✅ |
| Worker / SharedWorker / serviceWorker masking | Config-driven optional | ⚠️ |
| `RTCPeerConnection` ICE candidates | Fake class returning empty candidates | ✅ |

### 2.7 Timing / Performance

| Signal | Implementation | Status |
|---|---|---|
| `performance.getEntriesByType('navigation')` | Normalized monotonic timings | ✅ |
| `performance.now()` jitter profile | Residual low-severity drift on Chromium only | ⚠️ |

### 2.8 Internationalization

| Signal | Implementation | Status |
|---|---|---|
| `Intl.DateTimeFormat` | Wrapped with coerced timezone + locale | ✅ |
| `Intl.NumberFormat` | Default locale alignment wrapper | ✅ |
| `Intl.Collator` | Default locale alignment wrapper | ✅ |
| `Intl.ListFormat` | Default locale alignment wrapper | ✅ |
| `Intl.PluralRules` | Default locale alignment wrapper | ✅ |

### 2.9 Client Hints

| Signal | Implementation | Status |
|---|---|---|
| `Sec-CH-UA` / `Mobile` / `Platform` | Coherent headers generated | ✅ |
| `userAgentData.fullVersionList` | Repaired / enriched | ✅ |
| `userAgentData.platformVersion` | Enriched in JS high-entropy response | ✅ |
| `userAgentData.bitness` | Enriched in JS high-entropy response | ✅ |
| Header-side `Sec-CH-UA-Platform-Version` / `Bitness` | Coherent headers generated when high-entropy values exist | ✅ |

### 2.10 Behavioral / Interaction

| Signal | Implementation | Status |
|---|---|---|
| `MouseEvent.isTrusted` | Real Playwright input | ✅ |
| Cloudflare wait challenge activity | Jittered mouse activity + wait loop | ✅ |
| Pointer pressure / tilt | Not spoofed | ❌ |
| Scroll physics | Not implemented | ❌ |
| Typing simulation | Not implemented | ❌ |
| Session warmup | Minimal only | ⚠️ |
| Multi-tab simulation | Not implemented | ❌ |

### 2.11 Network / Transport

| Signal | Implementation | Status |
|---|---|---|
| TLS JA3 / JA4 on Chromium lane | Raw Playwright Chromium transport fingerprint | ❌ |
| TLS JA3 on browser fallback lane | `real_chrome` fallback available with native Chrome executable | ✅ |
| HTTP/2 SETTINGS / pseudo-header order | Browser-owned for browser lanes; still a monitored transport residual on Chromium | ⚠️ |
| HTTP/3 / QUIC upgrade behavior | Not explicitly tuned | ❌ |
| Real Chrome launch mode | Headful fallback lane for protected detail parity | ✅ |
| Real Chrome context policy | Native context by default for fetch path; probe can still inject scripts | ✅ |
| TCP/IP stack | Default OS | ❌ |
| `curl_cffi` impersonation | Enabled on HTTP lane (`impersonate=chrome131`) | ✅ |
| Proxy inventory exercise mode | Not implemented | ❌ |

---

## 3. Live Probe Results

### 3.1 Chromium Probe

Artifact: `backend/artifacts/probe_followup_chromium/20260426T063426Z/`

- **FAIL:** none
- **WARN:** none
- **INFO:** `chromium_ja3_limitation`

Key baseline:

| Signal | Value |
|---|---|
| `locale` | `en-IN` |
| `timezone` | `Asia/Kolkata` |
| `webdriver` | `false` |
| `iframe_leak` | `false` |
| `webrtc_ip_count` | `0` |
| `automation_globals_count` | `0` |
| `fonts_count` | `10` |
| `drift_keys` | `timing_jitter` |

### 3.2 Real Chrome Probe

Artifact: `backend/artifacts/probe_followup_real_chrome/20260426T063426Z/`

- **FAIL:** none
- **WARN:** none
- **INFO:** `no_risky_drift_detected`

Key baseline:

| Signal | Value |
|---|---|
| `locale` | `en-IN` |
| `timezone` | `Asia/Kolkata` |
| `webdriver` | `false` |
| `iframe_leak` | `false` |
| `webrtc_ip_count` | `0` |
| `automation_globals_count` | `0` |
| `fonts_count` | `10` |
| `drift_keys` | `timing_jitter` |

### 3.3 Font Evidence

Previous state:

- BrowserLeaks Fonts reported `214 fonts and 170 unique metrics found`

Current state:

- probe baseline now reports `Fonts count: 10`
- BrowserLeaks Fonts site completed cleanly in both Chromium and Real Chrome probe runs

Conclusion:

- metric-level font leakage is now materially reduced and no longer the top JS gap

---

## 4. Desertcart Detail Validation

Target:

- `https://www.desertcart.in/products/727923336-eat-yourself-healthy-food-to-change-your-life-american-measurements?source=search`

What was checked:

1. **Detail pipeline deviation**
   - No material divergence was found in the main acquisition path.
   - Listing and detail both go through `crawl_fetch_runtime.fetch_page(...)` and the shared browser runtime.
   - The real difference was target sensitivity plus the browser shaping applied on the fallback lane.

2. **Wait time vs JA3**
   - Extended challenge wait alone did **not** clear the page.
   - Managed `real_chrome` with shaped context also still blocked.
   - Native-context headful `real_chrome` cleared the wait challenge and produced usable detail HTML.

3. **Acceptance result**
   - Full pipeline run passed with `Records: 1`
   - Artifact: `backend/artifacts/test_sites_acceptance/20260426T060111Z__full_pipeline__test_sites_tail.json`

Current implementation choice:

- keep Chromium as the default cheap lane
- escalate to `real_chrome` when ecommerce hosts are blocked / protected
- run normal fetch-path `real_chrome` in a native context with stealth disabled by default
- keep run/domain browser storage scoped per lane so native real Chrome does not inherit shaped Chromium state
- keep probe runs able to inject scripts so fingerprint verification still works

Real Chrome toggles:

- `CRAWLER_RUNTIME_BROWSER_REAL_CHROME_ENABLED`
- `CRAWLER_RUNTIME_BROWSER_REAL_CHROME_EXECUTABLE_PATH`
- `CRAWLER_RUNTIME_BROWSER_REAL_CHROME_FORCE_HEADFUL`
- `CRAWLER_RUNTIME_BROWSER_REAL_CHROME_NATIVE_CONTEXT`
- `CRAWLER_RUNTIME_BROWSER_REAL_CHROME_APPLY_STEALTH`

---

## 5. Gap Analysis

| # | Gap | Layer | Severity | Notes |
|---|---|---|---|---|
| 1 | Chromium JA3 / JA4 mismatch | Transport | **Critical** | Chromium lane only |
| 2 | HTTP/2 SETTINGS / pseudo-header / priority drift | Transport | Medium | |
| 3 | HTTP/3 / QUIC upgrade behavior not tuned | Transport | Medium | |
| 4 | TCP/IP stack not tuned | Transport | Medium | |
| 5 | Pointer / scroll / typing realism is still basic | Behavioral | Medium | evaluated; no low-risk patch landed in this pass |
| 6 | No active challenge solver / CV flow | Challenge | Medium | wait-challenge only |

---

## 6. What Changed In This Pass

- added metric-level font masking, not just `document.fonts.check()`
- aligned `Intl.NumberFormat`, `Intl.Collator`, `Intl.ListFormat`, and `Intl.PluralRules`
- enabled real Chrome fallback by default when a local Chrome binary exists
- added separate real-Chrome launch/runtime controls in config
- added same-run Chromium -> Real Chrome engine replan after browser blocks
- reloaded host policy before browser escalation from exhausted HTTP attempts
- switched normal fetch-path Real Chrome to native context mode with stealth off by default
- isolated run-scoped and domain-scoped browser storage by engine so `chromium` and `real_chrome` no longer reuse each other's cookies/localStorage
- persisted explicit lane diagnostics (`browser_profile`, launch mode, native-context flag, stealth-enabled flag) into browser diagnostics and URL metrics
- fixed origin warmup so native `real_chrome` no longer re-applies stealth through the sibling warmup page
- kept probe-mode Real Chrome able to inject scripts for surface verification
- wrapped the `OfflineAudioContext` constructor path instead of masking only downstream audio reads
- added stable `navigator.keyboard`, `navigator.mediaCapabilities`, and `navigator.gpu` stubs
- aligned header-side `Sec-CH-UA-Platform-Version` and `Sec-CH-UA-Bitness` with repaired UA-CH data
- left the native real-Chrome fetch lane unchanged; no full shaping was re-enabled there
- evaluated low-risk behavioral realism and left it unchanged in this pass
- verified Desertcart detail with the acceptance harness
- reran both Chromium and Real Chrome probes and refreshed this audit

---

## 7. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Chromium lane still pre-blocks on JA3-sensitive hosts | High | High | use `real_chrome` fallback |
| Real Chrome behavior regresses if full shaping is re-enabled | Medium | High | keep native-context path isolated and configurable |
| Behavioral linearity still feeds ML scoring | Medium | Medium | add scroll / typing / pointer realism later |
| Probe-friendly behavioral changes regress trusted-input semantics | Medium | Medium | treat behavioral work separately from masking and re-probe both lanes |

---

## 8. Reference Files

### Identity / Runtime

- `backend/app/services/acquisition/browser_identity.py`
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/crawl_fetch_runtime.py`
- `backend/app/services/config/runtime_settings.py`

### Verification

- `backend/run_browser_surface_probe.py`
- `backend/run_test_sites_acceptance.py`
- `backend/tests/services/test_browser_context.py`
- `backend/tests/services/test_crawl_fetch_runtime.py`
- `backend/tests/test_browser_surface_probe.py`

---

## 9. Next Actions

1. Leave the Real Chrome fallback isolated. Do not fold full browser shaping back into that lane without retesting Desertcart-class targets.
2. If Chromium-only coverage still matters, next transport work is JA3 / JA4 / HTTP2 / HTTP3, not more JS noise.
3. If future hard targets still block after Real Chrome native mode, move next to behavioral realism or active challenge solving.
4. Treat behavioral realism as a separate pass with probe semantics tightened first, so trusted-input checks do not get blurred by the realism layer.
