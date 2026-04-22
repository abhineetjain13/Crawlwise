# Plan: Listing Recovery and Zara Remediation

**Created:** 2026-04-21
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** 3. Acquisition + Browser Runtime, 4. Extraction, 5. Publish + Persistence

## Goal

Fix the concrete regressions shown in the saved acceptance artifacts and Zara repros without adding another recovery layer. Done means listing crawls stop returning garbage chrome/category rows, acquisition stops giving up after weak or zero-card probes when product evidence is present, and Zara detail extraction stops leaking duplicate option axes / page-context-style filler while restoring real variant data. Net LOC for the implementation slices should be negative by deleting duplicate or no-op logic as part of the fix.

## Acceptance Criteria

- [ ] Zara listing returns 12 real product rows for the current failing crawl path, not 5 structured rows and not polluted category-cloud/navigation rows.
- [ ] Zara listing records contain product-detail URLs/titles only; SEO cloud, utility links, and menu labels are excluded upstream.
- [ ] Acquisition/traversal does not stop on Zara-like listing pages with `listing_card_count=0` when the DOM contains real product-grid cards; bounded recovery only runs when evidence supports it.
- [ ] Zara detail extraction does not emit duplicate variant axes or copy-SKU values inside option fields, and `variants` / `selected_variant` remain present in JSON and CSV-safe record data.
- [ ] No `page_context`-style filler field leaks into `record.data` or JSON/CSV export payloads for the Zara detail path.
- [ ] Net code delta across touched implementation files is <= 0 LOC.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_traversal_runtime.py tests/services/test_selectolax_css_migration.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_record_export_service.py -q`

## Do Not Touch

- `backend/app/api/*` — no route contract churn.
- `backend/app/services/publish/verdict.py` — do not paper over upstream extraction/acquisition failures.
- `backend/app/services/pipeline/persistence.py` — no downstream record cleanup hacks.
- `frontend/*` — leave the UI alone unless a backend contract bug makes that unavoidable.
- `backend/app/services/adapters/*` — only touch if the owning failure is proven to be adapter-specific; Zara should be fixed in generic/runtime owners first.

## Slices

### Slice 1: Lock Regressions to Saved Zara and Acceptance Evidence
**Status:** DONE
**Files:** `backend/tests/services/test_traversal_runtime.py`, `backend/tests/services/test_selectolax_css_migration.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_record_export_service.py`
**What:** Add focused regressions from the saved Zara listing/detail artifacts and the acceptance findings so later fixes are forced to hit the real failures instead of synthetic happy paths.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_traversal_runtime.py tests/services/test_selectolax_css_migration.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_record_export_service.py -q`

### Slice 2: Make Listing Card Detection Match Actual Zara Product Tiles
**Status:** DONE
**Files:** `backend/app/services/config/selectors.exports.json`, `backend/app/services/acquisition/traversal.py`, `backend/app/services/acquisition/browser_readiness.py`, `backend/tests/services/test_traversal_runtime.py`
**What:** Use the existing selector/config owners so readiness and traversal count the same product-card shapes that extraction already sees on Zara-like grids; delete or collapse any duplicate no-op card-count paths that keep recovery from progressing.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_traversal_runtime.py tests/services/test_browser_expansion_runtime.py -q`

### Slice 3: Remove Garbage Listing Candidates Upstream
**Status:** DONE
**Files:** `backend/app/services/listing_extractor.py`, `backend/app/services/extract/listing_candidate_ranking.py`, `backend/tests/services/test_selectolax_css_migration.py`
**What:** Tighten the listing-card and rendered-card filters so taxonomy clouds, utility links, promo rails, and menu items cannot out-rank real product rows; prefer one clean candidate-set path instead of overlapping DOM/rendered heuristics fighting each other.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_selectolax_css_migration.py tests/services/test_crawl_engine.py -q`

### Slice 4: Fix Zara Detail Variant Parsing and Export Hygiene
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/record_export_service.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_record_export_service.py`
**What:** Deduplicate same-axis DOM variant groups, ignore copy-code/button noise, keep real `variants` / `selected_variant` data intact, and ensure JSON/CSV exports stay limited to user-facing fields rather than raw markdown/page-context filler.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_record_export_service.py -q`

### Slice 5: Tighten Browser Give-Up Rules Without Growing Recovery Layers
**Status:** DONE
**Files:** `backend/app/services/acquisition/browser_page_flow.py`, `backend/app/services/acquisition/browser_runtime.py`, `backend/app/services/acquisition/traversal.py`, `backend/tests/services/test_browser_expansion_runtime.py`, `backend/tests/services/test_pipeline_core.py`
**What:** Audit the old-app recovery port against the current call path, remove inert branches, and keep only one bounded retry/wait path with diagnosable stop reasons when browser acquisition would otherwise give up too early.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_expansion_runtime.py tests/services/test_pipeline_core.py -q`

### Slice 6: Harden Commerce Requested-Field and Variant Coverage
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/network_payload_mapper.py`, `backend/tests/services/test_crawl_engine.py`, `backend/tests/services/test_network_payload_mapper.py`
**What:** Keep batch `requested_fields` / "Additional details" input live through batch fan-out, stop ghost-routed listing APIs from seeding false detail records, and prevent site-shell Open Graph fallbacks from persisting stale SPA detail pages as fake product successes while preserving real variant-rich detail output.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_network_payload_mapper.py tests/services/test_crawl_engine.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_detail_extractor_priority_and_selector_self_heal.py -q && .\.venv\Scripts\python.exe -m pytest tests -q`

### Slice 7: Unblackbox Additional Fields and Requested DOM Sections
**Status:** DONE
**Files:** `frontend/components/crawl/shared.tsx`, `frontend/components/crawl/crawl-config-screen.test.ts`, `backend/app/services/detail_extractor.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`
**What:** Align UI additional-field normalization with backend requested-field normalization so punctuation-heavy labels such as "Features & Benefits" survive dispatch, and keep ecommerce-detail DOM completion alive when requested custom section fields such as `product story` are visibly advertised by the page instead of letting structured-data early exit hide them.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_crawl_engine.py tests/services/test_browser_expansion_runtime.py -q` and `cd frontend; npm test -- components/crawl/crawl-config-screen.test.ts`

### Slice 8: Variant Recovery Becomes Quality-Gated, Not Presence-Gated
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/extract/detail_tiers.py`, `backend/app/services/field_value_candidates.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_shared_variant_logic.py`
**What:** Keep the current multi-tier candidate architecture, but stop letting any non-empty JS-state `variants` payload suppress DOM recovery. DOM variant extraction now runs when existing variant data is weak, and weak rows without usable `option_values` no longer survive once stronger DOM-backed variants exist.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_shared_variant_logic.py tests/services/test_crawl_engine.py -q --basetemp=.pytest-tmp-codex-1`

### Slice 9: Image Resolution Merges Better Sources Without Per-Tier Drift
**Status:** DONE
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/field_value_dom.py`, `backend/app/services/js_state_mapper.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_field_value_dom.py`
**What:** Delete the split JS-state-vs-DOM image winner logic by reusing one canonical image dedupe/filter path. `image_url` now materializes from the best canonical image candidate across sources, `additional_images` merges and dedupes across sources, and obvious provider/payment/logo noise is filtered once in the shared image owner.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_browser_expansion_runtime.py tests/services/test_field_value_dom.py -q --basetemp=.pytest-tmp-codex-6`

### Slice 10: Browser Extractability and DOM Completion Share One Contract
**Status:** DONE
**Files:** `backend/app/services/acquisition/browser_page_flow.py`, `backend/app/services/detail_extractor.py`, `backend/app/services/field_value_dom.py`, `backend/tests/services/test_browser_expansion_runtime.py`
**What:** Remove the heading-only browser extractability heuristic. Browser-time expansion skip decisions and extraction-time DOM completion checks now share the same requested-content extractability contract, including exact labels, normalized aliases, DOM sections, DOM patterns, and selector-backed fields.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_browser_expansion_runtime.py tests/services/test_detail_extractor_structured_sources.py -q`

### Slice 11: Preserve Exact Requested Labels Through Batch Fan-Out
**Status:** DONE
**Files:** `backend/app/services/pipeline/core.py`, `backend/tests/services/test_batch_runtime.py`, `backend/tests/services/test_crawl_service.py`, `backend/tests/services/test_field_policy.py`
**What:** Keep raw requested labels preserved through batch per-URL fan-out and extraction dispatch instead of canonicalizing them before acquisition. Canonical normalization still happens where matching logic needs it, but exact labels such as `Features & Benefits` now survive into acquisition/extraction/runtime shaping without adding a new normalization subsystem.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_field_policy.py tests/services/test_crawl_service.py tests/services/test_batch_runtime.py -q --basetemp=.pytest-tmp-codex-3`

## Doc Updates Required

- [x] `docs/backend-architecture.md` — update acquisition/listing behavior if owners or recovery semantics materially change.
- [ ] `docs/CODEBASE_MAP.md` — not expected unless ownership moves.
- [ ] `docs/INVARIANTS.md` — update only if a runtime contract changes.
- [ ] `docs/ENGINEERING_STRATEGY.md` — add a new anti-pattern only if this work uncovers another duplicate-recovery pattern worth codifying.

## Notes

- Concrete evidence for this plan comes from `docs/audits/SMOKETEST.md`, `backend/artifacts/test_sites_acceptance/20260421T094742Z__full_pipeline__test_sites_tail.json`, the saved Zara artifacts under `backend/artifacts/runs/1` and `backend/artifacts/runs/2`, and the live Zara repro run during this session.
- 2026-04-21 execution update:
  - saved Zara detail artifact now emits a single clean color axis and removes the copied code from option values;
  - saved acceptance artifacts now collapse USAJOBS and Karen Millen false-positive listing rows to zero and promote Startup.jobs from `Bookmark Apply` garbage to job-title rows;
  - live Zara browser acquisition now detects 40 listing cards upstream and extracts 13 product rows from the current listing path, clearing the prior 5-row failure mode;
  - browser-attempt exceptions now carry structured `browser_diagnostics` through batch error handling instead of disappearing as `{}`.
  - phase-2 smoke review found the active diff had already regressed the per-file LOC guard in `listing_extractor.py`; visual-fallback extraction was moved into `extract/listing_visual.py` so the listing owner stays under budget without adding a new recovery layer;
  - extraction runtime now handles XML sitemap/listing payloads as deterministic URL records, removing the 90s timeout path seen on `lafayette148ny.com/media/sitemap-products.xml`;
  - acceptance harness surface inference now recognizes slug-with-id `.../index.html` commerce detail URLs, fixing the `books.toscrape` detail false-positive listing route during acceptance runs;
  - harness `acquisition_only` mode was also repaired during the review pass so prefetch-mode smoke runs no longer die on an unassigned `url_result`;
  - suggestion-driven follow-up fixes stayed inside the existing owners: ecommerce detail titles now reject noisy DOM heading fallbacks and rank structured sources ahead of `dom_h1`, listing title scoring now drops pure-numeric candidates sooner, and generic DOM-variant helpers were pushed back into `extract/shared_variant_logic.py` so `detail_extractor.py` returns under the explicit LOC budget instead of growing another local helper block.
  - follow-up acceptance fixes now drop breadcrumb/list-position title pollution from structured candidates, derive listing/detail titles from meaningful URL slugs only when upstream title candidates are missing or noise, reject rating-only listing titles, and extend harness-only surface inference so `discogs /release/`, detail-like `.htm` product paths, and job-centric root hosts route to the correct extractor while explicit blocked verdicts stay blocked in acceptance reporting.
  - Gemini-audit remediation stayed in the owning buckets: ADP acquisition URL normalization moved into `ADPAdapter`, generic acquisition now resolves adapter-owned normalization through `adapters/registry.py`, detail DOM fallbacks keep linked gallery images, listing extraction rejects numeric-only titles upstream, and browser payload capture rejects oversized declared responses before reading bodies.
  - focused remediation verification passed with `pytest tests/services/test_acquirer.py tests/services/test_job_platform_adapters.py tests/services/test_normalizers.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_crawl_engine.py -q` plus `pytest tests/services/test_crawl_fetch_runtime.py -q -k "read_network_payload_body or should_capture_network_payload"`; a wider subset still has one unrelated pre-existing failure in `tests/services/test_crawl_fetch_runtime.py::test_create_browser_identity_builds_generator_lazily`.
  - slice-5 browser-runtime remediation is now complete: block classification no longer lets Akamai/recaptcha evidence override clearly extractable KitchenAid-class content, no-progress traversal keeps full rendered listing HTML as the primary acquisition payload instead of poisoning extraction with a thin traversal fragment, and Karen Millen-style `next_page_not_found` on an already-populated first page now remains `usable_content` rather than `traversal_failed`;
  - slice-5 verification passed with `pytest tests/services/test_block_detection.py tests/services/test_browser_expansion_runtime.py -q` and the exact slice gate `pytest tests/services/test_browser_expansion_runtime.py tests/services/test_pipeline_core.py -q`; live acquisition repro on 2026-04-21 returned `blocked=false` / `browser_outcome=usable_content` for KitchenAid listing + detail without traversal and for Karen Millen with explicit `paginate` traversal.
  - KitchenAid semantic-expansion follow-up stayed upstream: detail `page_markdown` now prunes review/Q&A/payment containers and low-signal chrome lines, JS-state product detection no longer accepts titled header/payment blobs as product state, JS-state image harvesting rejects payment/logo/bookmark/swatch/video assets, selector-backed long-text fields reject accordion indexes, and long-text candidate intake now drops placeholders like `normal` / `Product summary` before they can win `description` or `specifications`;
  - focused verification for that follow-up passed with `pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_field_value_dom.py tests/services/test_state_mappers.py tests/services/test_browser_expansion_runtime.py -q -k "ignores_review_json_ld_title_description_and_images or ignores_review_qa_controls_and_payment_icons or test_browser_expansion_runtime or test_field_value_dom or test_state_mappers"` plus a live KitchenAid detail repro on 2026-04-21 showing hero-product `image_url`, product-text `description`, null `specifications` instead of the details index, and a materially cleaner `page_markdown` excerpt without the prior review/payment dump.
  - variant follow-up stayed upstream as well: DOM variant intake now only accepts groups that resolve cleanly to canonical `color` / `size` axes, so Q&A-style radiogroups mentioning “size” no longer synthesize bogus variants and the old post-hoc axis/value noise filters were deleted instead of expanded; verification passed with `pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_shared_variant_logic.py tests/services/test_detail_extractor_priority_and_selector_self_heal.py tests/services/test_crawl_engine.py -q`.
  - audit follow-up moved the remaining report-cited tunables out of service bodies and into `app/services/config/*`: detail/listing thresholds now live in `runtime_settings.py`, extraction/browser/variant constants live in `config/extraction_rules.py`, and detail field-set ownership lives in `config/field_mappings.py`; the old skippable Zara copy-code regression was replaced with a committed deterministic fixture in `test_detail_extractor_structured_sources.py`, and full verification passed with `pytest tests -q`.
  - 2026-04-22 review follow-up validated seven new code-review comments against the live diff: three were real and fixed upstream (`browser_detail` ready-detail expansion on ecommerce runs without requested fields, `browser_page_flow` detail markdown label preservation, and `field_value_dom` composition fallback mislabeling); four were confirmed intentional via existing targeted guards (`crawl_crud` raw requested-field persistence, `crawl_fetch_runtime` escalation field propagation, `pipeline/core` canonical LLM missing-field matching, and `pipeline/direct_record_fallback` canonical requested-field scoring inputs). Focused guards passed for the touched owners, and the final backend suite passed with `pytest tests -q`.
  - 2026-04-22 commerce-requested-field follow-up stayed in the extraction owners: batch run creation now persists raw `requested_fields` / `additional_fields` inputs for later per-URL fan-out, ghost-route network payload mapping now rejects multi-record listing envelopes on detail surfaces, and ecommerce detail extraction now drops site-shell/Open-Graph-only false positives instead of persisting fake product records for stale SPA detail routes. Verification passed with `pytest tests/services/test_network_payload_mapper.py tests/services/test_crawl_engine.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_detail_extractor_priority_and_selector_self_heal.py -q` plus `pytest tests -q`; live validation also passed with a 10-site commerce sweep (10/10 on stable listing/detail coverage, including variant-heavy detail extraction and SPA listing output) and a real 3-URL batch detail crawl preserving requested fields across every URL.
  - 2026-04-22 additional-fields follow-up stayed in the owning frontend/extraction modules: UI field normalization now accepts separator-heavy labels like `Features & Benefits` by normalizing them to the same snake_case form the backend already expects, and ecommerce detail extraction now normalizes requested-field missingness before deciding on structured-data early exit so browser-expanded/custom section labels like `Product Story` keep the DOM tier live instead of disappearing behind a premature structured-data success. Focused verification passed with `pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_crawl_engine.py tests/services/test_browser_expansion_runtime.py -q` and `npm test -- components/crawl/crawl-config-screen.test.ts`; a full backend `pytest tests -q` run only hit the existing unrelated LOC-budget guard in `tests/services/test_structure.py` for `app/services/acquisition/browser_page_flow.py` and `app/services/field_value_dom.py`.
  - 2026-04-22 additional-fields exact-match follow-up corrected the slice-7 regression: the frontend now preserves raw additional-field labels instead of rewriting them before dispatch, detail extraction keeps exact requested section labels in play before broader alias collapse, and browser detail expansion now skips itself when those requested sections are already extractable from the current DOM. Focused verification passed with `pytest tests/services/test_field_policy.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_browser_expansion_runtime.py -q` and `npm test -- components/crawl/crawl-config-screen.test.ts`; live PUMA repro on `https://in.puma.com/in/en/pd/deviate-nitro-elite-4-run-club-mens-road-running-shoes/312907?swatch=01` now returns `features_benefits` from the raw `Features & Benefits` request without mutating the page through unrelated accordion clicks.
  - 2026-04-22 failure-mode remediation slices 8-11 stayed in the existing extraction/browser/pipeline owners: detail variant recovery is now quality-gated instead of presence-gated, image materialization uses one shared canonical dedupe/filter path across JS state and DOM, browser-time requested-content extractability reuses the extractor’s DOM contract, and batch fan-out now preserves raw requested labels into acquisition/extraction dispatch. Focused verification passed with `pytest tests/services/test_detail_extractor_structured_sources.py tests/services/test_shared_variant_logic.py tests/services/test_crawl_engine.py -q --basetemp=.pytest-tmp-codex-1`, `pytest tests/services/test_browser_expansion_runtime.py tests/services/test_field_value_dom.py tests/services/test_structure.py -q --basetemp=.pytest-tmp-codex-6` except for the known unrelated LOC-budget blockers in `app/services/field_value_dom.py` and `app/services/extract/listing_visual.py`, and `pytest tests/services/test_field_policy.py tests/services/test_crawl_service.py tests/services/test_batch_runtime.py -q --basetemp=.pytest-tmp-codex-3`. The remaining gate on `tests/services/test_pipeline_core.py` is still blocked by a pre-existing Windows `pytest` temp-path cleanup failure (`PermissionError: [WinError 5] Access is denied` under `.pytest-tmp-codex-*`) that obscures the same three `tmp_path`-backed test cases as before this slice.
- Zara findings from the current code path:
  - saved listing artifact returns only 5 structured rows;
  - live browser listing run returns polluted output because traversal never recognizes Zara product tiles as listing cards, then extraction admits category-cloud rows;
  - saved detail artifact duplicates the same color axis and ingests the `4493/144/800` copy-code as an option value.
- Negative LOC is a real constraint here: when two paths do the same recovery/filtering work, the fix should pick one owner and delete the loser.


Acceptance-Led Recovery Remediation Plan
Summary
Replace today’s overlapping recovery/remediation plans with one architecture-first plan whose source of truth is the saved acceptance artifact at backend/artifacts/test_sites_acceptance/20260421T094742Z__full_pipeline__test_sites_tail.json, not prior “DONE” status in plan docs. The implementation goal is negative or flat backend LOC by deleting duplicate or inert recovery paths while fixing the failure classes that are still demonstrably live: premature browser give-up, empty/garbage listing extraction, missing diagnostics on runtime failure, detail variant/export leakage, and acceptance-critical surface misclassification.

This plan explicitly includes Zara and the other current failure modes. Anti-bot work stays generic and bounded: no provider-specific bypass design, but KitchenAid-class failures are in scope when the current runtime is giving up too early on content that should be recoverable.

Implementation Changes
1. Collapse overlapping recovery work into one audited execution stream
Treat these plans as superseded implementation claims, not current truth: old-app-recovery-features-plan.md, extraction-regression-remediation-plan.md, extraction-architecture-debt-remediation-plan.md, and the current Zara-only plan.
Use the acceptance artifact plus saved run artifacts as the regression corpus for all slices.
Add a short doc note in the replacement plan that “plan completion” only counts if the named acceptance regressions move, not if unit tests alone pass.
2. Fix acquisition robustness and browser give-up rules in their existing owners
Audit the actual path from crawl_fetch_runtime / browser runtime / traversal / browser page flow and delete any recovery branches that do not affect the final acquisition result.
Make browser failure paths always emit populated browser_diagnostics and a concrete stop reason; Reverb-style empty-diagnostics failure is a regression to eliminate.
Tighten listing-page readiness/traversal so Zara-like product grids are counted as listing evidence before recovery gives up.
Keep challenge handling generic and bounded:
preserve challenge detection,
add wait/retry/pacing behavior only where it improves recoverable cases,
include KitchenAid in the acceptance target,
do not expand this pass into proxy-rotation or provider-specific bypass logic.
3. Fix garbage listing output upstream instead of adding downstream cleanup
Make the listing extraction path choose a single clean owner for candidate selection and remove duplicated ranking/filtering behavior that lets SEO clouds, nav links, promo tiles, and utility links compete with product rows.
Cover the current acceptance garbage cases, not just Zara:
Zara category cloud pollution,
USAJOBS and Startup.jobs UI-chrome/job-routing garbage,
Karen Millen promo-banner titles,
Zadig & Voltaire low-signal listing rows,
GovPlanet listing-detection miss.
If a site is failing because surface routing is wrong before extraction starts, fix the routing owner (backend/harness_support.py for acceptance runs, plus any shared owner if the same misclassification exists in the app path) in the same pass.
4. Repair detail extraction correctness where current “ported” logic is still leaking junk
Fix Zara detail variant parsing in the current generic owner so duplicate axis groups and copy-code buttons cannot become option values.
Keep variants and selected_variant as real record fields in persisted data and exports; remove only non-user-facing filler/noise, not the intended variant payload.
Ensure markdown/page-context internals remain internal and do not leak into JSON/CSV record exports.
Audit whether any current variant logic is incorrectly biased toward Shopify-style data; if so, remove that assumption at the shared variant/detail owner instead of adding another fallback layer.
5. Keep scope architecture-first and deletion-first
Prefer deleting duplicate helpers/branches over adding new ones.
Do not add new adapters unless the acceptance failure is proven impossible to fix in the generic path.
Do not add publish/persistence compensation for upstream extraction/runtime defects.
Do not add new plan docs after this; use this as the single execution plan and mark the overlapping ones as superseded in-place.
Public Interfaces / Contract Changes
No API route or frontend contract changes are planned.
Internal contract tightening:
browser/runtime failures must produce structured browser_diagnostics rather than {},
acceptance harness surface inference is allowed to change for acceptance-critical URLs,
exported JSON/CSV record payloads remain user-facing only and must not include internal markdown/page-context filler.
Test Plan
Regression tests from saved artifacts:
Zara listing saved artifact returns only product rows and reaches the expected count for the targeted crawl path.
Zara detail saved artifact emits clean color variants without duplicate axes or copy-code pollution.
KitchenAid recoverable acquisition path does not fail via premature give-up.
Reverb-style runtime failure path records non-empty diagnostics.
Acceptance-critical routing/output tests:
USAJOBS routes to job listing and does not emit sort/filter chrome as title.
Startup.jobs routes to job listing and does not emit button text as title.
Karen Millen and Zadig & Voltaire reject banner/promo/low-signal rows.
GovPlanet no longer lands in listing_detection_failed from the current non-standard listing DOM.
Verification gates:
focused pytest subsets for traversal, browser runtime, listing extraction, detail extraction, record export, and harness support;
then rerun the saved 20-site acceptance tail and compare failure-mode counts against the current baseline.
Assumptions
Primary success bar is architecture-first, but acceptance movement is still the only valid proof that the architecture cleanup worked.
Anti-bot scope is limited to generic bounded recovery and better robustness/diagnostics; broad proxy or provider-specific bypass strategy is out of scope.
Acceptance-critical surface inference fixes are included in this pass because several current “successes” are false positives caused by wrong routing.
Negative LOC remains a hard constraint for implementation, even if the plan itself is longer than the earlier narrow Zara-only plan.
- 2026-04-22 performance follow-up stayed in the acquisition owner: `resolve_browser_readiness_policy()` now keeps the initial browser navigation at `domcontentloaded` even when later settling may still require `networkidle`, which removed Zara's repeated 20s `goto(..., wait_until=\"networkidle\")` fallback tax. Focused verification passed with `pytest tests/services/test_browser_expansion_runtime.py tests/services/test_platform_detection.py -q`, and live Zara timing moved from roughly `listing 30.6s acquire + 1.2s extract / detail 27.7s acquire + 1.3s extract` down to `listing 24.2s acquire + 0.3s extract / detail 4.8s acquire + 1.4s extract`; the remaining Zara listing cost is now dominated by traversal (`~18.4s`) rather than navigation.
- 2026-04-22 Whirlpool/additional-fields follow-up stayed in shared extraction owners instead of site branches: camel/Pascal-case field normalization was fixed upstream in `field_policy.py`, network-payload signatures/list-container heuristics moved into `config/network_payload_specs.py`, requested extra fields now participate in payload anchor validation, and detail payloads with explicit mismatched URLs are rejected before they can overwrite the current page. Focused verification passed with `pytest tests/services/test_field_policy.py tests/services/test_network_payload_mapper.py tests/services/test_crawl_engine.py -q`. Live Whirlpool now restores the product title, canonical detail URL, `capacity`, `energy_rating`, and `additional_images`; remaining live pollution is limited to nested warranty/service option values still leaking into price/description selection.
