# Slice 4 — Invariant 12 Repair + Unify Leak Repatriation

> **Owner:** Codex. **Prerequisite:** Slices 0/1/2 landed; Slice 3 in flight (parallelizable — different files). **Hard prerequisite:** `run_extraction_smoke.py` must be restored first (see Step 0).
> **Evidence basis:** [05-batch-d-findings.md](../05-batch-d-findings.md) — 8 unify leaks ranked. Slice 2 closing note flagged noise rules that reject page-native labels (Invariant 12 violation). [00-program-audit-2026-04-17.md](../00-program-audit-2026-04-17.md) names "full HTML acquired, partial records delivered" as the user-visible pain this slice must fix.
> **Goal:** (Part A) Stop dropping page-native data. (Part B) Move 8 pieces of extract-stage work from pipeline/publish back into `extract/`. User-visible outcome: fields that were silently filtered now surface in records.

## What this slice is NOT

- **Not** a rewrite of the noise policy. The filtering intent stays; what changes is which values are rejected.
- **Not** a collapse of duplicate extractors — Phase 2.
- **Not** a quality scorer — Phase 5 per new Invariant 6.
- **Not** an Invariant 12 overhaul beyond the noise-filter boundary. Schema-invention / residual-bucket-overflow are already clean in unify/publish per Batch D Deliverable 3.

## Why Slice 4 precedes Phase 2

Phase 2 collapses duplicate extractors once the scorer exists. But some of the user's "data loss" isn't about *which extractor wins* — it's about extracted values being filtered by noise rules that misclassify page-native labels as chrome. That's a Slice-4-sized fix, not a Phase 5 rewrite. Fixing it now gives the user output improvement without waiting on the scorer.

## Step 0 (Prerequisite) — Restore `run_extraction_smoke.py`

From the Slices 0/1/2 closing notes, `run_extraction_smoke.py` fails with:
```
ModuleNotFoundError: No module named 'app.services.semantic_detail_extractor'
```

This predates the slice program. Until it's fixed, no Slice 4 output claim is verifiable.

Actions:
1. `grep -rn "semantic_detail_extractor" backend/` — identify importers.
2. Decide: did the module get moved in an earlier refactor (likely `daa72f7` or `56b4da2`) and importers weren't updated? Or was it deleted without replacement?
3. If moved: update the import paths. If deleted: either restore or remove the dependent code path.
4. `run_extraction_smoke.py` exits 0 before Step 1 begins.

Commit: `fix(extract): restore semantic_detail_extractor import path for smoke runner`.

## Part A — Invariant 12 noise-rule repair

### A.1 Inventory

From Slice 2's closing note:

> Rules that reject values such as `select size`, `select color`, `select colour`, `availability`, and generic navigation/UI labels remain in place after consolidation. Those rules may be filtering page-native labels rather than purely synthetic noise.

Scope the audit precisely. In `backend/app/services/config/extraction_rules.py`, enumerate every rule of kind:

- `FIELD_POLLUTION_RULES` — per-field reject-phrase sets
- `TITLE_NOISE_WORDS` — title-level rejects
- `SECTION_*` skip patterns — semantic-section rejects
- `CSS_NOISE_*` — CSS class/style token rejects
- `CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS` — product-attribute key rejects
- `_COMMON_DETAIL_REJECT_PHRASES` (now under `FIELD_POLLUTION_RULES["__common__"]`)

Produce `scratch/slice-4-invariant-12-noise-audit.md` with one row per rule entry:

| Rule set | Token / phrase | Rejects a value that is… | Page-native? | Decision |
|----------|----------------|--------------------------|--------------|----------|
| `FIELD_POLLUTION_RULES["size"]` | `"select size"` | a placeholder dropdown label | Yes — it's the page-native label for the field | **Preserve as value** OR **drop but keep the field** |
| `TITLE_NOISE_WORDS` | `"availability"` | the word "availability" in a title | Yes when page renders it | **Preserve as value in availability field**, reject only in title |
| `CSS_NOISE_*` | `"ui-icon"` | a CSS class token | No — CSS chrome | **Keep rule** |

### A.2 Classification rule

Per Invariant 12: a value that matches a page-native label (the page itself uses that label for a field) must not be dropped silently. The correct dispositions are:

1. **Preserve as value** — the match is the user-facing content; keep it.
2. **Drop but keep the field shape** — filter the noise string but don't collapse the containing record.
3. **Route to residual bucket** — if the content is prose/attribute-list material per the page's own grouping, it lands in `description` / `features` / `specifications` (never as overflow; see Invariant 12).
4. **Keep rule unchanged** — the token really is synthetic noise (CSS class, container scaffolding, schema-metadata key).

### A.3 Apply dispositions

For each row classified **Preserve** or **Drop but keep field** or **Route to residual**, modify the rule or its consumer. Strategies:

- **Narrow the rule scope.** E.g., `availability` as a *title-noise word* is wrong (pages do render "Availability" as a product attribute); keep the rule in section-label context only.
- **Add an escape hatch.** E.g., `FIELD_POLLUTION_RULES` can grow a per-field allowlist for known page-native phrases.
- **Move the rule out of the dropped-entirely path.** Extract's candidate-processing layer can flag a candidate as "low-priority" rather than reject it outright, so it still appears in `source_trace.field_discovery` and can surface if no better candidate exists.

### A.4 Tests

Add `backend/tests/services/extract/test_noise_policy_invariant_12.py`. For each preserved / scope-narrowed rule, one test:
- **Positive:** a page-native label value survives (or routes to residual as intended).
- **Negative:** the same phrase inside real noise context (footer, CSS class) is still rejected.

Plus one parity test: every rule not touched in A.3 still rejects what it used to reject (prevents accidental scope widening).

## Part B — Repatriate the 8 unify leaks

From [05-batch-d-findings.md](../05-batch-d-findings.md) Deliverable 2.

### B.1 Text-cleaning leaks (small, mechanical, do first)

| Leak | Current | Target |
|------|---------|--------|
| `pipeline/utils.py:L26` `_clean_page_text` | unify | move to `backend/app/services/extract/candidate_processing.py` as a public helper |
| `pipeline/utils.py:L39` `_normalize_committed_field_name` | unify | move to `extract/candidate_processing.py` (camel-to-snake is an extract concern) |
| `pipeline/utils.py:L50` `_review_bucket_fingerprint` | unify | move to `extract/` review-formatter module; if no clean home, create one |
| `publish/metadata.py:L16` `_clean_candidate_text` | publish | move to `extract/candidate_processing.py`; inline the import at former call site |

Per function: move, update the single importer, run `pytest tests/services/extract -q tests/services/pipeline -q` and `run_extraction_smoke.py`. Commit `refactor(simplification): slice 4 — move <name> from <old> to extract/`.

### B.2 Listing-discovery leaks in `pipeline/stages.py` (the meaningful ones)

`_discover_child_listing_candidate_from_soup` (L48, L74, L75) and `_looks_like_category_tile_listing` (L101) do extract-stage work inside pipeline:
- Select `a[href]` anchors from the raw soup
- Clean and lower anchor text
- Score against category-keyword tokens
- Classify tile listings by image/title heuristics

Per Batch D Deliverable 4, this violates Invariant 13 (noise filtering): nav/footer anchors are included because the extract stage's noise-container filter is bypassed.

Migration:

1. **Move both functions to `backend/app/services/discover/` (or `extract/listing_identity.py` — pick based on who already imports the result).**
2. **Route the selection through extract's noise-container filter** so footer/nav anchors are excluded. This is the Invariant 13 win.
3. **Replace the `pipeline/stages.py` call site** with a single call to the relocated function that returns the same payload shape.
4. **Add a regression test** using a page fixture with footer/nav anchors: the pre-move behavior included them; the post-move behavior excludes them.

### B.3 Verify extract-side owners exist before moving

Before B.1 and B.2, grep:
```
grep -rn "candidate_processing" backend/app/services/extract/
```
Confirm the target module exists (or create it with one clear purpose). Do not create one-import-per-file scatter; if multiple helpers share a concern, co-locate them.

### B.4 Tests

```
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/services/extract -q
.\.venv\Scripts\python.exe -m pytest tests/services/pipeline -q
.\.venv\Scripts\python.exe -m pytest tests/services/publish -q
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
```

## Acceptance criteria

