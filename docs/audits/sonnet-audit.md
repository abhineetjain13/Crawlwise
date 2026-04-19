# Acquisition System Audit — CrawlerAI
**Scope:** `browser_runtime.py`, `runtime.py`, `crawl_fetch_runtime.py`, `browser_identity.py`, `traversal.py`, `acquirer.py`, `http_client.py`, `pacing.py`, `_batch_runtime.py`, `cookie_store.py`
**Against:** INVARIANTS.md + Smoke test (AutoZone / DataDome 403)

---

## Executive Summary

The acquisition system has a structurally sound design — the `PageFetchResult` contract is clean, the traversal state machine is well-typed, and the block classification logic is genuinely good. The core problem is that the **runtime layering defeats itself**: every hardening mechanism (curl impersonation, browser identity, stealth, session persistence) is either misconfigured, absent, or bypassed by the waterfall ordering. The result for any DataDome / Cloudflare class target is: **all three fetchers fail in sequence, the IP gets deeper into the block list on every attempt, and the browser escalation arrives too late with no stealth and no trusted session state.**

18 distinct issues identified, grouped by severity.

---

## Category 1 — Critical Bugs (Break Protected-Site Acquisition)

### BUG-1 · Waterfall Ordering Is Worst-First for Protected Domains
**File:** `crawl_fetch_runtime.py:fetch_page()` (HTTP loop ~line 200)

For any protected domain the correct fetch order is `browser → curl_cffi → httpx`. The current order is `curl_cffi → httpx → browser`. On sites with DataDome, Kasada, or PerimeterX:

1. `curl_cffi` fires — gets 403 + `x-datadome: protected` header.
2. `httpx` fires — explicitly tagged `Python HTTPX` in the vendor's botName field.
3. Both results are logged as "blocked" and the browser is tried — but by now the IP has accumulated two new negative signals in DataDome's risk model for that session.

The correct policy: any domain in a static `PROTECTED_HOST_PATTERNS` set **must never touch `httpx` or a plain `curl_cffi` session**. The waterfall should be gated before it starts.

**Fix:** Add a `_host_requires_browser_only(url)` predicate that checks against a config-driven `protected_host_patterns` list. If true, skip the HTTP loop entirely and go directly to browser. This is structurally the same as the existing `requires_browser` platform policy path — just data-driven.

---

### BUG-2 · `curl_cffi` Hardcoded to `chrome124` — Over a Year Stale
**File:** `runtime.py:_curl_fetch_sync()` line 322

```python
response = curl_requests.get(url, impersonate="chrome124", ...)
```

Chrome 124 shipped April 2024. `curl_cffi` ≥ 0.7 supports through `chrome136`. AutoZone's DataDome deployment fingerprints the TLS ClientHello JA3/JA4 hash and the HTTP/2 SETTINGS frame — a stale impersonation value is immediately identifiable.

**Available impersonation targets in `curl_cffi` 0.7+:** `chrome124`, `chrome131`, `chrome133`, `chrome136`, `edge133`, `safari18_0`, `safari18_2`.

**Fix:** Rotate the impersonation target per-request from a weighted list biased toward the two most recent Chrome versions. Accept the value from `crawler_runtime_settings.curl_cffi_impersonate_target` so it's tunable without deploys.

```python
import random
_CURL_CFFI_TARGETS = ["chrome131", "chrome133", "chrome136", "chrome136"]  # weighted toward latest
impersonate = crawler_runtime_settings.curl_cffi_impersonate_target or random.choice(_CURL_CFFI_TARGETS)
```

---

### BUG-3 · `httpx` Sends `python-httpx/<version>` User-Agent
**File:** `runtime.py:http_fetch()` / `http_client.py`

`build_async_http_client` is called with no custom `User-Agent` header. httpx default is `python-httpx/0.x.x`. The smoke test literally showed AutoZone's DataDome setting `datadome_analytics_botName=Python HTTPX`. This is not a borderline signal — it is an exact-match bot label.

**Fix (minimal):** Pass a realistic browser UA in `build_async_http_client` by default. At minimum use a static recent Chrome string. Better: pull `user_agent` from a `BrowserIdentity` so the http and browser paths share a coherent UA.

```python
# In build_async_http_client or wherever headers are assembled:
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"}
```

---

### BUG-4 · `playwright-stealth` Installed but Never Applied
**File:** `browser_runtime.py:SharedBrowserRuntime.page()` line 177

```python
context = await self._browser.new_context(**self._build_context_options())
page = await context.new_page()
# stealth is never applied here
```

