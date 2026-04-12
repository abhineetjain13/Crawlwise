1. Separation of Concerns & SOLID
Score: 5/10
Violations:
[HIGH] app/services/pipeline/core.py -> _extract_detail and _extract_listing (Lines ~390-600): These functions violently violate the Single Responsibility Principle. They mix extraction orchestration (extract_candidates), LLM review invocation, database entity creation (session.add(CrawlRecord)), data sanitization, and logging into massive 150+ line procedural blocks.
[MEDIUM] app/services/extract/traversal.py -> apply_traversal_mode: This function requires 20+ parameters (mostly injected callbacks like page_content_with_retry, snapshot_listing_page_metrics). It acts as a God Object for traversal rather than delegating to polymorphic Strategy classes (e.g., ScrollStrategy, PaginationStrategy).
[MEDIUM] app/models/crawl.py -> Domain Anemia: While CrawlRun has basic status transition logic, core domain logic for batch progress calculation is leaked into app/services/_batch_progress.py (BatchRunProgressState). The entity should own its state recalculations.
Verdict:
The introduction of PipelineRunner and PipelineContext is a great step toward the Chain of Responsibility pattern, but the actual extraction stages (ExtractStage) just wrap massive legacy procedural functions. The persistence layer is tightly coupled to the extraction logic, making it impossible to test extraction without a live database session.
2. Extraction Correctness & Output Accuracy
Score: 7/10
Violations:
[HIGH] app/services/extract/service.py -> _collect_candidates: The function evaluates all extraction strategies (DOM, JSON-LD, Adapters, Network) simultaneously and appends them to a list, relying entirely on FieldDecisionEngine to rank them later. This wastes massive CPU cycles parsing the DOM even when a high-fidelity JSON-LD or API payload has already provided the exact answer.
[MEDIUM] app/services/pipeline/core.py -> _extract_listing_records_single_page: The HTML is parsed into soup = BeautifulSoup(html, "html.parser") on line ~225, but ctx.soup was already parsed in ParseStage. This duplicates a highly CPU-bound operation.
[LOW] app/services/extract/listing_identity.py -> merge_record_sets_on_identity: This function bypasses FieldDecisionEngine entirely, implementing its own naive merging logic (_should_prefer_listing_value) based on string length. This creates two competing sources of truth for field arbitration.
Verdict:
The First-Match-Wins priority stack is logically sound in theory but implemented as "Extract Everything, Rank Later" in practice, wasting compute. Schema isolation between Job and Ecommerce surfaces is strictly enforced, which prevents cross-contamination nicely.
3. Traversal & Acquisition Reliability
Score: 8/10
Violations:
[MEDIUM] app/services/acquisition/browser_client.py -> _fetch_rendered_html_attempt (Lines ~160): The function sets a timeout on browser.new_context(), but if it fails, it calls _evict_browser and creates a new one without a global timeout wrapping the entire retry loop. Under severe Playwright hangs, this can leave the worker stalled indefinitely.
[MEDIUM] app/services/acquisition/pacing.py -> wait_for_host_slot: Relies on Redis SET nx ex for distributed rate limiting. If a worker acquires the lock, sleeps, and the Redis connection drops, redis_fail_open defaults to 0.0 (proceed immediately). Under Redis failure, all workers will simultaneously stampede the target host.
Verdict:
The acquisition waterfall (curl -> Playwright) and traversal bounds (e.g., max 50 scrolls) are highly robust and defensive. However, the distributed rate limiting fails open, which protects the crawler's uptime at the expense of potentially DDoS-ing target websites during infrastructure degradation.
4. State Consistency & Idempotency
Score: 6/10
Violations:
[CRITICAL] app/services/pipeline/core.py -> _save_listing_records (Lines ~340): Records are written via session.add(db_record). url_identity_key is calculated for DB-level deduplication. However, there is no ON CONFLICT DO NOTHING or try/except IntegrityError block. If a batch is paused/resumed and encounters an existing key, the session.flush() will throw an IntegrityError, rolling back the transaction and permanently sticking the URL batch.
[HIGH] app/services/_batch_runtime.py -> _retry_run_update: While the FOR UPDATE lock correctly synchronizes run summary updates, it locks the crawl_runs row for the duration of the DB flush. If multiple workers process URLs for the same run simultaneously, they will heavily contend on this single row lock, causing DB transaction timeouts at high concurrency.
Verdict:
The system achieves atomicity by flushing records and updating run progress in a single transaction, which is excellent design. Unfortunately, the lack of UPSERT semantics on scraped records breaks idempotency, making run resumption highly fragile.
5. Resilience & Error Handling
Score: 6/10
Violations:
[HIGH] app/services/extract/source_parsers.py -> parse_datalayer / _parse_json_blob: Calls json.loads(candidate) synchronously on extracted strings. If a target site embeds a 15MB __NEXT_DATA__ blob, this synchronous CPU-bound call will block the entire asyncio event loop for hundreds of milliseconds, stalling all other concurrent requests on that worker.
[MEDIUM] app/services/pipeline/runner.py -> execute: Catches terminal verdicts but lacks a global try/except Exception wrapper that translates unhandled Python errors into standard URLProcessingResult(verdict=VERDICT_ERROR). A bare KeyError in an adapter will crash the Celery task entirely rather than failing the specific URL.
Verdict:
Acquisition error handling (timeouts, proxies, blocked pages) is exceptionally well-modeled and typed (AcquisitionOutcome). However, CPU-bound JSON parsing operations threaten the async event loop's stability.
6. Observability & Debuggability
Score: 9/10
Violations:
[LOW] app/services/crawl_events.py -> _should_persist_log: The log sampling logic stores counters in Redis (_db_log_counter_key). If Redis is unavailable, it fails open to True. At high scale, a Redis outage will result in millions of log rows flooding the PostgreSQL database, potentially causing an outage.
Verdict:
This is world-class observability for a scraping pipeline. The source_trace, manifest_trace, and winning_sources telemetry allow an operator to perfectly reconstruct exactly why a specific value was chosen for a field.
7. Security
Score: 8/10
Violations:
[MEDIUM] app/services/pipeline/core.py -> _sanitize_persisted_record_payload: While _scrub_sensitive_text exists in the acquisition layer to redact credentials from diagnostics, there is no scrubber applied to discovered_fields or review_bucket. PII (emails, phone numbers) scraped accidentally via regex or LLM inference will be persisted in plaintext to the database.
Verdict:
The SSRF protection (validate_public_target preventing local/AWS metadata scraping) and the dynamic fallback to bundled_chromium when DNS-pinning is required are exceptionally well-engineered. The only gap is PII redaction in the actual data payloads.
8. Scalability & Resource Management
Score: 7/10
Violations:
[HIGH] app/services/resource_monitor.py -> MemoryAdaptiveSemaphore: This semaphore blocks dynamically based on psutil.virtual_memory(). However, this measures system-wide memory, not process memory. In a containerized environment (Docker/K8s) without proper cgroup-aware psutil configuration, this will read the host node's memory and fail to throttle the crawler before OOMKilled.
[MEDIUM] app/services/extract/dom_extraction.py -> _build_label_value_text_sources: Collects text from network payloads, hydrated states, and the DOM into massive string arrays. For heavy React SPA pages, this forces the garbage collector to work overtime, resulting in high memory fragmentation per URL.
Verdict:
Decoupling the CPU-heavy DOM parsing to asyncio.to_thread is the correct architecture for FastAPI. The adaptive memory semaphore is a brilliant concept, but its reliance on raw psutil makes it dangerous in Kubernetes environments.
9. Configuration & 12-Factor
Score: 8/10
Violations:
[LOW] app/services/config/crawl_runtime.py -> CrawlerRuntimeSettings: Hardcodes PERFORMANCE_PROFILES inside the Python file rather than loading them from an external tuning.json or environment variables, requiring a code deployment to adjust browser timeout behaviors.
Verdict:
Configuration is heavily centralized via Pydantic BaseSettings, well-typed, and correctly utilizes environment variables. Minimal violations found.
10. Test Coverage & Regression Safety
Score: 6/10
Violations:
[HIGH] app/services/pipeline/runner.py: Because the extraction logic heavily depends on the database (Session passed down to 5 levels of depth to save logs and records), it is impossible to run pure unit tests on the extraction logic without mocking the entire SQLAlchemy async session.
[MEDIUM] app/services/extract/variant_extractor.py: The variant resolution logic for Shopify and Demandware relies on extremely complex, mutually dependent JSON dictionaries. A slight change to _dedupe_variants risks silent data loss without rigorous parametrized regression tests.
Verdict:
The architecture relies too heavily on passing the active Database Session into deep business logic functions, severely hurting testability.
11. Dead Code & Technical Debt Hotspots
Score: 5/10
Violations:
[HIGH] app/services/extract/traversal.py: This file is a technical debt volcano. apply_traversal_mode handles Infinite Scroll, Pagination, Load More, and Auto-detection inside a single monolithic function using nested functions and deeply coupled state (collected_fragments, captured_fragment_bytes). It needs to be refactored into the Strategy Pattern immediately.
[MEDIUM] app/services/extract/listing_card_extractor.py -> _auto_detect_cards: Utilizes a highly complex heuristic scoring system (_card_group_score) that mixes ecommerce and job logic. This is brittle and will require constant tweaking as new site layouts are encountered.
Verdict:
While the pipeline orchestration (PipelineRunner) is clean, the actual traversal and DOM-card extraction logic is highly procedural and brittle.
Final Summary
Overall Score: 6.8/10
Critical Path (Fix Immediately):
Idempotency Failure: Wrap session.add(db_record) in the persistence layer with ON CONFLICT DO NOTHING or handle IntegrityError. Currently, restarting a batch job will crash the database transaction on duplicate URLs.
Event Loop Starvation: Move json.loads() calls in parse_datalayer and _parse_json_blob into asyncio.to_thread(). Multi-megabyte JSON blobs will lock the FastAPI event loop.
Cgroup Memory Blindness: Update MemoryAdaptiveSemaphore to read container-aware memory limits (cgroups v2) rather than psutil virtual memory, or it will fail to prevent OOM kills in Kubernetes.
Database Lock Contention: Decouple URL record inserts from the CrawlRun progress update FOR UPDATE lock. Use Redis counters for real-time progress and batch DB updates asynchronously to prevent lock contention.
Extraction Waste: Implement short-circuiting in _collect_candidates. If the API/JSON-LD provides a 100% confidence match for a field, skip running the expensive XPath/Regex DOM extractors for that field.
Genuine Strengths:
SSRF Prevention: The url_safety.py implementation, combined with the dynamic switch to bundled_chromium when DNS-pinning is required (browser_client.py), is a masterclass in secure crawler design.
Observability: The manifest_trace and source_trace artifacts persisted alongside records provide perfect audibility into exactly which regex, DOM node, or JSON payload generated a specific data point.
Session Affinity: SessionContext (session_context.py) perfectly binds Proxies, TLS impersonation profiles, and Cookie Jars into a single lifecycle, ensuring targets see a consistent identity per scrape attempt.
Will Break At Scale (10k+ URLs):
Running 10,000 URLs concurrently will result in severe PostgreSQL transaction timeouts. Because every single URL flush attempts to acquire a FOR UPDATE lock on the parent CrawlRun row (via _retry_run_update), the database will spend more time managing row lock queues than persisting data. Progress updates must be asynchronous or batched.