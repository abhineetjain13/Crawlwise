# CrawlerAI Backend: Feature Specification Document

> **Agent-Readable Reference** — Grounded in code at `c:\Projects\pre_poc_ai_crawler\backend`

---

## 1. Architecture Overview

| Layer | Responsibility | Key Files |
|-------|---------------|-----------|
| **API** | HTTP routes, auth, validation | `app/api/*.py` |
| **Core** | Config, DB, security, dependencies | `app/core/*.py` |
| **Models** | SQLAlchemy ORM entities | `app/models/*.py` |
| **Schemas** | Pydantic request/response DTOs | `app/schemas/*.py` |
| **Services** | Business logic, extraction, acquisition | `app/services/**/*.py` |
| **Pipeline** | Orchestrates crawl lifecycle | `app/services/pipeline/core.py` |
| **Tasks** | Celery background job handlers | `app/tasks.py` |

**Framework**: FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL + Redis + Celery + Playwright

---

## 2. Data Models (Database Schema)

### 2.1 User Management
```python
# app/models/user.py
User
├── id: int PK
├── email: str (unique, indexed)
├── hashed_password: str
├── role: str ("user" | "admin")
├── is_active: bool
├── token_version: int  # For session invalidation
├── created_at, updated_at: datetime
```

### 2.2 Crawl System (Core Domain)
```python
# app/models/crawl.py
CrawlRun
├── id: int PK
├── user_id: int FK → users.id
├── run_type: str ("crawl" | "batch" | "csv")
├── url: str (primary URL or empty for batch)
├── status: str (pending|running|paused|completed|killed|failed|proxy_exhausted)
├── surface: str (ecommerce_listing|ecommerce_detail|job_listing|job_detail|automobile_listing|automobile_detail|tabular)
├── settings: JSONB (runtime params, proxy config, traversal)
├── requested_fields: JSONB (user-selected output fields)
├── result_summary: JSONB (progress, metrics, verdict)
├── queue_owner: str | None (distributed lease)
├── lease_expires_at: datetime | None
├── last_heartbeat_at: datetime | None
├── claim_count: int
├── last_claimed_at: datetime | None
├── created_at, updated_at, completed_at: datetime

CrawlRecord
├── id: int PK
├── run_id: int FK → crawl_runs.id (CASCADE)
├── source_url: str (origin URL)
├── url_identity_key: str | None (unique constraint with run_id)
├── data: JSONB (final extracted/cleaned fields)
├── raw_data: JSONB (pre-normalization extraction)
├── discovered_data: JSONB (LLM-discovered fields)
├── source_trace: JSONB (extraction provenance)
├── raw_html_path: str | None (artifact file path)
├── created_at: datetime

CrawlLog
├── id: int PK
├── run_id: int FK → crawl_runs.id
├── level: str (debug|info|warning|error)
├── message: str
├── created_at: datetime

ReviewPromotion  # Saved selector/schema mappings
├── id: int PK
├── run_id: int FK
├── domain: str (indexed)
├── surface: str
├── approved_schema: JSONB
├── field_mapping: JSONB
```

### 2.3 LLM Configuration
```python
# app/models/llm.py
LLMConfig
├── id: int PK
├── provider: str (anthropic|groq|nvidia)
├── model: str
├── api_key_encrypted: str (Fernet encrypted)
├── task_type: str (extraction|fallback|enrichment)
├── per_domain_daily_budget_usd: Decimal
├── global_session_budget_usd: Decimal
├── is_active: bool

LLMCostLog  # Audit trail for LLM spend
├── id: int PK
├── run_id: int | None
├── provider, model, task_type: str
├── input_tokens, output_tokens: int
├── cost_usd: Decimal
├── domain: str
├── created_at: datetime
```

### 2.4 Domain Memory (Selector Storage)
```python
# app/models/crawl.py (DomainMemory)
DomainMemory
├── id: int PK
├── domain: str (indexed)
├── surface: str (indexed)
├── platform: str | None (detected platform family)
├── selectors: JSONB (CSS/XPath rules)
```

