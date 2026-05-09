Crawlwise — Phase-Wise Refactoring Plan
Repository: github.com/abhineetjain13/Crawlwise (found under abhineetjain13)
Stack: Python, FastAPI, SQLAlchemy (async), Celery, Playwright, PostgreSQL, Redis

Executive Summary
The codebase is a capable, feature-rich web-crawling and data-extraction platform. It shows evidence of active, iterative growth — new subdirectories (pipeline/, extract/, fetch/, shared/) signal that modularization has started but is only partially complete. The most critical structural problems are: a God Object model file, multiple 1,000–1,900 line service files, duplicate utility functions with in-code delete-target comments, a dispatch service that branches on config flags inline, and 10+ domain models crammed into a single file. These are verified facts from the source, not inferences.

Phase 0 — Confirmed Anti-Patterns (Pre-Refactor Audit)
Before touching code, these violations are confirmed and measured.

🔴 God Object: models/crawl.py (879 lines, 19 classes)
crawl.py contains 19 classes across completely unrelated domains :

Core crawl infrastructure: CrawlRun, CrawlRecord, CrawlLog

Product matching domain: ProductIntelligenceJob, ProductIntelligenceSourceProduct, ProductIntelligenceCandidate, ProductIntelligenceMatch

Data enrichment domain: DataEnrichmentJob, EnrichedProduct

Domain memory: DomainMemory, DomainRunProfile, DomainCookieMemory, DomainFieldFeedback, HostProtectionMemory

Review: ReviewPromotion

Run-state logic: BatchRunProgressState (a 140-line dataclass with record_url_result, build_progress_patch, build_final_patch — business logic inside a model file)

SOLID Verdict — SRP ❌ ISP ❌: One file has 19 reasons to change. The BatchRunProgressState dataclass computing progress percentages, merging acquisition summaries, and building JSON patches is business logic that has no place in the ORM layer.

🔴 Mega-Files Exceeding All Size Thresholds
These files are confirmed by line-count reads :

File	Lines	Problem
acquisition/browser_runtime.py	1,986	Browser pool + context lifecycle + diagnostics in one class cluster
acquisition/traversal.py	1,903	Link traversal, pagination discovery, DOM recovery, structured-script detection
extract/shared_variant_logic.py	1,562	"Shared" logic — coincidental cohesion, the classic Utils trap
extract/variant_record_normalization.py	1,472	All variant normalization in a single module
services/listing_extractor.py	1,156	HTML listing extraction mixed with candidate ranking
services/llm_tasks.py	1,095	LLM task dispatch, prompt formatting, result parsing together
services/field_value_candidates.py	1,072	All field candidate logic (1,072 lines = ~5× the recommended limit)
pipeline/extraction_loop.py	1,329	The core URL processing pipeline — does acquire, extract, retry, persist
js_state/state_normalizer.py	~1,300+ (49 KB)	JS state normalization in one file
services/fetch/fetch_context.py	1,254	Fetch orchestration — already has in-code # PHASE-3 DELETE TARGETS comment
🔴 Lava Flow: Dead Code with Delete-Target Comments
fetch_context.py has this confirmed at line 1 :

python
# PHASE-3 DELETE TARGETS:
# _safe_int -> replaced by shared.coerce_primitives.safe_int (DELETE this function in Phase 3)
# clean_text, slug_tokens -> replaced by shared.text_coerce (DELETE in Phase 3)
# absolute_url, same_host -> replaced by shared.url_utils (DELETE in Phase 3)
These duplicated utility functions exist in both fetch_context.py and the services/shared/ modules simultaneously. The shared modules were built to replace them but the originals were never deleted. CBO is artificially inflated by this dead weight.

🔴 OCP Violation: dispatch_run Flag-Branching
crawl_service.py lines 255–278 show a direct if/else on settings flags :

python
async def dispatch_run(session, run):
    if not settings.celery_dispatch_enabled:
        return await _dispatch_run_locally(session, run)
    # ... celery path ...
    if not settings.legacy_inprocess_runner_enabled:
        raise
    # ... fallback to in-process ...
Three execution paths (local, celery, celery-with-in-process-fallback) are hard-coded inside one function. Adding a fourth dispatcher (e.g., a thread-pool runner or a cloud queue) requires modifying this function. This is a textbook OCP failure.

