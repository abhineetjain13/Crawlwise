# CrawlerAI Forensic Architecture Audit V7

## Preflight
- Read: AGENTS.md, CODEBASE_MAP.md, BUSINESS_LOGIC.md, ENGINEERING_STRATEGY.md, INVARIANTS.md
- Active plan: NONE
- Scope: FIRST RUN — all surfaces

## Delta
| ID | Status |
|----|--------|
| — | FIRST RUN |

---

## D1: SOLID/DRY/KISS — Score: 4.5/10
- **CRITICAL** 18+ files import `_`-prefixed private symbols cross-module (detail_dom_extractor, persistence, selector_self_heal, review, domain_memory_service, etc). AP-7, INVARIANTS §6.
- **HIGH** `detail_extractor.py:937` `build_detail_record()` ~155 lines. AP-2.
- **HIGH** `js_state_mapper.py:101` returns on first root_path match. INVARIANTS Bug 2.

## D2: Configuration Hygiene — Score: 5.5/10
- **HIGH** `platform_policy.py:18` hardcodes adapter order. AP-4.
- **HIGH** `pipeline/direct_record_fallback.py` magic number `3.0`. INVARIANTS §1.

## D3: Scalability — Score: 5.5/10
- **HIGH** `acquisition/runtime.py:489` sync `curl_requests.get()` inside async. AP-10.
- **HIGH** `browser_runtime.py:1601` `origin_warmup` swallows all exceptions. Masks resource exhaustion.

## D4: Extraction Pipeline — Score: 4.5/10
- **CRITICAL** `detail_extractor.py:995` early-exit after js_state skips DOM tier. Missing variants when JS state confident but incomplete.
- **CRITICAL** `browser_page_flow.py:1135` `_generate_page_markdown` crashes on `node.attrs=None` after decompose.
- **HIGH** `pipeline/core.py:358` `capture_page_markdown` gated on `llm_enabled()`, coupling acquisition to LLM.

## D5: Traversal — Score: 6.5/10
- **MEDIUM** `max_scrolls=1` hardcoded in `fetch_page` signature. No per-run tunability.

## D6: Resilience — Score: 5.0/10
- **HIGH** 141 `except Exception` across 29 files. `crawl_service.py:193`, `browser_page_flow.py:649` flatten exception taxonomy.

## D7: Dead Code — Score: 6.0/10
- **MEDIUM** Cross-module private imports create brittle coupling. No unused-function dead code detected in hot paths.

## D8: Acquisition — Score: 5.0/10
- **HIGH** Sync `curl_requests.get` in async acquisition path. AP-10.
- **MEDIUM** `browser_page_flow.py:649` broad exception around `wait_for_load_state` misclassifies page crashes as timeouts.

---

## Final Summary

**Overall Score: 5.3/10**

### Root Cause Findings
- **RC-1** Systemic private-symbol leakage (18+ files) breaks ownership boundaries and makes refactoring unsafe.
- **RC-2** `build_detail_record` monolith and js_state first-match cause deterministic extraction gaps.
- **RC-3** Sync curl call inside async path blocks event loop and limits concurrency.

### Leaf Node Findings
- **LN-1** `browser_page_flow.py:1135` NoneType crash in `_generate_page_markdown` after decompose.
- **LN-2** `pipeline/core.py:358` markdown capture coupled to LLM setting.
- **LN-3** `platform_policy.py:18` hardcoded adapter order prevents config-driven priority.

### Genuine Strengths
- Extraction tier hierarchy (adapter → structured → JS state → DOM → LLM) is architecturally sound.
- `browser_page_flow.py` readiness probe system with optimistic + networkidle waits is well-structured.
- LLM fallback is correctly gated and degraded (INVARIANTS §10 respected in pipeline).

---

## Codex-Ready Work Orders

### WO-RC-1: Privatize Cross-Module Imports
```
File: backend/app/services/extract/detail_dom_extractor.py
Action: Replace `_object_dict`, `_object_list` imports with public exports from field_value_core.
Verify: grep "_object_dict\|_object_list" backend/app/services/extract/
```

### WO-RC-2: Fix JS State First-Match
```
File: backend/app/services/js_state_mapper.py
Action: Change `_map_configured_state_payload` to collect from all root_paths, not return on first match.
Verify: grep "return mapped" backend/app/services/js_state_mapper.py
```

### WO-RC-3: Async curl_fetch
```
File: backend/app/services/acquisition/runtime.py
Action: Replace sync `curl_requests.get` with async curl_cffi wrapper or thread-pool executor.
Verify: grep "curl_requests.get" backend/app/services/acquisition/runtime.py
```

### WO-LN-1: Harden _generate_page_markdown
```
File: backend/app/services/acquisition/browser_page_flow.py
Action: Ensure all post-decompose nodes have `attrs={}` before attribute access.
Verify: grep "node.decompose" backend/app/services/acquisition/browser_page_flow.py
```

---

## Architectural Recommendations
1. **Public API contract for shared helpers**: Promote `_object_list`, `_object_dict`, `_safe_int`, `_coerce_int` to public symbols in `field_value_core` or create `utils/shared_types.py`.
2. **Async I/O boundary**: Isolate sync network calls behind `asyncio.to_thread()` or replace with async-native client.
3. **Exception taxonomy**: Replace broad `except Exception` in acquisition/browser with typed handlers (TimeoutError, PlaywrightError, OSError).
4. **Config-driven adapter ordering**: Move `_DEFAULT_ADAPTER_ORDER` from `platform_policy.py` into `config/platforms.json` or runtime settings.
5. **Detail extraction decomposition**: Split `build_detail_record` into `_run_detail_tier()` dispatcher + per-tier functions.
