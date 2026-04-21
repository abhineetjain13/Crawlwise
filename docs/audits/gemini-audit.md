Section 0: Delta Table (longitudinal)
Finding ID	Previous Status	Current Status	Evidence
N/A	N/A	N/A	FIRST RUN
Section 1–8: Dimension Scores
Dimension: D1. SOLID / DRY / KISS
Floor: 7/10 | Ceiling: 9/10 | Score: 8.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
LOW[pipeline/core.py → _sanitize_llm_existing_values (lines 101–125)]:
Contains inline HTML stripping logic mixed directly into pipeline orchestration. This violates SRP. Text sanitization logic belongs in text_sanitization.py or a dedicated LLM prompt preparation helper, not in the core async pipeline runner.
Verification: grep -r "class _Stripper(HTMLParser):" backend/app/services/pipeline/core.py
Verdict: The core pipeline is well-structured and uses clear data objects (_URLProcessingContext, _ExtractedURLStage) instead of positional sprawl. Minor SRP violations remain in inline data transformations.
Dimension: D2. Configuration Hygiene
Floor: 6/10 | Ceiling: 9/10 | Score: 7.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
HIGH[pipeline/core.py → _LLM_EXISTING_VALUE_MAX_CHARS (line 98)]:
A magic number (500) is hardcoded directly into the pipeline orchestration logic for LLM payload truncation. This bypasses the active llm_runtime_settings (which defines existing_values_max_chars = 2400), leading to disjointed configuration where tuning the env vars has no effect on this specific truncation. INVARIANT #7 (Config-driven runtime).
Verification: grep -r "_LLM_EXISTING_VALUE_MAX_CHARS =" backend/app/services/pipeline/core.py
Verdict: Tunables are generally well-extracted to JSON and BaseSettings classes. The hardcoded LLM truncation limit in the pipeline is a stark outlier that ignores the established config framework.
Dimension: D3. Scalability & Resource Management
Floor: 7/10 | Ceiling: 9/10 | Score: 8.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
MEDIUM[acquisition/browser_capture.py → _capture_response (lines 142–204)]:
Network capture payloads are JSON-decoded synchronously directly within the _capture_worker task running on the main event loop. For multi-megabyte payloads (e.g., Next.js __NEXT_DATA__ chunks or React Server Components), json.loads(text) is CPU-bound and blocks the async loop, potentially causing Playwright protocol timeouts.
Verification: grep -r "json.loads(text)" backend/app/services/acquisition/browser_capture.py
Verdict: Context and connection management is strict (Playwright objects and HTTP clients are properly released). Synchronous JSON decoding of large browser intercepts is the primary risk to event loop responsiveness.
Dimension: D4. Extraction & Normalisation Pipeline
Floor: 4/10 | Ceiling: 9/10 | Score: 6.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
CRITICAL[pipeline/core.py → _run_normalization_stage (lines 352–360) and field_value_core.py → validate_and_clean (lines 432–472)]:
The validate_and_clean function, which explicitly strips type-mismatched fields based on the surface's output schema, is completely dead code. It is never called. Consequently, _run_normalization_stage currently acts as a pass-through. This violates INVARIANT #10 (records contain only populated logical fields) because un-coerced types (e.g., variants="not-a-list") can bypass the extraction boundary and reach persistence.
Verification: grep -rn "def validate_and_clean" backend/app/services/field_value_core.py followed by grep -r "validate_and_clean(" backend/app/services/pipeline/core.py (which returns empty).
Verdict: The extraction hierarchy and provenance tracking are excellent. However, the failure to invoke the final validation gate defeats the purpose of the output schema, creating a severe data integrity risk.
Dimension: D5. Traversal Mode
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
No violations found.
Verification: grep -r "except Exception:" backend/app/services/acquisition/traversal.py returns no bare swallows for critical traversal logic. Same-origin checks correctly utilize path_tenant_boundary_family.
Verdict: Traversal accurately distinguishes between UI intent (paginate, load_more) and applies robust cycle detection, including safeguards against path-based cross-tenant bleeding.
Dimension: D6. Resilience & Error Handling
Floor: 9/10 | Ceiling: 9/10 | Score: 9.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
No violations found.
Verification: LLM failures gracefully exit via _validate_task_payload without raising fatal exceptions. is_non_retryable_http_status correctly shields browser resources from 401s and terminal 4xx errors.
Verdict: Exceptional resilience. Error state is carefully mapped to telemetry events and browser_diagnostics rather than swallowing exceptions or crashing the pipeline.
Dimension: D7. Dead Code & Technical Debt
Floor: 6/10 | Ceiling: 8/10 | Score: 7.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
HIGH [record_export_service.py (lines 620–625)]:
Contains re-export stubs at the bottom of the file (_render_markdown_inline = render_markdown_inline, etc.) kept around after a refactor. This is a direct AP-6 violation (compatibility shims left behind) that clutters the module namespace.
Verification: grep -rn "_render_markdown_inline = render_markdown_inline" backend/app/services/record_export_service.py
HIGH [See D4]:
validate_and_clean is fully implemented but disconnected from the execution graph.
Verdict: While the codebase is post-refactor and mostly free of legacy rot, disconnected architectural components and leftover re-exports still represent meaningful technical debt.
Dimension: D8. Acquisition Mode
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
MEDIUM[acquisition/runtime.py → _curl_fetch_sync (lines 358–361)]:
The curl_cffi fetcher ignores the http_user_agent defined in crawler_runtime_settings and hardcodes its own Accept and Accept-Language headers, creating divergence in header fingerprints between httpx and curl_cffi requests.
Verification: grep -rn '"Accept-Language": "en-US,en;q=0.9"' backend/app/services/acquisition/runtime.py
Verdict: Browser fallback orchestration is highly sophisticated, accurately gating Playwright usage behind content-length and JavaScript-shell heuristic checks. Minor header inconsistencies exist in the HTTP fetchers.
Section 9: Final Summary
Overall Score: 7.8/10 (previous: N/A, delta: N/A)
Root Cause Findings (architectural — require a plan, not a bug fix):
RC-1: validate_and_clean schema enforcement is disconnected from the pipeline — affects D4, D7
Leaf Node Findings (isolated bugs — Codex can fix directly):
LN-1: pipeline/core.py hardcodes _LLM_EXISTING_VALUE_MAX_CHARS = 500 instead of reading llm_runtime_settings.
LN-2: pipeline/core.py contains inline HTML parsing/stripping logic for LLM truncation.
LN-3: record_export_service.py retains AP-6 legacy re-export shims at the bottom of the file.
LN-4: curl_fetch_sync in acquisition/runtime.py hardcodes headers instead of sharing configuration with httpx.
Genuine Strengths (file-level evidence only, no generic praise):
browser_identity.py → _is_version_coherent: Expert-level fingerprint validation that correctly discards mismatched navigator.userAgentData bounds to prevent bot-detection flags.
js_state_mapper.py → _revive_flattened_slot: Implements an advanced Nuxt payload reviver capable of stitching together flattened array references, capturing state that generic JSON extractors miss.
Section 10: Codex-Ready Work Orders
WORK ORDER RC-1: Connect Post-Extraction Schema Validation to PipelineTouches buckets: API + Bootstrap, Extraction
Risk: CRITICAL
Do NOT touch: field_value_core.py (the logic there is correct, it just needs to be called).
What is wrong
The function validate_and_clean in field_value_core.py is supposed to enforce output schemas (e.g., setting a field to None if a string is expected but a list is found). However, it is never called anywhere in the extraction pipeline. Records are bypassing schema validation before persistence.
What to do
In app/services/pipeline/core.py, locate _run_normalization_stage.
Import validate_and_clean and clean_record from app.services.field_value_core.
Update _run_normalization_stage to iterate through extracted.records, apply validate_and_clean(record, context.surface), log any generated schema validation errors (as warnings, but don't fail the crawl), and apply clean_record(cleaned_data) to strip the resulting None values.
Return the updated records via the _ExtractedURLStage object.
Acceptance criteria

_run_normalization_stage explicitly iterates over extracted records and applies validate_and_clean.

Invalid types generated by adapters or generic extractors are successfully stripped before reaching persist_extracted_records.

python -m pytest tests -q exits 0.
What NOT to do
Do not modify the implementation of validate_and_clean itself.
Do not drop records entirely if a single field fails validation; only drop the invalid field.
WORK ORDER LN-1: Connect LLM Existing Value Max Chars to Runtime Settings (single-session fix)
File: backend/app/services/pipeline/core.py
Function: _sanitize_llm_existing_values
Fix: Remove the hardcoded _LLM_EXISTING_VALUE_MAX_CHARS = 500. Import llm_runtime_settings from app.services.config.llm_runtime and use llm_runtime_settings.existing_values_max_chars for truncation.
Test: grep -r "_LLM_EXISTING_VALUE_MAX_CHARS" backend/app/services/ should return empty.
WORK ORDER LN-2: Remove Inline HTML Stripper from Pipeline (single-session fix)
File: backend/app/services/pipeline/core.py
Function: _sanitize_llm_existing_values
Fix: Move the inline _Stripper class (HTMLParser) to app/services/text_sanitization.py as a generic utility function (e.g., strip_html_tags), and import it into core.py to clean the strings.
Test: grep -rn "class _Stripper" backend/app/services/pipeline/core.py should return empty.
WORK ORDER LN-3: Remove AP-6 Export Shims from Record Export Service (single-session fix)
File: backend/app/services/record_export_service.py
Function: Global scope (bottom of file)
Fix: Delete lines 620-625 containing _render_markdown_inline = render_markdown_inline, _render_markdown_block = render_markdown_block, etc.
Test: grep -rn "_render_markdown_inline =" backend/app/services/record_export_service.py should return empty.
ARCHITECTURAL RECOMMENDATIONS
Pydantic Output Validation
Applies to: Diffbot, Zyte.
Gap: RC-1 (Manual type checking via type(value).__name__ in validate_and_clean).
Slot: Pipeline normalisation stage.
Pseudocode:
code
Applies to: Crawlee, Apify.
Gap: D3 (Synchronous JSON/RSC parsing blocking the event loop in browser_capture.py).
Slot: Acquisition (browser_capture.py -> read_network_payload_body).
Pseudocode:
code
Python
import asyncio

async def _decode_rsc_payload_async(body_bytes: bytes) -> object | None:
    return await asyncio.to_thread(_decode_rsc_payload, body_bytes.decode('utf-8'))
Yield: Prevents Playwright websocket disconnects during heavy extraction loads by keeping the main event loop free while Megabyte-sized RSC blobs are parsed in a worker thread.