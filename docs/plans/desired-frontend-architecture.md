# CrawlerAI: Desired Frontend Architecture

> **Type:** Prescriptive target state. Grounded in actual frontend audit (2026-04-11).
> **Stack:** Next.js App Router, TypeScript, Tailwind CSS.
> **Authority:** Where this doc conflicts with existing code, the code is wrong.

---

## What Changes, What Stays, What Gets Deleted

### STAYS — No structural change needed
- `app/layout.tsx`, `app/page.tsx` (root redirect)
- `app/login/page.tsx`, `app/register/page.tsx`
- `app/dashboard/page.tsx`
- `app/crawl/page.tsx` — main crawl entry (CrawlConfigScreen / CrawlRunScreen switch)
- `app/runs/page.tsx`, `app/runs/[run_id]/page.tsx`
- `app/jobs/page.tsx`
- `app/admin/users/page.tsx`
- `components/layout/` — app-shell, auth-session-query, top-bar-context
- `components/crawl/` — crawl-config-screen, crawl-run-screen, shared, use-run-polling
- `components/ui/` — primitives, patterns, query-provider, theme-toggle, status
- `lib/api/client.ts` (the fetch wrapper itself)
- `lib/constants/`, `lib/format/`, `lib/utils.ts`

### GETS DELETED — Dead pages, dead routes, non-existent API calls
See deletion manifest below.

### GETS FIXED — Types aligned to actual backend response
- `lib/api/types.ts` — currently has types for non-existent selector and LLM config APIs
- `lib/api/index.ts` — contains dead API call functions that must be removed

---

## Deletion Manifest — Complete, No Exceptions

### Dead Pages (call non-existent backend APIs)
```
app/selectors/page.tsx         ← Calls /api/selectors which does not exist. DELETE.
app/admin/llm/page.tsx         ← Calls /api/llm/configs which does not exist. DELETE.
```

### Redirect-Only Pages (zero logic, just redirect to /crawl)
```
app/crawl/category/page.tsx    ← Only redirects to /crawl?mode=category. DELETE.
app/crawl/pdp/page.tsx         ← Only redirects to /crawl?mode=pdp. DELETE.
app/crawl/bulk/page.tsx        ← Only redirects to /crawl?mode=bulk. DELETE.
```
These routes should either be removed from the nav or handled with a Next.js `redirect()` in a single file — not separate page components.

### Dead API Functions in `lib/api/index.ts`
Remove every function that calls a non-existent backend endpoint:
```typescript
// DELETE these from api object:
listSelectors(params)          // GET /api/selectors — backend does not exist
suggestSelectors(payload)      // POST /api/selectors/suggest — backend does not exist
createSelector(payload)        // POST /api/selectors — backend does not exist
updateSelector(id, payload)    // PUT /api/selectors/{id} — backend does not exist
deleteSelector(id)             // DELETE /api/selectors/{id} — backend does not exist
deleteSelectorsByDomain(domain) // DELETE /api/selectors/domain/{domain} — backend does not exist
testSelector(payload)          // POST /api/selectors/test — backend does not exist
listLLMConfigs()               // GET /api/llm/configs — backend does not exist
createLLMConfig(payload)       // POST /api/llm/configs — backend does not exist
updateLLMConfig(id, payload)   // PUT /api/llm/configs/{id} — backend does not exist
deleteLLMConfig(id)            // DELETE /api/llm/configs/{id} — backend does not exist
```

### Dead Types in `lib/api/types.ts`
Remove all TypeScript types that only exist to support the deleted API functions:
```typescript
// DELETE any types related to:
// - Selector CRUD (Selector, SelectorSuggestion, SelectorTest, etc.)
// - LLM config CRUD (LLMConfig, LLMConfigCreate, LLMConfigUpdate, etc.)
```

### Navigation Links
Remove nav links to deleted pages (`/selectors`, `/admin/llm`) from `app-shell.tsx` or wherever nav is defined.

---

## Target Directory Layout

```
frontend/
├── app/
│   ├── layout.tsx                  # UNCHANGED
│   ├── page.tsx                    # UNCHANGED (redirect to /dashboard)
│   ├── login/page.tsx              # UNCHANGED
│   ├── register/page.tsx           # UNCHANGED
│   ├── dashboard/page.tsx          # UNCHANGED
│   │
│   ├── crawl/
│   │   └── page.tsx                # UNCHANGED — CrawlConfigScreen / CrawlRunScreen
│   │   # DELETE: crawl/category/, crawl/pdp/, crawl/bulk/ (redirect-only pages)
│   │
│   ├── runs/
│   │   ├── page.tsx                # UNCHANGED
│   │   └── [run_id]/page.tsx       # UNCHANGED
│   │
│   ├── jobs/page.tsx               # UNCHANGED
│   │   # DELETE: selectors/page.tsx
│   │
│   └── admin/
│       ├── users/page.tsx          # UNCHANGED
│       # DELETE: admin/llm/page.tsx
│
├── components/
│   ├── layout/                     # UNCHANGED
│   ├── crawl/                      # UNCHANGED
│   └── ui/                         # UNCHANGED
│
├── lib/
│   ├── api/
│   │   ├── client.ts               # UNCHANGED
│   │   ├── index.ts                # REMOVE dead selector + LLM config functions
│   │   └── types.ts                # REMOVE dead selector + LLM config types
│   │                               # ADD/FIX types for actual backend responses (see below)
│   ├── constants/                  # UNCHANGED
│   ├── format/                     # UNCHANGED
│   └── utils.ts                    # UNCHANGED
│
└── e2e/smoke.spec.ts               # UPDATE: remove smoke tests for deleted pages
```

