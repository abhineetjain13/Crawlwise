# Plan: Data Quality Extraction Hardening

**Created:** 2026-05-02
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** Bucket 2 Pipeline Orchestration, Bucket 3 Acquisition + Browser Runtime, Bucket 4 Extraction, Bucket 6 Review + Selectors + Domain Memory, Bucket 7 LLM Admin + Runtime, acceptance harness

## Goal

Fix ecommerce detail data quality at the upstream extraction boundary, not in export or enrichment. Merge the queued Self-Healing Extraction work with the latest data-quality audit. Done means the crawler rejects bad candidates before they win, repairs authorized missing high-value fields with visible diagnostics, removes duplicated downstream cleanup, and has acceptance gates that catch price magnitude errors, taxonomy pollution, long-text contamination, variant pollution, SKU/product-type artifacts, and silent repair skips.

## Investigation Summary

Latest audit source: `data_quality_audit.md`. Raw crawl JSON was not read; examples come from the audit report only.

Primary regressions:
- Price: `22999.00` vs `229.99`, INR cents drift, parent/variant mismatch, installment price accepted as total, missing price on visible PDPs.
- Taxonomy: category paths include `Back`, `Home`, `Previous`, `Next`, `VIEW ALL`, ellipses, marketing collection text, product title suffixes.
- Long text: description/spec/materials include buttons, delivery copy, SEO boilerplate, legal disclaimers, duplicate specs, reviews/care text leakage.
- Variants: promo toggles such as `off` and `20%` become variants; CSS hex values can become color names without accessible label.
- System artifacts: `COPY-*` SKU and low-signal `product_type` values (`default`, `Tag`, `inline`) reach user data.
- Self-heal/repair: old queued plan says repair exists but latest runs still showed `_self_heal.triggered=false`; current config and field targets drift from docs.

Confirmed code hot spots:
- `backend/app/services/detail_extractor.py` has only `_long_text_candidate_is_noise()` before `add_candidate()` at `_add_sourced_candidate`; most semantic cleanup runs after materialization.
- `backend/app/services/extract/detail_tiers.py` currently lets `BreadcrumbList` JSON-LD through for detail extraction.
- `backend/app/services/extract/detail_record_finalizer.py` repairs price, SKU, product type, variants, and text after record assembly; this is where duplicate downstream compensation has accumulated.
- `backend/app/services/extract/detail_price_extractor.py` owns visible PDP price backfill and cent normalization, but category/currency magnitude checks are too narrow.
- `backend/app/services/extract/detail_text_sanitizer.py` owns long-text cleanup by literal/regex chunks; this keeps growing as site copy changes.
- `backend/app/services/extract/detail_dom_extractor.py`, `shared_variant_logic.py`, and `variant_record_normalization.py` already own DOM variant recovery; fix there, not in exports.
- `backend/app/services/field_policy.py`, `config/field_mappings.exports.json`, `pipeline/extraction_retry_decision.py`, `selector_self_heal.py`, and `pipeline/direct_record_fallback.py` own requested/default repair targeting.
- `backend/app/services/js_state_mapper.py` still chooses one best product payload per state object via `_extract_product_payload_from_normalized()` and `_find_product_payload()`.
- `backend/tests/services/test_structure.py` has LOC/config/private-import ratchets; new drift guards belong there or nearby focused tests.

Duplication/debt to remove during slices:
- Price parsing appears as `_price_number()` in `detail_record_finalizer.py`, `_normalized_price_value()` in `detail_price_extractor.py`, and `extract_price_text()` / `normalize_decimal_price()` consumers. Choose one canonical Decimal path for detail price decisions.
- Variant noise constants exist in `config/extraction_rules.py`, `detail_dom_extractor.py`, `shared_variant_logic.py`, and structure-test allowlists. Move runtime tokens to config and shrink service allowlists.
- Low-signal product type and placeholder scalar rejection happens after selection in `detail_record_finalizer.py`; move rejectable artifact values to candidate validation.
- Long-text fulfillment/boilerplate filtering runs after selection in `detail_text_sanitizer.py`; move whole-value rejection to candidate gate, keep finalizer only for lossless trimming and cross-field consistency.

