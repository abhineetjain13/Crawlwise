# Fingerprint Probe Plan

## Status
- Last updated: 2026-04-25
- State: implemented, active for hardening
- Owner area: `backend/run_browser_surface_probe.py` + acquisition runtime/identity stack

## Goal
Use one operator probe to measure real browser identity exposure using the same acquisition runtime path as production crawls. No fake lab path. No downstream patching.

## Current Acquisition Implementation (Accurate)

### 1. Runtime parity with crawler path
- Probe uses `get_browser_runtime(...).page(...)` from acquisition runtime.
- Context spec comes from `build_playwright_context_spec(...)`.
- Same launch args, Browserforge fingerprint shaping, init script injection, stealth masking, permission shaping, WebRTC masking path.
- Supports `chromium` and `real_chrome`.

### 2. Identity coherence is upstream
- Identity alignment handled in `app/services/acquisition/browser_identity.py`.
- Coheres UA, UA-CH, navigator platform, locale/languages, timezone, Accept-Language, hardwareConcurrency, deviceMemory.
- Locality profile can align locale/timezone region; avoids mixed identity signals.
- No checker-specific spoof patches in probe script.

### 3. Proxy path fidelity
- Connection source can be:
1. `--run-id N` (reads stored run proxy/locality settings), or
2. explicit `--proxy` + optional `--proxy-profile-json`.
- Mixed mode (`--run-id` + explicit proxy flags) is rejected.
- SOCKS5 auth bridge path exists in acquisition proxy bridge and is runtime-tunable.
- Probe run uses selected live proxy and records masked inventory/metadata.

### 4. Fresh-state controls
- Probe page calls use `allow_storage_state=False` and `inject_init_script=True`.
- This keeps diagnostics on clean session shape and still exercises runtime init script path.

### 5. Defensive transport diagnostics
- Target diagnostics run three methods: `httpx`, `curl_cffi`, `browser`.
- Block classification uses shared acquisition classification (`classify_blocked_page`, header vendor signals, challenge evidence).
- Geo cross-check uses public endpoints and reports consensus.
- Root-cause classifier outputs mechanical categories (precontent block, browser-only block, geo-identity mismatch, transport-only block, inconclusive).

## Current Probe Scope

### Default probe sites (7)
1. `https://bot.sannysoft.com/`
2. `https://pixelscan.net/fingerprint-check`
3. `https://abrahamjuliot.github.io/creepjs/`
4. `https://browserleaks.com/javascript`
5. `https://coveryourtracks.eff.org/`
6. `https://bot.incolumitas.com/`
7. `https://fingerprintjs.github.io/fingerprintjs/`

### Extraction model
- Site-specific extractors:
1. `sannysoft`
2. `pixelscan`
3. `creepjs`
- Other sites use generic keyword/IP extraction.
- Baseline JS snapshot is collected per site, then merged into `consensus` + `drift`.

### Artifact contract
- Bundle path: `backend/artifacts/browser_surface_probe/<UTC stamp>/`
- Writes:
1. `report.json` (canonical)
2. `report.md`
3. per-site screenshot + html
4. target diagnostic artifacts (body/html/screenshot per method when used)

### Duplicate-control behavior
- Snapshot lines and rows deduped before report serialization.
- Raw counts preserved as `line_count_raw` / `row_count_raw`.
- Baseline no longer duplicates full per-site baseline block; keeps `consensus` + `drift`.

## Why This Implementation Is Strong
- Same runtime path as real acquisition. Probe findings are production-relevant.
- Upstream identity normalization prevents checker-chasing hacks.
- Multi-method diagnostics isolate transport vs browser failure domain.
- Degraded/failed probe sites do not destroy whole report; partial evidence still usable.
- Config/tunables stay in `app/services/config/*`, not hardcoded in runtime logic.

## Known Gaps / Next Hardening Slices
1. Add site-specific parser for high-value new sites (`browserleaks`, `cover_your_tracks`) to reduce generic-noise extraction.
2. Add optional per-site line/row cap overrides to cut very large pages (`fingerprintjs_demo`, `incolumitas`) without losing key signals.
3. Add historical drift compare mode (`current report` vs `previous stamp`) to detect stealth regressions automatically.
4. Add proxy-inventory exercise mode (sample >1 proxy) while preserving one-identity baseline semantics.
5. Add stricter recommendation mapping from findings -> exact upstream knob candidates (`runtime_settings` / `browser_identity`) with confidence labels.

## Verify Commands
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\test_browser_surface_probe.py -q
.\.venv\Scripts\python.exe run_browser_surface_probe.py --browser-engine chromium
```

## Non-Negotiables
- Fix upstream in acquisition/identity/runtime. Do not patch exports for fingerprint issues.
- Keep probe config in `app/services/config/browser_surface_probe.py`.
- Keep runtime tunables in `app/services/config/runtime_settings.py`.
- Keep LLM usage explicit and degradable; probe logic itself is deterministic.
