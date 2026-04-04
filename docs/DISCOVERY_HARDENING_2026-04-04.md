# Discovery Hardening Notes

Date: 2026-04-04

## Scope

Focused on strengthening detail-page discovery for complex product pages where rich data exists in multiple places but final output was too small or noisy.

Primary goals:

- keep committed CSV/JSON output clean and accurate
- widen discovery evidence passed into the LLM cleanup/review layer without auto-promoting noisy fields

## Changes

### Discovery Sources

- Added `embedded_json` discovery for:
  - generic `script[type="application/json"]` blobs
  - inline script payloads with ids containing `state`, `data`, `props`, or `product`
  - `data-*` attributes carrying JSON payloads such as `data-product`, `data-state`, `data-props`
- Continued to keep `json_ld`, `__NEXT_DATA__`, hydrated state, network payloads, microdata, and tables as first-class discovery sources.

### Semantic Specification Extraction

- Added support for label/value spec pairs embedded in list-like content such as:
  - `li` rows like `Number of Keys: 61`
  - short paragraph/div spec rows like `Polyphony: 16 Voice`
- This improves discovery on “Tech Specs” / accordion-style product pages that do not use `table` or `dl`.

### Noise Rejection

- Filtered obvious spec noise before it reaches review payloads:
  - `qty`, numeric price-tier row labels, `play video`, `guide`, `discount`, `learn more`, and similar utility/promotional rows
- Tightened generic alias resolution so nested keys like `name`, `type`, `label`, and `id` are only accepted from product-like objects instead of arbitrary hidden browser/app state.

### LLM Review Payload

- Included `embedded_json` in the discovery snapshot sent to the LLM cleanup review flow.
- Increased snapshot breadth so larger structured spec dictionaries are not truncated too aggressively before review.

## Validation

Automated tests added/updated:

- `backend/tests/services/discover/test_discover.py`
- `backend/tests/services/extract/test_extract.py`
- existing targeted crawl/LLM tests in `backend/tests/services/test_crawl_service.py`

Verified locally:

- `python -m pytest backend/tests/services/discover/test_discover.py backend/tests/services/extract/test_extract.py -q`
- `python -m pytest backend/tests/services/test_crawl_service.py -q -k "stores_llm_cleanup_suggestions or process_run_single_url"`
- `python -m py_compile backend/app/services/discover/service.py backend/app/services/extract/service.py backend/app/services/semantic_detail_extractor.py backend/app/services/crawl_service.py`

Live check completed against:

- `https://www.adafruit.com/product/5700`

Observed outcome on that live page:

- discovery found `json_ld` and `embedded_json`
- semantic specs contained clean keys like `product_dimensions`, `product_weight`, and `product_id`
- obvious promo/video rows were no longer included in the semantic spec sample

## Remaining Gaps

- Exact Sweetwater and DigiKey URLs used during debugging could not be re-fetched directly from this environment due intermittent DNS resolution failures, so the regression loop used fixture coverage plus a live Adafruit specialist product page as the closest reproducible real-world validation.
- The pre-run preview requirement for detected/configured output columns is still a separate UI/API task and was not implemented in this pass.
