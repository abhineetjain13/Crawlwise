# UCP Audit — UI Build Specification
**Version:** 1.0 | **Status:** READY FOR AGENT BUILD | **Date:** May 2026  
**Repo:** Crawlwise | **Feature:** `ucp_audit` surface  
**Design System:** Obsidian Data Console — sky blue accent (`#38BDF8`), IBM Plex Sans (body), JetBrains Mono (code/numbers)

---

## 1. Overview

This document is the authoritative UI specification for the **UCP Compliance Audit** frontend. It defines every component, its props, data contracts, layout rules, and interaction behavior. Backend API contracts and business logic live in the Architecture Plan (`CrawlerAI — UCP Compliance Audit Feature Plan v1.0`). This doc covers **frontend only**.

### 1.1 File Map

All new UI files are **net-new** — no existing components are modified.

```
frontend/components/ucp/
├── UCPAuditDashboard.tsx      # Root page/layout component
├── UCPScoreCard.tsx           # Per-dimension score ring
├── UCPFindingsTable.tsx       # Sortable/filterable findings list
└── UCPAgentViewPanel.tsx      # Side-by-side agent vs. human view diff
```

### 1.2 Data Flow

```
POST /api/v1/ucp-audit
    → task_id (polling)
    → GET /api/v1/ucp-audit/{task_id}
    → UCPComplianceReport (JSON)
    → UCPAuditDashboard (renders all sub-components)
```

The dashboard polls the task endpoint every **3 seconds** until `status === "completed"` or `status === "failed"`. Partial results are rendered progressively as each phase completes.

---

## 2. Design Tokens

```ts
// Use these from lib/constants.ts — NEVER hardcode in components
export const UCP_DESIGN = {
  accent:       '#38BDF8',   // sky blue
  accentHover:  '#0EA5E9',
  passFill:     '#22C55E',   // green — score > 70
  warnFill:     '#F59E0B',   // amber — score 40–70
  failFill:     '#EF4444',   // red — score < 40
  surface:      '#0F172A',   // dark panel bg
  surfaceAlt:   '#1E293B',   // card bg
  border:       '#334155',
  textPrimary:  '#F1F5F9',
  textMuted:    '#94A3B8',
  fontBody:     'IBM Plex Sans, sans-serif',
  fontMono:     'JetBrains Mono, monospace',
}
```

---

## 3. Component Specifications

---

### 3.1 `UCPAuditDashboard.tsx`

**Role:** Root layout. Owns fetch state, polling loop, and passes data down to all child components via props.

#### Props

```ts
interface UCPAuditDashboardProps {
  domain: string                  // e.g. "mystore.myshopify.com"
  auditId?: string                // pre-existing audit task ID (optional, for deep-link)
}
```

#### Internal State

```ts
interface DashboardState {
  auditStatus: 'idle' | 'running' | 'completed' | 'failed'
  report: UCPComplianceReport | null
  partialPhases: PhaseResult[]    // populated progressively during polling
  error: string | null
}
```

#### Layout (top → bottom)

```
┌──────────────────────────────────────────────────────────────┐
│  HEADER BAR                                                   │
│  "UCP Compliance Audit" [domain badge] [status chip]         │
│  [↓ Download JSON] [↓ Download PDF]  (disabled until done)  │
├──────────────┬───────────────────────────────────────────────┤
│              │  DIMENSION SCORE GRID                         │
│  OVERALL     │  D-UCP1 | D-UCP2 | D-UCP3 | D-UCP4           │
│  SCORE RING  │  D-UCP5 | D-UCP6 | D-UCP7                    │
│  (center)    │  (7 UCPScoreCard components, 4+3 grid)        │
│              │                                               │
├──────────────┴───────────────────────────────────────────────┤
│  CRITICAL FINDINGS TABLE  (UCPFindingsTable, severity=blocking)│
├──────────────────────────────────────────────────────────────┤
│  HIGH PRIORITY FINDINGS TABLE  (severity=warning)            │
├──────────────────────────────────────────────────────────────┤
│  AGENT-VIEW DELTA PANEL  (UCPAgentViewPanel)                 │
├──────────────────────────────────────────────────────────────┤
│  FIX SEQUENCE  (ordered checklist, exportable)               │
└──────────────────────────────────────────────────────────────┘
```