`playwright-stealth` is in `pyproject.toml`. `navigator.webdriver` is currently exposed. DataDome specifically checks for this. The fix is one call:

```python
from playwright_stealth import stealth_async
page = await context.new_page()
await stealth_async(page)
```

**Caveat from smoke test:** stealth alone did not bypass AutoZone. It removes `navigator.webdriver` but cannot fix IP reputation or incoherent fingerprints. Apply it unconditionally — it eliminates at least one detection vector — but do not treat it as a bypass.

---

### BUG-5 · Browser Identity Is Incoherent Across Dimensions
**File:** `browser_identity.py:create_browser_identity()`

The smoke test recorded:
- `navigator.userAgent`: macOS Chrome 91
- `navigator.platform`: Win32
- `navigator.userAgentData.platform`: macOS
- `navigator.userAgentData.brands`: Chrome 147

Four incoherence vectors simultaneously:

1. **OS mismatch:** macOS UA string + Win32 platform. These must match.
2. **UA version vs brands mismatch:** UA says Chrome 91, `userAgentData.brands` says 147. The UA major version and the `brands` array major version must be identical.
3. **Stale major version:** Chrome 91 was released May 2021. No real user is on it. Bot detection models weight this heavily.
4. **Header drops are incomplete:** `_HEADER_DROP_KEYS` drops `user-agent` from extra_http_headers, but `sec-fetch-*` headers should be conditionally reconstructed per-navigation, not dropped wholesale. A real Chrome always sends these on same-origin navigations.

**Fix:** Constrain `FingerprintGenerator` to the actual host OS + a browser version within 2 major versions of current stable. Use `platform.system()` to lock OS at startup. After generation, validate the identity for internal coherence before accepting it.

```python
import platform as _platform
import sys

def _host_os_fingerprint_arg() -> str:
    sys_platform = _platform.system().lower()
    if sys_platform == "darwin":
        return "macos"
    if sys_platform == "linux":
        return "linux"
    return "windows"

_FINGERPRINT_GENERATOR = FingerprintGenerator(
    browser=FingerprintConfig.browser,
    os=[_host_os_fingerprint_arg()],  # lock to actual host
    device=FingerprintConfig.device,
    locale=FingerprintConfig.locale,
)
```

Then validate after generation: assert `userAgent` platform token matches `userAgentData.platform`. If not, regenerate (max 3 attempts before using a safe static fallback).

---

### BUG-6 · Cookie / Session State Never Persisted — Every Request is a Cold Session
**File:** `cookie_store.py` (stub), `browser_runtime.py:SharedBrowserRuntime.page()` line 177

`validate_cookie_policy_config()` returns `None`. Every `new_context()` call creates a fresh context with no storage state. For DataDome-class anti-bots, session trust is a major factor — a session that has never loaded the homepage, never moved a mouse, and carries no cookies will always score higher risk than one with a warmed-up profile.

**Fix — Minimal (storage state file per host):**

```python
import json, pathlib, time

_STATE_DIR = pathlib.Path(settings.browser_storage_state_dir)  # from config

async def _load_storage_state(host: str) -> dict | None:
    path = _STATE_DIR / f"{host}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if time.time() - data.get("saved_at", 0) > 3600:  # 1h TTL
            return None
        return data.get("state")
    except Exception:
        return None

async def _save_storage_state(host: str, context) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = await context.storage_state()
    path = _STATE_DIR / f"{host}.json"
    path.write_text(json.dumps({"saved_at": time.time(), "state": state}))
```

Pass `storage_state=loaded_state` to `browser.new_context()`. Save state after any non-blocked successful fetch.

This does not require a full cookie policy implementation — just host-keyed JSON files with TTL. INVARIANT-6 (safety and policy boundaries) is satisfied as long as cross-domain state is never mixed.

---

### BUG-7 · `temporary_browser_page` Launches a Fresh Playwright Instance per Proxied Request
**File:** `browser_runtime.py:temporary_browser_page()` line 226

```python
async def temporary_browser_page(*, proxy: str):
    playwright = await async_playwright().start()   # NEW playwright process
    browser = await playwright.chromium.launch(...)  # NEW browser process
```

This means: for every URL that uses a proxy in browser mode, the system spins up a complete `playwright` subprocess + Chromium instance, does one page load, then tears it all down. Chromium cold-start is 1-3 seconds. With proxy rotation across 10 URLs, you're paying 10-30 seconds of pure startup overhead.

**Fix:** Build a proxy-aware browser pool. The simplest correct approach: create one `Browser` per proxy string, reuse it across requests, and close it when the proxy is removed from the pool.

