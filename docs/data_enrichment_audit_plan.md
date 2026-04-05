# Data Enrichment Audit And Plan

Date: 2026-04-05

Scope:
- Current repo: `C:\Projects\pre_poc_ai_crawler`
- Reference repo: `C:\Users\abhij\Downloads\pre_poc_ai_crawler`

## Executive Summary

The current repo is cleaner in its stage separation, but it regressed on the exact areas you called out:

1. Repeat-run learning is much weaker.
2. Listing-to-detail enrichment is mostly absent.
3. The fast-path acquisition/orchestration from the old repo is richer than the current one.
4. The old repo had more ways to recover missing fields without starting from scratch.

The result is predictable:
- slower acquisition on mixed/static listings because fewer lightweight short-circuits exist
- lower output coverage because listings are rarely promoted into enriched detail records
- weaker cleanup and replay because site memory stores less reusable extraction intelligence

## Audit Findings

### 1. Current pipeline stops at page-local listing extraction

Severity: High

Current repo evidence:
- `backend/app/services/crawl_service.py:740`
- `backend/app/services/crawl_service.py:775`
- `backend/app/services/crawl_service.py:827`

What the code does now:
- listing runs are adapter-first or page-local DOM/structured-data extraction only
- if no listing records are found, the run ends with `listing_detection_failed`
- if listing records are found, they are normalized and published immediately
- site memory is updated only with selector observations after the listing page is processed

What is missing versus the old repo:
- no generic listing-to-detail enrichment pass
- no sitemap/listing-page URL recovery when records are thin
- no bounded concurrent detail hydration for listing outputs

Old repo evidence:
- `backend/app/services/crawl_service.py:2163`
- `backend/app/services/crawl_service.py:2170`
- `backend/app/services/crawl_service.py:2217`

Why it matters:
- the old repo upgraded weak listing rows into richer detail rows
- the current repo mostly publishes what it can see on the listing page and stops there
- this is the biggest direct reason for coverage loss

### 2. Current site memory persists selectors, not reusable extraction intelligence

Severity: High

Current repo evidence:
- `backend/app/services/site_memory_service.py:151`
- `backend/app/services/crawl_service.py:2145`
- `backend/app/services/crawl_service.py:2179`

What the code stores now:
- `fields`
- `selectors`
- `selector_suggestions`
- `source_mappings`
- `llm_columns`
- `last_crawl_at`

Old repo evidence:
- `backend/app/storage/repository.py:1174`
- `backend/app/storage/repository.py:1246`
- `backend/app/storage/repository.py:1275`
- `backend/app/storage/repository.py:1292`
- `backend/app/storage/repository.py:1351`

What the old repo also persisted:
- `known_fields`
- `preferred_selector`
- `successful_providers`
- `failed_providers`
- `page_family_memory`
- URL-pattern learning and preview-oriented caches

Why it matters:
- the old repo could reuse not just selectors but strategy
- the current repo relearns too much on each crawl
- this hurts both speed and enrichment quality on repeat domains

### 3. Old repo had a stronger fast-path before browser escalation

Severity: Medium

Current repo evidence:
- `backend/app/services/acquisition/acquirer.py:190`
- `backend/app/services/acquisition/acquirer.py:232`
- `backend/app/services/acquisition/acquirer.py:291`

Current behavior:
- `curl_cffi` is tried first
- browser is used if blocked, JS-shell-like, requested fields imply it, or advanced mode is set
- once browser is needed, the current repo escalates directly into rendered-page acquisition

Old repo evidence:
- `backend/app/services/spa_crawler_service.py:4346`
- `backend/app/services/spa_crawler_service.py:4365`
- `backend/app/services/spa_crawler_service.py:4410`
- `backend/app/services/spa_crawler_service.py:4427`

Old behavior:
- run lightweight HTTP preflight first
- continue known next-page URLs during preflight
- short-circuit browser entirely when preflight is already sufficient
- reduce browser settle time when preflight already proved useful

Why it matters:
- this is a direct acquisition-speed regression for static and semi-static listings
- the current repo has a good transport layer, but weaker orchestration above it

### 4. Current detail extraction has good candidate reconciliation but weaker targeted enrichment

Severity: Medium

Current repo evidence:
- `backend/app/services/extract/service.py:71`
- `backend/app/services/crawl_service.py:857`
- `backend/app/services/crawl_service.py:881`

Current strengths:
- deterministic candidate extraction is broad
- semantic section/spec extraction exists
- LLM cleanup/review can promote some fields

What is missing versus the old repo:
- a clear second-stage enrichment policy for missing detail fields
- broader reuse of successful enrichment outputs on later runs
- listing-result-driven detail hydration as a default capability

Old repo evidence:
- `backend/app/services/detail_enrichment_policy.py:60`
- `backend/app/services/crawl_service.py:3611`
- `backend/app/services/crawl_service.py:4087`

Why it matters:
- the current repo can often detect candidates but still publish thinner records
- the old repo spent more effort reconciling and enriching the final record before publishing

### 5. Current discovery is broad, but publish-time enrichment is comparatively conservative

Severity: Medium

Current repo evidence:
- `backend/app/services/discover/service.py:43`
- `backend/app/services/extract/service.py:131`
- `backend/app/services/extract/service.py:172`
- `backend/app/services/extract/service.py:222`

Observation:
- current discovery/extraction is actually quite capable on a single page
- the regression is not mainly source discovery breadth
- the regression is what happens after first-page extraction: follow-ups, replay, and memory reuse

