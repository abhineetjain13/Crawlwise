# Domain Memory Exposure Audit: Backend Exists, Frontend Missing

**Date:** 2026-04-20  
**Status:** CONFIRMED - Critical feature gap  
**Severity:** HIGH - Users cannot manage their saved selectors

---

## Executive Summary

**Domain Memory EXISTS in backend and IS working**, but the frontend provides **NO user interface** to:
1. View saved selectors per domain
2. Edit existing selectors
3. Delete selectors
4. Browse all saved selectors across domains

Users can **create** selectors but have **no way to see or manage** what they've saved.

---

## Part 1: Backend - Domain Memory EXISTS ✓

### Database Layer

@`c:\Projects\pre_poc_ai_crawler\backend\app\models\crawl.py:522-538`
```python
class DomainMemory(Base):
    __tablename__ = "domain_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    surface: Mapped[str] = mapped_column(String(40), index=True)
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selectors: Mapped[dict] = mapped_column(JSONB, default=dict)  # ← Stores selector rules
    created_at: Mapped[datetime] = ...
    updated_at: Mapped[datetime] = ...
```

### Service Layer

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\domain_memory_service.py:9-54`
```python
async def load_domain_memory(session, *, domain: str, surface: str) -> DomainMemory | None:
    # Loads from database by domain + surface
    
async def save_domain_memory(session, *, domain: str, surface: str, selectors: dict, ...):
    # Saves to database (upsert)
    
def selector_rules_from_memory(memory: DomainMemory | None) -> list[dict[str, object]]:
    # Extracts selector rules from JSONB
```

### API Layer

@`c:\Projects\pre_poc_ai_crawler\backend\app\api\selectors.py:34-107`
```python
@router.get("")  # ← LIST selectors
async def selectors_list(domain: str = "", surface: str = "generic"):
    # Returns saved selectors for domain

@router.post("")  # ← CREATE selector
async def selectors_create(payload: SelectorCreateRequest):
    # Saves new selector to domain_memory

@router.put("/{selector_id}")  # ← UPDATE selector
async def selectors_update(selector_id: int, ...):
    # Updates existing selector

@router.delete("/{selector_id}")  # ← DELETE selector
async def selectors_delete(selector_id: int):
    # Removes selector from domain_memory

@router.delete("/domain/{domain}")  # ← DELETE all for domain
async def selectors_delete_domain(domain: str):
    # Bulk delete by domain
```

**ALL CRUD OPERATIONS EXIST IN BACKEND**

---

## Part 2: Frontend API Client - Methods EXIST ✓

@`c:\Projects\pre_poc_ai_crawler\frontend\lib\api\types.ts:170-185`
```typescript
export type SelectorRecord = {
  id: number;
  domain: string;
  surface: string;
  field_name: string;
  css_selector?: string | null;
  xpath?: string | null;
  regex?: string | null;
  status: string;
  sample_value?: string | null;
  source: string;
  source_run_id?: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};
```

@`c:\Projects\pre_poc_ai_crawler\frontend\lib\api\index.ts:113-127`
```typescript
export const api = {
  listSelectors: (params?: { domain?: string }) => {
    // ← EXISTS but UNUSED in UI!
    const query = new URLSearchParams();
    if (params?.domain) query.set("domain", params.domain);
    return apiClient.get<SelectorRecord[]>(withQuery("/api/selectors", query));
  },
  
  suggestSelectors: (payload: { url: string; expected_columns: string[] }) =>
    apiClient.post<SelectorSuggestResponse>("/api/selectors/suggest", payload),
    
  createSelector: (payload: SelectorCreatePayload) =>
    apiClient.post<SelectorRecord>("/api/selectors", payload),
    
  updateSelector: (selectorId: number, payload: SelectorUpdatePayload) =>
    apiClient.put<SelectorRecord>(`/api/selectors/${selectorId}`, payload),
    
  deleteSelector: (selectorId: number) =>
    apiClient.delete<void>(`/api/selectors/${selectorId}`),
    
  deleteSelectorsByDomain: (domain: string) =>
    apiClient.delete<{ deleted: number }>(`/api/selectors/domain/${encodeURIComponent(domain)}`),
    
  testSelector: (...) => apiClient.post(...),
  selectorPreviewHtml: (url: string) => ...,
};
```

**ALL API METHODS ARE DEFINED BUT listSelectors, updateSelector, deleteSelector ARE NEVER CALLED**

---

## Part 3: Frontend UI - Management Interface MISSING ✗

### Current Navigation Structure

@`c:\Projects\pre_poc_ai_crawler\frontend\components\layout\app-shell.tsx:36-51`
```typescript
const navGroups = [
  {
    label: "Workspace",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/crawl", label: "Crawl Studio", icon: Globe },
      { href: "/runs", label: "History", icon: History },
      { href: "/selectors", label: "Selector Tool", icon: Search },  // ← ONLY selector page
      { href: "/jobs", label: "Jobs", icon: Activity },
    ],
  },
  {
    label: "Admin",
    items: [
      { href: "/admin/users", label: "Users", icon: ShieldCheck },
      { href: "/admin/llm", label: "LLM Config", icon: Settings2 },
      // ← NO "Domain Memory" or "Saved Selectors" admin page!
    ],
  },
] as const;
```

### What the Selector Page Does (And Doesn't Do)

@`c:\Projects\pre_poc_ai_crawler\frontend\app\selectors\page.tsx:32-83`
```typescript
export default function SelectorsPage() {
  const [url, setUrl] = useState("");
  const [loadedUrl, setLoadedUrl] = useState("");
  const [rows, setRows] = useState<SelectorRow[]>([]);
  // ...

  async function loadPageAndSuggestions() {
    // ...
    const response = await api.suggestSelectors({  // ← Only gets FRESH LLM suggestions
      url: targetUrl,
      expected_columns: parsedColumns,
    });
    setRows(
      parsedColumns.map((field) => {
        const suggestion = response.suggestions[field]?.[0];
        return buildRowFromSuggestion(field, suggestion);  // ← Ignores saved selectors!
      }),
    );
    // ← MISSING: const saved = await api.listSelectors({ domain })
  }
  
  async function saveAcceptedRows() {
    // Saves via api.createSelector() - works correctly
  }
  
  // ← MISSING: Function to load and display saved selectors
  // ← MISSING: Function to edit existing selector
  // ← MISSING: Function to delete selector
  // ← MISSING: List view of all saved selectors
}
```

### What's Missing From The UI

| Feature | Backend API | Frontend UI | Status |
|---------|-------------|-------------|--------|
| Create selector | `POST /api/selectors` | "Save Accepted Selectors" button | ✅ Works |
| List saved selectors | `GET /api/selectors?domain=` | **NO UI** | ❌ Missing |
| View selector details | `GET /api/selectors` response | **NO UI** | ❌ Missing |
| Edit selector | `PUT /api/selectors/{id}` | **NO UI** | ❌ Missing |
| Delete selector | `DELETE /api/selectors/{id}` | **NO UI** | ❌ Missing |
| Bulk delete by domain | `DELETE /api/selectors/domain/{domain}` | **NO UI** | ❌ Missing |
| Browse all domains | `GET /api/selectors` (no domain filter) | **NO UI** | ❌ Missing |

---

## Part 4: Impact Analysis

### Current User Flow (Broken)

```
User opens /selectors
  ↓
