# Repository Stabilization Master Plan

Verified on April 20, 2026.

This is the canonical repo-wide stabilization plan.

It supersedes repo-stabilization use of:

- `docs/SPA_ACQUISITION_IMPROVEMENT_PLAN.md`
- `docs/plans/gemini-audit-remediation-tracker.md`
- `docs/plans/browser-runtime-remediation-plan.md`
- `docs/plans/extraction-enhancement-tracker.md`

Those documents may still contain useful local evidence, but they are not the execution source of truth for stabilization work after this document lands.

## Required References

Every slice prompt in this file assumes the implementation agent reads these first:

- [CLAUDE.md](/c:/Projects/pre_poc_ai_crawler/CLAUDE.md:1)
- [ENGINEERING_STRATEGY.md](/c:/Projects/pre_poc_ai_crawler/docs/ENGINEERING_STRATEGY.md:1)
- [INVARIANTS.md](/c:/Projects/pre_poc_ai_crawler/docs/INVARIANTS.md:1)
- [backend-architecture.md](/c:/Projects/pre_poc_ai_crawler/docs/backend-architecture.md:1)
- [gemini-audit.md](/c:/Projects/pre_poc_ai_crawler/docs/audits/gemini-audit.md:1)
- [crawl_audit.md](/c:/Projects/pre_poc_ai_crawler/docs/audits/crawl_audit.md:1)

## Planning Rules

- Tests are evidence, not absolution. A passing or intentionally narrow test does not automatically clear a risky code path.
- Audit claims are carried, narrowed, or rejected only after code inspection against the owning subsystem and repo contracts.
- If a test preserves behavior that conflicts with [INVARIANTS.md](/c:/Projects/pre_poc_ai_crawler/docs/INVARIANTS.md:1), the invariant wins and the test must change with the code.
- No slice may increase repository LOC net. Net LOC must be negative per slice.
- No slice may create a parallel path, alternate runner, `_v2`, new manager layer, or speculative framework.
- If a slice cannot stay inside its listed owners or cannot finish net-negative, stop and split or collapse existing code first.

## Objective

Raise the repo to an effective minimum of 8/10 across:

1. SOLID / DRY / KISS
2. Configuration hygiene
3. Scalability / maintainability / resource management
4. Extraction and normalization quality
5. Traversal mode robustness
6. Resilience and error handling
7. Dead code and technical debt
8. Acquisition mode and site coverage

## Verification Method

This plan is based on:

- direct code inspection of the owning modules
- current repo contracts in `CLAUDE.md`, `ENGINEERING_STRATEGY.md`, and `INVARIANTS.md`
- focused test runs
- audit-doc claims treated as hypotheses, not as self-proving facts

Focused verification executed on April 20, 2026:

- `python -m pytest backend/tests/services/test_platform_detection.py backend/tests/services/test_crawl_fetch_runtime.py backend/tests/services/test_job_platform_adapters.py backend/tests/services/test_llm_runtime.py backend/tests/services/test_crawl_service.py -q`
  Result: `1 failed, 58 passed`
  Live failure: `test_resolve_browser_readiness_policy_requires_networkidle_for_platform_or_traversal`
- `python -m pytest backend/tests/services/test_selectolax_css_migration.py backend/tests/services/test_confidence.py backend/tests/services/test_field_value_dom.py backend/tests/services/test_network_payload_mapper.py backend/tests/services/test_script_text_extraction.py -q`
  Result: `1 failed, 47 passed`
  Live failure: `test_listing_extractor_preserves_css_card_field_output`

## Audit Ledger

This table exists so no later agent has to reinterpret Gemini findings from scratch.