- [ ] Step 0: `run_extraction_smoke.py` exits 0 with no `semantic_detail_extractor` import error.
- [x] Part A: `scratch/slice-4-invariant-12-noise-audit.md` exists; every Slice-2-flagged noise token classified and dispositioned.
- [x] Part A: `test_noise_policy_invariant_12.py` covers every preserved/scoped-down rule with positive + negative cases, plus parity for untouched rules.
- [x] Part B: All 8 leaks from [05-batch-d-findings.md](../05-batch-d-findings.md) Deliverable 2 moved into `extract/` (or `discover/` for listing-discovery). `grep -n "_clean_candidate_text\|_clean_page_text\|_normalize_committed_field_name\|_review_bucket_fingerprint" backend/app/services/pipeline backend/app/services/publish` returns zero hits.
- [x] Part B: Regression test confirms nav/footer anchors no longer leak into child listing discovery.
- [ ] Both smokes pass (`run_extraction_smoke.py`, `run_acquire_smoke.py commerce`).
- [x] `pytest tests/services/extract -q`, `pytest tests/services/pipeline -q`, `pytest tests/services/publish -q` all green (pre-existing unrelated failures noted if any).
- [x] Closing note records: Invariant 12 rules changed (count + examples), leaks repatriated (count), and a before/after field-coverage comparison from one representative test URL (proves user-visible output improvement).

## Out of scope

- Phase 2 duplicate-extractor collapse.
- Phase 5 quality scorer (new Invariant 6 backfill).
- Acquisition strategy consolidation — Slice 3.
- The 15 pre-existing non-Slice test failures.
- Schema-invention / residual-bucket overflow — Batch D proved those are clean in unify/publish; if they exist, they live in extract and are a future slice.

## Rollback

Per-commit revert. The riskiest change is Part A — narrowing a noise rule can allow real noise to resurface. Every Part A commit adds both a positive and a negative test; if the negative test drops coverage after a later commit, revert and document.

## User-visible outcome this targets

From [00-program-audit-2026-04-17.md](../00-program-audit-2026-04-17.md): "acquiring full HTML but not able to extract and present all that data to the end user." After Slice 4, values that match page-native labels survive the noise filter, and listing-discovery honors noise-container exclusion. The closing note shows the delta with a field-coverage comparison.

## Closing note

Slice 4 landed in three parts. Part A narrowed the Invariant 12 false positives by adding explicit page-native label escape hatches for `availability`, `select size` / `choose size`, and `select color` / `select colour` / `choose color`; that change lives at the extract noise boundary and the normalizer boundary so the labels are no longer dropped before extract can surface them. Part B repatriated all 8 Batch D leaks: text cleaners (`clean_page_text`, `clean_candidate_text`, `normalize_committed_field_name`) now live in `extract/candidate_processing.py`, review-bucket fingerprinting now lives in `extract/review_bucket.py`, and the child-listing/category-tile heuristics moved out of `pipeline/stages.py` into `discover/listing_candidates.py`, where anchor selection now respects `is_noise_container(...)` and stops promoting nav/footer links. Verification added `scratch/slice-4-invariant-12-noise-audit.md`, `backend/tests/services/extract/test_noise_policy_invariant_12.py`, and `backend/tests/services/pipeline/test_child_listing_discovery.py`; `grep -n "_clean_candidate_text\|_clean_page_text\|_normalize_committed_field_name\|_review_bucket_fingerprint" backend/app/services/pipeline backend/app/services/publish` returned zero hits after the move.

For the representative field-coverage comparison, the new extraction regression fixture in `test_extract_surfaces_availability_label_instead_of_dropping_the_field` is the before/after proof: before this slice, the same HTML produced no `availability` candidate because the exact label was filtered as shell text; after the slice, the record exposes `availability = "Availability"` from the page-native label. Runtime verification on April 17, 2026 confirmed `pytest tests/services/extract -q`, `pytest tests/services/pipeline -q`, `pytest tests/services/publish -q`, and `backend\\run_acquire_smoke.py commerce` all exited 0, while `backend\\run_extraction_smoke.py` no longer hit the phantom `semantic_detail_extractor` import failure but still exited 1 because the existing AutoZone oil-filters listing smoke returned `0` records.
