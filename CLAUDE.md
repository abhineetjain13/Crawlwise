# CLAUDE.md

## Project

CrawlerAI is a POC crawler stack with:

- `backend/`: FastAPI + SQLAlchemy async backend, crawl worker loop, adapters, deterministic extraction pipeline, review/promotion flow.
- `frontend/`: Next.js app for crawl submission, run inspection, review, and admin views.
- `docs/`: product notes and implementation planning docs.

## Documentation Map

- `docs/backend-architecture.md`: current backend architecture and invariants only.
- `docs/backend-pending-items.md`: the single consolidated backend backlog for bugs, refactors, and follow-up architecture work.
- Root audit files are historical inputs, not the canonical backlog.

## Development authentication (POC)

- **Public registration is off by default.** `registration_enabled` defaults to `false` in `app/core/config.py` (`REGISTRATION_ENABLED` unset or false). `POST /api/auth/register` returns 403. The Register UI is informational only. For production multi-tenant use, set `REGISTRATION_ENABLED=true` in the backend environment and restore self-serve registration in the frontend.
- **Single bootstrap admin:** set `BOOTSTRAP_ADMIN_ONCE=1`, `DEFAULT_ADMIN_EMAIL`, and `DEFAULT_ADMIN_PASSWORD` (password rules in `app/services/auth_service.py`). Startup creates or repairs that admin user.
- **Dashboard “Reset data”** requires an admin session (`require_admin`), not merely any logged-in user.

## Control Ownership

User-selected crawl controls are authoritative. The backend must preserve them exactly as submitted.

- `surface` / page type is user-owned. Do not normalize, reinterpret, or reclassify `category`/listing vs `pdp`/detail in the backend.
- `settings.llm_enabled` is user-owned. Do not auto-enable LLM flows.
- `settings.advanced_mode` is user-owned. Traversal helpers (`paginate`, `scroll`, `load_more`) may run only when explicitly requested by the user.
- `settings.proxy_list` is user-owned. Do not auto-switch to hidden proxy policy or host-learned proxy behavior.
- Browser rendering escalation is allowed when acquisition needs a browser, but browser rendering does not authorize traversal. Rendering and traversal are separate decisions.
- If the user selects the wrong mode, fail visibly or return obviously poor results with diagnostics. Do not silently rewrite the request to "help".

## Current Crawl Contract

### Submission modes

- `run_type="crawl"`: single URL crawl submitted from the unified Crawl Studio.
- `run_type="batch"`: multi-URL loop submitted from pasted URLs.
- `run_type="csv"`: CSV upload, first column parsed as URL, header ignored when present.

### Page type

Page type is no longer split into separate frontend pages. The unified crawl UI uses:

- `settings.page_type="category"` with `surface="ecommerce_listing"`
- `settings.page_type="pdp"` with `surface="ecommerce_detail"`
- Frontend must derive `surface` directly from selected page type (`category`/`pdp`); do not expose an independent surface dropdown that can desynchronize payloads.

Category is the default page type in the UI.

### Crawl settings currently wired

- `settings.advanced_mode`: `null | "paginate" | "scroll" | "load_more"`
- `settings.max_pages`
- `settings.max_records`
- `settings.sleep_ms`
- `settings.proxy_list`
- `settings.llm_enabled`
- `settings.extraction_contract`: row-wise `field_name`, `xpath`, `regex`

`advanced_mode` is listing traversal only. It governs `paginate`, `scroll`, and `load_more` on listing pages. It does not control automatic browser rendering.

Automatic browser escalation is system-owned and independent of `advanced_mode`. The acquisition layer may still escalate from `curl_cffi` to Playwright for both listing and detail pages when curl output is blocked, redirected, empty, or structurally unusable.

## Backend State

### Pipeline architecture

The crawl pipeline follows: ACQUIRE → EXTRACT → UNIFY → PUBLISH

#### Acquisition layer (`services/acquisition/`)

