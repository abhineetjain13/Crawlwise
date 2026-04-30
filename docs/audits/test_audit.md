# Test Bucket Audit

Scope: `backend/tests/**/*.py` (42 test files, ~12,000+ lines total)

---

## T1. `test_crawl_fetch_runtime.py` — `_FetchRuntimeContext` Boilerplate Repeated 6×

**Status:** DONE. Verified 2026-04-29 — `_default_fetch_context` helper exists and is used in `test_crawl_fetch_runtime.py`.

**Finding:** The same 15-keyword-argument `_FetchRuntimeContext(...)` constructor appears identically in every test that exercises browser engine selection logic.

**Concrete lines:**
- `@/backend/tests/services/test_crawl_fetch_runtime.py:69-87`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:123-141`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:186-204`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:477-495`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:519-537`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:548-566`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:590-608`

Each block is ~18 lines. Only `url`, `surface`, and occasionally `forced_browser_engine` change.

**Fix applied:** Added `_default_fetch_context(url: str, surface: str, **overrides) -> _FetchRuntimeContext`.

---

## T2. `test_crawl_fetch_runtime.py` — `PageFetchResult` Boilerplate Repeated 8×

**Status:** DONE. Verified 2026-04-29 — `_page_fetch_result` helper exists and is used in `test_crawl_fetch_runtime.py`.

**Finding:** Same `PageFetchResult(url=..., final_url=..., html=..., status_code=200, method=...)` constructor pattern repeats with minor html/method variations.

**Concrete:** Lines ~88, ~142, ~205, ~454, ~630, ~657, ~704, ~738, ~762.

**Fix applied:** Added `_page_fetch_result(html: str, method: str = "browser", status_code: int = 200)`.

---

## T3. Pipeline Tests — `create_crawl_run` + Same Dict Pattern Repeated 30×

**Status:** DONE. Verified 2026-04-29 — `create_test_run` fixture exists in `conftest.py` and is used by pipeline-style tests.

**Finding:** Every async pipeline/integration test starts with the identical 6-line crawl-run creation boilerplate:
```python
run = await create_crawl_run(
    db_session,
    test_user.id,
    {
        "run_type": "crawl",
        "url": "...",
        "surface": "...",
        "settings": {"respect_robots_txt": False},
    },
)
```

**Concrete occurrences:**
- `test_pipeline_core.py` — 11 occurrences (lines 101, 144, 187, 267, 334, 396, 476, 634, 682, 745, and more)
- `test_review_service.py` — 8 occurrences (lines 25, 90, 158, 249, 308, 366, 432, 470, 510)
- `test_selector_pipeline_integration.py` — 3 occurrences
- `test_run_config_snapshots.py` — 3 occurrences
- `test_record_export_service.py` — 2 occurrences
- `test_product_intelligence.py` — 2 occurrences
- `test_records_api.py` — 1 occurrence

**Fix applied:** Added `create_test_run` fixture in `conftest.py`.

---

## T4. Pipeline Tests — `_fake_acquire` Returning `AcquisitionResult` Repeated 12×

**Status:** DONE. Verified 2026-04-29 — `_fake_acquire_result` helper exists and repeated `_no_adapter` closures were removed.

**Finding:** Same async closure pattern in `test_pipeline_core.py`:
```python
async def _fake_acquire(request):
    return AcquisitionResult(
        request=request,
        final_url=request.url,
        html=_detail_html(),
        method="test",
        status_code=200,
    )
```

**Concrete:** Appears in `test_pipeline_core.py` at lines 155, 200, 279, 346, 417, 488, 645, 702, 765, and others.

**Fix applied:** Extracted `_fake_acquire_result(request, html=_detail_html(), method="test", status_code=200)` and reused module-level `_no_adapter`.

---

## T5. `_detail_html()` / `_listing_html()` Duplicated Across 3 Files

**Finding:** Trivial HTML helper functions defined locally in multiple test files.

**Concrete:**
- `test_pipeline_core.py:30-35` — `_detail_html()` returns `<html><body><h1>Widget Prime</h1></body></html>`
- `test_pipeline_core.py:34-35` — `_listing_html()` returns `<html><body><h1>Empty category</h1></body></html>`
- `test_run_config_snapshots.py:13-21` — `_detail_html()` returns multi-line HTML
- `test_crawl_engine.py:42-52` — `_js_shell_html()` returns shell HTML

