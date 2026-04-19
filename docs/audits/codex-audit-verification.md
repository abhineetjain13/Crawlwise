# Codex Audit Verification

Date: 2026-04-19

Scope:
- Baseline audit: `docs/audits/codex-audit.md`
- Verification target: current workspace implementation
- Validation run: `pytest backend/tests/services/test_block_detection.py backend/tests/services/test_config_imports.py backend/tests/services/test_crawl_fetch_runtime.py backend/tests/services/test_crawl_engine.py backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py backend/tests/services/test_detail_extractor_structured_sources.py backend/tests/services/test_network_payload_mapper.py backend/tests/services/test_state_mappers.py backend/tests/services/test_traversal_runtime.py backend/tests/services/test_pipeline_core.py backend/tests/services/test_review_service.py backend/tests/services/test_platform_detection.py backend/tests/services/test_job_platform_adapters.py backend/tests/services/test_structure.py`
- Result: `90 passed`

Final cleanup applied during verification:
- Removed the remaining extraction compatibility facade by deleting `backend/app/services/crawl_engine.py` and routing production callers through `backend/app/services/extraction_runtime.py`.
- Removed dead browser compatibility wrappers by deleting `backend/app/services/acquisition/browser_client.py` and `backend/app/services/acquisition/browser_pool.py`.
- Dropped the discarded `sleep_ms` parameter from `backend/app/services/crawl_fetch_runtime.py:fetch_page(...)`.
- Made pipeline provenance persistence consistent by storing `manifest_trace`, `review_bucket`, and `semantic` in `discovered_data` and as structured values in `source_trace`.
- Removed the named private compat-layer test coupling from `test_crawl_fetch_runtime.py`, `test_browser_expansion_runtime.py`, and `test_detail_extractor_priority_and_selector_self_heal.py`.

## 1. SOLID / DRY / KISS
Score: 8/10

- `crawl_fetch_runtime.py` as a god module: Fixed.
  Evidence: `backend/app/services/crawl_fetch_runtime.py` now coordinates owned modules in `backend/app/services/acquisition/runtime.py` and `backend/app/services/acquisition/browser_runtime.py`, and `backend/tests/services/test_structure.py` passes the LOC budget check.
- Mixed acquisition imports through extraction facade (`crawl_engine.py`): Fixed.
  Evidence: extraction now routes through `backend/app/services/extraction_runtime.py`, with production callers updated in `backend/app/services/pipeline/core.py`, `backend/app/services/selector_self_heal.py`, and the smoke runners.
- Thin wrappers / no-op seams: Fixed.
  Evidence: `schema_service.py:get_canonical_fields`, `schema_service.py:resolve_schema`, `acquisition/browser_client.py`, and `acquisition/browser_pool.py` are gone.

## 2. Configuration Hygiene
Score: 7/10

- Generic ADP rewrite in shared acquisition flow: Partial.
  Evidence: normalization is isolated in `backend/app/services/platform_url_normalizers.py`, but `backend/app/services/acquisition/acquirer.py` still applies it in the shared path.
- Hardcoded payload family ranking: Fixed.
  Evidence: `backend/app/services/network_payload_mapper.py:_payload_priority` uses configured endpoint families from `backend/app/services/config/network_payload_specs.py`.
- Hardcoded selector runtime surface inference: Partial.
  Evidence: `backend/app/services/selectors_runtime.py:infer_surface` still falls back to generic `"jobs"` / `"careers"` URL heuristics when platform/feld signals are absent.
- Duplicated traversal/pacing defaults: Partial.
  Evidence: `backend/app/models/crawl_settings.py` emits a normalized `AcquisitionPlan` and `fetch_page(...)` no longer carries `sleep_ms`, but overlapping defaults still exist between `backend/app/services/acquisition_plan.py` and `backend/app/services/config/runtime_settings.py`.

## 3. Scalability / Maintainability / Resource Management
Score: 8/10

- Sync filesystem writes on async hot path: Fixed.
  Evidence: `backend/app/services/pipeline/core.py:_run_persistence_stage` wraps `persist_html_artifact(...)` in `asyncio.to_thread(...)`.
