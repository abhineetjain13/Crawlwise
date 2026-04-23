# Failure Mode Report: Extraction Quality Regression vs. Old App

**Date:** 2026-04-21
**Source:** Artifact analysis of last 6 crawls (runs 15–20), code audit of current vs. old app
**Scope:** Listing/detail extraction quality, bot detection, variant extraction, accordion/carousel data

---

## Executive Summary

The current app produces **noisy, semantically empty extraction output** on listing and detail pages where the old app (`C:\Users\abhij\Downloads\pre_poc_ai_crawler`) reliably extracted structured product data. The IMPLEMENTATION_GUIDE_OLD_TO_NEW.md was partially implemented but the ported features are **not wired into the pipeline** — they exist as dead code. Additionally, a critical bot-detection failure on KitchenAid and a variant extraction gap compound the regression.

---

## Part 1: Failure Modes from Last 6 Crawls

### FM-1: Listing Extraction Produces Noise Instead of Structured Records

**Severity:** CRITICAL
**Evidence:** Run 19 (Zara listing), Run 15 (Dyson listing), Run 17 (KitchenAid listing)
**Artifact data:**

| Run | Site | Surface | `listing_card_count` | `matched_listing_selectors` | Outcome |
|-----|------|---------|---------------------|----------------------------|---------|
| 19 | Zara | `ecommerce_listing` | 0 | 0 | `usable_content` but 0 cards detected |
| 15 | Dyson | `ecommerce_listing` | 1 | 0 | `usable_content` but no structured records |
| 17 | KitchenAid | `ecommerce_listing` | 0 | 0 | `usable_content` but Akamai detected |

**Root cause chain:**
1. `listing_extractor.py:extract_listing_records()` runs `_structured_stage()` → `_dom_stage()` → `_visual_listing_records()` in sequence
2. `_structured_stage()` finds JSON-LD payloads but they are often **navigation/category objects** not product records on SPA sites (Zara, Dyson)
3. `_dom_stage()` relies on `CARD_SELECTORS` which match **zero** card fragments on these SPA-rendered pages — the product grid uses custom React components with no semantic class names
4. `_visual_listing_records()` is the final fallback but it produces **image+alt-text only** records with no price, no URL, no brand — this is the "noise" the user sees
5. **No agentic retry loop exists** — when extraction is thin (<5 records), the current app accepts the noise and moves on

**Why old app succeeded:** The old app's `_extract_all_dom()` in `spa_crawler_service.py:3340-3356` runs **5 extraction strategies concurrently** via `asyncio.gather()`:
- JSON-LD extraction
- Commerce anchor row extraction (finds `<a>` tags with product-like hrefs)
- DOM parsing with **JavaScript-evaluated selectors** (`page.evaluate()` with product name/price/link extraction)
- Job link extraction
- `__NEXT_DATA__` extraction

It then uses `_choose_best_record_set()` to pick the richest source. The current app has **none of these parallel strategies** — it runs a single-threaded Python-only extraction pipeline that never evaluates JavaScript in the page context.

---

### FM-2: Detail Page Accordion/Tab Content Not Extracted

**Severity:** CRITICAL
**Evidence:** Run 20 (Zara detail ×2), Run 18 (KitchenAid detail ×2)
**Artifact data:**

| Run | Site | `buttons_found` | `clicked_count` | `expanded_elements` | Status |
|-----|------|----------------|-----------------|---------------------|--------|
| 20 | Zara perfume | 46 | 0 | [] | `time_budget_reached` |
| 20 | Zara loafers | 69 | 0 | [] | `time_budget_reached` |
| 18 | KitchenAid chopper | 145 | 2 | ["stand mixers", "coffee & espresso"] | `time_budget_reached` |
| 18 | KitchenAid processor | 46 | 0 | [] | `time_budget_reached` |

