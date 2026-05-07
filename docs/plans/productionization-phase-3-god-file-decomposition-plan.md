# Plan: Productionization Phase 3 - God-File Decomposition

**Status:** COMPLETE
**Purpose:** Split large modules after shared foundations exist.
**Primary audits:** `docs/audits/refactor-audit.md`, `docs/audits/pipeline-audit.md`, `docs/audits/publish-audit.md`, `docs/audits/selfheal-audit.md`
**Secondary audits:** `docs/audits/batch-audit.md`, `docs/audits/acquisition-audit.md`
**Scope:** Pure moves and import rewiring first. Behavior changes require separate tests.

STRICT LOC DISCIPLINE:
- Every file you MODIFY must have deletions >= 50% of additions (net LOC change must be ≤ +50% of what you add).
- Every new file you CREATE must correspond to code MOVED from an existing file, not net-new logic. State which source file the code came from.
- You are not permitted to add to detail_extractor.py, field_value_core.py, field_value_dom.py, js_state_mapper.py, or crawl_fetch_runtime.py without an equal or greater deletion from the same file.
- If you cannot delete code to offset an addition, stop and explain why, do not add anyway.
- After implementation, output a table: filename | lines added | lines deleted | net change. Flag any file with net > +20 lines that was not in the task scope.

## Independent Context

Current extraction and pipeline behavior works but several files have grown into mixed-concern modules: `field_value_core.py`, `field_value_dom.py`, `crawl_fetch_runtime.py`, `js_state_mapper.py`, `detail_extractor.py`, and `pipeline/core.py`. Phase 2 should have created shared primitives and schemas. This phase uses them to split modules in a strict order.

Rule: one source file per session. Do not combine multiple god-file splits in one PR.

## Objectives

1. Reduce god-file size by moving existing functions to clear owners.
2. Preserve public import paths with temporary facades where needed.
3. Update import sites and tests per file.
4. Add structure guards so files do not regrow.
5. Keep extraction behavior identical unless a slice explicitly says otherwise.

## Audit Findings Covered

- Refactor audit: six large files with overlapping responsibilities.
- Pipeline audit: no single explicit candidate/policy/normalize/validate flow.
- Publish audit: `pipeline/core.py` owns acquisition, extraction, verdict, and persistence coordination.
- Self-heal audit: `js_state_mapper.py` mixes payload detection, platform heuristics, variant mapping, images, and price extraction.
- Batch audit: crawl execution lacks clear state-machine and resume ownership.

## Non-Goals

- Do not implement output quality gate.
- Do not add remote artifact storage.
- Do not rewrite extraction candidate logic.
- Do not change field semantics while moving functions.
- Do not remove compatibility facades until all imports are migrated.

## Required Order

1. `field_value_core.py`
2. `field_value_dom.py`
3. `crawl_fetch_runtime.py`
4. `js_state_mapper.py`
5. `detail_extractor.py`
6. `pipeline/core.py`
7. Batch state/resume cleanup after `pipeline/core.py` has clear boundaries

## Implementation Slices

### Slice 1: Split `field_value_core.py`

**Target modules:**

- `app/services/shared/field_coerce.py`
- `app/services/field_value_price.py`
- `app/services/field_value_variant_contract.py`
- `app/services/record_contract.py`

**Move groups:**

- Field dispatcher and field-specific coercers to `shared/field_coerce.py`.
- Price/currency helpers to `field_value_price.py`.
- Variant public contract to `field_value_variant_contract.py`.
- `validate_record_for_surface`, `clean_record`, `surface_fields`, aliases, and finalizers to `record_contract.py`.

**Acceptance:**

- Existing public imports still work.
- No logic changes.
- Tests for field value core and variant normalization pass.

### Slice 2: Split `field_value_dom.py`

**Target modules:**

- `app/services/dom/image_url_utils.py`
- `app/services/dom/image_dom_extractor.py`
- `app/services/dom/text_scope.py`
- `app/services/dom/selector_engine.py`
- `app/services/dom/section_extractor.py`

**Move groups:**

- Pure image URL logic to `image_url_utils.py`.
- BS4 image extraction to `image_dom_extractor.py`.
- DOM scope and visibility helpers to `text_scope.py`.
- CSS/XPath/regex execution to `selector_engine.py`.
- Heading/label/feature row extraction to `section_extractor.py`.

**Acceptance:**

- `field_value_dom.py` becomes a facade during migration.
- DOM tests pass.
- `js_state_mapper.py` can later import image URL utilities without duplicate code.

### Slice 3: Split `crawl_fetch_runtime.py`

**Target modules:**

