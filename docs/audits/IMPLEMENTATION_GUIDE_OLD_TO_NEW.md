# Implementation Guide: Porting Winning Features from Old App

## Executive Summary

This document provides **concrete code evidence** for implementing only the genuinely superior features from the old app (`C:\Users\abhij\Downloads\pre_poc_ai_crawler`) into the current app.

---

## Feature 1: Semantic Accordion Expansion (CRITICAL)

### Why Current App Fails

**Current App** (`browser_runtime.py:111-124`):
```python
_DETAIL_EXPAND_SELECTORS = (
    "button, summary, details summary, "
    "[role='button'], [aria-expanded='false'], "
    "[data-testid*='expand'], [data-testid*='accordion']"
)

_DETAIL_EXPAND_KEYWORDS = {
    "ecommerce": ("about", "compatibility", "description", ...),
    "job": ("benefits", "compensation", ...)
}
```

**Problems**:
1. No field-aware expansion
2. No blocked token filtering (clicks "add to cart")
3. No ARIA attribute checking
4. Runs only when `readiness_probe` indicates missing content (often skips)

### Old App Solution

**File**: `semantic_browser_helpers.py:8-101`

```python
_SAFE_EXPAND_SELECTORS = [
    "summary",
    "details > summary",
    "[aria-expanded='false']",
    "button[aria-controls]",
    "[role='button'][aria-controls]",
    "[role='tab'][aria-controls]",
    "button",
    "[role='button']",
    "a",
]

_SAFE_EXPAND_TOKENS = (
    "read more", "show more", "view more",
    "details", "description", "specifications", "specs",
    "product details", "size", "fit", "materials",
    "fabric", "ingredients", "care", "shipping", "returns",
)

_BLOCKED_TOKENS = (
    "add to cart", "buy now", "checkout",
    "login", "sign in", "subscribe",
    "wishlist", "add to bag", "shopping bag",
)

async def safe_expand_semantic_content(
    page: Any,
    emit: Callable[[str], None],
    *,
    max_actions: int = 6,
    max_per_selector: int = 4,
    requested_fields: list[str] | None = None,
) -> int:
    """Expand accordions and hidden content in the browser.
    
    Key innovations:
    1. Field-aware: derives tokens from requested_fields
    2. ARIA-aware: checks aria-expanded="false" attribute
    3. Blocked tokens: avoids commerce action buttons
    4. Multi-strategy: tries multiple selector types
    """
    # Derive tokens from requested fields - CRITICAL for field extraction
    requested_tokens = {
        token.lower()
        for field in (requested_fields or [])
        for token in normalize_requested_field(field).replace(".", "_").split("_")
        if token and len(token) > 2
    }
    
    actions = 0
    for selector in _SAFE_EXPAND_SELECTORS:
        if actions >= max_actions:
            break
        
        try:
            elements = await page.query_selector_all(selector)
        except Exception:
            continue
            
        for element in elements[:max_per_selector]:
            if actions >= max_actions:
                break
                
            try:
                # Get comprehensive element text
                text = " ".join((await element.inner_text()).split()).strip().lower()
                aria_expanded = str(await element.get_attribute("aria-expanded") or "").strip().lower()
                aria_label = " ".join(((await element.get_attribute("aria-label")) or "").split()).strip().lower()
                title = " ".join(((await element.get_attribute("title")) or "").split()).strip().lower()
                
                probe = " ".join(part for part in (text, aria_label, title) if part).strip()
                
                # BLOCKED TOKENS - Don't click commerce buttons
                if any(token in probe for token in _BLOCKED_TOKENS):
                    continue
                
                # CHECK IF EXPANDABLE - ARIA-aware
                looks_expandable = (
                    selector in {"summary", "details > summary", "[aria-expanded='false']"}
                    or aria_expanded == "false"  # Critical: checks actual state
                    or any(token in probe for token in _SAFE_EXPAND_TOKENS)
                    or any(token in probe for token in requested_tokens)  # Field-aware
                )
                
                if not looks_expandable:
                    continue
                if not await element.is_visible():
                    continue
                    
                # Click to expand
                await element.scroll_into_view_if_needed()
                await element.click(timeout=1500)
                await page.wait_for_timeout(500)
                
                actions += 1
                emit(f"Semantic expand: revealed content via '{(probe or selector)[:48]}'")
            except Exception:
                continue
    
    return actions
```

### Integration Point

**File to modify**: `backend/app/services/acquisition/browser_runtime.py:679-693`

