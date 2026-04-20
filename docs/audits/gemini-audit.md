. SOLID / DRY / KISS — Core Software Principles
Score: 3/10
Violations:
[CRITICAL] app/services/acquisition/browser_page_flow.py → finalize_browser_fetch (lines 173–281):
This is a god function that takes 19 arguments. It violates SRP by orchestrating payload capture closing, block classification, outcome determination, screenshot capturing, metric aggregation, and artifact dictionary building. It makes the acquisition layer impossible to test without mocking the entire world.
[HIGH] app/services/extraction_runtime.py → _extract_raw_json_records (lines 62–94):
Violates SRP and KISS. It handles raw string decoding, JSON parsing, JSON-list unwrapping, heuristic validation (_has_surface_field_overlap), candidate extraction, and deduplication all in a single linear flow.
[HIGH] app/services/structured_sources.py → _balanced_json_fragment (lines 180–211):
Violates KISS. A hand-rolled, character-by-character bracket matching loop to extract JSON from strings. This is notoriously brittle against escaped quotes, regex literals containing brackets, and malformed strings. Use an AST parser or a proven library like chompjs.
[MEDIUM] app/services/field_value_dom.py / app.services.adapters.*:
Violates DRY. Helper functions like _node_text, _node_attr, and DOM text cleaning logic are duplicated across nearly every adapter (amazon.py, ebay.py, linkedin.py) and the core DOM extractors.
Verdict: The codebase relies heavily on massive procedural functions with dozens of parameters rather than encapsulating state into cohesive, testable objects. The extraction logic is highly coupled to the traversal and parsing logic.
2. Configuration Hygiene — No Site-Specific Hacks
Score: 4/10
Violations:
[CRITICAL] app/services/traversal.py → _requires_path_tenant_boundary (lines 538-542):
Hardcodes a site-specific check for "workday" directly inside the generic _is_same_origin loop cycle detector. This is a severe OCP violation. If Workday needs tenant boundary checks, this must be driven entirely by platforms.json without leaking the string "workday" into the core traversal engine.
[HIGH] app/services/js_state_mapper.py → _DECLARATIVE_PRODUCT_ROOTS (lines 35-41):
Hardcodes Nuxt, Next, and Apollo state paths into the Python file instead of externalizing them to the platform registry. Furthermore, _revive_nuxt_data_array (lines 110-130) embeds Nuxt-specific graph hydration logic directly into the generic js_state_mapper.py.
[HIGH] app/services/config/extraction_rules.py → _acquisition_guard_export references (lines 28-36):
Hardcodes site-specific redirect shell checks for myworkdayjobs.com and schooljobs.com into the Python globals.
[MEDIUM] app/services/listing_extractor.py → _listing_fragment_score (lines 173-228):
Heavy use of inline magic numbers. Adds +6, -10, +4 to a score based on arbitrary text lengths (< 12, <= 2000). These heuristic weights are buried in the logic instead of configured centrally, making tuning a nightmare.
Verdict: The platform registry (platforms.json) exists, but developers routinely bypassed it to inject site-specific hardcodes (Workday, Nuxt, Shopify) directly into the core engine. This destroys the generic abstraction.
3. Scalability, Maintainability & Resource Management
Score: 4/10
Violations:
[CRITICAL] app/services/structured_sources.py & app/services/listing_extractor.py:
CPU-bound blocking I/O in async paths. Functions like parse_microdata_fallback, _extract_from_listing_html, and massive BeautifulSoup(html, "html.parser") invocations run directly on the async event loop. For a 2MB HTML payload, BS4 parsing blocks the thread for 200-500ms, starving all other concurrent requests in the FastAPI/Celery worker.
[HIGH] app/services/browser_runtime.py → _block_unneeded_route (lines 127-142):
If route.abort() or route.continue_() throw an exception, it is caught and logged, but the request is left hanging. Playwright requires routes to be explicitly handled; if an error occurs and neither is called successfully, the browser request hangs indefinitely until the global timeout.
[MEDIUM] app/services/traversal.py → _run_paginate_traversal (lines 235-316):
Unbounded data structure. visited_urls: set[str] grows infinitely. While max_pages bounds it normally, if max_pages is misconfigured or disabled, a cyclic pagination trap will OOM the worker.
Verdict: CPU-bound HTML parsing is illegally intermingled with async I/O. The system will suffer from severe event loop starvation under high concurrency.
4. Extraction & Normalisation Pipeline Audit
Score: 2/10
Violations:
[CRITICAL] app/services/field_value_core.py → validate_and_clean (lines 351-378):
Schema pollution. The function claims to validate against _OUTPUT_SCHEMAS. However, line 368 states: if value in (...) or field_name not in schema: cleaned[field_name] = value; continue. This means if a rogue extractor emits "junk_field": "data", because "junk_field" is not in the schema, it is preserved and passed through to the output. This violates the strict output contract.
[HIGH] app/services/network_payload_mapper.py → _infer_surface_from_body (lines 182-192):
Uses simple key-counting (_PRODUCT_SIGNATURE, _JOB_SIGNATURE) to guess if a random JSON payload is a product or job. This is extremely loose and will trigger false positives on standard configuration dictionaries or localization bundles, polluting the pipeline with garbage JSON records.
[HIGH] app/services/field_value_core.py → normalize_decimal_price (lines 53-73):
Uses Decimal(candidate) without stripping currency symbols properly if the regex fails to isolate the number perfectly. Catching InvalidOperation is an expensive control flow mechanism.
[MEDIUM] app/services/record_export_service.py (lines 485-489):
Deadly export of private functions _render_markdown_inline = render_markdown_inline purely to bypass test visibility rules. This locks the internal implementation details into the public API signature.
Verdict: The extraction pipeline suffers from a catastrophic schema validation bug that permits silent data pollution. Heuristics for JSON payload detection are too loose, risking high false-positive extraction rates.
5. Traversal Mode Audit
Score: 6/10
Violations:
[HIGH] app/services/traversal.py → _click_with_retry (lines 388-448):
The fallback JS click uses node instanceof HTMLElement && node.click(). In many modern SPAs (React/Vue), programmatic clicks on the DOM node do not trigger the synthetic event handlers attached to the Fiber node. This will silently fail to paginate on React sites. It must dispatch a bubbling MouseEvent or use Playwright's native forceful clicking.
[MEDIUM] app/services/traversal.py → _detect_auto_mode (lines 114-129):
If it detects pagination controls but scroll_signals are also present, it defaults to pagination. Many modern sites use infinite scroll with a hidden pagination container for SEO. Relying on pagination when scroll is active will break traversal on those sites.
Verdict: Traversal logic handles basic cases and cycle detection well, but its click fallbacks and auto-detection prioritization are naive against modern React/Vue SPAs.
6. Resilience & Error Handling
Score: 5/10
Violations:
[CRITICAL] app/services/crawl_fetch_runtime.py → _run_http_fetch_chain (lines 201-213):
The pipeline attempts _curl_fetch and then _http_fetch sequentially inside the retry loop. If a target is unresponsive, it will timeout on curl_cffi, wait, and then timeout again on httpx before backing off. This doubles the timeout exposure and wastes massive amounts of worker time on dead targets.
[HIGH] app/services/browser_detail.py → expand_all_interactive_elements_impl (lines 127-130):
Bare exception handling: except Exception: await handle.evaluate(...). Swallowing click exceptions and blindly firing JS evaluates masks underlying Playwright state issues (like target closed).
[MEDIUM] app/services/pipeline/core.py → _mark_run_failed (lines 489-514):
Nested try/except SQLAlchemyError blocks attempting to recover a session, eventually falling back to a raw SessionLocal(). If the connection pool is exhausted, both will fail, and the run is left as a zombie in the RUNNING state.
Verdict: The resilience layer wastes time chaining timeouts linearly and masks critical browser failures with broad except Exception blocks. State machine corruption (zombie runs) is a risk under high DB load.
7. Dead Code & Technical Debt Hotspots
Score: 7/10
Violations:
[HIGH] app/services/robots_policy.py → _get_lock() (lines 27-33):
Needlessly complex double-checked locking singleton for _ROBOTS_CACHE_LOCK. FastAPI/AsyncIO applications should initialize locks synchronously at startup or module load, rather than using threaded _INIT_LOCK inside an async-driven module.
[MEDIUM] app/services/record_export_service.py (lines 485-489):
Exporting private functions explicitly for tests (_humanize_field_name = humanize_field_name). This prevents structural refactoring of the export service.
Verdict: Relatively clean of commented-out code and FIXMEs, but suffers from over-engineered concurrency primitives and test-induced public API pollution.
8. Acquisition Mode Audit & Site Coverage
Score: 5/10
Violations:
[CRITICAL] app/services/browser_capture.py → should_capture_network_payload (lines 169-195):
It explicitly filters out payloads unless content_type contains json or the URL ends in .json. This completely ignores text/x-component (React Server Components), application/trpc+json, and application/graphql-response+json. The pipeline is entirely blind to Next.js App Router payloads.
[HIGH] app/services/browser_identity.py → _generate_coherent_fingerprint (lines 89-106):
While it checks for major version coherence between User-Agent and userAgentData, it falls back to stripping client hints if generation fails after 3 tries. Stripping sec-ch-ua headers while sending a Chrome > 120 User-Agent is an immediate red flag to Cloudflare/PerimeterX, practically guaranteeing a block.
Verdict: Advanced concepts exist (network payload mapping, fingerprinting), but fatal execution flaws (ignoring RSC content types, creating incoherent browser fingerprints on fallback) cripple their effectiveness against modern targets.
FINAL SUMMARY
Overall Score: 4.5/10
Critical Path:
Schema Pollution: validate_and_clean passes unknown fields through to output, corrupting the strict data contract.
Next.js Blindness: Network capture explicitly ignores text/x-component, entirely missing modern React Server Component data payloads.
Event Loop Starvation: Massive BeautifulSoup DOM parsing runs synchronously on the async event loop, killing concurrency.
Timeout Doubling: HTTP retries chain curl_cffi and httpx timeouts linearly, destroying worker throughput on dead URLs.
Traversal Abstraction Leak: Site-specific strings ("workday") are hardcoded directly inside the generic traversal.py cycle detector.
Genuine Strengths:
LLM Circuit Breaker (app/services/llm_circuit_breaker.py): Highly robust Redis-backed Lua implementation for managing LLM provider degradation.
Selector Self-Heal (app/services/selector_self_heal.py): Excellent architecture for reducing HTML context and using LLMs to synthesize resilient XPath fallbacks dynamically.
Provenance Traceability (app/services/record_export_service.py): The CrawlRecordProvenanceResponse design cleanly maintains the lineage of where fields originated without polluting the core record data.
TOP 5 ARCHITECTURAL RECOMMENDATIONS
1. Fix Output Schema Validation (KISS / Contract Enforcement)
Files: app/services/field_value_core.py -> validate_and_clean.
Current: The function retains fields that aren't defined in _OUTPUT_SCHEMAS, allowing bad extractors to leak internal or rogue fields to the client.
Target:
code
Python
if field_name not in schema:
    continue # DROP IT. Do not copy to cleaned.
