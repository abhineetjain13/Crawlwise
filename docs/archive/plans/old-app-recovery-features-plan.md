> **Status:** DONE
> **Archived:** 2026-04-23
> **Reason:** verified complete

# Plan: Port Old-App Recovery Features Through the Existing Markdown and Extraction Paths

**Created:** 2026-04-21
**Agent:** Codex
**Status:** DONE
**Touches buckets:** 2. Crawl Ingestion + Orchestration, 3. Acquisition + Browser Runtime, 4. Extraction, 7. LLM Admin + Runtime

## Goal

Port the old app's higher-value recovery and extraction behavior into the current owners without creating parallel systems. Done means the current browser/detail/listing pipeline expands safe semantic detail controls, extracts accordion/tab content, retries thin listing runs through bounded browser recovery actions, and feeds the existing markdown export/view path with rendered page context.

## Acceptance Criteria

- [x] Detail-page browser expansion is field-aware, ARIA-aware, and skips blocked commerce/auth actions.
- [x] `extract_heading_sections()` recovers accordion/tab content instead of relying only on heading siblings.
- [x] Thin listing extraction can trigger one bounded browser recovery retry and only keeps the retry when record count improves.
- [x] Browser acquisition populates `page_markdown` and the existing markdown export/view path renders that context.
- [x] `python -m pytest tests -q` is the final verification target for this slice set.

## Do Not Touch

- `frontend/components/crawl/crawl-run-screen.tsx` and `frontend/lib/api/index.ts` — existing markdown UI/API flow stays unchanged.
- `backend/app/api/*` — no new route contract required.
- `backend/app/services/publish/*`, `backend/app/services/pipeline/persistence.py` — no downstream compensation for extraction bugs beyond persisting the new internal markdown field.
- `backend/app/services/selectors_runtime.py`, `domain_memory_service.py`, `review/*` — unchanged ownership.
- `backend/app/services/adapters/*`, `config/platforms.json` — no platform-specific hacks added.

## Slices

### Slice 1: Harden Existing Detail Expansion
**Status:** DONE
**Files:** `backend/app/services/acquisition/browser_detail.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/crawl_fetch_runtime.py`, `backend/app/services/acquisition/acquirer.py`, `backend/tests/services/test_browser_expansion_runtime.py`
**What:** Thread requested fields into browser detail expansion and use field-aware, ARIA-aware, blocked-token-safe expansion.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_expansion_runtime.py -q`

### Slice 2: Make DOM Sections Accordion-Aware
**Status:** DONE
**Files:** `backend/app/services/field_value_dom.py`, `backend/app/services/detail_extractor.py`, `backend/tests/services/test_field_value_dom.py`, `backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py`
**What:** Follow `aria-controls`, `details/summary`, wrapped accordion/tab containers, then sibling fallback.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_field_value_dom.py tests/services/test_detail_extractor_priority_and_selector_self_heal.py -q`

### Slice 3: Add Thin-Listing Recovery Retry
**Status:** DONE
**Files:** `backend/app/services/pipeline/core.py`, `backend/app/services/acquisition/acquirer.py`, `backend/app/services/crawl_fetch_runtime.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/acquisition/traversal.py`, `backend/app/services/config/runtime_settings.py`, `backend/tests/services/test_pipeline_core.py`, `backend/tests/services/test_traversal_runtime.py`, `backend/tests/services/test_browser_expansion_runtime.py`
**What:** Add one bounded browser recovery retry for thin listing results and keep it only when it improves extraction count.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_pipeline_core.py tests/services/test_traversal_runtime.py tests/services/test_browser_expansion_runtime.py -q`

### Slice 4: Feed the Existing Markdown View Better Content
**Status:** DONE
**Files:** `backend/app/services/acquisition/browser_page_flow.py`, `backend/app/services/acquisition/runtime.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/acquisition/acquirer.py`, `backend/app/services/record_export_service.py`, `backend/app/services/pipeline/persistence.py`, `backend/tests/services/test_browser_expansion_runtime.py`, `backend/tests/services/test_record_export_service.py`, `frontend/components/crawl/crawl-run-screen.test.tsx`
**What:** Generate internal rendered-page markdown context, persist it, and surface it through the existing markdown export/view flow.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_expansion_runtime.py tests/services/test_record_export_service.py -q`

## Doc Updates Required

- [x] `docs/backend-architecture.md` — acquisition, extraction, and markdown-export behavior updated.
- [ ] `docs/CODEBASE_MAP.md` — not needed; no new file ownership added.
- [ ] `docs/INVARIANTS.md` — not needed; no contract change to invariants.
- [ ] `docs/ENGINEERING_STRATEGY.md` — not needed; no new anti-pattern added.

## Notes

Phase 2 direct LLM record extraction was intentionally left out of implementation scope in this pass. The current work stops after deterministic/P1 behavior and existing markdown-path integration.
