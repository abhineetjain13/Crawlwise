# Phase 2 Stability Cleanup Tracker

Date: 2026-04-12
Scope: `backend/app/services/**`, `backend/app/core/config.py`, invariants from `docs/INVARIANTS.md`
Goal: convert the post-refactor audit into a concrete cleanup backlog focused on magic values, configuration sprawl, SOLID/DRY boundary issues, and shared-kernel extraction logic.

## Executive Readout

- Existing typed config coverage is materially better than before. `backend/app/services/config/runtime_settings.py` and `backend/app/services/config/llm_runtime.py` already centralize many crawler tunables.
- The original instability pattern has been materially reduced. The major config-sprawl and shared-kernel issues identified in this audit have now been implemented in code.
- The pipeline decomposition is now live code, not abandoned scaffolding. `backend/app/services/pipeline/core.py` executes `PipelineRunner` with concrete stages from `runner.py` and `stages.py`; the remaining debt is inside extraction/detail boundaries, not a parallel unused pipeline architecture.
- The extraction stage path now consumes `PipelineContext` directly via context-aware flow wrappers. Parameter inflation still exists in retry/fallback branches, but the primary `ExtractStage` path no longer explodes context into a 10+ argument manual call chain.
- Batch progress persistence no longer lives on the progress state model object. `BatchRunProgressState` remains stateful/pure, while persistence helpers now live in `app.services._batch_progress`.
- `backend/app/services/acquisition/strategies.py` exists and defines an extensible acquisition chain, but the live `acquire()` path still routes through `_acquire_once`; the acquisition waterfall remains the largest SRP hotspot.
- The worst internal parameter-count hotspots have been collapsed into request objects on the live path:
  - `traversal.apply_traversal_mode()` now accepts `TraversalRequest`
  - `traversal.collect_paginated_html()` now accepts `PaginationTraversalRequest`
  - `browser_client._fetch_rendered_html_attempt()` now accepts `_BrowserRenderAttempt`
  - `acquirer._acquire_once()` now accepts `_AcquireExecutionRequest`
- `_acquire_once()` is no longer carrying the full waterfall inline. Browser-first acceptance, curl result extraction, and browser-finalization/fallback logic now live in dedicated helpers under the same module, which makes the acquisition path materially less monolithic even before the strategy chain becomes the runtime entrypoint.
- `listing_extractor.py` now uses a `ListingExtractionRequest` plus explicit phase helpers (`_extract_paginated_listing_records`, `_collect_raw_listing_record_sets`, `_merge_listing_record_sets`) so the listing path reads as phase composition instead of one long procedural block.
- The largest architecture risk is not one catastrophic bug. It is the combination of:
  - residual heuristic regex/policy drift in extraction modules,
  - partially typed variant candidate boundaries,
  - remaining sanitization/normalization overlap between `noise_policy.py` and `normalizers/__init__.py`,
  - unverified integration surface outside the narrow tests run during cleanup.

## Audit Tracker

### T1. Centralize remaining magic values into typed settings
Status: Mostly completed
Priority: Critical
Primary invariants: `#1 No magic values in service code`, `#3 Pipeline config is the single source of truth`

#### Hardcoded acquisition and traversal thresholds

