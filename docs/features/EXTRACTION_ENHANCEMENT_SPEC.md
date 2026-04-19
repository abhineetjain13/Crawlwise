# CrawlerAI Extraction & Enrichment Enhancement Specification

**Version:** 1.1 (Revised)  
**Date:** April 2026  
**Status:** Implementation Ready  
**Target Surfaces:** Ecommerce Detail, Job Detail  
**Estimated Impact:** 30-50% improvement in extraction completeness for complex sites

---

## Executive Summary

This specification defines targeted enhancements to CrawlerAI's extraction pipeline, building on **existing capabilities** to achieve a **State-First, API-Ghost, Self-Healing** architecture. The core insight: modern ecommerce (Next.js, Shopify) and job boards (Workday, Greenhouse, Lever) embed ground-truth data in JavaScript hydration objects and background XHR payloads *before* rendering to DOM.

### What's Already Built ✅
- ✅ **`__NEXT_DATA__` extraction** via `extract_next_data()` in `source_parsers.py`
- ✅ **Network interception** via Playwright `page.on("response")` in `browser_client.py`
- ✅ **Hydrated state extraction** for React/Apollo apps
- ✅ **Accordion expansion** via `expand_all_interactive_elements()` in `browser_client.py`
- ✅ **Multi-tier extraction hierarchy** (contract → adapter → JSON-LD → network → DOM)

### What Needs Enhancement 🔧
- 🔧 **Expand JS state targets** beyond `__NEXT_DATA__` (add `__NUXT__`, `__APOLLO_STATE__`, etc.)
- 🔧 **Platform-specific XHR mappers** for Workday, Greenhouse, Lever API schemas
- 🔧 **Surface-aware field aliases** to eliminate cross-surface schema pollution
- 🔧 **Confidence scoring + LLM selector synthesis** for self-healing extraction
- 🔧 **Domain memory caching** for synthesized selectors

---

## Current Architecture Analysis

### Existing Strengths ✅
- ✅ **JS State Extraction:** `extract_next_data()` and `extract_hydrated_states()` in `source_parsers.py`
- ✅ **Network Interception:** Playwright `page.on("response")` captures XHR/fetch in `browser_client.py`
- ✅ **Interactive Element Expansion:** `expand_all_interactive_elements()` clicks buttons/accordions
- ✅ **Multi-tier extraction hierarchy:** contract → adapter → JSON-LD → dataLayer → network → DOM
- ✅ **Source ranking system:** `candidate_source_rank()` with priority-based selection
- ✅ **Field decision engine:** `FieldDecisionEngine` with rejection logic
- ✅ **BeautifulSoup + lxml:** Already using fast HTML parsing (no need for Selectolax)

### Enhancement Opportunities 🔧
- 🔧 **Limited JS state targets** — only `__NEXT_DATA__`, missing `__NUXT__`, `__APOLLO_STATE__`, etc.
- 🔧 **No platform-specific XHR mappers** — raw payloads not mapped to canonical schema
- 🔧 **Surface-agnostic field aliases** — causes job/ecommerce schema pollution
- 🔧 **No confidence scoring** — can't detect extraction failures
- 🔧 **No self-healing selector synthesis** — brittle on site redesigns
- 🔧 **No domain memory** — can't cache learned selectors  

---

## Recommended Tools Analysis

### Tools from Recommendations Document

#### 1. **Selectolax** (Fast HTML Parser)
**Status:** ❌ Not Needed  
**Reason:** Project already uses BeautifulSoup + lxml backend, which is nearly as fast. Switching would require rewriting existing parsers with minimal performance gain.

#### 2. **Parsel** (XPath/CSS Selector Library)
**Status:** ❌ Not Needed  
**Reason:** BeautifulSoup's `.select()` and lxml's XPath support already provide this functionality. No benefit to adding another dependency.

#### 3. **JMESPath** (JSON Query Language)
**Status:** ✅ **RECOMMENDED**  
**Reason:** Perfect for querying deeply nested XHR payloads from Workday, Greenhouse, Lever APIs. Cleaner than manual dict traversal.  
**Usage:** Map XHR payloads to canonical schema (e.g., `"departments[0].name"` → `department`)

#### 4. **glom** (Declarative Data Transformation)
**Status:** ✅ **RECOMMENDED**  
**Reason:** Ideal for multi-path fallback in JS state mapping (e.g., try `props.pageProps.product.title` → `props.pageProps.initialData.name` → `query.product.title`).  
**Usage:** Replace nested if/else chains in JS state mappers with declarative specs.

