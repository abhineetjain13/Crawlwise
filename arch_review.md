CrawlerAI — Comprehensive Logic & Architecture Audit
1. High-Level Architecture Map
Stack: FastAPI (Python async) + SQLAlchemy + Playwright + curl_cffi + BeautifulSoup + lxml, with a Next.js frontend.

Mental Model:

URL → ACQUIRE (curl_cffi → Playwright fallback) → BLOCKED DETECT → DISCOVER (adapters, JSON-LD, __NEXT_DATA__, network intercepts, microdata, tables) → EXTRACT (listing: structured→DOM cards | detail: 10-source priority chain) → UNIFY (normalize, dedupe, field-discovery) → PUBLISH (verdict, DB persist)
Key Characteristics:

Hybrid extraction strategy — deterministic parsers (CSS selectors, XPath, regex, JSON key aliasing) with optional LLM cleanup (fire-and-forget, no retry on 429)
No hardcoded magic values — all selectors, aliases, thresholds, and patterns live in data/knowledge_base/*.json loaded via pipeline_config.py
Surface-driven — ecommerce_listing, ecommerce_detail, job_listing, job_detail each have canonical schemas from canonical_schemas.json
Verdict system — success/partial/blocked/schema_miss/listing_detection_failed/empty based on core field presence only
2. The Extraction Pipeline (Step-by-Step)
URL → DOM → Cleaned Text → Structured Data
Stage 1: ACQUIRE (acquirer.py:acquire())

Waits for host pacing slot
If browser_first from site memory: tries Playwright first
Always tries curl_cffi first (unless browser_first): http_client.py:fetch_html_result()
Auto-detects JSON responses via Content-Type header or body sniffing
JSON responses bypass all HTML processing → go directly to _process_json_response()
Blocked detection (blocked_detector.py): active providers (high confidence) vs CDN providers (low confidence)
JS-shell detection: HTML ≥200KB with visible text ratio <2% → triggers Playwright
Playwright fallback (browser_client.py:fetch_rendered_html()):
Launches bundled chromium → falls back to system chrome
Navigates with domcontentloaded first, then optimistically tries load/networkidle
Waits for challenge resolution (DataDome, Cloudflare, etc.) — max CHALLENGE_WAIT_MAX_SECONDS (12s)
Dismisses cookie consent, expands accordions, flattens shadow DOM
Applies advanced_mode: paginate/scroll/load_more/auto
Intercepts all XHR/fetch JSON responses
Stage 2: DISCOVER (discover/service.py:discover_sources()) Produces DiscoveryManifest with ranked sources:

Rank 1: Adapter data (Amazon, Walmart, eBay, Indeed, LinkedIn, Greenhouse, Remotive, Shopify)
Rank 2: Network payloads (intercepted XHR JSON)
Rank 3: __NEXT_DATA__, hydrated states (__NUXT__, __APOLLO_STATE__, __myx, etc.), embedded JSON, Open Graph
Rank 4: JSON-LD
Rank 5: Microdata/RDFa
Rank 6: Hidden DOM
Rank 8: HTML tables
Stage 3: EXTRACT — Two paths:

For Listings (listing_extractor.py:extract_listing_records()):

Structured sources from manifest (JSON-LD ItemLists, __NEXT_DATA__, network payloads, hydrated states) — ranked by field richness
Next.js Flight script parsing (__next_f.push)
Inline object arrays in HTML
DOM card detection via CARD_SELECTORS_COMMERCE / CARD_SELECTORS_JOBS
Auto-detect repeating siblings via product signal density scoring
Fallback guard: 0 records → listing_detection_failed verdict (never falls back to single detail record)
For Detail Pages (extract/service.py:extract_candidates()): 10-source priority chain per field:

User extraction contract (XPath/regex)
Adapter data
Network payloads (filtered for noise URLs)
Hydrated app state / __NEXT_DATA__
JSON-LD (non-product blocks skipped for product fields)
Microdata
Saved domain selectors
Semantic sections (h2-h6, dl/dt/dd, tables)
DOM patterns (generic CSS selectors)
Label-value text patterns in description
For JSON APIs (json_extractor.py:extract_json_listing()):

_find_items_array() — recursive search using 37 COLLECTION_KEYS + GraphQL edges/node pattern
_normalize_item() — maps arbitrary JSON to canonical fields via FIELD_ALIASES (55 aliases)
Fallback: preserves scalar fields under original keys when no alias matches
3. Critical Friction Points & Bugs
Why the app failed to extract from simple JSON APIs:
Root cause: The JSON extraction path IS implemented but has a narrow entry gate.

In crawl_service.py:process_run() (line 677):

if acq.content_type == "json" and acq.json_data is not None:
    records, verdict, url_metrics = await _process_json_response(...)
The JSON path only triggers when curl_cffi returns Content-Type: application/json. If a site returns HTML with embedded JSON (e.g., __NEXT_DATA__, inline <script> blobs), it goes through the HTML path instead. This is actually correct behavior — the discovery layer handles those cases.

However, the _find_items_array() in json_extractor.py has a critical limitation:

It requires len(objects) >= 1 to return results (line 76)
But the listing extractor's structured source path requires len(structured_records) >= 2 (line 118 in listing_extractor.py)
Single-item JSON API responses on listing surfaces get silently dropped
Why the app got stuck for 3 minutes on a wait challenge:
Root cause: _wait_for_challenge_resolution() in browser_client.py:1165

The challenge wait loop:

max_wait_ms = CHALLENGE_WAIT_MAX_SECONDS * 1000  # 12,000ms = 12s
poll_interval_ms = CHALLENGE_POLL_INTERVAL_MS    # 2,000ms
This is 12 seconds max, NOT 3 minutes. However, the total browser wait time compounds from multiple sequential waits:

BROWSER_NAVIGATION_DOMCONTENTLOADED_TIMEOUT_MS: 15,000ms
BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS: 3,000ms (for load)
BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS: 3,000ms (for networkidle)
COOKIE_CONSENT_PREWAIT_MS: 400ms
CHALLENGE_WAIT_MAX_SECONDS * 1000: 12,000ms
SURFACE_READINESS_MAX_WAIT_MS: 12,000ms
LISTING_READINESS_MAX_WAIT_MS: 12,000ms
Total worst case: ~57 seconds per navigation attempt. With 2 browser launch profiles (bundled chromium + system chrome), this could reach ~2 minutes.

The real 3-minute hang on opencart.com is likely caused by _wait_for_challenge_resolution() returning should_wait=True due to weak signals (e.g., "oops!! something went wrong" matching BLOCK_BROWSER_CHALLENGE_WEAK_MARKERS) and then the surface readiness check never finding the expected selectors, causing the full 12s challenge wait + 12s surface readiness wait to elapse.

Why it fetches "extra rows" instead of real product data:
Root cause: The listing auto-detect card scorer in listing_extractor.py:_auto_detect_cards()

The auto-detect algorithm scores candidate sibling groups by element count and product signal density. On sites like practicesoftwaretesting.com (which is an SPA that renders products via JavaScript), the curl path returns an HTML shell with navigation elements. The auto-detect finds repeating <a> or <li> elements in the navigation menu and scores them as "cards" because:

They are repeating siblings (≥3 elements)
They contain text that matches some field aliases
The navigation links have URLs
The product signal density scoring (_auto_detect_cards) looks for:

Links with images
Price-like text
Product-related class names
But on a bare HTML shell from curl, navigation items can still score if they have enough text content. The guard _is_meaningful_listing_record() tries to filter these out by checking for LISTING_PRODUCT_SIGNAL_FIELDS, but if the nav items happen to contain words like "product" or "shop", they pass through.

For SPA sites specifically: curl returns the JS shell → _html_has_extractable_listings() checks for JSON-LD or __NEXT_DATA__ with product signals → if none found → Playwright is triggered → but if Playwright also fails or the site uses non-standard rendering, the curl HTML is used as fallback and produces garbage.

Pagination on SPA sites (0 correct URLs):
Root cause: _find_next_page_url() in browser_client.py:628

The pagination finder uses:

PAGINATION_NEXT_SELECTORS — CSS selectors like [rel="next"], [aria-label*="next" i]
DOM text matching — finds <a> elements with text "next", "next >", ">"
On SPA sites like practicesoftwaretesting.com:

Pagination is often handled via JavaScript state changes (pushState), not actual <a href> navigation
The "Next" button may be a <button> with an onclick handler, not an <a> tag
Or pagination may be infinite scroll only (no next button at all)
The _find_next_page_url() function only looks for href attributes on anchors. It will never find JS-driven pagination.

4. Proposed "Pruning" List
Files/Directories to DELETE:
Path	Reason
backend/app/services/page_intelligence/	Empty directory — no files, no imports
backend/tmp_schema.py	Temporary debugging file
backend/tmp_query.py	Temporary debugging file
backend/test_pruning.py	SPA pruner test script, not in test suite
backend/run_audit.py	Standalone audit script
backend/test_sites_audit.py	Standalone audit script
backend/run_regression.py	Standalone regression script
backend/run_coverage_test.py	Standalone coverage script
backend/backend/	Misplaced nested directory — contains only artifacts
backend/.cookie_test/	Development cookie artifacts
backend/backend_cookie_test/	Development cookie artifacts
backend/prune_test_out.txt	Test output file
backend/uvicorn.stderr.log	Log file
backend/uvicorn.stdout.log	Log file
audit_pipeline.md	Root-level historical doc (CLAUDE.md says root audit files are historical)
Test files to REVIEW (potentially redundant):
File	Assessment
tests/test_smoke.py	Keep — basic smoke test for the pipeline
tests/test_run_acquire_smoke.py	Keep — validates smoke runner
tests/test_config_paths.py	Keep — validates knowledge_base file paths
tests/test_crawl_schema.py (root)	Redundant — duplicates tests/services/test_crawl_schema.py
tests/test_security.py	Minimal value — 527 bytes, likely trivial assertions
tests/services/test_llm_service.py	Dead code — 128 bytes, likely empty or stub
tests/services/test_domain_utils.py	Minimal value — 259 bytes, single utility test
tests/services/extract/test_listing_extractor_urls.py	Low value — 3KB, URL resolution edge cases already covered in main listing extractor tests
Code sections to CLEAN UP:
browser_client.py:_wait_for_challenge_resolution() — The weak marker matching ("oops!! something went wrong", "error page") causes false positives on legitimate error pages. These should be removed from challenge detection.
acquirer.py:_is_invalid_surface_page() — The commerce surface check (_is_invalid_commerce_surface_page) only checks for redirect-to-root. It does not validate that the page actually contains commerce content.
listing_extractor.py:_extract_listing_records_single_page() — The structured source threshold of >= 2 records is inconsistent with the JSON extractor's >= 1 threshold, causing single-item API responses to be dropped on listing surfaces.
Summary of State
The codebase is well-architected with a clean separation of concerns. The knowledge-base-driven configuration is a strong pattern. The main issues are:

SPA handling gap: curl returns JS shells, Playwright escalation works but is slow, and pagination detection is anchor-only (misses JS-driven pagination)
Challenge detection false positives: Weak markers cause unnecessary waits on legitimate pages
Inconsistent thresholds: JSON extractor accepts 1 record, listing extractor requires 2
No dynamic schema architecture yet: Schemas are static JSON files; there's no runtime schema inference or adaptation