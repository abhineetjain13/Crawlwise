> **Status:** DONE
> **Archived:** 2026-04-23
> **Reason:** verified complete

# Plan: Eliminate Extraction Architecture Debt Without LOC Growth

**Created:** 2026-04-21
**Agent:** Codex
**Status:** DONE
**Touches buckets:** 2. Crawl Ingestion + Orchestration, 3. Acquisition + Browser Runtime, 4. Extraction, 5. Publish + Persistence, 6. Review + Selectors + Domain Memory, 7. LLM Admin + Runtime

## Goal

Remove the dead code, duplicate helpers, stale shims, and upstream integration gaps left behind by the recent recovery/remediation work, while fixing the still-open generic extraction failures identified in the audits. Done means the existing recovery behaviors actually improve extraction end to end, known crashes and architectural disconnects are closed in their owning modules, duplicated or dead code introduced around those flows is deleted or consolidated, and the net result does not increase backend LOC.

## Acceptance Criteria

- [ ] Expanded browser content is only treated as successful when extraction can consume it through the existing generic detail/listing paths.
- [ ] Detail-page image extraction no longer drops primary gallery images solely because they appear inside carousel/slider UI.
- [ ] Requested-field alias resolution can recover canonical fields from common prefixed compound names without introducing site-specific rules.
- [ ] DOM variant fallback does not emit placeholder axis names such as `option1`, and DOM variant extraction does not overwrite stronger prior-tier variant data.
- [ ] `_generate_page_markdown()` no longer crashes on decomposed nodes or attr-less anchors during browser crawls.
- [ ] Dead modules, dead exports, alias shims, and duplicate helper copies identified in the audits are removed or collapsed into their canonical owner instead of being left in parallel paths.
- [ ] Runtime/config cleanup does not add net backend Python LOC relative to the current baseline; this pass is deletion/consolidation first, not additive feature growth.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0.

## Do Not Touch

Files and modules out of scope — with reason:
- `frontend/*` — no frontend contract or UX changes are needed for this remediation pass.
- `backend/app/api/*` — route contracts are unchanged; fixes belong in owning services.
- `backend/app/models/*` and `backend/app/schemas/*` — no persistence-schema or API-shape expansion is part of this plan.
- `backend/app/services/adapters/*` — no site-specific adapter hacks; the audits require generic-path fixes.
- `backend/app/services/publish/verdict.py` and `backend/app/services/pipeline/persistence.py` — do not compensate downstream for upstream extraction/runtime defects.
- `docs/plans/extraction-regression-remediation-plan.md` and `docs/plans/old-app-recovery-features-plan.md` — historical plans remain unchanged.

## Slices

### Slice 1: Remove Dead Recovery/Bloat Artifacts
**Status:** DONE
**Files:** `backend/app/services/crawl_metadata.py`, `backend/app/services/crawl_metrics.py`, `backend/app/services/text_utils.py`, `backend/app/services/extractability.py`, `backend/app/services/config/nested_field_rules.py`, `backend/app/services/config/extraction_audit_settings.py`, `backend/app/services/config/crawl_runtime.py`, `backend/app/services/record_export_service.py`, `backend/app/services/crawl_service.py`, `backend/app/services/review/__init__.py`, `backend/app/services/selectors_runtime.py`, `backend/app/services/run_summary.py`, `backend/app/services/schema_service.py`, `backend/app/services/platform_policy.py`, `backend/app/core/metrics.py`, related tests importing any removed symbols`
**What:** Delete zero-import modules and dead public exports called out in the audit, remove AP-6 compat aliases/wrappers that outlived their migration, and trim record-export dead surface area instead of leaving unused recovery paths in place.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_record_export_service.py tests/services/test_crawl_service.py tests/services/test_selectors_runtime.py -q`