| Gemini point | Audit result | Execution disposition |
| --- | --- | --- |
| `detail_extractor.build_detail_record` nested closure factory | Upheld | Carry as a real maintainability and testability problem. Refactor inside the extraction owner, no new subsystem. |
| `adapters/adp.py` duplicate `_text` helper | Upheld | Delete duplicate helper. |
| `llm_tasks.py` manual payload validators | Upheld | Replace with typed validation in the LLM owner path. |
| `platform_url_normalizers.py` hardcoded ADP tenant domains | Upheld | Move authority to platform config/policy. |
| Adapter timeout magic numbers | Upheld | Centralize in `adapter_runtime_settings.py` and delete inline values. |
| `_image_candidate_score` hardcoded query params | Upheld | Fold into config hygiene cleanup. |
| sync extraction on async hot path | Upheld | Offload in pipeline orchestration. |
| `crawl_service.py` failure task durability risk | Upheld, narrower than stated | The task is tracked, but failure persistence is still shutdown-fragile. Fix under the orchestration owner. |
| destructive noise removal before structured parsing | Partially upheld | The behavior is intentional and test-backed, but the selector is broad enough to justify a safety-hardening pass rather than dismissal. |
| selector-ranking pollution in DOM fallbacks | Upheld | User/domain selectors need deterministic precedence over generic DOM fallbacks. |
| adapter HTML fallback duplication | Upheld | Remove duplicate Greenhouse/OracleHCM/UltiPro-style DOM scraping where generic extraction already owns it. |
| alias surface bleed risk | Upheld, low severity | Harden only if it reduces code. |
| traversal inline JS brittleness | Upheld, low severity | Clean up only inside the traversal owner and only if net-negative. |
| broad fetch exception handling and missing HTTP backoff | Upheld | Implement real retry/backoff inside fetch/runtime. |
| `safe_select()` swallowing selector errors | Upheld | Narrow exception handling and surface failures deliberately. |
| `_trim_prompt_section_body()` JSON decode fallback | Upheld | Tighten truncation behavior. |
| hardcoded `_LLML_FIELD_TYPE_VALIDATORS` in pipeline | Upheld | Collapse into existing field metadata/config. |
| hardcoded `_JOB_SECTION_PATTERNS` | Upheld | Externalize only if code gets smaller. |
| `llm_runtime.py` boundary muddiness | Upheld, low severity | Simplify or shrink facade. |
| no native Apollo support | Partially upheld | Current code already has partial Apollo-related patterns. Carry as coverage/consolidation work, not as a greenfield gap. |
| per-URL acquisition profile causing unstable browser identity | Upheld, low severity | Stabilize identity per run in acquisition-owned code. |
| markdownify-style pre-LLM context reduction | Verified as absent | Carry only as a replacement candidate if it can reduce existing prompt-prep LOC and improve token density. Not a first-pass mandatory slice. |
| visual prominence / bounding-box extraction | Verified as absent | Carry as optional extraction enhancement only if it can replace weaker heuristics with net-negative LOC. Not mandatory for first stabilization pass. |
| extend declarative `glom` strategy to network payload mapping | Upheld as consolidation opportunity | Carry only if it deletes custom traversal code and stays grep-friendly. |

## Non-Negotiable Constraints

These are binding for all slices:

- `pipeline/core.py` owns per-URL orchestration.
- `crawl_fetch_runtime.py` owns fetch/runtime behavior.
- `crawl_engine.py`, `detail_extractor.py`, `listing_extractor.py`, `structured_sources.py`, `js_state_mapper.py`, and `network_payload_mapper.py` own extraction behavior.
- `publish/*` owns verdict and metrics.
- Config and site-family rules belong in `backend/app/services/config/*` and `platform_policy.py`, not in generic runtime bodies.
- Browser escalation and traversal remain separate decisions.
- Listing pages do not regress into synthetic detail behavior.
- Shared runtime tunables stay config-driven.

## Slice Summary

| Slice | Title | Primary score lift |
| --- | --- | --- |
| Slice 1 | Orchestration watchdog and async hot-path stability | 3, 6, 7 |
| Slice 2 | Acquisition runtime, SPA escalation, and traversal readiness | 2, 5, 6, 8 |
| Slice 3 | Extraction fidelity and selector precedence | 1, 4, 6 |
| Slice 4 | Config hygiene and adapter deduplication | 1, 2, 7 |
| Slice 5 | Structured-state and network-payload consolidation | 4, 8 |
| Slice 6 | LLM boundary simplification | 1, 6, 7 |
| Slice 7 | Harness fidelity and verdict honesty | 5, 6, 8 |
| Slice 8 | Optional enhancement gate | 4, 8 |

## Common Execution Prompt

Use this preamble before any slice:

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, and `docs/plans/repo-stabilization-master-plan.md`. Work only inside the owner modules listed for this slice. Treat tests as evidence, not absolution. If an existing test preserves behavior that conflicts with invariants or the slice contract, update the test with the code. Net LOC for the slice must be negative. Do not create new layers, runners, registries, managers, or `_v2` paths. Execute the slice directly without reopening plan design.

## Slice 1: Orchestration Watchdog And Async Hot-Path Stability

