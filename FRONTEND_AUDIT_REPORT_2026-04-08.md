# Frontend Audit Report (Exhaustive)

Scope: `frontend/` (Next.js App Router UI, crawl studio, runs, jobs, selectors, admin pages, API client and contracts).  
Date: 2026-04-08

---

## 1) EXECUTIVE SUMMARY

Health scores (0-10):
- Architecture: **6.0**
- Correctness: **5.4**
- Reliability: **5.3**
- Maintainability: **5.1**
- Security: **5.8**
- Test maturity: **2.1**

Top 5 existential risks (ranked):
1. Frontend has **no automated tests** configured (`frontend/package.json` has no test script/deps), so refactor regressions can ship undetected.
2. Crawl submission path mutates intent via URL heuristics (`components/crawl/crawl-config-screen.tsx:inferDispatchSurface`), conflicting with user-owned control behavior.
3. Wrong default crawl tab/mode is set to PDP (`crawl-config-screen.tsx` defaults), increasing incorrect-run risk from first interaction.
4. Advanced traversal contract is ambiguous at UI boundary (`advanced_mode: "auto"` sent as payload), risking backend mismatch/silent ignore.
5. API auth token is stored in `localStorage` (`lib/api/client.ts`), making token theft possible under XSS.

Top 5 strengths:
1. API boundary is centralized and typed (`lib/api/client.ts`, `lib/api/index.ts`, `lib/api/types.ts`).
2. UI feature grouping is clean and route-oriented (`app/*`, `components/crawl/*`, `components/layout/*`).
3. Live run UX is strong and operationally useful (`components/crawl/crawl-run-screen.tsx`).
4. React Query usage is consistent for server-state orchestration.
5. Legacy/deeplink redirects are in place for route continuity (`app/runs/[run_id]/page.tsx`, `app/crawl/*/page.tsx`).

Honest production readiness:
Frontend is usable and functionally rich, but currently high-risk after refactors because it lacks automated test coverage and contains several correctness drifts in crawl intent/dispatch behavior. This is not a styling problem; it is a control-contract and regression-detection problem. Production use is feasible only after P0 fixes and a minimum frontend test harness are in place.

---

## 2) ARCHITECTURE FINDINGS (Ranked by Severity)

### Finding A1
- Severity: **Critical**
- Confidence: **High**
- Category: **Reliability / Test-debt**
- Evidence: `frontend/package.json` (scripts only `dev/build/start/lint`, no `test`)
- Problem: no automated unit/integration/e2e test layer exists.
- Production impact: refactor regressions in crawl submission/status rendering are discovered late by users.
- Minimal fix: add `vitest` + `@testing-library/react` + `jsdom` + `msw`.
- Ideal fix: add test pyramid (unit + integration + Playwright smoke).
- Effort: **M**
- Regression risk if unchanged: **Critical**

### Finding A2
- Severity: **High**
- Confidence: **High**
- Category: **Correctness / Contract**
- Evidence: `frontend/components/crawl/crawl-config-screen.tsx:buildDispatch`, `inferDispatchSurface`, `looksLikeJobUrl`, `looksLikeEcommerceListingUrl`
- Problem: surface is inferred from URL heuristics instead of explicit user control.
- Production impact: user-selected mode can be silently remapped.
- Minimal fix: add explicit surface/page-type selector and pass through directly.
- Ideal fix: remove heuristic inference from dispatch path entirely.
- Effort: **M**
- Regression risk if unchanged: **High**

### Finding A3
- Severity: **High**
- Confidence: **High**
- Category: **Correctness**
- Evidence: `frontend/components/crawl/crawl-config-screen.tsx` line-level defaults (`requestedTab ?? "pdp"`)
- Problem: default workflow starts in PDP, not category.
- Production impact: high probability of wrong crawl mode on first run.
- Minimal fix: switch defaults/fallback to category.
- Ideal fix: align defaults with backend contract constants from shared typed config.
- Effort: **S**
- Regression risk if unchanged: **High**

