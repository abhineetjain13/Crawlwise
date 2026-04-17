---
title: "refactor: architectural runtime stabilization tracker"
type: refactor
status: complete
date: 2026-04-16
---

# Refactor: Architectural Runtime Stabilization Tracker

## Summary

This tracker owns the acquisition and pipeline refactor plus browser-runtime stabilization work.

Phase 1:

- remove dead acquisition seams
- stabilize browser launch-profile fallback and diagnostics
- move blocked browser recovery into acquisition
- reduce duplicate DOM parsing in the hot path
- delete or rewrite tests that preserve wrong behavior

Phase 2:

- platform and adapter extensibility
- config consolidation
- async parsing consistency and profiling-led DOM efficiency

## Phase 1 Checklist

- [x] Create tracker in `docs/plans/`
- [x] Remove dead `strategies.py`
- [x] Remove acquisition dependency on `SITE_POLICY_REGISTRY` / `BROWSER_FIRST_DOMAINS`
- [x] Move blocked browser recovery ownership into acquisition
- [x] Stabilize `system_chrome` fallback and `NotImplementedError` handling
- [x] Extend browser failure diagnostics and run logs
- [x] Reuse shared soup in listing retry heuristics
- [x] Update or delete tests that pin dead seams or wrong ownership
- [x] Remove `BlockedDetectionStage` from the live default runner
- [x] Replace hardcoded adapter resolution list with config-driven registry construction
- [x] Route blocked adapter recovery through the same registry surface
- [x] Run targeted verification for acquisition, browser-client, pipeline, and crawl-service paths

## Test Cleanup Log

- Rewrote acquisition policy test to stop monkeypatching dead `BROWSER_FIRST_DOMAINS`
- Rewrote crawl-service blocked listing tests to reflect acquisition-owned recovery instead of pipeline-owned duplicate acquire calls
- Added browser-client regression coverage for `NotImplementedError` fallback from `system_chrome` to bundled Chromium
- Added runner regression to assert `BlockedDetectionStage` is no longer in the default stage chain
- Added adapter registry regression to assert config-driven registration still keeps `shopify` last

## Phase 2 Queue

- [x] Replace hardcoded adapter/platform registration with one coherent discovery path
- [x] Consolidate extraction/platform/runtime config ownership
- [x] Eliminate remaining synchronous HTML parsing on async hot paths

## Phase 2 Notes

- Moved browser-first domain discovery and adapter ordering into `platform_registry` so acquisition and adapter resolution share the same config-backed source of truth
- Threaded `page_sources` through `PipelineContext` so parse, manifest, and LLM/detail helpers can reuse the same DOM-derived source inventory instead of reparsing the acquired HTML
- Updated async parser coverage to assert `parse_page_sources_async()` preserves caller-provided soup when the pipeline has already parsed the DOM

## Verification

- `pytest backend/tests/services/config/test_platform_registry.py -q`
- `pytest backend/tests/services/discover/test_source_parsers.py -q -k "parse_page_sources_async_offloads_sync_parser"`
- `pytest backend/tests/services/pipeline/test_runner.py -q`
- `pytest backend/tests/services/adapters/test_adapters.py -q -k "registered_adapters_uses_config_driven_names_and_keeps_shopify_last"`
- `pytest backend/tests/services/acquisition/test_acquirer_policy.py -q`
- `pytest backend/tests/services/test_crawl_service.py -q -k "listing_browser_retry_blocked_marks_run_blocked or recovered_result_from_acquisition_completes_without_pipeline_retry"`
