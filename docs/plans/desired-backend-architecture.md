# CrawlerAI: Desired Backend Architecture

> **Type:** Prescriptive target state. Grounded in actual codebase audit (2026-04-11).
> **Authority:** Where this doc conflicts with existing code, the code is wrong.
> **Invariants:** All 25 rules in `docs/INVARIANTS.md` remain fully binding.

---

## Normalization and Noise Ownership

This target state is only correct if normalization and noise reduction are treated as first-class architectural concerns.

- Listing and detail remain separate orchestration paths, but they do **not** get separate duplicate normalization or sanitization stacks.
- Shared canonical normalization and generic noise rules must have one owner and one config model.
- Surface-specific overrides are allowed only when listing/detail behavior genuinely differs.
- Generic concerns such as UI noise stripping, site-chrome detection, footer/legal/contact/share suppression, candidate sanitization, and noisy attribute rejection must be consolidated instead of being reimplemented across `extract/`, `pipeline/`, semantic helpers, and `normalizers/`.

Package boundary rules for this target state:

- `extract/` and `acquisition/` are strict package APIs. External callers import from package `__init__.py`, not internal submodules.
- `pipeline/` remains a small public facade, not a package-wide re-export surface.

Deletion policy for this document:

- Items in the deletion manifest that still have live production callers move to a later proof-based deletion phase. They are not preserved permanently, but they are also not deleted speculatively.

This document is paired with [2026-04-11-backend-structural-consolidation-and-noise-ownership-plan.md](./2026-04-11-backend-structural-consolidation-and-noise-ownership-plan.md), which is the execution tracker for this consolidation work.

---

## What Changes, What Stays, What Gets Deleted

### STAYS — No structural change needed
- `app/api/` — all 7 routers are correct and complete
- `app/core/` — config, database, redis, security, dependencies, telemetry, metrics
- `app/models/` — keep all (LLMCostLog still used for tracking even with no config API)
- `app/schemas/crawl.py`, `user.py`, `common.py`
- `services/acquisition/` — acquirer, http_client, traversal, strategies, session_context, pacing, blocked_detector, cookie_store, browser_runtime
- `services/adapters/` — all 15 platform adapters + base + registry
- `services/normalizers/`
- `services/config/`

### GETS DELETED — Dead code, deleted features, duplicates
See deletion manifest below. Every item in this list is removed with no replacement once the owning callers have been eliminated or redirected.

### GETS RESTRUCTURED — God files decomposed, pipeline surface collapsed
- `services/pipeline/__init__.py` — collapsed from 150+ exports to ≤20
- `services/extract/service.py` (5,167 lines) → decomposed into sub-modules
- `services/extract/listing_extractor.py` (3,524 lines) → decomposed into sub-modules
- `services/acquisition/browser_client.py` (2,583 lines) → decomposed into sub-modules

---

## Deletion Manifest — Complete, No Exceptions

The agent MUST delete every item in this list. No item may be preserved "for safety", wrapped in a shim, or moved to a new name. If a caller breaks, fix the caller — do not keep the dead file.

### Duplicate Files in `services/` (filesystem duplicates / shadowed imports)
```
services/crawl_crud.py          ← appears twice. Keep one canonical copy, delete the duplicate.
services/crawl_access_service.py ← appears twice. Keep one, delete duplicate.
services/auth_service.py        ← appears twice. Keep one, delete duplicate.
```

### Duplicate Files in `services/pipeline/`
```
services/pipeline/listing_helpers.py  ← appears twice. Keep one, delete duplicate.
services/pipeline/rendering.py        ← appears twice. Keep one, delete duplicate.
```

### Dead Subsystems (Invariant 24)
```
services/knowledge_base/store.py   ← EMPTY FILE. Feature was deleted. Delete file + directory.
services/knowledge_base/           ← Delete entire directory.
services/host_memory.py            ← Redis-backed per-host preferences = site memory under a new name. Delete.
services/semantic_detail_extractor.py ← Separate LLM path outside pipeline/llm_integration.py. Delete.
                                       LLM calls belong in pipeline/llm_integration.py only.
services/xpath_service.py          ← XPath extraction. Audit callers. If no active pipeline caller, delete.
services/schema_service.py         ← resolve_schema(). Audit callers. If only called from deleted selector
                                       feature, delete.
services/shared_acquisition.py     ← acquire() is owned by acquisition/acquirer.py. If this is a wrapper
                                       or second entry point, delete. One acquisition entry point.
```