## Acceptance Criteria

- [ ] Ecommerce detail candidate admission rejects field-semantics violations before ranking: polluted category, low-signal product type, `COPY-*` SKU, fulfillment-only description, promo variant values.
- [ ] Detail JSON-LD `BreadcrumbList` does not populate product category candidates.
- [ ] Visible PDP price repair catches missing decimal and parent/variant magnitude mismatches without storing impossible prices.
- [ ] Long-text fields do not persist UI controls, shipping-only copy, exact duplicate specs, reviews/care leakage into materials, or legal boilerplate as primary product description.
- [ ] Variant extraction keeps semantic product option axes and rejects promo/header/newsletter/search/account values.
- [ ] Repair target config matches `docs/INVARIANTS.md` and `docs/BUSINESS_LOGIC.md`: default ecommerce repair is limited; deeper fields are repaired when requested or when acceptance harness explicitly requests them.
- [ ] Selector self-heal and LLM repair leave diagnostics for every missing requested/default field; LLM never runs unless both run settings and config allow it.
- [ ] Acceptance harness reports data-quality failures with per-field reasons and fails on known audit regressions.
- [ ] Downstream cleanup in `detail_record_finalizer.py` shrinks or is clearly limited to final reconciliation; no new cleanup in `publish/*`, `pipeline/persistence.py`, exports, or enrichment.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe run_extraction_smoke.py` exits 0.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe run_test_sites_acceptance.py` exits 0 or fails only with documented blocked/non-public sites.

## Do Not Touch

- `backend/app/services/publish/*` - downstream verdict/export must not hide bad extraction.
- `backend/app/services/pipeline/persistence.py` - persistence stores semantics; it does not repair them.
- `backend/app/services/record_export_service.py` - exports must not clean crawler output.
- `backend/app/services/data_enrichment/*` - enrichment consumes extracted source truth; no extraction cleanup here.
- `backend/app/services/detail_extractor.py` per-field candidate architecture - keep `_add_sourced_candidate`, `_winning_candidates_for_field`, and field-by-field materialization.
- `backend/app/services/extract/detail_extractor.py` does not exist - do not create shadow extractor files.
- `json.md` - do not read or bake raw crawl rows into code; use audit examples as regression fixtures.
- Browser acquisition scripts - do not write logical fields directly from browser page scripts; browser returns observations only.
- LLM prompts for primary extraction - LLM is missing-field repair only, gated and diagnostic.

## Slices