### Finding A4
- Severity: **High**
- Confidence: **Medium**
- Category: **Traversal / Contract**
- Evidence: `crawl-config-screen.tsx` (`advancedMode` default `"auto"` and payload forwarding)
- Problem: frontend sends `"auto"` unconditionally when advanced enabled; backend handling drift can disable traversal unexpectedly.
- Production impact: traversal intent mismatch and hard-to-debug run outcomes.
- Minimal fix: explicit UI-to-API mode mapping (`auto` policy defined and documented).
- Ideal fix: shared enum contract with runtime validation.
- Effort: **S**
- Regression risk if unchanged: **High**

### Finding A5
- Severity: **Medium**
- Confidence: **High**
- Category: **Security**
- Evidence: `frontend/lib/api/client.ts:storeAccessToken`, `readAccessToken`
- Problem: access token persisted in `localStorage`.
- Production impact: XSS can exfiltrate API token.
- Minimal fix: prefer httpOnly cookie-only auth and stop localStorage persistence.
- Ideal fix: short-lived token + rotation + strict CSP + sanitization policy.
- Effort: **M**
- Regression risk if unchanged: **High**

### Finding A6
- Severity: **Medium**
- Confidence: **High**
- Category: **Performance / Reliability**
- Evidence: `frontend/components/crawl/crawl-run-screen.tsx` (four independent polling queries + terminal refetch sync block)
- Problem: polling fan-out can increase backend/API pressure and produce timing races.
- Production impact: noisy network usage, UI stutter, stale cross-panel state.
- Minimal fix: central run heartbeat query and derive dependent refetch cadence.
- Ideal fix: SSE/WebSocket events for run progress/log deltas.
- Effort: **M**
- Regression risk if unchanged: **Medium**

### Finding A7
- Severity: **Medium**
- Confidence: **High**
- Category: **Maintainability / Correctness**
- Evidence: `frontend/components/layout/app-shell.tsx` (`AppShell` and `ShellContent` both query `["me"]`)
- Problem: duplicated auth/session fetch behavior in shell layers.
- Production impact: redundant calls and conditional drift risk.
- Minimal fix: single ownership of session query in top shell.
- Ideal fix: auth/session provider with memoized role/claims.
- Effort: **S**
- Regression risk if unchanged: **Medium**

### Finding A8
- Severity: **Medium**
- Confidence: **High**
- Category: **Correctness / UX**
- Evidence: `frontend/components/crawl/crawl-run-screen.tsx` (`startMs` initialized before run hydrate)
- Problem: elapsed time can be wrong if run data arrives after local state init.
- Production impact: inaccurate duration display and misleading run diagnostics in UI.
- Minimal fix: derive start timestamp from `run.created_at` once available.
- Ideal fix: centralized run time model in shared helper.
- Effort: **S**
- Regression risk if unchanged: **Low-Medium**

---

## 3) SITE-SPECIFIC HACKS REGISTER

| ID | Location (file:function) | Domain/Pattern Matched | Classification | Risk | Consolidation Action |
|---|---|---|---|---|---|
| FH-001 | `components/crawl/crawl-config-screen.tsx:looksLikeJobUrl` | `dice.com`, `linkedin.com`, `indeed`, `greenhouse.io`, etc. | SMELL | surface inference can misclassify | replace with explicit user selection |
| FH-002 | `components/crawl/crawl-config-screen.tsx:looksLikeEcommerceListingUrl` | `/products`, `/collections`, query token hints | SMELL | URL pattern overlap and drift | remove heuristic dispatch routing |
| FH-003 | `app/crawl/*/page.tsx` redirects | legacy module/mode routes | JUSTIFIED | compatibility layer | keep with deprecation timeline |

Consolidation strategy:
- Move behavior to user-controlled UI state + strict typed payload.
- Keep redirects only for compatibility, not behavioral inference.
- Delete URL-heuristic surface classification in submission path.
- Order: introduce explicit surface control -> add tests -> remove heuristics.

---

## 4) SCHEMA POLLUTION TRACE REPORT (Frontend Contribution)

Frontend is not primary extractor, but it can amplify backend pollution by:
- blindly serializing/forwarding broad additional fields
- rendering polluted outputs without confidence markers
- lacking test guards around crawl config payload integrity

Pollution-adjacent risk points:

