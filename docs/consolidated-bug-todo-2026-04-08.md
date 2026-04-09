# Consolidated TODO - Bugs and Pending Items (2026-04-08)

This list merges and verifies all points from:
- `docs/audit_report.md`
- `docs/backend-pending-items.md`
- `docs/codeant-triage-2026-04-07.md`
- `docs/EXCEPTION_HANDLING_PLAN.md`

Verification labels:
- `OPEN`: confirmed still present via current code/docs.
- `PARTIAL`: mitigated in part, but still pending.
- `VERIFY`: explicitly requires re-scan or deeper runtime validation.
- `INFO`: bookkeeping/non-goal from source reports.

Implementation updates:
- 2026-04-08: `backend/app/services/pipeline/core.py` `_sqlite_live_checkpoint` switched from `commit_with_retry()` to `with_retry()` wrapper semantics.
- 2026-04-08: `backend/app/services/acquisition/browser_client.py` listing-readiness selector counting now catches `PlaywrightError` instead of blanket `Exception`.
- 2026-04-08: `backend/app/services/acquisition/traversal.py` replaced blanket catches with `PlaywrightError` in next-link inspection and scroll-step fallback paths.
- 2026-04-08: additional exception-hardening pass in `backend/app/services/acquisition/browser_client.py` for launch-profile failures, low-value page checks, frame-content collection, listing metrics snapshot, and readiness selector checks.
- 2026-04-08: completed traversal high-priority exception pass in `backend/app/services/acquisition/traversal.py`; remaining blanket catches there are now `0`.
- 2026-04-08: completed browser-client high-priority exception pass; remaining blanket catches in `backend/app/services/acquisition/browser_client.py` are now `0`.
- 2026-04-08: started adapter exception hardening; replaced blanket catches in `backend/app/services/adapters/shopify.py` and `backend/app/services/adapters/greenhouse.py`.
- 2026-04-08: completed medium-priority adapter exception pass for `saashr.py`, `paycom.py`, `oracle_hcm.py`, `jibe.py`, and `icims.py`.
- 2026-04-08: completed low-priority infra exception pass in `host_memory.py`, `cookie_store.py`, `dashboard_service.py`, `schema_service.py`, and `page_classifier.py`; no blanket catches remain in those files.
- 2026-04-08: added row-locking on non-SQLite run updates in `_batch_runtime.py` via `SELECT ... FOR UPDATE` path inside `_retry_run_update`.
- 2026-04-08: removed exact-domain readiness override map and switched listing readiness to pattern-based resolver in `services/config/selectors.py` consumed by `browser_client.py`.
- 2026-04-08: cleared adapter-registry blanket catches in `services/adapters/registry.py`.
- 2026-04-08: cleared blanket catches in `services/acquisition/http_client.py` and `services/acquisition/acquirer.py`.
- 2026-04-08: cleared final service-level blanket catches in guardrail paths (`services/pipeline/core.py`, `services/_batch_runtime.py`).
- 2026-04-08: added in-process per-run async locking for `_retry_run_update` in `services/_batch_runtime.py` to serialize `result_summary` mutations on all dialects; non-SQLite row locking remains enabled with `FOR UPDATE`.
- 2026-04-08: routed batch `result_summary` writes through `_merge_run_summary_patch()` in `_batch_runtime.py` with monotonic counters and safer list/dict merge (`url_verdicts`, `verdict_counts`).
- 2026-04-08: added regression tests for summary merge behavior in `backend/tests/services/test_batch_runtime_summary_merge.py` (3 tests passing).
- 2026-04-08: added integration-style concurrency test for `_retry_run_update` serialization in `backend/tests/services/test_batch_runtime_integration.py` (combined batch-runtime tests: 4 passing).
- 2026-04-08: implemented persistent browser pooling in `services/acquisition/browser_client.py` (context-per-request, browser reuse by launch-profile/proxy key, stale pooled-browser eviction + retry).
- 2026-04-08: retired `commit_with_retry()` footgun implementation in `services/db_utils.py` (now hard-deprecated runtime error), and updated db-utils tests (`3 passed`).
- 2026-04-08: hardened background crawl rescue path in `api/crawls.py` with unified retry-safe failure marking (`_mark_run_failed_with_retry`) that writes status + summary together; added tests in `backend/tests/api/test_crawls_background.py` (`2 passed`).
- 2026-04-08: fixed `backend/app/services/pipeline/__init__.py` import syntax regression (invalid quoted entries in core import list).
- 2026-04-08: tightened HTTP redirect SSRF guardrails in `services/acquisition/http_client.py` by rejecting non-HTTP(S) and credential-bearing redirect targets before follow-up validation/fetch; added regression coverage in `backend/tests/services/acquisition/test_http_client.py` (`13 passed`).
- 2026-04-08: hardened SQL `LIKE` wildcard handling in `services/user_service.py` using escaped patterns with explicit `escape='\\'`; added regression test `backend/tests/services/test_user_service.py` and re-validated existing crawl URL search wildcard test (`2 passed`).
- 2026-04-08: extended network payload scrubbing to DB-persisted `manifest_trace` payloads via `scrub_network_payloads_for_storage()` in `services/acquisition/acquirer.py` and pipeline trace builder usage; added regression test `backend/tests/services/test_trace_builders.py` (`2 passed` with existing acquirer scrub test).
- 2026-04-08: executed verification security scans in backend scope: `detect-secrets` found no secrets in `app/` and `tests/` with cache/artifact exclusions; `pip-audit` reported environment-level vulnerabilities and requires isolated project-lock verification before dependency-status closure.
- 2026-04-08: ran project-scoped dependency audit by deriving requirements from `backend/pyproject.toml` and scanning with `pip-audit` (`No known vulnerabilities found`).
- 2026-04-08: added exception-path validation tests in `tests/api/test_crawls_background.py` for startup requeue DB failure handling and background runtime failure marking (`4 passed`).
- 2026-04-08: added correlation-id tagging for batch runtime background logs in `services/_batch_runtime.py` (`[corr=<id>]` prefix via telemetry context), persisting missing `result_summary.correlation_id` when absent; added `test_batch_runtime_correlation.py` and re-ran batch runtime tests (`6 passed`).
- 2026-04-08: added proxy failure cooldown/backoff in `services/acquisition/acquirer.py` (temporary skip of repeatedly failing proxies with bounded exponential cooldown, plus cooldown-bypass probe fallback to avoid deadlock when all proxies are cooling down); wired tunables in `pipeline_config.py` and added tests in `test_acquirer.py` (`41 passed`).
- 2026-04-08: introduced initial unified crawler exception hierarchy in `services/exceptions.py` and adopted it in targeted runtime paths (`ProxyPoolExhausted`, `RunControlSignal`); added regression coverage in `test_exception_hierarchy.py` (`5 passed` with targeted runtime checks).
- 2026-04-08: expanded unified exception hierarchy with `BrowserError`, `ExtractionError`, and `AdapterError`; narrowed startup requeue DB failure handling in `api/crawls.py` to `SQLAlchemyError` and tightened SQLite VACUUM fallback handling in `dashboard_service.py` with targeted exception tuple; regression tests passing (`5 passed` targeted run).
- 2026-04-08: hardened SSRF proxy boundary by validating configured proxies as public endpoints (`validate_proxy_endpoint`), disabling ambient env-proxy trust in HTTP acquisition (`trust_env=False`), and adding regression coverage in `test_url_safety.py`, `test_http_client.py`, and `test_acquirer.py` (`23 passed`).
- 2026-04-08: added browser-path final URL public-host revalidation in acquisition so Playwright results resolving to non-public targets are rejected (with curl fallback where available); regression covered in `test_acquirer.py`.
- 2026-04-08: broadened SQLite lock retry detection in `services/db_utils.py` to cover table/schema lock variants; added lock-variant regression coverage in `test_db_utils.py` (`6 passed`).
- 2026-04-08: replaced API-owned in-memory crawl task orchestration with a DB-lease worker loop (`services/workers.py`) started from app lifespan; runs are now claimed durably (`queue_owner` + lease heartbeat), stale running runs are re-queued instead of auto-failed on startup, and crawl API create/resume/kill paths no longer spawn/cancel in-memory tasks. Added queue tests (`test_workers_queue.py`) and updated startup/background tests (`8 passed`).
- 2026-04-08: hardened durable queue with contention-focused coverage (two-worker same-run claim race) and added queue observability counters (`queue_claimed_runs_total`, stale-recovery/heartbeat/release/failure metrics) in `services/workers.py` (`4 passed` workers queue tests).
- 2026-04-08: tightened queue lease-fencing semantics in `services/workers.py` so only `pending` or lease-expired `running` rows are claimable (no direct claim of lease-less `running` rows), with new regression coverage in `test_workers_queue.py` (`5 passed`).
- 2026-04-08: added multi-worker loop burn-in coverage in `test_workers_queue.py` by running two live `CrawlWorkerLoop` instances against the same queue and verifying each pending run is processed exactly once with clean lease release (`6 passed`).
- 2026-04-08: added queue ops observability helper `get_queue_health_snapshot()` + `QueueHealthSnapshot` in `services/workers.py` (status counts, leased vs stale running, oldest pending age), with regression coverage in `test_workers_queue.py` (`7 passed`).
- 2026-04-08: closed browser-path SSRF request-time gap by adding Playwright request guardrails in `browser_client.py` that block non-public HTTP(S) request targets during navigation/resource loading and record diagnostics for blocked requests; added targeted regression tests (`3 passed`).
- 2026-04-08: added exception-translation regression tests in `backend/tests/api/test_crawls_background.py` validating actionable HTTP 400 details and stack-trace cause preservation (`raise ... from exc`) for `crawls_create` and `crawls_create_csv` ValueError paths.
- 2026-04-08: standardized ValueError→HTTPException translation in `api/crawls.py` via shared `_raise_http_from_value_error(...)` helper and expanded regression coverage in `backend/tests/api/test_crawls_background.py` to include conflict endpoints (`crawls_delete`, `crawls_pause`, `crawls_resume`, `crawls_kill`, `crawls_cancel`) with actionable HTTP 409 detail + preserved `__cause__` (`9 passed` targeted file).
- 2026-04-08: optimized listing extractor regex hot paths by caching case-insensitive pattern compilation (`_compile_case_insensitive_regex`) and precompiling dimension/measurement matchers in `backend/app/services/extract/listing_extractor.py`; added targeted regression/cache tests in `backend/tests/services/extract/test_listing_extractor.py` (`3 passed`).
- 2026-04-08: frontend reliability/perf follow-up completed: Playwright smoke flow wired in CI (`.github/workflows/frontend-playwright-smoke.yml`) and verified locally (`1/1`), run-screen polling unified under single scheduler, table tab moved to progressive server pagination + virtualization, logs moved to incremental cursor fetching (`after_id`), and websocket live-log stream added with polling fallback (`/api/crawls/{run_id}/logs/ws`).
- 2026-04-08: added full SQLite lock integration coverage in `backend/tests/services/test_db_utils.py` using two real async sessions against a file-backed DB (`BEGIN IMMEDIATE` holder lock + retrying writer), closing the remaining lock-behavior integration gap for `with_retry`.
- 2026-04-08: fixed detail-title candidate ordering regression in `backend/app/services/extract/service.py` by filtering microdata navigation labels (`department navigation`) from title candidates; targeted extract regression suites now pass (`78 passed` across `test_extract.py` + `test_extract_refactoring_properties.py`).
- 2026-04-08: added explicit parallel-path timeout regression coverage in `backend/tests/services/test_crawl_service.py` (`test_process_run_honors_per_url_timeout_with_parallel_watchdog`) by forcing isolated-session batch concurrency and validating watchdog timeout failure semantics (`2 timeout tests passed` with existing sequential timeout test).
- 2026-04-08: reduced high-volume crawl-log pressure on relational DB writes by adding per-run DB log caps (`crawl_log_db_max_rows_per_run`) and JSONL file sink (`crawl_log_file_enabled`, `crawl_log_file_dir`) in `services/crawl_events.py`; added regression coverage in `backend/tests/services/test_crawl_events.py` (`6 passed`).
- 2026-04-08: optimized additional regex/text hot paths in semantic/source parsing by precompiling repeated heading/price/spec-key patterns in `services/semantic_detail_extractor.py` and Apollo meta-name pattern in `services/extract/source_parsers.py`; targeted suites remain green (`10 passed` semantic + `71 passed` extract).
- 2026-04-08: completed semantic hotspot follow-up in `services/semantic_detail_extractor.py` by precompiling remaining heading-level and alpha-detection regex checks (`_HEADING_LEVEL_RE`, `_HAS_ALPHA_RE`) used in section-label heuristics; semantic regression suite remains green (`10 passed`).
- 2026-04-08: refactoring-focused extraction cleanup pass split `extract/service.py` `_collect_candidates(...)` DOM/meta + semantic-target branches into helper functions (`_collect_dom_and_meta_candidates`, `_is_semantic_requested_field`) and deduplicated listing contract enforcement in `extract/listing_extractor.py` by reusing `_enforce_listing_field_contract(...)`; targeted extract suites remain green (`78 passed` in extract service tests, `67 passed` in listing extractor tests).
- 2026-04-08: continued crawl orchestration refactor in `services/crawl_service.py` by extracting runtime dependency patching into `_wire_runtime_dependencies()` (replacing inline multi-module monkeypatch block in `process_run`) and normalizing control-operation function shape/formatting (`pause_run`, `resume_run`, `kill_run`); crawl-service regression suite remains green (`79 passed`).
- 2026-04-08: reduced traversal-config duplication in `services/acquisition/browser_client.py` by centralizing shared config creation in `_traversal_config()` and reusing it across traversal wrappers (`_apply_traversal_mode`, `_collect_paginated_html`, `_find_next_page_url_anchor_only`, `_click_and_observe_next_page`, `_scroll_to_bottom`, `_click_load_more`, `_has_load_more_control`); refreshed browser-client traversal tests with stub compatibility updates (`35 passed`).
- 2026-04-08: fixed backend suite blockers before continuing refactors: corrected parameter-order syntax error in `api/crawls.py` (`crawls_logs` dependency args), stabilized Hypothesis datalayer property tests with explicit `@settings(... suppress_health_check=[HealthCheck.too_slow])`, and preserved fallback behavior while narrowing selected exception paths (`browser_client.py`, `workers.py`, `schema_service.py`); backend suite now passes (`662 passed`, `2 warnings`).
- 2026-04-08: continued `extract/service.py` complexity refactor by splitting first-match source tiers in `_collect_candidates(...)` into focused helpers (`_collect_contract_candidates`, `_collect_adapter_candidates`, `_collect_datalayer_candidates`, `_collect_network_payload_candidates`, `_collect_jsonld_candidates`, `_collect_structured_state_candidates`) while preserving tier order semantics; targeted extract refactoring suites remain green (`78 passed`).
- 2026-04-08: continued `extract/listing_extractor.py` complexity cleanup by decomposing `_extract_from_card(...)` into focused helpers (`_extract_ecommerce_price_fields`, `_extract_card_title`, `_extract_card_image_fields`, `_extract_job_card_fields`) while preserving behavior and field-resolution order; listing extractor regression suite remains green (`67 passed`).

