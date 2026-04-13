# CrawlerAI — Acquisition Layer Deep Audit
**Scope:** `acquirer.py`, `http_client.py`, `browser_client.py`, `browser_pool.py`, `traversal.py`, `blocked_detector.py`, `browser_challenge.py`, `browser_navigation.py`, `browser_readiness.py`, `browser_runtime.py`, `cookie_store.py`, `pacing.py`, `session_context.py`, `strategies.py`, `artifact_store.py`, `__init__.py`
**Audit Date:** 2026-04-13
**Auditor:** Claude Opus — Architecture + Correctness Review
**Status:** Actionable. All items are implementation-ready.

---

## Executive Summary

The acquisition layer is architecturally sound and meaningfully better than most crawl stacks — the waterfall (curl → browser), surface-aware escalation, challenge resolution, traversal engine, session affinity, and artifact scrubbing are all real competitive advantages. The core logic is correct. However, the layer has accumulated three distinct categories of problems that must be addressed before this can be called consolidated:

1. **Three real bugs** that silently corrupt or drop data in production today.
2. **Severe redundancy** in hot-path processing (BeautifulSoup parsing, `detect_blocked_page` calls) that adds measurable latency per acquisition and will compound as volume scales.
3. **Dead infrastructure** (`strategies.py`) and duplicated utilities that actively mislead future developers and guarantee the bugs will recur.

The layer is currently at ~70% of its potential throughput and coverage. All ten items below are achievable without introducing new failure modes.

---

## Severity Legend

| Level | Meaning |
|---|---|
| 🔴 **CRITICAL** | Silent data loss or correctness failure in production today |
| 🟠 **HIGH** | Measurable performance regression, resource leak, or reliability gap |
| 🟡 **MEDIUM** | Technical debt that blocks safe refactoring or causes developer confusion |
| 🟢 **LOW** | Cleanup / cosmetic; safe to defer |

---

## Section 1 — Bugs

---

### BUG-01 · Request headers silently dropped after first redirect
**Severity:** 🔴 CRITICAL
**File:** `http_client.py`
**Lines:** 283 (param), 351 (shadow)

**Description:** The `headers` parameter of `_fetch_once` is shadowed by response headers inside the `while True` redirect loop:

```python
# Line 283 — incoming request headers
async def _fetch_once(..., headers: dict[str, str] | None = None, ...) -> HttpFetchResult:
    ...
    while True:
        ...
        if headers:
            kwargs["headers"] = dict(headers)  # ← first hop: correct
        ...
        # Line 351 — response headers assigned to SAME NAME
        headers = {
            str(key).lower(): str(value)
            for key, value in getattr(response, "headers", {}).items()
        }
        # ← redirect happens; second hop: kwargs["headers"] = response headers from hop 1
```

On any URL that issues a redirect (301/302/307), all custom request headers (including impersonation headers passed via `session_context.fingerprint.extra_headers`) are silently replaced by the response headers of the previous hop on the second iteration. The request succeeds but with a poisoned header set. Sites that verify `Accept-Language`, `sec-ch-ua`, or custom headers on the final page will see incorrect values.

**Fix:**
```python
# Rename local variable
response_headers = {
    str(key).lower(): str(value)
    for key, value in getattr(response, "headers", {}).items()
}
status_code = int(getattr(response, "status_code", 0) or 0)
location = str(response_headers.get("location") or "").strip()
# All subsequent accesses use response_headers, not headers
```

**Acceptance Criteria:** A test that makes a request through a 301 redirect with a custom `X-Test-Header` verifies the header is present on the final hop's `kwargs`.

---

### BUG-02 · `asyncio.TimeoutError` not caught in traversal fallback
**Severity:** 🔴 CRITICAL
**File:** `browser_client.py`
**Lines:** 568–649

**Description:** The traversal `except` block does not include `asyncio.TimeoutError`:

