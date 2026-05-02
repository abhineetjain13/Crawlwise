# Data Enrichment Failure Report — Latest Run (50 Records, 36 Domains)

**Date:** 2026-05-02  
**Run size:** 50 ecommerce detail records  
**Domains:** 36  
**Enrichment job status:** DEGRADED (deterministic tier ran; LLM backfill partial)

---

## Executive Summary

| Tier | Records Enriched | Records Failed / Degraded | Top Failure Modes |
|------|------------------|----------------------------|-------------------|
| Deterministic | 50 | 0 (but 37 have at least 1 wrong/missing enriched field) | Upstream extraction feeds bad data; enrichment scoring too permissive; size gating missing; SEO keyword logic weak |
| LLM backfill | ~17 (35 %) | 33 missing deep fields | Error-path logging gaps, prompt truncation, no category gating |

**Key take-away:** Most enriched-field corruption comes from **upstream extraction bugs**, not enrichment logic. Enrichment should only be blamed when it makes the data worse or when its own deterministic logic is flawed. This report splits every issue into **Upstream** (extraction/pipeline must fix) vs **Enrichment** (enrichment service must fix).

---

## Issue Classification Legend

- **Upstream Bug** — Bad data arrived at enrichment. Enrichment cannot be expected to clean it up. Fix belongs in extraction (`field_value_dom.py`, `field_value_core.py`, `detail_extractor.py`, `normalizers.py`, adapter).
- **Enrichment Bug** — Enrichment logic itself produced wrong output even from acceptable input, or failed to produce output it should have.

---

## Upstream Extraction Bugs (NOT Enrichment's Fault)

These issues must be fixed in the extraction pipeline. Enrichment downstream should **not** add compensating logic.

### UP-1: Price Decimal Scale Errors (5 records)

- **Records:** 8, 9, 19, 43, 48
- **Domains:** farfetch.com, ssense.com, puma.com (IN/AR), grailed.com
- **Field:** `price` (raw extraction)

**Evidence**

- Record 8 (farfetch.com): raw price `104.10` for a ~$10,410 Philipp Plein jacket. European thousands separator `.` misread as decimal.
- Record 9 (ssense.com): raw price `38.90` instead of `3890`.
- Record 19 (puma.com IN): parent `9999` vs variant `99.99`.
- Record 43 (puma.com AR): parent `113999` vs variant `1139.99`.
- Record 48 (grailed.com): raw `10.12` vs description stating "$1012".

**Root Cause**

`normalize_decimal_price` in `normalizers.py` / `field_value_core.py` uses a single locale heuristic. It does not disambiguate based on TLD/domain locale and incorrectly divides integer cents by 100 or misinterprets European thousands separators.

**Owner:** `normalizers.py`, `field_value_core.py`  
**Regression Test:** Assert that `1012` without a decimal in the DOM does not become `10.12` unless the currency/TLD explicitly supports comma-decimal notation.

---

### UP-2: DOM Text Concatenation Missing Spaces (7 records)

- **Records:** 0, 5, 8, 26, 27, 33, 47
- **Domains:** sneakersnstuff.com, amazon.com, farfetch.com, wayfair.com, zara.com, decathlon.co.uk, phase-eight.com
- **Fields:** `description`, `specifications`, `materials`, `features`

**Evidence**

- Record 0: `"Crewneck100% CottonHeavyweight 14ozScreen printed logoPre-shrunk"`
- Record 8: `"black leather appliqué logo textured finish front zip fastening..."`
- Record 47: `"Polyester 100% Care: Delicate Machine Wash Lining: Polyester 100% Reviews ( 23 )"`

**Root Cause**

HTML-to-text utility in `field_value_dom.py` strips block-level tags without replacing them with spaces/newlines. Enrichment receives already-mashed text.

**Owner:** `field_value_dom.py` text cleaner  
**Regression Test:** Assert camelCase-like collisions (e.g., `"CottonHeavyweight"`) do not occur in description fields.

---

### UP-3: Cross-Product Contamination in Variants (3 records)

- **Records:** 3, 28, 29
- **Domains:** stockx.com, frankbody.com, colourpop.com
- **Fields:** `variants`, `variant_axes`, `additional_images`

**Evidence**

- Record 29 (colourpop.com): parent "Going Coconuts" palette has variants for entirely different palettes ("Blowin' Smoke", "It's My Pleasure").
- Record 3 (stockx.com): "Black White Panda" dunk includes images for "White-Midnight-Navy" and "Black-White-Gum".

