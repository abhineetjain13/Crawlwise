# Backend Architecture

> Last updated: 2026-04-19
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
- `api/selectors.py`: selector CRUD, suggestion, test, preview HTML
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
- `acquisition/http_client.py`
- `acquisition/browser_client.py`
- `acquisition/browser_pool.py`
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
- detail-page expansion
- listing traversal
- cookie policy enforcement
- robots handling when enabled

Current live behavior:

- fetch results carry headers, blocked state, browser diagnostics, and network payload metadata
- browser runtime is pooled and exposes runtime snapshots
- `browserforge`-backed context identity is active
- traversal is explicit and separate from browser escalation

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
- `network_payload_mapper.py` now uses declarative specs from `config/network_payload_specs.py`
- tracking-parameter stripping is live in field-value normalization via `w3lib`

### 6.5 Publish and persistence

Primary files:

- `publish/verdict.py`
- `publish/metrics.py`
- `publish/metadata.py`
- `artifact_store.py`
- persistence flow in `pipeline/core.py`

Responsibilities:

- compute per-URL verdicts
- compute acquisition and URL metrics
- build/persist field-discovery metadata
- persist HTML artifacts
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
- selector self-heal reuses stamped extraction runtime snapshot data

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