| Reference | Hardcoded value(s) | Problem | Recommended home |
| --- | --- | --- | --- |
| `backend/app/services/acquisition/acquirer.py:88-98` | `100_000`, `0.15`, `2`, `8`, `60 * 60`, `1024` | JS-shell detection and proxy backoff/storage policy live in service code rather than typed settings. | `CrawlerRuntimeSettings` or `pipeline_config.py` |
| `backend/app/services/acquisition/acquirer.py:1144-1145` | `max_candidates = 2` | Iframe promotion cap is a tweakable extraction heuristic. | `CrawlerRuntimeSettings` |
| `backend/app/services/acquisition/acquirer.py:1442-1445` | `< 1000`, `>= 2` | Browser fallback trigger mixes typed config with local thresholds. | `CrawlerRuntimeSettings` |
| `backend/app/services/acquisition/acquirer.py:1626`, `1636` | `< 1000` | Browser escalation still depends on service-local visible text threshold. | reuse runtime setting |
| `backend/app/services/acquisition/acquirer.py:1874` | `poll_ms = 250` | Cooperative sleep poll interval is hidden in service code. | `CrawlerRuntimeSettings` |
| `backend/app/services/acquisition/acquirer.py:2134-2147` | `> 0.8`, `>= 2`, `>= 15`, `>= 4` | Extractability classification is entirely heuristic but not typed/configurable. | dedicated extractability settings |
| `backend/app/services/acquisition/acquirer.py:2469` | `browser_successes >= 2 and curl_successes == 0` | Browser preference memory threshold is magic policy logic. | acquisition policy settings |
| `backend/app/services/acquisition/traversal.py:151`, `164`, `205` | `500`, `3`, `>= 2` | Infinite-scroll detector heuristics are embedded in JS/service code. | traversal settings |
| `backend/app/services/acquisition/traversal.py:1336`, `1341`, `1349-1350` | `1500`, `5000`, `250`, `3000` | Pagination click and settle timings bypass runtime config. | traversal/browser settings |
| `backend/app/services/acquisition/traversal.py:1407` | `min(..., 50)` | Scroll cap is a hidden limiter outside typed settings. | reuse `default_max_scrolls` + explicit max cap |
| `backend/app/services/acquisition/traversal.py:1428`, `1495`, `1567`, `1735` | `max(500, request_delay_ms)`, `500`, `>= 2` | Scroll/load-more pacing and weak-progress cutoffs are hardcoded. | traversal settings |
| `backend/app/services/acquisition/traversal.py:1596`, `1608`, `1613`, `1616`, `1621` | `links * 2`, `> 150`, `slice(0, 120)`, `600` | DOM scoring for active scroll container is frozen in inline JS. | traversal scoring settings |

#### Hardcoded adapter thresholds

| Reference | Hardcoded value(s) | Problem | Recommended home |
| --- | --- | --- | --- |
| `backend/app/services/adapters/shopify.py:70`, `73` | `limit=250` | Public catalog fetch size is adapter policy, not config. | adapter runtime settings |
| `backend/app/services/adapters/shopify.py:79` | `timeout_seconds=6` | Network timeout bypasses config. | adapter/acquisition settings |
| `backend/app/services/adapters/shopify.py:263-274` | `range(1, 4)` | Assumes max three variant axes inline. | adapter setting or shared variant policy |
| `backend/app/services/adapters/shopify.py:352` | `axis_name == "size"` | Domain rule is valid, but currently hardcoded and duplicated conceptually with variant extractor truthy axes. | shared variant policy |
| `backend/app/services/adapters/icims.py:89-95` | `range(0, 1000, 100)`, timeout `15` | Pagination depth, page size, and timeout are service-local. | adapter runtime settings |
| `backend/app/services/adapters/icims.py:223`, `263` | `len(title) < 3` | Minimum title quality gate is a tweakable heuristic. | listing/job extraction settings |

#### Hardcoded extraction heuristics

