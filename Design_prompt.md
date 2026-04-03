# CrawlFlow — Design System Prompt
**For use with a coding agent to implement the CrawlFlow UI**

---

## 1. Identity & Philosophy

**App Name:** CrawlFlow  
**Feel:** Pro-tool. High information density, zero clutter. Every pixel earns its place.  
**Inspiration:** Stripe Dashboard × Linear App — compact, opinionated, enterprise-grade.  
**Theme:** Supports both **Light Mode** (primary/default) and **Dark Mode**. Light is the default; dark should feel equally polished, not an afterthought.

---

## 2. Color Palette

### Light Mode (Default — `:root`)
```
--bg-base:       #f8fafc   /* deepest background, page root */
--bg-surface:    #ffffff   /* cards, panels */
--bg-elevated:   #f1f5f9   /* dropdowns, modals, popovers */
--bg-sidebar:    rgba(248, 250, 252, 0.85)  /* glassmorphism sidebar */
--border:        #e2e8f0   /* 1px subtle borders everywhere */
--border-focus:  #6366f1   /* focused input ring */

--text-primary:  #0f172a   /* headings, labels */
--text-secondary:#475569   /* descriptions, meta */
--text-muted:    #94a3b8   /* timestamps, placeholders */

/* Action Blue — primary accent */
--accent:        #6366f1   /* indigo-500 */
--accent-hover:  #4f46e5   /* indigo-600 */
--accent-subtle: rgba(99, 102, 241, 0.08)  /* ghost states, highlights */

/* Semantic */
--success:       #10b981   /* emerald-500 */
--warning:       #f59e0b   /* amber-500 */
--danger:        #ef4444   /* red-500 */
--info:          #3b82f6   /* blue-500 */

/* Status badge fills (low opacity backgrounds) */
--status-active-bg:   rgba(16, 185, 129, 0.10)
--status-inactive-bg: rgba(100, 116, 139, 0.10)
--status-running-bg:  rgba(99, 102, 241, 0.10)
--status-killed-bg:   rgba(239, 68, 68, 0.10)
--status-paused-bg:   rgba(245, 158, 11, 0.10)

/* Shadows — lighter for light mode */
--shadow-sm:    0 1px 3px rgba(0,0,0,0.08);
--shadow-md:    0 4px 12px rgba(0,0,0,0.10);
--shadow-lg:    0 8px 32px rgba(0,0,0,0.12);
--shadow-modal: 0 20px 60px rgba(0,0,0,0.18);
```

### Dark Mode Overrides (`[data-theme="dark"]` or `.dark`)
```
--bg-base:       #1e1e2e
--bg-surface:    #252535
--bg-elevated:   #2e2e42
--bg-sidebar:    rgba(30, 30, 46, 0.75)
--border:        #3a3a52
--text-primary:  #f1f5f9
--text-secondary:#94a3b8
--text-muted:    #64748b
--accent-subtle: rgba(99, 102, 241, 0.12)
--status-active-bg:   rgba(16, 185, 129, 0.12)
--status-inactive-bg: rgba(100, 116, 139, 0.12)
--status-running-bg:  rgba(99, 102, 241, 0.12)
--status-killed-bg:   rgba(239, 68, 68, 0.12)
--status-paused-bg:   rgba(245, 158, 11, 0.12)
--shadow-sm:    0 1px 2px rgba(0,0,0,0.30);
--shadow-md:    0 4px 12px rgba(0,0,0,0.40);
--shadow-lg:    0 8px 32px rgba(0,0,0,0.50);
--shadow-modal: 0 20px 60px rgba(0,0,0,0.60);
```

> Use CSS custom properties for all colors. Never hardcode hex values in components — always reference a variable so light/dark mode flips automatically.

---

## 3. Typography

**Font:** `Inter` (primary), fallback: `SF Pro Display`, `system-ui`, `sans-serif`  
**Load via:** Google Fonts or local — `Inter` weights 400, 500, 600, 700.

```css
/* Scale */
--text-xs:   0.75rem   / 12px  — timestamps, badges, table metadata
--text-sm:   0.8125rem / 13px  — body text, table rows, form helpers
--text-base: 0.875rem  / 14px  — default body, sidebar items
--text-md:   1rem       / 16px — card titles, section headers
--text-lg:   1.125rem  / 18px  — page titles
--text-xl:   1.5rem    / 24px  — hero numbers, metric values

/* Tracking */
--tracking-tight:  -0.02em   /* headings */
--tracking-normal: -0.01em   /* body */
--tracking-wide:    0.06em   /* small-caps labels, tags */

/* Label style (reusable) */
.label-caps {
  font-size: var(--text-xs);
  font-weight: 600;
  letter-spacing: var(--tracking-wide);
  text-transform: uppercase;
  color: var(--text-muted);
}
```

