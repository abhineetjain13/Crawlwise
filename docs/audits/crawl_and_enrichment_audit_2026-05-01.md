# Crawl & Enrichment Quality Audit — 2026-05-01 (Revised)

## 1. Executive Summary

This audit covers the 23 successfully-crawled commerce detail records (Run 1) and their corresponding enrichment job (Job 10). Failed sites (e.g. HM bot-protection failures) are excluded — those are tracked in a separate remediation effort.

| Pipeline | Status | Key Issue Classes |
|----------|--------|-------------------|
| **Extraction (Run 1)** | 23 records, core fields present | Variant-option pollution, brand corruption, locale price errors, availability URL passthrough, image artifacts, text-blob specs |
| **Enrichment (Job 10)** | 23 products, deterministic tier ran | Taxonomy hallucinations, material context blindness, size false-positives, bloated SEO keywords, deep-enrichment gaps |
| **LLM backfill** | 8 calls recorded (last 7 days) | Cost tracking broken ($0.00), single-model routing, no category gating |

---

## 2. Crawl Output Quality — Code-Level Root Causes

### 2.1 Variant Option Value Pollution (Back Market iPhone)

**Symptom:** `color`: `"Black $382.00"`, `condition`: `"Excellent $450.01 Popular"`

**Root cause:** `extract_node_value` in `app/services/field_value_dom.py:382-425` harvests visible text via `node.get_text(" ", strip=True)`. For `<option>` or swatch nodes that contain child `<span>` price badges or popularity labels, `get_text()` concatenates everything. There is no child-node stripping logic for variant-option fields.

**Fix location:** `field_value_dom.py` — add a variant-specific text extractor that drops child nodes matching price/label selectors before reading text.

### 2.2 Brand Corruption (`"0 Apple"`)

**Symptom:** Back Market iPhone brand is `"0 Apple"`.

**Root cause:** `coerce_field_value` in `app/services/field_value_core.py:816-824` handles brand as a dict by reading `value.get("name")` or `value.get("title")` or `value.get("value")`. If the structured source (JSON-LD or JS-state) contains `{"0": "Apple"}` or an array `["Apple"]` that gets wrapped as a dict with index keys, the `"0"` prefix leaks into the string. The `_coerce_brand_text` helper does not strip numeric prefixes.

**Fix location:** `field_value_core.py` — sanitize numeric index prefixes in `_coerce_brand_text`.

### 2.3 Parent Price Decimal Error (Puma ARS)

**Symptom:** Parent `price`: `"113999"` vs variant `price`: `"1139.99"`.

**Root cause:** `_decimal_text` in `app/services/data_enrichment/service.py:1117-1126` calls `normalize_decimal_price(value)` which applies a single locale heuristic. For ARS (Argentina), the site likely uses comma as decimal separator (`1.139,99`) or dot as thousands separator. The deterministic price normalizer does not disambiguate locale based on TLD/domain.

**Fix location:** `field_value_core.py` or `normalizers.py` — add per-domain locale hints (`ar.puma.com` → comma-decimal) to `normalize_decimal_price`.

### 2.4 Rating as String

**Symptom:** `"rating": "4.5"` (string) while `review_count` is integer.

**Root cause:** `coerce_field_value` in `app/services/field_value_core.py` does not have a float-coercion branch for `rating`. It falls through to `coerce_text`, returning a string. `review_count` has an explicit integer regex path.

**Fix location:** `field_value_core.py` — add `if field_name == "rating": return float(coerce_text(value))` in `coerce_field_value`.

### 2.5 Availability Schema.org URL

**Symptom:** `"availability": "https://schema.org/LimitedAvailability"` (Karen Millen)

**Root cause:** The availability normalizer in `field_value_core.py` (around lines 770-789) only maps boolean and plain-text values. It does not normalize Schema.org URLs to the internal snake_case enum (`limited_stock`).

**Fix location:** `config/extraction_rules.py` — add an `AVAILABILITY_URL_MAP`; apply it in `field_value_core.py` before the boolean/text paths.

### 2.6 Image Scraper Artifacts (Firstcry)

**Symptom:** `additional_images` contains UI assets: `ic_to_arrow.png`, `LodingCart.gif`.

**Root cause:** `_is_garbage_image_candidate` in `app/services/field_value_dom.py:264-276` checks `NON_PRODUCT_IMAGE_HINTS` and `NON_PRODUCT_PROVIDER_HINTS`, but those config lists do not include generic UI tokens like `loading`, `arrow`, `icon`, `spinner`. Also `extract_page_images` at line 554 does not filter by minimum dimensions for non-gallery contexts.

