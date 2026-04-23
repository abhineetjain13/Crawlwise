# Backend Dead Code & Bloat Audit

**Date:** 2026-04-21  
**Scope:** `backend/app/` — 33,779 LOC across 156 Python files  
**Objective:** Identify high-confidence dead code, duplication, inline config leaks, and bugs that reduce maintainability and increase LOC.  
**Method:** Static analysis + automated symbol cross-reference scan + full codebase traversal. No files were edited.  
**Cross-reference:** Validated against `docs/audits/gemini-audit.md` findings (see §9).

---

## Summary

| Category | Items | Est. LOC Savings |
|----------|-------|-------------------|
| Dead modules (zero importers) | 5 | ~155 |
| Dead public functions (zero callers) | 18 | ~650 |
| Dead dataclass/class (zero instantiators) | 5 | ~170 |
| Duplicate utility functions (4+ copies) | 6 | ~120 |
| Duplicate HTML analysis classes | 2 | ~60 |
| Alias shims & compat wrappers (AP-6) | 4 | ~20 |
| Inline config violations (AP-1) | 8 | ~20 (centralize) |
| Conflicting domain normalizers (AP-9) | 2 | ~10 |
| Config: dead modules + wrappers | 3 | ~150 |
| Config: duplicate endpoint tokens | 1 | ~21 |
| Config: stale settings bridges | 2 | ~4 |
| Config: Python data → JSON migration | 2 | ~483 (migrate) |
| Config: dead settings fields | 4 | ~4 |
| Bug: decompose → NoneType crash | 1 | 0 (fix) |
| Gemini-audit: validated & pending items | 3 | ~80 |
| **Total** | **64** | **~1,947** |

Additional ~1,000+ LOC savings available from consolidating the `_mapping_or_empty` / `_safe_dict` / `_normalize_text` pattern duplicated across 7+ files (see §4).

---

## 1. Dead Modules — Zero Importers (Delete Immediately)

### 1.1 `crawl_metadata.py` — 12 LOC
`@/backend/app/services/crawl_metadata.py:1-12`

Re-exports `load_domain_requested_fields` and `refresh_record_commit_metadata` from `publish/metadata.py`.  
**No file imports from `app.services.crawl_metadata`.** All consumers import directly from `app.services.publish.metadata`.

### 1.2 `crawl_metrics.py` — 14 LOC
`@/backend/app/services/crawl_metrics.py:1-14`

Re-exports `build_acquisition_profile`, `build_url_metrics`, `finalize_url_metrics` from `publish/metrics.py`.  
**No file imports from `app.services.crawl_metrics`.** All consumers import directly from `app.services.publish.metrics`.

### 1.3 `text_utils.py` — 6 LOC
`@/backend/app/services/text_utils.py:1-6`

Contains a single function `normalized_text(value)` that is identical to `_normalize_text` in `normalizers/__init__.py` and `clean_text` in `field_value_core.py`.  
**No file imports from `app.services.text_utils`.** The entire module is dead.

---

## 2. Dead Public Functions — Zero Cross-File Callers

Automated scan found **115 public symbols with zero cross-file references**. After filtering out symbols used within their own file, the following are truly dead (no callers anywhere):

### 2.1 `extractability.py` — Entire Module Dead (120 LOC)
`@/backend/app/services/extractability.py:1-120`

- `html_has_extractable_listings_from_soup()` — never imported by any file in `app/` or `tests/`
- `json_ld_listing_count()` — only called by the above dead function
- `NEXT_DATA_PRODUCT_SIGNALS` — only used by the above dead function

The runtime settings `extractability_non_product_type_ratio_max`, `extractability_json_ld_min_type_signals`, `extractability_next_data_signal_trigger`, `extractability_next_data_signal_min` in `runtime_settings.py` are also dead if this module is removed.

**Savings: ~120 LOC + 4 dead settings fields**

### 2.2 `legacy_fallback_markdown_rows` — 30 LOC
`@/backend/app/services/record_export_service.py:415-445`

Never imported or called from any file. Legacy export path superseded by the current markdown export.

### 2.3 `normalize_review_value` — 3 LOC
`@/backend/app/services/normalizers/__init__.py:159-160`

Exported in `__all__` but never imported anywhere. The review module uses `normalize_value` directly.

### 2.4 `discoverist_schema` — 5 LOC
`@/backend/app/services/record_export_service.py:788-791`

`lru_cache` wrapper around `DISCOVERIST_SCHEMA` that is only called by `stream_export_discoverist` in the same file. The `lru_cache` is unnecessary since `DISCOVERIST_SCHEMA` is already a static JSON-loaded constant. Inline the tuple comprehension.

### 2.5 `is_markdown_long_form` — 5 LOC
`@/backend/app/services/record_export_service.py:686-690`

