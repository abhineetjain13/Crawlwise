# Plan: Audit Remediation for Pipeline Validation, Runtime Config, and Export Cleanup

**Created:** 2026-04-21
**Agent:** Codex
**Status:** DONE
**Touches buckets:** 2, 3, 4, 5

## Goal

Address the actionable findings in `docs/audits/gemini-audit.md` without introducing new layers or downstream compensation. Done means the pipeline restores its post-extraction validation gate, LLM prompt sanitization becomes config-driven and leaves `pipeline/core.py`, acquisition runtime behavior stays config-consistent and avoids avoidable async hot-path blocking, and the export module drops leftover compat shims.

## Acceptance Criteria

- [x] `_run_normalization_stage` explicitly validates and cleans extracted records before persistence, dropping invalid fields rather than records.
- [x] `pipeline/core.py` no longer hardcodes the LLM existing-value truncation limit.
- [x] `pipeline/core.py` no longer contains the inline HTML stripper class.
- [x] `acquisition/runtime.py` stops hardcoding curl request headers that should follow runtime configuration/shared request behavior.
- [x] `acquisition/browser_capture.py` no longer performs large synchronous payload decode work directly on the async hot path.
- [x] `record_export_service.py` no longer contains legacy re-export shims.
- [x] Focused tests cover the changed contracts.
- [x] `python -m pytest tests -q` exits 0.

## Do Not Touch

Files and modules out of scope -- with reason:
- `backend/app/services/field_value_core.py` -- preserve the existing validation semantics and only wire its public helpers into the pipeline.
- `backend/app/services/adapters/*` -- audit findings do not require adapter changes.
- `backend/app/api/*` -- the work is service-level and should not change route contracts.
- `backend/app/services/publish/*` -- verdict behavior is out of scope unless a failing test proves otherwise.
- Pydantic output schema redesign -- noted in the audit as follow-on architecture work, not part of this remediation pass.

## Slices

### Slice 1: Restore normalization-stage schema enforcement
**Status:** DONE
**Files:** `backend/app/services/pipeline/core.py`, related pipeline/extraction tests
**What:** Wire `validate_and_clean` and `clean_record` into `_run_normalization_stage`, preserve crawl success when individual fields fail validation, and log schema-cleanup warnings instead of failing the URL.
**Verify:** focused pytest for normalization/persistence path, then broader pipeline tests

### Slice 2: Remove pipeline inline config and sanitization leakage
**Status:** DONE
**Files:** `backend/app/services/pipeline/core.py`, shared sanitization owner file, related tests
**What:** Replace the hardcoded LLM truncation limit with `llm_runtime_settings.existing_values_max_chars`, move HTML tag stripping out of `pipeline/core.py` into a shared utility owner, and keep `_sanitize_llm_existing_values` orchestration-only.
**Verify:** focused pytest for LLM existing-values sanitization plus grep checks confirming the hardcoded constant and inline stripper are gone

### Slice 3: Fix acquisition runtime consistency and async hot-path blocking
**Status:** DONE
**Files:** `backend/app/services/acquisition/runtime.py`, `backend/app/services/acquisition/browser_capture.py`, related acquisition tests
**What:** Make curl request headers follow runtime-owned behavior and offload CPU-bound network payload decoding/parsing from the event loop where browser capture currently does it inline.
**Verify:** focused acquisition/browser-capture tests, then relevant runtime test subset

### Slice 4: Remove export compat shims
**Status:** DONE
**Files:** `backend/app/services/record_export_service.py`, related export tests
**What:** Delete the bottom-of-file re-export aliases and confirm no callers depend on them.
**Verify:** focused export tests plus grep check confirming shim symbols are removed

### Slice 5: Final verification and doc update check
**Status:** DONE
**Files:** plan file, `docs/plans/ACTIVE.md`, only canonical docs if behavior/ownership documentation actually changed
**What:** Run full backend test suite, update slice statuses, and only update canonical docs if the implementation changes stable architecture knowledge rather than just fixing code.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`

## Doc Updates Required

- [x] `docs/backend-architecture.md` -- no stable architecture doc change required for this remediation
- [x] `docs/CODEBASE_MAP.md` -- no new owner file added after consolidating sanitization into existing modules
- [x] `docs/INVARIANTS.md` -- no contract change required
- [x] `docs/ENGINEERING_STRATEGY.md` -- no new anti-pattern discovered

## Notes

- The highest-risk finding is the disconnected normalization gate in `pipeline/core.py`; fix it first.
- `record_export_service.py` is treated as Bucket 5 work because it owns export behavior.
- The audit's Pydantic recommendation is intentionally excluded to avoid speculative architecture expansion.
- Slice 1 complete: normalization now validates surface-constrained fields before persistence and logs cleanup warnings without failing crawls.
- Slice 2 complete: LLM existing-value truncation now follows `llm_runtime_settings`, and HTML stripping is handled by shared field-value sanitization helpers instead of inline pipeline code.
- Slice 3 complete: curl request headers now use the runtime-owned default header builder, and browser payload decoding is offloaded with `asyncio.to_thread`.
- Slice 4 complete: legacy export re-export shims removed.
- Slice 5 complete: `python -m pytest tests -q` passed with 360 tests.
