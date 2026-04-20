# Browser Runtime Remediation Plan

Historical narrow plan. Repo-wide stabilization is now governed by [repo-stabilization-master-plan.md](./repo-stabilization-master-plan.md).

Purpose: reduce browser-render cost, stop dishonest "success" cases on challenge or wrong-content pages, and keep the fix inside the acquisition/browser owner modules defined by [docs/ENGINEERING_STRATEGY.md](../ENGINEERING_STRATEGY.md).

## Source Documents

- Strategy: [docs/ENGINEERING_STRATEGY.md](../ENGINEERING_STRATEGY.md)
- Runtime contract: [docs/INVARIANTS.md](../INVARIANTS.md)
- Current audit: [docs/audits/codex-audit.md](../audits/codex-audit.md)

## Current Evidence

### Code-path cost drivers

- `backend/app/services/acquisition/browser_runtime.py` runs a stacked wait sequence for every browser fetch: `goto(domcontentloaded)` -> fallback `goto(commit)` -> unconditional optimistic sleep -> unconditional `networkidle` wait -> platform readiness wait -> optional detail expansion -> optional traversal. The current defaults budget up to 15s + 3s + 30s + 6s before traversal-specific waits even begin.
- `backend/app/services/config/runtime_settings.py` currently sets `browser_navigation_domcontentloaded_timeout_ms=15000`, `browser_navigation_optimistic_wait_ms=3000`, `browser_navigation_networkidle_timeout_ms=30000`, `listing_readiness_max_wait_ms=6000`, `accordion_expand_wait_ms=500`, `scroll_wait_min_ms=1500`, and `load_more_wait_min_ms=2000`.
- `backend/app/services/crawl_fetch_runtime.py` can render in the browser after HTTP escalation and then the pipeline can trigger another browser render when extraction returns zero records. That duplicates the most expensive path instead of making one accountable acquisition decision.
- `backend/app/services/crawl_fetch_runtime.py` remembers a host as browser-preferred after any returned browser result, including blocked or low-value outcomes. That can push later requests onto the expensive path even when the browser result was not actually good.
- `backend/app/services/acquisition/browser_runtime.py` concatenates full HTML fragments during traversal. That grows payload size and extraction cost linearly with each successful traversal step.

### Artifact evidence from 2026-04-19

- `backend/artifacts/runs/9/pages/189eb1ea4a72fb97.html` and `backend/artifacts/runs/9/pages/b9e6b0f545baf22c.html` are ~50 KB DataDome CAPTCHA pages for AutoZone. The browser path captured challenge HTML, not usable product content.
- `backend/artifacts/runs/1/pages/c7ae2657561502ca.html` is a 49-byte `Empty category` page. That is a technically successful fetch with operationally useless content.
- `backend/artifacts/runs/10/pages/9e4542465ccdb1a9.html` is ~1.8 MB and `backend/artifacts/runs/11/pages/*.html` are ~1.6-1.7 MB Back Market pages. These prove that the current browser path often persists very large DOM snapshots even when extraction only needs a bounded subset of the page.
- `backend/artifacts/runs/3/pages/3e9f8d19fcfe911b.html` is ~963 KB for a KitchenAid listing page with very heavy script payload. The current render path waits on and persists a large client app surface.

### Diagnostics gaps

- `backend/app/services/acquisition/browser_runtime.py` returns only coarse counters such as `network_payload_count`, `navigation_strategy`, `listing_readiness`, and `detail_expansion`. It does not expose phase timings, fallback reason, challenge evidence, HTML size, or whether the browser result was actually extractable.
- `backend/app/services/artifact_store.py` persists only raw HTML. We do not persist a JSON diagnostics artifact or screenshot for browser failures, so artifact review is much weaker than it should be.
- `backend/app/services/publish/metrics.py` reports `browser_attempted` only when the final method is `browser`, so failed or bypassed browser attempts are invisible in URL metrics.

### Parser-efficiency observations

- `selectolax` is already used in the hot extraction paths: `backend/app/services/detail_extractor.py`, `backend/app/services/listing_extractor.py`, and several CSS-oriented adapters already parse with `LexborHTMLParser`.
- That usage is only partially efficient because the core extractors still also build `BeautifulSoup` trees for the same page. Detail extraction does `LexborHTMLParser(html)` and then `BeautifulSoup(cleaned_html, "html.parser")`; listing extraction does the same and also reparses each card fragment with BeautifulSoup.
- The mixed-parser cost is partly justified today because selector fallback and XPath-backed logic still live in BeautifulSoup/lxml helpers. This is not dead dependency weight, but it is still duplicate parse work on the extraction path.
- `parsel` is only used in `backend/app/services/script_text_extractor.py` for script-tag harvesting, and that helper is consumed by `structured_sources.py`. It is narrow and legitimate, but it is not a broad performance win for browser rendering.
- Conclusion: `selectolax` is materially used; `parsel` is narrowly used; neither changes the main browser wait stack. Parser consolidation is applicable as a follow-on latency item, not the first browser-runtime fix.