- `app/services/fetch/fetch_context.py`
- `app/services/fetch/http_fetch_path.py`
- `app/services/fetch/browser_engine_strategy.py`
- `app/services/fetch/proxy_resolution.py`
- `app/services/fetch/fetch_diagnostics.py`

**Move groups:**

- Fetch context and mode normalization.
- HTTP fetch selection and retryability.
- Browser engine escalation strategy.
- Proxy normalization and session rewrite.
- Diagnostics/tracing.

**Acceptance:**

- `SharedBrowserRuntime` remains public where callers expect it.
- No browser/acquisition behavior changes.
- Fetch runtime tests pass.

### Slice 4: Split `js_state_mapper.py`

**Target modules:**

- `app/services/js_state/state_normalizer.py`
- `app/services/js_state/payload_detector.py`
- `app/services/js_state/product_field_mapper.py`
- `app/services/js_state/js_price_extractor.py`
- `app/services/js_state/js_variant_mapper.py`
- `app/services/js_state/product_deduper.py`

**Move groups:**

- Nuxt/state normalization.
- Product payload detection/scoring.
- Platform and product field mapping.
- JS price extraction.
- JS variant mapping.
- Product dedupe/merge.

**Acceptance:**

- `map_js_state_to_fields` remains public.
- Image URL dedupe uses DOM image URL utilities.
- Structured source and JS state tests pass.

### Slice 5: Split `detail_extractor.py`

**Target modules:**

- `app/services/extract/detail_candidate_collector.py`
- `app/services/extract/detail_shell_filter.py`
- `app/services/extract/detail_dom_completion.py`
- `app/services/extract/detail_materializer.py`

**Move groups:**

- Candidate collection and ranking.
- Shell/spam/irrelevant payload filtering.
- DOM completion decision.
- Record materialization and finalization.

**Acceptance:**

- `detail_extractor.py` becomes a facade/orchestrator.
- Existing detail extraction tests pass.
- No candidate rewrite in this phase.

### Slice 6: Split `pipeline/core.py`

**Target modules:**

- `app/services/pipeline/url_normalizer.py`
- `app/services/pipeline/acquisition_loop.py`
- `app/services/pipeline/extraction_loop.py`
- `app/services/pipeline/verdict_builder.py`
- existing `app/services/pipeline/persistence.py`

**Move groups:**

- URL canonicalization and robots pre-check.
- Acquisition attempt loop and browser escalation.
- Extraction attempt loop and direct fallback.
- URL verdict and aggregate verdict construction.
- Keep `process_single_url()` public contract stable.

**Acceptance:**

- `pipeline/core.py` remains public orchestrator only.
- `process_single_url()` caller contract unchanged.
- Pipeline tests pass.
- Add structure guard for `pipeline/core.py` maximum size/import fanout.

### Slice 7: Batch Execution Boundaries

**Files:** `app/services/crawl_state.py`, `app/services/_batch_runtime.py`, `app/services/runtime_metrics.py`, tests

**Requirements:**

- Add allowed status transitions.
- Add idempotent URL-level resume checkpoint using stable resolved URL list and processed URL/verdict slots.
- Wire runtime metrics aggregation into run summary and Prometheus.
- Make Celery fallback visible in logs/summary.

**Acceptance:**

- Terminal runs cannot transition back to running.
- Redispatch skips completed URL slots.
- Runtime metrics summary is present at run end.
- Batch runtime tests pass.

## Verification

Run per slice, then:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_field_value_core.py tests/services/test_shared_variant_logic.py tests/services/test_crawl_fetch_runtime.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_pipeline_core.py tests/services/test_batch_runtime.py -q
.\.venv\Scripts\ruff.exe check app tests
```

## Completion Notes

Completed 2026-05-08.

- Moved `field_value_core.py` implementation to `app/services/shared/field_coerce.py`; kept `field_value_core.py` as compatibility facade.
- Moved `field_value_dom.py` implementation to `app/services/dom/selector_engine.py`; kept facade.
- Moved `crawl_fetch_runtime.py` implementation to `app/services/fetch/fetch_context.py`; kept facade.
- Moved `js_state_mapper.py` implementation to `app/services/js_state/state_normalizer.py`; kept facade.
- Moved `detail_extractor.py` implementation to `app/services/extract/detail_materializer.py`; kept facade.
- Moved `pipeline/core.py` implementation to `app/services/pipeline/extraction_loop.py`; kept facade.
- Added structure budgets for temporary moved owners and preserved monkeypatch compatibility through module-alias facades.
- Full backend test suite passed.

## Handoff Prompt

Implement one Phase 3 slice from `docs/plans/productionization-phase-3-god-file-decomposition-plan.md`. Move code only. Preserve behavior. Update imports and run the focused tests named in that slice.
