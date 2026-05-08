# Crawlwise — Revised Architecture Review & Focused Refactoring Plan

## Corrected File Size Table (Byte-Verified)

The original review underreported module sizes. Actual byte counts from the GitHub API reveal the acquisition and extract layers are significantly larger than first assessed.

| File | Bytes | Lines (approx) | Severity |
|---|---|---|---|
| `acquisition/browser_page_flow.py` | 79,412 | ~2,600 | 🔴 |
| `acquisition/browser_runtime.py` | 73,714 | ~2,400 | 🔴 |
| `acquisition/traversal.py` | 69,648 | ~2,200 | 🔴 |
| `acquisition/browser_identity.py` | 60,036 | ~1,900 | 🔴 |
| `extract/shared_variant_logic.py` | 59,217 | ~1,900 | 🔴 |
| `pipeline/extraction_loop.py` | 49,600 | ~1,413 | 🔴 |
| `extract/detail_dom_extractor.py` | 52,003 | ~1,650 | 🔴 |
| `extract/detail_materializer.py` | 51,989 | ~1,650 | 🔴 |
| `extract/variant_record_normalization.py` | 49,333 | ~1,550 | 🟡 |
| `extract/detail_record_finalizer.py` | 41,562 | ~1,300 | 🟡 |
| `services/listing_extractor.py` | 42,537 | ~1,350 | 🟡 |
| `services/llm_tasks.py` | 36,231 | ~1,150 | 🟡 |
| `services/extraction_runtime.py` | 33,842 | ~1,070 | 🟡 |
| `services/field_value_candidates.py` | 35,260 | ~1,100 | 🟡 |
| `acquisition/browser_detail.py` | 34,197 | ~1,050 | 🟡 |
| `extract/detail_price_extractor.py` | 33,788 | ~1,050 | 🟡 |

***

## Dead Code — Confirmed

### `pipeline/core.py` — Confirmed Dead Module

This file is 311 bytes and contains only a `sys.modules` monkey-patch that redirects the module name to `extraction_loop`:

```python
# pipeline/core.py — CONFIRMED DEAD
from app.services.pipeline import extraction_loop as _extraction_loop
_sys.modules[__name__] = _extraction_loop
```

This is a leftover migration shim from a previous rename. It has no callers that cannot already import `extraction_loop` directly. **Safe to delete** after a one-time grep for `from app.services.pipeline.core import` and `from app.services.pipeline import core`.

***

## Duplicate Code — Confirmed

### 1. `_string_list()` — Defined in 3 Separate Files

Confirmed at:
- `models/crawl.py` line 68 — `def _string_list(value: object) -> list[str]:`
- `services/pipeline/direct_record_fallback.py` — defined (same signature)
- `services/acquisition/browser_detail.py` — defined (same signature)

This is a trivial utility that deserialises a JSON list. It should live once in a `app/core/coerce.py` or `app/services/utils/coerce.py` module and be imported everywhere.

### 2. `listing_extractor.py` and `extract/listing_card_fragments.py` — Partial Duplication

`listing_extractor.py` (42 KB) internally defines `_listing_card_html_fragments`, `_node_html`, `_node_signature`, `_node_tag`, `_node_listing_links`, and `_meaningful_anchor_texts`. These functions are structurally identical in purpose to the functions in `extract/listing_card_fragments.py` (`collect_listing_fragment_html`, `select_listing_fragment_nodes`, `listing_node_text`, `listing_node_attr`). The `listing_extractor.py` file does import from `listing_card_fragments` — but maintains its own parallel private implementation of the same operations. The private copies in `listing_extractor.py` are unreferenced from outside and should be deleted in favour of the canonical versions in `listing_card_fragments.py`.

### 3. `extract/detail_materializer.py` and `extract/detail_record_finalizer.py` — Overlapping Sanitization

`detail_materializer.py` (51,989 bytes) defines `_looks_like_site_shell_record`, `_detail_description_value_looks_thin`, `_detail_long_text_value_looks_truncated`, and `_finalize_early_detail_record`. `detail_record_finalizer.py` (41,562 bytes) defines `_sanitize_ecommerce_detail_record`, `_sanitize_detail_placeholder_scalars`, `repair_ecommerce_detail_record_quality`, and `detail_title_looks_like_placeholder`. These two files both perform record quality assessment and sanitization on the same `dict[str, Any]` data structure. There is no clear ownership boundary between "materializing" a record and "finalizing" it — they are two names for the same concern.

