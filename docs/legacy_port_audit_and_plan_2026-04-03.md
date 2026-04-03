# Legacy Repo Audit And Implementation Plan

Date: 2026-04-03

## Scope

This audit compares the current repo at `C:\Projects\pre_poc_ai_crawler` against the older repo at `C:\Users\abhij\Downloads\pre_poc_ai_crawler`.

Goal: identify concrete ideas worth porting from the older repo to improve the current crawl pipeline in three areas:

1. coverage on normal to complex sites
2. robustness against simple anti-bot systems, especially Akamai-style blocks
3. bypass of simple initial-load friction such as cookie banners and lightweight interstitials

This document is code-grounded. It is not a rewrite proposal.

## Executive Summary

The current repo has improved materially since the earlier Foot Locker audit. It now has:

- JSON-first acquisition and extraction
- blocked-page detection
- a structured-data-first listing extractor
- a listing fallback guard that no longer silently downgrades failed listings into fake detail successes
- some platform adapters already ported into the main pipeline

The older repo is still substantially stronger in one architectural area: browser-runtime sophistication.

That older system had a separate robustness layer around:

- stealthier browser launch and context configuration
- stronger HTTP fallback and retry policy
- host-aware session reuse
- challenge assessment and wait loops
- origin warming before target navigation
- requested-field-driven semantic expansion of hidden content
- richer discovery of JSON blobs, hydrated state, and intercepted APIs

The largest gap is not any single selector. The current pipeline still treats the browser mainly as a simple HTML renderer and XHR sniffer. The old repo treated the browser as an active page-local acquisition environment.

One important clarification: true shadow DOM traversal is not implemented in either repo. The old repo uses the term "shadow selectors" in memory/UI language, but that is not actual shadow-root traversal support. That capability must be designed fresh.

## Capability Matrix

| Capability | Current repo | Legacy repo | Recommendation |
| --- | --- | --- | --- |
| JSON-first acquisition | Yes | Yes | Keep current path |
| Structured listing extraction | Yes | Yes | Keep and deepen |
| Generic hydrated-state discovery | Partial | Stronger | Port and expand |
| Requested fields drive browser actions | No | Yes | Port |
| Semantic section/spec extraction | No | Yes | Port |
| Challenge wait loop | No | Yes | Port |
| Origin warming | No | Yes | Port |
| Host-aware stealth preference | No | Yes | Port |
| Shared HTTP client with stealth retry | No | Yes | Port |
| Persistent browser pool | No | Yes | Port |
| Consent handling | Basic | Stronger | Port and extend |
| Shadow DOM traversal | No | No | New design |
| Frame-aware selector execution | No | Partial/manual | New design |

## Comparison Baseline

### Current repo strengths

- `backend/app/services/crawl_service.py`
  - clean acquisition -> discovery -> extraction flow
  - explicit blocked verdicts
  - explicit listing failure verdicts
- `backend/app/services/acquisition/acquirer.py`
  - JSON response detection
  - artifact persistence for HTML and JSON
- `backend/app/services/acquisition/blocked_detector.py`
  - deterministic challenge/block signatures
- `backend/app/services/discover/service.py`
  - discovery manifest with adapter, network, `__NEXT_DATA__`, JSON-LD, microdata, tables
- `backend/app/services/extract/listing_extractor.py`
  - structured-data-first listing extraction
- `backend/app/services/extract/json_extractor.py`
  - direct extraction from JSON APIs

### Legacy repo strengths worth mining

- `backend/app/services/browser_utils.py`
  - stealth Playwright setup
  - richer cookie consent handling
  - locale/timezone realism
  - cookie persistence helpers
- `backend/app/services/providers/http_provider.py`
  - shared HTTP client
  - stealth TLS retry via `curl_cffi`
  - host memory for preferring stealth on problem hosts
  - rate limiting and cache
  - speculative stealth detail fetch
- `backend/app/services/providers/browser_provider.py`
  - persistent browser pool
  - graceful HTTP fallback on pool exhaustion
- `backend/app/services/spa_crawler_service.py`
  - challenge assessment and wait loop
  - origin warm-up
  - bounded load-more, scroll, and pagination
  - intercepted JSON processing
  - richer browser-page extraction
- `backend/app/services/semantic_browser_helpers.py`
  - safe semantic expansion of accordions, tabs, details, and "read more" controls
- `backend/app/services/semantic_detail_extractor.py`
  - richer extraction of section/specification content
- `backend/app/services/requested_field_policy.py`
  - requested-field intent and coverage logic
