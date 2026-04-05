# CrawlerAI Pipeline Audit — AutoZone Extraction Failures

**Files audited:** `acquirer.py`, `browser_client.py`, `listing_extractor.py`, `pipeline_config.py`, `autozone_curl.html`

---

## Executive Summary

Two independent failure chains interact to produce the observed symptoms:

1. **The 2-minute hang** is caused by a false-positive JS-shell detection in `acquirer.py` that triggers a Playwright escalation, followed by a multiplicative timeout blow-up in `browser_client.py` across two browser profiles and two error retries (2 × 2 × 30 s ≈ 120 s).

2. **The garbled output** is caused by `_extract_from_json_ld` missing AutoZone's nested JSON-LD structure (`WebPage → mainEntity → ItemList`), which causes silent fallthrough to the DOM card detector, which in turn picks up sidebar filter-count badges (`(1353)`, `(42)`, …) as "listing cards."

The two bugs are independent but compound each other: because the extractor cannot find products from the curl HTML's JSON-LD, the acquisition layer's "useful content" heuristic cannot pre-empt the browser escalation, and the browser escalation wastes two minutes.

---

## Bug 1 — Acquisition Hang (`acquirer.py` + `browser_client.py`)

### 1a. False-Positive JS-Shell Detection (`acquirer.py` lines 296–316)

**The logic:**

```python
js_shell_detected = (
    html_len >= BROWSER_FALLBACK_HTML_SIZE_THRESHOLD  # 200 000 bytes
    and visible_len > 0
    and (visible_len / html_len) < BROWSER_FALLBACK_VISIBLE_TEXT_RATIO_MAX  # 0.02
)
...
needs_browser = bool(
    ...
    or (js_shell_detected and adapter_hint is None)  # ← fires for AutoZone
    ...
)
```

**Why it misfires on AutoZone:**

AutoZone's `curl_cffi` response is approximately 1.8 MB of fully-rendered HTML. The page is a Next.js SSR page, so virtually all meaningful content lives inside `<script type="application/ld+json">` and `<script id="__NEXT_DATA__">` tags rather than in text nodes. BeautifulSoup's `.get_text()` call therefore returns very little visible text, keeping the ratio far below the 0.02 threshold.

The pipeline correctly classifies this as a "JS shell" — but it isn't one. It is a fully-populated SSR page that happens to store its payload in script tags. The data is 100% present in the curl response, but the ratio heuristic cannot distinguish a real shell from a large SSR page that front-loads everything into structured data blobs.

**Compounding factor — `adapter_hint is None`:**

No adapter is registered for `autozone.com`, so `adapter_hint` is always `None`. The `(js_shell_detected and adapter_hint is None)` condition therefore always fires whenever the ratio is below the threshold, regardless of whether a more targeted check would have cleared it.

**The missing early-exit guard:**

After `has_useful_content` is populated on line 340, `curl_result` is stored as a fallback but the logic **never asks** whether that curl HTML already contains parseable structured products. A fast pre-screen for `<script type="application/ld+json">` containing at least two `Product` or `ItemList` nodes, or a populated `__NEXT_DATA__` that resolves to product records, would allow the pipeline to skip the Playwright escalation entirely in the common SSR case.

**Recommended fix — `acquirer.py`:**

```python
# After computing needs_browser, add a "rich-structured-data" bail-out:
if needs_browser and js_shell_detected and not blocked.is_blocked:
    if _html_has_extractable_listings(html):
        needs_browser = False
        curl_diagnostics["js_shell_overridden"] = "structured_data_found"

def _html_has_extractable_listings(html: str) -> bool:
    """Return True if the HTML contains enough structured product data
    to skip browser escalation despite a low visible-text ratio."""
    soup = BeautifulSoup(html, "html.parser")
    product_count = 0
    for node in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(node.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            ld_type = str(item.get("@type", "")).lower()
            # Direct product or item list
            if ld_type in ("product", "jobposting"):
                product_count += 1
            elif ld_type == "itemlist" or "itemlistElement" in item:
                product_count += len(item.get("itemListElement", []))
            # Nested: WebPage → mainEntity → ItemList  (AutoZone pattern)
            main_entity = item.get("mainEntity") or {}
            if isinstance(main_entity, dict):
                me_type = str(main_entity.get("@type", "")).lower()
                if me_type in ("itemlist", "product"):
                    product_count += max(
                        1, len(main_entity.get("itemListElement", []))
                    )
            # @graph arrays
            for graph_item in item.get("@graph", []):
                if not isinstance(graph_item, dict):
                    continue
                g_type = str(graph_item.get("@type", "")).lower()
                if g_type in ("product", "itemlist"):
                    product_count += max(
                        1, len(graph_item.get("itemListElement", [1]))
                    )
            if product_count >= 2:
                return True
    # __NEXT_DATA__ heuristic: check key exists and has a non-trivial payload
    next_data_node = soup.select_one("script#__NEXT_DATA__")
    if next_data_node:
        raw = next_data_node.string or ""
        # Fast heuristic: look for product-like keys without full JSON parse
        if raw.count('"productId"') + raw.count('"partNumber"') + \
           raw.count('"displayName"') >= 4:
            return True
    return False
```