---

## 3. API Surface

### 3.1 Authentication Flow (`/api/auth`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/register` | POST | No | Create user (disabled by default via `registration_enabled` setting) |
| `/login` | POST | No | JWT login + httpOnly cookie |
| `/me` | GET | Yes | Current user profile |

**Login Flow** (auth.py:45)
```
POST /api/auth/login
  -> authenticate_user() (auth_service.py:79)
     -> Query User by email from DB (auth_service.py:80)
     -> verify_password() check (security.py:19)
        -> pbkdf2_sha256.verify()
     -> create_access_token() (security.py:27)
        -> jwt.encode() with expiry
  -> Set httponly cookie in response (auth.py:51)
```

**Protected Route Access** (dependencies.py:73)
```
get_current_user() dependency
  -> Extract token from cookie/header (dependencies.py:74)
  -> decode_access_token() (security.py:33)
     -> jwt.decode() & validate
  -> Load User from DB by ID (dependencies.py:88)
  -> Check token_version match (dependencies.py:91)
```

**Security Model**:
- JWT tokens with 24h expiration (`jwt_expire_hours`)
- Token versioning for session invalidation
- PBKDF2-SHA256 password hashing (`security.py:19`)
- Fernet encryption for secrets (API keys)

### 3.2 Crawl Management (`/api/crawls`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /` | POST | Create single-URL crawl |
| `POST /csv` | POST | Create batch crawl from CSV upload |
| `GET /` | GET | List runs (paginated, filterable by status/type) |
| `GET /{id}` | GET | Get run details |
| `DELETE /{id}` | DELETE | Delete run (if not terminal) |
| `POST /{id}/pause` | POST | Pause active run |
| `POST /{id}/resume` | POST | Resume paused run |
| `POST /{id}/kill` | POST | Force-stop run |
| `POST /{id}/cancel` | POST | Alias for kill |
| `GET /{id}/logs` | GET | Get run logs (paginated) |
| `WS /{id}/logs/ws` | WS | Real-time log streaming |
| `POST /{id}/commit-fields` | POST | Manual field value commits |
| `POST /{id}/llm-commit` | POST | Commit LLM-suggested field values |

### 3.3 Records & Export (`/api/crawls/{id}/records`, `/api/records`)
| Endpoint | Description |
|----------|-------------|
| `GET /api/crawls/{id}/records` | List extracted records (paginated) |
| `GET /api/records/{id}/provenance` | Full provenance for debugging |
| `GET /api/crawls/{id}/export/json` | NDJSON export |
| `GET /api/crawls/{id}/export/csv` | CSV export |
| `GET /api/crawls/{id}/export/tables.csv` | Tables-only CSV |
| `GET /api/crawls/{id}/export/markdown` | Markdown tables |
| `GET /api/crawls/{id}/export/discoverist` | Discoverist format |

### 3.4 Review Workflow (`/api/review`)
| Endpoint | Description |
|----------|-------------|
| `GET /{run_id}` | Review payload (fields, records, suggested mappings) |
| `GET /{run_id}/artifact-html` | Raw HTML for visual review |
| `POST /{run_id}/save` | Save approved field mappings |

### 3.5 Selector Management (`/api/selectors`)
| Endpoint | Description |
|----------|-------------|
| `GET /?domain=&surface=` | List selectors for domain |
| `POST /` | Create selector rule |
| `PUT /{id}` | Update selector |
| `DELETE /{id}` | Delete selector |
| `DELETE /domain/{domain}` | Bulk delete for domain |
| `POST /suggest` | Auto-generate CSS/XPath suggestions |
| `POST /test` | Live test selector against URL |
| `GET /preview-html?url=` | Fetch URL for selector testing |