---

## 4. Spacing & Layout

```
/* 4px base grid */
--space-1:  4px
--space-2:  8px
--space-3:  12px
--space-4:  16px
--space-5:  20px
--space-6:  24px
--space-8:  32px
--space-10: 40px
--space-12: 48px

/* Border radius */
--radius-sm:  4px   /* badges, small chips */
--radius-md:  6px   /* buttons, inputs, table rows */
--radius-lg:  10px  /* cards, drawers, modals */
--radius-xl:  16px  /* large panels */

/* Shadows — defined per-theme in §2; referenced here for component use */
/* --shadow-sm, --shadow-md, --shadow-lg, --shadow-modal */
```

---

## 5. Layout Structure

```
┌──────────────────────────────────────────────────┐
│  SIDEBAR (collapsible)  │  MAIN CONTENT AREA      │
│  width: 56px collapsed  │  flex: 1, overflow-y    │
│  width: 220px expanded  │  auto                   │
│  glassmorphism panel    │                         │
│  sticky, full-height    │  ┌──── PAGE HEADER ────┐│
│                         │  │ Title + breadcrumb  ││
│  [Logo / wordmark]      │  └─────────────────────┘│
│  ─────────────────       │  ┌──── CONTENT ────────┐│
│  Nav items (icons+text) │  │                     ││
│  ─────────────────       │  └─────────────────────┘│
│  [User avatar]          │                         │
│  [Theme toggle]         │                         │
└──────────────────────────────────────────────────┘
```

### Sidebar
- **Collapsed state:** 56px wide, icons only, tooltips on hover.
- **Expanded state:** 220px wide, icons + labels.
- **Glass effect:** `backdrop-filter: blur(16px)`, `background: var(--bg-sidebar)`, right border `1px solid var(--border)`.
- **Collapse toggle:** Chevron button at the bottom of the nav section.
- **Nav items:** Icon (20px) + label. Active item: accent left-border (`3px solid var(--accent)`) + `--accent-subtle` background.
- **Nav sections:** Dashboard, Crawlers, History, Site Memory, (divider), Admin, Settings.

### Page Header
- Height: 52px.
- Contains: Page title (--text-lg, --tracking-tight), optional breadcrumb (--text-sm, --text-muted), right-side actions.
- Bottom border: `1px solid var(--border)`.
- Background: `var(--bg-base)`, sticky to top of content area.

---

## 6. Core Components

### 6.1 Buttons

```
Primary:    bg=--accent,          text=white,          hover: --accent-hover
Secondary:  bg=transparent,       text=--text-primary, border=1px --border, hover: --bg-elevated
Danger:     bg=transparent,       text=--danger,       border=1px rgba(--danger, 0.3), hover: rgba(--danger, 0.12) bg
Ghost:      bg=transparent,       text=--text-secondary, hover: --accent-subtle bg, text=--accent
Icon-only:  bg=transparent,       size=28px,           hover: --bg-elevated

Sizes:
  sm: height 28px, px 10px, text-xs, radius-sm
  md: height 32px, px 14px, text-sm, radius-md  ← default
  lg: height 38px, px 18px, text-base, radius-md

States:
  Loading: show spinner inline, keep width locked (no layout shift)
  Disabled: opacity 0.4, cursor not-allowed
```

### 6.2 Form Fields (Stripe-style)

```
/* Input anatomy */
label (--label-caps) → input → helper text

Input:
  background:   var(--bg-surface)
  border:       1px solid var(--border)
  border-radius: var(--radius-md)
  height:       32px
  padding:      0 10px
  font-size:    var(--text-sm)
  color:        var(--text-primary)
  transition:   border-color 150ms ease, box-shadow 150ms ease

  :focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-subtle);
    outline: none;
  }

Textarea:
  Same as input but height auto, min-height 80px, padding 8px 10px.

Select:
  Same styling as input; custom chevron icon (not native arrow).

Toggle Switch:
  Width: 36px, height: 20px, thumb: 16px.
  Off: bg var(--border); On: bg var(--accent).
  Animate thumb position with CSS transition 150ms.

Segmented Control:
  Container: bg var(--bg-surface), border 1px --border, radius --radius-md, padding 2px.
  Active segment: bg var(--bg-elevated), text --text-primary, shadow --shadow-sm.
  Inactive: text --text-muted.
  Height: 30px.
```

