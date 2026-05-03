# Extraction Quality Audit — 2026-05-03

Scope: `backend/app/services/field_value_core.py`, `field_value_dom.py`, `detail_extractor.py`, `extract/detail_dom_extractor.py`, `extract/shared_variant_logic.py`, `extract/variant_record_normalization.py`, `extract/detail_record_finalizer.py`, `config/extraction_rules.py`, `js_state_mapper.py`, `structured_sources.py`


## 1. Parsing Artifacts & Code Leakage

### 1.1 Vans Old Skool (VN000E9TBPG): Nested Bracket Pollution in Description / Specifications

**Symptom:** `"[ [ [ [[[Style ]][[ [[VN000E9TBPG]] ]][[]]] [The Old Skool was our first footwear design..."`

**Root cause:** The product description is stored in a React/JS prop or raw JSON array that gets flattened by `get_text(" ", strip=True)` in `field_value_dom.py` or by `_coerce_literal_text_list` in `field_value_core.py:504-527`. Neither path recognizes bracket-wrapped template syntax (`[[[Style]]][[[VN000E9TBPG]]]`) as noise. The DOM text extractor concatenates every leaf node's text, including SKU/style wrappers, without stripping structural brackets.

**Fix location:** `field_value_core.py` — add a bracket-noise stripper in `clean_text` or `_coerce_literal_text_list` that removes runs of `[`/`]` and their contents when they exceed a nesting depth. `field_value_dom.py` — add a pre-filter in `extract_page_long_text` or `extract_heading_sections` that drops nodes whose text is >80% bracket/symbol characters.

### 1.2 Converse (A16914F): Template String in `image_url`

**Symptom:** `"https://www.converse.com/shop/p/chuck-taylor-all-star-retro-embroidery-unisex-high-top-shoe/URL_TO_THE_PRODUCT_IMAGE"`

**Root cause:** Image URL extraction (likely in `field_value_dom.py:554+` or an adapter) reads the `src` or `content` attribute verbatim without resolving template placeholders. The site injects a backend template literal `URL_TO_THE_PRODUCT_IMAGE` that the scraper treats as a valid URL.

**Fix location:** `field_value_dom.py` — `_is_garbage_image_candidate` already checks for UI asset hints, but it does not check for unresolved template literals. Add a regex guard rejecting URLs containing `URL_TO_`, `{{`, `{$`, or other template placeholder patterns. Also add to `NON_PRODUCT_IMAGE_HINTS` in `config/extraction_rules.py`.

### 1.3 Sony Headphones (00498): Python Dict in `specifications`

**Symptom:** `"{'useOnlyPreMadeBundles': False}"`

**Root cause:** `coerce_field_value` in `field_value_core.py:999+` receives a dict object from `harvest_js_state_objects` (via `js_state_mapper.py` or `structured_sources.py`). The dict is not caught by any early branch for the `specifications` field, so it falls through to `coerce_text` which calls `str(value)`, producing `"{'useOnlyPreMadeBundles': False}"`. The `_coerce_literal_text_list` guard only catches `list`/`str`, not `dict`.

**Fix location:** `field_value_core.py` — in `coerce_field_value`, add a guard: if `field_name in {"description", "specifications", "product_details", "features"}` and `isinstance(value, (dict, list))`, attempt structured flattening or reject the value entirely instead of calling `str()`.

---

## 2. DOM Visibility & Concatenation Errors

### 2.1 Patagonia Jacket (84213-AQT): Hidden Colorways Concatenated into Description

**Symptom:** Description contains text for every hidden colorway variant: `"...Made in a Fair Trade Certified™ factory. - Aquatic Blue We built the Nano Puff... - Black We built the Nano Puff... - Blue Sage We built the Nano Puff..."`

**Root cause:** `get_text()` in BeautifulSoup (used by `field_value_dom.py` text extraction helpers) recursively extracts text from all child nodes, including those with `aria-hidden="true"` or inline `style="display:none"`. While `browser_detail.py:558-564` detects hidden nodes for browser expansion, the text extraction pipeline in `field_value_dom.py` does not apply the same visibility filter before flattening text. The parent description container includes hidden color-swatch detail panels as children.