### Recommendation
Add to `pyproject.toml`:
```toml
dependencies = [
  # ... existing deps ...
  "jmespath>=1.0.1",
  "glom>=23.5.0",
]
```

---

## Enhancement Architecture

### Phase 1: Expand JS State Coverage (Week 1-2)

**Current State:** `extract_next_data()` only extracts `__NEXT_DATA__` from `<script id="__NEXT_DATA__">`.

**Enhancement:** Expand to cover all major JS hydration patterns.

#### 1.1 Expand JS State Targets
**File:** `backend/app/services/extract/source_parsers.py` (MODIFY)

**Current Code:**
```python
def extract_next_data(soup: BeautifulSoup) -> dict | None:
    node = soup.select_one("script#__NEXT_DATA__")
    if node and node.string:
        parsed = parse_json_fragment(node.string)
        return parsed if isinstance(parsed, dict) else None
    return None
```

**Enhanced Code:**
```python
# Add to HYDRATED_STATE_PATTERNS in extraction_rules.py
ADDITIONAL_JS_STATE_PATTERNS = [
    "__NUXT__",                   # Nuxt.js
    "__APOLLO_STATE__",           # Apollo GraphQL
    "window.__PRELOADED_STATE__", # Redux SSR
    "window.APP_STATE",           # Generic app state
    "window.__INITIAL_STATE__",   # Generic initial state
]

def extract_js_state_objects(soup: BeautifulSoup) -> dict[str, Any]:
    """
    Extract all JS state objects from script tags.
    Returns: {"__NEXT_DATA__": {...}, "__NUXT__": {...}, ...}
    """
    state_objects = {}
    
    # Extract __NEXT_DATA__ (existing logic)
    next_data = extract_next_data(soup)
    if next_data:
        state_objects["__NEXT_DATA__"] = next_data
    
    # Extract __NUXT__ from <script>window.__NUXT__={...}</script>
    for script in soup.find_all("script"):
        if not script.string:
            continue
        text = script.string
        
        for pattern in ADDITIONAL_JS_STATE_PATTERNS:
            # Match: window.__NUXT__ = {...} or __NUXT__ = {...}
            match = re.search(
                rf"(?:window\.)?{re.escape(pattern)}\s*=\s*",
                text
            )
            if match:
                fragment = extract_balanced_json_fragment(text[match.end():])
                if fragment:
                    parsed = parse_json_fragment(fragment)
                    if parsed:
                        state_objects[pattern] = parsed
    
    return state_objects
```

**Integration:** Update `parse_page_sources()` to call `extract_js_state_objects()` and merge results into `next_data`.

#### 1.2 Surface-Aware JS State Mapper (NEW)
**File:** `backend/app/services/extract/js_state_mapper.py` (NEW)

```python
"""Map JS state trees to canonical schema using glom path specs."""

from glom import glom, Coalesce

# Next.js product page spec (Shopify, Vercel commerce)
NEXTDATA_ECOMMERCE_SPEC = {
    "title": Coalesce(
        "props.pageProps.product.title",
        "props.pageProps.initialData.name",
        "query.product.title",
        default=None
    ),
    "price": Coalesce(
        "props.pageProps.product.priceRange.minVariantPrice.amount",
        "props.pageProps.price",
        default=None
    ),
    "brand": Coalesce(
        "props.pageProps.product.vendor",
        "props.pageProps.brand",
        default=None
    ),
    "specifications": Coalesce(
        "props.pageProps.product.metafields",
        "props.pageProps.specifications",
        default={}
    ),
}

# Nuxt.js ecommerce spec
NUXT_ECOMMERCE_SPEC = {
    "title": Coalesce("data.product.name", "state.product.title", default=None),
    "price": Coalesce("data.product.price", "state.product.price", default=None),
    "brand": Coalesce("data.product.brand", "state.product.vendor", default=None),
}

def map_js_state_to_schema(
    js_state_objects: dict[str, Any],
    surface: str
) -> dict[str, Any]:
    """
    Map JS state to canonical fields using surface-specific glom specs.
    
    Args:
        js_state_objects: {"__NEXT_DATA__": {...}, "__NUXT__": {...}}
        surface: "ecommerce_detail", "job_detail", etc.
    
    Returns: Mapped canonical fields
    """
    if "ecommerce" not in surface.lower():
        return {}
    
    mapped = {}
    
    # Try __NEXT_DATA__ first
    if "__NEXT_DATA__" in js_state_objects:
        try:
            next_mapped = glom(js_state_objects["__NEXT_DATA__"], NEXTDATA_ECOMMERCE_SPEC)
            mapped.update({k: v for k, v in next_mapped.items() if v not in (None, "", [], {})})
        except Exception as e:
            logger.debug(f"Next.js state mapping failed: {e}")
    
    # Try __NUXT__ if Next.js didn't yield results
    if not mapped and "__NUXT__" in js_state_objects:
        try:
            nuxt_mapped = glom(js_state_objects["__NUXT__"], NUXT_ECOMMERCE_SPEC)
            mapped.update({k: v for k, v in nuxt_mapped.items() if v not in (None, "", [], {})})
        except Exception as e:
            logger.debug(f"Nuxt state mapping failed: {e}")
    
    # Normalize Shopify cent-format prices
    if "price" in mapped and mapped["price"]:
        mapped["price"] = normalize_shopify_price(mapped["price"])
    
    return mapped

def normalize_shopify_price(raw: Any) -> float:
    """Fix Shopify cent-format bug: "12999" → 129.99"""
    val = float(str(raw).replace(",", "").strip("$€£¥"))
    if val > 1000 and "." not in str(raw):
        val = val / 100
    return round(val, 2)
```

