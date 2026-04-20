# Extraction Enhancement Slice Tracker

Historical narrow plan. Repo-wide stabilization is now governed by [repo-stabilization-master-plan.md](./repo-stabilization-master-plan.md).

Purpose: track the post-refactor reimplementation of extraction enhancements as independently landable slices.

## Source Documents

- Source plan: [docs/features/extraction-enhancement-plan.md](../docs/features/extraction-enhancement-plan.md)
- Governing strategy: [docs/ENGINEERING_STRATEGY.md](../docs/ENGINEERING_STRATEGY.md)

## Rules For All Slices

- Keep current frontend and API behavior stable unless the slice explicitly changes runtime behavior.
- Keep `EXTRACTION_ENHANCEMENT_SPEC.md` unchanged until feature work starts.
- Prefer explicit modules over abstraction.
- Keep work inside the owning subsystem defined in `docs/ENGINEERING_STRATEGY.md`.
- Do not pull in `P11` or `P12`.

## Slice Summary

| Slice | Covers | Subsystem | New deps | Independent after |
| --- | --- | --- | --- | --- |
| Slice 1 | `P3`, `P5` | Extraction | None | None |
| Slice 2 | `P1`, `P7` | Extraction | None | None |
| Slice 3 | `P4` | Extraction + explicit config | None | Slice 1 preferred, not required |
| Slice 4 | `P10` | Acquisition | None | None |
| Slice 5 | `P9` | Extraction / normalization boundary | `w3lib` explicit declaration only | None |
| Slice 6 | `P8` | Crawl orchestration / acquisition policy | None | None |
| Slice 7 | `P2` | Extraction | `selectolax` | Earlier extraction slices may already be landed |
| Slice 8 | `P6` | Extraction | `parsel` | Slice 7 not required |

## Slice 1: JS State Ecommerce Fields + Shared HTML Text Helpers

**Implementation prompt**

> Read `docs/ENGINEERING_STRATEGY.md` first and stay strictly inside this slice. Implement Slice 1 from `plans/extraction-enhancement-tracker.md`: extend JS state ecommerce extraction in `backend/app/services/js_state_mapper.py` to recover price, sku, images, variants, and stock-related fields from `__NEXT_DATA__` and existing state payloads, and deduplicate the shared HTML-to-text and job-section parsing logic currently duplicated between `js_state_mapper.py` and `network_payload_mapper.py` into one explicit extraction helper module. Do not add a new config layer, do not change external API contracts, and add focused backend tests that prove Shopify/Next.js payload mapping and no-regression job section extraction behavior.

**Goal**

Restore high-yield ecommerce fields from JS state and remove duplicated extraction helpers without changing behavior outside extraction.

**Includes**

- Extend `__NEXT_DATA__` ecommerce field mapping for price, sku, image, variants, and stock-related fields.
- Reuse the same helper for HTML-to-text conversion and job section extraction in both mapper modules.
- Keep current extraction flow and source precedence intact.

**Owning subsystem**

- Extraction

**Planned files**

- `backend/app/services/js_state_mapper.py`
- `backend/app/services/network_payload_mapper.py`
- One new shared extraction helper module under `backend/app/services/`
- Focused extraction tests under `backend/tests/services/`

**Acceptance criteria**

- `__NEXT_DATA__` ecommerce mapping includes price, sku, image, variants, and stock-related fields.
- Duplicated job-section and HTML text helpers are removed from both mappers with no behavior regression.
- No new config layer is introduced.

**Tests**

- Shopify or Next.js payload maps price, sku, images, variants, and stock fields.
- Job description section extraction remains behaviorally identical after helper dedupe.

**Out of scope**

- `P1`, `P4`, `P7`, `P8`, `P9`, `P10`
- Parser swaps or dependency additions

**Status**

- `planned`

## Slice 2: Structured-Source Coverage Restoration

**Implementation prompt**

