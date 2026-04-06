# CrawlerAI Backend Architecture

> **Last Updated:** 2026-04-05
> **Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), SQLite, Playwright, curl_cffi
> **Test Status:** 360 tests collected; targeted regression suite green on 2026-04-05

---

## 1. System Overview

CrawlerAI is a deterministic web crawling pipeline that extracts structured data from ecommerce listing/detail pages and job boards. The backend runs as a FastAPI application with an in-process worker loop (no external message queue).

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                    │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP + Session Cookie / Bearer Token
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              10 API Route Modules                     │   │
│  │  auth | crawls | records | dashboard | jobs | llm    │   │
│  │  review | selectors | site_memory | users             │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│  ┌───────────────────────┴──────────────────────────────┐   │
│  │              Service Layer                            │   │
│  │  crawl_service | auth_service | review_service       │   │
│  │  selector_service | llm_service | dashboard_service  │   │
│  └───────────────────────┬──────────────────────────────┘   │
│                          │                                   │
│  ┌───────────────────────┴──────────────────────────────┐   │
│  │              Crawl Worker (workers.py)                │   │
│  │  Polls DB → Claims runs → Executes pipeline          │   │
│  │  Semaphore-limited concurrency (default: 8)           │   │
│  └───────────────────────┬──────────────────────────────┘   │
│                          │                                   │
│  ┌───────────────────────▼──────────────────────────────┐   │
│  │              Extraction Pipeline                      │   │
│  │  ACQUIRE → BLOCKED DETECT → DISCOVER → EXTRACT       │   │
│  │  → UNIFY → PUBLISH                                    │   │
│  └──────────────────────────────────────────────────────┘   │
│                          │                                   │
│  ┌───────────────────────┴──────────────────────────────┐   │
│  │              Knowledge Base (JSON)                    │   │
│  │  22 config files + 6 prompt templates                 │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              SQLite (crawlerai.db) + Alembic                 │
│  Tables: users, crawl_runs, crawl_records, crawl_logs,      │
│          review_promotions, selectors, llm_configs,         │
│          llm_cost_logs, site_memories                        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Structure