**Fix location:** `field_value_dom.py` — all text-extraction helpers (`extract_page_long_text`, `extract_heading_sections`, `get_text` wrappers) must skip child nodes where `node.get("aria-hidden") == "true"` or `"hidden" in node.get("class", [])` or `style="display:none"` is present. This should reuse the visibility logic already in `browser_detail.py`.

### 2.2 Barrow Kids (83I-UKD027): Size Variants Concatenated into Description

**Symptom:** `"Nylon tank top - Barrow - Boys - Green - 10Y... Green - 12Y... Green - 14Y... Green - 8Y..."`

**Root cause:** Same as 2.1 — hidden or inactive size-variant DOM nodes are included in the parent container's `get_text()` output. The size grid is rendered as child `<option>` or `<div>` elements inside the same parent as the description, and text extraction does not scope to visible-only children.

**Fix location:** Same as 2.1. Also consider scoping description extraction to exclude known variant containers (`fieldset`, `[role="radiogroup"]`, `.size-selector`, `.color-swatches`) via a config-driven exclusion selector list in `config/extraction_rules.py`.

---

## 3. UI & Boilerplate Text Leakage

### 3.1 Urban Outfitters BDG Bag (101211381): Feedback Form in `specifications`

**Symptom:** `"...BDG Giving classics an original twist... ] Was this product information helpful? Yes No"`

**Root cause:** `extract_heading_sections` in `field_value_dom.py` or `extract_page_long_text` targets a broad parent container (e.g., `.product-details`, `.product-info`) and concatenates all text within it. The feedback widget is a sibling or child of the specifications container and is not excluded by `SECTION_LABEL_SKIP_TOKENS` or pollution filters.

**Fix location:** `config/extraction_rules.py` — expand `DESCRIPTION_POLLUTION_TOKENS` / `SPECIFICATIONS_POLLUTION_TOKENS` with feedback-specific patterns: `"Was this product information helpful"`, `"Yes No"`, `"helpful?"`, `"Write a review"`. Also add generic UI container selectors to exclude: `[class*="feedback"]`, `[class*="review-form"]`, `[class*="rating-widget"]`.

### 3.2 Jordan 5 Retro (19468100086): Shipping Policy in `description`

**Symptom:** `"Once the order is shipped you will be emailed a tracking number. If you notice the tracking status reads 'Label Created'..."`

**Root cause:** Description fallback selects a broad page section when no structured `description` exists. The shipping/returns accordion panel is not excluded from the description scope. `config/extraction_rules.py` has `DESCRIPTION_POLLUTION_TOKENS` but it does not include shipping-specific phrases.

**Fix location:** `config/extraction_rules.py` — add shipping/returns/policy boilerplate tokens: `"tracking number"`, `"order is shipped"`, `"shipping policy"`, `"returns policy"`, `"delivery time"`, `"Label Created"`. Also add section-level exclusion for containers matching `[class*="shipping"]`, `[class*="returns"]`, `[class*="delivery-info"]`.

### 3.3 '47 NY Yankees Cap (B-RGW17GWS-VN): Marketing Copy in `description`

**Symptom:** `"(US) - only $35. Fast shipping on latest '47"`

**Root cause:** Same as 3.2 — the description is scraped from a marketing banner or promotional text block instead of the product description. The extraction source priority does not sufficiently penalize short, price-centric marketing strings when the real description is absent from structured data.

**Fix location:** `detail_extractor.py` — strengthen the long-text quality scorer to reject candidate descriptions that are <N words, contain only price + shipping phrases, or match marketing patterns (starting with `(US)`, `only $`, `Fast shipping`). This is a heuristic that belongs in `field_value_core.py` or `detail_record_finalizer.py`.

### 3.4 Anthropologie Boho Bangle (108064080): SEO Meta Description Scraped

**Symptom:** `"Shop the Boho Bangle Bracelets, Set of 3 and more at Anthropologie today. Read customer reviews..."`

**Root cause:** `config/extraction_rules.exports.json` lists `meta[name='description']` and `meta[property='og:description']` in `CANDIDATE_DESCRIPTION_META_SELECTORS`. These SEO blurbs are generic, marketing-driven, and often do not describe the actual product. The source priority in `detail_extractor.py` ranks structured data high, so the meta tag wins over thin DOM content even when the DOM contains a better description.

