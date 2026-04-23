# AGENTS.md — CrawlerAI Session Bootstrap

> **This is the only file you need to attach at the start of every session.**
> Read it fully before writing any code or asking clarifying questions.

---

## What CrawlerAI Is

CrawlerAI is a deterministic crawl, extraction, review, and export system for ecommerce, jobs, automobiles, and tabular targets. Backend: FastAPI + PostgreSQL + Redis + Celery + Playwright. Frontend: Next.js. Extraction is adapter → structured-source → DOM-first. LLM is opt-in backfill only — never the primary extraction mechanism.

---

## Mandatory Read Order — Do This Before Writing Code

| Step | File | Why |
|------|------|-----|
| 1 | `docs/INVARIANTS.md` | Hard contracts with violation signatures. Read every rule that touches your subsystem. |
| 2 | `docs/CODEBASE_MAP.md` | Where every file lives and which bucket owns it. |
| 3 | `docs/BUSINESS_LOGIC.md` | Product decision points and which files own them. |
| 4 | `docs/ENGINEERING_STRATEGY.md` | Anti-patterns to avoid — especially AP-12 through AP-15. |
| 5 | `docs/plans/ACTIVE.md` | Active plan pointer. If a plan is active, open the plan file and continue from the noted slice. |
| 6 | `docs/agent/SKILLS.md` | Look up the recipe for your current task. |

For backend detail: `docs/backend-architecture.md`
For frontend detail: `docs/frontend-architecture.md`
For plan creation: `docs/agent/PLAN_PROTOCOL.md`

---

## Pre-Code Checklist — Complete This Before Writing Anything

Before writing a single line of implementation:

- [ ] **Grep first.** Run `grep -r "concept_or_function_name" backend/app` to confirm no existing implementation covers this case.
- [ ] **Check config.** If your change involves a constant, token, threshold, or field name — confirm it lives in `app/services/config/` or will be moved there before this task ends.
- [ ] **Identify the owning bucket.** Every file you will touch or create has a clear home in one of the 7 buckets. If it does not, stop and decide.
- [ ] **Plan is current.** If a plan slice is active, it is not marked DONE from a previous session without a verify command logged.
- [ ] **What will you delete?** Name at least one thing you will remove or simplify as part of this change. If the answer is "nothing," the change is probably additive bloat.

---

## Ownership Buckets

| # | Bucket | Primary Files |
|---|--------|---------------|
| 1 | API + Bootstrap | `app/main.py`, `app/api/*`, `app/core/*` |
| 2 | Crawl Ingestion + Orchestration | `crawl_ingestion_service.py`, `crawl_service.py`, `crawl_crud.py`, `_batch_runtime.py`, `pipeline/*` |
| 3 | Acquisition + Browser Runtime | `acquisition/*`, `crawl_fetch_runtime.py`, `robots_policy.py`, `url_safety.py` |
| 4 | Extraction | `crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`, `structured_sources.py`, `js_state_mapper.py`, `network_payload_mapper.py`, `adapters/*`, `extract/*` |
| 5 | Publish + Persistence | `publish/*`, `artifact_store.py`, `pipeline/persistence.py` |
| 6 | Review + Selectors + Domain Memory | `review/__init__.py`, `selectors_runtime.py`, `selector_self_heal.py`, `domain_memory_service.py` |
| 7 | LLM Admin + Runtime | `llm_runtime.py`, `llm_provider_client.py`, `llm_config_service.py`, `llm_cache.py`, `llm_circuit_breaker.py`, `llm_tasks.py` |

Config for all buckets → `app/services/config/*`

---

## The Three Rules That Get Violated Most

**Rule 1 — Config in code is always wrong.**
If you wrote a string constant, URL token, timeout value, field name, or threshold inside any `.py` file outside `app/services/config/`, it is a violation. Move it before the task ends.

**Rule 2 — The candidate system is field-by-field and correct. The variant bugs are specific.**
The `candidates` dict and `_winning_candidates_for_field` in `detail_extractor.py` already select per-field independently. Do not restructure this. The cause of missing variants is 3 specific bugs: (1) early exit before DOM tier runs when `variant_dom_cues_present` is true, (2) `_map_ecommerce_detail_state` returning on first JS state object and discarding variant data in subsequent objects, (3) backfill calls not made after early exit return paths. Fix these bugs in place. Do not add browser interaction before verifying all 3 are fixed. See `INVARIANTS.md` Rule 3 for exact fix signatures.

**Rule 3 — Delete before adding.**
Every task should delete or simplify something. If a plan adds files without removing any, it is accumulating bloat. Trace bugs upstream and fix them at the source — do not add compensating logic downstream.

---

## Key Runtime Facts

- Per-URL execution: `pipeline/core.py`
- Fetch behavior: `crawl_fetch_runtime.py` (import `fetch_page` from here directly)
- Extraction facade: `crawl_engine.py`
- Field aliases + mappings: `services/config/field_mappings.py` (one place, all surfaces)
- Platform adapter registry: `services/adapters/registry.py` + `config/platforms.json`
- Domain memory scoped by `(domain, surface)` — never global
- Listing with zero records → `listing_detection_failed`, never a detail fallback
- LLM use is opt-in per run. It must not activate silently. It fills gaps — it does not win fields.

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

## Session Rules — Non-Negotiable

1. Read `CODEBASE_MAP.md` before exploring the filesystem.
2. Check `plans/ACTIVE.md` before starting implementation.
3. Do not create new files without confirming no existing file owns that concern.
4. Do not add config inside service code. Tunables belong in `app/services/config/*`.
5. Fix extraction bugs upstream. Never add downstream compensating logic.
6. After completing any slice: run the verify step, mark the slice done, update the relevant doc.
7. Do not attach stale audit docs or abandoned plan files to a new session. They are noise.

---

## Doc Map

| Doc | Job |
|-----|-----|
| `AGENTS.md` | Session bootstrap. This file. Keep under 200 lines. |
| `docs/INVARIANTS.md` | Hard runtime contracts with violation signatures. |
| `docs/CODEBASE_MAP.md` | File-to-bucket map. |
| `docs/BUSINESS_LOGIC.md` | Product decision points. |
| `docs/ENGINEERING_STRATEGY.md` | Anti-patterns (AP-1 through AP-15). |
| `docs/backend-architecture.md` | Detailed backend reference. |
| `docs/agent/SKILLS.md` | Task recipes. |
| `docs/agent/PLAN_PROTOCOL.md` | Plan creation and management. |
| `docs/plans/ACTIVE.md` | Current plan pointer. |

Do not create new docs without a clear reason why none of the above can absorb the content.
Stale audit docs in `docs/audits/` and abandoned plans in `docs/plans/` must not be attached to new sessions.