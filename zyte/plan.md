Failure Distribution: What the 51-Site Report Actually Says
Before the plan, the numbers need to be read at the right abstraction level. The report's failure modes cluster into 4 root architectural deficiencies, not 92 individual site problems.

Architecture Bucket	Count	Root Cause Category
variant_extraction	23	JS state traversal incomplete; DOM variant cues not triggering
media_extraction	22	Image gallery left on first structured-source match; lazy-loaded galleries not walked
text_extraction	16	Description candidate ranking stops at truncated/shallow source too early
core_extraction	10	Early-exit fires before structured sources are exhausted
price_extraction	6	Currency/magnitude reconciliation not seeing visible PDP price
availability_extraction	4	Availability read from wrong variant state (selected vs. parent)
The 4 Architecture-Level Problems (Not Site Hacks)
Problem 1: JS State Traversal Stops on First Matching Object
Evidence from report:

StockX (site 04): variant_count: crawler=0 | zyte=6 — zero variants despite JS-heavy SPA

Ulta (site 16): crawler=0 | zyte=48 — 48 color variants missing

ASOS (site 26), Wayfair (site 27), KitchenAid (site 46), Puma (sites 20, 43): all variant_count: crawler=0 | zyte=16–24

Codebase location:
js_state_mapper.py → mapecommercedetailstate() — returns on the first matching JS state object. Sites that hydrate via multiple window.__ objects (Next.js, Nuxt, custom SPA loaders) lose all variant data from subsequent objects. This is explicitly named AP-12 Bug 2 in ENGINEERING_STRATEGY.md.

What is NOT the fix:
Do not add per-site object-key heuristics. Do not add platform detections for StockX, Ulta, ASOS.

What IS the fix:
In js_state_mapper.py, iterate all matching JS state objects and backfill variant fields (and only variant fields) from subsequent ones when the primary object returned empty variants. Owner stays js_state_mapper.py. No new files.

Problem 2: requiresdomcompletion() Allows Early Exit When Variant DOM Cues Are Present
Evidence from report:

Nike (site 05): image_count: crawler=3 | zyte=12 + variant axis gap — JSON-LD fired, early exit happened, DOM image gallery and size selector never reached

Target (site 12): variant_count: crawler=0 | zyte=3, brand + price missing — structured source partial match caused early exit

BH Photo (site 25): image_count: crawler=0 | zyte=7, variants missing, price missing — early exit without DOM pass

Phase Eight (site 47): image_count: crawler=0 | zyte=13, brand + image_url missing

Codebase location:
detail_extractor.py → requiresdomcompletion(). The function checks confidence threshold and missing high-value fields, but does not check variant_dom_cues_present(soup) before allowing early exit. This is AP-12 Bug 1.

What is NOT the fix:
Do not add per-site DOM selector overrides. Do not add confidence threshold adjustments per domain.

What IS the fix:
In requiresdomcompletion(), add a check: if variant_dom_cues_present(soup) returns True, always return True (force DOM tier). The function already imports variant_dom_cues_present from shared_variant_logic. This is a 2-line change in the right place. Owner stays detail_extractor.py.

Problem 3: Image Candidate Collection Stops at First Structured Source; Lazy-Loaded Galleries Not Merged
Evidence from report (22 occurrences):

Amazon (site 06): image_count: crawler=1 | zyte=8 — only primary image, gallery skipped

Nike (site 05): crawler=3 | zyte=12

Zappos (site 23): crawler=1 | zyte=7

BH Photo (site 25): crawler=0 | zyte=7

Sephora (site 22): image gap alongside variant gap

Back Market (site 40): crawler=1 | zyte=8

Phase Eight (site 47): crawler=0 | zyte=13 — zero images despite a live PDP

Codebase location — two sub-problems:

3a. materialize_image_fields() in detail_extractor.py collects from ordered_candidates_for_field(surface, "image_url") and ordered_candidates_for_field(surface, "additional_images"). When JSON-LD or OG fires first with a single image, the image candidate list is a 1-item list and the DOM pass is skipped (early exit). This is the same early exit problem compounding into images.

3b. extract_page_images() in field_value_dom.py extracts images from the pruned DOM soup. But if the pruned DOM had data-src / loading="lazy" attributes and the page was fetched as HTTP (not rendered), those lazy-load URLs are not resolved. The function does not fall back to rawsoup (pre-pruning) when image count from cleaned soup is below a threshold.

What is NOT the fix:
Do not add site-specific image selector overrides for Amazon, Nike, Zappos individually. Do not add per-domain image count thresholds.