**Fix:** Move to `tests/fixtures/html_helpers.py` or add to `conftest.py`:
```python
def detail_html(title: str = "Widget Prime") -> str:
    return f"<html><body><h1>{title}</h1></body></html>"
def listing_html() -> str: ...
```
~15 lines recoverable.

---

## T6. `_read_optional_artifact_text` Duplicated in 3 Files

**Status:** DONE. Verified 2026-04-29 — centralized in `tests/fixtures/loader.py`.

**Finding:** Same artifact-loading helper with slightly different path resolution logic.

**Concrete:**
- `test_crawl_engine.py:55-67` — resolves from `tests/fixtures/artifact_html/` or project root
- `test_detail_extractor_structured_sources.py:22-26` — resolves from project root only
- `test_selectolax_css_migration.py:20-26` — resolves from project root only

**Fix applied:** Added `read_optional_artifact_text()` in `tests/fixtures/loader.py` with optional fixture subdir support.

---

## T7. `_rendered_listing_fragment` Duplicated in `test_crawl_engine.py`

**Finding:** HTML fragment builder with 5 optional kwargs used ~15× within the same file.

**Concrete:** `@/backend/tests/services/test_crawl_engine.py:70-87`

Used at lines ~1041, ~1048, ~1336, ~1369, etc. The function itself is fine, but it could be in a shared fixture file if other listing tests need it.

**Verdict:** Keep in file for now. Only one file uses it. Not duplicated.

---

## T8. `_FakeResponse` / `_FakeClient` Duplicated in 3+ Files

**Finding:** Mock HTTP response/client classes with minor variations.

**Concrete:**
- `test_crawl_fetch_runtime.py:33-53` — `_FakeResponse` with `body()`, `headers`, `url`
- `test_robots_policy.py:11-22` — `_FakeResponse` with `status_code`, `text`; `_FakeAsyncClient`
- `test_job_platform_adapters.py` — Multiple inline `_FakeResponse` / `_FakeClient` classes (lines 177, 219, 265, 316, 386)

**Fix:** Add `_FakeHttpxResponse`, `_FakeAsyncClient` to `tests/fixtures/http_mocks.py` or `conftest.py`. ~40 lines recoverable.

---

## T9. `test_traversal_runtime.py` + `test_browser_expansion_runtime.py` — Fake Playwright Classes Duplicated

**Finding:** `_FakeLocator`, `_FakePage`, `_State`, `_EmptyRoleLocator`, `_RoleLocator` classes in `test_traversal_runtime.py` (~200 lines) are conceptually similar to inline Playwright mocks in `test_browser_expansion_runtime.py` (lines 113-185).

**Assessment:** The traversal fakes are much more elaborate (scroll states, pagination, role controls). The expansion-runtime fakes are simpler (page with `locator()`, `evaluate()`, `content()`). They serve different needs. Not a true duplication.

**Verdict:** Keep separate. No merge benefit.

---

## T10. `test_browser_context.py` — `SimpleNamespace` Fingerprint Mock Repeated 6×

**Status:** DONE. Verified 2026-04-29 — `_make_fingerprint` helper exists and is used in `test_browser_context.py`.

**Fix applied:** Added `_make_fingerprint(...)` helper in `test_browser_context.py`.

---

## T11. `test_harness_support.py` — Assertion Dicts Repeated Inline

**Finding:** Many tests assert against full dict/list literals that could be parameterized.

**Concrete:**
- `test_parse_test_sites_markdown_reads_urls_from_tail` — asserts against 2-row list of dicts (lines 60-71)
- `test_build_explicit_sites_preserves_explicit_surface_order` — asserts against 2-row list (lines 105-116)

**Assessment:** These are assertion literals, not setup boilerplate. They are readable and test-specific. No action needed.

**Verdict:** Keep as-is.

---

## T12. `test_crawl_fetch_runtime.py` — `monkeypatch.setattr` for `curl_cffi` Module Replacement Repeated 3×

**Finding:** Same `monkeypatch.setitem(sys.modules, "curl_cffi", SimpleNamespace(requests=SimpleNamespace(get=_fake_get)))` pattern.

**Concrete:** Lines ~387-391, ~425-429.

**Fix:** Extract `_patch_curl_cffi(monkeypatch, fake_get)` helper. ~10 lines recoverable.

---

## T13. `test_selectolax_css_migration.py` — `_fake_structured_payloads` Repeated 2×

**Finding:** Same closure pattern for mocking `collect_structured_source_payloads`.

