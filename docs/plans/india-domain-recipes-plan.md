# Plan: India-First Domain Recipes, Selector Promotion, and Saved Run Defaults

**Created:** 2026-04-23
**Agent:** Codex
**Status:** BLOCKED
**Touches buckets:** 1, 2, 3, 5, 6, frontend

## Goal

Turn the existing selector/domain-memory workflow into a real domain-recipe system for commerce, with phase-1 product emphasis on Indian commerce sites without regressing the already-working generic commerce path. Done means three things are true together: saved selectors are provably consumed during extraction, completed runs expose winning selectors plus reusable affordance hints for promotion into domain memory, and run configuration becomes a separate reusable domain execution profile with user-driven fetch and diagnostics controls that make future crawls easier, faster, and less error-prone without coupling run config to selector storage.

## Acceptance Criteria

- [ ] Saved selector rules from domain memory are provably applied during extraction on future runs for the same normalized `(domain, surface)`.
- [ ] Run-local manual selectors from `settings.extraction_contract` override saved selector rules for that run only and never rewrite domain memory unless explicitly promoted by the user.
- [ ] Completed commerce runs expose aggregated winning selector candidates by field plus reusable affordance hints for accordions, tabs, carousels, shadow hosts, iframe promotion, and browser-required signals.
- [ ] The completed-run workflow lets the user save or delete promoted selectors and edit/save one shared domain run profile for the run's normalized `(domain, surface)`.
- [ ] Future crawl setup auto-loads the saved domain run profile into the form for single-URL runs, labels it as a saved domain profile, and still lets explicit user edits win before dispatch.
- [ ] Saved run profiles are stored separately from selector memory and are limited to execution-profile settings: fetch profile, locality profile, and diagnostics profile. They do not persist selectors, proxies, LLM credentials/config, `max_records`, requested fields, or session/auth state.
- [ ] Acquisition honors a user-driven fetch profile with explicit `fetch_mode` and `extraction_source` instead of relying on a single `force_browser` toggle.
- [ ] The first crawl setup can remain intentionally expensive and exploratory, including optional LLM use and richer diagnostics capture, while future crawls can reuse the saved run profile through Quick Mode defaults.
- [ ] The phase-1 India focus is represented by a concrete priority cohort of Myntra, Ajio, Nykaa, Meesho, and IndiaMART, but generic commerce behavior and the broader regression manifest do not regress.
- [ ] Focused selector/runtime, acquisition/runtime, and run-complete UI coverage passes.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0.

## Do Not Touch

- `docs/plans/ACTIVE.md` — leave the current active-plan pointer unchanged until the baseline/remediation work is verified stable.
- Active baseline/remediation implementation work — this plan is queued follow-on work and must not be merged into the current stabilization slices.
- Generic shared runtime with site-name conditionals — no `if "myntra"` or equivalent branches in shared acquisition/extraction paths.
- Variant-fix architecture in `detail_extractor.py` — do not re-scope AP-12 known-bug work into this plan.
- Optional agent / commerce-enrichment work from `docs/VISION.md` — out of scope for this plan.

## Decision Lock

This plan is implementation-ready. Future agents should implement it directly and must not re-open product, API, or storage decisions unless the user explicitly changes scope. If code reality conflicts with one of the decisions below, record the conflict in `Notes`, make the smallest compatible adjustment, and continue. Do not re-plan from scratch.

## Anti-Bloat Rules

- Do not add a new policy engine, planner, manager, registry, or cross-cutting abstraction for run profiles.
- Keep `CrawlRunSettings` as the canonical run snapshot owner.
- Keep `crawl_fetch_runtime.py` as the fetch-strategy execution owner.
- Keep selector memory and run-profile persistence as separate concerns with separate storage fields or tables and separate API routes.
- Prefer replacing overloaded flat settings with a typed nested profile shape instead of adding more sibling booleans and flags to the existing settings blob.
- Delete stale or superseded frontend/API contracts when the new run-profile flow lands. Do not keep both paths alive.

## Locked Contracts

### Domain Recipe API

Add these routes to `backend/app/api/crawls.py` and type them in `backend/app/schemas/crawl.py`, `frontend/lib/api/types.ts`, and `frontend/lib/api/index.ts`.