What IS the fix:

3a: Fix 2 above (force DOM tier when variant cues present) partially fixes this. Additionally, in materialize_image_fields(), when the winning image candidate count is ≤ 1 and rawsoup has more img tags than soup, fall through to extract_page_images(rawsoup) as a secondary pass. Owner: detail_extractor.py.

3b: In extract_page_images() in field_value_dom.py, resolve data-src and data-lazy-src attributes as additional image URL candidates alongside src. This is a single additional attribute check in the existing loop, not a new function. Owner: field_value_dom.py.

Problem 4: Description and Price Candidates Accept Truncated / Wrong-Magnitude First-Source Wins
Evidence from report:

Vitacost (site 38): description_length: crawler=157 | zyte=2028 — description terminates after meta description

Lululemon (site 19): crawler=104 | zyte=1171

Sephora (site 22): crawler=140 | zyte=993

Amazon (site 06): price: crawler=135996.22 | zyte=1849.99 — price magnitude ~73x off (INR vs USD cross-contamination)

31 Phillip Lim (site 41): price: crawler=59300.00 | zyte=595.00 — same INR/USD ratio (~100x)

KitchenAid (site 46): price: crawler=22999.00 | zyte=179.99 — same ~128x ratio

Apple (site 07): original_price: crawler=729.00 | zyte=29.12 — original price picking installment plan value

Codebase location — two sub-problems:

4a. Description: detail_extractor.py → materialize_record() → long-text selection logic. detaillongtextvaluelookstruncated() exists and is called, but the truncation check only catches "..." tails and specific word tokens. Meta descriptions (150–160 chars, grammatically complete) pass the truncation test and win as best_source. The DETAILLONGTEXTSOURCERANKS config does rank opengraph / description lower than dom_sections, but the DOM tier was skipped (Problem 2).

4b. Price magnitude: reconcile_detail_price_magnitudes() in detail_price_extractor.py already exists and is designed to catch this. But it requires the page_url to infer currency from the URL locale path (e.g., /in/, ar.puma.com). When the URL's locale signals INR or ARS but the structured source emits a number that happens to be in that currency's magnitude, the check passes. The reconciliation needs to cross-check the candidate price against the currency candidate derived from the URL before accepting a magnitude outlier.

What is NOT the fix:
Do not add per-site price cleaning. Do not add per-domain description length thresholds. Do not add currency override maps per domain.

What IS the fix:

4a: In requiresdomcompletion(), add: if the best available description candidate length is below DETAILLONGTEXTSOURCERANKS's weak-source threshold AND the page is extractable, force DOM tier. The check requiresdomlongtextcompletion() already exists — verify it is gated correctly in requiresdomcompletion(). If it is not, that is the 2-line fix. Owner: detail_extractor.py.

4b: In reconcile_detail_price_magnitudes(), after detecting a magnitude outlier, check the currency candidate derived from reconcile_detail_currency_with_url(). If currency is INR, ARS, PKR, or another high-nominal currency and the price is consistent with that currency's typical range, accept it. The fix is extending the magnitude table in config/extraction_rules.py with high-nominal currency expected ranges, not site-specific logic. Owner: detail_price_extractor.py + config/extraction_rules.py.

Scalar Field Pollution (Bonus: Low Effort, High Signal Cleanup)
Evidence: Sites 01, 16, 20, 24, 38, 41, 47 show color_looks_like_id, size_looks_polluted, variant_size_pollution.

Puma (20): size: crawler=Size | zyte=UK 3 — the UI placeholder label ("Size") was harvested as the size value

Vitacost (38): size: crawler=100 Softgels 200 Softgels 365 Softgels — all option labels concatenated into one scalar

Phase Eight (47): size: crawler=Bust — axis label leaked into scalar field

Codebase location:
variant_record_normalization.py → normalize_variant_record(). The coerce_variant_option_value() in detail_dom_extractor.py applies noise filtering per value, but when option values are concatenated at the DOM parse level (all <option> text joined), the scalar backfill in materialize_record() picks up the joined string.

What is NOT the fix:
Do not add per-site size label exclusions.

What IS the fix:
In normalize_variant_record(), when a scalar field (color, size) value contains more than one option-separator token ( / , | , whitespace-separated value count > 3), treat it as a pollution signal and null it. Add the threshold to config/extraction_rules.py as SCALAR_FIELD_MAX_OPTION_TOKENS. Owner: variant_record_normalization.py.

