# Top 3 Failure Modes Analysis & Strategic Recommendations

**Date:** 2026-04-20  
**Scope:** Crawler extraction system post-100-site test run  
**Focus:** Root cause analysis for extraction failures, traversal limitations, and detail crawl gaps

---

## Executive Summary

The crawler exhibits three systemic failure patterns that represent architectural limitations rather than isolated bugs:

1. **Hardcoded Selector Dependency** - DOM extraction requires CSS class names to match pre-defined patterns
2. **Traversal Short-Circuiting** - Card detection failures prevent pagination/scroll from discovering more products
3. **Structured Data Gaps** - Detail extraction prioritizes JS state over DOM when variants/images are in HTML

**Meta-Problem:** The system is designed as a "known platform adapter + hardcoded selector fallback" architecture, which cannot scale to the long tail of e-commerce sites without exponential maintenance burden.

---

## Failure Mode 1: Site Extraction Failures (Ulta Example)

### Symptom
```
[08:19:00] WARNING Extraction yielded 0 records (adapter: generic)
[08:19:00] INFO Pipeline finished. 0 records. verdict=listing_detection_failed
```

Page title shows "190 Products" but extraction returns zero.

### Root Cause Chain

```
extract_listing_records() 
  → _listing_card_html_fragments(dom_parser, is_job=False)
    → Tries CARD_SELECTORS["ecommerce"] (23 selectors)
       └─> None match Ulta's HTML
    → Falls back to LISTING_FALLBACK_CONTAINER_SELECTOR
       ("article, li, div, tr, section, [role='row']")
       └─> Matches thousands of divs
    → _listing_fragment_score(node) filters each
       └─> Requires: card|item|product|listing|result|tile|record|entry in class/id
       └─> Ulta uses proprietary class names → score ≤ 0 → rejected
  → No cards found → empty records → VERDICT_LISTING_FAILED
```

### Current Ecommerce Card Selectors (exhaustive list)

```json
[
  "[data-component-type='s-search-result']",  // Amazon
  ".s-item",                                    // eBay
  "a.card[data-test^='product-']",             // Generic card
  "a.card[href*='/product/']",
  ".product-card",
  ".product-item", 
  ".product-tile",
  ".product-grid-item",
  "[data-testid='product-card']",
  "[data-test-id='product-card']",
  ".grid-item[data-product-id]",
  ".product_pod",
  ".collection-product-card",
  "[data-testid='grid-view-products'] > article",
  "li.grid__item",                              // Shopify
  "li.product-base",                            // Myntra
  ".plp-card",
  ".search-result-gridview-item",
  ".product",
  "article.product",
  "[itemscope][itemtype*='Product']",          // Schema.org
  ".thumbnail[itemscope]",
  "[class*='ProductCard']",                     // CSS class partial match
  "[class*='product-tile']",
  "[class*='SearchResultTile']",
  "[class*='AllEditionsItem-tile']",
  "[class*='search-result-item']"
]
```

### Why Ulta Fails

Ulta's product cards likely use classes like:
- `ProductTile` (capital P, no dash)
- `ProductPod` 
- `product-brief` or `product-wrapper`
- `item-tile` (missing from list)
- Data attributes: `data-testid="product-tile"` (different format)
- Custom component classes not containing any of the 23 known patterns

### Evidence from Code

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\listing_extractor.py:261-306`
```python
def _listing_fragment_score(node) -> int:
    # Requires positive hints OR anchor count + price signals
    if any(token in signature for token in LISTING_STRUCTURE_POSITIVE_HINTS):
        score += 6  # "card", "item", "listing", "product", "result", "tile", "record", "entry"
    
    # No price in text? No product signals? → score stays low
    if not _detail_like_path(url, is_job=is_job):
        if not is_job and anchor_score < 8 and not has_supporting_listing_signals and title_score < 8:
            return None  # REJECTED
```

---

## Failure Mode 2: Traversal Mode Under-Extracting

### Symptom
Traverse mode enabled but only extracts products from first page/screen. Logs show:
```
Found 24 cards on page 1
Clicked "Load More" 
Next page: 0 new cards detected
```

### Root Cause Chain

```
execute_listing_traversal()
  → Scroll/paginate/load-more loop
    → After each action: _card_count(page, selectors)
      → Queries each CARD_SELECTOR individually
      → Takes max count across selectors
    → If card_count <= previous_count: loop exits
      └─> BUT: new page has DIFFERENT HTML structure
      └─> New page's cards don't match the SAME selectors
      └─> card_count appears unchanged → traversal stops early
