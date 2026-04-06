# Legacy Parity Architecture Plan

## Goal
- Restore the classes of sites that worked in the old app without reintroducing the old app's monolithic provider logic.
- Fix the current failure modes through architecture changes, not more per-site patches.
- Keep the current repo's good invariants:
  - acquisition diagnostics
  - deterministic source-ranked extraction
  - clean record APIs
  - knowledge-base driven tuning

## Inputs
- Current repo:
  - `backend/app/services/crawl_service.py`
  - `backend/app/services/acquisition/acquirer.py`
  - `backend/app/services/acquisition/browser_client.py`
  - `backend/app/services/extract/service.py`
  - `backend/app/services/adapters/registry.py`
  - `backend/app/api/records.py`
- Legacy repo:
  - `C:\Users\abhij\Downloads\pre_poc_ai_crawler\backend\app\services\providers\browser_provider.py`
  - `C:\Users\abhij\Downloads\pre_poc_ai_crawler\backend\app\services\providers\browser_listing_support.py`
  - `C:\Users\abhij\Downloads\pre_poc_ai_crawler\backend\app\services\adapters\platform_adapters.py`
  - `C:\Users\abhij\Downloads\pre_poc_ai_crawler\backend\app\services\discovery.py`
  - `C:\Users\abhij\Downloads\pre_poc_ai_crawler\backend\app\services\crawl_components.py`

## Executive Summary
- The new app is better structured than the old app, but it regressed on platform coverage and on evidence capture for JS-heavy and hidden-content pages.
- The biggest gap is not one bug. It is that the old app had three separate advantages that the new app currently does not combine:
  - broader ATS/platform handling
  - a dedicated browser/provider layer for listing-mode extraction
  - first-class artifact outputs beyond typed records
- The right fix is a layered runtime:
  - `Platform Resolver`
  - `Acquisition Provider`
  - `Evidence Graph`
  - `Record Mapper`
  - `Artifact Exporter`
- Do not copy the old app wholesale. Port the boundaries, not the old sprawl.

## Root Causes By Failure Mode

### 1. Job listing sites return almost nothing in CSV
- Current adapter coverage is narrow. The current registry only includes Amazon, Walmart, eBay, Indeed, LinkedIn, Greenhouse, Remotive, and Shopify.
- The legacy app had explicit family handling for iCIMS and ADP plus browser-mode support for Workday, iCIMS, ADP, and Coveo. It also had platform-aware listing helpers.
- Many of the failing URLs are ATS families that now fall straight into generic listing extraction:
  - iCIMS
  - Workday
  - ADP
  - Oracle Cloud
  - Rippling
  - Paycom
  - UltiPro / UKG
- Generic listing extraction is good for visible repeated cards. It is weak when the board is:
  - hydrated late
  - paginated through JS controls
  - backed by internal APIs
  - rendered with sparse visible card text
- Result: few or zero saved `row.data` records, so CSV export is empty even when the page was legible.

### 2. Commerce detail is better but still misses critical fields
- The new detail pipeline is candidate-first and deterministic, which is good, but its evidence capture is still shallow for:
  - gallery images
  - hidden accordions/tabs
  - field-specific sections such as `returns`
  - late-rendered JS content
- Current browser escalation for requested fields only happens when selector memory already exists.
- That means a user asking for `returns` on a new domain does not necessarily trigger the acquisition behavior needed to reveal the section.
- `additional_images` is treated mainly as a normalized field candidate, not as a first-class gallery evidence set with provenance.

### 3. iCIMS adapter is missing
- This is a direct platform-coverage regression.
- In the legacy app, iCIMS had:
  - endpoint discovery for `/ajax/joblisting/`
  - pagination logic
  - HTML fragment parsing
  - browser fallback extraction helpers
- In the current app, that family is absent from the adapter boundary.

### 4. Markdown is useful but CSV cannot come from it
- Today markdown is a presentation/export artifact, not a typed intermediate model.
- CSV export serializes only persisted structured records from `row.data`.
- Listing fallbacks can preserve `page_markdown` and `table_markdown`, but those are intentionally stripped from CSV export.
- Reverse-parsing markdown into CSV would be fragile and lossy.
- The real missing piece is not "parse CSV from markdown". It is "persist typed artifact outputs beside structured records".

### 5. Hidden fields in carousels, accordions, and rendered JS are still missed
- The current browser client already expands accordions and can open requested-field sections.
- The architecture gap is earlier: the crawler does not treat "field request implies evidence activation" as a first-class decision.
- The new pipeline still assumes:
  - if selectors are known, browser can help
  - if selectors are not known, generic HTML evidence is enough
- That assumption fails for hidden or interaction-gated content.

## What To Keep From The Current App
- `AcquisitionResult` and diagnostics artifacts.
- The ACQUIRE -> DISCOVER -> EXTRACT -> UNIFY -> PUBLISH shape.
- Knowledge-base driven tuning in `pipeline_config.py`.
- Deterministic field discovery summaries in `source_trace.field_discovery`.
- Clean separation between `record.data`, `record.raw_data`, and `source_trace`.