- `acquirer.py`: Typed `AcquisitionResult` with content-type routing (html/json/binary)
- JSON responses detected via Content-Type header or body sniffing, parsed automatically
- HTML waterfall: curl_cffi → Playwright fallback (when JS-blocked or short content)
- `blocked_detector.py`: Post-acquisition blocked/challenge page detection with deterministic signatures for WAFs (PerimeterX, Cloudflare, Akamai, Datadome), CAPTCHA pages, access-denied pages
- `host_memory.py`: TTL-aware, file-backed acquisition history. It is diagnostic/supporting state, not authority for rewriting user-owned crawl controls.
- `browser_client.py`: Stealth context, challenge wait, origin warming, cookie consent dismissal, network XHR/fetch interception, unconditional interactive expansion before HTML capture
- Detail pages never run traversal helpers (`paginate` / `scroll` / `load_more`) even if `advanced_mode` is present; traversal is listing-only policy.
- Listing pages also never run traversal helpers unless `advanced_mode` was explicitly set by the user.
- Playwright sessions do not map requested field names to click plans. The browser path always runs `expand_all_interactive_elements(page)` and then captures the page.

#### Acquisition hardening rules

- Public target validation is fail-closed. If Python DNS resolution fails, the crawler does NOT silently allow the target through.
- Windows host DNS issues are handled by a guarded `nslookup` fallback inside `url_safety.py`; every resolved address is still validated as public before acquisition proceeds.
- `curl_cffi` hostname pinning must preserve hostname-based TLS. Use `CurlOpt.RESOLVE` on the session while keeping the original request URL; do not rewrite the request URL to a raw IP.
- Playwright contexts must not set a manual `Host` header. That caused `net::ERR_INVALID_ARGUMENT` on valid storefronts.
- Chromium host pinning, when used, must stay at the resolver-rule level only; connection-controlled headers are off limits.
- API startup must not mark queued `pending` runs as failed. Orphan recovery belongs to the worker path for jobs that were actually in-flight.
- Every successful acquire must persist a machine-readable diagnostics artifact alongside the HTML/JSON artifact. Transport and blocker regressions should be debugged from diagnostics files, not only log output.
- Persisted cookies are optional runtime state, never committed source data. Cookie reuse must be policy-filtered: anti-bot/challenge cookies are not persisted, expired cookies are ignored, and session cookies remain in-memory unless explicitly enabled by policy.
- Cookie policy can now carry domain-specific overrides from `data/knowledge_base/cookie_policy.json`; use explicit allowlists for benign cookies rather than widening the global persistence rules.
- Acquisition pacing and retry behavior are knowledge-base driven. Preventive backoff and host-spacing must come from `pipeline_tuning.json`, not hardcoded sleeps scattered across the codebase.
- Commerce redirect shells are invalid acquisition results. Same-host redirects from a requested commerce URL to `/` must not be accepted as success merely because the redirected page contains structured data.
- Acquisition diagnostics should expose per-URL timing phases when available: curl fetch, browser decision, browser launch, origin warm-up, navigation, challenge wait, listing readiness wait, traversal, acquisition total, and extraction total.
- Detail-page UI should surface acquisition metadata from `source_trace` so audits can see method, browser attempt status, challenge state, and final URL without opening raw diagnostics artifacts.
- Backend diagnostics may classify or describe what happened, but diagnostics must not silently mutate the user-requested crawl mode.

#### Acquisition hardening backlog

- **Intelligent Wait**
  - Extend browser challenge handling so the crawler waits for real page readiness after DataDome / Cloudflare interstitials, not just disappearance of challenge text.
  - Prefer readiness signals tied to the requested surface, such as product title, product price, or listing card selectors.
- **Shared Cookie Store**
  - Harvest policy-approved anti-bot/session-adjacent cookies from successful browser sessions and make them available to same-domain `curl_cffi` follow-up requests where policy permits.
  - Persistence must stay domain-scoped and policy-driven; challenge cookies remain deny-by-default unless explicitly approved.
- **TLS Fingerprint Rotation**
  - Expand HTTP impersonation beyond a fixed pair and support bounded browser-fingerprint rotation for repeated 403/429/503 style soft blocks.
  - Record the selected fingerprint in diagnostics for later analysis.

