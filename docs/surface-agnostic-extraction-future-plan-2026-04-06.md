# Surface-Agnostic Extraction Future Plan

## Problem
- The current runtime still leans on eager surface buckets such as `ecommerce_*` and `job_*`.
- That works for strongly typed pages, but it under-serves pages that are still legible and valuable without matching those buckets cleanly:
  - editorial/blog listings
  - documentation indexes
  - mixed content hubs
  - tabular pages
  - B2B catalog pages without retail price signals
- Pydantic schema validation protects output shape after extraction. It does not solve page understanding or repeated-record detection by itself.

## Why Eager URL Classification Is Not Enough
- URL shape is only a weak prior. It should not be the main gate for whether extraction runs.
- A page can be:
  - legible but not commerce
  - listing-like but not product-like
  - mostly table-driven
  - a hybrid of summary blocks, repeated cards, and tables
- Forcing everything into `commerce` or `jobs` makes the extractor brittle and creates false failures on simple but unsupported page types.

## Product Direction
- Keep the user-selected surface as an output contract, not as the only extraction path.
- Move runtime detection toward page structure instead of URL class.
- Separate three concepts clearly:
  - acquisition succeeded
  - page is legible
  - structured records matching the requested schema were extracted

## Target Architecture
1. Add a generic page analysis layer before surface-specific extraction.
   It should detect:
   - repeated card groups
   - dominant tables
   - article/editorial pages
   - mixed pages with both cards and tables
2. Introduce extractor families instead of only domain buckets.
   Families:
   - repeated entity extractor
   - detail field extractor
   - table extractor
   - page-summary extractor
3. Treat schema resolution as a mapping stage after evidence capture.
   - First capture page evidence generically.
   - Then map that evidence into the requested Pydantic schema.
4. Support non-schema fallback outputs explicitly.
   - markdown/page summary
   - extracted tables
   - discovered repeated-card summaries
5. Reserve hard failures for:
   - blocked pages
   - transport failure
   - unreadable/empty pages
   - true schema miss after evidence capture

## Table Extraction Direction
- Tables should become a first-class extractor family, not a detail-page side effect.
- A run should be able to return:
  - normalized row objects when table headers are stable
  - markdown/CSV-like table fallback when headers are weak
  - provenance showing raw cells and table coordinates
- This applies regardless of whether the page was initially labeled commerce, jobs, or something else.

## Proposed Runtime Model
1. Acquire HTML and diagnostics.
2. Discover evidence generically:
   - headings
   - repeated groups
   - semantic sections
   - tables
   - JSON-LD / embedded state / microdata
3. Score available extraction routes.
4. Run one or more extractors:
   - repeated-entity
   - detail
   - table
   - page-summary fallback
5. Map extracted evidence into the requested schema.
6. Persist both:
   - structured output
   - fallback artifacts when structure is incomplete

## Verdict Model To Aim For
- `success`
  structured records match the requested contract
- `partial`
  legible evidence or fallback output exists, but typed structured extraction is incomplete
- `blocked`
  access/interstitial prevented useful capture
- `empty`
  unreadable or near-empty page
- `schema_miss`
  evidence exists but cannot satisfy the requested schema after mapping

`listing_detection_failed` should shrink over time and become a narrow internal diagnostic, not the dominant user-facing outcome.

## Near-Term Slices
1. Generalize repeated-card detection so non-commerce cards can still produce fallback entities.
2. Promote tables into a standalone extraction/output path.
3. Add a page-summary fallback artifact and API contract that is independent of commerce/jobs.
4. Split extraction evidence capture from schema mapping in the service layer.
5. Add tests for:
   - editorial/blog listings
   - table-heavy pages
   - mixed card + table pages
   - legible but unsupported pages

## Acceptance Criteria
- The pipeline does not depend on eager URL classification to preserve useful output.
- Any legible page can produce at least one persisted fallback artifact.
- Table-heavy pages return usable output even without commerce/job signals.
- Unsupported but readable pages complete as `partial`, not `failed`.
- Pydantic remains the output contract validator, not the only page-understanding mechanism.
