# Backend Architecture

> Last updated: 2026-04-21
>
> Canonical detailed backend reference. This is the merged replacement for the older split architecture docs.

## 1. Scope

CrawlerAI backend is a crawl execution, extraction, review, and export system with:

- authenticated FastAPI APIs
- Postgres persistence
- Redis-backed runtime state
- Celery execution
- pooled HTTP and browser acquisition
- structured-source and DOM extraction
- selectors, review, and domain-memory feedback loops
- admin-managed LLM configuration and optional task/runtime assistance

## 2. Runtime Stack

- API: FastAPI in `backend/app/main.py`
- Worker: Celery in `backend/app/tasks.py`
- DB: SQLAlchemy async + Alembic
- Cache/runtime state: Redis
- HTTP: `httpx` plus `curl_cffi`
- Browser: Playwright
- Parsing: BeautifulSoup, `glom`, `jmespath`, `lxml`, `extruct`, `browserforge`, `w3lib`

## 3. Registered API Surface

Routers registered in `backend/app/main.py`:

- `/api/auth`
- `/api/users`
- `/api/dashboard`
- `/api/crawls`
- `/api/crawls/{run_id}/records`
- `/api/records/{record_id}/provenance`
- `/api/jobs`
- `/api/review`
- `/api/selectors`
- `/api/llm`
- `/api/health`
- `/api/metrics`

Important route groups:

- `api/crawls.py`: create runs, CSV ingestion, logs, websocket updates, pause/resume/kill, commit fields, commit LLM suggestions
- `api/records.py`: records list plus JSON/CSV/markdown/artifacts/discoverist exports and provenance
- `api/review.py`: review payload, artifact HTML, save review mapping
- `api/selectors.py`: selector CRUD, cross-surface listing by domain, suggestion, test, preview HTML
- `api/llm.py`: provider catalog, config CRUD, connection test, cost log

## 4. Crawl Request and Settings Contract

`CrawlCreate` currently accepts:

- `run_type`: `crawl | batch | csv`
- `url` and/or `urls`
- `surface`: `ecommerce_listing | ecommerce_detail | job_listing | job_detail | automobile_listing | automobile_detail | tabular`
- `settings`
- `additional_fields`

`CrawlRunSettings` normalizes settings for storage/runtime. Important fields include:

- `proxy_list`
- `advanced_enabled`
- resolved traversal mode
- `max_pages`
- `max_scrolls`
- `max_records`
- `sleep_ms`
- `respect_robots_txt`
- `url_batch_concurrency`
- `url_timeout_seconds`
- `llm_enabled`
- `extraction_contract`
- `llm_config_snapshot`
- `extraction_runtime_snapshot`

## 5. High-Level Flow

```text
POST /api/crawls
  -> crawl_ingestion_service
  -> crawl_crud.create_crawl_run
  -> crawl_service.dispatch_run
  -> Celery task process_run
  -> _batch_runtime.process_run
  -> pipeline/core._process_single_url for each URL
  -> acquire page + diagnostics + artifacts
  -> extract records
  -> optional selector self-heal / optional LLM missing-field extraction
  -> publish verdict + metrics + source trace
  -> persist CrawlRecord rows and run summary
```

## 6. Subsystem Ownership

### 6.1 API and bootstrap

Primary files:

- `app/main.py`
- `app/api/*`
- `app/core/config.py`
- `app/core/database.py`
- `app/core/redis.py`
- `app/core/security.py`
- `app/core/telemetry.py`
- `app/core/metrics.py`

Responsibilities:

- app startup/shutdown
- migrations on startup
- route registration
- auth/dependencies
- correlation IDs
- health and metrics

### 6.2 Crawl ingestion and orchestration

Primary files:

- `crawl_ingestion_service.py`
- `crawl_service.py`
- `crawl_crud.py`
- `crawl_events.py`
- `_batch_runtime.py`
- `pipeline/core.py`
- `pipeline/types.py`
- `pipeline/runtime_helpers.py`

Responsibilities:

- create runs from payloads and CSV uploads
- stamp run snapshots
- dispatch and recover runs
- process URLs
- persist records and summary state
- emit logs and progress

