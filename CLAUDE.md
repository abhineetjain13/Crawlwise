# CLAUDE.md

## Project

CrawlerAI is a POC crawler stack with:

- `backend/`: FastAPI + SQLAlchemy async backend, crawl worker loop, adapters, deterministic extraction pipeline, review/promotion flow.
- `frontend/`: Next.js app for crawl submission, run inspection, review, selectors, admin views.
- `docs/`: product notes and implementation planning docs.

## Documentation Map

- `docs/backend-architecture.md`: current backend architecture and invariants only.
- `docs/backend-pending-items.md`: the single consolidated backend backlog for bugs, refactors, and follow-up architecture work.
- Root audit files are historical inputs, not the canonical backlog.

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

`advanced_mode` is listing traversal only. It governs `paginate`, `scroll`, `load_more`, and legacy `auto` traversal behavior on listing pages. It does not control automatic browser rendering.

Automatic browser escalation is system-owned and independent of `advanced_mode`. The acquisition layer may still escalate from `curl_cffi` to Playwright for both listing and detail pages when curl output is blocked, redirected, empty, or structurally unusable.

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
- Detail pages never run traversal helpers (`paginate` / `scroll` / `load_more`) even if `advanced_mode` is present; traversal is listing-only policy.

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
  - `_extract_items_from_json` reads `max_json_recursion_depth` from `pipeline_tuning.json` (default `8`) to find deeply nested product arrays
  - Card title extraction uses ordered selectors (`[itemprop='name']` → `.title` → headings) and skips price-like text to prevent price/title confusion
  - Card auto-detect scores candidate groups by product signal density (link + image + price) instead of pure element count, preventing nav lists from winning over product tiles
  - Price text is cleaned via regex to strip surrounding UI text (e.g. "In stock Add to basket")
  - `card_selectors.json` includes 22 ecommerce and 12 job selectors, including microdata `[itemscope][itemtype*='Product']` and class-substring patterns
- `json_extractor.py`: First-class JSON API extraction — finds data arrays in nested JSON using 37 collection keys (including `products`, `jobs`, `drinks`, `books`, `categories`, etc.) plus GraphQL edges/node patterns. Falls back to preserving scalar fields under original keys when no canonical alias matches.
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

Run status currently reflects verdict as: `completed` (`success`) and `failed` (all other verdicts, including `partial`, `listing_detection_failed`, `schema_miss`, `blocked`, `empty`, and `error`). Legacy `degraded` status is normalized to `failed`; the backend does not currently emit a separate `degraded` run status.

#### Listing fallback guard

Listing pages that produce 0 real item-level records are never downgraded into a single detail-style fallback record. They get `listing_detection_failed` verdict and a failed run status.

#### Selector memory

Placeholder selectors like `[data-field='x']` are no longer saved. Selectors are only stored when sourced from an adapter, user contract, or validated DOM match.

### Pipeline configuration (`services/pipeline_config.py`)

All tunable values (field aliases, collection keys, DOM patterns, card selectors, normalization rules, verdict rules, block signatures, consent selectors, etc.) are loaded from JSON files in `data/knowledge_base/` at startup. Code MUST import from `pipeline_config` — never hardcode these values.

### Record field policy

- `record.data`: Only populated logical fields shown to users. Empty/null fields and `_`-prefixed internal fields are stripped in the API response.
- `record.discovered_data`: Raw manifest containers (adapter_data, json_ld, network_payloads, etc.) are stripped from API responses. Only logical metadata (content_type, source, requested_field_coverage) is exposed.
- `record.raw_data`: Full raw extraction data, available for review/promote resolution but not shown in default views.
- `record.source_trace.field_discovery`: Deterministic field-level discovery summary for requested/additional fields. This is the primary backend contract for intelligence/review display: chosen value, contributing sources, candidate counts, and missing fields.
- `record.source_trace.acquisition`: Lightweight acquisition summary for UI/review use: final URL, browser attempt/use flags, challenge state, invalid-surface marker, and timing diagnostics.
- Requested field coverage is tracked in `discovered_data.requested_field_coverage` — it does NOT affect the extraction verdict.
- Review/LLM-oriented workflows should consume cleaned logical candidates plus preserved raw source evidence; do not throw away source-specific data during acquisition/discovery just because it is hidden from the default API view.

### Review service