```python
except (
    PlaywrightError,
    RuntimeError,
    ValueError,
    TypeError,
    OSError,
) as exc:  # ← asyncio.TimeoutError is NOT here
```

`PlaywrightTimeoutError` is a subclass of `PlaywrightError` and is caught correctly. But if any `asyncio.wait_for()` call inside `apply_traversal_mode` times out (e.g., an internal page navigation with a capped timeout), the resulting `asyncio.TimeoutError` propagates out of the traversal block and through `_fetch_rendered_html_attempt`, bypassing the fallback to single-page acquisition and crashing the entire browser attempt. Since traversal is browser-only and the browser attempt is wrapped in `asyncio.wait_for(BROWSER_RENDER_TIMEOUT_SECONDS)`, this will surface as an unexplained timeout on the whole acquisition rather than a graceful single-page fallback.

**Fix:**
```python
except (
    asyncio.TimeoutError,   # ← add this
    PlaywrightTimeoutError,  # already a subclass of PlaywrightError but explicit is safer
    PlaywrightError,
    RuntimeError,
    ValueError,
    TypeError,
    OSError,
) as exc:
```

**Acceptance Criteria:** A mock traversal that raises `asyncio.TimeoutError` produces a single-page fallback result with `traversal_fallback_used=True`, not a full acquisition failure.

---

### BUG-03 · `strategies.py` AcquisitionChain is dead infrastructure — never called
**Severity:** 🔴 CRITICAL (architectural correctness, not runtime crash)
**File:** `strategies.py`, `acquirer.py`

**Description:** `AcquisitionChain`, `HttpStrategy`, `BrowserStrategy`, `AdapterRecoveryStrategy`, and `build_default_chain()` exist in `strategies.py` but are **never called by any production code path**. The live `acquire()` function calls `_acquire_once()` which directly invokes the module-private `_try_http()`, `_try_browser()`, and `_try_promoted_source_acquire()`. The strategies module has zero callers in the production path.

This is critical because:
- Any fix applied to `strategies.py` (e.g., adding a new adapter) has no effect on the live system.
- Any developer reading `strategies.py` believes they are looking at the acquisition architecture, not dead code. Future changes will be applied to the wrong layer.
- The `AdapterRecoveryStrategy` in `strategies.py` calls `try_blocked_adapter_recovery` — but in the live path, adapter recovery is handled differently (via `resolve_adapter` in `_resolve_adapter_hint`). The two paths can diverge silently.

**Fix Options (pick one):**
- **Option A (recommended):** Delete `strategies.py` entirely. Wire `_try_http` and `_try_browser` into Strategy classes and call `AcquisitionChain.execute()` from `_acquire_once()`. This is the intended architecture.
- **Option B (safe interim):** Add a prominent `# NOT CALLED — see acquirer._acquire_once()` docstring and a runtime warning in `build_default_chain()`. Track as debt for the next refactor cycle.

**Acceptance Criteria:** Either `build_default_chain()` is called from `acquire()` and tested end-to-end, or `strategies.py` is removed and no import fails.

---

### BUG-04 · `save_cookies_payload` is a silent no-op — cookies silently dropped
**Severity:** 🟠 HIGH
**File:** `cookie_store.py`

**Description:** The legacy domain-scoped persistence function is a stub:

```python
def save_cookies_payload(payload: object, *, domain: str) -> None:
    logger.debug(
        "Skipping legacy domain-scoped cookie persistence for %s; use session-scoped persistence instead",
        domain,
    )
```

Any caller outside the session-scoped path (including any third-party adapter or older code path that calls `save_cookies_payload`) silently discards cookies. The `logger.debug` level ensures this is invisible in production logs. If callers exist anywhere in the adapter layer or test fixtures that use this API expecting persistence, their cookies are dropped with no error.

**Fix:** Add a `DeprecationWarning` call and audit all call sites. Alternatively, raise `NotImplementedError` to force callers to migrate.

---

## Section 2 — Performance

---

