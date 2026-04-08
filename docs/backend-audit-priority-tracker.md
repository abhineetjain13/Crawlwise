# Backend Audit Priority Tracker

Source: `audit_report.md` (2026-04-08)

## How to Use
- `Status`: `todo` | `in_progress` | `blocked` | `done`
- `Owner`: agent or engineer name
- Update this file in each PR to keep remediation state visible.

## P0 - Critical Reliability/Correctness

| ID | Status | Owner | Area | Problem | Action |
|---|---|---|---|---|---|
| P0-1 | done | codex | DB retries/state loss | `commit_with_retry` loses pending state after rollback on SQLite locks | Completed for this branch: runtime callsites were removed and `commit_with_retry` is hard-deprecated in `db_utils` (raises), with runtime flows migrated to `with_retry` unit-of-work mutations. |
| P0-2 | in_progress | codex | DB lock contention | SQLite write contention causes hangs/failures in worker + pipeline updates | Partially fixed: lock-safe retry mutation paths expanded in `_batch_runtime`; pipeline rescue writes avoid extra ad-hoc JSON rewrites; and summary patch persistence now short-circuits no-op updates to reduce stage/checkpoint write churn. Remaining contention risk persists in high-frequency SQLite write architecture. |
| P0-3 | done | codex | Browser resource usage | Browser process launched too often under concurrency | Completed in this branch: acquisition now reuses pooled browser processes (`browser_client` pool key/acquire path) while preserving context isolation per request. |
| P0-4 | done | codex | Background execution model | In-memory async task manager loses jobs on process restart | Completed in this branch: API-owned in-memory task orchestration was replaced by DB-backed lease claiming + heartbeat worker processing with stale-run recovery and contention coverage. |
| P0-5 | blocked | codex | Data store scalability | SQLite unsuitable for concurrent production workloads | Blocked in this pass: Postgres migration requires environment, migration plan, and rollout beyond safe localized patch |

## P1 - High Impact Bugs

| ID | Status | Owner | Area | Problem | Action |
|---|---|---|---|---|---|
| P1-1 | done | codex | `result_summary` race | Concurrent read-modify-write on JSON can clobber updates | Completed for current implementation: `_batch_runtime` uses merge-based summary patching plus per-run async serialization. Row-level `FOR UPDATE` is used only on non-SQLite databases; SQLite falls back to transactional retries without row-level locks because SQLite does not support `FOR UPDATE` semantics. |
| P1-2 | done | codex | Worker/API rescue paths | Failure-rescue blocks can fail under lock and leave run inconsistent | Completed for this branch: API background timeout/exception rescue now funnels through `_mark_run_failed_with_retry` and retries status + summary mutation together via `with_retry`; covered by `test_crawls_background.py`. |
| P1-3 | done | codex | URL task lifecycle | Batch URL tasks can stall indefinitely without hard watchdog | Done: added configurable per-URL watchdog (`settings.url_timeout_seconds`, clamped) and enforced it in sequential + parallel paths (task-level `wait_for` + batch wait timeout cancellation) |
| P1-4 | done | codex | Browser retry strategy | First profile failure shortens behavior for all subsequent profiles | Done: retry profile navigation shortening now scopes to failure reason (timeout/navigation errors only), not any first-profile failure. Also fixed traversal-mode normalization gap: `auto` is preserved when `advanced_enabled=true` (otherwise remains disabled), and `view_all` now maps to `load_more`. |
| P1-5 | done | codex | Orchestration coupling | Lazy imports/circular coupling between CRUD and orchestration | Completed in this pass: removed remaining lazy core import coupling in `pipeline/llm_integration.py` and `pipeline/trace_builders.py` by extracting shared review helpers into `pipeline/review_helpers.py` and importing directly from that module; `pipeline/core.py` now consumes the shared helpers without back-import loops. Added regression test `tests/services/pipeline/test_pipeline_coupling.py` to prevent reintroducing those lazy core imports. |

## P2 - Security Hardening