**Integration:** Call from `_collect_structured_state_candidates()` in `service.py`.

#### 1.3 Fix: Surface-Partitioned Field Aliases
**File:** `backend/app/services/config/field_mappings.py` (MODIFY)

**Current Bug:** Flat `FIELD_ALIASES` dict causes cross-surface pollution.

**Fix:**
```python
# BEFORE (causes pollution)
FIELD_ALIASES = {
    "type": ["type", "category", "job_type"],  # ← ambiguous!
    ...
}

# AFTER (surface-partitioned)
ECOMMERCE_FIELD_ALIASES = {
    "category": ["category", "type", "product_type"],
    "brand": ["brand", "vendor", "manufacturer"],
    ...
}

JOB_FIELD_ALIASES = {
    "job_type": ["job_type", "type", "employment_type"],
    "company": ["company", "employer", "organization"],
    ...
}

def get_surface_field_aliases(surface: str) -> dict[str, list[str]]:
    """Return field aliases filtered by surface."""
    if "ecommerce" in surface.lower():
        return ECOMMERCE_FIELD_ALIASES
    elif "job" in surface.lower():
        return JOB_FIELD_ALIASES
    return {}
```

**Integration:** Update `_append_source_candidates()` in `dom_extraction.py` to use `get_surface_field_aliases(surface)`.

---

### Phase 2: Platform-Specific XHR Mapping (Week 3-4)

**Current State:** Network interception captures raw XHR payloads but doesn't map them to canonical schema.

**Enhancement:** Add platform-specific mappers using JMESPath for deep JSON traversal.

#### 2.1 Platform Fingerprinter (NEW)
**File:** `backend/app/services/acquisition/platform_detector.py` (NEW)

```python
"""Detect ATS/ecommerce platform from URL and HTML fingerprints."""

PLATFORM_FINGERPRINTS = {
    "workday": [r"myworkdayjobs\.com", r"workday\.com"],
    "greenhouse": [r"boards\.greenhouse\.io", r"greenhouse\.io/embed"],
    "lever": [r"jobs\.lever\.co"],
    "taleo": [r"taleo\.net", r"tbe\.taleo\.net"],
    "shopify": [r"cdn\.shopify\.com", r"Shopify\.theme"],
}

def detect_platform(url: str, html: str) -> str | None:
    """Fingerprint platform from URL and HTML."""
    for platform, patterns in PLATFORM_FINGERPRINTS.items():
        if any(re.search(p, url, re.I) for p in patterns):
            return platform
        if any(re.search(p, html, re.I) for p in patterns):
            return platform
    return None
```

#### 2.2 XHR Payload Mapper (NEW)
**File:** `backend/app/services/extract/xhr_payload_mapper.py` (NEW)

