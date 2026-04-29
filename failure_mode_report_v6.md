# Failure Mode Report v6 — logs6.md / json8.md

## Scope

`logs6.md` covers **36 seed URLs**. Pipeline verdict: **partial** (34/36 records persisted).

---

## Complete Extraction Failures (0 records)

| Site | URL | Rejection Reason | Evidence (logs6.md) | Status |
|------|-----|------------------|---------------------|--------|
| **Lowes** | Minka Lavery Pendant Light | `detail_identity_mismatch` | Line 229-236: real Chrome loaded product page in 4136ms, but extraction yielded 0 records; persisted URL was `lowes.com/l/about/ai-at-lowes` (redirect/mismatch) | **Regression** — was recovered in v5 |
| **New Balance** | 574 Core | `challenge_shell` | Line 337-338: patchright rejected as challenge_shell; real Chrome loaded page in 1481ms but extraction still rejected as challenge_shell | **Persistent** |

**Total: 2 failures out of 36 URLs (5.6% failure rate)**

---

## Fixed / Improved in Overlap Sites (v5 → v6)

| Site | Field / Issue | v5 State | v6 State |
|------|---------------|----------|----------|
| **Nike** Air Force 1 | `price` | Completely empty across all 19+ variants | **FIXED** — all variants have `"price": "115"`, parent has price |
| **Adidas** Stan Smith | `price` | Completely empty across all variants | **FIXED** — parent has `"price": "100"` |
| **StockX** | `sku` | Fake UUID `5e6a1e57...` | **FIXED** — now correct style code `DD1391-100` |
| **Home Depot** | Cross-sell image leakage | 12/14 `additional_images` were unrelated tiles | **FIXED** — only 3 images, all correct product |
| **Nordstrom** | Extraction | `detail_identity_mismatch`, 0 records | **FIXED** — 1 record extracted successfully |
| **Zappos** | Extraction | `detail_identity_mismatch`, 0 records | **FIXED** — 1 record extracted successfully |
| **Zara** | Extraction | `detail_identity_mismatch`, 0 records | **FIXED** — 1 record extracted successfully |
| **Lululemon** | Extraction | Timeout (105s), 0 records | **FIXED** — 1 record with full variant matrix (8 colors × 9 sizes) |
| **Sephora** | Extraction | Timeout (105s), 0 records | **FIXED** — 1 record with 50+ color variants extracted |
| **Dick's Sporting Goods** | Extraction | Error page / challenge_shell | Already fixed in v5 via real Chrome; still working in v6 |
| **REI** | `barcode` | Correct string (fixed in v5) | Still correct |
| **Pura Vida** | Cross-sell images | Fixed in v5 | Still correct |
| **Frank Body** | Non-HTTPS URLs | Fixed in v5 | Still correct |

---

## Persistent Issues in Overlap Sites (v5 → v6)