```python
async def expand_detail_content_if_needed(
    page: Any,
    *,
    surface: str,
    readiness_probe: dict[str, object],
) -> dict[str, object]:
    # CURRENT: Only expands if readiness probe indicates missing content
    # PROBLEM: Probe often doesn't detect accordion content as missing
    
    # NEW: Always run semantic expansion for detail pages
    if "detail" in str(surface or "").lower():
        from .semantic_expansion import safe_expand_semantic_content
        
        expansions = await safe_expand_semantic_content(
            page,
            lambda msg: logger.info(msg),
            max_actions=crawler_runtime_settings.accordion_expand_max,
            requested_fields=getattr(surface_config, "fields", None),  # Field-aware!
        )
        
        if expansions > 0:
            # Re-probe after expansion
            current_probe = await probe_browser_readiness(...)
```

---

## Feature 2: Accordion-Aware Section Extraction

### Why Current App Fails

**Current App** (`field_value_dom.py:574-594`):
```python
def extract_heading_sections(root: BeautifulSoup | Tag) -> dict[str, str]:
    """Only extracts sibling content after headings - no accordion awareness."""
    for heading in root.find_all(["h2", "h3", "h4", "h5", "strong"]):
        for sibling in heading.next_siblings:
            # Just grabs next siblings, doesn't understand accordion/tab structure
```

**Problem**: Extracts content AFTER headings, not INSIDE accordions/tabs.

### Old App Solution

**File**: `semantic_detail_extractor.py:264-349`

```python
def _extract_sections(soup: BeautifulSoup) -> dict[str, str]:
    """Extract sections including accordion/tab content."""
    # Enhanced selectors including accordion/tab patterns
    selectors = [
        "summary",
        "details > summary",
        "button[aria-controls]",
        "[role='button'][aria-controls]",
        "[role='tab'][aria-controls]",
        "[data-accordion-heading]",      # Accordion-specific
        "[data-tab-heading]",            # Tab-specific
        "button", "[role='button']", "[role='tab']",
        "h2", "h3", "h4",
    ]
    
    for node in soup.select(",".join(selectors)):
        label = _label_text(node)
        if not _is_section_label(label):
            continue
            
        # Multiple extraction strategies
        content = _extract_section_content(node, soup)
        if content and len(content) >= 12:
            sections[label] = content
    
    return sections


def _extract_section_content(node: Tag, soup: BeautifulSoup) -> str:
    """Extract content from accordion/tab sections using multiple strategies."""
    
    # Strategy 1: ARIA controls - follow aria-controls attribute
    target_id = _clean_text(node.get("aria-controls"))
    if target_id:
        target = soup.find(id=target_id)
        if isinstance(target, Tag):
            return _section_text(target, label=_label_text(node))
    
    # Strategy 2: Native details/summary
    if node.name == "summary":
        parent = node.parent if isinstance(node.parent, Tag) else None
        if isinstance(parent, Tag) and parent.name == "details":
            return _section_text(parent, label=_label_text(node))
    
    # Strategy 3: Accordion containers - walk up DOM tree
    accordion_content = _find_wrapped_section_content(node)
    if accordion_content:
        return accordion_content
    
    # Strategy 4: Sibling extraction (fallback)
    return _extract_sibling_content(node)


def _find_wrapped_section_content(node: Tag) -> str:
    """Walk up DOM tree to find accordion/tab content containers."""
    label = _label_text(node)
    container = node
    steps = 0
    while isinstance(container, Tag) and steps < 4:
        for selector in (
            "[data-accordion-content]",
            "[data-content]",
            "[data-tab-content]",
            ".accordion__answer",
            ".tabs__content",
            ".tab-content",
            ".panel",
        ):
            target = container.select_one(selector)
            if isinstance(target, Tag):
                text = _section_text(target, label=label)
                if len(text) >= 12:
                    return text
        container = container.parent if isinstance(container.parent, Tag) else None
        steps += 1
    return ""
```

### Implementation

Replace `extract_heading_sections` in `field_value_dom.py` with the accordion-aware version above.

---

## Feature 3: Agentic Retry Loop (CRITICAL)

### Why Current App Fails

Current app has no automatic recovery when extraction yields <3 records.

### Old App Solution

**File**: `spa_crawler_service.py:1647-1762`

