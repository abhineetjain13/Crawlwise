# Extraction Enhancement Plan

Last updated: 2026-04-18
Scope: Acquisition, extraction, and normalization pipeline improvements
Status: Draft — pre-implementation

---

## Current Stack Reality (from grep)

Before prescribing anything, here is what is actually in use post-refactor:

| Concern | Library | Status |
|---|---|---|
| HTML parsing (all adapters + extractors) | `beautifulsoup4` with `html.parser` | Active, widespread |
| XPath extraction | `lxml` via `xpath_service.py` | Active |
| JSON-LD parsing | Custom `parse_json_ld()` in `structured_sources.py` | Active |
| Hydrated state (`__NEXT_DATA__` etc.) | Custom `harvest_js_state_objects()` in `structured_sources.py` | Active |
| JS state field mapping | `glom` in `js_state_mapper.py` | Active |
| XHR field mapping | `jmespath` in `network_payload_mapper.py` | Active, Greenhouse-only |
| Price normalization | `price-parser` | Package declared; all service-layer usage removed in refactor — needs full reimplementation |
| Structured data (microdata, OG) | `extruct` | Package declared; all service-layer usage removed in refactor — needs full reimplementation |
| Fast HTML parsing | `selectolax` | Not yet a declared package; needs add + full implementation |
| CSS selector / script regex | `parsel` | Not yet a declared package; needs add + full implementation |
| Fingerprint hardening | `browserforge` | Package declared; service-layer wiring removed in refactor — needs full reimplementation |

---

## Security Constraint (Feedonomics Integration)

- Python/PyPI packages only — no outbound runtime API calls
- No eval/exec of remotely-sourced strings
- `bypass_csp=False` on all Playwright contexts — mandatory
- `service_workers="block"` on all Playwright contexts — prevents SW from hiding XHR
- No persistent cookie storage beyond policy-approved files (INVARIANTS.md §23)
- `robots.txt` compliance required for all crawl targets — legal/ToS exposure for
  Feedonomics merchant partners

---

## Gap Analysis

### Gap 1 — extruct: microdata + Open Graph coverage (highest priority)

`extruct` covers JSON-LD, microdata, Open Graph, RDFa, and hCard in a single HTML pass.
The package is declared in `pyproject.toml` but its service-layer integration was removed
during the refactor. The current `parse_json_ld()` in `structured_sources.py` covers
JSON-LD only. Microdata and Open Graph extraction need to be fully reimplemented against
the post-refactor extraction pipeline.

**What's missed without it:** Walmart and older catalogue sites that use microdata
`itemprop` tags for price/brand/sku instead of JSON-LD. Open Graph product meta tags
that carry price and availability on sites without structured data.

---

### Gap 2 — BeautifulSoup with `html.parser` on every parse (performance)

Every adapter and both `detail_extractor.py` and `listing_extractor.py` call
`BeautifulSoup(html, "html.parser")` — Python's built-in parser. On large HTML
documents (50–200KB ecommerce PDPs) this is the single biggest CPU cost in the
extraction path. `selectolax` with the Lexbor engine is 10–30x faster for the same
CSS selector queries and handles malformed HTML better than `html.parser`.

`selectolax` is not yet a declared dependency and has no prior implementation in the
codebase. It needs to be added to `pyproject.toml` and built into the extraction
path from scratch. The split would be: `selectolax` for CSS-selector-only paths;
BeautifulSoup + `lxml` stays for XPath paths (already active in `xpath_service.py`).

---

### Gap 3 — XHR interception is Greenhouse-only

`network_payload_mapper.py` has one surface: `job_detail` with a hardcoded Greenhouse
response shape. The XHR capture machinery in acquisition presumably feeds into this,
but the mapper has no ecommerce path and no generic fallback for other job platforms.
`jmespath` is already imported — the specs just don't exist for other platforms.

---

### Gap 4 — `js_state_mapper.py` has no ecommerce price/sku/variants path

`NEXT_DATA_ECOMMERCE_SPEC` in `js_state_mapper.py` maps `title`, `brand`, `vendor`,
`handle`, `description` — but not `price`, `sku`, `images`, `variants`, `in_stock`.
These are all present in standard Shopify/Next.js `__NEXT_DATA__` payloads. The fields
exist in the state tree but are never mapped.

---

### Gap 5 — `_extract_job_sections()` is duplicated verbatim

