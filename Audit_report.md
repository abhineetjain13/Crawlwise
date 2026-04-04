A. Executive Summary
The backend establishes a solid conceptual pipeline (Acquire → Discover → Extract → Unify) and utilizes advanced Playwright/curl_cffi fallback strategies effectively. However, it suffers from several severe concurrency and data-integrity flaws that will manifest as scale increases.
Top 5 Highest-Value Issues:
Critical: _recover_orphan_runs causes cross-worker job assassination. If one worker restarts while another is running, the restarting worker will permanently fail the active worker's jobs.
High: Pagination implementation concatenates multiple HTML pages into a single giant string. This will cause catastrophic memory bloat, break structural CSS selectors, and crash BeautifulSoup on large listing runs.
High: CSV export dynamically builds headers from only the first 1000 rows. If row 1001 introduces a new field, it is silently dropped, leading to silent data loss in exports.
Medium: LLM prompt truncation blindly slices JSON strings, sending malformed JSON to providers resulting in guaranteed LLM failures/hallucinations on large pages.
Medium: Batch runs execute sequentially in a single thread, and a single unhandled URL exception can crash the entire run, discarding progress.
B. Findings Table
Title	Severity	Problem	Likely Symptom	Files / Functions	Scope	Recommendation	Type
Worker Fratricide on Boot	Critical	workers.py::_recover_orphan_runs finds all CLAIMED/RUNNING jobs in the DB and marks them FAILED. It does not filter by a worker_id.	If scaling to >1 worker container, any deployment/restart kills active jobs on healthy containers.	workers.py::_recover_orphan_runs	All Runs	Add a worker_id UUID column to CrawlRun. Workers must only recover orphans they specifically owned.	Bug
Memory Bomb in Pagination	High	_collect_paginated_html appends pages to a single string using <!-- PAGE BREAK -->.	OOM crashes on listing runs > 10 pages. Extractor will find wrong elements because multiple <body> tags are merged.	browser_client.py::_collect_paginated_html<br>listing_extractor.py	Listing	Yield/save individual pages to disk or process them sequentially. Do not concatenate DOMs.	Design Debt
Silent Data Loss in CSV Export	High	_stream_export_csv buffers 1000 rows to determine fieldnames. Fields appearing only in row 1001+ are silently discarded by DictWriter.	Missing columns in CSV exports for large runs, despite data existing in the UI/JSON.	records.py::_stream_export_csv	Export	Execute a fast first-pass SELECT json_keys(data) (or app-side merge) to build a complete header schema before streaming.	Bug
Token Truncation Corrupts JSON	Medium	_enforce_token_limit blindly slices strings by length and appends ... [TRUNCATED]. When applied to JSON payloads, it creates invalid JSON.	LLM extraction returns HTTP 400s or hallucinations because the prompt is syntactically broken.	llm_runtime.py::_enforce_token_limit	Detail / LLM	Implement JSON-aware pruning (like spa_pruner.py) or truncate string values inside the JSON, never the raw JSON string itself.	Bug
Head-of-Line Blocking in Batch Runs	Medium	process_run iterates through urls synchronously. A 1,000 URL batch run blocks the worker entirely.	Workers stalled for days on single jobs. UI shows slow progress.	crawl_service.py::process_run	Batch	Shift batch orchestration to dispatch individual celery/asyncio tasks per URL, joining results at the end.	Design Debt
Cross-Process State Drift	Medium	pacing.py and host_memory.py use in-memory asyncio.Lock and file-based JSON.	Rate limits violated and stealth preferences overwritten when running multiple worker processes.	pacing.py<br>host_memory.py	Acquisition	Move rate-limit pacing and stealth memory to Redis or the existing SQLite/Postgres DB.	Invariant Gap
C. Invariant Audit
The following invariants are currently missing or weak:
Job Resumption vs. Orphan Recovery:
Gap: process_run explicitly states: "RUNNING implies it was already in progress and we are resuming (e.g. after a worker restart)." However, because _recover_orphan_runs marks all RUNNING jobs as FAILED on startup, the resumption logic is unreachable dead code.
Immutability of Source Data:
Gap: In commit_selected_fields (crawls.py), when a user overrides a field, it mutates record.data directly. If the UI needs to revert, or if the run is re-processed, the pristine extracted state is tangled with manual overrides.
Per-URL Isolation in Batch Runs:
Gap: In process_run, an unhandled exception outside of the acquire block (e.g., a DB serialization error during extraction) falls back to the outer except Exception, marking the entire run FAILED. Partial progress on previous URLs is orphaned in the DB without a COMPLETED run status.
Extraction Data Type Contracts:
Gap: normalize_value (field_normalizers.py) coerces lists into comma-separated strings (", ".join()). If downstream LLM steps or API consumers expect lists for arrays (e.g., additional_images, features), this premature stringification breaks structural integrity.
D. Pipeline-Specific Review
1. Listing Pipeline
DOM Concatenation: As noted, injecting <!-- PAGE BREAK --> and running BeautifulSoup over multiple appended HTML documents destroys CSS selector integrity (e.g., div:first-child behaves unpredictably).
Deduplication: _merge_structured_record_sets deduplicates on title|price. If an ecommerce site lists variations of a product (e.g., "T-Shirt" for $19.99 in Red and Blue), one will be silently dropped.
Semantic Leakage: _is_meaningful_listing_record rejects records if the only fields are title and image_url. Some valid directory listings only have a title and image. This is too aggressive.
2. Detail Pipeline
LLM Pipeline Brittle Prompting: review_field_candidates dumps massive truncated HTML and JSON into the LLM. If the HTML limit (12,000) splits a tag halfway, the LLM context degrades.
XPath Validation: validate_xpath_candidate uses tree.xpath(xpath). If the LLM hallucinates a complex XPath 2.0/3.0 function, lxml (which supports XPath 1.0) will throw XPathSyntaxError which is swallowed, resulting in silent capability degradation.
3. Batch Execution
Synchronous Processing: The for idx in range(start_index, total_urls): loop is entirely sequential. There is no concurrency within a run.
Checkpointing Bug: The loop saves persisted_record_count and updates progress. However, if a user pauses the run, the logic update_run_status(run, CrawlStatus.PAUSED); return executes. When resumed, it starts from start_index again. If start_index logic (completed_urls) isn't perfectly incremented on partial URL failures, it will re-crawl URLs or skip them.
4. Output / Export Layer
Export Heuristics: records.py::_drop_duplicate_export_fields silently mutates the user's data during export. It attempts to drop fields that look like duplicates based on string-matching values and arbitrary scoring (score -= 20). Do not mutate or hide data at the export layer. If the system extracted it, the user expects it in the CSV/JSON.
Discoverist Schema: export_discoverist hardcodes fields from a JSON schema. If the run extracted custom_attribute, it is silently omitted from this export type.
E. Debt Patterns
Broad Exception Swallowing:
browser_client.py::_find_next_page_url uses except Exception: continue. If Playwright throws a disconnected error, it is silently treated as "no next page".
xpath_service.py heavily relies on except etree.XPathError: return None.
HTML Munging over Parsing:
_clean_candidate_text and BlockedPageResult use Regex to strip HTML tags (re.sub(r"<[^>]+>", " ", text)). This is notoriously unsafe and leads to text mashing (e.g., <h1>A</h1><p>B</p> becomes AB instead of A B).
Overloaded result_summary JSON:
CrawlRun.result_summary is acting as a sub-database. It tracks url_verdicts, verdict_counts, completed_urls, and control_requested. Because SQLAlchemy JSON fields don't detect deep mutations automatically, concurrent updates to this field (e.g., a user pausing via API while the worker updates progress) will cause race condition overwrites.
F. Bugs and Likely Bugs
Definite Bug: records.py::_export_headers sets X-Export-Partial: true if metadata["truncated"] is true. But _collect_export_metadata hardcodes "truncated": False. The header is mathematically incapable of representing reality.
Likely Bug: browser_client.py::_goto_with_fallback iterates through networkidle, load, domcontentloaded. If networkidle fails, it retries load without reloading the page context if the browser is stuck in a weird state. It should force a fresh context or explicit page.reload.
Race Condition: api/crawls.py::crawls_pause updates the database state to PAUSED. However, the worker is currently blocked inside acquire(). The worker doesn't check the DB again until acquire() finishes (which could be 30 seconds). The UI will show "Paused", but the worker is still crawling.
Data Loss Risk: commit_selected_fields relies on client-provided record_id. It does not verify that the record_id actually belongs to the run_id being modified, beyond the where clause. If the UI passes a wrong ID, it fails silently (if record is None: continue).
G. Tests to Add (Top 10)
test_worker_does_not_kill_active_peers:
Scenario: Spin up Worker A processing a job. Spin up Worker B.
Assert: Worker A's job remains RUNNING and finishes successfully.
test_csv_export_dynamic_schema_discovery:
Scenario: Seed 1001 records. Record 1001 has a new key {"rare_field": "value"}.
Assert: The generated CSV header includes rare_field.
test_llm_json_truncation_validity:
Scenario: Pass a 20,000 character JSON string to _enforce_token_limit.
Assert: json.loads() on the resulting string does not throw JSONDecodeError.
test_batch_run_partial_failure_isolation:
Scenario: Batch run of 3 URLs. Force URL 2 to raise a ValueError inside _extract_detail.
Assert: Run finishes COMPLETED (or PARTIAL), URL 1 and 3 output records are saved, URL 2 logs an error.
test_pagination_dom_isolation:
Scenario: Paginated extraction of 3 pages where Page 1 has item A, Page 2 has item A (duplicate).
Assert: Extractor returns exact count without CSS selector bleed between pages.
test_pause_resume_checkpointing:
Scenario: Batch of 10 URLs. Pause at URL 5. Resume.
Assert: Total URL fetch calls equal exactly 10. No skipped URLs.
test_blocked_detection_kasada:
Scenario: Pass Kasada challenge HTML.
Assert: Returns is_blocked=True, provider="kasada".
test_export_does_not_drop_heuristically:
Scenario: Run export on data with fields price_1 and price_2.
Assert: Neither column is dropped by _drop_duplicate_export_fields.
test_manual_field_commit_immutability:
Scenario: User edits a field via /commit-fields.
Assert: The edit is reflected in data, but raw_data retains the original extracted value perfectly.
test_pacing_cross_process:
Scenario: Two independent processes request locks for the same host.
Assert: The delta between executions respects ACQUIRE_HOST_MIN_INTERVAL_MS.
H. Implementation Roadmap
Phase 1: High-Confidence Fixes (Immediate)
Change records.py CSV exporter to pre-scan all JSON keys into a set via an initial fast DB pass before opening the DictWriter.
Remove or bypass _drop_duplicate_export_fields in records.py to prevent silent data mutation.
Fix LLM truncation logic: truncate string values inside the JSON payload before json.dumps, rather than slicing the serialized string.
Phase 2: Concurrency & State Invariants (Weeks 1-2)
Add worker_id to CrawlRun. Update _recover_orphan_runs to only recover runs matching the booting worker's ID (or use a heartbeat mechanism to detect truly dead workers).
Refactor CrawlRun.result_summary. Extract volatile state (progress, completed_urls) into top-level columns to avoid JSON race conditions.
Replace pacing.py and host_memory.py in-memory/file locks with Redis or PostgreSQL/SQLite row-level locks.
Phase 3: Structural Refactors (Weeks 3-4)
Pagination Rewrite: Stop using <!-- PAGE BREAK -->. Have browser_client.py yield HTML pages as an asynchronous generator. Pass them individually into listing_extractor.py and merge the resulting Python dictionaries.
Batch Parallelization: Introduce asyncio.gather with a bounded semaphore in process_run to execute batch URLs concurrently, dramatically speeding up multi-URL jobs.
Phase 4: Hardening (Ongoing)
Implement the 10 tests outlined above.
Replace Regex HTML stripping with BeautifulSoup(html).get_text(separator=" ").
Strengthen the UI field override logic to ensure raw_data acts as an immutable event-sourced log.