| ID | Status | Owner | Area | Problem | Action |
|---|---|---|---|---|---|
| P2-1 | done | Codex | SSRF/TOCTOU | DNS validation can diverge from request-time resolution | HTTP client now disables auto-redirects, revalidates each redirect target, and reapplies pinned DNS per hop |
| P2-2 | done | Codex | Captured payload privacy | Raw network payload storage may contain secrets/PII | Artifact network payload writer now scrubs sensitive keys/tokens/emails before disk persistence |
| P2-3 | done | Codex | Query safety | URL filter uses wildcard `like` without escaping | `list_runs` now escapes user `%`/`_`/`\` and uses SQL `LIKE ... ESCAPE '\'` |

## P3 - Observability/Operability

| ID | Status | Owner | Area | Problem | Action |
|---|---|---|---|---|---|
| P3-1 | done | codex | Logging architecture | DB log writes increase lock pressure and failure blast radius | Added dual-path logging (`stdout` + DB), log-level persistence gates, and URL-progress sampling controls to reduce SQLite write churn without breaking `/logs` UI. Browser diagnostics now also preserve traversal step summaries (`traversal_summary`) instead of dropping shared traversal stop-reason details. |
| P3-2 | in_progress | codex | Metrics/alerts | No operational SLO signals for lock/hang/failure patterns | Added runtime counters for DB lock errors/retries, browser launch failures, and proxy exhaustion; exposed `/api/dashboard/metrics` with runtime counters + run-duration signals. External alert wiring remains infra-level and intentionally pending. |
| P3-3 | done | codex | Traceability | Weak linkage between API request and background work | Added request correlation middleware (`X-Request-ID`), propagated run correlation IDs into `result_summary`, and prefixed crawl log messages with correlation IDs |

## P4 - Maintainability / Performance Debt

| ID | Status | Owner | Area | Problem | Action |
|---|---|---|---|---|---|
| P4-1 | todo |  | Config sprawl | Large monolithic pipeline config is hard to evolve | Move tunables/selectors into versioned external config with cached loader |
| P4-2 | done | codex | Duplicate traversal paths | Traversal behavior duplicated across modules | Completed: `browser_client` low-level traversal helpers now delegate to shared `acquisition/traversal.py` implementations (`collect_paginated_html`, next-page discovery/observation, pagination-state detection, scroll, load-more visibility/click), with compatibility fallbacks preserved via shared module hardening. |
| P4-3 | done | codex | CPU-heavy parsing | Large HTML cleanup/regex can block event loop | Completed in this pass: detail LLM discovered-source snapshot building now runs in a worker thread (`pipeline/core.py` offloads `_build_llm_discovered_sources(...)` via `asyncio.to_thread`), removing one of the last synchronous heavy `parse_page_sources` paths from the async runtime loop. Added verification in `tests/services/test_crawl_service.py::test_collect_detail_llm_suggestions_builds_discovered_sources_in_thread`. |

## Test Matrix Additions (Required)

| ID | Status | Owner | Test Gap | Required Coverage |
|---|---|---|---|---|
| T-1 | done | codex | DB lock behavior | Added focused `with_retry` unit tests plus a real SQLite file-backed two-session lock integration test that validates retry success after lock release (`test_db_utils.py`) |
| T-2 | done | codex | Concurrency correctness | Added multi-run concurrent crawl integration test using separate async sessions, asserting terminal status + summary consistency across concurrent `process_run` executions |
| T-3 | done | codex | Worker crash/recovery | Added startup recovery test for stale `running` runs and extracted deterministic recovery helper used by app lifespan |
| T-4 | done | codex | URL-level timeout safety | Added deterministic timeout test around single-URL processing path to verify failed terminal state and timeout error propagation |
| T-5 | blocked | codex | End-to-end smoke | Blocked for this slice: local HTTP server e2e coverage needs a dedicated async server fixture + browser/runtime orchestration; tracked for follow-up to avoid brittle CI behavior in this PR |