#### Extraction layer (`services/extract/`)

- `listing_extractor.py`: Structured-data-first strategy for listings:
  1. JSON-LD item lists / Product arrays
  2. Embedded app state (__NEXT_DATA__)
  3. Hydrated state objects (__NUXT__, __APOLLO_STATE__, etc.)
  4. Network payloads (XHR/fetch intercepted JSON)
  5. DOM card detection (CSS selectors + auto-detect heuristic)
  - `_extract_items_from_json` reads `max_json_recursion_depth` from `pipeline_tuning.json` (default `8`) to find deeply nested product arrays
  - Card title extraction uses ordered selectors (`[itemprop='name']` → `.title` → headings) and skips price-like text to prevent price/title confusion
  - Card auto-detect scores candidate groups by product signal density (link + image + price) instead of pure element count, preventing nav lists from winning over product tiles
  - Price text is cleaned via regex to strip surrounding UI text (e.g. "In stock Add to basket")
- `source_parsers.py`: Shared source parsing for `__NEXT_DATA__`, hydrated states, embedded JSON, Open Graph, JSON-LD, microdata, and tables
- `json_extractor.py`: First-class JSON API extraction — finds data arrays in nested JSON using 37 collection keys (including `products`, `jobs`, `drinks`, `books`, `categories`, etc.) plus GraphQL edges/node patterns. Falls back to preserving scalar fields under original keys when no canonical alias matches.
- `service.py`: Detail page extraction uses a strict first-match hierarchy per field: adapter → XHR/JSON payload → JSON-LD → hydrated state (`__NEXT_DATA__` / `__NUXT_DATA__`) → DOM selector defaults → LLM fallback
- `semantic_detail_extractor.py`: Extracts sections, specifications, label/value patterns from detail pages
- No manifest wrapper, evidence graph, or evidence bucket model exists between acquisition and extraction. Extraction takes plain `html`, `xhr_payloads`, and `url`.

#### Adapter registry (`services/adapters/`)

- Domain-matched adapters checked first, signal-based (Shopify) last
- Adapters: Amazon, Walmart, eBay, ADP, Workday, iCIMS, Indeed, LinkedIn Jobs, Greenhouse, Remotive/RemoteOK, Shopify
- Acquisition diagnostics now include an advisory `curl_platform_family` classification loaded from `platform_families.json`
- ADP: WorkForceNow recruitment DOM extraction for listing/detail pages after browser hydration
- Greenhouse: JSON API at boards-api.greenhouse.io + HTML fallback
- iCIMS: embedded-iframe board follow, AJAX pagination endpoint support, and HTML fragment parsing
- Workday: DOM extraction for listing/detail pages using `data-automation-id` signals
- Remotive/RemoteOK: HTML fallback (JSON-first path handles API responses directly)
- `try_blocked_adapter_recovery()`: When pages are blocked, attempt recovery via public platform endpoints (currently Shopify only)

#### Extraction verdicts

Runs now carry `extraction_verdict` in `result_summary`:
- `success`: core fields extracted (verdict based on core field presence only, NOT requested fields)
- `partial`: records saved but missing core fields
- `blocked`: anti-bot/challenge page detected
- `schema_miss`: JSON parsed but no records matched
- `listing_detection_failed`: listing page produced 0 records
- `empty`: no content extracted
- `error`: pipeline exception

Run status currently reflects verdict as: `completed` (`success`) and `failed` (all other verdicts, including `partial`, `listing_detection_failed`, `schema_miss`, `blocked`, `empty`, and `error`). Legacy `degraded` status is normalized to `failed`; the backend does not currently emit a separate `degraded` run status.

#### Listing fallback guard

Listing pages that produce 0 real item-level records are never downgraded into a single detail-style fallback record. They get `listing_detection_failed` verdict and a failed run status.

### Pipeline configuration (`services/pipeline_config.py`)

Pipeline config now imports typed Python constants from:

- `services/config/extraction_rules.py`
- `services/config/block_signatures.py`
- `services/config/selectors.py`
- `services/config/field_mappings.py`

Code should continue to import from `pipeline_config.py`, not duplicate config values in service code.

### Record field policy

- `record.data`: Only populated logical fields shown to users. Empty/null fields and `_`-prefixed internal fields are stripped in the API response.
- `record.discovered_data`: Large raw source containers are stripped from API responses. Only logical metadata (content_type, source, requested_field_coverage) is exposed.
- `record.raw_data`: Full raw extraction data, available for review/promote resolution but not shown in default views.
- `record.source_trace.field_discovery`: Deterministic field-level discovery summary for requested/additional fields. This is the primary backend contract for intelligence/review display: chosen value, source, and missing fields.
- `record.source_trace.acquisition`: Lightweight acquisition summary for UI/review use: final URL, browser attempt/use flags, challenge state, invalid-surface marker, and timing diagnostics.
- Requested field coverage is tracked in `discovered_data.requested_field_coverage` — it does NOT affect the extraction verdict.
- Review/LLM-oriented workflows should consume cleaned logical candidates plus preserved raw source evidence.

### Review service

- `discovered_fields` filters out structural container keys (`adapter_data`, `network_payloads`, `json_ld`, etc.) and empty-valued fields
- Only business-level fields with actual values from `record.data` and `record.raw_data` appear as review candidates
- Reviewed values can be persisted through `POST /api/crawls/{run_id}/commit-fields`; the old LLM commit path now delegates to the same backend write flow

### Current status snapshot

- Unified crawl contract is live: single-page submit flow with `run_type="crawl"`, user-owned controls, and explicit traversal-only advanced modes.
- Crawl runtime is DB-backed lease processing (`services/workers.py`) with stale lease recovery at startup; API no longer owns in-memory background orchestration.
- Extraction pipeline is ACQUIRE → EXTRACT → UNIFY → PUBLISH with listing fallback guard and deterministic first-match field resolution.
- Config is typed Python modules behind `pipeline_config.py`; no runtime selector CRUD/site-memory fallback subsystems in the active extraction path.
- Generic crawler paths are policy-driven: no tenant/site hardcodes; platform behavior is family-based and minimized to the required families.
- Browser-required policy for specific platform families (`PLATFORM_BROWSER_POLICIES`) overrides the default curl-first HTML waterfall (`curl_cffi` -> Playwright fallback); ATS URL classification uses known family domains (no loose host token guessing).
- Acquisition hardening remains active: curl-first waterfall, TLS-safe hostname pinning, fail-closed URL safety, observational diagnostics artifacts, policy-driven cookies.
- LLM/runtime behavior remains fail-fast on 429; dynamic field quality gates and JSON-LD structural filtering remain enforced.

## Tests

Run backend tests with:

```powershell
$env:PYTHONPATH='.'
pytest tests -q
```

The backend test mix covers adapters, acquisition, blocked detection, JSON extraction, listing extraction, crawl orchestration, review service, normalizers, security, host memory, requested field policy, URL safety, dashboard service, and worker recovery.
Use the current `pytest` collection as the source of truth for exact test counts.

Acquire-only smoke checks can be run without the full crawl pipeline:

```powershell
$env:PYTHONPATH='.'
python run_acquire_smoke.py api
python run_acquire_smoke.py commerce
python run_acquire_smoke.py jobs
python run_acquire_smoke.py hard
python run_acquire_smoke.py ats
python run_acquire_smoke.py specialist
```

Each smoke run now writes a timestamped JSON report under `artifacts/acquisition_smoke/`, and each successful acquire writes per-URL diagnostics under `artifacts/diagnostics/<run_id>/`.

Use these small batches first when validating acquisition changes. They are intentionally lighter and safer than a full `process_run()` audit, and they should remain free of site-specific fallback hacks.

Full extraction pipeline smoke tests (acquire + extract, no database):

```powershell
$env:PYTHONPATH='.'
python run_extraction_smoke.py
```

