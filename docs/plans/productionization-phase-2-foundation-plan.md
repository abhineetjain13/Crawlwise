# Plan: Productionization Phase 2 - Foundation Layer

**Status:** COMPLETE
**Purpose:** Add shared typed foundations before moving god-file code.
**Primary audits:** `docs/audits/refactor-audit.md`, `docs/audits/acquisition-audit.md`, `docs/audits/pipeline-audit.md`, `docs/audits/llm-audit.md`
**Secondary audits:** `docs/audits/selfheal-audit.md`, `docs/audits/batch-audit.md`
**Scope:** Additive foundations first. No import rewiring until tests exist.

STRICT LOC DISCIPLINE:
- Every file you MODIFY must have deletions >= 50% of additions (net LOC change must be ≤ +50% of what you add).
- Every new file you CREATE must correspond to code MOVED from an existing file, not net-new logic. State which source file the code came from.
- You are not permitted to add to detail_extractor.py, field_value_core.py, field_value_dom.py, js_state_mapper.py, or crawl_fetch_runtime.py without an equal or greater deletion from the same file.
- If you cannot delete code to offset an addition, stop and explain why, do not add anyway.
- After implementation, output a table: filename | lines added | lines deleted | net change. Flag any file with net > +20 lines that was not in the task scope.

## Independent Context

The audits agree that the codebase has working behavior but weak contracts: duplicate coercion primitives, implicit field policy gates, manual domain-profile normalization, and LLM type dependencies that pull infrastructure into shared types. This phase creates canonical owners and Pydantic schemas so Phase 3 can move code without creating more small duplicate files.

Important sequencing rule: create shared foundations first, then migrate imports in later PRs. Each session should own one file or one schema family.

## Objectives

1. Create shared primitive modules used by current god-files.
2. Add Pydantic domain-profile schema with versioning.
3. Add named config constants for profile and selector staleness.
4. Clarify LLM public facade and remove type-to-infrastructure inversion.
5. Add typed extraction/output contracts where they can be introduced without rewiring hot paths.

## Audit Findings Covered

- Refactor audit: duplicate `_safe_int`, `_coerce_int`, object-list/object-dict, URL helpers, text coercers.
- Acquisition audit: no Pydantic `DomainRunProfile` / `DomainProfileV2`; silent manual coercion.
- Acquisition audit: selector and acquisition staleness thresholds are implicit.
- Pipeline audit: no explicit typed candidate or extraction-result contract.
- LLM audit: `llm_types.py` depends on `llm_circuit_breaker`; public facade is not enforced.
- Self-heal audit: no selector-health typed snapshot contract.
- Batch audit: runtime metrics dataclass exists but is unused and not a real contract.

## Non-Goals

- Do not delete original helpers in this phase.
- Do not split god-files yet.
- Do not change extraction behavior.
- Do not change persistence or export payload shape.
- Do not add remote storage.

## Implementation Slices

### Slice 1: Shared Coercion Primitives

**Files:** `app/services/shared/coerce_primitives.py`, focused tests

**Requirements:**

- Move canonical `_safe_int`, `_coerce_int`, `_object_list`, `_object_dict` into shared module.
- Export with `__all__`.
- Leave originals in place with deprecation comments only if needed for compatibility.
- Tests cover normal, null, and malformed values.

**Acceptance:**

- New module is additive.
- No existing imports change in this slice.
- Tests pass.

### Slice 2: Shared URL Utilities

**Files:** `app/services/shared/url_utils.py`, focused tests

**Requirements:**

- Add `absolute_url`, `same_host`, `extract_urls`, `_ensure_scheme`, `_is_placeholder_image_url`.
- Canonical source is existing implementations from `field_value_core.py` and `crawl_fetch_runtime.py`.
- Preserve behavior exactly.

**Acceptance:**

- Existing callers untouched.
- Tests cover relative URL, scheme repair, host comparison, malformed URL trimming, placeholder image rejection.

### Slice 3: Shared Text Coercion