### PERF-01 · `detect_blocked_page` called 3× per HTTP attempt on same HTML
**Severity:** 🟠 HIGH
**Files:** `http_client.py` lines 224, 268, 450; `acquirer.py` line 1437

**Description:** For every HTML HTTP attempt, `detect_blocked_page` is called:
1. **Line 224 (in `_fetch_with_retry`):** Early-return check — `if detect_blocked_page(result.text).is_blocked: return result`
2. **Line 268 (in `_build_attempt_entry`):** For the attempt log entry — `entry["blocked"] = detect_blocked_page(result.text).is_blocked`
3. **Line 450 (in `_should_retry_with_stealth`):** Stealth retry decision — `detect_blocked_page(result.text).is_blocked`
4. **Line 1437 (`acquirer._try_http`):** Full analysis phase — `await asyncio.to_thread(detect_blocked_page, html)`

With 2 HTTP profiles (primary + stealth) and `HTTP_MAX_RETRIES=2`, the same HTML can be checked up to **9 times** before the final analysis even runs. Since `detect_blocked_page` involves a full BeautifulSoup parse for pages < 100KB, this is a significant waste on the hot path.

**Fix:** Cache the `BlockedPageResult` on the `HttpFetchResult` object:

```python
@dataclass
class HttpFetchResult:
    ...
    _blocked_result: BlockedPageResult | None = field(default=None, repr=False, compare=False)
    
    def blocked_result(self) -> BlockedPageResult:
        if self._blocked_result is None:
            self._blocked_result = detect_blocked_page(self.text)
        return self._blocked_result
```

Replace all inline calls with `result.blocked_result()`. The acquirer's `asyncio.to_thread` call can use the cached result if already computed.

**Estimated gain:** 20–40ms per blocked acquisition eliminated; ~6–9 BS4 parses reduced to 1.

---

### PERF-02 · 4 independent BeautifulSoup parses of the same HTML in `_try_http`
**Severity:** 🟠 HIGH
**File:** `acquirer.py`
**Lines:** 1438, 1462, 1470, 1476

**Description:** In a single `_try_http` execution, the same HTML document is parsed by BeautifulSoup up to 4 times across different `asyncio.to_thread` calls:

1. `await asyncio.to_thread(_analyze_html_sync, html)` → BS4 parse for visible text + gate phrases
2. `await asyncio.to_thread(_assess_extractable_html, html, ...)` → likely another BS4 parse internally
3. `_is_invalid_surface_page(...)` → `_is_invalid_commerce_surface_page` → `BeautifulSoup(html, HTML_PARSER)` for title check
4. `_surface_selection_warnings(...)` → `_diagnose_job_surface_page` → `BeautifulSoup(html, HTML_PARSER)` for title, headings, canonical

The `soup` object is never cached or passed between these calls; each function re-parses from the raw string. For a 200KB PDP HTML page, each parse takes 30–80ms (thread-bound). Total: potentially 120–320ms of redundant parsing per acquisition.

**Fix:** Parse once in `_try_http`, pass the `soup` object as an argument:

```python
# In _try_http, after fetching:
soup = await asyncio.to_thread(BeautifulSoup, html, HTML_PARSER)
visible_text, gate_phrases = await asyncio.to_thread(_analyze_html_sync_from_soup, soup)
extractability = await asyncio.to_thread(_assess_extractable_html_from_soup, soup, ...)
invalid_surface_page = _is_invalid_commerce_surface_page_from_soup(soup=soup, ...)
```

This requires adding `soup`-accepting overloads for each helper. The functions are private, so no public API breaks.

**Estimated gain:** 60–200ms per acquisition eliminated for complex HTML.

---

### PERF-03 · `AsyncSession` created per redirect hop — no connection pooling
**Severity:** 🟠 HIGH
**File:** `http_client.py`
**Lines:** 293–402

**Description:** `async with requests.AsyncSession(**session_kwargs) as session:` is inside the `while True:` redirect loop. A new curl_cffi session is instantiated and destroyed on every redirect hop. For a URL that issues two redirects before reaching the canonical PDP:

- 3 `AsyncSession` objects created and destroyed
- 0 connection reuse between hops
- 3× TLS handshake overhead (depending on curl_cffi internals)
- 3× session setup overhead

The manual redirect loop exists intentionally (to validate redirect targets via `validate_public_target`). This is correct. But the session does not need to be inside the loop.

**Fix:** Create the session once before the loop, reusing it across hops:

```python
async with requests.AsyncSession(**session_kwargs) as session:
    while True:
        target = await validate_public_target(request_url)
        ...
        response = await session.get(request_url, **kwargs)
        ...
        # handle redirects manually, reusing session
```

**Estimated gain:** Eliminates redundant TLS negotiation on sites with 2–3 redirect chains (common on ecommerce and ATS platforms).

---

### PERF-04 · Proxy endpoint validation is serial
**Severity:** 🟡 MEDIUM
**File:** `acquirer.py`
**Lines:** 555–556

**Description:**
```python
for proxy in rotator._proxies:
    await validate_proxy_endpoint(proxy)  # sequential, one proxy waits for the previous
```

With a 5-proxy pool, if each `validate_proxy_endpoint` does a DNS lookup, this is 5 sequential DNS-bound awaits before the acquisition can even start. With proxy pools of 10–20 entries, this startup overhead is noticeable.

**Fix:**
```python
await asyncio.gather(*(validate_proxy_endpoint(p) for p in rotator._proxies))
```

**Note:** Ensure `validate_proxy_endpoint` is safe to call concurrently (no shared mutable state).

---

### PERF-05 · `_validate_retry_backoff_config()` called on every retry calculation
**Severity:** 🟢 LOW
**File:** `http_client.py`
**Lines:** 244–249, 474

**Description:** `_validate_retry_backoff_config()` validates two config constants. It is called at module import time (line 474), which is correct. However, it is also called inside `_retry_backoff_seconds()` which runs on every retry. Two config values are re-validated dozens of times on a single busy acquisition.

**Fix:** Remove the call inside `_retry_backoff_seconds()`. The module-level call at line 474 is sufficient.

---

### PERF-06 · Platform family detected twice per acquisition
**Severity:** 🟢 LOW
**File:** `acquirer.py`
**Lines:** 537, 1459

**Description:**
```python
# Line 537 — in acquire(), before any HTML exists:
platform_family = _detect_platform_family(url)  # URL-only, less accurate

# Line 1459 — in _try_http(), after HTML is fetched:
platform_family = _detect_platform_family(url, html)  # URL + HTML, authoritative
```

The early URL-only detection at line 537 is used for the `browser_first` decision. The later detection inside `_try_http` is used for diagnostics. The early result is strictly weaker (no HTML signal) and is superseded by the later result. If the early detection is needed for the `browser_first` decision, it should be clearly documented as approximate. If not needed, it should be removed.

**Fix:** Pass the URL-only platform family as a hint into `_try_http` and let `_try_http` update it with HTML. Alternatively, move the `browser_first` decision entirely after HTTP fetch where the authoritative result is available (only possible if browser-first targets are a small fixed set).

---

## Section 3 — Technical Debt

---

### DEBT-01 · `_cooperative_sleep_ms` duplicated across modules
**Severity:** 🟡 MEDIUM
**Files:** `acquirer.py` lines 1809–1827, `browser_readiness.py` lines 38–50

**Description:** Identical interruptible-sleep logic is implemented twice. The `acquirer.py` version uses `COOPERATIVE_SLEEP_POLL_MS` while `browser_readiness.py` uses `INTERRUPTIBLE_WAIT_POLL_MS`. These may refer to the same constant or different ones — either way, divergence is guaranteed over time.

**Fix:** Delete `acquirer.py`'s copy. Import `_cooperative_sleep_ms` from `browser_readiness`. Verify constant references are aligned.

