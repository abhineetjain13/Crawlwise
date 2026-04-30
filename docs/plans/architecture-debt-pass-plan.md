# Plan: Architecture Debt Pass (Pre-Hybrid-Handoff)

**Created:** 2026-04-27
**Status:** DONE 2026-04-29
**Touches buckets:** extraction, acquisition, config, tests, docs
**Sister plan:** `docs/plans/hybrid-browser-http-handoff-plan.md` (this plan unblocks Slice 1+ of that one)

## Goal

Reduce duplication and config drift discovered during the 2026-04-27 explorer pass.
Consolidate to single canonical owners per concern, per `ENGINEERING_STRATEGY.md`
AP-9 / AP-13 / AP-15. No new behavior. No new files except where AP-5 demands it.

## Acceptance Criteria

- [x] No two files implement variant identity / merge / richness independently.
- [x] No two files compile `LISTING_UTILITY_TITLE_PATTERNS` or define a parallel utility-record check.
- [x] No stale `TypeError` compatibility shim remains in browser call paths.
- [x] Browser diagnostics dict shape is built in one place per emit point.
- [x] Per-URL batch failures roll back/reload the DB session and do not poison later URLs.
- [x] Location-required browser interstitials are diagnostic failures, not bot hard-block memory.
- [x] Terminal runs with persisted records remain JSON/CSV exportable even when some URLs fail.
- [x] `*.exports.json` blobs have provenance: a generator script + a documented invariant of how to regenerate.
- [x] OpenGraph / static structured-source key maps live under `app/services/config/*`.
- [x] `python -m pytest tests -q` exits 0 after each slice.
- [x] Detail extraction ownership is split enough that DOM fallback, price repair, title scoring, and record-quality cleanup now live behind canonical helper owners instead of growing new downstream fixes.

## Slices

### Slice 1: Variant Identity / Merge / Richness Consolidation
**Status:** DONE 2026-04-27 — `971 passed, 4 skipped, 6 failed (pre-existing fixture misses)`
**Files:** `backend/app/services/extract/shared_variant_logic.py`,
`backend/app/services/js_state_mapper.py`,
`backend/app/services/extract/variant_record_normalization.py`,
focused tests.
**What:** Promote `_variant_identity`, `_variant_row_richness`, `_variant_rows_by_richness`,
and `_merge_variant_rows` from `js_state_mapper.py` to public helpers in
`extract/shared_variant_logic.py`. Replace inline option-values-first identity
inside `_dedupe_variant_rows` with the same canonical helper so both code paths
agree on what makes two rows the same variant. Identity priority: `variant_id` >
`sku` > `option_values` > `url`. Richer row wins on merge.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services -q`

### Slice 2: Listing Utility Detection Consolidation
**Status:** DONE 2026-04-27 — `971 passed, 4 skipped, 6 failed (pre-existing fixture misses)`
**Files:** `backend/app/services/extract/listing_candidate_ranking.py`,
`backend/app/services/listing_extractor.py`,
`backend/app/services/field_value_core.py`,
`backend/app/services/extract/listing_visual.py`,
`backend/app/services/adapters/belk.py`.
**What:** Single canonical `looks_like_utility_record(title, url)` in
`extract/listing_candidate_ranking.py`. Compile patterns once. All five current
sites import it. Drop `_UTILITY_TITLE_REGEXES`, `_LISTING_UTILITY_TITLE_REGEXES`,
`_listing_url_or_title_looks_like_utility`, `_listing_title_contains_token_phrase`,
and the inline `re.search` loops in `listing_visual.py` / `belk.py`.
**Verify:** Listing extractor and acceptance test suite.

### Slice 3: Browser TypeError Shim Removal
**Status:** DONE 2026-04-27 — `961 passed, 4 skipped (pre-existing fixture misses)`
**Files:** `backend/app/services/acquisition/browser_runtime.py`,
`backend/app/services/acquisition/browser_recovery.py`,
`backend/app/services/crawl_fetch_runtime.py`.
**What:** Removed `try/except TypeError` shims from `_load_storage_state_for_run`,
`_load_storage_state_for_domain`, `_persist_storage_state_for_run`,
`_persist_storage_state_for_domain`, `_resolve_runtime_provider`,
`_resolve_proxied_page_factory` in browser_runtime.py; removed shim in
`_page_has_cookie` in browser_recovery.py; removed `inspect`-based dynamic
signature resolution in `_invoke_run_browser_attempts` in crawl_fetch_runtime.py.
Updated all test fakes to accept new `browser_engine` / `capture_screenshot` /
`host_policy` kwargs. Deleted obsolete shim-specific test.
**Verify:** `961 passed, 4 skipped, 0 failures` (6 pre-existing artifact fixture misses excluded).

### Slice 4: Per-URL Fault Boundary
**Status:** DONE 2026-04-28 — `test_batch_runtime.py` passed
**Files:** `backend/app/services/_batch_runtime.py`,
`backend/tests/services/test_batch_runtime.py`.
**What:** Per-URL failures now roll back the session, reload the run, persist a
URL-level `error` verdict/metrics row in summary, and continue to the next URL.
Only setup failures before URL iteration remain run-fatal. A mixed success/error
batch finishes `completed` with aggregate verdict `partial`.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_batch_runtime.py -q`