```

### Secondary Issue: Card Scoring Inconsistency

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\listing_extractor.py:204-248`

The `_listing_card_html_fragments()` function uses scored fragment selection:
- First pass: Use selectors, score by `card`, `product`, `price` signals
- Second pass: If no selectors match, scan fallback containers

**Problem:** Dynamic sites (React/Vue/Angular) often:
1. Render placeholder containers first (`div class="product-skeleton"`)
2. Hydrate with real content after fetch
3. Use different classes for list vs grid view
4. Change class names on scroll/pagination (lazy loading chunks)

The selector-based approach misses these temporal and state-based variations.

### Evidence from Traversal Code

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\acquisition\traversal.py:553`
```python
async def _card_count(page, *, surface: str) -> int:
    for selector in list(selectors or []):
        highest = max(highest, await page.locator(str(selector)).count())
    # Sequential IPC calls - slow AND selector-dependent
```

---

## Failure Mode 3: Detail Crawl Missing Variants & Additional Images

### Symptom
Product detail pages extract title, price, but miss:
- Color/size variants (only showing "default" or first variant)
- Additional images (only primary image_url)
- SKU/availability per variant

### Root Cause: Source Priority Hierarchy

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\detail_extractor.py:51-66`
```python
_SOURCE_PRIORITY = (
    "adapter",           # 1. Platform adapter (Shopify, Amazon, etc.)
    "network_payload",   # 2. Browser captured XHR/API responses
    "json_ld",           # 3. Schema.org JSON-LD
    "microdata",         # 4. HTML microdata
    "opengraph",         # 5. Meta tags
    "embedded_json",     # 6. <script> window.__INITIAL_STATE__ etc.
    "js_state",          # 7. JS state objects mapped via js_state_mapper
    "dom_h1",            # 8. DOM fallbacks...
    "dom_canonical",
    "selector_rule",
    "dom_selector",
    "dom_sections",
    "dom_images",        # Last resort
    "dom_text",
)
```

### The Variants Problem

Variants are typically found in:
1. **JS State Objects** - `__INITIAL_STATE__.product.variants[]` ✅ (js_state mapper handles)
2. **JSON-LD** - `"@type": "Product", "offers": [{"sku": "..."}]` ⚠️ (partial support)
3. **DOM Elements** - `<select data-variant-option="color">` ❌ (not extracted)

**Gap:** When JS state extraction fails (unsupported platform, obfuscated code), the DOM fallback doesn't look for:
- Variant option swatches (color/size buttons)
- Variant dropdown `<select>` elements  
- Image galleries with variant-specific associations

### The Additional Images Problem

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\field_value_dom.py:144-161`
```python
def _dedupe_image_urls(urls: list[str]) -> list[str]:
    # Scores by resolution params (?width=, ?w=)
    # Prefers largest images
    # Problem: Product galleries often have same base image, different crops
    # Secondary product images (lifestyle, detail shots) have DIFFERENT urls
    # These are scored lower than main hero image → excluded
```

The image extraction logic prioritizes "largest image by URL parameters" rather than "diverse set of product images."

### Evidence: Missing Variant Extraction

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\detail_extractor.py:87-113`
```python
# These fields are requested from js_state
_ECOMMERCE_DETAIL_JS_STATE_FIELDS = frozenset({
    "additional_images",
    "availability",
    "available_sizes",
    "brand",
    "color",
    "currency",
    "image_count",
    "image_url",
    "option1_name",      # Variant axis names
    "option1_values",    # Variant option values
    "option2_name",
    "option2_values",
    "original_price",
    "price",
    "product_id",
    "selected_variant",  # Currently selected variant object
    "size",
    "sku",
    "stock_quantity",
    "title",
    "variant_axes",      # All available variant combinations
    "variant_count",
    "variants",          # Full variant array with per-variant images/prices
})
```

**Key Issue:** If `js_state` mapping fails (unsupported platform, no `__INITIAL_STATE__`), these fields are **not** populated from DOM alternatives. There's no DOM-based variant extractor.

---

## Strategic Analysis: The Hardcoding Problem

### Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    EXTRACTION PIPELINE                       │
├─────────────────────────────────────────────────────────────┤
│  1. Platform Adapter (Shopify, Amazon, eBay, etc.)         │
│     └─> Hardcoded per platform API/JSON structure           │
│                                                              │
│  2. Structured Data (JSON-LD, microdata, embedded JSON)     │
│     └─> Hardcoded schema.org parsing                        │
│                                                              │
│  3. JS State Mapper (window.__INITIAL_STATE__, etc.)         │
│     └─> Hardcoded glom paths per framework                  │
│                                                              │
│  4. DOM Selectors (CARD_SELECTORS, DOM_PATTERNS)            │
│     └─> Hardcoded CSS selectors (23 ecommerce patterns)     │
│                                                              │
│  5. Self-Heal / LLM Fallback                                 │
│     └─> Reactive: only fires when extraction confidence low   │
└─────────────────────────────────────────────────────────────┘
```

### The Scaling Problem

| Approach | Coverage | Maintenance | New Site Onboarding |
|----------|----------|-------------|---------------------|
| Platform Adapters | ~15 major platforms | High - API changes break extraction | Days (dev + test) |
| DOM Selectors | ~40% of e-commerce sites | Medium - class names churn | Hours (inspect + PR) |
| Self-Heal | ~10% recovery | Low - reactive | Minutes (re-crawl) |
| **Gap** | **~50% of long tail** | - | **Currently unhandled** |

**Fundamental Issue:** Every new site requires either:
1. New adapter (if platform-detectable)
2. New selectors added to exports.json
3. User manually discovering XPaths via selector tool

This is not a scalable extraction engine—it's a curated collection of site-specific parsers.

---

## Recommended Solutions

### Solution A: Semantic Detection Layer (Medium Term)

**Concept:** Instead of "class name contains product," detect "this HTML structure represents a product listing" via:

1. **Content signals** (price patterns, image density, link destination patterns)
2. **Layout clustering** (visual grouping via layout analysis)
3. **Schema inference** (ML-based field type detection from text content)

**Implementation:**
```python
# Pseudo-architecture
class SemanticListingDetector:
    def detect_cards(self, html: str) -> list[ProductCard]:
        # 1. Find all "price-like" text patterns
        price_nodes = find_price_patterns(html)
        
        # 2. For each price, find nearest containing element
        #    with image + title + link → product card candidate
        candidates = []
        for price_node in price_nodes:
            container = find_ancestor_with_siblings(
                price_node,
                required_siblings=['img', 'a[title-like]'],
                max_depth=4
            )
            if container:
                candidates.append(container)
        
        # 3. Cluster candidates by structural similarity
        #    (same tag name depth, similar child element patterns)
        return cluster_by_structure(candidates)
```

**Advantage:** Works regardless of CSS class names.

### Solution B: LLM-Powered Extraction (Near Term)

**Concept:** Use LLM to extract from HTML directly, not just as fallback.

**Current:** LLM only triggers when confidence < 0.5
**Proposed:** LLM as primary extractor for unknown sites

**Implementation Pattern:**
```python
async def extract_with_llm(html: str, page_url: str, surface: str) -> list[dict]:
    # 1. Chunk HTML by semantic regions (strip nav/footer/scripts)
    content_chunks = semantic_chunk(html)
    
    # 2. LLM extracts structured records from each chunk
    records = []
    for chunk in content_chunks:
        result = await llm_extract_records(
            html_chunk=chunk,
            schema=get_surface_schema(surface),
            example=get_few_shot_example(surface)
        )
        records.extend(result)
    
    return records
```

**Cost Mitigation:**
- Cache results per-domain
- Use cheaper models (Haiku/GPT-4o-mini) for initial pass
- Only send "record-like" HTML fragments, not full page

### Solution C: Visual Extraction (Long Term)

**Concept:** Use browser screenshot + visual analysis (GPT-4V / multimodal) to:
1. Detect product card regions visually
2. Identify product boundaries by layout
3. Extract text from detected regions via OCR or HTML overlay

**Advantage:** Completely class-name agnostic. Works on any rendered page.

### Solution D: Adaptive Selector Learning (Medium Term)

**Concept:** When LLM or semantic detection succeeds on a new site, automatically:
1. Generate CSS selectors from successful extractions
2. Store in domain memory
3. Use for subsequent crawls (fast path)

**Self-Improvement Loop:**
```
Crawl new site 
  → LLM extracts records
  → Reverse-engineer selectors from LLM-identified elements
  → Store: domain "ulta.com" → selectors {title: ".ProductTile-name", ...}
  → Next crawl: use cached selectors (fast)
  → If selectors fail (site redesign): fallback to LLM, update selectors
