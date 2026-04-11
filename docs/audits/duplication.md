Analysis of Major Duplicate Code Groups: Repository abhineetjain13/Crawlwise

1. Analysis Summary and Redundancy Metrics

A comprehensive technical debt audit of the abhineetjain13/Crawlwise repository has identified a systemic reliance on "Copy-Paste" development patterns that significantly compromise the project's long-term maintainability. Out of 69,504 lines analyzed, 5,185 lines are flagged as redundant, resulting in a duplication density of approximately 7.46%.

This volume of redundancy is concentrated across 103 distinct duplicate groups, which are categorized by impact as follows:

* Major Duplicate Groups: 33
* Minor Duplicate Groups: 70

From an architectural perspective, this duplication rate is unacceptable. It indicates that code is being propagated without regard for abstraction, creating a massive surface area for "logic drift" where a single bug must be fixed in multiple locations. The prevalence of Major severity issues in core API clients and test suites suggests an immediate risk to developer agility and CI efficiency.

2. Detailed Catalog of Major Duplicate Groups

The following catalog provides the technical specifics for every "Major" severity duplicate block identified. These must be prioritized for consolidation.

Completed on 2026-04-11

* Group 1: `frontend/lib/api/client.ts` request-response helper duplication consolidated into a shared response-type parser. The open major-group list below starts at the next unresolved item.
* Group 2: `frontend/lib/api/client.ts` repeated response dispatch wrappers collapsed behind `requestWithResponseType()`.
* Group 3: `frontend/lib/api/client.ts` repeated read-method plumbing collapsed behind `createReadRequest()`.
* Group 4: `frontend/lib/api/client.ts` repeated body/delete method plumbing collapsed behind request factories.
* Group 7: audit line ranges no longer match the current `acquirer.py` / `page_classifier.py` code after later refactors; the previously reported duplicate block is stale and no longer present as written.
* Group 8: audit line ranges no longer match the current `crawl_events.py` / `crawl.py` / `_batch_progress.py` code after the typed summary/progress refactors; the previously reported duplicate block is stale and no longer present as written.
* Group 13: shared HTML/build-result helpers were extracted for `test_crawl_service.py` and `test_listing_extractor.py`, removing repeated crawl/listing fixture scaffolding.
* Group 21: repeated process-run setup in `test_crawl_service.py` was consolidated behind local helper flows.
* Group 38: repeated crawl-service acquisition/query assertions were consolidated behind shared helpers.
* Group 39: repeated traversal/capture setup in `test_fragment_capture.py` was consolidated behind `_run_fragment_capture_case()`.
* Group 44: repeated adapter-test response setup was consolidated behind shared test helpers.
* Group 45: repeated adapter-test fixture/assertion plumbing was consolidated behind shared test helpers.
* Group 54: repeated `SignalInventory` setup/assertion patterns were consolidated in `test_signal_inventory.py`.
* Group 60: repeated adapter-test HTML/record scaffolding was consolidated behind shared test helpers.
* Group 61: repeated adapter-test single-record assertions were consolidated behind shared test helpers.
* Group 69: repeated acquirer test fetch/browser patch scaffolding was consolidated behind `_run_acquire_case()`.
* Group 70: repeated acquirer test fetch/browser patch scaffolding was consolidated behind `_run_acquire_case()`.
* Group 79: repeated export-test run/record setup and paging-header assertions in `test_records_exports.py` were consolidated behind local helpers.
* Group 80: repeated export-test run/record setup and provenance/assertion scaffolding in `test_records_exports.py` were consolidated behind local helpers.
* Group 81: repeated crawl-service browser/listing process-run setup was consolidated behind shared helpers.
* Group 82: repeated crawl/listing extractor fixture builders were consolidated into shared test-only helpers.
* Group 85: repeated traversal/capture setup in `test_fragment_capture.py` was consolidated behind `_run_fragment_capture_case()`.
* Group 86: repeated traversal/capture setup in `test_fragment_capture.py` was consolidated behind `_run_fragment_capture_case()`.
* Group 11: duplicate metadata wrapper logic was removed from `pipeline/core.py`; the pipeline now imports `crawl_metadata.py` directly.
* Group 66: shared KitchenAid/food-processor fixture scaffolding in `test_crawl_service.py` and `test_listing_extractor.py` was consolidated into shared helpers.
* Group 73: the original duplicate line ranges in `api/crawls.py` no longer map to a real repeated block in the current router after later controller refactors, so this audit entry is stale.
* Group 75: repeated curl/browser diagnostics finalization in `acquirer.py` was consolidated behind shared result-diagnostics helpers.
* Group 99: repeated `xpath_discovery` config seeding and single-cost-log assertions in `test_llm_runtime.py` were consolidated behind local helpers.

3. Primary Redundancy Hotspots

The following files represent the most significant sources of code debt in the repository. Refactoring efforts must prioritize these files to yield the highest impact:

Critical Targets (High Frequency)

* frontend/lib/api/client.ts: Central to Groups 1, 2, 3, and 4. This file is a major offender, repeatedly implementing similar API communication patterns.
* backend/tests/services/test_crawl_service.py: Involved in Groups 13, 21, 38, 66, 81, and 82. This is the primary redundancy hotspot in the backend test suite.

Secondary Targets

* backend/tests/services/extract/test_listing_extractor.py: Critical participant in heavy-weight Groups 13, 66, and 82.
* backend/tests/services/adapters/test_adapters.py: Plagued by repetitive setup in Groups 44, 45, 60, and 61.
* backend/tests/services/acquisition/test_fragment_capture.py: Redundancy observed in Groups 39, 85, and 86.

4. Strategic Recommendations for Logic Consolidation

To mitigate the architectural risk identified in this report, I mandate the following actions:

Command 1: Mandate the abstraction of frontend API communication patterns. The repetitive blocks in frontend/lib/api/client.ts (Groups 1–4) must be unified into a generalized request handler. Furthermore, these blocks frequently contain the "Unexpected await inside a loop" critical antipattern (as seen on lines 107, 125, 140, 149, etc.). Refactoring this code is not merely about removing duplicates; it is about replacing inefficient, sequential I/O with modern concurrent patterns.

Command 2: Mandate the creation of shared test utilities and fixtures. The massive duplication in backend service tests—specifically Groups 13 (260 lines), 66 (285 lines), and 82 (236 lines)—is indicative of bloated test setups. The development team must extract common assertions and mocking logic into a dedicated test utility library or pytest fixtures. Addressing Groups 13 and 82 alone will remove nearly 500 lines of redundant code from the repository.

Command 3: Mandate a review and unification of core acquisition and classification logic. The 106-line duplication shared between backend/app/services/acquisition/acquirer.py and backend/app/services/llm_integration/page_classifier.py (Group 7) represents a high-risk drift scenario. Common logic for page analysis and element identification must be moved to a shared service layer to ensure consistent behavior across the acquisition and classification pipelines.