1) `title/category/brand/availability/color` display trust path  
- Source path: backend response -> `crawl-run-screen.tsx` table/json rendering (no frontend filtering by design).  
- Risk condition: polluted backend value rendered as authoritative without warning badge.  
- Minimal fix: add source-confidence/quality indicators in table cells where available from `source_trace`.  
- Ideal fix: explicit “quality/confidence” column + warnings for high-risk fields.  
- Priority: **P1**, Effort: **M**

2) Additional fields free-form input  
- Source path: `crawl-config-screen.tsx` (`AdditionalFieldInput`, `buildDispatch`)  
- Risk condition: noisy/unbounded additional fields raise backend extraction noise and UX confusion.  
- Minimal fix: field-name validation hints client-side (length, characters).  
- Ideal fix: share backend field-validation constraints in frontend schema.  
- Priority: **P2**, Effort: **S**

---

## 5) BROWSER TRAVERSAL MODE — BUG TRACE & FIX PLAN (Frontend)

### Paginated
- End-to-end status: **Partial**
- Evidence: mode option exists in `crawl-config-screen.tsx`; payload sends `advanced_mode`.
- Failure mode: mode contract not strongly typed/validated against backend runtime semantics.
- Minimal fix: add strict frontend enum mapping and submit validation.
- Ideal fix: shared contract package with runtime parser.
- Test case: select paginate, submit crawl, assert payload contains `advanced_enabled=true` and `advanced_mode="paginate"`.
- Priority: **P1**, Effort: **S**

### Infinite Scroll
- End-to-end status: **Partial**
- Evidence: mode option present (`scroll`) and sent.
- Failure mode: no frontend guard/test to ensure scroll mode survives config transformations.
- Minimal fix: unit tests around `buildDispatch` for scroll.
- Ideal fix: component tests validating form state -> payload.
- Test case: advanced enabled + scroll selected -> API call includes `scroll`.
- Priority: **P1**, Effort: **S**

### View All
- End-to-end status: **Broken as explicit UI option**
- Evidence: no explicit `"view_all"` option in mode dropdown.
- Failure mode: user cannot intentionally request `view_all`.
- Minimal fix: add `view_all` option with explicit mapping.
- Ideal fix: UI helper text explaining auto vs explicit mode precedence.
- Test case: selecting view_all sends expected canonical mode.
- Priority: **P0**, Effort: **S**

### Auto
- End-to-end status: **Ambiguous/Contract-risk**
- Evidence: default `"auto"` mode in UI; sent to API.
- Failure mode: depends on backend handling; no explicit contract enforcement in UI.
- Minimal fix: align with backend policy and add compatibility mapping.
- Ideal fix: backend-provided capabilities endpoint drives mode options.
- Priority: **P0**, Effort: **S**

---

## 6) BUG & DEFECT CANDIDATE LIST

| ID | P | Sev | File:Function | Symptom | Trigger | Root Cause | Fix | Test to Add | Status |
|---|---|---|---|---|---|---|---|---|---|
| FB-001 | P0 | High | `components/crawl/crawl-config-screen.tsx` | wrong initial mode | first visit | default tab set to PDP | default category | config init test | LIKELY BUG |
| FB-002 | P0 | High | `components/crawl/crawl-config-screen.tsx:inferDispatchSurface` | user intent rewritten | heuristic URL matching | inferred surface logic | explicit user-owned surface | dispatch contract tests | LIKELY BUG |
| FB-003 | P0 | High | `components/crawl/crawl-config-screen.tsx` | explicit view_all unavailable | advanced traversal usage | missing mode option | add option + mapping | traversal mode tests | LIKELY BUG |
| FB-004 | P1 | Med | `components/crawl/crawl-run-screen.tsx` | elapsed time drift | delayed run hydrate | static `startMs` initialization | derive from run created_at | duration render test | LIKELY BUG |
| FB-005 | P1 | Med | `components/layout/app-shell.tsx` | redundant auth queries | shell render | duplicate `["me"]` ownership | single session provider | shell session test | ARCH SMELL |
| FB-006 | P1 | Med | `lib/api/index.ts:commitSelectedFields` | silent legacy fallback | commit endpoint 404 | compatibility fallback masks drift | fail loudly / feature flag | api fallback unit test | ARCH SMELL |
| FB-007 | P1 | Med | `components/crawl/crawl-run-screen.tsx` | aggressive polling load | active run | multi-query intervals | consolidated polling/events | polling cadence test | ARCH SMELL |
| FB-008 | P1 | Med | `lib/api/client.ts` | token theft risk | XSS | localStorage token persistence | cookie auth | security integration check | LIKELY BUG |