#### Behavior Rules

- **D-UCP1 gate:** If `D-UCP1.score === 0`, overlay all other sections with a "Discovery Blocked" banner:  
  > *"Agent cannot discover this store. Fix D-UCP1 before other scores are meaningful."*  
  Other dimension cards render but are visually dimmed (opacity 0.4).
- **Polling:** Show a progress bar during `status === 'running'`. Each completed phase unlocks its section; incomplete sections show skeleton loaders.
- **Export buttons:** `Download JSON` → `GET /api/v1/ucp-audit/{auditId}/export?format=json`  
  `Download PDF` → `GET /api/v1/ucp-audit/{auditId}/export?format=pdf`  
  Both URLs must be imported from `lib/constants.ts` — no hardcoded strings.
- **Error state:** If polling returns `status === 'failed'`, show error message from `report.error` in a red banner with a "Retry" button that re-submits the original POST.

---

### 3.2 `UCPScoreCard.tsx`

**Role:** Single dimension score display. Used 7 times in the grid + 1 time for the overall score ring (with `isOverall=true`).

#### Props

```ts
interface UCPScoreCardProps {
  dimension: string           // "D-UCP1" | "D-UCP2" | ... | "D-UCP7" | "Overall"
  label: string               // "Discovery" | "Product Schema" | etc.
  score: number               // 0–100
  status: 'pass' | 'warning' | 'fail' | 'pending'
  findingsCount: number       // number of findings for this dimension
  isOverall?: boolean         // true → larger ring variant
  isBlocked?: boolean         // true → dimmed, "blocked" label overlay
  onClick?: () => void        // scrolls to this dimension's findings
}
```

#### Visual Spec

- **Shape:** SVG circle ring (stroke-dasharray technique), not a bar
- **Ring stroke color:** `passFill` if score > 70, `warnFill` if 40–70, `failFill` if < 40, `#475569` if `pending`
- **Center text:** Score number in `fontMono`, large (32px for overall, 22px for dimension cards)
- **Below ring:** `dimension` label in `textMuted` (12px), `label` text in `textPrimary` (14px)
- **Status chip:** Small pill below label — "PASS" (green bg), "WARNING" (amber bg), "FAIL" (red bg), "PENDING" (slate bg)
- **Findings badge:** Small circle top-right of card, count of findings, only shown if `findingsCount > 0`
- **`isOverall=true` variant:** Ring is 180px diameter (vs. 100px for dimension cards), no status chip, score displayed with `/100` suffix
- **`isBlocked=true`:** Card opacity 0.4, diagonal "BLOCKED" text overlay in `failFill`

#### Interaction

- Clicking a dimension card scrolls the page to the corresponding findings section (using `onClick` prop from parent)
- Hover state: card border brightens to `accent` color, cursor pointer

---

### 3.3 `UCPFindingsTable.tsx`

**Role:** Sortable, filterable table of `UCPFinding` objects. Used twice: once for `blocking` severity, once for `warning` severity.

#### Props

```ts
interface UCPFindingsTableProps {
  findings: UCPFinding[]
  title: string                        // "Critical Findings" | "High Priority Findings"
  defaultSeverityFilter?: string       // "blocking" | "warning" | "info"
  showDimensionFilter?: boolean        // default true
}

interface UCPFinding {
  finding_id: string
  dimension: string                    // "D-UCP1" through "D-UCP7"
  severity: 'blocking' | 'warning' | 'info'
  description: string
  affected_count: number               // number of products/pages affected
  fix_guidance: string                 // concrete action
  estimated_effort: string             // "15 min" | "1 sprint" | "custom dev"
}
```

#### Column Definitions

