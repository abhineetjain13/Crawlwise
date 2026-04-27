# Frontend Architecture

> Last updated: 2026-04-20

This document describes the live frontend structure, what it actually calls in the backend, and the remaining client/backend drift that should stay visible.

## 1. Stack and Role

Frontend is a Next.js App Router UI for:

- auth/session handling
- crawl configuration and launch
- run monitoring and record inspection
- selectors workflow
- dashboard/history/jobs operations
- admin users and LLM configuration

Key client libraries:

- Next.js App Router
- React Query
- Lucide icons
- React Markdown

## 2. Route Map

App routes under `frontend/app`:

- `/` -> redirect-style entry page
- `/login`
- `/register`
- `/dashboard`
- `/crawl`
- `/crawl/category`
- `/crawl/pdp`
- `/crawl/bulk`
- `/runs`
- `/runs/[run_id]`
- `/jobs`
- `/selectors`
- `/selectors/manage`
- `/admin/users`
- `/admin/llm`

Important route behavior:

- `/crawl` switches between config mode and run workspace based on `run_id`
- `/crawl/category`, `/crawl/pdp`, and `/crawl/bulk` are route shims into `/crawl?...`
- `/runs/[run_id]` routes back into the crawl workspace

## 3. Main Frontend Subsystems

### 3.1 App shell and auth

Primary files:

- `components/layout/app-shell.tsx`
- `components/layout/app-shell.module.css`
- `components/layout/auth-shell.module.css`
- `components/layout/auth-session-query.ts`
- `components/layout/top-bar-context.tsx`
- `app/layout.tsx`
- `components/ui/patterns.tsx` for shared operator-page section shells used across non-crawl app surfaces

Responsibilities:

- session gating
- shell layout and nav
- auth-route vs app-route split
- header state
- theme toggle and common shell framing

### 3.2 API contract layer

Primary files:

- `lib/api/client.ts`
- `lib/api/index.ts`
- `lib/api/types.ts`

Responsibilities:

- all backend HTTP calls
- API typing
- auth-aware fetch wrapper
- URL helpers for review HTML and selector preview HTML

This layer is the frontend/backend contract chokepoint.

### 3.3 Crawl config and dispatch

Primary files:

- `components/crawl/crawl-config-screen.tsx`
- `components/crawl/crawl.module.css`
- `components/crawl/shared.tsx`
- `lib/constants/crawl-defaults.ts`

Responsibilities:

- choose module/domain/mode
- derive surface from domain + module
- build dispatch payload
- collect advanced settings and additional fields
- submit crawl or CSV run

Current UI settings behavior reflects the backend contract:

- `advanced_enabled`
- `advanced_mode`
- `request_delay_ms`
- `max_records` as a target count for stopping after a page, not a strict row cap
- `respect_robots_txt`
- proxy input
- additional fields
- additional fields are dispatched as the operator typed them (trimmed/deduped only); the UI no longer rewrites labels like `Features & Benefits` into snake_case before the backend sees them

### 3.4 Run workspace

Primary files:

- `components/crawl/crawl-run-screen.tsx`
- `components/crawl/use-run-polling.ts`
- `components/crawl/shared.tsx`

Responsibilities:

- poll run state while active
- show records, JSON, markdown, and logs
- consume websocket logs when available
- show quality/verdict/progress signals
- expose pause/resume/kill and export actions

Important live data features:

- run records use cleaned `data`, `review_bucket`, and `source_trace`
- provenance API is typed and available through `getRecordProvenance`
- log websocket fallback is built into the screen

### 3.5 Operator surfaces

Primary files:

- `app/dashboard/page.tsx`
- `app/runs/page.tsx`
- `app/jobs/page.tsx`
- `app/selectors/page.tsx`
- `app/admin/users/page.tsx`
- `app/admin/llm/page.tsx`

Responsibilities:

- dashboard metrics and recent runs
- run history
- active jobs view
- selector picker/test/save workflow
- domain-memory management across domains and surfaces
- admin user management
- LLM provider/config/cost-log management

### 3.6 UI ownership and style policy

Primary files:

- `components/ui/button.tsx`, `badge.tsx`, `input.tsx`, `card.tsx`, `metric.tsx`, `table.tsx`, `alert.tsx`, and `dialog.tsx` for typed primitive owners
- `components/ui/primitives.tsx` as the compatibility barrel plus dropdown, toggle, tooltip, skeleton, and field helpers
- `components/ui/patterns.tsx` for shared operator-page patterns
- `components/ui/table.module.css` for compact and commerce table styling
- `app/product-intelligence/product-intelligence-components.tsx` for Product Intelligence local UI pieces