**Root Cause**

Extractor confuses "Related Products" / "You May Also Like" carousels with the actual product variant grid. Enrichment consumes this polluted data.

**Owner:** `detail_extractor.py` / variant mapper  
**Regression Test:** Assert variant names do not match other known parent products in the same domain.

---

### UP-4: Glossary/Guide Contamination in Raw Text (6 records)

- **Records:** 2, 3, 6, 11, 12, 20, 21, 22, 25, 30, 32, 37, 40, 48
- **Domains:** untuckit.com, toddsnyder.com, etc.
- **Fields:** `description`, `materials`

**Evidence**

- Record 41 (toddsnyder.com): `materials` contains entire fabric glossary ("The word 'seersucker' originates...").
- Record 32 (untuckit.com): `description` contains entire fit guide ("Regular Fit - Our classic cut... Slim Fit...").

**Root Cause**

Extractor captures hidden modals, accordions, or global size/fabric guides into product text fields. Enrichment scans these fields and matches glossary terms.

**Owner:** `field_value_dom.py` DOM extractor  
**Regression Test:** Assert `materials` length is under a reasonable character limit and does not contain definitions for fabrics not used in the product.

---

### UP-5: Wrong Core Identity Fields (4 records)

- **Records:** 14, 20, 38, 46
- **Domains:** homedepot.com, adidas.com, abebooks.com, kitchenaid.com
- **Fields:** `title`, `product_id`, `product_type`, `size`

**Evidence**

- Record 38 (abebooks.com): `title` = "plp" (internal Product Listing Page code).
- Record 46 (kitchenaid.com): `product_id` = "specifications".
- Record 14 (homedepot.com): `product_type` = "BRIGHTCOVE VIDEO".
- Record 20 (adidas.com): `size` = "100" (likely a price/ID mapped to wrong field).

**Root Cause**

CSS selectors or structured data fallbacks target structural DOM IDs/classes or internal tracking variables instead of actual product data.

**Owner:** adapter / `field_value_dom.py` / `field_value_core.py`  
**Regression Test:** Assert `product_id` does not equal generic structural words like "specifications" or "description".

---

### UP-6: UI Elements Extracted as Data (4 records)

- **Records:** 7, 10, 14, 31
- **Domains:** kith.com, costco.com, homedepot.com, puravidabracelets.com
- **Fields:** `variants[].size`, `description`, `product_details`, `care`

**Evidence**

- Record 7: variant size = "View Size Guide".
- Record 10: description = "Product Label ".
- Record 14: product details includes "Ask Magic Apron How soon can I get this delivered...".
- Record 31: care includes "Learn more about our materials and jewelry care here".

**Root Cause**

Extractor blindly grabs all text within parent containers, including buttons, tabs, and interactive prompts.

**Owner:** `field_value_dom.py` DOM extractor  
**Regression Test:** Assert variant sizes do not equal "View Size Guide".

---

### UP-7: Array Stringification Leaks (2 records)

- **Records:** 4, 5
- **Domains:** nike.com, amazon.com
- **Fields:** `product_details`, `features`

**Evidence**

- Record 4: `['Leather upper with perforated toe box...', 'Originally designed...']`
- Record 5: `['Digital Max Resolution:7680 x 4320...', 'Real boost clock...']`

**Root Cause**

Text cleaner casts Python lists directly to strings. Enrichment normalizers then treat literal `['...']` strings as text values.

**Owner:** `field_value_core.py` text cleaner  
**Regression Test:** Assert text fields do not start with `['` and end with `']`.

---

### UP-8: Image Duplication via Query Params (12 records)

- **Records:** 0, 1, 3, 4, 7, 11, 12, 13, 16, 18, 25, 26, 41
- **Field:** `additional_images`

**Evidence**

Same image repeated 5-10 times with different `width`, `height`, or `size` query parameters.

**Root Cause**

Image collector does not deduplicate base URLs before storing.

**Owner:** image collector (`field_value_dom.py` or adapter)  
**Regression Test:** Assert `additional_images` does not contain duplicate base URLs.

---

### UP-9: Missing Core Fields (extraction gap, not enrichment)

- **Records:** 15, 18
- **Domains:** asos.com, wayfair.com
- **Fields:** `price` (completely absent from raw data)