| Reference | Hardcoded value(s) | Problem | Recommended home |
| --- | --- | --- | --- |
| `backend/app/services/extract/listing_card_extractor.py:46-47` | `0.45`, `500` | Card detection ratio and regex input cap are local constants. | listing extraction settings |
| `backend/app/services/extract/listing_card_extractor.py:97`, `107`, `130`, `214`, `244` | `min_group_size = 2`, `len(found) >= 2` | Minimum sibling/group thresholds are duplicated and untyped. | listing extraction settings |
| `backend/app/services/extract/listing_card_extractor.py:796`, `798`, `832`, `878`, `914`, `1017`, `1213`, `1238` | `<= 40`, `<= 60`, `> 80`, `> 120`, `<= 40`, `> 40`, depth `6`, list slice `40` | Many title/location/salary/path recursion heuristics are uncatalogued. Most high-signal scoring and title-length gates have already been moved into extraction settings. | listing extraction settings |
| `backend/app/services/extract/json_extractor.py:29` | `max_records = 100` | Default max record count duplicates runtime defaults. | reuse typed runtime setting |
| `backend/app/services/extract/json_extractor.py:234` | `max_depth=4` | Alias lookup depth is a hidden extraction limit. | extraction settings |
| `backend/app/services/extract/json_extractor.py:305`, `310-325`, `492`, `554` | sample `5`, weights `3/3/4/2`, list caps `40/20` | Candidate-array scoring and traversal depth are hardcoded. | extraction settings |
| `backend/app/services/extract/source_parsers.py:289-297` | weighted field map `3/2/1/...` | DataLayer payload scoring is local only. | extraction settings |
| `backend/app/services/extract/source_parsers.py:580`, `592`, `634-638`, `647`, `668`, `892` | max depths `5`, sample `5`, thresholds `2/1/3`, heading limit `6` | Embedded blob classification thresholds are not centralized. | extraction settings |
| `backend/app/services/llm_runtime.py:104-105` | `5`, `120` | Circuit breaker policy is not typed. | `LLMRuntimeSettings` |
| `backend/app/services/llm_runtime.py:278` | token limit `5600` | Prompt safety cap is not typed. | `LLMRuntimeSettings` |
| `backend/app/services/llm_runtime.py:656-657` | retries `1`, delay `0.0` | Retry policy default is local. | `LLMRuntimeSettings` |
| `backend/app/services/llm_runtime.py:722`, `751`, `788` | `timeout=30.0` | Provider HTTP timeout is duplicated in three clients. | `LLMRuntimeSettings` |
| `backend/app/services/llm_runtime.py:956`, `998-999`, `1015`, `1042-1043`, `1090-1092`, `1162`, `1170`, `1175`, `1182` | `40`, `100`, `180`, `800`, `6`, `400`, `5`, `5600`, `* 3`, depth `3`, key cap `12`, list cap `10`, string cap `220` | LLM payload compaction and snippet heuristics are still service-local. | `LLMRuntimeSettings` |

#### Regex and noise policy drift

| Reference | Hardcoded value(s) | Problem | Recommended home |
| --- | --- | --- | --- |
| `backend/app/services/extract/variant_builder.py:40-48` | `_NETWORK_PAYLOAD_NOISE_URL_PATTERNS` regex | Noise URL filtering is defined locally instead of central `noise_policy.py` or config. | `noise_policy.py` + typed pattern settings |
| `backend/app/services/extract/listing_card_extractor.py:40-58` | multiple local regexes for pricing, measurement, size, variant prompts | Listing noise/shape heuristics are scattered instead of centralized policy. | listing extraction config / shared policy |

### T2. Eliminate environment-variable access outside config entrypoints
Status: Completed
Priority: High
Primary invariants: `#1`, config-sprawl objective

| Reference | Violation | Notes |
| --- | --- | --- |
| `backend/app/services/auth_service.py:26-32` | `_env_flag()` calls `os.getenv()` directly | Fixed: service now reads config-backed bootstrap settings only. |
| `backend/app/services/auth_service.py:53-62` | `_load_default_admin_credentials()` calls `os.getenv()` directly | Fixed: env-backed admin bootstrap now lives in `app.core.config`. |

Assessment:

- `backend/app/core/config.py` remains the effective env entrypoint for most runtime settings.
- I did not find evidence of a current circular-import loop in the service→config graph.
- Cleanup result:
  - `auth_service.py` no longer reads `os.getenv()` or `os.environ`.
  - `app.core.config` now owns the admin bootstrap env mapping.

### T3. Tighten typed boundaries between adapters, detail flow, and variant modules
Status: Mostly completed
Priority: High
Primary invariants: `#4 Pipeline boundaries must use typed objects`

#### Evidence

