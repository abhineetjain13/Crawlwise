# Frontend Architecture

> **Last Updated:** 2026-04-11

This document describes the current state of the frontend - where each piece of logic lives and how it connects.

---

## 1. Directory Structure

```
frontend/
├── app/                        # Next.js App Router pages
│   ├── page.tsx               # Landing → redirect to /dashboard
│   ├── layout.tsx             # Root layout + providers
│   ├── login/page.tsx         # Login form
│   ├── register/page.tsx      # Registration form  
│   ├── dashboard/page.tsx    # Dashboard overview
│   ├── crawl/
│   │   ├── page.tsx          # Main crawl entry (switches config/run)
│   │   ├── category/page.tsx  # Category listing mode
│   │   ├── pdp/page.tsx      # Product detail mode
│   │   └── bulk/page.tsx     # Bulk URL mode
│   ├── runs/
│   │   ├── page.tsx         # Run list view
│   │   └── [run_id]/
│   │       ├── page.tsx     # Run detail (alias for /crawl?run_id=)
│   │       └── loading.tsx
│   ├── jobs/page.tsx         # Active jobs view
│   ├── selectors/page.tsx   # Selector management (calls non-existent API)
│   └── admin/
│       ├── users/page.tsx   # User admin
│       └── llm/page.tsx    # LLM config (calls non-existent API)
│
├── components/
│   ├── layout/
│   │   ├── app-shell.tsx       # Authenticated layout shell
│   │   ├── auth-session-query.ts  # Session fetching
│   │   └── top-bar-context.tsx  # Header state
│   ├── crawl/
│   │   ├── crawl-config-screen.tsx   # Crawl form UI
│   │   ├── crawl-run-screen.tsx       # Run workspace UI
│   │   ├── shared.tsx             # Shared helpers, RecordsTable, LogTerminal
│   │   └── use-run-polling.ts     # Run polling logic
│   └── ui/
│       ├── primitives.tsx      # Button, Card, Input, etc.
│       ├── patterns.tsx       # PageHeader, SectionHeader, etc.
│       ├── query-provider.tsx  # React Query provider
│       ├── theme-toggle.tsx    # Dark mode toggle
│       └── status.ts         # Status display helpers
│
├── lib/
│   ├── api/
│   │   ├── index.ts       # API exports (everything goes through here)
│   │   ├── client.ts    # fetch wrapper with auth
│   │   └── types.ts    # TypeScript types for API
│   ├── constants/
│   │   ├── timing.ts        # Polling intervals
│   │   ├── crawl-defaults.ts  # Default settings
│   │   ├── storage-keys.ts   # LocalStorage keys
│   │   └── crawl-statuses.ts  # Status mappings
│   ├── format/
│   │   ├── domain.ts    # Domain formatting
│   │   └── date.ts    # Date formatting
│   ├── telemetry/
│   │   └── events.ts  # Analytics events
│   └── utils.ts       # Utility functions (cn, etc.)
│
├── e2e/
│   └── smoke.spec.ts   # Playwright e2e tests
│
├── playwright.config.ts
├── vitest.config.ts
├── vitest.setup.ts
└── next.config.ts
```

---

## 2. How Pages Connect

### Main Entry
```
/ → page.tsx 
  → redirect to /dashboard

/dashboard → dashboard/page.tsx
  → api.dashboard()

/login → login/page.tsx  
  → api.login()

/register → register/page.tsx

/crawl → crawl/page.tsx
  ├── No run_id → CrawlConfigScreen
  └── Has run_id → CrawlRunScreen

/crawl/category → crawl/category/page.tsx
  → Redirects to /crawl?mode=category

/crawl/pdp �� crawl/pdp/page.tsx
  → Redirects to /crawl?mode=pdp

/crawl/bulk → crawl/bulk/page.tsx
  → Redirects to /crawl?mode=bulk

/runs → runs/page.tsx
  → api.listCrawls()

/runs/{run_id} → runs/[run_id]/page.tsx
  → Redirects to /crawl?run_id={run_id}

/jobs → jobs/page.tsx
  → api.listJobs()

/selectors → selectors/page.tsx
  → api.suggestSelectors() ← DOESN'T WORK (backend missing)

/admin/users → admin/users/page.tsx
  → api.listUsers(), api.updateUser()

/admin/llm → admin/llm/page.tsx  
  → api.listLLMConfigs() ← DOESN'T WORK (backend missing)
```