🔴 DIP Violation: crawl_service.py Direct Instantiation of Infrastructure
crawl_service.py directly imports and calls SessionLocal (the DB factory) at line 11 and 186 :

python
from app.core.database import SessionLocal
...
async with SessionLocal() as session:
High-level orchestration logic should never instantiate its own DB session. It violates DIP — the session should be injected. This also makes the service untestable in isolation.

🟡 SRP Violation: crawl_crud.py — CRUD + Business Rules Mixed
create_crawl_run in crawl_crud.py (lines 37–113) does :

URL normalization

Surface validation

Domain run-profile merging

LLM config snapshotting

Requested-fields enrichment from domain memory

Run settings normalization

URL safety enforcement

ORM object creation and DB flush

This is 7 distinct responsibilities in a single "CRUD" function. "CRUD" implies data persistence only; all the pre-flight business logic belongs in an application service or use-case class.

🟡 Global Mutable State: Module-Level Singletons
browser_runtime.py has a module-level _BROWSER_POOL = BrowserRuntimePool() . crawl_service.py has a module-level _local_run_tasks: weakref.WeakValueDictionary. These are Global Coupling — any module that imports the file shares the same mutable state. Testing requires resetting global state, and concurrent process initialization is fragile.

🟡 crawl_service.py facade → crawl_ingestion_service.py → crawl_crud.py → crawl_service.py (Circular Concern)
The call chain from API → crawl_ingestion_service → crawl_crud.create_crawl_run → (returns run) → crawl_service.dispatch_run mixes persistence and dispatch in different files with no clear boundary. The ingestion service imports the CRUD service which snapshots LLM configs and run settings — infrastructure concerns buried in what looks like a data layer.

Phase 1 — Stabilization (No Behavior Change)
Goal: Stop the bleeding. Delete confirmed dead code, enforce file-size limits, add missing test coverage guards. Estimated effort: 1–2 weeks.

1.1 — Delete Lava Flow in fetch_context.py
The three functions with # PHASE-3 DELETE TARGETS comments must be removed now . They have already been replaced by shared.coerce_primitives, shared.text_coerce, and shared.url_utils. Every call site must be confirmed redirected to the shared module before deletion. Use grep -rn "_safe_int\|clean_text\|slug_tokens\|absolute_url\|same_host" backend/ to find all remaining callers.

Deliverable: fetch_context.py shrinks by ~50–100 lines, zero duplicate implementations.

1.2 — Rename and Split crawl_fetch_runtime.py
The current file is only 8 lines — a sys.modules redirect shim :

python
# PHASE-3 FACADE: implementation moved to app.services.fetch.fetch_context.
import sys as _sys
from app.services.fetch import fetch_context as _fetch_context
_sys.modules[__name__] = _fetch_context
This shim exists to avoid breaking callers during the move. It must be removed and all remaining callers pointing to crawl_fetch_runtime must be updated to import directly from fetch.fetch_context. Find with: grep -rn "crawl_fetch_runtime" backend/.

1.3 — Enforce a 500-Line Module Hard Limit
Add a test_structure.py check (the file already exists in tests/services/ ) that fails CI if any module in services/ exceeds 500 lines. This prevents regression while the larger refactors happen.

python
# Add to test_structure.py
import pathlib
MAX_LINES = 500
EXEMPT = {"shared_variant_logic.py", "variant_record_normalization.py"}  # tracked debt
for py in pathlib.Path("backend/app/services").rglob("*.py"):
    if py.name not in EXEMPT:
        assert py.read_text().count("\n") <= MAX_LINES, f"{py} exceeds {MAX_LINES} lines"
Phase 2 — Model Layer Decomposition
Goal: Break models/crawl.py into domain-aligned model files. No logic changes. Estimated effort: 1 week.

2.1 — Split models/crawl.py into 6 Files
Currently 19 classes in one file . Target structure:

text
app/models/
  crawl_run.py          # CrawlRun, CrawlRecord, CrawlLog
  crawl_progress.py     # BatchRunProgressState
  domain_memory.py      # DomainMemory, DomainRunProfile, DomainCookieMemory,
                        #   DomainFieldFeedback, HostProtectionMemory
  review.py             # ReviewPromotion
  product_intelligence.py  # ProductIntelligenceJob, SourceProduct,
                           #   Candidate, Match
  data_enrichment.py    # DataEnrichmentJob, EnrichedProduct
  __init__.py           # Re-exports all for backward compat during transition