```python
"""Map XHR payloads to canonical schema using JMESPath."""

import jmespath

# Greenhouse job detail spec
GREENHOUSE_SPEC = {
    "title": "title",
    "department": "departments[0].name",
    "location": "location.name",
    "salary_min": "pay_input_ranges[0].min_cents",
    "salary_max": "pay_input_ranges[0].max_cents",
    "description": "content",
}

# Workday job detail spec
WORKDAY_SPEC = {
    "title": "title",
    "company": "bulletFields[?type=='company'].value | [0]",
    "location": "bulletFields[?type=='location'].value | [0]",
    "job_type": "bulletFields[?type=='timeType'].value | [0]",
    "description": "jobDescription",
}

PLATFORM_SPECS = {
    "greenhouse": GREENHOUSE_SPEC,
    "workday": WORKDAY_SPEC,
}

def map_xhr_payload(
    payload: dict,
    platform: str
) -> dict[str, Any]:
    """Map XHR payload to canonical fields using JMESPath."""
    spec = PLATFORM_SPECS.get(platform, {})
    return {
        field: jmespath.search(path, payload)
        for field, path in spec.items()
        if jmespath.search(path, payload) not in (None, "", [], {})
    }
```

**Integration:** 
- Call `detect_platform()` in `browser_client.py` after page load
- Store platform in acquisition result
- Call `map_xhr_payload()` in `_collect_network_payload_candidates()` in `service.py`

---

### Phase 3: Enhanced Accordion Expansion (Week 5)

**Current State:** `expand_all_interactive_elements()` in `browser_client.py` clicks buttons/accordions generically.

**Enhancement:** Add surface-aware keyword targeting for specifications/requirements content.

#### 3.1 Surface-Aware Expansion Keywords
**File:** `backend/app/services/acquisition/browser_client.py` (MODIFY)

```python
# Add to browser_client.py
EXPAND_KEYWORDS = {
    "ecommerce": [
        "specifications", "details", "description",
        "view more", "read more", "show more",
        "dimensions", "tech specs", "compatibility",
    ],
    "job": [
        "full description", "requirements", "qualifications",
        "compensation", "salary", "benefits",
        "show all", "see more",
    ],
}

async def expand_all_interactive_elements(
    page,
    *,
    surface: str = "",  # Add surface parameter
    checkpoint=None
) -> dict:
    """
    Expand interactive elements with surface-aware keyword filtering.
    """
    keywords = EXPAND_KEYWORDS.get(
        "ecommerce" if "ecommerce" in surface.lower() else "job",
        []
    )
    
    # Existing expansion logic, but filter by keywords
    # ... (keep existing code, add keyword matching)
```

**Integration:** Pass `surface` parameter from `fetch_rendered_html()` call.

---

### Phase 4: Self-Healing Extraction (Week 6-8)

#### 4.1 Extraction Confidence Scorer
**File:** `backend/app/services/extract/confidence_scorer.py` (NEW)

```python
"""Score extraction results to gate LLM fallback."""

def score_extraction(result: dict, surface: str) -> float:
    """
    Score extraction completeness (0.0-1.0).
    Below threshold triggers LLM selector synthesis.
    """
    if "ecommerce" in surface.lower():
        return score_ecommerce(result)
    elif "job" in surface.lower():
        return score_job(result)
    return 0.0

def score_ecommerce(result: dict) -> float:
    score = 0.0
    if result.get("title"):        score += 0.25
    if result.get("price"):        score += 0.25
    if result.get("brand"):        score += 0.10
    if result.get("sku"):          score += 0.15
    if result.get("description"):  score += 0.15
    if result.get("image_url"):    score += 0.10
    
    # Penalty: suspiciously short or nav text
    if len(result.get("title", "")) < 3:
        score -= 0.20
    
    return min(1.0, max(0.0, score))

def score_job(result: dict) -> float:
    score = 0.0
    if result.get("title"):       score += 0.25
    if result.get("company"):     score += 0.25
    if result.get("location"):    score += 0.15
    if result.get("description"): score += 0.20
    if result.get("salary"):      score += 0.15
    
    return min(1.0, max(0.0, score))

HEAL_THRESHOLD = 0.55  # Below this → trigger LLM repair
```

#### 4.2 LLM Selector Synthesizer
**File:** `backend/app/services/extract/llm_selector_synthesizer.py` (NEW)