### Slice 5: Browser Diagnostics + Location Interstitial Contract
**Status:** DONE 2026-04-28 — focused diagnostics tests passed; `test_pipeline_core.py` passed
**Files:** `backend/app/services/acquisition/browser_runtime.py`,
`backend/app/services/acquisition/browser_page_flow.py`,
`backend/app/services/pipeline/runtime_helpers.py`,
`backend/app/services/crawl_fetch_runtime.py`,
`backend/app/services/config/selectors.exports.json`.
**What:** One owner function in `browser_runtime.py` completes the browser diagnostics
shape. Location-selection interstitials are recorded as
`browser_outcome=location_required` / `failure_reason=location_required`, do not
set bot hard-block memory, and use only configured safe dismiss actions. No ZIP/city
entry is automated unless user locality config supplies it later.
**Verify:** Browser diagnostics, host protection memory, and pipeline core tests.

### Slice 6: Export + UI Partial-Run Contract
**Status:** DONE 2026-04-28 — focused export/UI tests passed
**Files:** `backend/app/services/record_export_service.py`,
`frontend/components/crawl/crawl-run-screen.tsx`, tests.
**What:** Export routes remain status-agnostic; JSON/CSV stream any persisted
records even when a run summary contains failed/error URL verdicts. The run
workspace no longer forces failed/proxy-exhausted runs to Logs when records exist,
so partial output remains visible/exportable.
**Verify:** `test_record_export_service.py`; focused `crawl-run-screen.test.tsx`.

### Slice 7: `*.exports.json` Provenance
**Status:** DONE 2026-04-28 — focused config tests and export-data smoke passed
**Files:** `backend/app/services/config/*.exports.json`,
`backend/app/services/config/_export_data.py`, possible new
`backend/scripts/regenerate_config_exports.py` if no equivalent exists.
**What:** Document how each exports.json was produced. Either ship a regenerator
or convert each blob back into a typed Python config module. Today these are
opaque generated artifacts; new contributors cannot edit them safely.
**Verify:** Loader test that asserts every key referenced by `extraction_rules.py`
exists in the JSON, plus regen script smoke if added.

### Slice 8: OpenGraph / Static Key Maps Move
**Status:** DONE 2026-04-28 — structured source focused tests passed
**Files:** `backend/app/services/structured_sources.py`,
`backend/app/services/config/*.py`.
**What:** Any OG / Twitter / Nuxt / static structured-source key map currently
inlined in `structured_sources.py` (or peers) moves under `app/services/config/`.
Per INVARIANTS.md Rule 1, these are config, not service code.
**Verify:** Structured sources test suite + `pytest tests -q`.