2.2 — Evict BatchRunProgressState from the Model Layer
BatchRunProgressState in crawl.py is a 140-line business-logic dataclass that computes progress percentages, merges acquisition metrics, and builds JSON patches. It has zero ORM behavior. Move it to services/crawl_progress.py or services/pipeline/run_progress.py. The model layer must contain only ORM mappings and simple property accessors.

Phase 3 — Service Layer Decomposition
Goal: Split the five largest service files into focused, single-responsibility modules. Estimated effort: 2–3 weeks.

3.1 — Split pipeline/extraction_loop.py (1,329 lines)
This is the most critical split. The file currently handles :

Acquisition orchestration (fetch, browser, retry)

Extraction dispatch (call extraction_runtime.extract_records)

LLM fallback decision-making

Robots/block policy enforcement

Selector self-heal triggering

Record persistence delegation

Target split:

text
pipeline/
  acquisition_stage.py     # fetch + browser logic, block detection
  extraction_stage.py      # extract_records call + retry decision
  llm_fallback_stage.py    # LLM fallback application
  policy_gate.py           # robots, block, URL safety checks
  extraction_loop.py       # Slim orchestrator: calls the above stages in order
The extraction_loop.py should shrink to ~150 lines of pure orchestration.

3.2 — Split acquisition/browser_runtime.py (1,986 lines)
Two classes confirmed: BrowserRuntimePool and SharedBrowserRuntime with 20+ methods . Responsibilities:

text
acquisition/
  browser_pool.py         # BrowserRuntimePool — lifecycle, sizing, health
  browser_context.py      # SharedBrowserRuntime — context creation, teardown
  browser_metrics.py      # Diagnostics, failure reporting
  browser_runtime.py      # Thin re-export facade (temporary, delete in Phase 4)
3.3 — Split acquisition/traversal.py (1,903 lines)
text
acquisition/
  traversal_link_discovery.py   # Link extraction, URL deduplication
  traversal_pagination.py       # Pagination detection and navigation
  traversal_recovery.py         # DOM recovery, structured-script fallback
  traversal.py                  # Orchestrator only
3.4 — Split extract/shared_variant_logic.py (1,562 lines)
The name shared_variant_logic is a Logical Cohesion smell — a Utils-equivalent. Audit the actual functions and group by what they operate on:

text
extract/
  variant_field_resolution.py   # Field value picking logic
  variant_dom_traversal.py      # DOM-specific variant walking
  variant_schema_matching.py    # Schema/JSON-LD variant matching
  variant_normalization.py      # String normalization for variant data
3.5 — Split services/llm_tasks.py (1,095 lines)
text
services/llm/
  llm_prompt_builder.py     # Prompt template construction
  llm_response_parser.py    # Parsing and validating LLM responses
  llm_task_runner.py        # Actual task execution (discover_xpath, extract_records, etc.)
  llm_tasks.py              # Thin facade (backward compat)
Phase 4 — Architectural Hardening (SOLID Fixes)
Goal: Fix the three confirmed SOLID violations that affect testability and extensibility. Estimated effort: 1–2 weeks.

4.1 — Fix OCP: Replace dispatch_run Flag Branching with Strategy Pattern
Current code in crawl_service.py branches on settings.celery_dispatch_enabled and settings.legacy_inprocess_runner_enabled . Replace with a RunDispatcher protocol:

python
# services/dispatch/base.py
from typing import Protocol
class RunDispatcher(Protocol):
    async def dispatch(self, session: AsyncSession, run: CrawlRun) -> CrawlRun: ...

# services/dispatch/local_dispatcher.py
class LocalRunDispatcher:
    async def dispatch(self, session, run): ...

# services/dispatch/celery_dispatcher.py
class CeleryRunDispatcher:
    def __init__(self, fallback: RunDispatcher | None = None): ...
    async def dispatch(self, session, run): ...

