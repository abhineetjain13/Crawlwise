# Plan: Patchright Browser Engine Integration

**Created:** 2026-04-26
**Agent:** Codex
**Status:** DONE
**Touches buckets:** acquisition, config, tests, docs

## Goal

Add `patchright` as a first-class browser engine in the existing acquisition engine ladder so CrawlerAI can use a patched Chromium runtime without replacing the current Chromium and real-Chrome paths. Done means the runtime can normalize, select, launch, diagnose, and persist engine-scoped browser state for `patchright`, and the behavior is covered by focused tests.

## Acceptance Criteria

- [x] `patchright` is a supported browser engine in acquisition runtime and fetch-engine selection.
- [x] Browser diagnostics and engine-scoped storage state can carry `patchright` without bleeding into `chromium` or `real_chrome`.
- [x] Patchright launch falls back cleanly when the package is unavailable.
- [x] Targeted browser runtime and fetch-engine tests pass.
- [ ] `python -m pytest tests -q` result is recorded if broader verification is run.

## Do Not Touch

- `backend/app/services/publish/*` — no downstream repair.
- `backend/app/services/detail_extractor.py` — not part of this change.
- Frontend config screens — backend/browser runtime only unless a contract break forces follow-up.

## Slices

### Slice 1: Engine Contract
**Status:** DONE
**Files:** `backend/app/services/config/runtime_settings.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/crawl_fetch_runtime.py`
**What:** Add `patchright` engine support, runtime settings, normalization, engine attempt selection, and launch behavior.
**Verify:** Targeted browser runtime and fetch tests.

### Slice 2: Dependency + Runtime Safety
**Status:** DONE
**Files:** `backend/pyproject.toml`, lock/dependency metadata if needed
**What:** Add Patchright dependency and keep runtime failure explicit when package is not installed.
**Verify:** Import-path test or runtime launch test.

### Slice 3: Regression Coverage
**Status:** DONE
**Files:** `backend/tests/services/test_browser_context.py`, `backend/tests/services/test_crawl_fetch_runtime.py`
**What:** Cover engine normalization, runtime cache keys, storage scoping, and engine ladder behavior.
**Verify:** Focused pytest command.

### Slice 4: Hybrid Plan Handoff
**Status:** DONE
**Files:** `docs/plans/hybrid-browser-http-handoff-plan.md`, `docs/plans/ACTIVE.md`
**What:** Document deferred hybrid browser-to-HTTP strategy as a later plan and queue it.
**Verify:** Doc review.

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — only if ownership/file map changes.
- [x] `docs/INVARIANTS.md` — if engine-scoping contract expands beyond Chromium/real Chrome.
- [ ] `docs/backend-architecture.md` — if browser engine behavior needs reference docs.

## Notes

- Existing engine ladder already supports `chromium` and `real_chrome`.
- Existing cookie memory invariant is engine-scoped. `patchright` must obey same rule.
- `patchright` added as preferred Chromium-family lane when enabled and importable; explicit `forced_browser_engine="patchright"` stays explicit.
- `uv lock` added `patchright v1.58.2`.
- Local runtime prepared with:
  - `cd backend; .\.venv\Scripts\python.exe -m pip install patchright==1.58.2`
  - `cd backend; .\.venv\Scripts\python.exe -m patchright install chromium`
- Verify: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests\services\test_browser_context.py tests\services\test_crawl_fetch_runtime.py -q`
- Result: `141 passed, 11 warnings` on 2026-04-26.