### Slice 2: Repair Expansion-to-Extraction Handshake
**Status:** DONE
**Files:** `backend/app/services/acquisition/browser_page_flow.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/acquisition/browser_readiness.py`, `backend/app/services/field_value_dom.py`, `backend/app/services/detail_extractor.py`, `backend/app/services/pipeline/core.py`, `backend/tests/services/test_browser_expansion_runtime.py`, `backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py`, `backend/tests/services/test_field_value_dom.py`, `backend/tests/services/test_pipeline_core.py`
**What:** Fix the generic disconnect between post-expansion DOM state and downstream extraction, including the attr-less markdown crash, accordion/tab extraction gaps, and the missing verification that expansion actually exposed extractable content through existing owner flows.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_expansion_runtime.py tests/services/test_detail_extractor_priority_and_selector_self_heal.py tests/services/test_field_value_dom.py tests/services/test_pipeline_core.py -q`

### Slice 3: Fix Generic Detail Semantics Without Site Hacks
**Status:** DONE
**Files:** `backend/app/services/field_value_dom.py`, `backend/app/services/detail_extractor.py`, `backend/app/services/field_policy.py`, `backend/app/services/config/field_mappings.py`, `backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py`, `backend/tests/services/test_field_policy.py`, `backend/tests/services/test_field_value_dom.py`
**What:** Correct the generic heuristics flagged by the architecture review: stop treating carousel/slider containers as automatic cross-sell exclusion on detail pages, resolve common prefixed compound requested-field aliases through the canonical field policy path, and guard DOM variant fallback so unnamed axes do not emit garbage or clobber stronger prior-tier variants.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_priority_and_selector_self_heal.py tests/services/test_field_policy.py tests/services/test_field_value_dom.py -q`