1. `GET /api/crawls/{run_id}/domain-recipe`
   Returns:

   ```json
   {
     "run_id": 123,
     "domain": "www.example.com",
     "surface": "ecommerce_detail",
     "requested_field_coverage": {
       "requested": ["title", "price", "brand"],
       "found": ["title", "price"],
       "missing": ["brand"]
     },
     "selector_candidates": [
       {
         "candidate_key": "price|xpath|//*[@data-testid='price']",
         "field_name": "price",
         "selector_kind": "xpath",
         "selector_value": "//*[@data-testid='price']",
         "selector_source": "domain_memory",
         "sample_value": "Rs. 999",
         "source_record_ids": [456],
         "source_run_id": 123,
         "saved_selector_id": 22,
         "already_saved": true,
         "final_field_source": "dom_selector"
       }
     ],
     "affordance_candidates": {
       "accordions": [],
       "tabs": [],
       "carousels": [],
       "shadow_hosts": [],
       "iframe_promotion": null,
       "browser_required": false
     },
     "saved_selectors": [],
      "saved_run_profile": null
    }
    ```

2. `POST /api/crawls/{run_id}/domain-recipe/promote-selectors`
   Request:

   ```json
   {
     "selectors": [
       {
         "candidate_key": "price|xpath|//*[@data-testid='price']",
         "field_name": "price",
         "selector_kind": "xpath",
         "selector_value": "//*[@data-testid='price']",
         "sample_value": "Rs. 999"
       }
     ]
   }
   ```

   Response: the saved selector rows as normal selector records.

3. `POST /api/crawls/{run_id}/domain-recipe/save-run-profile`
   Request:

   ```json
   {
      "profile": {
        "version": 1,
        "fetch_profile": {
          "fetch_mode": "http_then_browser",
          "extraction_source": "rendered_dom",
          "js_mode": "enabled",
          "include_iframes": false,
          "traversal_mode": "paginate",
          "request_delay_ms": 1200,
          "max_pages": 8,
          "max_scrolls": 12
        },
        "locality_profile": {
          "geo_country": "IN",
          "language_hint": "en-IN",
          "currency_hint": "INR"
        },
        "diagnostics_profile": {
          "capture_html": true,
          "capture_screenshot": false,
          "capture_network": "matched_only",
          "capture_response_headers": true,
          "capture_browser_diagnostics": true
        }
      }
    }
    ```

   Response: the normalized saved run-profile payload.

Do not add delete endpoints for run-complete promotion. Deletion continues through existing selector CRUD using returned `saved_selector_id` values.

### Selector Promotion Rules

- Promote only selector candidates that directly contributed to a final field value in `record.data`.
- Never promote non-winning selector candidates.
- Never store affordances as selector rows.
- Deduplicate selector candidates by `(field_name, selector_kind, selector_value)` within the run payload.
- When promotion matches an existing saved selector for the same normalized `(domain, surface, field_name, selector_kind, selector_value)`, update that row's `sample_value`, `source`, and `is_active` instead of creating a duplicate.
- Save promoted selectors only to the exact `run.surface`. Do not save run-complete promotions to `generic`.
- Preserve current runtime behavior where exact-surface rules load first and generic rules may still exist as fallback if already present in storage.

### Domain Run Profile Contract

Persist run profiles separately from `DomainMemory.selectors`.

Storage decision:

- Preferred: add a new `DomainRunProfile` model keyed by normalized `(domain, surface)`.
- Acceptable fallback only if migration pressure is extreme: a separate `run_profile` top-level field on a non-selector persistence owner.
- Not allowed: storing run profile JSON inside `DomainMemory.selectors` or mixing profile state into selector rows.

The saved profile shape is:

```json
{
  "version": 1,
  "fetch_profile": {
    "fetch_mode": "auto",
    "extraction_source": "raw_html",
    "js_mode": "auto",
    "include_iframes": false,
    "traversal_mode": "auto",
    "request_delay_ms": 1000,
    "max_pages": 5,
    "max_scrolls": 8
  },
  "locality_profile": {
    "geo_country": "auto",
    "language_hint": null,
    "currency_hint": null
  },
  "diagnostics_profile": {
    "capture_html": true,
    "capture_screenshot": false,
    "capture_network": "off",
    "capture_response_headers": true,
    "capture_browser_diagnostics": true
  },
  "source_run_id": 123,
  "saved_at": "2026-04-23T12:34:56Z"
}
```

Rules:

- `fetch_profile.fetch_mode` enum is locked to:
  - `auto`
  - `http_only`
  - `browser_only`
  - `http_then_browser`
