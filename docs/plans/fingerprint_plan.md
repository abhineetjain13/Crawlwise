Fingerprint Report Harness
Summary
Replace the current stale backend/run_browser_surface_probe.py behavior with a real fingerprint report runner that uses the same Playwright runtime path as crawls: launch args, Browserforge init script, stealth layer, proxy handling, and browser engine selection.
Default the run to the three fixed targets:
https://bot.sannysoft.com/
https://pixelscan.net/fingerprint-check
https://abrahamjuliot.github.io/creepjs/
Write a timestamped artifact bundle under backend/artifacts/browser_surface_probe/<stamp>/ with:
report.json
report.md
one screenshot per site
one raw page dump per site (.html or normalized text dump)
The report must answer one question cleanly: what fingerprint values the crawler exposed, where they disagree, and which disagreements look risky.
Current External Facts Checked 2026-04-24
- `bot.sannysoft.com` still exposes explicit result rows for WebDriver, WebDriver Advanced, Chrome, Plugins, Languages, WebGL Vendor/Renderer, Broken Image Dimensions, plus a larger fingerprint detail table. The runner should key off those visible rows, not old hardcoded assumptions.
- Pixelscan’s current public docs describe the check as covering UA integrity, OS consistency, canvas/WebGL, hardware parameters, timezone/language alignment, and automation indicators. The report should treat Pixelscan as the best current source for IP/country/timezone/proxy coherence.
- CreepJS’ official README says the only trusted live deployment is `https://abrahamjuliot.github.io/creepjs/` and that the page exposes `window.Fingerprint` and `window.Creep`. It currently emphasizes WebGL, audio, fonts, screen, resistance, and timezone/device signals rather than older “trust score” wording.
Key Changes
Rework run_browser_surface_probe.py to open pages through get_browser_runtime(...).page(...) from acquisition/browser_runtime.py, with:
allow_storage_state=False by default
one stable identity reused across all three sites in the same report run
proxy path sourced from either:
--run-id <crawl_run_id>: read settings_view.proxy_list() and settings_view.proxy_profile() from that stored run
or explicit --proxy <url> flags plus optional --proxy-profile-json <path>
explicit --browser-engine chromium|real_chrome, default chromium
reject ambiguous input when --run-id and explicit proxy flags are both provided
when a proxy list has multiple entries, use the first proxy for the live report run and record the full masked proxy inventory plus rotation mode in metadata so operators know what was and was not exercised
Add site-specific extraction in the runner, not in crawl acquisition code:
sannysoft: capture the visible result rows, especially webdriver, UA, plugins, languages, WebGL, screen/window metrics, and failed checks
pixelscan: capture browser/version, OS, IP, city/country, proxy verdict, JS timezone, JS time, IP time, language headers, screen size, WebGL, canvas/audio hashes
creepjs: capture FP ID/fuzzy ID, WebRTC section, timezone/intl, headless indicators, stealth indicators, UA/userAgentData, screen, navigator summary
Add a normalized baseline section to the report from direct JS evaluation in the same runtime:
navigator.userAgent, navigator.userAgentData when present, navigator.webdriver, locale/languages, timezone, platform, vendor, screen/viewport, plugins count, hardware concurrency, device memory, WebGL vendor/renderer, WebRTC-discovered IPs if available
Store that baseline both per site and as a consensus/drift summary across the full run so the report can catch unstable identity even when one public checker changes wording.
Add report findings logic that flags:
timezone/IP country mismatch
language/locale region drift relative to timezone/IP
UA/version drift across sources
headless leakage
webdriver exposure
WebRTC leakage
screen/viewport instability across sites
cross-site IP drift or country drift when a rotating proxy or leaking WebRTC path changes identity during the same report run
Update docs/CODEBASE_MAP.md only if needed to reflect the expanded operator-facing role of run_browser_surface_probe.py.
Public Interfaces
CLI shape:
run_browser_surface_probe.py [--run-id N | --proxy URL ...] [--proxy-profile-json PATH] [--browser-engine chromium|real_chrome] [--report-dir PATH]
Output contract:
report.json contains metadata, connection source, proxy mask, baseline values, per-site extracted values, and normalized findings
report.md is the human-readable summary with the same findings and artifact links
Findings severity:
fail: hard mismatch or direct automation leak
warn: suspicious drift likely to hurt trust
info: observed value without immediate risk
Test Plan
Add focused tests for report normalization and finding generation using synthetic extracted payloads:
timezone/IP mismatch becomes fail
locale/language drift becomes warn
UA/version mismatch across sources becomes fail
headless/webdriver exposure is surfaced
screen/viewport drift across site baselines is surfaced
Add a focused runner-path test that proves the report uses the context spec path with init script, not bare context options only.
Manual verify:
run the report with a real proxied crawl source via --run-id or explicit --proxy
confirm artifact bundle exists
confirm pixelscan fields are populated
confirm sannysoft no longer reports the stale webdriver=true false positive from the old script path
confirm creepjs evidence is captured even when the page wording changes
confirm the report records which exact proxy inventory entry was exercised when multiple proxies are configured
Assumptions
Use the crawler proxy path as the primary diagnostic target, not just direct local browsing.
Use fresh browser state for the report by default; fingerprint debugging should not inherit learned cookies/storage.
Keep the three target URLs fixed in the runner; do not generalize into a broader site harness yet.
As observed on 2026-04-24, creepjs did not expose a literal Trust Score in plain page text during live probing; the report should treat current headless/stealth sections as the authoritative replacement signal instead of keying on that old label.

