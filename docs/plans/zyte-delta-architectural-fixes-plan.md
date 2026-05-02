# Plan: Zyte Delta Architectural Fixes

Architectural cleanup of the extraction stack to eliminate the recurring defect classes surfaced by the Zyte delta audit (lines 304+ of `zyte/output_audit.md`), flatten the variant schema to Zyte's shape, and end description pollution/truncation — all without per-site shims, while pruning duplicated logic and tests that pin old buggy behavior.

**Created:** 2026-05-02
**Agent:** Claude
**Status:** IN PROGRESS
**Touches buckets:** Bucket 4 (Extraction), Bucket 5 (Publish/Persistence firewall), `services/config/*`, persisted record schema, review UI/exports, tests

## Goal

The Zyte delta audit (DQ-8 … DQ-15 + Deep Dive) shows the crawler is failing along architectural seams, not on individual sites: variants, price/currency parity, breadcrumb source-of-truth, identifier validation, identity hallucinations, description pollution+truncation, and an over-engineered variant schema that nobody can read. Each seam currently has overlapping/duplicate logic across adapters, DOM helpers, normalizer, and the review surface, plus tests that lock the old behavior in. Fix at the seam, delete the duplicates and stale tests, ratchet acceptance expectations.

## Non-Goals

- No per-domain branches, no allowlists keyed by hostname.
- No HTML-snapshot diff harness yet (deferred to a follow-up plan once these slices land).
- No re-crawl of the 52 URLs as part of slice verification (user will run the full suite after all slices pass).
- No new behavior in `publish/*` or exports beyond consuming the simpler schema — every defect fix lands upstream.

## Acceptance Criteria

- [ ] Variants persisted/exported as a flat list of `{color?, size?, sku?, price?, currency?, url?, image_url?, availability?}` (Zyte-shape). `variant_count` is the only summary kept. `variant_axes`, `selected_variant`, `available_sizes`, `option_N_name/value` removed end-to-end.
- [ ] `parent.currency` equals every `variants[].currency` (DQ-9).
- [ ] Records with `len(variants) > 1` always have at least one differentiating axis (color or size) populated on every variant (DQ-10 reframed for flat shape).
- [ ] Variant `title` is no longer persisted (parent title + axis values is enough); if a downstream consumer needs it, it is computed at render time, not stored (DQ-11).
- [ ] `category` does not contain the record's `title`, `sku`, "Best Sellers", "Shop by …", or `···` tokens; JSON-LD `BreadcrumbList` is used when present (DQ-8).
- [ ] `barcode` is strictly numeric or absent; alphanumeric internal codes route to `sku`/`mpn` (DQ-15).
- [ ] `gender` is within `{Men, Women, Unisex, Kids, Boys, Girls}` or absent (DQ-14).
- [ ] `brand` does not contain trailing region suffixes (` | XX`, ` - XX`) (DQ-14).
- [ ] `title` is sourced from `h1` / JSON-LD `name` / `og:title`; rejected if equal to internal tokens (`plp`, `pdp`, `specifications`, `BRIGHTCOVE VIDEO`).
- [ ] `price` parsing is locale-aware with parent/variant parity; sale vs regular is preserved; JSON-LD `offers.price` is used before DOM (Target/ASOS/Wayfair/Amazon).
- [ ] `description` matches Zyte fidelity: full content (no premature truncation), zero UI/glossary/fit-guide/shipping/disclaimer/array-stringification pollution. `features` is a first-class string list. Other ancillary blocks (care, materials, specifications) are emitted **only** when identified by structured signals — never as a fallback dump.
- [ ] No duplicate field-cleanup helper survives (grep proves a single owner per concern).
- [ ] `python -m pytest tests -q` exits 0; legacy tests pinning old behavior are removed/inverted with a recorded reason.
- [ ] `python run_test_sites_acceptance.py` passes with ratcheted commerce expectations.

## Do Not Touch

