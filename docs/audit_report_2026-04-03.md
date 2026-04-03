# Crawl Pipeline Audit Report

Date: 2026-04-03

Scope:
- Re-audit the current crawl pipeline against the repo’s regression corpus in `TEST_SITES.md`
- Reproduce the Foot Locker failure first
- Validate additional commerce and jobs surfaces with real runs already stored in `backend/crawlerai.db`

## Executive Summary

The current pipeline can succeed on a narrow subset of detail pages where a platform adapter returns a ready-made record. It is not reliable yet for the broader product scope described in `TEST_SITES.md`, especially listing pages, JSON/API-first sources, and bot-protected surfaces.

The most important architectural issue is that listing pages fall back into a detail-style single-record path when card extraction fails. That produces superficially “successful” runs with either one page-level record or a few low-signal fields, even when the source page clearly contains many real records.

The Foot Locker case is a real extraction failure, not just a UI bug:
- Run `1` saved `48` records from `https://www.footlocker.com/category/womens/clothing/pants.html`
- Those records contain only `url` and `image_url`
- The run was marked `completed` with no indication that core listing fields like `title`, `price`, and `brand` were missing

## Test Evidence

### Completed Runs Reviewed

| Run | URL | Surface | Outcome |
| --- | --- | --- | --- |
| 1 | Foot Locker women pants listing | `ecommerce_listing` | `48` records, but only `url` and `image_url` |
| 2 | Foot Locker PDP | `ecommerce_detail` | `1` usable record from deterministic candidates |
| 3 | Walmart laptops listing | `ecommerce_listing` | Bot page captured, saved as `title = "Robot or human?"`, still marked completed |
| 4 | Indeed search listing | `job_listing` | `3` records, but only top-nav URLs from the adapter path |
| 5 | Indeed homepage as detail | `job_detail` | `title = "Access Denied"`, still marked completed |
| 6 | Allbirds PDP | `ecommerce_detail` | Good result via Shopify adapter |
| 7 | Allbirds men collection | `ecommerce_listing` | Listing collapsed into `1` page-level record despite Shopify signals and embedded product data |
| 8 | Greenhouse Stripe board | `job_listing` | Listing collapsed into `1` page-level record despite `490 jobs` in HTML |
| 9 | Remotive API | `job_listing` | Raw JSON captured, `0` records saved |

### Foot Locker Reproduction

Run `1` confirms the original complaint:
- `result_summary.record_count = 48`
- sample stored record:
  - `data.url = https://www.footlocker.com/product/...`
  - `data.image_url = https://images.footlocker.com/...`
  - no `title`
  - no `price`
  - no `brand`

This is consistent with the generic listing extractor in [backend/app/services/extract/listing_extractor.py](../backend/app/services/extract/listing_extractor.py), which only relies on shallow DOM selectors and does not use the structured page data that exists in the Foot Locker artifact.

## Findings

### 1. Critical: listing failure downgrades into a misleading single-record fallback

References:
- [backend/app/services/crawl_service.py](../backend/app/services/crawl_service.py)
  - listing branch at lines `310-326`
  - fallback single-record save at lines `375-409`

Problem:
- For listing surfaces, if adapter extraction fails and card detection finds no cards, the pipeline still drops into the generic candidate-to-single-record fallback.
- That fallback is conceptually for detail pages, but it is also used for listings.

Observed failures:
- Run `7` Allbirds collection became one page-level record with only title/url/image.
- Run `8` Greenhouse board became one page-level record with only `title = "Jobs at Stripe"`.

Why this matters:
- The pipeline reports success and a non-zero record count, but the result is not a listing extraction at all.
- This hides the real failure mode from both users and developers.

Recommendation:
- Split listing and detail post-processing explicitly.
- If a listing run produces zero valid item-level records, mark the run as degraded or failed, not completed.
- Persist an explicit extraction verdict such as:
  - `success`
  - `partial`
  - `blocked`
  - `schema_miss`
  - `listing_detection_failed`