Simplification: Eliminates downstream needs to filter out rogue keys. Ensures 100% deterministic output schemas.
Outcome: Restores data integrity. Fixes the CRITICAL Dimension 4 violation.
2. Offload CPU-Bound DOM Parsing (Scalability)
Files: app/services/listing_extractor.py, app/services/structured_sources.py.
Current: BeautifulSoup(html, "html.parser") is called synchronously in async path.
Target: Move all BeautifulSoup and LexborHTMLParser instantiations and heavy extractions into a reusable await asyncio.to_thread(_parse_dom_logic, html) wrapper.
Simplification: Consolidates parser instantiation.
Outcome: Fixes event loop starvation, allowing FastAPI/Celery workers to actually hit their concurrency targets.
3. Unify HTTP Fetcher Strategy (Resilience)
Files: app/services/crawl_fetch_runtime.py -> _run_http_fetch_chain.
Current: A loop attempts curl_cffi, fails (timeout), then attempts httpx, fails (timeout), then retries.
Target: Select one HTTP fetcher per attempt based on policy (e.g., attempt 1: curl_cffi. If blocked/failed, attempt 2: Browser). Remove httpx entirely as a fallback if curl_cffi is present, or route strictly via platforms.json configs.
Simplification: Removes nested for fetcher in (_curl_fetch, _http_fetch): loops.
Outcome: Cuts dead-target timeout exposure in half, vastly improving worker throughput.
4. Extract Site-Specific Logic to Config (OCP / Config Hygiene)
Files: app/services/traversal.py, app/services/js_state_mapper.py.
Current: "workday" is hardcoded in traversal path logic. __NEXT_DATA__ and Nuxt logic are hardcoded in JS mappers.
Target: Move tenant-boundary path rules and state-revival flags into platforms.json under PlatformConfig. Pass them down via AcquisitionPlan or ExtractionContext.
Simplification: Cleans the generic engines of all site-specific branching.
Outcome: Adheres to OCP. Prevents the generic crawler from turning into a spaghetti bowl of if site == 'X' logic.
5. Decouple the Browser Page Flow God-Function (SRP)
Files: app/services/acquisition/browser_page_flow.py -> finalize_browser_fetch.
Current: 19 arguments. Handles artifact writing, block detection, diagnostics, and dictionary packing.
Target: Create a BrowserAcquisitionResultBuilder class. Execute classifications as separate, testable steps before passing the final data object to the persistence layer.
Simplification: Replaces a massive, untestable parameter list with an object-oriented builder pattern.
Outcome: Makes the browser acquisition layer unit-testable and readable.
EXTRACTION ENHANCEMENT RECOMMENDATIONS
1. Intercept React Server Components (RSC) and TRPC Payloads
Competitor Reference: Apify Next.js scraper templates; Crawlee network interception.
Gap Addressed: Network capture drops payloads without .json or application/json. Completely blind to modern Next.js App Router applications.
Slot: XHR/JSON source (should_capture_network_payload).
Implementation Sketch:
code
Python
# browser_capture.py
def should_capture_network_payload(...):
    # Add to allowed content types:
    valid_types = {"application/json", "text/x-component", "application/trpc+json"}
    if not any(t in content_type for t in valid_types) and not lowered_url.endswith(".json"):
        return False
    # For text/x-component, parse the line-delimited JSON stream