```python
"""LLM-powered selector synthesis for self-healing extraction."""

SELECTOR_SYNTHESIS_PROMPT = """
You are analyzing the HTML structure of a {surface} page.
Return ONLY a JSON object mapping these canonical fields to 
CSS selectors. Return null for fields not present.

Fields: {field_list}

HTML skeleton (tags + aria, no text content):
{html_skeleton}

Respond ONLY with valid JSON. No explanation.
"""

async def synthesize_selectors(
    html: str,
    surface: str,
    domain: str,
    llm_service
) -> dict[str, str]:
    """
    Use LLM to generate CSS selectors for failed extraction.
    Cache result in domain_memory to avoid repeat LLM calls.
    """
    # Minify HTML to skeleton (tags + attributes only, ~3-5KB)
    skeleton = minify_to_skeleton(html)
    
    field_list = get_canonical_fields(surface)
    
    response = await llm_service.complete(
        prompt=SELECTOR_SYNTHESIS_PROMPT.format(
            surface=surface,
            field_list=", ".join(field_list),
            html_skeleton=skeleton
        ),
        max_tokens=800,
        temperature=0.0
    )
    
    selectors = json.loads(response)
    
    # Cache in domain_memory
    await domain_memory.upsert_selectors(domain, selectors)
    
    return selectors

def minify_to_skeleton(html: str) -> str:
    """
    Strip text content, keep tags + aria/data attributes.
    Reduces HTML from ~500KB to ~5KB.
    """
    soup = BeautifulSoup(html, "html.parser")
    
    for tag in soup.find_all(True):
        # Keep only structural and aria attributes
        keep_attrs = {
            k: v for k, v in tag.attrs.items()
            if k.startswith(("aria-", "data-", "role", "class", "id"))
        }
        tag.attrs = keep_attrs
        
        # Remove text content
        if tag.string:
            tag.string = ""
    
    return str(soup)[:5000]  # Cap at 5KB
```

**Integration:** `backend/app/services/extract/service.py`
- After `_finalize_candidates()`, score result
- If score < `HEAL_THRESHOLD`, call `synthesize_selectors()`
- Re-run extraction with synthesized selectors
- Cache selectors in `domain_memory` table

#### 4.3 Domain Memory Schema
**File:** `backend/alembic/versions/20260420_0012_domain_memory.py` (NEW)

```python
"""Add domain_memory table for selector caching."""

def upgrade():
    op.create_table(
        'domain_memory',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('domain', sa.String(255), nullable=False, index=True),
        sa.Column('surface', sa.String(40), nullable=False),
        sa.Column('platform', sa.String(40), nullable=True),
        sa.Column('selectors', JSONB, default=dict),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('domain', 'surface', name='uq_domain_surface')
    )
```

---

## Implementation Priority Matrix

### Quick Wins (Week 1)
- ✅ Surface-partition `FIELD_ALIASES` (fixes schema pollution)
- ✅ Shopify cent-format price fix
- ✅ Add `discovered_data` field to `CrawlRecord` model
- ✅ Fix `"auto"` mode browser forcing for known ATS platforms

### Core Build (Weeks 2-4)
- ✅ JS state harvester + mapper with glom specs
- ✅ XHR interception + platform fingerprinter
- ✅ AOM expander
- ✅ Confidence scorer
- ✅ Platform specs: Greenhouse, Lever, Shopify

### Deep Work (Weeks 5-8)
- ✅ LLM selector synthesis + cache layer
- ✅ Semantic normalization for complex fields
- ✅ Workday / Taleo XHR specs
- ✅ Structural change detection (cache invalidation)
- ✅ End-to-end confidence telemetry dashboard

---

## Acceptance Criteria

### Phase 1: JS State Interception
- [ ] `harvest_js_state()` returns non-null for ≥80% of test Next.js pages
- [ ] `grep -r "__NEXT_DATA__\|APP_STATE" backend/app/services/extract/` returns >0 hits
- [ ] JS-extracted price fields pass Shopify cent-format guard
- [ ] `specifications` field on ecommerce extractions contains no job-surface keys
- [ ] DOM fallback NOT triggered when JS state successfully harvested

### Phase 2: XHR Interception
- [ ] Greenhouse job detail extraction succeeds via XHR payload (no DOM parsing)
- [ ] Workday job detail extraction succeeds via XHR payload
- [ ] Platform fingerprinter correctly identifies Shopify, Greenhouse, Lever from test URLs
- [ ] `network_intercept` source appears in extraction audit for ATS platforms

### Phase 3: AOM Expansion
- [ ] Hidden specification accordion content extracted on 3 test ecommerce pages
- [ ] Hidden job requirements tab content extracted on 3 test job pages
- [ ] AOM expander runs after `page.goto()` but before HTML snapshot

### Phase 4: Self-Healing
- [ ] Confidence scorer returns <0.55 for intentionally broken test page
- [ ] LLM selector synthesis triggered and cached in `domain_memory`
- [ ] Re-extraction with synthesized selectors improves score to >0.70
- [ ] Second visit to same domain uses cached selectors (no LLM call)