```
backend/
├── app/                              # Main application package
│   ├── main.py                       # FastAPI app factory, lifespan, router registration
│   ├── workers.py                    # In-process crawl worker loop
│   │
│   ├── core/                         # Core infrastructure
│   │   ├── config.py                 # Pydantic-settings application config
│   │   ├── database.py               # Async SQLAlchemy engine/session
│   │   ├── dependencies.py           # FastAPI DI: get_db, get_current_user, require_admin
│   │   └── security.py               # JWT, pbkdf2_sha256 password hashing
│   │
│   ├── models/                       # SQLAlchemy ORM models
│   │   ├── crawl.py                  # CrawlRun, CrawlRecord, CrawlLog, ReviewPromotion
│   │   ├── user.py                   # User (auth fields, token_version)
│   │   ├── selector.py               # Selector (CSS/XPath/regex, status enum)
│   │   ├── llm.py                    # LLMConfig, LLMCostLog
│   │   └── site_memory.py            # SiteMemory (domain-keyed JSON)
│   │
│   ├── schemas/                      # Pydantic request/response schemas
│   │   ├── common.py                 # PaginatedResponse, PaginationMeta
│   │   ├── crawl.py                  # CrawlCreate, CrawlRunResponse, CrawlRecordResponse
│   │   ├── user.py                   # UserCreate, UserResponse, AuthResponse
│   │   ├── selector.py               # SelectorCreate/Update, SelectorTestRequest/Response
│   │   ├── llm.py                    # LLMConfig CRUD, LLMCostLogResponse
│   │   └── site_memory.py            # SiteMemoryPayload/Response/Update
│   │
│   ├── api/                          # FastAPI route handlers (10 routers)
│   │   ├── auth.py                   # POST /api/auth/register, /login, GET /me
│   │   ├── crawls.py                 # Crawl CRUD + pause/resume/kill/cancel/commit-fields
│   │   ├── records.py                # Records + provenance + export (JSON/CSV/discoverist)
│   │   ├── dashboard.py              # GET /api/dashboard, POST /dashboard/reset-data
│   │   ├── jobs.py                   # GET /api/jobs/active
│   │   ├── llm.py                    # LLM config/catalog/test/cost-log (admin)
│   │   ├── review.py                 # Review payload/artifact/save/selector-preview
│   │   ├── selectors.py              # Selector CRUD/suggest/test/clear-all
│   │   ├── site_memory.py            # Site memory CRUD by domain
│   │   └── users.py                  # User admin (list/patch/delete)
│   │
│   ├── tasks/                        # Background task definitions
│   │   └── crawl_tasks.py            # Async crawl task orchestration
│   │
│   ├── services/                     # Business logic services
│   │   ├── pipeline_config.py        # Central config loader (single source of truth)
│   │   ├── crawl_service.py          # Crawl CRUD, pipeline orchestration, field commit
│   │   ├── crawl_state.py            # CrawlStatus enum, transition logic
│   │   ├── auth_service.py           # Auth, JWT, admin bootstrap
│   │   ├── user_service.py           # User CRUD
│   │   ├── dashboard_service.py      # Dashboard metrics, data reset
│   │   ├── domain_utils.py           # Domain normalization
│   │   ├── llm_service.py            # LLM config CRUD, cost logging
│   │   ├── llm_runtime.py            # LLM provider testing, catalog
│   │   ├── selector_service.py       # Selector CRUD, AI suggestion, live URL testing
│   │   ├── xpath_service.py          # XPath building/validation
│   │   ├── url_safety.py             # URL validation, SSRF protection, DNS resolution
│   │   ├── semantic_detail_extractor.py  # Section/spec extraction for detail pages
│   │   ├── site_memory_service.py    # Site memory CRUD
│   │   ├── requested_field_policy.py # Requested field policy
│   │   │
│   │   ├── acquisition/              # ACQUIRE phase
│   │   │   ├── acquirer.py           # Main orchestrator: curl_cffi → Playwright waterfall
│   │   │   ├── browser_client.py     # Playwright stealth, challenge, consent, interception
│   │   │   ├── blocked_detector.py   # WAF/CAPTTCHA/challenge page detection
│   │   │   ├── host_memory.py        # TTL-aware file-backed host stealth memory
│   │   │   ├── http_client.py        # HTTP client utilities
│   │   │   └── pacing.py             # Request pacing and retry backoff
│   │   │
│   │   ├── discover/                 # DISCOVER phase
│   │   │   └── service.py            # DiscoveryManifest: adapter data, JSON-LD, network, etc.
│   │   │
│   │   ├── extract/                  # EXTRACT phase
│   │   │   ├── service.py            # Main extraction orchestrator (detail pages)
│   │   │   ├── listing_extractor.py  # Listing page extraction (structured-data-first)
│   │   │   ├── json_extractor.py     # JSON API extraction (37 collection keys)
│   │   │   └── spa_pruner.py         # SPA/JS shell pruning
│   │   │
│   │   ├── adapters/                 # Domain-specific platform adapters
│   │   │   ├── base.py               # Base adapter ABC
│   │   │   ├── registry.py           # Adapter registry (domain-matched → signal-based)
│   │   │   ├── amazon.py             # Amazon
│   │   │   ├── walmart.py            # Walmart
│   │   │   ├── ebay.py               # eBay
│   │   │   ├── shopify.py            # Shopify (signal-based, /products/<handle>.js)
│   │   │   ├── indeed.py             # Indeed jobs
│   │   │   ├── linkedin.py           # LinkedIn Jobs
│   │   │   ├── greenhouse.py         # Greenhouse ATS (boards-api + HTML fallback)
│   │   │   └── remotive.py           # Remotive/RemoteOK (HTML fallback)
│   │   │
│   │   ├── review/                   # REVIEW phase
│   │   │   └── service.py            # Review payload builder, artifact, save, preview
│   │   │
│   │   ├── normalizers/              # Field normalization
│   │   │   └── field_normalizers.py  # Value normalization utilities
│   │   │
│   │   ├── knowledge_base/           # KB persistence
│   │   │   └── store.py              # Atomic write KB storage
│   │   │
│   │   └── page_intelligence/        # (reserved, empty)
│   │
│   └── data/knowledge_base/          # Pipeline configuration (JSON)
│       ├── block_signatures.json     # WAF/CAPTTCHA signatures
│       ├── canonical_schemas.json    # Per-surface canonical field lists
│       ├── card_selectors.json       # 22 ecommerce + 12 job card selectors
│       ├── collection_keys.json      # 37 JSON data array keys
│       ├── consent_selectors.json    # Cookie consent CSS selectors
│       ├── cookie_policy.json        # Cookie persistence policy
│       ├── discoverist_schema.json   # Discoverist export schema
│       ├── dom_patterns.json         # DOM detection patterns
│       ├── extraction_rules.json     # Structural keys, noise, source ranking
│       ├── field_aliases.json        # Field name aliases
│       ├── field_mappings.json       # Domain-specific field mappings
│       ├── hydrated_state_patterns.json  # SPA state patterns
│       ├── llm_tuning.json           # LLM tuning parameters
│       ├── normalization_rules.json  # Field normalization rules
│       ├── pagination_selectors.json # Pagination CSS selectors
│       ├── pipeline_tuning.json      # Thresholds, timeouts, heuristics
│       ├── prompt_registry.json      # LLM prompt registry
│       ├── requested_field_aliases.json  # Requested field aliases
│       ├── review_container_keys.json    # Review filter keys
│       ├── selector_defaults.json    # Per-domain selector memory
│       ├── verdict_rules.json        # Core fields for success verdict
│       └── prompts/                  # LLM prompt templates (6 files)
│
├── alembic/                          # Database migrations
│   ├── env.py
│   └── versions/
│       ├── 20260402_0001_initial.py
│       ├── 20260403_0002_selector_xpath_first.py
│       ├── 20260403_0003_auth_and_status_invariants.py
│       ├── 20260403_0004_remove_selector_confidence.py
│       └── 20260405_0005_site_memory.py
│
├── tests/                            # Test suite
│   ├── conftest.py
│   ├── api/
│   ├── services/
│   │   ├── acquisition/
│   │   ├── adapters/
│   │   ├── discover/
│   │   ├── extract/
│   │   └── review/
│   └── [various test modules]
│
├── run_acquire_smoke.py              # Acquire-only smoke tests (6 batches)
├── run_extraction_smoke.py           # Full extraction smoke tests (10 sites)
├── run_regression.py                 # Regression test runner
├── run_audit.py                      # Audit script runner
├── run_coverage_test.py              # Coverage test runner
├── pyproject.toml                    # Dependencies, pytest config
└── alembic.ini                       # Alembic configuration
```