Yield Improvement: Unlocks native API-level extraction for Next.js App Router sites, bypassing DOM scraping entirely and reducing LLM fallbacks to near 0% on these modern platforms.
2. Visual Coordinate Bounding-Box Clustering
Competitor Reference: Diffbot Automatic APIs.
Gap Addressed: _listing_card_html_fragments relies entirely on DOM parent/child hierarchy. CSS Grid implementations often flatten the DOM (all items are siblings under <body>), breaking hierarchical card extraction.
Slot: DOM extraction step (listing_extractor.py).
Implementation Sketch:
code
Python
# via Playwright evaluate before closing page:
boundingBoxes = await page.evaluate("""() => {
    return Array.from(document.querySelectorAll('a, img, h2')).map(el => {
        const rect = el.getBoundingClientRect();
        return { tag: el.tagName, x: rect.x, y: rect.y, w: rect.width, h: rect.height, text: el.innerText };
    });
}""")
# Python side: Cluster elements that share similar Y-axis alignment thresholds.
Yield Improvement: Recovers listing cards on heavily CSS-Grid-flattened sites where DOM tree parsing fails, increasing listing coverage by ~15%.
3. Declarative Schema Normalization via JMESPath for JS State
Competitor Reference: Zyte AutoExtract architecture.
Gap Addressed: JS State extraction (js_state_mapper.py) uses hardcoded Python glom dictionaries (PRODUCT_FIELD_SPEC). This requires deploying code to support new platforms.
Slot: Hydrated state source (map_js_state_to_fields).
Implementation Sketch:
code
Python
# platforms.json
"js_state_mappings": {
  "ecommerce_detail": {
    "title": "props.pageProps.product.name | name | title",
    "price": "props.pageProps.product.offers.price"
  }
}
# js_state_mapper.py
def map_state_via_jmespath(payload, platform_config):
    return {
        field: jmespath.search(query, payload) 
        for field, query in platform_config.js_state_mappings.items()
    }
Yield Improvement: Unifies XHR and JS State mapping logic into a single declarative JSON config, allowing engineers to add new platform support via configuration rather than Python code changes.