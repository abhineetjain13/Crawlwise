# Crawl Fix Changelog — 2026-05-03

All findings verified against the local Postgres DB (`crawl_runs` / `crawl_records`
runs 1–20) and by directly fetching the target HTML where relevant.

Tests: **1253 passed / 4 skipped / 0 failed** on the full backend suite
(`.\.venv\Scripts\python.exe -m pytest tests -q`). 13 new regression tests added.

---

## Applied fixes (site failures first, output quality second)

### 1. Tire Rack listing — `listing_detection_failed` (runs #8, #10)
- **Evidence:** Both Tire Rack listing runs produced
  `url_verdicts = ["listing_detection_failed"]` and 0 records. Direct HTML fetch
  shows 10+ `<div class="productTile">` nodes with real product anchors of
  shape `/accessories/<product-slug>`.
- **Root cause:** `listing_url_is_structural()` in
  `backend/app/services/extract/detail_identity.py` rejected every 1–2 segment
  URL whose leading segment matched `LISTING_NON_LISTING_PATH_TOKENS`.
  `accessories` is in that set, so every product URL on Tire Rack was filtered
  out before card scoring could run.
- **Fix:** Skip the leading-segment rejection when the terminal segment looks
  like a product slug: ≥3 hyphen-separated alphanumeric tokens in a hyphenated
  raw terminal (covers `ctek-nxt-5-battery-charger-maintainer`,
  `nike-air-force-1-low`, etc.).
- **File:** `backend/app/services/extract/detail_identity.py`
- **Test:** `tests/services/test_listing_identity_regressions.py::test_tirerack_product_url_is_not_structural` + siblings.