### 3.6 LLM Admin (`/api/llm`)
| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /providers` | Admin | List available LLM providers |
| `GET /configs` | Admin | List configurations |
| `POST /configs` | Admin | Add provider config (encrypts API key) |
| `PUT /configs/{id}` | Admin | Update config |
| `DELETE /configs/{id}` | Admin | Delete config |
| `POST /test-connection` | Admin | Validate provider connectivity |

### 3.7 Dashboard (`/api/dashboard`)
| Endpoint | Auth | Description |
|----------|------|-------------|
| `GET /` | User | Stats: total runs, active, records, top domains |
| `GET /metrics` | Admin | Operational metrics |
| `POST /reset-data` | Admin | Purge all crawl data |

### 3.8 Health & Observability
| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | DB, Redis, browser pool status |
| `GET /api/metrics` | Prometheus metrics |

---

## 4. Core Capabilities

### 4.1 Status State Machine
```
pending → running → completed
   ↓        ↓
 killed    paused → running
   ↓        ↓
failed   killed/failed

proxy_exhausted (terminal from running)
```
State transitions enforced in `app/models/crawl_domain.py:_ALLOWED_TRANSITIONS`

### 4.2 Crawl Run Types
| Type | Input | Behavior |
|------|-------|----------|
| `crawl` | Single URL | One URL, extraction, done |
| `batch` | Multiple URLs | Sequential/batched URL processing |
| `csv` | CSV file upload | Batch with URL list from column |

### 4.3 Surface Types & Supported Fields
Surfaces define extraction schema and available fields:
- `ecommerce_listing` / `ecommerce_detail`: Product data
- `job_listing` / `job_detail`: Job postings
- `automobile_listing` / `automobile_detail`: Vehicle listings
- `tabular`: Generic table extraction

Field policy enforcement: `app/services/field_policy.py`

### 4.4 Multi-Stage Pipeline (process_single_url)

Orchestrated in `app/services/pipeline/core.py:251`:

**Stage 1: ACQUIRE** (`core.py:286`)
- `_run_acquisition_stage()` → `acquire(request)` → `fetch_page()`
- Returns HTML via HTTP (curl-cffi) or Browser (Playwright)
- Block detection via `is_blocked_html()` (`runtime.py:100`)

**Stage 2: EXTRACT** (`core.py:296`)
- `_run_extraction_stage()` → `_extract_records_for_acquisition()`
- Platform adapters: `run_adapter()` (`core.py:677`) via registry
- DOM extraction: `_run_record_extraction()` → `extract_records()` (thread pool)
- Selector self-heal: `apply_selector_self_heal()` (`core.py:612`)
- LLM fallback: `apply_llm_fallback()` (`core.py:624`) for low-confidence fields

**Stage 3: NORMALIZE** (`core.py:298`)
- `_run_normalization_stage()` → `finalize_record()` for each record
- Field coercion, URL absolutization, text sanitization

**Stage 4: PERSIST** (`core.py:856`)
- `_run_persistence_stage()` → `persist_extracted_records()` (`persistence.py:115`)
- Deduplication via `_compute_identity_key()` (hash of URL + title)
- Artifact storage: `persist_acquisition_artifacts()` → `artifact_store.write_text()`

### 4.5 Browser Automation Flow

Playwright-based in `app/services/acquisition/browser_runtime.py`:

**Pool Management** (`browser_runtime.py:126`)
- `SharedBrowserRuntime` with semaphore-limited contexts (`max_contexts`)
- Browser instance reuse with `browserforge` identity generation

**Context Acquisition** (`browser_runtime.py:429`)
- `_acquire_browser_context()` from shared pool
- `playwright-stealth` integration when installed

**Page Navigation** (`browser_page_flow.py:41`)
- `navigate_browser_page_impl()`: `page.goto()` with timeout handling
- `probe_browser_readiness_impl()`: Wait for selectors (`browser_readiness.py:51`)

**Listing Traversal** (`traversal.py:64`)
- `execute_listing_traversal()`: Scroll/click pagination
- Bounded per-step snapshots (not full DOM concatenation)
- Traversal-composed HTML + full rendered HTML retained

**Screenshot Capture** (`browser_capture.py:22`)
- Temp file staging → pipeline persistence
- Debug artifact for blocked pages

### 4.6 Platform Adapter System

Platform-specific parsers in `app/services/adapters/`:
- **E-commerce**: amazon, ebay, myntra, shopify, walmart
- **Jobs**: greenhouse, icims, linkedin, oracle_hcm, paycom, workday, ultipro, saashr, indeed, jibe
- **Remote**: remotive, remoteok
- **Generic**: adp (fallback)

**Adapter Resolution Flow** (`core.py:641`)
1. `_populate_adapter_records()` → `run_adapter()` (`core.py:677`)
2. Registry lookup: `registry.resolve_adapter()` (`registry.py:80`)
3. Detection: `adapter.can_handle(url, html)` (`registry.py:90`)
4. Extraction: `adapter.extract()` (`registry.py:97`)
5. Transform: `direct_record_to_surface_fields()` (`extraction_runtime.py:71`)
6. Attach: Records added to `acquisition_result.adapter_records`

**Registry**: `app/services/adapters/registry.py:58` - `registered_adapters()` list

### 4.7 Extraction Strategy (Priority Order)
1. Adapter match (platform-specific structured data)
2. JSON-LD / Microdata (`extruct` library)
3. Schema.org parsing
4. Selector rules (domain memory)
5. LLM extraction fallback (if enabled & budget allows)
6. Generic DOM heuristics

### 4.8 LLM Enhancement Pipeline

Budget-gated fallback extraction with caching and circuit breaking:

**Pipeline Entry** (`core.py:920`)
- `apply_llm_fallback()` triggered when record confidence < threshold
- `extract_missing_fields()` prepares HTML + existing fields

**LLM Task Execution** (`llm_runtime.py:30`)
1. `call_llm_with_cache()` → `build_llm_cache_key()` (`llm_cache.py:14`)
2. Cache lookup: `load_cached_llm_result()` (`llm_cache.py:16`) - Redis GET
3. On cache miss: `call_provider_with_retry()` (`llm_tasks.py:26`)
   - Providers: Anthropic, Groq, NVIDIA (`llm_provider_client.py:26`)
   - Store result: `store_cached_llm_result()` (`llm_cache.py:17`)

**Error Handling** (`llm_circuit_breaker.py:19`)
- `llm_circuit_breaker.classify_error()` for rate limits, auth, timeouts
- Prevents cascade failures

**Result Merge** (`core.py:199`)
- LLM fields merged into record
- Field type validation

### 4.9 Domain Memory & Selector Self-Healing

Selector persistence system for cross-run knowledge sharing:

**Load Phase** (`core.py:648`)
- `_load_selector_rules()` queries domain memory service
- `load_domain_memory()` (`domain_memory_service.py:133`) - SELECT from `domain_memory` table
- Filtered by normalized `(domain, surface)`

**Apply Phase** (`core.py:835`)
- Runtime loads stored selectors before extraction
- Layered: surface-specific + generic rules

**Self-Heal Phase** (`selector_self_heal.py:612`)
- `apply_selector_self_heal()` validates selectors on current page
- Test selectors: `selector_self_heal.py:89`
- Fix broken selectors: `selector_self_heal.py:95`

**Save Phase** (`domain_memory_service.py:53`)
- `create_domain_memory()` (`domain_memory_service.py:42`) instantiates record
- `INSERT/UPDATE domain_memory` table with validated selectors
- Reused on later runs before attempting new synthesis

### 4.10 Field Value Pipeline
`app/services/field_value_core.py`:
- Type coercion per field (price, date, URL, image, text)
- Canonical field mapping
- Multi-value field handling
- URL absolutization
- Text sanitization

### 4.11 Crawl Orchestration Flows

**Crawl Run Creation & Dispatch** (Trace 1)

```
POST /api/crawls endpoint (crawls.py:157)
  -> create_crawl_run_from_payload() (crawl_ingestion_service.py:21)
     -> validate & normalize payload (1b)
     -> create_crawl_run() (crawl_crud.py:29)
        -> CrawlRun model, status = PENDING (crawl_crud.py:72)
     -> dispatch_run() (crawl_service.py:176)
        -> if celery_enabled: apply_async() to queue (crawl_service.py:187)
        -> else: track_local_run_task()
  -> Celery worker: _run_task_in_worker_loop() (tasks.py:75)
     -> process_run_async() (tasks.py:44)
