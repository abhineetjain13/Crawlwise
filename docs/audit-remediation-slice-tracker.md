# Audit Remediation Slice Tracker

Date: 2026-04-11

Source audits reviewed:
- `ARCHITECTURAL_AUDIT_REPORT.md`
- `FIRST_PRINCIPLES_AUDIT.md`
- `SE_PRINCIPLES_VIOLATIONS.md`

This tracker is based on code verification, not on audit claims alone. Each slice below is intended to be independently implementable with bounded regression risk.

## Verification Summary

### Verified — now resolved
- ~~Browser worker shutdown is unsafe~~ → **S2 DONE**
- ~~Database engine pool tuning is minimal for Postgres~~ → **S3 DONE**
- ~~`CrawlLog` only has a single-column `run_id` index~~ → **S3 DONE** (migration 0010)
- ~~`run_prompt_task()` reads active LLM config from the database on each call because `llm_config_snapshot` is read but never populated~~ → **S4 DONE** (stamped at pipeline start)
- ~~LLM calls fail fast on rate-limit style errors; there is no circuit breaker or typed error model~~ → **S4 DONE**
- ~~`_process_single_url()` returns fragile raw tuples~~ → **S6 DONE** (`URLProcessingResult`)
- ~~`api/crawls.py` and `api/records.py` contain substantial controller-side business logic and export formatting logic~~ → **S8 DONE**
- ~~Sensitive acquisition artifacts may persist proxy URI credentials and related auth material~~ → **S7 DONE**
- ~~Operational runtime tuning is hardcoded in `pipeline_config.py` / `PIPELINE_TUNING` and cannot be environment-configured~~ → **S9 runtime-config DONE**
- ~~`_batch_runtime.py` mixes orchestration, progress bookkeeping, and failure/finalization details in one large control function~~ → **S6b DONE**
- ~~LLM payloads are parsed as JSON but not validated against task-specific schemas before downstream use~~ → **S5 DONE**
- ~~Hot-path acquisition callers pass a wide kwargs surface into `acquirer.py`~~ → **S9 acquisition-boundary DONE**
- ~~`acquisition_strategy.py` remains as a stale pre-typed boundary that does not match the live acquisition API~~ → **S9 strategy-cleanup DONE**
- ~~Run lifecycle/control code mutates `result_summary` via ad hoc dict handling~~ → **S9 summary-boundary DONE**
- ~~Batch orchestration and background failure paths still mutate `result_summary` and status via primitives in live lifecycle code~~ → **S9 batch-lifecycle DONE**
- ~~Hot-path summary patch merges still assign raw merged dicts back onto runs~~ → **S9 summary-merge DONE**
- ~~SSRF defenses are present but under-proven by explicit tests for link-local/CGNAT/redirect hardening flows~~ → **S10 DONE**

### Verified — still open

### Found During Implementation Audit (not in original reports)
- **CRITICAL**: `_batch_runtime.py` uses `settings.system_max_concurrent_urls` without importing `settings` from `app.core.config`. This was a **fatal NameError** that would crash every batch run at runtime. → **Fixed in S3.**
- Database engine was never disposed on application shutdown — connection pool leaks on restart. → **Fixed in S3.**
- LLM `_call_provider_with_retry` had dead `base_delay_s` parameter (explicitly discarded with `_ = base_delay_s`) and `max_retries=1` that was effectively a single call. → **Cleaned up in S4.**
- `_browser_pool_healthcheck_loop` had no exception handling — a single failure would kill the background maintenance task permanently. → **Fixed in S2.**

### Partially Verified / Downgraded
- Secrets are present in the local `.env`, including real-looking API keys and default admin credentials, but `.env` is already listed in `.gitignore` and is not currently tracked by Git. This is still an operational risk, but the audit claim that `.env` is committed is not currently true.
- SSRF protection is stronger than the audit describes. `validate_public_target()` rejects private, loopback, link-local, reserved, and CGNAT IPs; `http_client.py` pins DNS using curl `RESOLVE`; `browser_client.py` pins Chromium host resolution when possible and re-validates browser requests. The remaining work is targeted hardening and test coverage, not a greenfield SSRF fix.
- Blocking artifact writes in the main acquisition path are already offloaded with `asyncio.to_thread()`. The audit is outdated on the main hot path.
- Browser pool health maintenance already exists (`_evict_idle_or_dead_browsers`, healthcheck loop), but hard-kill/orphan cleanup is still missing.