- `detail_extractor.py` candidate arbitration core — already field-by-field per `AGENTS.md` extraction warning. Only its inputs/outputs.
- `publish/*`, `pipeline/persistence.py` writes beyond schema simplification.
- `pipeline/core.py` orchestration shape.
- LLM runtime — these defects are deterministic-extractor problems, LLM is gap-fill only.
- Frontend pages outside the variant/description display sites.

## Slices

### Slice 1: Variant schema flattening (Zyte-shape, drop `selected_variant`/`variant_axes`/`available_sizes`/`option_N_*`)
**Status:** IN PROGRESS
**Files (read-first, then edit):**
- `backend/app/services/extract/variant_record_normalization.py`
- `backend/app/services/extract/shared_variant_logic.py`
- `backend/app/services/extract/detail_dom_extractor.py`
- `backend/app/services/extract/detail_record_finalizer.py`
- `backend/app/services/js_state_mapper.py` (heavy variant-axes/selected-variant logic)
- `backend/app/services/field_value_candidates.py`
- `backend/app/services/adapters/{shopify,amazon,nike,myntra}.py`
- `backend/app/services/public_record_firewall.py`
- `backend/app/services/data_enrichment/service.py`
- `backend/app/schemas/crawl.py`, `schemas/data_enrichment.py`, `models/crawl.py` (only if columns/JSON shape persisted)
- frontend: `components/crawl/crawl-run-screen.tsx` and any review/record viewer that renders `selected_variant`/`variant_axes`/`option_*`

**What:**
- Define the canonical variant shape: `{color, size, sku, price, currency, url, image_url, availability, stock_quantity}` — all optional, no nested `option_values`. Persist as a JSON list. Keep top-level `variant_count`.
- Remove `selected_variant` entirely. Parent record fields (`price`, `currency`, `availability`, `color`, `size`, `image_url`) are populated by the existing extractors directly from the page; the synthetic `_refresh_record_from_selected_variant` is deleted.
- Remove `variant_axes`, `available_sizes`, and any `option_1_name`/`option_1_value`-style flattened columns from emitted records, exports, and UI.
- Variant title is **not** stored. If review/UX needs a label, compute `f"{record.title} – {variant.color or ''} {variant.size or ''}"` at render time.
- Update DB shape: if `CrawlRecord.payload`/`EnrichedProduct` carries the old keys, write a one-off migration helper that drops them on read (no rewrite of historical rows). Forward writes are clean.
- Grep + delete: `select_variant`, `variant_axes`, `resolve_variants`, `split_variant_axes`, `_refresh_record_from_selected_variant`, `ordered_axes`, and any helper rendered dead by this simplification. Each deletion recorded in plan Notes.

**Verify:**
- Unit tests assert the persisted record has only `{variants: [...flat...], variant_count}`; old keys absent.
- Frontend review screen renders variants as a simple table (color/size/price/url/sku) — snapshot test or manual check.
- `pytest backend/tests -q -k "variant"` (after deletions, the test suite must pass; remove tests that pinned the old shape, with reasons in Notes).

### Slice 2: Variant extraction contract (DQ-10/11 + missing/partial variants + ColourPop cross-product)
**Status:** IN PROGRESS
**Files:**
- `backend/app/services/extract/shared_variant_logic.py`
- `backend/app/services/extract/detail_dom_extractor.py`
- `backend/app/services/extract/variant_record_normalization.py`
- `backend/app/services/config/extraction_rules.py`, `config/selectors.py`
- adapter `variants` writers (grep)

**What:**
- Single canonical source order: structured (JSON-LD `hasVariant` / Shopify `variants` / Salesforce `variations` / harvested JS state) → DOM swatch/size grid scoped to the PDP form/add-to-cart container. **Never** carousels, related-products, or "you may also like".
- Same source supplies the variant identity AND its axis values (color/size). If neither axis can be derived, the variant is dropped (no half-variants).
- Variant `currency` is inherited from the parent extraction context (single locale lock per record); foreign-locale variants are rejected.
- Structural axis check: if DOM exposes both a size grid and a color grid, the cartesian product is required; missing one axis fails the slice's regression test.
- Grep + delete redundant variant collectors in adapters that walked carousels or duplicated DOM swatch logic.