```

**Batch Runtime URL Processing** (Trace 2)

```
process_run_async() (tasks.py:44)
  -> _run_with_session() -> process_run() (_batch_runtime.py:75)
     1. Load run from DB, update to RUNNING (_batch_runtime.py:83)
     2. Resolve URL list from settings (_batch_runtime.py:86)
     3. URL Processing Loop (_batch_runtime.py:113)
        for idx, url in enumerate(url_list):
          - Check control signals (pause/kill) (_batch_runtime.py:115)
          - process_single_url() with asyncio.wait_for() (_batch_runtime.py:154)
          - Collect verdict & metrics (_batch_runtime.py:181)
          - run.update_summary() (_batch_runtime.py:188)
        Exit: All URLs processed OR max_records reached (_batch_runtime.py:199)
     4. Finalization: update to COMPLETED (_batch_runtime.py:215)
        Aggregate verdict calculation (_batch_runtime.py:214)
```

**Page Acquisition Decision** (Trace 3)

```
_run_acquisition_stage() (core.py:290)
  -> acquire() (acquirer.py:103)
     -> normalize_platform_url() (acquirer.py:89)
     -> resolve_platform_runtime_policy() (acquirer.py:90)
     -> fetch_page() (crawl_fetch_runtime.py:45)
        -> if prefer_browser? (crawl_fetch_runtime.py:89)
           YES: _acquire_browser_context() (browser_runtime.py:429)
                 -> SharedBrowserRuntime pool (browser_runtime.py:126)
                 -> semaphore.acquire() (browser_runtime.py:131)
                 -> playwright context (browser_identity.py:34)
           NO: httpx.AsyncClient.get() (runtime.py:27)
        -> is_blocked_html() check (runtime.py:100)
           -> classify_blocked_page() (runtime.py:55)
