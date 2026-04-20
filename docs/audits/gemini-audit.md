1. SOLID / DRY / KISS — Core Software Principles
Score: 4/10
Violations:
[HIGH] app/services/detail_extractor.py → build_detail_record (lines 280–385):
Violates Single Responsibility Principle (SRP) and Testability. This function is a massive closure factory that defines four nested functions (_collect_authoritative_stage, _collect_structured_stage, etc.) which silently mutate outer-scope dictionaries (candidates, candidate_sources, field_sources). This makes the individual extraction phases completely untestable in isolation and tightly couples candidate collection to the final materialization step.
[MEDIUM] app/services/adapters/adp.py → _text (lines 14 & 166):
Violates DRY. A module-level helper _text() is defined, but the class also implements an identical self._text() instance method.
[MEDIUM] app/services/llm_tasks.py → _validate_task_payload and children (lines 212–306):
Violates KISS. Over 90 lines of manual isinstance, dict.get, and string formatting checks to validate LLM JSON payloads. The project already uses Pydantic extensively (e.g., app/schemas), rendering this massive wall of imperative validation code obsolete technical debt.
Verdict: The extraction pipeline relies heavily on nested closures mutating shared state, making the core data flow opaque and fragile. Basic schema validation is hand-rolled rather than utilizing the existing Pydantic framework.
2. Configuration Hygiene — No Site-Specific Hacks
Score: 3/10
Violations:
[CRITICAL] app/services/platform_url_normalizers.py → normalize_adp_detail_url (lines 9–14):
Violates Open-Closed Principle (OCP) and Configuration Hygiene. ADP-specific domains (workforcenow.adp.com, myjobs.adp.com) are hardcoded directly into the Python logic. If a new ADP tenant domain is added to platforms.json, the normalizer will silently fail to process it because it relies on this hardcoded bypass.
[HIGH] app/services/adapters/greenhouse.py, jibe.py, saashr.py, oracle_hcm.py, paycom.py, ultipro.py (Multiple locations):
Magic numbers. Widespread hardcoding of timeout_seconds=10 or timeout_seconds=12 directly inside HTTP adapter calls. This ignores adapter_runtime_settings and crawler_runtime_settings, making it impossible for operators to globally scale timeouts during high-latency events.
[MEDIUM] app/services/field_value_dom.py → _image_candidate_score (line 72):
Hardcoded query parameters (w, h, width, height) for CDN images inside logic rather than referencing the _CDN_IMAGE_QUERY_PARAMS constant defined earlier in the file.
Verdict: Domain routing and timeout configurations are leaking out of the configuration files and becoming embedded as magic strings/numbers directly inside the execution paths.
3. Scalability, Maintainability & Resource Management
Score: 2/10
Violations:
[CRITICAL] app/services/pipeline/core.py → _run_extraction_stage (lines 222 & 259):
Blocks the async event loop. _extract_records_for_acquisition calls extract_records completely synchronously. extract_records triggers BeautifulSoup parsing, Lexbor HTML parsing, JSON-LD decoding, JMESPath queries, and extruct microdata parsing. Running CPU-bound DOM parsing synchronously on the main thread will catastrophicly stall the FastAPI event loop under concurrent load.
[HIGH] app/services/crawl_service.py → _track_local_run_task (lines 80–91):
Unsafe task tracking. Spawns an untracked background failure task (failure_task = asyncio.create_task(_record_failure())) inside a callback. If the application receives a SIGTERM before this task completes, the failure state will be lost, leaving phantom "RUNNING" jobs in the database.
[MEDIUM] app/services/extraction_context.py → prepare_extraction_context (line 30):
Destructive DOM mutation prior to parsing. It calls node.decompose() on noise containers before giving structural extractors a chance to run. If the selector is overly aggressive, it permanently destroys DOM data that cannot be recovered by downstream fallback extractors.
Verdict: The failure to offload heavy DOM and JSON parsing to a thread pool (asyncio.to_thread) is a fatal flaw that guarantees event loop starvation in production.
4. Extraction & Normalisation Pipeline Audit
Score: 7/10
Violations:
[HIGH] app/services/field_value_dom.py → apply_selector_fallbacks (lines 351–386):
Source ranking pollution. It blindly executes all custom selector rules and generic DOM patterns, appending them to candidates without tracking the precision of the match. Because _ordered_candidates_for_field treats all dom_selector matches as equally ranked, a highly precise user-defined XPath can be overwritten by a generic regex fallback if they end up in the same bucket.
[MEDIUM] app/services/adapters/greenhouse.py → _extract_detail_from_html (lines 142–165):
Redundant DOM extraction. Adapters like Greenhouse and OracleHCM manually implement BS4 h1 and body scraping fallbacks. This logic is already perfectly handled by the generic pipeline's dom_h1 and dom_sections tiers. It duplicates logic and bypasses the generic confidence scoring mechanism.
[MEDIUM] app/services/field_policy.py → get_surface_field_aliases (lines 40–60):
Surface Bleed Risk. The dynamic patching of alias dictionaries based on normalized.startswith("ecommerce_") mutates aliases at runtime. While technically contained, this approach risks injecting job-specific aliases (like commitment) into commerce searches if the alias dictionary boundaries drift.
Verdict: Excellent inclusion of AOM, JMESPath XHR interception, and Hydrated State extraction. However, the adapter layer duplicates generic DOM logic, and selector ranking lacks tie-breaking granularity.
5. Traversal Mode Audit
Score: 8/10
Violations:
[LOW] app/services/acquisition/traversal.py → _looks_like_paginate_control (lines 352–395):
Executes a massive block of inline JavaScript inside Playwright locator.evaluate. While functionally correct, embedding 40 lines of raw JavaScript inside a Python string makes linting, testing, and escaping incredibly brittle.
Verdict: Highly robust cycle detection and pagination fallback heuristics. Traversal appropriately isolates advanced modes from standard escalation pathways.
6. Resilience & Error Handling
Score: 5/10
Violations:
[HIGH] app/services/crawl_fetch_runtime.py → fetch_page (lines 160, 218):
Catches bare Exception during HTTP fetch loops and Browser fallbacks without localized retry logic. If a transient httpx.ConnectTimeout occurs, it immediately escalates to a full Browser render or fails the job entirely, bypassing the intended http_retry_status_codes backoff behavior which is completely absent in the fetch_page function.
[MEDIUM] app/services/field_value_dom.py → safe_select (line 155):
except Exception: logger.debug(...); return[]. Swallows CSS syntax errors silently. If a user provides a malformed CSS selector in their domain memory, it will fail silently in the background rather than surfacing a validation error to the control plane.
[MEDIUM] app/services/llm_tasks.py → _trim_prompt_section_body (line 343):
Swallows json.JSONDecodeError with a bare pass. If the LLM prompt truncation splits a JSON string exactly at a boundary that makes it invalid, it falls back to raw string truncation which often breaks the LLM's parsing ability entirely.
Verdict: Error boundaries are too wide. Bare exception handlers mask root causes, and transient HTTP failures escalate to heavy browser loads instead of intelligently backing off.
7. Dead Code & Technical Debt Hotspots
Score: 6/10
Violations:
[HIGH] app/services/pipeline/core.py → _validate_llm_field_type (lines 92–106):
Technical Debt. It contains a hardcoded _LLML_FIELD_TYPE_VALIDATORS map that duplicates schema definitions already present in app/services/config/field_mappings.py.
[MEDIUM] app/services/extraction_html_helpers.py → extract_job_sections (lines 7–12):
Technical Debt. Contains a hardcoded dictionary _JOB_SECTION_PATTERNS ("what you", "qualif", "perks") for semantic extraction. This logic should be externalized to the EXTRACTION_RULES JSON config rather than living inside executable code.
[LOW] app/services/llm_runtime.py (lines 14–29):
Exports discover_xpath_candidates, extract_missing_fields directly from llm_tasks.py creating circular dependency risks and muddying module boundaries.
Verdict: Several extraction heuristics remain hardcoded in Python files rather than utilizing the centralized JSON rule engine, creating maintenance debt.
8. Acquisition Mode Audit & Site Coverage
Score: 8/10
Violations:
[MEDIUM] app/services/structured_sources.py → harvest_js_state_objects (lines 191–214):
__NUXT_DATA__ extraction is present but lacks native support for React Query (__APOLLO_STATE__) hydration reconstruction. While the prompt identifies it as a target, the implementation strictly maps Nuxt and NextJS, leaving a JS-truth coverage gap for major Shopify headless storefronts that use Apollo.
[LOW] app/services/pipeline/core.py → _build_acquisition_request (lines 173–183):
Generates a completely new AcquisitionProfile per URL. Browser identities and fingerprint states should ideally be pinned to the run_id across multiple URLs in the same run to avoid triggering bot-defenses due to rapidly changing TLS/Browser fingerprints mid-crawl.
Verdict: Outstanding implementation of Ghost-routing via NETWORK_PAYLOAD_SPECS. The fallback matrix is highly logical, though cross-request fingerprint persistence is missing.
FINAL SUMMARY
Overall Score: 5.3/10
Critical Path:
Async Event Loop Starvation: _run_extraction_stage calls heavily CPU-bound DOM parsing (BeautifulSoup, Lexbor, extruct) synchronously in the main async path, which will completely lock up the FastAPI server under moderate concurrent load.
Hardcoded Tenant Normalization: platform_url_normalizers.py hardcodes ADP domains, bypassing OCP and the platforms.json registry, meaning new ADP tenants will silently fail.
Task Tracking Data Loss: _track_local_run_task spawns unawaited background failure tasks; abrupt worker terminations will leave jobs stuck in the RUNNING state indefinitely.
Missing HTTP Backoff: fetch_page catches transient HTTP errors and immediately escalates to Playwright rather than honoring configured retry/backoff policies, drastically inflating infrastructure costs.
Selector Ranking Pollution: Generic DOM fallbacks and high-precision user selectors are placed in the same confidence bucket, allowing low-quality regex guesses to overwrite user-defined domain memory rules.
Genuine Strengths:
XHR Ghost-Routing: network_payload_mapper.py implements a brilliant, signature-based inference engine (_body_matches_signature_quick) to automatically map intercepted JSON payloads to canonical schemas without requiring brittle, site-specific API paths.
AOM Accessibility Extraction: browser_runtime.py explicitly utilizes the Accessibility Object Model (page.accessibility.snapshot()) to find and expand hidden interactive elements (accordions, tabs) before extraction, bypassing visual obfuscation cleanly.
Selector Self-Healing: selector_self_heal.py correctly reduces the DOM (reduce_html_for_selector_synthesis) before passing it to the LLM, ensuring token budgets are respected, and validates the generated XPath dynamically against the page before saving to domain memory.
TOP 5 ARCHITECTURAL RECOMMENDATIONS
1. Offload CPU-Bound Extraction to Thread Pool
Affected: app/services/pipeline/core.py (_run_extraction_stage)
Current: extract_records executes massive HTML parsing workloads synchronously, blocking asyncio.
Target:
code
Python
records, selector_rules = await asyncio.to_thread(
    _extract_records_for_acquisition, context, fetched
)
Simplification: Prevents the need to run the crawler in a multiprocess Gunicorn setup just to handle parsing blocking. 1-line fix.
Outcome: Eliminates Event Loop Starvation (Critical Path #1); Scalability score improves instantly.
2. Pydantic Model Validation for LLM Payloads
Affected: app/services/llm_tasks.py (_validate_task_payload, _validate_field_cleanup_review_payload, etc.)
Current: 90+ lines of brittle isinstance and .get() type-checking strings.
Target: Define standard Pydantic models for expected LLM outputs.
code
Python
try:
    FieldCleanupResponse.model_validate(payload)
except ValidationError as e:
    return str(e)
Simplification: Deletes ~100 lines of manual validation code, replacing it with the framework already imported natively across the app.
Outcome: Reduces Technical Debt; improves LLM payload parsing reliability.
3. Remove Domain Logic from Source Files
Affected: app/services/platform_url_normalizers.py (normalize_adp_detail_url)
Current: Hardcodes domains workforcenow.adp.com etc.
Target: Read domains dynamically from platform_policy.py.
code
Python
config = platform_config_for_family("adp")
if hostname not in[urlparse(d).hostname for d in config.domain_patterns]:
    return url
Simplification: Centralizes all domain definitions to platforms.json, preventing split-brain configuration bugs.
Outcome: Fixes Configuration Hygiene (Critical Path #2); strictly adheres to OCP.
4. Implement HTTP Retry Wrapper in Fetcher
Affected: app/services/crawl_fetch_runtime.py (fetch_page)
Current: Wraps _curl_fetch and _http_fetch in a blanket except Exception, escalating to browser immediately.
Target: Implement tenacity or a custom retry loop that honors crawler_runtime_settings.http_retry_status_codes before giving up.
Simplification: Consolidates HTTP resilience into a standard decorator rather than wrapping control flow in nested try/except blocks.
Outcome: Fixes Missing HTTP Backoff (Critical Path #4); massively reduces unnecessary Playwright executions.
5. Flatten Detail Extractor Closure Factory
Affected: app/services/detail_extractor.py (build_detail_record)
Current: Defines four internal functions that mutate outer-scope variables (candidates).
Target: Pass candidates and context explicitly as arguments to pure module-level functions.
code
Python
def collect_dom_stage(context, candidates, field_sources, ...):
    # pure execution, returns modifications
Simplification: Removes hidden state mutations.
Outcome: Code becomes strictly testable via standard unit tests; SOLID score improves from 4 to 8.
EXTRACTION ENHANCEMENT RECOMMENDATIONS
1. Markdownify Node-Walking for Pre-LLM Context
Gap: Currently, _truncate_html uses string indexing to snip substrings around anchor keywords, passing raw <div class="x">... noise to the LLM, burning tokens on markup.
Reference: Jina AI Reader / Firecrawl.
Slot: LLM Task Payload formatting (llm_tasks.py).
Sketch:
code
Python
import markdownify
def extract_markdown_snippet(html: str, anchors: list[str]) -> str:
    md = markdownify.markdownify(html, strip=['script', 'style', 'nav', 'footer'])
    # Perform truncation on dense markdown instead of raw HTML
    return truncate_around_anchors(md, anchors, limit=8000)
Expected Yield: Drastically reduces LLM token consumption by 40-60% per call, improves missing_field_extraction accuracy by removing DOM attribute noise.
2. Bounding Box / Visual Prominence Extraction
Gap: The DOM extractor scores title candidates solely by attribute signatures (_card_title_score_parts). It cannot differentiate between a large central H1 and a visually hidden H1.
Reference: Diffbot VIPS (Visual Page Segmentation) / Zyte.
Slot: Post-Playwright execution DOM augmentation (browser_runtime.py).
Sketch:
code
JavaScript
// Inside Playwright evaluate:
const rect = el.getBoundingClientRect();
el.setAttribute('data-area', rect.width * rect.height);
el.setAttribute('data-center-x', rect.left + rect.width/2);
Then, in field_value_dom.py, add a scoring bonus for nodes with the highest data-area that reside near the horizontal center.
Expected Yield: Resolves tie-breakers between generic titles and actual product/job titles accurately 95%+ of the time, reducing reliance on LLM title promotion.
3. Declarative Schema Healing via glom (Extended)
Gap: While glom is used in js_state_mapper.py for product API payloads, the network payload ghost-router (network_payload_mapper.py) uses custom JMESPath logic (_first_non_empty_path), resulting in fragmented state-resolution strategies.
Reference: Scrapy Itemloaders / Diffbot Normalization.
Slot: network_payload_mapper.py
Sketch:
code
Python
from glom import glom, Coalesce
GHOST_PRODUCT_SPEC = {
    "price": Coalesce("price.current", "pricing.price", "price", default=None),
    "sku": Coalesce("identifiers.sku", "sku", default=None)
}
mapped = glom(body, GHOST_PRODUCT_SPEC, default={})
Expected Yield: Unifies the API for JSON traversal. Simplifies adding new platform fallbacks for network interception, making ghost-routing much easier to extend.