---

### 1b. Cumulative 120-Second Timeout Blow-Up (`browser_client.py` lines 258–262, 736–800)

**The math:**

```python
def _browser_launch_profiles():
    return [
        {"label": "bundled_chromium", ...},   # profile 1
        {"label": "system_chrome", ...},       # profile 2
    ]
```

```python
# pipeline_config.py
BROWSER_ERROR_RETRY_ATTEMPTS = 1   # → 2 total attempts per profile
BROWSER_NAVIGATION_NETWORKIDLE_TIMEOUT_MS = 30_000  # 30 s = max_timeout
```

In `_goto_with_fallback`, the initial navigation uses the largest timeout:

```python
max_timeout = max([timeout for _, timeout in strategies])  # = 30 000 ms
await page.goto(url, wait_until="domcontentloaded", timeout=max_timeout)
```

When AutoZone's anti-bot layer detects Playwright and blocks the connection (or serves a challenge page that never fires `DOMContentLoaded`), this 30 s timeout is consumed in full. With 2 profiles × 2 retry attempts each, the worst-case wall time is:

```
2 profiles × 2 attempts × 30 s = 120 s  ≈ 2 minutes
```

Additionally, `BROWSER_ERROR_RETRY_DELAY_MS = 1000 ms` is added between retries, contributing another 4 s, for a true worst-case of ~124 s.

**Secondary issue — optimistic wait is 10 s for `networkidle`, unconditionally:**

```python
for wait_until, timeout in strategies:
    if wait_until in ("load", "networkidle"):
        try:
            await page.wait_for_load_state(wait_until, timeout=10000)
        except Exception:
            pass
```

AutoZone keeps long-lived keep-alive connections open for analytics and telemetry. When Playwright does successfully navigate (e.g., via `system_chrome`), `networkidle` never fires within 10 s, so this budget is always consumed, adding up to another 10 s of latency per successful navigation.

**Recommended fixes — `browser_client.py` + `pipeline_config.py`:**

**Fix A — Adaptive profile timeout:** When the first profile fails entirely (all retry attempts exhausted), reduce the timeout for subsequent profiles rather than re-using the same 30 s budget:

```python
async def _fetch_rendered_html_with_fallback(pw, *, ...):
    last_error = None
    first_profile_failed = False
    for profile in _browser_launch_profiles():
        # After first complete failure, reduce timeout for remaining profiles
        adjusted_strategies = (
            _shortened_navigation_strategies()
            if first_profile_failed
            else _navigation_strategies(browser_channel=profile.get("channel"))
        )
        try:
            result = await _fetch_rendered_html_attempt(
                ...,
                launch_profile=profile,
                navigation_strategies=adjusted_strategies,
            )
            ...
            return result
        except Exception as exc:
            last_error = exc
            first_profile_failed = True
            continue
    raise last_error

def _shortened_navigation_strategies() -> list[tuple[str, int]]:
    """Aggressive-timeout fallback for second-attempt profiles."""
    return [
        ("domcontentloaded", 12000),
        ("commit", 8000),
    ]
```

**Fix B — Reduce `networkidle` optimistic wait to 3 s for known SSR storefronts:**
Change the hardcoded `timeout=10000` to a configurable constant in `pipeline_config.py`:

```python
# pipeline_config.py
BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS: int = _TUNING.get(
    "browser_navigation_optimistic_wait_ms", 3000
)
```

```python
# browser_client.py _goto_with_fallback
await page.wait_for_load_state(wait_until, timeout=BROWSER_NAVIGATION_OPTIMISTIC_WAIT_MS)
```