# core/dependencies.py — wire by config at startup
def get_run_dispatcher() -> RunDispatcher:
    if settings.celery_dispatch_enabled:
        fallback = LocalRunDispatcher() if settings.legacy_inprocess_runner_enabled else None
        return CeleryRunDispatcher(fallback=fallback)
    return LocalRunDispatcher()
Adding a new dispatcher now requires zero changes to crawl_service.py.

4.2 — Fix DIP: Inject AsyncSession — Never Instantiate SessionLocal in Services
crawl_service.py directly calls SessionLocal() at line 186 . Services must never own session creation — sessions are injected by the router via FastAPI Depends(get_db) or by the Celery task wrapper in tasks.py. Audit with grep -rn "SessionLocal()" backend/app/services/ and remove every occurrence. Each function currently opening its own session should instead accept session: AsyncSession as a parameter.

4.3 — Fix SRP: Extract Pre-Flight Logic from crawl_crud.create_crawl_run
create_crawl_run in crawl_crud.py is doing 7 things . Create CrawlRunFactory (or a CreateCrawlRunUseCase) in services/crawl_ingestion_service.py that handles all pre-flight work and delegates only the ORM write to crawl_crud:

python
# services/crawl_ingestion_service.py
class CrawlRunFactory:
    async def build_run_payload(self, session, user_id, payload) -> dict:
        # URL normalization, surface validation, profile merging,
        # field enrichment, LLM snapshot — all here
        ...

# services/crawl_crud.py (after refactor)
async def create_crawl_run(session, user_id, prepared_payload: dict) -> CrawlRun:
    # ONLY: validate prepared_payload, instantiate CrawlRun, flush, return
    ...
Phase 5 — Domain Boundary Formalization
Goal: Make Product Intelligence and Data Enrichment first-class bounded contexts instead of extras bolted onto models/crawl.py. Estimated effort: 1 week.

5.1 — Introduce Domain-Aligned Folders
Currently product_intelligence/ exists as a service folder but its models live in models/crawl.py . After Phase 2 splits the models, align the full stack:

text
app/
  crawl/
    models/crawl_run.py, crawl_record.py, crawl_log.py
    services/crawl_service.py, crawl_crud.py, crawl_state.py
    api/crawls.py
  product_intelligence/
    models/product_intelligence.py
    services/discovery.py, matching.py, service.py
    api/product_intelligence.py
  data_enrichment/
    models/data_enrichment.py
    services/...
    api/data_enrichment.py
  core/       # DB, config, security, dependencies
  shared/     # coerce_primitives, url_utils, text_coerce
This eliminates the current pattern where models/crawl.py is imported by product intelligence and data enrichment services for models that conceptually belong to those domains.

Phase 6 — Test Coverage Closure
Goal: Ensure refactored modules have unit-test coverage at the new boundaries. Estimated effort: Ongoing, ~1 week dedicated.

The test suite is substantial — test_crawl_engine.py (188 KB), test_detail_extractor_structured_sources.py (208 KB), test_browser_expansion_runtime.py (153 KB). However, most tests are integration tests against the full pipeline, not unit tests against the individual modules being split. After each phase split:

test_acquisition_stage.py — unit test just the acquisition stage function

test_extraction_stage.py — unit test just extract_records call + retry decision

test_run_dispatcher.py — mock both LocalRunDispatcher and CeleryRunDispatcher, verify config-based wiring

test_crawl_run_factory.py — unit test CrawlRunFactory.build_run_payload in isolation from the DB

The test_structure.py file already exists and should be expanded after each phase to enforce the new module layout as a CI gate.

Priority Order
Priority	Phase	Key Win
🔴 1	Phase 1.1	Delete confirmed lava flow — zero risk, immediate cleanup
🔴 2	Phase 2.1–2.2	Break God Object model file — unblocks all other splits
🔴 3	Phase 4.2	Fix SessionLocal() in services — fixes DIP, improves testability
🟡 4	Phase 3.1	Split extraction_loop.py — highest complexity, highest payoff
🟡 5	Phase 4.1	Strategy pattern for dispatch — closes OCP gap
🟡 6	Phase 3.2–3.3	Split browser runtime + traversal
🟢 7	Phase 4.3	CrawlRunFactory — clean CRUD boundary
🟢 8	Phase 5	Domain folder alignment — architectural polish
🟢 9	Phase 6	Test coverage at new boundaries