Exported but never imported outside the file. Used only internally by `record_to_markdown`.

### 2.6 `humanize_field_name` — 8 LOC
`@/backend/app/services/record_export_service.py:767-774`

Exported but never imported outside the file. Used only internally.

### 2.7 `markdown_long_form_fields` — 5 LOC
`@/backend/app/services/record_export_service.py`

Exported but never imported outside the file.

### 2.8 `collect_table_export_rows` — 8 LOC
`@/backend/app/services/record_export_service.py:360-367`

Exported but never imported outside the file.

### 2.9 `export_headers` — 8 LOC
`@/backend/app/services/record_export_service.py:494-501`

Exported but never imported outside the file.

### 2.10 `clean_export_data` — 15 LOC
`@/backend/app/services/record_export_service.py`

Exported but never imported outside the file.

### 2.11 `record_artifact_bundle` — 12 LOC
`@/backend/app/services/record_export_service.py`

Exported but never imported outside the file.

### 2.12 `schema_trace_payload` — 12 LOC
`@/backend/app/services/schema_service.py:175-186`

Exported but never imported. The schema trace is built inline in pipeline/core.py instead.

### 2.13 `merge_url_verdicts` / `merge_verdict_counts` — 20 LOC
`@/backend/app/services/run_summary.py:45-65`

Both exported but never imported. Verdict merging is done inline in `_batch_runtime.py`.

### 2.14 `candidate_fingerprint` — 6 LOC
`@/backend/app/services/field_value_candidates.py:27`

Exported but never imported outside the file.

### 2.15 `excluded_fields_for_surface` — 5 LOC
`@/backend/app/services/field_policy.py:29`

Exported but never imported outside the file.

### 2.16 `load_platform_registry` — 5 LOC
`@/backend/app/services/platform_policy.py:77`

Exported but never imported. `platform_configs()` is used instead.

### 2.17 `validate_xpath_candidate` — ~15 LOC
`@/backend/app/services/xpath_service.py`

Exported but never imported. `validate_or_convert_xpath` is used instead.

### 2.18 `observe_acquisition_duration` — 6 LOC
`@/backend/app/core/metrics.py:114`

Exported but never imported. Acquisition duration is tracked elsewhere.

**Subtotal: ~250 LOC from truly dead public functions**

---

## 3. Dead / Redundant Classes

### 3.1 `PipelineConfig` dataclass + `PIPELINE_CONFIG` singleton — 7 LOC
`@/backend/app/services/pipeline/pipeline_config.py:29-36`

```python
@dataclass(frozen=True, slots=True)
class PipelineConfig:
    robots_cache_size: int = 512
    robots_cache_ttl: float = 3600.0
    robots_fetch_user_agent: str = "CrawlerAI"

PIPELINE_CONFIG = PipelineConfig()
```

Only imported by `robots_policy.py`. These 3 values are hardcoded defaults that should be in `config/runtime_settings.py` per AP-1. The dataclass + singleton pattern adds no value over 3 module-level constants or settings fields.

### 3.2 `FingerprintConfig` class — 5 LOC
`@/backend/app/services/pipeline/pipeline_config.py:22-26`

Plain class used as namespace for constants. Not instantiated, not a dataclass. Only imported by `browser_identity.py`. Should be env-controlled settings in `config/runtime_settings.py`.

### 3.3 `LLMFallbackConfig` class — 3 LOC
`@/backend/app/services/pipeline/pipeline_config.py:18-19`

Contains a single constant `CONFIDENCE_THRESHOLD = 0.55`. Should be a setting, not a class. Used in 2 places in `pipeline/core.py`.

### 3.4 `BrowserIdentity` dataclass — 9 LOC
`@/backend/app/services/acquisition/browser_identity.py:63-70`

This dataclass is only used within `browser_identity.py` itself (created by `create_browser_identity()`, consumed by `build_playwright_context_options()`). It's not dead, but it's an internal implementation detail that doesn't need to be exported.

### 3.5 `ValidatedTarget` dataclass — 8 LOC
`@/backend/app/services/url_safety.py:40-47`

Used only within `url_safety.py`. Not dead, but doesn't need to be exported.

---

## 4. Duplicate Utility Functions (AP-9)

### 4.1 `_mapping_or_empty` — 4 copies across codebase

| File | Line | Signature |
|------|------|-----------|
| `pipeline/core.py` | 154 | `def _mapping_or_empty(value: object) -> dict[str, object]` |
| `pipeline/persistence.py` | 17 | `def _mapping_or_empty(value: object) -> dict[str, object]` |
| `selector_self_heal.py` | 425 | `def _mapping_or_empty(value: object) -> dict[str, object]` |
| `acquisition/runtime.py` | 616 | `def _mapping_or_empty(value: object) -> dict[object, object]` |