```python
_PROXY_BROWSER_POOL: dict[str, Browser] = {}
_PROXY_BROWSER_LOCK = asyncio.Lock()

async def get_proxied_browser(proxy: str, playwright: Playwright) -> Browser:
    async with _PROXY_BROWSER_LOCK:
        browser = _PROXY_BROWSER_POOL.get(proxy)
        if browser and browser.is_connected():
            return browser
        browser = await playwright.chromium.launch(
            headless=settings.playwright_headless,
            proxy={"server": proxy},
        )
        _PROXY_BROWSER_POOL[proxy] = browser
        return browser
```

At minimum, refactor `temporary_browser_page` to reuse the global `SharedBrowserRuntime._playwright` instance (it's already running) and only vary the context-level proxy via `context.new_context(proxy={"server": proxy})`. Playwright supports per-context proxies without launching a new browser.

---

## Category 2 — Performance / Efficiency Issues

### PERF-1 · HTTP Waterfall Multiplies Wasted Requests by `O(proxies × fetchers)`
**File:** `crawl_fetch_runtime.py:fetch_page()` ~line 200

```python
for proxy in proxy_attempts:       # e.g. 3 proxies
    for fetcher in (_curl_fetch, _http_fetch):  # 2 fetchers
```

With 3 proxies, the system makes 6 HTTP requests before ever trying the browser for a 403 site. Each request burns proxy bandwidth, increments the bot-score at the vendor, and costs wall-clock time. For a domain that will require browser anyway this is pure waste.

**Fix:** Add early-exit on confirmed block: if any fetcher returns `blocked=True` from a known anti-bot vendor (detected via response headers like `x-datadome`, `cf-ray`, `x-px-*`), break the proxy loop immediately and go to browser. Vendor headers are already returned in `result.headers` — they're just not consulted.

```python
def _is_vendor_confirmed_block(result: PageFetchResult) -> bool:
    headers = result.headers
    return (
        headers.get("x-datadome") is not None
        or headers.get("cf-ray") is not None
        or "x-px-" in " ".join(headers.keys())
    )
```

---

### PERF-2 · `_card_count` Makes N Sequential Cross-Process Playwright Calls
**File:** `traversal.py:_card_count()` line 553

```python
for selector in list(selectors or []):
    highest = max(highest, await page.locator(str(selector)).count())
```

Each `await page.locator(...).count()` is an async IPC call to the browser process. With 10 selectors and 5 scroll iterations, this is 50 sequential cross-process calls just for card counting.

**Fix:** Evaluate all selector counts in a single JS call:

```python
async def _card_count(page, *, surface: str) -> int:
    selector_group = "jobs" if str(surface or "").strip().lower().startswith("job_") else "ecommerce"
    selectors = list(CARD_SELECTORS.get(selector_group) or [])
    if not selectors:
        return 0
    counts = await page.evaluate(
        """(selectors) => selectors.map(sel => {
            try { return document.querySelectorAll(sel).length; }
            catch { return 0; }
        })""",
        selectors,
    )
    return max(counts) if counts else 0
```

One IPC round-trip instead of N.

---

### PERF-3 · BeautifulSoup Parsed 3+ Times on Same HTML in Hot Path
**Files:** `runtime.py:classify_blocked_page()`, `runtime.py:_looks_like_js_shell()`, `browser_runtime.py:classify_low_content_reason()`

Each of these independently calls `BeautifulSoup(html, "html.parser")`. For a 200KB HTML page, a full BS4 parse takes 50-200ms. In the `should_escalate_to_browser` call chain, `_looks_like_js_shell` and `_has_extractable_detail_signals` both parse the same HTML.

**Fix:** Pass a parsed soup object as an optional argument, or build a lightweight `ParsedPage` value object that wraps HTML + the lazily-cached soup:

```python
@dataclass
class ParsedPage:
    html: str
    _soup: BeautifulSoup | None = field(default=None, repr=False)
    
    @property
    def soup(self) -> BeautifulSoup:
        if self._soup is None:
            self._soup = BeautifulSoup(self.html, "html.parser")
        return self._soup
```

This is consistent with INVARIANT-21 ("CPU-bound parsing must not block async hot paths") and INVARIANT-8 ("HTML parsed exactly once").

---

### PERF-4 · `_collect_anchor_container_fragments` Selects All `div` Elements
**File:** `traversal.py:_collect_anchor_container_fragments()` line 506

```python
for node in parser.css("article, li, div"):
```

On any modern SPA, `div` matches thousands of elements. This is O(n) over the full DOM with no early stop other than byte budget. The byte budget check is applied per-fragment — meaning thousands of elements are iterated before the check fires.

**Fix:** Add a depth limit and a minimum content threshold before the byte budget check:

```python
# Exclude divs with no meaningful text content (nav wrappers, modals, etc.)
MIN_TEXT_LENGTH = 40
for node in parser.css("article, li, div"):
    text = (node.text(strip=True) or "")
    if len(text) < MIN_TEXT_LENGTH:
        continue
    if node.css_first("a[href]") is None:
        continue
    # ... rest of fragment collection
```

Also: `selectolax` (which traversal.py already uses) has a `matches()` method that can filter inline — prefer it over iterating then checking.

---

### PERF-5 · `_page_snapshot` Called Redundantly in Auto-Mode Detection
**File:** `traversal.py:execute_listing_traversal()` lines 139-145

In auto mode:
1. `_detect_auto_mode` → `_has_scroll_signals` → `_page_snapshot` (IPC call)
2. If no mode detected: `_page_snapshot` is called again for `card_count`

Two identical async Playwright evaluations for the same page state.

**Fix:** Capture the snapshot once and thread it through:

```python
initial_snapshot = await _page_snapshot(page, surface=surface)
selected_mode = await _detect_auto_mode_from_snapshot(page, snapshot=initial_snapshot, surface=surface)
if not selected_mode:
    result.card_count = initial_snapshot["card_count"]
    ...
```

---

## Category 3 — Technical Debt / Principle Violations

### DEBT-1 · `runtime.py:fetch_page()` Is a Runtime Import Trampoline
**File:** `runtime.py` lines 441-444

```python
async def fetch_page(*args, **kwargs):
    from app.services.crawl_fetch_runtime import fetch_page as crawl_fetch_page
    return await crawl_fetch_page(*args, **kwargs)
```

This is a circular import workaround surfaced as a public API. Every call performs a module lookup (cached after first import, but still a code smell). More importantly it makes the import graph opaque — static analysis tools cannot resolve the call target.

**Fix:** Restructure so `runtime.py` contains only pure data types and stateless utilities. Move all orchestration logic to `crawl_fetch_runtime.py`. Update `__init__.py` to import `fetch_page` from `crawl_fetch_runtime` directly. This eliminates the indirection.

---

### DEBT-2 · `http_client.py` Duplicates Shared-Client Infrastructure from `runtime.py`
**File:** `http_client.py`

`http_client.py` has its own `_SHARED_CLIENTS` dict, lock, and `_get_shared_http_client`. `runtime.py` has `_SHARED_HTTP_CLIENTS`, its own lock, and `get_shared_http_client`. Two separate connection pools, two cleanup paths (both called in `__init__.py:close_shared_http_client`).

This violates INVARIANT-7 (shared runtime behavior must be config-driven and not duplicated across the codebase).

**Fix:** Merge into a single `HttpClientPool` in `runtime.py` (or a new `http_pool.py`) with a `get_client(proxy, force_ipv4)` interface. `http_client.py:request_result` becomes a thin wrapper over `fetch_page` for non-browser paths.

---

### DEBT-3 · `crawl_fetch_runtime.py:_call_browser_fetch` Has a TypeError-Based Signature Fallback
**File:** `crawl_fetch_runtime.py` lines 105-130

```python
except TypeError as exc:
    message = str(exc)
    if "unexpected keyword argument" not in message or not _is_browser_fetch_signature_error(exc):
        raise
    logger.info("Falling back to legacy _browser_fetch signature ...")
    if proxy is not None:
        return await _browser_fetch(url, timeout_seconds, proxy=proxy)
    return await _browser_fetch(url, timeout_seconds)
```

This is a compatibility shim for a function signature mismatch between the module-level `_browser_fetch` wrapper and the actual `browser_fetch` in `browser_runtime.py`. It uses exception message string matching to identify the error, which is fragile and produces silent behavioural degradation — if the fallback fires, traversal_mode, surface, max_pages, and max_scrolls are all silently dropped.

**Fix:** Align the signatures. If the shim exists to handle a temporary migration, it should be removed within the current sprint. The `_is_browser_fetch_signature_error` helper exists only to support this shim and should be deleted with it.

---

### DEBT-4 · Blocked-Page Detection for HTTP 401/403/429 Does Not Distinguish Transient from Bot-Block
**File:** `runtime.py:classify_blocked_page()` lines 77-82

```python
if status_code in {401, 403, 429}:
    return BlockPageClassification(blocked=True, outcome="challenge_page", ...)
```

A 401 on a login-required page is not a bot block — it is an authentication wall. Treating it as `challenge_page` causes a browser escalation that will also get a 401 (or redirect to login), wasting browser resources. A 429 is a rate limit, not necessarily a bot challenge — the correct response is to wait and retry, not escalate to browser.

**Fix:** Separate status-based outcomes:
- `401` → `outcome="auth_wall"`, `blocked=False` (so `should_escalate_to_browser` returns False)
- `429` → `outcome="rate_limited"`, `blocked=True` but escalation should trigger backoff, not browser
- `403` with DataDome/CF response headers → `outcome="bot_block"`, escalate to browser

Update `is_non_retryable_http_status` to return True for 401.

---

### DEBT-5 · No Protected-Host Static Classification — Policy Is Entirely Reactive
**Files:** `crawl_fetch_runtime.py`, `acquirer.py`

The system learns that a host prefers browser only after a *successful* browser fetch (`remember_browser_host_if_good`). For a brand-new DataDome-protected domain, the first run always burns through the full HTTP waterfall before reaching browser.

This violates the spirit of INVARIANT-4 (acquisition returns observational facts — not fabricated ones — which implies not wasting attempts that are predetermined to fail).

**Fix:** Add a `protected_host_patterns` config list (in `crawler_runtime_settings`) with regex patterns for known anti-bot deployments:

```python
PROTECTED_HOST_PATTERNS = [
    r"autozone\.com",
    r".*\.datadome\.co",
    # ... populated from a known-protections config file
]
```

These are checked in `fetch_page` before the HTTP loop. Matches jump directly to browser. The list starts small and grows from operational observation — the key is having the infrastructure for it.

---

### DEBT-6 · `_batch_runtime.py` Catches OSError in the URL Processing Loop
**File:** `_batch_runtime.py` lines 125-131

```python
except (RuntimeError, ValueError, TypeError, OSError) as exc:
    url_result = URLProcessingResult(records=[], verdict=VERDICT_ERROR, ...)
```

`OSError` inside a URL processing loop could be a disk full, a file descriptor exhaustion, or a DNS resolution failure. All of these are treated identically as soft errors — the loop continues to the next URL. Disk full will produce the same error on the next URL. FD exhaustion will compound. These should be re-raised after logging.

**Fix:** Split the exception handling:

```python
except (RuntimeError, ValueError, TypeError) as exc:
    # Soft errors — specific to this URL's processing
    ...
except OSError as exc:
    # Hard errors — may affect all subsequent URLs
    logger.error("Hard OS error during URL processing, aborting run", exc_info=True)
    raise
```

---

### DEBT-7 · `pacing.py` TTL Prune Uses Monotonic Time but Bucket Is Keyed by Host String
**File:** `pacing.py:_prune_expired_hosts()` line 30

The prune condition is `now - allowed_at > ttl_seconds`. But `allowed_at` is the *next* allowed time (future), not the last-access time. So for active hosts, `allowed_at > now`, meaning `now - allowed_at < 0`, and the prune condition never fires even when TTL expires. Only hosts whose `next_allowed_at` is in the past will be pruned.

This means the dict grows unboundedly until `_enforce_host_cache_limit` evicts the oldest entries by time — which is correct behavior but the TTL prune is effectively a no-op for any host that has been paced recently.

**Fix:** Track last-access time separately from next-allowed time:

```python
_HOST_LAST_SEEN: dict[str, float] = {}

# In wait_for_host_slot:
_HOST_LAST_SEEN[host] = now

# In _prune_expired_hosts:
expired = [h for h, last in _HOST_LAST_SEEN.items() if now - last > ttl_seconds]
```

---

## Category 4 — Missing Capabilities (High Impact)

### MISSING-1 · No Challenge Detection from Response Headers
The system parses HTML to detect blocks but ignores response headers, which are the most reliable and cheapest signal:

| Header | Vendor |
|--------|--------|
| `x-datadome` | DataDome |
| `cf-ray` | Cloudflare |
| `x-px-*` | PerimeterX / HUMAN |
| `x-akamai-*` | Akamai Bot Manager |
| `x-sucuri-*` | Sucuri |

Add a `classify_block_from_headers(headers)` function used in both `http_fetch` and `curl_fetch` before HTML parsing. If headers confirm a vendor, set `blocked=True` immediately — skip BeautifulSoup entirely.

---

### MISSING-2 · No Per-Host Challenge Cooldown
After a confirmed block from a host+proxy combination, the system currently retries other proxies immediately. But DataDome / Kasada model risk at the IP level AND the session level — retrying from the same IP pool in the same second increases risk scores.

Add a `_CHALLENGE_COOLDOWN: dict[str, float]` keyed by `(host, proxy_prefix)` with a configurable cooldown (30-60s default). Any proxy attempt against a challenged host within the window returns early without a network call.

---

### MISSING-3 · No Residential / Mobile Proxy Tier
All proxy paths in the current code are undifferentiated — any proxy string from `plan.proxy_list` is tried equally for any target. The smoke test conclusion was correct: for DataDome-class sites, datacenter proxies will not work regardless of stealth improvements. The code needs a proxy tier concept:

```python
@dataclass
class ProxyConfig:
    url: str
    tier: Literal["datacenter", "residential", "mobile"] = "datacenter"
```

Protected hosts should prefer `residential` or `mobile` tier proxies. This is a config-level concern, but the code infrastructure needs to support it — currently a proxy is just a string.

---

## Slice-Wise Implementation Plan

Priority order: security posture + ROI per sprint. Each slice is independently deployable and testable.

---

### Slice 1 — Stop the Bleeding (1-2 days)
**Goal:** Stop actively making bot detection worse on every request.

**Tasks:**

1. **BUG-3:** Add `User-Agent` header to `build_async_http_client` call in `runtime.py` and `http_client.py`. Use a static recent Chrome string from `crawler_runtime_settings.http_user_agent`. One-liner.

2. **BUG-2:** Replace hardcoded `"chrome124"` in `_curl_fetch_sync` with a configurable/rotating target from `crawler_runtime_settings.curl_cffi_impersonate_target`. Default to `["chrome131", "chrome133", "chrome136"]` weighted toward latest.

3. **BUG-4:** Apply `playwright-stealth` in `SharedBrowserRuntime.page()` after `new_page()`. Also apply in `temporary_browser_page`. Import guard so startup doesn't fail if package is missing (log warning, don't raise).

