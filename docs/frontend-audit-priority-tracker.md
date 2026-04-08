# Frontend Audit Priority Tracker

Source: `FRONTEND_AUDIT_REPORT_2026-04-08.md`

## How to Use
- `Status`: `todo` | `in_progress` | `blocked` | `done`
- Update this file in each frontend PR so remediation progress stays visible.

## P0 - Correctness / Traversal / Reliability

| ID | Status | Area | Problem | Action |
|---|---|---|---|---|
| FE-P0-1 | done | Test harness | No frontend test baseline | Added Vitest + RTL + jsdom + scripts (`test`, `test:watch`, `test:coverage`) |
| FE-P0-2 | done | Crawl defaults | Wrong default mode risk | Defaulted crawl flow to category/single |
| FE-P0-3 | done | Surface control | Surface was inferred/mutable | Surface is now deterministic from crawl tab (`category` -> listing, `pdp` -> detail); no independent surface selector |
| FE-P0-4 | done | Traversal contract | `view_all`/`auto` ambiguity | Added explicit `view_all`, maps to `load_more`; preserves `auto` when advanced is enabled |
| FE-P0-5 | done | Dispatch correctness | Manual field editor input was not sent to backend | `buildDispatch` now serializes validated manual rows into `settings.extraction_contract` |
| FE-P0-6 | done | Submit reliability | Rapid submit could create duplicate runs | Added in-flight submit guard and disabled submit while request is pending |
| FE-P0-7 | done | Module/surface race | Surface sync used route state and could drift from active tab | Removed independent surface state; payload surface is derived directly from active `crawlTab` |

## P1 - Security / Performance / Maintainability

| ID | Status | Area | Problem | Action |
|---|---|---|---|---|
| FE-P1-1 | done | Auth security | Token in localStorage | Removed localStorage auth persistence, uses cookie/session flow |
| FE-P1-2 | done | Shell query ownership | Duplicate `["me"]` fetch | Consolidated session query ownership in `AppShell` |
| FE-P1-3 | done | Run polling | Duplicate polling orchestration | Added `use-run-polling` and centralized terminal sync behavior |
| FE-P1-4 | done | Duration correctness | Elapsed time drift | Start time derives from run timestamps with safe fallback |
| FE-P1-5 | done | API contract cleanup | Legacy `llm-commit` client ambiguity | Frontend commit flow standardized on `commit-fields` path |
| FE-P1-6 | done | Run-screen payload pressure | Records fetched/evaluated too broadly | Scoped records fetching to active table/json tabs, reduced fetch ceiling, and added progressive JSON preview loading |
| FE-P1-7 | done | Run-screen pagination UX bug | Load More could persist forever after hitting preview cap | Added cap-aware load-more logic and clear capped-preview warning banners |

## P2 - Debt / UX Hardening

| ID | Status | Area | Problem | Action |
|---|---|---|---|---|
| FE-P2-1 | done | Result quality UX | No per-field confidence signal | Added per-field quality indicators in results table headers |
| FE-P2-2 | done | E2E reliability | No browser smoke flow | Added Playwright smoke scaffolding + CI workflow wiring (`.github/workflows/frontend-playwright-smoke.yml`) and confirmed local smoke execution |
| FE-P2-3 | done | UI consistency | Repeated inline error styles across pages | Added shared `InlineAlert` pattern and migrated run/jobs/runs/admin views |
| FE-P2-4 | done | Status consistency | Dashboard had local status color drift | Centralized dashboard status bar/dot color helpers in `lib/ui/status.ts` |
| FE-P2-5 | done | Run observability UX | No frontend signal for potentially stuck active runs | Added passive stuck-run warning banner in run screen based on stale run updates |

## Pending Items Carried From Audit Report

| ID | Status | Area | Problem | Action |
|---|---|---|---|---|
| TODO-FE-010 | done | Reliability | No browser-level regression net for core flow | Added CI smoke workflow + executed local Playwright smoke successfully |
| TODO-SIMP-FE-003 | done | Maintainability / Performance | Run screen still has split refetch cadence across run/records/logs/markdown | Collapsed to a single live scheduler tick for run/records/logs/markdown refetch with terminal sync retained |
| FTD-008 | done | Duplication debt | Duplicate formatter/presentation helpers still partially distributed | Consolidated status/date/domain/progress helpers; progress rendering now uses shared `ProgressBar` in `components/ui/patterns.tsx` |
| AUDIT-OBS-001 | done | Observability | No telemetry for crawl submit payload/validation failures | Added `crawl_submit_error_rate` + mode/surface/config tags from submit dispatch path |
| AUDIT-OBS-002 | done | Observability | No telemetry for polling failures by panel | Added deduped `run_screen_poll_error_rate` events for `run`, `records`, `logs`, `markdown` panels |
| AUDIT-OBS-003 | done | Observability | No counter for UI-selected vs payload-sent mismatches | Added `crawl_submit_surface_mismatch` and `advanced_mode_selected_vs_effective` submit instrumentation |
| AUDIT-PERF-001 | done | Performance | Large result sets still rely on non-virtualized table rendering | Added progressive server pagination for table tab and row virtualization windowing in `RecordsTable` |
| AUDIT-PERF-002 | done | Performance | Live logs can still cause heavy refresh churn on long runs | Added cursor-based incremental log fetching (`after_id` + bounded `limit`) and run-screen append/trim behavior |
| AUDIT-REALTIME-001 | done | Realtime updates | Polling-only model remains default for live run updates | Added websocket live-log stream with polling fallback (`/api/crawls/{run_id}/logs/ws`) |

## Recent Validation Snapshot
- Frontend tests: passing (`14/14` targeted Vitest for crawl run screen/shared + config dispatch)
- Playwright smoke: passing (`1/1`, local Chromium)
- Targeted lint checks: clean on updated files