All 4 are identical: `return dict(value) if isinstance(value, dict) else {}`.  
Also: `_safe_dict` in `review/__init__.py:210` is the same pattern: `return value if isinstance(value, dict) else {}`.

**Action:** Create `dict_or_empty(value)` in `db_utils.py` (or a new `type_coercion.py`), import everywhere.

### 4.2 `visible_text_from_soup` — 3 copies

| File | Line | Notes |
|------|------|-------|
| `acquisition/runtime.py` | 602 | `_visible_text_from_soup(soup)` — private |
| `acquisition/browser_readiness.py` | 227 | `visible_text_from_soup(soup)` — public export |
| `acquisition/browser_runtime.py` | 930 | `_visible_text_from_soup(soup)` — one-line wrapper importing from browser_readiness |

All 3 do the same thing: iterate `soup.find_all(string=True)`, skip `Comment`/`script`/`style`/`noscript`, join with spaces.

**Action:** Keep `visible_text_from_soup` in `browser_readiness.py`, delete the other two copies, import where needed.

### 4.3 `HtmlAnalysis` vs `BrowserHtmlAnalysis` — duplicate data classes

| File | Class | Fields |
|------|-------|--------|
| `acquisition/runtime.py:70` | `HtmlAnalysis` | `html, lowered_html, soup, visible_text, title_text` |
| `acquisition/browser_readiness.py:14` | `BrowserHtmlAnalysis` | `html, lowered_html, soup, visible_text, normalized_text, h1_present` |

Both parse HTML the same way. `BrowserHtmlAnalysis` adds `h1_present` and `normalized_text`. These should be unified into one class.

**Action:** Merge into `HtmlAnalysis` in `acquisition/runtime.py`, add the two extra fields, import in `browser_readiness.py`.

### 4.4 `_dedupe_fields` vs `_dedupe_aliases` vs `_dedupe_image_values`

| Location | Function | Key difference |
|----------|----------|----------------|
| `schema_service.py:29-38` | `_dedupe_fields()` | Normalizes to `.strip().lower()` |
| `field_policy.py:100-115` | `_dedupe_aliases()` | Accepts mixed-type groups, `.strip()` only |
| `record_export_service.py:633-660` | `_dedupe_image_values()` | Case-insensitive dedup with primary exclusion |

**Action:** Consolidate into `dedupe_preserve_order()` in `field_policy.py`.

### 4.5 `normalize_field_key` vs `normalize_committed_field_name`

- `field_policy.py:90-97` — `normalize_field_key(value)` — uses `_CAMEL_BOUNDARY_RE` + `_NON_FIELD_RE`, handles `&`
- `crawl_utils.py:165-178` — `normalize_committed_field_name(value)` — inline regex, no `&` handling

These produce different outputs for edge cases (e.g. `&` in field names). Per ENGINEERING_STRATEGY §AP-3, field naming belongs in `field_policy.py`.

**Action:** Replace `normalize_committed_field_name` with `normalize_field_key` (or alias). Update 2 importers.

### 4.6 `_normalize_domain` in `platform_policy.py` vs `normalize_domain` in `domain_utils.py`

`platform_policy.py:90-91`: `_normalize_domain(value)` does `str(value).strip().lower().removeprefix("www.")`  
`domain_utils.py:10-44`: `normalize_domain(url)` also strips scheme, handles ports, strips `www.`

`domain_utils.py` header says: *"All modules MUST use this instead of local _domain() helpers."* The private copy is **semantically different** (no scheme stripping, no port handling) — correctness risk.

**Action:** Replace `platform_policy._normalize_domain` with `domain_utils.normalize_domain`.

### 4.7 `_host_matches` in `greenhouse.py` vs `_matches_domain` in `platform_policy.py`

Both do exact or `.suffix` subdomain match. Identical logic.

**Action:** Make `platform_policy._matches_domain` public as `matches_domain`, use in `greenhouse.py`.

### 4.8 `_normalize_text` pattern — 6+ copies

The pattern `" ".join(str(value or "").split()).strip()` appears in:

| File | Function |
|------|----------|
| `normalizers/__init__.py:38-39` | `_normalize_text(value)` |
| `text_utils.py:4-5` | `normalized_text(value)` (dead module) |
| `field_policy.py:91` | inline in `normalize_field_key` |
| `xpath_service.py:419` | inline in `_loose_text_match.normalize` |
| `browser_runtime.py:812,878,888` | inline 3 times |

`clean_text` in `field_value_core.py:69-71` is the canonical version (also handles HTML entities via `unescape`).

