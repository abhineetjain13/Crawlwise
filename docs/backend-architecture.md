# CrawlerAI Backend Architecture

> **Last Updated:** 2026-04-10
> **Stack:** Python 3.14+, FastAPI, SQLAlchemy 2.0 (async), Postgres, Redis, Celery, Playwright, curl_cffi
> **Test Status:** Active targeted suites green on 2026-04-10

---

## 1. System Overview

CrawlerAI is a deterministic web crawling pipeline that extracts structured data from ecommerce listing/detail pages and job boards. The backend runs as a FastAPI API layer backed by Postgres for durable persistence, Redis for shared ephemeral runtime state, and Celery workers for background run execution.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                  │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP + Session Cookie / Bearer Token
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │               7 API Route Modules                    │  │
│  │  auth | crawls | records | dashboard | jobs |       │  │
│  │  review | users                                      │  │
│  └──────────────────────────────────────────────────────┘  │
│                         │                                   │
│  ┌──────────────────────┴──────────────────────────────┐  │
│  │                 Service Layer                        │  │
│  │  crawl_service | auth_service | review_service      │  │
│  │  llm_service | dashboard_service | user_service     │  │
│  └──────────────────────┬──────────────────────────────┘  │
└─────────────────────────┼──────────────────────────────────┘
                          │ enqueue / control
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                     Redis + Celery                         │
│  Redis: broker + shared runtime state + pacing / events   │
│  Celery: durable background execution of `crawl.process_run`│
└─────────────────────────┬──────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    Celery Worker Processes                 │
│  `app/tasks.py` → `process_run(run_id)`                    │
│  Browser pool init/shutdown hooks per worker process       │
│  Executes: ACQUIRE → EXTRACT → UNIFY → PUBLISH             │
└─────────────────────────┬──────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  Postgres + Alembic                        │
│  Tables: users, crawl_runs, crawl_records, crawl_logs,    │
│          review_promotions, llm_configs, llm_cost_log     │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Structure

```
backend/
├── app/
│   ├── main.py                    # FastAPI app + lifespan startup/shutdown
│   ├── tasks.py                   # Celery task entrypoints
│   ├── api/                       # auth, users, dashboard, crawls, records, jobs, review
│   ├── core/                      # config, database, redis, celery_app, auth, telemetry
│   ├── models/                    # ORM models (users, crawls, records, logs, review, llm)
│   ├── schemas/                   # request/response schemas
│   └── services/
│       ├── crawl_service.py       # enqueue/pause/resume/kill run control
│       ├── _batch_runtime.py      # run execution orchestration
│       ├── crawl_events.py        # Redis-backed log/progress sampling helpers
│       ├── runtime_metrics.py     # Redis-backed runtime counters
│       ├── pipeline/              # pipeline core helpers
│       ├── acquisition/           # acquirer, browser client/runtime, blocked detection, pacing, HTTP
│       ├── extract/               # listing/detail/json extraction + source parsers
│       ├── adapters/              # platform/domain adapters
│       ├── review/                # review payload + persistence helpers
│       └── config/                # typed config modules
├── alembic/                       # migrations
├── tests/
├── run_acquire_smoke.py
├── run_extraction_smoke.py
└── pyproject.toml
```

---

## 3. Entry Points

### 3.1 FastAPI Application (`app/main.py`)

- Creates the FastAPI app with lifespan management
- Registers CORS middleware and correlation-id middleware
- Mounts 7 API routers under `/api`
- Validates cookie policy configuration at startup
- Bootstraps the admin user at startup
- Shuts down browser pools and Redis clients during app shutdown

### 3.2 Celery App (`app/core/celery_app.py`)

- Configures the `crawlerai` Celery app
- Uses `settings.redis_url` for both broker and result backend
- Includes `app.tasks`
- Enables `task_track_started`, `acks_late`, `reject_on_worker_lost`, and `worker_prefetch_multiplier=1`

### 3.3 Celery Task Worker (`app/tasks.py`)

- Exposes `crawl.process_run`
- Creates an async SQLAlchemy session per task and calls `_batch_runtime.process_run(session, run_id)`
- Initializes and tears down the Playwright browser pool per Celery worker process

### 3.4 Run Dispatch / Control (`app/services/crawl_service.py`)

- `dispatch_run()` allocates a Celery task id, stores it in `crawl_runs.result_summary`, and enqueues the task
- `pause_run()` and `kill_run()` revoke the active Celery task and persist the updated run state
- `resume_run()` transitions the run and re-enqueues it through Celery

---

## 4. Persistence and Runtime State

### 4.1 Durable Database

Durable state lives in Postgres through SQLAlchemy async sessions and Alembic migrations.

