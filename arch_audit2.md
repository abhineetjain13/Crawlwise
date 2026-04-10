
This is a deep-dive architectural and code audit of the web data extraction pipeline. The review focuses on architectural boundaries, systemic vulnerabilities, schema arbitration hazards, and traversal edge cases based on the provided codebase.
─────────────────────────────────────────────────────────────────
EXECUTIVE SUMMARY
─────────────────────────────────────────────────────────────────
Health scores (0–10):
Architecture: 7
Correctness: 6
Reliability: 8
Maintainability: 6
Security: 5
Test maturity: 8
Top 5 existential risks:
Disabled DNS pinning in Playwright enables a critical Time-Of-Check to Time-Of-Use (TOCTOU) Server-Side Request Forgery (SSRF) vulnerability.
The extraction arbitration logic strictly prioritizes dataLayer over JSON-LD, causing low-fidelity marketing strings to chronically pollute strict schemas.
Advanced traversal mode captures full-page HTML snapshots per scroll/click, guaranteeing _MAX_TRAVERSAL_TOTAL_BYTES (6MB) OOM/truncation failures on virtualized Single Page Applications.
SQLite write concurrency is artificially throttled by a global asyncio.Lock(), which will cause catastrophic event-loop blocking under high worker concurrency.
Manual, regex-based parsing of JavaScript ASTs to extract dataLayer and hydrated_states is fragile and vulnerable to injection/malformed string crashes.
Top 5 strengths:
Excellent separation of acquisition and extraction stages, enabling decoupled retries and fallback chains.
The SignalInventory and PageClassification modules provide a highly resilient, heuristic-driven approach to surface detection.
Database retry logic (with_retry) correctly wraps entire Units of Work to prevent SQLAlchemy session state corruption on rollback.
Comprehensive test coverage for edge cases, specifically around extraction normalization and URL safety.
Robust fallback mechanisms for blocked pages, including public API recovery via specific adapters (try_blocked_adapter_recovery).
Assessment of Production Readiness:
The pipeline is robust in its core data modeling and fallback mechanics, but it is not safely scalable in its current form. The intentional disabling of DNS pinning opens the infrastructure to severe SSRF attacks, and the memory-heavy approach to DOM traversal will buckle under modern virtualized e-commerce sites. Schema pollution is hardcoded into the pipeline's priority configuration (SOURCE_RANKING). Fixing these arbitration and security gaps will immediately elevate this to a highly resilient, enterprise-grade extraction system.
─────────────────────────────────────────────────────────────────
2026-04-10 RECONCILIATION STATUS
─────────────────────────────────────────────────────────────────
This document is now historical. The authoritative live backlog is [docs/backend-audit-remediation-tracker.md](docs/backend-audit-remediation-tracker.md).