Global CSS policy:

- `app/globals.css` owns tokens, reset, shared browser defaults, animations, and cross-feature utilities only.
- App/auth shell CSS lives under `components/layout/`.
- Crawl Studio feature CSS lives under `components/crawl/`.
- Table CSS lives under `components/ui/table.module.css`.
- New JSX should use semantic Tailwind tokens such as `bg-background`, `text-muted`, `border-border`, and `shadow-card`. Raw `bg-[var(--...)]`, `text-[var(--...)]`, `border-[var(--...)]`, and `shadow-[var(--...)]` escapes are blocked by `frontend/scripts/check-token-escapes.mjs`.

## 4. Live Backend API Usage

The frontend currently uses live backend routes for:

- auth: `/api/auth/*`
- dashboard: `/api/dashboard`
- crawls: `/api/crawls/*`
- records: `/api/crawls/{id}/records`
- provenance: `/api/records/{id}/provenance`
- exports: `/api/crawls/{id}/export/*`
- logs + websocket: `/api/crawls/{id}/logs`, `/api/crawls/{id}/logs/ws`
- review: `/api/review/{id}`, `/api/review/{id}/artifact-html`, `/api/review/{id}/save`
- selectors: `/api/selectors`, `/api/selectors/suggest`, `/api/selectors/test`, `/api/selectors/preview-html`
- users: `/api/users`
- llm: `/api/llm/providers`, `/api/llm/configs`, `/api/llm/test-connection`, `/api/llm/cost-log`
- jobs: `/api/jobs/active`

## 5. Known Client/Backend Drift

There is still some API-surface drift and it should remain documented:

- `frontend/lib/api/index.ts` exposes `previewSelectors()` for `/api/review/{run_id}/selector-preview`, but that backend route does not exist.
- `ReviewPayload` types in the frontend still include `selector_memory` and `selector_suggestions`, while the current backend review response is centered on run, canonical/discovered fields, mapping, and records.
- The main selector UX is no longer LLM-first on `/selectors`; older docs claiming “selectors page missing backend integration” are stale.

## 6. Current Data Contracts That Matter To Frontend

### CrawlRun

The frontend expects:

- `status`
- `surface`
- `settings`
- `requested_fields`
- `result_summary`

### CrawlRecord

The frontend expects:

- `data`
- `raw_data`
- `discovered_data`
- `source_trace`
- optional `review_bucket`
- optional `provenance_available`

### Provenance

The frontend has a typed provenance object:

- `raw_data`
- `discovered_data`
- `source_trace`
- `manifest_trace`
- `raw_html_path`

### Selectors

The selectors UI is built on:

- selector CRUD records, now queryable across all surfaces for a domain when `surface` is omitted
- preview HTML loaded into a same-origin iframe so the selector tool can compute XPath directly from the loaded DOM
- manual test response with count and matched value
- optional LLM suggestion flow from Crawl Studio field configuration, not from the selector tool page
- a dedicated `/selectors/manage` domain-memory surface for edit/delete/toggle operations

### LLM Admin

The admin LLM UI is built on:

- provider catalog
- config CRUD
- connection tests
- cost log listing

## 7. Testing Surface

Frontend tests currently cover:

- auth session query
- API client behavior
- crawl config screen
- selector helper logic
- crawl run screen
- shared crawl helpers
- run polling

There is also Playwright e2e coverage under `frontend/e2e`.

## 8. Architectural Notes

- The frontend is intentionally thin on domain logic; the backend owns crawl semantics.
- `lib/api/index.ts` should remain the single access layer for backend calls.
- `components/crawl/shared.tsx` is a real shared hub and should not quietly become a second application framework.
- `components/ui/patterns.tsx` now owns the shared operator-page section framing (`SectionCard`, `SurfaceSection`, `MutedPanelMessage`) so dashboard/admin/tool pages do not hand-roll their own section chrome.
- `components/ui/dialog.tsx` owns destructive confirmations; browser `alert()` and `confirm()` are not used in app/components code.
- `components/ui/table.module.css` owns compact and commerce table styling while table call sites keep grep-friendly class names during migration.
- When backend record contracts change, update `lib/api/types.ts` and this doc together.

## 9. Companion Docs

- [../AGENTS.md](../AGENTS.md)
- [backend-architecture.md](backend-architecture.md)
- [ENGINEERING_STRATEGY.md](ENGINEERING_STRATEGY.md)
- [INVARIANTS.md](INVARIANTS.md)