### Slice 1: Repair Contract And Baseline Quality Fixtures
**Status:** TODO
**Files:** `backend/app/services/field_policy.py`, `backend/app/services/config/field_mappings.exports.json`, `backend/app/services/pipeline/extraction_retry_decision.py`, `backend/tests/services/test_field_policy.py`, `backend/tests/services/test_extraction_retry_decision.py`, `backend/tests/test_harness_support.py`, `backend/run_test_sites_acceptance.py`
**What:**
- Reconcile `SURFACE_FIELD_REPAIR_TARGETS` and `SURFACE_BROWSER_RETRY_TARGETS` with canonical docs.
- Default ecommerce detail repair/browser/LLM targets stay limited to `price`, `title`, `image_url`, plus `currency` only when price evidence exists and currency is needed for validation.
- `brand`, `sku`, `availability`, `variants`, `selected_variant`, and `variant_axes` are repaired when requested by the run or explicit acceptance manifest.
- Add audit-derived fixtures for: price missing, price magnitude, category pollution, description pollution, promo variants, fake SKU, low-signal product type.
- Do not read `json.md`; encode only minimal synthetic fixture records from `data_quality_audit.md`.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_field_policy.py tests/services/test_extraction_retry_decision.py tests/test_harness_support.py -q`

### Slice 2: Candidate Admission Gate
**Status:** TODO
**Files:** `backend/app/services/detail_extractor.py`, `backend/app/services/config/extraction_rules.py`, `backend/app/services/field_value_core.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_crawl_engine.py`
**What:**
- Add a single `_field_candidate_is_valid(field_name, value, source, page_url, surface)` gate inside `_add_sourced_candidate()` before `add_candidate()`.
- Keep config tokens/thresholds in `app/services/config/extraction_rules.py`; no inline blocklists in service code.
- Gate field classes:
  - `category`: reject UI breadcrumb controls, ellipsis-only/truncated paths, marketing collection-only values, product-title suffix duplicates.
  - `description`, `product_details`, `specifications`, `materials`, `care`: reject fulfillment-only, SEO-only, legal-only, button/link-only, and exact title/category echoes as whole candidates.
  - `sku`, `part_number`, `product_id`: reject `COPY-*`, UUID-only, and internal duplicate IDs unless corroborated by URL/structured product identity.
  - `product_type`: reject `default`, `tag`, `inline`, placeholder taxonomy values, and layout/internal markers.
  - `price`, `original_price`: reject zero/low-signal sentinel values at candidate stage; leave detailed magnitude correction to Slice 4.
- Record rejected candidate counts in internal diagnostics, not `record.data`.
**Verify:** focused tests prove bad candidates never appear in `record`, good values still win, and `_field_sources` stays correct.

### Slice 3: Structured Category And Breadcrumb Cleanup
**Status:** TODO
**Files:** `backend/app/services/extract/detail_tiers.py`, `backend/app/services/extract/detail_raw_signals.py`, `backend/app/services/config/extraction_rules.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_crawl_engine.py`
**What:**
- Change `_detail_json_ld_payload_is_irrelevant()` so `BreadcrumbList` is irrelevant for detail product field candidates.
- Keep DOM breadcrumb category recovery in `detail_raw_signals.py`, but apply the same category semantic gate before it enters candidates.
- Remove product title from the end of category path when exact/near-exact duplicate.
- Reject paths whose meaningful segment count becomes zero after UI-token removal.
- Do not add downstream category scrubbers in finalizer/export.
**Verify:** JSON-LD BreadcrumbList cannot produce `"Back > Home > Men > Shoes"`; clean DOM breadcrumb still produces a useful category; product-name suffix is removed or rejected.

### Slice 4: Price Semantics And Cross-Field Money Checks
**Status:** TODO
**Files:** `backend/app/services/extract/detail_price_extractor.py`, `backend/app/services/extract/detail_record_finalizer.py`, `backend/app/services/field_value_core.py`, `backend/app/services/config/extraction_rules.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_crawl_engine.py`
**What:**
- Consolidate detail price numeric decisions on one Decimal-based helper path; stop adding float regex parsers.
- Add configured magnitude rules by currency and weak product context:
  - integral cents correction for cent-based currencies and host hints.
  - reject or correct 100x values when DOM/variant/structured sources provide corroborating smaller price.
  - reject installment/payment-plan candidates when total-price candidates exist.
  - flag impossible parent/variant magnitude mismatch when no safe correction exists.
- Move price artifact rejection before final selection where possible; finalizer may reconcile parent/variant only when provenance shows a safe correction.
- Ensure `backfill_detail_price_from_html()` runs on every early/final return path that can persist ecommerce detail.
**Verify:** fixtures for KitchenAid-style `22999.00`, INR book cents drift, Puma parent/variant mismatch, and installment low price. Existing valid high-price luxury products must remain valid when corroborated.

### Slice 5: Long-Text Field Integrity
**Status:** TODO
**Files:** `backend/app/services/extract/detail_text_sanitizer.py`, `backend/app/services/detail_extractor.py`, `backend/app/services/config/extraction_rules.py`, `backend/tests/services/test_crawl_engine.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`
**What:**
- Split long-text logic into candidate rejection vs final trimming.
- Candidate rejection handles whole-value non-product text: shipping/delivery-only, SEO review template, legal fine print, button/link labels, global fit glossaries, site support copy.
- Final trimming may remove trailing UI controls like `Show More`, `More details`, `Learn more...` when the remaining text is product content.
- Add cross-field consistency pass after `_materialize_record()`:
  - drop `specifications` when exact duplicate of `description`.
  - flag `gender` vs description contradiction in diagnostics; do not silently rewrite gender.
  - flag materials polluted by `Reviews`, `Care`, or unrelated global glossary; reject when no clean segment remains.
- Delete now-redundant regex branches after candidate gate covers them.
**Verify:** Wayfair/Target/JD/Zappos/Walmart/Home Depot style text fixtures. No product-rich description should be dropped just because it mentions shipping in one sentence.

### Slice 6: Variant Semantic Confinement
**Status:** TODO
**Files:** `backend/app/services/extract/detail_dom_extractor.py`, `backend/app/services/extract/shared_variant_logic.py`, `backend/app/services/extract/variant_record_normalization.py`, `backend/app/services/config/extraction_rules.py`, `backend/tests/services/test_crawl_engine.py`, `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_state_mappers.py`
**What:**
- Keep variant extraction in existing owners; do not add browser-side scrapers.
- Constrain DOM variants to product option containers, forms, buy boxes, selected product regions, and labeled option groups.
- Reject newsletter/footer/header/search/account/promotional text from variant values.
- Reject promo axes/values: `off`, `discount`, `%` values, booleans, and marketing badges unless paired with real semantic axis/value evidence.
- Treat CSS hex color as styling evidence only. Keep it only when paired with accessible label/title/aria text; otherwise reject instead of inventing a color dictionary.
- Dedupe structured and DOM variants without appending lower-confidence duplicates.
**Verify:** Adidas promo toggle rejected; ColourPop hex-only color rejected or paired with label; FashionNova color+size intact; Sneakersnstuff newsletter/signup noise absent.

### Slice 7: JS State Multi-Root Harvest
**Status:** TODO
**Files:** `backend/app/services/js_state_mapper.py`, `backend/app/services/config/field_mappings.py`, `backend/tests/services/test_state_mappers.py`
**What:**
- Replace single best payload return in `_extract_product_payload_from_normalized()` / `_find_product_payload()` with bounded same-product payload collection.
- Merge same-product payloads using existing `_merge_same_product_record()`.
- Add adjacent pricing/offer/variant payload merge when identity matches URL, SKU, product id, title, selected variant id, or configured product root.
- Keep traversal limits from config/runtime settings; no unbounded tree walk.
- Do not merge recommendation/cross-sell products into the requested PDP.
**Verify:** title payload sibling has price/variants in adjacent node and gets merged; unrelated recommendation product remains excluded.

### Slice 8: Browser Retry, Selector Self-Heal, And LLM Repair
**Status:** TODO
**Files:** `backend/app/services/pipeline/core.py`, `backend/app/services/pipeline/extraction_retry_decision.py`, `backend/app/services/acquisition/browser_page_flow.py`, `backend/app/services/acquisition/browser_readiness.py`, `backend/app/services/platform_policy.py`, `backend/app/services/selector_self_heal.py`, `backend/app/services/pipeline/direct_record_fallback.py`, `backend/app/services/run_config_snapshot.py`, `backend/app/services/config/runtime_settings.py`, `backend/app/services/config/selectors.py`, `backend/tests/services/test_selector_pipeline_integration.py`, `backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py`
**What:**
- Preserve user controls: no silent `surface`, traversal, proxy, or `llm_enabled` rewrites.
- Low-quality non-browser ecommerce detail records retry browser only when missing requested/default repair targets and HTML/diagnostics show JS/rendered evidence.
- Add field-aware readiness probes for configured price, offer JSON, product image/title region, and variant controls.
- Selector self-heal triggers on missing requested/default targets, not just low total confidence.
- `reduce_html_for_selector_synthesis()` must retain composite price spans, aria labels, data attributes, itemprop, and buy-box containers.
- Validate synthesized selectors by field type/context and actual field improvement before persisting `(domain, surface)` memory.
- LLM repair runs only when enabled by both run settings and active config, after deterministic/browser/self-heal options. It fills missing fields only and records rejected fields.
**Verify:** self-heal diagnostics show triggered/skipped reason; no LLM call when `llm_enabled=False`; synthesized selector rejects newsletter/signup values; Amazon-style split price fixture passes.

### Slice 9: Downstream Cleanup Deletion And Guard Rails
**Status:** TODO
**Files:** `backend/app/services/extract/detail_record_finalizer.py`, `backend/app/services/extract/detail_text_sanitizer.py`, `backend/tests/services/test_structure.py`, focused tests touched by prior slices
**What:**
- Remove finalizer branches that are now impossible because candidate gate rejects the bad values.
- Keep finalizer for final reconciliation only: image dedupe, safe parent/variant inheritance, money precision, availability reconciliation, and source-trace safe diagnostics.
- Shrink `ALLOWED_SERVICE_CONFIG_CONSTANTS` for moved noise tokens.
- Add a structure or behavior ratchet for no new extraction cleanup in `publish/*`, `pipeline/persistence.py`, or export services.
- Check LOC budgets after deletions; do not raise budgets unless the slice also deletes offsetting code.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_structure.py -q`

### Slice 10: Data Quality Acceptance Harness
**Status:** TODO
**Files:** `backend/run_test_sites_acceptance.py`, `backend/harness_support.py`, `backend/test_site_sets/commerce_browser_heavy.json`, `backend/tests/test_harness_support.py`
**What:**
- Add first-class data quality checks:
  - price present or diagnostic `not_public` / `blocked` / `requires_selection`.
  - price magnitude sanity by currency/context.
  - no category UI tokens or product-title suffix.
  - no long-text UI/shipping-only/SEO-only/legal-only primary descriptions.
  - no promo/system artifacts in variants, SKU, or product_type.
  - no exact duplicate `description` / `specifications`.
  - self-heal/LLM skipped or triggered reason visible for missing target fields.
- Explicitly request deeper fields in the acceptance manifest when the quality target expects them.
- Output per-field quality report before pass/fail.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/test_harness_support.py -q`

### Slice 11: Full Verification And Doc Closeout
**Status:** TODO
**Files:** `docs/INVARIANTS.md`, `docs/BUSINESS_LOGIC.md`, `docs/CODEBASE_MAP.md`, `docs/ENGINEERING_STRATEGY.md`, this plan
**What:**
- Update canonical docs only for changed contracts, ownership, or newly enforced anti-patterns.
- Mark slices done only with verify command notes.
- Run full backend tests and smoke commands.
- Run acceptance after tests; document blocked/non-public sites with reason.
**Verify:**
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

## Doc Updates Required

- [ ] `docs/INVARIANTS.md` - if default repair targets or candidate gate contract changes.
- [ ] `docs/BUSINESS_LOGIC.md` - if user-visible quality verdicts, repair behavior, or acceptance semantics change.
- [ ] `docs/CODEBASE_MAP.md` - only if files are moved or new owners are created. Prefer no new files.
- [ ] `docs/ENGINEERING_STRATEGY.md` - add anti-pattern only if a new recurring drift class is found and guarded.
- [ ] `docs/plans/ACTIVE.md` - update after each completed slice.

## Risks

- Some sites hide price behind location, login, selected size, or bot challenge. Do not fake values; emit diagnostic.
- Over-aggressive text rejection can drop useful product descriptions that mention shipping. Whole-value rejection must require high non-product ratio.
- Price magnitude rules can break legitimate luxury/furniture items. Require corroborating evidence before correction; otherwise flag.
- Selector self-heal can poison domain memory. Persist only validated field improvements scoped by `(domain, surface)`.
- LLM can hallucinate. It fills empty allowed fields only, with type validation and rejection diagnostics.
- JS state multi-root merge can pull recommendations. Merge only same-product identity.

## Notes

- Supersedes `docs/plans/self_healing_extraction.md`; that queued plan is merged here.
- Existing active plan in `docs/plans/ACTIVE.md` was `COMPLETE`, so this plan becomes current work.
- Architect subagent was requested for parallel review; no final response was available before this plan write. The supplied `docs/architectural-data-quality-audit.md` was incorporated.
- Do not start implementation until user confirms this plan.
