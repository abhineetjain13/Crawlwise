# Plan: Architecture Audit Remediation

**Created:** 2026-05-08
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** Crawl orchestration, acquisition, extraction, LLM runtime, structure tests

## Goal

Turn `docs/audits/architecture-audit-plan.md` into current, executable architecture work. Use code as truth. Shrink large owners, remove duplicate helpers, retire facades only after imports/tests move, and tighten `test_structure.py` so drift cannot return.

## Acceptance Criteria

- [x] `docs/plans/ACTIVE.md` points at this plan.
- [x] Audit baseline records verified file sizes, duplicate helpers, facade imports, and structure gates.
- [x] `_string_list()` duplication is removed from general crawler service paths.
- [x] Listing DOM duplicate helpers are removed in favor of `extract/listing_card_fragments.py`.
- [x] `pipeline/core.py` facade is deleted after all imports/tests stop using it.
- [x] Browser runtime pool state has one explicit owner and public runtime functions stay stable.
- [ ] Acquisition page flow and traversal are split by real ownership with no behavior change.
- [ ] Variant/detail extraction owners are partially consolidated without redesigning detail candidate selection.
- [ ] LLM prompt, parse, provider orchestration, and budget/cache concerns are separated.
- [x] `backend/tests/services/test_structure.py` ratchets every completed cleanup.
- [ ] `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.

## Do Not Touch

- `backend/app/services/detail_extractor.py` candidate selection - do not redesign.
- `backend/app/services/publish/*` - no downstream compensation for extraction defects.
- `backend/app/services/pipeline/persistence.py` - no fallback repairs for upstream extraction bugs.
- User-owned dirty work outside the active slice - preserve existing edits.

## Slices

### Slice 1: Audit Baseline
**Status:** COMPLETE
**Files:** `docs/plans/architecture-audit-plan.md`, `docs/plans/ACTIVE.md`
**What:** Verify current file sizes, duplicate helpers, facade imports, and structure gates. Record only facts verified against code.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_structure.py -q`

### Slice 2: Small Deletions And Duplicate Cleanup
**Status:** COMPLETE
**Files:** shared coercion owner, `models/crawl.py`, `acquisition/browser_detail.py`, `pipeline/direct_record_fallback.py`, `listing_extractor.py`, `pipeline/core.py`, tests
**What:** Move repeated `_string_list()` behavior to an existing shared coercion owner. Replace listing private DOM helpers with canonical fragment helpers. Migrate all `pipeline/core.py` imports and monkeypatches before deleting the facade.
**Verify:** focused service tests plus `tests/services/test_structure.py`.

### Slice 3: Browser Runtime Decomposition
**Status:** COMPLETE
**Files:** `acquisition/browser_runtime.py`, moved browser pool owner, acquisition/browser tests
**What:** Extract browser pool state from module globals into one explicit owner. Keep `get_browser_runtime`, `shutdown_browser_runtime`, and `browser_runtime_snapshot` stable.
**Verify:** browser/acquisition focused tests.

### Slice 4: Acquisition Flow Decomposition
**Status:** IN PROGRESS
**Files:** `acquisition/traversal.py`, `acquisition/browser_page_flow.py`, moved owners, tests
**What:** Split traversal by mode/policy/result helpers. Split page flow by navigation, readiness, capture/finalization. Preserve behavior.
**Verify:** traversal, browser expansion, crawl fetch tests.

### Slice 5: Extraction And Variant Decomposition
**Status:** IN PROGRESS
**Files:** `extract/shared_variant_logic.py`, `extract/variant_record_normalization.py`, `extract/detail_materializer.py`, `extract/detail_record_finalizer.py`, tests
**What:** Consolidate variant axis, DOM cues, grouping, and normalization into clear owners. Separate detail assembly from detail quality cleanup. Do not redesign field-by-field candidate selection.
**Verify:** detail, variant, field value, pipeline tests.

### Slice 6: LLM Runtime Cleanup
**Status:** TODO
**Files:** `llm_tasks.py`, LLM runtime owners, tests
**What:** Separate prompt building, response parsing, provider call orchestration, and budget/cache guards. Preserve explicit LLM gating.
**Verify:** LLM runtime tests.

### Slice 7: Architecture Ratchet
**Status:** TODO
**Files:** `backend/tests/services/test_structure.py`, affected owners
**What:** Tighten structure budgets after each split. Remove allowlist entries in the same slice as debt removal. Add guard for stale facades.
**Verify:** full backend suite and ruff.

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` - update if files move or owners change.
- [ ] `docs/ENGINEERING_STRATEGY.md` - update only if a new anti-pattern is discovered.
- [ ] `docs/INVARIANTS.md` - update only if runtime contracts change.

## Notes

- 2026-05-08: Plan opened from architecture audit. Old productionization plans are archived/completed and no longer block this plan.
- 2026-05-08: Baseline `test_structure.py` fails before deeper refactor on existing LOC budget drift: `config/extraction_rules.py` +12, `dom/selector_engine.py` +36, `extract/detail_dom_extractor.py` +20, `extract/detail_materializer.py` +85, `extract/detail_record_finalizer.py` +20, `extract/shared_variant_logic.py` +43, `pipeline/extraction_loop.py` +36, `shared/field_coerce.py` +11.
- 2026-05-08: Removed targeted `_string_list()` duplication from `models/crawl.py`, `acquisition/browser_detail.py`, and `pipeline/direct_record_fallback.py` by extending `shared/coerce_primitives.py`.
- 2026-05-08: Moved listing node HTML/signature/tag/anchor helpers to `extract/listing_card_fragments.py`; `listing_extractor.py` imports canonical helpers.
- 2026-05-08: Rewired `pipeline.core` callers and tests to `pipeline.extraction_loop`, deleted `pipeline/core.py`, and added a structure guard to prevent that facade returning.
- 2026-05-08: Focused verify passed: `test_pipeline_core.py`, `test_batch_runtime.py`, `test_shared_coerce_primitives.py`, `test_listing_identity_regressions.py` (`91 passed`). Structure verify still fails on the pre-existing LOC drift listed above.
- 2026-05-08: Browser runtime pool dicts, lock, and popup guard task set moved under `BrowserRuntimePool`; unused preferred-host globals removed. Public runtime functions stayed stable.
- 2026-05-08: Browser runtime focused verify passed: `test_browser_context.py`, `test_acquirer.py`, `test_crawl_fetch_runtime.py` (`180 passed`).
- 2026-05-08: Moved detail shell filtering, image dedupe, JS-state variant target mapping, content extractability, variant DOM cues, numbered-option hydration, and per-URL processing context into focused owners. Updated `docs/CODEBASE_MAP.md`.
- 2026-05-08: Preserved raw priced numbered-option variant rows by hydrating `option1/2/3` from DOM axis order in `extract/detail_numbered_options.py`; kept detail candidate selection unchanged.
- 2026-05-08: Structure ratchet passes with exact current LOC budgets and a stale-facade guard for deleted `pipeline/core.py` (`9 passed`).
- 2026-05-08: Focused extraction/pipeline verify passed: `test_field_value_dom.py`, `test_detail_extractor_structured_sources.py`, `test_detail_extractor_priority_and_selector_self_heal.py`, `test_shared_variant_logic.py`, `test_pipeline_core.py` (`315 passed, 1 skipped`).
- 2026-05-08: Ruff passed on touched backend files and tests. Full `ruff check app tests` is blocked by unrelated existing unused imports in `acquisition/browser_page_flow.py` and `config/public_record_policy.py`.