**Execution prompt**

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, and `docs/plans/repo-stabilization-master-plan.md`. Implement Slice 1 only. Keep all work inside `backend/app/services/pipeline/core.py`, `backend/app/services/_batch_runtime.py`, and `backend/app/services/crawl_service.py`. Add the missing production per-URL timeout using the existing crawl settings contract, offload sync extraction work off the async hot path, make local failure persistence terminal and durable inside the orchestration owner, and remove the hardcoded LLM field-type validator map by reusing existing field metadata. Net LOC must be negative. Do not add a new worker layer, a new task registry, or a second timeout system.

Owners:

- `backend/app/services/pipeline/core.py`
- `backend/app/services/_batch_runtime.py`
- `backend/app/services/crawl_service.py`

Verified issues:

- missing production per-URL watchdog
- sync extraction on async hot path
- shutdown-fragile local failure persistence
- hardcoded `_LLML_FIELD_TYPE_VALIDATORS`

Required deletions:

- any harness-only timeout logic that duplicates production responsibility
- callback-only failure-persistence code path
- the hardcoded field-type map once existing metadata is reused

Acceptance gates:

- `backend/tests/services/test_batch_runtime.py`
- `backend/tests/services/test_crawl_service.py`
- focused test proving production path enforces per-URL timeout
- focused test proving extraction work is thread-offloaded

Non-goals:

- no multiprocess redesign
- no record-schema changes

## Slice 2: Acquisition Runtime, SPA Escalation, And Traversal Readiness

**Execution prompt**

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, and `docs/plans/repo-stabilization-master-plan.md`. Implement Slice 2 only. Keep all work inside `backend/app/services/crawl_fetch_runtime.py`, `backend/app/services/platform_policy.py`, `backend/app/services/config/platforms.json`, `backend/app/services/acquisition/acquirer.py`, `backend/app/services/acquisition/browser_runtime.py`, and `backend/app/services/acquisition/traversal.py`. Honor the configured HTTP retry/backoff settings in fetch/runtime, fix SPA-shell browser escalation order, make traversal readiness enforce network-idle when traversal is active, and stabilize browser identity per run inside acquisition-owned code. If traversal inline JavaScript is cleaned up, do it only if total LOC goes down. Net LOC must be negative. Do not create a new acquisition engine, a new readiness policy system, or a new runner.

Owners:

- `backend/app/services/crawl_fetch_runtime.py`
- `backend/app/services/platform_policy.py`
- `backend/app/services/config/platforms.json`
- `backend/app/services/acquisition/acquirer.py`
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/acquisition/traversal.py`

Verified issues:

- missing HTTP retry/backoff despite config support
- broad exception boundaries in fetch/runtime
- SPA-like 404 shell returns before escalation
- `traversal_active` ignored by readiness policy
- commerce SPA rules under-configured relative to ATS
- browser identity instability within a run
- brittle inline traversal inspection JS

Required deletions:

- duplicate or dead HTTP waterfall branches after retry consolidation
- runtime-only hardcoded SPA rules that can move to config
- repeated inline traversal inspection code if moved to one local helper

Acceptance gates:

- `backend/tests/services/test_crawl_fetch_runtime.py`
- `backend/tests/services/test_platform_detection.py`
- `backend/tests/services/test_crawl_engine.py`
- focused test proving retry/backoff occurs before browser escalation on retryable failures
- focused test proving SPA-shell 404 pages can still escalate
- focused test proving same-run browser identity is stable

Corpus gate:

- rerun current SPA problem surfaces from `TEST_SITES.md` and the SPA artifact set without indefinite hangs

Non-goals:

- no new browser-profile service
- no change to user-owned traversal authorization

## Slice 3: Extraction Fidelity And Selector Precedence

**Execution prompt**

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, and `docs/plans/repo-stabilization-master-plan.md`. Implement Slice 3 only. Keep all work inside `backend/app/services/detail_extractor.py`, `backend/app/services/listing_extractor.py`, `backend/app/services/field_value_dom.py`, and `backend/app/services/field_value_candidates.py`. Flatten the hidden stage-closure behavior in detail extraction without creating a new extraction subsystem, give user/domain selector hits deterministic precedence over generic DOM fallbacks, narrow selector-error swallowing, and fix the live listing-rating regression. Because the noise-removal selector remains broad, add a safety-hardening check that protects primary-content extraction without removing the current chrome-filtering intent. Net LOC must be negative. Do not add a ranking engine or LLM-based extraction layer.

Owners:

- `backend/app/services/detail_extractor.py`
- `backend/app/services/listing_extractor.py`
- `backend/app/services/field_value_dom.py`
- `backend/app/services/field_value_candidates.py`
- `backend/app/services/extraction_context.py`

Verified issues:

- nested mutating stage collectors in detail extraction
- selector/generic DOM precedence ambiguity
- overly broad selector exception swallowing
- live rating regression in listing extraction
- broad `NOISE_CONTAINER_REMOVAL_SELECTOR` can preserve hidden bugs if left unguarded

Required deletions:

- duplicated candidate-source bookkeeping
- closure-local stage logic replaced by explicit helpers
- dead fallback branches after precedence becomes deterministic

Acceptance gates:

- `backend/tests/services/test_selectolax_css_migration.py`
- `backend/tests/services/test_confidence.py`
- `backend/tests/services/test_field_value_dom.py`
- focused test proving selector precedence over generic DOM fallbacks
- focused test proving invalid selectors fail in a controlled, observable way
- focused test proving noise-removal safety on a page where a broad sidebar-like wrapper contains primary content

Non-goals:

- no new extraction package
- no change to canonical schema names

## Slice 4: Configuration Hygiene And Adapter Deduplication

**Execution prompt**

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, and `docs/plans/repo-stabilization-master-plan.md`. Implement Slice 4 only. Keep all work inside `backend/app/services/platform_url_normalizers.py`, `backend/app/services/platform_policy.py`, `backend/app/services/config/platforms.json`, `backend/app/services/config/adapter_runtime_settings.py`, `backend/app/services/extraction_html_helpers.py`, `backend/app/services/field_policy.py`, and the ATS adapters that still carry duplicate DOM fallback logic or hardcoded timeouts. Remove hardcoded ADP tenant logic from generic runtime code, centralize ATS adapter timeouts, delete duplicate helper code, externalize hardcoded extraction heuristics only when it reduces code, and remove adapter HTML fallbacks that duplicate generic extraction ownership. Net LOC must be negative. Do not build an adapter framework or add tenant-specific hacks.

Owners:

- `backend/app/services/platform_url_normalizers.py`
- `backend/app/services/platform_policy.py`
- `backend/app/services/config/platforms.json`
- `backend/app/services/config/adapter_runtime_settings.py`
- `backend/app/services/extraction_html_helpers.py`
- `backend/app/services/field_policy.py`
- ATS adapters with hardcoded timeouts or duplicate DOM fallback logic

Verified issues:

- hardcoded ADP tenant domains
- duplicated ADP `_text` helper
- ATS adapter timeout magic numbers
- hardcoded job-section patterns
- hardcoded image query-param scoring names
- low-risk alias boundary drift
- duplicate adapter HTML detail fallback logic

Required deletions:

- inline ADP domain sets
- inline ATS timeout values in touched adapters
- duplicate DOM HTML fallback code replaced by generic extractor ownership

Acceptance gates:

- `backend/tests/services/test_job_platform_adapters.py`
- `backend/tests/services/test_config_imports.py`
- focused test proving ADP normalization reads configured domains
- focused test proving ATS adapter timeouts come from runtime settings

Non-goals:

- no new adapter registry abstraction
- no new config system

## Slice 5: Structured-State And Network-Payload Consolidation

**Execution prompt**

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, and `docs/plans/repo-stabilization-master-plan.md`. Implement Slice 5 only. Keep all work inside `backend/app/services/structured_sources.py`, `backend/app/services/js_state_mapper.py`, and `backend/app/services/network_payload_mapper.py`. Treat the Gemini Apollo concern as a partial-coverage issue, not as proof of a missing subsystem. Preserve current state-source support, harden generic hydration coverage where it is actually thin, and consolidate mapping strategy only when doing so deletes custom traversal code. Net LOC must be negative. Do not add a second mapping framework or a dedicated Apollo extraction path.

Owners:

- `backend/app/services/structured_sources.py`
- `backend/app/services/js_state_mapper.py`
- `backend/app/services/network_payload_mapper.py`

Verified issues:

- partial Apollo-related support exists but coverage is not clearly first-class
- mapping strategy is split between declarative and custom traversal code

Required deletions:

- custom path-resolution code only where declarative reuse clearly replaces it

Acceptance gates:

- `backend/tests/services/test_network_payload_mapper.py`
- `backend/tests/services/test_script_text_extraction.py`
- add focused test for a current Apollo-like hydrated state shape only if it can be expressed without adding a new mapping subsystem

Non-goals:

- no greenfield Apollo mapper
- no speculative data-source family

## Slice 6: LLM Boundary Simplification

**Execution prompt**

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, and `docs/plans/repo-stabilization-master-plan.md`. Implement Slice 6 only. Keep all work inside `backend/app/services/llm_tasks.py` and `backend/app/services/llm_runtime.py`. Replace the manual payload-validation wall with typed validation, tighten prompt-section truncation behavior, and simplify the LLM facade boundary if that can be done with less code. Do not treat current prompt-bounding tests as proof that prompt construction is optimal; they only prove current behavior. Net LOC must be negative. Do not redesign prompts or rewrite provider transport.

Owners:

- `backend/app/services/llm_tasks.py`
- `backend/app/services/llm_runtime.py`

Verified issues:

- manual payload validation
- JSON decode fallback looseness in truncation
- boundary muddiness in `llm_runtime.py`
- markdownify-style prompt reduction absent, but only a candidate if it can replace code rather than add parallel formatting

Required deletions:

- manual validator functions replaced by typed models
- redundant facade exports if caller imports can stay explicit

Acceptance gates:

- `backend/tests/services/test_llm_runtime.py`
- focused test proving validation failures stay explicit
- focused test proving truncation keeps structured framing as far as possible

Non-goals:

- no prompt redesign
- no provider/client rewrite

## Slice 7: Harness Fidelity And Verdict Honesty

**Execution prompt**

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, `TEST_SITES.md`, and `docs/plans/repo-stabilization-master-plan.md`. Implement Slice 7 only. Keep all work inside `backend/run_test_sites_acceptance.py`, `backend/harness_support.py`, and directly adjacent existing harness helpers. Do not create a new runner. Make the harness classify outcomes honestly, expose whether it is running acquisition-only or full-pipeline mode, and align timeout/reporting with production ownership after Slices 1 and 2 land. Net LOC must be negative. Do not embed production logic in the harness.

Owners:

- `backend/run_test_sites_acceptance.py`
- `backend/harness_support.py`

Verified issues:

- optimistic success classification
- harness path diverges from production ownership
- hidden confusion between acquisition-only and full-pipeline behavior

Required deletions:

- any truthy-`ok` success shortcut
- harness-local logic that duplicates production timeout or verdict responsibility

Acceptance gates:

- existing harness checks
- focused check that placeholder shells and wrong-content pages are not reported as success
- focused check that mode is explicit in output

Non-goals:

- no new acceptance runner
- no production verdict logic moved into harness code

## Slice 8: Optional Enhancement Gate

This slice is not part of the minimum stabilization path. It exists so Gemini enhancement suggestions are not ignored, but they only execute if they satisfy the same constraints.

**Execution prompt**

> Read `CLAUDE.md`, `docs/ENGINEERING_STRATEGY.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, and `docs/plans/repo-stabilization-master-plan.md`. Implement Slice 8 only if every earlier slice is complete and green. Only land an enhancement if it replaces weaker code and leaves the repo net-negative in LOC. Candidates are: markdown-dense prompt context replacing current HTML-snippet logic, visual-prominence extraction replacing weaker title heuristics, or deeper declarative payload mapping replacing custom traversal logic. If an enhancement only adds code, do not land it.