## What To Restore From The Old App
- A real browser/provider boundary instead of leaking platform behaviors through generic acquisition.
- Platform-family extraction for ATS systems that are common and structurally repeatable.
- Page-wide detail field extraction behavior for detail requests.
- Artifact persistence as a first-class output, not only typed records.

## Target Architecture

### 1. Platform Resolver
- Add a `platform_family` layer before generic extraction.
- Resolution should classify by structural signals, not just hostname:
  - `workday`
  - `icims`
  - `adp`
  - `oracle_hcm`
  - `rippling_ats`
  - `paycom`
  - `ultipro_ukg`
  - `greenhouse`
  - `lever`
  - `generic_jobs`
  - `generic_commerce`
- Output should be advisory, not user-control rewriting.
- This belongs beside the current adapter registry, not inside `listing_extractor.py`.

### 2. Acquisition Provider Boundary
- Introduce a provider interface between `acquirer.py` and extraction:
  - `HttpProvider`
  - `BrowserProvider`
  - `HybridProvider`
- The provider decides how to produce evidence for the page family and requested fields.
- This ports the good part of the legacy `BrowserProvider` design without bringing back its all-in-one extraction logic.
- Key rule:
  - acquisition providers collect evidence and activation state
  - they do not finalize business records

### 3. Evidence Graph
- Replace the implicit "manifest + a few side buckets" model with an explicit evidence graph.
- Evidence buckets should include:
  - `visible_dom`
  - `hidden_dom`
  - `expanded_sections`
  - `gallery_media`
  - `tables`
  - `network_payloads`
  - `hydrated_state`
  - `json_ld`
  - `microdata`
  - `adapter_records`
  - `page_markdown`
  - `table_rows`
- Every evidence node should carry:
  - source
  - extraction method
  - visibility state
  - activation action if any
  - field hints
- This is the missing architectural piece behind both `additional_images` and `returns`.

### 4. Field Activation Planner
- Add a planner that maps requested fields to acquisition actions before final browser capture.
- Example actions:
  - expand accordions
  - open tabbed panels
  - click gallery thumbnails
  - auto-scroll section containers
  - wait for specific content roots
- This must not depend on preexisting site memory selectors only.
- Use three sources for planning:
  - generic field-intent rules from config
  - domain/site memory selectors when available
  - page-detected labels and controls

### 5. Platform Family Adapters
- Split adapters into two categories:
  - `API adapters`
  - `DOM family adapters`
- API adapters should be added first for the regressions that matter now:
  - iCIMS
  - ADP
  - Workday
  - Oracle Cloud HCM
  - Rippling ATS
  - Paycom
  - UltiPro / UKG
- DOM family adapters should handle:
  - pagination
  - listing row extraction
  - detail-link resolution
  - family-specific fields such as location, requisition id, department
- These are family adapters, not domain hacks.

### 6. Record Mapper
- Keep deterministic candidate reconciliation, but move it after evidence capture is complete.
- Add first-class typed mappers for:
  - `listing_records`
  - `detail_record`
  - `table_records`
  - `fallback_page_summary`
- `additional_images` should be sourced from `gallery_media`, not inferred only from generic image candidates.
- Requested fields like `returns` should be sourced from:
  - promoted field sections
  - hidden/expanded section evidence
  - label-value extraction over expanded text
  - network payloads when present

### 7. Artifact Exporter
- Persist outputs as an artifact bundle per URL:
  - `structured_records`
  - `table_rows`
  - `page_summary`
  - `markdown`
  - `raw_evidence_refs`
- CSV export should support two typed modes:
  - `records.csv` from structured records
  - `tables.csv` from typed extracted tables
- Do not parse markdown back into CSV.
- Instead, markdown and CSV should be sibling views of the same persisted artifact model.

## Concrete Plan By Problem Area

### A. ATS Recovery Program
1. Add `platform_family` classification and diagnostics.
2. Reintroduce iCIMS as the first new family adapter.
3. Add Workday and ADP next because they are common and existed in the legacy app.
4. Add Oracle, Rippling, Paycom, and UltiPro as second-wave adapters.
5. Create a shared `JobsBoardFamilyResult` contract so CSV export does not depend on each adapter inventing its own field keys.

### B. Detail Evidence Program
1. Add `gallery_media` extraction in acquisition/discovery.
2. Add field-activation planning for hidden content.
3. Split "requested field needs browser" into:
   - `needs_render`
   - `needs_activation`
   - `needs_family_adapter`
4. Expand semantic extraction to consume activated content, not only whatever happened to be visible already.
5. Persist field-level provenance showing whether a value came from visible DOM, hidden DOM, activated section, network payload, or platform adapter.

### C. Output Model Program
1. Introduce a typed artifact schema.
2. Persist fallback tables as rows, not only markdown.
3. Teach export APIs to export from artifact types directly.
4. Keep markdown export, but stop treating it as the only salvage path for readable pages.

## Implementation Slices

### Slice 1: Introduce Platform Family Boundary
- Status: Completed on 2026-04-06
- Deliverables:
  - `platform_family` resolver
  - diagnostics surface in acquisition and run summaries
  - no behavior change yet except better observability
