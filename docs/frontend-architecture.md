# Frontend Architecture

This document describes the frontend as it exists in the current codebase. It is based on the implementation under `frontend/`, not on planned refactors.

## Overview

The frontend is a Next.js App Router application with a shared authenticated shell, React Query for server-state fetching, and a small shared UI layer for patterns and primitives.

Current route groups under `frontend/app/`:

- `dashboard`
- `crawl`
- `runs`
- `jobs`
- `memory`
- `selectors`
- `admin/users`
- `admin/llm`
- `login`
- `register`

## Top-Level Structure

### `frontend/app`

- Route entrypoints for the application.
- Most pages are page-local and fetch their own data with React Query.
- The crawl studio is currently implemented in a single page file: `frontend/app/crawl/page.tsx`.

### `frontend/components/layout`

- Contains the authenticated shell and top-bar coordination.
- `app-shell.tsx` owns:
  - auth/session gate via `api.me()`
  - desktop sidebar and mobile drawer navigation
  - sticky top header
  - shared page padding and max-width container

### `frontend/components/ui`

- Shared UI building blocks.
- `primitives.tsx` contains low-level reusable controls such as `Button`, `Card`, `Input`, `Textarea`, `Badge`, and `Toggle`.
- `patterns.tsx` contains higher-level composition helpers such as `PageHeader`, `SectionHeader`, `EmptyPanel`, `MetricGrid`, and `JsonPanel`.
- `query-provider.tsx` creates the shared React Query client.
- `theme-toggle.tsx` manages the light/dark theme toggle used in the shell.

### `frontend/lib`

- Shared non-visual frontend logic.
- `api/` contains the typed API client and request helpers.
- `constants/` contains shared limits, timing values, status sets, and storage keys.
- `utils.ts` contains generic helper utilities such as class-name merging.

## Application Shell

The root layout in `frontend/app/layout.tsx` is responsible for:

- loading global CSS
- registering the query provider
- wrapping all authenticated pages in `AppShell`
- setting up the theme boot script
- registering the Inter and JetBrains Mono fonts

`AppShell` is the main structural boundary for the product UI:

- auth routes (`/login`, `/register`) render without the workspace shell
- all other routes render inside the sidebar + top bar layout
- unauthorized API responses redirect to `/login`
- page headers are pushed into the top bar through `PageHeader` and the top-bar context

Layout spacing for workspace pages comes from `ShellContent`:

- main content wrapper: `px-4 py-4 lg:px-8 lg:py-5`
- centered content container: `max-w-[1440px]`

## Data Fetching Model

The app uses React Query through `frontend/components/ui/query-provider.tsx`.

Current default query behavior:

- `retry: 1`
- `staleTime: 5000`

Pages generally fetch directly from the shared API layer instead of using an additional frontend service layer.

## API Layer

`frontend/lib/api/index.ts` is the main client boundary between pages and the backend.

Key characteristics:

- all requests flow through `apiClient`
- endpoint responses are strongly typed via `frontend/lib/api/types.ts`
- paginated endpoints return `{ items, meta }`
- file upload for CSV crawl creation uses `FormData`
- export endpoints return URLs rather than fetching blobs inside React

Examples of current frontend API coverage:

- auth: `login`, `register`, `me`
- crawl operations: `createCrawl`, `createCsvCrawl`, `getCrawl`, `listCrawls`, `pauseCrawl`, `resumeCrawl`, `killCrawl`, `deleteCrawl`
- crawl outputs: `getRecords`, `getCrawlLogs`, `exportCsv`, `exportJson`
- review/selector flows: `getReview`, `saveReview`, `previewSelectors`, `suggestSelectors`, `testSelector`
- admin: user and LLM config endpoints

## Crawl Studio

The crawl studio is currently implemented in `frontend/app/crawl/page.tsx`.

It is intentionally monolithic right now because the previous component refactor was removed after regressions. If this page is split again later, the split should happen from the current working behavior, not from the deleted refactor.

### State Model

The page uses a small local phase model:

- `config`
- `running`
- `complete`

Phase is derived from a mix of:

- URL state via `run_id` or legacy `runId`
- fetched run status
- a short completion transition delay from `UI_DELAYS.PHASE_TRANSITION_MS`

Important current behavior:

- opening `/crawl?run_id=<id>` starts in a run-loading state instead of briefly rendering the config form
- completed runs show a loading state until records are available, which avoids a misleading empty-results flash
- `New Crawl` clears prior form state before navigating back to `/crawl`

### Crawl Inputs

The page supports:

- crawl surface: `category` or `pdp`
- category modes: `single`, `sitemap`, `bulk`
- PDP modes: `single`, `batch`, `csv`
- manual extra fields
- optional advanced settings
- optional proxy list
- preview-before-launch modal

Dispatch payload construction happens in `buildDispatch(config)`.

The current backend contract used by the active page is:

- `llm_enabled`
- `advanced_enabled`
- `sleep_ms`
- `max_records`
- `max_pages`
- `proxy_enabled`
- `proxy_list`
- `additional_fields`
- `crawl_module`
- `crawl_mode`

### Active Run View

When a run is active or paused, the page renders:

- progress summary
- run actions: pause, resume, hard kill
- filtered log stream

Polling behavior is status-aware:

- run details poll while status is active
- records and logs poll only while the latest run status is active
- review data only loads for terminal runs

Polling intervals come from `frontend/lib/constants/timing.ts`:

- active job: 2000 ms
- records: 2000 ms
- logs: 2000 ms

### Completed Run View

The completed workspace includes:

- metrics
- table output
- JSON output
- intelligence review
- logs
- CSV/JSON exports
- bulk-crawl-from-selected-records flow

The table currently fetches up to 1000 records in one request for the workspace view.

### Performance Constraints Implemented

These optimizations are present in the current code:

- log display is capped to the most recent `CRAWL_DEFAULTS.MAX_LIVE_LOGS` entries
- expensive derived values such as visible columns, selected records, filtered logs, and intelligence suggestions use `useMemo`
- polling is disabled automatically when a run is not active
- summary record count prefers `run.result_summary.record_count` when available, instead of depending only on loaded table rows

### URL and Session Handling

The crawl page currently supports:

- `run_id` and `runId` query param compatibility
- session-storage based bulk-crawl prefill through `STORAGE_KEYS.BULK_PREFILL`
- reset back to `/crawl` for a fresh configuration flow

## Shared UI Pattern

The UI layer follows a simple split:

- primitives are dumb, reusable controls
- patterns coordinate page-level composition and shell integration

One important pattern detail:

- `PageHeader` does not render visible markup itself
- it writes title, description, and actions into the shell top bar through context

That means page header spacing should be managed by the shell and page sections, not by local breadcrumb wrappers or duplicate top-of-page headers.

## Current Invariants

- The authenticated workspace layout is owned by `AppShell`.
- The active crawl experience lives in `frontend/app/crawl/page.tsx`.
- Crawl history opens runs by linking to `/crawl?run_id=<id>`.
- Shared server-state fetching should go through the React Query client.
- Shared backend access should go through `frontend/lib/api/index.ts`.
- New documentation should describe the current single-page crawl implementation unless a verified replacement lands in code.

## Notes For Future Refactors

If the crawl page is split again:

- preserve the current URL-driven run restoration behavior
- preserve `run_id` compatibility
- do not reintroduce stale form state when opening history/completed runs
- keep completed-run loading distinct from true empty results
- update this document only after the new structure is merged and in use
