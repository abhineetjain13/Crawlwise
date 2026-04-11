# Re-crawl Quality and LLM Plan

Last updated: 2026-04-08  
Scope owner: Crawl pipeline + Crawl Studio frontend  
Status: Draft for review

---

## Objective

Add an explicit user-controlled rerun flow for low-quality outcomes without introducing hidden backend behavior:

1. Deterministic deep rerun (higher extraction budget, no LLM)
2. Deterministic + LLM enrichment rerun (LLM only after deterministic pass)

The user can trigger reruns from run results, compare outcomes, and keep full control over cost/time/quality trade-offs.

---

## Non-Goals

- No automatic LLM enablement.
- No site-specific logic.
- No silent rewriting of user-owned controls (`surface`, `advanced_mode`, `llm_enabled`, proxies).
- No replacement of deterministic extraction with LLM-first extraction.

---

## Product Decisions (Decision-Complete)

- **Rerun is explicit:** add UI actions only in terminal runs.
- **Rerun creates a new run:** no in-place mutation of existing run data.
- **Two rerun profiles only:**
  - `deep_deterministic`
  - `deep_plus_llm`
- **LLM scope:** fill missing or low-confidence fields only; never overwrite high-confidence deterministic fields by default.
- **Auditability:** every rerun stores `rerun_of_run_id`, `quality_profile`, and `llm_enrichment_used`.

---

## Architecture Decisions

- **Budget policy is config-driven:** extraction traversal/scan/time budgets must live in config, not hardcoded in service flow.
- **Quality profile is a run setting:** resolved in backend from profile name, persisted in run settings for traceability.
- **Deterministic-first invariant:** extraction order remains deterministic-first; LLM is post-pass enrichment.
- **Observability requirement:** per-stage timing and quality deltas are logged and persisted for comparison.

---

## Backend Contract Changes

## 1) Run settings additions

Persist on created rerun:

- `settings.quality_profile`: `"normal" | "deep_deterministic" | "deep_plus_llm"`
- `settings.rerun_of_run_id`: integer or null
- `settings.llm_enrichment_enabled`: boolean
- `settings.deep_budget`: optional resolved budget snapshot (for diagnostics)

## 2) API endpoints

- `POST /api/crawls/{run_id}/rerun`
  - Request:
    - `quality_profile`: required
    - optional overrides (`max_pages`, `max_records`, etc.) with strict validation
  - Behavior:
    - clone original run payload/settings
    - apply explicit profile policy
    - create new run
    - return `{ run_id: <new_id>, parent_run_id: <old_id> }`

- `GET /api/crawls/{run_id}/comparison?other_run_id=<id>`
  - Returns:
    - record count delta
    - requested field coverage delta
    - verdict delta
    - top missing fields before/after

## 3) Pipeline runtime behavior

- Resolve profile to extraction budgets:
  - recursion depth
  - structured scan budgets
  - per-URL timeout
  - optional browser preference
- Keep deterministic extraction unchanged in ordering.
- If profile includes LLM:
  - run enrichment only on missing/weak fields
  - store source trace as `llm_enrichment`
  - do not overwrite deterministic values unless explicit future option

---

## Frontend Contract Changes

- Add action group on run result page:
  - `Re-crawl (Better Quality)`
  - `Re-crawl + LLM Enrichment`
- Show clear confirmation modal:
  - expected slower runtime
  - whether LLM is used
- After trigger:
  - navigate to new run
  - show parent run linkage
- Add optional comparison panel for parent vs rerun.

---

## Implementation Slices

## Slice A: Profile config + plumbing

- Add typed quality profile config module.
- Resolve profile in run creation/rerun flow.
- Persist profile metadata in run settings and result summary trace.

Acceptance:
- New runs carry profile metadata.
- No behavior changes for default profile.

## Slice B: Rerun API and backend cloning flow

- Implement `POST /api/crawls/{id}/rerun`.
- Validate ownership and allowed profiles.
- Clone original settings with explicit profile overrides.

Acceptance:
- Rerun produces a new run ID and keeps user-owned controls unchanged unless user-selected profile demands only budget changes.

## Slice C: UI rerun actions

- Add two rerun buttons and confirmation UX.
- Add success state and navigation to new run.

Acceptance:
- User can trigger either rerun from terminal run view.

## Slice D: LLM enrichment pass (opt-in profile only)

- Add post-deterministic enrichment hook.
- Restrict to missing/low-confidence requested fields.
- Persist provenance for enriched fields.

Acceptance:
- LLM profile changes only allowed fields; deterministic fields remain stable.

## Slice E: Comparison + telemetry

- Add backend comparison response and frontend summary card.
- Emit telemetry for rerun reason, delta quality, runtime delta.

Acceptance:
- Parent/rerun quality and cost delta is visible.

---

## Risks and Mitigations

- **Risk: hidden policy drift** -> enforce explicit `quality_profile` in run settings and logs.
- **Risk: quality regressions from hard caps** -> make budgets profile-configurable, add low-yield rerun checks.
- **Risk: LLM hallucination** -> missing-field-only enrichment, provenance tags, deterministic precedence.
- **Risk: longer runtimes** -> user-visible profile labels and expected runtime messaging.

---

## Testing Strategy

- Backend:
  - rerun endpoint auth/ownership tests
  - profile resolution tests
  - deterministic-first precedence tests
  - LLM enrichment gating tests
  - parent/rerun comparison contract tests
- Frontend:
  - rerun action button tests
  - modal flow and API trigger tests
  - navigation to new run
  - comparison widget rendering tests
- Integration:
  - low-quality baseline run -> deep rerun improves or equals requested-field coverage
  - deep+LLM rerun improves missing fields without clobbering deterministic values

---

## Immediate Recommendation for Current Timeout Fix

Short-term until rerun feature lands:

- Keep:
  - frontend timestamp parsing fix (UTC handling)
  - removal of premature "stuck" warning
  - authenticated export download fix
  - JSON-LD-first shortcut for listing pages when viable records already exist
- Revisit in next PR:
  - hardcoded structured traversal caps introduced during timeout hotfix
  - move all such budgets into profile/config system

This keeps runs stable now while aligning future implementation with explicit quality profiles instead of one-off heuristics.
