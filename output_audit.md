# Executive Summary

- **Total records audited:** 50
- **Domains audited:** 36
- **Critical issue count:** 4
- **High issue count:** 4
- **Medium issue count:** 2
- **Low issue count:** 2

## Top 5 Recurring Patterns

1. Decimal scale errors on prices (e.g., `$1012` extracted as `10.12`).
2. DOM text concatenation missing spaces/delimiters.
3. Cross-product contamination (recommendations/related items extracted as variants or images).
4. Array stringification leaks (`['...', '...']` saved as raw strings).
5. SEO/Shipping boilerplate captured as product descriptions.

---

# Field Health Matrix

| Field | Health | Common failures | Affected record indexes | Fix priority |
|-------|--------|----------------|------------------------|--------------|
| price | BAD | Decimal scale errors dividing by 100 incorrectly. | 9, 19, 43, 48 | P0 |
| variants | MIXED | Related products mapped as variants; UI elements ("View Size Guide") mapped as sizes. | 7, 29 | P1 |
| materials / specifications | BAD | Scraping entire site glossaries; concatenating DOM text without spaces; including UI tooltips. | 8, 26, 32, 33, 41, 47 | P1 |
| product_id / product_type | MIXED | Extracting DOM section IDs (e.g., "specifications", "BRIGHTCOVE VIDEO") instead of product data. | 14, 46 | P1 |
| title | MIXED | Mostly good, but occasionally extracts internal codes (e.g., "plp"). | 38 | P2 |
| description | BAD | Capturing SEO boilerplate, shipping terms, or site-wide fit guides instead of item descriptions. | 2, 3, 6, 11, 12, 20, 21, 22, 25, 30, 32, 37, 40, 48 | P2 |
| additional_images | BAD | Massive duplication via query params; inclusion of recommended products. | 0, 1, 3, 4, 7, 11, 12, 13, 16, 18, 25, 26, 28, 41 | P3 |

---

# Critical Findings

## DQ-1: Price Decimal Scale Errors

- **Severity:** CRITICAL
- **Confidence:** HIGH
- **Records:** 9, 19, 43, 48
- **Domains:** ssense.com, puma.com, grailed.com
- **Fields:** `price`, `variants[].price`
- **Evidence type:** internal consistency

### Evidence

- **Record 9 (ssense.com):** Leather jacket price is `38.90` (likely `$3890`).
- **Record 19 (puma.com IN):** Parent price `9999`, but variant prices are `99.99`.
- **Record 43 (puma.com AR):** Parent price `113999`, but variant prices are `1139.99`.
- **Record 48 (grailed.com):** Price is `10.12`, but description explicitly says "starting at $1012".

### Why this is wrong

The normalizer or DOM extractor is incorrectly applying a `/100` division to integer cents, or misinterpreting comma/period decimal separators based on locale, destroying the actual price value.

- **Likely upstream owner:** normalizer
- **Likely fix direction:** Standardize locale-aware price parsing and ensure parent/variant price normalization logic uses the exact same scaling rules.
- **Regression test idea:** Assert that `1012` without a decimal in the DOM does not become `10.12` unless the currency explicitly uses a comma for thousands and period for decimals in that specific locale.

---

## DQ-2: Cross-Product Contamination in Variants

- **Severity:** CRITICAL
- **Confidence:** HIGH
- **Records:** 29
- **Domains:** colourpop.com
- **Fields:** `variants`, `variant_axes`
- **Evidence type:** internal consistency

### Evidence

Record 29 parent is "Going Coconuts" palette. Variants array contains entirely different products: "Blowin' Smoke", "It's My Pleasure", "Blue Moon", etc., all sharing the exact same `image_url`.

### Why this is wrong

The extractor is confusing a "Related Products" or "More Palettes" carousel with the variant selector for the current product.

- **Likely upstream owner:** variant mapper
- **Likely fix direction:** Scope variant extraction strictly to the product form/add-to-cart container, ignoring global carousels or cross-sell grids.
- **Regression test idea:** Assert that `variants[].shade` for ColourPop only contains shades available within the specific palette being crawled, not other standalone palettes.