### 2. Dell listing landing-page pollution (run #19)
- **Evidence:** Run #19 "succeeded" with 33 records, but every record is a
  `{url, title}`-only row from the site's global nav (e.g. `Sustainable Data
  Center`, `Alienware Gaming Laptops`) pointing to landing URLs like
  `/en-us/lp/dt/energy-efficient-data-center`. No price, image, description,
  brand or rating on any row.
- **Root cause:** `_unsupported_non_detail_ecommerce_merchandise_hint()` in
  `listing_candidate_ranking.py` rescued any URL whose path segment list didn't
  include a structural or editorial segment. Dell's `/en-us/lp/dt/...` landing
  pages sailed through because `lp`, `dt`, `landing`, `industry`, `solutions`,
  `campaign` were not in `LISTING_EDITORIAL_PATH_SEGMENTS`.
- **Fix:** Added `lp`, `dt`, `landing`, `industry`, `solutions`, `campaign`,
  `campaigns` to `LISTING_EDITORIAL_PATH_SEGMENTS`. This removes the primary
  landing-page false positive without disturbing the existing title-URL overlap
  rescue for short product slugs (verified by
  `test_extract_ecommerce_listing_keeps_title_only_detail_candidates_without_detail_markers`).
- **Files:** `backend/app/services/config/extraction_rules.exports.json`
- **Tests:** two dedicated regressions in `tests/services/test_listing_identity_regressions.py`.
- **Not fixed here:** `/gaming/alienware-laptops` — this is a 2-segment category
  landing page with terminal tokens that exactly match the title. Discriminating
  it from a real `/category/product-slug` requires acquisition-side work
  (browser-first fetch for Dell SPA shells) rather than URL heuristics. Flagged
  for the next pass.

### 3. `shared_variant_logic` — defensive config iteration (3 iterables)
- **Root cause:** `VARIANT_COLOR_HINT_WORDS`, `VARIANT_SIZE_VALUE_PATTERNS`,
  `VARIANT_OPTION_VALUE_NOISE_TOKENS` were iterated directly. If any is `None`
  during partial config load, iteration raises `TypeError` and variant
  extraction silently aborts for that record, producing the "missing variants"
  symptom noted across multiple detail crawls.
- **Fix:** `or ()` fallback on each iterable.
- **File:** `backend/app/services/extract/shared_variant_logic.py`

### 4. `shared_variant_logic` — `VARIANT_SCOPE_MAX_ROOTS` None guard
- **Root cause:** `len(roots) >= VARIANT_SCOPE_MAX_ROOTS` raises `TypeError`
  if the config is `None`, and DOM variant discovery dies before emitting any
  rows.
- **Fix:** Coerce `None` to "no limit" and skip the bound check in that case.
  Matches the pattern already used for `VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH`.
- **File:** `backend/app/services/extract/shared_variant_logic.py`

### 5. `shared_variant_logic` — silent variant drop
- **Root cause:** During semantic-identity merging, if
  `merged_by_semantic.get(...)` misses (unexpected shape), the row was silently
  `continue`d. Any such inconsistency loses variant data.
- **Fix:** Log a warning and append the original row as fallback.
- **File:** `backend/app/services/extract/shared_variant_logic.py`

### 6. Dict/set pollution in scalar text fields (`specifications` / `description`)
- **Evidence:** Audit 1.3 — Sony headphones `specifications` leaked
  `"{'useOnlyPreMadeBundles': False}"`.
- **Root cause:** `coerce_field_value()` in `field_value_core.py` fell through
  to `coerce_text(value)` which called `str(value)` on a Python dict, leaking
  the repr.
- **Fix:** Reject `dict`/`set`/`frozenset` values at the final fallthrough.
- **File:** `backend/app/services/field_value_core.py`
- **Test:** `test_field_value_dom_regressions.py::test_dict_value_is_rejected_for_description_field`.

### 7. Unresolved template placeholders in `image_url`
- **Evidence:** Audit 1.2 — Converse site emitted
  `"https://…/URL_TO_THE_PRODUCT_IMAGE"` as a product image.
- **Root cause:** `_is_garbage_image_candidate()` in `field_value_dom.py` did
  not reject unresolved server-side template literals.
- **Fix:** New module-level regex `_UNRESOLVED_TEMPLATE_URL_RE` covering
  `URL_TO_`, `{{…}}`, `{$…}`, `%%`, `[[…]]`.
- **File:** `backend/app/services/field_value_dom.py`
- **Test:** three cases in `test_field_value_dom_regressions.py`.

### 8. `http_timeout_seconds` TypeError on two fetch paths
- **Root cause:** `float(crawler_runtime_settings.http_timeout_seconds)` raises
  `TypeError` when the config value is `None`, masking downstream fetch errors.
- **Fix:** Treat `None` as "use `context.resolved_timeout`" on both call sites
  (`_try_browser_http_handoff`, `_attempt_http_fetch`).
- **File:** `backend/app/services/crawl_fetch_runtime.py`

### 9. `detail_dom_extractor` variant-key overwrite
- **Root cause:** Duplicate `variant_id` or `url` keys in existing variant rows
  overwrote earlier entries in `existing_by_key`, merging unrelated variants.
- **Fix:** `setdefault` so the first occurrence wins.
- **File:** `backend/app/services/extract/detail_dom_extractor.py`

### 10. LOC budgets bumped for two files whose defensive guards pushed them over
- `shared_variant_logic.py` 1030 → 1050
- `field_value_dom.py` 1580 → 1590
- These are conscious bumps tied to this fix batch per the budget policy in
  `tests/services/test_structure.py`.
- **File:** `backend/tests/services/test_structure.py`

---

## Explicitly rejected (verified against code, not real bugs)

- **CodeRabbit flag #88** (`count_failure=verdict != VERDICT_LISTING_FAILED`):
  not inverted. A listing-detection failure runs on successfully-acquired HTML;
  not counting it as an acquisition-contract failure is correct.
- **CodeRabbit flag "Dell detail `/spd/` needs adding to detail hints"**: user
  explicitly sets `ecommerce_detail` as the surface, so listing-vs-detail URL
  classification is not consulted for the target URL. Real failure mode for
  Dell detail run #20 (verdict=empty despite 25 network payloads) is
  extraction-side and requires a separate investigation.

---

## Deferred (honest list of what's left)

- Dell detail run #20 extraction-empty root cause. Run has saved HTML at
  `backend/artifacts/runs/20/pages/e24972a71e9d1480.html` (1 MB). Needs
  structured-sources / JS-state inspection; non-trivial.
- `/gaming/alienware-laptops` style 2-segment category landings still rescued
  as merchandise. Needs acquisition-strategy work (browser-first for Dell SPA
  shells) or a broader category-token heuristic.
- Audit 2.1/2.2 — hidden-node text leakage (aria-hidden / display:none children
  concatenated into description). Requires retrofit across many DOM text
  helpers; higher blast radius than this batch.
- Audit 3.1–3.4 — pollution-token expansions for feedback/shipping/marketing
  text and SEO meta-description demotion. Content-tuning, low risk; deferred
  to a separate batch with a fixture per case.
- Audit 4.1/4.2 — description truncation caps. Requires config audit.
- Remaining CodeRabbit hygiene flags (magic numbers, precomputed sets,
  hardcoded tokens): lower priority, none were the cause of a real failure.

---

## Files modified

| File | Change |
|---|---|
| `backend/app/services/extract/detail_identity.py` | Product-slug exemption in `listing_url_is_structural` |
| `backend/app/services/extract/listing_candidate_ranking.py` | (verified unchanged after tightening backed out — see test fit) |
| `backend/app/services/config/extraction_rules.exports.json` | Expanded `LISTING_EDITORIAL_PATH_SEGMENTS` |
| `backend/app/services/extract/shared_variant_logic.py` | `or ()` guards, `VARIANT_SCOPE_MAX_ROOTS` None guard, warn-on-miss instead of silent drop, `logging` import |
| `backend/app/services/field_value_core.py` | Dict/set rejection for scalar text fields |
| `backend/app/services/field_value_dom.py` | Unresolved-template-URL regex in `_is_garbage_image_candidate` |
| `backend/app/services/crawl_fetch_runtime.py` | `http_timeout_seconds` None guard on both fetch paths |
| `backend/app/services/extract/detail_dom_extractor.py` | `setdefault` on `existing_by_key` |
| `backend/tests/services/test_structure.py` | LOC budgets for two files |
| `backend/tests/services/test_listing_identity_regressions.py` | New — 6 regressions |
| `backend/tests/services/test_field_value_dom_regressions.py` | New — 7 regressions |

---

## Verification commands

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_test_sites_acceptance.py --url "https://www.tirerack.com/accessories/category.jsp?category=Batteries" --surface ecommerce_listing
.\.venv\Scripts\python.exe run_test_sites_acceptance.py --url "https://www.dell.com/en-us/shop/dell-laptops/scr/laptops/appref=xps-product-line" --surface ecommerce_listing
```