- Per-request `httpx.AsyncClient` creation: Fixed.
  Evidence: `backend/app/services/acquisition/http_client.py` and `backend/app/services/acquisition/runtime.py` reuse shared async clients keyed by proxy/family.
- Decorative pacing API: Fixed.
  Evidence: `backend/app/services/acquisition/pacing.py` implements host-slot pacing and adapter requests call `wait_for_host_slot(...)`.
- Browser host preference map only grew: Fixed.
  Evidence: `backend/app/services/acquisition/browser_runtime.py` timestamps and prunes remembered hosts via `prune_browser_preferred_hosts(...)`.
- Oversized runtime file / responsibility spread: Fixed.
  Evidence: the old monolith is split and `backend/tests/services/test_structure.py::test_service_files_stay_under_loc_budget` passes.

## 4. Extraction & Normalisation Pipeline
Score: 8/10

- JS state outranking JSON-LD / microdata / Open Graph: Fixed.
  Evidence: `backend/app/services/detail_extractor.py:_SOURCE_PRIORITY` and `build_detail_record(...)` apply structured sources before `js_state`.
- Workday hydrated-state extractor missing: Fixed.
  Evidence: `backend/app/services/config/platforms.json` defines Workday `js_state_extractors`, consumed by `backend/app/services/js_state_mapper.py`.
- Recognized payload families without concrete mappers: Fixed.
  Evidence: `backend/app/services/config/network_payload_specs.py` contains concrete `workday_detail` and `lever_detail` mappings used by `backend/app/services/network_payload_mapper.py`.
- Selector self-heal persisted before proof of improvement: Fixed.
  Evidence: `backend/app/services/selector_self_heal.py:apply_selector_self_heal(...)` only saves synthesized selectors after `_selector_heal_improved_record(...)` passes.
- Listing extraction ignored microdata / Open Graph / hydrated state: Fixed.
  Evidence: `backend/app/services/listing_extractor.py:extract_listing_records(...)` now includes JSON-LD, microdata, Open Graph, embedded JSON, and harvested JS state.
- Provenance payload too thin for export contracts: Fixed.
  Evidence: `backend/app/services/pipeline/core.py` now persists `manifest_trace`, `review_bucket`, and `semantic` into both `source_trace` and `discovered_data` as structured values.
- Image extraction accepted obvious garbage: Fixed.
  Evidence: `backend/app/services/field_value_dom.py:extract_page_images(...)` filters analytics, tracking, pixel, spacer, and related-detail image noise.

## 5. Traversal Mode Audit
Score: 8/10

- Missing explicit handling for `single`, `sitemap`, and `crawl`: Fixed.
  Evidence: `backend/app/services/crawl_utils.py:resolve_traversal_mode(...)` recognizes those values and `backend/app/services/acquisition/traversal.py:should_run_traversal(...)` explicitly disables browser traversal for them.
- Fragment-only paginator links not filtered: Fixed.
  Evidence: `backend/app/services/acquisition/traversal.py:_run_paginate_traversal(...)` stops with `paginate_fragment_only`.
- Traversal failures silently degraded to empty behavior: Partial.
  Evidence: `_find_actionable_locator(...)`, `_card_count(...)`, and `_wait_for_domcontentloaded(...)` now log failure context and emit clearer stop reasons, but they still continue after broad exceptions instead of surfacing explicit traversal failures to callers.

## 6. Resilience & Error Handling
Score: 8/10

- `listing_extractor` broad `except Exception: pass`: Fixed.
  Evidence: `backend/app/services/listing_extractor.py:_prepare_listing_dom(...)` logs debug information instead of silently passing.
- Traversal locator/card-count broad catches: Partial.
  Evidence: `backend/app/services/acquisition/traversal.py` still uses broad `except Exception` in a few selector/card-count checks, although it now logs context.
- `_mark_run_failed` swallowed SQLAlchemy failures: Fixed.
  Evidence: `backend/app/services/pipeline/core.py:_mark_run_failed(...)` logs rollback failures, retries via `SessionLocal`, and logs fallback persistence failures.