| Legacy ID | Disposition |
|---|---|
| TODO-SIMP-001 | open -> `AUD-017` and `AUD-027` |
| TODO-SIMP-002 | void 2026-04-10: the generic URL-based surface override path was superseded by the SignalInventory / platform-registry refactor and no standalone remediation item remains. |
| TODO-001 | void 2026-04-10: the original DNS-pinning recommendation is superseded on this branch by initial-target validation, routed per-request public-target blocking, and service-worker blocking in the browser path. |
| TODO-002 | closed 2026-04-10 via `AUD-001` |
| TODO-003 | void 2026-04-10: traversal capture now prefers card outerHTML and DOM-diff fragments with bounded fallback, so the original full-page-only OOM path no longer matches current code. |
| TODO-004 | void 2026-04-10: current `PAGE_URL_CURRENCY_HINTS` already compile strict boundary regexes via `_build_page_url_currency_hint_pattern()`. |
| TODO-005 | void 2026-04-10: `source_parsers._extract_balanced_json_fragment()` now uses `json.JSONDecoder().raw_decode()` before the fallback scanner, which covers the cited string-brace failure mode. |
─────────────────────────────────────────────────────────────────
2) ARCHITECTURE FINDINGS (Ranked by Severity)
─────────────────────────────────────────────────────────────────
1. Playwright TOCTOU SSRF Vulnerability
Severity: Critical
Confidence: High
Category: Security
Evidence: app.services.acquisition.browser_client._build_launch_kwargs
Problem: The Python layer validates URLs against private IP space (validate_public_target), but DNS pinning in Playwright is explicitly commented out (# Disabled DNS pinning as it causes HTTP2 errors). An attacker can return a safe IP to the Python check, then return a local AWS/AWS internal IP (169.254.169.254) to Playwright.
Production impact: Total infrastructure compromise via internal metadata endpoint exfiltration.
Minimal fix: Re-enable DNS pinning --host-resolver-rules for standard requests, or strictly route all Playwright traffic through an isolated egress proxy that drops RFC1918 traffic.
Ideal fix: Deploy a dedicated egress proxy (e.g., Squid/Envoy) configured to block all internal IP ranges at the network level, removing the burden from the application layer entirely.
Effort: M
Regression risk if unchanged: Critical
2. DataLayer Schema Pollution via Incorrect Arbitration Priority
Severity: High
Confidence: High
Category: Schema
Evidence: app.services.pipeline_config.SOURCE_RANKING, app.services.extract.service.candidate_source_rank
Problem: SOURCE_RANKING hardcodes datalayer: 10 and json_ld: 9. Analytics payloads (GA4/UA) optimize for short, generic strings (e.g., category: "Shoes"). JSON-LD contains exact taxonomy (e.g., category: "Apparel > Men's > Shoes"). By ranking datalayer higher, rich semantic data is routinely destroyed by marketing metadata.
Production impact: Degradation of detail data quality; output schema is polluted by generic tracking tokens.
Minimal fix: Demote datalayer to 8 (below json_ld), or apply field-specific overrides in _DETAIL_FIELD_SOURCE_RANK_OVERRIDES to ensure category and brand prefer json_ld.
Ideal fix: Implement a merge strategy where tracking data can only fill missing fields, but never overwrite fields present in json_ld or microdata.
Effort: S
Regression risk if unchanged: High
3. Advanced Traversal OOM & Data Truncation on Virtualized DOMs
Severity: High
Confidence: High
Category: Traversal
Evidence: app.services.acquisition.traversal._capture_fragment
Problem: During scroll and load_more, _capture_fragment appends the entire HTML string to a list. If a SPA uses a virtualized list (unmounting off-screen nodes), the script captures the same header/footer 10 times. _MAX_TRAVERSAL_TOTAL_BYTES (6MB) is hit almost immediately, truncating the crawl.
Production impact: Missing products on infinite-scroll pages; severe memory pressure on the worker.
Minimal fix: In _capture_fragment, diff the DOM or only extract the specific outerHTML of the elements matching the card selectors, rather than page.content().
Ideal fix: Inject a JavaScript MutationObserver to capture new nodes as they are added to the DOM, sending them back to Python via page.expose_function().
Effort: L
Regression risk if unchanged: High
4. Global SQLite Write Lock Throttles Asynchronous Concurrency
Severity: Medium
Confidence: High
Category: Performance
Evidence: app.services.db_utils.sqlite_write_lock
Problem: A single global asyncio.Lock() is used for all SQLite writes across the application to prevent OperationalError. If a worker scales to URL_BATCH_CONCURRENCY = 8, all 8 concurrent pipeline executions serialize at the database layer.
Production impact: Event-loop starvation and severe throughput bottlenecking when using SQLite.
Minimal fix: Ensure SQLite is strictly isolated to local testing. Prevent production deployments from using SQLite via startup assertions.
Ideal fix: Use WAL mode and asyncio.to_thread for SQLite writes, or force the use of PostgreSQL/PostGIS for batch operations.
Effort: M
Regression risk if unchanged: Medium
─────────────────────────────────────────────────────────────────
3) SITE-SPECIFIC HACKS REGISTER
─────────────────────────────────────────────────────────────────
| ID | Location (file:function) | Domain/Pattern Matched | Classification | Risk | Consolidation Action |
|---|---|---|---|---|---|
| 1 | source_parsers.py:_NETWORK_PAYLOAD_NOISE_URL_PATTERNS | klarna.com, affirm.com, zendesk.com | SMELL | Low | Move to pipeline_config.py under an explicit NETWORK_INTERCEPT_BLOCKLIST. |
| 2 | listing_extractor.py:_is_social_listing_url | facebook.com, instagram.com, tiktok.com | SMELL | Low | Move to pipeline_config.py as SOCIAL_HOST_SUFFIXES. |
| 3 | page_classifier.py:_ERROR_TEXT_PATTERNS | Hardcoded 404/500 text | JUSTIFIED | Low | Leave as-is, but consider merging into generic BLOCK_SIGNATURES. |
| 4 | pipeline_config.py:PAGE_URL_CURRENCY_HINTS | /us/, /gb/, /ja-jp/ | DANGEROUS | Medium | A URL like /user-guide/ matches /us/ and incorrectly forces USD. Make regexes strict boundary matches (e.g., (?:^|/)us(?:/|$)). |
| 5 | adapters/ (All) | Various | JUSTIFIED | Low | Excellent use of the Strategy pattern. No change needed. |
Consolidation Strategy:
Migrate PAGE_URL_CURRENCY_HINTS to strict regex boundaries to prevent aggressive false positives.
Abstract _NETWORK_PAYLOAD_NOISE_URL_PATTERNS and _LISTING_SOCIAL_HOST_SUFFIXES into the unified pipeline_config.py to maintain a single source of truth for host filtering.
─────────────────────────────────────────────────────────────────
4) SCHEMA POLLUTION TRACE REPORT
─────────────────────────────────────────────────────────────────
Polluted Fields: category, brand, availability
Extraction Sources: contract > adapter > datalayer > json_ld > network > dom.
Arbitration Logic: extract/service.py:_finalize_candidates iterates over candidates and selects the one with the highest candidate_source_rank.
The Bug: parse_datalayer blindly extracts GA4 item_category and UA detail.products[0].category. Because datalayer is ranked 10, it beats json_ld (9). DataLayers are heavily constrained by GA character limits and often contain polluted strings like "Detail Page" or "Apparel".
Validation Gate: sanitize_field_value strips some noise (e.g., "cookie", "privacy"), but misses generic tracking values.
Scope: Universal across all sites using GA4/UA.
Minimal Fix: Update pipeline_config.py -> _DETAIL_FIELD_SOURCE_RANK_OVERRIDES to set datalayer to 8 for category and brand.
Ideal Fix: Create a rigid per-field type validator in normalizers.py that calculates a "Semantic Quality Score" (e.g., depth of breadcrumb > separated string) and factors that into the arbitration alongside source rank.
Priority: P0 | Effort: S
─────────────────────────────────────────────────────────────────
5) BROWSER TRAVERSAL MODE — BUG TRACE & FIX PLAN
─────────────────────────────────────────────────────────────────
Paginated: Partial
Evidence: browser_client.py:_collect_paginated_html
Bug: Works well, but fails to handle sites where pagination triggers a soft-navigation (SPA) that doesn't change the URL or push state, because the deduplication logic heavily relies on URL changes (visited_urls.add(next_page_url)).
Infinite Scroll: Broken
Evidence: browser_client.py:_scroll_to_bottom -> traversal.py:_capture_fragment
Bug: OOM / Truncation. _capture_fragment reads page.content() entirely for each scroll step. If a page has 500kb of HTML, 10 scrolls = 5MB. Limits hit instantly. Furthermore, if a site uses virtualization, older items are removed from the DOM, but they are preserved in collected_fragments, resulting in massive data duplication when the fragments are parsed in _split_paginated_html_fragments.
Minimal Fix: In _capture_fragment, instead of page.content(), execute JS to return only the outerHTML of newly discovered cards based on CARD_SELECTORS.
Ideal Fix: Use Playwright page.route or page.on("response") to intercept the backend JSON APIs triggering the scroll, completely bypassing the need to parse rendered DOM HTML.
Priority: P1 | Effort: L
View All / Load More: Broken
Evidence: browser_client.py:_click_load_more
Bug: Suffers the exact same OOM string concatenation issue as Infinite Scroll.
─────────────────────────────────────────────────────────────────
6) BUG & DEFECT CANDIDATE LIST
─────────────────────────────────────────────────────────────────
| ID | P | Sev | File:Function | Symptom | Trigger | Root Cause | Fix | Test to Add | Status |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P0 | Crit | browser_client.py:_build_launch_kwargs | SSRF vulnerability | Target returns RFC1918 IP | DNS pinning disabled in Playwright | Re-enable --host-resolver-rules or use proxy | Test SSRF block | LIKELY BUG |
| 2 | P1 | High | pipeline_config.py:SOURCE_RANKING | Category/brand polluted | Target uses Google Analytics | Datalayer ranks higher than JSON-LD | Demote datalayer rank for ID fields | Test JSON-LD beats GA4 | LIKELY BUG |
| 3 | P1 | High | traversal.py:_capture_fragment | Traversal terminates early | Infinite scroll on large page | captured_fragment_bytes exceeds 6MB | Extract node HTML, not page HTML | Test large SPA scroll | LIKELY BUG |
| 4 | P1 | Med | source_parsers.py:_extract_balanced_json_fragment | Datalayer parse failure | String contains { or } | Custom JSON parser fails on strings | Use strict AST parsing or re.search fallback | Test JSON with embedded braces | LIKELY BUG |
| 5 | P2 | Med | listing_extractor.py:_is_merchandising_record | Valid products dropped | Title contains "sale" | Aggressive editorial regex | Refine regex bounds | Test valid "sale" items | LIKELY BUG |
| 6 | P2 | Low | browser_client.py:_goto_with_fallback | Intermittent timeout crash | Page load takes >30s | Swallows PlaywrightError, misses Timeout | Catch and handle TimeoutError | Test 31s page load | ARCH SMELL |
─────────────────────────────────────────────────────────────────
7) CODE REDUCTION & SIMPLIFICATION BACKLOG
─────────────────────────────────────────────────────────────────
TODO-SIMP-001: Consolidate coerce_field_candidate_value and normalize_value
Priority: P1
Effort: M
Files affected: extract/service.py, normalizers.py
What to merge: Currently, values go through coerce_field_candidate_value to strip HTML/JSON, then later pass through normalize_value and validate_value. This splits field parsing logic across two files.
What to keep: Move all type-specific coercion (e.g., _coerce_color_field) into normalizers.py as pre-processors.
Estimated LoC delta: -150 lines
Bug surface reduction: High — prevents cases where a value passes coercion but fails validation later, resulting in an empty field.
TODO-SIMP-002: Remove generic URL-based Surface Overrides
Priority: P2
Effort: S
Files affected: pipeline/core.py, page_classifier.py
What to remove: _reclassify_surface_if_job duplicates the logic of classify_page_type.
What to keep: Rely entirely on the output of SignalInventory and classify_page_type.
Estimated LoC delta: -40 lines
Bug surface reduction: Medium — reduces conflicting assumptions about whether a page is a listing or detail.
─────────────────────────────────────────────────────────────────
8) AGENT-EXECUTABLE REMEDIATION BACKLOG
─────────────────────────────────────────────────────────────────
TODO-001: Re-enable Playwright DNS Pinning to Prevent SSRF
Priority: P0
Effort: S
Category: Security
File(s): app/services/acquisition/browser_client.py
Problem: Playwright performs its own DNS resolution, ignoring the Python-level validate_public_target check. This exposes internal networks (e.g., AWS IMDS 169.254.169.254) to SSRF.
Action:
Locate _build_launch_kwargs.
Uncomment the DNS pinning logic: launch_kwargs["args"] = [f"--host-resolver-rules=MAP {target.hostname} {_chromium_host_rule_ip(pinned_ip)}"].
Validate that TLS/HTTP2 requests still function, or add logic to disable HTTP2 if the pin causes a certificate mismatch.
Acceptance criteria: E2E tests confirm that requests to a hostname resolving to 127.0.0.1 fail at the browser level.
Depends on: none
TODO-002: Demote DataLayer Priority for Semantic Fields
Priority: P1
Effort: S
Category: Schema
File(s): app/services/pipeline_config.py, app/services/extract/service.py
Problem: DataLayer events push truncated or generic text (e.g. category="Apparel") which overwrite highly accurate JSON-LD data because datalayer ranks 10 vs json_ld 9.
Action:
In app/services/extract/service.py, locate candidate_source_rank.
Ensure _DETAIL_FIELD_SOURCE_RANK_OVERRIDES applies a rank of 8 to datalayer for brand and category fields.
Acceptance criteria: Unit tests in test_arbitration.py pass, confirming JSON-LD beats DataLayer for category.
Depends on: none
TODO-003: Fix OOM Data Duplication in Advanced Traversal
Priority: P1
Effort: L
Category: Traversal
File(s): app/services/acquisition/traversal.py
Problem: _capture_fragment appends page.content() entirely. Virtualized DOMs cause 6MB limits to be breached instantly.
Action:
Modify _capture_fragment to inject JS via page.evaluate().
The JS should query CARD_SELECTORS, map them to el.outerHTML, and return the combined string of only the cards.
Append this slimmed-down HTML to collected_fragments.
Acceptance criteria: A page with 500kb of surrounding nav/footer HTML can be scrolled 20 times without exceeding 1MB of captured fragment bytes.
Depends on: none
TODO-004: Strict Boundaries for Currency URL Hints
Priority: P1
Effort: S
Category: HardcodedHack
File(s): app/services/pipeline_config.py, app/services/normalizers.py
Problem: PAGE_URL_CURRENCY_HINTS uses loose matching (e.g., "/us/": "USD"). URLs like /contact-us/ will falsely trigger USD.
Action:
Convert the keys in PAGE_URL_CURRENCY_HINTS to strictly bounded regexes (e.g., r"(?:^|/)us(?:/|$)").
Update extract_currency_hint to use re.search against these compiled patterns instead of basic in operators.
Acceptance criteria: /contact-us/ no longer resolves to USD currency.
Depends on: none
TODO-005: Make Custom JSON Parser Resilient to String Braces
Priority: P2
Effort: M
Category: Correctness
File(s): app/services/extract/source_parsers.py
Problem: _extract_balanced_json_fragment tracks depth by counting { and }. It tracks strings, but if string escaping logic is flawed, it truncates payloads early.
Action:
Replace the manual string parser with the regex module's recursive matching feature: (?<rec>\{(?:[^{}]+|(?&rec))*\}).
Alternatively, utilize Python's built-in json.JSONDecoder().raw_decode().
Acceptance criteria: A dataLayer push containing {"text": "this is a { test } string"} parses successfully.
Depends on: none
─────────────────────────────────────────────────────────────────
9) TECHNICAL DEBT REGISTER
─────────────────────────────────────────────────────────────────
| ID | Debt Item | Type | Daily Cost | Paydown Effort | Action | Priority |
|---|---|---|---|---|---|---|
| 1 | SQLite global write lock | complexity | Limits concurrent throughput per node | High | Migrate to async Postgres for scale | P1 |
| 2 | pipeline/core.py monolith | complexity | Merge conflicts, hard to trace | Medium | Continue breaking into submodules | P2 |
| 3 | Redundant text cleaning | duplication | CPU cycles | Low | Consolidate into utils.py:_clean_page_text | P2 |
| 4 | Regex HTML parsing in detect_blocked_page | hardcoded-hack | False positives/negatives | Medium | Use LXML XPath for fast, safe DOM checks | P2 |
─────────────────────────────────────────────────────────────────
10) RELIABILITY & INCIDENT READINESS
─────────────────────────────────────────────────────────────────
Hidden Failure Modes:
_goto_with_fallback catches PlaywrightError but does not explicitly raise if a hard timeout is reached, potentially leaving the page in an undefined state before extraction begins.
JSON decoding errors in parse_page_sources silently fail, resulting in empty data structures. This masks structural changes to target websites.
Observability Gaps: When an extraction yields 0 records and is marked VERDICT_LISTING_FAILED, there is no telemetry indicating which stage (Acquisition, DOM Extraction, Serialization) was the root cause.
Session Leaks: browser.new_context() is wrapped in an asyncio.wait_for, but if the context creation times out, the underlying Chromium process might remain orphaned.
Top Alert to Implement: Alert on Spike in VERDICT_LISTING_FAILED grouped by domain. This indicates an upstream site has altered its DOM or implemented new anti-bot measures.
─────────────────────────────────────────────────────────────────
11) SECURITY AUDIT SNAPSHOT
─────────────────────────────────────────────────────────────────
Critical (SSRF via DNS TOCTOU): Python verifies the IP, but Playwright resolves it again. Exploit: DNS rebinding to scan internal AWS services. Mitigation: Re-enable Playwright DNS pinning --host-resolver-rules.
Medium (ReDoS): Complex regexes in _PRICE_WITH_CURRENCY_RE and _EXPAND_SALARY_RANGE_REGEX could cause event-loop blocking on maliciously crafted HTML payloads. Mitigation: Apply hard length limits (e.g., 500 chars) to strings before running regex extractions.
Low (PII Leakage): scrub_network_payloads_for_storage strips keys containing authorization or token, but misses Set-Cookie or generic session_id. Mitigation: Add cookie and session identifiers to the scrub list.
─────────────────────────────────────────────────────────────────
12) PERFORMANCE & SCALABILITY AUDIT
─────────────────────────────────────────────────────────────────
Bottleneck: BeautifulSoup parsing is performed multiple times (in classify_page, parse_page_sources, and extract_listing_records).
Optimization: Parse the BeautifulSoup object exactly once in process_single_url and pass the parsed object down the chain.
Browser Inefficiency: _maybe_warm_origin opens a completely separate navigation to the origin to simulate human traffic. This adds ~2-3 seconds per run. It should only be triggered if a previous run on the domain failed with VERDICT_BLOCKED.
Data Structure Overhead: _flatten_json_ld_payloads uses heavy recursion. Refactoring to an iterative approach will save stack frames and minor overhead on deeply nested Schema.org graphs.
─────────────────────────────────────────────────────────────────
13) TEST COVERAGE GAP ANALYSIS
─────────────────────────────────────────────────────────────────
Path: app.services.acquisition.traversal._capture_fragment under infinite scroll.
Risk: Memory limit truncation (6MB max) failing silently on virtualized SPAs.
Test Type: Integration.
Case: Create a mock server that returns 1MB of HTML per page. Scroll 10 times. Assert that extraction continues and returns records, rather than aborting.
Priority: P1
Path: Playwright SSRF / DNS Pinning.
Risk: Access to internal networks.
Test Type: Integration.
Case: Attempt to crawl a URL that initially resolves to 93.184.216.34 but redirects to 169.254.169.254. Assert that the browser acquisition layer throws an error.
Priority: P0
─────────────────────────────────────────────────────────────────
14) "IF I OWNED THIS CODEBASE" — TOP 12 ACTIONS
─────────────────────────────────────────────────────────────────
Fix Playwright DNS Pinning (SSRF) immediately. It's a critical infrastructure risk.
Refactor _capture_fragment to extract card outerHTML instead of full page content to unblock advanced traversal on modern SPAs.
Demote DataLayer in Arbitration to stop generic analytics payloads from destroying rich JSON-LD data.
Remove SQLite Locks and migrate the primary datastore to PostgreSQL to allow true horizontal scaling of the URL_BATCH_CONCURRENCY.
Pass a single BeautifulSoup instance down the pipeline to cut CPU overhead by ~30% per URL.
Strict boundaries for PAGE_URL_CURRENCY_HINTS to prevent /contact-us/ from defaulting to USD.
Replace manual JSON bracket parsing with json.JSONDecoder().raw_decode in source_parsers.py.
Consolidate coerce and normalize functions to reduce the surface area of validation bugs.
Add telemetry for VERDICT_LISTING_FAILED to identify why extraction failed (no cards vs. no pagination vs. blocked).
Migrate hardcoded social URL blocks to the pipeline_config.py configuration matrix.
Implement DOM-change Observers instead of arbitrary sleeps (wait_for_timeout) in the browser interaction layer to speed up scraping.
Do NOT touch the Adapter Registry. It is cleanly implemented and acts as an excellent escape hatch.