```python
async def _agentic_retry_extraction(
    page: Any,
    url: str,
    current_records: list[dict],
    emit: Callable[[str], None],
    max_attempts: int = 3,
    max_records: int = 2000,
) -> tuple[list[dict], str | None, int]:
    """Intelligent retry loop when initial extraction is thin (<5 records).
    
    Recovery actions:
    1. Remove active filters that might be limiting results
    2. Click "View All" / "Show All" / category expansion
    3. Scroll deeper if page height suggests more content
    4. Try alternative extraction strategies
    """
    best_records = list(current_records)
    best_method: str | None = None
    attempts = 0
    
    # Define recovery actions with selectors
    recovery_actions = [
        {
            "name": "remove_filters",
            "description": "Removing active filters...",
            "selectors": [
                "button:has-text('Clear All')", "button:has-text('Clear Filters')",
                "a:has-text('Clear All')", "a:has-text('Reset')",
                "button:has-text('Reset Filters')", "[data-testid*='clear-filter']",
                ".filter-clear", ".clear-filters",
            ],
        },
        {
            "name": "view_all",
            "description": "Clicking View All / See All...",
            "selectors": [
                "a:has-text('View All')", "a:has-text('See All')",
                "a:has-text('Shop All')", "button:has-text('View All Products')",
                "a:has-text('View All Products')", "a:has-text('See All Products')",
                "select option[value*='all']",
                "a:has-text('Show All')", "button:has-text('Show All')",
            ],
        },
        {
            "name": "paginate",
            "description": "Trying pagination...",
            "selectors": [
                "a:has-text('Next')", "button:has-text('Next')",
                "a[aria-label='Next page']", "a[aria-label='Page 2']",
                ".pagination a:nth-child(2)", "[data-testid*='next-page']",
                "a:has-text('2')",
            ],
        },
    ]
    
    for action in recovery_actions:
        if attempts >= max_attempts:
            break
        if len(best_records) >= 8:  # enough records, stop retrying
            break
        
        attempts += 1
        emit(f"  Agentic retry {attempts}/{max_attempts}: {action['description']}")
        
        # Try each selector for this action
        clicked = False
        for sel in action["selectors"]:
            try:
                btn = await page.wait_for_selector(sel, timeout=1500)
                if btn and await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    clicked = True
                    emit(f"    Clicked: {sel}")
                    await page.wait_for_timeout(3000)
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    break
            except Exception:
                continue
        
        if not clicked:
            emit(f"    No actionable element found for {action['name']}")
            continue
        
        # RE-EXTRACT after the action
        retry_records: list[dict] = []
        try:
            json_ld = await _extract_json_ld_from_page(page, url, emit)
            commerce = await _extract_commerce_anchor_rows(page, url, emit)
            dom = await _extract_from_dom(page, url, emit)
            next_data = await _extract_next_data_from_page(page, url, emit)
            
            candidates = [
                ("agentic_json_ld", json_ld),
                ("agentic_commerce", commerce),
                ("agentic_dom", dom),
                ("agentic_next_data", next_data),
            ]
            retry_records, retry_method = _choose_best_record_set(candidates)
            
            if len(retry_records) > len(best_records):
                best_records = retry_records
                best_method = retry_method
                emit(f"    Agentic retry improved: {len(best_records)} records via {retry_method}")
            else:
                emit(f"    Agentic retry did not improve ({len(retry_records)} vs {len(best_records)})")
        except Exception as exc:
            emit(f"    Agentic retry extraction error: {exc}")
    
    return best_records, best_method, attempts
```

### Trigger Point

**File**: `spa_crawler_service.py:3378-3399`

```python
# TRIGGER: When extraction is thin
should_agentic = (
    method not in ("api_pagination", "api_interception")  # Skip if API already worked
    and len(all_records) < 5  # CRITICAL: Less than 5 records
    and len(api_products) < 5
    and len(paginated_api_products) < 5
    and len(commerce_anchor_records) < 5
    and getattr(site_hints, "enable_agentic_retry", True)
)

if should_agentic:
    emit("  Initial extraction thin; triggering agentic recovery loop...")
    retry_records, retry_method, agentic_attempts = await _agentic_retry_extraction(
        page=page,
        url=url,
        current_records=all_records,
        emit=emit,
        max_attempts=getattr(site_hints, "max_agentic_attempts", 3),
        max_records=max_records,
    )
    if retry_records and len(retry_records) > len(all_records):
        all_records = retry_records
        method = retry_method
```

### Integration

Add agentic retry trigger to current app's browser acquisition pipeline when:
- `len(records) < 5` after initial extraction
- Not from API interception (already optimal)
- `traversal_mode` is active

---

## Feature 4: Markdown Generation for LLM

### Why Current App Fails