These deletions are proof-based:

- if a module still has live production callers, first migrate or remove those callers
- do not preserve dead subsystems behind shims
- do not delete live modules speculatively during structural cleanup

### Dead Schema
```
app/schemas/llm.py  ← LLM config CRUD schema. No LLM config API exists or will exist. Delete.
```

### No New API Routes
The frontend currently calls `/api/selectors/*` and `/api/llm/configs`. These are deleted features.
**DO NOT add these routes.** The frontend will be fixed to remove those calls instead.

---

## Target Directory Layout

```
backend/
└── app/
    ├── main.py                         # FastAPI entry, 7 routers — UNCHANGED
    ├── tasks.py
    ├── api/                            # UNCHANGED — all 7 routers correct
    │   ├── auth.py, crawls.py, records.py, review.py
    │   ├── dashboard.py, jobs.py, users.py
    ├── core/                           # UNCHANGED
    ├── models/                         # UNCHANGED
    ├── schemas/                        # DELETE schemas/llm.py only
    │
    └── services/
        ├── auth_service.py             # DEDUPLICATED — one canonical file
        ├── user_service.py
        ├── crawl_service.py
        ├── crawl_crud.py               # DEDUPLICATED — one canonical file
        ├── crawl_ingestion_service.py
        ├── crawl_access_service.py     # DEDUPLICATED — one canonical file
        ├── crawl_state.py
        ├── crawl_events.py
        ├── crawl_metrics.py
        ├── crawl_metadata.py
        ├── crawl_utils.py
        ├── run_summary.py
        ├── record_export_service.py
        ├── dashboard_service.py
        ├── url_safety.py
        ├── domain_utils.py
        ├── db_utils.py
        ├── exceptions.py
        ├── llm_service.py
        ├── llm_runtime.py
        ├── requested_field_policy.py
        ├── resource_monitor.py
        │
        ├── config/                     # UNCHANGED
        ├── normalizers/                # UNCHANGED
        ├── adapters/                   # UNCHANGED
        │
        ├── acquisition/
        │   ├── __init__.py             # PUBLIC surface — new
        │   ├── acquirer.py             # SOLE acquire() entry point
        │   ├── http_client.py
        │   ├── browser_client.py       # Core fetch + expand (~500 lines after decomp)
        │   ├── browser_pool.py         # [NEW] Pool lifecycle extracted from browser_client
        │   ├── browser_challenge.py    # [NEW] Anti-bot detection extracted from browser_client
        │   ├── browser_readiness.py    # [NEW] Page readiness (replaces browser_page_wait.py)
        │   ├── browser_navigation.py   # [NEW] goto_with_fallback, nav strategies
        │   ├── browser_runtime.py
        │   ├── blocked_detector.py
        │   ├── cookie_store.py
        │   ├── pacing.py
        │   ├── strategies.py
        │   ├── traversal.py
        │   └── session_context.py
        │
        ├── extract/
        │   ├── __init__.py             # PUBLIC surface — new
        │   ├── service.py              # extract_candidates() entry (~200 lines after decomp)
        │   ├── candidate_processing.py # [NEW] coerce, sanitize, finalize
        │   ├── field_classifier.py     # EXISTS — verify scope matches responsibility
        │   ├── variant_extractor.py    # EXISTS — verify scope matches responsibility
        │   ├── dom_extraction.py       # [NEW] live DOM label-value, breadcrumb
        │   ├── listing_extractor.py    # extract_listing_records() entry (~400 lines after decomp)
        │   ├── listing_card_extractor.py       # [NEW] card detection + scoring
        │   ├── listing_structured_extractor.py # [NEW] JSON-LD, Next.js, hydrated state
        │   ├── listing_quality.py      # EXISTS
        │   ├── listing_normalize.py    # EXISTS
        │   ├── listing_identity.py     # EXISTS
        │   ├── json_extractor.py       # EXISTS
        │   ├── source_parsers.py       # EXISTS
        │   ├── field_decision.py       # EXISTS
        │   ├── signal_inventory.py     # EXISTS
        │   └── extractability.py      # EXISTS
        │
        └── pipeline/
            ├── __init__.py             # COLLAPSED to ≤20 exports (see below)
            ├── core.py
            ├── runner.py
            ├── stages.py
            ├── types.py
            ├── utils.py
            ├── field_normalization.py
            ├── listing_helpers.py      # DEDUPLICATED — one file
            ├── verdict.py
            ├── trace_builders.py
            ├── rendering.py            # DEDUPLICATED — one file
            ├── review_helpers.py
            ├── llm_integration.py      # SOLE LLM call site in entire codebase
            └── pipeline_config.py
```