- `discovered_fields` filters out structural container keys (`adapter_data`, `network_payloads`, `json_ld`, etc.) and empty-valued fields
- Only business-level fields with actual values from `record.data` and `record.raw_data` appear as review candidates
- Reviewed values can be persisted through `POST /api/crawls/{run_id}/commit-fields`; the old LLM commit path now delegates to the same backend write flow

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
- `_extract_items_from_json` now uses `pipeline_tuning.json:max_json_recursion_depth` (default `4`) for deeply nested product arrays (e.g. Myntra `searchData.results.products`)
- Hydrated state patterns expanded: `__myx`, `__STORE__`, `__APP_STATE__`
- Field aliases expanded: `landingPageUrl`, `searchImage`, `discountedPrice`, `mrp`
- Discovery now preserves more usable source evidence for detail pages: embedded JSON blobs, hydrated state assignments, semantic sections, and structured table/spec rows all feed field-level candidate generation
- Detail runs now persist deterministic `field_discovery` summaries for requested fields so intelligence/review UIs can show discovered values and source provenance instead of raw manifest blobs alone
- Manual reviewed-field commits now use a generic `commit-fields` API route rather than LLM-only naming
- API auth now accepts either the session cookie or `Authorization: Bearer <token>` for the same protected endpoints
- Listing card title extraction now uses ordered selectors (`[itemprop='name']` → `.title` → headings) and skips price-like headings — fixes webscraper.io where price `<h4>` preceded title `<h4>`
- Card auto-detect now scores candidate groups by product signal density (link + image + price presence) instead of pure element count — fixes nav lists being preferred over product tiles on ThriftBooks, iFixit, Under Armour
- Card selectors expanded with new generic patterns including: `[itemscope][itemtype*='Product']`, `[class*='ProductCard']`, `[class*='SearchResultTile']`, `[class*='product-tile']`, etc.
- Price text in card extraction now cleaned via regex to strip surrounding UI text ("£51.77 In stock Add to basket" → "£51.77")
- `collection_keys.json` expanded from 15 to 37 keys (added `drinks`, `books`, `categories`, `collections`, `articles`, `content`, etc.)
- JSON extractor now falls back to preserving scalar fields under original keys when no canonical alias matches — prevents empty records from APIs with non-standard naming (e.g. CocktailDB `strDrink`)
- Card extraction now prefers `[itemprop='image']` for image_url before falling back to generic `<img>` selectors
- JS-shell page detection: acquisition now triggers Playwright fallback when HTML is large (>=200KB) but visible text ratio is below 2% — catches Next.js/SPA shell pages like Sigma Aldrich where `curl_cffi` returns full HTML skeleton but no rendered product data
- Listing extractor now detects and filters category/navigation URLs (paths like `/products/cell-culture`) from product URLs (paths like `/product/sigma/nuc101`) — prevents category hub links from being extracted as product records
- Listing record quality guards now reject weak promo/category hub rows that only contain navigation metadata such as title + URL + publication date, and shared URL normalization drops asset links such as `.woff2`
- iFixit-style listing grids that render products as `article` children under `data-testid` containers are now covered by generic card selectors
- Acquisition timing summaries now roll up curl fetch, browser decision, browser launch/origin/navigation/challenge/readiness/traversal, acquisition total, and extraction total into run-level `acquisition_summary`
- LLM runtime calls are fire-and-forget with no retry — 429 rate limit errors fail immediately (retry/backoff removed to avoid blocking the pipeline on free-tier API limits)
- Dynamic field name validation rejects single-character keys, keys longer than 60 chars, sentence-like keys with 5+ underscores, and JSON-LD schema type names (AggregateRating, BreadcrumbList, etc.) from leaking into `record.data`
- Specification aggregate fields (`specifications`, `dimensions`) now require at least 2 real spec entries from the semantic extractor before being emitted — prevents phantom "specifications" on pages without actual spec tables
- `spec_drop_labels` expanded with JSON-LD type names, day-of-week patterns, and structural artifacts
- Extraction smoke runner (`run_extraction_smoke.py`) tests the full acquire→discover→extract pipeline without a database, validated against 5 client URLs (Adorama, Dice, SSENSE, Arc'teryx)
- Network payload noise filtering: geo/tracking/widget API responses (geolocation, analytics, Klarna, Affirm, livechat, etc.) are now filtered by URL pattern before entering the candidate pipeline — prevents ISP names, tracking IDs, and payment widget data from polluting title/category/brand candidates
- JSON-LD `@type` values no longer leak as category candidates: `_deep_get_all_aliases` now skips JSON-LD structural keys (`@type`, `@context`, `@id`, `@graph`), and a CamelCase schema type pattern filter catches remaining type names (e.g. IndividualProduct, PeopleAudience)
- `generic_category_values` expanded with 30+ additional schema.org type names (IndividualProduct, PeopleAudience, PostalAddress, QuantitativeValue, etc.)
- Dynamic field underscore threshold relaxed from >=3 to >=5 to preserve legitimate multi-word fields (job qualifications, accordion section headings)
- LLM retry/backoff removed — 429 errors now fail fast instead of blocking the pipeline with 5-10s sleeps per retry
- Text pattern extraction fallback: when a requested additional field has no candidates from structured sources, the pipeline now searches description text and HTML for "Label: Value" patterns matching the field name (e.g. "Supplier color: Black/Jet" inside SSENSE description)
- `_deep_get_all_aliases` now skips non-product container keys (`review`, `reviews`, `author`, `publisher`, `breadcrumb`, etc.) during traversal — prevents review titles from leaking as product title candidates
- JSON-LD blocks with non-product `@type` (Organization, WebSite, WebPage, BreadcrumbList, etc.) are now skipped for product-identity fields (title, price, brand, etc.) — fixes site name "SparkFun Electronics" appearing as product title
- Candidate rows per field capped at 5 — prevents intelligence tab from showing 13+ variant SKUs or size values
- Zero-quality candidates filtered from dynamic/intelligence fields — placeholder values like "-" no longer appear
- Category quality score now rejects social media names (youtube, facebook, etc.), namespace-prefixed values (food:foodProduct), and URL path fragments
- Brand quality score penalizes URL path fragments (e.g. "facets/brands/coca-cola")
- Extraction smoke runner expanded to 9 sites covering: ecommerce PDPs (Adorama, SSENSE, Arc'teryx, Adafruit, SparkFun, OpenFoodFacts), job listings (Dice), ecommerce listings (AutoZone, Puma)
- Magic numbers migration: JSON-LD frozensets (`_JSONLD_STRUCTURAL_KEYS`, `_JSONLD_NON_PRODUCT_BLOCK_TYPES`, `_PRODUCT_IDENTITY_FIELDS`, `_NESTED_NON_PRODUCT_KEYS`, `_JSONLD_TYPE_NOISE`), dynamic field drop tokens, and source ranking dict all moved from hardcoded service.py to `extraction_rules.json` and loaded via `pipeline_config.py`
- `MAX_CANDIDATES_PER_FIELD`, `DYNAMIC_FIELD_NAME_MAX_TOKENS`, `ACCORDION_EXPAND_MAX`, `ACCORDION_EXPAND_WAIT_MS` now configurable via `pipeline_tuning.json` (were hardcoded in service.py and browser_client.py)
- Created `block_signatures.json` and `consent_selectors.json` — these were referenced by pipeline_config.py but didn't exist as files (fell through to inline fallback defaults)
- Accordion expansion in browser_client.py now uses configurable max and wait from pipeline_tuning.json, passed as JS parameter to `page.evaluate()`

## Tests

Run backend tests with:

```powershell
$env:PYTHONPATH='.'
pytest tests -q
```

The backend test tree currently collects 360 tests covering adapters, acquisition, blocked detection, JSON extraction, listing extraction, crawl service orchestration, review service, normalizers, security, host memory, requested field policy, URL safety, dashboard service, discovery, and worker recovery.

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

Full extraction pipeline smoke tests (acquire + discover + extract, no database):

```powershell
$env:PYTHONPATH='.'
python run_extraction_smoke.py
```

This tests 10 client URLs through the complete extraction pipeline and writes a timestamped report under `artifacts/extraction_smoke/`.

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
13. **JS-shell detection must trigger Playwright.** Large HTML (>=200KB) with very low visible text ratio (<2%) indicates a SPA/Next.js shell. The acquirer must escalate to Playwright in these cases even when `visible_text_length` passes the absolute minimum threshold.
14. **LLM calls must fail fast.** No retry/backoff on 429 errors — let the free API tier fail gracefully rather than blocking the pipeline with sleeps. Re-evaluate when using paid API keys.
15. **Dynamic field names must pass quality gates.** Single-char keys, JSON-LD type names, day-of-week patterns, and sentence-like labels (5+ underscores) are filtered from `record.data`. Zero-quality candidates are filtered from dynamic/intelligence fields. Candidate rows per field are capped at 5. New noise patterns should be added to `spec_drop_labels` in `extraction_rules.json`, not hardcoded.
16. **JSON-LD structural keys must not produce candidates.** `@type`, `@context`, `@id`, `@graph` are metadata, not data fields. `_deep_get_all_aliases` skips them before alias matching. Network payload noise (geo, tracking, widget APIs) must be filtered by URL pattern before entering the candidate pipeline.

## Backlog Reference

Open backend bugs, architecture gaps, and refactoring work are tracked in `docs/backend-pending-items.md`. Keep this file focused on the current implemented contract and invariants.