`js_state_mapper.py:_extract_job_sections()` and `network_payload_mapper.py:_extract_job_sections()`
are byte-for-byte identical functions. Same for `_html_to_text()`. DRY violation,
maintenance trap.

---

### Gap 6 — No robots.txt check at dispatch time

There is no `robots.txt` compliance check before URLs are dispatched. Uses stdlib
`urllib.robotparser` — no new package. Needs to be written and wired into dispatch.
Required for Feedonomics merchant partner ToS compliance.

---

### Gap 7 — No CSS+regex chaining for script-text extraction

Several adapters use BeautifulSoup + manual `re.search()` to extract values buried in
inline `<script>` text (e.g. price in a JS assignment string). `parsel` exposes `.re()`
and `.re_first()` directly on selectors, eliminating the two-step find-then-regex pattern.
`parsel` is not yet a declared dependency. It uses `lxml` internally (already a dep) so
there is no new C extension to compile. Needs adding to `pyproject.toml` and
implementing across affected adapters from scratch.

---

### Gap 8 — Nuxt 3 `__NUXT_DATA__` deserialization

`structured_sources.py` captures `__NUXT_DATA__` as raw JSON but the Nuxt 3 format is
an array-based serialization (not a plain object). The current `_find_product_payload()`
recursive search will fail on it silently — it iterates values but the array encoding
requires a separate revivor pass.

---

### Gap 9 — No tracking parameter stripping on extracted URLs

Extracted product and job URLs frequently carry tracking parameters (`utm_*`, `gclid`,
`ref`, `source`, `sid`) that cause duplicate records for the same canonical page.
`w3lib.url.url_query_cleaner` strips these at normalization time. `w3lib` is a
transitive dependency of several packages in the stack but is not declared directly
in `pyproject.toml` and has no service-layer usage. Needs explicit declaration and
a new normalization function built around it.

---

### Gap 10 — `browserforge` fingerprint generation not implemented in service layer

`browserforge` generates realistic browser fingerprints (headers, user-agent, viewport,
platform) correlated to real browser population distributions. The package is declared
in `pyproject.toml` but its service-layer integration was removed during the refactor —
the Playwright context factory currently uses static hardcoded values. Needs a full
reimplementation in the browser context factory to replace static UA/viewport strings
with dynamically generated, statistically plausible fingerprint combinations.

---

## Improvement Proposals

### P1 — Reimplement extruct for microdata + Open Graph

**Files:** `structured_sources.py`, `detail_extractor.py`
**Change:** Reimplement `extruct.extract()` integration alongside the existing
`parse_json_ld()`. The package is declared but has no service-layer code — this is a
full implementation task, not a config change. Merge microdata and Open Graph
candidates into the existing candidate pipeline.

```python
from extruct import extract as extruct_extract

def extract_all_structured(html: str, url: str) -> dict:
    return extruct_extract(
        html,
        base_url=url,
        syntaxes=["microdata", "opengraph"],  # json-ld already handled natively
        uniform=True,
        return_html_node=False,
    )
```

Failure modes to handle:
- `uniform=True` flattens nested arrays — unwrap before candidate insertion
- Multiple microdata items of same `@type` — collect all, not just first
- Empty syntaxes list returns empty dict, not exception — safe default

**Expected yield:** Recovers price/brand/sku on Walmart-family and older catalogue
sites. Adds OG-based image URLs on sites with no JSON-LD.

---

### P2 — Implement selectolax for CSS-selector-only DOM paths

**Files:** All adapters, `detail_extractor.py`, `listing_extractor.py`
**Change:** Add `selectolax` to `pyproject.toml` and implement it as the parser for
all CSS-selector-only paths. This is a new dependency and a full implementation — no
prior code exists in the service layer. For paths that currently use
`soup.select()` / `soup.select_one()` / `soup.find()` with CSS selectors only,
replace with selectolax. Keep BeautifulSoup + lxml for XPath paths.

```python
from selectolax.parser import HTMLParser  # Lexbor engine — handles malformed HTML

tree = HTMLParser(html)
price_node = tree.css_first(".price-now, [itemprop='price']")
price = price_node.text(strip=True) if price_node else None

# For attribute extraction:
img_url = tree.css_first("img.product-hero")
src = img_url.attributes.get("src") if img_url else None
```

Key difference from BeautifulSoup:
- `selectolax` raises no exception on malformed HTML — silently best-effort parses
- `.text(strip=True)` is equivalent to `.get_text(strip=True)` but 10–30x faster
- Does NOT support XPath — keep lxml for those paths
- `tree.css()` returns a generator, not a list — do not call `len()` on it

