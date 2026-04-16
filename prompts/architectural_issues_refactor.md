# Web Content Acquisition Pipeline: PENDING Complex Refactoring Items

> **Status:** This document tracks architectural issues requiring **significant design work** — not quick fixes. Items marked ✅ have been resolved with simple changes.
>
> Last updated: 2026-04-16

---

## ✅ Fixed via Simple Changes

| Issue | Fix Applied | Files Changed |
|-------|-------------|---------------|
| **Monkey-patched `_acquirer_analysis`** | Added `acquirer_analysis: dict[str, object] | None` field to `HttpFetchResult` dataclass | `http_client.py:67`, `acquirer.py` (5 sites) |
| **Duplicated DOM selectors** | `EXTRACTION_RULES["dom_patterns"]` now references `DOM_PATTERNS` from `selectors.py` | `extraction_rules.py:10,62` |

---

## PENDING: Major Architectural Refactors

The following require **structural changes** to the pipeline architecture.

---

## Issue #1: Critical DRY Violation — DOM Parsing Duplication (15+ Times)

**Severity: HIGH** | **Complexity: HIGH** | **Requires: Pipeline architecture change**

BeautifulSoup is instantiated **15+ times** across the codebase. Each pipeline stage re-parses the same HTML from raw string instead of passing a shared DOM object.

| Location | File | Purpose |
|----------|------|---------|
| Parse #1 | `acquirer.py:1552` | Acquisition analysis (visible text, listing signal detection) |
| Parse #2 | `acquirer.py:1313` | Promoted source shell detection |
| Parse #3 | `source_parsers.py:110` | Source extraction (JSON-LD, Next.js data) |
| Parse #4 | `service.py:273` | Candidate extraction (DOM selector matching) |
| Parse #5 | `listing_extractor.py:173` | Listing card extraction |
| Parse #6 | `semantic_support.py:91` | Semantic section/specification extraction |

**Why complex:** Requires redesigning the `PipelineContext` to carry a shared `BeautifulSoup` instance from acquisition through extraction stages. All 6+ locations need to accept `soup: BeautifulSoup | None` parameter and only parse if None. Type signatures across 15+ functions must change.

**Blockers:**
- `PipelineContext` currently stores only `acquisition_result: AcquisitionResult` (which has `html: str`)
- Extraction layer has no access to acquisition's parsed soup
- `AcquisitionResult` would need to optionally carry `soup: BeautifulSoup | None` (not serializable to JSON for DB storage)

---

## Issue #2: Dead Strategy Pattern — `strategies.py` Never Called in Production

**Severity: HIGH** | **Complexity: MEDIUM** | **Requires: Production path rewiring**

`@/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/strategies.py:1-19` documents itself as **BUG-03**:

> "`AcquisitionChain` and all strategy classes defined here are never invoked by the live `acquire()` orchestrator. The production path calls `_acquire_once()` which directly dispatches to `_try_http()` / `_try_browser()` in `acquirer.py`. Any fix applied here has **no effect** on live behaviour."

**Why complex:** Requires replacing the entire production acquisition path (`acquire()` → `_acquire_once()` → `_try_http()` / `_try_browser()`) with the strategy chain. The decomposition exists but was never wired in. Risk of breaking the waterfall logic during the cutover.

---

## Issue #3: Pipeline `BlockedDetectionStage` Duplicates Acquirer Retry Logic

**Severity: HIGH** | **Complexity: MEDIUM** | **Requires: Architectural decision on responsibility boundary**

`@/c:/Projects/pre_poc_ai_crawler/backend/app/services/pipeline/stages.py:255-295` implements its own browser retry when blocked:

```python
if blocked.is_blocked and ctx.is_listing and acq.method != "playwright":
    browser_acq = await pipeline_core.acquire(
        request=ctx.acquisition_request.with_profile_updates(prefer_browser=True),
    )
```

This duplicates the acquirer's browser-first logic (`acquirer.py:620-627`) where `browser_first` is computed from `BROWSER_FIRST_DOMAINS` + `_memory_prefers_browser()` + `_requires_browser_first()`.

