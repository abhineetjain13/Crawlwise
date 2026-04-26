# Plan: Fingerprint, Real Chrome Escalation, Schema Pollution Remediation

**Created:** 2026-04-26
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** acquisition, extraction, pipeline persistence, config, tests, docs

## Goal

Fix the latest detail batch regressions at the source: retry protected detail pages on real Chrome when Chromium is only rejected after extraction, prevent polluted fields from reaching `record.data`, remove variant axis header noise, and document the remaining Chromium fingerprint limits as transport-layer limits beyond JA3.

## Acceptance Criteria

- [x] Chromium detail pages rejected as `challenge_shell` retry once on real Chrome when available.
- [x] Host memory records Chromium post-extraction challenge shells as `browser:chromium` blocks and real Chrome successes as `browser:real_chrome`.
- [x] `CrawlRecord.data` contains only populated, surface-allowed logical fields with valid value shapes and navigation-safe URLs.
- [x] Variant axis labels and header rows do not populate top-level `size`, `color`, `available_sizes`, `variants`, or `selected_variant`.
- [x] LLM fallback outputs pass the same schema/value firewall before persistence.
- [x] Fingerprint audit states Chromium transport residuals as JA3/JA4/HTTP2/HTTP3/TCP behavior, not JS leaks.
- [x] Targeted tests pass.
- [x] `python -m pytest tests -q` result is recorded.

## Do Not Touch

- `backend/app/services/publish/*` — no downstream export repair.
- `backend/app/services/detail_extractor.py` candidate architecture — keep field-by-field candidate system.
- Archived docs — stale context, not active contract.

## Slices

### Slice 1: Real Chrome Retry
**Status:** DONE
**Files:** `backend/app/services/pipeline/core.py`, `backend/app/services/crawl_fetch_runtime.py`, acquisition host memory tests
**What:** Retry post-extraction `challenge_shell` detail failures from Chromium on real Chrome; record engine sequence and retry reason; update host memory.
**Verify:** Targeted pipeline/acquisition tests.

### Slice 2: Schema Firewall
**Status:** DONE
**Files:** `backend/app/services/pipeline/persistence.py`, `backend/app/services/field_value_core.py`, config exports if needed
**What:** Validate final persisted data against surface schema, value shape, and URL safety before `CrawlRecord.data`; keep rejected field trace out of public data.
**Verify:** Persistence firewall tests.

### Slice 3: Variant Pollution Cleanup
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/extract/shared_variant_logic.py`
**What:** Drop axis headers/group labels from variants and top-level axis fields; ensure selected variant drives top-level option fields.
**Verify:** Variant pollution tests.

### Slice 4: LLM Gate + Docs
**Status:** DONE
**Files:** `backend/app/services/pipeline/core.py`, `docs/audits/RESEARCH_FINGERPRINT_STACK_AUDIT.md`
**What:** Ensure LLM outputs go through same firewall path and update fingerprint residual wording.
**Verify:** LLM firewall test and doc review.

### Slice 5: Regression
**Status:** DONE
**Files:** tests only unless regressions found
**What:** Run targeted tests and broader verification; record any known pre-existing failures.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`

**Result:** `939 passed, 10 skipped, 11 warnings` on 2026-04-26.

## Doc Updates Required

- [x] `docs/audits/RESEARCH_FINGERPRINT_STACK_AUDIT.md` — transport residual wording.
- [x] `docs/backend-architecture.md` — persistence firewall if behavior changes.
- [ ] `docs/INVARIANTS.md` — only if a new contract is needed.

## Notes

- Latest inspected run: `run_id=3`, `ecommerce_detail`; Adidas and Under Armour persisted, Nike rejected as `challenge_shell`.
- Root cause for missing real Chrome retry: Chromium browser acquisition returned `usable_content`; extraction guard later marked `challenge_shell`.
- Root cause for public data pollution: persistence only removed empty/internal keys, not invalid surface fields or unsafe URLs.