| Site | Issue | v5 State | v6 State |
|------|-------|----------|----------|
| **ASOS** | Identity mismatch / wrong product | Barrel pants data for t-shirt URL | **Unchanged** — URL still malformed (`…barrel-pants…/prd/jjxx/…t-shirt…`), `description` and `product_details` still describe barrel pants while `title` says "JJXX marilyn oversized T-shirt" |
| **ColourPop** | Variant leakage | 25+ unrelated palettes in `variant_axes.shade` | **Unchanged** — 26 leaked shades including `Pink Dreams`, `Silver Lining`, `Blowin' Smoke`, etc. `size: "24"` and `color: "#000000"` still wrong |
| **Fashion Nova** | UI element pollution | `toggle_color_swatches` injected into variants | **Unchanged** — still present in 4 color variant entries |
| **Macy's** | Sparse variants + broken images | No variant metadata, beacon-sized thumbnails | **Changed** — variants now have color options, but `title` is generic "MENS SHOES" (should be specific shoe model). `description` now has **cross-product pollution** (mentions "Hiser men's lace up oxford", "Calvin Klein Adeso dress shoe", and "Club Room casual dress shoes" in same field). Additional images now 30+ URLs with mixed product IDs |
| **PUMA** | Placeholder category, wrong SKU, price format | `category: "Category"`, GTIN as SKU, price without decimal | **Unchanged** — `sku: "4069159504308"` (GTIN), `price: "9999"` (no decimal), `category` absent |
| **Decathlon** | Specification pollution, truncated description | Shoe material description for balls, `description` ends with `…` | **Unchanged** — `specifications` still has "The main material of a shoe…", `description` still truncated |
| **Ulta** | Wrong `product_type`, cross-sell swatches | `product_type: "CriteoProductRail"`, swatch images in `additional_images` | **Unchanged** — `product_type` still ad-platform name. Cross-sell swatches still present |
| **B&H Photo** | Missing images | No `image_url` or `additional_images` | **Unchanged** — still absent. `size: "1"` is wrong (should be 32") |
| **Farfetch** | Price missing decimal | `"price": "13880"` ambiguous | **Unchanged** — still no decimal |
| **SSENSE** | No sku/barcode, price format | Parent lacks `sku`/`barcode`, `"price": "3890"` | **Unchanged** — variants still lack `sku`, `barcode`, `variant_id`, `image_url`, `availability` |
| **GOAT** | Very sparse extraction | Only 8 fields | **Unchanged** — still missing `brand`, `price`, `currency`, `availability`, `variants`, `barcode`, `review_count` |
| **Amazon** | Sparse extraction, no price | 7 fields, no `price`/`currency`/`availability` | **Partially improved** — now has `features`, `product_type`, `part_number`, `product_details`, `review_count`. Still **missing `price`, `currency`, `availability`, `variants`, `barcode`** |
| **JD Sports** | Missing fields | No `sku`, `product_id`, `variants`, `barcode` | **Unchanged** — still missing |
| **Apple** iPhone 16 | Missing fields, wrong description | `description` is trade-in offer, missing `variants`, `barcode`, `availability` | **Unchanged** |
| **Kith** | No price, wrong barcodes | `"price": "28200"` (cents bug) in v5, first 8 variants had SKU as barcode | **Changed** — now **no `price` field at all** in parent or variants. Barcodes still missing on most variants |
| **Target** | Missing fields | Not in v5 overlap | **New in overlap** — no `sku`, `price`, `brand`, `variants`. `description` is about delivery/pickup options, not product |
| **Wayfair** | Sparse extraction | Not in v5 overlap | **New in overlap** — missing `sku`, `price`, `brand`, `variants`, `barcode`, `currency`, `availability`. `additional_images` includes user photos from different product IDs |
| **Costco** | Empty description | `"description": "Product Label ​"` | **Unchanged** — still nearly empty. Variants lack `barcode`, `variant_id` |
| **Walmart** | Truncated specs, legal boilerplate | `specifications` ended with "More details", massive legal text in `product_details` | **Unchanged** — still present |

---

## New Critical Issues (v6 — Field-Level Data from json8.md)

| Site | Issue | Evidence |
|------|-------|----------|
| **Lowes** | Complete regression — real Chrome loads page but extraction yields 0 records with `detail_identity_mismatch`; persists wrong URL (`lowes.com/l/about/ai-at-lowes`) | Was recovered in v5 via real Chrome. Now fails despite successful page load. |
| **Macy's** | Cross-product description pollution | `description` mentions three different shoe models in one field: "The Hiser men's lace up oxford", "Calvin Klein Adeso dress shoe", and "Club Room casual dress shoes". Generic title "MENS SHOES" instead of product name. |
| **Sephora** | `features` UI pollution | `"features": "1 2 3 4 5 6 7 8 9 10"` — this is star-rating widget text, not product features |
| **Zappos** | Broken image URLs in `additional_images` | Contains Amazon CDN URLs with invalid size suffixes: `…_AC_SR1224`, `…_AC_SR1532`, `…_AC_SR1840`, `…_AC_SR300`, `…_AC_SR608`, `…_AC_SR916` (missing file extension). Also has `kratos` path URLs that may be internal thumbnails. |
| **Zara** | Cross-sell image leakage (minor) | Last `additional_images` entry is `07223038250` — a different product (not the Rustic Cotton T-shirt) |
| **ASOS** | `selected_variant` lacks `option_values` | `selected_variant` only has `sku`, `price`, `currency`, `image_url`, `availability` — no `size` or `color` selected |
| **Kith** | Missing `price` entirely | Parent and all 29 variants have **no `price` field**. All variants are `out_of_stock` which may suppress price extraction. |
| **Wayfair** | Missing core fields | No `sku`, `price`, `brand`, `variants`, `barcode`, `currency`, `availability`. Only `title`, `rating`, `features`, `image_url`, `materials`, `description`, `product_type`, `review_count`, `specifications`, `additional_images` present. |
| **Target** | Missing core fields | No `sku`, `price`, `brand`, `variants`, `barcode`, `currency`, `availability`, `product_id`. `description` is generic shipping/pickup text. |
| **B&H Photo** | `size` wrong + missing images | `size: "1"` should be `32"`. No `image_url`, `additional_images`, or `variants` array despite `variant_axes` present. |

---

## Missing Fields Frequency (json8.md)

| Field | Count | Sites |
|-------|-------|-------|
| `price` | 5 | Kith (no field), Amazon (no field), Target (no field), Wayfair (no field), Home Depot (no field) |
| `sku` | 4 | SSENSE, Target, Wayfair, Home Depot |
| `brand` | 3 | Target, Wayfair, GOAT |
| `image_url` | 1 | B&H Photo |
| `additional_images` | 1 | B&H Photo |
| `variants` | 5 | Amazon, GOAT, Target, Wayfair, Home Depot |
| `barcode` | 4 | SSENSE, Target, Wayfair, Home Depot |
| `product_id` | 2 | JD Sports, GOAT |
| `availability` | 3 | SSENSE (variants lack it), Target, Wayfair |
| `variant.sku` | 3 | SSENSE, Macy's (color variants lack SKU) |
| `variant.barcode` | 3 | SSENSE, Macy's, Home Depot |
| `variant.variant_id` | 3 | SSENSE, Macy's, Home Depot |
| `variant.image_url` | 3 | SSENSE, Macy's, Home Depot |
| `variant.availability` | 2 | SSENSE, Macy's |
| `currency` | 2 | Amazon, Wayfair |
| `description` (meaningful) | 3 | Costco ("Product Label"), Target (shipping text), Apple (trade-in offer) |

---

## Infrastructure / Runtime Failures (v6)

| Failure | Site / URL | Detail | Status |
|---------|-----------|--------|--------|
| `detail_identity_mismatch` | Lowes Minka Lavery Light | Real Chrome loaded product page in 4136ms, but extraction rejected as identity mismatch; persisted wrong URL | **Regression from v5** |
| `challenge_shell` | New Balance 574 Core | Patchright rejected; real Chrome loaded page in 1481ms but extraction still rejected | **Persistent** |
| Bot protection → real Chrome fallback | Dick's Sporting Goods | Patchright rejected, real Chrome succeeded | **Recovered** (same as v5) |
| Bot protection → real Chrome fallback | Home Depot | Patchright rejected, real Chrome succeeded | **Recovered** (same as v5) |
| Rate limiting → real Chrome fallback | REI | Patchright detected bot protection, real Chrome succeeded | **Recovered** (same as v5) |

---

## Root Cause Status (Updated from v5)

1. **Identity mismatch / wrong product extraction** — **IMPROVED**: ASOS still broken (malformed URL). Lowes now fails with identity mismatch (regression). Nordstrom, Zappos, Zara all fixed.

2. **DOM selector drift / bot protection** — **IMPROVED**: Dick's, Home Depot, REI still recovered via real Chrome. Lowes regressed (page loads but extraction fails). New Balance still blocked.

3. **Over-inclusive scraping (images + text)** — **IMPROVED**: Home Depot cross-sell images fixed. Macy's now has cross-product description pollution (new). Zappos has broken CDN image URLs. Zara has one cross-sell image. ColourPop variant leakage persistent.

4. **UI element pollution** — **PERSISTENT**: Sephora `features` has "1 2 3 4 5 6 7 8 9 10" star widget text. Fashion Nova still has `toggle_color_swatches`. ASOS parent `size` has "Size Guide Please select…" text.

5. **Format / precision issues** — **PARTIALLY FIXED**: Nike and Adidas prices now present. Kith lost all price fields. Farfetch/SSENSE prices still lack decimals. PUMA `price: "9999"` still wrong.

6. **Sparse extraction** — **IMPROVED**: Amazon gained fields but still missing price/currency. GOAT unchanged. Wayfair and Target newly sparse.

7. **Timeout failures** — **ELIMINATED**: Lululemon, Sephora, Zappos all now extract successfully. Zero timeout failures in v6.

8. **Bot protection / challenge shells** — **IMPROVED**: New Balance is the only remaining unrecoverable challenge shell. Lowes real Chrome loads but extraction fails (new failure mode).

---

## Summary Statistics

| Metric | v5 (39 URLs) | v6 (36 URLs) | Delta |
|--------|-------------|-------------|-------|
| Total URLs | 39 | 36 | -3 |
| Successful extractions | 29 | 34 | **+5** |
| Complete failures (0 records) | 10 | 2 | **-8** |
| Timeout failures | 4 | 0 | **-4** |
| Identity mismatch rejections | 5 | 1 | **-4** |
| Challenge shell rejections | 1+ | 1 | stable |
| Sites with missing price | 3 | 5 | +2 (Nike/Adidas fixed; Kith/Target/Wayfair lost price) |
| Sites with cross-sell image leakage | 4 | 2 | -2 (Home Depot/Zara fixed; Macy's desc pollution new) |
| Sites recovered via real Chrome | 4 | 3 | -1 (Lowes regressed) |
| Success rate | 74.4% | **94.4%** | **+20.0%** |