---

## 3. Entry Points

### 3.1 FastAPI Application (`app/main.py`)

- Creates FastAPI app with lifespan context manager
- Registers CORS middleware (configurable origins)
- Mounts 10 API routers under `/api` prefix
- Bootstraps admin user on startup via `auth_service.bootstrap_admin()`
- Runs database table creation on startup

### 3.2 Crawl Worker (`app/workers.py`)

- Runs as a background task via `app.add_event_handler("startup", ...)`
- Polls database every 1 second for `pending` runs
- Claims runs atomically with `SELECT ... FOR UPDATE SKIP LOCKED`
- Executes runs concurrently with semaphore-limited concurrency (default: 8)
- Recovers only stale `claimed` / `running` runs after a grace window from crashes
- Invokes `run_crawl_task()` from `app/tasks/crawl_tasks.py`

---

## 4. Database Schema

### 4.1 Tables

| Table | Model | Key Columns |
|-------|-------|-------------|
| `users` | `User` | id, email, hashed_password, role, is_active, token_version, created_at |
| `crawl_runs` | `CrawlRun` | id, url, run_type, status, settings (JSON), result_summary (JSON), submitted_by, started_at, finished_at |
| `crawl_records` | `CrawlRecord` | id, run_id, record_index, data (JSON), raw_data (JSON), discovered_data (JSON), source_trace (JSON) |
| `crawl_logs` | `CrawlLog` | id, run_id, level, message, timestamp |
| `review_promotions` | `ReviewPromotion` | id, domain, field_name, approved_value, selector, promoted_at |
| `selectors` | `Selector` | id, domain, field_name, css_selector, xpath, regex, status, source, created_at |
| `llm_configs` | `LLMConfig` | id, provider, model, api_key (encrypted), monthly_budget, is_active |
| `llm_cost_logs` | `LLMCostLog` | id, config_id, prompt_tokens, completion_tokens, cost, timestamp |
| `site_memories` | `SiteMemory` | id, domain, payload (JSON), updated_at |