| Reference | Observation | Risk |
| --- | --- | --- |
| `backend/app/services/adapters/base.py:14-19` | `AdapterResult.records` is `list[dict]` | Partially fixed: now routed through shared adapter record types. |
| `backend/app/services/pipeline/detail_flow.py:261-279` | Schema resolution and extraction use raw `adapter_records[0]` and raw `list[dict]` | Partially fixed: key signatures now use shared adapter record aliases. |
| `backend/app/services/pipeline/detail_flow.py:347-353` | Adapter record is blindly merged into candidate values | Substitution is syntactic, not semantic. |
| `backend/app/services/pipeline/detail_flow.py:543-558` | LLM preview record also merges raw adapter dicts | Weak contract propagates into LLM prompt assembly. |
| `backend/app/services/extract/variant_builder.py:30-34` | `variant_builder` imports private helpers from `variant_extractor` | Fixed: shared variant logic now lives in a separate helper module. |
| `backend/app/services/extract/variant_builder.py:226-299`, `1575-1580` | Variant-building boundary previously exposed `dict[str, list[dict]]` throughout | Fixed for variant bundles/candidate payloads via dedicated variant TypedDicts; remaining weakness is downstream adapter-record semantics in `detail_flow.py`. |

Liskov/Substitution assessment:

- `shopify.py` and `icims.py` do follow the `BaseAdapter` method signatures.
- A lightweight shared adapter record contract now exists, but the semantic payload shape is still not fully enforced.
- Example: Shopify emits variant rows with both `available` and `availability` (`backend/app/services/adapters/shopify.py:246-257`), while downstream code treats adapter payloads as generic canonical dicts. That is substitution by convention, not by enforced interface.
- I did not find site-specific branching leaking into `detail_flow.py`; the leakage is weaker but still real: `detail_flow.py` depends on undocumented adapter dict shapes.

### T4. Remove duplicate helper kernels and normalization drift
Status: Completed
Priority: High
Primary invariants: `#1`, `#3`, DRY objective

#### Duplicate or overlapping helpers

| Reference pair | Duplicate logic | Recommendation |
| --- | --- | --- |
| `backend/app/services/extract/json_extractor.py:467-500` and `backend/app/services/extract/listing_item_normalizer.py:551-577` | `_find_alias_values()` and `_normalized_field_token()` duplicated with slightly different traversal limits (`40` vs `30`) | Fixed via `extract/shared_logic.py` |
| `backend/app/services/extract/json_extractor.py:577-585` and `backend/app/services/extract/listing_item_normalizer.py:586-596` | slug-to-URL resolution (`_derive_slug_url` vs `_resolve_slug_url`) | Fixed via `extract/shared_logic.py` |
| `backend/app/services/extract/json_extractor.py:530-562` and `backend/app/services/extract/listing_item_normalizer.py:502-519` | nested image extraction / URL joining | Fixed via `extract/shared_logic.py` |
| `backend/app/services/extract/variant_extractor.py:46-75` and `backend/app/services/adapters/shopify.py:343-356` | canonical variant-axis splitting exists in two places with different rules (`axis_name in _TRUE_VARIANT_AXES` vs `axis_name == "size"`) | Fixed via `extract/shared_variant_logic.py` |
| `backend/app/services/normalizers/__init__.py:231-257` and `backend/app/services/extract/source_parsers.py:685-704` | JSON-like payload normalization/parsing duplicated (`_parse_json_like_value` vs `_normalized_json_candidate` + `_parse_json_blob`) | Fixed via `extract/shared_json_helpers.py` |
| `backend/app/services/adapters/shopify.py:393-420` and broader normalization stack in `backend/app/services/normalizers/__init__.py` | Shopify keeps its own price normalization kernel | Fixed via shared price normalizer in `normalizers/__init__.py` |

#### Sanitization drift note

- Shared text normalization now lives in `app.services.text_utils`.
- Shared UI-noise stripping now lives in `app.services.text_sanitization`.
- `noise_policy.py` and `normalizers/__init__.py` now consume those shared helpers instead of each carrying their own text/UI-noise ownership.

## Invariant Violations Summary

### Invariant #1: No magic values in service code

Broken in:

- `backend/app/services/acquisition/acquirer.py`
- `backend/app/services/acquisition/traversal.py`
- `backend/app/services/adapters/shopify.py`
- `backend/app/services/adapters/icims.py`
- `backend/app/services/extract/listing_card_extractor.py`
- `backend/app/services/extract/json_extractor.py`
- `backend/app/services/extract/source_parsers.py`
- `backend/app/services/llm_runtime.py`