### 6.3 Cards

```
background:     var(--bg-surface)
border:         1px solid var(--border)
border-radius:  var(--radius-lg)
padding:        var(--space-5)
box-shadow:     var(--shadow-sm)

Metric Card:
  ├── Label (--label-caps)
  ├── Value (--text-xl, font-weight 700, --tracking-tight)
  ├── Delta (--text-xs — green if positive, red if negative, with arrow icon)
  └── Sparkline (40px tall, accent color, no axes, filled area)
```

### 6.4 Tables (Data Grid)

```
Density: compact — row height 36px.
Header:  bg var(--bg-elevated), border-bottom 1px --border, --label-caps style.
Rows:    border-bottom 1px var(--border) at 30% opacity. Alternating rows optional.
Hover:   bg var(--accent-subtle), reveal inline action buttons (opacity 0 → 1).
Selected: bg var(--accent-subtle), left border 2px var(--accent).

Columns:
  - Checkbox column: 36px, always visible.
  - Status: Badge component (see 6.5).
  - Actions: right-aligned icon buttons, visible on row hover only.

Pagination:
  Below table, centered. Prev/Next buttons + page number display.
  Font: --text-sm. Disabled state: opacity 0.4.
```

### 6.5 Badges / Status Pills

```
Anatomy: icon (8px dot) + text (--text-xs, --tracking-wide, uppercase)
Padding: 2px 8px
Border-radius: var(--radius-sm)

Variants:
  Active:    color #10b981, bg var(--status-active-bg)
  Inactive:  color #94a3b8, bg var(--status-inactive-bg)
  Running:   color #6366f1, bg var(--status-running-bg)   + pulsing dot animation
  Paused:    color #f59e0b, bg var(--status-paused-bg)
  Killed:    color #ef4444, bg var(--status-killed-bg)
  Completed: color #10b981, bg var(--status-active-bg)
  Pending:   color #94a3b8, bg var(--status-inactive-bg)
```

### 6.6 Modals & Drawers

```
Modal:
  Overlay: rgba(0,0,0,0.6), backdrop-filter blur(4px)
  Panel: bg var(--bg-elevated), border 1px --border, radius --radius-xl, shadow --shadow-modal
  Max-width: 540px, centered.
  Header: title (--text-md, fw600) + close icon button (top-right).
  Footer: right-aligned button group (Cancel secondary, Confirm primary).
  Animation: scale 0.96→1 + opacity 0→1, 150ms ease.

Side Drawer (right):
  Width: 380px (config drawers), 480px (output/detail drawers).
  Slides in from the right: translateX(100%) → translateX(0), 200ms ease.
  bg var(--bg-surface), left border 1px --border.
  Header: title + close button + optional subtitle.
  Scrollable body, sticky footer with action buttons.
```

### 6.7 Tabs

```
Style: underline variant (not boxed).
Tab bar: border-bottom 1px --border.
Active tab: border-bottom 2px --accent, color --text-primary, fw 600.
Inactive: color --text-muted, hover color --text-secondary.
Font: --text-sm.
Padding: 0 16px, height 40px.
```

### 6.8 Progress Bars

```
Track: bg var(--border), height 6px, radius 999px.
Fill: bg var(--accent), radius 999px, transition width 300ms ease.
Variant — danger threshold: Fill turns var(--danger) when > 90% of max.
Label above: "X / Y records" (--text-xs, --text-secondary).
```

### 6.9 Toast / Notifications

```
Position: top-right, 16px from edges, z-index 9999.
Width: 320px.
bg var(--bg-elevated), border 1px --border, radius --radius-lg, shadow --shadow-lg.
Anatomy: [icon] [title (fw600)] [description (--text-sm)] [dismiss ×]
Variants: info (accent icon), success (green icon), warning (amber icon), error (red icon).
Auto-dismiss: 5s, with progress line at bottom shrinking.
Animation: slide in from right + fade in; fade out + slide out.

Site Memory Banner (special):
  Full-width top bar inside the page content area (not sidebar).
  bg var(--accent-subtle), border-bottom 1px --border.
  Icon + "Loaded X fields for [domain] from Site Memory" + [Dismiss] + [Edit] links.
  --text-sm, --text-primary.
```