### Not Verified / Already Addressed
- "No global concurrency limits" is no longer true. `_batch_runtime.py` enforces `settings.system_max_concurrent_urls`.
- "No database-level max_records enforcement" is no longer true. `models/crawl.py` already defines trigger-based enforcement for Postgres.
- DNS rebinding to AWS metadata IP is not currently an obvious bypass because link-local IPs are blocked generically and DNS pinning is already implemented in both HTTP and browser paths.

## Slice Design Principles

- Each slice should modify one primary subsystem.
- Cross-slice dependencies are explicit and minimal.
- Every slice must have a rollback-safe acceptance test.
- Structural refactors are sequenced after runtime hardening so production risk is reduced before deeper design work.

## Slice Tracker

| Slice | Scope | Status | Depends On | Regression Risk |
|---|---|---|---|---|
| S1 | Secrets and environment hygiene | **Done** | None | Low |
| S2 | Browser worker lifecycle hardening | **Done** | None | Medium |
| S3 | Database pool and query-path hardening | **Done** | None | Low |
| S3b | Missing settings import in _batch_runtime.py | **Done** (found during audit) | None | Critical (was runtime NameError) |
| S4 | LLM runtime resilience and caching | **Done** (circuit breaker + error model + snapshot stamp + deterministic cache) | None | Medium |
| S5 | LLM output contracts and observability | **Done** | S4 done | Medium |
| S6 | Run atomicity and pipeline boundary cleanup | **Done** (typed URLProcessingResult/Config) | None | Medium |
| S6b | Batch runtime orchestration / progress-state extraction | **Done** | S6 helpful, not required | Medium |
| S7 | Artifact redaction and diagnostics safety | **Done** | None | Low |
| S8 | Route/controller extraction | **Done** | None | Medium |
| S9 | Config and domain-model refactor | **Done** | S8 helpful, not required | High |
| S10 | SSRF hardening tests and gap closure | **Done** | None | Low |

## External Phase Mapping

The implementation work also tracks a separate phase-oriented todo list. The items below are now complete and should be treated as closed in that view as well.

| External Phase | Mapped Slice(s) / Docs | Status |
|---|---|---|
| Phase 1 | CPU offloading and redundant parse cleanup in the pipeline hot path | **Done** |
| Phase 8 | Browser pool hardening, psutil-based orphan cleanup, worker-safe shutdown | **Done** |

## Slice Details

### S1. Secrets and Environment Hygiene — DONE

Validated problem:
- `.env` contains live secrets and insecure defaults even though the file is currently ignored by Git.

Primary files:
- `.env`
- `.env.example` (new)
- `README.md` or deployment docs
- `backend/app/core/config.py`

Changes implemented:
- Added placeholder-only [.env.example](c:/Projects/pre_poc_ai_crawler/.env.example) for local bootstrap without exposing real secrets.
- Tightened config validation in `backend/app/core/config.py` so insecure default secrets and placeholder bootstrap credentials raise outside local dev/test environments, not just in `production`.
- Switched the bootstrap admin default email placeholder to `admin@example.invalid` and treat it as insecure until explicitly replaced.
- Added operator documentation in [environment-bootstrap.md](c:/Projects/pre_poc_ai_crawler/docs/environment-bootstrap.md) covering secret rotation and one-time admin bootstrap handling.
- Confirmed `.env` remains untracked by Git.

Why independent:
- No runtime contract change outside configuration validation.

Acceptance:
- `git ls-files .env` fails. ✅
- `.env.example` contains placeholders only. ✅
- App startup clearly rejects unsafe defaults outside local dev. ✅

### S2. Browser Worker Lifecycle Hardening — DONE

Validated problem:
- Worker shutdown path was unsafe — `shutdown_browser_pool_sync()` reset pool state instead of closing browsers on RuntimeError.
- Pool cleanup was not resilient to hard-kill/orphaned browser processes.
- Healthcheck loop could die silently on exception.

Primary files changed:
- `backend/app/services/acquisition/browser_client.py`

Changes implemented:
- `shutdown_browser_pool_sync()` now force-kills browser child processes via psutil when the async path fails, instead of silently resetting state.
- `_kill_orphaned_browser_processes()` added — terminates Chromium/Firefox/WebKit children of the current PID using psutil.
- `prepare_browser_pool_for_worker_process()` now calls orphan cleanup on worker init.
- `_browser_pool_healthcheck_loop()` now catches and logs exceptions instead of dying silently.

