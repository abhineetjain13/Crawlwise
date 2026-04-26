# CODEX_WO_QUEUE.md — CrawlerAI Backend Patch-as-Pattern & Dead Code Audit

> Audit date: 2025-04-25  
> Scope: Duplicated normalization, legacy wrappers, dead code paths, unused modules, structural debt  
> Method: grep + code reading for duplicate definitions, legacy shims, unreachable paths  

---

## 1. Patch-as-Pattern: Duplicated Normalization Logic

### 1A. `_FIELD_ALIASES` re-initialization

| File | Line | Pattern | Severity |
|------|------|---------|----------|
| `services/field_value_core.py` | 39 | `_FIELD_ALIASES = FIELD_ALIASES if isinstance(FIELD_ALIASES, dict) else {}` | MEDIUM |
| `services/field_policy.py` | 22 | `_FIELD_ALIASES = FIELD_ALIASES if isinstance(FIELD_ALIASES, dict) else {}` | MEDIUM |

**Pattern**: Both files import `FIELD_ALIASES` from `config/field_mappings.py` and then defensively re-assign it to a local `_FIELD_ALIASES` with an isinstance guard. The config export is always a dict, so the guard is dead code. The duplication means alias lookups happen through two different local caches.

### 1B. `_REQUESTED_FIELD_ALIAS_BASES` hardcodes in `field_policy.py`

| File | Lines | Pattern | Severity |
|------|-------|---------|----------|
| `services/field_policy.py` | 128-155 | `_REQUESTED_FIELD_ALIAS_BASES` dict with hardcoded field names and inline alias tuples | HIGH |

This dict mixes config-sourced aliases (`_FIELD_ALIASES.get("responsibilities", [])`) with hardcoded inline aliases:
- `"country_of_origin": ["country of origin", "country_of_origin", ...]` (lines 144-153)
- `"importer_info": ["importer", "importer_info", ...]` (lines 144-153)
- `"color_variants": _FIELD_ALIASES.get("color_variants", [])` (line 154)

These inline aliases should be in `config/field_mappings.py` exports.

### 1C. `_node_text` / `_node_attr` / `_node_css` duplication

| File | Lines | Symbol | Severity |
|------|-------|--------|----------|
| `services/listing_extractor.py` | 605-644 | `_node_text`, `_node_attr`, `_node_css` | MEDIUM |
| `services/adapters/myntra.py` | 204 | `_node_text` (different signature) | LOW |

The listing extractor defines its own DOM helper trio instead of using the shared helpers from `field_value_dom.py`. The Myntra adapter has a different `_node_text` that takes a selector argument.

### 1D. `_card_title_score` dual definition

| File | Lines | Symbol | Severity |
|------|-------|--------|----------|
| `services/listing_extractor.py` | 762 | `_card_title_score(node)` — takes a node, computes score from node text/attrs | MEDIUM |
| `services/listing_extractor.py` | 800 | `_card_title_score_parts(*, text, attrs, tag_name)` — takes decomposed parts | LOW |

Two functions with similar names but different signatures. The `_card_title_score_parts` variant exists to allow scoring without a node object, but the naming suggests they're the same function.

---

## 2. Legacy Wrappers and Compat Shims

### 2A. `_LEGACY_STATUS_MAP` in `crawl_domain.py`

| File | Lines | Symbol | Status | Severity |
|------|-------|--------|--------|----------|
| `models/crawl_domain.py` | 31-34 | `_LEGACY_STATUS_MAP = {"cancelled": KILLED, "degraded": FAILED}` | Active — `normalize_status()` uses it | LOW |

Still needed for DB rows with old status values. Not dead code, but a compat shim that should be removed once all DB rows are migrated.

### 2B. `_LEGACY_MANIFEST_KEYS` / `_LEGACY_REVIEW_KEYS` in `schemas/crawl.py`

| File | Lines | Symbol | Status | Severity |
|------|-------|--------|--------|----------|
| `schemas/crawl.py` | 456-475 | `_LEGACY_MANIFEST_KEYS`, `_LEGACY_REVIEW_KEYS` | Active — used in `_extract_manifest_trace` and `_DISCOVERED_DATA_EXCLUDE_KEYS` | MEDIUM |

These filter old provenance keys from API responses. The list grows with each deprecated key. Once all old runs age out, these can be removed.

### 2C. `_LEGACY_PROMPTS_DIR` in `llm_config_service.py`

| File | Lines | Symbol | Status | Severity |
|------|-------|--------|--------|----------|
| `services/llm_config_service.py` | 17-18 | `_LEGACY_PROMPTS_DIR = .../knowledge_base/prompts` | Active — checked as fallback in prompt loading | MEDIUM |

If the `data/knowledge_base/prompts` directory still has files, LLM will use stale prompts from the old location.

### 2D. `_legacy_artifact_paths` in `dashboard_service.py`

| File | Lines | Symbol | Status | Severity |
|------|-------|--------|--------|----------|
| `services/dashboard_service.py` | 373-376 | `_legacy_artifact_paths()` returning `backend/backend/artifacts` | Active — used in data reset | LOW |

One-time cleanup path for a double-nesting bug. Can be removed after next deployment.

---

## 3. Dead Code and Unreachable Paths

### 3A. `pipeline/persistence.py` — no external importers

| File | Lines | Symbol | Status | Severity |
|------|-------|--------|--------|----------|
| `services/pipeline/persistence.py` | 1-27 | `_object_list`, `persist_crawl_record`, etc. | No imports found outside `pipeline/core.py` | LOW |