Implication:
- the right plan is not to replace the current deterministic extractor
- the right plan is to add an enrichment layer above it and store the outputs better

## Root Cause

The old repo treated enrichment as part of the crawl strategy.

The current repo treats enrichment as a narrow post-processing aid:
- selector suggestion
- candidate review
- semantic extraction

That makes the current system more modular, but less aggressive about converting weak first-pass results into publishable rich records.

## Recommended Plan

### Phase 1. Restore the missing enrichment loop

Goal:
- turn listing results into enriched detail records when it is economically justified

Work:
- add a generic listing-to-detail enrichment stage after current listing extraction
- only trigger when:
  - records contain likely detail URLs
  - record count is below a threshold
  - description/spec coverage is below a threshold
- fetch detail pages concurrently with strict caps and timeouts
- merge enriched detail fields back into listing rows with deterministic precedence rules

Target files:
- `backend/app/services/crawl_service.py`
- new helper module such as `backend/app/services/enrichment/listing_detail_enricher.py`

Acceptance criteria:
- richer description/spec/image/category coverage on listing runs
- no major latency regression on large listings
- enrichment is skipped predictably on large/high-confidence runs

### Phase 2. Upgrade site memory from selector cache to strategy memory

Goal:
- make repeat crawls faster and more complete

Work:
- extend `site_memory` payload to store:
  - `known_fields`
  - `preferred_provider` or provider history
  - page-family scoped memory
  - successful enrichment hints
  - reusable detail URL patterns
- load page-family memory before acquisition/extraction decisions
- write back successful enrichment outcomes after publish

Target files:
- `backend/app/services/site_memory_service.py`
- `backend/app/schemas/site_memory.py`
- `backend/app/models/site_memory.py`
- `backend/alembic/versions/*`
- `backend/app/services/crawl_service.py`

Acceptance criteria:
- second run on same host shows fewer browser escalations or fewer failed fields
- detail/listing families reuse their own memory instead of only host-level memory

### Phase 3. Reintroduce old fast-path orchestration ideas into current acquisition

Goal:
- recover speed without weakening current acquisition hardening

Work:
- add a lightweight HTTP preflight stage for listing/category pages
- if preflight yields enough records, skip browser entirely
- if preflight proves the page is useful, lower browser settle time and carry forward hints
- when pagination URLs are obvious, continue them via lightweight HTTP before browser escalation

Target files:
- `backend/app/services/acquisition/acquirer.py`
- `backend/app/services/crawl_service.py`
- potentially new helper `backend/app/services/acquisition/preflight.py`

Acceptance criteria:
- faster time-to-first-record on static/semi-static listings
- fewer unnecessary browser launches
- no loss of coverage on JS-heavy pages

### Phase 4. Add targeted missing-field enrichment for detail pages

Goal:
- improve single-record completeness after deterministic extraction

Work:
- define a missing-field enrichment pass for detail pages
- use cached HTML/rendered HTML only, no extra network unless explicitly required
- resolve only missing requested/canonical fields
- persist successful enrichment outputs into site memory when stable

Target files:
- `backend/app/services/crawl_service.py`
- new helper such as `backend/app/services/enrichment/detail_field_enricher.py`

Acceptance criteria:
- improved requested-field coverage on PDP/job-detail pages
- no increase in hallucinated fields
- deterministic provenance retained per enriched field

### Phase 5. Add explicit coverage and efficiency scoring

Goal:
- make regressions obvious instead of anecdotal

Work:
- add metrics to every run:
  - acquisition method
  - browser escalated or not
  - records found at preflight
  - records after enrichment
  - requested-field coverage
  - enrichment delta by field
  - total wall-clock time by stage
- compare current vs enriched output on the same fixture set

Target files:
- `backend/app/services/crawl_service.py`
- `backend/app/schemas/crawl.py`
- smoke/audit scripts under `backend/`

Acceptance criteria:
- you can quantify whether an enrichment change helped or hurt
- speed and coverage can be optimized together instead of trading blindly

## Implementation Order

1. Phase 5 instrumentation first
2. Phase 1 listing-to-detail enrichment
3. Phase 2 richer site memory
4. Phase 3 preflight/short-circuit acquisition
5. Phase 4 targeted detail missing-field enrichment

Reason:
- instrumentation gives a stable baseline
- listing-to-detail enrichment is the highest-coverage win
- richer site memory compounds the benefit on repeat domains
- preflight then improves speed after enrichment behavior is visible

## Test Matrix

Prioritize these groups:

1. Easy static listings with clear detail URLs
- expected win: browser avoidance and better description/spec enrichment

2. Mixed static/JS commerce listings
- expected win: keep current acquisition resilience, add better detail hydration

3. Job boards with stable detail pages
- expected win: better location/description/metadata completeness

4. Repeat-run same-domain tests
- expected win: fewer relearning steps and faster acquisition

Suggested repo additions:
- `backend/tests/services/enrichment/test_listing_detail_enricher.py`
- `backend/tests/services/enrichment/test_detail_field_enricher.py`
- `backend/tests/services/test_site_memory_reuse.py`
- `backend/tests/services/acquisition/test_preflight_short_circuit.py`

## Bottom Line

The current repo does not look fundamentally worse at deterministic single-page extraction.

The regression is that the old repo had a better system around the extractor:
- better follow-up enrichment
- better repeat-run memory
- better lightweight preflight before expensive browser work

If you want the fastest path to meaningful improvement, start by restoring generic listing-to-detail enrichment and expanding site memory beyond selectors.