---

## DQ-3: Massive Glossary/Guide Contamination

- **Severity:** CRITICAL
- **Confidence:** HIGH
- **Records:** 32, 41
- **Domains:** untuckit.com, toddsnyder.com
- **Fields:** `description`, `materials`
- **Evidence type:** internal consistency

### Evidence

- **Record 41 (toddsnyder.com):** `materials` contains the entire fabric glossary for the website ("The word 'seersucker' originates... This cotton-cashmere yarn... Our soft and sturdy Premium Jersey... Oxford cloth...").
- **Record 32 (untuckit.com):** `description` contains the entire fit guide for all fits ("Regular Fit - Our classic cut... Slim Fit - Two inches less... Relaxed Fit...").

### Why this is wrong

The extractor is capturing hidden modals, accordions, or global size/fabric guides that exist in the DOM but do not describe the specific product.

- **Likely upstream owner:** DOM extractor
- **Likely fix direction:** Exclude hidden global modals/tabs from text extraction, or restrict `description`/`materials` targeting to the active product detail block.
- **Regression test idea:** Assert that `materials` length is under a reasonable character limit and does not contain definitions for fabrics not used in the product.

---

## DQ-4: Wrong Core Identity Extraction

- **Severity:** CRITICAL
- **Confidence:** HIGH
- **Records:** 14, 20, 38, 46
- **Domains:** homedepot.com, adidas.com, abebooks.com, kitchenaid.com
- **Fields:** `title`, `product_id`, `product_type`, `size`
- **Evidence type:** internal consistency

### Evidence

- **Record 38 (abebooks.com):** `title` is "plp" (likely an internal code for Product Listing Page).
- **Record 46 (kitchenaid.com):** `product_id` is "specifications".
- **Record 14 (homedepot.com):** `product_type` is "BRIGHTCOVE VIDEO".
- **Record 20 (adidas.com):** `size` is "100" (likely a price or ID mapped to the wrong field).

### Why this is wrong

CSS selectors or structured data fallbacks are targeting structural DOM IDs/classes or internal tracking variables instead of the actual product data.

- **Likely upstream owner:** adapter / DOM extractor
- **Likely fix direction:** Refine selectors to target semantic tags (e.g., `h1` for title) or structured JSON-LD rather than generic `div` IDs.
- **Regression test idea:** Assert that `product_id` does not equal generic structural words like "specifications" or "description".

---

# High and Medium Findings

## DQ-5: Array Stringification Leaks

- **Severity:** HIGH
- **Confidence:** HIGH
- **Records:** 4, 5
- **Domains:** nike.com, amazon.com
- **Fields:** `product_details`, `features`
- **Evidence type:** internal consistency

### Evidence

- **Record 4:** `['Leather upper with perforated toe box...', 'Originally designed...']`
- **Record 5:** `['Digital Max Resolution:7680 x 4320...', 'Real boost clock...']`

### Why this is wrong

The extractor is capturing a JSON array or Python list and casting it directly to a string without joining the elements properly.

- **Likely upstream owner:** text cleaner / normalizer
- **Likely fix direction:** Detect array types during normalization and join them with standard delimiters (e.g., newlines or bullets) before saving as a string.
- **Regression test idea:** Assert that text fields do not start with `['` and end with `']`.

---

## DQ-6: DOM Text Concatenation Missing Delimiters

- **Severity:** HIGH
- **Confidence:** HIGH
- **Records:** 0, 5, 8, 26, 27, 33, 47
- **Domains:** sneakersnstuff.com, amazon.com, farfetch.com, wayfair.com, zara.com, decathlon.co.uk, phase-eight.com
- **Fields:** `description`, `specifications`, `materials`, `features`
- **Evidence type:** internal consistency

### Evidence

- **Record 0:** `"Crewneck100% CottonHeavyweight 14ozScreen printed logoPre-shrunk"`
- **Record 8:** `"black leather appliqué logo textured finish front zip fastening..."`
- **Record 47:** `"Polyester 100% Care: Delicate Machine Wash Lining: Polyester 100% Reviews ( 23 )"`