---

## Risk Mitigation

### Performance Impact
**Risk:** JS state harvesting + XHR interception adds latency.  
**Mitigation:** 
- JS state extraction is <50ms (single `page.evaluate()`)
- XHR interception is passive (no blocking)
- AOM expansion limited to 5 nodes max per page

### LLM Cost Explosion
**Risk:** LLM selector synthesis on every page.  
**Mitigation:**
- Gated by confidence threshold (only on failures)
- Cached per domain (one-time cost)
- HTML skeleton minification reduces token count 100x

### Schema Pollution Regression
**Risk:** Surface-partitioned aliases break existing extractions.  
**Mitigation:**
- Backward compatibility: fall back to flat aliases if surface unknown
- Comprehensive test suite for ecommerce/job cross-contamination

---

## Testing Strategy

### Unit Tests
- `test_js_state_harvester.py`: Mock Playwright page with `__NEXT_DATA__`
- `test_xhr_mapper.py`: JMESPath specs against Greenhouse/Workday fixtures
- `test_confidence_scorer.py`: Score calculation for various extraction results
- `test_surface_aliases.py`: Verify no cross-surface field leakage

### Integration Tests
- `test_nextjs_ecommerce_extraction.py`: Full pipeline on Shopify test page
- `test_greenhouse_job_extraction.py`: Full pipeline on Greenhouse test page
- `test_aom_expansion.py`: Verify accordion content extracted

### Regression Tests
- Existing test suite must pass (no breaking changes)
- Add fixtures for known problematic sites (Workday, complex Shopify)

---

## Monitoring & Telemetry

### New Metrics
- `extraction.js_state_hit_rate`: % of pages with JS state harvested
- `extraction.xhr_intercept_hit_rate`: % of pages with XHR payloads captured
- `extraction.aom_expansion_count`: # of nodes expanded per page
- `extraction.confidence_score_avg`: Average confidence score by surface
- `extraction.llm_synthesis_trigger_rate`: % of extractions requiring LLM fallback
- `extraction.llm_synthesis_cache_hit_rate`: % of domains using cached selectors

### Dashboards
- **Extraction Quality Dashboard:** Confidence scores over time by surface
- **Source Contribution Dashboard:** % of fields extracted by source tier
- **LLM Cost Dashboard:** LLM synthesis calls and token usage

---

## Rollout Plan

### Week 1: Foundation
- Implement surface-partitioned field aliases
- Add `discovered_data` field to schema
- Fix Shopify price normalization

### Week 2-3: JS State + XHR
- Implement JS state harvester + mapper
- Implement XHR interceptor + platform detector
- Deploy to staging with 10% traffic

### Week 4-5: AOM + Confidence
- Implement AOM expander
- Implement confidence scorer
- Deploy to staging with 50% traffic

### Week 6-8: Self-Healing
- Implement LLM selector synthesizer
- Implement domain memory caching
- Deploy to production with gradual rollout (10% → 50% → 100%)

---

## Success Metrics

### Target Improvements (3 months post-deployment)
- **Extraction Completeness:** +40% for complex ecommerce sites (Shopify, custom Next.js)
- **Job Board Coverage:** +60% for ATS platforms (Workday, Greenhouse, Lever)
- **Hidden Content Extraction:** +80% for accordion/tab specifications
- **Schema Pollution:** -100% (zero job fields on ecommerce pages)
- **LLM Cost:** <$0.02 per domain (amortized over repeat visits)

---

## Appendix: Code Integration Points

### Modified Files
- `backend/app/services/extract/source_parsers.py`: Expand JS state extraction
- `backend/app/services/config/field_mappings.py`: Surface-partition aliases
- `backend/app/services/acquisition/browser_client.py`: Surface-aware expansion
- `backend/app/models/crawl.py`: Add `discovered_data` field (already exists ✅)

### New Files
- `backend/app/services/extract/js_state_mapper.py`
- `backend/app/services/acquisition/platform_detector.py`
- `backend/app/services/extract/xhr_payload_mapper.py`
- `backend/app/services/extract/confidence_scorer.py`
- `backend/app/services/extract/llm_selector_synthesizer.py`
- `backend/alembic/versions/20260420_0012_domain_memory.py`

### New Dependencies
Add to `backend/pyproject.toml`:
```toml
dependencies = [
  # ... existing deps ...
  "jmespath>=1.0.1",
  "glom>=23.5.0",
]
```

---

**End of Specification**