**Evidence**

Records 15 and 18 have no `price`, `sale_price`, or `original_price` in the raw crawl data. Enrichment cannot invent a price.

**Owner:** adapter / DOM extractor  
**Regression Test:** Assert extraction smoke covers asos.com and wayfair.com detail pages.

---

### UP-10: Missing Variant `option_values` (1 record)

- **Record:** 45
- **Domain:** karenmillen.com
- **Field:** `variants[].option_values`

**Evidence**

12 variants with different SKUs but no `option_values` object. Enrichment cannot derive size/color from SKUs alone.

**Owner:** variant mapper (`detail_extractor.py`)  
**Regression Test:** Assert `option_values` exists if `variants` array length > 1.

---

### UP-11: Currency Mismatch (1 record)

- **Record:** 26
- **Domain:** zadig-et-voltaire.com
- **Fields:** `currency` parent vs variant

**Evidence**

Parent currency "GBP", all variants "EUR". Adapter merged responses from two regional API endpoints.

**Owner:** adapter / variant mapper  
**Regression Test:** Assert parent `currency` equals every variant `currency` in a single record.

---

### UP-12: Availability Schema.org URL (2 records)

- **Records:** 14, 45
- **Domains:** homedepot.com, karenmillen.com
- **Field:** `availability`

**Evidence**

`"availability": "https://schema.org/LimitedAvailability"` passed through as raw string. Normalizer only handles boolean/plain text.

**Owner:** `field_value_core.py` coerce_field_value / availability normalizer  
**Regression Test:** Assert Schema.org availability URLs map to internal snake_case enum.

---

### UP-13: Title Truncation (1 record)

- **Record:** 40
- **Domain:** backmarket.com
- **Field:** `title`

**Evidence**

`title` = "iPhone 15 • Unlocked" but URL is `/iphone-15-plus` and description says "iPhone 15 Plus". "Plus" modifier dropped by extractor.

**Owner:** DOM extractor / adapter  
**Regression Test:** Assert `title` matches `h1` or canonical URL slug keywords.

---

## Enrichment Service Bugs (Enrichment Must Fix)

These are cases where enrichment logic itself is wrong or too permissive, regardless of upstream data quality.

### EN-1: Category Scoring Diluted by Title/Brand/Materials (9 records)

- **Records:** 0, 6, 12, 26, 28, 29, 34, 38, 43
- **Field:** `category_path`

**Evidence**

- Record 28: `category_path` resolves to "Best Sellers" (merchandising tag).
- Record 26: SKU appended into breadcrumb → taxonomy matcher scores SKU tokens.
- Record 38: Author/Title concatenated as category.
- Record 34: UI artifact "···" leaks into category tokens.
- Record 43: Brand repeated 4 times + product title concatenated into category.

**Root Cause**

`_match_category_path` (service.py:798 → `top_taxonomy_candidates` in `shopify_catalog.py`) merges **all** candidate values (`category`, `product_type`, `title`, `brand`, `materials`) into a single `source_tokens` set and computes `len(overlap) / len(source_tokens)`. Generic title tokens dominate. Threshold is `0.42`, too permissive.

**Owner:** `shopify_catalog.py` + `service.py`  
**Fix Direction:**

- Tiered token pools (FM-2 from `data-enrichment-bugfix-plan.md`): weight `category`+`product_type` at 1.0, `title` at 0.3, `brand`+`materials` at 0.1.
- Raise `category_match_threshold` to ≥ 0.65.
- Prefer JSON-LD `ItemListElement` breadcrumbs when available.

**Regression Test:** Assert `category_path` does not contain the exact `title` or `sku` of the product.

---

### EN-2: Material Context Blindness in `_normalize_materials` (6 records)

- **Records:** 8, 26, 32, 33, 41, 47
- **Field:** `materials_normalized`

**Evidence**

- Record 41: `materials_normalized` emits entire fabric glossary because `_normalize_materials` scans `description` without section restriction.
- Record 32: includes `iron` from care instructions.
- Record 47: leaks "Reviews" from concatenated DOM text.

**Root Cause**

`_normalize_materials` (service.py:717) scans `_candidate_values` from `materials`, `product_attributes`, `description`, and `title` with no section restriction. The `_term_present` regex matches any occurrence.

**Owner:** `service.py`  
**Fix Direction:**

