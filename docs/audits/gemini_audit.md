## 2026-05-04 Fix Status

| ID | Issue | Status | Notes |
|----|-------|--------|-------|
| DQ-1 | Price decimal scaling errors | OPEN | Tracked under Zyte-delta Slice 3 (price parity / magnitude drift). |
| DQ-2 | UI elements extracted as variant axes | RESOLVED (partial) | Extended `VARIANT_OPTION_VALUE_UI_NOISE_PHRASES` in `config/extraction_rules.py` with "add to cart", "add to bag", "account.wishlist", "increment quantity", "pickup unavailable", "lifetime warranty", "free trial", "day free trial", etc. Covers LEGO / REI / Sweetwater / ROAM Luggage / Best Buy cases. Deeper DOM-structure filtering still tracked under Zyte-delta Slice 2. |
| DQ-3 | Stringified JSON in variant color (Bombas) | DEFERRED | Must be fixed upstream in the structured-source mapper. Unwrapping dict-reprs inside `coerce_text` conflicts with the existing "reject raw object reprs in scalar fields" contract (see `test_option_scalars_reject_raw_objects_and_null_tokens`). |
| DQ-4 | Negative prices (-1, -9 defaults) | RESOLVED | `normalize_decimal_price` now drops negative Decimals. Regression: `test_normalize_decimal_price_rejects_negative_values`. |
| DQ-5 | Currency/price mismatch (Glossier INR) | OPEN | Needs structured-source mapper change to bind currency to the same offer node as price. |
| DQ-6 | DOM text concatenation in features/descriptions | RESOLVED (partial) | Added nav-tab concatenation phrases ("overview specs specifications compatibility resources support software" etc.) to `DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES` — covers the Canon case. Broader DOM-scope fix (target `.product-description` / `#details` instead of tab containers) still tracked under Zyte-delta Slice 6. |
| DQ-7 | Parent vs variant price mismatch | RESOLVED | `reconcile_parent_price_against_variant_range` in `detail_price_extractor.py` now adopts the unanimous variant price as the parent when both are within 0.5x..2x (same order of magnitude). Skips cents-magnitude cases (left to `reconcile_detail_price_magnitudes`) and authoritative sources (`network_payload`). Regression: `test_repair_ecommerce_detail_reconciles_parent_price_against_unanimous_variants` and `test_repair_ecommerce_detail_skips_variant_range_reconcile_when_magnitudes_differ`. |
| DQ-8 | Category extracted as URL path (Vans) | RESOLVED | `coerce_field_value("category", ...)` now rejects URL-path strings via `_category_value_is_url_path` (covers `https:`, `://`, `www.`, common TLDs). Regression: `test_coerce_field_value_category_rejects_url_path_strings`. |
| DQ-9 | Title quality / missing names | RESOLVED (partial) | Added "kids boys" / "kids girls" / "kids boy" / "kids girl" / "boys kids" / "girls kids" to `DETAIL_LOW_SIGNAL_TITLE_VALUES` so LUISAVIAROMA's bare gender-category titles trigger title promotion. SKU-prefix / trailing variant-suffix cases (Sweetwater, MR PORTER) still tracked under Zyte-delta Slice 6 — too risky to strip heuristically without losing legitimate model names. |
| DQ-10 | Zero-percent materials | RESOLVED | `_clean_materials_pollution` now drops chunks matching `_MATERIALS_ZERO_PERCENT_PATTERN` (`0%`, `0.0%`, `0 %`). Harrods "OUTER: 0% Silk..." case now yields only the non-zero `FILLING: 100% Feather Down` segment. |

---