**Verify:**
- Unit tests on synthetic-HTML/JSON-LD fixtures (no per-site logic):
  - Karen Millen-shaped: 12 SKUs, every variant has a non-empty axis.
  - ColourPop-shaped: related-products carousel does not leak.
  - Puma-shaped: both color and size axes present when both grids are in DOM.
  - Zadig-shaped: parent GBP context rejects EUR variant payload.
- `pytest backend/tests -q -k variant`
- `python run_extraction_smoke.py`

### Slice 3: Price + currency parity (DQ-9, DQ-12, missing price total, sale/regular swap)
**Status:** TODO
**Files:**
- `backend/app/services/extract/detail_price_extractor.py`
- `backend/app/services/field_value_core.py` (locale-aware number parsing)
- `backend/app/services/extract/variant_record_normalization.py` (currency inheritance)
- `backend/app/services/config/extraction_rules.py`

**What:**
- One locale-aware price parser. Locale signal order: JSON-LD `priceCurrency` → page `<html lang>` → currency symbol on price node. Number parser deterministically chooses thousands/decimals. Delete duplicate `_parse_price`/`coerce_price`/`normalize_price` if any survive (grep first).
- Source-of-truth order for `price`: JSON-LD `offers.price` → microdata → adapter structured → DOM. DOM only when structured truly absent.
- Sale vs regular: when JSON-LD exposes both `price` and `priceSpecification`/`highPrice`, map to `price` (sale) and `original_price` (regular). DOM fallback uses generic strike-through semantics (`<s>`, `<del>`, classes containing `was|old|strike|regular`) — no per-site classes.
- Variant prices inherit parent locale; reject magnitude divergence > 100× without locale change.
- Reject leaks: a parsed "price" must not also be written into `size`/`product_id` (Adidas size=100).

**Verify:**
- Unit tests on synthetic fixtures (Farfetch EU, Puma AR, KitchenAid sale/regular, Target/ASOS JSON-LD-present-DOM-fail). `pytest backend/tests -q -k "price or currency"`.

### Slice 4: Breadcrumb / category source-of-truth (DQ-8)
**Status:** TODO
**Files:**
- `backend/app/services/extract/detail_raw_signals.py`
- `backend/app/services/config/extraction_rules.py`

**What:**
- Prefer JSON-LD `BreadcrumbList` `ItemListElement` ordered by `position`. DOM fallback only when JSON-LD absent.
- DOM fallback rejects nodes whose text equals (case-insensitive, trimmed) the current `title` or `sku`, or matches navigation/merchandising token blocklists in `config/extraction_rules.py` (`Shop by …`, `All Categories`, `Best Sellers`, `···`, `…`).
- A breadcrumb whose terminal node equals the title/sku has the terminal node dropped — never concatenated.
- Grep + consolidate any duplicate breadcrumb readers in adapters; route through `detail_raw_signals`.

**Verify:**
- Unit tests: Wayfair-shaped (`SKU:` suffix dropped), FrankBody-shaped ("Best Sellers" rejected), AbeBooks-shaped (terminal-equals-title dropped), Grailed-shaped (brand-repetition collapse), generic JSON-LD beats DOM. `pytest backend/tests -q -k "breadcrumb or category"`.

### Slice 5: Identifier + identity firewall (DQ-13/14/15 + Deep Dive identity hallucinations)
**Status:** TODO
**Files:**
- `backend/app/services/field_value_core.py`
- `backend/app/services/public_record_firewall.py`
- `backend/app/services/config/field_mappings.py`
- `backend/app/services/extract/detail_title_scorer.py`