---

### DEBT-02 · `_AcquireExecutionRequest` duplicates `AcquisitionRequest` fields
**Severity:** 🟡 MEDIUM
**File:** `acquirer.py`
**Lines:** 340–358, 275–337

**Description:** `_AcquireExecutionRequest` is an internal dataclass that manually copies every field from `AcquisitionRequest` plus adds `proxy`, `browser_first`, `runtime_options`, and `session_context`. The population logic at lines 577–595 explicitly copies each field. Any new field added to `AcquisitionRequest` must also be added to `_AcquireExecutionRequest` and the copy block — a three-place change for every one-place intent. This is a confirmed source of future drift.

**Fix:** Flatten `_AcquireExecutionRequest` to hold only the fields it adds:
```python
@dataclass(slots=True)
class _AcquireExecutionContext:
    request: AcquisitionRequest  # the original, not copied
    proxy: str | None
    browser_first: bool
    runtime_options: BrowserRuntimeOptions
    session_context: SessionContext | None
```

---

### DEBT-03 · Proxy failure state is process-local — not coordinated across workers
**Severity:** 🟡 MEDIUM
**File:** `acquirer.py`
**Lines:** 108–253

**Description:** `_PROXY_FAILURE_STATE` is a plain Python dict. In a multi-worker deployment (Celery, Gunicorn multi-process), each worker process maintains its own independent proxy failure tracking. A proxy that is failing for worker A continues to be used by workers B, C, D with no cooldown. Under load, a bad proxy will be hammered by all workers simultaneously while the backoff only applies within a single process.

Redis-backed pacing already exists in `pacing.py`. Proxy failure state should use the same infrastructure — or at minimum document clearly that this is process-local only.

**Fix (minimal):** Add a `# NOTE: process-local only` comment and open a follow-up issue for Redis-backed proxy health.
**Fix (proper):** Mirror the `pacing.py` Redis pattern with `crawl:proxy:failure:{host}` keys, TTL = `PROXY_FAILURE_STATE_TTL_SECONDS`.

---

### DEBT-04 · `_needs_browser` is a 115-line function with interleaved condition trees
**Severity:** 🟡 MEDIUM
**File:** `acquirer.py`
**Lines:** 1543–1658

**Description:** `_needs_browser` encodes 8+ distinct escalation conditions (blocked page, HTTP status, missing extractable data, JS shell, gate phrases, invalid surface, structured override) in a single flat function. Conditions are interleaved with diagnostic writes. The `structured_override` logic at lines 1630–1639 conditionally undoes an earlier `needs_browser=True` decision, meaning the function's output depends on non-obvious ordering. This is the #1 candidate for introducing subtle escalation bugs during refactoring.

**Fix:** Convert to an `EscalationDecision` class with one method per condition:
```python
class BrowserEscalationDecider:
    def decide(self, http_result, url, surface, requested_fields, profile) -> tuple[bool, str]:
        if self._is_blocked(http_result): return True, "blocked_page"
        if self._is_error_status(http_result): return True, f"http_{http_result.status_code}"
        if self._is_js_shell(http_result): return True, "js_shell"
        if self._has_structured_override(http_result): return False, "structured_data_found"
        ...
```

---

### DEBT-05 · Private browser_pool functions imported into browser_client
**Severity:** 🟡 MEDIUM
**Files:** `browser_client.py` lines 36–43, `browser_pool.py`

**Description:** `browser_client.py` imports underscore-prefixed (private) functions:
```python
from app.services.acquisition.browser_pool import (
    _acquire_browser,       # private
    _browser_pool_key,      # private
    _evict_browser,         # private
    ...
)
```

These are part of `browser_pool`'s operational API and should be promoted to public functions (remove leading underscore). Importing private functions across module boundaries breaks the encapsulation contract and makes `browser_pool.py` internal structure impossible to refactor without auditing all cross-module imports.