**Current App** (`acquirer.py:72`):
```python
@dataclass
class AcquisitionResult:
    ...
    page_markdown: str = ""  # ALWAYS EMPTY - never populated!
```

The field exists but is **never filled**.

### Old App Solution

**File**: `spa_crawler_service.py:2780-2844`

```python
async def _html_to_markdown(page: Any) -> str:
    """Convert rendered page to cleaned Markdown-like text for LLM extraction.
    
    Key features:
    1. Removes noise elements (nav, footer, scripts, cookie banners)
    2. Extracts visible text with proper formatting
    3. Extracts links with text -> href mapping
    4. Adds ARIA accessibility tree for semantic context
    """
    try:
        payload = await page.evaluate("""() => {
            // Remove noise elements that pollute extraction
            const removeSelectors = [
                'nav', 'footer', 'header', 'script', 'style', 'noscript',
                '[class*="cookie"]', '[class*="consent"]', '[class*="modal"]',
                '[class*="popup"]', '[class*="banner"]', '[role="navigation"]',
                '[role="banner"]', '[role="contentinfo"]',
            ];
            const clone = document.body.cloneNode(true);
            removeSelectors.forEach(sel => {
                clone.querySelectorAll(sel).forEach(el => el.remove());
            });
            const text = clone.innerText || '';
            
            // Extract visible links
            const links = Array.from(document.querySelectorAll('a[href]'))
              .map(el => ({
                href: el.href || '',
                text: (el.innerText || el.textContent || '').trim(),
              }))
              .filter(item => item.href && item.text && item.text.length >= 3)
              .slice(0, 200);
              
            return { text, links };
        }""")
        
        text = str((payload or {}).get("text") or "")
        links = (payload or {}).get("links") or []
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        markdown = "\n".join(lines)
        
        # Add links section
        link_lines: list[str] = []
        for item in links:
            href = str(item.get("href") or "").strip()
            text_value = str(item.get("text") or "").strip()
            if href and text_value:
                link_lines.append(f"- {text_value} -> {href}")
        if link_lines:
            markdown = f"{markdown}\n\nVisible links:\n" + "\n".join(link_lines[:120])
        
        # Add ARIA accessibility tree for semantic context
        try:
            snapshot = await page.accessibility.snapshot()
            
            def _serialize_aria_tree(node: dict, depth: int = 0) -> str:
                if not node or depth > 8:
                    return ""
                out = []
                indent = "  " * depth
                name = str(node.get("name") or "").strip()
                if name:
                    role = str(node.get("role") or "element")
                    out.append(f"{indent}[{role}] {name}")
                for child in node.get("children", []):
                    if isinstance(child, dict):
                        out.append(_serialize_aria_tree(child, depth + 1))
                return "\n".join(filter(None, out))
            
            aria_text = _serialize_aria_tree(snapshot)
            if aria_text:
                markdown += "\n\n=== SEMANTIC ACCESSIBILITY SNAPSHOT ===\n" + aria_text
        except Exception:
            pass
            
        return markdown
    except Exception:
        return ""
```

### Integration

Add to `browser_page_flow.py` in `serialize_browser_page_content_impl`:

```python
async def _generate_page_markdown(page) -> str:
    """Generate markdown for LLM extraction."""
    # Port _html_to_markdown() from old app
    ...

# In build() method of BrowserAcquisitionResultBuilder:
markdown = await _generate_page_markdown(payload.page)
# Store in result or artifact
```

---

## Feature 5: LLM Direct Extraction Fallback

### Why Current App Fails

Current app uses LLM for:
- XPath discovery
- Missing field extraction
- Field cleanup

But NOT for direct "extract from HTML" when all else fails.

### Old App Solution

**File**: `llm_service.py:763-813`