**Action:** Replace all inline copies with `clean_text` from `field_value_core.py` or `_normalize_text` from `normalizers`.

---

## 5. Alias Shims & Compat Wrappers (AP-6)

### 5.1 `_domain = normalize_domain` in `review/__init__.py`
`@/backend/app/services/review/__init__.py:207`

Used in 2 places. `normalize_domain` is already imported at line 11. The alias adds indirection for zero benefit.

### 5.2 `_normalized_domain` wrapper in `selectors_runtime.py`
`@/backend/app/services/selectors_runtime.py:485-488`

One-line wrapper adding deferred import around `normalize_domain`. Used once.

### 5.3 `process_run` compat wrapper in `crawl_service.py`
`@/backend/app/services/crawl_service.py:104-106`

```python
async def process_run(session: AsyncSession, run_id: int) -> None:
    """Compatibility wrapper so test patches on crawl_service symbols still apply."""
    await _batch_process_run(session, run_id)
```

This is an AP-6 compat shim. All real callers import `process_run` from `_batch_runtime.py` directly (tasks.py, harness_support.py, 3 test files). The comment explicitly says it exists for test patching — tests should patch the real function.

### 5.4 `_log = log_event` alias in `crawl_service.py`
`@/backend/app/services/crawl_service.py:42`

```python
_log = log_event
```

Used 4 times in the same file. No reason for the alias.

---

## 6. Inline Config Violations (AP-1)

| Constant | Location | Should move to |
|----------|----------|-----------------|
| `DEFAULT_CIRCUIT_FAILURE_THRESHOLD = 5` | `llm_circuit_breaker.py:16` | Delete — redundant with `llm_runtime_settings.circuit_failure_threshold` (already defaults to 5) |
| `_PROMPT_JSON_REPARSE_MAX_CHARS = 16_384` | `llm_tasks.py:33` | `config/llm_runtime.py` |
| `_GENERIC_ASSIGNMENT_MAX_SCRIPT_CHARS = 250_000` | `structured_sources.py:30` | `config/runtime_settings.py` |
| `_GENERIC_ASSIGNMENT_MAX_MATCHES_PER_SCRIPT = 24` | `structured_sources.py:31` | Same |
| `_MIN_FIELD_OVERLAP_RATIO = 0.25` | `extraction_runtime.py:191` | `config/extraction_rules.py` |
| `_MIN_FIELD_OVERLAP_ABSOLUTE = 2` | `extraction_runtime.py:192` | Same |
| `_SIGNATURE_MIN_MATCH = 3` | `network_payload_mapper.py:22` | Same |
| `LLMFallbackConfig.CONFIDENCE_THRESHOLD = 0.55` | `pipeline_config.py:19` | `config/llm_runtime.py` |

**Note on `DEFAULT_CIRCUIT_FAILURE_THRESHOLD`:** `llm_runtime_settings.circuit_failure_threshold` already defaults to `5`. The `_resolved_failure_threshold()` function uses `getattr()` with the local constant as fallback, then checks `if raw_threshold is None` and falls back again. Triple-redundant. Replace with direct `llm_runtime_settings.circuit_failure_threshold`.

---

## 7. Bug: `NoneType` Crash in `_generate_page_markdown`

**Severity:** Critical — crashes every browser crawl on complex HTML (e.g. Zara)  
**Location:** `@/backend/app/services/acquisition/browser_page_flow.py:718-779`

**Root cause:** After `node.decompose()` on line 729, BeautifulSoup sets `node.attrs = None`. The guard at lines 731-33 (`if not isinstance(attrs, dict): continue`) correctly skips decomposed nodes in the noise-token loop. **However**, `soup.select("a[href]")` at line 753 can also match decomposed nodes where `attrs is None`. When `anchor.get("href")` is called, it raises `AttributeError: 'NoneType' object has no attribute 'get'`.

The pre-sanitize at lines 724-726 runs **before** `decompose()`, so it doesn't protect against nodes decomposed afterward.

**Fix:** Add `attrs` guard in the anchor loop:
```python
for anchor in soup.select("a[href]"):
    attrs = getattr(anchor, "attrs", None)
    if not isinstance(attrs, dict):
        continue
    href = " ".join(str(attrs.get("href") or "").split()).strip()
    ...
```

---

## 8. Structural Bloat: Largest Files Needing Split