---

## 3. Component Hierarchy

```
AppShell (layout/app-shell.tsx)
├── AuthSessionQuery
│   └── Session gating
├── TopBarContext
│   └── PageHeader projection
└── Children (page content)

CrawlConfigScreen (components/crawl/crawl-config-screen.tsx)
├── TabBar (category/pdp)
├── UrlInput
├── SettingsForm
│   ├── ModeSelector
│   ├── AdvancedOptions
│   └── FieldSelector
└── SubmitButton → api.createCrawl() → navigate /crawl?run_id=

CrawlRunScreen (components/crawl/crawl-run-screen.tsx)
├── RunHeader (status, url, surface)
├── ProgressBar
├── TabPanel
│   ├── TableTab → RecordsTable
│   ├── JsonTab → JSON preview
│   ├── MarkdownTab → Markdown preview
│   └── LogsTab → LogTerminal
└── ActionBar → pause/resume/kill

RecordsTable (components/crawl/shared.tsx)
├── Virtualized rows
├── Column headers
└── Pagination

LogTerminal (components/crawl/shared.tsx)
├── Log entries
└── Terminal-like styling

SelectorsPage (app/selectors/page.tsx)
├── UrlInput
├── ExpectedColumnsInput
├── Preview iframe
├── FieldRows
│   ├── FieldName
│   ├── SelectorValue
│   ├── TestButton → api.testSelector()
│   ├── AutoDetect → api.suggestSelectors()
│   └── Accept/Save
└── SaveButton → api.createSelector()
```

---

## 4. API Layer (lib/api/index.ts)

All frontend access goes through here:

```typescript
export const api = {
  // Auth
  register(email, password) → POST /api/auth/register
  login(email, password) → POST /api/auth/login
  me() → GET /api/auth/me
  
  // Dashboard
  dashboard() → GET /api/dashboard
  resetApplicationData() → POST /api/dashboard/reset-data
  
  // Crawls
  createCrawl(payload) → POST /api/crawls
  createCsvCrawl(formData) → POST /api/crawls/csv
  listCrawls(params) → GET /api/crawls
  getCrawl(runId) → GET /api/crawls/{id}
  deleteCrawl(runId) → DELETE /api/crawls/{id}
  pauseCrawl(runId) → POST /api/crawls/{id}/pause
  resumeCrawl(runId) → POST /api/crawls/{id}/resume
  killCrawl(runId) → POST /api/crawls/{id}/kill
  commitSelectedFields(runId, items) → POST /api/crawls/{id}/commit-fields
  
  // Records
  getRecords(runId, params) → GET /api/crawls/{id}/records
  getRecordProvenance(recordId) → GET /api/records/{id}/provenance
  getCrawlLogs(runId, params) → GET /api/crawls/{id}/logs
  
  // Exports
  getMarkdown(runId) → GET /api/crawls/{id}/export/markdown
  downloadCsv(runId) → GET /api/crawls/{id}/export/csv
  downloadJson(runId) → GET /api/crawls/{id}/export/json
  exportCsv/Json/Markdown(runId) → URL string
  
  // Review
  getReview(runId) → GET /api/review/{id}
  reviewHtml(runId) → URL string
  saveReview(runId, payload) → POST /api/review/{id}/save
  previewSelectors(runId, payload) → POST /api/review/{id}/selector-preview
  
  // Users (admin)
  listUsers(params) → GET /api/users
  updateUser(userId, payload) → PATCH /api/users/{id}
  
  // SELECTORS - DOESN'T EXIST IN BACKEND
  listSelectors(params) → GET /api/selectors
  suggestSelectors(payload) → POST /api/selectors/suggest
  createSelector(payload) → POST /api/selectors
  updateSelector(id, payload) → PUT /api/selectors/{id}
  deleteSelector(id) → DELETE /api/selectors/{id}
  deleteSelectorsByDomain(domain) → DELETE /api/selectors/domain/{domain}
  testSelector(payload) → POST /api/selectors/test
  
  // JOBS
  listJobs() → GET /api/jobs/active
  
  // LLM CONFIG - DOESN'T EXIST IN BACKEND  
  listLLMConfigs() → GET /api/llm/configs
  createLLMConfig(payload) → POST /api/llm/configs
  updateLLMConfig(id, payload) → PUT /api/llm/configs/{id}
  deleteLLMConfig(id) → DELETE /api/llm/configs/{id}
}
```

