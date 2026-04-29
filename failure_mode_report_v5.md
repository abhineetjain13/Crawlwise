# Failure Mode Report v5 — logs6.md

## Scope

`logs6.md` covers 39 seed URLs, same product catalog as v4 but with real Chrome fallback added for bot-protected sites. Pipeline verdict: **partial** (29/39 records persisted).

---

## Complete Extraction Failures (0 records)

| Site | URL | Rejection Reason | Evidence (logs6.md) | Status |
|------|-----|------------------|---------------------|--------|
| Nordstrom | Treasure & Bond Blouson Jacket | `detail_identity_mismatch` | Line 166-168: "Extraction yielded 0 records (generic extraction path)" | **New Failure** |
| Zappos | Hoka Bondi 9 | `detail_identity_mismatch` | Line 426-428: "Extraction yielded 0 records (generic extraction path)" | **New Failure** |
| Zara | Rustic Cotton T-shirt | `detail_identity_mismatch` | Line 528-530: "Extraction yielded 0 records (generic extraction path)" | **New Failure** |
| Waterstones | 1984 by George Orwell | `challenge_shell` | Line 604-616: rate limiting detected twice, then rejected as challenge_shell | **New Failure** |
| Best Buy | Dell Plus Laptop | **Timeout** (105s) | Line 222: "URL processing timed out" | **New Failure** |
| New Balance | 574 Core | **Timeout** (105s) | Line 362: "URL processing timed out" after real Chrome fallback | **New Failure** |
| Lululemon | ABC Jogger | **Timeout** (105s) | Line 374: "URL processing timed out" after 30s page load | **New Failure** |
| Sephora | Colorful Eyeshadow | **Timeout** (105s) | Line 416: "URL processing timed out" | **New Failure** |

**Total: 10 failures out of 39 URLs (25.6% failure rate)**

---

## New Critical Issues (v5 — Field-Level Data from json6.md)