### 6.10 Terminal / Log Stream

```
bg: #0d0d14  (near-black, independent of theme — always dark)
border: 1px solid var(--border)
border-radius: var(--radius-lg)
font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace
font-size: 12px
line-height: 1.6
padding: 12px 16px
overflow-y: auto
max-height: 320px

Log line format:
  [TIMESTAMP]  [LEVEL]  message

Levels by color:
  INFO:    #94a3b8
  SUCCESS: #10b981
  WARN:    #f59e0b
  ERROR:   #ef4444
  PROXY:   #6366f1

Auto-scrolls to bottom. "Jump to bottom" FAB appears when user scrolls up.
```

---

## 7. Screen-by-Screen Specifications

### 7.1 Dashboard

**Layout:** 2-column on wide screens (≥1280px), stacked on narrow.

**Metric Cards Row** (4 cards):
- Total Runs, Active Jobs, Total URLs Crawled, Success Rate.
- Each card: label + value + delta + sparkline.
- Sparkline: 8–10 data points, accent fill, no axes.

**Active Jobs Section** (below cards):
- Card with header "Active Jobs" + live badge (pulsing dot + count).
- Each job row: Run ID (monospace, --text-xs) | Type badge | Target URL (truncated, tooltip on hover) | Progress bar | Elapsed time | Pause / Resume / Kill buttons.
- Empty state: "No active jobs" centered, with a "Start a Crawl" CTA button.

**Recent Activity Feed** (right column or bottom):
- List of last 10 runs. Each row: status dot | crawl type | URL | time ago | record count.
- "View All History" link at bottom.

**Quick Launch** (top-right of page header area):
- Two buttons: "+ Category Crawl" (primary) and "+ PDP Crawl" (secondary).

---

### 7.2 Category Crawl & PDP Crawl (Crawler Modules)

**Defaults (applied on first load and new-crawl reset):**
- Active crawler tab: **PDP Crawl** (not Category Crawl).
- Smart Extraction toggle: **OFF**.
- Advanced Crawl panel: **collapsed / OFF**.

**Main area:** Segmented control at top to switch between "Category Crawl" and "PDP Crawl". Default active tab is PDP Crawl.

---

#### 7.2.A — Configuration Panel (left or side-drawer, right)

Opens inline when the page first loads (not a drawer on the main crawl screen — show it as the primary left-panel or a form area). Opens as a side-drawer only when re-configuring from the Running or Complete state.

**Section: Target**
- URL input (full-width, monospace placeholder).
- Crawl type selector:
  - Category: segmented — Single Page | Sitemap | **Bulk** (tab)
  - PDP: segmented — Single | Batch | CSV Upload

**Section: Smart Extraction** *(toggle, default OFF)*
- Label: "Smart Extraction" + `Sparkles` icon + "OFF" badge when disabled.
- When OFF: system uses saved Site Memory mappings + user-defined fields only.
- When ON: system auto-detects fields using LLM before crawl begins (adds latency — show a helper text: "Adds ~10–30s before crawl starts").

**Section: Additional Fields** *(both Category and PDP)*
- Label (--label-caps): "ADDITIONAL FIELDS"
- Helper text (--text-xs, --text-muted): "Comma-separated field names the crawler will look for during extraction."
- Input: full-width text input, placeholder: `e.g. price, sku, availability, brand`
- These field names are passed to the crawler alongside standard detected fields. If Smart Extraction is ON, the LLM is specifically prompted to locate these fields.

**Section: Field Configuration** *(PDP only — collapsed by default, expands when user clicks "Configure Fields")*

Sub-section A — **Auto-detected Fields** (read-only list, populated after a preview fetch):
- Each row: field name chip | source badge (HTML / JSON-LD / API / Regex) | extracted sample value (--text-xs, monospace, truncated) | remove icon.

Sub-section B — **New Field (Manual Entry)**:
- Label: "+ New Field" button (ghost, icon `Plus`). Clicking adds a new editable row.
- Each row (inline form):
  ```
  [ Field Name input ] [ XPath input (monospace) ] [ Regex input (monospace) ] [ 🗑 delete ]
  ```
  - Field Name: text input, width ~160px, placeholder "e.g. price".
  - XPath: monospace input, width ~240px, placeholder `//span[@class='price']`. Validated on blur — show green check or red X inline.
  - Regex: monospace input, width ~200px, placeholder `\$[\d,.]+`. Validated on blur.
  - Delete icon: `Trash2` icon button (danger ghost), removes the row with a fade-out animation.
  - Rows are draggable to reorder (drag handle `GripVertical` on the left).
