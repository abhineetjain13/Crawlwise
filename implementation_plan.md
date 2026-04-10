EXECUTIVE SUMMARY
─────────────────────────────────────────────────────────────────
Health scores (0–10):
Architecture: 6/10 (Strong micro-patterns, but orchestration is monolithic and tightly coupled)
Correctness: 5/10 (Critical arbitration bugs cause schema pollution; virtualized DOMs cause data loss)
Reliability: 6/10 (SQLite queue contention will bottleneck; excellent async network retry loops)
Maintainability: 4/10 (Extreme config/regex sprawl; site-specific hacks mixed with core logic)
Security: 9/10 (Top-tier SSRF mitigations with low-level DNS pinning and redirect guards)
Test maturity: 7/10 (Good coverage of happy paths, but missing invariant tests for fallback hierarchies)
Top 5 existential risks:
The extraction arbitrator (_collect_candidates) uses early-exit continue statements, allowing low-quality dataLayer strings to permanently override high-fidelity JSON-LD data.
Advanced traversal (infinite scroll/load more) captures only the final DOM state, resulting in silent, unrecoverable data loss on virtualized/windowed frontends.
The background job queue uses SQLite row-level locks (queue_owner) which, despite aggressive with_retry backoffs, will inevitably encounter database is locked deadlocks under concurrent batch loads.
Site-specific routing logic (e.g., ADP, iCIMS, Oracle) is hardcoded into generic utility functions, guaranteeing regressions when new platforms share similar URL tokens.
In-flight Playwright browser contexts lack strict process-level garbage collection, creating a high risk of zombie Chromium processes if the Python worker OOMs or receives a SIGKILL.
Top 5 strengths:
Exceptional SSRF defense posture; pinning DNS resolution at the curl_cffi and playwright protocol layers prevents TOCTOU (Time-of-Check to Time-of-Use) attacks.
Comprehensive fallback chaining (Curl -> Browser) maximizes success rates without universally paying the performance penalty of headless browsers.
Robust DOM state snapshotting (_snapshot_listing_page_metrics) provides behavioral heuristics to detect loading shells and bypass anti-bot interstitials.
Clean separation of the LLM runtime from deterministic extraction, treating AI as a progressive enhancement rather than a critical dependency.
Well-structured data provenance tracking (source_trace, manifest_trace), making debugging extraction failures highly deterministic.
Assessment of production readiness:
The pipeline is secure and functionally rich, but it is not ready for unattended operation at scale. The extraction arbitration logic is fundamentally flawed, causing the system to prefer noisy marketing analytics data over structured schema definitions. Coupled with the SQLite-based queue and the data loss in the browser traversal module, running this across thousands of domains will result in corrupted output schemas and severe database contention. Fixing the extraction hierarchy (P0) and externalizing site configs (P1) are absolute prerequisites for scaling.
─────────────────────────────────────────────────────────────────
2) ARCHITECTURE FINDINGS
─────────────────────────────────────────────────────────────────
Finding 1: Extraction Arbitration Short-Circuiting
Severity: Critical
Confidence: High
Category: Correctness / Schema
Evidence: app/services/extract/service.py::_collect_candidates (Lines 152-166)
Problem: The _collect_candidates loop uses if _collect_datalayer_candidates(...): continue. This early-exits the collection pipeline. If a Google Analytics dataLayer contains a truncated string or numeric ID for a category/brand, the pipeline skips json_ld, microdata, and dom extraction entirely.
Production impact: Widespread schema pollution. Marketing analytics payloads (which prioritize speed and brevity) overwrite rich structured data.
Minimal fix: Remove continue statements in _collect_candidates. Collect all rows from all sources, then allow _finalize_candidates to sort by SOURCE_RANKING.
Ideal fix: Implement a true Strategy pattern where all Extractors run independently, returning a list of Candidate dataclasses that are evaluated by an isolated Arbitrator class using confidence scoring.
Effort: S
Regression risk: Medium (Will change output for many sites, generally for the better, but requires QA).
Finding 2: Virtualized DOM Data Loss in Traversal Mode
Severity: Critical
Confidence: High
Category: Traversal
Evidence: app/services/acquisition/browser_client.py::_apply_traversal_mode and app/services/acquisition/traversal.py::scroll_to_bottom
Problem: scroll_to_bottom executes a scroll loop but returns only a summary dict with html=None. The caller (browser_client.py) falls back to page.content(). Because modern SPAs use DOM virtualization, items scrolled out of the viewport are removed from the DOM.
Production impact: A page with 500 items that requires 10 scrolls will only output the last ~40 items visible in the viewport. The first 460 items are permanently lost.
Minimal fix: Inject a JS snippet prior to scrolling that overrides Element.prototype.remove for product cards, forcing the browser to keep them in the DOM.
Ideal fix: During the scroll loop, actively intercept and accumulate the underlying JSON XHR responses, or take HTML snapshots of the listing container at each interval and merge them via string concatenation.
Effort: M
Regression risk: Low (Currently broken anyway).
Finding 3: SQLite Queue Contention limits Scalability
Severity: High
Confidence: High
Category: Reliability / Architecture
Evidence: app/services/workers.py::claim_runs, app/services/db_utils.py::with_retry
Problem: The background queue is built on SQLite using UPDATE crawl_runs SET queue_owner.... While WAL mode is enabled, SQLite allows only one concurrent writer. The with_retry loop masks the database is locked errors, but under high concurrency (e.g. 8+ workers), threads will burn CPU spinning on locks and eventually fail.
Production impact: Max throughput ceiling is artificially low. Worker deadlocks.
Minimal fix: Decrease the polling frequency in CrawlWorkerLoop and increase the claim_batch_size to minimize write transactions.
Ideal fix: Decouple the job queue from SQLite. Use Redis, RabbitMQ, or PostgreSQL (with SKIP LOCKED) for orchestration, relegating SQLite strictly to single-tenant local testing.
Effort: L
Regression risk: Low.
Finding 4: Side-Effects in Pydantic Model Validators
Severity: Medium
Confidence: High
Category: Design / Maintainability
Evidence: app/schemas/crawl.py::CrawlRecordResponse._clean_for_display
Problem: A @model_validator is being used to aggressively filter and mutate dictionaries (self.data, self.discovered_data) to hide internal fields and shape the HTTP response. Pydantic models should validate shape, not execute heavy business/presentation logic.
Production impact: Serializing a CrawlRecordResponse internally (e.g., for a webhook or internal queue) destructively mutates the data.
Minimal fix: Move this dictionary reshaping logic into a dedicated presenter/serializer function in records.py or a service layer.
Ideal fix: Separate internal models from external DTOs using discrete Pydantic schemas (e.g., CrawlRecordInternal vs CrawlRecordPublic).
Effort: S
Regression risk: Low.
─────────────────────────────────────────────────────────────────
3) SITE-SPECIFIC HACKS REGISTER
─────────────────────────────────────────────────────────────────
| ID | Location (file:function) | Domain/Pattern Matched | Classification | Risk | Consolidation Action |
|---|---|---|---|---|---|
| H1 | extraction_rules.py:PLATFORM_FAMILIES | adp, icims, paycom, greenhouse | SMELL | Medium | Move acquisition matching and browser-first policy into an acquisition-only PlatformRegistry. |
| H2 | selectors.py:_build_listing_readiness_overrides | oraclecloud.com, adp.com, ultipro.com | SMELL | Medium | Remove domain matching from selectors.py; let selectors.py stay family-keyed and have PlatformRegistry supply only acquisition family detection. |
| H3 | acquirer.py:_is_invalid_job_surface_page / pipeline/core.py surface remap helpers | Titles: "GovernmentJobs", "City, State..." and other redirect-shell heuristics | DANGEROUS | High | Keep backend surface normalization URL/platform-driven (listing vs detail comes from the request, job vs commerce comes from backend detection), and downgrade redirect-shell title/canonical checks to diagnostics only rather than letting them own remap decisions. |
| H4 | pipeline_config.py:BROWSER_FIRST_DOMAINS | careers.clarkassociatesinc.biz (via tests/config) | SMELL | Low | Move browser-first acquisition flags into PlatformRegistry under acquisition-only fields such as requires_browser. |
| H5 | cookie_store.py:cookie_policy_for_domain | your-domain.com | JUSTIFIED | Low | Extract this entirely into an environment-loaded dictionary so open-source/core code doesn't reference specific clients. |
Consolidation Strategy:
Define Schema: Create a PlatformConfig model for acquisition-only policy and family detection. Keep fields limited to acquisition concerns such as family matchers, requires_browser, and optional proxy_policy. Do not put extraction selectors, noise filters, or schema/site-memory in the registry.
Extract: Remove raw domain strings from python dictionaries in extraction_rules.py and selectors.py. selectors.py may keep family-keyed readiness selectors/max-wait values, but family detection must come from the registry.
Load: Load platform family rules dynamically from a platforms.json file via app/services/config/platform_registry.py.
Adapter Pattern: For complex extraction special cases (for example USAJobs), keep explicit adapters outside the registry rather than expanding the registry into an extraction-rule store.
─────────────────────────────────────────────────────────────────
4) SCHEMA POLLUTION TRACE REPORT
─────────────────────────────────────────────────────────────────
Polluted Fields: brand, category, availability, price
Extraction Sources (Priority Order): Contract -> Adapter -> dataLayer -> Network -> JSON-LD -> Hydrated -> DOM -> Semantic -> Text.
Arbitration Logic: app/services/extract/service.py::_collect_candidates uses an if _collect_...: continue ladder.
The Bug (Condition): If a site pushes GTM dataLayer events, parse_datalayer yields values. _collect_candidates appends them and immediately continues to the next field, completely bypassing JSON-LD and Microdata.
Site-Specific or Universal? Universal logic bug affecting any site using Google Analytics ecommerce tracking.
Minimal fix: Delete all continue statements in _collect_candidates. Ensure all sources are appended to rows.
Ideal fix:
Fix the continue bug.
Implement strict sanitization in app/services/normalizers.py::validate_value. E.g., for brand, reject strings containing >, <, /, or strings longer than 40 chars. For category, reject "detail-page", "product", or strings matching ^e\d+$ (GA tracking codes).
Priority: P0 | Effort: S
─────────────────────────────────────────────────────────────────
5) BROWSER TRAVERSAL MODE — BUG TRACE & FIX PLAN
─────────────────────────────────────────────────────────────────
Preamble:
Traversal helpers are explicit opt-in behavior only. `paginate`, `scroll_to_bottom`, and `click_load_more` / `load_more` may execute only when the user has set `settings.advanced_mode` (or the normalized traversal mode derived from that field). Initial browser rendering for acquisition/readiness does not imply traversal permission and must remain independent from traversal execution.