| Column | Source Field | Width | Sortable | Notes |
|---|---|---|---|---|
| Severity | `severity` | 90px | Yes | Color-coded pill: red/amber/blue |
| Dimension | `dimension` | 80px | Yes | Monospace badge |
| Description | `description` | auto | No | Full text, wraps |
| Affected | `affected_count` | 80px | Yes | Number + "products" suffix |
| Effort | `estimated_effort` | 110px | Yes | Tag chip |
| Fix Guidance | `fix_guidance` | 260px | No | Expandable (truncated at 80 chars, click to expand) |

#### Filters (above table)

- **Dimension filter:** Multi-select dropdown — "All" + D-UCP1 through D-UCP7
- **Severity filter:** Toggle buttons — All | Blocking | Warning | Info
- **Search:** Free text search across `description` and `fix_guidance` fields

#### Behavior

- Default sort: `severity` (blocking first), then `affected_count` descending
- Empty state: "No findings at this severity level" with a checkmark icon
- Rows are not clickable (no drill-down needed at MVP)
- Table is paginated at 25 rows; show "Showing X of Y findings" footer

---

### 3.4 `UCPAgentViewPanel.tsx`

**Role:** Side-by-side diff showing what an AI agent extracts vs. what a human sees. This is the **unique differentiator panel** — must be visually distinctive.

#### Props

```ts
interface UCPAgentViewPanelProps {
  samples: AgentViewDelta[]     // array of 3–5 sample product deltas
  isLoading?: boolean
}

interface AgentViewDelta {
  url: string
  agent_extracted: Record<string, any>     // structured data agent gets
  human_visible: Record<string, any>       // rendered content human sees
  missing_in_agent_view: string[]          // fields in human_visible but not agent_extracted
  agent_only_signals: string[]             // JSON-LD signals not in DOM
  fidelity_score: number                   // 0–1
}
```

#### Layout

```
┌─────────────────────────────────────────────────────────────┐
│  PANEL HEADER: "Agent View vs. Human View"                   │
│  [Sample URL tabs: Product 1 | Product 2 | Product 3]       │
├─────────────────────────┬───────────────────────────────────┤
│  AGENT VIEW             │  HUMAN VIEW                        │
│  (HTTP-only extraction) │  (Full browser render)             │
│                         │                                   │
│  Key-value pairs from   │  Key-value pairs from rendered    │
│  JSON-LD + meta tags    │  DOM / visible content            │
│                         │                                   │
│  ✓ name                 │  ✓ name                           │
│  ✓ price                │  ✓ price                          │
│  ✗ [missing: color]     │  ✓ color (in DOM, not in JSON-LD) │
│  ✓ sku                  │  ✗ sku (not rendered)             │
│                         │                                   │
├─────────────────────────┴───────────────────────────────────┤
│  FIDELITY SCORE: [score ring] | MISSING FROM AGENT: [list]  │
│  AGENT-ONLY SIGNALS: [list]                                 │
└─────────────────────────────────────────────────────────────┘
```

#### Visual Diff Rules

- Fields present in **both** views: rendered with a green `✓` checkmark, white text
- Fields in **human view but missing from agent view** (`missing_in_agent_view`): highlighted in `failFill` background with a `✗` icon and label "Not in JSON-LD"
- Fields in **agent view only** (`agent_only_signals`): highlighted in `accent` background with an `ℹ` icon and label "Structured only"
- JSON values displayed in `fontMono` at 13px
- Long values truncated at 60 chars with `...` and tooltip on hover showing full value

#### Sample URL Tabs

- 3–5 tabs, one per sampled product
- Tab label: domain path only (e.g. `/products/blue-t-shirt`)
- Active tab: `accent` underline
- Fidelity score shown as small ring badge on each tab

#### Loading State

- Skeleton placeholders for both columns
- "Running agent extraction..." label with spinner

---

## 4. Fix Sequence Section

This section lives in `UCPAuditDashboard.tsx` directly (not a separate component at MVP).

### Data Shape

```ts
interface FixSequenceItem {
  order: number
  dimension: string
  action: string            // short imperative: "Add UCP manifest to /.well-known/ucp"
  effort: string            // "15 min" | "1 sprint" | "custom dev"
  impact: 'critical' | 'high' | 'medium'
  done: boolean             // toggleable by user (stored in localStorage)
}
```