- "Save to Site Memory" ghost link below the list.

**Section: Advanced Crawl** *(PDP only — toggle row, default OFF)*
- Toggle row: label "Advanced Crawl" + toggle switch. Default: OFF.
- When toggled ON: panel expands (animated height) revealing three sliders:

  ```
  ┌─────────────────────────────────────────────────────┐
  │  Request Delay                                       │
  │  [───●──────────────] 500 ms   range: 0–5000ms      │
  │                                                     │
  │  Max Records                                        │
  │  [──────────●───────] 100      range: 1–10000       │
  │                                                     │
  │  Max Pages                                          │
  │  [──────●──────────] 10        range: 1–500         │
  └─────────────────────────────────────────────────────┘
  ```
  - Slider track: `var(--border)`, filled portion: `var(--accent)`, thumb: 16px circle accent.
  - Current value displayed inline to the right of the slider, editable as a number input.
  - Each slider has a small reset icon (↺) that snaps it back to its default value.
  - Default values: Request Delay 500ms, Max Records 100, Max Pages 10.

**Section: Proxy**
- Toggle row + expandable textarea (host:port or host:port:user:pass, one per line) when ON.

**Drawer / panel footer:**
- "Preview & Run" (primary) | "Cancel" (ghost).

---

#### 7.2.B — Bulk Crawl Tab (Category only)

Accessible via the "Bulk" segment in the Category crawl type selector, **or** automatically navigated-to when the user clicks "Bulk Crawl" from the Category Crawl Complete page with pre-selected URLs.

- URL list textarea: large (min-height 200px), monospace, one URL per line.
- When arriving from Complete page: textarea is pre-populated with the selected URLs from the results table. Show a banner: "X URLs loaded from previous crawl results." (dismissible).
- Same Additional Fields, Proxy, and settings controls as standard Category Crawl.
- "Launch Bulk Crawl" primary button → same pre-run preview modal flow as standard crawl.

---

#### 7.2.C — Pre-run Preview Modal

Title: "Review Before Running"
- Target URL (monospace, truncated with tooltip).
- Estimated Scope: Pages × Records per page = Estimated total (table layout).
- Settings summary: Request delay, proxy status (Active/Inactive + proxy count), Smart Extraction ON/OFF.
- Additional Fields requested (if any): comma-separated chips.
- Manual fields (if any): count badge "X custom fields defined".
- Proxy Health (if proxy enabled): mini table — proxy host | status dot (green/red) | last response code.
- PDP only — "Detected Columns" table: column name | source | sample value.
- PDP only — LLM Cleanup note (if Smart Extraction ON): "LLM cleanup pass will run after extraction."
- Footer: "Cancel" (ghost) + "Launch Job" (primary, shows inline spinner on click, button locked until job confirmed dispatched).

---

#### 7.2.D — Crawl Running Page (Live Execution View)

**Triggered immediately after "Launch Job" is confirmed.** Replaces the configuration view with the live execution screen. No navigation away required — it is the same route, state-driven.

**Page header update:** Breadcrumb shows "Crawlers › [Crawl Type] › Running" + Run ID (monospace, --text-xs). Status badge (Running, pulsing) in the header.

**Layout: Two-panel**

```
┌──────────────────────┬─────────────────────────────────┐
│  LEFT: Progress Panel │  RIGHT: Live Log Stream          │
│  (30% width)         │  (70% width, terminal component) │
└──────────────────────┴─────────────────────────────────┘
```

**Left — Progress Panel:**
- Run ID, crawl type badge, target URL (truncated).
- Large progress ring or progress bar (records collected / max records).
- Stats: Records Collected, Pages Visited, Elapsed Time, Est. Remaining.
- Proxy status: "X / Y proxies active" with mini health dots.
- Additional Fields status: chips showing each requested field + whether it's been found (grey → green as found).
- Controls: Pause (secondary) | Resume (disabled until paused) | Hard Kill (danger).
- Paused state: amber banner "Job paused. Output so far is preserved. Click Resume to continue."