### Why this is wrong

When extracting text from multiple block-level elements (like `<li>` or `<div>`), the extractor is stripping the HTML tags without replacing them with spaces or newlines, causing words to mash together.

- **Likely upstream owner:** text cleaner
- **Likely fix direction:** Ensure the HTML-to-text utility replaces block-level tags and `<br>` with spaces or newlines before stripping tags.
- **Regression test idea:** Assert that camelCase-like collisions (e.g., `"CottonHeavyweight"`) do not occur in description fields.

---

## DQ-7: UI Elements Extracted as Data

- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Records:** 7, 10, 14, 31
- **Domains:** kith.com, costco.com, homedepot.com, puravidabracelets.com
- **Fields:** `variants[].size`, `description`, `product_details`, `care`
- **Evidence type:** internal consistency

### Evidence

- **Record 7:** Variant size is "View Size Guide".
- **Record 10:** Description is "Product Label ​".
- **Record 14:** Product details includes "Ask Magic Apron How soon can I get this delivered to my zip code?".
- **Record 31:** Care includes "Learn more about our materials and jewelry care here".

### Why this is wrong

The extractor is blindly grabbing all text within a parent container, including buttons, tabs, and interactive prompts.

- **Likely upstream owner:** DOM extractor
- **Likely fix direction:** Exclude common UI elements (`button`, `a.size-guide`, `.tooltip`) when extracting text from description/variant containers.
- **Regression test idea:** Assert that variant sizes do not equal "View Size Guide".

---

## DQ-8: Cross-Product Contamination in Images

- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Records:** 3, 28
- **Domains:** stockx.com, frankbody.com
- **Fields:** `additional_images`
- **Evidence type:** internal consistency

### Evidence

- **Record 3 (StockX):** A "Black White Panda" dunk includes images for "White-Midnight-Navy" and "Black-White-Gum".
- **Record 28 (Frank Body):** "Original Coffee Scrub" includes an image named "Glycolic-Body-Scrub_Before".

### Why this is wrong

The image collector is scraping carousels for "You May Also Like" or "Customers Also Bought".

- **Likely upstream owner:** image collector
- **Likely fix direction:** Restrict image extraction to the main product gallery container.
- **Regression test idea:** Assert that image URLs do not contain slugs for entirely different products.

---

# Low Priority Cleanup

- **SEO/Shipping Boilerplate:** Records 2, 3, 6, 11, 12, 20, 21, 22, 25, 30, 37, 40, 48 contain marketing fluff (e.g., "Buy now with free shipping", "Shop SEPHORA COLLECTION's", "Buyer protection guaranteed") in the description.
- **Image Duplication via Query Params:** Records 0, 1, 4, 7, 11, 12, 13, 16, 18, 25, 26, 41 have massive `additional_images` arrays where the exact same image is repeated 5-10 times with different `width`, `height`, or `size` query parameters. The normalizer should deduplicate base URLs.

---

# Per-Domain Notes

## puma.com (Records 19, 43)

- **Good signals:** Variants, colors, and images are well-structured.
- **Bad signals:** Severe decimal scale mismatch between parent and variant prices.
- **Most likely broken extractor stage:** Normalizer (Price parsing).
- **First fix to try:** Align parent price parsing logic with variant price parsing logic.

## colourpop.com (Record 29)

- **Good signals:** High-quality image extraction, good description.
- **Bad signals:** Entirely different products mapped as variants.
- **Most likely broken extractor stage:** Variant mapper.
- **First fix to try:** Scope variant extraction to the actual shade selector, ignoring the "Related Palettes" grid.

## toddsnyder.com (Record 41) / untuckit.com (Record 32)

- **Good signals:** Clean variant axes and pricing.
- **Bad signals:** Scraping massive global glossaries/fit guides into product text fields.
- **Most likely broken extractor stage:** DOM extractor.
- **First fix to try:** Exclude hidden modals/accordions from text extraction.

## abebooks.com (Record 38)

