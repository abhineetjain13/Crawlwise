# Browser Hardening Review — 2026-04-24

## Scope

- Full current git diff review, with focus on acquisition hardening, proxy handling, host memory, cookie/storage persistence, and changed tests.

## Verified

- 2026-04-24 follow-up review fixes:
  - `git diff --check`
  - `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_fetch_runtime.py tests/services/test_browser_context.py tests/services/test_browser_expansion_runtime.py -q`
- 2026-04-24 audit3/acquisition follow-up:
  - `git diff --check`
  - `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_block_detection.py tests/services/test_browser_context.py tests/services/test_browser_expansion_runtime.py tests/services/test_crawl_fetch_runtime.py tests/services/test_shared_variant_logic.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_state_mappers.py tests/services/test_pipeline_core.py tests/services/test_publish_metrics.py -q`
  - Result: `326 passed, 1 skipped`
  - `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe run_extraction_smoke.py`
  - Result: failed before execution because `backend/corpora/acceptance_corpus.json` is missing.
- Backend changed suites:
  - `backend/tests/services/test_batch_runtime.py`
  - `backend/tests/services/test_browser_context.py`
  - `backend/tests/services/test_browser_expansion_runtime.py`
  - `backend/tests/services/test_config_imports.py`
  - `backend/tests/services/test_crawl_fetch_runtime.py`
  - `backend/tests/services/test_crawl_service.py`
  - `backend/tests/services/test_crawls_api_domain_recipe.py`
  - `backend/tests/services/test_pipeline_core.py`
  - `backend/tests/services/test_publish_metrics.py`
- Frontend changed suites:
  - `frontend/components/crawl/crawl-config-screen.test.ts`
  - `frontend/components/crawl/crawl-config-screen.prefill.test.tsx`
  - `frontend/components/crawl/crawl-run-screen.test.tsx`
- Manual proxy connectivity check:
  - Sessionized ProxyScrape URL returned `200` from `https://httpbin.org/ip`

## Implemented Tweaks

- Browser launch now supports `--headless=new`.
- Browser request blocking stopped aborting fonts.
- Browser context identity now uses Browserforge init script and skips `playwright-stealth` when Browserforge is active.
- Desktop viewport now stays smaller than screen height.
- Challenge recovery now emits randomized mouse activity instead of fixed coordinates.
- Proxy handling moved to launch-owned browser runtimes.
- SOCKS5 auth bridge added for username/password upstream proxies.
- Sticky-session inference added for sessionized proxy usernames.
- Rotating proxy profiles now disable storage-state reuse and origin warmup.
- Challenge cookies and challenge localStorage values are filtered before persistence.
- Host protection memory now records browser-engine and request-vs-browser outcome state.
- Proxy controls are treated as explicit run controls, not saved domain profile state.
- Follow-up review fixes:
  - Restored `_px*`, `pxcts`, and `datadome` challenge-cookie filtering while keeping value-token filtering.
  - Proxy usernames are no longer rewritten unless an explicit proxy profile session-rewrite flag is set.
  - Blocked browser results are returned when later fallback attempts error instead of hiding block evidence.
  - Challenge recovery drops stale 403/429 status metadata after the rendered page clears the challenge.
- Audit3 follow-up fixes:
  - Browser contexts now grant configured permissions, currently `geolocation`.
  - Playwright globals are masked by init script even when Browserforge is unavailable.
  - Web Worker construction is masked by config to reduce Playwright/Kasada surface.
  - `navigator.webdriver` stealth is re-enabled and no longer skipped when Browserforge injection is active.
  - Challenge mouse activity now uses explicit noisy interpolation instead of Playwright's linear `steps` movement.
  - KPSDK/Kasada shells now classify as `blocked` / `challenge_page` instead of `low_content_shell`.
  - DOM radio variant group labels no longer use option `<label for=...>` text as the axis name.
