# CLAUDE.md — CrawlerAI Session Bootstrap

> **This is the only file you need to attach at the start of every session.**
> Read it fully before writing any code or asking clarifying questions.

---

## What CrawlerAI Is

CrawlerAI is a deterministic crawl, extraction, review, and export system for ecommerce,
jobs, automobiles, and tabular targets. The backend is FastAPI + PostgreSQL + Redis +
Celery + Playwright. Frontend is Next.js. Extraction is adapter → structured-source →
DOM-first; LLM is opt-in normalization only, never the primary extraction mechanism.

---

## Read Order — Do This Before Writing Code

| Step | File | Why |
|------|------|-----|
| 1 | `docs/CODEBASE_MAP.md` | Tells you where every file lives and which bucket owns it |
| 2 | `docs/ENGINEERING_STRATEGY.md` | Tells you the anti-patterns you must not introduce |
| 3 | `docs/INVARIANTS.md` | Tells you the runtime contracts you must not break |
| 4 | `docs/agent/SKILLS.md` | Look up the recipe for your current task before starting |
| 5 | `docs/plans/ACTIVE.md` | Check if there is an active plan pointer; if yes, open the linked plan file and work from that document |

For backend detail: `docs/backend-architecture.md`
For frontend detail: `docs/frontend-architecture.md`
For local setup: `docs/environment-bootstrap.md`
For creating/managing plans: `docs/agent/PLAN_PROTOCOL.md`

---

## Ownership Buckets — Every File Has One Home

| # | Bucket | Primary Files |
|---|--------|---------------|
| 1 | API + Bootstrap | `app/main.py`, `app/api/*`, `app/core/*` |
| 2 | Crawl Ingestion + Orchestration | `crawl_ingestion_service.py`, `crawl_service.py`, `crawl_crud.py`, `_batch_runtime.py`, `pipeline/*` |
| 3 | Acquisition + Browser Runtime | `acquisition/*`, `crawl_fetch_runtime.py`, `robots_policy.py`, `url_safety.py` |
| 4 | Extraction | `crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`, `structured_sources.py`, `js_state_mapper.py`, `network_payload_mapper.py`, `adapters/*`, `extract/*` |
| 5 | Publish + Persistence | `publish/*`, `artifact_store.py`, `pipeline/persistence.py` |
| 6 | Review + Selectors + Domain Memory | `review/__init__.py`, `selectors_runtime.py`, `selector_self_heal.py`, `domain_memory_service.py` |
| 7 | LLM Admin + Runtime | `llm_runtime.py`, `llm_provider_client.py`, `llm_config_service.py`, `llm_cache.py`, `llm_circuit_breaker.py`, `llm_tasks.py` |

Config tunables for all buckets → `app/services/config/*`

**If new code does not clearly belong to one bucket, stop and decide before writing.**

---

## Session Rules — Non-Negotiable

1. **Read `docs/CODEBASE_MAP.md` before exploring the filesystem.** It already tells you where things live.
2. **Check `docs/plans/ACTIVE.md`** before starting implementation. Use it as the pointer, then open the actual plan file and follow the workflow in `docs/agent/PLAN_PROTOCOL.md`.
3. **Do not create new files** without confirming no existing file already owns that concern.
4. **Do not add config inside service code.** Tunables belong in `app/services/config/*`.
5. **Fix extraction bugs upstream**, not with downstream compensating logic.
6. **After completing a major slice**, update the relevant canonical doc and mark the slice done in the plan file.
7. **Run tests before declaring any slice done**: see test commands in `docs/agent/SKILLS.md`.

---

## Key Runtime Facts

- Per-URL execution: `pipeline/core.py`
- Fetch behavior: `crawl_fetch_runtime.py` (import `fetch_page` from here directly)
- Extraction facade: `crawl_engine.py`
- Field aliases + mappings: `services/config/field_mappings.py` (one place, all surfaces)
- Platform adapter registry: `services/adapters/registry.py` + `config/platforms.json`
- Domain memory scoped by `(domain, surface)` — never global
- Listing with zero records → `listing_detection_failed`, never a detail fallback
- LLM use is opt-in per run. It must not activate silently.

---

## Run Commands

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

---

## Doc Rules

- `CLAUDE.md` — session bootstrap only. Keep under 200 lines.
- `docs/CODEBASE_MAP.md` — file-to-bucket map. Update when files move or are added.
- `docs/ENGINEERING_STRATEGY.md` — principles + named anti-patterns. The most important doc for preventing bloat.
- `docs/INVARIANTS.md` — must-preserve runtime rules. Only changes when a contract genuinely changes.
- `docs/backend-architecture.md` — detailed backend reference. Update when subsystem behavior changes.
- `docs/frontend-architecture.md` — detailed frontend reference.
- `docs/agent/SKILLS.md` — task recipes. Add new ones as new patterns emerge.
- `docs/agent/PLAN_PROTOCOL.md` — how plans are created and managed.
- `docs/plans/ACTIVE.md` — current plan pointer. Always up to date.

**Do not create new docs without a clear reason why none of the above can absorb the content.**