**Fix location:** `config/extraction_rules.py` — expand `NON_PRODUCT_IMAGE_HINTS` with `loading`, `arrow`, `icon`, `spinner`, `placeholder`. Optionally add a min-dimension gate in `field_value_dom.py`.

### 2.7 Python Dict String in `product_type` (Puma)

**Symptom:** `"product_type": "{'variationGroup': True}"`

**Root cause:** `_flatten_dict_values` in `app/services/data_enrichment/service.py:1018-1027` recursively flattens dicts into strings via `str(item)`. When a JS-state payload contains a Python dict object (from `harvest_js_state_objects` in `extraction_context.py`), the stringification leaks raw dict syntax.

**Fix location:** `extraction_context.py` — ensure `harvest_js_state_objects` extracts scalar strings, not objects, for `product_type`. Or add a guard in `field_value_core.py` that rejects string values starting with `{` for `product_type`.

### 2.8 Text Blob Concatenation (Rockler specs, Wayfair sofa)

**Symptom:** `specifications` is a single unformatted string: `"Brand Rockler Weight 18.25 Tech Spec Brand: Rockler Materials..."`

**Root cause:** `extract_heading_sections` in `app/services/field_value_dom.py:996-1012` collects text from `<tr>`, `<dt>/<dd>`, and generic `<li>/<p>/<div>` nodes, but the `<li>` splitter (line 627) only splits on `:`. Rockler specs use key-value pairs without colons in some nodes, so they get concatenated as a flat space-delimited blob.

**Fix location:** `field_value_dom.py` — add a key-value regex pattern for Rockler-style flat spec lists (e.g. `Brand Rockler Weight 18.25 ...`) inside `extract_label_value_pairs` or a new spec normalizer.

---

## 3. Data Enrichment Quality — Code-Level Root Causes

### 3.1 Taxonomy Hallucinations

**Symptoms:**
- Fashion Nova Pant Set → `Furniture > Furniture Sets`
- Tommy Hilfiger Oxfords → `Apparel & Accessories > Clothing > Men's Undergarments`
- Zadig & Voltaire T-Shirt → `Business & Industrial > Retail > Paper & Plastic Shopping Bags > T-Shirt Shopping Bags`

**Root cause:** `_top_taxonomy_candidates` in `app/services/data_enrichment/service.py:721-733` delegates to `top_taxonomy_candidates` in `shopify_catalog.py`. The matching is keyword-based with `category_match_threshold=0.42` (hard-coded in `config/data_enrichment.py`). It scores category paths by token overlap against `category`, `product_type`, and `title`. A title containing "T-shirt" overlaps with "T-shirt Shopping Bags" enough to pass the 0.42 threshold.

**Fix location:** `config/data_enrichment.py` — raise `category_match_threshold` to ≥ 0.65 for keyword-only matching, or add a negative-penalty for non-apparel tokens (`shopping bags`, `furniture sets`). Alternatively, use the LLM backfill (`category_path`) as the primary taxonomy source when deterministic confidence is < 0.6.

### 3.2 Material Extraction Artifacts (Context Blindness)

**Symptoms:**
- Todd Snyder Suit: materials list `cashmere, cotton, denim, leather, linen, suede, twill, fabric` — the brand's global fabric glossary from the footer/description was scraped.
- Untuckit Shirt: materials include `iron` — extracted from care instructions ("Iron warm, if needed").

**Root cause:** `_normalize_materials` in `app/services/data_enrichment/service.py:679-697` scans **all** candidate values from `materials`, `product_attributes`, `description`, and `title` without restricting to product-detail sections:

```python
for value in _candidate_values(
    data, "materials", "product_attributes", "description", "title"
):
```

The `_term_present` regex (`(?<![a-z0-9]){term}(?![a-z0-9])`) matches any occurrence, including footer links and care-instruction text.

**Fix location:** `service.py` — restrict material candidate sources to `materials` and `product_attributes` first. Only fall back to `description` if the primary sources are empty, and strip care-instruction sections (look for "care", "wash", "iron", "dry clean" labels) before scanning.

### 3.3 Price & Currency Formatting