**Files:** `app/services/shared/text_coerce.py`, focused tests

**Requirements:**

- Add `clean_text`, `strip_html_tags`, `coerce_text`, `coerce_long_text`, `is_title_noise`, `text_or_none`, `slug_tokens`.
- Preserve current behavior exactly.
- Keep policy decisions out of this module.

**Acceptance:**

- New module has no imports from god-files.
- Tests cover HTML stripping, whitespace normalization, title noise, slug tokens.

### Slice 4: DomainProfileV2 Pydantic Schema

**Files:** `app/services/acquisition/domain_profile_schema.py`, config constants, tests

**Requirements:**

- Add `DomainProfileV2`, `FetchProfile`, `SelectorRule`, and `AcquisitionContract` Pydantic models.
- Include `schema_version`, timestamps, selector hit/miss fields, rule staleness, and profile staleness.
- Add config constants under `app/services/config/*`:
  - `DOMAIN_PROFILE_SCHEMA_VERSION`
  - `SELECTOR_RULE_STALE_AFTER_DAYS`
  - `ACQUISITION_CONTRACT_MAX_FAILURES`
  - `FALLBACK_SURFACE`
- Add adapters to parse existing dict profiles into the schema without changing DB writes yet.

**Acceptance:**

- Existing domain-profile persistence still works.
- Invalid profile data has explicit validation errors in tests.
- Legacy profile dicts can be parsed into V2.

### Slice 5: LLM Contract Cleanup

**Files:** `app/services/llm_types.py`, `app/services/llm_circuit_breaker.py`, `app/services/llm_runtime.py`, LLM tests

**Requirements:**

- Move `LLMErrorCategory` and `classify_error` into a pure type/errors module.
- Make `llm_circuit_breaker.py` import from that pure module.
- Document `llm_runtime.py` as public facade.
- Update callers to import public LLM symbols from facade unless they are same-package internals.
- Merge provider env-key mapping with `llm_provider_catalog()`.

**Acceptance:**

- Importing `llm_types.py` does not initialize Redis/circuit-breaker infrastructure.
- Existing LLM tests pass.
- No duplicate provider mapping remains.

### Slice 6: Typed Contracts For Later Use

**Files:** `app/services/extract/contracts.py`, `app/services/domain_selector_health.py`, focused tests

**Requirements:**

- Add typed `RawCandidate`, `CandidateSet`, `ExtractionWarning`, `ExtractionResult`.
- Add `SelectorHealthSnapshot` and `CRITICAL_FIELDS_BY_SURFACE`.
- Add `RuntimeMetrics` contract or make existing `runtime_metrics.py` importable and serializable.
- Do not wire into runtime yet.

**Acceptance:**

- Contracts serialize cleanly.
- No runtime behavior changes.

## Verification

Run focused tests per slice, then:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_llm_runtime.py tests/services/test_acquisition_domain_profile_schema.py tests/services/test_shared_coerce_primitives.py tests/services/test_shared_url_utils.py tests/services/test_shared_text_coerce.py -q
.\.venv\Scripts\ruff.exe check app tests
```

## Completion Notes

Completed 2026-05-08.

- Added shared coercion primitives, URL utilities, and text coercion modules with focused tests.
- Added `DomainProfileV2`, `FetchProfile`, `SelectorRule`, `AcquisitionContract`, profile config constants, and legacy dict parsing tests.
- Moved LLM error category/classification into pure `llm_errors.py`; `llm_types.py` no longer imports circuit-breaker infrastructure.
- Consolidated provider API-key lookup and provider catalog around one provider definition list.
- Added extraction result/candidate/warning contracts, selector health snapshot, critical surface fields, and runtime metrics contract.
- Verified focused Phase 2 tests and `ruff check app tests`.

## Handoff Prompt

Implement one Phase 2 slice from `docs/plans/productionization-phase-2-foundation-plan.md`. Keep it additive unless the slice explicitly says to update imports. Do not split god-files in this session.