---

## P0 - Critical correctness/reliability/security

- [x] **Replace commit-only retry usages with unit-of-work retry**
  - **Status:** `DONE`
  - **Why:** `commit_with_retry()` still exists and explicitly warns state can be lost on rollback.
  - **Verification:** no runtime callsites remain; `commit_with_retry()` is now hard-deprecated and raises with migration guidance to `with_retry(session, operation)`.
  - **Source(s):** `audit_report.md` (Top risk #1, Architecture finding #2, 30/60/90, blueprint), plus pending reliability concerns.

- [x] **Audit and remove dangerous `commit_with_retry()` call sites for mutable run state**
  - **Status:** `DONE`
  - **Why:** Progress/result mutations can still lose updates under lock if using commit-only retries in mutable flows.
  - **Verification:** direct call in `backend/app/services/pipeline/core.py` removed earlier; repository-wide search now shows no runtime usage of `commit_with_retry()`.
  - **Source(s):** `audit_report.md`.

- [x] **Fix `result_summary` race conditions with atomic updates/locking**
  - **Status:** `DONE`
  - **Why:** Python read-modify-write updates risk last-writer-wins under concurrency.
  - **Verification:** `_batch_runtime.py` now uses `_merge_run_summary_patch()` for progress/finalize/proxy-exhausted writes, plus per-run in-process locking in `_retry_run_update` and non-SQLite `with_for_update()` row locking; regression + integration tests added (`test_batch_runtime_summary_merge.py`, `test_batch_runtime_integration.py`) and passing.
  - **Source(s):** `audit_report.md` bug candidate #2, top risks, remediation plan.

- [x] **Eliminate per-request browser process launch; implement browser pooling**
  - **Status:** `DONE`
  - **Why:** audit flags catastrophic overhead if launching browser per URL.
  - **Verification:** browser acquisition path now uses pooled browser instances (`_acquire_browser`/`_browser_pool_key`) and reuses browser processes across requests while still creating isolated contexts per request.
  - **Source(s):** `audit_report.md` architecture finding #1, performance section, 30-day plan.

- [x] **Replace in-memory/background-task orchestration with durable queue architecture**
  - **Status:** `DONE`
  - **Why:** restart-safe reliability concerns remain in reports; long-running batch orchestration risk.
  - **Verification:** API in-memory task ownership has been removed in favor of DB-backed lease claiming + heartbeat worker loop, stale-running recovery now re-queues to pending, contention tests now cover both claim-race and two-live-worker loop processing (each run processed exactly once), claim semantics fence `running` rows behind lease-expiry, queue metrics counters are emitted for claims/heartbeats/releases/recovery/failures, and a queue health snapshot helper now exposes operational queue shape (pending/running/completed/failed, leased vs stale running, oldest pending age).
  - **Source(s):** `audit_report.md` top risks, technical debt, 60-day plan.

- [x] **Harden TOCTOU SSRF protections (pinning, redirect revalidation, proxy boundary)**
  - **Status:** `DONE`
  - **Why:** report still flags DNS check vs request-use gap class as a risk.
  - **Verification:** redirect hops are revalidated per-hop and reject non-HTTP(S)/credential-bearing targets, configured proxies are validated as public endpoints, HTTP acquisition disables ambient env-proxy trust, browser final URLs are revalidated as public, and request-time browser guardrails now block non-public HTTP(S) request targets.
  - **Source(s):** `audit_report.md` architecture #4 and security section.

- [x] **Prevent stuck `running` status when background error recovery also faces DB lock**
  - **Status:** `DONE`
  - **Why:** rescue path can fail to finalize run status under contention.
  - **Verification:** `_run_crawl_background` timeout/exception paths now call `_mark_run_failed_with_retry` which retries status + summary mutation together via `with_retry`; dedicated tests validate failed transition and terminal-status no-op behavior.
  - **Source(s):** `audit_report.md` bug candidate #4.

- [ ] **Re-evaluate production DB backend strategy (SQLite contention risk)**
  - **Status:** `PARTIAL`
  - **Why:** heavy concurrent writes and lock contention repeatedly flagged.
  - **Verification:** immediate mitigation landed by broadening SQLite lock retry detection (`database/table/schema locked` variants). Long-term backend strategy/migration decision remains open.
  - **Source(s):** `audit_report.md` technical debt, performance, 30-day plan.

---

## P1 - Invariant-sensitive architecture and hardcoded logic

- [x] **Remove hardcoded per-domain listing readiness logic from browser code**
  - **Status:** `DONE` (high priority per user request)
  - **Why:** domain-specific behavior in service code violates config centralization and maintainability expectations.
  - **Verification:** browser path now calls config `resolve_listing_readiness_override(page_url)` (pattern-based), and exact-domain `LISTING_READINESS_OVERRIDES` map has been removed.
  - **Source(s):** `backend-pending-items.md` (explicit), `audit_report.md` maintainability concerns.

- [ ] **Finish de-hardcoding extraction/config behavior from large config/code blobs**
  - **Status:** `PARTIAL`
  - **Why:** repeated debt item: config/rules should be externalized and easier to change safely.
  - **Verification:** listing card-title selector priority was moved from `extract/listing_extractor.py` into typed config (`services/config/extraction_rules.py` -> `pipeline_config.LISTING_CARD_TITLE_SELECTORS`); detail extraction noise-phrase tuples (`_TITLE_NOISE_PHRASES`, `_CATEGORY_NOISE_PHRASES`, `_AVAILABILITY_NOISE_PHRASES`) were moved from `extract/service.py` into typed config (`candidate_cleanup.*_noise_phrases` -> `pipeline_config.CANDIDATE_*_NOISE_PHRASES`); buy-box parsing heuristics (headings, required tokens, regex patterns, currency map) were moved from `extract/service.py` into `listing_extraction.*` config keys consumed via `pipeline_config.LISTING_BUY_BOX_*`; salary money matching in `extract/service.py` now derives symbols/codes from config (`pipeline_config.CURRENCY_SYMBOL_MAP`, `pipeline_config.CURRENCY_CODES`) instead of inline literals; `image_collection` field-type matching now consumes typed config (`candidate_cleanup.field_name_patterns.image_collection_tokens` -> `pipeline_config.CANDIDATE_IMAGE_COLLECTION_TOKENS`) instead of inline token tuples; inline category reject literals (`guest`, `max_discount`, `website`, `web site`) were folded into config (`candidate_cleanup.generic_category_values`) so `_coerce_category_field(...)` uses only config-backed sets; product-detail/spec parsing heuristics were de-hardcoded from `extract/service.py` into `listing_extraction.*` config (`product_detail_required_keys`, `product_detail_presence_any_keys`, list scan limit, `structured_spec_groups_key`, search depth, group/row limits) consumed via `pipeline_config.LISTING_*` constants; additional extraction cleanup literals (image noise tokens, image URL hint tokens, image dict key preference order, color CSS-noise tokens, size CSS-noise tokens, size package tokens, availability status token groups) now come from `candidate_cleanup.*` config via `pipeline_config.CANDIDATE_*` constants instead of inline tuples in `extract/service.py`; dynamic-field hard rejects, description source selectors, and URL tracking key/prefix filters are now config-driven (`candidate_cleanup.dynamic_field_name_hard_rejects`, `description_meta_selectors`, `description_fallback_content_selectors`, `tracking_param_exact_keys`, `tracking_param_prefixes`) consumed via `pipeline_config.CANDIDATE_*` constants; URL/asset filtering plus nested scan limits are now config-driven (`candidate_cleanup.candidate_url_allowed_schemes`, `candidate_url_absolute_prefixes`, `asset_file_extensions`, `image_file_extensions`, `deep_alias_list_scan_limit`, `nested_collection_scan_limit`) consumed via `pipeline_config.CANDIDATE_*` constants; product-detail payload/image fallback path keys are now config-driven (`listing_extraction.product_detail_image_source_keys`, `product_detail_top_level_payload_keys`, `product_detail_props_path`, `product_detail_product_blob_path`) consumed via `pipeline_config.LISTING_PRODUCT_DETAIL_*` constants; additional listing/detail helper literals are now config-driven (`buy_box_heading_scan_tags`, `description_candidate_fields`, `materials_and_care_section_labels`) with property-test timing stability hardened for extraction refactor checks (`test_extract_refactoring_properties.py:test_property_14_candidate_deduplication` now runs with `deadline=None` and `HealthCheck.too_slow` suppression); and remaining inline regex/token literals for dynamic-field parsing and value coercion are now config-driven (`dynamic_numeric_field_pattern`, `dynamic_field_name_pattern`, `color_variant_count_pattern`, `rating_word_tokens`, `analytics_dimension_token_pattern`, `alpha_char_pattern`) consumed via `pipeline_config.CANDIDATE_*` constants. Regression checks remain green (`pytest backend/tests/services/extract/test_extract.py backend/tests/services/extract/test_extract_refactoring_properties.py backend/tests/services/extract/test_listing_extractor.py -q`: `145 passed`).
  - **Source(s):** `audit_report.md` technical debt + blueprint + "If I owned this codebase".

- [ ] **Refactor `extract/service.py` complexity hotspots**
  - **Status:** `PARTIAL`
  - **Scope:** `extract_candidates`, `coerce_field_candidate_value`, regex-heavy sections, branch-shape cleanup, `_field_is_type` architecture verification.
  - **Verification:** `coerce_field_candidate_value` branch complexity reduced via `_dispatch_string_field_coercer(...)`; `_collect_candidates(...)` branch shape further reduced by extracting DOM/meta and semantic-target logic into dedicated helpers (`_collect_dom_and_meta_candidates`, `_is_semantic_requested_field`). Targeted extraction tests remain green (`pytest backend/tests/services/extract/test_extract.py backend/tests/services/extract/test_extract_refactoring_properties.py -q`: `78 passed`).
  - **Source(s):** `backend-pending-items.md`, `codeant-triage-2026-04-07.md`.

- [ ] **Refactor `extract/listing_extractor.py` complexity hotspots**
  - **Status:** `PARTIAL`
  - **Scope:** oversized nested decision blocks, regex simplification (S6035/S5869/S6397/S5843), confusing `elif` chains.
  - **Verification:** size parsing path extracted into `_extract_card_size(...)`; listing contract logic inside `_extract_listing_records_single_page(...)` now deduplicates through `_enforce_listing_field_contract(...)`, and `_extract_from_card(...)` branch complexity was reduced by extracting focused helper functions for ecommerce/job/card-title/image blocks. Listing extractor tests remain green (`pytest backend/tests/services/extract/test_listing_extractor.py -q`: `67 passed`). Broader regex-class cleanup (including S5843 family) remains pending.
  - **Source(s):** `backend-pending-items.md`, `codeant-triage-2026-04-07.md`.

- [ ] **Clarify listing merge-function debt vs prior “removed merge” expectation**
  - **Status:** `VERIFY`
  - **Why:** pending report notes mismatch between audit expectation and `listing_identity.py` merge helpers still present.
  - **Source(s):** `backend-pending-items.md`.

- [ ] **Refactor `crawl_service.py` orchestration complexity**
  - **Status:** `PARTIAL`
  - **Scope:** `process_run` complexity, page fallback/state transitions split, branch-shape cleanup.
  - **Verification:** `crawl_service.py` now delegates runtime dependency wiring through `_wire_runtime_dependencies()` and keeps `process_run` as a thin compatibility wrapper over `_batch_process_run`; control-operation handlers were cleaned up for consistent shape while preserving behavior. Full orchestration cleanup remains pending in batch runtime internals.
  - **Source(s):** `codeant-triage-2026-04-07.md`.

- [ ] **Remove duplicate traversal logic across acquisition modules**
  - **Status:** `PARTIAL`
  - **Why:** duplicate logic increases bug-fix surface.
  - **Verification:** shared traversal logic lives in `services/acquisition/traversal.py`, with browser-client wrappers now using a single centralized traversal config factory (`_traversal_config()`) instead of repeated inline config construction. Browser-client traversal coverage is green after compatibility updates to test doubles (`pytest backend/tests/services/acquisition/test_browser_client.py -q`: `35 passed`). Remaining duplication outside these paths is still pending.
  - **Source(s):** `audit_report.md` technical debt register.

---

## P2 - Exception handling overhaul (all points preserved)

- [ ] **Create unified crawler exception hierarchy**
  - **Status:** `PARTIAL`
  - **Scope:** add `CrawlerException`, `AcquisitionException`, `BrowserException`, `ExtractionException`, `AdapterException`.
  - **Verification:** hierarchy now includes base + specialized subclasses for browser/extraction/adapter paths, with active adoption in acquisition/run-control flows; wider propagation across all services remains pending.
  - **Source(s):** `EXCEPTION_HANDLING_PLAN.md`.

- [x] **Replace blanket `except Exception:` in high-priority acquisition files**
  - **Status:** `DONE`
  - **Verification:** current code search shows `browser_client.py:0` and `traversal.py:0`.
  - **Files from plan:**
    - `backend/app/services/acquisition/browser_client.py` (20+)
    - `backend/app/services/acquisition/traversal.py` (15+)
  - **Source(s):** `EXCEPTION_HANDLING_PLAN.md`.

- [x] **Replace blanket catches in adapters (medium-priority set)**
  - **Status:** `DONE`
  - **Files from plan:**
    - `backend/app/services/adapters/shopify.py`
    - `backend/app/services/adapters/saashr.py`
    - `backend/app/services/adapters/paycom.py`
    - `backend/app/services/adapters/oracle_hcm.py`
    - `backend/app/services/adapters/jibe.py`
    - `backend/app/services/adapters/icims.py`
    - `backend/app/services/adapters/greenhouse.py`
  - **Progress:** all files listed in this medium-priority set now updated to specific exception tuples.
  - **Source(s):** `EXCEPTION_HANDLING_PLAN.md`.

- [x] **Replace blanket catches in infra/low-priority set**
  - **Status:** `DONE`
  - **Files from plan:**
    - `backend/app/services/acquisition/host_memory.py`
    - `backend/app/services/acquisition/cookie_store.py`
    - `backend/app/services/dashboard_service.py`
    - `backend/app/services/crawl_state.py`
    - `backend/app/services/schema_service.py`
    - `backend/app/services/llm_integration/page_classifier.py`
  - **Progress:** blanket catches removed in all files with active catch sites; `crawl_state.py` currently has no `except Exception` site to refactor.
  - **Source(s):** `EXCEPTION_HANDLING_PLAN.md`.

- [ ] **Adopt specific exception classes in targeted paths**
  - **Status:** `PARTIAL`
  - **Scope:** Playwright (`TimeoutError`, `Error`), JSON (`JSONDecodeError`), HTTP (`HTTPError`, `TimeoutException`, `ConnectError`), file errors (`FileNotFoundError`, `PermissionError`, `OSError`).
  - **Verification:** blanket `except Exception` sites are now removed across `backend/app/services`; targeted runtime exceptions now inherit shared crawler base classes in acquisition/run-control flows, and selected API/infra handlers are narrowed to SQLAlchemy-focused catches. Follow-up remains for full domain-specific exception propagation.
  - **Source(s):** `EXCEPTION_HANDLING_PLAN.md`.

- [ ] **Exception handling validation checklist**
  - **Status:** `PARTIAL`
  - **Scope:** add exception-path tests, preserve stack traces, ensure actionable messages, update docs.
  - **Verification:** API/background regression tests now cover startup requeue DB exceptions, runtime failure-marking paths, and HTTP exception translation preserving both actionable details and original causes for create/create-csv plus conflict endpoints (delete/pause/resume/kill/cancel) ValueError paths; additional checklist coverage across more services remains.
  - **Source(s):** `EXCEPTION_HANDLING_PLAN.md`.

---

## P3 - Security and data-handling follow-ups

- [x] **Re-run dependency vulnerability scan**
  - **Status:** `DONE`
  - **Scope:** confirm `cryptography` and `python-multipart` findings remain cleared.
  - **Verification:** project-scoped `pip-audit` run over dependencies derived from `backend/pyproject.toml` returned no known vulnerabilities.
  - **Source(s):** `codeant-triage-2026-04-07.md`.

- [x] **Re-run secret scan**
  - **Status:** `DONE`
  - **Scope:** confirm sanitized proxy example no longer flagged; confirm no remaining non-test leaks.
  - **Verification:** `detect-secrets scan app tests` completed with no findings under configured exclusions.
  - **Source(s):** `codeant-triage-2026-04-07.md`.

- [x] **Add scrubber for captured network payload artifacts**
  - **Status:** `DONE`
  - **Why:** avoid persisting tokens/PII from intercepted payloads.
  - **Verification:** both artifact files and DB-persisted manifest traces now pass through the same scrubber before write, with regression coverage for redacting token/email-like values.
  - **Source(s):** `audit_report.md` security section.

- [x] **Harden LIKE search wildcard handling**
  - **Status:** `DONE`
  - **Why:** prevent broadening wildcard scope via user input patterns.
  - **Verification:** wildcard escaping is now applied consistently in both run URL search and user-email search paths, each using explicit SQL escape behavior with regression coverage.
  - **Source(s):** `audit_report.md` security snapshot.

---

## P4 - Reliability/observability/performance backlog

- [x] **Task-level absolute timeout wrappers for isolated URL tasks**
  - **Status:** `DONE`
  - **Why:** report flagged leaked tasks/hangs; code has watchdog logic but full path coverage should be validated.
  - **Verification:** both sequential and parallel isolated URL paths are now regression-covered in `backend/tests/services/test_crawl_service.py` (`test_process_run_honors_per_url_timeout_setting`, `test_process_run_honors_per_url_timeout_with_parallel_watchdog`), confirming timeout enforcement through `asyncio.wait_for` wrappers and watchdog failure marking.
  - **Source(s):** `audit_report.md` reliability section.

- [x] **Move high-volume crawl logs out of primary relational DB path**
  - **Status:** `DONE`
  - **Verification:** crawl events now always append to per-run JSONL files under configurable artifact path while DB persistence is bounded per run via `crawl_log_db_max_rows_per_run` (in addition to existing level/sampling controls), reducing sustained high-volume logging load on the relational path. Targeted crawl-events tests pass (`6 passed`).
  - **Source(s):** `audit_report.md` observability + 90-day plan.

- [x] **Add trace/correlation IDs to background/task logs**
  - **Status:** `DONE`
  - **Verification:** batch runtime background logs now include correlation prefixes, and missing run correlation IDs are persisted before processing; targeted tests added/passing.
  - **Source(s):** `audit_report.md`.

- [x] **Address proxy depletion behavior/backoff under running workloads**
  - **Status:** `DONE`
  - **Verification:** acquisition now tracks per-proxy failures and applies bounded cooldown before reuse, reducing repeated hammering of dead proxies while still probing one proxy when all are cooled down to prevent total stall.
  - **Source(s):** `audit_report.md`.

- [x] **Optimize heavy text/regex processing hot paths**
  - **Status:** `DONE`
  - **Verification:** prior listing/extract regex optimizations are now complemented by semantic/source-parser precompilation (`_PRICE_ONLY_TEXT_RE`, `_HEADING_TAG_RE`, `_PACK_KEY_RE`, `_NUMERIC_KEY_RE`, `_APOLLO_STATE_META_NAME_RE`) to avoid repeated runtime compilation in hot loops. Targeted suites pass (`pytest backend/tests/services/test_semantic_detail_extractor.py -q`: `10 passed`; `pytest backend/tests/services/extract/test_extract.py -q`: `71 passed`).
  - **Source(s):** `audit_report.md` performance section.

- [x] **Investigate/refactor semantic hotspot modules**
  - **Status:** `DONE`
  - **Scope:** `semantic_detail_extractor.py`, `extract/source_parsers.py` triage to determine true refactor need.
  - **Verification:** both hotspot modules received targeted runtime-cost reductions (compiled regex reuse in source parser and semantic extractor, including heading/spec/alpha checks); semantic coverage remains green (`pytest backend/tests/services/test_semantic_detail_extractor.py -q`: `10 passed`).
  - **Source(s):** `codeant-triage-2026-04-07.md`.

---

## P5 - Verification-only and report bookkeeping items

- [ ] **Re-run CodeAnt on current branch and refresh pending delta**
  - **Status:** `OPEN`
  - **Source(s):** `codeant-triage-2026-04-07.md`.

- [x] **Verify whether batch prefetch mode is resolved/renamed**
  - **Status:** `DONE`
  - **Verification (local):**
    - repo scan shows no `prefetch_mode`/batch-prefetch setting usage in runtime paths (`backend/app/services/_batch_runtime.py`, `backend/app/services/batch.py`);
    - current pipeline contract uses explicit `prefetched_acquisition` handoff in `_process_single_url(...)` (`backend/app/services/pipeline/core.py`) rather than a distinct prefetch mode flag.
  - **Source(s):** `backend-pending-items.md` (historical reference in this TODO; file currently absent in this branch).

- [x] **Verify `_field_is_type` design target (lookup table vs generic helper)**
  - **Status:** `DONE`
  - **Verification (local):**
    - `_field_is_type(...)` is now table-backed + helper-driven (`_FIELD_TYPE_TOKENS`, `_field_has_any_token`) in `backend/app/services/extract/service.py`, matching the intended direction;
    - targeted regression suites now pass in this refactor area (`pytest backend/tests/services/extract/test_extract.py backend/tests/services/extract/test_extract_refactoring_properties.py -q`: `78 passed`) after fixing title-candidate noise handling in `_dispatch` pipeline inputs.
  - **Source(s):** `backend-pending-items.md` (historical reference in this TODO; file currently absent in this branch).

- [ ] **Re-verify S5843 class findings after latest refactors**
  - **Status:** `PARTIAL`
  - **Verification (local only):**
    - targeted regex hotspot check in `backend/app/services/extract/listing_extractor.py` confirms current line-matching patterns are simple/bounded (`_match_line`, `_match_dimensions_line`) with no newly introduced nested-unbounded constructs in that section;
    - local regression signal is positive for listing extraction (`pytest backend/tests/services/extract/test_listing_extractor.py -q`: 63 passed);
    - CodeAnt/Sonar rule re-run was not performed locally in this pass, so S5843 closure remains pending external/static-rule confirmation.
  - **Source(s):** `backend-pending-items.md`, `codeant-triage-2026-04-07.md`.

- [ ] **Preserve explicit non-goals from triage when executing this TODO**
  - **Status:** `INFO`
  - **Scope:** no mass docstring generation, no test-style churn unless needed, no dead-code action without list, no frontend chasing unless re-flagged.
  - **Source(s):** `codeant-triage-2026-04-07.md`.

---

## Items explicitly marked as resolved/cleared in source docs (not TODO)

- `platform_resolver.py` deletion and crawl service modular split.
- core extraction hierarchy invariants (`first-match`) reported as holding.
- listing-detection-failed verdict behavior reported as implemented.
- artifact persistence and killed-run partial-output behavior reported as implemented.
- `soup.find_all(...)` warning called out as false positive in triage.

These are intentionally excluded from active TODOs to keep this list pending-only.