| Site | Issue | Evidence |
|------|-------|----------|
| **Nike** Air Force 1 | **Price completely missing across all variants** | All 19 variants have `"price": ""`. Parent has no `price` field either. Has `currency: "USD"` but zero price data. |
| **Adidas** Stan Smith | **Price completely missing + UI text pollution in size** | All 23 variants have `"price": ""`. Variant sizes include UI text: `"12.5 is currently unavailable."`, `"13.5 is currently unavailable."`, etc. These same strings appear in `variant_axes.size`. Base64 placeholder image `R0lGODlhAQABAIAAAP/wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==` in `additional_images`. Malformed image URL with `g_auto` path segment. |
| **Kith** (SATISFY) | **Variant prices 100x too high + wrong barcodes + wrong selected_variant title** | Variant `"price": "28200"` instead of `"282.00"` (Shopify cents-not-dollars bug). First 8 variants (sizes 3-7) have `barcode` = SKU number (e.g. `"13875993"`) not real GTIN. Sizes 8+ have real GTINs (`3701313802608`). `selected_variant.title` = `"3"` instead of product title. |
| **Farfetch** | **Price missing decimal** | `"price": "13880"` — should be `13880.00` or `138.80` depending on currency convention. No way to distinguish $13,880 vs $138.80 from data alone. |
| **SSENSE** | **No sku, no barcode, sparse variants** | Parent has no `sku` or `barcode`. All 4 variants lack `sku`, `barcode`, `variant_id`, `image_url`, `availability`. `"price": "3890"` without decimal. Parent `availability: "out_of_stock"` but variants have no availability. |
| **Amazon** (EVGA RTX 3090) | **Extremely sparse extraction** | Only 7 fields extracted: `url, brand, title, rating, image_url, description, review_count`. Missing: `sku, product_id, availability, currency, variants, additional_images, part_number, product_type, features, specifications, product_details, barcode, price`. Amazon adapter producing near-empty records. |
| **GOAT** | **Very sparse extraction** | Only 8 fields: `sku, url, title, image_url, product_id, description, product_type, additional_images`. Missing: `brand, price, currency, availability, variants, barcode, part_number, features, specifications, product_details, review_count`. SKU `"DD1391 100"` is correct style code. |
| **StockX** | **Fake SKU + cross-sell image leakage** | `sku: "5e6a1e57-1c7d-435a-82bd-5666a13560fe"` is an internal UUID, not the product SKU (should be `DD1391-100`). `additional_images` contains 7 cross-sell images of OTHER Nike Dunks (Cave Stone, Court Purple, Grey Fog, Medium Curry, White Midnight Navy). Missing: `variants, part_number, features, specifications, review_count`. |
| **Home Depot** | **Massive cross-sell image leakage + missing fields** | 12 out of 14 `additional_images` are unrelated tile products (desert-trail, earthy-mix-rain-forest, montauk-black, retro-nero, lockson-mix, satin-white-daltile, calacatta-gold, white-matte, adelaide-black-white, carrara, black-gloss). Missing: `price, sku, variants, product_type, part_number`. |
| **Lowes** | **No price + description is document links** | No `price` field. `description` = "Warranty Guide Prop65 Warning Label Use and Care Manual Installation Manual Dimensions Guide" — just a list of document link text, not product description. Missing: `variants, barcode, part_number, product_type, review_count, features, specifications, product_details`. |
| **Costco** | **Empty description and specifications** | `description: "Product Label ​"` — nearly empty. `specifications: "Specifications"` — just the label text. Variants lack `image_url, barcode, variant_id, option_values`. |
| **ASOS** | **Severe identity mismatch (same as v4)** | URL is malformed concatenation of two product paths (`…barrel-pants…/prd/asos-design/…t-shirt…`). `title` = "oversized T-shirt with lace hem" but `description` = "barrel pants" and `product_details` = "Jeans by ASOS Curve Barrel leg". `product_id: "210397084"` is the pants ID, `sku: "210817202"` is the t-shirt SKU. `additional_images` are ALL barrel pants images. `size` field at parent contains "Size Guide Please select US 14 - Out of stock US 16 US 18…" — UI text pollution. |
| **ColourPop** | **Extreme variant leakage (same as v4)** | `variant_axes.shade` has 24 entries (Pink Dreams, Silver Lining, Blowin' Smoke, etc.) — most are unrelated palettes. `size: "24"` and `color: "#000000"` are wrong. `additional_images` contains cross-sell (`PPBlushCompact-ForeverYours`). |
| **Fashion Nova** | **UI element pollution (same as v4)** | `toggle_color_swatches: "Open color swatches"` injected into 4 variant entries. Parent `availability: "out_of_stock"` but variants L-3X are `in_stock`. |
| **Macy's** | **Broken image URLs + sparse variants** | `additional_images` has tracking pixel sizes: `?op_sharpen=1&wid=44&fit=fit` and `?op_sharpen=1&wid=60&fit=fit` — these are thumbnail/beacon URLs, not product images. `sku: "199277621121USA"` looks fabricated. All 8 variants lack `sku, barcode, variant_id, image_url, availability`. |
| **Ulta** | **Wrong product_type** | `product_type: "CriteoProductRail"` — this is an ad platform name, not a product type. Should be "Concealer" or "Makeup". Cross-sell swatch images still present: `2532917_sw`, `2501208_sw`. |

---

## Persistent Issues in Overlap Sites (v4 → v5)

| Site | Issue | v4 State | v5 State |
|------|-------|----------|----------|
| JD Sports | Missing `sku`, `product_id`, `variants` | Same | **Unchanged** — still no `sku`, `product_id`, `variants`, `barcode`, `part_number`. Title omits KV8507. |
| Dick's Sporting Goods | Error page | Broken since v2 | **FIXED** — real Chrome fallback now works. Birkenstock extracted successfully. Cross-sell images still present though. |
| Home Depot | Error page | Broken since v2 | **FIXED** — real Chrome fallback now works. But cross-sell image leakage is severe. |
| Ulta | Cross-sell swatches | Present in v4 | **Unchanged** — `2532917_sw`, `2501208_sw` still in `additional_images`. |
| Adidas | Missing price | Missing in v4 | **Unchanged** — price still completely absent. Now also has UI text pollution in sizes. |
| ColourPop | Variant leakage | 25+ palettes in v4 | **Unchanged** — still 24 leaked shades in `variant_axes`. |
| ASOS | Identity mismatch | Wrong product in v4 | **Unchanged** — still extracting barrel pants data for t-shirt URL. |
| Fashion Nova | UI element pollution | `toggle_color_swatches` in v4 | **Unchanged** — still present. |
| Macy's | Sparse variants, broken images | Same in v4 | **Unchanged** — still no variant metadata, still beacon-sized images. |
| B&H Photo | Missing images | No images in v4 | **Improved** — now has `image_url` and `additional_images` absent but `variants` exist with size data. Actually still no `image_url` or `additional_images` fields at all. |
| PUMA | Placeholder category, wrong SKU | `category: "Category"`, GTIN as SKU in v4 | **Unchanged** — `sku: "4069159504308"` is still a GTIN. `price: "9999"` still lacks decimal. |
| Decathlon | Specification pollution, truncated description | Same in v4 | **Unchanged** — `specifications` still has irrelevant material descriptions ("The main material of a shoe…"). `description` truncated with `…`. |
| REI | Format anomalies | `barcode` as stringified array in v4 | **Improved** — `barcode` now correct string `"0840424803104"`. But `description` still has variant text repeated in parent. `additional_images` only has 1 tiny swatch image. `features: "10 ft. 4 in."` is just a dimension, not features. |
| Pura Vida | Cross-sell image leakage | Present in v4 | **Improved** — all `additional_images` now appear to be the correct product (50907BLCK series). No cross-sell detected. |
| Frank Body | Non-HTTPS duplicate | Present in v4 | **Fixed** — all `additional_images` now use HTTPS or valid CDN paths. |

---

## Fixed / Improved in Overlap Sites

| Site | Field | v4 State | v5 State |
|------|-------|----------|----------|
| Dick's Sporting Goods | Extraction | Error page, 0 records | **Working** — 1 record extracted via real Chrome fallback |
| Home Depot | Extraction | Error page, 0 records | **Working** — 1 record extracted via real Chrome fallback |
| REI | `barcode` | Stringified array `['0840424803104']` | Correct string `"0840424803104"` |
| Pura Vida | Cross-sell images | Unrelated products in `additional_images` | All images now correct product |
| Frank Body | Non-HTTPS URLs | `http://` URLs present | All HTTPS/CDN now |

---

## New Minor Issues (v5)

| Site | Issue |
|------|-------|
| **Apple** iPhone 16 | `description` is about trade-in offer, not the product. Missing: `variants, barcode, availability, product_type, additional_images`. |
| **Walmart** AirPods | `specifications` truncated with "More details" instead of actual specs. `product_details` has massive legal text and battery disclaimers (~1600 bytes of legal boilerplate). `additional_images` has duplicate size variants from CDN (same image at 117px, 160px, 573px). |
| **SSENSE** | `price: "3890"` without decimal formatting. |
| **Farfetch** | `price: "13880"` without decimal — ambiguous (could be $138.80 or $13,880). |
| **UNTUCKit** | `selected_variant.title` = "Wrinkle-Resistant Linen Short-Sleeve Cameron Shirt X-Small / Slim Fit / Blue" but `selected_variant` is actually size Small / Regular Fit. `part_number: "193405401487"` is the barcode for X-Small Slim Fit variant, not the selected Regular Fit Small (`193405392235`). |
| **Decathlon** | `specifications` includes shoe material description ("The main material of a shoe is the main material used to make the outer part of the shoe…") — irrelevant for balls. `description` truncated with `…`. |
| **Lowes** | `description` is just document link text ("Warranty Guide Prop65 Warning Label…"). No actual product description. |

---

## Missing Fields Frequency (logs6.md / json6.md)

| Field | Count | Sites |
|-------|-------|-------|
| `price` | 3 | Nike (all variants empty), Adidas (all variants empty), Lowes (absent) |
| `sku` | 3 | SSENSE, GOAT (no brand/price either), Home Depot |
| `image_url` | 1 | B&H Photo |
| `additional_images` | 1 | B&H Photo |
| `variants` | 5 | Amazon, GOAT, Lowes, JD Sports, Wayfair |
| `barcode` | 2 | SSENSE, Lowes |
| `product_id` | 2 | JD Sports, GOAT |
| `availability` | 1 | SSENSE (parent says out_of_stock, variants lack field) |
| `variant.sku` | 3 | SSENSE, Macy's, Adidas |
| `variant.barcode` | 3 | SSENSE, Macy's, Adidas |
| `variant.variant_id` | 3 | SSENSE, Macy's, Adidas |
| `variant.image_url` | 3 | SSENSE, Macy's, Adidas |
| `variant.availability` | 2 | SSENSE, Macy's |
| `currency` | 1 | Amazon |
| `description` (meaningful) | 2 | Costco ("Product Label ​"), Lowes (document links) |

---

## Infrastructure / Runtime Failures (v5)

| Failure | Site / URL | Detail | Status |
|---------|-----------|--------|--------|
| Timeout (105s) | Best Buy Dell Laptop | No page load or extraction completed | **New** |
| Timeout (105s) | New Balance 574 Core | Real Chrome fallback loaded page but extraction timed out | **New** |
| Timeout (105s) | Lululemon ABC Jogger | Page loaded in 30s but extraction timed out | **New** |
| Timeout (105s) | Sephora Colorful Eyeshadow | Page loaded but extraction timed out | **New** |
| Rate limiting (2x) | Waterstones 1984 | Detected rate limiting on both patchright and real Chrome; rejected as challenge_shell | **New** |
| Rate limiting → real Chrome fallback | Lowes | Patchright detected bot protection; real Chrome succeeded | **Recovered** |
| Rate limiting → real Chrome fallback | REI | Patchright detected bot protection; real Chrome succeeded | **Recovered** |
| Challenge shell → real Chrome fallback | Home Depot | Patchright rejected as challenge_shell; real Chrome succeeded | **Recovered** |
| Challenge shell → real Chrome fallback | Dick's Sporting Goods | Patchright rejected as challenge_shell; real Chrome succeeded | **Recovered** |
| Challenge shell → real Chrome fallback | New Balance | Patchright rejected; real Chrome loaded page but then timed out | **Failed** |

---

## Root Cause Status (Updated from v4)

1. **Identity mismatch / wrong product extraction** — **PERSISTENT**: ASOS still extracts barrel pants for t-shirt URL (URL itself is malformed). New instances: , Nordstrom, Zappos, Zara all rejected as `detail_identity_mismatch`.

2. **DOM selector drift** — **PARTIALLY FIXED**: Dick's and Home Depot now work via real Chrome fallback. JD Sports still missing fields.

3. **Over-inclusive scraping (images + text)** — **PERSISTENT**: Home Depot has 12/14 cross-sell images. Macy's has beacon-sized thumbnails. StockX has 7 cross-sell Dunk images. Ulta still has cross-sell swatches.

4. **UI element pollution** — **PERSISTENT**: Adidas size values include "is currently unavailable." text. Fashion Nova still has `toggle_color_swatches`. ASOS parent `size` has "Size Guide Please select…" text.

5. **Format / precision issues** — **PERSISTENT + NEW**: Nike and Adidas both have completely empty price strings across all variants. Kith prices are 100x (cents-not-dollars). Farfetch/SSENSE prices lack decimals. PUMA `price: "9999"` still no decimal. B&H Photo still missing all images.

6. **Sparse extraction** — **NEW**: Amazon adapter produces near-empty records (7 fields only). GOAT very sparse (8 fields). Lowes missing price + meaningful description. Costco has empty description/specifications.

7. **Timeout failures** — **NEW**: 4 sites timed out (Best Buy, New Balance, Lululemon, Sephora). Lululemon page took 30s to load. New Balance timed out even after real Chrome fallback.

8. **Bot protection / challenge shells** — **PARTIALLY FIXED**: Real Chrome fallback recovers Lowes, REI, Home Depot, Dick's. But Waterstones fails even with real Chrome (double rate-limit). New Balance real Chrome loads page but then times out during extraction.

---

## Summary Statistics

| Metric | v4 (logs5) | v5 (logs6) | Delta |
|--------|-----------|-----------|-------|
| Total URLs | 18 | 39 | +21 |
| Successful extractions | 16 | 29 | +13 |
| Complete failures (0 records) | 2 | 10 | +8 |
| Timeout failures | 0 | 4 | +4 |
| Identity mismatch rejections | 0 | 5 | +5 |
| Sites with missing price | 1 | 3 | +2 |
| Sites with cross-sell image leakage | 4 | 4 | 0 |
| Sites recovered via real Chrome | 0 | 4 | +4 |
| Success rate | 88.9% | 74.4% | -14.5% |

