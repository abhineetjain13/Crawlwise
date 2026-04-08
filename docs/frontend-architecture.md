# Frontend Architecture

This document describes the current frontend implementation in `frontend/`.

## Overview

The frontend is a Next.js App Router app with:
- `AppShell` for authenticated workspace layout
- React Query for server-state
- typed API access via `frontend/lib/api`
- Crawl Studio split into config and run workspaces

Primary routes:
- `dashboard`, `crawl`, `runs`, `jobs`, `memory`, `selectors`
- `admin/users`, `admin/llm`
- `login`, `register`

## Structure

### `frontend/app`
- Route entrypoints and page composition.
- `frontend/app/crawl/page.tsx` switches between:
  - `CrawlConfigScreen` (no `run_id`)
  - `CrawlRunScreen` (`run_id` present)

### `frontend/components/layout`
- `app-shell.tsx` owns authenticated layout, session gating, sidebar/topbar.
- `PageHeader` values are projected into the shell top bar.

### `frontend/components/ui`
- `primitives.tsx`: low-level controls (`Button`, `Card`, `Input`, etc.)
- `patterns.tsx`: page-level patterns (`PageHeader`, `SectionHeader`, `InlineAlert`, `ProgressBar`, etc.)

### `frontend/components/crawl`
- `crawl-config-screen.tsx`: crawl submission UI + `buildDispatch(...)`
- `crawl-run-screen.tsx`: run workspace (progress, table/json/markdown/logs, actions)
- `shared.tsx`: crawl-specific shared components/helpers (`RecordsTable`, `LogTerminal`, form helpers)
- `use-run-polling.ts`: run status flags and one-shot terminal sync helper

## Crawl Contract in Frontend

The crawl config UI is contract-driven and deterministic:
- Crawl tab drives surface:
  - `category` -> `ecommerce_listing`
  - `pdp` -> `ecommerce_detail`
- No independent surface dropdown exists.

Modes:
- Category: `single`, `sitemap`, `bulk`
- PDP: `single`, `batch`, `csv`

Advanced traversal:
- UI modes: `auto`, `scroll`, `load_more`, `view_all`, `paginate`
- `view_all` is normalized to `load_more` before dispatch
- `auto` is preserved when advanced mode is enabled

Dispatch settings include:
- `llm_enabled`, `advanced_enabled`, `advanced_mode`
- `anti_bot_enabled`, `sleep_ms`
- `max_records`, `max_pages`, `max_scrolls`
- `proxy_enabled`, `proxy_list`
- `additional_fields`, `crawl_module`, `crawl_mode`
- `extraction_contract` from manual field rows

## Data Fetching and Realtime Model

React Query remains the baseline model, with status-aware fetching.

Run workspace behavior:
- Single scheduler cadence for active run refresh orchestration
- Terminal sync executes one final coordinated refetch
- Table tab uses progressive server pagination (`page` + `limit`)
- JSON tab uses bounded preview fetching
- Logs use incremental cursor fetching (`after_id`) and append/trim behavior
- WebSocket live-log stream:
  - endpoint: `/api/crawls/{run_id}/logs/ws`
  - frontend consumes stream when available
  - polling fallback remains active when socket is unavailable/disconnected

## Performance and UX Guards

- `RecordsTable` uses row-window virtualization to reduce DOM churn
- log viewport is capped to recent `MAX_LIVE_LOGS`
- expensive derivations are memoized
- stuck-run warning surfaces stale active-run state

## API Layer

`frontend/lib/api/index.ts` is the only shared API boundary for pages/components.

Notable API behavior:
- typed response contracts from `frontend/lib/api/types.ts`
- URL query helpers for paginated/cursored endpoints
- CSV crawl upload via `FormData`
- export downloads via blob endpoints (`downloadCsv/downloadJson/downloadMarkdown`)
- websocket base URL derived via `getApiWebSocketBaseUrl()`

## Invariants

- Authenticated workspace UI is owned by `AppShell`.
- `/crawl?run_id=<id>` is the canonical run workspace route.
- Crawl surface is derived from selected crawl tab, not inferred heuristics.
- Shared backend access goes through `frontend/lib/api/index.ts`.
- Shared server-state orchestration goes through React Query.
