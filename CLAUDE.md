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

#### Discovery layer (`services/discover/`)

- `service.py`: Produces `DiscoveryManifest` from HTML — discovers adapter data, network payloads, __NEXT_DATA__, JSON-LD, microdata, tables, hydrated state objects (__NUXT__, __APOLLO_STATE__, etc.)

#### Extraction layer (`services/extract/`)

- `listing_extractor.py`: Structured-data-first strategy for listings:
  1. JSON-LD item lists / Product arrays
  2. Embedded app state (__NEXT_DATA__)
  3. Hydrated state objects (__NUXT__, __APOLLO_STATE__, etc.)
  4. Network payloads (XHR/fetch intercepted JSON)
  5. DOM card detection (CSS selectors + auto-detect heuristic)
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

## Tests

Backend tests currently pass with:

```powershell
$env:PYTHONPATH='.'
pytest tests -q
```

122 tests covering: adapters, acquisition, blocked detection, JSON extraction, listing extraction, crawl service orchestration, review service, normalizers, security, host memory, requested field policy.

## Architecture Invariants

These MUST be preserved across all changes:

1. **No magic values in code.** All tunable thresholds, field lists, selectors, and patterns MUST live in `data/knowledge_base/*.json` and be loaded via `pipeline_config.py`. Never hardcode these in service code.
2. **Async-safe adapters.** All HTTP calls in async adapter methods MUST use `asyncio.to_thread()` for synchronous libraries (curl_cffi). Blocking the event loop causes visible user-facing latency.
3. **Verdict based on core fields only.** `_compute_verdict()` determines success/partial based on VERDICT_CORE_FIELDS presence. Requested field coverage is metadata, not a verdict input.
4. **Clean record API responses.** `CrawlRecordResponse.data` strips empty/null values and `_`-prefixed internal keys. `discovered_data` strips raw manifest containers. Users see only populated logical fields.
5. **Listing fallback guard.** Listing pages with 0 item records MUST get `listing_detection_failed` verdict. Never fall back to detail-style single-record extraction for listings.
6. **Review shows only actionable fields.** `discovered_fields` in review payloads excludes container keys and empty-valued fields.
7. **Pipeline config is the single source of truth** for: field aliases, collection keys, DOM patterns, card selectors, block signatures, consent selectors, verdict core fields, normalization rules.

## Known Gaps / Risks

- LLM integration is configuration-only today. The pipeline still behaves deterministically.
- XPath and regex rules are currently first-pass extraction helpers; there is no full selector authoring validation UI yet.
- Frontend run detail page does not yet surface `extraction_verdict` or `degraded` status.
- `try_blocked_adapter_recovery()` currently only supports Shopify — other platform recovery paths not yet implemented.

## Preferred Next Steps

1. Redesign frontend with Stripe/Linear enterprise style (Tailwind v4, CSS animations, light/dark).
2. Surface extraction verdict and degraded/failed states in frontend run detail page.
3. Run regression corpus (TEST_SITES.md) through the updated pipeline.
4. Add Lever ATS adapter.
5. Expand `try_blocked_adapter_recovery()` to additional platforms.