- `fetch_profile.extraction_source` enum is locked to:
  - `raw_html`
  - `rendered_dom`
  - `rendered_dom_visual`
  - `network_payload_first`
- `fetch_profile.js_mode` enum is locked to:
  - `auto`
  - `enabled`
  - `disabled`
- `fetch_profile.traversal_mode` reuses the existing traversal values already supported by frontend/backend:
  - `auto`
  - `scroll`
  - `load_more`
  - `view_all`
  - `paginate`
- `request_delay_ms`, `max_pages`, and `max_scrolls` use the same validation/clamping already used by crawl settings.
- `locality_profile` is intentionally minimal in v1 and exists to support the India-first focus without introducing a full session/cookie subsystem in this plan.
- `diagnostics_profile.capture_network` enum is locked to:
  - `off`
  - `matched_only`
  - `all_small_json`
- Excluded from saved profiles: selector rows, `proxy_enabled`, `proxy_list`, all LLM config and budgets, `max_records`, `requested_fields`, `additional_fields`, `respect_robots_txt`, cookies, auth/session state, and any user identifier.
- LLM remains a per-run toggle and is not persisted in the saved domain run profile.

### Saved Default Auto-Load Rules

- Auto-load saved domain run profiles only for single-URL crawl forms:
  - category single
  - PDP single
- Do not auto-load saved defaults for:
  - category bulk
  - PDP batch
  - PDP CSV upload
- When a saved profile is auto-loaded, show a UI message that the values came from the saved domain profile.
- User edits in the form always win over auto-loaded values before dispatch.
- The backend still snapshots the final resolved settings onto the run at creation time.
- The first-run UX is intentionally split:
  - `Quick Mode`: minimal controls, uses saved profile when present
  - `Advanced Mode`: full fetch/locality/diagnostics profile editing plus existing selector editor
- `Quick Mode` and `Advanced Mode` are UI presentation modes only. They are not separate persistence models.

### Crawl Studio Quick And Advanced Mode Contract

The missing UI split is locked as follows so future implementation does not invent extra controls:

- `Quick Mode` is for the normal repeat-run path and only shows:
  - target URL
  - saved-domain-profile banner with domain + surface label
  - `fetch_mode`
  - `llm_enabled`
  - one compact diagnostics preset selector
- `Advanced Mode` is for first-pass exploratory setup and shows:
  - everything in `Quick Mode`
  - `extraction_source`
  - `js_mode`
  - `include_iframes`
  - `traversal_mode`
  - `request_delay_ms`
  - `max_pages`
  - `max_scrolls`
  - `geo_country`
  - `language_hint`
  - `currency_hint`
  - `capture_html`
  - `capture_screenshot`
  - `capture_network`
  - `capture_response_headers`
  - `capture_browser_diagnostics`
  - existing manual selector/domain-memory editor

`Quick Mode` defaults, when no saved domain run profile exists yet:

- `fetch_mode=auto`
- diagnostics preset = `standard`
- `llm_enabled` keeps the existing per-run toggle default from Crawl Studio

`Quick Mode` diagnostics presets map to the saved run-profile payload exactly:

- `lean`
  - `capture_html=true`
  - `capture_screenshot=false`
  - `capture_network=off`
  - `capture_response_headers=true`
  - `capture_browser_diagnostics=true`
- `standard` (default)
  - `capture_html=true`
  - `capture_screenshot=false`
  - `capture_network=matched_only`
  - `capture_response_headers=true`
  - `capture_browser_diagnostics=true`
- `deep_debug`
  - `capture_html=true`
  - `capture_screenshot=true`
  - `capture_network=all_small_json`
  - `capture_response_headers=true`
  - `capture_browser_diagnostics=true`

Why this split is locked:

- Zyte's documented defaults already choose geolocation and JavaScript automatically unless explicitly overridden, so `geo_country` and `js_mode` belong in `Advanced Mode`, not `Quick Mode`.
- Zyte treats browser HTML, HTTP response body, screenshots, and network capture as separate request outputs, so `Quick Mode` should collapse those into a preset instead of exposing raw low-level capture toggles on the main form.
- Zyte documents `includeIframes=false` by default and network capture as capped/filtered, so iframe inclusion and broad payload capture remain advanced diagnostics controls only.

Explicit v1 exclusions from Crawl Studio, even in `Advanced Mode`:

- no viewport control
- no device-emulation control
- no session ID control
- no cookie editor
- no request-header editor beyond current generic runtime behavior

