# Extraction Logic Audit: Current vs. Older App

## Executive Summary

The **older app** (`C:\Users\abhij\Downloads\pre_poc_ai_crawler`) extracts significantly more data because it has **superior accordion/carousel expansion logic** and **semantic content extraction**. The current app has basic expansion but lacks the comprehensive semantic understanding of the older implementation.

---

## Key Differences

### 1. Accordion/Expandable Content Handling

#### Older App: `semantic_browser_helpers.py`
**File**: `backend/app/services/semantic_browser_helpers.py:50-101`

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
    "read more",
    "show more",
    "view more",
    "details",
    "description",
    "specifications",
    "specs",
    "product details",
    "size",
    "fit",
    "materials",
    "fabric",
    "ingredients",
    "care",
    "shipping",
    "returns",
)

_BLOCKED_TOKENS = (
    "add to cart",
    "buy now",
    "checkout",
    "login",
    "sign in",
    "subscribe",
    "wishlist",
    "add to bag",
    "shopping bag",
)
```

**Key Features**:
- **Field-aware expansion**: Considers requested fields when expanding (`requested_tokens`)
- **Smart filtering**: Blocks commerce action buttons (add to cart, buy now)
- **ARIA-aware**: Checks `aria-expanded="false"` attribute
- **Multi-strategy**: Tries multiple selector types
- **Bounded**: `max_actions=6`, `max_per_selector=4`

#### Current App: `browser_detail.py` + `browser_runtime.py`
**Files**: 
- `backend/app/services/acquisition/browser_detail.py:84-159`
- `backend/app/services/acquisition/browser_runtime.py:111-124`

```python
_DETAIL_EXPAND_SELECTORS = (
    "button, summary, details summary, "
    "[role='button'], [aria-expanded='false'], "
    "[data-testid*='expand'], [data-testid*='accordion']"
)

_DETAIL_EXPAND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ecommerce": ("about", "compatibility", "description", "details", "dimensions", 
                  "more", "product", "read more", "show more", "spec", "view more"),
    "job": ("benefits", "compensation", "description", "more", "qualifications", 
            "requirements", "responsibilities", "salary", "see more", "show all")
}
```

**Current App Limitations**:
1. **No field-aware expansion** - doesn't know what fields user wants
2. **No blocked tokens** - may click "add to cart" buttons
3. **Limited ARIA handling** - only checks `aria-expanded='false'` in selectors
4. **No semantic understanding** - purely keyword-based matching

---

### 2. Section Content Extraction (Post-Expansion)

#### Older App: `semantic_detail_extractor.py`
**File**: `backend/app/services/semantic_detail_extractor.py:264-349`

```python
def _extract_sections(soup: BeautifulSoup) -> dict[str, str]:
    selectors = [
        "summary",
        "details > summary",
        "button[aria-controls]",
        "[role='button'][aria-controls]",
        "[role='tab'][aria-controls]",
        "[data-accordion-heading]",      # Accordion-specific
        "[data-tab-heading]",            # Tab-specific
        "button",
        "[role='button']",
        "[role='tab']",
        "h2", "h3", "h4",
    ]

def _find_wrapped_section_content(node: Tag) -> str:
    # Looks for accordion/tab content containers
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
```

**Key Features**:
- **Accordion-specific selectors**: `[data-accordion-heading]`, `[data-accordion-content]`
- **Tab-specific selectors**: `[data-tab-heading]`, `[data-tab-content]`
- **Parent traversal**: Walks up DOM to find content containers
- **ARIA controls support**: Follows `aria-controls` attribute
- **Native details/summary**: Special handling for `<details>` elements

#### Current App: `field_value_dom.py`
**File**: `backend/app/services/field_value_dom.py:574-594`

```python
def extract_heading_sections(root: BeautifulSoup | Tag) -> dict[str, str]:
    for heading in root.find_all(["h2", "h3", "h4", "h5", "strong"]):
        # Only extracts sibling content, no accordion awareness
        for sibling in heading.next_siblings:
            # ... basic sibling extraction
```

**Limitation**: Only extracts sibling content after headings - no accordion/tab awareness.

---

### 3. Browser Integration

#### Older App: SPA Crawler Service
**File**: `backend/app/services/spa_crawler_service.py:2020-2024`

```python
async def _shared_semantic_expander(page, emit, max_expansions: int = 6):
    """Bounded shared semantic expander for hidden detail content."""
    expansions = await safe_expand_semantic_content(page, emit, max_actions=max_expansions)
    return expansions
```

The older app calls `safe_expand_semantic_content()` during **SPA crawling**, ensuring accordions are expanded BEFORE content extraction.

#### Current App: Browser Runtime
**File**: `backend/app/services/acquisition/browser_runtime.py:679-693`

```python
async def expand_detail_content_if_needed(
    page: Any,
    *,
    surface: str,
    readiness_probe: dict[str, object],
) -> dict[str, object]:
    # Only expands if readiness probe indicates content is missing
    if readiness_probe.get("is_ready"):
        return detail_expansion_skip("already_ready")
