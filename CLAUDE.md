# CLAUDE.md

## Project

CrawlerAI is a POC crawler stack with:

- `backend/`: FastAPI + SQLAlchemy async backend, crawl worker loop, adapters, deterministic extraction pipeline, review/promotion flow.
- `frontend/`: Next.js app for crawl submission, run inspection, review, selectors, admin views.
- `docs/`: product notes and implementation planning docs.

## Current Crawl Contract

### Submission modes

- `run_type="crawl"`: single URL crawl submitted from the unified Crawl Studio.
- `run_type="batch"`: multi-URL loop submitted from pasted URLs.
- `run_type="csv"`: CSV upload, first column parsed as URL, header ignored when present.

### Page type

Page type is no longer split into separate frontend pages. The unified crawl UI uses:

- `settings.page_type="category"` with `surface="ecommerce_listing"`
- `settings.page_type="pdp"` with `surface="ecommerce_detail"`

Category is the default page type in the UI.

### Crawl settings currently wired

- `settings.advanced_mode`: `null | "auto" | "paginate" | "scroll" | "load_more"`
- `settings.max_pages`
- `settings.max_records`
- `settings.sleep_ms`
- `settings.proxy_list`
- `settings.llm_enabled`
- `settings.extraction_contract`: row-wise `field_name`, `xpath`, `regex`

Advanced crawl is a single toggle-backed mode. There is no separate Spacraler implementation.

## Frontend State

### Implemented

- Unified crawl studio at `/crawl`
- Tabs for `Crawl`, `Batch`, and `CSV`
- Compact right-side crawl settings rail
- Category/PDP toggle, defaulting to Category
- Advanced crawl toggle + mode dropdown
- Proxy rotation toggle + list input
- LLM toggle kept separate and off by default
- Extraction contract editor with row-wise add/delete
- Legacy `/crawl/category` and `/crawl/pdp` routes now redirect to `/crawl`
- Root route now redirects to `/login`
- Protected app routes are gated by a frontend `me()` check before child pages mount

### Notes

- CSV submission uses multipart `POST /api/crawls/csv`
- Batch submission uses JSON `POST /api/crawls` with `run_type="batch"`

## Backend State

### Pipeline architecture

The crawl pipeline follows: ACQUIRE → BLOCKED DETECT → DISCOVER → EXTRACT → UNIFY → PUBLISH

#### Acquisition layer (`services/acquisition/`)

- `acquirer.py`: Typed `AcquisitionResult` with content-type routing (html/json/binary)
- JSON responses detected via Content-Type header or body sniffing, parsed automatically
- HTML waterfall: curl_cffi → Playwright fallback (when JS-blocked or short content)
- `blocked_detector.py`: Post-acquisition blocked/challenge page detection with deterministic signatures for WAFs (PerimeterX, Cloudflare, Akamai, Datadome), CAPTCHA pages, access-denied pages
- `host_memory.py`: TTL-aware, file-backed memory of which hosts need stealth TLS
- `browser_client.py`: Stealth context, challenge wait, origin warming, cookie consent dismissal, network XHR/fetch interception

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

#### Discovery layer (`services/discover/`)

- `service.py`: Produces `DiscoveryManifest` from HTML — discovers adapter data, network payloads, __NEXT_DATA__, JSON-LD, microdata, tables, hydrated state objects (__NUXT__, __APOLLO_STATE__, etc.)
- Discovery is intentionally source-preserving: adapter outputs, JSON-LD, intercepted network JSON, hydrated state, tables, and DOM-derived signals should all remain available for downstream reconciliation even when only one source wins deterministic extraction.
- Acquisition/discovery should optimize for preserving all useful source evidence in `raw_data`, `source_trace`, and manifest-derived structures; user-facing cleanup happens later in review/output layers.

#### Extraction layer (`services/extract/`)

- `listing_extractor.py`: Structured-data-first strategy for listings:
  1. JSON-LD item lists / Product arrays
  2. Embedded app state (__NEXT_DATA__)
  3. Hydrated state objects (__NUXT__, __APOLLO_STATE__, etc.)
  4. Network payloads (XHR/fetch intercepted JSON)
  5. DOM card detection (CSS selectors + auto-detect heuristic)
  - All structured sources are collected and ranked by field richness — sparse JSON-LD no longer short-circuits richer hydrated state data
  - `_extract_items_from_json` recurses up to depth 4 to find deeply nested product arrays
- `json_extractor.py`: First-class JSON API extraction — finds data arrays in nested JSON (supports `products`, `jobs`, `items`, `data`, `results`, GraphQL edges/node patterns)
- `service.py`: Detail page candidate extraction with priority: contract > adapter > network > __NEXT_DATA__ > JSON-LD > microdata > selectors > DOM patterns
- `semantic_detail_extractor.py`: Extracts sections, specifications, label/value patterns from detail pages

#### Adapter registry (`services/adapters/`)

- Domain-matched adapters checked first, signal-based (Shopify) last
- Adapters: Amazon, Walmart, eBay, Indeed, LinkedIn Jobs, Greenhouse, Remotive/RemoteOK, Shopify
- Greenhouse: JSON API at boards-api.greenhouse.io + HTML fallback
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

Run status reflects verdict: `completed` (success), `degraded` (partial/listing_detection_failed/schema_miss), `failed` (blocked/empty/error).

#### Listing fallback guard

Listing pages that produce 0 real item-level records are never downgraded into a single detail-style fallback record. They get `listing_detection_failed` verdict and `degraded` status.

#### Selector memory

Placeholder selectors like `[data-field='x']` are no longer saved. Selectors are only stored when sourced from an adapter, user contract, or validated DOM match.

### Pipeline configuration (`services/pipeline_config.py`)