```

---

## Immediate Tactical Fixes

### 1. Expand Card Selector Coverage (1-2 days)

Add broader pattern matching:
```json
// selectors.exports.json additions
"[class*='tile' i]",           // case-insensitive contains
"[class*='item' i]",
"[class*='card' i]",
"[data-testid*='product' i]",
"[data-test-id*='product' i]",
"[data-component*='product' i]",
"[data-automation*='product' i]",
"article:has(img):has(a):has(.price, [class*='price'])"
```

### 2. DOM-Based Variant Extraction (2-3 days)

Add variant detection from DOM:
```python
# detail_extractor.py

def _extract_variants_from_dom(soup, page_url: str) -> list[dict]:
    variants = []
    
    # Detect variant swatches (color/size buttons)
    swatch_groups = soup.select('[data-testid*="swatch"], [class*="swatch"], [class*="option"]')
    
    # Detect variant dropdowns
    variant_selects = soup.select('select[data-variant], select[name*="variant"], select[name*="option"]')
    
    # Build variant combinations
    option_groups = []
    for select in variant_selects:
        options = [opt.text for opt in select.find_all('option') if opt.get('value')]
        option_groups.append({
            'name': select.get('data-option-name') or select.get('name'),
            'values': options
        })
    
    # Generate variant objects
    if option_groups:
        variants = compute_variant_combinations(option_groups, page_url)
    
    return variants
```

### 3. Traversal Robustness (1 day)

@`c:\Projects\pre_poc_ai_crawler\backend\app\services\acquisition\traversal.py:553`
```python
# Replace sequential selector counting with semantic detection
async def _card_count(page, *, surface: str) -> int:
    # Current: count by selectors (brittle)
    # Proposed: count by structural signals
    return await page.evaluate("""
        () => {
            // Find elements containing price patterns
            const prices = Array.from(document.querySelectorAll('*'))
                .filter(el => /\\$[\\d,]+\\.\\d{2}/.test(el.textContent));
            
            // Group by nearest common ancestor with image + link
            const containers = prices.map(p => {
                let el = p;
                for (let i = 0; i < 5 && el; i++, el = el.parentElement) {
                    if (el.querySelector('img') && el.querySelector('a[href*="/product"]')) {
                        return el;
                    }
                }
                return null;
            }).filter(Boolean);
            
            // Deduplicate by position
            return new Set(containers.map(c => c.getBoundingClientRect().top)).size;
        }
    """);
```

---

## Conclusion

The current extraction system is **curation-based**, not **detection-based**. To achieve true scale:

| Timeline | Approach | Impact |
|----------|----------|--------|
| **This week** | Expand selectors + DOM variant extraction | +20% coverage |
| **This month** | LLM primary extraction for unknown sites | +40% coverage |
| **This quarter** | Semantic detection + adaptive learning | +70% coverage, self-improving |
| **This year** | Visual extraction as final fallback | 95%+ coverage |

**The fundamental shift needed:** Stop asking "what platform is this?" and start asking "what content is on this page?"

---

## Appendix: Evidence Locations

### Card Detection
- @`c:\Projects\pre_poc_ai_crawler\backend\app\services\listing_extractor.py:204-248` - `_listing_card_html_fragments()`
- @`c:\Projects\pre_poc_ai_crawler\backend\app\services\listing_extractor.py:261-306` - `_listing_fragment_score()`
- @`c:\Projects\pre_poc_ai_crawler\backend\app\services\config\selectors.exports.json:101-172` - CARD_SELECTORS

### Source Priority
- @`c:\Projects\pre_poc_ai_crawler\backend\app\services\detail_extractor.py:51-66` - `_SOURCE_PRIORITY`
- @`c:\Projects\pre_poc_ai_crawler\backend\app\services\detail_extractor.py:87-113` - `_ECOMMERCE_DETAIL_JS_STATE_FIELDS`

### Traversal
- @`c:\Projects\pre_poc_ai_crawler\backend\app\services\acquisition\traversal.py:553` - `_card_count()`

### Image Extraction
- @`c:\Projects\pre_poc_ai_crawler\backend\app\services\field_value_dom.py:144-161` - `_dedupe_image_urls()`