Implementation Outcome 2026-04-24
- `backend/run_browser_surface_probe.py` is now an operator-facing diagnostic, not a standalone Playwright sample. It uses the shared browser runtime/context path so launch args, Browserforge identity, init scripts, proxy routing, WebRTC policy, and runtime pooling are exercised exactly like crawl acquisition.
- Probe artifacts are the source of truth for browser hardening changes. A useful report contains `report.json`, `report.md`, per-site HTML, screenshots, connection source metadata, direct JS baseline, per-site extraction, consensus/drift summary, and normalized findings.
- The successful path was not "more JS stealth first". The breakthrough was measuring the actual exposed surface across Sannysoft, Pixelscan, and CreepJS, then fixing upstream identity/runtime coherence where the report proved drift.
- Runtime hardware normalization belongs upstream in `browser_identity.py` and `runtime_settings.py`: host-consistent `hardwareConcurrency`, Chrome-bucketed `deviceMemory`, and matching page-JS values. Do not patch checker-specific output.
- Public checker failures are partial-report events, not runner failures. Each site records `site_status`, `attempts`, error text, and saved artifacts; failed/degraded sites produce warning findings while successful sites remain usable.
- Pixelscan's `Incognito Window` label remains the outstanding fingerprint target. Treat it as a persistent-profile/runtime-shape issue, not as another navigator-property shim.

Current Probe Pipeline
1. Run the probe through the same backend environment used for crawls:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe run_browser_surface_probe.py --browser-engine chromium
```

2. For a crawl/proxy identity, use `--run-id N` so the probe reads that run's `settings_view.proxy_list()` and `settings_view.proxy_profile()`. Do not mix `--run-id` with explicit `--proxy` flags.
3. Inspect `backend/artifacts/browser_surface_probe/<stamp>/report.json` first, then `report.md`. The JSON is canonical for regression comparison.
4. Check direct JS baseline against each public checker. Risky fixes are justified only when the report shows drift, direct automation leakage, WebRTC leakage, locale/timezone/IP mismatch, UA version mismatch, or screen/viewport instability.
5. Run focused tests after changing probe or identity behavior:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\test_browser_surface_probe.py tests\services\test_browser_context.py tests\services\test_crawl_fetch_runtime.py -q
.\.venv\Scripts\python.exe -m pytest tests\services\test_config_imports.py -q
```

6. Run at least one live commerce crawl after browser runtime changes. Browser hardening is only useful if acquisition still produces records without large timeout regressions.

Regression Rules
- Keep probe config in `app/services/config/browser_surface_probe.py`.
- Keep runtime tunables in `app/services/config/runtime_settings.py`.
- Keep crawler fixes upstream in acquisition/runtime/identity code. Do not compensate in publish/export code.
- Do not persist bot-defense challenge storage into domain memory or run-scoped browser state.
- If a batch/detail crawl times out while a single URL succeeds, inspect `_batch_runtime` timeout budgeting before touching extraction.
