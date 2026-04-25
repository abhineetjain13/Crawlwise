Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py around lines 83 - 89, BELK_TITLE_SELECTORS contains an overly broad fallback "a[href]" that can match any link; update the tuple so the generic anchor is only used as a last-resort and make it more constrained—e.g., replace "a[href]" with a more specific selector like "a[href*='/product/'], a[class*='product' i], [data-testid*='product-name' i] a" or move "a[href]" to the end and add post-extraction validation in the title extraction routine (the function that consumes BELK_TITLE_SELECTORS) to reject results that are clearly non-title (too short/long, contain navigation words, or not inside a product container element); ensure changes reference BELK_TITLE_SELECTORS and the title extraction function so the fallback is both ordered and validated.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/platforms.json around lines 407 - 414, The Nike platform entry currently restricts matching to India-only domains and an India-specific HTML marker; decide whether this should be global and if so, update the nike configuration's "domain_patterns" to include global domains (e.g., nike.com, nike.co.uk, nike.com.au, etc.) and broaden the "html_contains" array to remove or make optional the region-specific "prod-assets.nike.in" token (or replace with region-agnostic markers like "__PRELOADED_STATE__" and "skuData"); if the intent is India-only, add a comment to the nike config noting it is intentionally region-scoped to avoid accidental global matching changes.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_llm_runtime.py around lines 284 - 288, The test is missing a mock for store_cached_llm_result so an invalid cache write could go unnoticed; add a monkeypatch for store_cached_llm_result (similar to fake_load_cached_llm_result) that is an async function which raises an AssertionError if called (or otherwise asserts), and set it via monkeypatch.setattr("app.services.llm_tasks.store_cached_llm_result", <async-guard-fn>) so the test fails if the code attempts to cache invalid payloads.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_shared_variant_logic.py around lines 244 - 267, The test test_variant_select_groups_reject_style_control_selects assumes iter_variant_select_groups returns a list but its name implies an iterator; verify the actual return type and update the test: if iter_variant_select_groups yields a generator/iterator, wrap the call in list(iter_variant_select_groups(soup)) in the assertion so it compares to [] correctly, otherwise keep the direct comparison; also add a brief docstring to the test matching the style of other tests in the file describing the purpose of the case.

- Verify each finding against the current code and only fix it if needed.

In @docs/INVARIANTS.md around lines 145 - 146, Update the sentence to state an absolute prohibition: replace the current phrasing with a clear rule such as "If diagnostics_profile.capture_screenshot is False, browser acquisition must not capture any screenshots, regardless of outcome." Ensure the text references the diagnostics_profile.capture_screenshot flag and aligns with the violation signature "Browser acquisition captures a screenshot when capture_screenshot=False" so there is no ambiguity about allowable exceptions.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/runs/page.tsx around lines 192 - 195, Remove the accidental text node (leading whitespace) before the Plus icon in the Button render so it doesn't produce a visible gap; locate the JSX for the Button (the Button component with className "h-[var(--control-height)]" and the Plus icon usage <Plus className="size-3.5"/>), delete the space/newline between the opening tag and <Plus so the icon is the first child (e.g., change "> <Plus" to "><Plus") and ensure no extra text nodes remain before "New Crawl".

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/crawl/crawl-run-screen.tsx around lines 167 - 176, The reducedPayload construction omits the required data field from records (type ProductIntelligencePrefillPayload expects Pick<CrawlRecord, "id" | "run_id" | "source_url" | "data">), which can break the /product-intelligence consumer; either make data optional on the type (e.g., change ProductIntelligencePrefillPayload records to Pick<CrawlRecord, "id" | "run_id" | "source_url"> & { data?: CrawlRecord["data"] }) or update the reducedPayload mapping to include a data property (e.g., data: {} or an appropriate empty value) for each record so reducedPayload.records always contains data. Ensure changes reference reducedPayload and ProductIntelligencePrefillPayload (and CrawlRecord) consistently.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/data/prompts/product_intelligence_enrichment.user.txt around lines 25 - 33, The schema's reason_updates currently defined as a single object will drop multiple SerpAPI conflicts; change reason_updates from an object to an array of objects (e.g., "reason_updates": [ { "reason_name": ..., "reason_code": ..., ... } ]) so multiple conflict entries can be recorded; update the example usage to wrap the example conflict in an array and change the prose/example that currently says "empty object" to state "empty array" to reflect the new type; ensure field keys (reason_name, reason_code, description, source, timestamp, conflicting_value, resolution_action) remain inside each array element.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/data/prompts/product_intelligence_enrichment.user.txt at line 42, The prompt sentence "Prefer identifiers over titles. Prefer extracted candidate facts over SerpAPI snippets. Do not overwrite extracted brand, price, SKU, MPN, GTIN, URL, or availability." is ambiguous — update the prompt (product_intelligence_enrichment.user.txt) to explicitly enumerate the protected fields and where they live: add a protected_fields list containing "brand, price, sku, mpn, gtin, url, availability" and reference whether those values come from the input record or a prior extraction; also clarify "do not overwrite" as a rule to never replace non-empty input/extracted values (e.g., when populating the output schema) and instruct the agent to only fill those fields when they are empty or confirmed more accurate. Ensure the output schema section in the same prompt clearly includes these field names (or a mapping to input fields) so the rule is unambiguous.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/product_intelligence/matching.py around lines 268 - 276, The _currency_from_price function mixes a symbol ("$") with ISO codes ("EUR", "GBP"); update it to return consistent ISO codes for all currencies (e.g., "USD", "EUR", "GBP") by mapping "$" -> "USD", "€" -> "EUR", "£" -> "GBP" and keep the fallback as an empty string; modify the return values in _currency_from_price accordingly so consumers always receive ISO currency codes.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/product_intelligence/service.py around lines 372 - 375, The loop over discovered_payloads incorrectly maps missing source_index to 0; update the logic in the block handling candidate_payload (the for loop using source_product_ids_by_index and source_index) to explicitly check for the presence of "source_index" (e.g., if "source_index" not in candidate_payload or candidate_payload.get("source_index") is None: continue) instead of using int(... or 0), parse and validate the index only when present, and only then call source_product_ids_by_index.get(parsed_index) so candidates without a source_index are skipped rather than defaulting to the first source.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_product_intelligence.py around lines 464 - 499, Replace the direct mutation of product_intelligence_settings.candidate_poll_seconds in test_product_intelligence_candidate_poll_marks_timeout with the monkeypatch fixture: use the test's monkeypatch to set product_intelligence_settings.candidate_poll_seconds to 0.0 before calling _poll_candidate_and_score and rely on monkeypatch to restore it automatically; update the test signature to accept monkeypatch and remove the try/finally block so the change is isolated and safe for parallel test runs.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Screenshot capture is requested but the result is discarded.
   Path: backend/app/services/acquisition/acquirer.py
   Lines: 133-133

2. logic error: The time-budget check happens after one extra click and wait.
   Path: backend/app/services/acquisition/browser_detail.py
   Lines: 293-293

3. logic error: Screenshot timing can disappear from diagnostics when capture is skipped or fails.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 118-118

4. performance: Enabling screenshots by default changes existing fetch calls to incur extra capture overhead.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 1098-1098

5. logic error: Fallback variant generation can fabricate non-existent product combinations.
   Path: backend/app/services/adapters/amazon.py
   Lines: 263-263

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.