## Constraints From Strategy And Invariants

- Keep ownership in subsystem 3: `acquisition/*` and `crawl_fetch_runtime.py`.
- Do not add a new cross-cutting manager or policy engine. Refactor the owning modules instead.
- Preserve invariant separation between browser escalation and traversal authorization.
- Preserve observational acquisition facts only. Failures must be reported honestly, not guessed.
- Prefer focused tests around contracts: escalation, traversal, diagnostics, artifact persistence, and browser identity.

## Remediation Slices

### Slice 1: Browser Evidence Contract

Owner:
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/crawl_fetch_runtime.py`
- `backend/app/services/artifact_store.py`
- `backend/app/services/pipeline/core.py`
- `backend/app/services/publish/metrics.py`

Changes:
- Add explicit browser phase timings: navigation, optimistic wait, network-idle wait, readiness wait, expansion, traversal, content serialization, and payload capture.
- Record a first-class `browser_reason` for why the browser ran: platform-required, traversal-required, HTTP escalation, host preference, or empty-extraction retry.
- Record a first-class `browser_outcome` for what happened: usable_content, challenge_page, low_content_shell, navigation_failed, traversal_failed, or render_timeout.
- Persist a JSON diagnostics artifact next to the HTML artifact for every browser attempt.
- Persist a screenshot artifact for browser failures and challenge outcomes.
- Surface `browser_attempted`, `browser_reason`, `browser_outcome`, `html_bytes`, and `phase timings` into URL metrics.

Acceptance criteria:
- A browser attempt that ends on a challenge page is visible as a challenge outcome in diagnostics and metrics.
- Artifact review for one run is possible without opening raw HTML first.
- Failed browser attempts remain visible even when the final returned method is HTTP.

Focused tests:
- browser diagnostics artifact persistence
- screenshot persistence for challenge/failure outcomes
- publish metrics include attempted-browser data even when final method is not `browser`

### Slice 2: Remove Sticky And Duplicate Browser Work

Owner:
- `backend/app/services/crawl_fetch_runtime.py`
- `backend/app/services/pipeline/core.py`

Changes:
- Only remember a host as browser-preferred after a browser result is both unblocked and extractable.
- Require repeated good browser outcomes before a host becomes browser-first; use the existing runtime setting as the threshold instead of a one-hit memory.
- Stop the pipeline from triggering a second browser render when the first acquisition already used the browser.
- Stop the pipeline from triggering a second browser render after a classified challenge or low-content browser outcome.
- Thread the first browser attempt reason and outcome through the empty-extraction retry decision so the retry path is honest.

Acceptance criteria:
- One URL processing path performs at most one browser render unless an explicit retry policy says otherwise.
- A single bad browser page no longer poisons the host into browser-first behavior.
- Empty extraction on a challenge page remains a diagnosable failure, not a trigger for more blind browser work.

Focused tests:
- host preference requires good outcomes
- empty-extraction retry does not re-render after browser acquisition
- challenge outcomes suppress duplicate browser retries

### Slice 3: Fast-Path Browser Readiness

Owner:
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/config/runtime_settings.py`
- `backend/app/services/platform_policy.py`

Changes:
- Replace the current unconditional wait stack with a phased readiness budget:
  - navigate to `domcontentloaded`
  - short extractability probe
  - only wait longer when the page still looks incomplete
  - only wait for `networkidle` on platform-configured surfaces or when traversal is active
- Treat readiness as an early-exit contract, not a mandatory post-navigation tax.
- Make the optimistic wait conditional on missing content signals instead of always paying the full sleep.
- Run detail expansion only when the page is detail-shaped and still missing target content.
- Cap detail expansion by both interaction count and elapsed time budget.
- Add a bounded AOM-assisted expansion path for detail pages: use `page.accessibility.snapshot()` plus role/name-based targeting as a secondary strategy when the cheap DOM-keyword path does not expose enough detail content.
- Keep AOM expansion behind tight limits and diagnostics. It should be a targeted fallback for accordions/tabs, not a new unconditional browser tax.

Acceptance criteria:
- SSR and hybrid pages that are already extractable at `domcontentloaded` do not pay the full browser wait budget.
- Readiness waits remain config-driven and platform-owned.
- Browser diagnostics show which wait phases actually ran and how long they took.

