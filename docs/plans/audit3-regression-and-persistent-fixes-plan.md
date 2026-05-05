# Plan: Audit 3 Regression + Persistent Issues Fix

Addresses all issues from `zyte/output_audit3.md` plus relevant code-review flags from `coderabbit_codeant_flags.md`, layered on top of the in-progress Zyte Delta plan. No per-site hacks.

**Created:** 2026-05-03
**Status:** COMPLETE
**Touches buckets:** Bucket 4 (Extraction), Bucket 5 (Firewall), `services/config/*`, tests

## Issue → Slice Mapping

| # | Audit Issue | Root Cause | Existing Slice | Gap? |
|---|---|---|---|---|
| R1 | UI tabs scraped as sizes (Nike/Nordstrom) | Size selector not scoped to purchase form | Slice 2 (variant contract) | Partial — Slice 2 scopes DOM variants to PDP form, but size extraction in `detail_dom_extractor.py` also needs form-scoping for non-variant size fields |
| R2 | Hidden DOM concatenation (Patagonia) | Description reads `display:none` colorway blocks | Slice 6 (description fidelity) | No gap — Slice 6 explicitly calls out `display:none` / `aria-hidden` exclusion |
| R3 | Null → bad data (Nikwax color="1", Allbirds color gone, Birkenstock size gone) | Field validation accepts garbage; regression from over-aggressive field stripping | **NEW** | Not covered — needs field-value validation + regression guard |
| P1 | Cookie policy as description/title (Barrow Kids) | Title/description selectors match footer/overlay | Slice 6 (scoping) | No gap — Slice 6 scopes to PDP content container |
| P2 | Price decimal shift (New Balance 19500→$195) | Cents-pattern not detected | Slice 3 (price parity) | No gap — Slice 3 covers locale-aware parsing + magnitude drift |
| P3 | Placeholder images + missing variants (Vans, Patagonia) | Variant extraction fails silently; placeholder URL not filtered | Slice 2 (variant contract) + **NEW** | Variant gap covered; placeholder image filter is new |
| P4 | Truncated descriptions + stringified objects (Sony) | Text cap too low; dict not serialized | Slice 6 (truncation + array-stringification) | No gap |
| P5 | Promo/shipping in description ('47, Jordan 5) | Description not scoped to product body | Slice 6 (pollution removal) | No gap |
| P6 | Corrupted cross-site payload (Nike/Valentino) | Record merge/collision bug | **NEW** | Not covered — URL validation needed |

## Slices

### Slice A: Field-value validation + regression guard (R3)

**Status:** COMPLETE
**Files:**
- `backend/app/services/field_value_core.py` (value validation for color/size)
- `backend/app/services/field_value_dom.py` (quantity-input detection)
- `backend/app/services/extract/detail_record_finalizer.py` (field stripping regression guard)
- `backend/app/services/config/extraction_rules.py` (validation thresholds)
- `backend/app/services/public_record_firewall.py` (reject garbage values at boundary)

**What:**
- **Color validation**: reject single-digit numeric strings (e.g., `"1"` from a quantity `<input value="1">`), reject tracking pixel classes (`_clck`, `_fbp`), reject values that are clearly not color names. Generic rule: a color value that is purely numeric with length ≤ 2 is rejected.
- **Size validation**: reject UI navigation labels (`Photos`, `Verified Purchases`, `Reviews`, `Description`, `Details`, `Shipping`) — these are tab labels, not sizes. Add a configurable `SIZE_REJECT_TOKENS` blocklist in `extraction_rules.py`. A size value matching any token (case-insensitive, trimmed) is dropped.
- **Regression guard**: when a field had a non-empty value from a higher-priority source and a lower-priority source produces `None`/empty, do not overwrite. The candidate system already handles this per-field, but the finalizer's field-stripping path must not drop a field that had a valid value just because a later normalization pass couldn't re-derive it.
- **Placeholder image filter**: reject `image_url` values matching known placeholder patterns (`via.placeholder.com`, `placehold.co`, `placeholder.com`, `1x1` pixel trackers). Add `PLACEHOLDER_IMAGE_PATTERNS` to `extraction_rules.py`. Apply in `public_record_firewall.py`.

**Codeant flags addressed:**
- `field_value_core.py` lines 1028-1039: integer-field string parsing (related — ensures numeric strings are handled correctly)
- `field_value_dom.py` lines 399-407: expensive deepcopy (optimization, not blocking, but do together)

**Verify:**
- Unit tests: color="1" → rejected; size="Photos" → rejected; placeholder image URL → rejected; field with prior value not overwritten by None.
- `pytest tests -q -k "field_value or firewall"`
- Completed with full backend suite: `1283 passed, 4 skipped`.

---

### Slice B: URL integrity + record collision guard (P6)

**Status:** COMPLETE
**Files:**
- `backend/app/services/field_url_normalization.py` (multi-URL detection)
- `backend/app/services/public_record_firewall.py` (URL validation at boundary)
- `backend/app/services/config/extraction_rules.py` (URL validation patterns)

**What:**
- **Multi-URL detection**: a URL field containing two concatenated URLs (e.g., `https://selfridges.com/.../https:/mytheresa.com/...`) is invalid. Detect by checking if the value contains `https://` or `http://` more than once after the initial scheme. Reject at the firewall.
- **Cross-domain URL guard**: if `url` and `image_url` point to different root domains from the page's final URL, flag as suspicious but do not reject (legitimate CDN case). Only reject when two distinct product URLs are concatenated into one string.
- Add `URL_CONCATENATION_PATTERN` to `extraction_rules.py`.

**Verify:**
- Unit tests: concatenated URL → rejected; normal URL → passes; CDN URL on different domain → passes.
- `pytest tests -q -k "url or firewall"`
- Completed with full backend suite: `1283 passed, 4 skipped`.

---

### Slice C: Codeant flags — code quality sweep (non-blocking but should land with these slices)

**Status:** COMPLETE

These are code-review findings that improve robustness and should be fixed alongside the audit fixes. Grouped by file:

**`field_value_core.py`:**
- Lines 521-548: remove duplicate `rows` type annotation
- Lines 1028-1039: parse numeric strings to int for integer fields

**`field_value_dom.py`:**
- Lines 384-388: guard `DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR` before `select_one`
- Lines 399-407: replace `deepcopy(scope)` with selective copy (performance)
- Lines 1026-1030: safe int conversion for section limits
- Lines 331-350: extract cross-product tokens to config constant

**`detail_text_sanitizer.py`:**
- Lines 336-344: remove redundant numeric/guide/glossary checks after `sanitize_detail_long_text`
- Line 183: precompute `artifact_price_values` frozenset
- Lines 420-423: extract hardcoded threshold 3 to config constant
- Lines 238-246: precompute noise prefixes and min-product-words at module level

**`detail_price_extractor.py`:**
- Lines 174-186: set `original_price_source` correctly (jsonld vs dom_text)

**`detail_dom_extractor.py`:**
- Lines 1260-1278: fix variant merge logic (index-based fallback only with strong positional correlation)
- Lines 342-346: remove redundant `% off` regex clause

**`detail_record_finalizer.py`:**
- Lines 419-425: add inline comment explaining variant axis sync intent

**`shared_variant_logic.py`:**
- Lines 979-1009: add docstring for two-stage merge
- Lines 782-785: return None instead of URL-based identity fallback
- Lines 161-177: validate `VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH` before `range()`
- Lines 66-96: rename non-prefixed config symbols to underscore-prefixed

**`variant_record_normalization.py`:**
- Lines 149-154: precompute uppercase currency set at module level

**`field_value_candidates.py`:**
- Line 494: coerce config constants to int once at module load
- Lines 831-833: return joined string for non-list multi-fields

**`extraction_rules.py`:**
- Lines 127-134: defensive `.get()` for `DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR`

**`field_mappings.py`:**
- Lines 208-218: extract raw string literals to named constants
- Lines 25-27: add `NORMALIZER_LIST_TEXT_FIELDS` to exports, remove `tuple()` wrapper

**`normalizers/__init__.py`:**
- Lines 25-28: remove redundant `str()` calls in currency regex
- Lines 66-73: precompute boolean token sets at module level

**`js_state_mapper.py`:**
- Lines 253-256: simplify redundant URL comparison conditional

**`pipeline/core.py`:**
- Lines 441-446: extract `browser_diagnostics` to local variable

**`public_record_firewall.py`:**
- Lines 93-100: replace hardcoded URL field literals with constants
- Lines 78-87: add shape validation for barcode→SKU routing

**`harness_support.py`:**
- Line 42: add VND, IDR, HUF to high-denomination currencies
- Line 1148: hex-color regex accept uppercase A-F
- Lines 1003-1008: add minimum price threshold

**`data_enrichment/service.py`:**
- Lines 758-759: add LRU cache for compiled material strip patterns

**Adapters:**
- `amazon.py` line 323: remove unused `axis_values_by_name`, use `axis_entries`
- `amazon.py` lines 176-180: SKU only populated for real ASIN

**Tests:**
- `test_crawl_engine.py` lines 5071-5075: add `assert len(rows) == 1`
- `test_network_payload_mapper.py` lines 310-311: strict `len(rows) == 1`
- `test_harness_support.py` lines 537-576: add missing assertions

**Codeant logic-error flags (second batch):**
- `TEST_SITES.md` line 171-172: malformed multi-URL entries
- `amazon.py` line 366: removing selected variant breaks callers
- `amazon.py` line 321: dropping variant-axis metadata changes contract
- `myntra.py` line 241: variant count inconsistency after flattening
- `field_mappings.exports.json` line 73: dropping legacy variant aliases breaks parsing
- `field_mappings.exports.json` line 248: removing `price_original` from JS state fields
- `shopify.py` line 198: dropping selected-variant payload
- `data_enrichment.py` line 142: narrowing crawl sources misses data

**Verify:**
- Each codeant flag fix verified individually with targeted test
- Full suite: `pytest tests -q`
- Completed: backend `pytest tests -q` passed; frontend `npm run lint` passed.

---

## Execution Order

1. **Slice A** (field-value validation) — fixes the most urgent regressions (R3, R1 partially)
2. **Slice B** (URL integrity) — fixes P6, small and self-contained
3. **Slice C** (codeant sweep) — lands all code-review fixes, grouped by file to minimize context switches

Slices A and B are new work. Slice C is pre-flagged code review items that should land alongside.

## Relationship to Zyte Delta Plan

The Zyte Delta plan slices 2-6 already cover R1, R2, P1, P2, P4, P5. This plan fills the gaps:
- **R3** (null→bad data): not in Zyte Delta
- **P6** (cross-site URL): not in Zyte Delta
- **Codeant flags**: orthogonal code quality, not in Zyte Delta

Once Zyte Delta Slice 6 (description fidelity) lands, R2/P1/P4/P5 should also be resolved. This plan's Slice A and B are independent and can land in parallel.