Reason: Zyte exposes those as lower-level request controls, but this plan's locked product contract is a reusable domain run profile, not a raw request builder. The current backend already owns browser identity and viewport behavior, and adding those controls here would be additive bloat.

### Fetch Profile Execution Rules

Run profile controls execution only. They do not modify selector memory.

Mapping rules:

- `fetch_mode=http_only`
  - disable browser escalation except for existing hard safety behavior already enforced by runtime
- `fetch_mode=browser_only`
  - skip HTTP-first fetch and go directly to browser acquisition
- `fetch_mode=http_then_browser`
  - explicit HTTP-first, browser fallback
- `fetch_mode=auto`
  - keep existing runtime heuristics and platform policy behavior

- `extraction_source=raw_html`
  - extraction prefers non-rendered HTML sources
- `extraction_source=rendered_dom`
  - extraction prefers browser-rendered DOM but not screenshot/visual coupling
- `extraction_source=rendered_dom_visual`
  - extraction allows rendered DOM plus visual fallbacks when available
- `extraction_source=network_payload_first`
  - extraction prioritizes captured network payloads before DOM-only fallbacks when payload evidence exists

Diagnostics rules:

- `capture_html=true` keeps current HTML artifact behavior
- `capture_screenshot=true` requests screenshot persistence for the run
- `capture_network=matched_only` stores matched network payloads only
- `capture_network=all_small_json` stores small JSON payloads within current byte caps
- `capture_response_headers=true` preserves response-header diagnostics for the run
- `capture_browser_diagnostics=true` keeps detailed browser-attempt diagnostics in artifacts/logs

### Selector Precedence Rules

For a running extraction, precedence is locked as:

1. exact-surface saved selector rules from domain memory
2. `generic` saved selector rules from domain memory, if any exist already
3. run-local `settings.extraction_contract`
4. built-in DOM pattern fallbacks

Conflict resolution is field-local:

- If the same field has both a saved selector rule and a run-local rule, the run-local rule wins for that run.
- If a field gets values from multiple selector sources, normal candidate ranking remains field-by-field and existing extractor invariants still apply.
- This plan does not replace the candidate system with record-level winner-takes-all behavior.

### Affordance Semantics

Affordances are not executable selectors and must be stored only as part of the saved domain run profile, not in selector memory and not in selector rows.

- `accordions`: stable expand/collapse targets that reveal requested or high-value detail content
- `tabs`: stable tab controls that switch visible requested/high-value detail content
- `carousels`: stable next/prev or slide containers relevant to image/detail reveal
- `shadow_hosts`: stable host selectors indicating requested content is behind shadow DOM
- `iframe_promoted`: boolean indicating selector preview or acquisition had to promote an iframe document
- `browser_required`: derived run-complete flag, not stored inside `interaction_hints`

`browser_required` is true only when the successful run required browser acquisition after the non-browser path was blocked, shell-only, or empty. A user choosing `fetch_mode=browser_only` does not by itself mark the site as browser-required unless the run evidence shows browser was actually needed for success.

## Slices

### Slice 1: Queue Gate And India Cohort Definition
**Status:** BLOCKED
**Files:** `docs/plans/india-domain-recipes-plan.md`, `backend/test_site_sets/commerce_india_priority.json`, acceptance helpers as needed
**What:** Keep this plan blocked until the active baseline work has a verified green checkpoint. Define the phase-1 India priority cohort used by this plan's acceptance checks: Myntra, Ajio, Nykaa, Meesho, and IndiaMART. Add a dedicated India-priority acceptance manifest after baseline is stable, but keep the broader generic commerce manifest authoritative for non-regression. This slice creates the cohort file and acceptance expectations only; it does not introduce site-specific branches in runtime code.
**Verify:** Baseline/top-50 acceptance remains the non-regression gate, and the new India-priority manifest runs independently after baseline stabilization.

