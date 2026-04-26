# Engineering Strategy

## Purpose

Engineering constraints for CrawlerAI. Defines how code should be shaped and how to change it without reintroducing bloat.

`AGENTS.md` — session bootstrap and operator guide.
`INVARIANTS.md` — hard runtime contracts with violation signatures. Read it first.
`BUSINESS_LOGIC.md` — product decision points and owning files.
`CODEBASE_MAP.md` — file-to-bucket orientation map.

---

## Core Principles

**KISS** — Prefer explicit data flow. Prefer a few local conditionals over framework-like abstractions. Code must be traceable in one grep session.

**DRY** — Deduplicate only when the duplicated logic is genuinely the same rule. Do not create fake "shared" helpers that mix unrelated concerns.

**SOLID, practically** — One subsystem has one obvious owner. Facades stay small and stable. Downstream code depends on contracts, not upstream internals.

**YAGNI** — Do not add speculative plugin systems, ranking layers, policy engines, or adapter frameworks. Build only what the active product surface requires.

---

## Backend Ownership Model

| # | Bucket | Primary Files |
|---|--------|---------------|
| 1 | API + Bootstrap | `app/main.py`, `app/api/*`, `app/core/*` |
| 2 | Crawl Ingestion + Orchestration | `crawl_ingestion_service.py`, `crawl_service.py`, `crawl_crud.py`, `_batch_runtime.py`, `pipeline/*` |
| 3 | Acquisition + Browser Runtime | `acquisition/*`, `crawl_fetch_runtime.py`, `robots_policy.py`, `url_safety.py` |
| 4 | Extraction | `crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`, `structured_sources.py`, `js_state_mapper.py`, `network_payload_mapper.py`, `adapters/*`, `extract/*` |
| 5 | Publish + Persistence | `publish/*`, `artifact_store.py`, `pipeline/persistence.py` |
| 6 | Review + Selectors + Domain Memory | `review/__init__.py`, `selectors_runtime.py`, `selector_self_heal.py`, `domain_memory_service.py` |
| 7 | LLM Admin + Runtime | `llm_runtime.py`, `llm_provider_client.py`, `llm_config_service.py`, `llm_cache.py`, `llm_circuit_breaker.py`, `llm_tasks.py` |

Config tunables for all buckets → `app/services/config/*`

**If new code does not clearly belong to one bucket, stop and decide before writing.**

---

## Non-Negotiable Design Rules

1. **One obvious home per concern.** `config/field_mappings.py` is the single location for all field aliases. `field_policy.py` owns field eligibility. `crawl_fetch_runtime.py` owns fetch behavior. `crawl_engine.py` is the extraction facade.

2. **Generic code stays generic.** Platform-specific behavior goes in `adapters/[platform].py` or `config/platforms.json`. Specs and tunables go in `app/services/config/*`.

3. **Architecture must stay grep-friendly.** A failure must be traceable to one subsystem in one grep session. Avoid new layers whose main effect is hiding the call path.

4. **Strong contracts beat clever internals.** Typed boundaries and named objects over tuple returns and positional argument growth.

5. **Fix upstream, not downstream.** When extraction produces a bad field value, fix the extractor or config that produces it. Never add compensating normalizers in `publish/` or `pipeline/`.

---

## Anti-Patterns

These are patterns that have actually appeared in this codebase.
They are listed so agents recognize and stop them — not just understand the principles above in the abstract.

### AP-1: Inline config
Adding `TIMEOUT = 30` or `PLATFORM_RETRIES = 3` directly in service/extractor code.
**Fix:** Move to `app/services/config/` and import it.

### AP-2: Downstream compensation
Adding a fallback in `publish/verdict.py` or `pipeline/persistence.py` to handle malformed field values that should have been caught upstream.
**Fix:** Trace the bad value to its source and fix it there.

### AP-3: Cross-bucket field aliases
Defining field alias dicts in `detail_extractor.py` or `listing_extractor.py` separately from `config/field_mappings.py`.
**Fix:** All aliases live in `config/field_mappings.py` — surface-specific sections, one file.

