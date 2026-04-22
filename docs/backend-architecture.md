# Backend Architecture

> Last updated: 2026-04-22
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
- `requested_fields`
- `additional_fields`

Current live behavior:

- batch and crawl run creation preserve raw user-entered `requested_fields` / `additional_fields` on the run, while runtime-only canonicalization happens later when extraction and confidence scoring need alias matching
- batch run settings persist the resolved `urls` list inside `CrawlRunSettings`, so `_batch_runtime.py` fans out the same URL set that the create request submitted

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

Current live behavior:

- local startup recovery only reclaims stale active runs: fresh `pending` rows without a local task id are left alone, while stale `running` rows are forced into `failed` and stale local-dispatch `pending` rows are forced into `killed` so interrupted work does not stay orphaned forever
- batch execution now refreshes `last_heartbeat_at` as runs advance so startup recovery can distinguish live external workers from truly stale local work

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
- adapter-owned acquisition URL normalization now runs before runtime policy selection, so platform-specific URL cleanup stays in adapters instead of generic acquisition code
- browser diagnostics now classify `browser_reason` and `browser_outcome`, record phase timings and HTML bytes, and preserve failed browser-attempt evidence even when the final acquisition method stays HTTP
- browser rendering now probes extractability at `domcontentloaded`, skips optimistic/network-idle/readiness waits when content is already usable, and limits detail expansion with bounded DOM-first then accessibility-assisted fallback
- blocked-page detection is evidence-based: anti-bot vendor markers alone do not block a page, but challenge-specific signals such as CAPTCHA-delivery elements and corroborating blocker text do
- browser outcomes now distinguish challenge pages, low-content terminal shells, and explicit navigation/page-closed failures instead of collapsing them into generic browser HTML
- listing traversal now captures bounded per-step listing snapshots for extraction instead of concatenating full rendered DOMs across page turns, and diagnostics expose traversal fragment count plus traversal HTML bytes
- traversal-enabled browser fetches now retain both traversal-composed HTML and the full rendered HTML so the pipeline can retry extraction once when traversal fragments produce zero records
- browser block classification now preserves usable listing/detail content when vendor markers and challenge widgets coexist with clear extractable signals, instead of forcing a blocked verdict from anti-bot evidence alone
- traversal stop reasons remain diagnostic when the first rendered listing page is already usable: no-progress traversal keeps the full rendered HTML as the primary payload and only downgrades to `traversal_failed` when listing evidence is still below threshold
- detail-page expansion is field-aware and commerce-safe: requested fields now contribute expansion tokens, blocked action labels such as add-to-cart/login are skipped, and ARIA-driven affordances (`aria-expanded`, `aria-controls`, tabs, summaries) are considered even when the initial detail readiness probe already looks usable
- detail-page expansion now short-circuits when the current rendered DOM already exposes the requested section headings, avoiding unrelated follow-up clicks that would otherwise mutate an already-extractable detail page
- thin browser listing results can trigger one bounded recovery re-acquisition that performs ordered listing actions (`clear filters`, `view all`, `next page`) before traversal/extraction, and the pipeline only keeps the retry when it improves record count
- browser acquisition now generates internal `page_markdown` context from rendered HTML plus visible links and the accessibility snapshot; detail-page serialization prunes review/Q&A/payment containers and drops low-signal chrome lines before persistence so semantic expansion stays anchored to product content instead of whole-page UI noise
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
- network payload detail inference now keeps its signature/list-container config in `config/network_payload_specs.py`, recognizes normalized camel/Pascal-case commerce keys (`ProductName`, `DetailUrl`, `FieldValues`), and rejects product/detail payloads whose explicit URL anchor does not match the current detail page
- generic ghost-route payload fallback now rejects multi-record listing envelopes for detail surfaces, so paginated product-list APIs cannot masquerade as a single detail payload just because one row happens to expose product-like keys
- tracking-parameter stripping is live in field-value normalization via `w3lib`
- platform registry config in `config/platforms.json` now owns adapter registration metadata, network signatures, JS-state mappings, and listing-readiness selectors/waits
- extraction runtime now short-circuits raw XML sitemap/listing payloads into deterministic URL records before HTML DOM parsing, which keeps sitemap targets out of the expensive BeautifulSoup listing path
- ecommerce detail title selection now ranks structured sources ahead of raw DOM headings, rejects noisy DOM `<h1>/<title>` values such as promo or generic-results text, and only promotes fallback titles when the replacement source is materially stronger
- ecommerce detail extraction now drops low-signal site-shell records when the surviving title still resolves to site-brand chrome and no real product anchors survive, preventing stale SPA/detail misses from being persisted as false product successes
- detail extraction now has a DOM variant fallback for `ecommerce_detail` pages when structured data and JS state leave variant axes empty
- JS-state ecommerce-detail mapping now scores candidate product payloads so richer nested PDP nodes beat shallow landing/navigation shells, and generic direct-axis variant keys such as `condition`, `grade`, `storage`, and `memory` are normalized without adapter-specific branches
- DOM listing extraction no longer accepts the first non-empty candidate set; it now ranks structured, DOM, and browser-captured rendered-card candidates by record quality and keeps visual elements as a last-resort fallback only
- listing title filtering now rejects numeric-only titles before persistence, and detail DOM image fallback keeps linked gallery media instead of dropping anchored product thumbnails
- DOM image extraction now scores likely product-gallery media higher and filters obvious tracking, logo, and spacer assets before building `additional_images`
- ecommerce-detail DOM completion now treats missing `additional_images` as a high-value gap, so structured-data early exit does not suppress DOM gallery recovery when only a primary image was found upstream
- DOM section extraction now follows accordion/tab structures through `aria-controls`, native `details/summary`, and common wrapped content containers before falling back to plain heading-sibling scans
- raw requested field labels are preserved through crawl creation, and ecommerce-detail DOM section matching now checks those exact requested labels before collapsing to broader canonical aliases; composite headings such as `Features & Benefits` therefore extract into `features_benefits` instead of being silently reduced to a generic alias like `benefits`
- surface alias lookup now keeps normalized requested labels addressable as identity mappings as well as exact requested-field keys, so custom dynamic fields continue to flow through candidate collection even when they do not collapse to a built-in alias
- requested custom ecommerce-detail fields now keep DOM completion active when matching section headings are present, so structured-data early exit does not hide fields such as `product_story` after detail expansion
- DOM variant fallback now materializes concrete variant rows, keeps `variant_count` aligned with those rows, and avoids widening an already authoritative `selected_variant` choice with later DOM-only axis noise
- long-text candidate intake now rejects low-signal placeholders such as single-word review/schema values or accordion index labels before they can win `description` / `specifications`, and selector-backed long-text fields must expose non-interactive prose rather than button/tab indexes
- ecommerce-detail JS-state product detection now requires real commerce cues instead of accepting arbitrary titled image blocks, and JS-state image harvesting filters payment, logo, bookmark, swatch, and video assets before they can outrank structured product media
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

- [../AGENTS.md](../AGENTS.md)
- [ENGINEERING_STRATEGY.md](ENGINEERING_STRATEGY.md)
- [INVARIANTS.md](INVARIANTS.md)
- [frontend-architecture.md](frontend-architecture.md)