> Read `docs/ENGINEERING_STRATEGY.md` first and stay strictly inside this slice. Implement Slice 2 from `plans/extraction-enhancement-tracker.md`: restore structured-source coverage in `backend/app/services/structured_sources.py` and `backend/app/services/detail_extractor.py` by integrating `extruct` microdata and Open Graph extraction into the existing candidate pipeline and by safely reviving or traversing array-style Nuxt 3 `__NUXT_DATA__` before product payload discovery. Keep existing JSON-LD behavior intact, do not change API contracts, and add focused extraction tests for microdata, Open Graph, and Nuxt 3 payload handling.

**Goal**

Recover structured product metadata that was lost in the refactor while keeping the current extraction architecture explicit and stable.

**Includes**

- Add `extruct` microdata and Open Graph extraction to the existing structured candidate flow.
- Feed recovered structured rows into the same candidate collection path used today.
- Handle array-style `__NUXT_DATA__` safely before `_find_product_payload()` traversal.

**Owning subsystem**

- Extraction

**Planned files**

- `backend/app/services/structured_sources.py`
- `backend/app/services/detail_extractor.py`
- Focused extraction tests under `backend/tests/services/`

**Acceptance criteria**

- `extruct` microdata and Open Graph candidates are merged into the existing structured candidate flow.
- Nuxt 3 array-style `__NUXT_DATA__` is revived or traversed safely before `_find_product_payload()`.
- Existing JSON-LD behavior remains intact.

**Tests**

- Microdata-only product page yields title, price, or brand candidates.
- Open Graph-only page yields image or product metadata candidates.
- Nuxt 3 array payload no longer silently drops product data.

**Out of scope**

- Generic XHR mapping
- Browser fingerprint work
- URL normalization and robots handling

**Status**

- `planned`

## Slice 3: Generic Network Payload Mapping

**Implementation prompt**

> Read `docs/ENGINEERING_STRATEGY.md` first and stay strictly inside this slice. Implement Slice 3 from `plans/extraction-enhancement-tracker.md`: expand `backend/app/services/network_payload_mapper.py` beyond the current Greenhouse-only path by moving payload mapping specs into one explicit config module under `backend/app/services/config/` and adding deterministic first-non-empty-path mapping for generic ecommerce and job-detail payloads. Preserve Greenhouse behavior, do not inline new provider-specific specs in service code, do not change external API contracts, and add focused tests for Greenhouse regression plus generic ecommerce and job payload mapping.

**Goal**

Broaden XHR payload extraction without reintroducing hidden rules or provider sprawl in service code.

**Includes**

- Keep Greenhouse support intact.
- Add explicit config-backed path specs for generic ecommerce and job-detail payloads.
- Use deterministic first-non-empty-path resolution.

**Owning subsystem**

- Extraction with explicit config support

**Planned files**

- `backend/app/services/network_payload_mapper.py`
- One new explicit config module under `backend/app/services/config/`
- Focused extraction tests under `backend/tests/services/`

**Acceptance criteria**

- Greenhouse remains supported.
- Generic ecommerce and job-detail payload specs are added without hardcoding additional providers inline.
- First non-empty path resolution is deterministic and tested.

**Tests**

- Greenhouse payload regression test passes.
- Ecommerce payload maps the first non-empty configured path.
- Generic job payload maps title, company, and location from non-Greenhouse shapes.

**Out of scope**

- Structured-source parsing changes
- Browser acquisition changes
- URL normalization and robots checks

**Status**

- `planned`

## Slice 4: Browser Fingerprint Restoration

**Implementation prompt**

> Read `docs/ENGINEERING_STRATEGY.md` first and stay strictly inside this slice. Implement Slice 4 from `plans/extraction-enhancement-tracker.md`: restore `browserforge`-based browser identity generation in the acquisition layer by updating `backend/app/services/acquisition/browser_client.py` and any directly adjacent acquisition runtime helper needed for Playwright context creation. Replace static identity values with coherent generated values, keep `service_workers="block"` and `bypass_csp=False` enforced, keep extraction logic out of acquisition, and add focused tests around context creation behavior.

