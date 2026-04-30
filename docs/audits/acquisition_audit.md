# Acquisition Bucket Audit

Scope: `backend/app/services/acquisition/*`, `crawl_fetch_runtime.py`

## God Files

| File | Lines | Primary Concern |
|------|-------|----------------|
| `browser_runtime.py` | 2,273 | Browser pool, lifecycle, stage runner, diagnostics — 4 concerns in 1 file |
| `browser_page_flow.py` | 1,612 | Navigation, settling, serialization, artifact capture, result builder |
| `traversal.py` | 1,955 | Scroll/load-more/paginate traversal + structured-script detection + recovery |
| `browser_identity.py` | 1,665 | Fingerprint generation, locale coherence, init-script builders |
| `crawl_fetch_runtime.py` | 1,206 | Fetch orchestration BUT also `SharedBrowserRuntime` subclass + thin wrappers |

---

## A1. Thin-Wrapper Function Proliferation (Dead Code)

**Status:** DONE. Verified 2026-04-29 — wrappers no longer exist in `crawl_fetch_runtime.py`.

**Finding:** `crawl_fetch_runtime.py` contained ~10 functions that did nothing except rename and forward to their counterparts in `acquisition/*.py`.

**Impact:** ~200 lines of zero-value indirection removed.

**Fix applied:** Wrappers deleted; canonical functions called directly from `fetch_page()` and internal helpers.

---

## A2. `SharedBrowserRuntime` Duplicated in Two Files

**Status:** DONE. Verified 2026-04-29 — subclass removed from `crawl_fetch_runtime.py`.

**Finding:** `browser_runtime.py` defined `SharedBrowserRuntime` (l.364). `crawl_fetch_runtime.py` defined a subclass `class SharedBrowserRuntime(_SharedBrowserRuntime)` (l.123) that overrode ONLY `_build_context_spec()` and `_build_context_options()`.

**Impact:** Two definitions of the same class name in different modules created confusion about which one was canonical.

**Fix applied:** Subclass deleted; override logic moved into `browser_runtime.py`'s `SharedBrowserRuntime` as conditional paths.

---

## A3. `browser_runtime.py` — 4 Concerns in 1 File

**Status:** PARTIAL. Verified 2026-04-29 — proxy config, diagnostics, and stage runner moved out; `browser_runtime.py` still remains a large pool/lifecycle owner.

**Sub-concerns and line ranges:**
1. **Browser pool management** (l.364-753): `SharedBrowserRuntime` class, runtime registry, eviction, snapshots.
2. **Stage execution framework** (l.2090-2140): `_run_browser_stage`, `_abort_browser_stage`, `_force_close_browser_handles`.
3. **Diagnostics contract builders** (l.226-264, l.1958-2003): `build_browser_diagnostics_contract`, `build_failed_browser_diagnostics`.
4. **Request routing / proxy utilities** (l.306-362, l.1245-1264): `_build_browser_proxy_config`, `_proxy_host_port`, `_display_proxy`, etc.

**Fix:** Split into `browser_runtime_pool.py`, `browser_stage_runner.py`, `browser_diagnostics.py`. Target: each file < 800 lines.

**Partial fix applied:** Added `browser_proxy_config.py` for browser proxy parsing/redaction, `browser_diagnostics.py` for browser diagnostic contracts, and `browser_stage_runner.py` for bounded stage execution/teardown. Remaining work: pool/lifecycle split.

---

## A4. `browser_runtime.py` — Thin Internal Wrappers

**Status:** DONE. Verified 2026-04-29 — pass-through wrappers removed.

**Finding:** Same file contained pass-through wrappers:
- `_navigate_browser_page()` → `navigate_browser_page_impl()`
- `_settle_browser_page()` → `settle_browser_page_impl()`
- `_serialize_browser_page_content()` → `serialize_browser_page_content_impl()`
- `wait_for_listing_readiness()` → `_wait_for_listing_readiness()` → `wait_for_listing_readiness_impl()`
- `probe_browser_readiness()` → `probe_browser_readiness_impl()`
- `expand_detail_content_if_needed()` → `expand_detail_content_if_needed_impl()`
- `classify_low_content_reason()` → `classify_low_content_reason_impl()`
- `looks_like_low_content_shell()` → `classify_low_content_reason_impl()`

**Fix applied:** Wrappers deleted; `*_impl` functions imported directly where stable. ~100 lines recovered.

---

## A5. `runtime.py` — Hardcoded Platform/Signal Constants (INVARIANTS Rule 1 / AP-1 Violations)

**Status:** DONE. Verified 2026-04-29 — constants moved to config.

**Finding:** Generic acquisition code contained bare strings that should be in `config/`.

**Fix applied:** All string tokens and numeric thresholds moved to `config/extraction_rules.py` / `config/signal_markers.py` / `config/runtime_settings.py`. ~50 lines recovered.

---

## A6. `runtime.py` — `_challenge_element_hits()` Duplicated Comprehension Pattern

**Status:** DONE. Verified 2026-04-29 — extracted helper.

**Finding:** Lines 734-774 defined `iframe_src_markers`, `iframe_title_markers`, `script_src_markers`, `html_markers` using the same 5-line comprehension pattern 4 times.

