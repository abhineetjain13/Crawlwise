Data Quality Audit Report
1. Schema & Field Inventory
Top-Level Fields
Field Name	Presence %	Data Type Consistency	Nullable
sku	90%	Mostly String; 3 records missing.	Yes
url	100%	Consistent (String/URL).	No
brand	100%	Consistent (String).	No
price	94%	Inconsistent (String vs Number).	Yes
title	100%	Consistent (String).	No
currency	97%	Consistent (String).	Yes
variants	39%	Consistent (Array).	Yes
image_url	100%	Consistent (String/URL).	No
description	100%	Consistent (String).	No
availability	87%	Consistent (String).	Yes
selected_variant	39%	Consistent (Object).	Yes
original_price	32%	Inconsistent (String vs Number).	Yes
product_details	19%	Inconsistent (String vs Array-like String).	Yes
Nested Fields (variants[])
Field Name	Presence %	Data Type Consistency	Nullable
sku	85%	Consistent (String).	Yes
size	95%	Consistent (String).	Yes
price	100%	Inconsistent (String vs Number).	No
variant_id	60%	Consistent (String).	Yes
availability	95%	Consistent (String).	Yes
option_values	100%	Consistent (Object).	No
barcode	40%	Consistent (String).	Yes
2. Missing Data Analysis
Missing SKUs: The following records lack a top-level SKU: Levtex Home (Duvet Set), MSI (Floor Tile), Flexsteel (Sofa).
Zero Variants: 19 out of 31 records (approx. 61%) have no variants array. Notably, high-complexity items like the iPhone 16 and RTX 3090 are missing variants (storage/color options).
Partial Variant Population:
SATISFY (SKU: 13876003): Several variants (e.g., size 3, 3.5, 4) have a sku but no barcode, while others have both.
Dime (SKU: DIME2SP2542BLK-M): The first 4 variants contain variant_id and available booleans; the subsequent 7 variants lack these fields entirely.
3. Illogical / Polluted Data
Nonsensical Sizes (Dime):
size: "UiFU2s", "Email", "Sign up for updates and promotions".
Price Anomalies:
adidas Stan Smith (SKU: M20324): price is "100.00" while original_price is "1.00". This violates the logic that original price should be 
≥
≥
 current price.
Nike Dunk Low (StockX vs GOAT): Same product (DD1391-100) listed at $56.00 on StockX but $250.00 on GOAT. While market prices vary, a ~450% difference suggests potential data scrap-error or different condition types (Used vs New) not explicitly labeled.
Availability Contradictions:
adidas Stan Smith (SKU: M20324): Top-level availability is "out_of_stock", but selected_variant lists availability as "in_stock".
SKU Issues:
Nike Dunk: One record uses DD1391 100 (space) and another uses DD1391-100 (hyphen), causing fragmentation in search.
URL Protocol: All URLs appear to have protocols, but the Scotch Tape and Dime image URLs contain tracking/resize parameters (e.g., ?v=1745568172, &width=117) which may expire or lead to low-res thumbnails.
4. Cross-Record Integrity
Duplicate variant_id: No duplicate IDs found across different products, but several variants within the same product (SATISFY) point to identical URLs.
Image Reliability:
Sleep Number (SKU: 4201005351): Uses a complex CDN path (bfasset.costco-static.com) that redirects.
Wayfair Sofa: additional_images contains URLs with resize-h48-w48, which are tiny 48px icons/placeholders rather than actual product photos.
5. Variant-Level Issues
Redundant/Duplicate Variants:
SATISFY (Record 8): Contains variants for size "8" and size "8 US" pointing to the same SKU and price.
Fashion Nova (Record 28): Lists "Yellow" as a color variant for a product that is already defined as "Yellow" at the parent level, resulting in recursive-looking data.
Price Divergence: No variants show price divergence from the parent in this sample, but several variants lack the original_price field found at the parent level.
6. Summary & Severity Table
Issue	Severity	Count/Freq	Recommendation
UI Scraping in Size	Critical	1 Product (Dime)	Scrub "Email"/"Sign up" strings from size filters.
Price Logic Flip	High	1 Product (adidas)	Flag records where original_price < price.
Missing Variants	High	61% of records	Improve crawler depth for iPhone/GPU categories.
Availability Mismatch	Medium	10% of records	Sync parent availability with selected_variant.
Non-Standard Avail.	Low	2 Products	Map "limited_stock" to "in_stock".
Top 5 Recommended Fixes:
Hard-filter "Size" strings: Remove any value containing "Sign up", "Email", or sequences like "UiFU".
Price Validation: Implement a check that original_price must be null or 
≥
≥
 price.