### Slice 2: Prove And Correct Saved-Selector Runtime Usage
**Status:** TODO
**Files:** `backend/app/services/pipeline/core.py`, `backend/app/services/domain_memory_service.py`, `backend/app/services/field_value_dom.py`, `backend/tests/services/test_selector_pipeline_integration.py`
**What:** Audit and lock selector precedence so runtime behavior is explicit and tested. Implement the exact precedence rules in `Locked Contracts`, including support for pre-existing `generic` rules as fallback but saving new promoted rules only to exact surface. Simplify duplicate rule assembly into one canonical load path. Do not widen or loosen `(domain, surface)` lookup rules.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_selector_pipeline_integration.py -q`

### Slice 3: Record Exact Worked-Selector Provenance
**Status:** TODO
**Files:** `backend/app/services/field_value_dom.py`, `backend/app/services/detail_extractor.py`, `backend/app/services/listing_extractor.py`, `backend/tests/services/test_crawl_engine.py`
**What:** Extend extraction provenance so selector-backed fields record the exact worked rule rather than only a generic `dom_selector` source. Persist the trace under `record.source_trace.field_discovery[field_name].selector_trace` with this exact shape:

```json
{
  "selector_kind": "xpath",
  "selector_value": "//*[@data-testid='price']",
  "selector_source": "domain_memory",
  "selector_record_id": 22,
  "source_run_id": 123,
  "sample_value": "Rs. 999",
  "page_url": "https://example.com/p/1",
  "survived_to_final_record": true
}
```

Only write `selector_trace` for fields that reached `record.data`. Keep executable selectors separate from affordance hints.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py -q`

### Slice 4: Aggregate Promotion Candidates After Completed Runs
**Status:** TODO
**Files:** `backend/app/api/crawls.py`, `backend/app/services/review/__init__.py`, `backend/app/schemas/selectors.py`, `frontend/lib/api/types.ts`, `frontend/lib/api/index.ts`, `frontend/components/crawl/crawl-run-screen.tsx`
**What:** Add the exact `GET /api/crawls/{run_id}/domain-recipe` route from `Locked Contracts`. Aggregate by field and affordance type instead of returning raw per-record candidates. Build `candidate_key` as `{field_name}|{selector_kind}|{selector_value}`. `source_record_ids` are sorted unique record IDs. `already_saved` is true when a matching saved selector already exists for the same normalized `(domain, surface, field_name, selector_kind, selector_value)`. Delete the stale frontend `previewSelectors()` contract and `ReviewSelectorPreview` type instead of layering a second unused promotion path on top.
**Verify:** Backend API tests for the new run-recipe payload and frontend tests for grouped selector/affordance rendering on the completed-run page.

### Slice 5: Introduce A Separate Domain Run Profile
**Status:** TODO
**Files:** `backend/app/models/crawl.py`, `backend/alembic/versions/*`, `backend/app/services/crawl_crud.py`, `backend/app/models/crawl_settings.py`, a minimal run-profile service module if needed
**What:** Add a separate `DomainRunProfile` persistence owner keyed by normalized `(domain, surface)`. Persist exactly the payload shape from `Locked Contracts`. Do not extend selector storage for this. Normalization rules:

- omit unknown keys
- coerce empty-string numeric inputs to `null`
- clamp numeric values using existing crawl-setting limits
- always stamp `source_run_id` and UTC `saved_at` on save

Future-run setting resolution must be: generic UI defaults, then saved domain run profile, then explicit user edits in the crawl form, then backend snapshotting in `create_crawl_run`.
**Verify:** Migration/model round-trip coverage plus crawl-creation tests proving saved-default merge precedence.

### Slice 6: Replace Flat Fetch Flags With A User-Driven Fetch Profile
**Status:** TODO
**Files:** `frontend/components/crawl/crawl-config-screen.tsx`, `frontend/components/crawl/crawl-config-screen.test.ts`, `backend/app/services/crawl_fetch_runtime.py`, `backend/app/services/acquisition/browser_detail.py`, `backend/tests/services/test_crawl_fetch_runtime.py`
**What:** Replace the plan's old `force_browser` concept with the explicit fetch profile from `Locked Contracts`. Add `Quick Mode` and `Advanced Mode` in the crawl UI:

- `Quick Mode`:
  - target URL
  - saved-profile banner
  - fetch mode
  - LLM toggle
  - diagnostics preset with exact values from `Crawl Studio Quick And Advanced Mode Contract`
- `Advanced Mode`:
  - full field set from `Crawl Studio Quick And Advanced Mode Contract`
  - existing traversal controls mapped into `fetch_profile.traversal_mode`