### 4.2 Migrations

5 Alembic migrations tracked:
1. **Initial** — users, crawls, selectors
2. **Selector XPath first** — reorders selector columns
3. **Auth/status invariants** — adds token_version, status constraints
4. **Remove selector confidence** — drops unused column
5. **Site memory** — adds site_memories table

---

## 5. API Endpoints

### 5.1 Auth (`/api/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | Public | Register new user |
| POST | `/api/auth/login` | Public | Login (sets httponly cookie) |
| GET | `/api/auth/me` | Session/Bearer | Current user info |

### 5.2 Crawls (`/api/crawls`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/crawls` | Authenticated | Submit single/batch crawl |
| POST | `/api/crawls/csv` | Authenticated | Submit CSV upload |
| GET | `/api/crawls` | Authenticated | List runs (paginated) |
| GET | `/api/crawls/{id}` | Authenticated | Run detail |
| DELETE | `/api/crawls/{id}` | Authenticated | Delete run |
| POST | `/api/crawls/{id}/pause` | Authenticated | Pause running crawl |
| POST | `/api/crawls/{id}/resume` | Authenticated | Resume paused crawl |
| POST | `/api/crawls/{id}/kill` | Authenticated | Kill running crawl |
| POST | `/api/crawls/{id}/cancel` | Authenticated | Cancel pending crawl |
| POST | `/api/crawls/{id}/commit-fields` | Authenticated | Manual reviewed field commit |
| POST | `/api/crawls/{id}/llm-commit` | Authenticated | LLM-based field commit |
| GET | `/api/crawls/{id}/logs` | Authenticated | Run logs |

### 5.3 Records (`/api/crawls/{id}/records`, `/api/records`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/crawls/{id}/records` | Authenticated | List records (paginated) |
| GET | `/api/records/{id}/provenance` | Authenticated | Field provenance view |
| GET | `/api/crawls/{id}/export/json` | Authenticated | Stream JSON export |
| GET | `/api/crawls/{id}/export/csv` | Authenticated | Stream CSV export |
| GET | `/api/crawls/{id}/export/discoverist` | Authenticated | Stream Discoverist export |

### 5.4 Review (`/api/review`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/review/{id}` | Authenticated | Review payload |
| GET | `/api/review/{id}/artifact-html` | Authenticated | Raw HTML artifact |
| POST | `/api/review/{id}/save` | Authenticated | Save review selections |
| POST | `/api/review/{id}/selector-preview` | Authenticated | Selector preview |

### 5.5 Selectors (`/api/selectors`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/selectors` | Authenticated | List selectors |
| POST | `/api/selectors` | Authenticated | Create selector |
| PUT | `/api/selectors/{id}` | Authenticated | Update selector |
| DELETE | `/api/selectors/{id}` | Authenticated | Delete selector |
| POST | `/api/selectors/suggest` | Authenticated | AI-based suggestion |
| POST | `/api/selectors/test` | Authenticated | Live URL test |
| DELETE | `/api/selectors/clear-all` | Authenticated | Clear all selectors |
| DELETE | `/api/selectors/domain/{domain}` | Authenticated | Delete by domain |

### 5.6 Admin Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/dashboard` | Authenticated | Dashboard metrics |
| POST | `/api/dashboard/reset-data` | Admin | Reset application data |
| GET | `/api/jobs/active` | Authenticated | Active running jobs |
| GET/POST | `/api/llm/config` | Admin | LLM config CRUD |
| POST | `/api/llm/test` | Admin | LLM connection test |
| GET | `/api/llm/cost-log` | Admin | Cost tracking log |
| GET | `/api/llm/catalog` | Admin | Provider catalog |
| GET/PATCH/DELETE | `/api/users/{id}` | Admin | User administration |
| GET/PUT/DELETE | `/api/site-memory/{domain}` | Authenticated | Site memory CRUD |

---

## 6. Crawl Pipeline

The pipeline follows: **ACQUIRE → BLOCKED DETECT → DISCOVER → EXTRACT → UNIFY → PUBLISH**

### 6.1 ACQUIRE (`services/acquisition/`)

**Orchestrator:** `acquirer.py`