---

## 5. Data Flow in Run Workspace

```
Initial load (run_id in URL)
  → use-run-polling.ts hook
  → poll every 2s while active
  → api.getCrawl(runId)
  → update React Query cache

Table tab selected
  → api.getRecords(runId, {page, limit})
  → RecordsTable with virtualization

JSON tab selected
  → api.downloadJson(runId)
  → parse + display

Markdown tab selected  
  → api.getMarkdown(runId)

Logs tab selected
  → api.getCrawlLogs(runId, {after_id})
  → LogTerminal with append

WebSocket available
  → connect /api/crawls/{id}/logs/ws
  → stream live
  → fallback to polling if unavailable
```

---

## 6. What each component does

| Component | File | Purpose |
|-----------|------|---------|
| AppShell | layout/app-shell.tsx | Full-page layout, session check |
| CrawlConfigScreen | crawl/crawl-config-screen.tsx | Crawl form with all options |
| CrawlRunScreen | crawl/crawl-run-screen.tsx | Run results workspace |
| RecordsTable | crawl/shared.tsx | Virtualized record display |
| LogTerminal | crawl/shared.tsx | Terminal-style logs |
| use-run-polling | crawl/use-run-polling.ts | Run status polling |
| SelectorsPage | app/selectors/page.tsx | Selector CRUD UI |
| primitives | ui/primitives.tsx | Button, Card, Input, etc. |
| patterns | ui/patterns.tsx | PageHeader, Section, Alert |
| api client | lib/api/client.ts | fetch wrapper |
| api types | lib/api/types.ts | All TypeScript types |

---

## 7. Key Hooks and State

```typescript
// use-run-polling.ts
useRunPolling(runId: number) → {
  run: CrawlRun | null
  isActive: boolean
  shouldPoll: boolean
  error: Error | null
}

// crawl-config-screen.tsx
useCrawlForm() → {
  url, setUrl()
  surface, setSurface()
  mode, setMode()
  settings, updateSettings()
  isSubmitting, submit()
}

// crawl-run-screen.tsx  
useRunWorkspace(runId: number) → {
  run: CrawlRun | null
  activeTab: 'table' | 'json' | 'markdown' | 'logs'
  setTab()
  refresh()
  actions: { pause, resume, kill }
}
```

---

## 8. Frontend expects these backend endpoints

| Frontend uses | Backend status |
|--------------|-------------|
| /api/auth/* | EXISTS |
| /api/crawls/* | EXISTS |
| /api/crawls/{id}/records | EXISTS |
| /api/crawls/{id}/logs | EXISTS |
| /api/crawls/{id}/logs/ws | EXISTS |
| /api/review/* | EXISTS |
| /api/dashboard | EXISTS |
| /api/users | EXISTS |
| /api/jobs | EXISTS |
| /api/selectors | MISSING |
| /api/selectors/suggest | MISSING |
| /api/selectors/test | MISSING |
| /api/llm/configs | MISSING |