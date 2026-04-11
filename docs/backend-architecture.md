# CrawlerAI Backend Architecture

> **Last Updated:** 2026-04-11

This document describes the current state of the codebase - where each piece of logic lives and how it connects.

---

## 1. Directory Structure

```
backend/
├── app/
│   ├── main.py                    # FastAPI entry, 7 routers registered
│   ├── tasks.py                   # Celery task: crawl.process_run
│   ├── api/
│   │   ├── auth.py              # /api/auth/* (register, login, me)
│   │   ├── crawls.py            # /api/crawls/* (CRUD + pause/resume/kill + ws)
│   │   ├── records.py          # /api/crawls/{id}/records + exports
│   │   ├── review.py          # /api/review/{id}/*
│   │   ├── dashboard.py       # /api/dashboard/*
│   │   ├── jobs.py            # /api/jobs/active
│   │   └── users.py          # /api/users/*
│   ├── core/
│   │   ├── config.py          # settings object
│   │   ├── database.py       # Base, SessionLocal, engine
│   │   ├── redis.py         # get_redis(), close_redis()
│   │   ├── celery_app.py    # Celery app config
│   │   ├── security.py     # encode/decode JWT
│   │   ├── dependencies.py # get_db, get_current_user
│   │   ├── telemetry.py    # logging config, correlation_id
│   │   └── metrics.py     # Prometheus
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py        # User ORM
│   │   ├── crawl.py      # CrawlRun, CrawlRecord, CrawlLog, ReviewPromotion
│   │   ├── crawl_settings.py  # CrawlRunSettings dataclass
│   │   ├── crawl_domain.py    # CrawlStatus, ACTIVE/TERMINAL_STATUSES
│   │   └── llm.py       # LLMConfig, LLMCostLog
│   ├── schemas/
│   │   ├── crawl.py    # Request/Response DTOs
│   │   ├── user.py
│   │   ├── llm.py
│   │   └── common.py   # PaginatedResponse, PaginationMeta
│   └── services/
│       ├── __init__.py
│       ├── main.py                # FastAPI factory
│       ├── tasks.py               # Celery task entry
```

The services directory is deeply nested - that's where the virus has spread:

```
backend/app/services/
├── __init__.py
├── auth_service.py                 # bootstrap_admin_user
├── user_service.py             # User CRUD 
├── crawl_service.py           # dispatch_run, pause, resume, kill
├── crawl_crud.py            # get_run, list_runs, delete_run, commit_*
├── crawl_ingestion_service.py  # create_crawl_run_from_*
├── crawl_access_service.py     # require_accessible_run
├── crawl_state.py            # CrawlStatus, TERMINAL_STATUSES, control req Redis
├── crawl_events.py            # append_log_event, prepare_log_event
├── crawl_metrics.py          # build_acquisition_profile, url metrics
├── crawl_metadata.py        # requested_field helpers
├── crawl_utils.py          # normalize_target_url, parse_csv_urls
├── crawl_crud.py           # get_run, get_run_logs
├── crawl_access_service.py  # require_accessible_run
├── run_summary.py           # merge_run_summary_patch
├── record_export_service.py # all export formatters
├── dashboard_service.py    # dashboard metrics
├── url_safety.py           # SSRF check, DNS resolution
├── schema_service.py       # resolve_schema
├── domain_utils.py        # normalize_domain
├── auth_service.py        # bootstrap_admin_user
├── db_utils.py
├── exceptions.py          # RunControlError, custom hierarchy
├── llm_service.py        # LLM client wrapper
├── llm_runtime.py        # snapshot configs, cost tracking
├── xpath_service.py      # XPath extraction + validation
├── knowledge_base/store.py # get_selector_defaults (EMPTY - deleted feature)
├── normalizers/__init__.py  # text/number normalizers
├── resource_monitor.py    # MemoryAdaptiveSemaphore
├── requested_field_policy.py # expand_requested_fields
├── semantic_detail_extractor.py # semantic extraction fallback
├── shared_acquisition.py  # acquire(), run_adapter(), try_blocked_adapter_recovery()

# CONFIG - typed tunables
├── config/
│   ├── __init__.py
│   ├── extraction_rules.py      # pipeline tunables
│   ├── field_mappings.py      # canonical schemas
│   ├── selectors.py          # card, pagination selectors
│   ├── block_signatures.py    # WAF signatures
│   ├── runtime_settings.py
│   ├── crawl_runtime.py      # URL timeouts, max concurrency
│   ├── llm_runtime.py      # LLM tunables
│   ├── platform_registry.py  # platform family registry
│   ├── platform_readiness.py # DOM readiness checks
│   ├── listing_heuristics.py
│   ├── nested_field_rules.py
│   └── acquisition_guards.py

# ACQUISITION - HTTP + browser
├── acquisition/
│   ├── acquirer.py         # main acquire() - curl_cffi → playwright
│   ├── http_client.py     # curl_cffi wrapper
│   ├── browser_client.py # playwright stealth context
│   ├── browser_runtime.py  # browser lifecycle
│   ├── blocked_detector.py # is_blocked()
│   ├── host_memory.py   # Redis-backed host preferences
│   ├── cookie_store.py  # policy-driven cookies
│   ├── pacing.py       # request pacing
│   ├── strategies.py   # acquisition strategies
│   ├── traversal.py   # scroll/paginate/load_more
│   └── session_context.py

# EXTRACT - listing + detail + JSON
├── extract/
│   ├── service.py         # extract_candidates()
│   ├── listing_extractor.py  # extract_listing_records()
│   ├── detail_extractor.py  # (moved to service.py)
│   ├── json_extractor.py   # extract_json_listing/detail()
│   ├── listing_quality.py   # listing_set_quality()
│   ├── listing_normalize.py
│   ├── listing_identity.py  # strong_identity_key()
│   ├── source_parsers.py    # JSON-LD, hydrated state, XHR
│   ├── field_classifier.py  # classify field type
│   ├── field_decision.py   # field decision logic
│   ├── variant_extractor.py
│   ├── signal_inventory.py
│   └── extractability.py    # can_extract()

# ADAPTERS - platform-specific
├── adapters/
│   ├── __init__.py
│   ├── base.py            # BaseAdapter, AdapterResult
│   ├── registry.py       # resolve_adapter(), try_blocked_adapter_recovery()
│   ├── amazon.py
│   ├── walmart.py
│   ├── ebay.py
│   ├── shopify.py
│   ├── adp.py
│   ├── icims.py
│   ├── greenhouse.py
│   ├── indeed.py
│   ├── jibe.py
│   ├── linkedin.py
│   ├── oracle_hcm.py
│   ├── paycom.py
│   ├── remoteok.py
│   ├── remotive.py
│   └── saashr.py

# PIPELINE - core pipeline stages
├── pipeline/
│   ├── __init__.py        # ALL THE EXPORTS - 150+ symbols
│   ├── core.py           # _process_single_url, _extract_listing, _extract_detail
│   ├── runner.py        # PipelineRunner, build_default_stages
│   ├── stages.py       # AcquireStage, ExtractStage, etc.
│   ├── types.py       # PipelineContext, URLProcessingConfig, etc.
│   ├── utils.py       # parse_html, _clean_page_text
│   ├── field_normalization.py  # _normalize_record_fields, _public_record_fields
│   ├── listing_helpers.py     # _listing_acquisition_blocked
│   ├── verdict.py          # VERDICT_*, _aggregate_verdict
│   ├── trace_builders.py    # _build_acquisition_trace
│   ├── rendering.py       # _render_fallback_card_group
│   ├── review_helpers.py
│   ├── llm_integration.py
│   ├── listing_helpers.py
│   ├── rendering.py
│   └── pipeline_config.py  # typed config facade

# REVIEW - review flows
├── review/
│   └── __init__.py     # review service helpers
```

---

## 2. How data flows through the system

### Entry: FastAPI receives crawl request
```
POST /api/crawls
  → app/api/crawls.py::crawls_create()
  → app/services/crawl_ingestion_service.py::create_crawl_run_from_payload()
  → app/services/crawl_service.py::dispatch_run()
  → Celery: task.process_run(run_id)
```

### Celery worker processes run
```
crawl.process_run(run_id)
  → app/services/_batch_runtime.py::process_run()
  → _BatchRunContext built from run settings
  → For each URL in url_list:
      → app/services/pipeline/core.py::_process_single_url()
```

### Pipeline per-URL
```
_process_single_url()
  → STAGE_FETCH: acquire()
  → STAGE_ANALYZE: _extract_listing() OR _extract_detail()
  → STAGE_SAVE: persist CrawlRecord
```