**Root cause chain:**
1. `expand_all_interactive_elements_impl()` in `browser_detail.py:103-191` uses a **single flat locator** (`_DETAIL_EXPAND_SELECTORS`) that matches ALL buttons on the page
2. It iterates through every matched element checking `looks_expandable` — but on pages with 46–145 buttons, the **2.5s time budget** (`detail_expand_max_elapsed_ms=2500`) expires before reaching the actual accordion/tab buttons
3. The `looks_expandable` check requires either `aria-expanded="false"`, `aria-controls`, `tag_name=="summary"`, OR a keyword match — but Zara's accordion buttons use **custom React components** with none of these attributes; their text is just "MORE INFO" or "DESCRIPTION" which doesn't match the keyword list
4. Even when expansion succeeds (KitchenAid chopper: 2 clicks), the extraction pipeline **does not use the expanded content** — `extract_heading_sections()` in `field_value_dom.py:688-701` only extracts from the static HTML snapshot, not from the post-expansion DOM

**Why old app succeeded:** The old app's `safe_expand_semantic_content()` in `semantic_browser_helpers.py:50-101`:
- Uses **9 separate selector queries** (not one flat locator), each bounded by `max_per_selector=4`
- Is **field-aware**: derives expansion tokens from `requested_fields` (e.g., if user wants "material", it clicks buttons with "material" text)
- Has **blocked tokens** to avoid clicking "Add to Cart" / "Buy Now"
- Checks **actual ARIA state** (`aria_expanded == "false"`) before clicking
- The old app then extracts sections via `_extract_sections()` in `semantic_detail_extractor.py:264-349` which follows `aria-controls` attributes, walks up the DOM to find accordion content containers, and handles `<details>/<summary>` natively

The current app's `extract_heading_sections()` WAS ported from the old app (it has `_SECTION_LABEL_SELECTOR`, `_SECTION_CONTAINER_SELECTORS`, `_find_wrapped_section_content`) but the **expansion step is broken** — it finds 0 elements to expand on Zara because the selector strategy is wrong.

---

### FM-3: KitchenAid Detail Crawl Blocked by Akamai Bot Detection

**Severity:** HIGH
**Evidence:** Run 18 (KitchenAid detail ×2)
**Artifact data:**

| Page | `browser_outcome` | `challenge_provider_hits` | `challenge_element_hits` |
|------|-------------------|--------------------------|--------------------------|
| KitchenAid chopper | `challenge_page` | ["akamai", "g-recaptcha", "recaptcha"] | ["captcha_titled_iframe"] |
| KitchenAid processor | `challenge_page` | ["akamai", "g-recaptcha", "recaptcha"] | ["captcha_titled_iframe"] |

**Root cause chain:**
1. KitchenAid uses **Akamai Bot Manager** with reCAPTCHA challenge
2. The current app's browser launches with **no fingerprint diversification** — `browser_identity.py` generates browserforge fingerprints but the **context options are minimal**: no WebGL spoofing, no canvas noise, no consistent viewport/timezone/locale per session
3. The current app's `pacing.py` enforces `acquire_host_min_interval_ms=250` between requests to the same host — but for Akamai-protected sites, this is far too aggressive. The old app used **adaptive pacing** that detected Akamai headers and increased delay to 3–5 seconds
4. The current app has **no cookie consent pre-handling** for Akamai — Akamai's JavaScript challenge sets a `_abck` cookie that must be present before the real page loads. The current app's `cookie_consent_prewait_ms=400` is too short for Akamai's challenge cycle
5. The old app's `spa_crawler_service.py` had a **challenge recovery loop** that waited for Akamai challenges to auto-resolve (up to 7 seconds), then retried navigation — the current app has no such recovery

**Why old app succeeded on KitchenAid:** The old app:
- Used **longer navigation waits** (`networkidle` strategy by default, not `domcontentloaded`)
- Had **adaptive pacing** that detected Akamai response headers and increased inter-request delays
- Had a **challenge recovery loop** that waited for `_abck` cookie to appear before proceeding
- Used **consistent session identity** — same fingerprint, viewport, timezone across all requests in a session

---

### FM-4: Variants Missing Despite `variant_count` Being Captured

**Severity:** HIGH
**Evidence:** User report — variant count shows but no variant rows
**Code analysis:**

The variant extraction has **two separate code paths** that produce inconsistent results:

1. **JS state path** (`js_state_mapper.py:253-365`): When `__NEXT_DATA__` or embedded JSON contains a `variants` array, `_map_product_payload()` correctly builds full variant rows with `variant_id`, `sku`, `price`, `color`, `size`, `option_values`. This sets `variant_count = len(variants)` AND populates `variants` list.

2. **DOM path** (`detail_extractor.py:563-666`): `_extract_variants_from_dom()` finds `<select>` dropdowns and swatch containers, builds `option1_name`, `option1_values`, `variant_axes`, `available_sizes`. It sets `variant_count = sum(len(group["values"]))` which is the **sum of axis values**, NOT the number of actual variant combinations.

**The gap:** When JS state extraction finds variants, it works. But when JS state has **no variant data** (common on sites like Zara, Dyson that use React state instead of `__NEXT_DATA__`), the DOM path runs. The DOM path:
- Only finds **up to 2 option groups** (hard cap at line 647: `if len(deduped_groups) >= 2: break`)
- Computes `variant_count` as the **sum of axis values** (e.g., 3 colors + 4 sizes = 7) instead of the Cartesian product (3 × 4 = 12)
- Does NOT build individual variant rows — it only captures axis names and values, not the actual combinations
- The `variants` field in the record remains `null` because `_extract_variants_from_dom()` returns `option1_name/option1_values` but not a `variants` list

**Why old app succeeded:** The old app's `js_state_mapper.py` had the same JS state path, but its `spa_crawler_service.py` also ran **in-browser JavaScript evaluation** (`page.evaluate()`) that directly accessed the React component state to extract variant data from `window.__NEXT_DATA__`, `window.__NUXT__`, or the React fiber tree. The current app's `harvest_js_state_objects()` only searches `<script>` tags for JSON-like objects — it never evaluates JavaScript in the browser context.

---

### FM-5: Markdown Generation Crashes on Complex HTML (Zara)

**Severity:** HIGH
**Evidence:** System memory — `AttributeError: 'NoneType' object has no attribute 'get'` on every browser crawl
**Root cause:** `_generate_page_markdown()` in `browser_page_flow.py:613-674` calls `node.get("class", [])` on BeautifulSoup nodes that can have `attrs=None` after `decompose()` on certain complex HTML (e.g., Zara). The guard at lines 619–621 (`isinstance(getattr(node, "attrs", None), dict)`) was added but the **second pass** at lines 625–637 still accesses `attrs.get("class", [])` without the same guard, causing crashes on the same nodes that were decomposed during the first pass.

**Status:** Partially fixed (first pass guarded, second pass vulnerable)

---

## Part 2: Why the Old App Extracted Better Data — Architectural Audit

### OA-1: Multi-Strategy Concurrent Extraction

**Old app:** `spa_crawler_service.py:3340-3363`
```python
results = await asyncio.gather(
    _extract_json_ld_from_page(page, url, emit),
    _extract_commerce_anchor_rows(page, url, emit),
    _extract_from_dom(page, url, emit),
    _extract_job_links_from_dom(page, url, emit),
    _extract_next_data_from_page(page, url, emit),
    return_exceptions=True,
)
all_records, method = _choose_best_record_set([...])
```

**Current app:** `extraction_runtime.py:43-103`
```python
# Sequential: structured → DOM → visual fallback
# No concurrency, no strategy selection, no "best set" picking
```

**Impact:** The old app always found the richest source. The current app stops at the first source that returns ≥1 record, even if it's garbage.

---

### OA-2: In-Browser JavaScript Extraction

**Old app:** `spa_crawler_service.py:2256-2320` — Uses `page.evaluate()` to run JavaScript inside the browser that directly queries the DOM for product names, prices, links, and images using CSS selectors that are evaluated in the **live rendered DOM** (post-React hydration).

**Current app:** All extraction is **Python-only** on the serialized HTML string. The `LexborHTMLParser` and `BeautifulSoup` parsers operate on the static HTML snapshot. They cannot access:
- React component state
- Computed CSS styles that reveal/hide content
- JavaScript-evaluated data attributes
- `window.__NEXT_DATA__`, `window.__NUXT__` (only searched in `<script>` tags, not evaluated)