### 6.3 Acquisition and browser runtime

Primary files:

- `acquisition/acquirer.py`
- `acquisition/runtime.py`
- `acquisition/browser_capture.py`
- `acquisition/browser_runtime.py`
- `acquisition/http_client.py` (thin adapter over `runtime.get_shared_http_client`)
- `acquisition/browser_identity.py`
- `acquisition/cookie_store.py`
- `acquisition/pacing.py`
- `acquisition/traversal.py`
- `crawl_fetch_runtime.py`
- `robots_policy.py`
- `url_safety.py`

Responsibilities:

- safe target validation
- pooled HTTP/browser fetch
- JS-shell and blocked-page escalation
- browser identity generation
- network payload capture
- temporary screenshot staging for browser artifacts
- detail-page expansion
- listing traversal
- cookie policy enforcement
- robots handling when enabled

Current live behavior:

- fetch results carry headers, blocked state, browser diagnostics, transient browser artifacts, and network payload metadata
- browser runtime is pooled and exposes runtime snapshots
- `browserforge`-backed context identity is active
- traversal is explicit and separate from browser escalation
- JSON-expected acquisition now stays in `acquisition/http_client.py`; adapters consume decoded payloads instead of compensating for transport quirks
- browser network interception is bounded through a small response-queue worker pool with per-endpoint payload budgets instead of untracked background tasks
- browser diagnostics now classify `browser_reason` and `browser_outcome`, record phase timings and HTML bytes, and preserve failed browser-attempt evidence even when the final acquisition method stays HTTP
- browser rendering now probes extractability at `domcontentloaded`, skips optimistic/network-idle/readiness waits when content is already usable, and limits detail expansion with bounded DOM-first then accessibility-assisted fallback
- blocked-page detection is evidence-based: anti-bot vendor markers alone do not block a page, but challenge-specific signals such as CAPTCHA-delivery elements and corroborating blocker text do
- browser outcomes now distinguish challenge pages, low-content terminal shells, and explicit navigation/page-closed failures instead of collapsing them into generic browser HTML
- listing traversal now captures bounded per-step listing snapshots for extraction instead of concatenating full rendered DOMs across page turns, and diagnostics expose traversal fragment count plus traversal HTML bytes
- traversal-enabled browser fetches now retain both traversal-composed HTML and the full rendered HTML so the pipeline can retry extraction once when traversal fragments produce zero records
- detail-page expansion is field-aware and commerce-safe: requested fields now contribute expansion tokens, blocked action labels such as add-to-cart/login are skipped, and ARIA-driven affordances (`aria-expanded`, `aria-controls`, tabs, summaries) are considered even when the initial detail readiness probe already looks usable
- thin browser listing results can trigger one bounded recovery re-acquisition that performs ordered listing actions (`clear filters`, `view all`, `next page`) before traversal/extraction, and the pipeline only keeps the retry when it improves record count
- browser acquisition now generates internal `page_markdown` context from rendered HTML plus visible links and the accessibility snapshot; the existing markdown export/view path consumes that persisted raw-data context rather than introducing a second markdown surface
- browser screenshots are staged to temp files inside the artifacts area and then persisted by the pipeline, avoiding large in-memory PNG handoffs on the hot path
- a single shared HTTP client pool in `acquisition/runtime.py` is keyed on `(proxy, address-family preference, force_ipv4)`; `acquisition/http_client.py` no longer maintains a second pool and simply delegates to `get_shared_http_client`
- curl_cffi impersonation target is now an actionable setting (`crawler_runtime_settings.curl_impersonate_target`, default `chrome131`) rather than dead config, and httpx clients ship with a matching default Chrome `User-Agent`/`Accept` header set so direct HTTP requests present a coherent identity
- browser contexts apply `playwright-stealth` when installed and accept a per-fetch `proxy` for rotated-proxy traversal; `temporary_browser_page` is a thin wrapper over `SharedBrowserRuntime.page(proxy=...)`
- `browser_identity` is host-OS-locked via `browserforge`, with a small regeneration loop to reject fingerprints whose UA tokens disagree with the OS
- blocked-page escalation is now two-pronged: vendor-specific response headers (DataDome, Cloudflare, Akamai, PerimeterX, Sucuri, ...) classified via `classify_block_from_headers` short-circuit into the browser and mark the host vendor-blocked so sibling fetchers skip further HTTP attempts; HTML heuristics continue to catch vendor-silent blocks
- `is_non_retryable_http_status` keeps `401` out of browser escalation (auth walls) while still escalating `403`/`429` challenges, and `classify_blocked_page` emits typed `BlockPageClassification` outcomes (`auth_wall`, `rate_limited`, `challenge_page`, ...) distinct from network failures
- platform/runtime policy no longer hardcodes vendor-owned domains just to force browser usage; escalation is driven by runtime policy, response/header evidence, and structured blocker signatures
- host pacing is now enforced before both HTTP and browser attempts in `crawl_fetch_runtime.py`, and protection evidence can temporarily widen the per-host interval instead of hammering the same blocked edge
- after browser navigation, blocked challenge pages now get one bounded recovery window: the runtime polls for clearance, checks Akamai-style `_abck` issuance when relevant, and only then performs a single paced reload before surfacing the failure
- the legacy `async def fetch_page` trampoline in `acquisition/runtime.py` has been removed; callers import `fetch_page` from `crawl_fetch_runtime` directly