**Fix applied:** Extracted `_mapping_markers_from_config(key: str) -> dict[str, str]` helper. ~20 lines recovered.

---

## A7. `traversal.py` — Inline Constants in Generic Code

**Status:** DONE. Verified 2026-04-29 — constants moved to config.

**Finding:** Module-level `_STRUCTURED_SCRIPT_TYPES`, `_STRUCTURED_SCRIPT_IDS`, `_STRUCTURED_SCRIPT_TEXT_MARKERS`, `_PRICE_HINT_RE`, and `_LISTING_RECOVERY_ACTIONS` were inline.

**Fix applied:** All moved to `config/extraction_rules.py` / `config/traversal_rules.py`.

---

## A8. `browser_page_flow.py` — `_ACCESSIBILITY_SNAPSHOT_TIMEOUT_SECONDS = 0.5`

**Status:** DONE. Verified 2026-04-29 — timeout moved to `config/runtime_settings.py`.

**Finding:** Line 45 had a bare timeout constant.

**Fix applied:** Added `browser_accessibility_snapshot_timeout_seconds`; `browser_page_flow.py` now reads the config setting.

---

## A9. `browser_detail.py` — Thin Wrapper Proliferation

**Status:** DONE. Verified 2026-04-29 — wrappers removed, cross-file imports cleaned up.

**Finding:** Same `*_impl` / wrapper pattern as `browser_runtime.py` and `browser_page_flow.py`.

**Cross-file leakage:** `browser_runtime.py` imported the WRAPPER `expand_all_interactive_elements` from `browser_detail.py` instead of the impl `expand_all_interactive_elements_impl`. Same for `expand_interactive_elements_via_accessibility`.

**Fix applied:** `*_impl` functions imported directly in `browser_runtime.py`. 3 wrappers deleted from `browser_detail.py`. ~40 lines recovered.

---

## A10. `browser_identity.py` — Deep-Copy Boilerplate Repeated 4×

**Status:** DONE. Verified 2026-04-29 — `_safely_clone_fingerprint()` extracted.

**Finding:** The same deep-copy + navigator fallback pattern appears identically in 4 alignment functions.

**Concrete lines:**
- `@/backend/app/services/acquisition/browser_identity.py:325-341`
- `@/backend/app/services/acquisition/browser_identity.py:372-387`
- `@/backend/app/services/acquisition/browser_identity.py:1037-1049`
- `@/backend/app/services/acquisition/browser_identity.py:1081-1093`

Each block is ~13 lines of `try: deep copy; except: try: shallow copy + navigator copy; except: return raw`.

**Fix applied:** Extracted `_safely_clone_fingerprint(raw: Any) -> Any` and reused it in the 4 alignment functions.

---

## A11. `browser_identity.py` — Browser Engine Constants Duplicated with `browser_runtime.py`

**Status:** DONE. Verified 2026-04-29 — constants consolidated in config.

**Finding:** Lines 105-111 defined `_CHROMIUM_BROWSER_ENGINE`, `_PATCHRIGHT_BROWSER_ENGINE`, `_REAL_CHROME_BROWSER_ENGINE`, `_SUPPORTED_BROWSER_ENGINES` — identical constants existed in `browser_runtime.py`.

**Fix applied:** Defined once in `config/browser_engines.py`; imported in both files. ~6 lines recovered.

---

## A12. `browser_identity.py` — Thin Wrapper `build_playwright_context_options`

**Status:** DONE. Verified 2026-04-29 — wrapper removed.

**Finding:** `build_playwright_context_options()` simply called `build_playwright_context_spec()` and returned `.context_options`.

**Fix applied:** Callers use `build_playwright_context_spec(...).context_options` directly. ~15 lines recovered.

---

## A13. `browser_page_flow.py` — Known `_generate_page_markdown` attrs=None Bug

**Status:** DONE. Verified 2026-04-29 — guard present at `browser_page_flow.py:1145-1146`.

**Finding:** `_generate_page_markdown` crashed with `AttributeError: 'NoneType' object has no attribute 'get'` because BeautifulSoup nodes can have `attrs=None` after `decompose()`.

**Fix applied:** Guard added:
```python
for node in list(soup.find_all(True)):
    if not isinstance(getattr(node, "attrs", None), dict):
        node.attrs = {}
```

---

## Summary: Acquisition LOC Reduction Targets

| File | Current | Target | Savings |
|------|---------|--------|---------|
| `browser_runtime.py` | 2,273 | ~1,400 | ~870 |
| `crawl_fetch_runtime.py` | 1,206 | ~900 | ~300 |
| `browser_page_flow.py` | 1,612 | ~1,300 | ~310 |
| `browser_detail.py` | ~800 | ~760 | ~40 |
| `browser_identity.py` | 1,665 | ~1,580 | ~85 |
| `traversal.py` | 1,955 | ~1,700 | ~255 |
| `runtime.py` | 796 | ~650 | ~145 |
| **Total** | **~10,307** | **~8,290** | **~2,015** |

*Savings come from: deleting thin wrappers (~395), moving constants to config (~156), splitting god files (~1,200), deduplicating comprehension patterns (~20), removing duplicate block classification paths (~220), deduplicating deep-copy boilerplate (~35).*