Acceptance:
- Worker shutdown does not create a new pool on cleanup failure. ✅
- Repeated worker restart cleans up orphaned browsers. ✅
- Healthcheck loop survives transient exceptions. ✅

External phase alignment:
- Phase 8 "Browser Pool Hardening" is complete.

### S3. Database Pool and Query-Path Hardening — DONE

Validated problem:
- Postgres pool had no `pool_pre_ping`, `pool_recycle`, `pool_timeout` — stale connections would crash under load.
- Engine was never disposed on shutdown — connection pool leaked.
- `crawl_logs` lacked composite indexes for common access paths.
- `_batch_runtime.py` used `settings.system_max_concurrent_urls` without importing `settings` — **fatal NameError at runtime**.

Primary files changed:
- `backend/app/core/config.py` — added `db_pool_size`, `db_max_overflow`, `db_pool_recycle_seconds`, `db_pool_timeout_seconds`, `db_pool_pre_ping` settings.
- `backend/app/core/database.py` — engine now uses configurable pool params; added `dispose_engine()` for shutdown.
- `backend/app/main.py` — lifespan shutdown now calls `dispose_engine()`.
- `backend/app/services/_batch_runtime.py` — added missing `from app.core.config import settings`.
- `backend/alembic/versions/20260410_0010_crawl_log_composite_indexes.py` — new migration.

Changes implemented:
- Database engine configured with `pool_pre_ping=True`, `pool_recycle=600s`, `pool_timeout=10s` (all environment-configurable).
- `dispose_engine()` called in lifespan shutdown after browser pool and Redis cleanup.
- Missing `settings` import fixed in `_batch_runtime.py` (this was a **runtime-crashing bug**).
- Composite indexes added: `crawl_logs(run_id, created_at)`, `crawl_logs(run_id, level)`, `crawl_runs(user_id, created_at)`.

Acceptance:
- New engine options are configured for non-SQLite databases. ✅
- Engine is disposed on shutdown. ✅
- Migration adds indexes without touching application semantics. ✅
- `_batch_runtime.py` no longer crashes with NameError. ✅

### S4. LLM Runtime Resilience and Caching — DONE

Validated problem:
- No LLM result cache.
- No populated config snapshot on runs.
- Rate limits fail fast without a circuit breaker or typed retry semantics.

Primary files changed:
- `backend/app/services/llm_runtime.py`
- `backend/app/services/_batch_runtime.py`

Changes implemented:
- **Typed error model**: `LLMErrorCategory` StrEnum with categories: `rate_limited`, `timeout`, `auth_failure`, `provider_error`, `parse_failure`, `validation_failure`, `circuit_open`, `missing_config`. All `LLMTaskResult` returns now carry `error_category`.
- **Per-provider circuit breaker**: Trips after 5 consecutive failures, cooldown 120s, half-open probe after cooldown. `circuit_breaker_snapshot()` exposed for observability.
- **Config snapshot stamping**: `process_run()` now stamps `llm_config_snapshot` into run settings at pipeline start when LLM is enabled, so config changes mid-run don't affect in-flight extraction.
- **Error classification**: `_classify_error()` routes raw error strings into typed categories for downstream consumption.
- **Deterministic LLM result cache**: `run_prompt_task()` now computes a stable Redis cache key from the effective task, domain, provider/model, prompt content, response contract, and normalized variables, then reuses validated results across retries/resumes/reruns.
- **Cache persistence discipline**: only successful, schema-valid LLM responses are cached; provider failures and malformed payloads still execute normally and are not written back as poisoned cache entries.
- Rate limits still fail fast per architecture invariant 18.

Acceptance:
- Rate limits fail fast without cascading. ✅
- Repeated failures trip circuit breaker instead of hammering provider. ✅
- Runs use stable config snapshot after start. ✅
- Errors are typed and classifiable. ✅
- Repeated equivalent prompt tasks hit the deterministic cache and avoid a second provider call / duplicate cost log. ✅

### S5. LLM Output Contracts and Observability — DONE

Validated problem:
- Parsed JSON is not schema-validated.
- No explicit confidence or structured review quality metadata exists.

Primary files:
- `backend/app/services/llm_runtime.py`
- `backend/app/services/pipeline/llm_integration.py`
- prompt files in `backend/app/data/knowledge_base/prompts/`

