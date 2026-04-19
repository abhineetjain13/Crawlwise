1. SOLID / DRY / KISS — Core Software Principles
Score: 3/10
Violations:
[CRITICAL] pipeline/core.py → _process_single_url (lines 145–298): Massive God function. Handles robots.txt validation, HTTP/Browser acquisition, network payload injection, adapter execution, fallback extraction, DB logging, URL metric finalization, and selector self-healing in a single linear block. Blatant SRP violation making unit testing impossible without mocking the universe.
[HIGH] js_state_mapper.py → _map_js_state_to_fields (lines 80-90): Directly references _map_job_detail_state and _map_ecommerce_detail_state which internally hardcode schema keys (REMIX_GREENHOUSE_SPEC). OCP violation; adding a new platform requires modifying the generic state mapper.
[HIGH] adapters/adp.py, adapters/greenhouse.py, adapters/icims.py: Repeated implementation of _clean_text (e.g., adp.py lines 152-153) despite the existence of app.services.field_value_utils.clean_text. DRY violation.
[MEDIUM] config/_module_exports.py → make_getattr (lines 7-30): Over-engineered dynamic module attribute injection to override __getattr__. Breaks IDE autocompletion, static typing (mypy), and makes configuration resolution unnecessarily opaque (KISS violation).
Verdict: The core pipeline is heavily procedural rather than object-oriented or composed of discrete functional stages. Dynamic config injection and adapter-level boilerplate create unnecessary technical debt.
2. Configuration Hygiene — No Site-Specific Hacks
Score: 2/10
Violations:
[CRITICAL] crawl_fetch_runtime.py → _classify_network_endpoint (lines 541–558): Hardcodes site-specific domains ("greenhouse", "workday", "lever.co", "shopify") directly inside the core browser interception logic. Pure hack. This logic belongs in platform_policy.json and the PlatformRegistryDocument.
[HIGH] js_state_mapper.py → REMIX_GREENHOUSE_SPEC (lines 53-80): Hardcodes a site-specific Greenhouse JSONPath schema into the generic JS state mapper.
[MEDIUM] domain_utils.py → normalize_domain (lines 24-26): Hardcodes port 80 and 443 stripping inside business logic rather than referencing configuration or standard library constants.
[LOW] platform_url_normalizers.py → normalize_adp_detail_url (lines 10-14): Site-specific normalizer lives in global scope rather than being encapsulated within the ADPAdapter boundary.
Verdict: Severe configuration hygiene failures. The abstraction boundary between the generic crawler engine and platform-specific heuristics is completely broken by inline string matching in hot paths.
3. Scalability, Maintainability & Resource Management
Score: 4/10
Violations:
[CRITICAL] crawl_fetch_runtime.py → is_blocked_html (lines 122–171): Performs synchronous, CPU-bound BeautifulSoup parsing and DOM iteration (node.decompose(), soup.get_text()) directly on the async event loop. Will stall the event loop under concurrent load.
[HIGH] script_text_extractor.py → iter_script_text_nodes (lines 14-25): Uses Selector(text=html) synchronously. parsel parsing is CPU-intensive and blocks the async thread.
[HIGH] crawl_fetch_runtime.py → _capture_response (lines 280-285): Reads response.body() into memory without stream chunking. Though constrained by _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES, 500KB * 25 payloads * N concurrent contexts = OOM risk under heavy concurrency.
[MEDIUM] crawl_service.py → _track_local_run_task (lines 59-86): Spawns unbounded asyncio.create_task references into a global _local_run_tasks dictionary. While it has a _cleanup callback, task cancellation during shutdown creates race conditions handled clumsily by recover_stale_local_runs.
Verdict: CPU-bound HTML parsing on the async event loop is a fatal flaw that will choke the API and Celery workers under scale. Resource tracking relies on globals rather than structured concurrency.
4. Extraction & Normalisation Pipeline Audit
Score: 6/10
Violations:
[CRITICAL] detail_extractor.py → _materialize_record (lines 169–200): Accumulates candidates using candidates.get(field_name,[]). finalize_candidate_value blindly takes the first value without sorting by source tier. Because build_detail_record invokes sources in priority order, it usually works, but _apply_dom_fallbacks arbitrarily mutates candidates. Unsafe implicit priority ranking.
[HIGH] crawl_fetch_runtime.py → expand_all_interactive_elements (lines 393-448): Blindly selects [data-testid*='expand'] and invokes .click(). Missing AOM/visibility checks prior to clicking, causing potential overlap/modal interference.
[MEDIUM] selector_self_heal.py → reduce_html_for_selector_synthesis (lines 26-28): Slices HTML at 200,000 characters (text[:200_000]). Blind string slicing of HTML creates malformed markup, which is then fed to the LLM for XPath synthesis, causing hallucinations.
[MEDIUM] records.py → CrawlRecordResponse._clean_for_display (lines 52-66): The API schema relies on a Pydantic model_validator to scrub _ prefixed fields instead of maintaining a strict separation between raw DB models and external DTOs.
Verdict: The extraction hierarchy works conceptually, but implementation relies on implicit ordering rather than strict, typed source-priority tracking. The LLM context truncation is dangerously naive.
5. Traversal Mode Audit
Score: 5/10
Violations:
[CRITICAL] traversal.py → _run_paginate_traversal (lines 142-150): Uses urljoin(current_url, href) and issues page.goto(). If the pagination link points to a cross-domain promotion or relative path escaping the tenant, the crawler escapes the domain boundary. Missing same-origin enforcement constraint.
[HIGH] traversal.py → _run_paginate_traversal (lines 151): Uses locator.click(timeout=1000) without capturing the resulting navigation Promise, leading to race conditions where _page_snapshot captures the DOM before the SPA transition completes.
[MEDIUM] crawl_utils.py → resolve_traversal_mode (lines 100-131): Complex string normalizations ("infinite_scroll" to "scroll", "view_all" to "load_more") mixed with legacy advanced_mode flags. Tangled configuration inheritance.
Verdict: Traversal lacks robust off-domain protection and mismanages Playwright's asynchronous navigation lifecycle during pagination.
6. Resilience & Error Handling
Score: 4/10
Violations:
[HIGH] crawl_fetch_runtime.py → _capture_response (lines 280-285, 289-296): Contains bare except Exception: return. Silently swallows JSON decode errors and body read failures without updating URL metrics or logging the failure reason cleanly to the run.
[HIGH] robots_policy.py → _fetch_robots_snapshot (lines 60-84): Catches generic Exception implicitly via (TimeoutError, URLError, OSError, ValueError). However, urlopen blocks the thread indefinitely if the underlying socket hangs because Python's default socket timeout isn't strictly honored by all TLS handshakes unless specified at the context level.
[MEDIUM] crawl_fetch_runtime.py → _browser_fetch (lines 331-344): goto wrapped in try/except falling back to wait_until="commit". But if the page crashes entirely (Target Closed), it raises TargetClosedError which is swallowed and returned as a generic 200 OK with whatever empty DOM was present.
Verdict: Widespread use of broad exception catching (except Exception) that masks underlying Playwright instability and network partition errors.
7. Dead Code & Technical Debt Hotspots
Score: 6/10
Violations:
[MEDIUM] crawl_state.py → update_run_status (line 25): # TODO: implement event publishing. Leftover technical debt in core state transitions.
[MEDIUM] runtime_helpers.py → log_for_pytest (lines 13-14): Exists entirely to be patched in tests. Production code should never contain test-specific stubs.
[LOW] browser_pool.py → BrowserPool (lines 22-23): Empty class stub (pass) that serves no purpose, as browser pool logic is handled by SharedBrowserRuntime in crawl_fetch_runtime.py.
Verdict: Moderate technical debt. Test-specific hooks in production files break boundary cleanliness.
8. Acquisition Mode Audit & Site Coverage
Score: 5/10
Violations:
[CRITICAL] network_payload_specs.py → NETWORK_PAYLOAD_SPECS (lines 11-140): Completely missing declarative specs for Workday, Taleo, Lever, and standard SPA commerce APIs. The framework supports XHR mapping but lacks the actual definitions, resulting in silent fallback to DOM scraping for these platforms.
[HIGH] crawl_fetch_runtime.py → fetch_page (lines 504-511): The decision to escalate to browser (_should_escalate_to_browser) relies on _looks_like_js_shell which triggers if text < 120 chars and 3+ scripts exist. Extremely brittle heuristic that fails on modern SSR-hydrated sites that ship substantial text but require JS for the specific extraction targets.
[MEDIUM] browser_identity.py → create_browser_identity (lines 19-36): Generates realistic fingerprints but drops user-agent from extra_http_headers and passes it via context options, which in Playwright CDP can mismatch navigator.userAgent unless userAgent is strictly aligned in CDP overrides.
Verdict: The XHR interception engine is conceptually strong but practically empty due to missing payload specs. Escalation heuristics to the browser are brittle.
FINAL SUMMARY
Overall Score: 4.5/10
Critical Path:
CPU-Blocking I/O in Async Paths: is_blocked_html and iter_script_text_nodes run synchronous BeautifulSoup and parsel operations on the async event loop, risking complete API/worker deadlock under high concurrency.
SRP Violation in _process_single_url: The 150-line monolith in pipeline/core.py intertwines network I/O, LLM execution, DOM parsing, and database transactions, making isolated error recovery impossible.
Off-Domain Pagination Leaks: _run_paginate_traversal blindly follows href attributes via page.goto(), allowing the crawler to escape the target tenant and scrape unintended external domains.
Configuration Bleed: Hardcoded domains ("greenhouse", "workday", "shopify") in crawl_fetch_runtime.py bypass the platform_policy configuration engine.
Memory Exhaustion via XHR Interception: Unbounded body byte accumulation in _capture_response risks OOM crashes when Playwright context concurrency scales up.
Genuine Strengths:
Selector Self-Healing Loop: selector_self_heal.py successfully implements an autonomous feedback loop, calling the LLM (discover_xpath_candidates), validating the output (_validated_xpath_rules), and persisting it back to domain_memory for future runs.
Robust Field Normalization: field_value_core.py and normalizers.py effectively execute rigorous standardizations (cent-to-dollar conversions, clean location concatenations, tracker query stripping) safely decoupled from extraction.
TOP 5 ARCHITECTURAL RECOMMENDATIONS
1. Decouple CPU-Bound HTML Parsing from the Event Loop
Target: crawl_fetch_runtime.py (is_blocked_html), script_text_extractor.py.
Current: Synchronous BeautifulSoup and parsel parsing runs directly in async def functions, blocking the asyncio loop.
Target Structure: Wrap all BeautifulSoup(html, "html.parser") and Selector(text=html) calls in asyncio.to_thread(). For extraction, instantiate a singleton ProcessPoolExecutor for heavy DOM traversal.
Simplification: Prevents the need to sprinkle await asyncio.sleep(0) hacks. Cleanly segregates I/O tasks from CPU tasks.
Outcome: Eliminates worker deadlocks and drastically improves concurrent request throughput.
2. Refactor _process_single_url using the Chain of Responsibility
Target: pipeline/core.py (_process_single_url).
Current: A massive monolithic function checking robots.txt, fetching, adapting, parsing, LLM fallback, and saving.
Target Structure:

class PipelineContext: url: str; run: CrawlRun; html: str; records: list
class PipelineStage(Protocol): async def process(ctx: PipelineContext) -> None
# Implement: RobotsStage, AcquisitionStage, AdapterStage, DomExtractionStage, LLMFallbackStage, PersistenceStage.
Simplification: Reduces core.py from 300+ lines of nested if statements to a clear, iterable array of stage execution.
Outcome: Resolves the SRP violation, allows unit testing individual pipeline stages, and isolates DB transaction boundaries.
3. Enforce strict Domain Boundaries in Traversal
Target: traversal.py (_run_paginate_traversal).
Current: await page.goto(urljoin(current_url, href)) navigates without verifying the destination host.
Target Structure: Extract the netloc of the original run URL. Before page.goto, compare urlparse(next_url).netloc. If it diverges, raise an OffDomainTraversalError and halt pagination.
Simplification: Consolidates domain safety checks.
Outcome: Prevents the crawler from bleeding into external advertising, social media, or partner sites during unbounded pagination.
4. Purge Tenant Hardcodes from the Acquisition Runtime
Target: crawl_fetch_runtime.py (_classify_network_endpoint), js_state_mapper.py.
Current: Hardcodes strings like "greenhouse" and "shopify" in generic pipeline interceptors.
Target Structure: Use the existing PlatformConfig. Add network_signatures and js_state_roots to the schema in platforms.json. Read these inside _classify_network_endpoint dynamically via platform_configs().
Simplification: Removes branch logic and centralizes all tenant-specific behaviors into JSON config.
Outcome: Restores OCP compliance and makes adding new XHR-intercepted platforms a config-only operation.
5. Safe HTML Truncation via DOM Parsing
Target: selector_self_heal.py (reduce_html_for_selector_synthesis).
Current: Performs blind string slicing (text[:200_000]), potentially truncating in the middle of a <div... which breaks XPath syntax generation in the LLM.
Target Structure: Use BeautifulSoup to find the main content node (<main>, <article>, or #root). Serialize only that node. If still too large, iteratively .decompose() non-essential tags (footers, asides) before serialization.
Simplification: Removes arbitrary character limits in favor of semantic content extraction.
Outcome: Prevents LLM hallucinations caused by malformed HTML strings, improving selector synthesis accuracy.
EXTRACTION ENHANCEMENT RECOMMENDATIONS
1. XHR Ghost-Routing / Playwright Request Interception
Concept: (Apify/Zyte pattern). Modern ATS platforms (Workday, Taleo, Lever) load job data via background JSON APIs. Parsing the DOM is brittle and slow.
Gap Addressed: network_payload_specs.py is virtually empty. The system is equipped to intercept JSON but lacks the mappings for the most critical enterprise ATS platforms.
Implementation Sketch:
code
Python
# network_payload_specs.py
"job_detail": (
    {
        "name": "workday_detail",
        "required_path_groups": (("jobPostingInfo",),),
        "field_paths": {
            "title": ("jobPostingInfo.title",),
            "description_html": ("jobPostingInfo.jobDescription",),
            "location": ("jobPostingInfo.location",),
            "posted_date": ("jobPostingInfo.startDate",)
        }
    },
)
Yield Improvement: Near 100% precision on Workday/Lever jobs. Reduces reliance on the brittle _apply_dom_fallbacks and entirely skips LLM fallback for these platforms.
2. Schema Healing via Declarative Path Specs (glom)
Concept: (Diffbot/glom pattern). Replace massive nested if/elif dictionary retrieval logic with declarative fallback paths.
Gap Addressed: structured_sources.py _parse_opengraph_fallback and _parse_microdata_node are deeply nested and prone to missing variant keys.
Implementation Sketch:
code
Python
from glom import glom, Coalesce

# Replace nested dict.get() chains:
OPENGRAPH_SPEC = {
    "title": Coalesce("og:title", "twitter:title", default=None),
    "image": Coalesce("og:image", "og:image:secure_url", "twitter:image", default=None),
    "price": Coalesce("product:price:amount", "og:price:amount", default=None),
}
normalized = glom(raw_meta_tags, OPENGRAPH_SPEC)
Yield Improvement: Significant cleanup of technical debt in structured data parsing. Uncovers hidden image and price data currently missed due to slight key variations.
3. Accessibility Tree (AOM) Snapshotting for LLM Context
Concept: (Scrapy-Playwright / Diffbot pattern). Instead of feeding raw HTML to the LLM for missing field extraction, feed it the Accessibility Object Model (AOM) tree, which represents exactly what the user sees hierarchically.
Gap Addressed: llm_tasks.py truncates raw HTML (which is 90% markup noise) via _truncate_html.
Implementation Sketch:
code
Python
# crawl_fetch_runtime.py
async def _capture_aom_snapshot(page: Page) -> str:
    snapshot = await page.accessibility.snapshot()
    # Recursively format node['role'] and node['name']
    def format_node(node, indent=0):
        text = f"{'  ' * indent}[{node['role']}] {node.get('name', '')}\n"
        for child in node.get('children',