Allowed candidates:

- markdown-dense prompt context if it replaces current snippet code with less code
- visual-prominence extraction if it replaces weaker title heuristics with less code
- deeper declarative payload mapping if it deletes custom traversal logic

Blocked by default:

- any additive enhancement that increases LOC
- any new dependency or subsystem introduced only for a speculative score gain

## Recommended Order

1. Slice 1
2. Slice 2
3. Slice 3
4. Slice 4
5. Slice 6
6. Slice 7
7. Slice 5
8. Slice 8

## Done Criteria

The master plan is complete only when all of the following are true:

- both currently failing focused tests are green
- SPA acquisition no longer hangs indefinitely on the current corpus
- production per-URL processing has its own watchdog
- fetch/runtime honors configured retry/backoff before escalating
- selector precedence is deterministic and diagnosable
- hardcoded tenant and timeout rules are removed from generic runtime code
- every mandatory slice finished net-negative in LOC
- no competing master stabilization plan is needed after this file

## Rule For Future Agents

- Do not re-audit the repo before coding unless the code has materially diverged.
- Do not downgrade an audit claim to “tests pass” without inspecting the owning code against repo contracts.
- Execute one slice at a time.
- If a slice reveals a conflicting invariant, update code and tests to preserve the invariant, not the old implementation.