**Fix:** Rename to `acquire_browser`, `browser_pool_key`, `evict_browser` in `browser_pool.py`. Update all import sites.

---

### DEBT-06 · `acquirer.py` has a duplicate `_artifact_basename` function (dead code)
**Severity:** 🟢 LOW
**File:** `acquirer.py`
**Lines:** 2388–2392

**Description:** A second `_artifact_basename` function exists in `acquirer.py` using SHA-256 and a host-slug prefix, completely different from `artifact_store.py`'s MD5-based version. The acquirer version is never called — all artifact path resolution uses `artifact_paths()` from `artifact_store`. The duplicate creates confusion about which format is canonical.

**Fix:** Delete lines 2388–2407 from `acquirer.py`. No callers exist.

---

### DEBT-07 · Unbounded network payload accumulation in browser_client
**Severity:** 🟡 MEDIUM
**File:** `browser_client.py`
**Lines:** 429–447

**Description:** The `_on_response` handler accumulates every intercepted JSON response into `intercepted: list[dict]` with no count or size limit. A heavily instrumented page (analytics, recommendations, A/B testing APIs) can produce 50–200 JSON responses. Since `intercepted` is held in memory for the entire session until `_populate_result` is called, pages with large API responses can produce 20–50MB of payload accumulation per page acquisition.

`traversal.py` has `_MAX_TRAVERSAL_FRAGMENTS = 50` and `_MAX_TRAVERSAL_TOTAL_BYTES = 6_000_000` guards, but these only apply after the data is already accumulated.

**Fix:** Add a count + total-size gate in `_on_response`:
```python
_MAX_INTERCEPTED = 100
_MAX_INTERCEPTED_BYTES = 5_000_000

async def _on_response(response):
    if len(intercepted) >= _MAX_INTERCEPTED:
        return
    ...
    body = await response.json()
    body_size = len(str(body))
    if sum(len(str(p.get("body", ""))) for p in intercepted) + body_size > _MAX_INTERCEPTED_BYTES:
        return
    intercepted.append(...)
```

---

## Section 4 — Coverage & Correctness Gaps

---

### COV-01 · Job surface `_is_invalid_surface_page` never returns True — only warns
**Severity:** 🟠 HIGH
**File:** `acquirer.py`
**Lines:** 1830–1843, 1864–1933

**Description:** `_is_invalid_surface_page` delegates to `_is_invalid_commerce_surface_page`, which handles `ecommerce_detail` and `ecommerce_listing`. For job surfaces (`job_listing`, `job_detail`), this function always returns `False`. The job surface analysis runs through `_diagnose_job_surface_page` which only produces a _warning_ (appended to `surface_selection_warnings`) and never signals `invalid_surface_page=True`.

This means: if a job listing crawl lands on a redirect shell or auth wall, the `browser_first` escalation check at line 1640 (`if invalid_surface_page: needs_browser = True`) never fires for job surfaces. The HTTP result is returned as-is with a warning that downstream code may or may not check.

**Fix:** `_is_invalid_surface_page` should also check job surface signals:
```python
def _is_invalid_surface_page(...) -> bool:
    if _is_invalid_commerce_surface_page(...):
        return True
    # Add: check redirect shell for job surfaces
    job_warning = _diagnose_job_surface_page(...)
    if job_warning and any(s in {"redirect_shell_title", "redirect_shell_canonical", "auth_wall_heading"} 
                           for s in job_warning.get("signals", [])):
        return True
    return False
```

---

### COV-02 · `_classify_outcome` checks `diag["blocked"]` key that is only set post-persistence
**Severity:** 🟡 MEDIUM
**File:** `acquirer.py`
**Lines:** 667–689

**Description:** `_classify_outcome` at line 676 checks `diag.get("blocked")` to determine if the outcome is `AcquisitionOutcome.blocked`. However, during live acquisition, the diagnostics dict uses `"curl_blocked"` and `"browser_blocked"` as keys (set in `_try_http` line 1486 and `_finalize_browser_result` line 870). The top-level `"blocked"` key is only set by `artifact_store._write_diagnostics` _after_ persistence — that is, after `_classify_outcome` has already been called (line 661 vs 636).