- `backend/app/services/discovery.py`
  - broader discovery heuristics for structured blobs and page-type inference

## Audit Area 1: Coverage On Normal To Complex Sites

### Current state

The current repo is solid on simple and moderately structured pages:

- adapter records are honored first
- network payloads are captured from Playwright responses
- `__NEXT_DATA__`, JSON-LD, microdata, and tables are discovered
- listing extraction prefers structured sources before DOM cards
- detail extraction can include user-requested additional fields in the target field set

But coverage stops short on complex pages because the pipeline does not actively reveal or traverse hidden content.

### Concrete gaps

#### 1. Additional fields do not currently drive active hidden-content recovery

`backend/app/services/crawl_service.py` passes `additional_fields` into both listing and detail extraction. But in the current repo:

- listing extraction passes `target_fields` into `extract_listing_records(...)`
- `_extract_from_card(...)` ignores that parameter entirely
- detail extraction uses `additional_fields` only as extra field names to search in already-visible sources

So today, "additional fields" mostly means "search harder in the visible HTML and discovered blobs." It does not mean:

- expand accordions
- click tabs
- open `<details>`
- reveal hidden descriptions/specifications
- inspect collapsed JS-rendered panels

This is the main functional gap for PDP enrichment and richer jobs detail extraction.

#### 2. Discovery is still too narrow for modern hydrated apps

`backend/app/services/discover/service.py` currently discovers:

- adapter data
- intercepted network payloads
- `__NEXT_DATA__`
- JSON-LD
- microdata/RDFa
- tables

It does not yet have generalized discovery for:

- `__NUXT__`
- `__APOLLO_STATE__`
- `window.__INITIAL_STATE__`
- Redux/Zustand/store blobs embedded in inline scripts
- JSON script tags without `application/ld+json`
- framework-specific hydration payloads
- inline JS assignments containing records

The old repo's `discovery.py` is materially broader here.

#### 3. Selector execution is shallow

Current selector execution in `backend/app/services/extract/service.py` supports:

- contract-level XPath and regex
- saved CSS selectors only
- simple DOM fallbacks

It does not support:

- saved XPath selectors
- frame-scoped selectors
- selector capability metadata
- shadow-root traversal
- chained selectors that cross document boundaries

This is a real architectural limit, not just missing patterns.

#### 4. Listing extraction still tops out at visible-card heuristics

The current listing extractor is much better than before, but its DOM fallback is still a static-card model:

- common selector lookup
- sibling-group autodetection
- simple text/link/image/price extraction

That works for many sites, but it loses on:

- component-heavy SPAs
- split cards where content lives outside the anchor node
- nested lazy media
- "data in HTML but not obvious in visible text" patterns
- cards whose fields are assembled from multiple elements or inline JSON

The old `spa_crawler_service.py` had more aggressive page-local extraction and intercepted-data reconciliation.

#### 5. Shadow DOM support is absent in both repos

This needs to be stated explicitly:

- the legacy repo does not implement actual shadow-root traversal
- the current repo does not implement actual shadow-root traversal
- "shadow selectors" in the old docs/UI means selector memory, not browser traversal through shadow roots

For your stated goal, this is net-new design work.

### Legacy ideas worth porting

#### Requested-field-driven semantic expansion

The strongest portable idea from the old repo is the pairing of:

- `requested_field_policy.py`
- `semantic_browser_helpers.py`
- `semantic_detail_extractor.py`

That combination lets the system:

- infer what the user actually wants from selected fields
- expand relevant hidden UI sections
- extract sections/specifications after expansion
- measure requested-field coverage

That is exactly the missing bridge between "additional fields" in the UI and actual richer extraction behavior.

#### Page-local semantic detail harvesting

The legacy semantic detail path extracted:

- section text
- specification key/value pairs
- label/value patterns
- table-driven details
- promoted semantic fields

This should be added to the current detail pipeline before the system decides a detail record is "good enough."

### Recommendations

#### P0

- Add a requested-field intent layer to the current repo.
- Add a browser-side semantic expansion stage for detail pages and optionally listing cards.
- Add semantic detail extraction after expansion and before final publish.

#### P1

- Expand discovery to include common hydrated-state and inline-JSON patterns beyond `__NEXT_DATA__`.
- Let network payload ranking and inline script extraction feed both listing and detail extraction.

#### P1

- Extend selector storage and execution to support capability metadata:
  - `css`
  - `xpath`
  - `shadow_css`
  - `shadow_path`
  - `frame_scope`
  - `page_kind`

#### P2

- Implement true shadow DOM traversal in the browser runtime.
- Add frame-aware extraction support.