---

## 7) CODE REDUCTION & SIMPLIFICATION BACKLOG

TODO-SIMP-FE-001: Unify status formatting and color mapping  
Priority: P1  
Effort: S  
Files affected: `app/dashboard/page.tsx`, `app/runs/page.tsx`, `app/jobs/page.tsx`  
What to remove/merge/collapse: duplicate `STATUS_CONFIG`/status helpers  
What to keep: one `lib/ui/status.ts` map + helpers  
Estimated LoC delta: ~-90  
Bug surface reduction: Medium  
Risk: low; validate badge text/tone parity

TODO-SIMP-FE-002: Remove duplicated domain/date helpers  
Priority: P2  
Effort: S  
Files affected: `app/dashboard/page.tsx`, `app/runs/page.tsx`, `app/admin/users/page.tsx`  
What to remove/merge/collapse: repeated `getDomain`, date formatters  
What to keep: `lib/format/*` helpers  
Estimated LoC delta: ~-60  
Bug surface reduction: Low-Medium  
Risk: low

TODO-SIMP-FE-003: Consolidate run polling orchestration  
Priority: P1  
Effort: M  
Files affected: `components/crawl/crawl-run-screen.tsx`  
What to remove/merge/collapse: repeated refetch cadence logic across queries  
What to keep: centralized run-state scheduler/hook  
Estimated LoC delta: ~-70  
Bug surface reduction: High  
Risk: medium; verify terminal-state sync

---

## 8) AGENT-EXECUTABLE REMEDIATION BACKLOG

### Implementation Status Update (2026-04-08)

Completed in this branch:
- `DONE` TODO-FE-001: Vitest + RTL + jsdom harness added (`test`, `test:watch`, `test:coverage`).
- `DONE` TODO-FE-002: default crawl mode is category single.
- `DONE` TODO-FE-003: removed surface inference from dispatch path; payload uses explicit user selection.
- `DONE` TODO-FE-004: explicit `view_all` option present and normalized to canonical `load_more`; `auto` is preserved when advanced traversal is enabled.
- `DONE` TODO-FE-005: frontend moved to cookie/session auth flow; localStorage token persistence removed.
- `DONE` TODO-FE-006: single `["me"]` query ownership in shell (no duplicate query in `ShellContent`).
- `DONE` TODO-FE-007: run polling orchestration extracted into `use-run-polling` with centralized terminal sync.
- `DONE` TODO-FE-008: elapsed-time source now derives from run timestamps with safe session fallback.

Completed:
- `DONE` TODO-FE-009: per-field quality indicators now render in results table headers.

Completed:
- `DONE` TODO-FE-010: Playwright smoke flow wired in CI (`.github/workflows/frontend-playwright-smoke.yml`) and verified locally.

### Reconciliation Snapshot (Latest)

All items tracked in `docs/frontend-audit-priority-tracker.md` are now marked `done`, including:
- observability events (`AUDIT-OBS-001/002/003`)
- performance items (`AUDIT-PERF-001/002`)
- realtime log updates (`AUDIT-REALTIME-001`)
- simplification and e2e reliability follow-ups (`TODO-SIMP-FE-003`, `TODO-FE-010`, `FTD-008`)

### P0 — Correctness / Traversal / Reliability

TODO-FE-001: Add frontend test harness and baseline critical tests  
Priority: P0  
Effort: M (2h-1d)  
Category: Reliability  
File(s): `frontend/package.json`, new `frontend/vitest.config.ts`, new test setup files  
Problem: no automated frontend tests exist; high refactor risk.  
Action:
1. Add Vitest + React Testing Library + jsdom + MSW.
2. Add scripts: `test`, `test:watch`, `test:coverage`.
3. Add first critical tests for crawl dispatch and API client retry/auth behavior.
Acceptance criteria: tests run in CI/local; baseline suite passes.  
Depends on: none