```
acquire(url, settings)
  │
  ├── Validate URL (url_safety.py: SSRF check, DNS resolution, public IP verify)
  ├── Check host memory (host_memory.py: does this host need stealth?)
  │
  ├── Try curl_cffi first
  │   ├── DNS resolve → CurlOpt.RESOLVE for hostname pinning (preserves TLS/SNI)
  │   ├── Apply proxy rotation if configured
  │   ├── Apply stealth TLS fingerprint if host_memory says so
  │   └── Detect JSON response (Content-Type header or body sniff)
  │
  ├── If JS-blocked / challenge / short content / JS-shell → Playwright fallback
  │   ├── browser_client.py: stealth context creation
  │   ├── Origin warming
  │   ├── Cookie consent dismissal (from consent_selectors.json)
  │   ├── Network XHR/fetch interception
  │   ├── Accordion expansion (configurable max + wait)
  │   ├── Shadow DOM flattening
  │   └── Advanced modes: scroll, paginate, load_more
  │
  └── Return AcquisitionResult(html/json, network_payloads, diagnostics)
```

**Key invariants:**
- curl_cffi always tried first; Playwright is fallback only
- DNS pinning uses `CurlOpt.RESOLVE` on session, not URL rewrite
- No manual `Host` header injection in Playwright contexts
- Acquisition pacing from `pipeline_tuning.json`, not hardcoded sleeps
- Diagnostics persisted alongside HTML/JSON artifacts

**Blocked Detection:** `blocked_detector.py`
- Tiered: Active markers (high confidence) → CDN markers (low confidence) → Block phrases → Title regexes → Structural signals
- Rich content guard: don't block if page has rich usable content
- Adapter recovery: `try_blocked_adapter_recovery()` (Shopify only currently)

### 6.2 DISCOVER (`services/discover/`)

**Service:** `discover/service.py`

Produces `DiscoveryManifest` from acquired HTML:

```
discover(html, url, acquisition_result)
  │
  ├── Check adapter registry for domain-matched adapter
  ├── Parse JSON-LD (all script[type='application/ld+json'] blocks)
  ├── Extract __NEXT_DATA__ (script tags)
  ├── Find hydrated state objects (__NUXT__, __APOLLO_STATE__, __myx, __STORE__, __APP_STATE__)
  ├── Collect intercepted network payloads (XHR/fetch JSON)
  ├── Parse microdata ([itemscope] elements)
  ├── Extract tables (HTML <table> elements)
  └── Return DiscoveryManifest with all sources preserved
```

**Key invariant:** Source-preserving — all sources remain available for downstream reconciliation even when only one wins deterministic extraction.

### 6.3 EXTRACT (`services/extract/`)

#### Listing Extraction (`listing_extractor.py`)

Structured-data-first strategy with ordered fallback:

```
extract_listing(manifest, url, contract_fields)
  │
  ├── 1. JSON-LD item lists / Product arrays
  ├── 2. Embedded app state (__NEXT_DATA__)
  ├── 3. Hydrated state objects (__NUXT__, __APOLLO_STATE__, etc.)
  ├── 4. Network payloads (intercepted JSON)
  ├── 5. DOM card detection
  │   ├── Use card_selectors.json (22 ecommerce + 12 job patterns)
  │   ├── Auto-detect: score candidate groups by product signal density
  │   └── Extract fields from cards using ordered selectors
  │
  ├── Filter category/navigation URLs and title/image-only hub cards from product URLs
  ├── Resolve relative URLs against page URL
  └── Return list of records OR listing_detection_failed verdict
```

**Fallback guard:** 0 item-level records → `listing_detection_failed` verdict (never downgrades to detail-style single record).

#### Detail Extraction (`service.py`)

Deterministic source priority:

```
extract_detail(manifest, url, contract_fields)
  │
  ├── 1. Extraction contract (user-defined XPath/regex)
  ├── 2. Adapter data
  ├── 3. Network payloads
  ├── 4. __NEXT_DATA__
  ├── 5. JSON-LD
  ├── 6. Microdata
  ├── 7. DOM selectors
  ├── 8. Semantic sections (semantic_detail_extractor.py)
  └── 9. DOM patterns
       │
       ├── Quality scoring per field
       ├── Type-aware normalization
       ├── Noise filtering (JSON-LD types, promo labels, etc.)
       └── Return single record with field_discovery summaries
```

