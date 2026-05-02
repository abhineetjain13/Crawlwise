# Backend Directory Structure, Key Modules & Dependencies

## Top-Level Layout

```
backend/
├── alembic/                  # Alembic migrations (22 revision files)
├── app/                      # Main FastAPI application
├── tests/                    # Pytest suite (api/, fixtures/, services/)
├── pyproject.toml            # Dependencies + project metadata
├── tasks.py                  # Celery task bridge
├── run_*.py                  # Smoke / acceptance test runners
└── harness_support.py        # Test harness utilities
```

## `app/` — Application Core

### `app/main.py` — FastAPI Factory
- Creates `FastAPI` app with `lifespan` context manager
- Registers **11 API routers** from `app/api/`
- Sets up CORS, correlation-id middleware, `/api/health`, `/api/metrics`
- Lifespan startup: installs asyncio filter, validates cookie policy, bootstraps admin user, recovers stale runs
- Lifespan shutdown: closes browser runtime, HTTP clients, Redis, DB engine

### `app/tasks.py` — Celery Bridge
- Wraps `_batch_runtime.process_run_async` in a per-task `asyncio` event loop
- Handles `SIGTERM`/`SIGINT` graceful cancellation
- Depends on: `core.celery_app`, `core.database.SessionLocal`, `services._batch_runtime`

---

## `app/api/` — Routers (11 modules)

| Router | File | Domain |
|---|---|---|
| auth | `auth.py` | Login / JWT |
| users | `users.py` | User CRUD |
| crawls | `crawls.py` | Crawl run lifecycle |
| records | `records.py` | Record export |
| jobs | `jobs.py` | Job status |
| review | `review.py` | Review / promotions |
| selectors | `selectors.py` | Selector rules |
| llm | `llm.py` | LLM config & costs |
| dashboard | `dashboard.py` | Dashboard metrics |
| data_enrichment | `data_enrichment.py` | Enrichment jobs |
| product_intelligence | `product_intelligence.py` | Product matching |

All routers depend on `app.core.dependencies` (DB session, auth) and `app.schemas`.

---

## `app/core/` — Infrastructure

| Module | Role | Key Dependencies |
|---|---|---|
| `config.py` | Pydantic `BaseSettings`, env loading | — |
| `database.py` | Async SQLAlchemy engine + `SessionLocal` | `config.settings` |
| `celery_app.py` | Celery broker configuration | `config.settings` |
| `redis.py` | Redis client + key helpers | `config.settings` |
| `security.py` | Password hashing, JWT encode/decode | — |
| `dependencies.py` | FastAPI injectables (DB session, current user) | `database`, `security` |
| `telemetry.py` | Correlation IDs, structured logging | — |
| `metrics.py` | Prometheus metrics + health checks | `database`, `redis` |
| `migrations.py` | Migration helpers | — |

---

## `app/models/` — ORM

| File | Models |
|---|---|
| `crawl.py` | `CrawlRun`, `CrawlRecord`, `CrawlLog`, `ReviewPromotion`, `DataEnrichmentJob`, `EnrichedProduct`, `ProductIntelligenceJob`, `ProductIntelligenceSourceProduct`, `ProductIntelligenceCandidate`, `ProductIntelligenceMatch` |
| `user.py` | `User` |
| `llm.py` | `LLMConfig`, `LLMCostLog` |
| `crawl_domain.py` | Domain memory models |
| `crawl_settings.py` | Run settings persistence |

All inherit from `Base` defined in `core.database`.

---

## `app/schemas/` — Pydantic DTOs

| File | Schemas |
|---|---|
| `crawl.py` | Run create/update, record DTOs |
| `user.py` | User request/response |
| `llm.py` | LLM config schemas |
| `product_intelligence.py` | Matching & candidate schemas |
| `data_enrichment.py` | Enrichment schemas |
| `selectors.py` | Selector rule schemas |
| `common.py` | Shared base classes |

---

## `app/services/` — Business Logic (58+ files)

### Acquisition Layer (`services/acquisition/`)