### Acquisition
```
acquire(url, settings)
  → url_safety.validate_url()
  → host_memory.get()
  → acquirer.acquire()
      → Try http_client first (curl_cffi)
      → If blocked → browser_client (Playwright)
  → Return AcquisitionResult(html, network_payloads, diagnostics)
```

### Extraction (listing)
```
_extract_listing(html, url, surface)
  → source_parsers.parse_json_ld()
  → source_parsers.parse_hydrated_state()
  → source_parsers.parse_xhr_payloads() 
  → listing_extractor.extract_listing_records()
  → listing_quality.listing_set_quality()
  → Return ExtractionResult(records)
```

### Extraction (detail)
```
_extract_detail(html, url, surface, fields)
  → adapters.resolve_adapter()
  → json_extractor.extract_json_detail()
  → source_parsers.parse_json_ld()
  → extract.service.extract_candidates()
  → llm_runtime.review_field_candidates() (if enabled)
  → Return ExtractionResult(record)
```

### Persistence
```
_persist_record(run_id, record)
  → CrawlRecord INSERT
  → source_trace built
  → verdict computed
  → run status updated
```

---

## 3. API Routes (what actually exists)

| Router | Prefix | Files |
|--------|--------|-------|
| auth | /api/auth | auth.py |
| crawls | /api/crawls | crawls.py (+ websocket) |
| records | /api/crawls/{id}/records | records.py |
| review | /api/review | review.py |
| dashboard | /api/dashboard | dashboard.py |
| jobs | /api/jobs | jobs.py |
| users | /api/users | users.py |

No selectors API. No LLM config API.

---

## 4. Key Classes/Functions by Area

### URL → Acquisition
- `services.acquisition.acquirer.acquire()` - main entry
- `services.acquisition.http_client.HttpClient` - curl_cffi wrapper
- `services.acquisition.browser_client.BrowserManager` - Playwright

### URL → Extraction  
- `services.pipeline.core._process_single_url()` - per-URL entry
- `services.pipeline.core._extract_listing()` - listing path
- `services.pipeline.core._extract_detail()` - detail path
- `services.extract.listing_extractor.extract_listing_records()`
- `services.extract.service.extract_candidates()` - detail candidates
- `services.extract.json_extractor.extract_json_detail/list()`

### URL → Persistence
- `services.crawl_crud.create_record()` - INSERT
- `services.pipeline.field_normalization._public_record_fields()` - sanitizes output
- `services.pipeline.verdict._aggregate_verdict()` - computes run verdict

### URL → Adapters
- `services.adapters.registry.resolve_adapter()` - finds adapter
- `services.adapters.base.BaseAdapter` - base class
- 15 platform adapters (amazon, walmart, ebay, shopify, etc.)

---

## 5. Redis Keys (runtime state)

| Key Pattern | Purpose |
|-------------|---------|
| `crawl:{run_id}:control` | Pause/resume/kill requests |
| `crawl:{run_id}:logs` | Log event buffer |
| `crawl:{run_id}:progress` | Progress counters |
| `host:{domain}:prefs` | Host preferences (blocked, proxy, etc.) |
| `pacing:{domain}` | Domain pacing state |

---

## 6. Database Tables

| Table | Model | Purpose |
|-------|-------|---------|
| users | User | authentication |
| crawl_runs | CrawlRun | run state |
| crawl_records | CrawlRecord | extracted data |
| crawl_logs | CrawlLog | run logs |
| review_promotions | ReviewPromotion | reviewed schemas |
| llm_configs | LLMConfig | LLM configs (NO API) |
| llm_cost_log | LLMCostLog | usage tracking |

---

## 7. How frontend calls backend

Frontend expects these endpoints:

| Frontend Call | Backend Exists? |
|--------------|----------------|
| api.listCrawls() | YES (/api/crawls) |
| api.createCrawl() | YES (/api/crawls) |
| api.getRecords() | YES (/api/crawls/{id}/records) |
| api.getCrawlLogs() | YES (/api/crawls/{id}/logs) |
| api.getReview() | YES (/api/review/{id}) |
| api.listSelectors() | NO |
| api.suggestSelectors() | NO |
| api.testSelector() | NO |
| api.listUsers() | YES (/api/users) |
| api.updateUser() | YES (/api/users/{id}) |
| api.listLLMConfigs() | NO |
| api.createLLMConfig() | NO |