Agent Plan: Ordered Implementation Sequence
The following is the exact sequence your agent should work through. Each step targets one architecture-level mechanism. No site-specific logic, no new files.

Step 1 — Fix JS State Multi-Object Traversal
File: js_state_mapper.py
Change: In map_ecommerce_detail_state() (or equivalent entry), iterate all matching state objects; when the primary object has empty variants, backfill from subsequent objects rather than returning immediately.
Test signal: Sites 04 (StockX), 16 (Ulta), 20 (Puma), 26 (ASOS), 43 (Puma AR), 46 (KitchenAid) should gain variants.
Constraint: Do not change the winner-takes-all logic for scalar fields (price, title). Only backfill variants and variant_count from subsequent objects.

Step 2 — Force DOM Tier When Variant DOM Cues Present
File: detail_extractor.py → requiresdomcompletion()
Change: Add if variant_dom_cues_present(soup): return True before the confidence-threshold early-exit check. variant_dom_cues_present is already imported.
Test signal: Sites 05 (Nike), 12 (Target), 25 (BH Photo), 27 (Wayfair), 44 (Karen Millen) should gain images + variants.

Step 3 — Resolve Lazy-Load Image Attributes in DOM Image Extraction
File: field_value_dom.py → extract_page_images()
Change: When building the image candidate list, also check data-src, data-lazy-src, data-original attributes on <img> tags alongside src. Absolute-URL them with the existing absolute_url() call. Do not add new functions.
Test signal: Amazon (06), Zappos (23), Back Market (40) image counts should improve.

Step 4 — Verify requiresdomlongtextcompletion() Is Correctly Gated
File: detail_extractor.py → requiresdomcompletion()
Change: Confirm that requiresdomlongtextcompletion(record, extractable_fields) is called even when confidence threshold would otherwise allow early exit. If the call is inside an if normalizedsurface == "ecommerce_detail": block that is skipped during early exit, move the call before the early exit return. This is a check + a potential 3-line reorder, not a rewrite.
Test signal: Sites 19 (Lululemon), 38 (Vitacost), 34 (Decathlon), 50 (Grailed) description lengths should improve.

Step 5 — Extend Price Magnitude Reconciliation for High-Nominal Currencies
File: config/extraction_rules.py + detail_price_extractor.py → reconcile_detail_price_magnitudes()
Change: Add a HIGH_NOMINAL_CURRENCY_EXPECTED_RANGES dict to config: {"INR": (50, 5_000_000), "ARS": (100, 50_000_000), "PKR": (100, 1_000_000)}. In reconcile_detail_price_magnitudes(), after detecting a magnitude outlier, if the currency candidate matches a high-nominal currency and the raw price falls within that currency's expected range, accept the candidate price as correct (do not clamp to USD-scale). This prevents the 100x magnitude rejection from firing on legitimately large-nominal prices.
Test signal: Sites 41 (31 Phillip Lim, INR), 43 (Puma AR, ARS), 46 (KitchenAid, INR) price outliers should resolve.

Step 6 — Null Polluted Scalar Fields with Concatenated Option Tokens
File: config/extraction_rules.py (add SCALAR_FIELD_MAX_OPTION_TOKENS = 1) + variant_record_normalization.py → normalize_variant_record()
Change: After the existing scalar field backfill, check: if the resolved scalar value (color or size) contains more than SCALAR_FIELD_MAX_OPTION_TOKENS whitespace-separated tokens that each individually pass the axis-noise filter, null the scalar. This catches "Size", "100 Softgels 200 Softgels 365 Softgels", "Bust" leaking into scalars.
Test signal: Sites 20 (Puma size=Size), 38 (Vitacost size=concat), 47 (Phase Eight size=Bust).

What NOT to Do
These patterns appeared in the report but must not trigger site-specific fixes:

Do not add per-domain image selector rules for Nike, Amazon, Farfetch, Grailed

Do not add per-domain variant axis mappings for StockX, Ulta, ASOS

Do not add per-domain price normalization for Indian or Argentinian sites

Do not add a shopify in url or stockx in host branch anywhere in generic extraction paths (AP-4)

Do not add a new image_gallery_extractor.py or variant_helpers.py (AP-5, AP-13)

Do not touch pipeline_persistence.py, publish_verdict.py, or any export path to compensate for extraction gaps (AP-2)

Do not add a selected_variant synthesis to backfill parent fields (AP-20)

All 6 steps above modify exactly 4 files plus config. No new files. No new layers.