TODO-FE-002: Set default crawl mode to category single  
Priority: P0  
Effort: S (<2h)  
Category: Correctness  
File(s): `frontend/components/crawl/crawl-config-screen.tsx`  
Problem: default currently starts in PDP flow.  
Action:
1. Change initial `crawlTab`/fallback effect defaults to `category`.
2. Confirm query param sync reflects category default.
Acceptance criteria: fresh load defaults to `/crawl?module=category&mode=single`.  
Depends on: none

TODO-FE-003: Remove heuristic surface inference from dispatch  
Priority: P0  
Effort: M (2h-1d)  
Category: Correctness  
File(s): `frontend/components/crawl/crawl-config-screen.tsx`, potentially `frontend/lib/api/types.ts`  
Problem: URL heuristics mutate intended surface.  
Action:
1. Introduce explicit surface/page-type selector in UI.
2. Replace `inferDispatchSurface` in `buildDispatch` with direct user-selected surface.
3. Keep migration-safe default only for legacy routes (visible to user).
Acceptance criteria: submitted payload surface always equals explicit user selection.  
Depends on: TODO-FE-001

TODO-FE-004: Add explicit `view_all` traversal option and strict mode mapping  
Priority: P0  
Effort: S (<2h)  
Category: Traversal  
File(s): `frontend/components/crawl/crawl-config-screen.tsx`, `frontend/lib/api/types.ts`  
Problem: explicit `view_all` is unavailable and `auto` semantics are ambiguous.  
Action:
1. Extend `AdvancedCrawlMode` to include `view_all` (or canonical mapping token).
2. Update mode dropdown and payload serializer.
3. Add helper text clarifying `auto` vs explicit mode behavior.
Acceptance criteria: mode selection offers Auto/Scroll/Paginate/Load More/View All with deterministic payload.  
Depends on: TODO-FE-001

### P1 — Security / Performance / Maintainability

TODO-FE-005: Replace localStorage token persistence with cookie-only auth path  
Priority: P1  
Effort: M (2h-1d)  
Category: Security  
File(s): `frontend/lib/api/client.ts`, login/logout flow files  
Problem: token in `localStorage` is vulnerable to XSS exfiltration.  
Action:
1. Remove `storeAccessToken/readAccessToken` usage from request flow.
2. Use cookie/session-only auth via `credentials: include`.
3. Keep backward-compat migration step if needed.
Acceptance criteria: authenticated requests work without localStorage token; logout/session expiry behavior preserved.  
Depends on: none

TODO-FE-006: Consolidate auth query ownership in app shell  
Priority: P1  
Effort: S (<2h)  
Category: Simplification  
File(s): `frontend/components/layout/app-shell.tsx`  
Problem: duplicated `["me"]` query in `AppShell` and `ShellContent`.  
Action:
1. Keep query in one place and pass role/session state down.
2. Remove redundant query and duplicate unauthorized handling.
Acceptance criteria: one session query path; identical UI behavior.  
Depends on: TODO-FE-001

TODO-FE-007: Refactor run polling into a single orchestration hook  
Priority: P1  
Effort: M (2h-1d)  
Category: Performance  
File(s): `frontend/components/crawl/crawl-run-screen.tsx`, new `frontend/components/crawl/use-run-polling.ts`  
Problem: repeated interval/refetch logic across multiple queries.  
Action:
1. Implement hook that derives polling cadence from run state.
2. Centralize terminal sync refresh behavior.
3. Keep existing UI output identical.
Acceptance criteria: reduced duplicate refetch logic; no regression in live updates.  
Depends on: TODO-FE-001

TODO-FE-008: Fix elapsed-time source of truth in run screen  
Priority: P1  
Effort: S (<2h)  
Category: Correctness  
File(s): `frontend/components/crawl/crawl-run-screen.tsx`  
Problem: elapsed time can drift due to early state initialization.  
Action:
1. Derive start timestamp from run data when present.
2. Use local fallback only before run hydration.
Acceptance criteria: elapsed duration matches run timestamps during and after polling.  
Depends on: TODO-FE-001

### P2 — Debt / UX Hardening