**Acceptance criteria:**
```bash
grep -n "chrome124" app/services/acquisition/runtime.py  # must return empty
grep -n "stealth_async" app/services/acquisition/browser_runtime.py  # must return a hit
grep -n "User-Agent" app/services/network_resolution.py  # or wherever build_async_http_client lives — must have a custom UA
```

**Tests:**
- `test_curl_fetch_impersonate_not_hardcoded`: mock `curl_requests.get`, assert impersonate kwarg is in the approved list.
- `test_http_fetch_sends_user_agent`: capture headers from a mock httpx client, assert `User-Agent` is not `python-httpx`.

---

### Slice 2 — Coherent Browser Identity (2-3 days)
**Goal:** Eliminate cross-dimension fingerprint incoherence.

**Tasks:**

1. **BUG-5a:** Lock `FingerprintGenerator` OS parameter to host OS using `platform.system()` at module import time.

2. **BUG-5b:** After `_FINGERPRINT_GENERATOR.generate()`, validate that:
   - UA platform token (`Windows NT`, `Macintosh`, `Linux`) matches `navigator.platform` family.
   - Major Chrome version in UA matches the first entry in `userAgentData.brands` (if present).
   - Retry generation up to 3 times on incoherence, then fall back to a safe static `BrowserIdentity`.