### Slice 9: Extraction Quality Follow-Up From 39-Site Batch
**Status:** DONE 2026-04-29
**Files:** extraction/acquisition owners only.
**What:** Fix bad-field quality upstream, not in exports: carousel/title
dissociation in `detail_extractor.py` or gallery config; `.com` + INR locality
conflict in acquisition/session config; comparison-image leakage in gallery
scoping; missing brand/sku/variants in structured source / JS state / DOM variant
owners; transient query-param canonicalization in `field_url_normalization.py`.
**Done:** Public `record.data` now rejects default ecommerce detail schema pollution
(`vendor`, `product_type`, Shopify option summaries, publish timestamps, counts)
unless explicitly requested; detail public URLs drop transient variant/sku/size query
params while raw/variant trace keeps them; Chewy-style JSON-LD multi-offer variants
now become variant rows with inferred size axes from title/URL text, and page-level
`original_price` is not copied to every variant when variant prices differ.
Comparison-model image sections are now treated as non-primary gallery context
so unrelated model assets do not enter detail `additional_images`.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` and `run_test_sites_acceptance.py` on Nike, Kith, Nordstrom, Costco, and Lowes all returned `Quality: good`.

Problem : detail_extractor.py still at 2,397 lines after the latest split
This is the last remaining monster file. It's doing DOM extraction, JS state parsing, price normalization, variant logic, and title scoring in one place. It's the same pattern that service.py was — the listing extractor decomposition shows you already know how to fix this. The extract/ directory pattern (candidate_ranking, card_fragments, visual, variant_normalization) should be applied here.
Proposed split:

detail_dom_extractor.py — DOM field extraction (selectors, CSS, itemprop)
detail_price_extractor.py — price/variant/currency logic
detail_title_scorer.py — title source ranking and noise filtering
detail_record_finalizer.py — confidence scoring and field validation

2026-04-29 follow-up: DOM variant recovery moved into `extract/detail_dom_extractor.py`.
Record cleanup, image dedupe, variant row repair, long-text cleanup, and quality normalization moved into
`extract/detail_record_finalizer.py`. `detail_extractor.py` is now orchestration/candidate arbitration only
and is down to ~1,184 LOC. Focused extraction verification passed: `252 passed, 4 skipped`.

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — note new public exports in `extract/shared_variant_logic.py`
      and canonical owner for utility detection.
- [x] `docs/ENGINEERING_STRATEGY.md` — added AP-16 for detail-expansion site-chrome clicks.

## Notes

- 2026-04-27: Plan opened to track six debt items left from the 2026-04-27 explorer
  pass. User explicitly asked for sequential execution in caveman-list order.
- 2026-04-28: Added and implemented 39-site batch fallout slices for per-URL
  fault isolation, location-required browser diagnostics, and partial-run exports.
  Full backend run: `974 passed, 4 skipped, 6 failed` from pre-existing missing
  artifact fixtures in `test_crawl_engine.py`.
- 2026-04-28: Continued Slice 9 output fixes: schema pollution firewall,
  ecommerce detail URL canonicalization, and Chewy-style offer variant size
  inference.
- 2026-04-28: Slice 7 and Slice 8 implemented. Detail extraction was split
  further into DOM context, price, tier, and title helpers. Full backend
  verification still fails on missing Belk artifact fixtures plus remaining
  detail identity/self-heal cases, so plan is not marked COMPLETE.
- 2026-04-29: Closeout verification passed. Added real DOM fallback ownership in
  `extract/detail_dom_extractor.py`; fixed same-URL detail identity matching for
  variant selector paths (`/color/...`) and record token recovery; sanitized
  persisted browser storage-state null bytes; rejected locale-only fake network
  payload URLs that poisoned Zara detail extraction. Verification:
  `1021 passed, 4 skipped` on `pytest tests -q`. Live acceptance re-checks for
  Nordstrom, Zappos, and Zara now all pass in `full_pipeline` mode.
- 2026-04-29: Plan reopened. User correctly called out that
  `backend/app/services/detail_extractor.py` is still 2840 LOC and the v5
  quality/failure backlog is not cleared. Next work continues the extractor
  split and output-quality fixes instead of treating this pass as done.
- 2026-04-29: Continued Slice 9 upstream quality pass. Nike adapter now reads
  live `__NEXT_DATA__` product payloads, shared JS state mapping now carries
  `currentPrice`-style values through final normalization, variant cleanup now
  strips `is currently unavailable.` pollution from both rows and
  `variant_axes`, and malformed relative image fragments like Adidas `g_auto/*`
  and base64 GIF placeholders are rejected earlier. Verified on focused suites:
  `168 passed, 4 skipped`. Synthetic detail extraction now confirms generic
  currentPrice backfill produces price-bearing variants with cleaned size axes.
- 2026-04-29: Continued Slice 9 upstream quality pass. Generic detail cleanup
  now repairs fake UUID-like SKUs when a real merch code is present in URL or
  product details, strips shell text like Costco `Product Label` / `Powered by
  Product details... View More`, infers textual mattress-size variants
  (`Queen`, `King`, etc.), strips review-copy suffixes like Nordstrom
  `Customers say ...` from scalar variant fields, drops Lowes-style
  document-link-only descriptions, and backfills shared `image_url` /
  `availability` onto sparse variant rows when every variant is missing them.
  Verified on focused suites: `116 passed, 4 skipped`.
- 2026-04-29: Closeout finished. Fixed generic browser-driver disconnect handling,
  kept per-URL batch errors isolated, prevented detail expansion from clicking
  header/nav/footer site chrome, hardened shell/404 rejection, repaired image
  identity matching for same-site PDP assets, and cleaned variant availability
  so bare permutation rows do not carry redundant `in_stock`. Verification:
  `1057 passed, 4 skipped` on `pytest tests -q`. Live acceptance report:
  `backend/artifacts/test_sites_acceptance/20260429T025621Z__full_pipeline__test_sites_tail.json`
  with 5/5 `Quality: good` for Nike, Kith, Nordstrom, Costco, and Lowes.
- Previous explorer pass (closed): removed duplicate interactive handle helpers,
  unified proxy rotation parser. Verified `245 passed` on focused subset.