- Restrict primary scan to `materials` and `product_attributes` **only**.
- Fall back to `description` only if primary sources are empty, and strip care-instruction sections ("care", "wash", "iron", "dry clean") before scanning.
- Add negative-penalty for tokens that appear in global glossary blocks.

**Regression Test:** Assert `materials_normalized` does not contain definitions for fabrics not explicitly mentioned in the product-detail block.

---

### EN-3: Size False-Positives (4 records)

- **Records:** 7, 20, 29, 45
- **Domains:** kith.com, adidas.com, colourpop.com, karenmillen.com
- **Field:** `size_normalized`

**Evidence**

- Record 7: "View Size Guide" accepted as size.
- Record 20: "100" (price/ID) accepted because `_plausible_size_value` regex accepts any pure number.
- Record 29: Eyeshadow `size: 24` with `size_system: numeric` — grams/pan count, not apparel size.

**Root Cause**

- `_plausible_size_value` (service.py:677) regex `\d+(?:\.\d+)?` has **no category gating**. Beauty/electronics numeric values pass as sizes.
- No UI-string deny-list in `_normalize_sizes`.

**Owner:** `service.py`  
**Fix Direction:**

- Gate `_normalize_sizes`: skip when `category_path` or `product_type` contains `beauty`, `electronics`, `home`, `tools`, `hardware`.
- Maintain deny-list of UI strings (`View Size Guide`, `Select Size`, `Size Chart`).

**Regression Test:** Assert `size_normalized` does not equal "View Size Guide" and does not run for `colourpop.com` eyeshadow.

---

### EN-4: SEO Keywords Bloated by Weak Stopword Filtering (most records)

- **Field:** `seo_keywords`

**Evidence**

- Pura Vida Bracelet: redundant unigrams + incoherent bigrams (`black seascape`, `seascape stretch`, `stretch bracelet`).
- Generic category tokens like "cup", "sleeves", "furniture", "sets" leak into keywords.

**Root Cause**

`_build_seo_keywords` (service.py:821) concatenates `title`, `brand`, `category`, `product_type`, `color_family`, `gender`, `category_path`, `size_values`, `materials` into one token stream. Only title bigrams are filtered against `seo_stopwords`; `raw_parts` unigrams are not. Max keyword cap hit by low-value filler tokens.

**Owner:** `service.py`  
**Fix Direction:**

- Apply `seo_stopwords` to **all** token sources before deduplication.
- Skip bigrams that duplicate already-selected unigrams.
- Cap at a diversity ratio: if a unigram exists, do not emit a bigram containing it.

**Regression Test:** Assert `seo_keywords` does not contain generic category tokens like "furniture" or "sets" when the product is apparel.

---

### EN-5: Deep Enrichment Fields Missing on ~65 % of Records

- **Records:** ~33
- **Fields:** `intent_attributes`, `audience`, `style_tags`, `ai_discovery_tags`, `suggested_bundles`

**Evidence**

Only ~17 of 50 records have deep fields populated. LLM backfill coverage is inconsistent.

**Root Cause**

- `llm_tasks.py` error paths return before writing `LLMCostLog`, so silent failures are invisible.
- No deterministic fallback exists for deep fields.
- LLM invoked for *all* missing fields without category gating, wasting tokens on irrelevant categories.

**Owner:** `llm_tasks.py` + `service.py`  
**Fix Direction:**

- Fix `llm_tasks.py` to log failed/partial calls with error metadata.
- Add deterministic fallbacks: `audience` = [`gender_normalized`] + [`category_path` leaf node]; `style_tags` = `color_family` + `materials_normalized`.
- Gate LLM deep enrichment: skip when `category_path` contains `electronics`, `tools`, `hardware`, `home`, `furniture`, `beauty`.

**Regression Test:** Assert every enriched product has at least 1 deep field populated when `llm_enabled=true`.

---

### EN-6: Gender Normalization Accepts Invalid Values (2 records)

- **Records:** 25, 28
- **Domains:** asos.com, frankbody.com
- **Field:** `gender_normalized`

**Evidence**

- Record 25: `gender` = "default".
- Record 28: `brand` = "Frank Body \| USA" (region suffix leaks into brand).

**Root Cause**

`_normalize_from_terms` for gender does not reject internal site variables. Brand normalizer does not strip pipe/dash region suffixes.

**Owner:** `service.py`  
**Fix Direction:**

