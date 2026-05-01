# Plan: Data Enrichment Deterministic Bug Fixes

**Created:** 2026-05-01
**Agent:** Cascade
**Status:** COMPLETE
**Touches buckets:** Extraction (upstream only), Enrichment Service, Tests

## Goal

Fix deterministic normalization bugs in `app/services/data_enrichment/service.py` that cause variant-field pollution and category misclassification.

## Confirmed Failure Modes

### FM-1: Variant Dict Pollutes Size/Color/Material Candidates

**Location:** `_candidate_values` → `_flatten_dict_values` in `service.py:823-847`

`_flatten_dict_values` recursively extracts **all** values from dict fields like `variant_axes` and `selected_variant`. When `_normalize_sizes` calls `_candidate_values(data, "size", "available_sizes", "variant_axes", "selected_variant")`, it receives every value in the variant dict — not just size-related ones.

**Impact:** Non-size values (e.g., `"1994"`, `"CD"`, image URLs, color names) are appended to `size_normalized`. In `_normalize_sizes:501`, any value ≤ 4 chars is uppercased unconditionally, so `"us"` → `"US"`, `"cd"` → `"CD"`.

Same pollution path exists for `color_family` (line 275) and `availability_normalized` (line 293).

### FM-2: Category Scoring Diluted by Title/Brand/Materials

**Location:** `_match_category_path` in `service.py:556-611`

All candidate values — `category`, `product_type`, `title`, `brand`, `materials`, `product_attributes` — are merged into a single `source_tokens` set. The score is `len(overlap) / len(source_tokens)`.

**Impact:** Generic title tokens dominate. Example: `"13-cup food processor"` contributes token `"cup"`, which can falsely match `"Apparel & Accessories > Clothing > Cup Sleeves"` when the actual category signal is weak or missing.

### FM-3: Price Parsing Bug is Upstream (NOT enrichment)

KitchenAid price `22999.00` instead of `$229.99` is an extraction bug in the raw signal. Per INVARIANTS Rule 2 ("Fix upstream, not downstream"), this plan deliberately does **not** compensate for it in enrichment. Tackle separately in Self-Healing Extraction plan.

### FM-4: SEO Keywords Missing Stopword Filter on Raw Part Tokens

**Location:** `_build_seo_keywords` in `service.py:614-658`

`title_tokens` are filtered against `seo_stopwords`, but the `raw_parts` loop (brand, category, product_type, color_family, gender, materials, size, category_path) appends tokens **without** stopword filtering. Generic words from `category` or `materials` fields leak into the final keyword list.

**Impact:** SEO keywords contain low-value filler tokens that should have been dropped, diluting search relevance.

**Fix:** Apply the same stopword filter to all token sources before deduplication, not just title bigrams.

## Proposed Fixes

### Fix FM-1: Targeted Dict Extraction

Introduce `_targeted_candidate_values(data, target_keys, *lookup_keys)` that:
- For scalar fields: behaves like `_candidate_values`
- For dict fields: only extracts values whose **dict key** is in `target_keys`
- For nested dicts: applies the same key filter recursively

Update:
- `_normalize_sizes`: use targeted extraction for `variant_axes` / `selected_variant` with target keys `["size", "width"]`; `fit` is not a size source.
- `_normalize_from_terms` for color: use targeted extraction with target keys `["color", "shade", "finish", "tone"]`
- `_normalize_from_terms` for availability: skip `variants` / `selected_variant` dict flattening entirely, or use targeted keys `["availability", "stock", "status"]`

### Fix FM-2: Tiered Category Token Pools

Refactor `_match_category_path` scoring:
1. **Primary pool:** tokens from `category` + `product_type` fields only. Weight = 1.0.
2. **Secondary pool:** tokens from `title`. Weight = 0.3.
3. **Tertiary pool:** tokens from `brand` + `materials`. Weight = 0.1.

Score computation:
- Compute overlap for each pool separately against taxonomy tokens.
- Weighted sum = primary_score + 0.3 * secondary_score + 0.1 * tertiary_score.
- If primary pool is empty or yields score < 0.3, fall back to combined weighted score.
- Penalize matches where primary pool overlap is zero and the match relies only on generic secondary/tertiary tokens.

**Decision:** Title is **not** completely ignored. It is kept as a weighted fallback (weight 0.3) to handle sources with weak or missing category fields. Primary pool (category + product_type) gets weight 1.0. This prevents the `"13-cup food processor"` → `"Cup Sleeves"` misclassification while avoiding brittle edge cases.

## Do Not Touch

- Price normalization compensation for upstream extraction errors.
- LLM enrichment tier (semantic fields).
- `publish/*` export paths.

## Acceptance Criteria

- [x] `_normalize_sizes` rejects non-size variant dict values.
- [x] `color_family` rejects non-color variant dict values.
- [x] Category path for `"13-cup food processor"` with `category="Kitchen Appliances"` stays on Kitchen Appliances instead of `"Cup Sleeves"`.
- [x] Category path for `"ZXQ Plinth"` with `category="ZXQ Plinth"` still returns null (low confidence).
- [x] `python -m pytest tests/services/test_data_enrichment.py -q` exits 0.
- [x] New regression tests added for FM-1, FM-2, and FM-4.
- [x] Variant `fit` / broad width labels do not become `size_normalized` values.
- [x] SQLAlchemy product-level enrichment failures roll back and reload ORM rows before continuing the job.

## Verification

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/test_data_enrichment.py -q
```

## Slices

### Slice 1: Targeted Dict Extraction (FM-1)
- Add `_targeted_candidate_values` helper.
- Update `_normalize_sizes`, color, availability normalizers.
- Add regression tests for variant pollution.

### Slice 2: Tiered Category Scoring (FM-2)
- Refactor `_match_category_path` token pools.
- Add regression tests for title-diluted category misclassification.
- Verify existing low-confidence null test still passes.

### Slice 3: SEO Stopword Filter (FM-4)
- Apply stopword filter to all token sources in `_build_seo_keywords`, not just title bigrams.
- Add regression tests verifying generic category tokens are excluded from keywords.

## Notes

- These are deterministic-only fixes. No LLM behavior changes.
- No database migration needed.
- The `_flatten_dict_values` helper may still be needed for fully unstructured dicts; do not delete it until confirming no callers need it.
- Verified 2026-05-01 with full backend suite: `1139 passed, 4 skipped`.
- Follow-up 2026-05-01: size normalization now rejects implausible values before uppercasing short tokens, and data enrichment job isolation rolls back on `SQLAlchemyError` before marking the product failed. Verified with `tests/services/test_data_enrichment.py -q`: `15 passed`; full backend suite: `1141 passed, 4 skipped`.