- LLM provider JSON decode path unguarded: Fixed.
  Evidence: `backend/app/services/llm_provider_client.py:_safe_json_response(...)` guards malformed provider JSON and `call_provider(...)` catches `ValueError`.
- 4xx and 5xx treated as the same downstream class: Fixed.
  Evidence: `backend/app/services/acquisition/runtime.py:is_non_retryable_http_status(...)` and `backend/app/services/crawl_fetch_runtime.py:fetch_page(...)` separate non-retryable 4xx responses from retryable failures.
- Fake `ProxyPoolExhausted` after direct-connect failure: Fixed.
  Evidence: `backend/app/services/crawl_fetch_runtime.py:fetch_page(...)` threads proxy attempts end-to-end and `backend/app/services/acquisition/acquirer.py` only raises `ProxyPoolExhausted` after proxied acquisition fails.

## 7. Dead Code & Technical Debt Hotspots
Score: 8/10

- Hollow schema/review persistence shell: Fixed.
  Evidence: `backend/app/services/schema_service.py` now owns only `load_resolved_schema(...)` and trace helpers; the misleading compatibility `resolve_schema(...)` wrapper is gone, while `backend/app/services/review/__init__.py:save_review(...)` persists `ReviewPromotion`.
- Dead wrappers / false API surface: Fixed.
  Evidence: `backend/app/services/acquisition/browser_client.py`, `backend/app/services/acquisition/browser_pool.py`, `backend/app/services/acquisition/acquirer.py:scrub_network_payloads_for_storage(...)`, and `detect_blocked_page(...)` are gone.
- `crawl_state.py` lingering TODO in status transition path: Fixed.
  Evidence: `backend/app/services/crawl_state.py:update_run_status(...)` clears progress counters without the old TODO stub.
- Tests importing private compatibility-layer helpers directly: Fixed.
  Evidence: the previously named audit offenders now target owned/public modules instead of deleted compat-layer helpers.

## 8. Acquisition Mode Audit & Site Coverage
Score: 7/10

- `proxy_list` dropped at runtime boundary: Fixed.
  Evidence: `backend/app/services/crawl_fetch_runtime.py:fetch_page(...)` normalizes proxy lists and iterates proxy attempts across browser and non-browser fetchers.
- Config promised adapters that registry could not serve: Fixed.
  Evidence: `backend/app/services/adapters/registry.py` now registers Workday, and detection-only families such as Lever/Rippling are not declared as adapter-backed in `backend/app/services/config/platforms.json`.
- Hydrated-state coverage incomplete for routed job platforms: Partial.
  Evidence: Workday is covered, but Rippling remains detection-only with no adapter or JS-state extractor.
- Workday / Lever payload families boosted but not mapped: Fixed.
  Evidence: `backend/app/services/config/network_payload_specs.py` contains concrete `workday_detail` and `lever_detail` mappings consumed by `backend/app/services/network_payload_mapper.py`.
- ADP normalization still lives in shared acquisition routing: Partial.
  Evidence: `backend/app/services/acquisition/acquirer.py` still calls `normalize_platform_acquisition_url(...)` instead of pushing this entirely into adapter-owned planning.

## Final Score
Overall Score: 8.0/10

Score basis:
- The remaining compatibility facades and dead wrapper surfaces called out by the prior verification pass are now removed.
- Runtime, extraction, provenance persistence, proxy threading, pacing, and shared-client reuse are materially improved and test-backed.
- The highest-value remaining debt is now concentrated in platform-owned planning boundaries and traversal error semantics rather than dead code or false API surfaces.

Residual highest-value follow-ups:
- Move ADP normalization fully out of shared acquisition routing into adapter-owned planning.
- Tighten `selectors_runtime.infer_surface(...)` so generic `"jobs"` / `"careers"` URL heuristics are replaced by a more explicit signal hierarchy.
- Decide whether the overlapping defaults in `acquisition_plan.py` and `config/runtime_settings.py` should be collapsed into one authoritative source.
- Promote traversal selector/card-count failures into explicit traversal outcomes instead of logging and continuing.