### AP-4: Hardcoded platform names in generic paths
`if "shopify" in url` or `if "greenhouse" in host` inside `crawl_fetch_runtime.py`, `crawl_engine.py`, or any generic service.
**Fix:** Platform detection belongs in `adapters/registry.py` via `can_handle()` or in `config/platforms.json`.

### AP-5: New cross-cutting layer
Creating `manager.py`, `registry2.py`, `helpers.py`, or `utils_new.py` instead of placing code in the existing subsystem.
**Fix:** Find the owning bucket file and extend it, or split the existing file by responsibility.

### AP-6: Dead compat shims
Re-export stubs left behind after a migration.
**Fix:** Delete the old location entirely when the migration is done.

### AP-7: Private-function test coupling
Tests that import private functions or constants from service internals.
**Fix:** Delete these tests. Write contract tests that assert observable behavior from public APIs.

### AP-8: Speculative feature addition
An agent adds caching, a plugin hook, or a new abstraction layer that was not in the task scope.
**Fix:** YAGNI. Build what the active plan requires.

### AP-9: Duplicate variant/listing normalization
The same normalization or deduplication logic written in both `detail_extractor.py` and `listing_extractor.py`.
**Fix:** Identify which extraction stage owns it and remove the duplicate.

### AP-10: `LLM_TUNING` / config that bypasses env
A dict or constant inside a service module that silently overrides env-controlled settings.
**Fix:** All runtime tunables come from `config.py` via environment.

### AP-11: Parallel config sources for one runtime rule
The same endpoint tokens, thresholds, or classifier hints defined in two different config modules.
**Fix:** One canonical config owner. Derive any stage-specific views from it.

### AP-12: Misdiagnosing extraction as winner-takes-all when the real bugs are specific ← MOST COMMON CAUSE OF MISSING VARIANTS

The candidate system in `detail_extractor.py` is correctly field-by-field. `_winning_candidates_for_field` selects per-field independently — price and sku can come from different sources simultaneously. **Do not replace or restructure this system.**

The actual cause of missing variants and missing prices is 3 specific bugs:

**Bug 1 — Early exit in `build_detail_record` skips the DOM tier.** `_requires_dom_completion` does not check for DOM variant cues before allowing a confidence-threshold early exit. Result: variant controls in the DOM are never collected when JSON-LD fires first. Fix: add `variant_dom_cues_present(soup)` check to `_requires_dom_completion`.

**Bug 2 — `_map_ecommerce_detail_state` returns on first matching JS state object.** Sites with multiple hydration objects lose variant data from non-first objects. Fix: iterate all objects and backfill variant fields from subsequent ones.

**Bug 3 — Backfill calls not made after early exit.** `_backfill_detail_price_from_html` and variant backfill must be called before every return path in `build_detail_record`, not just after the full tier sequence.

**Visible PDP price gaps stay upstream.** If a rendered product detail page has a visible display-price block but structured data omits price, add or tune selector config in `app/services/config/extraction_rules.py` and backfill in `detail_extractor.py`. Do not repair prices in persistence, export, or verdict code. Detail extraction must still reject category/collection URLs with product-tile prices instead of fabricating a PDP record.

**Violation to avoid:** Adding browser interaction (click probes, Playwright variant walks) before verifying these 3 fixes. The probe is only justified for `stateful_dom` sites that still fail after all 3 bugs are fixed.

### AP-13: Config proliferation ← SECOND MOST COMMON
Creating a new `constants.py`, `config.py`, or inline dict inside a bucket folder
because "there was no obvious place" to put a constant.

**Violation looks like:** `services/extraction/constants.py`, `acquisition/config.py`, a `FIELD_NAMES = [...]` dict at the top of `detail_extractor.py`.

**Fix:** Before creating any config-like file or constant, grep `app/services/config/` for an appropriate home. The correct home almost always exists. If it does not, extend the nearest file — do not create a new one without explicit confirmation.