- **Good signals:** Pricing and variants are captured.
- **Bad signals:** Title is "plp".
- **Most likely broken extractor stage:** Adapter.
- **First fix to try:** Fallback to `h1` or `og:title` instead of whatever internal variable is currently being targeted.

---

# Fix Backlog for Codex

| Priority | Bug pattern | Affected fields | Affected domains/records | Suspected owner | Suggested test |
|----------|-------------|-----------------|--------------------------|-----------------|----------------|
| P0 | Decimal scale errors | `price`, `variants[].price` | ssense.com (9), puma.com (19, 43), grailed.com (48) | Normalizer | Assert price matches expected magnitude (no $10.12 for $1012 items). |
| P1 | Cross-product variants | `variants` | colourpop.com (29) | Variant mapper | Assert variant names do not match other known parent products. |
| P1 | Glossary/Guide dumps | `materials`, `description` | toddsnyder.com (41), untuckit.com (32) | DOM extractor | Assert text fields do not contain site-wide glossary definitions. |
| P1 | Wrong core identity | `title`, `product_id` | abebooks.com (38), kitchenaid.com (46) | Adapter | Assert `title != "plp"` and `product_id != "specifications"`. |
| P2 | Array stringification | `features`, `product_details` | nike.com (4), amazon.com (5) | Text cleaner | Assert text does not contain `['`. |
| P2 | Missing text delimiters | `description`, `specifications` | sneakersnstuff.com (0), farfetch.com (8), wayfair.com (26) | Text cleaner | Assert block-level HTML tags are replaced with spaces/newlines. |
| P3 | Image duplication | `additional_images` | nike.com (4), lululemon.com (18), etc. | Image collector | Deduplicate image URLs by ignoring sizing query parameters. |

---

# Do Not Fix Downstream

- **Price decimal errors:** Do not attempt to multiply prices by 100 in the export layer. The normalizer must correctly parse the raw string based on the locale.
- **Missing spaces in text:** Do not attempt to write regex to split camelCase words (e.g., `"CottonHeavyweight"`) downstream. The HTML tags must be replaced with spaces before tag stripping upstream.
- **Array stringification:** Do not write regex to strip `['` and `']` downstream. The upstream pipeline must handle list types natively.

---

# Needs Human or Browser Verification

- **AbeBooks (Record 38):** Verify if the page actually renders "plp" in the `h1` due to a bot-defense mechanism or a broken page template, or if the crawler is just targeting the wrong element.
- **SSENSE (Record 9):** Verify if the $38.90 price is a legitimate extreme clearance sale, a pricing error on the live site, or strictly a crawler decimal parsing bug.

---

# Missed Audit Points

- **Total records audited:** 50
- **Domains audited:** 36
- **Critical issue count:** 3 (New Delta Findings)
- **High issue count:** 3 (New Delta Findings)
- **Medium issue count:** 4 (New Delta Findings)
- **Low issue count:** 2 (New Delta Findings)

## Top 5 Recurring Patterns in This Delta

1. Category path semantic corruption (capturing titles, SKUs, UI artifacts, or merchandising tags instead of true breadcrumbs).
2. Currency mismatches between parent and variant records.
3. Variants completely missing `option_values` objects.
4. Internal contradictions within variant objects (e.g., size value contradicts variant title).
5. Brand and gender normalization failures (e.g., region suffixes in brand, "default" as gender).

> **Note:** This is a Delta Report focusing on fields and issues not covered in the initial audit, specifically targeting category, currency, brand, gender, barcode, and deeper variant inconsistencies.

---

## Field Health Matrix

| Field | Health | Common failures | Affected record indexes | Fix priority |
|-------|--------|----------------|------------------------|--------------|
| category | BAD | Appending Title/SKU; capturing "Best Sellers"; capturing UI nav elements ("Shop by Type", "···"). | 0, 6, 12, 26, 28, 29, 34, 38, 43 | P0 |
| currency | MIXED | Parent currency contradicts variant currency. | 26 | P0 |
| `variants[].option_values` | BAD | Completely missing on variants that clearly have differing options (e.g., colors/sizes). | 45 | P0 |
| brand | MIXED | Including region/site suffixes (e.g., "\| USA"); missing spaces. | 28, 45 | P2 |
| gender | MIXED | Extracting raw system values like "default" instead of standardizing. | 25 | P2 |
| barcode | MIXED | Extracting internal alphanumeric SKUs into the barcode field. | 29 | P2 |
| title | MIXED | Truncating important model identifiers (e.g., missing "Plus"). | 40 | P2 |