| Module | Purpose |
|---|---|
| `acquirer.py` | `AcquisitionRequest` / `AcquisitionResult`, top-level `acquire()` |
| `browser_runtime.py` | Playwright browser pool, context lifecycle |
| `browser_page_flow.py` | Page navigation, DOM readiness, markdown serialization |
| `browser_detail.py` | Detail-page browser automation |
| `browser_capture.py` | Screenshot / artifact capture |
| `browser_identity.py` | Browser fingerprinting, UA rotation |
| `browser_proxy_bridge.py` | Proxy routing for browser contexts |
| `browser_readiness.py` | DOM-ready heuristics |
| `browser_recovery.py` | Retry / crash recovery logic |
| `browser_stage_runner.py` | Staged execution wrapper |
| `browser_diagnostics.py` | Failure diagnostics collection |
| `traversal.py` | Link traversal, pagination discovery |
| `cookie_store.py` | Persistent cookie jar |
| `http_client.py` | Shared `httpx.AsyncClient` wrapper |
| `runtime.py` | HTTP fetch result types, cache, blocked-HTML detection |
| `pacing.py` | Host-level rate limiting (`wait_for_host_slot`) |
| `dom_runtime.py` | DOM snapshot helpers |
| `host_protection_memory.py` | Hard-block tracking per host |
| `browser_proxy_config.py` | Proxy profile configuration |

**Key re-exports** in `services/acquisition/__init__.py`: `browser_runtime_snapshot`, `shutdown_browser_runtime`, `close_shared_http_client`, `PageFetchResult`, `validate_cookie_policy_config`, etc.

### Pipeline Orchestration (`services/pipeline/`)

| Module | Purpose |
|---|---|
| `core.py` | `process_single_url()` — the main pipeline: acquire → adapter / LLM / detail extract → normalize → persist |
| `_batch_runtime.py` | `process_run_async()` — iterates URLs, applies crawl settings, heartbeat, calls `process_single_url()` |
| `persistence.py` | Save records + artifacts to DB |
| `direct_record_fallback.py` | LLM fallback when deterministic extraction fails |
| `extraction_retry_decision.py` | Retry logic on empty / low-quality extraction |
| `runtime_helpers.py` | Stage constants (`STAGE_ACQUIRE`, `STAGE_EXTRACT`, …), logging helpers |
| `types.py` | `URLProcessingConfig`, `URLProcessingResult` |

**Dependency flow**:
```
_batch_runtime.py ──► pipeline/core.py ──► acquisition/acquirer.py
                              │
                              ├──► adapters/registry.py
                              ├──► llm_runtime.py / llm_tasks.py
                              ├──► extraction_runtime.py / detail_extractor.py
                              └──► pipeline/persistence.py
```

### Deterministic Extraction (`services/extract/`)

| Module | Purpose |
|---|---|
| `detail_dom_extractor.py` | Field extraction from DOM |
| `detail_record_finalizer.py` | Record validation, image merging, final cleanup |
| `detail_identity.py` | Identity code generation / matching |
| `detail_price_extractor.py` | Price normalization |
| `detail_raw_signals.py` | Breadcrumbs, category inference |
| `detail_text_sanitizer.py` | Text cleaning |
| `detail_tiers.py` | Tiered extraction strategy |
| `detail_title_scorer.py` | Title quality scoring |
| `listing_candidate_ranking.py` | Listing relevance ranking |
| `listing_card_fragments.py` | Listing card parsing |
| `listing_visual.py` | Visual (image) listing signals |
| `shared_variant_logic.py` | Variant deduplication |
| `variant_record_normalization.py` | Variant flattening / merging |

### Platform Adapters (`services/adapters/`)

| Adapter | Platform |
|---|---|
| `amazon.py`, `ebay.py`, `shopify.py`, `walmart.py`, `myntra.py`, `nike.py`, `belk.py`, `adp.py` | E-commerce |
| `greenhouse.py`, `icims.py`, `indeed.py`, `jibe.py`, `linkedin.py`, `oracle_hcm.py`, `paycom.py`, `remoteok.py`, `remotive.py`, `saashr.py`, `ultipro.py`, `workday.py` | Jobs/HR |
| `base.py` | `AdapterResult`, host matching utilities |
| `registry.py` | `get_adapter_class()`, `run_adapter()` dispatcher |

### LLM Layer

| Module | Purpose |
|---|---|
| `llm_runtime.py` | Thin entry point for direct LLM extraction |
| `llm_tasks.py` | Prompt construction, model dispatch (Anthropic / Groq / NVIDIA), response parsing |
| `llm_provider_client.py` | Provider-specific client wrappers |
| `llm_config_service.py` | Run-level LLM config resolution |
| `llm_cache.py` | Prompt/response caching |
| `llm_circuit_breaker.py` | Failure-rate circuit breaker |
| `llm_types.py` | Shared LLM type aliases |

### Configuration (`services/config/`)