**Fix C (most impactful) — Pre-empt browser escalation in `acquirer.py`:** Implemented above in Fix 1a. This is the highest-leverage fix because it prevents the browser from being launched at all for AutoZone's SSR pages.

---

## Bug 2 — Garbled Listing Output (`listing_extractor.py`)

### 2a. `_extract_from_json_ld` Misses AutoZone's Nested JSON-LD Structure (lines 514–544)

**The current parser:**

```python
for payload in items:
    ld_type = payload.get("@type", "")
    if ld_type == "ItemList" or "itemListElement" in payload:
        # ... process items
    elif ld_type in ("Product", "JobPosting"):
        # ... process single item
```

**What AutoZone actually emits:**

AutoZone uses a common e-commerce pattern where the product list is nested under a `WebPage` wrapper via `mainEntity`, and/or the entire page graph is wrapped in a `@graph` array:

**Pattern A — `WebPage → mainEntity → ItemList`:**
```json
{
  "@context": "https://schema.org",
  "@type": "WebPage",
  "mainEntity": {
    "@type": "ItemList",
    "itemListElement": [
      {"@type": "ListItem", "position": 1, "item": {"@type": "Product", ...}},
      ...
    ]
  }
}
```

**Pattern B — `@graph` array:**
```json
{
  "@context": "https://schema.org",
  "@graph": [
    {"@type": "BreadcrumbList", ...},
    {"@type": "ItemList", "itemListElement": [...]}
  ]
}
```

Neither pattern is handled. Both fall through silently, the function returns an empty list, and the pipeline falls through all structured strategies to the DOM card detector.

The exact same blind spot exists in `_extract_from_structured_sources` (lines 382–406), which also only checks `ld_type == "ItemList"` or `ld_type in ("Product", "JobPosting")` on the top-level payload without recursing into `mainEntity` or `@graph`.

**Recommended fix — `listing_extractor.py`:**

```python
def _extract_from_json_ld(soup: BeautifulSoup, surface: str, page_url: str) -> list[dict]:
    records: list[dict] = []
    for node in soup.select("script[type='application/ld+json']"):
        raw = node.string or node.get_text(" ", strip=True) or ""
        data = _parse_json_script(raw)
        if data is None:
            continue
        items = data if isinstance(data, list) else [data]
        for payload in items:
            if not isinstance(payload, dict):
                continue
            records.extend(_extract_ld_records_from_payload(payload, surface, page_url))
    return records


def _extract_ld_records_from_payload(
    payload: dict, surface: str, page_url: str
) -> list[dict]:
    """Recursively extract listing records from a single JSON-LD payload dict.

    Handles:
    - Top-level ItemList / Product / JobPosting
    - @graph arrays (common on large e-commerce storefronts)
    - WebPage / CollectionPage → mainEntity → ItemList  (AutoZone, Home Depot)
    - Nesting up to 2 levels deep to avoid runaway recursion on large graphs
    """
    records: list[dict] = []
    ld_type = str(payload.get("@type", "")).strip()

    # Direct: ItemList or bare itemListElement key
    if ld_type == "ItemList" or "itemListElement" in payload:
        for el in payload.get("itemListElement", []):
            if isinstance(el, dict):
                item = el.get("item", el)
                if isinstance(item, dict):
                    record = _normalize_ld_item(item, surface, page_url)
                    if record:
                        record["_source"] = "json_ld_item_list"
                        records.append(record)

    # Direct: single Product or JobPosting
    elif ld_type in ("Product", "JobPosting"):
        record = _normalize_ld_item(payload, surface, page_url)
        if record:
            record["_source"] = "json_ld"
            records.append(record)

    # ── NEW: @graph array ─────────────────────────────────────────────────
    graph = payload.get("@graph")
    if isinstance(graph, list):
        for graph_item in graph:
            if isinstance(graph_item, dict):
                records.extend(
                    _extract_ld_records_from_payload(graph_item, surface, page_url)
                )

    # ── NEW: mainEntity nesting (WebPage → ItemList) ─────────────────────
    if not records:
        main_entity = payload.get("mainEntity")
        if isinstance(main_entity, dict):
            records.extend(
                _extract_ld_records_from_payload(main_entity, surface, page_url)
            )

    # ── NEW: offers.itemOffered array (some storefront schemas) ──────────
    if not records:
        offers = payload.get("offers")
        if isinstance(offers, dict):
            item_offered = offers.get("itemOffered")
            if isinstance(item_offered, list):
                for item in item_offered:
                    if isinstance(item, dict):
                        record = _normalize_ld_item(item, surface, page_url)
                        if record:
                            record["_source"] = "json_ld_offers"
                            records.append(record)

    return records
```