## Audit Area 2: Robustness Against Simple Akamai And Similar Bot Protection

### Current state

The current repo has the beginning of a robustness model, but it is still mostly reactive:

- `backend/app/services/acquisition/http_client.py`
  - single `curl_cffi` fetch with `chrome110`
- `backend/app/services/acquisition/acquirer.py`
  - simple waterfall: HTTP first, Playwright fallback
  - fallback based on short/JS-gated HTML
- `backend/app/services/acquisition/browser_client.py`
  - browser launch
  - cookie load/save
  - cookie acceptance
  - network interception
- `backend/app/services/acquisition/blocked_detector.py`
  - post-fetch block detection

This is useful, but it is not yet a robust acquisition strategy.

### Concrete gaps

#### 1. Anti-bot handling is mostly post-failure detection

The current pipeline detects blocked pages after acquisition. It does not do much to avoid blocks before or during acquisition.

Missing pieces relative to the old repo:

- host-aware stealth preference
- retry by block class
- origin warming
- challenge wait loop
- browser launch fallback strategy
- realistic locale/timezone tuning
- pool-based browser reuse
- speculative stealth fetch for sensitive detail pages

#### 2. Browser runtime is too stateless

The current browser client launches a fresh browser, creates a generic context, loads cookies, navigates once, maybe scrolls, and returns HTML.

Compared with the old repo, it is missing:

- stealth plugin application
- anti-automation launch args
- locale/timezone adaptation by host
- persistent browser pool
- bounded retries for transient browser failures
- host/session reuse beyond cookie files

That matters because simple Akamai-style systems often care less about "did you use Playwright" and more about whether the session behaves like a stable browser.

#### 3. HTTP fallback is too simple

The old `http_provider.py` did much more:

- shared `httpx` client
- TLS impersonation retry
- retry on `247`, `401`, `403`, `429`
- preferred stealth hosts with TTL
- rate limiting
- fetch cache
- speculative stealth detail fetch

The current `http_client.py` is a thin wrapper around one `curl_cffi` request.

That simplicity is the clearest place where the old repo is still ahead.

### Legacy ideas worth porting

#### Host-aware stealth policy

The old repo remembered which hosts tended to need stealth TLS. That is higher value than globally overusing stealth fetches.

Recommended port:

- introduce host-level acquisition memory
- remember:
  - successful provider
  - challenge signals
  - stealth preference
  - last successful mode
  - cookie/session usefulness

#### Challenge assessment and wait loop

The logic in `spa_crawler_service.py` around `_assess_challenge_signals(...)` and `_wait_for_challenge_resolution(...)` is one of the most valuable portable ideas.

That logic distinguishes:

- hard blocks
- interactive challenges worth waiting through
- weak signals that should not kill the run

The current blocked detector is good as a verdict mechanism, but not sufficient as an acquisition policy mechanism.

#### Origin warming

The old repo explicitly visited the site origin before the target URL on some runs, paused briefly, and performed small interactions. That is often enough to get past lightweight session checks and cookie/session setup pages.

This is directly relevant to simple Akamai-protected commerce sites.

### Recommendations

#### P0

- Replace the thin HTTP client with a richer provider patterned after the old `http_provider.py`.
- Add host-aware stealth preference memory and retry policy.
- Rework browser acquisition into a reusable runtime instead of one-shot browser launches.

#### P0

- Add challenge classification into the browser acquisition path:
  - `none`
  - `weak_signal`
  - `interactive_wait`
  - `hard_block`

#### P1

- Add origin warming before target navigation on hosts with known challenge/session friction.
- Add speculative stealth detail fetch for hosts that block detail pages more often than listing pages.

#### P1

- Add persistent browser pools for worker/runtime paths, with graceful fallback on exhaustion.

## Audit Area 3: Bypass Of Cookie Acceptance And Other Simple Initial-Load Challenges

### Current state

The current repo does support basic cookie dismissal:

- selector list in `backend/app/services/acquisition/browser_client.py`
- cookie load/save by domain
- `Escape` fallback

That covers a reasonable chunk of commodity consent banners.

### Concrete gaps

#### 1. Consent handling is too narrow

Compared with the old repo's `browser_utils.py`, the current selector set is smaller and the handling is less integrated into the wider acquisition flow.

Missing behaviors:

- multiple consent passes
- timing tied to challenge resolution
- host-aware reuse of good selectors
- modal/banner clearing beyond pure cookie consent

#### 2. No generalized interaction loop for lightweight interstitials

The current browser path can scroll or click load-more in explicit advanced modes, but it does not have a general page-local completion loop that can:

- wait for challenge resolution
- dismiss cookie banners
- expand hidden sections
- retry modal clearing
- then continue extraction

The old `spa_crawler_service.py` effectively had this.

### Legacy ideas worth porting

#### Unified browser completion phase

The old repo's browser flow did not treat consent dismissal as a separate one-off utility. It combined:

- navigation
- challenge waiting
- cookie dismissal
- section expansion
- scroll/load-more

That should be pulled into the current browser runtime as an explicit phase.

### Recommendations

#### P0

- Introduce a page-local browser completion orchestrator in the current repo:
  - settle initial nav
  - assess challenges
  - wait when appropriate
  - dismiss consent
  - clear obvious overlays
  - expand requested-field-relevant hidden content
  - then extract

#### P1

- Persist successful consent selectors or overlay-clear patterns by host/path family.

## Architecture Issues In The Current System

### 1. Browser acquisition is a utility, not a first-class subsystem

Today the browser path is basically "Playwright fallback with optional scroll." That architecture is too weak for:

- JS-heavy pages
- mild anti-bot friction
- hidden-content extraction
- page-local interactive recovery

Recommendation:

- promote browser acquisition into a dedicated subsystem with:
  - policy
  - host memory
  - challenge classification
  - reusable completion stages
  - diagnostics

### 2. Additional fields are not behavior-driving

The UI concept of additional/requested fields is stronger than the current backend behavior. The current backend searches for more keys, but does not actively reveal more content.

Recommendation:

- make requested fields drive browser actions, semantic extraction, and coverage scoring

### 3. Discovery is still too HTML-centric

The current manifest is clean but narrow. Modern sites often expose the best data in hydrated app state or inline JS assignments rather than JSON-LD and visible DOM.

Recommendation:

- expand discovery into a generalized "structured source discovery" module rather than keeping it mostly to `__NEXT_DATA__` and JSON-LD

### 4. Selector storage is underpowered for modern pages

Current selector reuse can help simple sites, but it cannot express:

- frame scope
- shadow scope
- traversal chains
- extraction mode
- host/path-family constraints

Recommendation:

- redesign selector memory before claiming shadow-selector capability in the UI or docs

### 5. Blocked-page detection is reactive but not policy-driven

The current detector is useful for verdicting, but not enough for avoidance.

Recommendation:

- move block/challenge detection earlier into the acquisition policy loop

### 6. The old repo's strongest ideas should not be ported as a monolith

The old `spa_crawler_service.py` contains valuable behaviors, but it is too large and too entangled to copy directly.

Recommendation:

- port behavior, not file structure
- extract the portable concepts into smaller modules inside the current pipeline

## Implementation Plan

## Phase 0: Baseline And Regression Corpus

### Goal

Create a stable evaluation harness before porting behavior.

### Deliverables

- curated regression set from `TEST_SITES.md`
- explicit categories:
  - simple commerce listing
  - complex commerce listing
  - commerce detail
  - simple jobs listing
  - ATS jobs listing
  - JS-heavy jobs detail
  - anti-bot/light challenge
  - cookie/interstitial-heavy
- metrics captured per run:
  - acquisition method
  - blocked state
  - record count
  - requested-field coverage
  - publish verdict
  - visible-vs-final quality notes

### Current repo files to touch

- `backend/app/services/crawl_service.py`
- test harness or scripts under `scripts/` or `backend/tests/`
- docs for the regression matrix

### Acceptance

- every phase below can be judged against the same corpus

## Phase 1: Acquisition Hardening

### Goal

Bring the current acquisition layer up to parity with the best parts of the old HTTP and browser providers.

### Deliverables

- replace thin `http_client.py` semantics with a richer provider layer
- stealth TLS retry policy
- shared HTTP client
- host-level stealth preference memory
- browser launch fallback
- realistic browser args
- realistic locale/timezone defaults
- persistent browser pool for worker execution

### Current repo files to touch

- `backend/app/services/acquisition/http_client.py`
- `backend/app/services/acquisition/acquirer.py`
- `backend/app/services/acquisition/browser_client.py`
- config/settings and any host-memory store

### Acceptance

- fewer immediate 403/429 failures on known difficult hosts
- repeated crawls on the same host show better acquisition consistency
- no regression on simple HTTP-friendly sites

## Phase 2: Challenge And Initial-Load Orchestration

### Goal

Move from reactive block detection to policy-driven initial page completion.

### Deliverables

- challenge assessor
- challenge wait loop
- origin warming
- consent and overlay clearing pass
- browser completion state machine with diagnostics