**Add to pyproject.toml:** `selectolax>=0.3.21` (new dependency)

**Expected yield:** ~40% reduction in extraction CPU time on large PDPs.
Enables higher Celery worker concurrency for same hardware budget.

---

### P3 — Fill missing ecommerce fields in `js_state_mapper.py`

**File:** `js_state_mapper.py`
**Change:** Extend `NEXT_DATA_ECOMMERCE_SPEC` with price, sku, images, variants,
in_stock. These paths are present in all standard Shopify/Next.js `__NEXT_DATA__`
payloads.

```python
from glom import Coalesce, Iter, T

NEXT_DATA_ECOMMERCE_SPEC = {
    # existing fields ...
    "price": Coalesce(
        "props.pageProps.product.variants.0.price",
        "props.pageProps.product.price",
        "props.pageProps.productData.price",
        default=None,
    ),
    "compare_at_price": Coalesce(
        "props.pageProps.product.variants.0.compare_at_price",
        default=None,
    ),
    "sku": Coalesce(
        "props.pageProps.product.variants.0.sku",
        "props.pageProps.product.sku",
        default=None,
    ),
    "in_stock": Coalesce(
        "props.pageProps.product.variants.0.available",
        "props.pageProps.product.available",
        default=None,
    ),
    "image_url": Coalesce(
        "props.pageProps.product.images.0.src",
        "props.pageProps.product.featured_image",
        default=None,
    ),
}
```

**Expected yield:** Recovers price and availability on all Shopify-based storefronts
that currently fall through to DOM extraction. Eliminates LLM fallback for these.

---

### P4 — Expand XHR mapper beyond Greenhouse

**File:** `network_payload_mapper.py`
**Change:** Add ecommerce XHR spec and generic job detail fallback using jmespath.
The current mapper is hardcoded to one Greenhouse response shape.

```python
ECOMMERCE_XHR_SPEC = {
    "title":    ["product.title", "data.name", "result.productName"],
    "price":    ["product.price.amount", "offers[0].price", "pricing.current.value"],
    "sku":      ["product.sku", "product.mpn", "data.itemCode"],
    "brand":    ["product.brand.name", "product.brand", "data.brand"],
    "in_stock": ["product.availability", "data.inStock"],
    "image_url":["product.images[0].url", "media[0].url"],
}

GENERIC_JOB_XHR_SPEC = {
    "title":    ["job.title", "posting.jobTitle", "data.positionTitle"],
    "company":  ["job.company.name", "employer.displayName", "company.name"],
    "location": ["job.location", "locations[0].city", "jobLocation.address.addressLocality"],
    "salary":   ["compensation.salary", "job.salaryRange", "baseSalary.value"],
    "remote":   ["job.remote", "workplaceType", "location.remote"],
}

def _try_paths(body: dict, paths: list[str]) -> Any:
    for path in paths:
        result = jmespath.search(path, body)
        if result not in (None, "", [], {}):
            return result
    return None
```

Specs must live in `pipeline_config.py` per INVARIANTS.md §3 — not inline.

---

### P5 — Deduplicate `_extract_job_sections` and `_html_to_text`

**Files:** `js_state_mapper.py`, `network_payload_mapper.py`
**Change:** Move both functions to a shared `html_text_utils.py` module.
Import from there in both files. Zero behavior change, eliminates the DRY violation.

---

### P6 — Implement parsel for script-text regex extraction in adapters

**Add to pyproject.toml:** `parsel>=1.9.0` (new dependency; uses `lxml` already in deps)

Implement `parsel` across adapters that currently use the two-step
`BeautifulSoup.find("script") + re.search(pattern, script.string)` pattern.
No prior parsel code exists in the service layer — full implementation needed:

```python
from parsel import Selector

sel = Selector(text=html)

# Instead of: soup.find("script", id="__NEXT_DATA__").string
next_data_raw = sel.css("script#__NEXT_DATA__::text").get()

# Instead of: re.search(r'price:\s*(\d+)', script.string)
price_raw = sel.re_first(r'"currentPrice"\s*:\s*"?([0-9.,]+)"?')

# CSS + XPath chain in one expression:
img_src = sel.css("img.product-image").xpath("@data-src").get()
```

Note: `.re()` returns a list of strings and cannot be further chained — terminal operation.

---

### P7 — Nuxt 3 `__NUXT_DATA__` revivor