TODO-FE-009: Surface field confidence indicators in results table  
Priority: P2  
Effort: M (2h-1d)  
Category: Schema  
File(s): `frontend/components/crawl/crawl-run-screen.tsx`, table components in `components/crawl/shared.tsx`  
Problem: polluted values are rendered without confidence context.  
Action:
1. Add optional confidence/source badges where `source_trace` provides metadata.
2. Highlight risky fields when source quality is low.
Acceptance criteria: operators can visually distinguish low-confidence values.  
Depends on: none

TODO-FE-010: Add Playwright smoke flow for core user journey  
Priority: P2  
Effort: M (2h-1d)  
Category: Reliability  
File(s): new `frontend/e2e/*`  
Problem: no browser-level regression net for critical flow.  
Action:
1. Add smoke test: login -> create crawl -> monitor run page -> view exports.
2. Run against local backend fixture/stub.
Acceptance criteria: basic journey passes in CI/local reliably.  
Depends on: TODO-FE-001

---

## 9) TECHNICAL DEBT REGISTER

| ID | Debt Item | Type | Daily Cost | Paydown Effort | Action | Priority |
|---|---|---|---|---|---|---|
| FTD-001 | No frontend tests | test-debt | High | M | add test stack + P0 tests | P0 |
| FTD-002 | Heuristic surface inference | hardcoded-hack | High | M | explicit user selection | P0 |
| FTD-003 | Wrong default mode | drift | Medium | S | default to category | P0 |
| FTD-004 | Traversal mode contract ambiguity | config-debt | High | S | strict enum mapping | P0 |
| FTD-005 | Token in localStorage | security-debt | Medium-High | M | cookie-only auth | P1 |
| FTD-006 | Duplicate auth query ownership | over-abstraction | Medium | S | single ownership | P1 |
| FTD-007 | Polling orchestration duplication | complexity | Medium | M | central polling hook | P1 |
| FTD-008 | Duplicate status/date/domain helpers | duplication | Low-Medium | S | shared formatter modules | P2 |

---

## 10) RELIABILITY & INCIDENT READINESS

Current hidden/silent failure modes:
- Crawl mode/surface drift from inferred dispatch can silently submit unintended runs.
- Traversal configuration can appear selected in UI but mismatch backend handling.
- No automated frontend regression checks for mission-critical user flow.

Observability gaps:
- No client-side telemetry hooks for crawl submission payload validation failures.
- No frontend alert on repeated polling/request errors by endpoint.

Top 10 production alerts/metrics to implement (frontend + API edge):
1. `crawl_submit_error_rate` by mode/surface.
2. `crawl_submit_surface_mismatch` counter (UI-selected vs payload sent).
3. `advanced_mode_selected_vs_effective` mismatch count.
4. `run_screen_poll_error_rate` by query (`run`, `records`, `logs`, `markdown`).
5. `api_client_fallback_base_url_usage` frequency.
6. `401_redirect_rate` from app shell.
7. `commit_selected_fields_fallback_path_usage` (if legacy fallback retained).
8. `json_render_payload_size` percentile in run screen.
9. `live_log_autoscroll_override_events` frequency.
10. `frontend_uncaught_error` grouped by route/component.

Browser leak/zombie concerns:
- No direct process-leak risk in frontend itself; primary risk is runaway polling and memory pressure on large JSON render paths.

Stuck-state detection gaps:
- UI relies on backend status transitions; no explicit “stuck run suspected” indicator based on unchanged progress/time.

---

## 11) SECURITY AUDIT SNAPSHOT

Findings:
- **Medium-High**: bearer token in `localStorage` (`lib/api/client.ts`) allows XSS token exfiltration.
- **Medium**: dynamic Markdown rendering is mostly safe (links sanitized via `isSafeHref`), but broader content hardening policy is not explicit.
- **Low-Medium**: fallback API base URL candidate switching can blur trust boundaries in local/dev misconfig cases.

Attack scenarios:
- Injected script reads `crawlerai-access-token` and replays authenticated API calls.
- Malicious content attempts to exploit rendered output context through unsanitized fields (currently mitigated for links, but still needs policy clarity).

Mitigations:
- Move auth to httpOnly cookies, remove localStorage token.
- Maintain strict CSP and review any `dangerouslySetInnerHTML` usage (none seen in audited files).
- Keep URL protocol allowlist checks (already present in markdown link render path).

Crawler-specific SSRF/path/injection note:
- Frontend largely forwards user URLs; backend SSRF controls remain primary guard.