### Current repo files to touch

- `backend/app/services/acquisition/browser_client.py`
- `backend/app/services/acquisition/blocked_detector.py`
- possibly a new `backend/app/services/acquisition/browser_runtime.py`

### Acceptance

- hosts with "checking your browser", cookie banners, or short interstitials show higher successful acquisition rates
- hard-blocked runs still fail fast with explicit reason

## Phase 3: Requested-Field-Driven Hidden Content Recovery

### Goal

Make additional fields change crawler behavior, not just field matching.

### Deliverables

- requested-field policy module
- browser semantic expansion helper
- semantic detail extractor
- requested-field coverage metrics
- detail publish gate that considers requested-field coverage

### Current repo files to touch

- `backend/app/services/crawl_service.py`
- `backend/app/services/extract/service.py`
- new modules under `backend/app/services/extract/` or `backend/app/services/browser/`

### Acceptance

- when users request fields like material, fit, care, shipping, benefits, qualifications, or specs, the crawler actively opens relevant page sections
- coverage of requested fields improves on rich detail pages without site-specific hacks

## Phase 4: Discovery Expansion

### Goal

Discover more structured data sources before falling back to weak DOM heuristics.

### Deliverables

- generalized inline-script JSON blob extraction
- support for common hydration globals beyond Next.js
- improved ranking of intercepted network payloads
- structured-source provenance in manifests

### Current repo files to touch

- `backend/app/services/discover/service.py`
- `backend/app/services/extract/listing_extractor.py`
- `backend/app/services/extract/json_extractor.py`

### Acceptance

- more complex JS-heavy sites yield records from structured sources before DOM-card fallback

## Phase 5: Selector And Shadow/Frame Capability Redesign

### Goal

Fix the selector model so it can express modern page boundaries.

### Deliverables

- selector capability metadata
- selector execution engine for:
  - CSS
  - XPath
  - shadow-root traversal
  - optional frame scope
- host/path-family scoped selector memory

### Current repo files to touch

- selector storage layer
- `backend/app/services/extract/service.py`
- browser-side selector execution modules
- any admin/UI surfaces that mention shadow selectors

### Acceptance

- the system can actually traverse shadow roots when a selector is marked shadow-aware
- the UI terminology matches the backend capability

## Phase 6: Browser Specialist Extraction For Complex Listings

### Goal

Bring the current repo closer to the old page-local browser extraction ability without importing the old monolith.

### Deliverables

- bounded page-local extraction routines for JS-heavy listing pages
- stronger reconciliation between intercepted API data and DOM evidence
- optional pagination/load-more specialist path

### Current repo files to touch

- `backend/app/services/acquisition/browser_client.py`
- `backend/app/services/extract/listing_extractor.py`
- possibly a new specialist extraction module

### Acceptance

- better yield on JS-heavy commerce and jobs listings
- no uncontrolled browser wandering to unrelated pages

## Phase 7: Observability And QA

### Goal

Make the system explain why it succeeded or failed.

### Deliverables

- acquisition diagnostics per run
- challenge state diagnostics
- requested-field coverage metrics
- structured-source provenance
- host-memory visibility

### Acceptance

- a failed or partial run is explainable without artifact spelunking

## Recommended Execution Order

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6
8. Phase 7

This order matters:

- Phase 1 and Phase 2 are the highest-value porting work for anti-bot and simple challenges.
- Phase 3 is the highest-value porting work for richer detail extraction and "additional fields" behavior.
- Phase 5 should not be pulled earlier unless shadow DOM support is immediately blocking target sites.

## Highest-Value Ideas To Port First

If only a few slices are funded now, start here:

1. old `http_provider.py` ideas into current acquisition
2. old browser stealth/context/origin-warming ideas into current browser runtime
3. old challenge wait loop into current browser acquisition
4. old requested-field policy plus semantic expansion for detail pages
5. old semantic detail extraction for sections/specifications

## What Not To Port As-Is

- Do not copy `spa_crawler_service.py` wholesale.
- Do not copy old UI wording around "shadow selectors" without implementing real shadow-root traversal.
- Do not overfit to Akamai-only logic; keep provider detection generic and policy-driven.

## Final Recommendation

The current repo should not be rewritten around the old repo. It should absorb the old repo's best ideas in three focused moves:

1. make acquisition host-aware and challenge-aware
2. make requested fields drive hidden-content recovery
3. redesign selectors and browser extraction so complex modern pages are first-class, including real shadow DOM support

That gives the current system the older repo's strongest capabilities without importing its monolithic complexity.