**Fix location:** `config/extraction_rules.py` — deprioritize or reject `meta[name='description']` / `og:description` for ecommerce detail when the content matches SEO patterns: starts with `"Shop the"`, `"Shop for"`, `"Buy"`, `"Discover"`, or contains `"Read customer reviews"`, `"at [Brand] today"`, `"Free shipping"`. Alternatively, remove meta selectors from the default description source list and only use them as a last-resort fallback below DOM sections.

### 3.5 Nikwax Tech Wash (724687): Quantity Selector Scraped as `color`

**Symptom:** `color` field is `"1"`.

**Root cause:** The `color` field extraction picks up a quantity `<select>` or `<input type="number">` node. `field_value_core.py:656-658` has a guard `if re.fullmatch(r"\d{1,2}", cleaned) and len(cleaned) <= 2: return None`, but this guard only runs inside `coerce_field_value` when the value is passed as a scalar. If the value arrives via a different path (e.g., adapter direct assignment, JS-state mapping, or DOM selector that bypasses `coerce_field_value`), the guard is skipped.

**Fix location:** `detail_dom_extractor.py` or `field_value_dom.py` — variant/color DOM discovery should exclude `<input type="number">`, `<select>` nodes with quantity-related labels (`qty`, `quantity`, `amount`), and nodes whose parent label contains quantity tokens. Also ensure all color assignments go through `coerce_field_value` so the numeric guard is always applied.

---

## 4. Truncations & Missing Data

### 4.1 Sony Headphones (00498): Description Truncated Mid-Sentence

**Symptom:** `"WH-1000XM5 Wireless Noise-canceling Headphones with Wireless"` (cuts off abruptly).

**Root cause:** `config/extraction_rules.py` contains a character limit or paragraph cap on description extraction. Alternatively, `detail_extractor.py` early-exits from DOM completion before all description sections are collected. The Zyte delta plan (Slice 6) already identifies a truncation cap as a known bug: "identify the cap that is shortening descriptions vs. Zyte's full text (likely a paragraph-only rule, char limit, or first-block selector)."

**Fix location:** `config/extraction_rules.py` — audit `DESCRIPTION_MAX_CHARS`, `DESCRIPTION_MAX_PARAGRAPHS`, or similar caps. Remove or raise the limit so descriptions are not truncated. `detail_extractor.py` — verify that `_requires_dom_completion` does not return `False` when only a partial description block has been collected.

### 4.2 New Balance (U18908JY-5): Description Truncated

**Symptom:** `"New Balance x Joe Freshgoods men's standard fit"` (cuts off).

**Root cause:** Same as 4.1 — a length cap or early-exit condition truncates the description before the full body text is extracted. This is particularly likely if the description is split across multiple accordion panels and only the first panel is collected.

**Fix location:** Same as 4.1. Also check `field_value_dom.py` accordion/tab scoping: ensure all expanded panels are concatenated, not just the first visible one.

### 4.3 Allbirds (WR3MABC080): Missing `color` on Root and Variants

**Symptom:** Color field is absent entirely.

**Root cause:** Allbirds uses a single-color product page where the color is implicit in the product title or URL slug. The flat variant contract (`extract/variant_record_normalization.py`) drops axis-less variants. Since there is only one variant and no explicit color swatch, the color is never extracted from the title/URL and the variant is dropped or kept without a color.

**Fix location:** `extract/shared_variant_logic.py` or `variant_record_normalization.py` — when a product has a single variant and no explicit color/size axis, infer the color from the product title or URL slug if the title contains a known color word. This should use the existing `VARIANT_COLOR_HINT_WORDS` config list.

### 4.4 Birkenstock (arizona-core-birkoflor-0-eva-u_1): Missing `size`

**Symptom:** Size field is absent.

**Root cause:** Same pattern as 4.3 — Birkenstock single-size products where the size is implicit. The variant extraction does not backfill size from the title/URL when no size selector exists on the page.

**Fix location:** Same as 4.3, but for size. Use `VARIANT_SIZE_VALUE_PATTERNS` to scan the title/URL for size tokens when no explicit size axis is present on single-variant products.

### 4.5 Nike AF1 (80S-THROWBACK): Missing `variants` Array

**Symptom:** `variants` array is missing entirely.