Paginated (collect_paginated_html)
Status: Partial
Evidence: browser_client.py::_click_and_observe_next_page
Failure mode: Uses page.goto(url) based on href detection. If a site uses client-side routing (e.g., React/Vue) with onClick handlers and href="#", find_next_page_url_anchor_only fails or reloads the current page, breaking the loop.
Minimal fix: Rely on locator.click() exclusively if href is invalid or #.
Ideal fix: Combine XHR interception with locator.click().
Priority: P1 | Effort: M
Infinite Scroll (scroll_to_bottom)
Status: Broken (Data Loss)
Evidence: traversal.py::scroll_to_bottom, browser_client.py::_apply_traversal_mode
Failure mode: Scrolling triggers virtualized DOMs to delete off-screen nodes. The function returns a summary but no HTML fragments. The caller captures the DOM only once at the end.
Minimal fix: Inside the scroll loop in browser_client.py, capture page.content() at each iteration, find the listing container, and append its innerHTML to a running array.
Ideal fix: Override Element.prototype.remove for children of the listing grid so the DOM naturally accumulates items, OR rely entirely on XHR JSON interception for infinite scroll.
Test case: Target a known virtualized list (e.g., Wayfair or Reddit). Ensure record count > viewport capacity.
Priority: P0 | Effort: M
View All / Load More (click_load_more)
Status: Partial (Data Loss)
Evidence: traversal.py::click_load_more
Failure mode: Exact same data loss vector as Infinite Scroll if the "Load More" button replaces items rather than appending them (common in SPA pagination).
Priority: P0 | Effort: S (Fixed by the same mechanism as Infinite Scroll).
─────────────────────────────────────────────────────────────────
6) BUG & DEFECT CANDIDATE LIST
─────────────────────────────────────────────────────────────────
| ID | P | Sev | File:Function | Symptom | Trigger | Root Cause | Fix | Test to Add | Status |
|---|---|---|---|---|---|---|---|---|---|
| B1 | P0 | Crit | service.py:_collect_candidates | High-quality schema data ignored | Any site with GTM/GA4 | Early continue short-circuits source collection | Remove continue from collection blocks | Ensure JSON-LD overrides dataLayer if values conflict | LIKELY BUG |
| B2 | P0 | High | browser_client.py:_apply_traversal_mode | Data loss on scroll | Infinite scroll on virtualized DOM | DOM snapshot taken only at end of traversal | Capture HTML fragments inside scroll loop | Scroll 5 pages on virtualized DOM, assert count | LIKELY BUG |
| B3 | P1 | High | source_parsers.py:_extract_items_from_json | CPU spike / Worker crash | Deeply nested JSON payload | Recursive extraction without strict bounds | Enforce max_depth parameter strictly | Feed 100-deep nested JSON payload | LIKELY BUG |
| B4 | P1 | Med | workers.py:_run_forever | Stalled/Zombie workers | DB lock or unhandled exception | Loop lacks top-level catch-all try/except | Add top-level exception handler to keep loop alive | Inject SQLAlchemy error into claim_runs | ARCH SMELL |
| B5 | P2 | Med | schemas/crawl.py:CrawlRecordResponse | Data mutation | Accessing API endpoint | @model_validator mutates internal state | Move formatting to records.py presenter | Serialize object twice, assert equality | LIKELY BUG |
─────────────────────────────────────────────────────────────────
7) CODE REDUCTION & SIMPLIFICATION BACKLOG
─────────────────────────────────────────────────────────────────
TODO-SIMP-001: Consolidate Field Normalization and Validation
Priority: P1
Effort: M
Files affected: app/services/normalizers.py, app/services/extract/listing_normalize.py, app/services/extract/service.py
What to remove: Drop the duplicate _normalize_field_value logic in listing_normalize.py and fold it into normalizers.py.
What to keep: A single normalize_and_validate(field_name, value) function used globally by both detail and listing extractors.
Estimated LoC delta: -150 lines.
Bug surface reduction: High. Ensures listing pages and detail pages apply the exact same noise rejection logic to prices and titles.
TODO-SIMP-002: Merge _extract_listing and _extract_detail orchestration
Priority: P2
Effort: L
Files affected: app/services/pipeline/core.py
What to remove: The split orchestration blocks that duplicate logging, metric finalization, and DB saves.
What to keep: A single _extract_content function that delegates to the specific extractor, then runs a unified persistence and metrics block.
Estimated LoC delta: -200 lines.
Bug surface reduction: Medium. Fixes drift where metrics or trace tracking gets updated in _extract_detail but forgotten in _extract_listing.
─────────────────────────────────────────────────────────────────
8) AGENT-EXECUTABLE REMEDIATION BACKLOG
─────────────────────────────────────────────────────────────────
TODO-001: Remove short-circuit logic in candidate extraction
Priority: P0
Effort: S
Category: Correctness
File(s): app/services/extract/service.py
Problem: _collect_candidates uses continue statements after checking high-priority sources (like adapter or datalayer). This prevents the pipeline from collecting json_ld or microdata, resulting in garbage analytics data permanently winning over high-quality structured schema data.
Action:
Open app/services/extract/service.py.
Locate the _collect_candidates function.
Remove the continue statement inside if _collect_contract_candidates(...), if _collect_adapter_candidates(...), if _collect_datalayer_candidates(...), if _collect_network_payload_candidates(...), and if _collect_jsonld_candidates(...).
Ensure all discovered candidates are appended to rows.
Acceptance criteria: Running extraction on a page with both a noisy dataLayer and a valid JSON-LD object results in the JSON-LD value being chosen for the brand field in _finalize_candidates.
Depends on: none
TODO-002: Accumulate DOM snapshots during scroll traversal
Priority: P0
Effort: M
Category: Traversal
File(s): app/services/acquisition/traversal.py, app/services/acquisition/browser_client.py
Problem: Infinite scroll only captures the final DOM state. Virtualized grids remove off-screen elements, causing massive data loss on listing pages.
Action:
Open app/services/acquisition/traversal.py.
Modify scroll_to_bottom to accept a callback capture_dom_fragment.
Only perform scroll traversal or invoke capture_dom_fragment when traversal was explicitly enabled by `settings.advanced_mode` / the normalized traversal mode.
Inside the scroll_to_bottom loop, after the settle window completes, call await capture_dom_fragment(page).
Open browser_client.py and implement the callback to push await page.content() into a list of strings.
Merge the list of strings using \n<!-- PAGE BREAK... -->\n similar to how collect_paginated_html works.
Acceptance criteria: `advanced_mode=true` with `advanced_mode="scroll"` (or equivalent normalized traversal mode) accumulates all DOM fragments seen during traversal, while `advanced_mode=false` skips scroll traversal entirely and falls back to normal single-page acquisition.
Depends on: none
TODO-003: Strict Schema Validation Gate
Priority: P0
Effort: M
Category: Schema
File(s): app/services/normalizers.py
Problem: Data layers push garbage values (e.g., brand: "Home > Shoes", category: "detail-page"). The current validate_value function has very weak rules.
Action:
Open app/services/normalizers.py.
Enhance validate_value.
For brand: return None if length > 40, contains >, /, or matches cookie|privacy.
For category: return None if it exactly matches "detail-page", "product", or starts with e followed by digits (GA tracking codes).
For color: return None if it matches CSS definitions (e.g. contains {, rgb, padding).
Acceptance criteria: Passing "Home > Men > Shoes" to validate_value("brand", ...) returns None.
Depends on: TODO-001
TODO-004: Decouple Site Overrides into PlatformRegistry
Priority: P1
Effort: M
Category: HardcodedHack
File(s): app/services/config/extraction_rules.py, app/services/config/selectors.py, app/services/acquisition/acquirer.py
Problem: Codebase uses specific domain strings (e.g. "adp", "icims") scattered across multiple files.
Action:
Create app/services/config/platform_registry.py.
Define a registry for acquisition-only family detection and policy (for example family matchers, requires_browser, proxy_policy).
Migrate PLATFORM_FAMILIES and PLATFORM_LISTING_READINESS_URL_PATTERNS into this acquisition registry for family detection only.
Update _requires_browser_first and resolve_listing_readiness_override to query this single source of truth.
Acceptance criteria: No raw domain strings (like "adp.com") exist in extraction_rules.py or selectors.py; platform_registry.py is explicitly not used for extraction selectors, noise filters, or schema/site-memory logic.
Depends on: none
TODO-005: Remove Side-Effects from Pydantic Responses
Priority: P2
Effort: S
Category: Simplification
File(s): app/schemas/crawl.py, app/api/records.py
Problem: CrawlRecordResponse._clean_for_display mutates the dictionary inside a Pydantic @model_validator.
Action:
Open app/schemas/crawl.py. Remove the @model_validator(mode="after") from CrawlRecordResponse.
Create a function format_record_for_api(record: CrawlRecord) -> dict in app/api/records.py.
Apply the filtering logic (_extract_manifest_trace, hiding internal fields) inside this function before passing it to the Pydantic schema.
Acceptance criteria: Instantiating CrawlRecordResponse programmatically does not silently delete data.
Depends on: none
─────────────────────────────────────────────────────────────────
9) TECHNICAL DEBT REGISTER
─────────────────────────────────────────────────────────────────
| ID | Debt Item | Type | Daily Cost | Paydown Effort | Action | Priority |
|---|---|---|---|---|---|---|
| TD1 | SQLite Queue Contention | architecture | High (limits scale) | L | Migrate orchestration to Redis/Postgres | P1 |
| TD2 | Regex Sprawl in Config | complexity | Med (ReDoS risk) | M | Move complex extractions to Python Adapters | P2 |
| TD3 | Duplicated Normalization | duplication | Med (bugs) | S | Merge listing_normalize into normalizers | P1 |
| TD4 | _process_single_url size | complexity | Low | M | Refactor into ExtractionPipeline class | P2 |
| TD5 | Local FS Host/Cookie Cache | architecture | Med (Pod sync) | M | Move caches to Redis/DB tables | P1 |
─────────────────────────────────────────────────────────────────
10) RELIABILITY & INCIDENT READINESS
─────────────────────────────────────────────────────────────────
Hidden Failure Modes: If a worker process is OOM-killed, the SQLite lease (lease_expires_at) naturally expires, and recover_stale_leases picks it up. However, the Playwright Chromium process spawned by that worker is orphaned and stays alive indefinitely.
Observability Gaps: The background job loop catches generic exceptions and logs "Worker run execution failed", but does not output stack traces to a structured APM (like Sentry/Datadog). Rate-limit errors from the LLM (Groq/Anthropic) fail silently into the source trace rather than raising operational alerts.
Recommended Alerts:
crawl_queue_stale_leases_recovered > 5 per minute (Indicates worker crash looping).
crawl_proxy_exhausted_total > 0 (Proxy pool is burned).
db_lock_errors_total > 50 per minute (SQLite concurrency limit reached).
llm_cost_log anomaly (Tokens per run exceeding limits).
─────────────────────────────────────────────────────────────────
11) SECURITY AUDIT SNAPSHOT
─────────────────────────────────────────────────────────────────
Finding 1: Excellent SSRF Mitigations (Low Risk)
Scenario: Malicious user submits http://169.254.169.254.
Mitigation: validate_public_target blocks private/reserved IPs. Furthermore, low-level DNS pinning in curl_cffi (CurlOpt.RESOLVE) and Playwright (--host-resolver-rules) entirely mitigates DNS rebinding attacks.
Finding 2: Path Traversal in Cookie Store (Low Risk)
Scenario: User triggers crawl on http://../../../etc/passwd.
Mitigation: Safely handled. cookie_store_path uses string sanitization (safe = "".join(ch if ch.isalnum() else "_")), neutralizing traversal payloads.
Finding 3: ReDoS via Dynamic Field Config (Medium Risk)
Scenario: app/services/pipeline_config.py compiles regexes provided via settings. A crafted regex could lock the event loop.
Mitigation: Ensure extraction_contract regexes input by users execute with a strict timeout. xpath_service.py:extract_selector_value implements a timeout=0.05 on regex_lib.search, which successfully mitigates this.
─────────────────────────────────────────────────────────────────
12) PERFORMANCE & SCALABILITY AUDIT
─────────────────────────────────────────────────────────────────
Bottleneck 1: Synchronous BeautifulSoup parsing. BeautifulSoup(html, "html.parser") is heavily utilized. While html.parser is decent, lxml is significantly faster. Switching the BS4 parser to lxml globally will yield a 3-5x parsing speedup.
Bottleneck 2: SQLite Write Locks. Background workers aggressively poll and update crawl_runs. Migration to Postgres is mandatory for >10 concurrent workers.
Bottleneck 3: Excessive LLM Payload size. Prompt payloads include the full JSON representation of hydrated_states and next_data. Aggressively pruning empty nodes and null values before json.dumps will save tokens and latency on Groq/Anthropic endpoints.
─────────────────────────────────────────────────────────────────
13) TEST COVERAGE GAP ANALYSIS
─────────────────────────────────────────────────────────────────
Highest-risk untested paths:
Extraction Arbitration Hierarchy
Risk: High. The bug where dataLayer short-circuits JSON-LD was missed because tests mocked specific combinations but didn't assert that a valid JSON-LD payload overrides a garbage dataLayer payload.
Test: Integration. Provide HTML with both dataLayer (containing noise) and JSON-LD (containing truth). Assert JSON-LD wins.
Infinite Scroll Data Persistence
Risk: High. Prevents scaling on modern SPAs.
Test: E2E. Mock a virtualized DOM that removes items > 20. Scroll 3 times. Assert 60 items are captured, not 20.
Worker Shutdown Gracefulness
Risk: Medium. Zombie chromium processes.
Test: Unit. Ensure shutdown_browser_pool() successfully kills browser PIDs even if context creation was interrupted.
─────────────────────────────────────────────────────────────────
14) "IF I OWNED THIS CODEBASE" — TOP 12 ACTIONS
─────────────────────────────────────────────────────────────────
Fix the arbitration continue bug (TODO-001). It is silently destroying data quality for any site using GTM. (Takes 10 minutes).
Implement DOM fragment aggregation for Infinite Scroll (TODO-002). Allows the crawler to actually work on modern ecommerce sites. (Takes 3 hours).
Fortify validate_value normalizers (TODO-003). Stops the pipeline from picking up garbage "Cookie Policy" strings as Brands. (Takes 1 hour).
Switch BeautifulSoup to use lxml instead of html.parser. Instant 3x CPU efficiency gain for parsing 5MB React payloads. (Takes 10 minutes).
Migrate the queue from SQLite to PostgreSQL. Mandatory for horizontal scaling of the worker pods. (Takes 1 day).
Decouple PLATFORM_FAMILIES into a JSON registry (TODO-004). Cleans up the code and makes adding new sites a config change, not a code deploy. (Takes 2 hours).
Consolidate normalize_value logic (TODO-SIMP-001). Removes duplicated logic between listing and detail pipelines. (Takes 1 hour).
Remove Pydantic @model_validator side-effects (TODO-005). Prevents weird serialization bugs downstream. (Takes 30 minutes).
Implement global Exception handler in CrawlWorkerLoop. Prevents worker threads from dying silently. (Takes 15 minutes).
Move cookie_store and host_preferences to the Database. Local filesystem state breaks in Kubernetes deployments. (Takes 2 hours).
Refactor _process_single_url into a Class. It has too many arguments and too much local state. (Takes 4 hours).
I would NOT touch the SSRF network layer or url_safety.py. The current implementation with explicit DNS pinning is excellent and highly secure; altering it risks introducing severe vulnerabilities.