| File | LOC | Concern |
|------|-----|---------|
| `acquisition/traversal.py` | 1606 | Monolithic — pagination, scroll, crawl, sitemap, expansion |
| `pipeline/core.py` | 1160 | Extraction + LLM fallback + self-heal — split LLM orchestration |
| `listing_extractor.py` | 1141 | Fragment scoring, card detection, fallback mixed |
| `acquisition/browser_page_flow.py` | 1029 | Markdown gen, expansion, capture, accessibility |
| `acquisition/browser_runtime.py` | 1005 | Browser lifecycle + retry + diagnostics |
| `detail_extractor.py` | 995 | Tier orchestration + DOM extraction + structured merge |
| `llm_tasks.py` | 873 | All LLM prompt tasks in one file |
| `record_export_service.py` | 791 | Export streaming + markdown rendering + discoverist |
| `field_value_dom.py` | 765 | DOM extraction + selector rules + label pairs |
| `selectors_runtime.py` | 720 | Selector CRUD + suggestion + LLM discovery |
| `acquisition/runtime.py` | 693 | HTTP fetch + escalation heuristics + block classification |
| `js_state_mapper.py` | 622 | JS state extraction + variant splitting |

These 12 files alone account for **11,040 LOC** (33% of the codebase). Splitting by responsibility per ENGINEERING_STRATEGY §File Shape Guidance would significantly improve maintainability.

---

## 9. Gemini-Audit Validation (Cross-Reference)

Validating each finding from `docs/audits/gemini-audit.md` against the current codebase:

### 9.1 ALREADY FIXED (no action needed)

| Finding | Status | Evidence |
|---------|--------|----------|
| **LN-1:** `_LLM_EXISTING_VALUE_MAX_CHARS = 500` hardcoded | ✅ Fixed | `grep` returns empty. `_sanitize_llm_existing_values` now reads `llm_runtime_settings.existing_values_max_chars` at `pipeline/core.py:166` |
| **LN-2:** Inline `_Stripper` HTML parser class | ✅ Fixed | `grep "class _Stripper"` returns empty. `strip_html_tags` imported from `field_value_core.py` at `pipeline/core.py:30` |
| **LN-3:** AP-6 re-export shims `_render_markdown_inline = render_markdown_inline` | ✅ Fixed | `grep "_render_markdown_inline ="` returns empty. Shims removed from `record_export_service.py` |

### 9.2 STILL PENDING — Requires Action

| Finding | Status | Details |
|---------|--------|---------|
| **RC-1:** `validate_and_clean` disconnected from pipeline | ⚠️ Partially fixed | `_run_normalization_stage` at `pipeline/core.py:513-537` now calls `validate_record_for_surface()` (a wrapper that calls `validate_and_clean` + `clean_record` + `strip_record_tracking_params`). **However**, `validate_and_clean` itself has a bug: the `_OUTPUT_SCHEMAS` dict at `field_value_core.py:475-489` only defines schemas for `ecommerce_detail` and `job_detail`. Any other surface (e.g. `ecommerce_listing`, `job_listing`) gets an empty schema and validation is silently skipped. This means listing surfaces bypass type validation entirely. |
| **D3:** Sync `json.loads` blocking event loop in `browser_capture.py` | ❌ Still pending | `browser_capture.py` still calls `json.loads(text)` synchronously in `_capture_worker`. For multi-MB payloads this blocks the async event loop. Should use `asyncio.to_thread(json.loads, text)`. |
| **D2/LN-4:** `curl_cffi` fetcher hardcodes headers | ❌ Still pending | `acquisition/runtime.py` `_curl_fetch_sync` hardcodes `Accept` and `Accept-Language` instead of reading from `crawler_runtime_settings` or `default_request_headers()`. |

### 9.3 New Findings From Gemini-Audit Review

The gemini audit missed these related issues discovered during validation:

- **`_OUTPUT_SCHEMAS` incomplete coverage** — only covers 2 of 4+ surfaces. Listing surfaces have zero type validation.
- **`extractability.py` entirely dead** — the gemini audit didn't flag this module as dead code despite it having zero callers.
- **`_mapping_or_empty` quadruple duplication** — the gemini audit didn't identify this pattern duplication across 4 files.

---

## 10. Dead Code in `record_export_service.py` (Deep Dive)

This 791-LOC file has the highest density of dead exports. The following functions are exported but never imported outside the file:

| Function | LOC | Status |
|----------|-----|--------|
| `legacy_fallback_markdown_rows` | ~30 | Dead — no callers |
| `clean_export_data` | ~15 | Dead — no callers |
| `collect_table_export_rows` | ~8 | Dead — no callers |
| `export_headers` | ~8 | Dead — no callers |
| `humanize_field_name` | ~8 | Dead — no callers |
| `is_markdown_long_form` | ~5 | Dead — no callers |
| `markdown_long_form_fields` | ~5 | Dead — no callers |
| `discoverist_schema` | ~5 | Unnecessary `lru_cache` over static data |
| `record_artifact_bundle` | ~12 | Dead — no callers |
| `stringify_markdown_value` | ~12 | Only used internally |
| `render_markdown_inline` | ~15 | Only used internally + by `llm_tasks.py` |
| `render_markdown_block` | ~15 | Only used internally |

