# CLAUDE.md

## Purpose

CrawlerAI is a deterministic crawl, extraction, review, and export system for ecommerce, jobs, automobiles, and tabular targets.

- `backend/`: FastAPI + Postgres + Redis + Celery + Playwright
- `frontend/`: Next.js operator UI
- `docs/`: architecture, invariants, strategy, setup, and feature notes

Read this file first. It is the short operating guide for humans and coding agents.

## Canonical Docs

- [Backend Architecture](docs/backend-architecture.md): live backend structure, routes, flows, storage, implemented features
- [Frontend Architecture](docs/frontend-architecture.md): live frontend structure, route map, API usage, known drift
- [Engineering Strategy](docs/ENGINEERING_STRATEGY.md): engineering principles, constraints, module ownership, workflow
- [Invariants](docs/INVARIANTS.md): must-preserve runtime and behavior rules
- [Environment Bootstrap](docs/environment-bootstrap.md): local setup and environment rules

## Repo Shape

Primary backend responsibilities:

1. API/auth
2. crawl ingestion and orchestration
3. acquisition and browser runtime
4. extraction
5. publish and persistence
6. review, selectors, and domain memory
7. LLM config/runtime

Primary frontend responsibilities:

1. auth/session shell
2. crawl configuration
3. run workspace
4. selectors tool
5. dashboard/history/jobs
6. admin users + LLM config

Core backend path:

```text
submit crawl -> persist run -> dispatch worker -> process each URL
-> acquire page/artifacts/diagnostics -> extract records
-> optional selector self-heal / optional LLM assistance
-> publish verdict + metrics + provenance -> persist records and summary
```

## Repo Facts That Matter

- Per-URL execution lives in `backend/app/services/pipeline/core.py`.
- Artifact and `CrawlRecord` persistence live in `backend/app/services/pipeline/persistence.py`.
- Fetch/runtime behavior lives mainly in `backend/app/services/crawl_fetch_runtime.py`.
- Extraction facade is `backend/app/services/crawl_engine.py`.
- Domain memory is live and stores selector rules by normalized `(domain, surface)`.
- Selector self-heal should reuse validated domain memory before attempting another synthesis pass.
- Selectors API is live at `/api/selectors`.
- LLM admin API is live at `/api/llm`.
- Record provenance API is live at `/api/records/{record_id}/provenance`.
- Review artifact HTML is live at `/api/review/{run_id}/artifact-html`.
- Browser escalation and traversal are different decisions.
- Runtime knobs belong in `backend/app/services/config/*`.

## Agent Rules

These are repo-specific coding rules. Follow them unless the user explicitly asks for something else.

1. Preserve explicit ownership. Put code in the existing subsystem that already owns the behavior.
2. Prefer deletion over abstraction. If two layers say the same thing, collapse them.
3. Do not create new cross-cutting “manager”, “registry”, or “helper” layers unless the repo already uses that pattern for the same concern.
4. Keep crawl/runtime behavior explicit and traceable. Hidden side effects are worse than duplicated conditionals.
5. Do not add site-specific hacks to generic paths when an adapter or config-owned slot exists.
6. Treat docs as code. If behavior changes, update the canonical doc instead of leaving stale prose behind.
7. Prefer targeted tests that defend contracts and invariants over tests that freeze implementation trivia.

## User-Control and Runtime Contracts

- User-selected crawl controls are authoritative. Do not silently rewrite `surface`, traversal intent, proxy selection, or `llm_enabled`.
- Browser escalation is allowed for rendering and anti-bot recovery. Traversal only runs when settings authorize it.
- Acquisition diagnostics are observational. Do not invent blocker causes after the fact.
- Listing runs with zero records are failures, not detail fallbacks.
- Stored `record.data` must stay clean: populated logical fields only.
- Run snapshots matter: `llm_config_snapshot` and `extraction_runtime_snapshot` should keep behavior stable within a run.

## Current Crawl Contract

`CrawlCreate` accepts:

- `run_type`: `crawl | batch | csv`
- `url` or `urls`
- `surface`: `ecommerce_listing | ecommerce_detail | job_listing | job_detail | automobile_listing | automobile_detail | tabular`
- `settings`
- `additional_fields`

Important settings in current use:

- `proxy_list`
- `advanced_enabled`
- `advanced_mode` / resolved `traversal_mode`
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

## Implemented Recent Features

These landed recently and should be assumed live unless code says otherwise:

- extruct-backed microdata and Open Graph structured-source support
- Nuxt `__NUXT_DATA__` revival in structured-source harvesting
- declarative network payload specs for generic job/ecommerce detail mapping
- declarative JMESPath-backed JS state mappings for ecommerce detail extraction
- bounded browser network-payload capture and temp-file screenshot staging
- browser-captured visual listing geometry fallback for flattened listing grids
- browser identity generation via `browserforge`
- URL tracking-parameter stripping in field-value normalization
- selector self-heal with domain-memory persistence/reuse
- review bucket and provenance-aware record responses
- selector CRUD/suggest/test/preview UI + API
- LLM provider catalog, config CRUD, connection test, and cost log

## Known Drift / Watchouts

- `frontend/lib/api/index.ts` still exposes `previewSelectors()` for `/api/review/{id}/selector-preview`, but that backend route is not present.
- Audit docs contain both valid constraints and stale claims; verify against code before acting on them.
- `ENGINEERING_STRATEGY.md` is the engineering constraints doc, not a place for full architecture duplication.
- `backend-architecture.md` is the detailed system map. Keep `CLAUDE.md` short.

## Where To Look

- crawl submission / dispatch: `backend/app/api/crawls.py`, `backend/app/services/crawl_ingestion_service.py`, `backend/app/services/crawl_service.py`
- pipeline orchestration: `backend/app/services/pipeline/core.py`
- fetch/runtime: `backend/app/services/crawl_fetch_runtime.py`
- extraction: `backend/app/services/crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`
- structured sources: `structured_sources.py`, `js_state_mapper.py`, `network_payload_mapper.py`
- publish/verdict: `backend/app/services/publish/*`
- review/selectors/memory: `backend/app/services/review/__init__.py`, `selectors_runtime.py`, `selector_self_heal.py`, `domain_memory_service.py`
- frontend API layer: `frontend/lib/api/index.ts`, `frontend/lib/api/types.ts`
- run workspace UI: `frontend/components/crawl/crawl-run-screen.tsx`

## Development Commands

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Useful focused slices:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py -q
.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_fetch_runtime.py -q
.\.venv\Scripts\python.exe -m pytest tests/services/test_selector_pipeline_integration.py -q
.\.venv\Scripts\python.exe -m pytest tests/services/test_selectors_api.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_harness_support.py -q
```

## Documentation Rules

- Keep this file under 200 lines.
- Put engineering constraints in [docs/ENGINEERING_STRATEGY.md](docs/ENGINEERING_STRATEGY.md).
- Put backend detail in [docs/backend-architecture.md](docs/backend-architecture.md).
- Put frontend detail in [docs/frontend-architecture.md](docs/frontend-architecture.md).
- Put must-preserve behavior in [docs/INVARIANTS.md](docs/INVARIANTS.md).
- If two docs repeat the same material, merge them and leave one canonical source.