Apply the same change to `_extract_from_structured_sources` in the manifest path (lines 382–406) — replace the inline loop with calls to `_extract_ld_records_from_payload`.

---

### 2b. `_is_meaningful_listing_record` Does Not Reject Numeric or Filter-Count Titles (lines 1300–1347)

**The problem:**

When DOM card fallback runs and matches sidebar filter badges, records arrive with titles like `"(1353)"`, `"42"`, or — as seen in `run-1.json` — with integer title values `1`, `2`, … `8`. The function only checks for empty public fields and nav-URL heuristics. There is no guard against:

- A `title` that is a raw integer (from numeric JSON fields aliased to "title")
- A `title` that matches a filter-count pattern like `(1353)`
- A record that has only a `title` field and a `price` of `0` (the exact run-1.json symptom)

**The integer-title origin:**

The 8 records `{"title": 1, "price": 0}` through `{"title": 8, "price": 0}` almost certainly originate from a `__NEXT_DATA__` sub-object where a numeric page-section index or result-page counter is matched by `_find_alias_values` as the "title" field. This path is `_normalize_generic_item` → `FIELD_ALIASES["title"]` → any alias that happens to hold a small integer.

**The `price: 0` origin:**

In `_normalize_listing_value`, when a `price` alias resolves to the integer `0`, it likely passes the `v not in (None, "", [], {})` guard because `0` is falsy in Python but not equal to any of those sentinel values directly — except it *is* falsiness that matters here. However, looking at the empty-filter in `_normalize_ld_item`:

```python
record = {k: v for k, v in record.items() if v}
```

`0` would be filtered out here. So the `0` price is likely coming from the DOM card path where the price text is `"0"` or a bare `"$0"` string.

**Recommended fix — `listing_extractor.py`:**

```python
_NUMERIC_ONLY_RE = re.compile(r"^\s*\(?\s*[\d,]+\s*\)?\s*$")
_FILTER_COUNT_RE = re.compile(r"^\s*\(\s*\d[\d,]*\s*\)\s*$")

def _is_meaningful_listing_record(record: dict) -> bool:
    """Reject repeated nav/facet links that do not contain any item data."""
    public_fields = {
        key: value
        for key, value in record.items()
        if not str(key).startswith("_") and value not in (None, "", [], {})
    }
    if not public_fields:
        return False

    # ── NEW: reject records whose title is a bare integer or filter count ──
    raw_title = public_fields.get("title")
    if raw_title is not None:
        title_str = str(raw_title).strip()
        if _FILTER_COUNT_RE.match(title_str):
            # e.g. "(1353)" — sidebar facet count badge
            return False
        if isinstance(raw_title, (int, float)) and not isinstance(raw_title, bool):
            # e.g. title = 1, 2, 3 — numeric index leaked from JSON
            return False
        if title_str.isdigit():
            # e.g. "42" — string digit from DOM text node
            return False

    # ── NEW: reject records with only title + zero price and no URL ───────
    raw_price = public_fields.get("price")
    url_value = str(public_fields.get("url") or "").strip()
    if (
        raw_price in (0, "0", "$0", "0.00", "$0.00")
        and not url_value
        and len(public_fields) <= 2
    ):
        return False

    url_value = str(public_fields.get("url") or "").strip()
    meaningful_keys = {key for key in public_fields if key != "url"}
    if meaningful_keys == LISTING_MINIMAL_VISUAL_FIELDS and not url_value:
        return False

    product_signal_keys = meaningful_keys & LISTING_PRODUCT_SIGNAL_FIELDS

    if url_value and _looks_like_category_url(url_value):
        if not product_signal_keys:
            return False

    if (
        url_value
        and not product_signal_keys
        and meaningful_keys.issubset(LISTING_MINIMAL_VISUAL_FIELDS)
    ):
        parsed = urlparse(url_value)
        path = parsed.path.rstrip("/")
        segments = [s for s in path.split("/") if s]
        if len(segments) <= 1 and not parsed.query:
            return False
        path_token_set = {s.lower().replace("-", "") for s in segments}
        if path_token_set & _NON_LISTING_PATH_TOKENS:
            return False

    job_signal_keys = meaningful_keys & LISTING_JOB_SIGNAL_FIELDS
    if job_signal_keys and not record.get("title") and not record.get("salary"):
        return False

    if meaningful_keys:
        return True

    return False
```