3. **BUG-5c:** Add `_STATIC_FALLBACK_IDENTITY` constant — a well-tested, coherent Windows/Chrome 136 identity — used when generation fails validation.

4. Add a `validate_browser_identity(identity: BrowserIdentity) -> list[str]` function that returns a list of incoherence reasons. Call it in tests and log warnings in production.

**Acceptance criteria:**
```bash
python -c "
from app.services.acquisition.browser_identity import create_browser_identity
import re, platform
for _ in range(20):
    ident = create_browser_identity()
    ua = ident.user_agent
    os_system = platform.system().lower()
    if os_system == 'windows':
        assert 'Windows NT' in ua, f'OS mismatch: {ua}'
    print('ok:', ua[:60])
"
```

**Tests:**
- `test_browser_identity_os_coherent`: generate 50 identities, assert UA and platform match host OS.
- `test_browser_identity_version_coherent`: assert UA major version matches userAgentData brands if both present.
- `test_browser_identity_no_ancient_versions`: assert extracted Chrome major version >= 120.

---

### Slice 3 — Waterfall Reordering + Protected Host Policy (2-3 days)
**Goal:** Stop wasting HTTP attempts on confirmed bot-detection sites.

**Tasks:**

1. **BUG-1 + DEBT-5:** Add `protected_host_patterns: list[str]` to `crawler_runtime_settings`. Add `_host_is_protected(url: str) -> bool` function in `crawl_fetch_runtime.py` that checks the URL against compiled patterns. Compile regexes at import time, cache in a module-level list.