**What:** add canonical, single-owner validators (delete overlaps as found):
- `barcode`: strict digits, length 8/12/13/14; otherwise route to `sku`/`mpn` heuristically; never write a non-numeric to `barcode`.
- `sku`: strip CMS prefixes (`COPY-`, `DRAFT-`, `tmp-`) via regex list in config; reject tracking-hash shapes (length > 20, mixed entropy, no separators).
- `product_id`: reject values equal to structural English tokens (`specifications`, `description`, `details`, `overview`, `reviews`).
- `product_type`: reject media-player tokens (`BRIGHTCOVE`, `VIDEO`, `PLAYER`) — generic, in config.
- `gender`: enforce taxonomy `{Men, Women, Unisex, Kids, Boys, Girls}`; `default`/`null`/empty/`na` → drop.
- `brand`: strip trailing region/site suffixes via generic anchored pattern (` | <token>`, ` - <token>` matched against ISO/region/site dictionary in config).
- `title`: must originate from `h1` / JSON-LD `name` / `og:title`; reject internal tokens (`plp`, `pdp`, structural IDs); never truncate at delimiters that drop model qualifiers — title is taken whole from the chosen source.

All validators run in `public_record_firewall.py` as the safety net; upstream extractors remain primary. Delete superseded per-field cleanup helpers (record deletions in Notes).

**Verify:** unit tests per validator with the audit's exact failure shapes. `pytest backend/tests -q -k "firewall or normalize"`. Grep proves single owner per concern.

### Slice 6: Description fidelity + features first-class + accordion/tab scoping
**Status:** TODO
**Files (investigate first — user expects sanitizer already exists, find it before adding):**
- `backend/app/services/extract/detail_text_sanitizer.py`
- `backend/app/services/extract/detail_dom_extractor.py` (scope to PDP content block; modal/tab exclusion)
- `backend/app/services/extract/detail_record_finalizer.py`
- `backend/app/services/config/extraction_rules.py` (token blocklists, length guards)
- `backend/app/services/field_value_core.py` (array-stringification join)

**What:**
- **Investigate** existing sanitizer + accordion/tab/modal scoping. Document what's there, what's broken, what's duplicated. Do not add a parallel sanitizer.
- **Truncation bug**: identify the cap that is shortening descriptions vs. Zyte's full text (likely a paragraph-only rule, char limit, or first-block selector). Remove or raise the cap so description matches the full PDP body.
- **Pollution removal** (architectural, generic, config-driven token lists):
  - UI tokens: `Show More`, `More Details`, `Learn more`, `Size Guide`, `View Size Guide`, `Add to Cart`, `Ask …`.
  - Shipping/returns/legal boilerplate: `Buy now with free shipping`, `Buyer protection guaranteed`, `We aim to show you accurate product information…`.
  - Glossary/fit-guide blocks: detect by repeated definition/heading patterns (e.g., 3+ `<h*>fabric_name</h*> + paragraph` repetitions, or N+ known fit/material tokens) — drop the whole block, not individual lines.
  - Array stringification: detect strings shaped `['…', '…']` and join via newline/bullet at the field-coercion layer (`field_value_core.py`).
  - Block-tag whitespace: ensure the HTML→text utility replaces block tags and `<br>` with `\n` before stripping. Single owner; delete duplicates.
- **Scoping**: text fields read only from the active PDP content container. Hidden modals/tabs (`aria-hidden="true"`, `display:none` resolved at parse time, `role="dialog"`, off-screen accordions whose toggle is a global helper like fit-guide/size-guide) are excluded at the source, not post-filtered.
- **Features as first-class**: `features: list[str]` matches Zyte. Source order: JSON-LD `additionalProperty`/`feature`, structured bullets within the PDP block, then DOM `<ul>/<ol>` inside the PDP block (not site-wide).
- **Care/materials/specifications**: emit **only** when identified by structured signals (JSON-LD properties, microdata, labeled DOM dt/dd or labeled tables). When identification is uncertain, drop — no fallback dump. Final objective: zero pollution.

**Verify:**
- Investigation note in plan Notes lists existing sanitizer/scope code and what changes vs. is deleted.
- Unit tests on synthetic fixtures: ToddSnyder-shaped (full glossary block dropped, real description preserved at full length), UnTuckIt-shaped (fit guide dropped), Sam'sClub-shaped (description matches Zyte's bulleted full text), B&H-shaped (`Show More`/`More Details` removed), Walmart-shaped (info disclaimer removed), Nike/Amazon-shaped (`features` is a clean list, not `['...']`).
- Add a **truncation regression** test: feed a fixture whose source has 8+ paragraphs; assert all are present.
- `pytest backend/tests -q -k "description or features or sanitiz"`.

