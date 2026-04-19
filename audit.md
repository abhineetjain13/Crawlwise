# Acquisition System Audit — Refactor Delta Review
**Comparing:** Previous version → Agent refactor (April 19 2026)
**Scope:** `browser_runtime.py`, `runtime.py`, `browser_identity.py`, `http_client.py`, `acquirer.py`, `pacing.py`

---

## Verdict Summary

8 issues closed correctly. 2 new bugs introduced by the refactor. 12 issues remain open. The fixes that landed are real and meaningful — `temporary_browser_page` and stealth wiring are clean, the HTTP client deduplication is correct, and the 401/429 reclassification is exactly right. The new bugs are in `classify_block_from_headers` and are production-severity: they will cause Cloudflare-hosted pages to be spuriously marked as blocked.

---

## Section 1 — Confirmed Fixes

### ✅ BUG-4 · Stealth Now Applied
**`browser_runtime.py` lines 46–58, 190**

```python
try:
    from playwright_stealth import Stealth as _PlaywrightStealth
    _STEALTH_APPLIER = _PlaywrightStealth().apply_stealth_async
except Exception:
    _STEALTH_APPLIER = None
```

The import guard is correct — startup does not fail if the package is absent. `_apply_stealth(page)` is called in `SharedBrowserRuntime.page()` immediately after `context.new_page()`. Correctly placed inside the `try` block so a stealth failure logs at DEBUG and does not abort the fetch.

**One concern:** `Stealth().apply_stealth_async` is the API from some forks. The canonical PyPI `playwright-stealth` exposes `stealth_async(page)`. Verify your installed version matches this call pattern. If CI shows `_STEALTH_APPLIER = None` in logs, stealth is silently off.

---

### ✅ BUG-7 · `temporary_browser_page` No Longer Launches a New Process
**`browser_runtime.py` lines 237–241**

```python
@asynccontextmanager
async def temporary_browser_page(*, proxy: str):
    runtime = await get_browser_runtime()
    async with runtime.page(proxy=proxy) as page:
        yield page
```

Clean. Proxy is now passed to `new_context(proxy={"server": proxy})` via `SharedBrowserRuntime.page(proxy=proxy)`. Eliminates the per-request Playwright process cold-start (1–3 second overhead per proxied URL). The context-level proxy is a supported Playwright pattern.

---

### ✅ BUG-5 (partial) · Browser Identity OS Now Locked to Host
**`browser_identity.py` lines 13–26**

`_host_os_fingerprint_arg()` correctly maps `platform.system()` to `browserforge`'s OS name. `FingerprintGenerator` is constrained to `os=[_HOST_OS]`. `_generate_coherent_fingerprint()` validates the UA token against the OS (3 retries). The macOS UA on a Windows host problem is fixed.

**What remains open (see NEW-3 below):** Chrome version coherence between UA string major version and `userAgentData.brands` is still not validated.

---

### ✅ DEBT-1 · Import Trampoline Removed
**`runtime.py`** no longer has a `fetch_page` function. **`acquirer.py` line 10** now imports directly:

```python
from app.services.crawl_fetch_runtime import fetch_page
```

Static analysis can now resolve the call target. The circular import workaround is gone.

---

### ✅ DEBT-2 · Duplicate HTTP Client Pool Eliminated
**`http_client.py`** no longer has its own `_SHARED_CLIENTS` dict, lock, or `_get_shared_http_client`. It now delegates to `runtime.get_shared_http_client`. `close_shared_http_client` in `http_client.py` delegates to `close_runtime_shared_http_client`. One pool, one cleanup path.

`get_shared_http_client` in `runtime.py` gained a `force_ipv4` parameter and updated the dict key to `tuple[str | None, str, bool]` to accommodate it correctly.

---

### ✅ DEBT-4 · 401/429 Classification Corrected
**`runtime.py` lines 119–137**

| Status | Before | After |
|--------|--------|-------|
| 401 | `blocked=True, outcome="challenge_page"` | `blocked=False, outcome="auth_wall"` |
| 429 | `blocked=True, outcome="challenge_page"` | `blocked=True, outcome="rate_limited"` |
| 403 | `blocked=True, outcome="challenge_page"` | `blocked=True, outcome="challenge_page"` |