2. In `fetch_page()`: if `_host_is_protected(url)` and not already `browser_first`, set `browser_first = True` and `browser_reason = "protected-host"` before the HTTP loop.

3. **MISSING-1:** Add `classify_block_from_headers(headers) -> str | None` in `runtime.py`. Returns vendor name string if a vendor header is detected, `None` otherwise. Call this in `http_fetch` and `curl_fetch` *before* HTML parsing — set `blocked=True` immediately on vendor confirmation.

4. **PERF-1:** Add `_is_vendor_confirmed_block(result: PageFetchResult) -> bool` that checks `result.headers` for vendor markers. In the proxy loop, `break` immediately on vendor-confirmed block without trying remaining proxies.

**Acceptance criteria:**
```bash
grep -n "_host_is_protected\|protected_host" app/services/acquisition/crawl_fetch_runtime.py | wc -l
# Should be >= 3 (definition + call + config reference)

grep -n "classify_block_from_headers" app/services/acquisition/runtime.py
# Must exist
```

**Tests:**
- `test_protected_host_skips_http_loop`: mock `_browser_fetch`, assert it's called without calling `_curl_fetch` or `_http_fetch` for a protected host.
- `test_vendor_header_breaks_proxy_loop`: assert that after a DataDome header in the first proxy response, the second proxy is not attempted.