Acquisition must honor `fetch_profile.fetch_mode` exactly. Saved affordance hints may still be consumed only through bounded existing browser-detail flows; they may prioritize known accordions/tabs/carousels/shadow hosts but must never navigate away from the page or turn into arbitrary click automation. Do not add generic listing traversal behavior driven by these hints in this plan. Remove or deprecate any now-redundant flat fetch flags created only for the old plan direction.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_fetch_runtime.py -q`

### Slice 7: Completed-Run Save/Edit Workflow
**Status:** TODO
**Files:** `frontend/components/crawl/crawl-run-screen.tsx`, related frontend tests, backend promote/save handlers
**What:** Add a completed-run "Domain Recipe" panel that uses the exact routes from `Locked Contracts`. UI requirements:

- section 1: requested-field coverage summary
- section 2: selector candidates grouped by field
- section 3: affordance hints grouped by type
- section 4: editable domain run-profile form

Button behavior:

- "Save Selected Selectors" posts only checked selector candidates to `promote-selectors`
- "Save Run Profile" posts the normalized run-profile form to `save-run-profile`
- "Delete Saved Selector" uses existing selector CRUD against the returned `saved_selector_id`

Show which selector candidates are already saved versus new from the current run. Keep this as the primary first-pass promotion workflow rather than forcing the user into the standalone selector tool. The completed-run page is also where an expensive exploratory run can be converted into a reusable cheaper default for future runs.
**Verify:** Frontend tests for loading existing recipe state, saving edited run profile, promoting selectors from a completed run, and rendering requested-field coverage plus existing/new markers.

### Slice 8: Docs And Acceptance Closure
**Status:** TODO
**Files:** `docs/backend-architecture.md`, `docs/BUSINESS_LOGIC.md`, `docs/CODEBASE_MAP.md` if ownership changes, `docs/INVARIANTS.md` only if a contract changes
**What:** Update canonical docs to describe selector provenance, post-run recipe promotion, separate domain run-profile behavior, and the new completed-run UI flow. Add the India-priority acceptance cohort without weakening the broader generic commerce regression gate. Close the plan only after targeted tests and full-suite verification pass.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` and the applicable acceptance manifest runs after baseline is stable.

## Doc Updates Required

- [ ] `docs/backend-architecture.md` — document selector provenance, run-recipe promotion API, and the separate domain run-profile model with fetch/locality/diagnostics sections
- [ ] `docs/BUSINESS_LOGIC.md` — document the new user-visible run-complete promotion flow, Quick/Advanced Mode behavior, and saved-domain-profile precedence rules
- [ ] `docs/CODEBASE_MAP.md` — update only if new files/routes materially change ownership or add non-obvious new assets
- [ ] `docs/INVARIANTS.md` — update only if a must-preserve selector/runtime contract changes
- [ ] `docs/ENGINEERING_STRATEGY.md` — update only if implementation uncovers a new recurring anti-pattern

## Notes

- This plan is intentionally saved without changing `docs/plans/ACTIVE.md` because the active baseline/remediation work must remain authoritative until it is verified stable.
- Current repo fact: `docs/plans/ACTIVE.md` points to `docs/plans/AGENT_TASK_BASELINE_TO_MANIFEST.md`, but that file does not exist. Do not "fix" that pointer as part of this plan unless the user explicitly asks for active-plan cleanup.
- Current repo fact: saved selector rules are already loaded into the runtime path in `backend/app/services/pipeline/core.py`; this plan assumes the implementation focus is proving/fixing actual precedence and provenance rather than inventing first-use wiring.
- Current repo fact: the completed-run UI in `frontend/components/crawl/crawl-run-screen.tsx` does not yet expose a recipe-promotion workflow, and selector response schemas do not yet expose `source_run_id`, `created_at`, or `updated_at`.
- Memory scope is intentionally global shared for v1, matching the user's product decision. Future multi-tenant hardening may revisit this, but it is out of scope here.
- Phase-1 India focus is product prioritization, not shared-runtime hardcoding. The targeted cohort exists to sharpen acceptance and UX priorities, not to justify platform-name branches in generic services.
- Shadow DOM items are affordance hints unless they are proven executable selectors through the existing selector runtime.
- The old plan direction that attached saved run config directly to selector/domain memory is superseded. Run profile and selector memory are intentionally separate so the system becomes simpler, not more layered.
- The current crawl settings blob is too flat and overloaded. The implementation should migrate toward the nested run-profile shape by replacing sibling flags, not by adding parallel copies of the same concept.
- Implementation order is locked as Slice 1 -> Slice 2 -> Slice 3 -> Slice 4 -> Slice 5 -> Slice 6 -> Slice 7 -> Slice 8. Do not reorder Slice 4-7; the run-complete UI depends on the API and storage contracts being in place first.