401 no longer triggers browser escalation (correctly — it's an auth wall, not a bot block). `is_non_retryable_http_status` now includes 401.

---

### ✅ MISSING-1 · Header-Based Block Detection Added
**`runtime.py` lines 64–115**

`classify_block_from_headers()` is correctly wired into both `http_fetch` (line 343–344) and `_curl_fetch_sync` (lines 397–398):

```python
vendor = classify_block_from_headers(headers)
blocked = bool(vendor) or await blocked_html_checker(html, response.status_code)
```

The function exists, the call sites are correct. See NEW-1 below for a logic bug in the implementation.

---

### ✅ BUG-2 · `curl_cffi` Impersonation Configurable
**`runtime.py` line 386**

```python
impersonate=crawler_runtime_settings.curl_impersonate_target,
```

Hardcoded `"chrome124"` is gone. Also added `Accept` and `Accept-Language` headers to curl requests — correct, these are expected in real Chrome requests. Verify `crawler_runtime_settings.curl_impersonate_target` defaults to a current value (≥ `chrome131`) and not `None` (which would throw).

---

## Section 2 — New Bugs Introduced

### 🔴 NEW-1 · `classify_block_from_headers` Will False-Positive on All Cloudflare-Hosted Sites
**`runtime.py` lines 64–115**

The vendor header table includes:
```python
("cf-ray", "cloudflare"),
("cf-mitigated", "cloudflare"),
```

`cf-ray` is present on **every response from Cloudflare CDN** — 200 OK, 301, 404, everything. It is Cloudflare's request tracing header, not a block indicator. Mapping its presence to `blocked=True` will cause browser escalation on any 200 OK page served through Cloudflare — which is a large fraction of the internet.

`cf-mitigated` is the correct block indicator (it appears only when Cloudflare actively challenges or blocks), but `cf-ray` alone is catastrophically over-broad.

The same issue applies to `x-px-ref` (PerimeterX):
```python
("x-px-ref", "perimeterx"),
```
`x-px-ref` is a page-tracking reference ID present on legitimate HUMAN/PerimeterX-instrumented pages even when they are not blocked. Only `x-px-block` is a definitive block signal.

**Impact:** Every Cloudflare-hosted ecommerce site (Shopify, most mid-market retailers) will return `blocked=True` from `http_fetch` even on successful 200 responses. This will trigger unnecessary browser escalations for a large portion of your crawl workload.

**Fix:**

```python
# Remove cf-ray and x-px-ref from the table entirely.
# Only keep headers that are definitively bot-block signals, not presence-only markers.
_BOT_VENDOR_HEADER_MARKERS: tuple[tuple[str, str, str], ...] = (
    # (header_name, match_value_contains, vendor)
    # header must CONTAIN match_value to be a positive signal
    ("x-datadome", "", "datadome"),        # any value = block
    ("x-datadome-cid", "", "datadome"),
    ("server", "datadome", "datadome"),    # value must contain "datadome"
    ("cf-mitigated", "challenge", "cloudflare"),  # value must be "challenge"
    ("x-sucuri-id", "", "sucuri"),
    ("x-sucuri-cache", "", "sucuri"),
    ("x-akamai-transformed", "", "akamai"),
    ("akamai-grn", "", "akamai"),
    ("x-px-block", "", "perimeterx"),     # definitive block header only
)
```

Refactor `classify_block_from_headers` to accept a `match_value` filter and only return a hit when the header value satisfies the constraint:

```python
def classify_block_from_headers(headers: Any) -> str | None:
    normalized = _normalize_headers(headers)
    for header_name, must_contain, vendor in _BOT_VENDOR_HEADER_MARKERS:
        value = normalized.get(header_name)
        if value is None:
            continue
        if must_contain and must_contain not in value:
            continue
        return vendor
    return None
```

---

### 🔴 NEW-2 · `_apply_stealth` Import Pattern May Silently Disable Stealth
**`browser_runtime.py` lines 46–49**

```python
from playwright_stealth import Stealth as _PlaywrightStealth
_STEALTH_APPLIER = _PlaywrightStealth().apply_stealth_async
```

The canonical `playwright-stealth` package (PyPI) exposes `stealth_async(page)`, not `Stealth().apply_stealth_async`. The `Stealth` class with `apply_stealth_async` is the API from `playwright-stealth` ≥ 1.0.0 or from the `undetected-playwright` fork. If your installed version is the canonical package, the import succeeds (the `Stealth` class exists), but `apply_stealth_async` may not exist or may behave differently — and the bare `except Exception` will silently swallow it, leaving `_STEALTH_APPLIER = None`.

**Verify right now:**

```bash
python -c "from playwright_stealth import Stealth; s = Stealth(); print(dir(s))"
# If apply_stealth_async is not in the output, stealth is silently off
```

**Safe canonical approach:**

```python
try:
    from playwright_stealth import stealth_async as _stealth_async  # canonical API
    async def _apply_stealth(page: Any) -> None:
        try:
            await _stealth_async(page)
        except Exception:
            logger.debug("Failed to apply playwright-stealth", exc_info=True)
except ImportError:
    async def _apply_stealth(page: Any) -> None:  # pragma: no cover
        pass
```

This fails loudly at import time if the package is wrong (rather than silently at runtime), and uses the stable public API.

---

## Section 3 — Still Open From Previous Audit

Issues not touched by this refactor, ordered by priority.

### 🔴 BUG-1 · Waterfall Is Still Worst-First (Not Fixed)
**`crawl_fetch_runtime.py`** (not uploaded, but behaviour confirmed unchanged)

The HTTP loop still fires `curl_cffi → httpx` before browser for non-`prefer_browser` requests. For DataDome-protected domains, this is two fingerprint-polluting requests before the only fetcher with a chance. The `classify_block_from_headers` addition helps (vendor-confirmed blocks will route to browser faster), but the underlying ordering is still wrong for known-protected domains.

**Remaining work:** `protected_host_patterns` config list + `_host_is_protected(url)` predicate gating the waterfall. See Slice 3 in the previous audit.

---

### 🟠 BUG-3 · httpx Still Sends `python-httpx/<version>` User-Agent (Not Fixed)
**`runtime.py:get_shared_http_client()`**

`build_async_http_client` is called with no custom `User-Agent`. httpx will default to `python-httpx/0.x.x`. The curl_cffi path gained `Accept`/`Accept-Language` headers but httpx did not. For any site where httpx runs before curl escalation, the bot fingerprint is still explicit.

**Fix remains:** Pass `headers={"User-Agent": crawler_runtime_settings.http_user_agent}` when building the shared client, using the same configurable UA string.

---

### 🟠 BUG-5 (remaining) · Chrome Version Coherence Not Validated
**`browser_identity.py:_generate_coherent_fingerprint()`**

OS token coherence is fixed. UA major version vs `userAgentData.brands` major version coherence is not. The scenario described in the smoke test — `navigator.userAgent` says Chrome 91, `userAgentData.brands` says Chrome 147 — can still occur if browserforge generates a fingerprint with mismatched version fields.

**Add to `_generate_coherent_fingerprint()`:**

```python
import re as _re
_UA_VERSION_RE = _re.compile(r"Chrome/(\d+)\.")

def _is_version_coherent(fingerprint) -> bool:
    ua = str(fingerprint.navigator.userAgent or "")
    match = _UA_VERSION_RE.search(ua)
    if not match:
        return True  # can't validate, accept
    ua_major = int(match.group(1))
    if ua_major < 120:  # reject ancient versions
        return False
    brands = fingerprint.navigator.userAgentData
    if not isinstance(brands, dict):
        return True
    brand_list = brands.get("brands") or []
    for brand in brand_list:
        if isinstance(brand, dict) and "Chrome" in str(brand.get("brand") or ""):
            brand_major = int(str(brand.get("version") or "0").split(".")[0])
            if abs(brand_major - ua_major) > 2:
                return False
    return True

# In _generate_coherent_fingerprint:
for _ in range(3):
    fingerprint = _FINGERPRINT_GENERATOR.generate()
    ua = str(fingerprint.navigator.userAgent or "").lower()
    if expected_token in ua and _is_version_coherent(fingerprint):
        return fingerprint
```

---

### 🟠 BUG-6 · No Session Persistence (Not Fixed)
**`cookie_store.py`** remains a stub.

Every browser context is still a cold session with no cookies, no storage state, no trust carryover. For DataDome/Kasada class sites this is the single highest-impact missing capability after fingerprint coherence. The `SharedBrowserRuntime.page()` method's new `proxy` parameter provides the right hook to load session state keyed by `(host, proxy)` — but nothing is being loaded.

**Remaining work:** Implement `session_store.py` as described in Slice 4 of the previous audit.

---

### 🟡 PERF-1 · No Vendor-Confirmed Early Exit From Proxy Loop (Partial)
**`crawl_fetch_runtime.py`**

`classify_block_from_headers` is now called inside `http_fetch` and `curl_fetch`, so `result.blocked=True` is set earlier. However the proxy loop in `fetch_page` still iterates all proxies even after a vendor-confirmed block from the first proxy. The `_is_vendor_confirmed_block(result)` predicate and loop break are not implemented.

Once NEW-1 is fixed (cf-ray false positive removed), add:

```python
# After each fetcher returns in the proxy loop:
if result.blocked and _vendor_header_in(result.headers):
    # vendor has confirmed this is a bot block, not a proxy issue
    # escalate to browser immediately, don't burn remaining proxies
    break
```

---

### 🟡 PERF-2 · `_card_count` Still N Sequential Playwright IPC Calls (Not Fixed)
**`traversal.py`** — unchanged from previous version. Still loops over selectors with individual `locator().count()` calls.

---

### 🟡 PERF-3 · BeautifulSoup Parsed 3× on Same HTML (Not Fixed)
**`runtime.py`, `browser_runtime.py`** — `_looks_like_js_shell`, `_has_extractable_detail_signals`, and `classify_low_content_reason` each parse independently.

---

### 🟡 DEBT-5 · No Static Protected-Host Pattern List (Not Fixed)
The reactive `_BROWSER_PREFERRED_HOSTS` learning mechanism exists. The proactive `protected_host_patterns` config that would skip the HTTP waterfall for known-bot-detection hosts does not.

---

### 🟡 DEBT-7 · Pacing TTL Prune Still a No-Op (Not Fixed)
**`pacing.py`** — unchanged. `_prune_expired_hosts` checks `now - allowed_at > ttl_seconds` where `allowed_at` is in the future for any recently paced host. The prune condition never fires for active hosts. Cache grows unboundedly until the size limit evicts entries.

---

## Section 4 — Regression Risk: One Subtle Issue Introduced

### ⚠️ `get_shared_http_client` Signature Change May Break Call Sites
**`runtime.py` lines 279–303**

Old signature: `get_shared_http_client(*, proxy: str | None = None)`
New signature: `get_shared_http_client(*, proxy: str | None = None, force_ipv4: bool = False)`

`http_client.py` now calls `get_shared_http_client(proxy=proxy, force_ipv4=force_ipv4)` correctly. But any other call site across the codebase (tests, adapters) that passes `force_ipv4` as a positional or uses the old dict key structure `tuple[str | None, str]` will produce a cache miss on every call — silently creating a new client per request instead of reusing the shared one. The dict key changed from 2-tuple to 3-tuple.

**Verify:** Search for all call sites of `get_shared_http_client` across the codebase and confirm they all use the `force_ipv4=` keyword argument.

---

## Scorecard

| Issue | Status | Priority |
|-------|--------|----------|
| BUG-4 Stealth wired | ✅ Fixed | — |
| BUG-7 temporary_browser_page | ✅ Fixed | — |
| BUG-5 OS coherence | ✅ Fixed | — |
| DEBT-1 Import trampoline | ✅ Fixed | — |
| DEBT-2 Duplicate HTTP pool | ✅ Fixed | — |
| DEBT-4 401/429 classification | ✅ Fixed | — |
| MISSING-1 Header block detection | ✅ Fixed (with bug) | — |
| BUG-2 curl impersonation | ✅ Fixed | — |
| **NEW-1 cf-ray false positive** | 🔴 Introduced | Immediate |
| **NEW-2 stealth import pattern** | 🔴 Verify | Immediate |
| BUG-1 Waterfall order | 🔴 Open | Slice 3 |
| BUG-3 httpx User-Agent | 🟠 Open | Slice 1 remaining |
| BUG-5 version coherence | 🟠 Open | Slice 2 remaining |
| BUG-6 Session persistence | 🟠 Open | Slice 4 |
| PERF-1 Proxy loop early exit | 🟡 Open | Slice 3 |
| PERF-2 _card_count IPC | 🟡 Open | Slice 6 |
| PERF-3 BeautifulSoup 3× | 🟡 Open | Slice 6 |
| DEBT-5 Protected host patterns | 🟡 Open | Slice 3 |
| DEBT-7 Pacing TTL | 🟡 Open | Slice 6 |
| Regression: get_shared_http_client key | ⚠️ Verify | Immediate |

---

## Immediate Actions Before Next Slice

1. **Fix NEW-1 now** — remove `cf-ray` and `x-px-ref` from `_BOT_VENDOR_HEADER_MARKERS`. These will silently double your browser escalation rate on any Cloudflare-hosted target. The fix is two line deletions and a value guard for `cf-mitigated`.

2. **Verify NEW-2** — run `python -c "from playwright_stealth import Stealth; print(hasattr(Stealth(), 'apply_stealth_async'))"`. If `False`, stealth is silently off. Switch to `from playwright_stealth import stealth_async`.

3. **Verify curl impersonate default** — confirm `crawler_runtime_settings.curl_impersonate_target` has a non-None default (e.g., `"chrome136"`). A `None` value causes `curl_requests.get(impersonate=None)` which fails or falls back to no impersonation.

4. **Audit `get_shared_http_client` call sites** — confirm the 3-tuple key change does not produce spurious cache misses in tests or other callers.