**Concrete:** Lines ~599-605 and ~1130-1136 (estimated).

**Fix:** Extract a helper if used again. Low priority (~6 lines).

---

## T14. `test_state_mappers.py` — Inline `monkeypatch.setattr(js_state_mapper, "glom", _fake_glom)` Repeated 3×

**Finding:** Same monkeypatch pattern for mocking `glom` failures.

**Concrete:** Lines ~883, ~904, ~957.

**Fix:** Add `_patch_glom(monkeypatch, side_effect=None)` helper. ~6 lines recoverable.

---

## T15. `test_config_imports.py` — Config Import Smoke Test (Single File, No Issue)

**Finding:** Tests that config modules import cleanly. This is a legitimate smoke test.

**Verdict:** Keep as-is. No boilerplate issue.

---

## T16. `test_crawl_engine.py` — Inline Artifact HTML Fixtures Embedded in Test Code

**Finding:** Large HTML strings (~100-500 chars each) embedded directly in test functions for artifact-based tests. There are ~30+ such inline HTML blobs.

**Concrete examples:**
- `@/backend/tests/services/test_crawl_engine.py:91-161` — `listing_visual_elements` artifact dict with 4 nested element dicts (~70 lines)
- `@/backend/tests/services/test_crawl_engine.py:163-240` — Another visual listing test

