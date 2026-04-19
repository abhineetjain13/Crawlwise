# Changelog

## 2026-04-19

- Added the Gemini audit remediation tracker and six independent slice docs under `docs/plans/`.
- Completed Slice 1: acquisition hot-path hardening.
- Completed Slice 4: pipeline orchestration split.
- Moved parser-heavy blocked-page and browser-escalation checks off async hot paths in `crawl_fetch_runtime.py`.
- Made intercepted payload body reads explicit with `read`, `too_large`, `response_closed`, and `read_error` outcomes, while preserving fetch result contracts.
- Added an async script-text extraction wrapper and focused backend tests for payload outcomes, async offloading, and script-text parity.
- Decomposed `backend/app/services/pipeline/core.py` so `_process_single_url` now runs through typed robots, fetch, extract, and persistence helpers without changing its external contract.
- Added focused per-URL pipeline tests covering robots blocks, prefetch-only mode, empty listing verdicts, and detail persistence after selector self-heal plus LLM fallback.
- Completed Slice 2: traversal and detail interaction safety.
- Enforced same-origin pagination and added explicit transition waiting for paginate and load-more traversal before snapshotting.
- Added expansion-handle actionability checks so hidden or non-actionable detail toggles are skipped before click fallback.
- Completed Slice 5: extraction priority and selector safety.
- Made detail-record materialization sort candidates by explicit source priority instead of relying on append order.
- Replaced selector self-heal HTML truncation with DOM-aware, valid-HTML reduction and added focused extraction/self-heal tests.
- Completed Slice 6: operational cleanup and boundaries.
- Pruned stale local run task bookkeeping in `crawl_service.py`, keeping pause/resume/kill contracts stable while clearing orphaned task ids during local recovery.
- Tightened `robots_policy.py` internals without changing explicit allow, disallow, missing, or fetch-failure outcomes, and added a forbidden-robots test.
- Simplified static config exports in `backend/app/services/config/selectors.py` and `field_mappings.py`, removed the unused pipeline `log_for_pytest` stub, and collapsed `BrowserPool` into a thin runtime proxy.
- Moved record display scrubbing behind explicit `CrawlRecordResponse` serializers, kept route payloads unchanged, and added focused tests for run control, config import stability, and record response behavior.
- Made `_should_escalate_to_browser` surface-aware so detail-surface fetches escalate to the browser when no extractable signals are present, even when the HTML is not a JS shell (covers SPA detail pages like saashr).
- Added a post-transport-error browser fallback in `fetch_page` so HTTP transport failures (`TooManyRedirects`, DNS/`getaddrinfo`, etc.) attempt a browser fetch before re-raising the original exception.
- Removed the body-text `discount_percentage` regex fallback in `detail_extractor` to stop fabricating discount values from unrelated copy (e.g., composition text, care instructions).
- Stopped per-field commit metadata refresh from clobbering extraction-time field provenance; `refresh_record_commit_metadata` now preserves existing per-field sources during initial persistence.