**Impact:** On SPA sites (Zara, Dyson, KitchenAid), the rendered DOM has product data in React-managed elements that have no semantic HTML markers. Python-only extraction sees only the SSR shell or empty hydration placeholders.

---

### OA-3: Agentic Retry Loop

**Old app:** `spa_crawler_service.py:1647-1762` — When initial extraction yields <5 records, the agentic retry loop:
1. Removes active filters ("Clear All", "Reset Filters")
2. Clicks "View All" / "See All" / "Shop All"
3. Tries pagination
4. Re-extracts after each action using all 5 strategies

**Current app:** No equivalent. `listing_recovery_diagnostics` in artifacts shows `"status": "skipped", "reason": "not_requested"` on every crawl. The `listing_recovery_enabled=True` config exists but the recovery logic only handles scroll/load-more, not filter removal or view-all expansion.

**Impact:** On filtered or paginated listings, the current app extracts only the initially visible subset.

---

### OA-4: Semantic Expansion Before Extraction

**Old app:** `semantic_browser_helpers.py:50-101` — 9 ordered selector queries, field-aware tokens, blocked commerce tokens, ARIA state checking, bounded per-selector. Called **before** content serialization.

**Current app:** `browser_detail.py:103-191` — Single flat locator matching ALL buttons, iterated sequentially with a 2.5s time budget. On pages with 46–145 buttons, the budget expires before reaching actual accordion buttons.

**Impact:** Accordion/tab content is never revealed, so extraction only gets the collapsed (minimal) content.

---

### OA-5: LLM Direct Extraction Fallback

**Old app:** `spa_crawler_service.py:4235-4254` — When deterministic extraction yields <3 records AND markdown is available AND LLM is configured, the old app sends the cleaned markdown + ARIA accessibility tree to the LLM for direct extraction.

**Current app:** LLM is only used for **missing field extraction** (`llm_runtime.py:extract_missing_fields()`) — it fills in individual fields on an existing record. There is no "extract records from scratch" LLM fallback.

**Impact:** When all deterministic extraction fails (SPA sites with no JSON-LD, no semantic DOM), the current app returns empty records with no recovery path.

---

### OA-6: Adaptive Bot Detection Handling

**Old app:** `spa_crawler_service.py` had:
- Challenge recovery loop (wait up to 7s for auto-resolution)
- Akamai `_abck` cookie detection and wait
- Adaptive pacing that increased delays when protection headers detected
- Consistent session identity (fingerprint, viewport, timezone)

**Current app:** `browser_identity.py` generates fingerprints but:
- No challenge recovery loop
- No adaptive pacing for protected sites
- `acquire_host_min_interval_ms=250` is too aggressive for Akamai
- `cookie_consent_prewait_ms=400` is too short for Akamai challenge cycle
- No `_abck` cookie detection

**Impact:** Sites like KitchenAid that never failed in the old app now return challenge pages.

---

## Part 3: Failure Mode Summary Table

| ID | Failure Mode | Severity | Current App Root Cause | Old App Advantage |
|----|-------------|----------|----------------------|-------------------|
| FM-1 | Listing noise instead of structured records | CRITICAL | Single sequential extraction, no JS evaluation, no strategy selection | 5 concurrent strategies + `_choose_best_record_set()` |
| FM-2 | Accordion/tab content not extracted | CRITICAL | Flat button locator + 2.5s budget + no field-aware expansion | 9 ordered selectors + field-aware tokens + blocked tokens |
| FM-3 | KitchenAid blocked by Akamai | HIGH | No challenge recovery, aggressive pacing, no `_abck` detection | Challenge recovery loop + adaptive pacing + session identity |
| FM-4 | Variants missing despite count captured | HIGH | DOM path builds axes only, not variant rows; no JS state evaluation | In-browser JS evaluation of React state for variant data |
| FM-5 | Markdown crash on complex HTML | HIGH | Second-pass attrs access not guarded after decompose() | N/A (same bug potential) |

---

## Part 4: Recommendations (No Site-Specific Hacks)

All recommendations are **architectural** — they fix the extraction pipeline's structural deficits, not individual site quirks.