---

### Slice 4 — Session Persistence (3-4 days)
**Goal:** Give the browser a warm session profile per host.

**Tasks:**

1. **BUG-6:** Add `browser_storage_state_dir` to `settings` (defaults to `./data/browser_sessions/`).

2. Create `app/services/acquisition/session_store.py`:
   - `async def load_storage_state(host: str) -> dict | None` — reads JSON with TTL check.
   - `async def save_storage_state(host: str, context) -> None` — saves Playwright storage state.
   - `async def invalidate_storage_state(host: str) -> None` — called after a confirmed block to discard compromised session.
   - File locking via `asyncio.Lock` keyed by host to prevent concurrent writes.

3. In `SharedBrowserRuntime.page()`: before `browser.new_context()`, call `load_storage_state(host)` and pass result as `storage_state` kwarg. After successful (non-blocked) fetch, call `save_storage_state`.

4. In `temporary_browser_page`: same — load before context creation, save after.

5. In `fetch_page()`: after a vendor-confirmed block, call `invalidate_storage_state(host)`.

**Tests:**
- `test_storage_state_loaded_on_second_fetch`: first fetch saves state, second fetch passes it to `new_context`.
- `test_storage_state_invalidated_on_block`: after a blocked result, storage file is removed.
- `test_storage_state_ttl_expired_returns_none`: file older than TTL is ignored.

---

### Slice 5 — Proxy Browser Pool + `temporary_browser_page` Fix (2-3 days)
**Goal:** Eliminate per-request Playwright process startup overhead.

**Tasks:**

1. **BUG-7:** Add `_PROXY_CONTEXTS: dict[str, BrowserContext]` to `SharedBrowserRuntime`. Add `get_proxied_context(proxy: str) -> BrowserContext` method that reuses or creates a context with `proxy={"server": proxy}`. Use a lock keyed by proxy string.

2. Rewrite `temporary_browser_page` as:
   ```python
   @asynccontextmanager
   async def temporary_browser_page(*, proxy: str):
       runtime = await get_browser_runtime()
       async with runtime.proxied_page(proxy=proxy) as page:
           yield page
   ```

3. Add `SharedBrowserRuntime.proxied_page(proxy)` that calls `get_proxied_context(proxy)` and creates a page from it with stealth applied.

4. Add health check in `get_proxied_context` — if existing context has a closed page, discard and recreate.

5. Add `cleanup_proxy_contexts()` to `reset_fetch_runtime_state()`.

**Acceptance criteria:**
```bash
grep -n "async_playwright().start()" app/services/acquisition/browser_runtime.py | wc -l
# Must be 1 (only in SharedBrowserRuntime._ensure)
```

---

### Slice 6 — Performance Optimizations (1-2 days, parallelizable with other slices)
**Goal:** Reduce unnecessary Playwright IPC and BeautifulSoup overhead.

**Tasks:**

1. **PERF-2:** Replace sequential `locator().count()` loop in `_card_count` with single `page.evaluate(JS)` call.