---

## Authoritative API Function List

After cleanup, `lib/api/index.ts` exports exactly these functions:

```typescript
export const api = {
  // Auth
  register(email, password)
  login(email, password)
  me()

  // Dashboard
  dashboard()
  resetApplicationData()           // admin only

  // Crawls
  createCrawl(payload)
  createCsvCrawl(formData)
  listCrawls(params)
  getCrawl(runId)
  deleteCrawl(runId)
  pauseCrawl(runId)
  resumeCrawl(runId)
  killCrawl(runId)
  commitSelectedFields(runId, items)

  // Records
  getRecords(runId, params)
  getRecordProvenance(recordId)
  getCrawlLogs(runId, params)

  // Exports
  getMarkdown(runId)
  downloadCsv(runId)
  downloadJson(runId)
  exportCsv(runId)
  exportJson(runId)
  exportMarkdown(runId)

  // Review
  getReview(runId)
  reviewHtml(runId)
  saveReview(runId, payload)
  previewSelectors(runId, payload)  // review-context selector preview — different from the deleted selector CRUD

  // Users (admin)
  listUsers(params)
  updateUser(userId, payload)

  // Jobs
  listJobs()
}
```

---

## Types to Fix in `lib/api/types.ts`

After removing dead types, ensure these actual backend response shapes are accurately typed:

### `CrawlRecord` — align to actual `record.data` contract
```typescript
interface CrawlRecord {
  id: number
  url: string
  surface: "ecommerce_detail" | "ecommerce_listing" | "job_detail" | "job_listing"
  verdict: "success" | "partial" | "listing_detection_failed" | "failed" | "pending"
  data: Record<string, unknown>            // populated logical fields only (backend strips empty/null/_-prefixed)
  discovered_data: Record<string, unknown> // logical metadata only (raw containers stripped)
  source_trace: {
    field_discovery: FieldDiscovery[]
    acquisition: AcquisitionTrace
  }
}

interface FieldDiscovery {
  field: string
  value: unknown
  source: string       // "json_ld" | "dom" | "http_adapter" | "xhr" | "hydrated_state" | "llm"
  missing: boolean
}

interface AcquisitionTrace {
  method: "http" | "browser"
  browser_used: boolean
  challenge_detected: boolean
  timing_ms: number
}
```

### `CrawlSettings` — align to actual backend `CrawlRunSettings`
```typescript
interface CrawlSettings {
  advanced_mode: null | "paginate" | "scroll" | "load_more"
  max_pages: number | null
  max_records: number | null
  sleep_ms: number | null
  proxy_list: string[] | null
  llm_enabled: boolean
  extraction_contract: string[] | null     // requested fields list
}
```

---

## Control Ownership Rules (Frontend Enforces)

These mirror backend Invariant 13. The UI must not silently alter submitted controls.

- **`page_type`** — shown as submitted. Never auto-switches.
- **`advanced_mode`** — off by default. User explicitly enables. Label must clarify: this is listing traversal (paginate/scroll/load_more), NOT browser rendering escalation.
- **`llm_enabled`** — off by default.
- **`proxy_list`** — user-managed. No auto-populate.

---

## Pages Backed by Real API (Authoritative)

| Page | Route | Backend API |
|------|-------|-------------|
| Dashboard | `/dashboard` | GET /api/dashboard |
| Crawl submission | `/crawl` | POST /api/crawls |
| Run detail | `/crawl?run_id=X` | GET /api/crawls/{id} |
| Run list | `/runs` | GET /api/crawls |
| Jobs | `/jobs` | GET /api/jobs/active |
| User admin | `/admin/users` | GET+PATCH /api/users |

| Page | Route | Status |
|------|-------|--------|
| Selector manager | `/selectors` | ❌ DELETE — backend missing, feature removed |
| LLM config | `/admin/llm` | ❌ DELETE — backend missing, feature removed |

---

## E2E Test Alignment

`e2e/smoke.spec.ts` must be updated to:
- Remove any test visiting `/selectors`
- Remove any test visiting `/admin/llm`
- Remove any test asserting on selector or LLM config UI elements
- Keep: login, dashboard, crawl submission, run polling, record display, user admin