### Layout

- Numbered list, ordered by `fix_priority` from the compliance engine
- Each row: `[checkbox] [order]. [dimension badge] [action text] [effort chip] [impact badge]`
- Checkbox state persisted in `localStorage` keyed by `auditId + finding_id`
- "Export Fix Plan" button → downloads the list as a markdown checklist (no API call — client-side generation)
- Completed items shown with strikethrough text and moved to a collapsed "Done" section at the bottom

---

## 5. API Constants (must live in `lib/constants.ts`)

The agent must define these constants — never hardcode URLs in components:

```ts
export const UCP_API = {
  submitAudit:    '/api/v1/ucp-audit',
  pollAudit:      (id: string) => `/api/v1/ucp-audit/${id}`,
  exportAudit:    (id: string, fmt: 'json' | 'pdf') => `/api/v1/ucp-audit/${id}/export?format=${fmt}`,
  POLL_INTERVAL:  3000,    // ms
  MAX_POLL_TRIES: 200,     // 10 min max polling window
}
```

---

## 6. UCPComplianceReport — Frontend Data Contract

This is the JSON shape the frontend expects from the poll endpoint when `status === 'completed'`.

```ts
interface UCPComplianceReport {
  audit_id: string
  domain: string
  created_at: string              // ISO 8601
  status: 'completed' | 'failed' | 'running'
  overall_score: number           // 0–100
  discovery_blocked: boolean      // true if D-UCP1 score === 0
  dimensions: UCPDimensionScore[]
  agent_view_samples: AgentViewDelta[]
  fix_sequence: FixSequenceItem[]
  report_formats_available: ('json' | 'markdown' | 'pdf')[]
  error?: string
}

interface UCPDimensionScore {
  dimension: string               // "D-UCP1" through "D-UCP7"
  label: string                   // "Discovery" | "Product Schema" | etc.
  score: number                   // 0–100
  status: 'pass' | 'warning' | 'fail'
  findings: UCPFinding[]
  fix_priority: number            // 1 = critical
}
```

---

## 7. Dimension Labels Reference

| Dimension ID | Label | Card Subtitle |
|---|---|---|
| D-UCP1 | Discovery | UCP manifest presence & validity |
| D-UCP2 | Product Schema | JSON-LD completeness per page |
| D-UCP3 | Metafield Coverage | Size, Color, Material, Brand, GTIN |
| D-UCP4 | Taxonomy Alignment | Google Product Taxonomy depth & consistency |
| D-UCP5 | Variant Fidelity | Per-SKU price + availability signals |
| D-UCP6 | Policy Readability | Shipping, returns, currency — machine-readable |
| D-UCP7 | Agent-View Delta | Agent extract vs. human view fidelity |

---

## 8. State & Error Handling

### Loading States (per section)

| Section | Skeleton Type |
|---|---|
| Overall Score Ring | Pulsing grey circle, same dimensions as ring |
| Dimension Grid | 7 grey rectangle cards |
| Findings Tables | 5 grey rows per table |
| Agent View Panel | Two-column grey blocks |
| Fix Sequence | 6 grey list rows |

### Error States

| Scenario | UI Response |
|---|---|
| Audit task fails | Red banner with `error` message + "Retry" button |
| Domain unreachable | Inline error on D-UCP1 card: "Could not reach domain" |
| Polling timeout (>10 min) | "Audit is taking longer than expected. [Check Status]" |
| Export fails | Toast notification: "Export failed — try again" |
| No findings | Empty state illustration + "All checks passed at this level" |

---

## 9. Acceptance Criteria (Frontend)

The agent must verify these before marking the work order complete:

- [ ] `UCPAuditDashboard` renders with a mock `UCPComplianceReport` JSON (no API call needed for this check)
- [ ] `UCPScoreCard` score ring animates from 0 to final score on mount (CSS transition, 800ms)
- [ ] D-UCP1 = 0 triggers discovery-blocked banner AND dims all other dimension cards
- [ ] `UCPFindingsTable` sorts by severity correctly (blocking → warning → info)
- [ ] `UCPAgentViewPanel` shows correct diff highlights: red for missing-in-agent, blue for agent-only
- [ ] Export buttons call correct endpoints from `lib/constants.ts` (no hardcoded URLs anywhere)
- [ ] Fix sequence checkbox state survives page reload (localStorage persistence)
- [ ] No hardcoded color values — all colors from `UCP_DESIGN` token map
- [ ] All API URLs constructed from `UCP_API` constants
- [ ] Passes TypeScript strict mode with no `any` except where explicitly noted in this spec

---

## 10. Mock Data for Development

Use this minimal mock to develop and test components without a live backend:

```ts
// frontend/mocks/ucpAuditMock.ts
export const mockUCPReport: UCPComplianceReport = {
  audit_id: "aud_mock_001",
  domain: "demo-store.myshopify.com",
  created_at: "2026-05-18T00:00:00Z",
  status: "completed",
  overall_score: 42,
  discovery_blocked: false,
  dimensions: [
    { dimension: "D-UCP1", label: "Discovery", score: 100, status: "pass", findings: [], fix_priority: 1 },
    { dimension: "D-UCP2", label: "Product Schema", score: 68, status: "warning", findings: [
      { finding_id: "f001", dimension: "D-UCP2", severity: "warning", description: "brand field missing on 34% of products", affected_count: 34, fix_guidance: "Add brand to JSON-LD additionalProperty array", estimated_effort: "1 sprint" }
    ], fix_priority: 2 },
    { dimension: "D-UCP3", label: "Metafield Coverage", score: 41, status: "warning", findings: [
      { finding_id: "f002", dimension: "D-UCP3", severity: "blocking", description: "size attribute missing on 91% of apparel products", affected_count: 91, fix_guidance: "Map Shopify metafield size to JSON-LD additionalProperty", estimated_effort: "1 sprint" }
    ], fix_priority: 1 },
    { dimension: "D-UCP4", label: "Taxonomy Alignment", score: 55, status: "warning", findings: [], fix_priority: 3 },
    { dimension: "D-UCP5", label: "Variant Fidelity", score: 29, status: "fail", findings: [
      { finding_id: "f003", dimension: "D-UCP5", severity: "blocking", description: "78% of multi-variant products use collapsed offers object", affected_count: 78, fix_guidance: "Expand offers array to one entry per variant with independent price + availability", estimated_effort: "custom dev" }
    ], fix_priority: 1 },
    { dimension: "D-UCP6", label: "Policy Readability", score: 70, status: "pass", findings: [], fix_priority: 3 },
    { dimension: "D-UCP7", label: "Agent-View Delta", score: 52, status: "warning", findings: [], fix_priority: 2 },
  ],
  agent_view_samples: [
    {
      url: "https://demo-store.myshopify.com/products/blue-tee",
      agent_extracted: { name: "Blue T-Shirt", price: "29.99", currency: "USD", sku: "BLU-TEE-M" },
      human_visible: { name: "Blue T-Shirt", price: "29.99", currency: "USD", sku: "BLU-TEE-M", color: "Blue", size: "M" },
      missing_in_agent_view: ["color", "size"],
      agent_only_signals: ["gtin13"],
      fidelity_score: 0.67
    }
  ],
  fix_sequence: [
    { order: 1, dimension: "D-UCP5", action: "Expand collapsed offers arrays to per-variant entries", effort: "custom dev", impact: "critical", done: false },
    { order: 2, dimension: "D-UCP3", action: "Add size metafield to apparel JSON-LD additionalProperty", effort: "1 sprint", impact: "critical", done: false },
    { order: 3, dimension: "D-UCP2", action: "Add brand field to all product JSON-LD blocks", effort: "1 sprint", impact: "high", done: false },
  ],
  report_formats_available: ["json", "markdown", "pdf"]
}
```

---

*End of UI Specification. For backend contracts, see: `CrawlerAI — UCP Compliance Audit Feature Plan v1.0`.*
