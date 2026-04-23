# CrawlerAI Codebase Map

Use this doc for ownership and file location. Do not filesystem-wander first.
If a file is not listed, assume it is a helper under a listed owner.

---

## Backend Root: `backend/app/`

### Support files outside `backend/app/`

| File | Purpose |
|---|---|
| `run_test_sites_acceptance.py` | Acceptance runner for curated test-site batches |
| `harness_support.py` | Acceptance helpers, explicit-surface handling, audit shaping |
| `test_site_sets/commerce_browser_heavy.json` | Commerce acceptance manifest and quality expectations |

### `api/` — route handlers only

| File | Purpose |
|---|---|
| `crawls.py` | Run creation, CSV ingestion, run control, logs, domain recipe/profile/feedback/cookie-memory routes |
| `records.py` | Record listing, exports, provenance |
| `review.py` | Review payloads and approved mapping save |
| `selectors.py` | Selector CRUD, suggest, test, preview |
| `llm.py` | LLM provider catalog, config, connection test, cost log |
| `auth.py` | Login, register, `/me` |
| `users.py`, `dashboard.py`, `jobs.py`, `health.py`, `metrics.py` | Named route modules |

### `core/` — infrastructure only

| File | Purpose |
|---|---|
| `config.py` | Pydantic settings from `.env` |
| `database.py` | Async SQLAlchemy engine and session factory |
| `redis.py` | Shared Redis connection |
| `security.py` | JWT, password hashing, encryption |
| `dependencies.py` | FastAPI auth dependency helpers |
| `telemetry.py`, `metrics.py` | Observability |

### `models/` — ORM entities

| Model | File | Purpose |
|---|---|---|
| `User` | `user.py` | account, role, token version |
| `CrawlRun` | `crawl.py` | run state, surface, settings, summary |
| `CrawlRecord` | `crawl.py` | extracted record payload and provenance |
| `CrawlLog` | `crawl.py` | run logs |
| `DomainMemory` | `crawl.py` | selector memory scoped by `(domain, surface)` |
| `DomainRunProfile` | `crawl.py` | reusable execution defaults scoped by `(domain, surface)` |
| `DomainCookieMemory` | `crawl.py` | reusable browser state scoped by domain |
| `DomainFieldFeedback` | `crawl.py` | per-field keep/reject learning history |
| `ReviewPromotion` | `crawl.py` | approved review schema snapshot |
| `LLMConfig`, `LLMCostLog` | `llm.py` | LLM config and cost tracking |

### `schemas/` — request and response DTOs

`crawl.py`, `user.py`, `llm.py`, `selectors.py`, `common.py`

---

## Bucket 2: Crawl Ingestion + Orchestration

| File | Purpose |
|---|---|
| `crawl_ingestion_service.py` | Validate and normalize `CrawlCreate`, stamp run snapshots |
| `crawl_service.py` | `dispatch_run()` entry |
| `crawl_crud.py` | DB create and state transitions |
| `domain_run_profile_service.py` | Load/save reusable execution defaults |
| `crawl_events.py` | WebSocket log emission |
| `_batch_runtime.py` | URL loop, progress, pause, kill checks |
| `tasks.py` | Celery task entry |
| `pipeline/core.py` | Per-URL orchestration: acquire -> extract -> normalize -> persist |
| `pipeline/persistence.py` | `CrawlRecord` writes, dedupe, summaries |
| `pipeline/runtime_helpers.py` | Typed stage helpers |
| `pipeline/types.py` | Pipeline typed objects |

Flow:
`POST /api/crawls -> crawl_ingestion_service -> crawl_crud -> crawl_service -> tasks/_batch_runtime -> pipeline/core`

---

## Bucket 3: Acquisition + Browser Runtime

| File | Purpose |
|---|---|
| `acquisition/acquirer.py` | Main acquisition entry and policy |
| `acquisition/runtime.py` | Shared HTTP client pool |
| `acquisition/http_client.py` | Thin shared-client wrapper |
| `acquisition/browser_runtime.py` | Shared Playwright runtime and limits |
| `acquisition/browser_capture.py` | Screenshots and network payload capture |
| `acquisition/browser_identity.py` | Browser fingerprint generation |
| `acquisition/browser_page_flow.py` | Page navigation and readiness probing |
| `acquisition/browser_readiness.py` | DOM readiness checks |
| `acquisition/traversal.py` | Listing pagination and load-more |
| `acquisition/pacing.py` | Host-level rate limiting |
| `acquisition/cookie_store.py` | Temp storage state plus domain cookie memory helpers |
| `crawl_fetch_runtime.py` | `fetch_page()` owner: HTTP/browser decision, escalation, block detection |
| `robots_policy.py` | robots.txt policy |
| `url_safety.py` | SSRF and public-target validation |