- Fingerprint probe follow-up:
  - Browser surface probe became the required diagnostic loop for browser hardening: shared runtime path, direct JS baseline, public checker extraction, consensus/drift summary, and normalized findings.
  - Runtime hardware identity is normalized upstream so Browserforge identity and page JS agree on `hardwareConcurrency` and Chrome-style `deviceMemory`.
  - AutoZone two-detail batch timeout was traced to `_batch_runtime` outer URL timeout matching acquisition timeout; default URL budget now includes acquisition slack unless a user explicitly sets `url_timeout_seconds`.

## Live Probe Notes

- AutoZone listing and product still render DataDome challenge pages through current proxy/browser path.
- Real Chrome was available and tested; it still hit DataDome challenge pages, so engine selection alone did not clear AutoZone.
- Chewy returned a 748-byte KPSDK shell. After KPSDK signature config, the same failure is now reported as `blocked` / `challenge_page`, not listing detection failure.
- Etsy remains a DataDome `403` / challenge-page acquisition block in live probe.
- The current actionable failures are acquisition blocks, not downstream extraction failures, except the fixed DOM radio variant regression.

## Review Decision Log

### Selected Options

- Architecture Issue 1: Option A — restore challenge-cookie filters and keep value-token filters.
- Architecture Issue 2: Option A — gate proxy session rewriting behind explicit proxy profile controls.
- Architecture Issue 3: Option A — preserve blocked browser result unless a later attempt succeeds.
- Architecture Issue 4: Option A — avoid stale blocked response metadata after challenge recovery clears.
- Audit3 Issue 1: Implemented Playwright global masking and configured Web Worker masking.
- Audit3 Issue 2: Re-enabled non-colliding `navigator.webdriver` stealth with Browserforge.
- Audit3 Issue 3: Replaced linear challenge mouse movement with noisy manual interpolation.
- Audit3 Issue 4: Added configured context permissions.
- Extraction Issue 1: Fixed radio option labels being misread as variant axis labels.
- Fingerprint Follow-up Issue 1: Option A — keep browser surface probing as the first verification step before more stealth/runtime changes.
- Fingerprint Follow-up Issue 2: Option A — fix batch/detail crawl delays by separating outer URL timeout budget from acquisition timeout budget.
- Static Review Issue 1: Tightened timezone normalization so invalid timezone IDs fail closed.
- Static Review Issue 2: Preserved native `Intl.DateTimeFormat` descriptors while overriding resolved timezone.
- Static Review Issue 3: Disabled storage-state reuse for rotating proxy profiles and updated stale test coverage.
- Static Review Issue 4: Added singleflight locking to the SOCKS5 auth bridge startup path.
- Static Review Issue 5: Removed the recovered-response wrapper and records recovered status as metadata on the original response.
- Static Review Issue 6: Made browser surface probe per-site failures non-fatal with retry/status metadata.
- Static Review Issue 7: Replaced generic Kasada `ips.js` marker with Kasada-specific path markers.

### Deferred Items

- Stronger DataDome/Kasada bypass work remains deferred. Current proxy/browser path still gets challenged on AutoZone, Etsy, and Chewy.
- Pixelscan `Incognito Window` signature remains deferred to persistent-profile work. Do not handle it with checker-specific JS shims.
- Static review requests for notifier-based operator alerts remain deferred; probe artifacts and degraded findings are enough for this local operator workflow.

### Reviewed Not Applied

- Batch URL timeout fallback was kept. It is intentional: absent per-run timeout now uses acquisition timeout plus buffer; explicit `url_timeout_seconds` still wins.
- Browserforge init script exposure was already wired through `build_playwright_context_spec()` and `context.add_init_script()`.
- Asyncio exception filter install was already active in FastAPI lifespan and Celery worker startup; only a safe guard was added around lifespan install.
- `prefer_proxy` and `_RECENT_OUTCOME_STATE` flags were stale against current code. No such diagnostic key/map exists in the reviewed diff.

### Unresolved Decisions

- Code Quality: keep consolidation pass focused on deleting stale scratch docs, stale compatibility tests, and unused config once this hardening PR lands.
- Tests: keep browser surface probe and AutoZone two-detail batch as the release gates for this slice, alongside the targeted pytest suites listed above.
