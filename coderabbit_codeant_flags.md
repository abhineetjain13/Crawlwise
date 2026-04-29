Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/cookie_store.py around lines 707 - 710, The path-match logic in the cookie filter is too permissive and can match prefixes like "/foo" with "/foobar"; add a helper _cookie_path_matches(request_path: str, cookie_path: str) implementing RFC 6265 §5.1.4 (return True if paths are identical, or cookie_path is a prefix and either cookie_path ends with "/" or the next char in request_path after the cookie_path prefix is "/"), then replace the existing path check in the loop (the branch using cookie_path.rstrip("/") or "/") with a call to _cookie_path_matches(request_path, cookie_path) while keeping the host/domain check that uses _cookie_domain_matches.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/adapters/amazon.py around lines 250 - 256, The helper _detail_value_from_table currently calls self._detail_table(parser) on each lookup causing repeated DOM traversal; change its signature from _detail_value_from_table(self, parser, label) to _detail_value_from_table(self, detail_table: dict, label: str) and update its implementation to search the provided detail_table (matching normalized_key to target) instead of calling _detail_table; compute detail_table once by calling self._detail_table(parser) before extracting asin and other fields (reorder so detail_table is available) and update all call sites (e.g., the asin extraction and other places referencing _detail_value_from_table) to pass the precomputed detail_table.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/_export_data.py around lines 49 - 52, The dict comprehension in _export_data currently iterates all payload.items() and thus returns the internal "_export_provenance" entry; change the comprehension to skip that metadata key (e.g. only include items where name != "_export_provenance" or name not in a small exclude set) so callers receive only actual config keys, still decoding values with _decode_export_value for the included names.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.exports.json around lines 1384 - 1385, The current DETAIL_PRICE_JSONLD_PATTERN allows an optional opening quote but not an optional closing quote, so update the regex for DETAIL_PRICE_JSONLD_PATTERN to handle quotes symmetrically (either require both quotes or allow both to be absent); specifically modify the pattern referenced as DETAIL_PRICE_JSONLD_PATTERN to consume an optional closing quote after the captured price (e.g., make the terminal \"? symmetrical to the opening one) or replace it with a stricter quoted-only variant if you want to enforce JSON-compliant strings.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py at line 113, Add the missing constant DETAIL_DOCUMENT_LINK_LABEL_PATTERNS to the module export list __all__; update the __all__ sequence so DETAIL_DOCUMENT_LINK_LABEL_PATTERNS appears between DETAIL_CURRENT_PRICE_SELECTORS and DETAIL_EXPAND_KEYWORD_EXTENSIONS (preserving alphabetical order) to ensure it is exported for from extraction_rules import *.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/detail_extractor.py around lines 511 - 522, The code currently calls _sanitize_ecommerce_detail_record explicitly before calling repair_ecommerce_detail_record_quality, but repair_ecommerce_detail_record_quality already invokes _sanitize_ecommerce_detail_record internally; remove the explicit call to _sanitize_ecommerce_detail_record (the lines invoking it with record, page_url, requested_page_url) so that only repair_ecommerce_detail_record_quality(record, html="", page_url=page_url, requested_page_url=requested_page_url) handles sanitization and quality repair for ecommerce_detail surfaces.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/variant_record_normalization.py around lines 658 - 666, The current logic replaces record["selected_variant"] whenever selected_identity is not found in kept_identities, which also triggers when selected_identity is None and thus overwrites a possibly meaningful identity-less selected_variant; update the check so you only replace the selected_variant when selected_identity is not None and not present in kept_identities (i.e., compute selected_identity using variant_identity(selected_variant) as you do now, then change the conditional to require selected_identity is not None AND selected_identity not in kept_identities) so identity-less selected_variant objects are preserved.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/js_state_mapper.py around lines 548 - 572, The price fallback mixes formats: _raw_current_price_value/_raw_original_price_value can return currency-qualified strings while normalize_price returns normalized numeric strings; ensure both paths produce the same format by passing the raw_* result through the same normalization step (or by adapting normalize_price to accept and normalize currency-qualified strings). Update the price and original_price assignments (where variant_attribute, _raw_current_price_value, _raw_original_price_value, normalize_price, base.get and shopify_like are used) to normalize raw_* outputs before assigning so both fallback branches yield consistent formatted prices.

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/crawl/shared.tsx around lines 535 - 557, getLogIcon and getLogIconStyle evaluate message conditions in different orders so the icon (getLogIcon) and color (getLogIconStyle) can mismatch for the same message; fix by making the condition order identical in both functions (getLogIcon and getLogIconStyle): move the http/https check to after the more specific checks for "challenge/blocked/captcha/bot check" and "page loaded"/"page load", and replace the broad msg.includes("http") with a stricter check (e.g., msg.includes("https://") or a URL regex) so URL matching does not override more specific phrases like "page loaded" or "blocked".

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/crawl/shared.tsx around lines 601 - 614, The function logMessageIsError currently does a case-sensitive check using level === "error" which misses uppercase variants; update the check to normalize level (e.g., String(level).toLowerCase()) and compare against "error" so values like "ERROR" or "Error" are detected, while preserving the existing guard that returns false for any other truthy level; keep the rest of the text-based heuristics unchanged and ensure level is handled safely when null/undefined.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_dom_extractor.py around lines 104 - 114, The canonical link extraction uses canonical.get("href") which may return None; update the block around the canonical variable to check that canonical has a non-empty href before calling absolute_url and add_sourced_candidate — e.g., retrieve href = canonical.get("href") (or canonical.attrs.get("href")), verify href is truthy (not None/empty), then call absolute_url(page_url, href) and pass the result into add_sourced_candidate; ensure the checks are applied in the same scope where canonical, absolute_url, and add_sourced_candidate are used so you avoid passing None into absolute_url.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_dom_extractor.py around lines 196 - 207, The check calling surface.startswith("job_") can raise AttributeError when surface is None; update the condition to guard/normalize surface (e.g., use str(surface or "") or check if surface is truthy) before calling startswith so the branch safely executes; adjust the condition around the existing block that uses body_text, candidates, fields and add_sourced_candidate to use the normalized_surface variable or an explicit is not None check to prevent AttributeError.

- Verify each finding against the current code and only fix it if needed.

In @output_issues.md around lines 5 - 89, Split each multi-concern review item into separate, atomic tasks and add a priority label and category for each (e.g., [CRITICAL] Data Quality: price parsing, [MAJOR] Schema Compliance: remove UI keys). For entries that reference scraper/adapter behavior, create one task for parsing/fixing prices (look for extractVariants, parseVariantPrice, selected_variant, buildProductObject), one for image/gallery fixes (additional_images, image_url), one for variant axes/normalization (variant_axes, variants, option_values, size, color, selected_variant), and one for adapter/page validation (amazonAdapter, parseProductPage, extractProductData, validateProductFields); ensure each new task lists the exact symbol(s) to change, the single expected change, and a test/verification step. Also add severity tags ([CRITICAL]/[MAJOR]/[MINOR]) and group tasks under categories like Data Quality, Schema Compliance, and Extraction Validation so reviewers and implementers can prioritize and verify fixes independently.

These are comments left during a code review. Please review all issues and provide fixes.

1. resource leak: Rolling back and then reusing the same session in failure recovery can lose the run state and break recovery logging.
   Path: backend/app/services/_batch_runtime.py
   Lines: 118-118

2. logic error: Legitimate expanders in page chrome are now skipped, leaving some detail content unexpanded.
   Path: backend/app/services/acquisition/browser_detail.py
   Lines: 227-227

3. logic error: Expandable controls inside sidebars are now over-filtered and may never be clicked.
   Path: backend/app/services/acquisition/browser_detail.py
   Lines: 275-275

4. logic error: The location-gate detector can miss real interstitials and misclassify them as usable content.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 933-933

5. logic error: Failed dismissal attempts are reported as not found, hiding that the interstitial is still blocking the page.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 958-958

6. possible bug: Adding a new required diagnostics parameter and outcome state breaks the existing builder contract.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 847-847

7. resource leak: Popup-guard task registry can accumulate stale task references.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 126-126

8. logic error: Passing a full URL into the domain lookup can prevent cookie memory from being found.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 179-179

9. possible bug: Host-only cookies can be skipped when exporting the Cookie header.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 691-691

10. logic error: Best-effort DOM fallback changes the function’s HTML contract and can return non-equivalent page markup
   Path: backend/app/services/acquisition/dom_runtime.py
   Lines: 72-72

11. logic error: Generic 403/429 responses now incorrectly force browser-first mode for unrelated hosts.
   Path: backend/app/services/acquisition/host_protection_memory.py
   Lines: 171-171

12. logic error: CAPTCHA pages can be misclassified as usable content by the new detail-signal heuristic
   Path: backend/app/services/acquisition/runtime.py
   Lines: 272-272

13. possible bug: Weak detail heuristic can treat short shell pages as real product pages
   Path: backend/app/services/acquisition/runtime.py
   Lines: 548-548

14. logic error: Duplicate cookie headers can cause inconsistent authentication on curl requests
   Path: backend/app/services/acquisition/runtime.py
   Lines: 437-437

15. logic error: Normalizing price text too aggressively can strip currency context and produce incorrect currency extraction.
   Path: backend/app/services/adapters/amazon.py
   Lines: 143-143

16. type error: Mixing raw numeric and normalized prices across Nike product sources breaks adapter output consistency.
   Path: backend/app/services/adapters/nike.py
   Lines: 254-254

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.