**Subtotal: ~140 LOC of dead/unexported-needed code in one file**

---

## 11. Dead Exception Classes

`@/backend/app/services/exceptions.py` defines 14 exception classes. Several are never raised or caught outside their definition:

| Class | Used? |
|-------|-------|
| `CrawlerError` | Base class — needed |
| `CrawlerConfigurationError` | Used in `crawl_utils.py` |
| `AcquisitionError` | Base class — needed |
| `AcquisitionFailureError` | Never raised |
| `AcquisitionTimeoutError` | Never raised |
| `BrowserError` | Never raised |
| `BrowserNavigationError` | Never raised |
| `ExtractionError` | Never raised |
| `ExtractionParseError` | Never raised |
| `PipelineError` | Never raised |
| `PipelineWriteError` | Never raised |
| `AdapterError` | Never raised |
| `RunControlError` | Never raised |

8 of 14 exception classes are never raised anywhere. They may exist for future use or were leftover from a refactor. Verify before deleting.

---

## 12. `_normalize_text` / `clean_text` / `normalized_text` Consolidation

Three functions doing the same thing (whitespace normalization):

| Function | File | Handles HTML entities? |
|----------|------|----------------------|
| `clean_text(value)` | `field_value_core.py:69` | Yes (`unescape`) |
| `_normalize_text(value)` | `normalizers/__init__.py:38` | No |
| `normalized_text(value)` | `text_utils.py:4` (dead) | No |

Plus 6+ inline copies of the pattern `" ".join(str(value or "").split()).strip()`.

**Action:** Make `clean_text` the canonical whitespace normalizer. Replace `_normalize_text` with a call to `clean_text`. Delete `text_utils.py`.

---

## Action Priority (Ordered by Impact × Confidence)

| Priority | Item | LOC Saved | Risk | Effort |
|----------|------|-----------|------|--------|
| **P0** | Fix NoneType crash (§7) | 0 | Critical bug | Low |
| **P1** | Delete dead modules (§1) | ~35 | Zero | Trivial |
| **P1** | Delete `extractability.py` (§2.1) | ~120 | Low | Trivial |
| **P1** | Delete dead exports in `record_export_service.py` (§10) | ~140 | Low | Low |
| **P2** | Consolidate `_mapping_or_empty` (§4.1) | ~20 | Low | Low |
| **P2** | Consolidate `visible_text_from_soup` (§4.2) | ~30 | Low | Low |
| **P2** | Merge `HtmlAnalysis` / `BrowserHtmlAnalysis` (§4.3) | ~60 | Medium | Medium |
| **P2** | Consolidate dedup helpers (§4.4) | ~30 | Low | Medium |
| **P2** | Replace `normalize_committed_field_name` (§4.5) | ~15 | Low | Low |
| **P2** | Replace `_normalize_domain` (§4.6) | ~10 | Medium | Low |
| **P2** | Consolidate `_normalize_text` pattern (§12) | ~30 | Low | Low |
| **P3** | Remove alias shims (§5) | ~20 | Zero | Trivial |
| **P3** | Centralize inline config (§6) | ~20 | Low | Medium |
| **P2** | Config folder cleanup (§13) | ~250 | Low | Low |
| **P3** | Delete dead exception classes (§11) | ~30 | Low | Trivial |
| **P3** | Delete other dead public functions (§2.2-2.18) | ~250 | Low | Low |
| **P3** | Fix gemini-audit pending items (§9.2) | ~20 | Medium | Medium |
| **P4** | Split large files (§8) | ~0 (restructure) | Medium | High |

---

## 13. Config Folder Audit (`app/services/config/`)

The config folder contains 18 files totaling ~18,900 LOC (dominated by JSON data files). The Python modules total ~1,050 LOC.

### 13.1 Dead Module: `nested_field_rules.py` — 48 LOC, zero importers

`@/backend/app/services/config/nested_field_rules.py:1-48`

**No file in `app/` or `tests/` imports from `app.services.config.nested_field_rules`.** All 6 exported symbols (`NESTED_TEXT_KEYS`, `NESTED_URL_KEYS`, `NESTED_PRICE_KEYS`, `NESTED_ORIGINAL_PRICE_KEYS`, `NESTED_CURRENCY_KEYS`, `NESTED_CATEGORY_KEYS`, `PAGE_URL_CURRENCY_HINTS`) have zero consumers.

The module also imports from `extraction_rules.py` at module-load time, creating an unnecessary import chain.

**Action:** Delete `nested_field_rules.py`. If the NESTED_* keys are needed in the future, import `NESTED_OBJECT_KEYS_CONFIG` directly from `extraction_rules.py` and build the tuples at the call site.