### 2. High: bot-blocked or access-denied pages are treated as successful crawls

References:
- [backend/app/services/acquisition/acquirer.py](../backend/app/services/acquisition/acquirer.py) lines `60-79`
- [backend/app/services/crawl_service.py](../backend/app/services/crawl_service.py) lines `277-290`, `227-237`

Problem:
- The only hard blocked-page check is `html.strip() < 100`.
- Semantic block pages are not detected.
- As long as some HTML exists, the run can complete successfully.

Observed failures:
- Run `3` Walmart listing stored `title = "Robot or human?"`
- Run `5` Indeed detail stored `title = "Access Denied"`
- Both runs ended in `status = completed`

Why this matters:
- Users cannot trust the success state.
- Downstream review and promotion flow may learn poisoned values from anti-bot or challenge pages.

Recommendation:
- Add a dedicated blocked-page detector after acquisition and before extraction.
- Start with deterministic signatures:
  - `access denied`
  - `robot or human`
  - `captcha`
  - `enable javascript`
  - known provider markers like PerimeterX, Cloudflare, Akamai, Datadome
- Store `result_summary.blocked = true` and avoid saving challenge-page data as normal records.

### 3. High: JSON/API sources are in scope, but the pipeline has no first-class JSON path

References:
- [backend/app/services/acquisition/acquirer.py](../backend/app/services/acquisition/acquirer.py) lines `37-85`
- [backend/app/services/discover/service.py](../backend/app/services/discover/service.py)
- [backend/app/services/extract/service.py](../backend/app/services/extract/service.py) lines `18-86`

Problem:
- `TEST_SITES.md` explicitly includes JSON/API-first regression cases.
- The current pipeline always treats the response body as HTML text.
- There is no content-type based acquisition branch for JSON documents and no schema-aware JSON listing extractor.

Observed failure:
- Run `9` hit `https://remotive.com/api/remote-jobs?category=software-dev`
- raw artifact contains a valid `jobs` array with titles, company names, locations, salaries, and descriptions
- pipeline saved `0` records

Why this matters:
- JSON APIs are the easiest and highest-confidence sources in the corpus.
- Missing them means the system fails on the lowest-difficulty regression tier first.

Recommendation:
- Add a typed acquisition result:
  - `html`
  - `json`
  - `binary/unsupported`
- If content type is JSON:
  - parse once in acquisition
  - store the parsed payload directly
  - route into a JSON listing/detail extractor
- For known schemas like Remotive, RemoteOK, Greenhouse JSON, Shopify JSON, use adapters first.

### 4. High: generic listing extraction is too shallow for modern commerce and job pages

References:
- [backend/app/services/extract/listing_extractor.py](../backend/app/services/extract/listing_extractor.py) lines `39-79`, `105-156`

Problem:
- The generic listing extractor depends on a small set of CSS selectors and shallow child-node heuristics.
- It does not use structured embedded data when card extraction is weak.
- It extracts only a small universal field set and misses platform-specific data shapes.

Observed failures:
- Run `1` Foot Locker: 48 records but only URL and image.
- Run `4` Indeed listing: adapter path returned navigation links instead of jobs.
- Run `8` Greenhouse board: clear job rows in HTML, but only page title reached storage.

Why this matters:
- Most listing pages in the test corpus are exactly where users expect the system to scale.
- The current extractor works only when the page happens to match a narrow selector set.

Recommendation:
- Replace the current listing fallback with a two-stage strategy:
  1. structured source extraction first
     - embedded JSON
     - hydrated app state
     - JSON-LD item lists
     - intercepted XHR/fetch payloads
  2. DOM card extraction only as a last fallback
- Add domain adapters for high-value unsupported sites already in the corpus, starting with:
  - Foot Locker
  - Greenhouse
  - Lever
  - Remotive / RemoteOK JSON

