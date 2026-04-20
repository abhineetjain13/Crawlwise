# SPA Acquisition Improvement Plan

## Objective

Improve SPA acquisition so that:

1. SPA listings and details do not hang indefinitely.
2. Pure client-rendered SPAs are escalated to browser acquisition earlier and more reliably.
3. SPA failures are classified correctly instead of being counted as success.
4. Stable SPA coverage improves without overfitting to broken demo sites.

## Architecture Grounding

This plan is constrained by `docs/ENGINEERING_STRATEGY.md`.

Relevant rules from that doc:

- `pipeline/core.py` owns per-URL orchestration, not extraction internals.
- `crawl_fetch_runtime.py` owns fetch/runtime behavior, not record semantics.
- `publish/*` owns verdict, metrics, and commit metadata.
- Config and platform-specific behavior belong in `app/services/config/*` and `platform_policy.py`, not in generic runtime bodies.
- Do not create parallel systems because an existing module is awkward.

That means this plan must not:

- add a second SPA orchestration flow outside `pipeline/core.py` and `_batch_runtime.py`
- add SPA-specific extraction behavior in the acquisition layer
- add site-specific branches inside generic runtime code when config can own them
- create a second acceptance/runtime pipeline instead of extending an existing owner

## Evidence Reviewed

Artifacts reviewed:

- `backend/artifacts/MASTER_FAILURE_MODE_REPORT_100_SITES.md`
- `backend/artifacts/FAILURE_MODE_REPORT_20_SPA_SITES_CORRECTED.md`
- `backend/artifacts/FAILURE_MODE_REPORT_20_MORE_SPA_SITES.md`
- `backend/artifacts/20_spa_sites_smoke_test.log`
- `backend/artifacts/20_more_spa_sites_smoke_test.log`

Relevant runtime code reviewed:

- `backend/app/services/_batch_runtime.py`
- `backend/app/services/pipeline/core.py`
- `backend/app/services/crawl_fetch_runtime.py`
- `backend/app/services/acquisition/runtime.py`
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/platform_policy.py`
- `backend/app/services/config/platforms.json`
- `backend/run_test_sites_acceptance.py`
- `backend/harness_support.py`

Additional architecture and ownership references reviewed:

- `docs/ENGINEERING_STRATEGY.md`
- `docs/backend-architecture.md`
- `backend/app/services/selectors_runtime.py`
- `backend/app/services/publish/__init__.py`
- `backend/app/services/pipeline/persistence.py`

## What The Artifacts Say

The SPA failures split into four buckets:

1. Pure SPA shells with no usable HTML.
   Examples: `next-js-commerce-mu`, `ecommerce-demo-kappa`, `angular-ecommerce-demo`, `vue-commerce-demo`, `headless-commerce-demo`, `shopify-headless-demo`, `nuxt-shopify-demo`, `gatsby-shopify-demo`, `react-shopify-demo`.
   Pattern: 3.7KB to 4.2KB HTML, `listing_extraction_empty`, no meaningful cards.

2. SPA or client-route URLs returning server-side 404/minimal shells.
   Examples: `medusa.express/products`, several Vercel `/products` routes.
   Pattern: non-SSR route looks dead from HTTP, but the failure mode is still SPA-specific.

3. False positives from placeholder or error pages.
   Examples: `"Edit"`, `"All Products"`, `"Page Not Found"`, `"404"`, `"Sylius Demo"`.

4. Known-good controls.
   Browser-rendered success: `practicesoftwaretesting.com/#/`, `practicesoftwaretesting.com/#/shop`, `demo.spreecommerce.org/products`.
   SSR success: `demo.saleor.io/products`.

Important nuance:

- The artifact harness already wraps acquisition in `asyncio.wait_for(...)`, so the reports show bounded per-site runs.
- The production batch runtime does not enforce the same outer per-URL timeout.

That means the artifact corpus is useful for diagnosing SPA detection/readiness problems, but the user's "hang indefinitely" symptom is more consistent with the production runtime path than with the smoke harness.

## Existing Paths And Why They Matter

The repo already has multiple entrypaths with different owners. They should not be collapsed casually, but they also should not each grow their own SPA logic.

1. Production crawl path.
   `crawl_service.py` -> `_batch_runtime.py` -> `pipeline/core.py` -> `acquisition/acquirer.py` -> `crawl_fetch_runtime.py`
   This is the canonical runtime path for real crawl behavior.

2. Selector/operator preview path.
   `selectors_runtime.py` calls `fetch_page(...)` directly for preview/test workflows.
   This is an operator tool, not a second crawl pipeline.

