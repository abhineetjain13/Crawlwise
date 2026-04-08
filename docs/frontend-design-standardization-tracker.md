# Frontend Design Standardization Tracker

Source: `docs/frontend-design-standardization-plan.md`

## Status Key
- `todo`
- `in_progress`
- `done`
- `blocked`

## Phase 1 - Guardrails and Inventory

| ID | Status | Item | Notes |
|---|---|---|---|
| DS-P1-1 | done | Create design standardization plan | Added `frontend-design-standardization-plan.md` |
| DS-P1-2 | done | Create execution tracker checklist | This file |
| DS-P1-3 | in_progress | Inventory hardcoded one-off styles and duplicate primitives | Deep audit findings captured; migration still ongoing |

## Phase 2 - Primitive Consolidation

| ID | Status | Item | Notes |
|---|---|---|---|
| DS-P2-1 | done | Normalize auth error alerts to shared primitive | Login/register now use `InlineAlert` |
| DS-P2-2 | done | Consolidate crawl tab primitive usage | `components/crawl/shared.tsx` tab now delegates to canonical `patterns.TabBar` |
| DS-P2-3 | done | Introduce shared `StatusDot` primitive and adopt in runs/dashboard | Added `StatusDot` in `components/ui/patterns.tsx`, adopted in runs, dashboard, and crawl run summary |
| DS-P2-4 | done | Standardize shared surface/panel wrapper usage | Added `SurfacePanel` in `components/ui/patterns.tsx`; migrated runs and dashboard wrapper shells |

## Phase 3 - Tokenization and Typographic Consistency

| ID | Status | Item | Notes |
|---|---|---|---|
| DS-P3-1 | done | Remove `bg-white` hardcoding in selectors preview containers | Switched to token-backed classes |
| DS-P3-2 | done | Remove hardcoded theme boot script background values | Theme script now sets only `data-theme`; CSS owns backgrounds |
| DS-P3-3 | done | Replace arbitrary px typography classes in shared patterns/primitives | Added semantic typography utilities in `globals.css`; migrated `components/ui/patterns.tsx` and `components/ui/primitives.tsx` away from hardcoded px text classes |
| DS-P3-4 | done | Move remaining one-off color literals into globals tokens | Tokenized terminal and markdown code surface colors in `globals.css` and removed hardcoded page canvas literals |

## Phase 4 - Table and Data Surface Unification

| ID | Status | Item | Notes |
|---|---|---|---|
| DS-P4-1 | done | Unify table visual contract across runs/jobs/admin/crawl | Added shared `TableSurface` pattern and migrated runs/jobs/admin users tables to consistent surface + overflow contract; crawl records table now uses shared state surfaces around table region |
| DS-P4-2 | done | Normalize empty/loading/error states through shared patterns | Added `DataRegionLoading`, `DataRegionEmpty`, and `DataRegionError` patterns; replaced ad-hoc loading/empty/error blocks in runs/jobs/crawl-run/admin/dashboard data regions |

## Phase 5 - Crawl-Specific Decomposition

| ID | Status | Item | Notes |
|---|---|---|---|
| DS-P5-1 | done | Split `components/crawl/shared.tsx` into DS primitives vs crawl composition | Moved reusable run workspace primitives (`RunWorkspaceShell`, `RunSummaryChips`) to canonical `components/ui/patterns.tsx`; crawl module now keeps crawl-specific helpers |
| DS-P5-2 | done | Remove remaining crawl-specific duplicate style APIs | Removed duplicate crawl tab/output APIs (`TabBar`, `SegmentedMode`, `OutputTab`) from crawl shared and switched usage to canonical `patterns.TabBar` |

## Running Crawl Page Redesign Slices

| ID | Status | Item | Notes |
|---|---|---|---|
| DS-RUN-1 | done | Extract `RunWorkspaceShell` layout wrapper | Added reusable shell slots (header/actions/tabs/summary/content) and adopted in `crawl-run-screen.tsx` |
| DS-RUN-2 | done | Add `RunSummaryChips` and consistent hierarchy | Added compact metric chips for time/verdict/quality; wired into run workspace tab header |
| DS-RUN-3 | done | Replace `OutputTab` with canonical tab primitive | `crawl-run-screen.tsx` now uses `patterns.TabBar` for output tabs |
| DS-RUN-4 | done | Tokenize terminal/log one-off colors | `crawl-terminal` and markdown code block colors now use theme tokens |
| DS-RUN-5 | done | Normalize panel heights and action alignment | Standardized completed-run tab panel minimum heights and aligned header action grouping via shell layout |