### Slice 7: Test & duplicate-code purge + acceptance ratchet
**Status:** TODO
**Files:**
- `backend/tests/**`
- `backend/test_site_sets/commerce_browser_heavy.json`
- `backend/run_test_sites_acceptance.py` (only if expectation schema needs widening)

**What:**
- Sweep `grep -r` for assertions that pin now-fixed buggy behavior (category containing title, alphanumeric `barcode`, `selected_variant`-shaped expectations, `variant_axes` keys, `option_1_*` columns, capped description). Delete or invert; record reasons in Notes.
- Add cross-cutting **architectural** invariants as shared test helpers (no site logic):
  - `assert_variant_currency_parity(record)`
  - `assert_variant_has_axis(record)`
  - `assert_no_legacy_variant_keys(record)` (no `selected_variant`, `variant_axes`, `available_sizes`, `option_*`)
  - `assert_category_clean(record)`
  - `assert_identifier_shapes(record)`
  - `assert_title_not_internal_token(record)`
  - `assert_description_not_polluted(record)` + `assert_description_not_truncated(record, fixture)`
- Wire helpers into the acceptance runner so every commerce row in `commerce_browser_heavy.json` is checked.
- Ratchet `commerce_browser_heavy.json` quality expectations upward where prior tolerances masked these defects.

**Verify:** `python -m pytest tests -q` exits 0; `python run_test_sites_acceptance.py` exits 0; grep search for duplicated normalizer/sanitizer functions returns one owner each.

## Doc Updates Required

- [ ] `docs/INVARIANTS.md` — add: flat variant schema; parent/variant currency parity; mandatory axis when multi-variant; category never contains identity tokens; barcode digit-only; title source order; locale-aware price parser is single-owner; description must not truncate vs. structured source; pollution-token blocklists owned in config.
- [ ] `docs/CODEBASE_MAP.md` — only if a file is added/moved.
- [ ] `docs/ENGINEERING_STRATEGY.md` — add anti-patterns: "duplicate per-field cleanup helpers shadowing the public record firewall"; "synthesizing parent fields from a `selected_variant`".
- [ ] `docs/plans/ACTIVE.md` — point to this plan once approved.

## Notes