```

---

## 5. Configuration System

### 5.1 Environment Variables (`.env`)
```python
# Core
app_name, backend_host, backend_port
frontend_url, frontend_origins
database_url, redis_url

# Security
jwt_secret_key, jwt_algorithm, jwt_expire_hours
encryption_key  # 32-byte Fernet key

# Execution Mode
celery_dispatch_enabled  # Use Celery vs local asyncio
legacy_inprocess_runner_enabled
registration_enabled  # Multi-tenant signup

# Browser
playwright_headless
browser_pool_size  # Default: 2
browser_context_timeout_seconds

# HTTP Client
http_timeout_seconds, http_max_connections

# LLM
anthropic_api_key, groq_api_key, nvidia_api_key
llm_cache_ttl_seconds  # Default: 86400 (24h)

# Crawl Limits
system_max_concurrent_urls  # Default: 8
crawl_log_db_max_rows_per_run

# Admin Bootstrap
default_admin_email, default_admin_password
bootstrap_admin_once
```

### 5.2 Runtime Settings (per crawl)
Stored in `CrawlRun.settings` JSONB:
```python
urls: list[str]                    # Target URLs
proxy_list: list[str]              # Rotating proxies
traversal_mode: str | None         # "pagination" | "infinite_scroll" | "none"
max_pages: int (default: 3)        # Pagination limit
max_records: int (default: 50)     # Per-URL record cap
max_scrolls: int (default: 5)      # Infinite scroll iterations
sleep_ms: int                      # Request pacing
respect_robots_txt: bool
url_batch_concurrency: int         # Parallel URL processing
url_timeout_seconds: float
llm_enabled: bool
extraction_contract: list[dict]   # Field requirements per URL
```

---

## 6. Background Processing

### 6.1 Task Distribution
Two modes controlled by `celery_dispatch_enabled`:

**Local Mode** (default, POC):
- `crawl_service._track_local_run_task()` creates asyncio.Task
- Runs in FastAPI process
- Weakref tracking for cleanup

**Celery Mode** (production):
- `process_run_task.delay(run_id)` dispatches to workers
- Redis as broker
- Worker signal handling for graceful shutdown

### 6.2 Pipeline Execution
`app/services/_batch_runtime.py`:
1. Load run + settings
2. Process URLs sequentially or with concurrency
3. Per-URL: acquire → extract → normalize → persist
4. Update progress in `result_summary` JSONB
5. Write logs to `crawl_logs` table
6. Mark terminal status on completion/failure

### 6.3 Progress Tracking
`BatchRunProgressState` (dataclass) tracks:
- total_urls, completed_count
- url_verdicts (per-URL success/partial/blocked/empty)
- verdict_counts aggregation
- acquisition_summary (methods, timing, payloads)
- quality_summary (field coverage scores)

---

## 7. Export Formats

| Format | Content | Use Case |
|--------|---------|----------|
| **JSON** | Full records with metadata | API integration |
| **CSV** | Flattened records | Spreadsheet analysis |
| **tables.csv** | HTML table extractions only | Table data |
| **Markdown** | Formatted tables | Documentation |
| **discoverist** | Schema with discovered fields | Review/promotion |
| **provenance** | Raw + trace + manifest | Debugging |

Streaming exports for large datasets via `StreamingResponse`.

---

## 8. Key Design Decisions

| Decision | Rationale | File |
|----------|-----------|------|
| Async SQLAlchemy | Non-blocking DB for concurrent crawls | `app/core/database.py` |
| JSONB for records | Schema flexibility across surfaces | `app/models/crawl.py` |
| Fernet encryption | AES-128 for API keys at rest | `app/core/security.py` |
| Curl-cffi first | TLS fingerprint spoofing before browser | `app/services/acquisition/runtime.py` |
| Browser pooling | Reuse contexts for multi-page crawls | `app/services/acquisition/browser_runtime.py:126` |
| Semaphore limiting | Bound concurrent browser contexts | `app/services/acquisition/browser_runtime.py:131` |
| Domain memory | Persist learned selectors per domain+surface | `app/models/crawl.py:DomainMemory` |
| Adapter registry | Pluggable platform parsers | `app/services/adapters/registry.py:58` |
| Circuit breaker | Prevent LLM cost overrun | `app/services/llm_circuit_breaker.py:19` |
| LLM caching | Redis-backed response deduplication | `app/services/llm_cache.py:16` |
| Selector self-heal | Adapt to DOM changes without re-crawl | `app/services/selector_self_heal.py:612` |
| Thread pool extraction | Offload CPU work from event loop | `app/services/pipeline/core.py:722` |
| Identity key dedupe | Hash-based duplicate detection | `app/services/pipeline/persistence.py:89` |
| Token versioning | Session invalidation support | `app/core/security.py:24` |

---

## 9. Testing & Quality

### 9.1 Test Infrastructure
- **Unit**: `pytest` with `pytest-asyncio`
- **Smoke**: `run_acquire_smoke.py`, `run_extraction_smoke.py`
- **Acceptance**: `run_test_sites_acceptance.py` against real URLs
- **Harness**: `harness_support.py` for structured test cases

### 9.2 Linting & Types
- `ruff` (formatting/linting)
- `mypy` / `basedpyright` (type checking)
- `pylint` (complexity analysis)
- `bandit` (security scanning)
- `vulture` (dead code detection)

### 9.3 Database Migrations
Alembic in `backend/alembic/`:
- `alembic.ini` configuration
- `alembic/versions/` migration scripts
- `init_db.py` for fresh setup

---

## 10. File Inventory (Critical Paths)

```
backend/
├── app/
│   ├── main.py                 # FastAPI factory, lifespan, middleware
│   ├── api/                    # Route handlers (9 modules)
│   │   ├── auth.py:45          # Login endpoint, cookie setting
│   │   └── crawls.py:157       # POST /api/crawls entry point
│   ├── core/
│   │   ├── config.py           # Pydantic settings
│   │   ├── database.py         # Async SQLAlchemy engine
│   │   ├── security.py:19      # Password hashing, JWT create/decode
│   │   ├── dependencies.py:73    # get_current_user() dependency
│   │   └── metrics.py          # Health checks, Prometheus
│   ├── models/
│   │   ├── crawl.py            # CrawlRun, CrawlRecord, CrawlLog, DomainMemory
│   │   ├── user.py             # User
│   │   ├── llm.py              # LLMConfig, LLMCostLog
│   │   └── crawl_domain.py     # Status enum, transitions
│   ├── schemas/
│   │   ├── crawl.py            # Request/response DTOs
│   │   ├── user.py, llm.py, selectors.py, common.py
│   └── services/
│       ├── pipeline/
│       │   ├── core.py:251       # process_single_url orchestration
│       │   ├── core.py:286       # Stage 1: ACQUIRE entry
│       │   ├── core.py:296       # Stage 2: EXTRACT entry
│       │   ├── core.py:298       # Stage 3: NORMALIZE entry
│       │   ├── core.py:856       # Stage 4: PERSIST entry
│       │   └── persistence.py:115 # Record persistence to DB
│       ├── _batch_runtime.py:75  # process_run() URL loop
│       ├── _batch_runtime.py:83  # Status transition to RUNNING
│       ├── crawl_service.py:176  # dispatch_run() decision point
│       ├── crawl_service.py:187  # Celery apply_async()
│       ├── crawl_crud.py:29      # create_crawl_run()
│       ├── crawl_ingestion_service.py:21 # Payload validation
│       ├── extraction_runtime.py:84  # extract_listing_records()
│       ├── acquisition/
│       │   ├── acquirer.py:103     # acquire() entry
│       │   ├── browser_runtime.py:126 # SharedBrowserRuntime pool
│       │   ├── browser_runtime.py:131 # Semaphore limiting
│       │   ├── browser_runtime.py:429 # _acquire_browser_context()
│       │   ├── browser_page_flow.py:41 # Page navigation
│       │   ├── browser_readiness.py:51 # Readiness probing
│       │   ├── traversal.py:64       # Listing traversal
│       │   ├── browser_capture.py:22 # Screenshot capture
│       │   └── runtime.py:27       # HTTP client (httpx)
│       ├── adapters/
│       │   └── registry.py:58       # registered_adapters()
│       ├── domain_memory_service.py:133 # load_domain_memory()
│       ├── selector_self_heal.py:612    # Self-heal entry
│       ├── llm_runtime.py:30       # extract_missing_fields()
│       ├── llm_cache.py:16         # Cache lookup (Redis)
│       ├── llm_tasks.py:26         # Provider retry logic
│       └── llm_circuit_breaker.py:19  # Error classification
│   └── tasks.py:44               # process_run_async()
│   └── tasks.py:75               # _run_task_in_worker_loop()
├── pyproject.toml              # Dependencies, tool configs
└── alembic/                    # Database migrations
```

---

## 11. Quick Reference for Agents

### Adding a New Surface
1. Add to `field_policy.py:canonical_fields_for_surface()`
2. Add normalization in `field_value_core.py:direct_record_to_surface_fields()`
3. Update `CrawlCreate` surface validation in schema

### Adding a New Adapter
1. Create `adapters/{platform}.py` with `parse(html, url) -> list[AdapterRecord]`
2. Register in `adapters/registry.py:_ADAPTER_MAP`
3. Add platform detection in `platform_policy.py`

### Modifying Status Behavior
1. Update `crawl_domain.py:CrawlStatus` enum
2. Update `_ALLOWED_TRANSITIONS` map
3. Update `TERMINAL_STATUSES` / `ACTIVE_STATUSES` sets

### Adding Export Format
1. Add method in `record_export_service.py`
2. Add route in `records.py`
3. Add content-type handling in export response builder

---

*Document version: 1.1 | Updated with codemap architecture traces*