**Right — Live Log Stream:**
- Terminal component (see 6.10) set to full height of the panel.
- Always auto-scroll unless user scrolls up (show "↓ Jump to Latest" FAB).
- Log lines stream in real time via WebSocket or SSE.
- Filter bar above terminal: toggles for INFO | WARN | ERROR | PROXY (each toggles that level's visibility without clearing history).
- "Clear Display" ghost button — clears visual buffer only, does not affect stored logs.
- Logs captured here are the same logs that will appear in the Logs tab of the Complete page.

**Transition to Complete state:**
- When the job reaches `COMPLETED`, `KILLED`, or `FAILED`: animate the left panel to show a completion summary (green check / red X / grey skull icon based on status). Automatically transition the right panel to show the output tabs (see 7.2.E) after a 1.5s delay, or immediately on user click of "View Results" button that appears on completion.

---

#### 7.2.E — Crawl Complete Page (Output Workspace)

**Triggered when job status is `COMPLETED`, `KILLED` (partial), or `FAILED` (partial output).**

Page header: "Crawlers › [Crawl Type] › Complete" + Run ID + Status badge (Completed / Killed / Failed).

**Summary bar** (below page header, above tabs):
- Records collected | Duration | Pages visited | Fields extracted | Download All ▾ (CSV, JSON, Discoverist CSV).

**Tab bar:** Table | JSON | Intelligence | Logs

**Table Tab:**
- Dense data grid (see 6.4). Column headers = output fields.
- Checkbox column for row selection.
- Download bar above grid (right-aligned): "Download CSV" | "Download JSON" | "Download Discoverist CSV" buttons.
- **Category Crawl only — "Bulk Crawl" action button:**
  - Appears in the download bar area, styled as a secondary button with icon `ArrowRightCircle`.
  - Label: "Bulk Crawl Selected" — disabled when no rows are selected; shows count badge when rows are selected: "Bulk Crawl (12)".
  - On click: navigates to the Crawlers page → Category Crawl → **Bulk tab**, with the selected URLs pre-populated in the URL list textarea. Shows a brief transition toast: "12 URLs loaded into Bulk Crawl."
  - Tooltip on hover (when disabled): "Select rows to bulk crawl their URLs."

**JSON Tab:**
- Code block with syntax highlighting (JSON), full height.
- Copy button (top-right of code block) + Download JSON button.
- Prettified by default; "Compact" toggle to minify.

**Intelligence Tab (LLM Cleanup — PDP only):**
- Split-pane (left: raw, right: LLM suggestions).
- Left: raw field → value pairs per record, --text-sm, monospace values.
- Right: LLM suggestion rows: field name (inline editable) | suggested value | Accept ✓ | Reject ✗.
- "Accept All" / "Reject All" batch buttons at top of right pane.
- Confirmed rows dim and show "Accepted" (green chip) or "Rejected" (red chip).
- "Commit Accepted Fields" primary button at bottom — sends accepted columns to backend for storage. Disabled until at least one row is accepted.

**Logs Tab:**
- Full terminal component (see 6.10) showing the captured log output from the run.
- This is a historical read-only replay of the live log stream from 7.2.D.
- Filter bar (same toggles: INFO | WARN | ERROR | PROXY) + Search input (grep-style, highlights matching lines).
- "Download Logs" button (plain text file download).

---

### 7.3 Run History

**Filters bar** (top, sticky):
- Date range picker (start/end) | URL search input | Crawl Type multi-select | Status multi-select.
- "Clear Filters" ghost button.

**Table columns:**
Run ID | Crawl Type | Target URL | Started At | Duration | Status | Records | Triggered By | Actions.

**Row actions (on hover):**
View Output (icon) | Download ▾ (dropdown: CSV, JSON, Discoverist CSV) | Re-run (icon).

**Bulk actions bar (appears when rows selected):**
"X selected" + Download Selected (CSV) + Download Selected (JSON) + Delete Selected (danger).

---

### 7.4 XPath / CSS Selector Tool

**Layout:** Two-column split, resizable.
- **Left panel:** URL input at top → "Load Page" button → iframe-like preview area (or screenshot of the fetched page). User can click elements to highlight them.
- **Right panel:** List of field rows. Each row:
  - Field name (editable text input).
  - XPath/CSS input (monospace, with syntax validation indicator).
  - "Auto-detect" button (icon + label, triggers LLM suggestion — shows loading state).
  - Extracted value preview (--text-xs, --text-muted, monospace, below input).
  - Accept / Edit inline.
- "Add Field +" button below list.
- Save to Site Memory button (primary, drawer footer sticky).

---

### 7.5 Active Jobs (Command Center)

Full-page table, auto-refreshes every 5s (show last-refreshed timestamp, --text-xs, --text-muted).

**Table columns:**
Run ID | User | Crawl Type | Target URL | Progress (bar + count) | Status badge | Elapsed | Actions.

**Action buttons per row:** Pause | Resume | Hard Kill — each a small button with appropriate semantic color. Disabled states enforced per job state (e.g., can't Pause a PAUSED job).

**Global Kill Bar (Admin only):**
Fixed floating bar at bottom of screen.
bg var(--danger) at low opacity, border top 1px --danger at 30% opacity.
"Kill All Active Jobs" danger button center. Requires confirmation modal.

---

### 7.6 Admin Panel — User Management

**Table columns:**
Name | Email | Role (badge: Admin / User) | Status (Active/Inactive badge) | Registered | Actions.

**Row actions:**
Deactivate / Reactivate (toggle label based on state) | Change Role (segmented control or dropdown inline).

**Filters:** Search input (name or email) + Status filter (All / Active / Inactive).

---

### 7.7 Site Memory

**List of domains** (card per domain or table rows).
Each entry: Domain (monospace) | Field count | Last crawl timestamp | Actions (View / Edit / Delete).

**Expand / Detail view:**
Table of stored mappings: Field Name | Source | XPath/Regex | Last Updated.
Edit inline. Delete individual mapping with confirm popover.

**"Clear All Site Memory" button (Admin only):** Danger, requires confirm modal.

---

### 7.8 LLM Config (Admin only)

**Single focused card, max-width 560px, centered:**
- Provider selector (segmented: OpenAI | Anthropic | Custom).
- Model name input.
- API Key input (masked, with show/hide toggle icon).
- Endpoint URL input (shown only for Custom provider).
- "Test Connection" button (secondary) → shows inline success/error status with icon.
- "Save Configuration" button (primary, disabled until test passes or user acknowledges).

---

### 7.9 Settings (User-level)

- Profile section: Name, Email (read-only), change password link.
- Preferences: Theme toggle (Light / Dark / System), polling interval for active jobs (10s default), pagination size.
- Danger Zone: "Delete My Run History" — red section, confirm modal.

---

## 8. Animation & Motion

```
/* Micro-interactions */
--transition-fast:   100ms ease
--transition-base:   150ms ease
--transition-slow:   200ms ease

Rules:
- Hover state color changes: --transition-fast
- Button press (scale 0.97): --transition-fast
- Modal open/close: scale + fade, --transition-slow
- Drawer slide: --transition-slow
- Toast slide: --transition-slow
- Tab switch: fade content 100ms
- Progress bar fill update: 300ms ease
- Sidebar expand/collapse: width transition 200ms ease

No animation should exceed 300ms (keep it snappy / pro-tool feel).
Respect prefers-reduced-motion: wrap all animations in the media query.
```

---

## 9. Iconography

Use **Lucide Icons** (consistent stroke weight: 1.5px, size: 16px default, 20px for nav).

Key icons to use:
- Dashboard: `LayoutDashboard`
- Crawlers: `Globe` or `Spider` (custom fallback: `Network`)
- History: `History`
- Site Memory: `Database`
- Admin: `ShieldCheck`
- Settings: `Settings2`
- Active Jobs: `Activity`
- Pause: `PauseCircle`
- Resume: `PlayCircle`
- Kill: `XCircle`
- Download: `Download`
- Re-run: `RefreshCw`
- Auto-detect (AI): `Sparkles`
- Accept: `Check`
- Reject: `X`
- Log: `Terminal`
- Bulk Crawl redirect: `ArrowRightCircle`
- New Field add: `Plus`
- Field delete: `Trash2`
- Field drag handle: `GripVertical`
- Slider reset: `RotateCcw`
- Smart Extraction: `Sparkles`
- XPath valid: `CheckCircle`
- XPath invalid: `AlertCircle`
- Jump to log bottom: `ChevronsDown`

---

## 10. Responsiveness

This is a desktop-first internal tool. Minimum supported viewport: **1024px**.
- Below 1280px: sidebar collapses by default.
- Below 1024px: show a "best viewed on desktop" banner; don't attempt a mobile layout.
- Tables scroll horizontally within their container (never compress columns below readable width).
- Drawers: full-height, right-anchored. On 1024–1280px, drawers push the main content (don't overlay).

---

## 11. Accessibility

- All interactive elements have `:focus-visible` ring: `2px solid var(--accent)`, `2px offset`.
- Color alone never conveys meaning — always pair color with icon or text label (e.g., status badges always have a dot + text).
- All form inputs have associated `<label>` elements.
- Modals trap focus and restore on close.
- Tables use `<thead>`, `<tbody>`, `role="grid"` where applicable.
- Minimum contrast ratio 4.5:1 for all body text, 3:1 for large text / UI elements.

---

## 12. Implementation Notes for the Coding Agent

1. **CSS Custom Properties first.** Define all tokens in `:root` (light — the default) and `[data-theme="dark"]` (or `.dark`). Every component must consume tokens, never raw values.

2. **Theme toggle:** Persist in `localStorage`. Apply class/attribute to `<html>` element. **Default to `light`** on first load (no stored preference). On subsequent loads, restore from `localStorage`.

3. **Sidebar state:** Persist collapsed/expanded in `localStorage`.

4. **Polling:** Dashboard active-jobs count and Active Jobs page both poll. Use a shared polling hook/utility. Default interval: 10s (dashboard), 5s (active jobs page). Configurable via Settings.

5. **Data grid performance:** For tables with potentially thousands of rows, use virtual scrolling (e.g., `@tanstack/react-virtual` or equivalent).

6. **Log stream (live):** Use a WebSocket or SSE connection for real-time log delivery during the Crawl Running state (§7.2.D). Fall back to polling every 2s if WebSocket is unavailable. Auto-scroll logic: only auto-scroll if user is already at the bottom (within 50px). All log lines received during the live stream must be stored (in state or cache) so they can be replayed in the Logs tab of the Complete page (§7.2.E) without a second API call.

7. **Glassmorphism sidebar** requires `backdrop-filter`. Add a solid fallback background for browsers that don't support it.

8. **Sparklines:** Use a lightweight SVG sparkline (no full charting library needed). 8–10 data points, accent-colored filled area, no axes, no labels.

9. **LLM Cleanup accept/reject UI:** Each row has local state (pending / accepted / rejected). "Accept All" is a batch operation on all pending rows. Once committed, the state is sent to the backend and the UI shows a confirmation summary.

10. **Site Memory banner:** Mount once per page load when a domain match is found. Dismiss stores in session storage so it doesn't re-appear on the same session. Does not persist across sessions.

11. **Crawler page state machine.** The Crawlers page has three distinct states driven by job status, not by route change: `CONFIG` (setup form shown), `RUNNING` (live execution view, §7.2.D), and `COMPLETE` (output workspace, §7.2.E). Manage this via a top-level page state variable (e.g., `crawlPhase: 'config' | 'running' | 'complete'`). The URL may include the Run ID as a query param once a job is dispatched so the page can be refreshed and resume the correct state.

12. **Bulk Crawl navigation.** When "Bulk Crawl Selected" is clicked on the Complete page, pass the selected URLs via router state (not query params — URLs can be long). On the Crawlers page, detect the incoming state, switch to Category Crawl → Bulk tab, populate the textarea, and show the pre-population banner. Clear the router state after consuming it so a page refresh doesn't re-trigger the population.

13. **New Field rows.** Each manually added field row (§7.2.A) is an independent controlled form with its own validation state. XPath and Regex fields validate on blur using a lightweight parser (e.g., `wgxpath` for XPath, native `RegExp` constructor try/catch for Regex). Show a green `CheckCircle` or red `AlertCircle` icon inline inside the input's right padding. Never block the user from saving — just warn.

14. **Advanced Crawl sliders.** Each slider's value is mirrored in an adjacent number input. Editing the number input moves the slider thumb. Clamp on input blur. Store Advanced Crawl settings in the same config state object as standard settings so they are included in the pre-run preview payload regardless.

15. **Additional Fields.** Parse the comma-separated input into a string array on blur (trim whitespace, filter empties, deduplicate). Pass as `additional_fields: string[]` in the job dispatch payload. Display parsed chips below the input in real time as the user types, each removable with a ×.

16. **Default state on new crawl:** Always initialize with PDP Crawl tab selected, Smart Extraction OFF, Advanced Crawl OFF. Never persist the last-used crawl type as a default — always reset to PDP on "New Crawl" action.

---

*End of CrawlFlow Design System Prompt*