### 4. `extract/shared_variant_logic.py` and `extract/variant_record_normalization.py` — Confirmed Duplicate Scope

`variant_record_normalization.py` (49,333 bytes) defines `normalize_variant_record`, `_dedupe_and_prune_variant_rows`, `_clean_variant_rows`, `_enforce_variant_axis_contract`, and `_normalize_variant_axis_value`. `shared_variant_logic.py` (59,217 bytes) defines `normalized_variant_axis_key`, `normalized_variant_axis_display_name`, `variant_dom_cues_present`, `infer_variant_group_name`, and `_variant_axis_label_is_noise`. Both files operate on the same `variant` dict structures. The split between them is arbitrary — they are functionally one module that was split by author and then grew independently. Combined they exceed 108 KB.

### 5. `acquisition/runtime.py` and `acquisition/browser_runtime.py` — Two Separate Runtime Files

`acquisition/runtime.py` (27,306 bytes) defines `http_fetch`, `classify_blocked_page`, `should_escalate_to_browser`, `PageFetchResult`, and `BlockPageClassification` — i.e., the **HTTP acquisition runtime**. `acquisition/browser_runtime.py` (73,714 bytes) is the **browser acquisition runtime**. These are correctly separate concerns, but they share no common interface or base class, meaning callers must know which transport to use at call site rather than programming to a `Fetcher` abstraction. This is a confirmed DIP gap, not duplication per se.

### 6. `_batch_runtime.process_run` vs `crawl_service._batch_process_run` — Confirmed Split Orchestration

`tasks.py` calls `_batch_runtime.process_run`. `crawl_service.py` imports it as `_batch_process_run` and calls it at line 188 as a local fallback path (`legacy_inprocess_runner_enabled`). There are two separate code paths for running the same crawl job: the Celery async path and the legacy in-process path. They share `_batch_runtime.process_run` as the core, but the divergence adds maintenance burden and makes run lifecycle semantics harder to reason about.

### 7. `services/xpath_service.py` and `services/selectors_runtime.py` — Two Selector Engines

`xpath_service.py` (13,956 bytes) implements `extract_selector_value`, `validate_or_convert_xpath`, `build_absolute_xpath`, and CSS/XPath resolution. `selectors_runtime.py` (26,672 bytes) implements `suggest_selectors`, `test_selector`, `create_selector_record`, and `list_selector_records`. These are **correctly separated** — `xpath_service` is the evaluator, `selectors_runtime` is the CRUD/API service. No action needed. Listed here to correct the v1 audit which incorrectly flagged them as duplicates.

***

## Revised Severity and Priority Table

After the deeper audit, the priority order changes from v1:

| # | Finding | Type | Severity | Phase |
|---|---|---|---|---|
| 1 | Zero unit tests for service layer | Coverage gap | 🔴 Blocking | 1 |
| 2 | `browser_runtime.py` — 8 module-level mutable globals | Global Coupling | 🔴 Blocking | 1 |
| 3 | `models/crawl.py` imports `crawler_runtime_settings` | DIP violation | 🔴 Blocking | 1 |
| 4 | `pipeline/core.py` — dead monkey-patch shim | Dead code | 🔴 Blocking | 1 |
| 5 | `_string_list()` in 3 files | Duplication | 🟡 Important | 1 |
| 6 | `pipeline/extraction_loop.py` — 40-import God Orchestrator | SRP/DIP | 🔴 Blocking | 2 |
| 7 | `acquisition/browser_page_flow.py` 79 KB God Class | SRP | 🔴 Blocking | 2 |
| 8 | `acquisition/traversal.py` 69 KB God Class | SRP | 🔴 Blocking | 2 |
| 9 | `extract/detail_materializer.py` + `detail_record_finalizer.py` overlap | Duplication | 🟡 Important | 2 |
| 10 | `listing_extractor.py` private copies of `listing_card_fragments` fns | Duplication | 🟡 Important | 2 |
| 11 | `extraction_runtime.py` — 6× `if "listing" in surface` | OCP violation | 🟡 Important | 3 |
| 12 | `shared_variant_logic.py` + `variant_record_normalization.py` overlap | Duplication | 🟡 Important | 3 |
| 13 | `llm_tasks.py` — 6-responsibility SRP violation | SRP | 🟡 Important | 2 |
| 14 | `_batch_runtime` legacy runner fork | Control coupling | 🟡 Important | 3 |
| 15 | `BaseAdapter` mixes fetch + extract concerns | ISP | 💡 Suggestion | 3 |