**Symptoms:**
- Firstcry (#7): lists `868.21` without currency code (should be INR).
- ASOS (#15) and Wayfair (#16): missing price data entirely.

**Root cause:** `_normalize_price` in `app/services/data_enrichment/service.py:582-609` builds the normalized price object only if a raw price exists:

```python
raw_price = _first_present(data, "price", "sale_price", "original_price")
```

For Firstcry, the crawl record **does** have a price but lacks a `currency` key. `_normalize_price` then falls through to `infer_currency_from_page_url(source_url)`. If `infer_currency_from_page_url("firstcry.com")` returns `None` (not mapped), the currency is omitted.

For ASOS and Wayfair, the raw `price` field is completely absent from the crawl data — this is an **upstream extraction failure**, not an enrichment bug.

**Fix location:** `field_value_core.py` — add `firstcry.com` → `INR` to the domain-to-currency mapping in `infer_currency_from_page_url`. For ASOS/Wayfair, fix upstream extraction.

### 3.4 Size False Positive (ColourPop Eyeshadow)

**Symptom:** ColourPop Eyeshadow (#19) has `size: 24` with `size_system: numeric`. "24" is likely grams or pan count, not apparel size.

**Root cause:** `_plausible_size_value` in `app/services/data_enrichment/service.py:657-668` uses a regex that accepts any pure number:

```python
return bool(re.fullmatch(r"\d+(?:\.\d+)?(?:\s*(?:m|t|w|y|us|uk|eu))?", normalized))
```

There is **no category gating**. A numeric value in any product category passes as a plausible size.

**Fix location:** `service.py` — gate `_normalize_sizes` so it only runs when the product category or title contains apparel/footwear/lingerie signals. Skip size normalization for `beauty`, `electronics`, `home`, `tools`, `hardware`.

### 3.5 Bloated SEO Keywords

**Symptom:** Pura Vida Bracelet (#21) keywords: `black, seascape, stretch, bracelet, ..., black seascape, seascape stretch, stretch bracelet` — redundant unigrams and bigrams with little semantic value.

**Root cause:** `_build_seo_keywords` in `app/services/data_enrichment/service.py:759-799` concatenates all `raw_parts` (title, brand, category, etc.) into a single token stream, then emits unigrams from the combined stream plus bigrams from the title only:

```python
title_tokens = _keyword_tokens(data.get("title"), stopwords)
for token in [
    *_keyword_tokens(" ".join(clean_text(part) for part in raw_parts), stopwords),
    *list(_bigrams(title_tokens)),
]:
```

There is no deduplication against the title itself, and bigrams are generated from adjacent title tokens regardless of semantic coherence.

**Fix location:** `service.py` — replace bigram generation with semantic phrase extraction (e.g. noun chunks) or skip bigrams entirely if they duplicate unigrams. Cap keyword diversity: if a unigram already exists, do not emit a bigram containing it.

### 3.6 Deep Enrichment Fields Dropped

**Symptom:** `intent_attributes`, `audience`, `style_tags`, `ai_discovery_tags`, `suggested_bundles` only present for ~35% of products (items #1-7 and #12).

**Root cause:** These fields are **only produced by the LLM backfill** (`data_enrichment_semantic.user.txt` prompt). The deterministic tier (`_build_deterministic_enrichment`) does not populate them. The LLM prompt (`app/data/prompts/data_enrichment_semantic.user.txt`) asks for:

```
"intent_attributes": ["3-8 short product intent phrases"],
"audience": ["2-5 audience descriptors"],
...
```

But only 8 LLM calls were recorded for 23 products. The missing 15 products either:
1. Had LLM calls that failed before `session.add(LLMCostLog)` (error paths in `llm_tasks.py:269-314` return before the DB write), or
2. Hit the cache, or
3. The `llm_enabled` job option was not set for all products.

Regardless of the exact mechanism, the coverage gap is real: the deterministic pipeline cannot backfill deep enrichment fields, and the LLM backfill is inconsistent.

**Fix location:** `llm_tasks.py` — ensure failed/partial LLM calls are still recorded in `llm_cost_log` with error metadata. Alternatively, move deep-field generation into a cheaper model or deterministic heuristic tier (e.g. rule-based audience tags from category + gender).

---

## 4. LLM Usage & Optimization

### 4.1 Cost Tracking Bug

`llm_cost_log.cost_usd` is `$0.0000` for every call. `llm_configs.per_domain_daily_budget_usd` and `global_session_budget_usd` are also `$0.00`.

**Root cause:** `estimate_cost_usd` in `app/services/llm_provider_client.py` (called from `llm_tasks.py:329`) has no pricing table for Groq models. The config stores `$0.00` because no default rates are loaded.

**Fix:** Add Groq token pricing to `llm_provider_client.py` or `config/llm_runtime.py`.

### 4.2 Multi-Model Routing Gap

Per `docs/VISION.md` Phase 2, the most important optimization is **multi-model routing**. Current state: only one model (`llama-3.3-70b-versatile`) handles all tasks.

| Task Type | Current Model | Better Fit |
|-----------|---------------|------------|
| `data_enrichment_semantic` | `llama-3.3-70b` (Groq) | `llama-3.1-8b` or `gemma-2-9b` sufficient for enum mapping |
| `xpath_discovery` | `llama-3.3-70b` (Groq) | Good fit, but **zero calls** in last 7 days — deterministic tier is working |

**Fix:** Add per-task model selection in `llm_config_service.py` `resolve_active_config`. Register cheaper models for `data_enrichment_semantic`.

### 4.3 Category-Gated Enrichment

The LLM is called for `size`/`gender` on products where those fields are semantically irrelevant (tools, electronics, home goods). This wastes ~30% of enrichment tokens.

**Fix:** In `_enrich_product` (`service.py:265-308`), skip LLM backfill for `size_normalized` and `gender_normalized` when the deterministic `category_path` contains `electronics`, `tools`, `hardware`, `home`, `furniture`, `beauty`.

---

## 5. Fix Priority Matrix (Data Quality Focus)

| Priority | Issue | Owner File | Effort | Impact |
|----------|-------|------------|--------|--------|
| **P0** | Variant option text pollution | `field_value_dom.py` (child-node stripper) | Low | High (breaks faceted search) |
| **P0** | Taxonomy hallucinations (keyword overlap) | `shopify_catalog.py` + `config/data_enrichment.py` | Medium | High (wrong category = wrong audience) |
| **P0** | Material context blindness (footer/care text) | `data_enrichment/service.py` `_normalize_materials` | Low | High (wrong product data) |
| **P0** | Brand corruption `"0 Apple"` | `field_value_core.py` `_coerce_brand_text` | Low | Medium |
| **P1** | Size false positive (non-apparel) | `data_enrichment/service.py` `_normalize_sizes` | Low | Medium |
| **P1** | ARS price decimal error | `field_value_core.py` / `normalizers.py` | Low | Medium |
| **P1** | Availability URL normalization | `config/extraction_rules.py` + `field_value_core.py` | Low | Medium |
| **P1** | Image artifact filtering | `config/extraction_rules.py` `NON_PRODUCT_IMAGE_HINTS` | Low | Medium |
| **P1** | LLM cost tracking $0.00 | `llm_provider_client.py` `estimate_cost_usd` | Low | High (visibility) |
| **P1** | Deep enrichment dropped / partial LLM | `llm_tasks.py` error-path logging + `service.py` deterministic deep fields | Medium | Medium |
| **P2** | `product_type` dict string | `extraction_context.py` or `field_value_core.py` | Low | Low |
| **P2** | Rating string → float | `field_value_core.py` `coerce_field_value` | Low | Low |
| **P2** | Text blob specs (key-value regex) | `field_value_dom.py` `extract_label_value_pairs` | Medium | Low |
| **P2** | Bloated SEO keywords | `data_enrichment/service.py` `_build_seo_keywords` | Low | Low |
| **P2** | Firstcry currency missing | `field_value_core.py` `infer_currency_from_page_url` | Low | Low |

---

## 6. Summary of Missing Fields & Recommendations

### Extraction Tier

| Field | Missing On | Root Cause | Recommended Fix |
|-------|-----------|------------|-----------------|
| `brand` | 1/19 (Firstcry Babyhug) | Site uses non-standard brand markup | Add domain-specific selector rule |
| `image_url` | 1/19 (Cozyla Calendar) | Image not in standard gallery DOM | Add fallback image selector for Cozyla domain |
| `sku` | 3/19 | Source site lacks structured SKU | Acceptable — no action |
| `availability` | 5/19 | Structured data absent or URL-formatted | Fix URL normalizer + add Schema.org mapping |
| `category` | 6/19 | Breadcrumb extraction fails on flat taxonomies | Add flat-string category heuristics |
| `rating` | 12/19 | Site does not expose rating | Acceptable |
| `materials` | 12/19 | Non-apparel items or missing markup | Acceptable for non-apparel |

### Enrichment Tier

| Field | Missing On | Root Cause | Recommended Fix |
|-------|-----------|------------|-----------------|
| `color_family` | 1/23 (Back Market iPhone) | Upstream variant-option pollution | Fix extraction first |
| `materials_normalized` | 2/23 (Back Market, Zadig) | Context blindness / regex miss | Restrict scan to product-detail sections; add "100% Cotton*" parser |
| `availability_normalized` | 1/23 (Zadig) | Deterministic mapper missed snake_case value | Add `in_stock` → `in_stock` passthrough in `_normalize_from_terms` |
| `size` / `size_system` | 13/23 (non-apparel) | Domain-appropriate absence | Add category gating to metric calculation |
| `gender` | 15/23 (non-apparel/unisex) | Domain-appropriate absence | Add category gating to metric calculation |
| Deep enrichment fields | 15/23 | LLM backfill inconsistent / prompt truncation | Add deterministic fallbacks; fix LLM error logging |