---

# Critical Findings

## DQ-8: Category Path Semantic Corruption

- **Severity:** CRITICAL
- **Confidence:** HIGH
- **Records:** 0, 6, 12, 26, 28, 29, 34, 38, 43
- **Domains:** sneakersnstuff.com, apple.com, walmart.com, wayfair.com, frankbody.com, colourpop.com, thomann.co.uk, abebooks.com, grailed.com
- **Fields:** `category`
- **Evidence type:** internal consistency

### Evidence

- **Record 28 (frankbody.com):** `category` is "Best Sellers" (merchandising tag, not a category).
- **Record 26 (wayfair.com):** `category` ends with "> SKU: XTYA1522" (SKU appended).
- **Record 38 (abebooks.com):** `category` is "Robert C. Martin > Clean Code..." (Author > Title).
- **Record 34 (thomann.co.uk):** `category` starts with "··· > All Categories > ..." (UI artifacts).
- **Record 12 (walmart.com):** `category` includes "> Shop Headphones by Type >" (Nav label).
- **Record 43 (grailed.com):** `category` repeats brand 4 times and ends with the product title.

### Why this is wrong

The extractor is failing to isolate the true product breadcrumb. It is grabbing global navigation menus, merchandising badges, or concatenating the brand/title/SKU into the category string, which destroys category taxonomy.

- **Likely upstream owner:** DOM extractor / structured source mapper
- **Likely fix direction:** Prioritize `ItemListElement` from JSON-LD breadcrumbs over scraping DOM elements. If using DOM, exclude the current page title/SKU node from the breadcrumb list.
- **Regression test idea:** Assert that `category` does not contain the exact `title` or `sku` of the product.

---

## DQ-9: Parent/Variant Currency Mismatch

- **Severity:** CRITICAL
- **Confidence:** HIGH
- **Records:** 26 (Note: Index 26 in the JSON is Zadig & Voltaire, SKU JMTS01771443X02)
- **Domains:** zadig-et-voltaire.com
- **Fields:** `currency`, `variants[].currency`
- **Evidence type:** internal consistency

### Evidence

Parent currency is "GBP", but all variants have currency as "EUR".

### Why this is wrong

A single product record cannot have variants priced in Euros while the parent is priced in British Pounds. This indicates the crawler crossed regional boundaries during extraction or merged data from two different localized API responses.

- **Likely upstream owner:** adapter / variant mapper
- **Likely fix direction:** Ensure the variant extraction context inherits or strictly matches the locale/currency context of the parent page request.
- **Regression test idea:** Assert that `variants[].currency` exactly matches parent `currency`.

---

## DQ-10: Variants Missing Option Values

- **Severity:** CRITICAL
- **Confidence:** HIGH
- **Records:** 45
- **Domains:** karenmillen.com
- **Fields:** `variants[].option_values`
- **Evidence type:** internal consistency

### Evidence

Record 45 has 12 variants with different SKUs (e.g., "BKK28382-105-14", "BKK28382-133-14"), but the `option_values` object is completely missing from every variant.

### Why this is wrong

Without `option_values`, downstream systems cannot know what differentiates these variants (likely size and color, based on the SKUs). The variants array is rendered useless for purchasing.

- **Likely upstream owner:** variant mapper
- **Likely fix direction:** Ensure the variant mapper always populates `option_values` when multiple variants are detected, extracting from the DOM selectors or the site's variant JSON object.
- **Regression test idea:** Assert that if `variants` array length > 1, every variant must contain an `option_values` object with at least one key.

---

# High and Medium Findings

## DQ-11: Internal Contradiction in Variant Data