Executive Summary
Total records audited: 41
Domains audited: 35
Critical issue count: 5
High issue count: 4
Medium issue count: 3
Low issue count: 3
Top 5 recurring patterns:
UI button text and fulfillment statuses extracted as variant axes (sizes/colors).
Missing decimal points causing 100x price inflation.
Un-separated DOM text concatenation in descriptions and features.
Negative default values (-1, -9) leaking into price fields.
Titles polluted with SKUs, variant options, or completely missing the product name.
Field Health Matrix
Field	Health	Common failures	Affected record indexes	Fix priority
price	negative defaults (-1, -9).	21, 25, 32, 34	High
currency	MIXED	Mismatch between extracted price value and currency code.	28	High
variants[].size / color	BAD	Capturing UI buttons ("Add to Cart", "Next"), fulfillment text, or stringified JSON.	2, 8, 9, 30, 37, 40	High
description / features	BAD	Concatenating unrelated page text, nav menus, or all variant descriptions without separators.	3, 5, 8, 19, 29, 30	Medium
title	MIXED	Appending variant details, prepending SKUs, or capturing generic text ("kids boys").	7, 17, 18, 19	Medium
category	MIXED	Extracting raw URL paths instead of breadcrumb text.	4	Low
materials	MIXED	Extracting "0%" materials or duplicating text.	5, 20	Low
Critical Findings
DQ-1: Price Decimal Scaling Errors
Severity: CRITICAL
Confidence: HIGH
Records: 21, 25
DQ-2: UI Elements Extracted as Variant Axes
Severity: CRITICAL
Confidence: HIGH
Records: 8, 9, 30, 37, 40
Domains: bestbuy.com, rei.com, lego.com, store.hermanmiller.com, roamluggage.com
Fields: variants[].size, variants[].color, variants[].style
Evidence type: internal consistency
Evidence:
LEGO sizes: "Add to Bag", "Next", "account.wishlist.notInList"
REI sizes: "Add a lifetime membership to cart for", "Increment Quantity"
ROAM Luggage sizes: "100-Day Free Trial", "Lifetime Warranty"
Best Buy styles: "Pickup Unavailable from this seller"
Why this is wrong: The variant mapper is blindly scraping dropdowns, list items, or grid buttons without filtering out non-purchasable UI actions, fulfillment methods, or marketing banners.
Likely upstream owner: variant mapper
Likely fix direction: Restrict variant axis extraction to actual product option selectors, excluding add-to-cart blocks, quantity selectors, and shipping toggles.
Regression test idea: Assert that variants[].size does not contain "Add to Cart" or "Quantity".
DQ-3: Stringified JSON in Variant Color
Severity: CRITICAL
Confidence: HIGH
Records: 2
Domains: bombas.com
Fields: variants[].color
Evidence type: schema/format
Evidence: "{'id': 'black-onyx', 'title': 'black onyx', 'swatch': {'id': '7csvZrVqBm3bqzhRMmtPZj', '__typename': 'Asset'}, 'group': None, '__typename': 'Color'}"
Why this is wrong: The extractor grabbed the raw React/GraphQL state object instead of parsing out the title or id string.
Likely upstream owner: structured source mapper
Likely fix direction: Parse the JSON object and extract the title field rather than casting the entire object to a string.
Regression test idea: Assert variants[].color does not contain { or __typename.
DQ-4: Negative Prices
Severity: CRITICAL
Confidence: HIGH
Records: 32, 34
Domains: gucci.com, sony.co.in
Fields: price
Evidence type: internal consistency
Evidence: Gucci price -1, Sony price -9.
Why this is wrong: Negative prices are impossible in ecommerce. These are clearly default/fallback values from the site's backend or structured data that were exposed when the actual price was hidden or required user interaction.
Likely upstream owner: normalizer
Likely fix direction: Drop prices that are < 0 and treat them as missing/null.
Regression test idea: Assert price >= 0 across all records.
DQ-5: Currency and Price Value Mismatch
Severity: CRITICAL
Confidence: HIGH
Records: 28
Domains: glossier.com
Fields: price, original_price, currency
Evidence type: internal consistency
Evidence: price: "16.00", original_price: "5400.00", currency: "INR".
Why this is wrong: 16.00 INR is ~
0.19
U
S
D
,
w
h
i
c
h
i
s
i
n
c
o
r
r
e
c
t
f
o
r
a
G
l
o
s
s
i
e
r
l
i
p
b
a
l
m
.
T
h
e
‘
p
r
i
c
e
‘
i
s
c
l
e
a
r
l
y
i
n
U
S
D
(
0.19USD,whichisincorrectforaGlossierlipbalm.The‘price‘isclearlyinUSD(
16.00), but the currency was extracted as INR, and original_price grabbed a completely unrelated number (5400).
Likely upstream owner: structured source mapper
Likely fix direction: Ensure currency extraction is tied to the same DOM node or JSON block as the price value to prevent cross-contamination.
Regression test idea: Assert original_price is not > 100x the price unless explicitly verified.
High And Medium Findings
DQ-6: DOM Text Concatenation in Features/Descriptions
Severity: HIGH
Confidence: HIGH
Records: 3, 19, 29, 30
Domains: patagonia.com, luisaviaroma.com, usa.canon.com, lego.com
Fields: description, features
Evidence type: internal consistency
Evidence:
Canon features: "Overview Specs Specifications Compatibility Resources Support Software"
LEGO features: "Punch it!\" ... 6+ 4.4 $5.99 6+ 3.6 $4.99 ..."
Patagonia description: "... - Aquatic Blue We built the Nano Puff... - Black We built the Nano Puff..."
Why this is wrong: The extractor is grabbing the innerText of a high-level container (like the whole page body or a tabbed container), pulling in nav menus, related product prices, and hidden variant descriptions without spacing.
Likely upstream owner: DOM extractor
Likely fix direction: Target specific product description containers (.product-description, #details) rather than generic wrappers, and use innerHTML to <br> conversion instead of raw innerText.
Regression test idea: Assert features does not contain "Overview Specs Specifications".
DQ-7: Parent vs Variant Price Mismatch
Severity: HIGH
Confidence: HIGH
Records: 15
Domains: selfridges.com
Fields: price, variants[].price
Evidence type: internal consistency
Evidence: Parent price: "190.00", but both variants (50ml, 100ml) have price: "310.00".
Why this is wrong: The parent price should reflect the default variant or a range. A parent price of 190 when all variants are 310 indicates the parent price was scraped from a related product, a stale cache, or an incorrect DOM element.
Likely upstream owner: DOM extractor
Likely fix direction: If parent price contradicts all variant prices, recalculate parent price from the default/first variant.
Regression test idea: Assert parent price exists within the set of variant prices.
DQ-8: Category Extracted as URL Path
Severity: HIGH
Confidence: HIGH
Records: 4
Domains: vans.com
Fields: category
Evidence type: schema/format
Evidence: "https: > www.vans.com > en-us > c > shoes > icons > old-skool-5205"
Why this is wrong: The category field should contain human-readable breadcrumbs (e.g., "Shoes > Icons > Old Skool"), not a literal URL string split by >.
Likely upstream owner: text cleaner
Likely fix direction: Fall back to DOM breadcrumbs if structured data provides a URL instead of a category name.
Regression test idea: Assert category does not contain https:.
DQ-9: Title Quality and Missing Names
Severity: MEDIUM
Confidence: HIGH
Records: 7, 17, 18, 19
Domains: sweetwater.com, mrporter.com, net-a-porter.com, luisaviaroma.com
Fields: title
Evidence type: internal consistency
Evidence:
LUISAVIAROMA: "kids boys" (missing actual product name).
Sweetwater: "Wh1Kxm5Blk Sony Wh 1000Xm5..." (SKU prepended).
MR PORTER: "Pasha Aviator-Style Silver-Tone Sunglasses - silver - One Size" (variant details appended).
Why this is wrong: Titles should represent the clean product name. Capturing generic category text ("kids boys") means the actual title selector failed. Appending SKUs/sizes creates dirty data.
Likely upstream owner: DOM extractor
Likely fix direction: Prioritize og:title or structured data name over raw <h1> tags which often contain injected SKUs or variant strings.
Regression test idea: Assert LUISAVIAROMA titles are not exactly "kids boys".
DQ-10: Zero Percent Materials
Severity: MEDIUM
Confidence: HIGH
Records: 20
Domains: harrods.com
Fields: materials
Evidence type: internal consistency
Evidence: "OUTER: 0% Silk OUTER: 0% Lyocell FILLING: 100% Feather Down"
Why this is wrong: "0% Silk" is likely a hidden DOM element, an unchecked box in a specs table, or a misinterpretation of a care label.
Likely upstream owner: DOM extractor
Likely fix direction: Filter out material strings that explicitly state 0%.
Regression test idea: Assert materials does not contain 0%.
Low Priority Cleanup
Duplicate Image URLs: Gymshark (Record 0) and Allbirds (Record 1) contain 10+ URLs in additional_images that are just different resolutions of the exact same image. The image collector should deduplicate by base URL/path, ignoring width/height query parameters.
Raw Brackets in Specs: Urban Outfitters (Record 11) specifications contains [ Product Sku: 101211381; Color Code: 048 ... ]. The text cleaner should strip these internal CMS brackets.
Cut-off Descriptions: Sweetwater (Record 7) and Notre (Record 21) have descriptions that end abruptly without punctuation.
Per-Domain Notes
lego.com:
Bad signals: Capturing "Add to Bag" and "account.wishlist.notInList" as sizes. Features contain concatenated reviews.
Most likely broken extractor stage: Variant mapper.
First fix to try: Restrict variant extraction to actual <select> or radio button option groups.
roamluggage.com:
Bad signals: Capturing "100-Day Free Trial" and "Lifetime Warranty" as sizes.
Most likely broken extractor stage: Variant mapper.
First fix to try: Exclude non-purchasable marketing badges from variant axis arrays.
bombas.com:
Bad signals: Stringified JSON in color field.
Most likely broken extractor stage: Structured source mapper.
First fix to try: Parse JSON and extract .title.
Fix Backlog For Codex
Priority	Bug pattern	Affected fields	Affected domains/records	Suspected owner	Suggested test
1	Missing decimal in price	price	notre-shop.com, onepeloton.com	normalizer	price < 10000 for standard apparel/shoes
2	UI buttons as variants	variants[].size/color	lego.com, rei.com, roamluggage.com	variant mapper	variants[].size != "Add to Cart"
3	Negative prices	price	gucci.com, sony.co.in	normalizer	price >= 0
4	Stringified JSON	variants[].color	bombas.com	structured source mapper	variants[].color does not contain {
5	Currency/Price mismatch	currency, original_price	glossier.com	structured source mapper	original_price is within 10x of price
Do Not Fix Downstream
Negative prices (-1, -9): Do not map -1 to null downstream. The crawler must stop emitting negative prices entirely.
Stringified JSON in colors: Do not write regex to parse {'title': 'black'} in the export layer. The upstream mapper must handle the object correctly.
Needs Human Or Browser Verification
Glossier (Record 28): Need to verify if the original price of 5400 is actually on the page (e.g., a bundle price or a free shipping threshold in INR) or if it's a complete hallucination.
Selfridges (Record 15): Need to verify if the base product is actually £190 (perhaps for a smaller unlisted size) while the 50ml/100ml variants are £310.