**Why complex:** A URL can trigger **two full acquisition cycles** — once through the normal waterfall, then again through the pipeline's blocked-detection retry. The fix requires deciding whether:
- Option A: Remove the pipeline stage entirely (acquirer handles blocked detection internally — it already has the detector)
- Option B: Make the acquirer expose blocked-detection results so the pipeline can decide without re-acquiring
- Option C: Move all blocked-handling to the pipeline (acquirer becomes "dumb" fetcher)

Each option changes the layer boundaries significantly.

---

## Issue #4: Global Mutable State Across 4+ Modules

**Severity: MEDIUM** | **Complexity: HIGH** | **Requires: Dependency injection framework**

Multiple modules use **module-level mutable globals** that resist testing and create cross-request state leakage:

| Global | Location | Risk |
|--------|----------|------|
| `_PROXY_FAILURE_STATE: dict` | `acquirer.py:154` | Proxy cooldown state persists across tests; no reset API |
| `_BROWSER_POOL_STATE` | `browser_pool.py:114` | Singleton with PID check; `global` reassignment in `prepare_browser_pool_for_worker_process()` |
| `_global_url_semaphore` | `_batch_runtime.py:59` | Lazy-init global with `settings` dependency; no cleanup |
| `_pool`, `_client` (Redis) | `redis.py:44-58` | Global singletons with `global` mutation in `close_redis()` |

**Why complex:** No dependency injection container exists. All code accesses these via direct module-level reads. Introducing a `RuntimeState` container that's injected into `acquire()` and the pipeline requires changing **dozens** of function signatures or introducing a contextvar/registry pattern.

---

## Issue #5: `SITE_POLICY_REGISTRY` Empty at Import → Stale `BROWSER_FIRST_DOMAINS`

**Severity: HIGH** | **Complexity: LOW-MEDIUM** | **Requires: Lazy evaluation pattern**

`@/c:/Projects/pre_poc_ai_crawler/backend/app/services/config/extraction_rules.py:33`:
```python
SITE_POLICY_REGISTRY = {}
```

`BROWSER_FIRST_DOMAINS` at `@/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/acquirer.py:193-197` is derived from it **at module import time**:

```python
BROWSER_FIRST_DOMAINS = sorted(
    domain
    for domain, policy in SITE_POLICY_REGISTRY.items()
    if isinstance(policy, dict) and bool(policy.get("browser_first"))
)
```

If `SITE_POLICY_REGISTRY` is populated later (e.g., by `EXTRACTION_RULES` processing), `BROWSER_FIRST_DOMAINS` will be **stale** — computed from the empty dict.

**Why complex:** The fix (convert to lazy function) is simple, but **risk is high** — `BROWSER_FIRST_DOMAINS` is used in `acquire()` at `acquirer.py:624` for domain-based fast-track decisions. If the lazy function has any performance overhead or caching bug, it affects every acquisition request.

---

## Issue #6: 2794-Line God File with 14-Parameter Functions

**Severity: HIGH** | **Complexity: HIGH** | **Requires: Module decomposition + coord with strategies.py**

`@/c:/Projects/pre_poc_ai_crawler/backend/app/services/acquisition/acquirer.py` (2794 lines) contains:

| Function | Parameters |
|----------|------------|
| `acquire()` | 14 positional/keyword |
| `acquire_html()` | 14 (identical signature) |
| `_try_http()` | 13 |
| `_try_browser()` | 14 |
| `_try_promoted_source_acquire()` | 11 |

Also contains: proxy rotation logic, proxy failure state management, session context handling, surface validation, commerce/job diagnostics, HTML scrubbing, artifact path resolution, platform detection, browser escalation decisions, extractability assessment, and outcome classification.