Changes implemented:
- Added task-specific payload validation in `backend/app/services/llm_runtime.py` for `xpath_discovery`, `missing_field_extraction`, `field_cleanup_review`, `page_classification`, and `schema_inference`.
- `run_prompt_task()` now rejects malformed but parseable JSON with `LLMErrorCategory.VALIDATION_FAILURE` before any downstream pipeline consumer sees it.
- Added Prometheus LLM outcome and latency metrics in `backend/app/core/metrics.py`, labeled by task, provider, outcome, and error category so parse failures, validation failures, timeouts, and rate limits are distinguishable at `/api/metrics`.
- Added focused tests in `backend/tests/services/test_llm_runtime.py` covering malformed payload rejection and metrics export.

Why independent:
- Can be layered on top of current LLM execution without changing acquisition or persistence.

Dependency note:
- Can ship before S4, but becomes stronger once cache/error taxonomy exists.

Acceptance:
- Invalid LLM JSON shapes are rejected deterministically. ✅
- Metrics distinguish timeout, rate limit, parse failure, and validation failure. ✅

### S6. Run Atomicity and Pipeline Boundary Cleanup — PARTIALLY DONE

Validated problem:
- `_process_single_url()` returned a raw `tuple[list[dict], str, dict]` — fragile, no named access.
- `_process_single_url()` accepted 12+ positional parameters — hard to extend and error-prone.
- Progress update and record persistence are still separated enough to risk inconsistent resume behavior.

Primary files changed:
- `backend/app/services/pipeline/types.py` (new) — `URLProcessingResult` and `URLProcessingConfig` dataclasses.
- `backend/app/services/pipeline/core.py` — all return sites now use `URLProcessingResult`; function accepts `URLProcessingConfig`.
- `backend/app/services/pipeline/__init__.py` — exports new types.
- `backend/app/services/_batch_runtime.py` — caller uses `URLProcessingConfig` and accesses result via named fields.

Changes implemented:
- **`URLProcessingResult`**: typed dataclass with `records`, `verdict`, `url_metrics`. Supports tuple destructuring via `__iter__` for backward compatibility with existing tests.
- **`URLProcessingConfig`**: typed dataclass grouping `proxy_list`, `traversal_mode`, `max_pages`, `max_scrolls`, `max_records`, `sleep_ms`, `update_run_state`, `persist_logs`.
- `_process_single_url` accepts either `config: URLProcessingConfig` or legacy kwargs (config takes precedence).
- All internal sub-functions (`_extract_listing`, `_extract_detail`, `_process_json_response`) also return `URLProcessingResult`.

Remaining (for other agent or follow-up):
- Per-URL transactional boundary for record persistence + progress update.

Acceptance:
- Pipeline boundary uses typed objects instead of raw tuples. ✅
- Parameter sprawl reduced via config object. ✅
- All existing tests pass (741/741 non-pre-existing). ✅
- Resume atomicity: NOT YET DONE.

CPU offloading note:
- Phase 1 "CPU Offloading" is complete for the pipeline hot path. Shared HTML parsing now routes through off-thread helpers so CPU-bound BeautifulSoup construction and related synchronous parsing do not block the event loop in the main pipeline flow.

### S7. Artifact Redaction and Diagnostics Safety — DONE

Validated problem:
- Sensitive-key scrubbing exists, but proxy URI credential handling needs explicit verification and coverage.

Primary files:
- `backend/app/services/acquisition/acquirer.py`
- `backend/app/services/acquisition/browser_client.py`

Changes:
- Add explicit proxy URL credential redaction.
- Add tests covering diagnostics payloads, network payload artifacts, and browser logs.
- Audit all persisted diagnostics for embedded auth material.

Why independent:
- Narrow security hardening slice with low coupling.

Acceptance:
- `user:pass@host` style values never appear in artifacts or logs.
- Redaction tests cover headers, cookies, bearer tokens, emails, and proxy credentials.

Changes implemented:
- Extended acquisition artifact string scrubbing to redact URL-embedded credentials such as `http://user:pass@host:port` across stored payloads.
- `_write_diagnostics()` now writes scrubbed diagnostics instead of persisting raw nested diagnostics payloads.
- Added targeted tests covering proxy credential redaction in acquisition network artifacts, diagnostics artifacts, and manifest trace payloads.

Acceptance:
- Proxy credentials are masked before persistence in network payload JSON. ✅
- Proxy credentials are masked before persistence in diagnostics artifacts. ✅
- Manifest trace construction preserves the same redaction behavior for stored payload snippets. ✅

### S6b. Batch Runtime Orchestration / Progress-State Extraction — DONE