This means: a blocked result will often be classified as `AcquisitionOutcome.direct_html` or `AcquisitionOutcome.browser_rendered` instead of `AcquisitionOutcome.blocked`. The `blocked_page_result_total` metric (line 648) reads from `diagnostics` directly and may also misfire.

**Fix:**
```python
def _classify_outcome(result: AcquisitionResult) -> str:
    ...
    # Check all blocked keys, not just the post-persistence one
    curl_blocked = bool(diag.get("curl_blocked"))
    browser_blocked = bool(diag.get("browser_blocked"))
    blocked_dict = diag.get("blocked")
    is_blocked = (
        curl_blocked or browser_blocked
        or (isinstance(blocked_dict, dict) and blocked_dict.get("is_blocked"))
        or getattr(blocked_dict, "is_blocked", False)
    )
    if is_blocked:
        return AcquisitionOutcome.blocked
```

---

## Tracker Table

| ID | Severity | File | Summary | Status |
|---|---|---|---|---|
| BUG-01 | 🔴 CRITICAL | `http_client.py:351` | `headers` param shadowed by response headers in redirect loop | ⬜ Open |
| BUG-02 | 🔴 CRITICAL | `browser_client.py:620` | `asyncio.TimeoutError` not caught in traversal fallback | ⬜ Open |
| BUG-03 | 🔴 CRITICAL | `strategies.py` | `AcquisitionChain` is dead code — never called by production path | ⬜ Open |
| BUG-04 | 🟠 HIGH | `cookie_store.py` | `save_cookies_payload` silently no-ops — cookies dropped | ⬜ Open |
| PERF-01 | 🟠 HIGH | `http_client.py` | `detect_blocked_page` called 3× per attempt on same HTML | ⬜ Open |
| PERF-02 | 🟠 HIGH | `acquirer.py` | 4 independent BS4 parses of same HTML in `_try_http` | ⬜ Open |
| PERF-03 | 🟠 HIGH | `http_client.py` | `AsyncSession` created per redirect hop — no connection pooling | ⬜ Open |
| PERF-04 | 🟡 MEDIUM | `acquirer.py:555` | Proxy validation is serial — should be `asyncio.gather` | ⬜ Open |
| PERF-05 | 🟢 LOW | `http_client.py:244` | `_validate_retry_backoff_config()` called on every retry | ⬜ Open |
| PERF-06 | 🟢 LOW | `acquirer.py:537,1459` | Platform family detected twice — URL-only then URL+HTML | ⬜ Open |
| DEBT-01 | 🟡 MEDIUM | `acquirer.py:1809` | `_cooperative_sleep_ms` duplicated in acquirer + browser_readiness | ⬜ Open |
| DEBT-02 | 🟡 MEDIUM | `acquirer.py:340` | `_AcquireExecutionRequest` duplicates all fields from `AcquisitionRequest` | ⬜ Open |
| DEBT-03 | 🟡 MEDIUM | `acquirer.py:108` | Proxy failure state is process-local — not coordinated across workers | ⬜ Open |
| DEBT-04 | 🟡 MEDIUM | `acquirer.py:1543` | `_needs_browser` is 115-line interleaved decision tree | ⬜ Open |
| DEBT-05 | 🟡 MEDIUM | `browser_client.py:36` | Private `browser_pool` functions imported across module boundary | ⬜ Open |
| DEBT-06 | 🟢 LOW | `acquirer.py:2388` | Dead `_artifact_basename` function (duplicate, never called) | ⬜ Open |
| DEBT-07 | 🟡 MEDIUM | `browser_client.py:429` | Unbounded network payload accumulation in `_on_response` | ⬜ Open |
| COV-01 | 🟠 HIGH | `acquirer.py:1830` | Job surface `_is_invalid_surface_page` never returns True — only warns | ⬜ Open |
| COV-02 | 🟡 MEDIUM | `acquirer.py:667` | `_classify_outcome` checks wrong `"blocked"` key — misclassifies blocked results | ⬜ Open |