#### JSON Extraction (`json_extractor.py`)

First-class JSON API extraction:
- 37 collection keys (products, jobs, drinks, books, categories, etc.)
- GraphQL edges/node patterns
- Falls back to preserving scalar fields under original keys

### 6.4 UNIFY → PUBLISH

```
unify(records, manifest, requested_fields)
  │
  ├── Strip empty/null fields from record.data
  ├── Strip _-prefixed internal keys from record.data
  ├── Strip raw manifest containers from discovered_data
  ├── Build source_trace.field_discovery summaries
  ├── Compute extraction_verdict (success/partial/blocked/schema_miss/empty/error)
  ├── Map verdict to run status (completed=success, failed=all others)
  └── Persist to database
```

**Verdict logic:** Based on `VERDICT_CORE_FIELDS` presence only (from `verdict_rules.json`). Requested field coverage does NOT affect verdict.

---

## 7. Adapter Registry

**Registry:** `services/adapters/registry.py`

Resolution order:
1. Domain-matched adapters (exact domain match)
2. Signal-based adapters (Shopify detection via page signals)

| Adapter | Type | Strategy |
|---------|------|----------|
| Amazon | Ecommerce PDP | Domain match |
| Walmart | Ecommerce PDP | Domain match |
| eBay | Ecommerce PDP | Domain match |
| Shopify | Ecommerce (signal-based) | `/products/<handle>.js` endpoint |
| Indeed | Jobs listing | Domain match |
| LinkedIn Jobs | Jobs listing | Domain match |
| Greenhouse | ATS | `boards-api.greenhouse.io` + HTML fallback |
| Remotive/RemoteOK | Jobs listing | HTML fallback |

**Recovery:** `try_blocked_adapter_recovery()` attempts public platform endpoints when pages are blocked. Currently supports Shopify only.

---

## 8. Knowledge Base

All tunable values loaded at startup via `services/pipeline_config.py`. Code MUST import from this module — never hardcode these values.

| File | Contents |
|------|----------|
| `pipeline_tuning.json` | Max concurrent, backoff, recursion depth, accordion max/wait, candidate caps |
| `extraction_rules.json` | JSON-LD structural keys, non-product block types, product identity fields, source ranking, noise patterns, spec drop labels |
| `block_signatures.json` | WAF provider markers (PerimeterX, Cloudflare, Akamai, DataDome, Kasada), CAPTCHA phrases, access-denied patterns |
| `consent_selectors.json` | Cookie consent dialog CSS selectors |
| `cookie_policy.json` | Domain-specific cookie persistence allowlists |
| `card_selectors.json` | 22 ecommerce + 12 job card CSS selectors |
| `collection_keys.json` | 37 JSON data array keys |
| `canonical_schemas.json` | Per-surface canonical field lists |
| `field_aliases.json` | Field name → canonical name mappings |
| `field_mappings.json` | Domain-specific field mappings |
| `dom_patterns.json` | DOM detection patterns |
| `hydrated_state_patterns.json` | SPA state object patterns |
| `normalization_rules.json` | Field-specific normalization rules |
| `verdict_rules.json` | Core fields for success verdict |
| `selector_defaults.json` | Per-domain default selectors |
| `pagination_selectors.json` | Pagination CSS selectors |
| `llm_tuning.json` | LLM tuning parameters |
| `prompt_registry.json` | LLM prompt registry |
| `requested_field_aliases.json` | Requested field aliases |
| `review_container_keys.json` | Review filter keys |
| `discoverist_schema.json` | Discoverist export schema |

**Prompts** (`prompts/`):
- `field_cleanup_review.system.txt` / `.user.txt`
- `missing_field_extraction.system.txt` / `.user.txt`
- `xpath_discovery.system.txt` / `.user.txt`

---

## 9. Design Patterns