2. **PERF-3:** Introduce `ParsedPage` value object or pass soup as optional kwarg through `classify_blocked_page` → `should_escalate_to_browser` → `_looks_like_js_shell` call chain.

3. **PERF-4:** Add `len(text) < MIN_TEXT_LENGTH` early-exit in `_collect_anchor_container_fragments` before the `css_first("a[href]")` check.

4. **PERF-5:** Capture `initial_snapshot` once in `execute_listing_traversal` and pass to `_detect_auto_mode` to avoid duplicate evaluation.

5. **DEBT-7:** Fix `_prune_expired_hosts` to track last-access time separately.

---

### Slice 7 — Structural Cleanup (1-2 days)
**Goal:** Eliminate the import trampoline, HTTP client duplication, and signature shim.

**Tasks:**

1. **DEBT-1:** Move all orchestration out of `runtime.py:fetch_page` trampoline. Make `runtime.py` a pure data/utilities module. Update `__init__.py` imports.

2. **DEBT-2:** Merge `http_client.py` shared client into `runtime.py`'s pool. Delete duplicate lock + dict.

3. **DEBT-3:** Delete `_call_browser_fetch` TypeError shim and `_is_browser_fetch_signature_error`. Align `_browser_fetch` signature with `browser_fetch`.

4. **DEBT-4:** Split `classify_blocked_page` status handling into `auth_wall` / `rate_limited` / `bot_block` outcomes. Update `is_non_retryable_http_status` to include 401.

5. **DEBT-6:** Narrow `OSError` out of the URL processing loop catch block in `_batch_runtime.py`.

---

## Summary Table

| ID | File | Severity | Slice | Impact |
|----|------|----------|-------|--------|
| BUG-1 | `crawl_fetch_runtime.py` | Critical | 3 | Wastes HTTP attempts, deepens IP block score |
| BUG-2 | `runtime.py` | Critical | 1 | Stale TLS fingerprint, instantly detectable |
| BUG-3 | `runtime.py`, `http_client.py` | Critical | 1 | Explicit Python bot label in response |
| BUG-4 | `browser_runtime.py` | Critical | 1 | `navigator.webdriver` exposed |
| BUG-5 | `browser_identity.py` | Critical | 2 | Cross-OS/version incoherence |
| BUG-6 | `cookie_store.py`, `browser_runtime.py` | Critical | 4 | No session trust carryover |
| BUG-7 | `browser_runtime.py` | High | 5 | Full browser launch per proxied request |
| PERF-1 | `crawl_fetch_runtime.py` | High | 3 | O(proxies×fetchers) wasted requests |
| PERF-2 | `traversal.py` | Medium | 6 | N sequential Playwright IPC calls |
| PERF-3 | `runtime.py`, `browser_runtime.py` | Medium | 6 | 3+ BeautifulSoup parses per page |
| PERF-4 | `traversal.py` | Medium | 6 | Unbounded `div` CSS traversal |
| PERF-5 | `traversal.py` | Low | 6 | Duplicate snapshot evaluation |
| DEBT-1 | `runtime.py` | Medium | 7 | Circular import trampoline |
| DEBT-2 | `http_client.py` | Medium | 7 | Duplicate HTTP client pool |
| DEBT-3 | `crawl_fetch_runtime.py` | Medium | 7 | TypeError-based signature shim |
| DEBT-4 | `runtime.py` | Medium | 7 | 401/429 misclassified as bot blocks |
| DEBT-5 | `crawl_fetch_runtime.py` | High | 3 | No static protected-host policy |
| DEBT-6 | `_batch_runtime.py` | Medium | 7 | OSError swallowed in URL loop |
| DEBT-7 | `pacing.py` | Low | 6 | TTL prune logic is effectively a no-op |
| MISSING-1 | `runtime.py` | High | 3 | No header-based block detection |
| MISSING-2 | `crawl_fetch_runtime.py` | High | 4 | No post-challenge cooldown |
| MISSING-3 | `acquirer.py` | High | Future | No proxy tier concept |

---

## Library Recommendations

| Use Case | Library | Notes |
|----------|---------|-------|
| Browser stealth | `playwright-stealth` | Already installed, just not wired |
| TLS impersonation | `curl_cffi >= 0.7` | Already installed, pin to chrome131+ |
| Fingerprint generation | `browserforge` | Already installed, constrain OS param |
| Session storage | Playwright's `context.storage_state()` | Built-in, no new dependency |
| Proxy-aware browser pool | Custom `SharedBrowserRuntime` extension | No new dependency needed |
| Header-based block detection | Custom + `httpx.Headers` | No new dependency, add vendor header list to config |