| Table | Model | Key Columns |
|-------|-------|-------------|
| `users` | `User` | id, email, hashed_password, role, is_active, token_version, created_at |
| `crawl_runs` | `CrawlRun` | id, user_id, run_type, url, status, surface, settings, requested_fields, result_summary, queue_owner, lease_expires_at, last_heartbeat_at, claim_count, last_claimed_at, completed_at |
| `crawl_records` | `CrawlRecord` | id, run_id, source_url, data, raw_data, discovered_data, source_trace, raw_html_path |
| `crawl_logs` | `CrawlLog` | id, run_id, level, message, created_at |
| `review_promotions` | `ReviewPromotion` | id, run_id, domain, surface, approved_schema, field_mapping, created_at |
| `llm_configs` | `LLMConfig` | id, provider, model, api_key_encrypted, task_type, budget fields, is_active |
| `llm_cost_log` | `LLMCostLog` | id, run_id, provider, model, task_type, token counts, cost_usd, domain, created_at |

### 4.2 Shared Ephemeral Runtime State

Redis is authoritative for shared, short-lived coordination state:

- Celery broker and result backend
- Host memory / acquisition preferences
- Crawl event sampling counters
- Runtime metrics counters
- Shared acquisition pacing and lock state

Redis-backed state is fail-open where appropriate for diagnostics and pacing helpers; Postgres remains the durable source of truth for runs, records, logs, and review state.

### 4.3 Migrations

Alembic tracks the schema history, including:

1. Initial schema
2. Auth/status invariants
3. Removal of selector/site-memory persistence from the active design
4. Durable queue lease fields on `crawl_runs`

The current schema is Postgres-oriented and uses `JSONB` for structured run and record payloads.

---

## 5. API Endpoints

### 5.1 Auth (`/api/auth`)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/register` | Public when enabled | Register new user |
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
| POST | `/api/review/{id}/selector-preview` | Authenticated | Selector preview compatibility endpoint |

### 5.5 Admin Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/dashboard` | Authenticated | Dashboard metrics |
| POST | `/api/dashboard/reset-data` | Admin | Reset application data |
| GET | `/api/jobs/active` | Authenticated | Active running jobs |
| GET/PATCH/DELETE | `/api/users/{id}` | Admin | User administration |

---

## 6. Crawl Pipeline

The pipeline follows: **ACQUIRE → EXTRACT → UNIFY → PUBLISH**

### 6.1 Dispatch Flow

```
POST /api/crawls
  │
  ├── Persist run in Postgres
  ├── Generate Celery task id
  ├── Save task id in result_summary
  └── Enqueue `crawl.process_run(run_id)` via Celery/Redis
```

### 6.2 ACQUIRE (`services/acquisition/`)

**Orchestrator:** `acquirer.py`

```
acquire(url, settings)
  │
  ├── Validate URL (url_safety.py: SSRF check, DNS resolution, public IP verify)
  ├── Check Redis-backed host memory (host_memory.py)
  │
  ├── Try curl_cffi first
  │   ├── DNS resolve → CurlOpt.RESOLVE for hostname pinning
  │   ├── Apply proxy rotation if configured
  │   ├── Apply platform/pacing policy
  │   └── Detect JSON response
  │
  ├── If blocked / JS-shell / unusable → Playwright fallback
  │   ├── browser_client.py: stealth context creation
  │   ├── Origin warming
  │   ├── Cookie consent dismissal
  │   ├── Network XHR/fetch interception
  │   ├── Interactive expansion
  │   └── Advanced modes: scroll, paginate, load_more
  │
  └── Return AcquisitionResult(html/json, network_payloads, diagnostics)
```

**Key invariants:**
- `curl_cffi` is the default acquisition path; Playwright is escalation/fallback
- DNS pinning uses `CurlOpt.RESOLVE`, never raw-IP URL rewrites
- Redis-backed pacing/host-memory state must not become authority for rewriting user crawl controls
- Diagnostics persist alongside HTML/JSON artifacts

### 6.3 EXTRACT (`services/extract/`)

#### Listing Extraction (`listing_extractor.py`)

Ordered strategy:

1. JSON-LD item lists / Product arrays
2. Embedded app state (`__NEXT_DATA__`)
3. Hydrated state objects (`__NUXT__`, `__APOLLO_STATE__`, etc.)
4. Intercepted network payloads
5. DOM card detection

0 real item-level records results in `listing_detection_failed`; listing pages never downgrade to detail-style single-record fallback.

#### Detail Extraction (`service.py`)

Field resolution is strict first-match:

1. Adapter
2. XHR/JSON payload
3. JSON-LD
4. Hydrated state
5. DOM selector defaults
6. LLM fallback

#### JSON Extraction (`json_extractor.py`)

- First-class JSON API extraction
- Collection-key and GraphQL edge/node discovery
- Falls back to preserving scalar fields under original keys

### 6.4 UNIFY → PUBLISH

```
unify(records, manifest, requested_fields)
  │
  ├── Strip empty/null/internal fields from API-facing payloads
  ├── Build source_trace summaries
  ├── Compute extraction_verdict
  ├── Map verdict to run status
  └── Persist runs/records/logs to Postgres
```

---

## 7. Adapter Registry

**Registry:** `services/adapters/registry.py`

Resolution order:

1. Domain-matched adapters
2. Signal-based adapters (Shopify)

Implemented adapters currently include:

- Amazon
- Walmart
- eBay
- ADP
- Greenhouse
- iCIMS
- Indeed
- Jibe
- LinkedIn Jobs
- Oracle HCM
- Paycom
- RemoteOK
- Remotive
- SaaShr
- Shopify

