# CrawlerAI Codebase Map

> **For agents:** Read this instead of exploring the filesystem.
> Every significant file is listed here with its bucket and one-line purpose.
> If a file is not listed, it is a utility/helper inside an already-listed module.

---

## Backend Root: `backend/app/`

### `api/` — Route handlers only. No business logic.

| File | Purpose |
|------|---------|
| `crawls.py` | Create runs, CSV ingestion, pause/resume/kill, commit fields/LLM, logs, websocket |
| `records.py` | List records, JSON/CSV/MD/artifact/discoverist exports, provenance |
| `review.py` | Review payload, artifact HTML, save approved mapping |
| `selectors.py` | Selector CRUD, suggest, test, preview-html |
| `llm.py` | Provider catalog, config CRUD, connection test, cost log |
| `auth.py` | Login (JWT + httpOnly cookie), register, `/me` |
| `users.py`, `dashboard.py`, `jobs.py`, `health.py`, `metrics.py` | As named |

### `core/` — App infrastructure only. No business logic.

| File | Purpose |
|------|---------|
| `config.py` | Pydantic settings from `.env` |
| `database.py` | Async SQLAlchemy engine + session factory |
| `redis.py` | Shared Redis connection |
| `security.py` | JWT create/decode, PBKDF2 password hashing, Fernet encryption |
| `dependencies.py` | `get_current_user()` FastAPI dependency |
| `telemetry.py`, `metrics.py` | Observability |

### `models/` — SQLAlchemy ORM entities

| Model | File | Key Fields |
|-------|------|-----------|
| `User` | `user.py` | id, email, role, token_version |
| `CrawlRun` | `crawl.py` | id, user_id, run_type, status, surface, settings JSONB, result_summary JSONB |
| `CrawlRecord` | `crawl.py` | id, run_id, source_url, data JSONB, raw_data JSONB, source_trace JSONB |
| `CrawlLog` | `crawl.py` | id, run_id, level, message |
| `DomainMemory` | `crawl.py` | domain, surface, selectors JSONB — scoped by `(domain, surface)` |
| `ReviewPromotion` | `crawl.py` | run_id, domain, surface, approved_schema JSONB |
| `LLMConfig` | `llm.py` | provider, model, task_type, api_key_encrypted, budgets |
| `LLMCostLog` | `llm.py` | provider, run_id, input_tokens, cost_usd |

### `schemas/` — Pydantic DTOs (request/response shapes, not ORM models)

`crawl.py`, `user.py`, `llm.py`, `selectors.py`, `common.py`

---

## Bucket 2: Crawl Ingestion + Orchestration

| File | Purpose |
|------|---------|
| `crawl_ingestion_service.py` | Validates + normalizes `CrawlCreate` payload, stamps run snapshots |
| `crawl_service.py` | `dispatch_run()` — Celery vs local asyncio decision point |
| `crawl_crud.py` | DB operations: `create_crawl_run()`, status transitions |
| `crawl_events.py` | WebSocket log emission |
| `_batch_runtime.py` | URL processing loop, progress state, pause/kill signal checks |
| `tasks.py` | Celery task entry: `process_run_async()` → `_run_task_in_worker_loop()` |
| `pipeline/core.py` | `_process_single_url()` — orchestrates acquire → extract → normalize → persist |
| `pipeline/persistence.py` | `CrawlRecord` writes, deduplication via identity key, run summary updates |
| `pipeline/runtime_helpers.py` | Typed helpers called from `core.py` — robots, fetch, extract, persist stages |
| `pipeline/types.py` | Pipeline-internal typed objects |

**Crawl flow:**
```
POST /api/crawls → crawl_ingestion_service → crawl_crud.create_crawl_run
→ crawl_service.dispatch_run → tasks.process_run_async
→ _batch_runtime.process_run (URL loop) → pipeline/core._process_single_url
→ [acquire] → [extract] → [normalize] → [persist]
```

---

## Bucket 3: Acquisition + Browser Runtime

| File | Purpose |
|------|---------|
| `acquisition/acquirer.py` | Main acquisition entry: `acquire(request)` — platform URL normalization + policy |
| `acquisition/runtime.py` | Shared HTTP client pool keyed on `(proxy, address-family, force_ipv4)` |
| `acquisition/http_client.py` | Thin adapter over `runtime.get_shared_http_client()` |
| `acquisition/browser_runtime.py` | `SharedBrowserRuntime` pool, semaphore-limited Playwright contexts |
| `acquisition/browser_capture.py` | Screenshot temp-file staging, network payload interception |
| `acquisition/browser_identity.py` | `browserforge`-backed fingerprint generation (host-OS-locked) |
| `acquisition/browser_page_flow.py` | `navigate_browser_page_impl()` + readiness probing |
| `acquisition/browser_readiness.py` | DOM readiness probe (selectors, network-idle, load events) |
| `acquisition/traversal.py` | Listing pagination + load-more: bounded per-step snapshots |
| `acquisition/pacing.py` | Host-level rate limiting state |
| `acquisition/cookie_store.py` | Cookie policy enforcement |
| `crawl_fetch_runtime.py` | `fetch_page()` — the HTTP/browser decision, escalation, block detection |
| `robots_policy.py` | robots.txt fetch, parse, allow/disallow checks |
| `url_safety.py` | SSRF + public-target validation |

**Import rule:** `fetch_page` is imported from `crawl_fetch_runtime` directly. The legacy trampoline in `acquisition/runtime.py` is removed.