### 5. Medium: review and UI layers are coupled to structural metadata, not just extracted fields

References:
- [backend/app/services/review/service.py](../backend/app/services/review/service.py) lines `29-40`
- [frontend/app/runs/[run_id]/page.tsx](../frontend/app/runs/[run_id]/page.tsx) lines `74-86`, `195-225`

Problem:
- `build_review_payload()` merges `discovered_data`, `raw_data`, and `data` keys into `discovered_fields`.
- For listing runs, `discovered_data` contains container keys like:
  - `adapter_data`
  - `network_payloads`
  - `next_data`
  - `json_ld`
  - `microdata`
  - `tables`
- The run detail page builds CSV columns from review selections instead of directly from available record data.

User-facing consequence:
- Completed runs can appear empty or misleading in the main CSV view if review data is absent, delayed, or dominated by structural keys rather than business fields.

Recommendation:
- Separate:
  - extracted record fields
  - evidence fields
  - internal container metadata
- Build default CSV columns directly from `record.data` first.
- Show evidence-source fields only in the evidence tab, not as canonical field candidates by default.

### 6. Medium: learned selector memory is not real selector learning

References:
- [backend/app/services/crawl_service.py](../backend/app/services/crawl_service.py) lines `430-447`

Problem:
- `_upsert_selectors()` writes placeholder selectors like `[data-field='title']`.
- Those selectors are not derived from the source DOM and are unlikely to match anything on the site later.

Why this matters:
- The system appears to “learn” selectors, but the stored memory is not actionable.
- That creates false confidence and technical debt in the review/promotion workflow.

Recommendation:
- Do not save selector memory unless a selector was actually discovered or authored.
- Store provenance with each learned selector:
  - `source = adapter | authored | generated`
  - confidence
  - validation result
  - last successful domain sample

## What Works Today

The pipeline is not broken everywhere. The good path is visible in run `6`:
- Allbirds PDP succeeded through the Shopify adapter
- stored fields included `title`, `brand`, `price`, `sku`, `availability`, image URLs, and tags

This shows the architecture can produce strong results when:
- the source has a supported adapter
- the response is not blocked
- the record shape is already close to the target schema

## Priority Recommendations

### P0

1. Make listing failure explicit
- Never convert a failed listing extraction into a single detail-style fallback record
- Add extraction quality flags to the run summary

2. Add blocked/challenge detection
- Detect anti-bot and access-denied pages before publish
- Mark those runs as blocked or failed, not completed

3. Add JSON-first acquisition and extraction
- Parse JSON responses by content type
- Route them to dedicated JSON extractors/adapters

### P1

4. Expand adapter coverage for the regression corpus
- Foot Locker listing
- Greenhouse boards
- Lever boards
- Remotive / RemoteOK APIs

5. Rework listing extraction order
- adapter / structured state / network payloads first
- DOM cards last

6. Improve run-detail UX
- render stored `record.data` immediately
- separate canonical fields from evidence containers

### P2

7. Replace placeholder selector memory with validated learning

8. Add run-quality metrics
- field coverage %
- blocked-page confidence
- item-level extraction confidence
- expected-vs-actual listing count when detectable

## Recommended Next Regression Slice

Use the corpus order already defined in `TEST_SITES.md`, but do it with the new gates above:

1. JSON/API first
- `#3`, `#5`, `#38`, `#39`, `#40`

2. ATS boards
- `#27-35`

3. Commerce listings
- `#14`, `#15`, `#21-23`, plus Shopify collection sanity

4. Hard anti-bot group last
- Walmart, Nike, H&M, Under Armour, Workday, Dice

## Bottom Line

The current system is best described as:
- good on some supported PDP adapters
- fragile on generic listings
- blind to JSON-first sources
- unable to distinguish success from challenge pages

The Foot Locker issue is therefore not an isolated bug. It is a symptom of a broader architectural gap between:
- what the product claims to support
- what the pipeline can reliably classify and extract today