---

## 12) PERFORMANCE & SCALABILITY AUDIT

Top bottlenecks:
- Multi-query polling in `crawl-run-screen.tsx`.
- Large record payload handling (`limit: 1000`) and full JSON stringify/render.
- Duplicate session query in shell.

Browser/renderer inefficiencies:
- Frequent re-renders from polling and derived memo computations.
- Log viewport sync logic can trigger extra UI churn.

Profiling plan:
1. React Profiler for `CrawlRunScreen` under active run.
2. Measure network requests/minute by query key.
3. Track paint/commit durations for JSON/table tabs at 100/500/1000 records.
4. Measure memory growth during 10+ minute live run.

Optimization ROI ranking:
1. Consolidated polling hook or SSE (high ROI).
2. Incremental/virtualized table render for large records (high ROI).
3. Avoid full JSON stringify on every render (medium ROI).
4. Remove duplicate auth query and repeated helper logic (medium ROI).

---

## 13) TEST COVERAGE GAP ANALYSIS

Highest-risk untested paths:

1) Crawl dispatch builder path  
- Why high risk: directly controls run type/surface/settings.  
- Test type: unit + component.  
- Case: category single + advanced auto + proxy list -> expected payload shape and values.  
- Priority: **P0**

2) Traversal mode selection contract  
- Why high risk: user-visible mode with backend-sensitive semantics.  
- Test type: unit.  
- Case: explicit `paginate`/`scroll`/`view_all` and `auto` mapping behavior.  
- Priority: **P0**

3) API client retry/auth/fallback behavior  
- Why high risk: all network IO depends on this.  
- Test type: unit (MSW).  
- Case: 401 clears auth; 5xx retries exponential; 404 behavior with configured base URL.  
- Priority: **P0**

4) App shell auth gating and admin reset behavior  
- Why high risk: entry control and destructive action controls.  
- Test type: component integration.  
- Case: unauthorized redirects; non-admin reset blocked; admin reset path calls API once.  
- Priority: **P1**

5) Run screen polling + terminal sync behavior  
- Why high risk: high-traffic screen with concurrency/timing complexity.  
- Test type: integration.  
- Case: active->terminal transition triggers final synchronized refetch exactly once.  
- Priority: **P1**

---

## 14) "IF I OWNED THIS CODEBASE" — TOP 12 ACTIONS

1. Add test harness and write 10 P0 tests around dispatch/API client first.
2. Fix default crawl mode to category.
3. Remove URL-based surface inference and make it explicit user-controlled.
4. Add explicit traversal mode matrix including `view_all`.
5. Align `auto` semantics to backend contract and document it in UI copy.
6. Move away from localStorage token persistence.
7. Consolidate auth query ownership in shell.
8. Refactor run polling into a dedicated hook.
9. Add large-record rendering safeguards (virtualization/chunking).
10. Centralize status/date/domain helper utilities.
11. Add frontend telemetry for crawl submission and polling failures.
12. Add Playwright smoke test for main happy path.

What I would not touch yet:
- Broad visual redesign; correctness/contract and test safety are higher leverage now.

---

## 15) CLARIFYING QUESTIONS

1. Should `surface` be an explicit user-controlled UI field (required), or inferred only as a temporary fallback? u can add surface in the UI as well with auto detect as default this will allow user to guide the app and reduce schema pollution
2. For advanced traversal, is `view_all` a distinct API mode or an alias to `load_more`? view all and show all is differn than load more logically right from a site perspective? 
3. Should frontend ever submit `advanced_mode="auto"` literally, or normalize it before send? auto means auto detect when user toggles on from UI
4. Is bearer token storage in `localStorage` acceptable in your threat model, or should frontend move to cookie-only auth now?
5. Do you want SSE/WebSocket for run updates now, or keep polling and just harden cadence? i want websocket but previous implementation failed so implement as last prioity
6. Should run table default row limit remain high (1000), or become progressive/virtualized? progressive
7. Do you want hard validation on additional field names in UI (matching backend constraints) before submit? yes the names should make sense so that typing errors can be avoided 
8. Can we remove legacy `commitSelectedFields` fallback to old endpoint, or must it stay temporarily? remove