3. Smoke and harness tools.
   `run_acquire_smoke.py`, `run_extraction_smoke.py`, and `run_test_sites_acceptance.py`
   These are diagnostics and corpus runners, not production orchestrators.

The plan below is therefore grounded on one rule:

- runtime behavior changes belong in the production owners
- harnesses should only expose those behaviors, not re-implement them

## Code-Level Issues

### 1. No hard per-URL timeout in the production batch path

- `backend/app/models/crawl_settings.py` exposes `url_timeout_seconds()`.
- `backend/app/services/config/runtime_settings.py` exposes `url_process_timeout_seconds`.
- `backend/app/services/_batch_runtime.py` calls `_process_single_url(...)` directly with no `asyncio.wait_for(...)`.

Impact:

- A stuck Playwright call, traversal loop, payload capture close, or browser shutdown can stall a run indefinitely.
- This is an orchestration concern, so the fix belongs in `_batch_runtime.py` / `pipeline/core.py`, not in the smoke harness.

### 2. Non-retryable 404 returns too early for SPA-like shells

- In `backend/app/services/crawl_fetch_runtime.py`, `fetch_page()` returns immediately on `is_non_retryable_http_status(result.status_code)` before browser escalation logic runs.

Impact:

- Client-routed SPAs that return a minimal 404 shell on `/products` never get first-class fetch-layer browser escalation.
- Recovery depends on later pipeline behavior and on which runner path is being used.

### 3. Traversal readiness policy is regressed

- `backend/app/services/platform_policy.py::resolve_browser_readiness_policy()` ignores `traversal_active`.
- `backend/tests/services/test_platform_detection.py` already expects traversal to require network idle / traversal readiness.
- Current targeted test result: `1 failed, 4 passed` in `tests/services/test_platform_detection.py`.

Impact:

- SPA listings using scroll/load-more/paginate can enter browser traversal without the intended readiness gate.
- This increases both false empties and unstable long waits.

### 4. Commerce SPA browser-first policy is mostly heuristic, not explicit

- `backend/app/services/config/platforms.json` contains browser/readiness rules mainly for ATS platforms.
- Commerce SPAs rely on generic shell heuristics in `backend/app/services/acquisition/runtime.py`.

Impact:

- Angular/React/Vue commerce SPAs are handled inconsistently.
- Stable known-good SPA domains are not promoted to deterministic browser-first behavior.
- Per `ENGINEERING_STRATEGY.md`, this should be solved in config/policy ownership, not by adding ad hoc domain branches in `crawl_fetch_runtime.py`.

### 5. Runtime timeout knobs are exposed but weakly enforced

Configured knobs exist for:

- `acquisition_attempt_timeout_seconds`
- `browser_render_timeout_seconds`
- `url_process_timeout_seconds`
- browser context/page/close timeouts

But the reviewed call path does not enforce them as a single end-to-end watchdog.

Impact:

- Operators can believe SPA runs are bounded when the effective runtime still depends on nested Playwright waits and cooperative exits.

### 6. Failure classification still hides real SPA problems

- `backend/harness_support.py::classify_failure_mode()` returns `"success"` whenever `result["ok"]` is truthy.
- The master report already calls out this measurement problem.

Impact:

- Placeholder pages and server error pages pollute SPA success metrics.
- Improvement work is harder to validate because the KPI is noisy.

### 7. The acceptance harness is not the full production pipeline

- `backend/run_test_sites_acceptance.py` runs `acquire(...)`, adapter, and extractor directly.
- It does not exercise the full pipeline flow in `backend/app/services/pipeline/core.py`, including the later empty-extraction browser retry.

Impact:

- Artifact failures are directionally useful, but they are not a perfect proxy for production behavior.

## Duplicate-Path Audit Result

I did audit the codebase for overlapping feature paths before revising this plan.

What already exists:

- one production orchestration path
- one fetch/runtime owner
- one publish/metrics owner
- separate smoke tools for acquisition-only, extraction-only, and acceptance diagnostics

What is at risk of duplication if implemented carelessly:

- adding SPA retry/escalation logic in `_batch_runtime.py` instead of keeping it in `crawl_fetch_runtime.py` and `platform_policy.py`
- adding a second timeout system inside browser internals instead of enforcing the user-visible budget at orchestration level
- adding a new standalone pipeline smoke runner instead of extending `run_test_sites_acceptance.py`
- adding site-specific SPA hacks in generic runtime files instead of config/policy

The revised plan below avoids those duplicate-path mistakes.