| Module | Content |
|---|---|
| `runtime_settings.py` | Global crawler tunables (timeouts, pool sizes) |
| `extraction_rules.py` + `.exports.json` | Field extraction rules |
| `field_mappings.py` + `.exports.json` | Field name mappings |
| `selectors.py` + `.exports.json` | CSS/XPath selector presets |
| `browser_fingerprint_profiles.py` | Browser profile definitions |
| `browser_init_scripts.py` | Playwright init scripts (large) |
| `browser_surface_probe.py` | Surface detection rules |
| `network_capture.py` / `network_payload_specs.py` | Network intercept rules |
| `platforms.json` | Platform detection signatures |
| `data_enrichment.py` | Enrichment config |
| `product_intelligence.py` | Matching thresholds |
| `security_rules.py` | Block signature rules |
| `block_signatures.py` | Known block page patterns |

### Supporting Services

| Module | Purpose |
|---|---|
| `crawl_service.py` | Run CRUD, stale-run recovery |
| `crawl_crud.py` | Low-level run / record DB operations |
| `crawl_state.py` | Status enum, control flags (`TERMINAL_STATUSES`) |
| `crawl_events.py` | Event publishing |
| `crawl_utils.py` | URL normalization, CSV parsing |
| `crawl_access_service.py` | Permission checks |
| `crawl_fetch_runtime.py` | Fetch orchestration utilities |
| `crawl_ingestion_service.py` | Bulk ingestion |
| `dashboard_service.py` | Metrics aggregation for dashboard |
| `domain_memory_service.py` | Per-domain selector learning |
| `domain_run_profile_service.py` | Domain acquisition contract profiles |
| `record_export_service.py` | CSV / JSON export |
| `schema_service.py` | Schema validation |
| `selector_self_heal.py` | Selector repair on drift |
| `selectors_runtime.py` | Selector execution engine |
| `xpath_service.py` | XPath compilation / caching |
| `field_value_core.py` | Field validation for surface |
| `field_value_candidates.py` | Candidate scoring |
| `field_value_dom.py` | DOM-based field resolution |
| `field_policy.py` | Field repair policies |
| `field_url_normalization.py` | URL canonicalization |
| `listing_extractor.py` | Top-level listing extraction entry |
| `extraction_runtime.py` | `extract_records()` orchestrator |
| `extraction_context.py` | Extraction context object |
| `extraction_html_helpers.py` | HTML utility functions |
| `js_state_mapper.py` | JavaScript state → record mapping |
| `js_state_helpers.py` | JS state parsing helpers |
| `network_payload_mapper.py` | XHR/fetch response → record mapping |
| `network_resolution.py` | DNS / proxy resolution |
| `structured_sources.py` | JSON-LD / microdata parsing |
| `platform_policy.py` | Platform family detection |
| `robots_policy.py` | robots.txt compliance |
| `public_record_firewall.py` | Public record filtering |
| `confidence.py` | Extraction confidence scoring |
| `artifact_store.py` | Artifact persistence |
| `auth_service.py` | User / admin bootstrapping |
| `user_service.py` | User management |
| `detail_extractor.py` | Legacy detail extraction entry |
| `publish/` | `verdict.py`, `metadata.py`, `metrics.py` — result verdicts |
| `data_enrichment/` | `service.py`, `shopify_catalog.py` |
| `product_intelligence/` | `service.py`, `discovery.py`, `matching.py` |
| `normalizers/` | Output normalizers |

---

## `tests/` — Test Structure

| Directory | Content |
|---|---|
| `api/` | API endpoint tests |
| `services/` | 49 files — unit tests for extraction, acquisition, pipeline, etc. |
| `fixtures/` | Shared test data |
| `conftest.py` | Pytest fixtures (DB, client, etc.) |

---

## Dependency Summary (Layer Cake)

```
┌─────────────────────────────────────────┐
│  app/api/  (FastAPI routers)            │
├─────────────────────────────────────────┤
│  app/schemas/  (Pydantic DTOs)            │
├─────────────────────────────────────────┤
│  app/services/  (Business logic)          │
│  ├── pipeline/  (orchestration)          │
│  ├── acquisition/  (browser + HTTP)      │
│  ├── adapters/  (platform extractors)    │
│  ├── extract/  (DOM/text extraction)     │
│  ├── llm_*  (LLM backfill)               │
│  ├── config/  (rules & tunables)         │
│  └── crawl_*, domain_*, record_*          │
├─────────────────────────────────────────┤
│  app/models/  (SQLAlchemy ORM)            │
├─────────────────────────────────────────┤
│  app/core/  (infra: DB, Redis, Celery,    │
│             security, telemetry)          │
└─────────────────────────────────────────┘
```

**Cross-cutting entry points**:
- `app/main.py` → `api/*` + `core/*` + `services/acquisition`
- `app/tasks.py` → `core/celery_app` + `services/_batch_runtime`
- `services/_batch_runtime.py` → `pipeline/core.py` → `acquisition`, `adapters`, `extract`, `llm_tasks`, `persistence`