This is no longer the dominant repo-wide issue. Most high-value tunables from the audit have been migrated into typed settings. Remaining violations are narrower and mostly regex/policy drift.

### Invariant #3: Pipeline config is the single source of truth

Broken in:

- local regex and heuristic definitions in `listing_card_extractor.py`
- local scoring maps in `json_extractor.py` and `source_parsers.py`

Update:
- The network-payload noise URL filter has been moved behind `noise_policy.py`.

### Invariant #4: Pipeline boundaries must use typed objects

Partially broken in:

- `backend/app/services/adapters/base.py`
- `backend/app/services/pipeline/detail_flow.py`
- `backend/app/services/extract/variant_builder.py`
- `backend/app/services/extract/variant_extractor.py`

The repo is compliant for `URLProcessingResult` and now has a lightweight shared adapter-record contract, but variant candidate boundaries still rely heavily on nested dict/list payloads.
Update:
- Variant candidate/result payloads now flow through dedicated TypedDict bundles in `variant_types.py`.
- Remaining boundary debt is primarily in downstream adapter-record semantics, not variant bundle typing itself.

## Shared Kernel Consolidation Plan

Recommended first-pass kernel moves:

1. `shared_logic.py::find_alias_values()`
   - Unify `json_extractor` and `listing_item_normalizer` recursive alias search.

2. `shared_logic.py::resolve_relative_or_slug_url()`
   - Unify slug/path/urljoin behavior across `json_extractor`, `listing_item_normalizer`, and listing normalization paths.

3. `shared_logic.py::collect_image_urls()`
   - One collector for nested image fields, URL joining, dedupe, and canonical-image splitting.

4. `shared_logic.py::split_variant_axes()`
   - One authoritative rule for selectable axes vs single-value attributes used by `variant_extractor`, `variant_builder`, and Shopify.

5. `shared_logic.py::parse_json_like_blob()`
   - One tolerant parser for embedded JSON fragments and hydrated payload blobs.

Implemented:
- `extract/shared_logic.py`
- `extract/shared_json_helpers.py`
- `extract/shared_variant_logic.py`

## Recommended Fix Order

1. Finish the remaining regex/policy centralization, especially listing-card regex drift and any residual extraction-scoring literals not yet covered.
2. Continue tightening variant sub-boundaries beyond adapter-record typing.
3. Add narrow regression tests around:
   - traversal timing behavior,
   - listing card detection thresholds,
   - JSON array scoring,
   - Shopify adapter pagination and timeout settings,
   - variant-axis reconciliation.

## Cleanup Progress

Completed in code:

- `auth_service.py` env/config cleanup
- LLM runtime typed settings
- extraction heuristic typed settings
- adapter heuristic typed settings
- acquisition/traversal typed settings
- shared extractor helper kernel
- shared JSON fragment helper kernel
- shared variant helper kernel
- lightweight typed adapter-record boundary
- shared network payload noise URL filter
- shared Shopify price normalizer
- acquisition/traversal settings regression coverage
- adapter runtime settings regression coverage
- iCIMS pagination now respects configured page size end-to-end
- listing-card scoring weights and title-length gates centralized into extraction settings
- listing-card settings regression coverage
- shared text normalization ownership extracted into `text_utils.py`
- shared UI-noise stripping extracted into `text_sanitization.py`
- variant bundle/result TypedDict contracts expanded and consumed in `variant_builder.py`
- regression coverage added for shared sanitization, JSON candidate scoring, and source-parser scoring/threshold settings

Previously deferred items closed in this pass:

- broader sanitization unification between `noise_policy.py` and `normalizers/__init__.py`
- fully typed variant candidate/result structures
- broader regression coverage beyond the earlier targeted config/adapter slices

## Audit Limits

- This pass focused on stabilization hotspots requested in the prompt, not a whole-repo numeric literal census.
- I did not find a current circular import caused by config modules.
- I did not find direct site-specific branches inside `detail_flow.py`; the boundary problem is weak typing, not explicit site leakage.