**Goal**

Restore realistic browser identity generation in acquisition without leaking extraction concerns into Playwright setup.

**Includes**

- Use `browserforge` for coherent user agent, headers, viewport, and related browser identity fields.
- Keep existing security invariants enforced in browser context creation.
- Limit changes to acquisition-owned modules.

**Owning subsystem**

- Acquisition

**Planned files**

- `backend/app/services/acquisition/browser_client.py`
- Any directly adjacent acquisition runtime helper needed for Playwright context creation
- Focused acquisition tests under `backend/tests/services/`

**Acceptance criteria**

- Static browser identity values are replaced with `browserforge`-generated coherent values.
- `service_workers="block"` and `bypass_csp=False` remain enforced.
- No extraction logic leaks into acquisition.

**Tests**

- Playwright context creation uses generated user agent, viewport, and headers.
- Security invariants remain set.

**Out of scope**

- Extraction parser changes
- robots.txt gating
- URL normalization

**Status**

- `planned`

## Slice 5: URL Normalization And Tracking-Strip

**Implementation prompt**

> Read `docs/ENGINEERING_STRATEGY.md` first and stay strictly inside this slice. Implement Slice 5 from `plans/extraction-enhancement-tracker.md`: add explicit tracking-parameter stripping for extracted product and job URLs at the extraction-normalization boundary using `w3lib`, with the implementation kept local to `backend/app/services/field_value_utils.py` or a narrow adjacent URL helper plus the relevant extractor finalization call sites. Strip tracking parameters before final record output, preserve non-tracking functional query parameters, avoid broad normalization refactors, and add focused tests for both removal and preservation cases.

**Goal**

Prevent duplicate records caused by tracking parameters while keeping URL normalization explicit and local.

**Includes**

- Explicit direct dependency use of `w3lib`.
- Tracking-parameter stripping before final record output.
- Preservation of canonical functional query parameters.

**Owning subsystem**

- Extraction / normalization boundary

**Planned files**

- `backend/app/services/field_value_utils.py` or one narrow adjacent URL helper
- Relevant extraction finalization call sites
- `backend/pyproject.toml`
- Focused backend tests under `backend/tests/services/`

**Acceptance criteria**

- Extracted product and job URLs strip tracking params before final record output.
- Non-tracking functional query params are preserved.
- Normalization remains explicit and local.

**Tests**

- `utm_*`, `gclid`, `fbclid`, `ref`, and `sid` are stripped.
- Canonical functional query params are preserved.

**Out of scope**

- robots.txt policy
- Parser swaps
- Browser acquisition changes

**Status**

- `planned`

## Slice 6: robots.txt Dispatch Gate

**Implementation prompt**

> Read `docs/ENGINEERING_STRATEGY.md` first and stay strictly inside this slice. Implement Slice 6 from `plans/extraction-enhancement-tracker.md`: add a narrow robots policy module and wire it into the dispatch or fetch scheduling boundary so crawlability is checked before URLs are fetched. Keep the behavior explicit in crawl orchestration or acquisition policy code, keep existing request and response shapes stable, make allowed, disallowed, missing-robots, and robots-fetch-failure behavior explicit and tested, and avoid unrelated extraction changes.

**Goal**

Add a clear pre-fetch robots policy gate without expanding the public API surface.

**Includes**

- One narrow `robots_policy` module with a single crawlability entrypoint.
- Wiring at the dispatch or fetch scheduling boundary before URLs are fetched.
- Explicit handling for allowed, disallowed, missing, and fetch-failure cases.

**Owning subsystem**

- Crawl orchestration or acquisition policy boundary

**Planned files**

- `backend/app/services/robots_policy.py`
- The dispatch or runtime entrypoint that decides whether a URL should be fetched
- Focused backend tests under `backend/tests/services/`

**Acceptance criteria**

- Crawlability is checked before dispatch or fetch scheduling.
- Allowed, disallowed, missing robots, and robots fetch failure paths are all explicit and tested.
- Existing API shapes stay the same; only runtime behavior changes.