### AP-14: Plan burial — writing plans without executing them
Creating plan documents, audit reports, and remediation specs without running a verification test afterward.
This accumulates dead work that future agents misread as authoritative guidance.

**Violation looks like:** More than 3 plan files in `docs/plans/` with status `IN PROGRESS` simultaneously. An audit doc in `docs/audits/` with findings that were never closed by a passing test run. A plan slice marked DONE with no verify command logged.

**Fix:** Close plans before opening new ones. Archive audit docs that are older than the last passing test run — their findings are either fixed or irrelevant. If a plan was abandoned, mark it explicitly `ABANDONED` and note what was verified vs what was not. Do not build on top of unverified work.

### AP-15: Grep skip — creating before searching
Writing a new function, class, or module without first confirming no existing implementation covers the case.

**Violation looks like:** Two price-cleaning functions in different files. A new `normalize_price()` written because `field_value_price.py` "seemed complex." A new URL validator added alongside `url_safety.py`.

**Fix:** Always run `grep -r "function_name_or_concept" backend/app` before writing new code. If a similar function exists, extend it. If it is too complex to extend safely, the complexity is the real bug — fix that first.

---

## Agent Behavior

- Read the owning module and nearby tests before changing behavior.
- Update the canonical doc when you change architecture, ownership, or user-facing contracts.
- Do not create parallel systems because an existing module is awkward; refactor the owner instead.
- Avoid turning docs into changelogs. Capture stable knowledge, not every edit.
- When an audit or plan doc conflicts with code, trust code first, then update the docs.
- After any major implementation: run `pytest tests -q`, update the plan slice, update the relevant doc.

---

## File Shape

- Split by responsibility, not by arbitrary suffixes like `_misc`, `_helpers2`, or `_v2`.
- Large files are acceptable only when they remain coherent, searchable, and clearly owned.
- If a file becomes hard to summarize in one paragraph, it needs a structural split.
- Facade files orchestrate steps; helpers move out once responsibilities diverge.

---

## Testing Rules

Test contracts and invariants, not implementation trivia.

**High-value tests:** crawl creation/normalization, fetch escalation, traversal, listing/detail extraction behavior, source priority ordering, structured-source mapping, selector CRUD, self-heal gating, review save/promote, export/provenance, LLM boundaries and failure handling.

**Low-value tests (delete):** private helper call order, mocks that restate implementation, assertions that freeze harmless refactors, tests that import private constants just to check they exist.

---

## Documentation Rules

| Doc | Job |
|-----|-----|
| `AGENTS.md` | Session bootstrap only. Keep under 200 lines. |
| `CODEBASE_MAP.md` | File-to-bucket map. Update when files move. |
| `BUSINESS_LOGIC.md` | Product decision points and owning files. |
| `ENGINEERING_STRATEGY.md` | Engineering constraints + named anti-patterns. |
| `INVARIANTS.md` | Must-preserve runtime rules with violation signatures. |
| `backend-architecture.md` | Detailed backend reference. |
| `agent/SKILLS.md` | Task recipes. Add as new patterns emerge. |
| `agent/PLAN_PROTOCOL.md` | Plan creation and management workflow. |
| `plans/ACTIVE.md` | Current plan pointer. Always up to date. |

**Audit docs in `docs/audits/`** are read-once forensic artifacts. Once the findings are fixed and verified by a passing test run, archive or delete them. Do not attach stale audit docs to new agent sessions.

**Plan docs in `docs/plans/`** are active working documents only while IN PROGRESS. Abandoned plans must be marked `ABANDONED`. Completed plans are historical. Neither abandoned nor completed plans should be attached to new agent sessions.

---

## Change Workflow

1. Identify owning subsystem from `CODEBASE_MAP.md`.
2. Grep for existing implementations before writing anything new.
3. Read local code and nearby tests first.
4. If non-trivial, create a plan per `PLAN_PROTOCOL.md`.
5. Make the smallest responsible change set. Delete before adding.
6. Add or adjust focused tests.
7. Update the canonical doc if behavior, ownership, or contracts changed.
8. Run verify command. Mark slice done only after verify passes.
