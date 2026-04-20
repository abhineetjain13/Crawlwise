# Stabilization Plan: 5.3 → 8.0 Average

Current scores: D1=4, D2=3, D3=2, D4=7, D5=8, D6=5, D7=6, D8=8

## Key Insight: Audit Is Partially Stale

Several flagged issues are already fixed:
- `asyncio.to_thread` for extraction (D3) — already in `pipeline/core.py:627`
- Pydantic validation for LLM payloads (D1) — already in `llm_tasks.py:107-421`
- ADP domain hardcode (D2) — already uses `url_host_matches_platform_family`
- HTTP retry/backoff (D6) — already in `crawl_fetch_runtime.py:282-308`

**Real remaining gaps are narrower than the audit suggests.**

## Phase 1: Critical (Dims 3,6 → 8)

**1A. Fix failure-task durability** — `crawl_service.py`: make failure persistence sync in callback, not fire-and-forget. Dim3: 7→8

**1B. Narrow browser-first exception** — `crawl_fetch_runtime.py:264`: `except Exception` → `except (httpx.HTTPError, OSError, TimeoutError, RuntimeError)`. Dim6: 5→7

**1C. Narrow safe_select** — `field_value_dom.py`: `except Exception` → specific selector exceptions. Dim6: 7→7.5

**1D. Fix truncation JSON fallback** — `llm_tasks.py:752`: log warning instead of bare `pass`. Dim6: 7.5→8

## Phase 2: SOLID & Config (Dims 1,2 → 8)

**2A. Flatten detail_extractor** — Extract 4 stages from `build_detail_record` into standalone testable functions. Dim1: 4→7

**2B. Centralize adapter timeouts** — Replace inline `timeout_seconds=10/12` in all ATS adapters with `adapter_runtime_settings`. Dim2: 3→6

**2C. Fix _image_candidate_score params** — Use `_CDN_IMAGE_QUERY_PARAMS` constant. Dim2: 6→7

**2D. Remove duplicate adapter DOM fallbacks** — Greenhouse/OracleHCM BS4 h1 scraping duplicates generic pipeline. Delete. Dim1: 7→8, Dim2: 7→8

## Phase 3: Tech Debt (Dim 7 → 8)

**3A. Collapse _validate_llm_field_type** — Replace hardcoded map in `pipeline/core.py:194` with field_value_core metadata. Dim7: 6→7

**3B. Simplify llm_runtime.py facade** — Remove re-exports, callers import directly. Dim7: 7→8

## Execution Order

1. Phase 1 (1A-1D) — fixes production risks
2. Phase 2 (2A-2D) — structural improvements
3. Phase 3 (3A-3B) — debt cleanup

## Predicted Outcome

| Dim | Now | After | Key fix |
|-----|-----|-------|---------|
| 1 | 4 | 8 | flatten detail_extractor + remove adapter dupes |
| 2 | 3 | 8 | centralize timeouts + image params + ADP already fixed |
| 3 | 2 | 8 | asyncio.to_thread already done + fix failure task |
| 4 | 7 | 8 | selector precedence (already improved) |
| 5 | 8 | 8 | maintain |
| 6 | 5 | 8 | narrow exceptions + retry already exists |
| 7 | 6 | 8 | collapse hardcoded validators + simplify facade |
| 8 | 8 | 8 | maintain |

**Average: 5.3 → 8.0**