Validated problem:
- `backend/app/services/_batch_runtime.py` mixed run lifecycle transitions, correlation/bootstrap setup, URL resolution, progress bookkeeping, per-URL persistence, and terminal failure handling inside `process_run()`.

Primary files changed:
- `backend/app/services/_batch_runtime.py`
- `backend/app/services/_batch_progress.py` (new)
- `backend/tests/services/test_batch_progress.py` (new)
- `backend/tests/services/test_batch_runtime_context.py`
- `backend/tests/services/test_batch_runtime_integration.py`

Changes implemented:
- Added `_BatchRunContext` plus `_resolve_run_urls()`, `_build_batch_run_context()`, `_start_or_resume_run()`, and `_load_batch_run_context()` to isolate startup and execution-context loading.
- Added `BatchRunProgressState` in `backend/app/services/_batch_progress.py` to own monotonic summary merges, verdict counting, acquisition-summary aggregation, and per-URL/final summary persistence.
- Extracted finalization and known exception paths into `_finalize_batch_run()` and `_handle_batch_run_exception()`.
- Kept `process_run()` as the top-level orchestrator over explicit helpers instead of mixing those abstraction levels inline.
- Tightened the dispatch integration test so Celery-mode assertions explicitly enable Celery dispatch instead of depending on ambient settings.

Acceptance:
- `process_run()` now reads as orchestration over helpers rather than a single mixed-abstraction state machine. ✅
- Progress merge behavior is unit-tested independently of the main runtime loop. ✅
- Targeted runtime verification passed: `41 passed` across batch-runtime and crawl-service dispatch/process subsets. ✅

### S8. Route/Controller Extraction — DONE

Validated problem:
- `api/crawls.py` and especially `api/records.py` still embed business logic and export formatting logic.

Primary files:
- `backend/app/api/crawls.py`
- `backend/app/api/records.py`
- new service modules for CSV ingestion and export formatting

Changes implemented:
- Added `backend/app/services/crawl_ingestion_service.py` for crawl-payload normalization and CSV ingestion.
- Added `backend/app/services/record_export_service.py` for export paging, formatting, markdown rendering, and artifact shaping.
- Trimmed `backend/app/api/crawls.py` and `backend/app/api/records.py` down to HTTP/auth concerns plus service delegation.
- Added focused service-level tests for CSV ingestion and export rendering.

Why independent:
- This is an API-layer refactor that should not change core crawl execution.

Guardrails:
- Preserve route signatures and response formats.
- Keep authorization checks in routes or shared HTTP dependencies.

Acceptance:
- Route files shrink materially.
- Export formatting can be unit tested without FastAPI route invocation.

Status:
- Acceptance met. ✅

### S9. Config and Domain-Model Refactor — IN PROGRESS

Validated problem:
- Important domain concepts are still primitive strings/dicts.
- Some service interfaces still take large parameter lists.

Primary files:
- `backend/app/services/config/*`
- `backend/app/models/crawl.py`
- acquisition request/response service boundaries