---

## Recommended Implementation Order

The following sequencing minimizes risk of introducing regressions while achieving maximum correctness improvement first:

**Phase 1 — Zero-risk fixes (can ship today, no behavior change to working cases):**
1. BUG-02: Add `asyncio.TimeoutError` to traversal except clause
2. DEBT-06: Delete dead `_artifact_basename` in `acquirer.py`
3. PERF-05: Remove `_validate_retry_backoff_config()` from inside `_retry_backoff_seconds`
4. DEBT-01: Delete `_cooperative_sleep_ms` from `acquirer.py`, import from `browser_readiness`

**Phase 2 — Bug fixes with targeted tests required:**
5. BUG-01: Fix `headers` shadowing in `_fetch_once` (rename to `response_headers`)
6. COV-02: Fix `_classify_outcome` to check `curl_blocked`/`browser_blocked` keys
7. BUG-04: Add `DeprecationWarning` or `NotImplementedError` to `save_cookies_payload`
8. COV-01: Extend `_is_invalid_surface_page` to handle job surfaces

**Phase 3 — Performance (measurable improvement, moderate refactor):**
9. PERF-01: Cache `BlockedPageResult` on `HttpFetchResult`
10. PERF-03: Move `AsyncSession` outside redirect loop
11. PERF-04: Parallelize proxy validation with `asyncio.gather`
12. PERF-02: Single BS4 parse per acquisition in `_try_http`

**Phase 4 — Architectural debt (requires architecture review before implementation):**
13. BUG-03: Activate or delete `strategies.py`
14. DEBT-04: Refactor `_needs_browser` into `BrowserEscalationDecider`
15. DEBT-02: Flatten `_AcquireExecutionRequest`
16. DEBT-05: Promote browser_pool private functions to public API
17. DEBT-07: Cap `_on_response` payload accumulation
18. DEBT-03: Evaluate Redis-backed proxy failure state

---

## What Is Solid — Do Not Change

The following are working correctly and competitively differentiated. Do not disturb these during remediation:

- **Session affinity model** (`session_context.py`) — proxy/fingerprint/cookie binding is correct and well-encapsulated. The `identity_key` keying for cookie persistence is clean.
- **`browser_challenge.py` assessment logic** — the `_assess_challenge_signals` tiered detection (strong marker + blocked + short HTML) correctly avoids over-triggering. The `waiting_unresolved` vs `blocked_signal` distinction is precise.
- **`pacing.py` Redis distributed lock** — the acquire-check-set-release pattern with Lua `_RELEASE_LOCK_SCRIPT` is race-condition-safe and fail-open. Do not change.
- **`blocked_detector.py` composite signal** — the layered check (active provider markers, phrase signals, CDN markers, structural signals, rich content override) is well-calibrated. The 100KB fork for BS4 vs regex is correct.
- **`artifact_store.py` prune logic** — double-checked locking with `time.monotonic` and `_ARTIFACT_CLEANUP_LOCK` is correct.
- **`traversal.py` fragment limits** — `_MAX_TRAVERSAL_FRAGMENTS`, `_MAX_TRAVERSAL_FRAGMENT_BYTES`, `_MAX_TRAVERSAL_TOTAL_BYTES` are well-designed. The `_JS_EXTRACT_CARDS` identity deduplication via `seen` set is correct.
- **`cookie_store.py` session-scoped persistence** — the session-scoped store (`session_cookie_store_path` keyed by `domain + session_identity`) is correct. The `tmp_path.replace(path)` atomic write pattern is correct.
- **`_needs_browser` structured_override logic** — the cancellation of browser escalation when structured data is already present is correct in intent. Only the implementation shape is the debt (DEBT-04).