---

## Pipeline `__init__.py`: Narrow Public Facade

**Current problem:** `pipeline/__init__.py` must remain a narrow facade. It must not become a hidden god module that lets any caller import anything without knowing where it lives.

**Target:**
```python
# pipeline/__init__.py — ≤20 symbols, typed only
from app.services.pipeline.core import process_run_urls
from app.services.pipeline.types import (
    URLProcessingConfig,
    URLProcessingResult,
    PipelineContext,
)
from app.services.pipeline.verdict import (
    VERDICT_SUCCESS,
    VERDICT_PARTIAL,
    VERDICT_FAILED,
    VERDICT_LISTING_DETECTION_FAILED,
    compute_verdict,
)
from app.services.pipeline.pipeline_config import PipelineConfig
```

`pipeline/__init__.py` is the exception to the strict package rule: it remains a deliberately small facade for a handful of stable pipeline-facing symbols. It must not grow into a broad re-export surface again.

---

## Package Public Surfaces

### `extract/__init__.py`
```python
from app.services.extract.service import extract_candidates, candidate_source_rank
from app.services.extract.candidate_processing import (
    coerce_field_candidate_value,
    finalize_candidate_row,
    sanitize_field_value,
    sanitize_field_value_with_reason,
)
from app.services.extract.listing_extractor import extract_listing_records
```

Until `candidate_processing.py` exists, these functions may remain sourced from `service.py`, but the external package surface stays the same.

### `acquisition/__init__.py`
```python
from app.services.acquisition.acquirer import acquire
from app.services.acquisition.browser_client import (
    BrowserResult,
    fetch_rendered_html,
    expand_all_interactive_elements,
)
```

`browser_pool` exports are deferred until `browser_pool.py` exists as its own module.

**Rule:** No caller outside `extract/` or `acquisition/` may import from internal sub-modules. If a function is needed externally, promote it to package `__init__.py`.

---

## Authoritative API Route List (No Additions)

| Route prefix | File | Status |
|-------------|------|--------|
| `/api/auth/*` | `api/auth.py` | ✅ Correct |
| `/api/crawls/*` | `api/crawls.py` | ✅ Correct |
| `/api/crawls/{id}/records` | `api/records.py` | ✅ Correct |
| `/api/review/*` | `api/review.py` | ✅ Correct |
| `/api/dashboard/*` | `api/dashboard.py` | ✅ Correct |
| `/api/jobs/*` | `api/jobs.py` | ✅ Correct |
| `/api/users/*` | `api/users.py` | ✅ Correct |
| `/api/selectors/*` | — | 
| `/api/llm/configs` | — | 

---

## What Must Not Return (Invariant 24)

| Deleted thing | Forbidden aliases |
|--------------|------------------|
| `host_memory.py` | `site_preferences.py`, `domain_state.py`, `host_prefs.py` |
| `knowledge_base/` | `selector_store/`, `extraction_memory/`, `site_knowledge/` |
| `semantic_detail_extractor.py` | `llm_extractor.py` (LLM lives in `pipeline/llm_integration.py` only) |
| `shared_acquisition.py` | `acquisition_facade.py`, `acquire_helpers.py` |
| Selector CRUD API | Any `/api/selectors` route variant |
| LLM config API | Any `/api/llm` route variant |