**Tests**

- Allowed URL dispatches.
- Disallowed URL is blocked before fetch.
- Missing or failed robots fetch follows the documented default behavior.

**Out of scope**

- URL normalization
- Browser fingerprint work
- Structured-source parsing

**Status**

- `planned`

## Slice 7: CSS-Path Parser Migration With selectolax

**Implementation prompt**

> Read `docs/ENGINEERING_STRATEGY.md` first and stay strictly inside this slice. Implement Slice 7 from `plans/extraction-enhancement-tracker.md`: add `selectolax` to `backend/pyproject.toml` and migrate only CSS-selector-only extraction paths in `backend/app/services/detail_extractor.py`, `backend/app/services/listing_extractor.py`, and any purely CSS-based adapters to use `selectolax` where it clearly replaces BeautifulSoup selector work. Keep BeautifulSoup and lxml in place for XPath-dependent or helper-dependent paths, do not introduce a general parser abstraction layer, and add focused tests that prove CSS-path field parity while XPath-backed paths remain unchanged.

**Goal**

Reduce extraction parser overhead on CSS-only paths without changing the architecture of mixed or XPath-driven extraction.

**Includes**

- Add `selectolax` dependency.
- Migrate only CSS-selector-only extraction paths.
- Leave XPath-dependent or helper-dependent paths on existing parsers.

**Owning subsystem**

- Extraction

**Planned files**

- `backend/pyproject.toml`
- `backend/app/services/detail_extractor.py`
- `backend/app/services/listing_extractor.py`
- Only the adapters that are purely CSS-selector based
- Focused extraction tests under `backend/tests/services/`

**Acceptance criteria**

- `selectolax` is used only for CSS-selector-only paths.
- BeautifulSoup and `lxml` remain in place for XPath-dependent or helper-dependent paths.
- No broad parser abstraction layer is introduced.

**Tests**

- CSS-only extraction paths keep field parity after parser swap.
- XPath-backed paths are unchanged.

**Out of scope**

- Script regex extraction migration
- Browser acquisition changes
- robots.txt and URL normalization

**Status**

- `planned`

## Slice 8: Script-Text Extraction Upgrade With parsel

**Implementation prompt**

> Read `docs/ENGINEERING_STRATEGY.md` first and stay strictly inside this slice. Implement Slice 8 from `plans/extraction-enhancement-tracker.md`: add `parsel` to `backend/pyproject.toml` and convert only the current BS4-plus-regex script-text extraction sites where selector-plus-regex chaining clearly improves the implementation. Keep the helper narrow and explicit, do not replace general DOM parsing with `parsel`, preserve current extraction contracts, and add focused tests for `__NEXT_DATA__` and inline script extraction behavior.

**Goal**

Improve script-text extraction where CSS/XPath plus regex chaining is materially clearer than the current two-step approach.

**Includes**

- Add `parsel` dependency.
- Convert only script-text extraction sites that clearly benefit from selector-plus-regex chaining.
- Keep any shared helper narrow and explicit.

**Owning subsystem**

- Extraction

**Planned files**

- `backend/pyproject.toml`
- Affected adapters or extraction helpers only
- Optional narrow shared script extraction helper
- Focused extraction tests under `backend/tests/services/`

**Acceptance criteria**

- Current BS4-plus-regex script extraction sites are converted only where `parsel` clearly improves selector-plus-regex handling.
- `parsel` is not introduced as a general parser replacement.
- Behavior is covered by focused adapter or extraction tests.

**Tests**

- `__NEXT_DATA__` extraction still succeeds through the new implementation.
- Inline script regex extraction still succeeds.
- Regex terminal behavior is handled correctly.

**Out of scope**

- General parser migration
- Structured-source recovery
- Browser acquisition changes

**Status**

- `planned`

## Tracker Maintenance

After a slice lands, update only that slice's status, landed PR or commit reference, and any newly exposed dependency notes. Do not expand scope or add `P11` or `P12` from this tracker.
