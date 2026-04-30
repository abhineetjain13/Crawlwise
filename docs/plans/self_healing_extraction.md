# Self-Healing Extraction & Field Quality Plan

**Objective:** Improve canonical requested field coverage for ecommerce detail runs before re-running `testsites.md`. Main pain: missing `price`, missing `brand`, missing `availability`, weak `variants`, and polluted variant values. Use browser rendering and LLM when the user enabled them. Do not add brittle per-site selectors as the main fix.

**Implementation status:** Slice 1 complete. Slice 2 in progress; low-quality browser retry now exists but needed narrower default field targeting plus URL-budget gating after timeout regressions on Amazon/Apple/Kith. Slice 5 targeting fix complete. Slice 6 targeting fix complete. Verified with `pytest tests -q` on 2026-04-30: 1090 passed, 4 skipped.

---

## Audit Findings

Evidence from `failure_mode_report_v8.md`, `json.md`, DB run `1`, and current code:

1. `json.md`: 33 records from 34 URLs. Missing: `price` 4/33, `brand` 5/33, `variants` 18/33, `barcode` 23/33, `availability` 7/33.
2. DB run `1`: `requested_fields=[]`. This weakens self-heal targeting because the run did not declare canonical fields like `price`, `brand`, `availability`, `variants`.
3. DB run `1`: every record shows `_self_heal.triggered=false`. Existing self-heal exists but is effectively unused for the latest test run.
4. `selector_self_heal_enabled()` requires both run LLM and `selector_self_heal.enabled`. Runtime default is `selector_self_heal_enabled=False`.
5. `apply_llm_fallback()` can fill missing fields, but only after selector synthesis and only when `llm_enabled=True`. It cannot repair missing fields if no record survives extraction.
6. Browser retry exists for empty extraction and `challenge_shell`, but not for low-quality records where a non-browser fetch produced a record missing high-value fields.
7. `_can_skip_dom_tier()` already consults `_requires_dom_completion()`. The old plan claim that DOM is skipped purely by high confidence is stale.
8. `js_state_mapper.py` no longer returns first match only at top level. It merges same-product mapped records, but `_extract_product_payload_from_normalized()` still returns one best payload per state object. Nested adjacent product/pricing/variant nodes can still be missed.
9. `browser_readiness_policy` only knows listing overrides, traversal, and detail networkidle. It does not wait for requested high-value field evidence like price text, offer JSON, variant controls, or visible product content.
10. Variant pollution is real: Sneakersnstuff included `Email`, signup text, and random tokens as sizes. That is a DOM variant confinement/validation bug, not an export bug.

Conclusion: current architecture has the pieces, but quality gates are too weak. The crawler accepts partial records too early, selector self-heal is off, and browser/LLM escalation is not tied to canonical field deficits.

---

## Target Contract

For ecommerce detail, when user requested canonical fields or uses the default ecommerce detail profile:

1. Extraction must produce a field-quality report per URL: found fields, missing high-value fields, field sources, confidence, browser engine, self-heal action.
2. Missing high-value fields (`price`, `currency`, `availability`, `brand`, `sku`, `image_url`, `variants`, `selected_variant`) must trigger repair before persistence when repair is authorized.
3. Repair order:
   - existing adapter / network payload / structured data / JS state / DOM candidates
   - browser acquisition retry only when acquisition evidence is insufficient or non-browser output is low quality
   - selector synthesis when rendered HTML contains field evidence
   - LLM missing-field extraction when enabled and deterministic/rendered sources still miss requested fields
4. LLM is user-gated, explicit, and diagnostic. If enabled, it is a normal repair tier for missing requested fields. It must not overwrite populated deterministic values unless a future plan adds explicit conflict review.
5. Patchright/real Chrome are acquisition tools. They should collect better rendered HTML, network payloads, page markdown, accessibility text, and detail expansion evidence. They should not become hidden browser-side scrapers that bypass extraction provenance.

---

## Slice 1 — Quality Gate Before Persistence

**Owner:** `backend/app/services/pipeline/core.py`, `backend/app/services/confidence.py`, `backend/app/services/config/extraction_rules.py`

Work:

- Add a canonical ecommerce detail high-value field set in config if none already covers this exact gate.
- Add a `needs_field_repair(record, run, acquisition_result)` decision helper near pipeline quality/retry logic.
- Treat default ecommerce detail fields as repair targets when `requested_fields=[]`; do not let empty requested fields mean "quality does not matter".
- Emit diagnostics into `source_trace.extraction`: missing high-value fields, repair eligibility, repair action skipped reason.
- Keep public `record.data` clean; diagnostics stay in `source_trace` / `discovered_data`.

Verify:

- Unit tests for empty `requested_fields=[]` still flag missing `price`/`availability`/`variants`.
- Unit tests prove complete records skip repair.

---

## Slice 2 — Browser Retry For Low-Quality Records

**Owner:** `backend/app/services/pipeline/core.py`, `backend/app/services/pipeline/extraction_retry_decision.py`, `backend/app/services/platform_policy.py`, `backend/app/services/acquisition/browser_page_flow.py`

Work:

- Extend retry decision beyond "zero records":
  - if initial fetch was non-browser and high-value requested fields are missing, retry browser when HTML has JS-required, price, offer, app-state, or variant cues.
  - if Patchright returned usable content but still missed high-value fields and diagnostics show weak rendered evidence, allow one real Chrome retry when config enables it.