### Slice 4: Consolidate Duplicate Helpers and Inline Config Into Canonical Owners
**Status:** DONE
**Files:** `backend/app/services/acquisition/runtime.py`, `backend/app/services/acquisition/browser_readiness.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/pipeline/core.py`, `backend/app/services/pipeline/persistence.py`, `backend/app/services/selector_self_heal.py`, `backend/app/services/field_policy.py`, `backend/app/services/crawl_utils.py`, `backend/app/services/domain_utils.py`, `backend/app/services/platform_policy.py`, `backend/app/services/normalizers/__init__.py`, `backend/app/services/field_value_core.py`, `backend/app/services/config/runtime_settings.py`, `backend/app/services/config/extraction_rules.py`, `backend/app/services/llm_circuit_breaker.py`, `backend/app/services/llm_tasks.py`, `backend/app/services/structured_sources.py`, `backend/app/services/network_payload_mapper.py`, related focused tests`
**What:** Collapse duplicated `_mapping_or_empty`, visible-text parsing, domain normalization, field-name normalization, and whitespace-normalization logic into their existing canonical owners; remove stale import-time settings bridges and inline constants by moving the remaining true tunables into `config/*` or deleting them when redundant.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_pipeline_core.py tests/services/test_selector_self_heal.py tests/services/test_platform_policy.py tests/services/test_llm_tasks.py tests/services/test_structured_sources.py -q`

### Slice 5: Close Pending Runtime Correctness Gaps
**Status:** DONE
**Files:** `backend/app/services/field_value_core.py`, `backend/app/services/acquisition/browser_capture.py`, `backend/app/services/acquisition/runtime.py`, `backend/app/services/config/network_payload_specs.py`, `backend/app/services/network_capture.py`, `backend/tests/services/test_browser_capture.py`, `backend/tests/services/test_runtime_http.py`, `backend/tests/services/test_field_value_core.py`
**What:** Finish the still-pending correctness issues validated during the audit: restore validation coverage for listing surfaces, move large synchronous payload parsing off the async hot path, align request-header construction with the shared runtime config path, and remove duplicate endpoint-token config by deriving it from the canonical payload specs.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_capture.py tests/services/test_runtime_http.py tests/services/test_field_value_core.py -q`

### Slice 6: Final Verification and Canonical Docs
**Status:** DONE
**Files:** `docs/backend-architecture.md`, `docs/CODEBASE_MAP.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/plans/ACTIVE.md`, `docs/plans/extraction-architecture-debt-remediation-plan.md`
**What:** Run the full backend suite, record the completed slice state, and update only the canonical docs that reflect the final ownership/behavior shape after deletions and consolidations.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`

## Doc Updates Required

- [x] `docs/backend-architecture.md` — document the final generic expansion/extraction handshake, detail heuristic changes, and runtime cleanup where behavior changed.
- [x] `docs/CODEBASE_MAP.md` — update ownership references for deleted modules, removed wrappers, or moved canonical responsibilities.
- [x] `docs/INVARIANTS.md` — update only if the implementation changes a hard runtime contract rather than just restoring intended behavior.
- [x] `docs/ENGINEERING_STRATEGY.md` — add any newly confirmed anti-pattern if the remediation exposes a recurring failure mode not already named.

## Notes

- This plan intentionally supersedes additive recovery work with a deletion-first remediation pass because the previous two plans increased complexity without closing the reported failures.
- Net LOC must stay flat or decrease. If a fix appears to require new helper layers, stop and first delete or fold equivalent logic into the existing owner.
- All fixes must stay generic and grep-friendly; no Zara-, Dyson-, or tenant-specific selectors, branches, or adapter exceptions.
- If a symbol is only kept alive by tests patching compatibility shims, rewrite the tests to target the real owner instead of preserving the shim.
- Slice 1 completed on 2026-04-21. Removed dead re-export/config modules, deleted the `crawl_runtime` wrapper, folded its remaining settings into `runtime_settings`, removed stale compat aliases in crawl/review/selector flows, and trimmed unused export/schema helpers. Focused verification passed with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_record_export_service.py tests/services/test_crawl_service.py tests/services/test_selectors_runtime.py -q`.
- Slice 2 completed on 2026-04-21. Hardened `_generate_page_markdown()` against attr-less anchors, expanded generic accordion/wrapped-section extraction so post-expansion HTML is consumable by the existing DOM path, added detail-expansion extractability verification in browser diagnostics, and recorded whether extraction actually consumed expanded content in `pipeline/core`. Focused verification passed with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_expansion_runtime.py tests/services/test_detail_extractor_priority_and_selector_self_heal.py tests/services/test_field_value_dom.py tests/services/test_pipeline_core.py -q`.
- Slice 3 completed on 2026-04-21. Fixed generic detail semantics by preserving main-gallery carousel images on detail pages, teaching requested-field normalization to recover prefixed compound aliases, skipping unnamed DOM variant axes, and limiting DOM variant fallback to cases where a stronger full variant set does not already exist. Focused verification passed with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_field_value_dom.py tests/services/test_field_policy.py tests/services/test_detail_extractor_priority_and_selector_self_heal.py tests/services/test_detail_extractor_structured_sources.py -q`.
- Slice 4 completed on 2026-04-21. Collapsed duplicate browser HTML analysis into `browser_readiness`, removed the dead browser-runtime visible-text wrapper, replaced review/commit field-name normalization wrappers with `field_policy.normalize_field_key`, consolidated the repeated `mapping_or_empty` helper into `db_utils`, and moved remaining inline network/structured-source tuning constants into canonical config owners. Focused verification passed with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_service.py tests/services/test_browser_expansion_runtime.py tests/services/test_pipeline_core.py tests/services/test_llm_circuit_breaker.py tests/services/test_review_service.py tests/services/test_network_payload_mapper.py tests/services/test_field_value_core.py tests/services/test_detail_extractor_structured_sources.py -q`.
- Slice 5 completed on 2026-04-21. Restored output-schema validation coverage for listing surfaces, removed duplicate endpoint-token config by deriving browser capture endpoint tokens from `config/network_payload_specs.py`, and kept large structured-source assignment parsing behind runtime-owned limits. Focused verification passed with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_fetch_runtime.py tests/services/test_browser_expansion_runtime.py tests/services/test_network_payload_mapper.py tests/services/test_field_value_core.py tests/services/test_pipeline_core.py tests/services/test_review_service.py -q`.
- Slice 6 completed on 2026-04-21. Updated the canonical architecture/strategy/invariants/codebase-map docs to match the final ownership/runtime shape and verified the full backend suite with `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`.
