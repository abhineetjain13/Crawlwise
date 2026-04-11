1. Separation of Concerns & SOLID
Score: 3/10
Violations:
[CRITICAL] pipeline/core.py -> _process_single_url (Lines 100-240): This is a massive God function that violates the Single Responsibility Principle. It manages the acquisition waterfall, executes adapter fallbacks, checks blocked-page heuristics, orchestrates the entire extraction pipeline, mutates database records, and updates run-state logs. It tightly couples I/O (acquisition) with CPU-bound processing (extraction) and database transactions.
[HIGH] extract/json_extractor.py -> extract_json_detail / extract_json_listing: These functions bypass the central FieldDecisionEngine entirely. If the API returns a JSON response type, the system executes a completely separate normalization and schema application path, ensuring that JSON extraction and HTML extraction will silently drift in behavior and output formatting over time.
[MEDIUM] pipeline/listing_helpers.py -> _enforce_listing_field_contract: Retained dead code. A comment explicitly states: "This function is kept for testing purposes. The actual contract enforcement happens inline." Production code should not contain dead logic just to keep legacy tests passing.
Verdict: The orchestration layer is fundamentally procedural rather than pipeline-oriented. The lack of a strict boundary between I/O, CPU work, and DB persistence makes the system rigid, difficult to test without deep mocking, and prone to side-effect bugs.
2. Extraction Correctness & Output Accuracy
Score: 5/10
Violations:
[HIGH] pipeline/core.py -> extract_candidates (Lines 630-680): Severe CPU/Memory waste. The HTML is parsed into a BeautifulSoup object here, but it was already parsed in run_adapter just lines earlier. Furthermore, HTML is parsed again inside various nested semantic extractors. For a 5MB DOM, this redundant parsing will incinerate CPU cycles.
[HIGH] extract/service.py -> _apply_surface_record_contract: Field isolation is brittle. Job-specific contract enforcement (e.g., mapping price to salary) happens via ad-hoc procedural mutations (normalized["salary"] = normalized.pop("price")) rather than through a declarative schema pipeline.
[MEDIUM] pipeline/trace_builders.py -> _build_review_bucket: PII leak risk. Discovered fields are swept up from random data attributes and dumped into the discovered_data column. While acquirer.py scrubs network payloads, the review bucket does not scrub embedded JSON/DOM data, meaning PII (emails/tokens) scraped accidentally will persist into the DB.
Verdict: While the "first-match-wins" arbitration via FieldDecisionEngine is a strong concept, the data pipeline leading up to it is messy. Redundant DOM parsing and procedural schema enforcement waste compute and invite cross-surface contamination.
3. Traversal & Acquisition Reliability
Score: 6/10
Violations:
[CRITICAL] acquisition/browser_client.py -> _kill_orphaned_browser_processes: Zombie process leak. The function relies on psutil to find and kill orphaned Chrome processes, but psutil is imported in a try/except block and treated as an "optional dependency fallback". If psutil is missing in the production container, zombie browser processes will accumulate infinitely until the server OOMs.
[HIGH] acquisition/browser_client.py -> _fetch_rendered_html_attempt (Lines 160-175): Hardcoded magic timeouts on critical context boundaries. await asyncio.wait_for(browser.new_context(...), timeout=15.0) uses a magic float 15.0 instead of the environment-backed configurations.
[MEDIUM] acquisition/traversal.py -> scroll_to_bottom: The wait_for_load_state("networkidle") captures PlaywrightError and does nothing, assuming the time has elapsed. However, if the network connection drops entirely, it masks the failure and registers it as a successful pagination step with 0 new items.
Verdict: The acquisition layer is robust against SSRF and handles proxies well, but process lifecycle management relies on fragile, optional dependencies. Hardcoded timeouts in the Playwright integration undermine the configuration system.
4. State Consistency & Idempotency
Score: 4/10
Violations:
[CRITICAL] pipeline/core.py -> _save_listing_records: Deduplication logic (_dedupe_listing_persistence_candidates) only operates within the current memory batch of extracted records. It does not check the database for existing identity keys. If a batch run pauses, fails, and resumes, or if pagination overlaps, duplicate records will be silently inserted into the database.
[HIGH] _batch_runtime.py and pipeline/core.py: Transaction tearing. _process_single_url creates and commits a DB transaction for a CrawlRecord, but the overall batch progress update happens via a separate with_for_update() transaction in persist_patch. If the worker is hard-killed between these two steps, phantom records will exist without corresponding batch progress, breaking idempotency on resume.
Verdict: The system lacks true transactional boundaries spanning progress-tracking and record-insertion. Memory-only deduplication guarantees data corruption (duplicates) during standard distributed failure/resume cycles.
5. Resilience & Error Handling
Score: 5/10
Violations:
[CRITICAL] pipeline/core.py -> _process_single_url: Event loop starvation. BeautifulSoup(html, "html.parser") is executed synchronously on the main thread. Python's asyncio is single-threaded. Parsing a 4MB HTML file takes ~150-300ms. If 8 concurrent URL tasks hit the ANALYZE stage simultaneously, the entire FastAPI event loop will freeze for >1 second, failing health checks and dropping concurrent network I/O.
[MEDIUM] acquisition/browser_client.py -> _fetch_rendered_html_attempt: Catch-all exception handling. The fallback loop catches (PlaywrightError, RuntimeError, ValueError, TypeError, OSError). Catching TypeError and ValueError masks actual programming bugs in the crawler itself, treating them as generic browser launch failures.
Verdict: Asynchronous I/O is implemented well, but CPU-bound operations (DOM parsing, massive Regex executions) are not offloaded to thread/process pools, which will fatally starve the async event loop under high concurrency.
6. Observability & Debuggability
Score: 7/10
Violations:
[MEDIUM] pipeline/core.py -> _extract_detail (Line 615): The system attempts to log the winning extraction sources (source_summary = ", ".join(winning_sources[:5])). However, if FieldDecisionEngine rejects a source due to sanitization rules, it only logs to logger.debug. Production operators cannot easily query the DB trace to see why an obvious XPath candidate was discarded in favor of a lower-tier source.
[LOW] crawl_events.py -> append_log_event: Swallows IntegrityError and Exception silently with a logger.debug if the detached DB session fails. Operational telemetry will silently drop during DB turbulence, precisely when logs are needed most.
Verdict: Telemetry and source-tracing are generally excellent. The trace structure attached to records is highly detailed, though production logging masks the internal arbitration decisions.
7. Security
Score: 8/10
Violations:
[LOW] url_safety.py: While validate_public_target correctly defends against DNS rebinding via IP resolution, and Playwright correctly implements --host-resolver-rules=MAP, http_client.py does not strictly pin the host header to the resolved IP for all proxy schemes, leaving a minor edge-case TOCTOU vector if the proxy itself resolves the DNS differently than the Python application.
Verdict: The security posture regarding SSRF prevention, proxy redaction, and browser isolation is remarkably mature and well-thought-out for a crawler system.
8. Scalability & Resource Management
Score: 4/10
Violations:
[CRITICAL] alembic/versions/20260410_0009_max_records_trigger.py: Hard Postgres lock-in. The migration uses raw plpgsql triggers to enforce max_records. This completely breaks the SQLAlchemy abstraction. You cannot run this system on SQLite for local testing or CI/CD without rewriting the database layer.
[HIGH] pipeline/core.py: Memory bloat. The system stores acq.html (the raw HTML string), passes it to BeautifulSoup, and keeps multiple string copies of fragments in memory during pagination traversal (_MAX_TRAVERSAL_TOTAL_BYTES = 6_000_000). Under high concurrency, this will spike RAM usage drastically.
Verdict: The system claims to be framework-agnostic but is hard-coupled to PostgreSQL triggers. Memory management is reckless regarding large string duplication and DOM object retention in the async context.
9. Configuration & 12-Factor
Score: 6/10
Violations:
[MEDIUM] extract/json_extractor.py -> _score_candidate_array: Arbitrary magic weighting. The algorithm scores candidate JSON arrays with score += 3 and score += 4 based on hardcoded key presence. These weights belong in extraction_rules.py, not buried in conditional logic.
[MEDIUM] config/extraction_rules.py: Unbounded Regex execution. SALARY_RANGE_REGEX is massive and highly complex. Against adversarial or malformed HTML, this pattern is highly susceptible to Catastrophic Backtracking (ReDoS), which will lock the CPU.
Verdict: runtime_settings.py effectively uses Pydantic for environment validation, but internal heuristic files (extraction_rules.py) contain dangerous regexes and magic numbers that bypass the configuration layer.
10. Test Coverage & Regression Safety
Score: N/A (Code structure inferred)
Violations:
[HIGH] pipeline/core.py: High cyclomatic complexity in _process_single_url makes unit testing nearly impossible. Testing the "blocked page fallback" path requires mocking the HTTP client, Playwright, DB session, blocked detector, and the adapter registry simultaneously.
Verdict: The orchestration code is written in a way that practically guarantees reliance on slow, flaky integration tests rather than fast, deterministic unit tests.
11. Dead Code & Technical Debt Hotspots
Score: 5/10
Violations:
[HIGH] adapters/jibe.py, oracle_hcm.py, etc.: Adapter bloat. Many adapters reinvent HTTP fetching using asyncio.to_thread(curl_requests.get...) instead of using the centralized http_client.py fetch logic. This means adapters bypass global rate limits, proxy rotation backoffs, and stealth headers defined centrally.
[LOW] semantic_detail_extractor.py -> _flatten_shadow_dom: Complex Javascript evaluation injected as strings into Playwright. This is extremely fragile technical debt that will break silently if target sites implement strict CSPs preventing inline script execution.
Verdict: Platform adapters are violating their boundaries by performing direct HTTP I/O, bypassing the centralized safety and throttling mechanisms of the core crawler.
Final Summary
Overall Score: 5.3/10
Critical Path (Ranked by Impact):
Main Thread Blocking: BeautifulSoup parsing runs synchronously on the async event loop in pipeline/core.py, which will freeze the FastAPI server under concurrent load.
Memory-Only Deduplication: Listing deduplication fails to check the database, guaranteeing duplicate records across paused/resumed batches.
Zombie Browser Leaks: Playwright context cleanup relies on psutil, which is optional. Without it, dead browsers will leak and consume all host memory.
Transaction Tearing: Crawl Run progress and Record insertions are committed separately, risking corrupted state if workers crash.
Database Lock-in: Migration 20260410_0009 uses raw plpgsql, destroying the SQLAlchemy compatibility layer and locking the system to Postgres.
Genuine Strengths:
SSRF Protection: url_safety.py and the validate_public_target flow combined with DNS pinning in browser_client.py is enterprise-grade security against internal network probing.
Data Lineage: The source_trace system (built in trace_builders.py and arbitrated in FieldDecisionEngine) is exceptionally well-designed for pipeline observability, allowing users to see exactly which tier provided a specific field value.
Will Break At Scale:
At 10k+ concurrent URLs, the system will experience cascading event-loop stalls due to synchronous HTML parsing (BeautifulSoup). As the loop stalls, Playwright browser contexts will timeout randomly. Concurrently, missing psutil dependencies will cause those timed-out browsers to become zombies, exhausting RAM and resulting in an unavoidable, unrecoverable Out-Of-Memory (OOM) death spiral for the worker nodes.