**File:** `structured_sources.py`
**Change:** When `__NUXT_DATA__` is captured as an array, apply the Nuxt 3 array
revivor before passing to `_find_product_payload()`. The Nuxt 3 format stores data as
`[nodes, reviver_index]` where the first element is a flat array of values and the
second is the tree structure.

```python
def _deserialize_nuxt3(raw: list) -> dict:
    # Nuxt 3 serializes as [data_array, reducer_map]
    # Simple heuristic: if it's a list where first element is also a list,
    # attempt to find any dict within it that looks like product data
    if not isinstance(raw, list):
        return {}
    for item in raw:
        if isinstance(item, dict):
            result = _find_product_payload(item)
            if result:
                return result
        elif isinstance(item, list):
            for sub in item:
                if isinstance(sub, dict):
                    result = _find_product_payload(sub)
                    if result:
                        return result
    return {}
```

---

### P8 — robots.txt compliance at dispatch

**New file:** `backend/app/services/robots_policy.py`
**Wiring:** Call before URL is dispatched in `crawl_service.py`

```python
from functools import lru_cache
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

@lru_cache(maxsize=512)
def _fetch_robots(base_url: str) -> RobotFileParser:
    rp = RobotFileParser(f"{base_url}/robots.txt")
    rp.read()
    return rp

def is_crawlable(url: str, user_agent: str = "*") -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    try:
        return _fetch_robots(base).can_fetch(user_agent, url)
    except Exception:
        return True  # fail open — do not block on robots.txt fetch errors
```

Uses stdlib only (`urllib.robotparser`). No new dependency.

**Note:** Fail-open on robots.txt fetch errors (network timeout, 404) is intentional —
a missing robots.txt does not mean disallowed. Cache is bounded by `maxsize=512`.

---

### P9 — Implement URL tracking parameter stripping

**File:** `field_value_utils.py` or a new `url_utils.py`
**Add to pyproject.toml:** `w3lib>=2.2.1` (explicit declaration; currently only a
transitive dep with no direct service-layer usage)
**Change:** Implement a normalization function using `w3lib.url.url_query_cleaner`
applied to all extracted product/job URLs before they enter the candidate pipeline.
No prior w3lib code exists in the service layer — full implementation needed.

```python
from w3lib.url import url_query_cleaner

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "gclid", "fbclid", "msclkid", "ref", "source", "sid", "mc_cid", "mc_eid",
}

def strip_tracking_params(url: str) -> str:
    return url_query_cleaner(url, parameterlist=list(TRACKING_PARAMS), remove=True)
```

`w3lib` is a transitive dependency — no new package needed, just an explicit import.

---

### P10 — Reimplement browserforge in Playwright context factory

**File:** `browser_client.py` or equivalent Playwright context factory
**Change:** The package is declared but its service-layer integration was removed in
the refactor. Reimplement `browserforge` fingerprint generation in the Playwright
context factory to replace the current static UA/viewport strings:

```python
from browserforge.headers import HeaderGenerator
from browserforge.fingerprints import FingerprintGenerator

fp_gen = FingerprintGenerator(browser="chrome", os="windows")
header_gen = HeaderGenerator(browser="chrome", os="windows", device="desktop")

fingerprint = fp_gen.generate()
headers = header_gen.generate()

context = await browser.new_context(
    user_agent=fingerprint.navigator.user_agent,
    viewport={"width": fingerprint.screen.width, "height": fingerprint.screen.height},
    locale=fingerprint.navigator.language,
    extra_http_headers=dict(headers),
    service_workers="block",
    bypass_csp=False,   # never bypass — Feedonomics security requirement
)
```

`FingerprintGenerator` draws from a real browser population distribution — each context
gets a statistically plausible combination of UA, viewport, and platform rather than a
static string. This is the gap between basic Playwright stealth and actual fingerprint
consistency.

---

### P11 — ARIA snapshot for hidden content expansion (Playwright path only)

This is genuinely novel vs competitors. Most crawlers click "View More" by CSS text
matching, which breaks on translated UIs or sites that rename the button. Querying the
**accessibility tree** finds interactive elements by semantic role and name regardless
of CSS class or label text language.

