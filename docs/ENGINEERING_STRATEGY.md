# Engineering Strategy

## Purpose

This is the engineering constraints doc for the repo.

`CLAUDE.md` is the short operator guide.
`INVARIANTS.md` is the hard runtime contract.
`backend-architecture.md` and `frontend-architecture.md` describe the live system.

This file defines how code should be shaped and how agents and humans should change it without reintroducing bloat.

## Core Principles

### KISS

- Prefer explicit data flow over hidden indirection.
- Prefer a few local conditionals over framework-like abstraction layers.
- Prefer code that is easy to trace in one grep session.

### DRY

- Deduplicate only when the duplicated logic is genuinely the same rule.
- Do not create fake “shared” helpers that mix unrelated concerns.
- If two docs repeat the same architecture description, collapse them.

### SOLID, practically

- One subsystem should have one obvious owner.
- Facades should stay small and stable.
- Downstream code should depend on contracts, not upstream internals.

### YAGNI

- Do not add speculative plugin systems, ranking layers, policy engines, or adapter frameworks.
- Build only what the active product surface and current extraction roadmap require.

## Backend Ownership Model

1. API and platform bootstrap
   Files: `app/main.py`, `app/api/*`, `app/core/*`
2. Crawl ingestion and orchestration
   Files: `crawl_ingestion_service.py`, `crawl_service.py`, `crawl_crud.py`, `_batch_runtime.py`, `pipeline/*`
3. Acquisition and browser runtime
   Files: `acquisition/*`, `crawl_fetch_runtime.py`, `robots_policy.py`, `url_safety.py`
4. Extraction
   Files: `crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`, `structured_sources.py`, `js_state_mapper.py`, `network_payload_mapper.py`
5. Publish and persistence
   Files: `publish/*`, `artifact_store.py`, `pipeline/core.py`, `pipeline/persistence.py`
6. Review, selectors, and domain memory
   Files: `review/__init__.py`, `selectors_runtime.py`, `selector_self_heal.py`, `domain_memory_service.py`
7. LLM admin and runtime
   Files: `llm_runtime.py`, `llm_provider_client.py`, `llm_config_service.py`, `llm_cache.py`, `llm_circuit_breaker.py`, `llm_tasks.py`

If new code does not clearly belong to one of these, stop and place it deliberately.

## Frontend Ownership Model

1. App shell, auth session, navigation
   Files: `components/layout/*`, `app/layout.tsx`
2. API client and contract types
   Files: `lib/api/*`
3. Crawl config and dispatch
   Files: `components/crawl/crawl-config-screen.tsx`, `components/crawl/shared.tsx`
4. Run workspace and live polling
   Files: `components/crawl/crawl-run-screen.tsx`, `use-run-polling.ts`
5. Operator tools and admin
   Files: `app/selectors/page.tsx`, `app/admin/*`, `app/jobs/page.tsx`, `app/runs/page.tsx`, `app/dashboard/page.tsx`

## Non-Negotiable Design Rules

### 1. One obvious home per concern

- `pipeline/core.py` owns per-URL orchestration, not extraction internals.
- `crawl_fetch_runtime.py` owns fetch/runtime behavior, not record semantics.
- `crawl_engine.py` is the extraction facade.
- `publish/*` owns verdict, metrics, and commit metadata.
- `field_policy.py` owns field naming and eligibility rules.
- `selectors_runtime.py` and `domain_memory_service.py` own selector persistence and reuse.
- LLM transport/config/cache belongs in LLM modules, not in extraction modules.

### 2. Generic code stays generic

- Do not bury site- or tenant-specific hacks in generic runtime, routing, or utility modules when adapters or config can own them.
- Specs and tunables go in `app/services/config/*` when they are configuration, not in service bodies.

### 3. Architecture should stay grep-friendly

- A failure should be traceable quickly to one subsystem.
- Avoid new layers whose main effect is hiding the call path.
- Avoid alias wrappers and compatibility shims that outlive their migration window.

### 4. Strong contracts beat clever internals

- Preserve route-level and record-level contracts unless the user explicitly wants them changed.
- Prefer typed boundaries and named objects over tuple returns and positional argument growth.

## Agent Behavior In This Repo

- Read the owning module and nearby tests before changing behavior.
- Update the canonical doc when you change architecture, ownership, or user-facing contracts.
- Do not create parallel systems because an existing module is awkward; refactor the owner instead.
- Avoid turning docs into changelogs. Capture stable knowledge, not every edit.
- When an audit or plan doc conflicts with code, trust code first and then update the docs.

## File Shape Guidance

- Facade files may orchestrate multiple steps, but helpers should move out once responsibilities diverge.
- Split by responsibility, not by arbitrary suffixes such as `_misc`, `_helpers2`, or `_v2`.
- Large files are acceptable only when they remain coherent, searchable, and clearly owned.
- If a file becomes hard to summarize in one paragraph, it probably needs a structural split.

## Testing Rules

Test contracts and invariants, not implementation trivia.

High-value tests:

- crawl creation and settings normalization
- fetch/runtime escalation, traversal, robots, diagnostics, browser identity
- detail/listing extraction behavior
- structured-source mapping and payload mapping
- selector CRUD, selector self-heal, and domain-memory reuse
- review save/promote behavior
- provenance and export behavior
- LLM config/runtime boundaries and failure handling

Low-value tests:

- private helper call order
- mocks that just restate implementation
- assertions that freeze harmless refactors

If a rule matters, a focused test should defend it.

## Documentation Rules

- `CLAUDE.md`: short entrypoint and agent guardrails
- `ENGINEERING_STRATEGY.md`: engineering constraints, principles, ownership, workflow
- `INVARIANTS.md`: must-preserve runtime behavior
- `backend-architecture.md`: detailed backend map and live feature inventory
- `frontend-architecture.md`: detailed frontend map and frontend/backend contract notes

Do not let multiple docs compete for the same job.

## Current Architectural Takeaways

The recent refactor added real capability:

- extruct-backed structured sources
- declarative network payload specs
- browserforge identity restoration
- URL tracking-param stripping
- selector self-heal + domain memory
- provenance/review-bucket-aware responses
- live selectors and LLM admin surfaces

Those gains should not be followed by uncontrolled subsystem growth. The right move now is disciplined consolidation, not another wave of abstraction.

## Change Workflow

1. Identify the owning subsystem.
2. Read the local code and nearby tests first.
3. Make the smallest responsible change set.
4. Add or adjust focused tests.
5. Update the canonical doc if behavior, ownership, or contracts changed.
6. Verify with focused checks before widening scope.