Import rule: import `fetch_page` from `crawl_fetch_runtime.py` directly.

---

## Bucket 4: Extraction

| File | Purpose |
|---|---|
| `crawl_engine.py` | Extraction facade and routing |
| `detail_extractor.py` | Detail-page extraction |
| `listing_extractor.py` | Listing-page extraction |
| `structured_sources.py` | JSON-LD, microdata, OG, Nuxt, harvested JS state |
| `js_state_mapper.py` | JS state to field mapping |
| `network_payload_mapper.py` | Network payload to field mapping |
| `field_value_core.py` | Canonical field coercion |
| `field_value_*.py` | Per-field normalization helpers |
| `field_policy.py` | Field eligibility by surface |
| `adapters/registry.py` | Adapter resolution |
| `adapters/[platform].py` | Platform-specific extraction |
| `extract/listing_card_fragments.py` | Canonical listing-fragment discovery shared by traversal, browser artifact capture, and listing extraction |
| `extract/listing_candidate_ranking.py` | Shared candidate-set ranking and utility filtering for listing rows |
| `extract/*` | Other extraction helpers |

Canonical config owners:

| File | Purpose |
|---|---|
| `config/field_mappings.py` | field aliases |
| `config/selectors.py` | DOM selectors |
| `config/platforms.json` | adapter metadata, signatures, JS mappings, readiness selectors |
| `config/network_payload_specs.py` | payload specs and endpoint tokens |

---

## Bucket 5: Publish + Persistence

| File | Purpose |
|---|---|
| `publish/verdict.py` | URL verdicts |
| `publish/metrics.py` | acquisition and URL metrics |
| `publish/metadata.py` | field-discovery metadata |
| `artifact_store.py` | HTML artifact I/O |
| `pipeline/persistence.py` | persistence owner shared with Bucket 2 |

Verdict set:
`success`, `partial`, `blocked`, `listing_detection_failed`, `empty`

---

## Bucket 6: Review + Selectors + Domain Memory

| File | Purpose |
|---|---|
| `review/__init__.py` | Review payloads and approved field mapping persistence |
| `selectors_runtime.py` | Selector CRUD and runtime lookup |
| `selector_self_heal.py` | Selector synthesis and validation |
| `domain_memory_service.py` | Domain memory load/save |

All selector memory is scoped by normalized `(domain, surface)`.

---

## Bucket 7: LLM Admin + Runtime

| File | Purpose |
|---|---|
| `llm_runtime.py` | Pipeline LLM entry |
| `llm_provider_client.py` | Provider HTTP clients |
| `llm_config_service.py` | Config CRUD and key encryption |
| `llm_cache.py` | Redis-backed response dedupe |
| `llm_circuit_breaker.py` | Error classification and cost protection |
| `llm_tasks.py` | Provider retry logic |
| `llm_types.py` | LLM-internal types |

---

## Frontend Root: `frontend/`

| Path | Purpose |
|---|---|
| `app/` | Next.js App Router pages |
| `components/layout/` | shell, auth, nav, theme |
| `components/crawl/crawl-config-screen.tsx` | Crawl Studio form and dispatch |
| `components/crawl/crawl-run-screen.tsx` | Run workspace and Domain Recipe workflow |
| `components/crawl/use-run-polling.ts` | run polling |
| `lib/api/client.ts` | auth-aware fetch wrapper |
| `lib/api/index.ts` | only frontend backend-access layer |
| `lib/api/types.ts` | frontend API types |

---

## Quick Guardrails

- Config belongs in `services/config/*`
- Fix extraction upstream, not in publish or persistence
- Do not create `_helpers.py`, `_utils.py`, or compat stubs
- Do not hardcode platforms in generic paths
- Test public behavior, not private internals

See `docs/ENGINEERING_STRATEGY.md` for the full anti-pattern list.