### 6.4 Extraction

Primary files:

- `crawl_engine.py`
- `detail_extractor.py`
- `listing_extractor.py`
- `structured_sources.py`
- `js_state_mapper.py`
- `network_payload_mapper.py`
- `field_value_*`
- `extract/*`
- `adapters/*`

Responsibilities:

- choose listing vs detail path
- run platform adapters
- parse JSON-LD, embedded JSON, JS state, microdata, Open Graph, and network payloads
- extract field values from structured sources and DOM
- normalize field values before publish

Important implemented features:

- `structured_sources.py` now integrates extruct-backed microdata and Open Graph extraction, with fallback parsing when dependencies are unavailable
- Nuxt `__NUXT_DATA__` payload revival is live in structured-source harvesting
- `network_payload_mapper.py` now uses declarative specs from `config/network_payload_specs.py`, and browser-side endpoint classification derives its path tokens from that same spec source instead of maintaining a parallel capture-only token table
- tracking-parameter stripping is live in field-value normalization via `w3lib`
- platform registry config in `config/platforms.json` now owns adapter registration metadata, network signatures, JS-state mappings, and listing-readiness selectors/waits
- detail extraction now has a DOM variant fallback for `ecommerce_detail` pages when structured data and JS state leave variant axes empty
- DOM listing extraction no longer accepts the first non-empty candidate set; it now ranks structured, DOM, and browser-captured rendered-card candidates by record quality and keeps visual elements as a last-resort fallback only
- DOM image extraction now scores likely product-gallery media higher and filters obvious tracking, logo, and spacer assets before building `additional_images`
- DOM section extraction now follows accordion/tab structures through `aria-controls`, native `details/summary`, and common wrapped content containers before falling back to plain heading-sibling scans
- DOM variant fallback now materializes concrete variant rows, keeps `variant_count` aligned with those rows, and avoids widening an already authoritative `selected_variant` choice with later DOM-only axis noise
- output schema validation now applies to listing surfaces as well as detail surfaces before persistence, so type mismatches on listing records are nullified instead of silently bypassing validation
- pipeline post-processing now has two bounded optional recovery layers: selector self-heal for detail pages, and a snapshot-backed `direct_record_extraction` LLM task that only replaces weak deterministic record sets when the LLM result scores better

### 6.5 Publish and persistence

Primary files:

- `publish/verdict.py`
- `publish/metrics.py`
- `publish/metadata.py`
- `artifact_store.py`
- `pipeline/core.py`
- `pipeline/persistence.py`

Responsibilities:

- compute per-URL verdicts
- compute acquisition and URL metrics
- build/persist field-discovery metadata
- persist HTML artifacts plus browser diagnostics/screenshot sidecars when a browser attempt occurred
- keep artifact I/O and `CrawlRecord` persistence out of the orchestration hot path in `pipeline/core.py`
- write `CrawlRecord` rows and update run summaries

Current verdict rules:

- records + not blocked -> `success`
- records + blocked -> `partial`
- blocked + no records -> `blocked`
- listing + no records -> `listing_detection_failed`
- detail + no records -> `empty`

### 6.6 Review, selectors, and domain memory

Primary files:

- `review/__init__.py`
- `selectors_runtime.py`
- `selector_self_heal.py`
- `domain_memory_service.py`

Responsibilities:

- build review payloads
- save approved field mappings
- expose review artifact HTML
- store and manage selectors in domain memory
- suggest/test selectors
- synthesize and validate selectors during self-heal flows

Current storage/runtime model:

- selector/domain memory is stored by normalized `(domain, surface)`
- selectors are persisted inside `DomainMemory`
- runtime can layer surface-specific and generic rules
- `GET /api/selectors` can now list all selector records for a domain across surfaces when `surface` is omitted, which is what the frontend uses for domain-memory management and crawl-config prefill
- selector self-heal reuses stamped extraction runtime snapshot data
- selector self-heal persists only validated improvements and reuses domain memory on later runs before attempting another synthesis pass
- once reused domain-memory rules satisfy the requested fields for a record, the pipeline does not launch a second generic selector-synthesis round just because confidence remains low

### 6.7 LLM admin and runtime

Primary files:

- `llm_runtime.py`
- `llm_provider_client.py`
- `llm_config_service.py`
- `llm_cache.py`
- `llm_circuit_breaker.py`
- `llm_tasks.py`
- `llm_types.py`
- `api/llm.py`

Responsibilities:

- manage provider configs
- test provider connectivity
- run task-specific prompts
- cache responses and isolate failures
- expose provider catalog and cost log

Current crawl/runtime usage:

- optional missing-field extraction in the pipeline
- selector suggestion and review cleanup support
- config snapshots prevent mid-run drift

## 7. Persistence Model

Primary models:

- `User`
- `CrawlRun`
- `CrawlRecord`
- `CrawlLog`
- `ReviewPromotion`
- `LLMConfig`
- `LLMCostLog`
- `DomainMemory`

Notable current schema direction:

- durable queue lease support
- max-records trigger support
- URL identity keys on records
- domain-memory storage

## 8. Record, Review, and Provenance Contracts

`CrawlRecordResponse` intentionally cleans user-facing output:

- `data`: populated logical fields only
- `raw_data`: full stored extraction payload
- `discovered_data`: trimmed review/provenance metadata
- `source_trace`: acquisition and extraction provenance
- `review_bucket`: unverified attributes exposed for review
- `provenance_available`: indicates manifest/provenance detail exists

`CrawlRecordProvenanceResponse` exposes the fuller provenance/debug view:

- `raw_data`
- `discovered_data`
- `source_trace`
- `manifest_trace`
- `raw_html_path`

The normal records API hides:

- empty/null values
- `_`-prefixed internal fields
- obsolete raw manifest containers in standard display responses

## 9. Recent Feature Status From Plans/Audits

Implemented from recent extraction/audit work:

- extruct-backed microdata + Open Graph support
- generic network payload specs
- browserforge identity restoration
- URL tracking-param stripping
- Nuxt data revival
- selector self-heal + domain memory
- provenance/review bucket response cleanup

Still worth treating as active engineering concerns:

- generic-path hardcodes that should live in adapters/config
- large utility/service modules that still own too many concerns
- frontend/backend client-surface drift where unused client methods outlive removed routes
- selector tool and Crawl Studio now share selector memory semantics, so future selector changes need tests in both surfaces instead of assuming one page is authoritative

## 10. Operational References

Useful local commands:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Companion docs:

- [../CLAUDE.md](../CLAUDE.md)
- [ENGINEERING_STRATEGY.md](ENGINEERING_STRATEGY.md)
- [INVARIANTS.md](INVARIANTS.md)
- [frontend-architecture.md](frontend-architecture.md)