```python
async def extract_records_from_html(
    self,
    html_snippet: str,
    content_type: str,
    accessibility_tree: str | None = None,
    *,
    requested_fields: list[str] | None = None,
    markdown: str | None = None,  # Uses markdown from _html_to_markdown
    page_title: str | None = None,
    canonical_url: str | None = None,
    meta_summary: str | None = None,
) -> tuple[list[dict[str, Any]] | None, int, int]:
    """Last-resort: ask the LLM to directly extract structured records from HTML.
    
    Called when:
    - All deterministic extraction failed
    - Only 0-2 records found
    - Need to extract from messy/unstructured HTML
    """
    field_hint = {
        "ecommerce": "title, url, price, image, brand, description, rating, availability",
        "jobs": "title, url, company, location, category, type, posted_date, reference_number, job_id, apply_url, description",
    }.get(content_type, "title, url, description, image, price, location, company")
    
    system_prompt = (
        f"You are a data extraction engine. Extract all {content_type} records from the "
        "provided page content as structured JSON.\n\n"
        "Rules:\n"
        "- Return ONLY a JSON array of objects. No prose before or after.\n"
        "- Each object represents one record (product, job, listing, etc.).\n"
        f"- Standard fields for this content type: {field_hint}.\n"
        "- Only include fields whose values are actually present in the content.\n"
        "- Do NOT invent field names beyond the standard set and any explicitly requested fields.\n"
        "- Do NOT include navigation items, headers, footer content, or ads.\n"
        "- Prefer the page's own text verbatim over paraphrasing.\n"
        "- Return [] if no records are found."
    )
    
    page_context = self._build_page_context(
        html_snippet,
        accessibility_tree,
        markdown=markdown,  # Uses cleaned markdown
        page_title=page_title,
        canonical_url=canonical_url,
        meta_summary=meta_summary,
    )
    
    requested = ", ".join(requested_fields or [])
    requested_block = f"Requested/preferred fields: {requested}\n\n" if requested else ""
    user_prompt = f"{requested_block}Page content:\n{page_context}"
    
    raw, inp, out = await self.call_llm(system_prompt, user_prompt)
    if raw.startswith(_ERROR_PREFIX):
        return None, inp, out
    result = self._parse_json_array(raw)
    return result, inp, out
```

### Trigger Point

**File**: `spa_crawler_service.py:4235-4254`

```python
# Strategy 2: LLM extraction (if browser got Markdown but no/few records)
if not skip_followup_extraction and len(result.records) < 3 and markdown and llm_service.is_available:
    llm_records, llm_usage = await _llm_extract_from_markdown(
        markdown, url, anthropic_key, emit, site_hints
    )
    if llm_records:
        result.records = llm_records
        result.llm_usage = llm_usage
        result.method_used = "llm_extraction"
        emit(f"LLM extraction: {len(result.records)} products")
```

### Integration

Add to current app's pipeline:

```python
# After all deterministic extraction attempts
if len(records) < 3 and llm_available:
    llm_records = await llm_service.extract_records_from_html(
        html=html,
        content_type=surface,
        markdown=page_markdown,  # From Feature 4
        requested_fields=requested_fields,
    )
    if llm_records:
        records.extend(llm_records)
```

---

## Implementation Priority

| Priority | Feature | Est. Impact | Files to Modify |
|----------|---------|-------------|-----------------|
| **P0** | Semantic accordion expansion | +30-50% data | `semantic_expansion.py` (new), `browser_runtime.py` |
| **P0** | Accordion-aware section extraction | +20-30% fields | `field_value_dom.py` |
| **P1** | Agentic retry loop | +15-25% coverage | `browser_runtime.py` or new module |
| **P1** | Markdown generation | Enables LLM fallback | `browser_page_flow.py` |
| **P2** | LLM direct extraction | +10-15% recovery | `llm_tasks.py` or `llm_service.py` |

---

## Configuration Additions

Add to `runtime_settings.py`:

```python
# Semantic expansion
semantic_expand_max_actions: int = 8
semantic_expand_max_per_selector: int = 5
semantic_expand_wait_ms: int = 600

# Agentic retry
agentic_retry_enabled: bool = True
agentic_retry_max_attempts: int = 3
agentic_retry_min_records_threshold: int = 5

# LLM extraction
llm_direct_extraction_enabled: bool = True
llm_extraction_min_records_trigger: int = 3
```

---

## Testing Checklist

### Accordion Expansion
- [ ] Product specs accordion reveals specifications
- [ ] "Read more" button reveals full description
- [ ] Tab panels all captured (not just active tab)
- [ ] "Add to cart" button NOT clicked

### Agentic Retry
- [ ] Filtered listing expands when "Clear All" clicked
- [ ] "View All Products" pagination triggered
- [ ] <3 records triggers retry automatically

### LLM Extraction
- [ ] Markdown generated with links and ARIA tree
- [ ] LLM extracts records when deterministic fails
- [ ] Token usage tracked correctly

---

## Summary

The old app's superiority comes from:

1. **Smarter accordion handling** - Field-aware, ARIA-aware, commerce-safe
2. **Agentic recovery** - Automatic retry when extraction is thin
3. **Markdown + LLM fallback** - Last-resort extraction from rendered content
4. **Multi-strategy concurrency** - Runs all extractors, picks best

These are **concrete, implementable features** with code evidence above.
