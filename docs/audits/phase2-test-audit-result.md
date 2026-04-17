Phase 2 Audit
Scope
Target module/slice: Extraction & Acquisition Pipeline Refactor (Acquire -> Discover -> Extract -> Normalize -> Publish)
Files reviewed: All provided test_*.py files in the payload.
Related production files: app.services.crawl_service, app.services.pipeline.core, app.services.acquisition.browser_client, app.services.extract.service, app.services._batch_runtime.
Boundary being enforced: Strict stage boundaries isolating Acquisition (I/O) from Extraction (CPU/DOM parsing).
Executive Decision
Audit verdict: HIGH-RISK
Primary reason: Core pipeline integration tests (test_crawl_service.py, test_browser_client.py) rely on massive monkeypatching of private helpers and cross-stage mocks, actively preventing the safe separation of pipeline stages.
Can refactor proceed before test cleanup? NO
Minimum cleanup required before proceeding: Delete or rewrite heavily mocked tests in test_crawl_service.py and test_browser_client.py that enforce internal call ordering rather than public stage contracts.
Findings
Finding 1
Severity: critical
Test file: test_crawl_service.py
Test name or test group: test_process_run_* (e.g., test_process_run_single_url, test_process_run_batch)
Classification: coupled-to-internals
Trust level: do-not-trust
Problem: The tests assert the behavior of the entire pipeline (process_run) by heavily monkeypatching internal stage functions (app.services.pipeline.core.acquire, app.services.pipeline.core.run_adapter, discover_xpath_candidates, review_field_candidates).
Evidence: _process_run_with_acquisition wrapper patches acquire and run_adapter globally to return fake AcquisitionResult objects.
Why this blocks or does not block refactor: If the pipeline is refactored into distinct stages (ParseStage, ExtractStage, etc.), these tests will instantly break because the patched internal module paths will change or disappear. They cement the monolithic process_run structure.
Action: replace
Replacement seam: PipelineRunner.execute(ctx) using real stage classes, but with an injected HTTP transport/Acquirer interface (or a local dummy server as done in test_smoke_crawl.py).
Notes: Stop testing pipeline integration by mocking other pipeline steps.
Finding 2
Severity: high
Test file: test_browser_client.py
Test name or test group: test_fetch_rendered_html_attempt_passes_page_content_helper_to_low_value_check
Classification: coupled-to-internals
Trust level: do-not-trust
Problem: The test mocks 11 different private functions (_build_launch_kwargs, _acquire_browser, _context_kwargs, _load_cookies, _maybe_warm_origin, _goto_with_fallback, _dismiss_cookie_consent, _wait_for_challenge_resolution, _wait_for_listing_readiness, _page_looks_low_value, _populate_result) just to verify that one private function passes a variable to another.
Evidence: The test explicitly checks assert captured["page_content_with_retry"] is browser_client._page_content_with_retry.
Why this blocks or does not block refactor: This is an extreme example of white-box testing. Any internal refactoring of the Playwright acquisition flow will break this test, even if the public output (BrowserResult) remains perfect.
Action: delete
Replacement seam: browser_client.fetch_rendered_html against a local test HTTP server.
Notes: Never assert the passing of internal module functions to other internal functions.
Finding 3
Severity: high
Test file: test_batch_runtime_retry_update.py
Test name or test group: test_retry_run_update_retries_fast_on_lock_contention
Classification: coupled-to-internals
Trust level: low-trust
Problem: The test fakes SQLAlchemy transaction semantics (_FakeNestedTransaction, _FakeResult) and forces a simulated module reload (batch_runtime_module) to test an internal DB lock retry loop.
Evidence: Defines class _FakeLockError(Exception): sqlstate = "55P03" and mocks session.execute(AsyncMock(side_effect=[OperationalError..., _FakeResult(run)])).
Why this blocks or does not block refactor: It locks the data access layer to a very specific procedural implementation. Moving to a Repository pattern or modifying transaction boundaries will invalidate the test.
Action: rewrite
Replacement seam: BatchRunStore.apply() or an integration test using the db_session fixture where a concurrent lock is actually simulated via two real sessions.
Notes: Mocks at the ORM session level are notoriously brittle.
Finding 4
Severity: medium
Test file: test_extract.py
Test name or test group: test_extract_candidates_skips_dom_when_jsonld_winner_is_decisive
Classification: coupled-to-internals
Trust level: medium-trust
Problem: Asserts that a specific optimization path is taken by patching a private method to throw an error if called.
Evidence: monkeypatch.setattr(extract_service, "_collect_dom_and_meta_candidates", _unexpected_dom_collection).
Why this blocks or does not block refactor: As extraction logic is flattened (Feature: extraction-pipeline-improvements, Task 7), _collect_dom_and_meta_candidates is likely to be eliminated or merged.
Action: rewrite
Replacement seam: extract_candidates(html=...).
Notes: Instead of patching the private method, assert that source_trace["extraction_audit"]["title"]["sources"] shows status: skipped for DOM sources. (The test actually already does this on lines 112-117, so the monkeypatch is redundant and should simply be deleted).
Finding 5
Severity: medium
Test file: test_crawls_background.py
Test name or test group: test_crawls_logs_ws_releases_db_session_between_polls
Classification: coupled-to-internals
Trust level: low-trust
Problem: Over-specifies the WebSocket polling loop by asserting exact pointer identity of session objects yielded from a faked _session_factory.
Evidence: assert session in entered_sessions[1:], assert len({id(session) for session in entered_sessions}) == 3.
Why this blocks or does not block refactor: Couples the endpoint test to the exact database connection pooling/session lifecycle implementation instead of verifying the WebSocket emits the correct JSON logs.
Action: delete
Replacement seam: Real TestClient or httpx.AsyncClient WebSocket connection.
Notes: Verifying connection pooling logic should happen in DB infrastructure tests, not WebSocket endpoint tests.
Keep List
Test file: test_datalayer.py
Test name/group: test_datalayer_parsing_round_trip_ga4 (and all other Hypothesis tests here)
Why it is safe: Pure function tests driven by Hypothesis properties. Zero mocking. Perfect invariant protection.
Classification: invariant
Trust level: high-trust
Test file: test_extract_refactoring_properties.py
Test name/group: test_property_15_refactoring_equivalence
Why it is safe: Uses Hypothesis to enforce strict I/O equivalence between the old and new extraction functions without caring about internal implementation.
Classification: contract
Trust level: high-trust
Test file: test_signal_inventory.py
Test name/group: All tests.
Why it is safe: Data-in, data-out tests validating structural requirements of the new SignalInventory abstraction using property-based inputs.
Classification: invariant
Trust level: high-trust
Test file: test_normalizers.py
Test name/group: All tests.
Why it is safe: Completely isolated unit tests for field-level string normalizers. No external dependencies.
Classification: invariant
Trust level: high-trust
Test file: test_runner.py
Test name/group: test_pipeline_runner_converts_unhandled_stage_error_into_url_error
Why it is safe: Tests the actual PipelineRunner orchestration class using simple, fake _ExplodingStage classes rather than mocking the DB or real stages. Perfect architectural boundary test.
Classification: contract
Trust level: high-trust
Rewrite/Delete Queue
Test file: test_browser_client.py
Test/group: test_fetch_rendered_html_attempt_passes_page_content_helper_to_low_value_check
Action: Delete
Why first: Contains 11 deep monkeypatches of private methods. High risk of false failures during Playwright/browser client refactoring.
Stable seam to target instead: Local HTTP server + browser_client.fetch_rendered_html.
Test file: test_crawl_service.py
Test/group: test_process_run_*
Action: Rewrite
Why first: Falsely enforces integration boundaries. Blocks separating the pipeline into distinct sequential stages because it expects the old monolithic process_run to execute patched internal functions.
Stable seam to target instead: PipelineRunner.execute(ctx) (pipeline behavior) and test_smoke_crawl.py (true E2E behavior).
Test file: test_batch_runtime_retry_update.py
Test/group: All tests
Action: Delete
Why first: Hardcoded SQLAlchemy internals and fake exception states (_FakeNestedTransaction). Does not verify business logic, only procedural steps.
Stable seam to target instead: Real concurrent database operations on BatchRunStore using test PostgreSQL containers.
Test file: test_extract.py
Test/group: test_extract_candidates_skips_dom_when_jsonld_winner_is_decisive
Action: Rewrite (remove monkeypatch)
Why first: Protects a valid requirement (don't waste CPU on DOM if JSON-LD wins), but enforces it via a bad mechanism (mocking a private function).
Stable seam to target instead: Assert on trace["extraction_audit"].
Replacement Coverage Plan
Behavior to protect: Pipeline execution flow (Acquire -> Extract -> Normalize) handles errors gracefully and aggregates results.
Public/stable seam: PipelineRunner and PipelineContext.
Test style: contract
What to avoid asserting: Do not assert app.services.pipeline.core.acquire is called. Do not patch global functions. Inject a mock Acquirer dependency into the PipelineContext or use mock stages.
Behavior to protect: Browser rendering gracefully handles captchas/blocks.
Public/stable seam: browser_client.fetch_rendered_html.
Test style: characterization / contract
What to avoid asserting: Do not mock _page_looks_low_value or _wait_for_challenge_resolution. Point the browser at a real local test server that serves a PerimeterX/Cloudflare template.
Unknowns
None. The evidence strongly supports immediate action to remove the heavily mocked tests blocking the pipeline refactor.
Final Recommendation
PROCEED AFTER TARGETED TEST CLEANUP
Reason:
The property-based tests (test_extract_refactoring_properties.py, test_datalayer.py, test_signal_inventory.py) provide excellent, high-trust safety nets for the extraction logic. However, the pipeline orchestration tests (test_crawl_service.py) and browser acquisition tests (test_browser_client.py) are tightly coupled to private implementation details via heavy monkeypatching. They will actively resist structural changes and must be eliminated or refactored to use public seams before modifying the pipeline architecture.
First 3 concrete next actions:
Delete test_fetch_rendered_html_attempt_passes_page_content_helper_to_low_value_check and related heavy-mock tests in test_browser_client.py.
Remove the _process_run_with_acquisition helper in test_crawl_service.py and replace its test coverage with PipelineRunner tests executing concrete PipelineContext states.
Remove the _collect_dom_and_meta_candidates monkeypatch from test_extract.py and rely strictly on the extraction_audit trace for assertions.

Slice 1 execution note — 2026-04-17
- applied:
  - deleted the private-helper assertion in `backend/tests/services/acquisition/test_browser_client.py`
  - rewrote the JSON-LD arbitration test to assert only `extraction_audit`
  - retired the `test_process_run_*` block from `backend/tests/services/test_crawl_service.py` so it no longer gates acquisition-boundary work
  - added a stable policy test for traversal browser-forcing after moving that seam into `backend/app/services/acquisition/policy.py`
- remaining intent:
  - replace the retired `process_run` coverage with `PipelineRunner`-level contract tests before Slice 3
