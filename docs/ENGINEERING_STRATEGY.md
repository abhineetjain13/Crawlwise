# Engineering Strategy

## Purpose

This is the engineering constraints doc for the repo.

`AGENTS.md` is the session bootstrap and operator guide.
`INVARIANTS.md` is the hard runtime contract.
`backend-architecture.md` and `frontend-architecture.md` describe the live system.
`docs/CODEBASE_MAP.md` is the compressed file-to-bucket orientation map.

This file defines how code should be shaped and how agents and humans should change it
without reintroducing bloat.

---

## Core Principles

### KISS
- Prefer explicit data flow over hidden indirection.
- Prefer a few local conditionals over framework-like abstraction layers.
- Prefer code that is easy to trace in one grep session.

### DRY
- Deduplicate only when the duplicated logic is genuinely the same rule.
- Do not create fake "shared" helpers that mix unrelated concerns.
- If two docs repeat the same architecture description, collapse them.

### SOLID, practically
- One subsystem should have one obvious owner.
- Facades should stay small and stable.
- Downstream code should depend on contracts, not upstream internals.

### YAGNI
- Do not add speculative plugin systems, ranking layers, policy engines, or adapter frameworks.
- Build only what the active product surface and current extraction roadmap require.

---

## Backend Ownership Model

1. **API + Bootstrap** — `app/main.py`, `app/api/*`, `app/core/*`
2. **Crawl Ingestion + Orchestration** — `crawl_ingestion_service.py`, `crawl_service.py`, `crawl_crud.py`, `_batch_runtime.py`, `pipeline/*`
3. **Acquisition + Browser Runtime** — `acquisition/*`, `crawl_fetch_runtime.py`, `robots_policy.py`, `url_safety.py`
4. **Extraction** — `crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`, `structured_sources.py`, `js_state_mapper.py`, `network_payload_mapper.py`, `adapters/*`, `extract/*`
5. **Publish + Persistence** — `publish/*`, `artifact_store.py`, `pipeline/persistence.py`
6. **Review + Selectors + Domain Memory** — `review/__init__.py`, `selectors_runtime.py`, `selector_self_heal.py`, `domain_memory_service.py`
7. **LLM Admin + Runtime** — `llm_runtime.py`, `llm_provider_client.py`, `llm_config_service.py`, `llm_cache.py`, `llm_circuit_breaker.py`, `llm_tasks.py`

Config tunables for all buckets: `app/services/config/*`

If new code does not clearly belong to one of these, stop and place it deliberately.

---

## Frontend Ownership Model

1. App shell, auth session, navigation — `components/layout/*`, `app/layout.tsx`
2. API client and contract types — `lib/api/*`
3. Crawl config and dispatch — `components/crawl/crawl-config-screen.tsx`
4. Run workspace and live polling — `components/crawl/crawl-run-screen.tsx`, `use-run-polling.ts`
5. Operator tools and admin — `app/selectors/*`, `app/admin/*`, `app/jobs/*`, `app/runs/*`, `app/dashboard/*`

---

## Non-Negotiable Design Rules

### 1. One obvious home per concern
- `pipeline/core.py` owns per-URL orchestration, not extraction internals.
- `crawl_fetch_runtime.py` owns fetch/runtime behavior, not record semantics.
- `crawl_engine.py` is the extraction facade.
- `publish/*` owns verdict, metrics, and commit metadata.
- `field_policy.py` owns field naming and eligibility rules.
- `config/field_mappings.py` is the single location for all field aliases — all surfaces, one file.
- `selectors_runtime.py` and `domain_memory_service.py` own selector persistence and reuse.
- LLM transport/config/cache belongs in LLM modules, not in extraction modules.

### 2. Generic code stays generic
- Do not bury site- or tenant-specific hacks in generic runtime, routing, or utility modules.
- Platform-specific behavior goes in `adapters/[platform].py` or `config/platforms.json`.
- Specs and tunables go in `app/services/config/*`, not in service bodies.

### 3. Architecture must stay grep-friendly
- A failure should be traceable quickly to one subsystem.
- Avoid new layers whose main effect is hiding the call path.
- Avoid alias wrappers and compatibility shims that outlive their migration window.

### 4. Strong contracts beat clever internals
- Preserve route-level and record-level contracts unless the user explicitly wants them changed.
- Prefer typed boundaries and named objects over tuple returns and positional argument growth.

### 5. Fix upstream, not downstream
- When extraction produces a bad field value, fix the extractor or config that produces it.
- Do not add compensating normalizers in `publish/` or `pipeline/` to paper over bad upstream data.

---

## Anti-Patterns (Named, Specific to This Repo)

These are patterns that have actually appeared in this codebase. They are listed so agents
recognize and stop them, not just understand the principles above in the abstract.

### AP-1: Inline config
Adding `TIMEOUT = 30` or `PLATFORM_RETRIES = 3` directly in service/extractor code.
**Fix:** Move to `app/services/config/` and import it.

### AP-2: Downstream compensation
Adding a fallback in `publish/verdict.py` or `pipeline/persistence.py` to handle malformed
field values that should have been caught upstream in the extractor or field alias config.
**Fix:** Trace the bad value to its source and fix it there.