**Block detection:** Vendor response headers (`DataDome`, `Cloudflare`, `Akamai`, `PerimeterX`, `Sucuri`) short-circuit to browser. HTML heuristics catch vendor-silent blocks. `401` → auth wall (no escalation). `403`/`429` → escalate.

---

## Bucket 4: Extraction

| File | Purpose |
|------|---------|
| `crawl_engine.py` | Extraction facade — routes listing vs detail, runs adapters |
| `detail_extractor.py` | Detail page extraction (product/job/auto detail) |
| `listing_extractor.py` | Listing page extraction |
| `structured_sources.py` | JSON-LD, microdata (extruct), Open Graph, Nuxt `__NUXT_DATA__`, harvested JS state |
| `js_state_mapper.py` | JMESPath-backed JS state → field mapping |
| `network_payload_mapper.py` | Declarative network payload → field mapping (specs in `config/network_payload_specs.py`) |
| `field_value_core.py` | Type coercion per field (price, date, URL, image, text), canonical field mapping |
| `field_value_*.py` | Per-field normalization helpers |
| `field_policy.py` | `canonical_fields_for_surface()` — field eligibility rules per surface |
| `adapters/registry.py` | `registered_adapters()` — adapter resolution + `can_handle()` dispatch |
| `adapters/[platform].py` | Per-platform extractors: amazon, ebay, shopify, greenhouse, workday, linkedin, etc. |
| `extract/*` | Extraction utilities (called from extractor files) |

**Extraction priority order:**
1. Adapter match (platform-specific)
2. JSON-LD / Microdata (extruct)
3. Schema.org parsing
4. Selector rules (domain memory)
5. LLM extraction fallback (if enabled + budget)
6. Generic DOM heuristics

**Config lives here:**
| File | Contains |
|------|---------|
| `config/field_mappings.py` | All field aliases — one place, all surfaces |
| `config/selectors.py` | DOM selector config |
| `config/platforms.json` | Adapter registry metadata, network signatures, JS-state mappings, listing-readiness selectors |
| `config/network_payload_specs.py` | Declarative network payload specs and canonical endpoint path tokens for payload mapping/capture |

---

## Bucket 5: Publish + Persistence

| File | Purpose |
|------|---------|
| `publish/verdict.py` | Per-URL verdict: `success / partial / blocked / listing_detection_failed / empty` |
| `publish/metrics.py` | Acquisition + URL metrics |
| `publish/metadata.py` | Field-discovery metadata builder |
| `artifact_store.py` | HTML artifact I/O — reads/writes off the async hot path |
| `pipeline/persistence.py` | (also in Bucket 2) — `CrawlRecord` persistence, deduplication |

**Verdict rules:**
- records + not blocked → `success`
- records + blocked → `partial`
- blocked + no records → `blocked`
- listing + no records → `listing_detection_failed`
- detail + no records → `empty`

---

## Bucket 6: Review + Selectors + Domain Memory

| File | Purpose |
|------|---------|
| `review/__init__.py` | Build review payloads, save approved field mappings via `ReviewPromotion` |
| `selectors_runtime.py` | Selector CRUD + runtime lookup — loads `DomainMemory` by `(domain, surface)` |
| `selector_self_heal.py` | Synthesis + validation loop — only persists selectors that improve targeted fields |
| `domain_memory_service.py` | `load_domain_memory()`, `create_domain_memory()` — DB operations for `DomainMemory` |

**Selector lifecycle:** load domain memory → apply to extraction → if fields missing: self-heal → validate improvement → persist only if better → reuse on next run before re-synthesizing.

---

## Bucket 7: LLM Admin + Runtime

| File | Purpose |
|------|---------|
| `llm_runtime.py` | `extract_missing_fields()` — pipeline LLM entry point |
| `llm_provider_client.py` | Anthropic / Groq / NVIDIA HTTP clients |
| `llm_config_service.py` | Config CRUD, API key encryption/decryption |
| `llm_cache.py` | Redis-backed response deduplication (`build_llm_cache_key`) |
| `llm_circuit_breaker.py` | Error classification — prevents cascade cost failures |
| `llm_tasks.py` | `call_provider_with_retry()` — provider retry logic |
| `llm_types.py` | LLM-internal types |

---

## Frontend Root: `frontend/`

| Path | Purpose |
|------|---------|
| `app/` | Next.js App Router pages: `/login`, `/dashboard`, `/crawl`, `/runs/[run_id]`, `/selectors`, `/selectors/manage`, `/admin/*` |
| `components/layout/` | App shell, auth session, nav, theme |
| `components/crawl/crawl-config-screen.tsx` | Crawl configuration + dispatch |
| `components/crawl/crawl-run-screen.tsx` | Run workspace, record display, pause/kill/export |
| `components/crawl/use-run-polling.ts` | Run state polling |
| `lib/api/client.ts` | Auth-aware fetch wrapper |
| `lib/api/index.ts` | **ALL** backend HTTP calls live here — the only API access layer |
| `lib/api/types.ts` | All frontend-facing types — update here when backend contracts change |

**Known drift:** `previewSelectors()` in `index.ts` calls `/api/review/{id}/selector-preview` which does not exist in the backend.

---

## What To Never Do (Quick Reference)

- Put config in service code → use `services/config/*`
- Fix extraction downstream → fix upstream in the extractor or config
- Create a `_helpers.py`, `_utils.py`, `_misc.py` → find the owning bucket file
- Hardcode a platform name in a generic path → use `adapters/` or `config/platforms.json`
- Import private functions from service internals in tests → test public APIs only
- Leave re-export stubs after a migration → delete the old location entirely

Full anti-pattern list: `docs/ENGINEERING_STRATEGY.md` → Anti-Patterns section.