**Why complex:** The `strategies.py` decomposition attempt (Issue #2) was supposed to replace this but was never wired in. Extracting into focused modules (`proxy_rotator.py`, `browser_escalation.py`, `surface_validator.py`, etc.) requires:
1. Coordinating with the strategy pattern fix (use strategies or extract modules — pick one)
2. Maintaining the exact waterfall behavior during the move
3. The file has **DEBT-01** and **DEBT-06** comments indicating half-finished decompositions

---

## Issue #7: Hardcoded Configuration — Platform Adapter Registry

**Severity: HIGH** | **Impact: Violates Open/Closed Principle**

Platform resolution relies on hardcoded lists:

```python
# registry.py:24
_ADAPTERS: list[BaseAdapter] = [
    AmazonAdapter(),
    WalmartAdapter(),
    EbayAdapter(),
    ShopifyAdapter(),
    # ... 11 more hardcoded instances
]

# platforms.json - Hardcoded domain patterns
{
  "family": "icims",
  "domain_patterns": ["icims.com"],
  "url_contains": ["/jobs/search"]
}

# acquirer.py:193 - Derived hardcoded list at import
BROWSER_FIRST_DOMAINS = sorted(...)
```

**Why complex:** Requires designing a plugin discovery mechanism (entry points, config directory scanning, or dynamic import). The adapter registry and platform registry are two separate systems that need to merge or become consistent.

---

## Issue #8: Config Leakage — Scattered Configuration System

**Severity: MEDIUM-HIGH** | **Impact: Maintenance burden**

Extraction rules fragmented across 5+ files:

| File | Lines | Responsibility |
|------|-------|----------------|
| `selectors.py` | ~50 | DOM_PATTERNS (CSS selectors) |
| `extraction_rules.py` | **2181** | SITE_POLICY_REGISTRY, EXTRACTION_RULES |
| `extraction_rules.py:774` | nested | "listing_extraction" config |
| `platform_registry.py` | ~200 | Platform domain matching |
| `acquirer.py` | - | Imports SITE_POLICY_REGISTRY directly |

**Why complex:** Requires designing a centralized configuration schema with validation. The acquisition layer's direct import of extraction config violates separation of concerns — untangling this requires understanding all cross-layer dependencies.

---

## Issue #9: Resource Inefficiency — Inconsistent Async Strategy + No DOM Pooling

**Severity: MEDIUM** | **Impact: Event loop starvation**

**Correctly offloaded:**
- `acquirer.py:1636` — `asyncio.to_thread()` for `_analyze_html_sync()`
- `acquirer.py:1665` — `asyncio.to_thread()` for `_assess_extractable_html()`

**Synchronously blocking:**
- `service.py:273` — `BeautifulSoup(html, "html.parser")` in `extract_candidates()`

**Missing:**
- No DOM object pooling (unlike browser pool)
- No parsed HTML cache between pipeline stages

**Why complex:** Fixing the inconsistency requires first solving Issue #1 (passing soup between stages). Implementing DOM pooling requires designing a lifecycle management system (when to evict from pool? lxml or html.parser? thread-safety?).

---

## Recommended Fix Order

Dependencies between issues:

```
Issue #1 (DOM passing) ──┬──► Issue #9 (async consistency)
                         │
Issue #6 (god file) ─────┼──► Issue #2 (strategies wiring)
                         │    (pick one: strategies OR extraction)
                         │
Issue #4 (global state) ──┴──► Issue #3 (pipeline/acquirer boundary)
                              (needs state container first)
```

**Phase 1: Foundation (4 weeks)**
1. Issue #5 — Convert `BROWSER_FIRST_DOMAINS` to lazy function (low risk, unblocks testing)
2. Issue #4 — Introduce `AcquisitionContext` container, migrate globals incrementally
3. Issue #6 — Extract modules from `acquirer.py` (coordinate with strategies decision)

**Phase 2: Architecture (6 weeks)**
4. Issue #2 — Wire strategies OR commit to module extraction
5. Issue #1 — Implement "parse once, pass soup" across pipeline
6. Issue #3 — Resolve pipeline/acquirer blocked-handling boundary

**Phase 3: Polish (3 weeks)**
7. Issue #7 — Plugin-based platform registry
8. Issue #8 — Centralized config with schema validation
9. Issue #9 — DOM pooling (after Issue #1 is stable)

---

## Success Metrics (Unchanged)

- [ ] BeautifulSoup instantiations reduced from 15+ to 1 per document
- [ ] New platform addition requires **zero** code changes (config-only)
- [ ] All HTML parsing offloaded to threads (zero blocking event loop)
- [ ] Config consolidated to ≤3 files with clear responsibilities
- [ ] Memory profiling shows reduced peak usage in extraction pipeline
- [ ] 90%+ test coverage with isolated, deterministic unit tests (no globals)