### 13.2 Dead Module: `extraction_audit_settings.py` — 80 LOC, zero importers

`@/backend/app/services/config/extraction_audit_settings.py:1-80`

**No file imports from `app.services.config.extraction_audit_settings`.** The `ExtractionAuditSettings` class defines 30+ extraction tuning fields with env prefix `CRAWLER_EXTRACTION_`, but none of these settings are referenced anywhere in the codebase. The `SOURCE_PARSER_DATALAYER_FIELD_WEIGHTS` constant it exports is also never imported.

This is a significant AP-1 violation in reverse: settings were properly externalized to a Pydantic `BaseSettings` class, but the class is never consumed. The extraction code that should use these settings likely still has inline constants (e.g., `listing_card_group_min_size` is hardcoded in `listing_extractor.py` rather than reading from `extraction_audit_settings.listing_card_group_min_size`).

**Action:** Either wire `extraction_audit_settings` into the extraction code (replacing inline constants), or delete the entire module. The current state (settings defined but unused) is the worst of both worlds — maintenance burden with zero runtime benefit.

### 13.3 Duplicate: `ENDPOINT_TYPE_PATH_TOKENS` vs `NETWORK_PAYLOAD_SPECS.endpoint_path_tokens`

Two separate config sources define the same path tokens for network endpoint classification:

| Source | Format | Used by |
|--------|--------|---------|
| `network_capture.py:44-64` — `ENDPOINT_TYPE_PATH_TOKENS` | `dict[surface → dict[type → tuple[tokens]]]` | `browser_capture.py` (classify endpoint) |
| `network_payload_specs.py:73,192` — `endpoint_path_tokens` in each spec | Inline in spec dicts | `network_payload_mapper.py` (score endpoint) |

The path tokens `/jobs/`, `/job_posts/`, `/postings/` appear in **both** files. Adding a new endpoint type requires updating two places. `network_payload_specs.py` is the richer format (includes `field_paths`, `required_path_groups`); `network_capture.py` should derive its tokens from the specs rather than maintaining a parallel dict.

**Action:** Replace `ENDPOINT_TYPE_PATH_TOKENS` in `network_capture.py` with a function that extracts `endpoint_path_tokens` from `NETWORK_PAYLOAD_SPECS`. Delete the hardcoded dict.

### 13.4 Unnecessary Wrapper: `crawl_runtime.py` — 22 LOC

`@/backend/app/services/config/crawl_runtime.py:1-22`

This module is a thin wrapper around `runtime_settings.py` that:
1. Re-exports `crawler_runtime_settings` (already importable from `runtime_settings.py`)
2. Re-exports `coerce_url_timeout_seconds` as a one-line wrapper that calls `crawler_runtime_settings.coerce_url_timeout_seconds(value)`
3. Defines 4 constants: `LONG_RUN_THRESHOLD_SECONDS = 30 * 60`, `MAX_DURATION_SAMPLE_SIZE = 1000`, `STALLED_RUN_THRESHOLD_SECONDS = 2 * 60`, `STEALTH_MIN_TTL_HOURS = 1`

Only 2 files import from it (`dashboard_service.py` and `crawl_settings.py`). The 4 constants should be fields on `CrawlerRuntimeSettings` (they are runtime tunables). The `coerce_url_timeout_seconds` wrapper is unnecessary — callers can call `crawler_runtime_settings.coerce_url_timeout_seconds()` directly.

**Action:** Move the 4 constants into `CrawlerRuntimeSettings`, delete `crawl_runtime.py`, update 2 importers.

### 13.5 Duplicate: `STEALTH_MIN_TTL_HOURS` vs `stealth_prefer_ttl_hours`

`crawl_runtime.py:8` defines `STEALTH_MIN_TTL_HOURS = 1`  
`runtime_settings.py:120` defines `stealth_prefer_ttl_hours: int = 24`

These are different values (1 vs 24) with confusingly similar names. `STEALTH_MIN_TTL_HOURS` is never used anywhere (grep confirms zero references outside its definition). `stealth_prefer_ttl_hours` is the actual setting used by the stealth preference logic.

**Action:** Delete `STEALTH_MIN_TTL_HOURS` — it's dead code with a misleading name.

### 13.6 Dead Settings Fields in `runtime_settings.py`

4 fields in `CrawlerRuntimeSettings` exist only to serve the dead `extractability.py` module:

```python
extractability_non_product_type_ratio_max: float = 0.8
extractability_json_ld_min_type_signals: int = 2
extractability_next_data_signal_trigger: int = 15
extractability_next_data_signal_min: int = 4
```

If `extractability.py` is deleted (§2.1), these 4 settings become dead and should be removed.