The module is imported by `pipeline/core.py` but its `_object_list` is a local duplicate. The module itself is live but the helper is redundant.

### 3B. `services/pipeline/__init__.py` re-exports

| File | Lines | Symbol | Status | Severity |
|------|-------|--------|--------|----------|
| `services/pipeline/__init__.py` | 1-18 | Re-exports `STAGE_*`, `URLProcessingConfig`, `URLProcessingResult` | Used by `_batch_runtime.py` | LOW (live) |

No dead re-exports found.

### 3C. `GHOST_ROUTE_COMPATIBLE_SURFACES` in `network_payload_specs.py`

| File | Lines | Symbol | Status | Severity |
|------|-------|--------|--------|----------|
| `services/config/network_payload_specs.py` | 75 | `GHOST_ROUTE_COMPATIBLE_SURFACES` | Used in `network_payload_mapper.py:259` | LOW (live) |

This frozenset prevents network payload extraction when the inferred surface doesn't match the requested surface for certain compatible surfaces. Not dead code, but the name suggests it was a workaround.

### 3D. `LLMCommitItem` / `LLMCommitRequest` / `LLMCommitResponse` in `schemas/crawl.py`

| File | Lines | Symbol | Status | Severity |
|------|-------|--------|--------|----------|
| `schemas/crawl.py` | 314-323 | `LLMCommitItem(FieldCommitItem)`, `LLMCommitRequest(FieldCommitRequest)`, `LLMCommitResponse(FieldCommitResponse)` | Empty subclasses with no additional fields | MEDIUM |

These are identity subclasses that add no fields or validation. They exist as schema markers but carry no behavioral difference from their parents.

---

## 4. Structural Debt

### 4A. `CrawlRunSettings` as dict wrapper

| File | Lines | Symbol | Pattern | Severity |
|------|-------|--------|---------|----------|
| `models/crawl_settings.py` | 68-343 | `CrawlRunSettings` | `@dataclass` wrapping `data: dict[str, Any]` with 20+ accessor methods | HIGH |

This class is a typed facade over an untyped dict. Every accessor does `self.data.get(key)` with fallback defaults. The class provides type safety at the method level but the underlying dict is still `Any`. This means:
- No Pydantic validation on settings values
- No IDE autocompletion for settings keys
- Any key can be stored without validation

### 4B. `extract_records()` in `extraction_runtime.py` as god function

| File | Lines | Symbol | Pattern | Severity |
|------|-------|--------|---------|----------|
| `services/extraction_runtime.py` | 71-198 | `extract_records()` | 130-line function with 5 branching paths (XML, JSON, blocked, listing, detail) | HIGH |

This function is the single entry point for all extraction and routes based on content type and surface string. It cannot be tested in isolation because each branch has different dependencies.

### 4C. `detail_extractor.py` size

| File | Lines | Symbol | Pattern | Severity |
|------|-------|--------|---------|----------|
| `services/detail_extractor.py` | 1-3124 | entire file | 3124 lines, 50+ functions | HIGH |

The file is the largest in the codebase. It handles title extraction, price extraction, variant extraction, confidence scoring, shell detection, redirect detection, and field promotion — all in one module.

### 4D. `listing_extractor.py` size

| File | Lines | Symbol | Pattern | Severity |
|------|-------|--------|---------|----------|
| `services/listing_extractor.py` | 1-1348 | entire file | 1348 lines | MEDIUM |

Similar scope issue as detail_extractor but smaller.

---

## 5. Frontend Dead API Calls

No dead frontend API endpoints were found. All `/api/` routes defined in `frontend/lib/api/index.ts` have corresponding backend route handlers in `backend/app/api/`. No calls to removed endpoints (e.g., `/api/semantic`, `/api/knowledge`, `/api/llm-backfill`) were found.

---

## 6. Test Coverage Gaps

### 6A. Tests importing private symbols

See TYPE_VIOLATIONS.md §5 — 8 test files import private (`_`-prefixed) symbols. This creates a coupling that prevents refactoring those symbols without test changes.

### 6B. No tests found for these service modules

| Module | Approximate Lines | Severity |
|--------|-------------------|----------|
| `services/crawl_events.py` | ~260 | MEDIUM |
| `services/crawl_ingestion_service.py` | ~80 | LOW |
| `services/crawl_access_service.py` | ~50 | LOW |
| `services/domain_run_profile_service.py` | ~200 | MEDIUM |
| `services/platform_policy.py` | ~80 | LOW |
| `services/llm_cache.py` | ~100 | MEDIUM |
| `services/llm_provider_client.py` | ~150 | MEDIUM |

---

## Acceptance Grep Commands

```bash
# Duplicated _FIELD_ALIASES isinstance guard
cd backend && grep -rn "_FIELD_ALIASES = FIELD_ALIASES if isinstance" app/ --include="*.py"

# Duplicated _object_list
cd backend && grep -rn "def _object_list" app/ --include="*.py"

# Duplicated _safe_int
cd backend && grep -rn "def _safe_int" app/ --include="*.py"

# Legacy shims
cd backend && grep -rn "_LEGACY\|_legacy" app/ --include="*.py"

# Empty schema subclasses
cd backend && grep -rn "class LLMCommit" app/schemas/ --include="*.py"

# God function size
cd backend && wc -l app/services/extraction_runtime.py app/services/detail_extractor.py app/services/listing_extractor.py
```