***

## Revised Three-Phase Plan

***

### Phase 1 — Stabilize & Purge
**⏱ 2–3 weeks | Risk: Very Low | Goal: Zero-behaviour-change housekeeping + safety net**

This phase has no architectural changes — only deletion, deduplication, and test coverage. It is entirely safe and yields immediate measurable improvement.

#### 1.1 — Delete `pipeline/core.py` (Confirmed Dead)

```bash
# Verify no callers remain
grep -r "from app.services.pipeline.core import\|from app.services.pipeline import core" backend/
# If grep returns nothing → safe delete
git rm backend/app/services/pipeline/core.py
```

#### 1.2 — Deduplicate `_string_list()` into a shared utility

Create `backend/app/core/coerce.py`:
```python
def string_list(value: object) -> list[str]:
    """Deserialise a JSON list value to a list of stripped strings."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None]
    return []
```

Remove private definitions from `models/crawl.py` (line 68), `pipeline/direct_record_fallback.py`, and `acquisition/browser_detail.py`. Update all three call sites to import from `app.core.coerce`. This is a 3-file change with zero logic change.

#### 1.3 — Remove `crawler_runtime_settings` from `models/crawl.py`

`CrawlRun` imports and directly accesses `crawler_runtime_settings` — a domain entity depending on infrastructure config. Move the two usages to the service layer callers (`crawl_service.py`, `crawl_crud.py`), passing computed values as constructor parameters.

#### 1.4 — Establish Unit Test Coverage for Core Services

Create characterization tests (capturing current output as golden values) for:

```
backend/tests/unit/
  services/
    test_extraction_runtime.py     ← test each surface branch in isolation
    test_listing_extractor.py      ← test _structured_listing_record, DOM path
    test_field_value_candidates.py
    test_confidence.py
    test_llm_tasks.py              ← mock LLM; test budget enforcement + cache
    test_crawl_service.py          ← mock DB session; test state transitions
  extract/
    test_detail_materializer.py
    test_detail_record_finalizer.py
    test_shared_variant_logic.py
```

All I/O mocked via `unittest.mock.AsyncMock`. Target: regression net, not 100% coverage.

#### 1.5 — Encapsulate Global Browser State

Transform the 8 module-level mutable dicts in `browser_runtime.py` into a `BrowserPool` class:

```python
class BrowserPool:
    def __init__(self) -> None:
        self._direct: dict[str, SharedBrowserRuntime] = {}
        self._proxied: dict[tuple[str, str], SharedBrowserRuntime] = {}
        self._lock = asyncio.Lock()
        self._preferred_hosts: dict[str, float] = {}
        self._preferred_host_successes: dict[str, tuple[int, float]] = {}
        self._popup_guard_tasks: set[asyncio.Task] = set()
```

Instantiate once in the FastAPI `lifespan` context manager and inject via `Depends()`. This eliminates Global Coupling and makes the pool testable without process-level side effects.

**Phase 1 Exit Criteria:**
- `pipeline/core.py` deleted, no broken imports
- `_string_list` exists only in `app.core.coerce`
- `models/crawl.py` imports nothing from `app.services.config`
- `browser_runtime.py` has zero module-level mutable collections
- `pytest backend/tests/unit/` passes with all core service paths covered

***

### Phase 2 — Decompose the God Modules
**⏱ 4–5 weeks | Risk: Medium (mitigated by Phase 1 tests) | Goal: One responsibility per module**

Execute only after Phase 1 test suite is green. Work files from largest to smallest by byte count.

#### 2.1 — Split `acquisition/browser_page_flow.py` (79 KB → 5 modules)

```
acquisition/page_flow/
  navigation.py          ← page.goto, URL resolution, redirect handling
  popup_guard.py         ← dialog/overlay detection and dismissal
  scroll_loader.py       ← infinite scroll, lazy-load triggering
  form_controller.py     ← input filling, button clicking, submit actions
  readiness_checker.py   ← network-idle, stability heuristics
                           (partially extracted to browser_readiness.py already — consolidate here)
```

`browser_page_flow.py` retains only re-exports for backward compatibility during transition, then is deleted.

Note: `acquisition/browser_readiness.py` (9,707 bytes) already exists and likely covers the readiness concern. Confirm its scope and absorb `browser_page_flow` readiness logic into it rather than creating a new file.