**Assessment:** These are test data, not code. Moving them to `.json` fixture files would hurt readability when debugging failures (you'd need to open a second file). The current inline approach makes the test self-contained.

**Verdict:** Acceptable. Not boilerplate.

---

## T17. `test_pipeline_core.py` — `_fake_run_adapter` / `_fake_extract_records` / `_no_adapter` Repeated

**Finding:** Same 3-lambda no-op closures repeated 5+ times:
```python
async def _no_adapter(*_args, **_kwargs):
    return None

def _fake_extract_records(html, *_args, **_kwargs):
    return [...]
```

**Concrete:** Lines ~236-237, ~300-301, ~366-367, and others.

**Fix:** Define once at module level. ~15 lines recoverable.

---

## T18. `test_product_intelligence.py` — Repetitive DB Setup for Domain Memory Tests

**Finding:** Same `save_domain_memory` + `load_domain_memory` setup/assert pattern repeated.

**Concrete:** Not yet inspected in full detail, but grep shows multiple `create_crawl_run` + domain memory operations.

**Assessment:** Domain memory tests are inherently stateful and repetitive. Extracting a `_seed_domain_memory(db_session, host, ...)` helper would help.

**Estimated savings:** ~30 lines.

---

## Summary: Test LOC Reduction Targets

| Pattern | Files | Occurrences | Lines Each | Total Savings |
|---------|-------|-------------|------------|---------------|
| `_FetchRuntimeContext` boilerplate | `test_crawl_fetch_runtime.py` | 6 | 15 | ~90 |
| `PageFetchResult` boilerplate | `test_crawl_fetch_runtime.py` | 8 | 5 | ~40 |
| `create_crawl_run` dict pattern | 7 files | 30 | 5 | ~150 |
| `_fake_acquire` AcquisitionResult | `test_pipeline_core.py` | 12 | 5 | ~60 |
| `_detail_html()` / `_listing_html()` | 3 files | 3 | 5 | ~15 |
| `_read_optional_artifact_text` | 3 files | 3 | 7 | ~20 |
| `_FakeResponse` / `_FakeClient` | 3 files | 5 | 8 | ~40 |
| `SimpleNamespace` fingerprint | `test_browser_context.py` | 6 | 20 | ~100 |
| `curl_cffi` monkeypatch | `test_crawl_fetch_runtime.py` | 3 | 4 | ~10 |
| `_no_adapter` / `_fake_extract_records` | `test_pipeline_core.py` | 5 | 3 | ~15 |
| `_patch_glom` helper | `test_state_mappers.py` | 3 | 2 | ~6 |
| Domain memory setup | `test_product_intelligence.py` | 4 | 8 | ~30 |
| **Total** | | **85** | | **~576** |

*Note: Savings are conservative. Actual reduction may be higher if nested closures are also counted.*

---

## Priority Actions

| Priority | Item | Impact |
|----------|------|--------|
| DONE | Extract `_create_test_run` helper for pipeline tests | ~150 LOC, used in 7 files |
| DONE | Extract `_default_fetch_context` + `_page_fetch_result` in `test_crawl_fetch_runtime.py` | ~130 LOC |
| DONE | Extract `_make_fingerprint` in `test_browser_context.py` | ~100 LOC |
| DONE | Extract `_fake_acquire_result` + `_no_adapter` in `test_pipeline_core.py` | ~75 LOC |
| PARTIAL | Centralize `_read_optional_artifact_text` + `_FakeResponse` in `tests/fixtures/` | Artifact loader + reusable HTTP body/text mocks done; adapter-specific mocks remain local |

---

## INVARIANTS + ENGINEERING STRATEGY Violations in Tests

### V1. AP-7 / AP-17: Private-Function Test Coupling — 4 Files

**Status:** DONE. Verified 2026-04-29 — grep found no listed private imports.

**Finding:** Tests import and assert on underscore-prefixed private functions/constants from production modules. ENGINEERING STRATEGY AP-7: "Tests that import private functions or constants from service internals. Fix: Delete these tests. Write contract tests that assert observable behavior from public APIs."

**Concrete:**
- `@/backend/tests/services/test_records_api.py:8` — `from app.api.records import _route_responses`
- `@/backend/tests/services/test_publish_metrics.py:5` — `from app.services.publish.metadata import _stringify_value`
- `@/backend/tests/services/test_pacing.py:6` — `from app.services.acquisition.pacing import _normalized_host`
- `@/backend/tests/services/test_crawls_api_domain_recipe.py:8` — `from app.api.crawls import _domain_run_profile_payload`

**Assessment:** `_normalized_host` test is a pure-helper unit test (low value per Testing Rules). `_route_responses` and `_domain_run_profile_payload` test private API internals. `_stringify_value` tests a trivial formatter.

**Fix applied:** Deleted or rewrote the listed private-import tests.

---

### V2. AP-10 / INVARIANTS Rule 1: Direct Global `crawler_runtime_settings` Mutation — 8 Files

**Status:** DONE. Verified 2026-04-29 — `patch_settings` fixture exists and direct assignment grep is clean.

**Finding:** Tests mutate the global singleton `crawler_runtime_settings` directly and restore with `try/finally`. This bypasses env-controlled settings and creates cross-test leakage risk.

**Concrete files/lines:**
- `@/backend/tests/services/test_selector_pipeline_integration.py:224-324` — Mutates `selector_self_heal_enabled`, `selector_self_heal_min_confidence` (twice in one test)
- `@/backend/tests/services/test_run_config_snapshots.py:124-162` — Same settings mutation + extra mid-test mutation at line 138
- `@/backend/tests/services/test_platform_detection.py:119-137` — Mutates `platform_detection_html_search_limit`
- `@/backend/tests/services/test_pacing.py:18-36` — Mutates `acquire_host_min_interval_ms`, `protected_host_additional_interval_ms`
- `@/backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py:214-230` — Mutates `selector_self_heal_enabled`, `selector_self_heal_min_confidence`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:296-301` — Mutates `force_httpx`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:370-398` — Mutates `http_user_agent`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:413-437` — Mutates `curl_impersonate_target`
- `@/backend/tests/services/test_crawl_fetch_runtime.py:1861-1906` — Mutates `http_max_retries`, `http_retry_backoff_base_ms`, `http_retry_backoff_max_ms`
- `@/backend/tests/services/test_browser_expansion_runtime.py:862-938` — Mutates `browser_navigation_optimistic_wait_ms`, `browser_spa_implicit_networkidle_timeout_ms`
- `@/backend/tests/services/test_browser_expansion_runtime.py:2145-2180` — Mutates `detail_aom_expand_max_interactions`

**Total occurrences:** ~15 individual setting mutations across 8 files.

**Fix applied:** Added a `monkeypatch`-based settings fixture to `conftest.py`:
```python
@pytest.fixture
def patch_settings(monkeypatch):
    def _patch(**kwargs):
        originals = {}
        for key, value in kwargs.items():
            originals[key] = getattr(crawler_runtime_settings, key)
            monkeypatch.setattr(crawler_runtime_settings, key, value)
        return originals
    return _patch
```
Replaced `original = ...; try: settings.x = y; finally: settings.x = original` blocks with `patch_settings(x=y)` context.

---

### V3. INVARIANTS Rule 1 / AP-4: Hardcoded Platform/Provider Names in Tests — 6 Files

**Finding:** Bare string constants for platform names (`"shopify"`, `"greenhouse"`) and provider names (`"cloudflare"`, `"akamai"`, `"datadome"`, `"DataDome"`) used directly in test assertions and mock data.

**Concrete:**
- `@/backend/tests/services/test_platform_detection.py:16-18` — Asserts `detect_platform_family(...url...) == "greenhouse"`
- `@/backend/tests/services/test_publish_metrics.py:17` — `platform_family="shopify"` in mock data
- `@/backend/tests/services/test_publish_metrics.py:55,101,108` — Asserts `metrics["platform_family"] == "shopify"`
- `@/backend/tests/services/test_publish_metrics.py:114,125,139,154,167` — `"cloudflare"`, `"akamai"`, `"datadome"` in diagnostics dicts
- `@/backend/tests/services/test_pipeline_core.py:217,218,295,296,358,359,840` — `"akamai"`, `"datadome"` in challenge_provider_hits
- `@/backend/tests/services/test_browser_surface_probe.py:123,124,133,134,144,145` — `"akamai"` repeated 6× in mock classifications
- `@/backend/tests/services/test_harness_support.py:189,192,205,216,217,744,745,746,749` — `"cloudflare"`, `"DataDome"`, `"datadome"` repeated
- `@/backend/tests/services/test_state_mappers.py:787,807` — `"company_name": "Greenhouse"` in expected output

**Assessment:** These are test assertions against known fixture data and mock return values. The platform names are part of the test contract (e.g., asserting that a URL is classified as "greenhouse"). This is acceptable for tests — the violation signature in INVARIANTS targets *runtime code*, not test assertions.

**Verdict:** Acceptable in tests. These are not INVARIANTS violations because tests do not control runtime behavior.

---

### V4. `test_structure.py` — Allowlist Is a Debt Ledger, Not Shrinking

**Finding:** `ALLOWED_PRIVATE_SERVICE_IMPORTS` in `test_structure.py` contains 60 entries (lines 28-88). Per ENGINEERING STRATEGY hygiene gate #3: "Allowlists are debt ledgers, not parking lots. If a private import or exception is removed in code, remove it from the allowlist in the same change."

**Concrete:** The allowlist grew from ~30 entries to 60. It includes cross-bucket imports like:
- `detail_extractor.py -> app.services.extract.detail_dom_extractor:_backfill_variants_from_dom_if_missing`
- `detail_extractor.py -> app.services.extract.detail_identity:_detail_identity_codes_from_record_fields`
- `crawl_fetch_runtime.py -> app.services.acquisition.browser_runtime:_display_proxy`

**Assessment:** These represent real technical debt that the test file is documenting rather than enforcing reduction. The allowlist should shrink as code is refactored.

**Fix:** Not a test-code issue — it's a production-code issue (already flagged in acquisition/extraction audits). The test file is correctly acting as a ratchet. No action on tests; action is on production code to remove the imports.

---

### V5. Low-Value Tests — Private Helper Call Order / Constant Existence

**Status:** DONE. Verified 2026-04-29 — listed private helper imports no longer exist.

**Finding:** ENGINEERING STRATEGY Testing Rules explicitly list "private helper call order, mocks that restate implementation, assertions that freeze harmless refactors, tests that import private constants just to check they exist" as low-value tests to delete.

**Concrete candidates:**
- `@/backend/tests/services/test_pacing.py:9-11` — `test_normalized_host_preserves_port_information()` tests `_normalized_host` (private helper). Only asserts `"example.com:443" == "example.com:443"`. Low value.
- `@/backend/tests/services/test_publish_metrics.py:5` — Imports `_stringify_value` directly. The test likely asserts trivial formatting behavior that `str()` already guarantees.

**Fix applied:** Deleted or rewrote the listed tests.

---

## Summary: INVARIANTS/STRATEGY Violations in Tests

| Violation | Files | Count | Risk Level |
|-----------|-------|-------|------------|
| Private-function imports (AP-7/AP-17) | 4 | 4 imports | Medium |
| Global settings mutation (AP-10) | 8 | ~15 mutations | **High** — cross-test leakage |
| Hardcoded platform names (tests only) | 6 | ~30 occurrences | Low — test assertions |
| Allowlist growth (not test bug) | 1 | 60 entries | Medium — debt ledger |
| Low-value private helper tests | 2 | 2 tests | Low |

**Priority fix closed:** Global settings mutation (V2) now uses `patch_settings`; direct assignment grep is clean.