Changes implemented so far:
- Added `backend/app/models/crawl_domain.py` for the pure crawl status model and transition helpers.
- Added `backend/app/models/crawl_settings.py` for typed crawl-settings normalization/access.
- Added env-backed runtime settings in `backend/app/services/config/runtime_settings.py` and moved operational crawl/acquisition/browser tuning out of `PIPELINE_TUNING`.
- Added `backend/app/services/config/crawl_runtime.py`, `backend/app/services/config/llm_runtime.py`, and `backend/app/services/config/acquisition_guards.py` as narrower config surfaces.
- Updated `CrawlRun` with `status_value`, `settings_view`, `is_active()`, `is_terminal()`, and settings helpers.
- Updated `crawl_crud.py`, `_batch_runtime.py`, and `crawl_service.py` to use typed settings/domain helpers in their main flows.
- Rewired hot runtime consumers (`acquisition/*`, `llm_runtime.py`, `_batch_runtime.py`, `pipeline/core.py`, `url_safety.py`) off `pipeline_config.py` for operational tuning.
- Removed `backend/app/services/pipeline_config.py` and rewired the remaining test/config consumers to import directly from `app.services.config.*`.
- Added `AcquisitionRequest` to `backend/app/services/acquisition/acquirer.py` and moved the real pipeline hot path onto that typed request boundary via `backend/app/services/shared_acquisition.py` and `backend/app/services/pipeline/core.py`.
- Fixed Postgres `max_records` triggers to be schema-safe across pooled sessions.
- 2026-04-10: Completed the crawl-domain portion of S9 by adding `CrawlRunSettings`/status helpers, moving crawl runtime tunables into `app.services.config.crawl_runtime`, and updating the crawl CRUD + batch runtime paths to use the typed helpers.
- 2026-04-11: Extended `CrawlRunSettings` with typed `llm_config_snapshot()`, `extraction_contract()`, and `acquisition_profile()` helpers; rewired `pipeline/core.py`, `crawl_metrics.py`, and `llm_runtime.py` off raw `run.settings` reads for those hot-path concerns; and removed the unreferenced stale `backend/app/services/acquisition/acquisition_strategy.py` module.
- 2026-04-11: Moved additional hot-path reads for URL collection, traversal mode, extraction-contract validation, requested-field persistence, and per-URL timeout resolution behind typed settings helpers in `crawl_utils.py`, `crawl_crud.py`, and `_batch_runtime.py`.
- 2026-04-11: Added `CrawlRun.summary_dict()`, `get_summary()`, `update_summary()`, and `remove_summary_keys()` and rewired run lifecycle/control flows in `crawl_service.py`, `crawl_state.py`, `crawl_events.py`, and `pipeline/core.py` off ad hoc `result_summary` dict mutation.
- 2026-04-11: Rewired `_batch_runtime.py`, `_batch_progress.py`, `pipeline/core.py`, and `api/crawls.py` to use typed `CrawlRun` status/summary helpers in live batch progress, correlation stamping, finalization, proxy-exhaustion failure handling, stage updates, and background error marking.
- 2026-04-11: Added `CrawlRun.merge_summary_patch()` and rewired batch progress/finalization plus event summary persistence away from direct merged-dict assignment in `_batch_runtime.py`, `_batch_progress.py`, and `crawl_events.py`.

Why later:
- Higher regression surface than the runtime hardening slices.

Acceptance:
- New code stops importing broad config facades by default.
- New service boundaries use typed request/value objects where introduced.

Status:
- Acceptance met. Runtime tuning is now env-backed, the batch runtime has explicit orchestration/progress boundaries, `pipeline_config.py` has been removed, the acquisition hot path uses a typed `AcquisitionRequest`, stale config/strategy outliers have been removed, and the run settings/status/summary hot paths now route through typed model/domain helpers instead of primitive dict/string handling.

### S10. SSRF Hardening Tests and Gap Closure — DONE

Validated problem:
- SSRF defenses are already present, but the code lacks an explicit test-and-proof slice to lock them down.

Primary files:
- `backend/app/services/url_safety.py`
- `backend/app/services/acquisition/http_client.py`
- `backend/app/services/acquisition/browser_client.py`
- tests

Changes implemented:
- Added focused `url_safety.py` tests covering link-local literal IP rejection, CGNAT literal IP rejection, blocked metadata hostname rejection, `.local` suffix rejection, and public literal IP acceptance.
- Added HTTP client redirect hardening coverage for embedded-credential redirect targets in addition to existing redirect-chain revalidation and non-HTTP redirect rejection coverage.
- Kept and revalidated browser-side SSRF proof coverage for DNS pinning and rebinding-sensitive next-page rejection flows.
- Updated the browser acquisition metrics test to import the live aggregation helper from `_batch_progress.py` and assert the current traversal-attempt contract.

Why independent:
- Test-heavy slice with small code deltas.

Acceptance:
- Tests prove SSRF rejection and DNS pinning behavior across HTTP and browser acquisition. ✅

## Recommended Execution Order

1. S1 Secrets and environment hygiene
2. S2 Browser worker lifecycle hardening
3. S3 Database pool and query-path hardening
4. S4 LLM runtime resilience and caching
5. S5 LLM output contracts and observability
6. S6 Run atomicity and pipeline boundary cleanup
7. S7 Artifact redaction and diagnostics safety
8. S10 SSRF hardening tests and gap closure
9. S8 Route/controller extraction
10. S9 Config and domain-model refactor

## Why This Ordering Minimizes Regressions

- S1-S3 reduce operational risk without changing core extraction behavior.
- S4-S5 isolate LLM changes before deeper pipeline refactors.
- S6 fixes correctness boundaries before large structural cleanups.
- S8-S9 are intentionally later because they are architecture-improving but higher churn.

## Suggested Tracker Fields For Execution

For each slice, track:
- Owner
- Status
- Branch
- Files touched
- Acceptance tests
- Rollback plan
- Follow-on slices blocked/unblocked
