
Comprehensive Architecture & Code Quality Review
Date: October 26, 2023
Reviewer: AI Architecture Review
System: Backend Python/FastAPI Web Scraping Application
Executive Summary
Overall Health: 🟡 Needs Attention
Key Metrics:
Total Issues: 14
Critical (P0): 2
High (P1): 4
Medium (P2): 5
Low (P3): 3
Technical Debt Score: 6/10
Code Quality Score: 7/10
Architecture Score: 7.5/10
Top 3 Priorities:
Remediate SSRF Vulnerabilities: Lack of target URL validation allows malicious users to scan internal VPC networks or access metadata services (169.254.169.254).
Eliminate Blocking I/O in Async Event Loop: The Knowledge Base store.py executes synchronous file reads/writes, severely crippling FastAPI concurrency.
Refactor Brittle Absolute XPaths: The build_absolute_xpath generates brittle DOM paths (/html/body/div[1]...) that degrade selector memory and learning reliability over time.
System Profile
Role: Core product data extraction pipeline
Criticality: Revenue-impacting (primary data acquisition engine)
Stage: Growth/Maturing Prototype
Primary Language: Python
Framework: FastAPI, SQLAlchemy (Async), Playwright
Domain: Web scraping, LLM-assisted extraction, and adapter-based heuristic parsing
Risk Map
Domain	Risk	Critical Issues	High Issues
Domain Model	Low	0	0
Boundaries	Low	0	0
Data & Schema	Medium	0	1
Resilience	High	1	1
Security	High	1	0
Scalability	High	0	2
Code Quality	Medium	0	1
Technical Debt	Medium	0	0
Knowledge Base	High	1	1
Selectors	High	0	1
Detailed Findings
🔴 Critical Issues (P0)
[Severity: Critical] Server-Side Request Forgery (SSRF) Vulnerability
Scope: System
Domain: Security
File(s): app/services/acquisition/acquirer.py, app/api/crawls.py
Line(s): N/A (Missing logic)
Context
The API accepts arbitrary URLs via CrawlCreate and processes them directly via curl_cffi and playwright. There is no check to verify if the resolved IP address belongs to internal networks (e.g., 127.0.0.0/8, 10.0.0.0/8, 169.254.169.254).
Risk
Malicious actors can submit internal IPs or AWS/GCP metadata URLs to extract cloud credentials, scan internal ports, or compromise the host VPC.
Recommendation
Implement a pre-fetch DNS resolution check. Reject requests where the resolved IP is an internal, private, or loopback address. Alternatively, use an egress proxy (like Smokescreen) strictly configured to drop internal routing.
Trade-offs
Adds slight latency to the initial crawl setup due to DNS resolution. May restrict legitimate internal dev testing if not toggled by environment.
Rationale
SSRF in a web-scraping tool is a textbook attack vector and poses an immediate existential security threat to the cloud environment.
Estimated Effort
1 day
Priority
P0 (Critical - immediate)
[Severity: Critical] Blocking File I/O in Async Event Loop
Scope: Module
Domain: Scalability
File(s): app/services/knowledge_base/store.py
Line(s): _load_json, _write_json functions
Context
The application uses FastAPI (ASGI) and runs entirely on asyncio. However, the Knowledge Base service reads and writes to disk synchronously (path.read_text(), path.write_text()). These functions are called deep within async routes (e.g., build_review_payload -> get_canonical_fields -> load_canonical_schemas).
Risk
Synchronous disk I/O blocks the main async thread. Under high concurrency, fetching reviews or modifying mappings will freeze the entire application, causing timeout cascades and drastically limiting throughput.
Recommendation
Refactor store.py to use aiofiles for asynchronous reads/writes, or wrap the existing synchronous calls in asyncio.to_thread().
Trade-offs
Requires refactoring the calling functions to await the results, bubbling up the async signature.
Rationale
Blocking the event loop in Python defeats the purpose of using FastAPI/AsyncIO and strictly limits horizontal scalability.
Estimated Effort
2 days
Priority
P0 (Critical - immediate)
🟠 High Priority Issues (P1)
[Severity: High] Brittle Absolute XPath Generation
Scope: Module
Domain: Selectors
File(s): app/services/xpath_service.py
Line(s): ~85-103 (build_absolute_xpath)
Context
The build_absolute_xpath function walks up the DOM tree to generate paths like /html/body/div[1]/main/section/div[3]. These are saved as deterministic fallback selectors.
Risk
Absolute XPaths are notoriously brittle. A single layout change, ad insertion, or A/B test variation will break the selector, polluting the selector memory database with useless, failing rules.
Recommendation
Switch to generating semantic, relative XPaths based on attributes (e.g., //div[@id='main-content']//span[@class='price']) or closest semantic anchors. Use a library like parsel or custom heuristic algorithms to rank unique attributes.
Trade-offs
Slightly higher CPU cost to compute unique relative XPaths compared to pure DOM traversal.
Rationale
Resilient scraping requires robust selectors. Pushing absolute XPaths into the "knowledge base" degrades long-term extraction quality.
Estimated Effort
3 days
Priority
P1 (High - this sprint)
[Severity: High] Duplicated LLM HTTP Client Logic
Scope: Module
Domain: Code Quality / Maintenance
File(s): app/services/llm_runtime.py
Line(s): ~140-270 (_call_openai, _call_groq, _call_anthropic, _call_nvidia)
Context
There are four separate, nearly identical implementations of httpx.AsyncClient calls for different LLM providers. Error handling, parsing, and timeout logic are duplicated.
Risk
Modifying proxy rules, telemetry, retry semantics, or timeout configurations requires updating 4 separate methods. It violates DRY and increases the likelihood of disparate behavior across providers.
Recommendation
Abstract the HTTP call into a generic _execute_llm_request(url, headers, payload, provider) method. Provider specific functions should only build the headers and payload formatting, delegating the network request to the generic handler.
Trade-offs
Standardizing payload schemas across providers (Anthropic's structure differs slightly from OpenAI's) requires careful mapping.
Rationale
Centralizing network I/O simplifies resilience patterns (like circuit breakers or fallback retries).
Estimated Effort
1 day
Priority
P1 (High - this sprint)
[Severity: High] Unbounded Storage for Crawl Artifacts
Scope: System
Domain: Scalability
File(s): app/services/acquisition/acquirer.py
Line(s): ~80 (_write_network_payloads, path.write_text)
Context
HTML pages, JSON responses, and network payloads are written to disk for every request. There is no automated TTL, rotation, or pruning strategy outside of a global dashboard reset (dashboard_service.py).
Risk
In a production environment doing thousands of crawls, the disk will fill up rapidly, leading to out-of-space application crashes and database corruption (SQLite is on the same disk).
Recommendation
Implement a background worker (e.g., Celery/APScheduler) that prunes artifacts older than 7 days. Alternatively, store artifacts directly in an S3-compatible object store with lifecycle policies.
Trade-offs
Using S3 adds infrastructure dependency; a local background task adds application complexity.
Rationale
Unbounded local disk writes are a critical operational vulnerability.
Estimated Effort
2 days
Priority
P1 (High - this sprint)
[Severity: High] Deeply Nested Exception Handling & Double Rollbacks
Scope: Module
Domain: Resilience
File(s): app/services/crawl_service.py
Line(s): ~540-575 (_mark_run_failed)
Context
The failure handler uses a deeply nested try...except block with multiple session rollbacks and commits to handle double-fault scenarios.
Risk
This pattern is extremely hard to reason about, often swallows underlying TimeoutErrors, and can leave the SQLAlchemy session in a detached/broken state for subsequent requests if pooling is misconfigured.
Recommendation
Refactor using a clean context manager or rely on FastAPI's dependency injection to handle session teardown automatically. Update states via a new, isolated transaction rather than attempting to rescue a poisoned transaction.
Trade-offs
Requires separating transaction scopes clearly between job status updates and payload extraction.
Rationale
Database transaction boundaries must be explicitly clear and robust against arbitrary application failures.
Estimated Effort
2 days
Priority
P1 (High - this sprint)
🟡 Medium Priority Issues (P2)
Inconsistent Knowledge Base Loading: pipeline_config.py loads JSON on startup; store.py loads on-the-fly. Standardize this to load on startup with a hot-reload endpoint to prevent fragmented state.
Bare Exceptions in Browser Actions: browser_client.py uses except Exception: inside _dismiss_cookie_consent and _scroll_to_bottom. This masks TimeoutError and could obscure memory leaks. Change to specific PlaywrightError catches.
SQLite Concurrency Limits: database.url defaults to SQLite. For a highly concurrent scraping app writing records and logs rapidly, SQLite WAL mode will eventually suffer database locked errors. Plan migration path to PostgreSQL.
Missing Pagination Implementation: advanced_mode == "paginate" simply returns the first page and closes the browser (browser_client.py). This is a documented POC but represents significant technical debt for listing extraction.
🟢 Low Priority Issues (P3)
Unused Imports:
app/services/adapters/amazon.py: import json is unused.
app/services/adapters/indeed.py: import json is unused.
Magic Numbers: Extract confidence thresholds (0.78, 0.75, 0.95) scattered across adapters and crawl_service.py into pipeline_config.py.
Adapter Code Duplication: Adapters share highly repetitive _extract_listing boilerplate. Abstract iteration logic into BaseAdapter.
Code Quality Analysis
Magic Numbers & Hardcoded Values
Total Found: ~15
llm_runtime.py:157: max_output_tokens: 1200 (Should be config-driven)
llm_runtime.py:158: temperature: 0.1 (Should be config-driven)
crawl_service.py:734: confidence: 0.78 (Should be in pipeline_config.json)
crawl_service.py:777: confidence: 0.7
browser_client.py:91: timeout=30_000 and timeout=15_000
Site-Specific Hardcoding
Total Found: 4
remotive.py:32: if "remotive.com" in url ... elif "remoteok.com" in url (Breaks Open-Closed Principle for adapters. Consider splitting into two adapters).
shopify.py:64: Hardcoded .json?limit=250 string interpolation.
Unused Imports
Total Files Affected: 2
amazon.py: import json
indeed.py: import json
Impact: Minor namespace pollution. Easily cleaned with a tool like ruff or flake8.
Technical Debt Items
Total Known Limitations: 1
browser_client.py:108: advanced_mode == "paginate" is documented as a POC and does not actually paginate.
Complex Functions: 1
crawl_service.py:_extract_detail: High cyclomatic complexity integrating adapters, candidate generation, and LLM resolution.
Knowledge Base Review
Structure Assessment
The JSON-driven approach (data/knowledge_base) is excellent for non-developer tuning. However, dual-loading mechanisms (pipeline_config.py vs store.py) create a split brain. pipeline_config.py reads once at startup, while store.py reads continually.
Selector Management
The system combines robust fallback arrays (card_selectors.json, dom_patterns.json) with learned selectors via DB. The architecture is sound, but absolute XPaths generated by build_absolute_xpath inject brittle trash into the system.
Schema Management
Pydantic schemas and SQLAlchemy models are well aligned. canonical_schemas.json governs extraction dynamically, which is brilliant for extensibility.
Recommendations
Unify the knowledge base into an in-memory Singleton instantiated on startup, with a dedicated /api/system/reload endpoint to flush and reload JSON files. This fixes the blocking I/O (P0) and split-brain (P2) simultaneously.
Architectural Strengths
🏗 Architectural Strength: Multi-Tier Acquisition Waterfall
Location: app/services/acquisition/acquirer.py
Benefit: Highly efficient bandwidth and CPU usage. It defaults to the lightweight curl_cffi (impersonating browsers at the TLS layer) and only escalates to expensive headless Playwright instances if the payload is challenged or requires JS rendering.
🏗 Architectural Strength: Discovery Manifest Pattern
Location: app/services/discover/service.py
Benefit: Standardizes source extraction. By eagerly gathering JSON-LD, Microdata, __NEXT_DATA__, and XHR payloads into a unified DiscoveryManifest, downstream extractors can query structured data cleanly without re-parsing the DOM multiple times.
🏗 Architectural Strength: Configuration Security Guard
Location: app/core/config.py (_check_secret_defaults)
Benefit: Prevents accidental deployment of default JWT and Encryption keys to production environments by explicitly checking against known weak defaults and crashing fast.
Technical Trajectory
Assessment: ⬆️ Improving
Reasoning: The application demonstrates a clear trajectory toward scalable, heuristic-driven web extraction. The separation of Adapters, Manifest Discovery, and JSON extractors prevents massive spaghetti-code common in scraping systems. The issues identified are primarily maturation pains (SSRF guards, Async I/O hygiene) rather than fundamental design flaws.
Remediation Roadmap
Sprint 1 (Immediate - Week 1-2)

Implement URL target validation in create_crawl_run to prevent SSRF (P0).

Refactor store.py to cache JSON data in memory or use asynchronous file I/O (P0).

Fix deeply nested exception handling in _mark_run_failed (P1).
Estimated Effort: 4-5 days
Sprint 2 (Short-term - Week 3-4)

Refactor build_absolute_xpath to generate relative semantic paths (P1).

Implement a background task to prune old HTML/JSON artifacts (P1).

Consolidate LLM HTTP Client requests into a generic handler (P1).
Estimated Effort: 5-7 days
Sprint 3-4 (Medium-term - Month 2)

Extract all magic numbers to pipeline_config.json (P2).

Unify Knowledge Base loading mechanisms (P2).

Switch Playwright error handling to catch specific exception types (P2).
Estimated Effort: 4 days
Backlog (Long-term - Quarter)

Implement actual pagination logic for Playwright (P2).

Remove unused imports and lint codebase (P3).

Refactor adapter boilerplate logic to base class (P3).

Plan migration from SQLite to PostgreSQL for scale (P2).
Estimated Effort: 2 weeks
Metrics & Tracking
Suggested Metrics to Track
Selector Success Rate: Percentage of DB selectors successfully matching content (will highlight absolute XPath failure rates).
Extraction Fallback Rate: How often the system escalates from curl_cffi to playwright.
Event Loop Block Time: Use APM (like Datadog/Sentry) to monitor AsyncIO loop block durations to ensure disk I/O isn't dragging down routing.
Before/After Targets
Zero critical vulnerability scans (Resolve SSRF).
10x improvement in concurrent /api/crawls requests handled per second (after fixing synchronous I/O).
Final Recommendation
✅ Architecturally Sound - Minor improvements needed
Justification: The core architecture separating Acquisition -> Discovery -> Extraction -> Unification is highly resilient for web scraping. The system gracefully handles the chaos of the web via adapters, network interception, and fallback logic. By addressing the critical SSRF vector and the asynchronous I/O blocking issue, this application is ready to scale cleanly in a production environment.