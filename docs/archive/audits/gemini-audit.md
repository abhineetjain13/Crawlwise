Read: AGENTS.md, CODEBASE_MAP.md, BUSINESS_LOGIC.md, ENGINEERING_STRATEGY.md, INVARIANTS.md
Active plan: NONE
Audit scope emphasis: FIRST RUN
FIRST RUN
Section 1–8: Dimension Scores
Dimension: D1. SOLID / DRY / KISS
Floor: 6/10 | Ceiling: 8/10 | Score: 7.0/10
Previous score: N/A → Change: FIRST RUN
Reason for change: FIRST RUN
Violations:
MEDIUM tests/test_pipeline_core.py → test_extract_records_for_acquisition_keeps_adapter_fields_empty_when_no_adapter_matches (approx lines 150-160):
The test suite imports and asserts against private internal structs (_FetchedURLStage, _URLProcessingContext, _extract_records_for_acquisition) to verify pipeline behavior.
Breaks ENGINEERING_STRATEGY.md AP-7 (Private-function test coupling).
Production failure mode: Blocks structural refactoring of pipeline/core.py because internal implementation details are ossified by the test suite.
Verification: rg "from app.services.pipeline.core import.*_FetchedURLStage" tests/
Verdict: The core pipeline and extractors are generally well-layered and adhere to SRP. However, the test suite actively breaks encapsulation by coupling to private pipeline orchestration models, violating AP-7 and hindering future architectural cleanup.
Dimension: D2. Configuration Hygiene
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: FIRST RUN
Reason for change: FIRST RUN
Violations:
LOW browser_detail.py → expand_all_interactive_elements_impl (approx lines 120-130):
Hardcoded magic number timeouts (timeout=1_000, timeout=250) are scattered inline for Playwright actions instead of using crawler_runtime_settings.
Breaks Config Hygiene (magic numbers scattered inline).
Production failure mode it enables: Prevents operators from globally tuning interaction tolerances for slow sites without modifying source code.
Verification: rg "timeout=(1_000|250|2000)" backend/app/services/acquisition/browser_detail.py
Verdict: Configuration hygiene is extremely strong, with runtime settings driving nearly all timeouts, selectors, and fallback gates. A few minor magic numbers linger in Playwright interaction fallbacks.
Dimension: D3. Scalability & Resource Management
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: FIRST RUN
Reason for change: FIRST RUN
Violations:
No critical or high violations found. The shared HTTP client correctly prevents connection pool leaks, and Playwright contexts are strictly closed in finally blocks. Async workers inside browser_capture.py are properly tracked, cancelled, and drained on closure.
Verification: rg -A 5 "async def _capture_worker" backend/app/services/acquisition/browser_capture.py
Verdict: Resource management is exceptionally robust. The system properly bounds memory, enforces concurrency limits on network capture, safely drains tasks, and cleanly separates async HTTP pools from Playwright contexts.
Dimension: D4. Extraction & Normalisation Pipeline
Floor: 4/10 | Ceiling: 7/10 | Score: 5.5/10
Previous score: N/A → Change: FIRST RUN
Reason for change: FIRST RUN
Violations:
CRITICAL field_policy.py → field_allowed_for_surface (lines 28–34):
The function uses an implicit blocklist (_ALL_CANONICAL_FIELDS - allowed) to filter schema properties. Any completely unknown field (e.g., garbage_tracker_id) is not in _ALL_CANONICAL_FIELDS, meaning it evades the exclusion check and returns True. In field_value_core.py, these garbage fields are actively preserved and merged into the final record.data.
Breaks INVARIANTS.md #10 and #11 (Persisted record.data contains only populated logical fields).
Production failure mode it enables: Silent schema pollution. Any random JSON-LD or network payload key can bleed directly into the user-facing record payload.
Verification:
rg "def excluded_fields_for_surface" backend/app/services/field_policy.py
rg "field_allowed_for_surface" backend/app/services/field_value_core.py
CRITICAL detail_extractor.py → _promote_detail_title (approx lines 360–380):
The fallback ranking override condition allows weaker sources to overwrite strictly authoritative sources (like adapter or network_payload) simply because their string length is longer: (rank < current_rank or source in {...} or len(candidate) > len(title)).
Breaks source ranking integrity (authoritative-first hierarchy).
Production failure mode it enables: A concise, accurate product title from a dedicated Shopify API payload (rank 1) will be silently overwritten by a noisy, SEO-bloated dom_h1 tag (rank 10) just because the DOM tag contains more characters.
Verification: rg "rank < current_rank or source in.*or len\(candidate\)" backend/app/services/detail_extractor.py
Verdict: The extraction pipeline has powerful declarative mapping capabilities, but the ranking enforcement and schema validation layers contain critical logical holes. The implicit schema blocklist leaks garbage fields, and the title promotion heuristic defeats the authoritative-first source priority model.
Dimension: D5. Traversal Mode
Floor: 9/10 | Ceiling: 10/10 | Score: 9.5/10
Previous score: N/A → Change: FIRST RUN
Reason for change: FIRST RUN
Violations:
No violations found. Traversal modes correctly separate pagination, scroll, and load_more. Cross-tenant boundaries are respected via _is_same_origin, cycle detection is active, and structural links (javascript:, #) are properly ignored.
Verification: rg "def _is_same_origin" backend/app/services/acquisition/traversal.py
Verdict: Traversal orchestration is mathematically sound. It correctly sandboxes pagination state, applies cycle detection to prevent infinite loops, and honors multi-tenant path boundaries seamlessly.
Dimension: D6. Resilience & Error Handling
Floor: 7/10 | Ceiling: 9/10 | Score: 8.0/10
Previous score: N/A → Change: FIRST RUN
Reason for change: FIRST RUN
Violations:
MEDIUM traversal.py → _locator_still_resolves (approx lines 500-510):
Contains a bare except Exception: pass block while polling locator count, silently swallowing potentially critical runtime failures.
Breaks D6 Resilience rules against bare except Exception: pass.
Production failure mode it enables: Can mask underlying Playwright crashes, context closures, or cancellation signals (asyncio.CancelledError), causing the crawler to hang or behave unpredictably instead of propagating the error.
Verification: rg -A 3 "except Exception:" backend/app/services/acquisition/traversal.py
Verdict: Error handling handles HTTP bounds, 4xx/5xx bifurcation, and blocked page classification intelligently. However, a lingering bare exception swallow in the traversal recovery code risks masking critical context failures.
Dimension: D7. Dead Code & Technical Debt
Floor: 7/10 | Ceiling: 8/10 | Score: 7.5/10
Previous score: N/A → Change: FIRST RUN
Reason for change: FIRST RUN
Violations:
MEDIUM tests/test_browser_expansion_runtime.py → imports (approx lines 10-20):
Imports and tests _generate_page_markdown and _FakeExpansionPage directly.
Breaks ENGINEERING_STRATEGY.md AP-7 (Private-function test coupling).
Production failure mode it enables: Architectural lock-in. Internal Markdown serialization and Playwright flow logic cannot be safely refactored because the test suite expects private classes and methods to remain unchanged.
Verification: rg "from app.services.acquisition.browser_page_flow import.*_generate_page_markdown" tests/
Verdict: Technical debt is low regarding dead code and TODOS, but the test suite creates artificial friction by testing private module implementations instead of public API contracts.
Dimension: D8. Acquisition Mode
Floor: 9/10 | Ceiling: 10/10 | Score: 9.5/10
Previous score: N/A → Change: FIRST RUN
Reason for change: FIRST RUN
Violations:
No violations found. The HTTP/Browser escalation strategy correctly assesses heuristics, explicit platform policy, and vendor block headers without hardcoding sites in the generic engine. Fingerprinting applies seamlessly to contexts.
Verification: rg "def should_escalate_to_browser" backend/app/services/acquisition/runtime.py
Verdict: The acquisition routing is exemplary. The escalation from curl_cffi to Playwright is purely evidence-driven, maintaining clean boundaries and preventing unnecessary browser usage.
Section 9: Final Summary
Overall Score: 7.9/10 (previous: N/A, delta: FIRST RUN)
Root Cause Findings (architectural — require a plan, not a bug fix):
RC-1: Schema Exclusion Logic Allows Arbitrary Output Field Pollution — affects D4
RC-2: Title Promotion Overwrites Strong Sources With Weak Sources (Precedence Violation) — affects D4
Leaf Node Findings (isolated bugs — Codex can fix directly):
LN-1: acquisition/traversal.py → _locator_still_resolves → Replace bare except Exception: pass with explicit Playwright/Exception catching that re-raises CancelledError.
LN-2: acquisition/browser_detail.py → expand_all_interactive_elements_impl → Replace hardcoded timeout=1_000 and timeout=250 with runtime settings.
LN-3: tests/test_pipeline_core.py → Fix test suites importing private structs _FetchedURLStage and _URLProcessingContext by testing public outputs.
Genuine Strengths (file-level evidence only, no generic praise):
browser_capture.py → _capture_worker: Safely and reliably bounds memory and concurrency while capturing streaming RSC and JSON payloads via Queue workers, handling cancellation cleanly.
platform_policy.py → resolve_platform_runtime_policy: Completely extracts platform recognition from generic crawler paths, achieving perfect OCP adherence.
Section 10: Codex-Ready Work Orders
WORK ORDER RC-1: Schema Exclusion Logic Allows Arbitrary Output Field Pollution
Touches buckets: 4 (Extraction), 5 (Publish + Persistence)
Risk: CRITICAL
Do NOT touch: LLM tasks, Adapter implementations
What is wrong
In field_policy.py, excluded_fields_for_surface returns all canonical fields not allowed for a surface. field_allowed_for_surface checks if a field is not in this excluded list. Consequently, any completely unknown field (e.g. garbage_key) evades the exclusion check and is incorrectly flagged as allowed. In field_value_core.py, validate_record_for_surface then blindly injects these allowed unknown fields back into the sanitized payload, violating strict schema enforcement.
What to do
In app/services/field_policy.py, rewrite field_allowed_for_surface to use a strict allowlist. It must check if normalized_field is exactly within the list returned by canonical_fields_for_surface(surface).
Do not rely on excluded_fields_for_surface for determining if a field is natively allowed; only use it if evaluating legacy explicit rejections.
In app/services/field_value_core.py, ensure validate_record_for_surface drops any field not explicitly returned by the surface schema.
Acceptance criteria

field_allowed_for_surface("ecommerce_detail", "random_garbage_key") returns False.

validate_record_for_surface drops keys that do not exist in the surface's canonical schema.

python -m pytest tests -q exits 0.
What NOT to do
Do not modify the _OUTPUT_SCHEMAS map structure.
Do not disable type validation for fields that are canonical.
WORK ORDER RC-2: Title Promotion Overwrites Strong Sources With Weak Sources
Touches buckets: 4 (Extraction)
Risk: CRITICAL
Do NOT touch: DOM section extraction, LLM fallback
What is wrong
In app/services/detail_extractor.py, _promote_detail_title evaluates replacement titles with a flawed logical condition: (rank < current_rank or source in {"network_payload", ...} or len(candidate) > len(title)). Because of the or, a lower-quality source (like dom_h1) can overwrite a high-quality authoritative source (like adapter or network_payload) purely because the candidate string is longer. This destroys the authoritative-first source ranking.
What to do
In app/services/detail_extractor.py, update the _promote_detail_title condition.
Remove the len(candidate) > len(title) override bypass.
Remove the source in {...} bypass.
The condition should strictly mandate that the candidate must either be an objectively higher-ranked source (rank < current_rank), OR if the ranks are equal, it can be longer/better formatted.
Acceptance criteria

A title extracted from an adapter (rank 0) is never overwritten by a dom_h1 (rank 10) title, regardless of length.

grep -r "or len(candidate) > len(title)" backend/app/services/detail_extractor.py returns empty.

python -m pytest tests -q exits 0.
What NOT to do
Do not change the integer ranks in DETAIL_TITLE_SOURCE_RANKS.
Do not completely remove the promotion logic; it is still needed to replace js_state shells with valid dom_h1 content when js_state produces noise.
WORK ORDER LN-1: Bare Exception Swallows in Traversal (single-session fix)
File: app/services/acquisition/traversal.py
Function: _locator_still_resolves
Fix: Replace the bare except Exception: pass with explicit exception handling. If asyncio.CancelledError is caught, re-raise it. Log other Playwright/Exception errors securely at debug level.
Test: rg -A 2 "except Exception:" backend/app/services/acquisition/traversal.py should show proper logging and re-raising of cancellation instead of pass.
WORK ORDER LN-2: Magic Number Timeouts in Browser Detail (single-session fix)
File: app/services/acquisition/browser_detail.py
Function: expand_all_interactive_elements_impl
Fix: Replace inline timeout=1_000 and timeout=250 calls with configurable variables fetched from crawler_runtime_settings (e.g., crawler_runtime_settings.accordion_expand_wait_ms or a related setting).
Test: rg "timeout=(1000|1_000|250)" backend/app/services/acquisition/browser_detail.py returns empty.
WORK ORDER LN-3: Test Layer Violations (single-session fix)
File: tests/test_pipeline_core.py
Function: Various test imports
Fix: Remove direct imports of _FetchedURLStage and _URLProcessingContext. Refactor the associated tests to pass through the public process_single_url API or mock responses cleanly without instantiating private orchestration structs.
Test: rg "_FetchedURLStage" tests/ returns empty.