- **Severity:** HIGH
- **Confidence:** HIGH
- **Records:** 4
- **Domains:** nike.com
- **Fields:** `variants[].title`, `variants[].size`, `variants[].option_values`
- **Evidence type:** internal consistency

### Evidence

In Record 4, the third variant has `size: "6"` and `option_values.size: "6"`, but the title is "Nike Air Force 1 '07 Men's Shoes - White/White - Size 6". However, the first variant (and the `selected_variant`) has `size: "5"`, but its title is also "Nike Air Force 1 '07 Men's Shoes - White/White - Size 6".

### Why this is wrong

The variant title was likely hardcoded or scraped from the parent DOM state at the time of page load (which happened to be Size 6), and then blindly copied to other variants, contradicting their actual size data.

- **Likely upstream owner:** variant mapper
- **Likely fix direction:** Construct variant titles dynamically using the parent title + the specific variant's `option_values`, rather than scraping the DOM title for every variant.
- **Regression test idea:** Assert that variant titles containing size/color strings match the actual `option_values` of that variant.

---

## DQ-12: Additional Decimal Scale Error (Farfetch)

- **Severity:** HIGH
- **Confidence:** HIGH
- **Records:** 8
- **Domains:** farfetch.com
- **Fields:** `price`, `variants[].price`
- **Evidence type:** internal consistency / schema

### Evidence

Price is "104.10" for a "Philipp Plein leather disco biker jacket".

### Why this is wrong

Philipp Plein leather jackets retail for thousands of dollars. The actual price is almost certainly $10,410.00. The normalizer incorrectly parsed a thousands separator as a decimal.

- **Likely upstream owner:** normalizer
- **Likely fix direction:** Improve locale-aware number parsing. If a site uses `.` for thousands and `,` for decimals (common in Europe), the normalizer must respect the locale.
- **Regression test idea:** Assert that prices over 1000 are not incorrectly divided by 100 due to European number formatting.

---

## DQ-13: Title Truncation / Mismatch

- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Records:** 40
- **Domains:** backmarket.com
- **Fields:** `title`, `url`, `description`
- **Evidence type:** internal consistency

### Evidence

`title` is "iPhone 15 • Unlocked". However, the `url` is `/iphone-15-plus`, the `description` explicitly says "iPhone 15 Plus", and the features mention a "6.7-inch" screen.

### Why this is wrong

The title extractor truncated or missed the "Plus" designation, which fundamentally changes the product being represented.

- **Likely upstream owner:** DOM extractor
- **Likely fix direction:** Ensure the title selector targets the full product name (often found in `h1` or JSON-LD) rather than a truncated breadcrumb or mobile-optimized short title.
- **Regression test idea:** Assert that `title` contains key model modifiers (like "Plus", "Pro", "Max") if they exist in the canonical URL slug.

---

## DQ-14: Brand and Gender Normalization Failures

- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Records:** 25, 28
- **Domains:** asos.com, frankbody.com
- **Fields:** `gender`, `brand`
- **Evidence type:** internal consistency

### Evidence

- **Record 25 (asos.com):** `gender` is "default".
- **Record 28 (frankbody.com):** `brand` is "Frank Body \| USA".

### Why this is wrong

"default" is an internal site variable, not a valid gender. " \| USA" is a site region suffix, not part of the brand name.

- **Likely upstream owner:** normalizer
- **Likely fix direction:** Add a cleanup step for brand to strip common pipe/dash region suffixes. Map internal gender strings ("default", "unisex", "null") to standard taxonomy (Men, Women, Unisex, Kids) or omit if unknown.
- **Regression test idea:** Assert `gender` only contains standard values (Men, Women, Unisex, Kids, etc.). Assert `brand` does not contain " \| ".

---

## DQ-15: SKU Mapped to Barcode

- **Severity:** MEDIUM
- **Confidence:** HIGH
- **Records:** 29
- **Domains:** colourpop.com
- **Fields:** `barcode`
- **Evidence type:** schema/format

### Evidence

`barcode` is "FG000877".

### Why this is wrong

"FG000877" is an internal alphanumeric SKU or part number. Barcodes (UPC/EAN/GTIN) must be strictly numeric (usually 12-14 digits).

