# TYPE_VIOLATIONS.md — CrawlerAI Backend Type Contract Audit

> Audit date: 2025-04-25  
> Scope: Type annotations, defensive coercions, None-safety, and contract breaches  
> Method: grep + code reading for `coerce_`, `ensure_`, `safe_`, `Optional`, `| None`, `isinstance` guards  

---

## 1. Defensive Coercion Helpers — Masking Upstream Contract Breaches

### 1A. `coerce_*` family in `field_value_core.py`

| Symbol | Line | Signature | Contract Assumption | Actual Caller Pattern |
|--------|------|-----------|---------------------|----------------------|
| `coerce_text` | 491 | `(value: object) -> str \| None` | callers may pass non-str | called on `payload.get("name")`, `payload.get("title")` which should already be str | 
| `coerce_structured_scalar` | 537 | `(value: object, *, keys: tuple[str,...]) -> str \| None` | value may be dict | called on structured source payloads |
| `coerce_location` | 582 | `(value: object) -> str \| None` | value may be dict with "address" | called on location fields |
| `coerce_variant_axes` | 694 | `(value: object) -> dict[str, list[str]] \| None` | value may be non-dict | called on variant_axes from JS state |
| `coerce_product_attributes` | 723 | `(value: object) -> dict[str, object] \| None` | value may be non-dict | called on product attributes |
| `coerce_availability_dict` | 768 | `(value: object) -> str \| None` | value may be dict | called on availability fields |
| `coerce_field_value` | 788 | `(field_name: str, value: object, page_url: str) -> object \| None` | universal fallback | called on any field from any source |
| `coerce_content_length` | 490 (browser_capture.py) | `(headers) -> int \| None` | headers may lack content-length | called on response headers |

**Classification**: These are **necessary boundary guards** at the extraction↔external-data boundary. The JS state and network payloads are untrusted. However, `coerce_text` and `coerce_field_value` are also called on **internal** data (e.g., `listing_extractor.py:106` `coerce_text(payload.get("name"))`) where the type should already be known. This indicates the internal type contract is not enforced upstream.

**Severity**: MEDIUM — coercions at external boundaries are correct; coercions on internal data mask missing type enforcement.

### 1B. Schema-layer `isinstance` guards (dual validation)

| File | Lines | Guard | What It Masks |
|------|-------|-------|---------------|
| `schemas/crawl.py` | 63-66 | `@field_validator _coerce_dict_payload` | ORM producing non-dict for `data`, `raw_data`, `discovered_data`, `source_trace` |
| `schemas/crawl.py` | 69-76 | `@model_validator _normalize_record_payloads` | Same 4 fields re-checked (field_validator already ran) |
| `schemas/crawl.py` | 346-353 | `CrawlRecordProvenanceResponse._expand_provenance` | Same 3 fields checked a third time |

**Root cause**: The ORM model (`CrawlRecord`) declares `data: dict`, `raw_data: dict`, etc., but the database column may contain JSON that deserializes to a non-dict (e.g., `None`, `list`, `str`). The dual guard is a workaround for SQLAlchemy's relaxed JSON column typing.

**Severity**: HIGH — three layers of isinstance guard on the same fields indicates the ORM→schema contract is broken.

---

## 2. `None` on Non-Optional Parameters

### 2A. `URLProcessingConfig.record_writer: object | None`

| File | Line | Declaration | Usage |
|------|------|-------------|-------|
| `services/pipeline/types.py` | 35 | `record_writer: object \| None = None` | Checked at call sites with `if record_writer is not None` |

**Severity**: LOW — properly typed as Optional.

### 2B. `LLMTaskResult.payload: dict | list | None`

| File | Line | Declaration | Usage |
|------|------|-------------|-------|
| `services/llm_types.py` | 10 | `payload: dict \| list \| None` | Callers must check for None |

**Severity**: LOW — properly typed as Optional, but the union of three types (dict | list | None) is broad. Callers that assume dict will fail on list.

### 2C. `AcquisitionPlan` fields with `None` defaults

| File | Lines | Pattern |
|------|-------|---------|
| `services/acquisition_plan.py` | (multiple) | `traversal_mode: str | None = None`, `proxy_list: tuple[str,...] | None = None` |

**Severity**: LOW — these are legitimately optional at construction time.

---

## 3. `Any` Type Escapes

| File | Line | Symbol | Type | Severity |
|------|------|--------|------|----------|
| `services/pipeline/types.py` | 12 | `URLProcessingResult.records` | `list[dict]` (untyped dict) | MEDIUM |
| `services/pipeline/types.py` | 14 | `URLProcessingResult.url_metrics` | `dict[str, Any]` | MEDIUM |
| `services/llm_types.py` | 10 | `LLMTaskResult.payload` | `dict | list | None` (untyped containers) | MEDIUM |
| `services/detail_extractor.py` | (all functions) | `record: dict[str, Any]` | pervasive `Any` in record dicts | HIGH |
| `services/listing_extractor.py` | (all functions) | `record: dict[str, Any]` | pervasive `Any` in record dicts | HIGH |
| `services/extraction_runtime.py` | 71-84 | `extract_records() -> list[dict]` | completely untyped return | HIGH |

**Classification**: The extraction pipeline operates on `dict[str, Any]` throughout. This is a structural choice (records are dynamic), but it means no type checker can verify field access. The `extract_records()` return type `list[dict]` (no key/value types) is the weakest point.

**Severity**: HIGH for extraction pipeline; MEDIUM for peripheral modules.

---

## 4. `# type: ignore` Catalog

See DEBT_INVENTORY.md §5 — all instances are for optional/untyped third-party imports. **No internal type contract is suppressed.**

---

## 5. Test Imports of Private Symbols

| Test File | Line | Imported Symbol | Severity |
|-----------|------|-----------------|----------|
| `tests/services/test_traversal_runtime.py` | 1004, 1018, 1032, 1046 | `_is_same_origin` | LOW (test-only) |
| `tests/services/test_records_api.py` | 8 | `_route_responses` | LOW (test-only) |
| `tests/services/test_publish_metrics.py` | 5 | `_stringify_value` | LOW (test-only) |
| `tests/services/test_pacing.py` | 6 | `_normalized_host` | LOW (test-only) |
| `tests/services/test_detail_extractor_structured_sources.py` | 9 | `_variant_option_availability` | LOW (test-only) |
| `tests/services/test_crawl_engine.py` | 11 | `_normalize_variant_record` | LOW (test-only) |
| `tests/services/test_crawls_api_domain_recipe.py` | 8 | `_domain_run_profile_payload` | LOW (test-only) |
| `tests/services/test_selectors_runtime.py` | 7 | `_coerce_int` | LOW (test-only) |

Tests importing private symbols means those symbols cannot be renamed or removed without breaking tests. This is standard but worth noting for refactoring.

---

## Acceptance Grep Commands

```bash
# Defensive isinstance guards on dict fields
cd backend && grep -rn "isinstance.*dict.*else {}" app/ --include="*.py"

# coerce_ helpers
cd backend && grep -rn "def coerce_" app/ --include="*.py"

# Any type in signatures
cd backend && grep -rn "dict\[str, Any\]" app/services/ --include="*.py" | head -30

# list[dict] untyped returns
cd backend && grep -rn "list\[dict\]" app/ --include="*.py"
```