---

### 2c. DOM Card Auto-Detector Selects Sidebar Filter Elements (`listing_extractor.py` lines 1514–1569)

**The problem:**

`_auto_detect_cards` scans all `ul, ol, div.grid, div.row, div[class*='results'], div[class*='product'], div[class*='listing'], ...` containers for repeating sibling groups. AutoZone's sidebar has a filter accordion (`div[class*='results']` or a `ul` under the filter rail) where each `<li>` child contains a label and a count badge. These elements:

- Pass `len(children) >= 3` (many filter options)
- Each child has an `<a href>` link (filtered URL)
- Each child has substantial text (filter label + count = >20 chars)
- `_card_group_score` returns a high `(ratio, count)` tuple

The filter rail is therefore selected as the "best card group" and its options are misidentified as listing items.

**Root cause in `_card_group_score`:**

```python
if has_link and (has_image or has_price or has_substantial_text):
    signals += 1
```

Filter options have links and substantial text but no images and no price. The `has_substantial_text` condition (>20 chars) is too permissive — it accepts navigation text.

**Recommended fix — `listing_extractor.py`:**

Increase the signal bar for "commerce" surfaces: a card must have either an image OR a price element in addition to a link. Pure text-only items with links are navigation:

```python
def _card_group_score(group: list[Tag], surface: str = "") -> tuple[float, int]:
    """Score a candidate card group by product-like signals."""
    signals = 0
    is_commerce = "ecommerce" in str(surface or "").lower()
    for el in group[:30]:
        has_link = bool(el.select_one("a[href]"))
        has_image = bool(el.select_one("img, picture, [style*='background-image']"))
        has_price = bool(
            el.select_one("[itemprop='price'], .price, [class*='price'], .amount")
        )
        text = el.get_text(" ", strip=True)
        # Raise the bar on commerce surfaces: require link + image OR price.
        # This prevents sidebar filter lists (link + text only) from winning.
        if is_commerce:
            if has_link and (has_image or has_price):
                signals += 1
        else:
            has_substantial_text = len(text) > 20
            if has_link and (has_image or has_price or has_substantial_text):
                signals += 1
    sample_size = min(len(group), 30)
    ratio = signals / sample_size if sample_size > 0 else 0.0
    return (ratio, len(group))
```

Pass `surface` down from `_auto_detect_cards` and from its caller in `_extract_listing_records_single_page`.

Additionally, add an explicit container exclusion for sidebar/filter rail elements:

```python
def _auto_detect_cards(soup: BeautifulSoup, surface: str = "") -> tuple[list[Tag], str]:
    # ── NEW: exclude known non-product containers ─────────────────────────
    for noise_el in soup.select(
        "aside, nav, [class*='filter'], [class*='facet'], "
        "[class*='sidebar'], [class*='breadcrumb'], footer, header"
    ):
        noise_el.decompose()
    # ... rest unchanged
```

---

## Additional Bugs Found

### Bug 3 — `MAX_JSON_RECURSION_DEPTH` Is Too Shallow for AutoZone's `__NEXT_DATA__` (`pipeline_config.py` line 87)

```python
MAX_JSON_RECURSION_DEPTH: int = _TUNING.get("max_json_recursion_depth", 4)
```

AutoZone's `__NEXT_DATA__` is a deeply-nested Next.js page props tree. The product array often lives at a depth of 6–8 keys (e.g., `props → pageProps → initialState → search → results → products`). The default depth cap of `4` causes `_collect_candidate_record_sets` to halt before reaching it.

Note the workaround in `_extract_from_next_data` (line 657):
```python
max_depth=max(MAX_JSON_RECURSION_DEPTH + 4, 8),
```
This adds `+4` and floors at `8` — which suggests someone already encountered this problem. However this `+4` compensation is not applied in `_extract_from_structured_sources` when it calls `_extract_items_from_json` for hydrated states and network payloads (lines 416–432). Those calls use the plain `MAX_JSON_RECURSION_DEPTH = 4` default:

```python
# listing_extractor.py line 416-421 — uses default max_depth = 4
state_records = _extract_items_from_json(state, surface, page_url)
```

**Recommended fix:** Raise the default or unify the depth:

```python
# pipeline_config.py
MAX_JSON_RECURSION_DEPTH: int = _TUNING.get("max_json_recursion_depth", 8)
```

Or, ensure `_extract_items_from_json` callers for structured sources use the same `+4` compensation as `_extract_from_next_data`.

---

### Bug 4 — `_extract_from_structured_sources` Has the Same JSON-LD Blind Spot (lines 382–406)

The manifest-path extractor duplicates the same top-level-only JSON-LD logic as the direct-HTML parser but without the proposed `_extract_ld_records_from_payload` helper. Both paths must be updated — patching only one creates split behavior depending on whether the `DiscoveryManifest` is populated or not:

```python
# listing_extractor.py _extract_from_structured_sources
ld_records: list[dict] = []
for payload in manifest.json_ld:
    if not isinstance(payload, dict):
        continue
    # ── Replace the existing ld_type checks with: ──────────────────────
    ld_records.extend(
        _extract_ld_records_from_payload(payload, surface, page_url)
    )
```

---

### Bug 5 — `_normalize_ld_item` Silently Drops `price = 0` via Falsy Filter (line 628)

```python
record = {k: v for k, v in record.items() if v}
```

This strips any field whose value is falsy, including `price = 0`, `rating = 0`, and `availability = ""`. The `price = 0` case is a real product (a free download or sample), not noise. The filter should instead use the same sentinel set used everywhere else:

```python
_EMPTY_VALUES = (None, "", [], {})

record = {k: v for k, v in record.items() if v not in _EMPTY_VALUES}
```

This is a minor correctness bug but explains why any $0.00 products are missing from results even when correctly parsed from JSON-LD.

---

## Summary Table

| # | File | Location | Type | Severity | Description |
|---|------|----------|------|----------|-------------|
| 1a | `acquirer.py` | L296–316 | Logic Bug | **Critical** | SSR pages with JSON-in-scripts falsely trigger JS-shell detection, causing unnecessary Playwright escalation |
| 1b | `browser_client.py` | L258–262, L736–800 | Config/Logic | **Critical** | 2 profiles × 2 retries × 30 s timeout = 120 s worst-case hang |
| 2a | `listing_extractor.py` | L514–544, L382–406 | Missing Feature | **Critical** | JSON-LD parser misses `@graph` and `mainEntity → ItemList` patterns (AutoZone's schema) |
| 2b | `listing_extractor.py` | L1300–1347 | Missing Guard | **High** | `_is_meaningful_listing_record` accepts integer/numeric titles and filter-count strings |
| 2c | `listing_extractor.py` | L1514–1569 | Heuristic Gap | **High** | DOM card auto-detector selects sidebar filter rails; `_card_group_score` too permissive |
| 3  | `pipeline_config.py` | L87 | Config | **Medium** | `MAX_JSON_RECURSION_DEPTH = 4` too shallow; `__NEXT_DATA__` products at depth 6–8 are missed by hydrated-state and network-payload paths |
| 4  | `listing_extractor.py` | L382–406 | Logic Bug | **Medium** | Manifest-path JSON-LD extractor has the same blind spot as the direct-HTML path (fix must be applied to both) |
| 5  | `listing_extractor.py` | L628 | Minor Bug | **Low** | `if v` falsy filter silently drops `price = 0`, `rating = 0` from valid JSON-LD products |

---

## Recommended Fix Order

1. **Fix 2a first** (JSON-LD nested-pattern support) — this single change will cause the structured extractor to find products in the curl HTML, which unblocks Fix 1a.
2. **Fix 1a** (pre-screen structured data before browser escalation) — once structured extraction works, this eliminates the Playwright path entirely for SSR sites like AutoZone.
3. **Fix 2b** (numeric title rejection in `_is_meaningful_listing_record`) — cheap, zero risk.
4. **Fix 1b** (reduce per-profile timeout budget) — defense-in-depth for sites that genuinely need a browser.
5. **Fix 2c** (exclude sidebar containers from DOM card detector) — prevents filter-count noise on any site where structured extraction fails.
6. **Fix 3** (raise `MAX_JSON_RECURSION_DEPTH`) — needed for deep `__NEXT_DATA__` trees on other sites.
7. **Fix 4** (apply JSON-LD helper to manifest path) — ensures consistent behavior.
8. **Fix 5** (`if v not in _EMPTY_VALUES`) — correctness for $0 products.