Blocked-page recovery currently includes Shopify public endpoint fallback.

---

## 8. Configuration Model

All tunables are loaded via typed config modules and surfaced through `services/pipeline_config.py`. Service code should import through `pipeline_config.py`, not duplicate configuration values.

| File | Contents |
|------|----------|
| `config/extraction_rules.py` | Pipeline tuning, field rules, platform families, browser-first family policy |
| `config/block_signatures.py` | WAF/challenge signatures |
| `config/selectors.py` | Card, pagination, consent, and readiness selectors |
| `config/field_mappings.py` | Canonical schemas, aliases, collection keys |

Policy stance:

- Generic crawler paths must not contain tenant/site hardcoded hacks
- Family-level platform policy is allowed where required
- Browser-first behavior is family-driven, not host-literal in service code

---

## 9. Design Patterns

| Pattern | Where |
|---------|-------|
| **Waterfall Acquisition** | `curl_cffi` → Playwright escalation |
| **Strategy Pattern** | Platform adapters via `BaseAdapter` |
| **Source-Ranked Extraction** | Deterministic first-match field resolution |
| **Config-Driven Policy** | Typed config modules via `pipeline_config.py` |
| **Task Queue Dispatch** | Celery task enqueue + revoke for run control |
| **Fail-Closed URL Safety** | DNS failure → reject |
| **Policy-Driven Cookies** | Domain policy allowlists + filtered persistence |
| **Redis Shared State** | Pacing, host memory, event counters, runtime metrics |

---

## 10. Authentication & Authorization

- Password hashing via `pbkdf2_sha256`
- JWT auth with `token_version`-based revocation
- Session cookie or bearer token accepted
- Bootstrap admin from environment at startup
- `require_admin` guards admin-only endpoints
- Public registration is disabled by default unless `REGISTRATION_ENABLED=true`

---

## 11. Testing

### 11.1 Unit/Integration Tests

```powershell
$env:PYTHONPATH='.'
pytest tests -q
```

Use the current `pytest` collection as the source of truth for exact test counts. Coverage includes acquisition, extraction, adapters, crawl service, Celery dispatch integration, Redis-backed runtime helpers, review flows, security, and worker/process lifecycle behavior.

### 11.2 Acquire-Only Smoke Tests

```powershell
$env:PYTHONPATH='.'
python run_acquire_smoke.py api
python run_acquire_smoke.py commerce
python run_acquire_smoke.py jobs
python run_acquire_smoke.py hard
python run_acquire_smoke.py ats
python run_acquire_smoke.py specialist
```

### 11.3 Full Extraction Smoke Tests

```powershell
$env:PYTHONPATH='.'
python run_extraction_smoke.py
```

---

## 12. Architecture Invariants

These MUST be preserved across all changes:

1. **No magic values in service code** — shared tunables live in typed config modules behind `pipeline_config.py`
2. **Async-safe adapters** — sync HTTP clients in async paths must use `asyncio.to_thread()`
3. **Verdict based on core fields only** — requested field coverage is metadata, not verdict input
4. **Clean record API responses** — `data` strips empty/null/internal keys; `discovered_data` strips raw containers
5. **Listing fallback guard** — listing pages with 0 item records yield `listing_detection_failed`
6. **Review shows only actionable fields** — no container keys or empty values in review payloads
7. **Postgres is the durable source of truth** — runs, logs, records, review state, and LLM config/cost data persist in Postgres
8. **Redis is shared ephemeral state only** — broker/runtime coordination may live in Redis; durable business state must not
9. **Celery owns background run execution** — FastAPI enqueues and controls runs, workers execute them
10. **Preserve usable content over brittle anti-bot heuristics** — vendor markers alone are not enough to classify a block
11. **HTTP pinning preserves TLS identity** — preserve hostname when pinning DNS
12. **Acquisition regressions must be diagnosable from artifacts** — successful acquires emit artifacts and machine-readable diagnostics
13. **Cookie reuse is policy-driven** — only policy-approved cookies persist; challenge cookies stay deny-by-default
14. **Diagnostics are observational** — report what happened; do not fabricate causes
15. **User-owned crawl controls are never rewritten by the backend** — no silent mode or proxy policy mutation
16. **Field extraction is first-match, not score-based** — adapter → payload → JSON-LD → hydrated state → DOM → LLM fallback
17. **Playwright expansion is generic, not field-routed** — requested fields must not determine click plans
18. **Deleted subsystems stay deleted** — do not reintroduce selector CRUD, site memory persistence, or runtime-editable per-domain extraction logic
19. **LLM calls fail fast on 429** — no retry/backoff sleep loops on rate limits
20. **Generic crawler paths stay generic** — no tenant/site hacks in production acquisition or extraction paths

---

## 13. Backlog Reference

All active backend bugs, refactors, and follow-up architecture work live in [backend-pending-items.md](/C:/Projects/pre_poc_ai_crawler/docs/backend-pending-items.md). This document describes the current implemented backend, not future backlog items.