- Acceptance:
  - failing ATS URLs are classified into stable family buckets in diagnostics
- Completed notes:
  - Added config-backed `platform_families.json`
  - Added `platform_resolver.py`
  - Wired `curl_platform_family` into acquisition diagnostics, site memory, acquisition traces, and run summaries
  - Validated live on:
    - Emory iCIMS board -> `platform_family=icims`
    - Smith+Nephew Workday board -> `platform_family=workday`

### Slice 2: Restore ATS Family Coverage
- Status: Completed on 2026-04-06
- Deliverables:
  - iCIMS adapter
  - Workday family support
  - ADP family support
  - family tests and live canaries
- Acceptance:
  - ATS listings produce structured saved records again
  - CSV export becomes non-empty because `row.data` exists
- Completed notes:
  - Added first-class `iCIMS` adapter to the current registry
  - Added embedded-iframe follow for branded shells that proxy the real iCIMS board
  - Added AJAX pagination and HTML-fragment parsing tests
  - Added first-class `Workday` adapter support for listing and detail pages
  - Added first-class `ADP` adapter support for WorkForceNow recruitment pages using hydrated browser DOM
  - Added regression coverage for `iCIMS`, `Workday`, `ADP`, registry resolution, platform-family detection, and acquisition diagnostics
  - Live validation:
    - Emory iCIMS board -> adapter `icims`, `record_count=12`
    - Smith+Nephew Workday board -> adapter `workday`, `record_count=20`
    - ADP WorkForceNow board -> adapter `adp`, `record_count=10`

### Slice 3: Add Evidence Graph And Activation Planner
- Status: In progress on 2026-04-06
- Deliverables:
  - `gallery_media`
  - `expanded_sections`
  - explicit activation actions
  - requested-field activation policy
- Acceptance:
  - `additional_images` and section fields such as `returns` can be sourced with provenance
- Progress notes:
  - Added requested-field activation planning so browser escalation can trigger from field intent, not only selector memory
  - Added persisted evidence buckets for `gallery_media`, `expanded_sections`, and browser activation context
  - Added evidence-graph payloads into `manifest_trace`
  - Live canary:
    - Karen Millen PDP now emits `additional_images` from `gallery_media`
  - Remaining before Slice 3 can close:
    - stronger live activation coverage for hidden policy sections such as `returns`
    - more reliable browser-side evidence capture on JS commerce pages

### Slice 4: Typed Artifact Outputs
- Status: In progress on 2026-04-06
- Deliverables:
  - typed table artifacts
  - page summary artifact
  - export endpoints for record CSV and table CSV
- Acceptance:
  - readable fallback pages can still produce tabular output when a typed table exists
  - markdown is no longer the only useful salvage format
- Progress notes:
  - Added typed artifact bundle export path
  - Added explicit `tables.csv` export
  - Default CSV export now falls back to typed table rows when structured records are empty
  - Added artifact JSON export with `structured_record`, `table_rows`, `page_summary`, `markdown`, and `evidence_refs`

### Slice 5: Second-Wave ATS Families
- Deliverables:
  - Oracle HCM
  - Rippling
  - Paycom
  - UltiPro / UKG
- Acceptance:
  - the supplied regression list is largely covered by family adapters or family-aware browser providers

## Non-Goals
- Do not recreate the old giant browser provider that both navigates and finalizes business records.
- Do not solve this by adding per-domain hacks to `listing_extractor.py`.
- Do not parse markdown back into records as the main export path.
- Do not let platform-family detection rewrite user-selected surface.

## Test Strategy

### Contract Tests
- One fixture per platform family:
  - iCIMS listing
  - Workday listing
  - ADP listing
  - Oracle HCM listing
  - Rippling listing
  - Paycom listing
  - UltiPro listing

### Live Canaries
- Use the URLs from the regression list as canaries, grouped by family.
- Record:
  - records found
  - structured field count
  - CSV rows exported
  - field coverage for requested extras

### Detail Canaries
- Include commerce PDPs with:
  - image galleries
  - accordion sections
  - tabbed returns/shipping/spec blocks

## Acceptance Criteria
- The supplied ATS URLs no longer depend on generic listing extraction alone.
- Current-family ATS sites produce saved structured records and non-empty CSV when the board is legible.
- Detail pages persist `additional_images` from explicit gallery evidence when available.
- A requested field like `returns` can trigger activation and extraction without prior domain selector memory.
- Readable pages can persist typed fallback artifacts beyond markdown.
- The new boundaries are generic and config-driven, not domain hacks.

## Recommended Build Order
- First: platform family resolver
- Second: iCIMS, Workday, ADP
- Third: evidence graph plus activation planner
- Fourth: typed artifact exports
- Fifth: Oracle, Rippling, Paycom, UltiPro

## Bottom Line
- The old app won on breadth and browser-aware family handling.
- The new app wins on structure and diagnostics.
- The correct path is to combine those strengths:
  - restore family-aware providers and adapters
  - promote evidence capture and activation to first-class architecture
  - export from typed artifacts instead of relying on markdown salvage alone