- **Likely upstream owner:** structured source mapper
- **Likely fix direction:** Add validation to the `barcode` field to reject alphanumeric strings and map them to `sku` or `part_number` instead.
- **Regression test idea:** Assert that `barcode` contains only digits.

---

# Low Priority Cleanup

- **Internal System Artifacts in SKU:** Record 30 (Fashion Nova) has `sku: "COPY-1720644688978"`. This is a backend CMS artifact (likely a duplicated product draft), not the actual customer-facing SKU.
- **Missing Spaces in Brand:** Record 45 (Karen Millen) extracts `brand: "KarenMillen"`. The normalizer should ideally preserve or inject proper spacing based on standard brand dictionaries.

---

# Per-Domain Notes

## wayfair.com (Record 26)

- **Good signals:** Rich specifications and details extracted well.
- **Bad signals:** SKU appended directly into the category breadcrumb.
- **Most likely broken extractor stage:** DOM extractor.
- **First fix to try:** Strip text matching `SKU: *` from the final category node.

## zadig-et-voltaire.com (Record 26 / JSON index 26)

- **Good signals:** Variants are well-populated with images and barcodes.
- **Bad signals:** Parent currency (GBP) contradicts variant currency (EUR).
- **Most likely broken extractor stage:** Adapter / Variant mapper.
- **First fix to try:** Force variant extraction to use the same currency context as the parent page.

## karenmillen.com (Record 45)

- **Good signals:** High-quality description and images.
- **Bad signals:** Variants array is completely missing `option_values`.
- **Most likely broken extractor stage:** Variant mapper.
- **First fix to try:** Extract option values from the `?colour=ivory` URL params or the size buttons in the DOM.

---

# Fix Backlog for Codex

| Priority | Bug pattern | Affected fields | Affected domains/records | Suspected owner | Suggested test |
|----------|-------------|-----------------|--------------------------|-----------------|----------------|
| P0 | Category semantic corruption | `category` | wayfair, frankbody, abebooks, grailed, etc. | DOM extractor | Assert `category` does not contain `SKU:`, "Best Sellers", or the exact product title. |
| P0 | Currency mismatch | `currency`, `variants[].currency` | zadig-et-voltaire.com (26) | Adapter | Assert parent `currency` equals variant `currency`. |
| P0 | Missing option values | `variants[].option_values` | karenmillen.com (45) | Variant mapper | Assert `option_values` exists if variants length > 1. |
| P1 | Variant title contradiction | `variants[].title` | nike.com (4) | Variant mapper | Assert variant titles containing sizes match the variant's actual size. |
| P1 | Locale decimal parsing | `price` | farfetch.com (8) | Normalizer | Assert prices > 1000 are not incorrectly parsed as decimals. |
| P2 | Title truncation | `title` | backmarket.com (40) | DOM extractor | Assert `title` matches `h1` or canonical URL slug keywords. |
| P2 | Alphanumeric barcodes | `barcode` | colourpop.com (29) | Normalizer | Assert `barcode` is strictly numeric. |

---

# Do Not Fix Downstream

- **Category Path Cleanup:** Do not attempt to write regex downstream to strip `SKU:` or "Best Sellers" from categories. The upstream extractor must pull the correct breadcrumb element (preferably from JSON-LD).
- **Variant Option Values:** Do not attempt to infer missing variant sizes/colors from the variant SKUs downstream. The variant mapper must capture this at the time of extraction.
- **Currency Mismatches:** Do not attempt to guess whether the parent or the variant currency is the "correct" one downstream. The adapter must maintain a consistent locale state.

---

# Needs Human or Browser Verification

- **Farfetch (Record 8):** Verify the actual price of the Philipp Plein jacket on the live site to confirm if it is $10,410 (decimal parsing bug) or if it is legitimately on a 99% clearance sale for $104.10.
- **Fashion Nova (Record 30):** Verify if the live site actually exposes `COPY-1720644688978` as the SKU in the DOM/JSON-LD, or if the crawler is digging into hidden/invalid metadata fields.