- Map internal gender strings ("default", "unisex", "null") to standard taxonomy or omit if unknown.
- Strip common pipe/dash region suffixes from brand before storing.

**Regression Test:** Assert `gender_normalized` only contains standard values (Men, Women, Unisex, Kids, etc.). Assert `brand` does not contain " \| ".

---

## Per-Record Breakdown: Upstream vs Enrichment

| Record | Domain | Upstream Issues | Enrichment Issues |
|--------|--------|----------------|-------------------|
| 0 | sneakersnstuff.com | `description` (missing spaces), `additional_images` dedup | `category_path` (UI nav leak), `seo_keywords` (blob concatenation) |
| 1 | — | `additional_images` dedup | — |
| 2 | — | `description` (SEO boilerplate) | `seo_keywords` (shipping boilerplate leaks in) |
| 3 | stockx.com | `variants` (cross-product images), `additional_images` dedup | `color_family` / `size_normalized` (cross-product variants consumed) |
| 4 | nike.com | `product_details` (array leak), `variants` (title contradiction) | `size_normalized` (title contradiction accepted), `seo_keywords` (array leak) |
| 5 | amazon.com | `product_details` (array leak), `price` (missing) | `seo_keywords` (array leak) |
| 6 | apple.com | `category` (title/SKU appended) | `category_path` (title-diluted scoring) |
| 7 | kith.com | `variants[].size` ("View Size Guide"), `additional_images` dedup | `size_normalized` (UI string accepted) |
| 8 | farfetch.com | `price` (decimal scale), `description` (missing spaces) | `price_normalized` (locale misread), `materials_normalized` (concat leak scanned) |
| 9 | ssense.com | `price` (decimal scale) | `price_normalized` (locale misread) |
| 10 | costco.com | `description` ("Product Label" UI) | — |
| 11 | — | `description` (SEO boilerplate) | `seo_keywords` (boilerplate leaks in) |
| 12 | walmart.com | `category` ("Shop by Type" nav) | `category_path` (nav-diluted scoring) |
| 13 | — | `additional_images` dedup | — |
| 14 | homedepot.com | `product_type` ("BRIGHTCOVE VIDEO"), `availability` (Schema URL), `product_details` (UI text) | — |
| 15 | asos.com | `price` (missing entirely) | — |
| 16 | lululemon.com | `additional_images` dedup | — |
| 18 | wayfair.com | `price` (missing), `category` (SKU appended) | `category_path` (SKU-diluted scoring) |
| 19 | puma.com IN | `price` (parent/variant scale mismatch) | `price_normalized` (inconsistent scaling) |
| 20 | adidas.com | `size` ("100" price/ID mapped wrong) | `size_normalized` (no category gating) |
| 21 | puravidabracelets.com | — | `seo_keywords` (bloated) |
| 22 | — | `description` (shipping boilerplate) | `seo_keywords` (boilerplate leaks in) |
| 25 | asos.com | `gender` ("default" internal value) | `gender_normalized` (accepts invalid value) |
| 26 | wayfair.com | `category` (SKU appended), `description` (missing spaces), `materials` (glossary) | `category_path` (SKU-diluted scoring), `materials_normalized` (glossary scanned) |
| 28 | frankbody.com | `category` ("Best Sellers"), `brand` ("Frank Body \| USA") | `category_path` (merchandising tag scored), `seo_keywords` (brand suffix leaks) |
| 29 | colourpop.com | `variants` (cross-product palettes), `barcode` (SKU leak) | `color_family` (cross-product variants consumed) |
| 30 | fashionnova.com | `sku` (CMS artifact) | — |
| 32 | untuckit.com | `description` (fit guide glossary), `materials` (glossary) | `materials_normalized` (glossary scanned) |
| 33 | — | `materials` (concatenated DOM) | `materials_normalized` (concat leak scanned) |
| 34 | thomann.co.uk | `category` (UI artifact "···") | `category_path` (UI artifact scored) |
| 37 | — | `description` (marketing fluff) | `seo_keywords` (marketing fluff leaks in) |
| 38 | abebooks.com | `title` ("plp"), `category` (author/title) | `category_path` (author/title scored) |
| 40 | backmarket.com | `title` truncation (missing "Plus") | — |
| 41 | toddsnyder.com | `materials` (fabric glossary) | `materials_normalized` (glossary scanned) |
| 43 | puma.com AR | `price` (decimal scale), `category` (brand repeated) | `price_normalized` (locale misread), `category_path` (brand-diluted scoring) |
| 45 | karenmillen.com | `variants` (missing `option_values`), `availability` (Schema URL) | `size_normalized` / `color_family` (no structured data to consume) |
| 46 | kitchenaid.com | `product_id` ("specifications") | — |
| 47 | phase-eight.com | `description` (reviews leak), `materials` (concat leak) | `materials_normalized` (reviews scanned) |
| 48 | grailed.com | `price` (decimal scale), `category` (brand/title repeated) | `price_normalized` (locale misread), `category_path` (brand-diluted scoring) |

