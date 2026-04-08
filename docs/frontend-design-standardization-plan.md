# Frontend Design Standardization Plan

Date: 2026-04-08  
Scope: `frontend/` design consistency, style debt reduction, and running crawl page redesign.

## Current State Check

From the frontend tracker and latest implementation pass:
- Functional frontend audit backlog items are completed.
- Core reliability/perf items are complete (tests, polling, logs cursor, websocket logs, table pagination + virtualization).

Design and standardization debt remains and is tracked by this plan.

## Design Audit Findings (Deep)

1. Duplicate tab systems exist (`patterns.TabBar`, `crawl/shared.TabBar`, `OutputTab`), causing inconsistent behavior and visual drift.
2. Card/surface wrappers are repeatedly authored inline instead of composed through a single primitive.
3. Typography relies heavily on arbitrary pixel classes (`text-[11px]`, `text-[13px]`, etc.) instead of semantic utilities.
4. Several hardcoded one-off colors/surfaces exist (`bg-white`, `#141414`, `#d4d4d8`, overlay literals), bypassing theme tokens.
5. Alert/error patterns are partially standardized (`InlineAlert`) but still duplicated in auth/config pages.
6. Status presentation logic is centralized in `lib/ui/status.ts` but rendered with mixed inline style patterns.
7. Table styling is fragmented across global class, ad-hoc table markup, and page-specific composition.
8. Crawl components in `components/crawl/shared.tsx` have evolved into a parallel mini design system.
9. Spacing/radius conventions still include many one-off values and bespoke layout fractions.
10. Running crawl page has state-dependent layout shifts (active vs terminal) that reduce continuity.

## Standardization Principles

1. Token-first styling: color/spacing/typography should come from `globals.css` variables and semantic utilities.
2. Primitive-first composition: pages should compose from shared primitives/patterns, not re-author the same surface/tabs/alerts.
3. One component per role: tab, panel, status-dot, and alert variants should each have a single canonical implementation.
4. One-off styles allowed only when:
   - they are isolated to a unique interaction/brand moment, and
   - they are intentionally documented in the component.

## Phased Technical Debt Removal Plan

## Phase 1: Guardrails and Inventory (Low Risk)

- Create a short style governance note in `docs/`:
  - allowed: tokenized colors and semantic text utilities
  - discouraged: raw hex colors and arbitrary px text classes
  - exception policy for true one-off visuals
- Inventory duplicates:
  - tabs
  - card wrappers
  - alerts
  - table wrappers
  - status dots/chips

Deliverable: baseline debt map and migration checklist.

## Phase 2: Primitive Consolidation (High ROI)

- Consolidate to one tab primitive and remove crawl-specific duplicates.
- Add/standardize shared `Panel` or `SurfaceCard` wrapper usage.
- Normalize alert rendering to `InlineAlert` (or a single alert API).
- Add shared `StatusDot` primitive powered by `lib/ui/status.ts`.

Deliverable: reduced primitive duplication and consistent interactions.

## Phase 3: Tokenization and Typographic Consistency

- Replace hardcoded one-off colors with token variables in `globals.css`.
- Replace arbitrary text pixel classes with semantic typography utilities (caption/label/body/meta).
- Move recurring spacing/radius literals into utility aliases or token-backed classes.

Deliverable: theme-safe and scale-consistent styling.

## Phase 4: Table and Data Surface Unification

- Standardize table presentation around one canonical table contract.
- Keep virtualization and pagination behavior, but unify visual style and row density.
- Normalize loading/empty/error states via shared patterns.

Deliverable: consistent data-display language across runs/jobs/admin/crawl.

## Phase 5: Crawl-Specific Decomposition

- Split `components/crawl/shared.tsx` into:
  - design-system-aligned reusable pieces
  - crawl-only composition wrappers
- Remove any remaining style APIs that duplicate global primitives.

Deliverable: crawl UX aligns with global system, not a parallel style layer.

## Running Crawl Page Redesign Plan (`crawl-run-screen.tsx`)

Goal: improve visual continuity and hierarchy without changing behavior.

### Target Direction

- Single persistent workspace shell across active and terminal states.
- Stable top summary strip (status, verdict, quality, duration, records, actions).
- Tabs remain in one location regardless of run state.
- Logs keep realtime behavior (websocket + fallback) but with clearer prominence when run is active.

### Implementation Slices

1. Extract `RunWorkspaceShell` layout component (header/actions/tabs/content slots).
2. Introduce `RunSummaryChips` for consistent metric/status hierarchy.
3. Replace `OutputTab` and crawl-specific tab variants with canonical tab primitive.
4. Tokenize terminal/log color literals via global variables.
5. Normalize panel heights and action alignment for table/json/markdown/log tabs.

### Non-Goals for This Redesign

- No API contract changes.
- No run-control behavior changes.
- No backend event changes.

## Execution Order Recommendation

1. Phase 2 (primitive consolidation) and run-screen slice 1/2 together.
2. Phase 3 tokenization pass.
3. Phase 4 table surface unification.
4. Phase 5 crawl shared decomposition.

This order gives visible UX consistency gains early while minimizing regression risk.