#### 2.2 — Split `acquisition/traversal.py` (69 KB → 3 modules)

```
acquisition/traversal/
  url_queue.py       ← priority queue, deduplication, visited-set management
  depth_policy.py    ← max-depth enforcement, same-domain filtering, robots integration
  crawl_graph.py     ← link discovery, adjacency tracking, cycle detection
```

#### 2.3 — Decompose `pipeline/extraction_loop.py` (49 KB) into Pipeline Stages

The loop is a direct-call God Orchestrator with 40 imports. The target is a staged pipeline:

```
pipeline/
  url_processor.py      ← thin orchestrator: calls stages in order, handles errors
  fetch_stage.py        ← wraps acquisition call + blocked-page detection
  extract_stage.py      ← wraps extraction_runtime + record validation
  enrich_stage.py       ← LLM fallback + selector self-heal (calls direct_record_fallback)
  persist_stage.py      ← consolidates existing persistence.py + any inline writes
```

Stages communicate only via dataclass return values — no stage imports another stage. `extraction_retry_decision.py` (already separate, 11 KB) plugs into `url_processor.py` as-is.

#### 2.4 — Resolve `detail_materializer.py` + `detail_record_finalizer.py` Overlap

Both files perform record quality assessment and sanitization on the same `dict[str, Any]` structure. Consolidate into a clear two-step model:

```
extract/
  record_assembly.py    ← candidate collection + field source selection (from materializer)
  record_quality.py     ← sanitization + repair + placeholder detection (from finalizer)
```

`_materialize_record` (the core assembly function) stays in `record_assembly.py`. All `_sanitize_*`, `repair_*`, and `detail_title_looks_like_placeholder` move to `record_quality.py`.

#### 2.5 — Delete Duplicate DOM Implementations in `listing_extractor.py`

The following private functions in `listing_extractor.py` are confirmed duplicates of public functions already in `extract/listing_card_fragments.py`:

| Private function in `listing_extractor.py` | Canonical in `listing_card_fragments.py` |
|---|---|
| `_listing_card_html_fragments` | `collect_listing_fragment_html` |
| `_node_html` | `listing_node_text` (via node) |
| `_node_listing_links` | `_node_listing_links` |
| `_node_signature` | `_listing_node_signature` |

Delete the private copies from `listing_extractor.py` and update the 4–5 internal callers to use the canonical imports. Zero logic change.

#### 2.6 — Split `services/llm_tasks.py` (36 KB → 4 modules)

The existing `llm_cache.py`, `llm_circuit_breaker.py`, `llm_budget.py`, and `llm_provider_client.py` are already correctly scoped individual files. `llm_tasks.py` ignores those boundaries. The fix:

```
services/llm/
  prompt_builder.py   ← template construction, context assembly, field truncation
  response_parser.py  ← JSON parsing, schema validation, type coercion
  # budget, cache, circuit_breaker already exist — do not duplicate
  # llm_provider_client.py already exists — do not duplicate
```

`llm_tasks.py` becomes a thin orchestrator calling `prompt_builder` → `llm_provider_client` → `response_parser`, with `budget`, `cache`, and `circuit_breaker` as collaborators.

**Phase 2 Exit Criteria:**
- No file in `acquisition/` exceeds 25 KB
- No file in `pipeline/` exceeds 15 KB
- `listing_extractor.py` duplicate private functions deleted (confirmed by grep)
- `detail_materializer.py` and `detail_record_finalizer.py` consolidated
- All Phase 1 tests pass; new integration tests added for changed entry points

***

### Phase 3 — Harden: Abstractions, OCP, and Layer Enforcement
**⏱ 3–4 weeks | Risk: Low-Medium | Goal: Extensibility, correct dependency direction, no string dispatch**

#### 3.1 — Fix the Surface OCP Violation (Strategy Registry)

Replace the 6× `if "listing" in surface` in `extraction_runtime.py` with a registered strategy:

```python
# extract/contracts.py (already exists — extend it)
class SurfaceExtractor(Protocol):
    def extract(self, html: str, url: str, ctx: ExtractionContext) -> list[dict]: ...

# extract/surface_registry.py
_REGISTRY: dict[str, SurfaceExtractor] = {}

def register(prefix: str, extractor: SurfaceExtractor) -> None:
    _REGISTRY[prefix] = extractor

def get_extractor(surface: str) -> SurfaceExtractor:
    for prefix, ext in _REGISTRY.items():
        if prefix in surface:
            return ext
    raise ValueError(f"No extractor registered for surface: {surface!r}")
```