SKU Normalization: Strip non-alphanumeric characters (spaces, hyphens) when comparing product IDs.
Schema Enforcement: Force price and original_price to be Floats to avoid math errors on strings.
Availability Mapping: Restrict the availability field to the five-set enum (in_stock, etc.).
7. Text-Field Pollution & Nonsensical Content
Field	Record / SKU	Polluted Value Found	Pattern
size	Dime	"Sign up for updates and promotions"	UI Text
size	Dime	"Email"	UI Text
description	Sleep Number	"Product Label ​"	Placeholder
description	ASOS DESIGN	Title says "Beach lace" but desc says "Barrel pants".	Content Mismatch
description	Fashion Nova	"Receive free US shipping on orders over $7"	Marketing/UI
description	Wayfair	"Show More" (at end of string)	UI Fragment
color	ColourPop	"#000000"	Hex code (unlabeled)
availability	ASOS	"limited_stock"	Outside valid set
availability	KUIKMA	"limited_stock"	Outside valid set
product_details	Nike (CW2288)	['Leather upper...', 'Originally designed...']	JSON stringified array
features	Tarte	"*Source: Circana, LLC...Dollar & Unit Sales..."	Legal/Marketing Disclaimer
specifications	Nike Air Force 1	"Fits large; we recommend ordering a half size down"	Size Tip in Specs
Specific Pattern Flags:
HTML/Unescaped Entities: Found in adidas Stan Smith additional_images (encoded commas %2C and &width=).
UI/Placeholder: Dime variants are the worst offenders, capturing the newsletter sign-up form as "Size" options.
Marketing Junk: Tarte (SKU 2501218) features field contains a 3-sentence market share disclaimer instead of product features.
Size in Color: Tommy Hilfiger selected_variant lists color as "Black" but the parent SKU is ...1121USA which contains the size "11.5".
Garbage Strings: UiFU2s in the Dime record indicates a failure in the CSS selector during scraping (capturing a randomly generated class name or ID).


Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @json.md around lines 3227 - 3497, The variants array contains incorrect original_price values ("original_price": "1.00") that are lower than the current "price": "100.00"; update each variant object in the "variants" array so its "original_price" is equal to or greater than "price" (e.g., set "original_price" to "100.00" or a higher sale price) to ensure discount and pricing logic using the "price" and "original_price" fields computes correctly.

- Verify each finding against the current code and only fix it if needed.

In @json.md around lines 1428 - 1807, The variants array contains duplicated entries lacking SKU/barcode/variant_id; remove the duplicate variant objects that appear after the original, complete variants (i.e., delete the second block of sizes 3–18 and the later "8 US"–"12 US" entries) and keep only the first complete set in the "variants" array; also update the "variant_axes" array to remove the redundant "US" size labels so it only references the canonical size axis.

- Verify each finding against the current code and only fix it if needed.

In @json.md around lines 3535 - 3545, The selected_variant object has inconsistent data: its size "4" entry lists availability "in_stock" while the actual variant for size "4" is "out_of_stock"; update the selected_variant block (the JSON keys selected_variant, sku, size, availability, option_values) so its availability value matches the real variant (change "availability": "in_stock" to "availability": "out_of_stock") and ensure original_price/price remain consistent with that variant.