---

## Fix Priority

### P0 — Fix Upstream First

These must be fixed in extraction before enrichment can produce clean output.

1. **Price locale parsing** (`normalizers.py` / `field_value_core.py`): Add per-domain locale hints. Parent/variant must use same scaling rule.
2. **DOM text concatenation** (`field_value_dom.py`): Replace block-level tags with spaces/newlines before stripping.
3. **Variant mapper contamination** (`detail_extractor.py`): Scope variant extraction to product form/add-to-cart container only.
4. **Glossary/guide exclusion** (`field_value_dom.py`): Exclude hidden modals/accordions from text extraction.
5. **Core identity selectors** (adapter): Target semantic tags (`h1`, JSON-LD) instead of generic `div` IDs.
6. **UI element stripping** (`field_value_dom.py`): Exclude `button`, `.size-guide`, `.tooltip` from description/variant containers.
7. **Array stringification** (`field_value_core.py`): Detect lists and join with delimiters before storing.
8. **Image deduplication** (image collector): Deduplicate `additional_images` by base URL before storing.
9. **Missing `option_values`** (`detail_extractor.py`): Extract from URL params or DOM buttons when structured data absent.
10. **Currency mismatch** (adapter): Maintain consistent locale context across parent and variant requests.
11. **Availability URL normalization** (`field_value_core.py`): Map Schema.org URLs to internal snake_case enum.

### P0 — Fix Enrichment

These are enrichment-specific bugs that must be fixed regardless of upstream data.

12. **Category tiered scoring** (`shopify_catalog.py` + `service.py`): Implement primary/secondary/tertiary token pools; raise threshold to ≥ 0.65.
13. **Material context restriction** (`service.py`): Scan `materials`+`product_attributes` only; strip care-instructions from `description` fallback.
14. **Size category gating** (`service.py`): Skip size normalization for `beauty`, `electronics`, `home`, `tools`, `hardware`.
15. **Size UI-string deny-list** (`service.py`): Reject "View Size Guide", "Select Size", "Size Chart".

### P1 — Fix Next

16. **SEO keyword stopword filter** (`service.py`): Apply stopwords to **all** token sources, not just title bigrams.
17. **SEO bigram deduplication** (`service.py`): Skip bigrams that duplicate unigrams.
18. **LLM error logging** (`llm_tasks.py`): Record failed/partial calls with metadata.
19. **Deep field deterministic fallbacks** (`service.py`): Populate `audience`, `style_tags` from `category_path`+`gender`+`color_family`.
20. **LLM category gating** (`service.py`): Skip LLM deep enrichment for irrelevant categories.
21. **Gender/brand cleanup** (`service.py`): Map "default" → null; strip pipe/dash region suffixes from brand.

### P2 — Polish

22. **Title truncation upstream** (`field_value_dom.py` / adapter): Ensure title selector targets full product name.
23. **Barcode SKU leak** (`field_value_core.py`): Reject alphanumeric strings for `barcode`; map to `sku` instead.

---

## Verification

Run after upstream fixes:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe run_extraction_smoke.py
```

Run after enrichment fixes:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/services/test_data_enrichment.py -q
```

---

## Do Not Fix Downstream

- Do **not** multiply/divide prices in the export layer. Fix `normalize_decimal_price` upstream.
- Do **not** write regex to strip "Best Sellers" or "SKU:" from `category_path` downstream. Fix the taxonomy matcher / extraction upstream.
- Do **not** infer missing `option_values` from SKU suffixes in the publish layer. The variant mapper must capture them during extraction.
- Do **not** add HTML tag re-insertion logic in enrichment. Fix the text cleaner in `field_value_dom.py` upstream.
- Do **not** compensate for array stringification in enrichment. Fix `coerce_field_value` in `field_value_core.py` upstream.