| Pattern | Where |
|---------|-------|
| **Waterfall Acquisition** | curl_cffi → Playwright → curl_cffi fallback |
| **Strategy Pattern** | Platform adapters via `BaseAdapter` ABC |
| **Source-Ranked Extraction** | Deterministic priority from `extraction_rules.json` |
| **Knowledge Base** | All tunables in JSON, loaded via `pipeline_config.py` |
| **Worker Claim** | `SELECT ... FOR UPDATE SKIP LOCKED` for race-free claiming |
| **State Machine** | `_ALLOWED_TRANSITIONS` in `crawl_state.py` |
| **Atomic Writes** | temp-file + `os.replace()` for KB store |
| **Fail-Closed URL Safety** | DNS failure → reject, never silently allow |
| **Policy-Driven Cookies** | `cookie_policy.json` allowlists, challenge cookies filtered |

---

## 10. Authentication & Authorization

- **Password hashing:** `pbkdf2_sha256` (passlib)
- **JWT:** python-jose, with `token_version` on User model for revocation
- **Session:** httponly cookie set on login
- **API auth:** Accepts either session cookie OR `Authorization: Bearer <token>`
- **Admin bootstrap:** Auto-creates admin user from env vars on startup
- **Role-based:** `require_admin` dependency guards admin-only endpoints

---

## 11. Testing

### 11.1 Unit/Integration Tests

```powershell
$env:PYTHONPATH='.'
pytest tests -q
```

The backend test tree currently collects 360 tests. Coverage includes adapters, acquisition, blocked detection, JSON extraction, listing extraction, crawl service, review, normalizers, security, host memory, URL safety, dashboard, discovery, and worker recovery.

### 11.2 Acquire-Only Smoke Tests

```powershell
$env:PYTHONPATH='.'
python run_acquire_smoke.py api        # Adorama, Dice, SSENSE
python run_acquire_smoke.py commerce   # Arc'teryx, Adafruit, SparkFun
python run_acquire_smoke.py jobs       # Indeed, LinkedIn
python run_acquire_smoke.py hard       # Challenging sites
python run_acquire_smoke.py ats        # ATS platforms
python run_acquire_smoke.py specialist # Specialist retailers
```

Writes reports to `artifacts/acquisition_smoke/` and per-URL diagnostics to `artifacts/diagnostics/<run_id>/`.

### 11.3 Full Extraction Smoke Tests

```powershell
$env:PYTHONPATH='.'
python run_extraction_smoke.py
```

Tests 10 client URLs through complete extraction pipeline. Writes report to `artifacts/extraction_smoke/`.

---

## 12. Architecture Invariants

These MUST be preserved across all changes:

1. **No magic values in code** — All tunables in `data/knowledge_base/*.json`, loaded via `pipeline_config.py`
2. **Async-safe adapters** — HTTP calls use `asyncio.to_thread()` for sync libraries
3. **Verdict based on core fields only** — `_compute_verdict()` uses `VERDICT_CORE_FIELDS`, not requested fields
4. **Clean record API responses** — `data` strips empty/null/internal keys; `discovered_data` strips raw manifest containers
5. **Listing fallback guard** — 0 item records → `listing_detection_failed`, never detail-style fallback
6. **Review shows only actionable fields** — `discovered_fields` excludes container keys and empty values
7. **Pipeline config is single source of truth** — field aliases, collection keys, selectors, block signatures, etc.
8. **Preserve usable content over brittle heuristics** — Anti-bot signatures only block when page actually behaves like challenge
9. **HTTP pinning preserves TLS identity** — Original hostname URL preserved with DNS pinning
10. **Acquisition regressions diagnosable from artifacts** — HTML/JSON + per-URL diagnostics + smoke summaries
11. **Cookie reuse is policy-driven** — Only policy-approved cookies persisted via `cookie_policy.json`
12. **Diagnostics are observational** — Report only what actually happened, no fabricated causes
13. **JS-shell triggers Playwright** — Large HTML (>=200KB) + low text ratio (<2%) → Playwright escalation
14. **LLM calls fail fast** — No retry/backoff on 429 errors
15. **Dynamic field names pass quality gates** — Single-char keys, JSON-LD types, sentence-like labels filtered
16. **JSON-LD structural keys produce no candidates** — `@type`, `@context`, `@id`, `@graph` skipped before alias matching

---

## 13. Backlog Reference

All active backend bugs, refactors, and follow-up architecture work now live in [backend-pending-items.md](/C:/Projects/pre_poc_ai_crawler/docs/backend-pending-items.md). This architecture document is intended to describe the current implemented system, not to duplicate the backlog.