`extract/contracts.py` already exists at 1,542 bytes — this is the correct home. Adding a new surface requires only: write one class, call `register()`. No changes to `extraction_runtime.py`.

#### 3.2 — Introduce `FetcherPort` (DIP for acquisition layer)

`fetch_stage.py` (Phase 2) should not directly call `acquire()` or `http_fetch()`. Define:

```python
# pipeline/ports.py
class FetcherPort(Protocol):
    async def fetch(self, request: AcquisitionRequest) -> AcquisitionResult: ...
```

The concrete `acquire` function is injected at `url_processor.py` level. This makes `fetch_stage` fully unit-testable with a stub and decouples the pipeline from the specific transport layer.

#### 3.3 — Consolidate Variant Logic

Merge `extract/shared_variant_logic.py` (59 KB) and `extract/variant_record_normalization.py` (49 KB) into a clean `extract/variant/` sub-package:

```
extract/variant/
  axis.py           ← axis key normalization, label noise detection, display names
  dom_cues.py       ← variant_dom_cues_present, _variant_scope_roots, infer_variant_group_name
  normalization.py  ← normalize_variant_record, _clean_variant_rows, contract enforcement
  grouping.py       ← cluster logic, cross-product detection, deduplication
```

Both source files are deleted. Total combined size (108 KB) distributed across 4 focused modules.

#### 3.4 — Retire Legacy In-Process Runner

`crawl_service.py` line 188 calls `_batch_process_run` directly when `legacy_inprocess_runner_enabled` is true. This is Control Coupling — a flag dictating execution path. Assess whether `legacy_inprocess_runner_enabled` is still active in production config. If not used, delete the branch and simplify `crawl_service.py`. If still needed, extract it to a named `InProcessRunStrategy` so the fork is explicit.

#### 3.5 — Enforce Layer Boundaries in CI

Add `import-linter` to `pyproject.toml`:

```toml
[tool.importlinter]
root_package = "app"

[[tool.importlinter.contracts]]
name = "Models must not import services"
type = "forbidden"
source_modules = ["app.models"]
forbidden_modules = ["app.services"]

[[tool.importlinter.contracts]]
name = "API layer must not import config directly"
type = "forbidden"
source_modules = ["app.api"]
forbidden_modules = ["app.services.config"]
```

This catches future regressions like `models/crawl.py` → `crawler_runtime_settings` automatically in CI.

**Phase 3 Exit Criteria:**
- `extraction_runtime.py` has zero `if "listing" in surface` checks
- `shared_variant_logic.py` and `variant_record_normalization.py` deleted
- `import-linter` passes in CI with zero violations
- Legacy in-process runner branch removed or explicitly named
- Full test suite green

***

## Coupling & Cohesion State — Before vs After

| Module / Boundary | Current | Target |
|---|---|---|
| `extraction_loop.py` → all services | Content Coupling (40 direct imports) | Message Coupling (stage return values) |
| `browser_runtime.py` module globals | Global Coupling | Data Coupling via `BrowserPool` instance |
| `models/crawl.py` → `crawler_runtime_settings` | Content Coupling | Removed entirely |
| `listing_extractor.py` duplicate DOM fns | Copy-Paste | Canonical import from `listing_card_fragments` |
| `detail_materializer` + `detail_record_finalizer` | Communicational (same data, split arbitrarily) | Sequential (assemble → quality-check) |
| `shared_variant_logic` + `variant_record_normalization` | Logical Cohesion (named "shared") | Functional Cohesion (named by domain role) |

***

## Recommended Targets After All Phases

| Metric | Current Worst | Target |
|---|---|---|
| Max file size | 79,412 bytes (`browser_page_flow.py`) | ≤ 25 KB |
| Module-level mutable globals | 8 (`browser_runtime.py`) | 0 in service layer |
| `if "[surface]" in x` dispatch occurrences | 6 | 0 |
| Duplicate utility function definitions | 3 (`_string_list`) | 1 (in `core/coerce.py`) |
| Dead stub modules | 1 (`pipeline/core.py`) | 0 |
| Unit test files for core service layer | 0 | ≥ 10 |
| Files violating layer dependency rule | ≥ 3 | 0 |