- User explicitly forbade per-site coding: every fix is a generic rule with config-driven token lists — no hostname switches.
- User flagged code/test bloat: every slice ends with a grep audit and explicit deletion of superseded helpers and pinned-buggy tests, recorded here.
- User flagged variant-display confusion: Slice 1 flattens the schema to Zyte shape; the rest of the variant slices then build on the simpler shape.
- User flagged description truncation as the real description issue (not just pollution): Slice 6 begins with an investigation step to locate the existing sanitizer/scope code, fix the truncation cap, then tighten pollution rules; final objective is zero pollution and full-fidelity text.
- Verification stays at unit + acceptance; HTML-snapshot diff harness is a deliberate follow-up plan once these land.
- 2026-05-02 progress: public-firewall output now enforces flat variants only. Legacy public keys (`selected_variant`, `variant_axes`, `available_sizes`, `option*`) are stripped. Variant rows are flattened to `{color,size,sku,price,currency,url,image_url,availability,stock_quantity}` and extra keys like `title`, `option_values`, `variant_id`, `barcode`, `original_price` are dropped at the public boundary.
- 2026-05-02 progress: single-owner public validators now live in `field_value_core.py` with config-backed rule tables in `config/field_mappings.py`. Barcode is digit-only 8/12/13/14 or rerouted to `sku`; gender is normalized to the fixed taxonomy or dropped; brand region suffixes are trimmed; structural `product_id` / `product_type` tokens are dropped; noisy draft SKU prefixes are stripped.
- 2026-05-02 progress: enrichment and acceptance helpers no longer rely on `selected_variant` / `variant_axes` for the newly landed paths. Enrichment now reads variant color/size/availability directly from `variants`. Acceptance quality checks now judge flat variant rows and legacy-key absence instead of selected-variant presence.
- 2026-05-02 verify: `backend\\.venv\\Scripts\\python.exe -m pytest tests -q -k "variant or firewall or normalize or data_enrichment or harness_support"` -> 211 passed.
- 2026-05-02 progress: adapter/DOM/JS-state producers now emit flat `variants` plus `variant_count` only. `shopify`, `amazon`, `nike`, `myntra`, `js_state_mapper.py`, and `detail_dom_extractor.py` no longer return `selected_variant`, `variant_axes`, `available_sizes`, or `optionN_*` public payload keys. `detail_record_finalizer.py` now strips stale legacy keys before variant cleanup and drops parent size/color scalars that only came from a single variant row.
- 2026-05-02 progress: old tests that pinned variant IDs, variant `original_price`, `option_values`, `selected_variant`, `variant_axes`, `available_sizes`, and non-canonical shade/flavour axes were inverted to the flat contract. DOM fallback now replaces weak one-row JS variants when DOM exposes stronger color/size rows.
- 2026-05-02 progress: `variant_record_normalization.py` no longer repairs `selected_variant`, `variant_axes`, `available_sizes`, or option summary fields. It now infers missing sizes before flattening, flattens once, cleans flat rows only, dedupes by public/semantic identity, drops header placeholders and weak axis-less rows when real color/size rows exist, preserves numeric-only rows only when they carry parent-price repair signal, and strips legacy keys at the end.
- 2026-05-02 verify: `backend\\.venv\\Scripts\\python.exe -m pytest tests -q -k "variant or firewall or normalize or data_enrichment or harness_support or detail"` -> 412 passed, 1 skipped.
- 2026-05-02 progress: slice 2 contract now rejects axis-less public variants at the owner boundary instead of letting SKU-only / cross-product rows leak through. DOM variant discovery is scoped to PDP/product-form regions, noise contexts like carousels/related/upsell/newsletter are excluded upstream, and parent currency is now the single locale lock for variant rows. Foreign-currency variant rows are dropped.
- 2026-05-02 progress: slice 3 price owner now reads JSON-LD offer price/currency/original-price bundles structurally before DOM fallbacks. `highPrice` and `priceSpecification` feed `original_price`, locale-formatted values still normalize through the same owner, and stale tests that pinned variant `original_price` persistence or axis-less JS-state rows were inverted.
- 2026-05-02 progress: slice 4 category owner now preserves JSON-LD `BreadcrumbList` payloads through the structured tier, ranks `json_ld_breadcrumb` above generic product category text, strips merchandising prefixes like `Shop by ...`, drops UI tokens like `Best Sellers`, and removes terminal title/SKU breadcrumb nodes in the detail finalizer.
- 2026-05-02 verify: `backend\\.venv\\Scripts\\python.exe -m pytest tests -q -k "variant"` -> 102 passed.
- 2026-05-02 verify: `backend\\.venv\\Scripts\\python.exe -m pytest tests -q -k "price or currency"` -> 74 passed.
- 2026-05-02 verify: `backend\\.venv\\Scripts\\python.exe -m pytest tests -q -k "breadcrumb or category"` -> 20 passed.
- 2026-05-02 verify: `backend\\.venv\\Scripts\\python.exe -m pytest tests -q -k "variant or price or currency or breadcrumb or category"` -> 184 passed.
- 2026-05-02 verify: `backend\\.venv\\Scripts\\python.exe run_extraction_smoke.py` -> skipped because acceptance corpus path is missing in local env.
- Smoke commands (run inside `backend/`):
  - `.\.venv\Scripts\python.exe -m pytest tests -q`
  - `.\.venv\Scripts\python.exe run_extraction_smoke.py`
  - `.\.venv\Scripts\python.exe run_test_sites_acceptance.py`