All tunable values (field aliases, collection keys, DOM patterns, card selectors, normalization rules, verdict rules, block signatures, consent selectors, etc.) are loaded from JSON files in `data/knowledge_base/` at startup. Code MUST import from `pipeline_config` — never hardcode these values.

### Record field policy

- `record.data`: Only populated logical fields shown to users. Empty/null fields and `_`-prefixed internal fields are stripped in the API response.
- `record.discovered_data`: Raw manifest containers (adapter_data, json_ld, network_payloads, etc.) are stripped from API responses. Only logical metadata (content_type, source, requested_field_coverage) is exposed.
- `record.raw_data`: Full raw extraction data, available for review/promote resolution but not shown in default views.
- Requested field coverage is tracked in `discovered_data.requested_field_coverage` — it does NOT affect the extraction verdict.
- Review/LLM-oriented workflows should consume cleaned logical candidates plus preserved raw source evidence; do not throw away source-specific data during acquisition/discovery just because it is hidden from the default API view.

### Review service

- `discovered_fields` filters out structural container keys (`adapter_data`, `network_payloads`, `json_ld`, etc.) and empty-valued fields
- Only business-level fields with actual values from `record.data` and `record.raw_data` appear as review candidates

### Recent fixes

- Single-page frontend contract now uses `run_type="crawl"`
- Listing extractor now resolves relative URLs against the page URL
- Review payload now exposes extracted fields instead of manifest container keys
- Password hashing now uses `pbkdf2_sha256` instead of the broken bcrypt runtime path
- Shopify PDP adapter now scopes detail acquisition to `/products/<handle>.js`
- Extraction contract rows now feed XPath and regex candidate extraction
- Shopify adapter HTTP calls now use `asyncio.to_thread()` to avoid blocking the event loop
- Cookie consent selectors imported from `pipeline_config` (not hardcoded in browser_client)
- Verdict logic no longer downgrades to PARTIAL based on missing requested fields
- Acquisition always tries curl_cffi first, keeps result as Playwright fallback (fixes ERR_HTTP2_PROTOCOL_ERROR on Windows)
- Blocked detector splits provider markers into active (high confidence) vs CDN (low confidence) tiers — prevents false positives on Akamai-served pages
- URL safety now uses fail-closed public-host validation with an `nslookup` fallback on Windows systems where `socket.getaddrinfo()` intermittently fails for public hosts
- `curl_cffi` SSRF pinning now uses session-level `CurlOpt.RESOLVE` while keeping the original hostname URL, which preserves TLS/SNI and fixes false acquisition failures on CDN-backed sites
- Playwright no longer injects a `Host` header into browser contexts; this fixes `net::ERR_INVALID_ARGUMENT` on sites like Under Armour and Hatch
- Blocked-page detection no longer treats dormant DataDome modal markup alone as a hard block when the page clearly contains rich usable content
- FastAPI startup no longer marks queued `pending` crawl runs as failed; only actual in-flight orphan recovery should change run state
- Cookie persistence now runs through a shared policy in `data/knowledge_base/cookie_policy.json`; challenge/anti-bot cookies are filtered out on both load and save, and stale cookie jars are removed automatically when nothing policy-safe remains
- Acquisition now records observed HTTP attempt logs and applies bounded retry backoff plus per-host spacing from `pipeline_tuning.json`; diagnostics should reflect only real attempts and actual failures, never inferred failure reasons that did not occur
- Kasada challenge detection (KPSDK script + short page)
- Playwright `_goto_with_fallback` catches all exceptions, not just TimeoutError
- Listing extractor ranks structured sources by field richness instead of short-circuiting on first source with >=2 records
- `_extract_items_from_json` recurses up to depth 4 for deeply nested product arrays (e.g. Myntra `searchData.results.products`)
- Hydrated state patterns expanded: `__myx`, `__STORE__`, `__APP_STATE__`
- Field aliases expanded: `landingPageUrl`, `searchImage`, `discountedPrice`, `mrp`

## Tests

Backend tests currently pass with:

```powershell
$env:PYTHONPATH='.'
pytest tests -q
```

184 tests covering: adapters, acquisition, blocked detection, JSON extraction, listing extraction, crawl service orchestration, review service, normalizers, security, host memory, requested field policy, URL safety, dashboard service, discovery.

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

## Architecture Invariants

These MUST be preserved across all changes:

1. **No magic values in code.** All tunable thresholds, field lists, selectors, and patterns MUST live in `data/knowledge_base/*.json` and be loaded via `pipeline_config.py`. Never hardcode these in service code.
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

## Known Gaps / Risks

- LLM integration is configuration-only today. The pipeline still behaves deterministically.
- XPath and regex rules are currently first-pass extraction helpers; there is no full selector authoring validation UI yet.
- Frontend run detail page does not yet surface `extraction_verdict` or `degraded` status.
- `try_blocked_adapter_recovery()` currently only supports Shopify — other platform recovery paths not yet implemented.
- Intelligence tab currently presents raw discovered data as a single blob — needs deterministic noise cleanup + structured field-level review (see `docs/PENDING_IMPROVEMENTS.md`).
- `build_absolute_xpath` generates brittle absolute paths that pollute selector memory.

## Preferred Next Steps

1. Implement deterministic intelligence/review flow: clean up noise from all sources (DOM, JSON, JSON-LD, network), organize into field-level candidates, optional LLM final-pass for presentation, user decides which fields to keep — promoted as canonical for future runs.
2. Surface extraction verdict and degraded/failed states in frontend run detail page.
3. Add Lever ATS adapter.
4. Expand `try_blocked_adapter_recovery()` to additional platforms.
5. Switch `build_absolute_xpath` to semantic relative XPaths.