```python
async def expand_collapsed_sections(page, max_clicks: int = 6) -> list[str]:
    KEYWORDS = {
        "specifications", "spec", "details", "view more", "show more",
        "full description", "requirements", "qualifications", "responsibilities",
        "show all", "read more", "see more", "expand",
    }
    expanded = []
    for _ in range(max_clicks):
        snapshot = await page.accessibility.snapshot()
        target = _find_expandable(snapshot, KEYWORDS) if snapshot else None
        if not target:
            break
        locator = page.get_by_role(target["role"], name=target["name"], exact=False)
        if not await locator.is_visible(timeout=1000):
            break
        await locator.click()
        # Wait for DOM mutation, not networkidle.
        # networkidle fires immediately on cached accordion toggles (no network call).
        await page.wait_for_function(
            "() => document.readyState === 'complete'", timeout=2000
        )
        expanded.append(target["name"])
    return expanded

def _find_expandable(node: dict, keywords: set[str]) -> dict | None:
    name = (node.get("name") or "").lower()
    role = node.get("role", "")
    if role in ("button", "tab", "treeitem") and any(k in name for k in keywords):
        return node
    for child in node.get("children") or []:
        result = _find_expandable(child, keywords)
        if result:
            return result
    return None
```

**Why this gives an edge:** Competitors using CSS text selectors break when sites run
A/B tests that rename button labels. This approach is layout-agnostic and
internationalization-safe.

---

### P12 — Candidate fingerprinting to detect extraction regressions (novel)

**Concept:** After each extraction run, hash the set of field names and non-null value
count for the record. Store as `source_trace.extraction_fingerprint`. On re-crawl,
compare fingerprints. A fingerprint drop (fewer fields, lower value count) without a
corresponding HTTP status change is a signal that the page structure changed and the
extractor silently regressed.

This requires no external library — just a short hash of the record's field coverage:

```python
import hashlib

def extraction_fingerprint(record_data: dict) -> str:
    populated = sorted(k for k, v in record_data.items() if v not in (None, "", [], {}))
    payload = f"{len(populated)}:{','.join(populated)}"
    return hashlib.md5(payload.encode()).hexdigest()[:12]
```

**Why this gives an edge:** Silent extraction regressions (page redesign causes fields
to return empty) are invisible in current monitoring because the run still "succeeds".
This fingerprint enables automated regression detection without adding observability
infrastructure — it is pure data in the existing `source_trace`.

---

## Implementation Order

| Priority | Item | Dep status | Effort | Impact |
|---|---|---|---|---|
| P3 | Fill price/sku/variants in `js_state_mapper.py` | No new dep | Low | Very High |
| P5 | Deduplicate `_extract_job_sections` / `_html_to_text` | No new dep | Low | Code health |
| P1 | Reimplement `extruct` for microdata + OG | Package declared, service code removed | Medium | High |
| P4 | Expand XHR mapper beyond Greenhouse | No new dep | Medium | High |
| P7 | Nuxt 3 `__NUXT_DATA__` revivor | No new dep | Low | Medium |
| P10 | Reimplement `browserforge` in context factory | Package declared, service code removed | Medium | Medium |
| P12 | Extraction fingerprint regression detection | No new dep | Low | Ops edge |
| P9 | URL tracking param stripping | `w3lib` — add explicit dep + implement | Low | Medium |
| P8 | robots.txt compliance | stdlib only, implement from scratch | Low | Compliance |
| P2 | Implement `selectolax` for CSS paths | New dep + full implementation | Medium | Perf |
| P6 | Implement `parsel` for script-regex extraction | New dep + full implementation | Low | Medium |
| P11 | ARIA snapshot hidden content expansion | No new dep, implement from scratch | Medium | Medium |

**Packages declared in `pyproject.toml` needing full service-layer reimplementation:**
`extruct`, `glom` (partial — ecommerce fields missing), `jmespath` (partial — ecommerce missing),
`price-parser`, `browserforge`

**New packages to add to `pyproject.toml`:** `selectolax`, `parsel`, `w3lib` (explicit)

---

## Explicitly Out of Scope

| Item | Reason |
|---|---|
| zyte-common-items / Zyte API | Third-party service / schema ownership conflict |
| crawl4ai, Apify, Diffbot platforms | Third-party paid services |
| trafilatura | Targets article boilerplate removal, not structured field extraction |
| Scrapy / Crawlee as framework replacement | Architectural swap, not additive |
| AI-powered selector synthesis at runtime | Non-deterministic; violates INVARIANTS.md §3 |
| Per-site selector CRUD / site memory | Deleted subsystem per INVARIANTS.md §29 |
| `playwright-stealth` npm | Node.js only; `playwright-stealth` Python is in deps |
| `bypass_csp=True` in any context | Feedonomics security constraint — never |
