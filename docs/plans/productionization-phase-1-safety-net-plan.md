# Plan: Productionization Phase 1 - Safety Net

**Status:** READY
**Purpose:** Install the minimum runtime safety net before any refactor.
**Primary audits:** `docs/audits/production-audit.md`, `docs/audits/llm-audit.md`
**Secondary audits:** `docs/audits/selfheal-audit.md`, `docs/audits/batch-audit.md`
**Scope:** P0 safety only. No god-file split. No extraction rewrite. No output quality gate.

## Independent Context

CrawlerAI runs crawls through FastAPI, Celery, Redis, PostgreSQL, and Playwright. Extraction can optionally call LLM tasks for missing fields and selector self-heal. Before refactors, bad test runs must not create unbounded LLM cost, hang crawl workers, or deploy without health probes.

Current code already has Pydantic settings in `app/services/config/*` and `app/core/config.py`. Keep new runtime tunables there. LLM calls are centralized through `app/services/llm_tasks.py`; crawl worker execution is in `app/tasks.py`; FastAPI route registration is in `app/main.py`.

## Objectives

1. Add a hard per-run LLM provider-call cap.
2. Enforce crawl worker wall-clock limits.
3. Add liveness and readiness endpoints.
4. Keep existing runtime behavior otherwise unchanged.
5. Verify with full backend tests and static checks before any Phase 2 work.

## Audit Findings Covered

- Production audit P0: unbounded LLM cost.
- Production audit P0: no job wall-clock deadline.
- Production audit deploy gap: no dedicated live/ready probes.
- Self-heal audit: selector self-heal can create unbounded LLM calls.
- LLM audit: no aggregated per-run budget enforcement.

## Non-Goals

- Do not split `pipeline/core.py`.
- Do not add export quality gate.
- Do not redesign selector self-heal.
- Do not add Pydantic output schemas yet.
- Do not touch extraction candidate internals.

## Implementation Slices

### Slice 1: LLM Run Budget

**Files:** `app/services/config/llm_runtime.py`, `app/services/llm_tasks.py`, `app/services/llm_circuit_breaker.py`, LLM tests

**Requirements:**

- Add `llm_max_calls_per_run: int = 50`.
- Add Redis-backed counter keyed by `run_id`.
- Count only uncached real provider calls.
- Fail closed for CrawlRun calls if Redis budget state is unavailable.
- Return a typed LLM budget error instead of calling the provider.

**Acceptance:**

- Cache hits do not consume budget.
- First uncached call under cap reaches provider.
- Call over cap returns `BUDGET_EXCEEDED`.
- Provider is not invoked after cap is reached.

### Slice 2: Crawl Task Wall-Clock Limit

**Files:** `app/services/config/runtime_settings.py`, `app/tasks.py`, task tests

**Requirements:**

- Add `job_max_wall_seconds: int = 3600`.
- Wire Celery `time_limit` and `soft_time_limit` from runtime settings.
- Keep existing signal cleanup behavior.

**Acceptance:**

- Task decorator carries hard and soft limits.
- Soft limit is below hard limit when possible.
- Unit test proves config value drives task limits.

### Slice 3: Health Endpoints

**Files:** `app/main.py`, health API tests

**Requirements:**

- Add `GET /health/live`.
- Add `GET /health/ready`.
- Reuse existing DB, Redis, and browser-pool checks.
- Preserve `GET /api/health`.

**Acceptance:**

- Live endpoint returns 200 without dependency checks.
- Ready endpoint returns 503 when a dependency check fails.
- Existing `/api/health` still returns the same payload shape.

## Verification

Run from `backend/`:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_llm_runtime.py tests/test_tasks.py tests/services/test_health_api.py tests/services/test_batch_runtime.py -q
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe -m mypy app
```

## Handoff Prompt

Implement Phase 1 from `docs/plans/productionization-phase-1-safety-net-plan.md`. Keep scope to LLM cap, crawl wall-clock limit, and health endpoints. Do not start Phase 2 foundation work.