### R-1: Wire Multi-Strategy Concurrent Extraction into Listing Pipeline

**Target:** `listing_extractor.py:extract_listing_records()`
**Change:** Replace sequential `_structured_stage() → _dom_stage() → _visual_stage()` with concurrent execution of all three, then pick the best result set using a scoring function (record count × field coverage). This mirrors the old app's `_extract_all_dom()` + `_choose_best_record_set()` pattern.

### R-2: Add In-Browser JavaScript Extraction as a Strategy

**Target:** New function in `browser_page_flow.py` or `browser_capture.py`
**Change:** Add a `page.evaluate()` call that extracts product records directly from the rendered DOM using JavaScript. This should run **before** the Python-only extraction pipeline. The JS function should:
- Find product card elements using a broad set of selectors
- Extract name, price, link, image from each card
- Return a JSON array of records

This is the single highest-impact change — it would fix FM-1 and FM-4 for all SPA sites.

### R-3: Fix the Expansion Selector Strategy

**Target:** `browser_detail.py:expand_all_interactive_elements_impl()`
**Change:** Replace the single flat `_DETAIL_EXPAND_SELECTORS` locator with the old app's 9 ordered selector queries from `semantic_browser_helpers.py`. Add:
- Field-aware token derivation from `requested_fields`
- Blocked commerce tokens
- Per-selector bounding (`max_per_selector=4`)
- Increase `detail_expand_max_elapsed_ms` from 2500 to 6000ms

### R-4: Build Variant Rows from DOM Axes

**Target:** `detail_extractor.py:_extract_variants_from_dom()`
**Change:** After extracting option groups, compute the **Cartesian product** of all axes to generate individual variant rows (like `resolve_variants()` already does for JS state variants). Set `variant_count` to the product count, not the sum. Populate the `variants` field with the generated rows.

### R-5: Add Challenge Recovery Loop for Bot Detection

**Target:** `browser_page_flow.py:navigate_browser_page_impl()`
**Change:** After navigation, if Akamai/Cloudflare challenge is detected:
1. Wait up to 7 seconds for auto-resolution (poll for `_abck` cookie)
2. If resolved, re-serialize the page
3. If not resolved, retry navigation once with longer timeout
4. Increase `acquire_host_min_interval_ms` to 2000ms for hosts that return protection headers

### R-6: Add LLM Direct Extraction Fallback

**Target:** `pipeline/core.py` or new module
**Change:** When `len(records) < 3` after all deterministic extraction AND `page_markdown` is non-empty AND LLM is configured, call the LLM with the markdown + ARIA tree to extract records directly. This mirrors the old app's Strategy 2 at `spa_crawler_service.py:4235`.

### R-7: Fix Markdown Second-Pass Crash

**Target:** `browser_page_flow.py:625-637`
**Change:** Add the same `isinstance(getattr(node, "attrs", None), dict)` guard to the second noise-removal pass that was added to the first pass at lines 619–621.

---

## Implementation Priority

| Priority | Recommendation | Est. Impact | Files |
|----------|---------------|-------------|-------|
| **P0** | R-2: In-browser JS extraction | +40-60% listing coverage | `browser_page_flow.py` or `browser_capture.py` |
| **P0** | R-3: Fix expansion selectors | +30-50% detail field coverage | `browser_detail.py` |
| **P1** | R-1: Concurrent multi-strategy | +20-30% listing quality | `listing_extractor.py` |
| **P1** | R-4: Variant rows from DOM axes | Fixes FM-4 completely | `detail_extractor.py` |
| **P1** | R-5: Challenge recovery loop | Fixes FM-3 (KitchenAid etc.) | `browser_page_flow.py` |
| **P2** | R-6: LLM direct extraction | +10-15% last-resort recovery | `pipeline/core.py` |
| **P2** | R-7: Fix markdown crash | Prevents AttributeError | `browser_page_flow.py` |

---

**Report Date:** 2026-04-21
**Artifacts Analyzed:** Runs 15–20 (Dyson, Ulta, KitchenAid ×3, Zara ×3)
**Old App Reference:** `C:\Users\abhij\Downloads\pre_poc_ai_crawler\backend\app\services\`