## Improvement Plan

### Slice 1: Add a hard SPA-safe per-URL watchdog

Owner modules:

- `backend/app/services/_batch_runtime.py`
- `backend/app/services/pipeline/core.py`
- `backend/app/models/crawl_settings.py`
- `backend/app/services/pipeline/persistence.py`
- `backend/app/services/publish/*`

Changes:

1. Wrap `_process_single_url(...)` in `asyncio.wait_for(...)` using `run.settings_view.url_timeout_seconds()`.
2. On timeout, emit a terminal verdict and structured diagnostics:
   - current stage
   - current URL
   - browser attempted
   - last known browser phase timings
   - timeout source: `url_process_timeout`
3. Best-effort cancel and close the active browser page/context/runtime for that URL.
4. Persist timeout artifacts the same way low-content/challenge artifacts are persisted.

Non-goal:

- do not add a second timeout policy path in the harness scripts
- do not move orchestration timeout ownership into `crawl_fetch_runtime.py`

Acceptance criteria:

- A stuck SPA URL cannot exceed configured timeout by more than a small cleanup buffer.
- Timed-out URLs fail closed with diagnostics instead of leaving the run in `running`.

### Slice 2: Escalate SPA shells before the fetch layer bails on 404

Owner modules:

- `backend/app/services/crawl_fetch_runtime.py`
- `backend/app/services/acquisition/runtime.py`
- `backend/app/services/platform_policy.py`

Changes:

1. Add a dedicated SPA-shell detector for listing/detail pages:
   - root/app container present
   - high script count
   - very low visible text
   - SPA markers such as `#__next`, `id="root"`, `id="app"`, `ng-version`, `data-reactroot`, `__NUXT__`
2. Allow browser escalation for `404`/`410` responses when the HTML still looks like a client-rendered SPA shell.
3. Record a distinct browser reason such as `spa-shell-404` or `spa-shell-low-content`.

Non-goal:

- do not add SPA-specific fallback branches in `_batch_runtime.py`
- do not add domain-specific `if "foo" in url` logic to generic runtime bodies unless promoted through platform config/policy

Acceptance criteria:

- The known SPA shell failures from the artifacts trigger browser acquisition in the fetch path instead of returning immediately from HTTP.
- Normal real 404 pages without SPA shell signals still fail fast without unnecessary browser work.

### Slice 3: Restore and tighten SPA readiness for traversal flows

Owner modules:

- `backend/app/services/platform_policy.py`
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/acquisition/traversal.py`

Changes:

1. Fix `resolve_browser_readiness_policy()` so `traversal_active=True` requires readiness behavior again.
2. For SPA listings, treat readiness as a bounded race:
   - card count growth
   - configured readiness selectors
   - optimistic wait
   - bounded network idle
3. Never let SPA readiness depend on unbounded network quiescence.
4. Record explicit stop reasons for:
   - `spa_readiness_timeout`
   - `networkidle_timed_out`
   - `traversal_no_progress`

Non-goal:

- do not create a second traversal-readiness mechanism outside `platform_policy.py` + `browser_runtime.py`

Acceptance criteria:

- The existing failing traversal-readiness test passes.
- SPA listing pages with polling/XHR traffic do not sit waiting for indefinite quiescence.

### Slice 4: Promote stable SPA browser-first rules and keep broken demos out of the main KPI

Owner modules:

- `backend/app/services/config/platforms.json`
- `backend/app/services/platform_policy.py`
- `TEST_SITES.md`
- `backend/run_test_sites_acceptance.py`

Changes:

1. Add explicit browser-first/readiness config for stable SPA controls that are part of the corpus.
2. Split the SPA corpus into:
   - stable regression canaries
   - adversarial / flaky / known-bad demos
3. Keep Vercel demo routes as negative tests for "fail fast and classify correctly", not as headline success KPIs.

Stable canaries from the current artifact set:

- `https://practicesoftwaretesting.com/#/`
- `https://practicesoftwaretesting.com/#/shop`
- `https://demo.spreecommerce.org/products`
- `https://demo.saleor.io/products`

Acceptance criteria:

- Stable SPA canaries get deterministic browser or SSR handling.
- Broken demo routes no longer dominate the main SPA success number.

### Slice 5: Fix measurement so SPA improvements are visible

Owner modules:

- `backend/harness_support.py`
- `backend/run_test_sites_acceptance.py`
- `backend/app/services/publish/*` if verdict/report fields need alignment

Changes:

1. Do not classify any non-empty record set as success by default.
2. Reject placeholder/error signatures such as:
   - `404`
   - `Page Not Found`
   - `Edit`
   - `All Products`
   - site-name-only titles with no card/detail evidence
3. Add SPA-specific report buckets:
   - `spa_shell_404`
   - `spa_shell_low_content`
   - `spa_readiness_timeout`
   - `client_route_unresolved`

Acceptance criteria:

- The acceptance report stops counting placeholder/error pages as SPA success.
- Post-fix metrics can distinguish "browser never used", "browser used but timed out", and "browser rendered but content was still junk".

### Slice 6: Align the smoke harness with the production path

Owner modules:

- `backend/run_test_sites_acceptance.py`
- `backend/harness_support.py`

Changes:

1. Extend `run_test_sites_acceptance.py` with an explicit mode switch so it can run:
   - acquire-only diagnostics
   - production-pipeline diagnostics through the existing pipeline owner
2. Keep `run_acquire_smoke.py` as the fast transport diagnostic tool.
3. Report both:
   - acquisition outcome
   - pipeline outcome

Non-goal:

- do not add a brand-new standalone runner when the existing acceptance runner can absorb the mode cleanly
- do not let harness code become a second implementation of SPA retry, readiness, or verdict rules

Acceptance criteria:

- Artifact interpretation becomes consistent with the real runtime.
- SPA regressions can be attributed to fetch, browser readiness, traversal, or extraction instead of being collapsed together.

## Test Plan

Add or extend tests for:

1. `tests/services/test_batch_runtime.py`
   - run-level URL timeout produces terminal failure and logs
2. `tests/services/test_crawl_fetch_runtime.py`
   - 404 SPA shell escalates to browser
   - real 404 page does not escalate
3. `tests/services/test_platform_detection.py`
   - traversal readiness policy passes again
4. `tests/services/test_browser_expansion_runtime.py`
   - SPA readiness exits on bounded policy, not indefinite wait
5. `tests/test_harness_support.py`
   - error/placeholder pages are not counted as success
6. `tests/services/test_selector_pipeline_integration.py`
   - selector/operator tooling still uses the shared fetch/runtime owner without gaining a separate SPA policy path

Smoke validation after implementation:

1. Stable SPA canaries:
   - `practicesoftwaretesting.com/#/`
   - `practicesoftwaretesting.com/#/shop`
   - `demo.spreecommerce.org/products`
   - `demo.saleor.io/products`
2. Adversarial SPA shells:
   - `medusa.express/products`
   - `next-js-commerce-mu.vercel.app/products`
   - `vue-commerce-demo.vercel.app/products`
   - `react-shopify-demo.vercel.app/products`

Expected post-fix behavior:

- Stable canaries succeed.
- Broken/demo routes fail fast with correct classification.
- No SPA URL can hang indefinitely.

## Priority Order

1. Slice 1: hard per-URL watchdog
2. Slice 2: early SPA-shell browser escalation
3. Slice 3: traversal/readiness fix
4. Slice 5: measurement cleanup
5. Slice 6: harness alignment
6. Slice 4: corpus hardening and browser-first registry cleanup

## Risks And Guardrails

1. Over-escalating normal 404s to browser will waste time.
   Guardrail: only escalate 404s when SPA shell signals are strong.

2. Network idle is a bad universal readiness signal for SPAs.
   Guardrail: race it against selector/card growth and keep it strictly bounded.

3. Vercel demos are noisy and sometimes genuinely broken.
   Guardrail: use them as adversarial classification tests, not primary success targets.

4. Timeout cleanup can leak browser contexts if cancellation is incomplete.
   Guardrail: explicit best-effort page/context/runtime teardown plus tests that assert cleanup behavior.

## Summary

The highest-confidence root cause for "SPA hangs indefinitely" is not the artifact harness itself; it is the production runtime path missing an enforced outer URL timeout while SPA browser readiness and traversal remain partially heuristic. The first implementation milestone should therefore be a hard per-URL watchdog, followed immediately by earlier SPA-shell browser escalation and the traversal-readiness regression fix.

## Answer To The Duplicate-Path Concern

The initial plan did audit the key owner modules, but it was not explicit enough about the ownership constraints from `ENGINEERING_STRATEGY.md`. The main correction is this:

- SPA timeout belongs to orchestration.
- SPA detection/escalation belongs to fetch/runtime policy.
- SPA readiness belongs to browser runtime plus platform policy.
- Verdict and diagnostics belong to publish/persistence.
- Harnesses should expose those behaviors, not implement their own versions.

That is the grounded version of the plan, and it avoids adding yet another path for the same feature.