User enters URL + fields
  ↓
LLM suggests selectors
  ↓
User clicks "Accept" on some rows
  ↓
User clicks "Save Accepted Selectors"
  ↓
✅ Selectors saved to database
  ↓
User refreshes page / comes back tomorrow
  ↓
User enters same URL
  ↓
⚠️ UI shows only FRESH LLM suggestions
  ↓
❌ User sees NO indication selectors were saved
  ↓
❌ User can't edit existing selectors
  ↓
❌ User creates duplicate selectors
  ↓
Database has multiple selectors for same field
```

### What Users CANNOT Do Today

1. **See what they've saved** - No "My Selectors" view
2. **Edit a selector** - Must delete and recreate (but can't see list to delete)
3. **Delete a selector** - No delete button in UI
4. **Manage selectors per domain** - No domain-level view
5. **Disable a selector** - No is_active toggle exposed
6. **View selector history** - No created_at/updated_at display

---

## Part 5: Required Frontend Implementations

### Option A: Enhance Existing /selectors Page

Add to current `selectors/page.tsx`:
1. **Load saved selectors** on page load
2. **Merge with suggestions** (prefer saved)
3. **Show "Saved" indicator** on rows
4. **Add delete button** per row
5. **Add "View My Selectors" tab** listing all saved

### Option B: Add New Management Page

Create `app/admin/selectors/page.tsx` or `app/selectors/manage/page.tsx`:
1. **List all domains** with saved selectors
2. **Expand domain** to see selectors
3. **Edit/Delete** per selector
4. **Bulk operations** (delete all for domain)

### Recommended: Both

1. **Quick fix:** Update `/selectors` to load saved selectors
2. **Proper fix:** Add `/selectors/manage` for full CRUD

---

## Part 6: Verification Queries

Check what's in your database right now:

```sql
-- Count saved selectors per domain
SELECT domain, surface, COUNT(*) as selector_count
FROM domain_memory
GROUP BY domain, surface
ORDER BY selector_count DESC;

-- See actual selector data
SELECT domain, surface, selectors->'rules' as rules
FROM domain_memory
LIMIT 5;

-- Check if selectors have been created recently
SELECT domain, updated_at, selectors->'_meta'->>'next_id' as rule_count
FROM domain_memory
ORDER BY updated_at DESC
LIMIT 10;
```

Expected: You should see rows if you've ever clicked "Save Accepted Selectors"

---

## Summary

| Layer | Status | Evidence |
|-------|--------|----------|
| Database | ✅ EXISTS | `DomainMemory` model with JSONB selectors |
| Service | ✅ WORKS | `save_domain_memory`, `load_domain_memory` |
| API | ✅ COMPLETE | All CRUD endpoints implemented |
| API Client | ✅ DEFINED | `listSelectors`, `updateSelector`, etc. |
| UI - Create | ✅ WORKS | "Save Accepted Selectors" button |
| UI - List | ❌ **MISSING** | No `api.listSelectors()` call in selectors page |
| UI - Edit | ❌ **MISSING** | No `api.updateSelector()` call anywhere |
| UI - Delete | ❌ **MISSING** | No `api.deleteSelector()` call in UI |
| UI - Browse | ❌ **MISSING** | No "My Selectors" or "Domain Memory" page |

**The infrastructure is complete. Only the UI is missing.**

---

## Next Steps

### Immediate (1-2 hours)
1. Add `api.listSelectors()` call to `/selectors` page
2. Merge saved selectors with LLM suggestions
3. Mark saved rows with "Saved" status

### Short Term (1 day)
4. Add delete button per selector row
5. Add edit capability (inline or modal)

### Medium Term (2-3 days)
6. Create `/selectors/manage` page for full domain management
7. Add domain-level operations (delete all, export, import)
8. Add selector validation status display

**Backend is production-ready. Frontend needs completion.**