**Root cause:** Nike's product page may expose variants in a non-standard DOM structure (e.g., a size grid that is not inside a `<fieldset>` or standard `<select>`) or via JS state that `js_state_mapper.py` does not recognize. The DOM variant discovery in `detail_dom_extractor.py` or `shared_variant_logic.py` may fail because the Nike variant controls use custom class names or React components that don't match the generic variant scope selectors.

**Fix location:** `detail_dom_extractor.py` — expand variant DOM discovery to include Nike-specific container patterns (e.g., `.size-grid`, `.product-sizes`, `.css-` prefixed swatch containers) while keeping it generic. Also check `js_state_mapper.py` — ensure Nike's JS state hydration object is recognized as a product payload and parsed for variants.

### 4.6 Patagonia Jacket (84213-AQT): Missing `variants` Array

**Symptom:** `variants` array is missing entirely.

**Root cause:** Patagonia may expose variants as a color/size matrix in structured data (JSON-LD `hasVariant`) that is not being parsed, or the DOM variant discovery fails because the color/size options are rendered in a non-standard accordion/tab layout. The flat variant contract requires explicit color/size axes, and if neither structured nor DOM discovery finds them, the variants array is dropped.

**Fix location:** `structured_sources.py` — verify JSON-LD `hasVariant` parsing is active and correctly maps to the flat variant schema. `detail_dom_extractor.py` — check if Patagonia's variant UI is inside a `<details>/<summary>` or tab panel that is not currently expanded at the time of DOM extraction. Ensure `expand_all_interactive_elements` in `crawl_fetch_runtime.py` / `browser_detail.py` expands variant accordions before DOM extraction.

---

## 5. Cross-Cutting Root Causes

| Class | Affected Issues | Root Cause File(s) | Fix Strategy |
|-------|-----------------|---------------------|--------------|
| **No hidden-node filtering** | 2.1, 2.2 | `field_value_dom.py` | Skip `aria-hidden="true"`, `display:none`, `hidden` children in all text extraction |
| **No dict/list guard in coerce** | 1.1, 1.3 | `field_value_core.py` | Reject `str(dict)` / `str(list)` for scalar text fields; flatten structured arrays properly |
| **Meta description over-ranked** | 3.4 | `config/extraction_rules.py`, `detail_extractor.py` | Deprioritize SEO meta tags; pattern-match and reject generic marketing blurbs |
| **Pollution tokens incomplete** | 3.1, 3.2, 3.3 | `config/extraction_rules.py` | Expand token lists for feedback, shipping, returns, marketing banners |
| **Description truncation cap** | 4.1, 4.2 | `config/extraction_rules.py`, `detail_extractor.py` | Remove or raise char/paragraph limits; collect all accordion panels |
| **Axis-less variant drop** | 4.3, 4.4 | `variant_record_normalization.py`, `shared_variant_logic.py` | Infer color/size from title/URL for single-variant products |
| **Structured currency template defaults trusted blindly** | 0.1 (generic) | `detail_price_extractor.py`, `structured_sources.py`, `js_state_mapper.py` | JSON-LD `priceCurrency: "USD"` is often a template default on multi-market sites. For New Balance India, the site itself is inconsistent (header selector = USD, visible text = Rs.) — **likely a site bug, not crawler bug**. Generic fix: detect currency conflicts between JSON-LD, DOM text, and `<html lang>`, flag in diagnostics instead of silently picking one |
| **Template URL passthrough** | 1.2 | `field_value_dom.py`, `config/extraction_rules.py` | Reject URLs containing unresolved template placeholders |
| **Variant DOM discovery gaps** | 4.5, 4.6 | `detail_dom_extractor.py`, `js_state_mapper.py` | Expand generic variant scope selectors; ensure accordion/tab expansion before extraction |

---

## 6. Recommended Verification

After fixes, run:

```bash
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q -k "description or variant or color or size or specifications or currency or field_value"
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Add regression fixtures for:
- Vans bracket-noise description
- Converse template URL
- Sony dict-in-specifications
- Patagonia hidden-colorway description
- Urban Outfitters feedback-form specifications
- Anthropologie meta-description rejection
- Nikwax quantity-as-color
- New Balance truncation
- Allbirds implicit color
- Nike AF1 variant discovery
- New Balance JSON-LD USD template default vs. visible Rs./INR