Focused tests:
- browser fetch exits early when detail/listing signals are present after `domcontentloaded`
- `networkidle` is skipped for pages that satisfy the fast-path contract
- expansion is bypassed when the page already exposes structured/detail content
- AOM-assisted expansion finds accessible tabs/accordions that the current keyword DOM scan misses
- AOM expansion obeys interaction/time caps and records why it ran

### Slice 4: Honest Failure Classification

Owner:
- `backend/app/services/acquisition/runtime.py`
- `backend/app/services/acquisition/browser_runtime.py`

Changes:
- Tighten blocker classification so vendor markers alone do not define a blocked page.
- Add challenge-aware classifiers for common anti-bot outcomes seen in current artifacts, including DataDome-style CAPTCHA pages.
- Distinguish low-value shells, empty categories, and genuine rendered content in diagnostics.
- Ensure navigation exceptions and page-close failures become explicit outcomes, not generic retries or empty HTML.

Acceptance criteria:
- AutoZone-style challenge pages are classified as challenge outcomes, not just generic browser HTML.
- Low-content terminal pages are separated from valid rendered detail/listing pages.
- Diagnostics remain observational and source-backed.

Focused tests:
- challenge page fixtures classify correctly
- low-content page fixture classifies correctly
- page-close/navigation failure produces explicit outcome and diagnostics

### Slice 5: Bound Traversal And HTML Growth

Owner:
- `backend/app/services/acquisition/traversal.py`
- `backend/app/services/acquisition/browser_runtime.py`
- `backend/app/services/crawl_engine.py` or extraction owner only if the acquisition contract truly needs widening

Changes:
- Stop concatenating unbounded full-page DOM snapshots for every traversal step.
- Keep traversal evidence as bounded fragments or per-step artifacts, then pass either the final DOM or a deliberate multi-fragment structure to extraction.
- Record traversal HTML bytes and fragment count in diagnostics.
- Preserve listing coverage while capping per-URL artifact and extraction growth.

Acceptance criteria:
- Traversal-heavy listing runs no longer grow HTML size with every page turn without bound.
- Listing extraction still sees all intended traversal coverage.
- Artifact storage remains reviewable without producing multi-megabyte HTML by default.

Focused tests:
- paginate/scroll traversal returns bounded HTML payloads
- multi-page listing extraction still yields records from all collected steps
- diagnostics expose traversal fragment count and total bytes

## Follow-on Latency Item: Extraction Parser Consolidation

Why it is not in the first execution slices:
- The browser-render wait stack is the larger and more dishonest cost center.
- The current mixed parser setup has a clear ownership boundary today: `selectolax` for CSS-first extraction, BeautifulSoup/lxml for selector fallback, XPath, and compatibility paths.
- Broad parser churn during the browser fix would raise regression risk in extraction.

Applicable follow-up:
- After the browser slices land, profile detail/listing extraction and reduce duplicate DOM parsing where the BeautifulSoup copy is only supporting CSS reads that `selectolax` already handles.
- Keep `parsel` narrow unless a concrete script-extraction hotspot proves otherwise.
- Do not introduce a generic parser abstraction layer.

## Execution Order

1. Slice 1 first. Without better evidence we cannot tune the browser path safely.
2. Slice 2 second. It cuts duplicate cost and prevents bad browser outcomes from biasing future requests.
3. Slice 3 third. Once evidence exists, shorten the success path.
4. Slice 4 fourth. Tighten blocker honesty using the now-richer artifacts.
5. Slice 5 last. This is the largest contract touch and should only land after earlier slices expose the real traversal payload shape.

## Verification Plan

- Unit tests around `acquisition/runtime.py`, `acquisition/browser_runtime.py`, `crawl_fetch_runtime.py`, `pipeline/core.py`, and `publish/metrics.py`
- Artifact-level regression checks against the 2026-04-19 browser outputs in `backend/artifacts/runs/*`
- Focused pytest slices:
  - `backend/tests/services/test_crawl_fetch_runtime.py`
  - `backend/tests/services/test_browser_expansion_runtime.py`
  - `backend/tests/services/test_pipeline_core.py`
  - add dedicated browser diagnostics and challenge classification tests
- Re-run a small canary set from `TEST_SITES.md`:
  - AutoZone detail
  - Back Market listing/detail
  - KitchenAid listing
  - at least one low-noise sandbox browser listing

## Definition Of Done

- Browser attempts are measurable by reason, phase timing, and outcome.
- The system does not perform redundant browser renders for one URL.
- Challenge pages and low-value shells are classified honestly and leave reviewable artifacts.
- Successful browser acquisitions pay materially less wait time on already-rendered pages.
- The fix stays inside the acquisition/browser owner modules and updates canonical docs only if contracts change.
