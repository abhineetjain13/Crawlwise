# CLAUDE.md

## Project

CrawlerAI — deterministic web crawling pipeline for ecommerce and job board data extraction.

- `backend/` — FastAPI + Postgres + Redis + Celery. Pipeline: ACQUIRE → EXTRACT → UNIFY → PUBLISH.
- `frontend/` — Next.js crawl submission, run inspection, review, and admin views.
- `docs/` — architecture docs, backlog, and planning notes.

## Documentation Map

| Document | Purpose |
|----------|---------|
| `docs/backend-architecture.md` | Full backend architecture, pipeline details, API endpoints |
| `docs/INVARIANTS.md` | All architecture invariants (must-preserve rules) |
| `docs/backend-pending-items.md` | Consolidated backend backlog (bugs, refactors, TODOs) |
| `docs/frontend-architecture.md` | Frontend architecture and component structure |
| `ENGINEERING_STRATEGY.md` | Project health plan, decomposition roadmap, process improvements |

## Running Tests

```powershell
cd backend
$env:PYTHONPATH='.'
pytest tests -q                              # full suite
pytest tests/services/extract/ -q            # extraction only
python run_acquire_smoke.py commerce         # acquisition smoke (api|commerce|jobs|hard|ats|specialist)
python run_extraction_smoke.py               # full extraction pipeline smoke
```

## Development Auth (POC)

- Registration is off by default (`REGISTRATION_ENABLED=false`).
- Bootstrap admin: set `BOOTSTRAP_ADMIN_ONCE=1`, `DEFAULT_ADMIN_EMAIL`, `DEFAULT_ADMIN_PASSWORD`.
- Dashboard "Reset data" requires admin role.

## Control Ownership (Critical)

User-selected crawl controls are **authoritative**. The backend must preserve them exactly as submitted. Never silently rewrite the request.

- page type — user-owned. Do not reclassify.
- `settings.llm_enabled` — user-owned. Do not auto-enable.
- `settings.advanced_mode` — user-owned. Traversal runs only when explicitly requested.
- `settings.proxy_list` — user-owned. Do not auto-switch.
- Browser rendering escalation ≠ traversal authorization. Rendering and traversal are separate decisions.
- Wrong user choice → fail visibly with diagnostics, do not silently fix.

## Crawl Contract

**Submission modes:** `crawl` (single URL), `batch` (multi-URL), `csv` (file upload).

**Page types:**
- `page_type="category"` → `surface="ecommerce_listing","job_listing"`
- `page_type="pdp"` → `surface="ecommerce_detail", "job_detail"`

**Settings:** `advanced_mode` (`null|paginate|scroll|load_more`), `max_pages`, `max_records`, `sleep_ms`, `proxy_list`, `llm_enabled`, `extraction_contract`.

`advanced_mode` is listing traversal only — it does not control browser rendering escalation.

## Pipeline Overview

```
ACQUIRE: curl_cffi (default) → Playwright fallback → AcquisitionResult
EXTRACT: adapter → JSON payload → JSON-LD → hydrated state → DOM → LLM fallback
UNIFY:   strip internals, build source_trace, compute verdict
PUBLISH: persist to Postgres
```

**Extraction is first-match per field** — first valid hit wins, not scoring.

**Listing guard** — 0 item records → `listing_detection_failed`, never detail fallback.

## Record API Contract

- `record.data` — only populated logical fields (empty/null/`_`-prefixed stripped).
- `record.discovered_data` — logical metadata only (raw containers stripped).
- `record.source_trace.field_discovery` — per-field provenance (value, source, missing).
- `record.source_trace.acquisition` — method, browser flags, challenge state, timing.

## Key Invariants (Top 7)

> Full list: `docs/INVARIANTS.md`

1. **No magic values in service code** — tunables live in typed config via `pipeline_config.py`.
2. **User controls are never rewritten** — page type, LLM, traversal mode, proxy are user-owned.
3. **Extraction is first-match, not score-based** — deterministic source hierarchy per field.
4. **Listing fallback guard** — 0 records = `listing_detection_failed`, never detail extraction.
5. **Deleted subsystems stay deleted** — no site memory, selector CRUD, or discovery manifests.
6. **Diagnostics are observational** — report what happened, don't fabricate causes.
7. **Generic paths stay generic** — no tenant/site hardcodes; platform behavior is family-based.

## Agent Rules

- Before editing any file > 500 lines, verify changes with `git diff` after editing.
- Every code change session must end with: run affected tests, show results.
- Never batch more than 3 file edits in one session without verification.
- Commit messages must follow: `type(scope): imperative description` (types: `fix`, `feat`, `refactor`, `test`, `docs`, `chore`).
