# Browser Runtime Remediation Final Review

Date: 2026-04-19

## Selected Options

- Replace `parsel` in `backend/app/services/script_text_extractor.py` with `selectolax.lexbor.LexborHTMLParser`.
  Reason: script harvesting only needed fast `<script>` iteration and attribute/text reads. Keeping a second parser dependency for that narrow helper added weight without buying capability.
- Remove dead browser-remediation leftovers in `backend/app/services/acquisition/browser_runtime.py` and `backend/app/services/crawl_fetch_runtime.py`.
  Reason: the old one-hit browser-host preference path and the old string-scan challenge helper were no longer on the live call path after Slices 2 and 4.
- Keep the Slice 1-5 behavior and diagnostics contract as landed.
  Reason: the browser remediation now has explicit outcomes, bounded traversal payloads, and focused coverage across acquisition, pipeline, and metrics.

## Deferred Items

- Do not replace BeautifulSoup broadly in `backend/app/services/detail_extractor.py` or `backend/app/services/listing_extractor.py` yet.
  Reason: those modules still rely on BeautifulSoup-backed selector fallback, compatibility logic, and DOM helpers. A larger `selectolax` migration would widen scope into extraction ownership and raise regression risk.
- Do not widen `parsel` usage anywhere else.
  Reason: after the script-text helper change, there is no remaining justified use in the remediation path.
- Do not add a parser abstraction layer.
  Reason: it would violate the strategy doc by adding indirection without a concrete need.

## Residual Risks

- Detail and listing extraction now share a single prepared extraction context, so cleaned-vs-original HTML drift no longer regresses structured parsing between the two pipelines.
- Removing `parsel` from the backend dependency list assumes no external tooling imports it through this project package. Repo-local usage is now gone.

## Verification

- Browser-remediation suite plus script-text coverage passed:
  `test_script_text_extraction.py`
  `test_browser_context.py`
  `test_browser_expansion_runtime.py`
  `test_crawl_engine.py`
  `test_crawl_fetch_runtime.py`
  `test_pipeline_core.py`
  `test_platform_detection.py`
  `test_publish_metrics.py`
  `test_acquirer.py`
  `test_traversal_runtime.py`
  `test_block_detection.py`

## Unresolved Decisions

- None for the browser-runtime remediation chapter.