```

**Current App Issue**: Expansion only happens if `readiness_probe` indicates missing content. If the probe doesn't detect accordion content as "missing", expansion is skipped.

---

## Recommendations to Implement

### Priority 1: Port `safe_expand_semantic_content` from Older App

Create new file: `backend/app/services/acquisition/semantic_expansion.py`

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
    
    Args:
        page: Playwright page object
        emit: Callback for logging expansion events
        max_actions: Maximum total click actions
        max_per_selector: Maximum clicks per selector type
        requested_fields: Fields user wants to extract (guides expansion)
    
    Returns:
        Number of successful expansions
    """
    # Derive tokens from requested fields
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
        
        elements = await page.query_selector_all(selector)
        
        for element in elements[:max_per_selector]:
            if actions >= max_actions:
                break
                
            # Get element text and attributes
            text = " ".join((await element.inner_text()).split()).strip().lower()
            aria_expanded = str(await element.get_attribute("aria-expanded") or "").strip().lower()
            aria_label = " ".join(((await element.get_attribute("aria-label")) or "").split()).strip().lower()
            title = " ".join(((await element.get_attribute("title")) or "").split()).strip().lower()
            
            probe = " ".join(part for part in (text, aria_label, title) if part).strip()
            
            # Skip blocked tokens (commerce actions)
            if any(token in probe for token in _BLOCKED_TOKENS):
                continue
            
            # Check if element looks expandable
            looks_expandable = (
                selector in {"summary", "details > summary", "[aria-expanded='false']"}
                or aria_expanded == "false"
                or any(token in probe for token in _SAFE_EXPAND_TOKENS)
                or any(token in probe for token in requested_tokens)
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
    
    return actions
```

### Priority 2: Enhance Section Extraction

Update `backend/app/services/field_value_dom.py` to add accordion-aware extraction:

```python
def extract_heading_sections_enhanced(root: BeautifulSoup | Tag) -> dict[str, str]:
    """Extract sections including accordion/tab content."""
    sections: dict[str, str] = {}
    
    # Enhanced selectors including accordion/tab patterns
    selectors = [
        "summary", "details > summary",
        "button[aria-controls]",
        "[role='button'][aria-controls]",
        "[role='tab'][aria-controls]",
        "[data-accordion-heading]",
        "[data-tab-heading]",
        "button", "[role='button']", "[role='tab']",
        "h2", "h3", "h4", "h5",
    ]
    
    for node in root.select(",".join(selectors)):
        label = _clean_text(node.get_text(" ", strip=True))
        if not label or len(label) < 3 or len(label) > 60:
            continue
            
        # Try multiple content extraction strategies
        content = _extract_section_content_enhanced(node, root)
        if content and len(content) >= 12:
            sections[label] = content
    
    return sections

def _extract_section_content_enhanced(node: Tag, soup: BeautifulSoup) -> str:
    """Extract content from accordion/tab sections."""
    # Strategy 1: ARIA controls
    target_id = node.get("aria-controls")
    if target_id:
        target = soup.find(id=target_id)
        if isinstance(target, Tag):
            return _clean_text(target.get_text(" ", strip=True))
    
    # Strategy 2: Native details/summary
    if node.name == "summary":
        parent = node.parent
        if isinstance(parent, Tag) and parent.name == "details":
            return _clean_text(parent.get_text(" ", strip=True))
    
    # Strategy 3: Accordion containers
    container = node
    for _ in range(4):  # Walk up 4 levels
        for selector in (
            "[data-accordion-content]",
            "[data-content]",
            ".accordion__answer",
            ".tabs__content",
            ".tab-content",
            ".panel",
        ):
            target = container.select_one(selector)
            if isinstance(target, Tag):
                text = _clean_text(target.get_text(" ", strip=True))
                if len(text) >= 12:
                    return text
        container = container.parent if isinstance(container.parent, Tag) else None
        if not container:
            break
    
    # Strategy 4: Sibling extraction (fallback)
    return _extract_sibling_content(node)
```

### Priority 3: Integration Point

Modify `backend/app/services/acquisition/browser_runtime.py` to use semantic expansion:

```python
async def _settle_browser_page(
    page: Any,
    *,
    url: str,
    surface: str,
    # ... other params
):
    # After initial readiness probe...
    
    # NEW: Always run semantic expansion for detail pages
    if "detail" in str(surface or "").lower():
        from .semantic_expansion import safe_expand_semantic_content
        
        expansions = await safe_expand_semantic_content(
            page,
            lambda msg: logger.info(msg),
            max_actions=crawler_runtime_settings.accordion_expand_max,
            requested_fields=getattr(surface_config, "fields", None),
        )
        
        if expansions > 0:
            # Re-probe after expansion
            current_probe = await probe_browser_readiness(...)
```

---

## Configuration Settings to Add

Update `backend/app/services/config/runtime_settings.py`:

```python
# Add to CrawlerRuntimeSettings:
semantic_expand_max_actions: int = 8          # Increased from 6
semantic_expand_max_per_selector: int = 5
semantic_expand_wait_ms: int = 600           # Slightly longer wait
semantic_expand_enabled: bool = True         # Toggle feature
```

---

## Testing Recommendations

Test sites with accordions/carousels:
1. **E-commerce**: Product detail pages with "Specifications", "Reviews", "Shipping" accordions
2. **Job boards**: Job listings with "Requirements", "Benefits" expandable sections
3. **SPAs**: React/Vue apps with tabbed interfaces

Validation criteria:
- Content from ALL accordion panels is extracted
- Tab content is captured, not just active tab
- "Read more" / "Show more" buttons are clicked
- Commerce buttons (Add to cart) are NOT clicked

---

## Summary

| Feature | Older App | Current App | Gap |
|---------|-----------|-------------|-----|
| Field-aware expansion | ✅ Yes | ❌ No | **Critical** |
| Blocked tokens (commerce) | ✅ Yes | ❌ No | **Critical** |
| ARIA-expanded check | ✅ Yes | ⚠️ Partial | Medium |
| Accordion selectors | ✅ Rich | ⚠️ Basic | High |
| Tab content extraction | ✅ Yes | ❌ No | **Critical** |
| Section extraction | ✅ Multi-strategy | ⚠️ Sibling-only | High |

**Estimated Impact**: Implementing these changes should increase data extraction coverage by **30-50%** on sites with accordion/tab UIs.