This exercises the complete acquisition and extraction pipeline without the database and writes a timestamped report under `artifacts/extraction_smoke/`.

## Architecture Invariants

These MUST be preserved across all changes:

1. **No duplicate magic values in service code.** Shared tunables live in the typed config modules imported through `pipeline_config.py`. Do not duplicate them in service code.
2. **Async-safe adapters.** All HTTP calls in async adapter methods MUST use `asyncio.to_thread()` for synchronous libraries (curl_cffi). Blocking the event loop causes visible user-facing latency.
3. **Verdict based on core fields only.** `_compute_verdict()` determines success/partial based on VERDICT_CORE_FIELDS presence. Requested field coverage is metadata, not a verdict input.
4. **Clean record API responses.** `CrawlRecordResponse.data` strips empty/null values and `_`-prefixed internal keys. `discovered_data` strips raw manifest containers. Users see only populated logical fields.
5. **Listing fallback guard.** Listing pages with 0 item records MUST get `listing_detection_failed` verdict. Never fall back to detail-style single-record extraction for listings.
6. **Review shows only actionable fields.** `discovered_fields` in review payloads excludes container keys and empty-valued fields.
7. **Pipeline config is the single source of truth** for: field aliases, collection keys, DOM patterns, card selectors, block signatures, consent selectors, verdict core fields, normalization rules.
8. **Acquisition must preserve usable content over brittle challenge heuristics.** Anti-bot signatures should only block when the page actually behaves like a challenge page, not merely because vendor markup exists in otherwise rich HTML.
9. **HTTP pinning must not break TLS identity.** Preserve the original hostname URL whenever using DNS pinning or SSRF hardening.
10. **Acquisition regressions must be diagnosable from artifacts.** Successful phase-1 runs should emit HTML/JSON artifacts plus per-URL diagnostics and smoke-run summaries so failures can be compared across batches without relying on transient logs.
11. **Cookie reuse must be policy-driven.** Do not commit site cookies. Persist only policy-approved cookies via `cookie_policy.json`, and treat challenge/session cookies as ephemeral unless explicitly allowed.
12. **Diagnostics must be observational.** Acquisition diagnostics should report only what actually happened during the fetch/render path; do not fabricate blocker causes, fallback reasons, or retry metadata.
13. **User-owned crawl controls must never be rewritten by the backend.** Do not normalize or reclassify `surface`, auto-enable LLM, auto-enable traversal, or auto-switch hidden proxy policy. If the user chose poorly, fail visibly instead of mutating the request.
14. **JS-shell detection may trigger Playwright rendering, not traversal.** Browser escalation is allowed for rendering blocked/empty/JS-shell pages, but pagination, infinite scroll, and load-more remain explicit `advanced_mode` actions only.
15. **Field extraction is first-match, not score-based.** For each field, resolution order is adapter → XHR/JSON payload → JSON-LD → hydrated state → DOM selector defaults → LLM fallback. First valid hit wins.
16. **Playwright expansion is generic, not field-routed.** No code path may use requested field names to decide what to click before capture; the browser path runs the same interactive expansion pass on every session.
17. **Deleted subsystems stay deleted.** Do not reintroduce site memory, selector CRUD, discovery manifests, evidence buckets, or runtime-editable per-domain extraction logic under new names.
18. **LLM calls must fail fast.** No retry/backoff on 429 errors — let the free API tier fail gracefully rather than blocking the pipeline with sleeps. Re-evaluate when using paid API keys.
19. **Dynamic field names must pass quality gates.** Single-char keys, JSON-LD type names, day-of-week patterns, and sentence-like labels (5+ underscores) are filtered from `record.data`. Zero-quality candidates are filtered from dynamic/intelligence fields. Candidate rows per field are capped at 5. New noise patterns should be added to config, not hardcoded.
20. **JSON-LD structural keys must not produce candidates.** `@type`, `@context`, `@id`, `@graph` are metadata, not data fields. `_deep_get_all_aliases` skips them before alias matching. Network payload noise (geo, tracking, widget APIs) must be filtered by URL pattern before entering the candidate pipeline.