### AP-3: Cross-bucket field aliases
Defining field alias dictionaries in `detail_extractor.py` or `listing_extractor.py` separately
from `config/field_mappings.py`, causing divergence between surfaces.
**Fix:** All aliases live in `config/field_mappings.py` — surface-specific sections, one file.

### AP-4: Hardcoded platform names in generic paths
`if "shopify" in url` or `if "greenhouse" in host` inside `crawl_fetch_runtime.py`,
`crawl_engine.py`, or any generic service.
**Fix:** Platform detection belongs in `adapters/registry.py` via `can_handle()` or in `config/platforms.json`.

### AP-5: New cross-cutting layer
Creating a new `manager.py`, `registry2.py`, `helpers.py`, or `utils_new.py` instead of
placing code in the existing subsystem that owns the concern.
**Fix:** Find the owning bucket file and extend it, or split the existing file by responsibility.

### AP-6: Dead compat shims
Re-export stubs left behind after a migration (e.g., `from acquisition.runtime import fetch_page`
as a passthrough after the real move to `crawl_fetch_runtime`).
**Fix:** Delete the old location entirely when the migration is done.

### AP-7: Private-function test coupling
Tests that import private functions or constants from service internals to assert call order
or internal state rather than asserting observable behavior.
**Fix:** Delete these tests. Write contract tests that assert what comes out of public APIs.

### AP-8: Speculative feature addition
An agent adds caching, a plugin hook, or a new abstraction layer that was not in the task
scope, reasoning that "it might be useful later."
**Fix:** YAGNI. Build what the active plan requires. Open a separate plan if the new thing is genuinely needed.

### AP-9: Duplicate variant/listing normalization
The same normalization or deduplication logic written in both `detail_extractor.py` and
`listing_extractor.py` (or in an adapter) without a shared owner.
**Fix:** Identify which extraction stage should own it and remove the duplicate.

### AP-10: `LLM_TUNING` / config that bypasses env
A dict or constant inside a service module that silently overrides or duplicates what
should be an env-controlled setting from `app/core/config.py`.
**Fix:** All runtime tunables come from `config.py` via environment. Remove the inline override.

### AP-11: Parallel config sources for one runtime rule
The same endpoint tokens, thresholds, or classifier hints defined in two different config modules
for different stages of the pipeline, so capture and extraction drift over time.
**Fix:** Keep one canonical config owner and derive any stage-specific views from it.

---

## Agent Behavior In This Repo

- Read the owning module and nearby tests before changing behavior.
- Update the canonical doc when you change architecture, ownership, or user-facing contracts.
- Do not create parallel systems because an existing module is awkward; refactor the owner instead.
- Avoid turning docs into changelogs. Capture stable knowledge, not every edit.
- When an audit or plan doc conflicts with code, trust code first and then update the docs.
- After any major implementation: run `pytest tests -q`, update the plan slice, update the relevant doc.

---

## File Shape Guidance

- Facade files may orchestrate multiple steps, but helpers should move out once responsibilities diverge.
- Split by responsibility, not by arbitrary suffixes such as `_misc`, `_helpers2`, or `_v2`.
- Large files are acceptable only when they remain coherent, searchable, and clearly owned.
- If a file becomes hard to summarize in one paragraph, it probably needs a structural split.

---

## Testing Rules

Test contracts and invariants, not implementation trivia.

**High-value tests:**
- Crawl creation and settings normalization
- Fetch/runtime escalation, traversal, robots, diagnostics, browser identity
- Detail/listing extraction behavior and source priority ordering
- Structured-source mapping and payload mapping
- Selector CRUD, selector self-heal gating (only saves improvements), domain-memory reuse
- Review save/promote behavior
- Provenance and export behavior
- LLM config/runtime boundaries and failure handling

**Low-value tests (delete these):**
- Private helper call order
- Mocks that just restate implementation
- Assertions that freeze harmless refactors
- Tests that import private constants just to check they exist

If a rule matters, a focused test should defend it.

---

## Documentation Rules

- `AGENTS.md` — session bootstrap only. Keep under 200 lines.
- `docs/CODEBASE_MAP.md` — file-to-bucket map. Update when files are added/moved.
- `docs/ENGINEERING_STRATEGY.md` — engineering constraints + named anti-patterns.
- `docs/INVARIANTS.md` — must-preserve runtime behavior.
- `docs/backend-architecture.md` — detailed backend map and live feature inventory.
- `docs/frontend-architecture.md` — detailed frontend map and client/backend contract notes.
- `docs/agent/SKILLS.md` — task recipes for common operations.
- `docs/agent/PLAN_PROTOCOL.md` — plan creation and management workflow.

Do not let multiple docs compete for the same job.

---

## Change Workflow

1. Identify the owning subsystem from `docs/CODEBASE_MAP.md`.
2. Read the local code and nearby tests first.
3. If the task is non-trivial, create a plan per `docs/agent/PLAN_PROTOCOL.md`.
4. Make the smallest responsible change set.
5. Add or adjust focused tests.
6. Update the canonical doc if behavior, ownership, or contracts changed.
7. Verify with focused test run before widening scope.