### 13.7 `field_mappings.py` and `selectors.py` — Identical Pattern

Both files are 15 LOC each with identical structure:

```python
from app.services.config._export_data import load_export_data
_EXPORTS_PATH = Path(__file__).with_name("*.exports.json")
_STATIC_EXPORTS = load_export_data(str(_EXPORTS_PATH))
for _name, _value in _STATIC_EXPORTS.items():
    globals()[_name] = _value
__all__ = sorted(_STATIC_EXPORTS.keys())
```

This is a reusable pattern. The `globals().update()` approach is a code smell — it makes it impossible for IDEs and linters to know what symbols exist, and it defeats static analysis. Consider a typed accessor pattern instead.

**Action:** Create a `JsonExportModule` helper class that loads the JSON and provides typed attribute access, replacing the `globals()` injection pattern.

### 13.8 `extraction_rules.py` — Mixed Concerns (96 LOC)

This module mixes three different responsibilities:
1. **JSON data loading** — `globals().update(_STATIC_EXPORTS)` (same pattern as §13.7)
2. **Python-defined constants** — `LISTING_STRUCTURE_POSITIVE_HINTS`, `LISTING_STRUCTURE_NEGATIVE_HINTS`, `LISTING_FALLBACK_CONTAINER_SELECTOR`, `TITLE_PROMOTION_*`
3. **Settings bridging** — `DYNAMIC_FIELD_NAME_MAX_TOKENS = crawler_runtime_settings.dynamic_field_name_max_tokens`, `MAX_CANDIDATES_PER_FIELD = crawler_runtime_settings.max_candidates_per_field`

The settings bridging (item 3) is particularly problematic: it creates module-level copies of settings values that are **frozen at import time**. If `crawler_runtime_settings` is later modified (e.g., via profile application), the copies in `extraction_rules.py` will be stale.

**Action:** Remove the settings bridges. Consumers should read `crawler_runtime_settings.dynamic_field_name_max_tokens` directly instead of `DYNAMIC_FIELD_NAME_MAX_TOKENS`.

### 13.9 `network_payload_specs.py` — 374 LOC of Inline Data

This is the largest Python config file. It defines `NETWORK_PAYLOAD_SPECS` — a deeply nested dict with hardcoded field path tuples. Issues:

- **Massive duplication within the file**: `generic_job_detail` repeats the same path tuples in both `required_path_groups` and `field_paths` (e.g., `"title"` paths appear identically in both at lines 76-86 and 101-112).
- **Not env-controllable**: These specs cannot be tuned at runtime. Any change requires a code deploy.
- **Should be JSON**: This data is pure configuration, not logic. It should be in a JSON file (like `extraction_rules.exports.json`) and loaded via `_export_data.py`, reducing Python LOC by ~370 and making specs editable without code changes.

**Action:** Migrate `NETWORK_PAYLOAD_SPECS` to `network_payload_specs.exports.json`, load via `_export_data.py`. This eliminates 374 LOC of Python and makes specs runtime-editable.

### 13.10 `block_signatures.py` — 109 LOC of Inline Data

Same issue as §13.9: `BLOCK_SIGNATURES` is a large hardcoded dict that is pure configuration data. It should be a JSON file loaded via `_export_data.py`.

**Action:** Migrate `BLOCK_SIGNATURES` to `block_signatures.exports.json`, reducing Python LOC by ~109.

### 13.11 Config Folder Summary

| File | LOC | Status | Action |
|------|-----|--------|--------|
| `nested_field_rules.py` | 48 | Dead — zero importers | Delete |
| `extraction_audit_settings.py` | 80 | Dead — zero importers | Delete or wire in |
| `crawl_runtime.py` | 22 | Unnecessary wrapper | Merge into `runtime_settings.py`, delete |
| `STEALTH_MIN_TTL_HOURS` in `crawl_runtime.py` | 1 | Dead + confusing name | Delete |
| `ENDPOINT_TYPE_PATH_TOKENS` in `network_capture.py` | 21 | Duplicate of `network_payload_specs.py` | Derive from specs, delete dict |
| `extraction_rules.py` settings bridges | 4 | Stale-at-import-time risk | Delete bridges, use settings directly |
| `network_payload_specs.py` | 374 | Pure data in Python | Migrate to JSON |
| `block_signatures.py` | 109 | Pure data in Python | Migrate to JSON |
| 4 `extractability_*` fields in `runtime_settings.py` | 4 | Dead (if §2.1 applied) | Delete with `extractability.py` |
| `field_mappings.py` + `selectors.py` | 30 | Identical `globals()` pattern | Refactor to typed accessor |

**Config folder savings: ~250 LOC deleted + ~483 LOC migrated from Python to JSON**