- Add field-aware readiness policy:
  - detail pages wait for networkidle as today
  - additionally probe for configured high-value evidence classes: visible price text, JSON offer payload, variant controls, product image/title region
  - selectors/tokens live in `app/services/config/*`
- Preserve user controls: no silent proxy/traversal/LLM flips.

Verify:

- Tests for retry decision: non-browser partial detail retries; browser complete detail does not retry; usable Patchright only escalates to real Chrome on missing high-value fields plus weak evidence.
- Smoke target set: Amazon, Target, GOAT, Wayfair.

---

## Slice 3 — JS State Multi-Root Harvest

**Owner:** `backend/app/services/js_state_mapper.py`

Work:

- Replace single best payload per state object with bounded collection of product-like payloads.
- Merge same-product payloads field-by-field using existing `_merge_same_product_record()`.
- Add adjacent pricing/offer/variant payload merge when identity matches by URL, SKU, product id, title, or selected variant id.
- Keep limits from config. No unbounded tree walk.

Verify:

- Unit fixtures where price and variants are siblings of the title payload.
- Regression: unrelated recommendation products do not merge into the requested PDP.

---

## Slice 4 — DOM Variant Confinement

**Owner:** `backend/app/services/extract/detail_dom_extractor.py`, `backend/app/services/extract/shared_variant_logic.py`, `backend/app/services/extract/variant_record_normalization.py`

Work:

- Constrain DOM variant extraction to product option containers, forms, buy boxes, and selected product regions.
- Reject newsletter/footer/header/search/account text as variant values.
- Require axis semantics for DOM-only variants: size/color/shade/condition/etc. from config.
- Dedupe DOM variants against structured variants without appending lower-confidence duplicates.

Verify:

- Sneakersnstuff no longer includes `Email`, signup copy, or random tokens as size values.
- FashionNova color + size stays intact.

---

## Slice 5 — Selector Self-Heal Activation

**Owner:** `backend/app/services/selector_self_heal.py`, `backend/app/services/run_config_snapshot.py`, `backend/app/services/config/runtime_settings.py`, `backend/app/services/config/selectors.py`

Work:

- Enable selector self-heal for test/evaluation profiles when `llm_enabled=True`; keep production default configurable.
- Trigger selector synthesis on missing high-value requested/default fields, not only low total confidence.
- Improve `reduce_html_for_selector_synthesis()` so composite price spans, aria labels, `data-*`, itemprop, and buy-box containers survive reduction.
- Validate synthesized selectors against field type and context, not just non-empty sample text.
- Persist only selectors that improve the target field and pass domain/surface scoping.

Verify:

- Unit test for Amazon-style split price spans.
- Unit test for selector synthesis rejecting newsletter/signup values.
- DB/source trace shows `_self_heal.triggered=true` when repair runs.

---

## Slice 6 — LLM Missing-Field Repair

**Owner:** `backend/app/services/pipeline/direct_record_fallback.py`, `backend/app/services/llm_tasks.py`, `backend/app/data/prompts/*missing*`

Work:

- Treat LLM as explicit field repair when `llm_enabled=True` and high-value fields remain missing after browser + deterministic tiers.
- Use reduced HTML plus page markdown plus existing values. Ask only for missing fields.
- Add strict validation:
  - price must parse as price
  - currency must match price/site context if present
  - variants must be structured rows with semantic axes
  - brand cannot be guessed from retailer domain unless prompt marks it as retailer/manufacturer evidence
- Never overwrite populated deterministic fields in this slice.
- Log rejected LLM fields and reason.

Verify:

- Unit tests for accepted price/currency, rejected bad variant text, and no overwrite.
- Run with `llm_enabled=False` proves no LLM calls.

---

## Slice 7 — Evaluation Harness Before `testsites.md`

**Owner:** `backend/run_test_sites_acceptance.py`, existing test helpers

Work:

- Add acceptance thresholds for ecommerce detail:
  - `price` present for at least 31/33 successful records
  - no `price` missing on Amazon, Target, GOAT, Wayfair unless acquisition is blocked or site genuinely hides price
  - `variants` either present or marked `not_applicable`/`not_public` with diagnostic reason
  - no variant axis pollution from known bad values
  - `_self_heal` / LLM diagnostics visible when repair runs
- Add per-field report output before pass/fail.

Verify:

- Run smallest unit tests per slice.
- Then run:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

---

## Risks

- Some sites hide price until location, login, size selection, or bot challenge. Plan must mark those as `not_public` / `blocked`, not fake values.
- Real Chrome can improve rendered evidence but costs time. Keep one retry per URL and log it.
- Selector self-heal can poison domain memory. Only persist validated selectors scoped by `(domain, surface)`.
- LLM can hallucinate. It fills missing enabled fields only, with type checks and diagnostics.

---

## Done

- Latest DB run shows self-heal/LLM repair actually triggered for low-quality records when enabled.
- Price gaps shrink materially on Amazon, Target, GOAT, Wayfair.
- Variant pollution is gone.
- `source_trace` explains why every missing high-value field stayed missing.
- `testsites.md` acceptance can fail with actionable per-field reasons, not just raw JSON gaps.
