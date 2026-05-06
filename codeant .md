Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_runtime.py around lines 335 - 341, The current list comprehension over REAL_CHROME_IGNORE_DEFAULT_ARGS can raise a TypeError if that constant is None; update the comprehension to defensively iterate over (REAL_CHROME_IGNORE_DEFAULT_ARGS or ()) so None becomes an empty iterable, then build ignore_default_args the same way and only set launch_kwargs["ignore_default_args"] when non-empty (symbols: REAL_CHROME_IGNORE_DEFAULT_ARGS, ignore_default_args, launch_kwargs).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/extraction_rules.py around lines 337 - 344, The four depth constants are redundant and confusing; consolidate them by keeping a single canonical constant (choose either VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT or DEFAULT_VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH) and remove the duplicates (e.g., drop one of VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT / DEFAULT_VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH and ensure VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK remains if it has a distinct semantic use). Update all references in the module (and any imports) to use the chosen canonical name (e.g., replace uses of DEFAULT_VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH with VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT or vice versa), and ensure VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH (the value 6) remains only if it has a separate purpose; otherwise collapse it into the single chosen constant and adjust comments to reflect the consolidated intent.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/extraction_rules.py around lines 251 - 258, DETAIL_TEXT_SCOPE_SELECTORS may contain duplicate "main" when DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR equals "main"; update the assignment to deduplicate entries (similar to HYDRATED_STATE_PATTERNS) by building the sequence from the desired values and then removing duplicates via dict.fromkeys or an equivalent deduplication step before converting back to a tuple. Ensure you reference the existing variables (_STATIC_EXPORTS.get("DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR", "main"), "main", "article", "[role='main']", "[class*='product-main' i]", "[class*='product-content' i]") and produce a final tuple assigned to DETAIL_TEXT_SCOPE_SELECTORS with duplicates removed.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/data_enrichment/service.py around lines 1119 - 1172, The recursive flatteners (_flatten_dict_values, _flatten_list_values, _flatten_targeted_dict_values, _flatten_targeted_list_values) lack a recursion depth limit; add an optional max_depth:int parameter (default e.g. 50) to each function, decrement it on each recursive call and stop recursing when max_depth <= 0 (either return remaining items unchanged/empty or raise a ValueError), and propagate the parameter through all internal calls so every invocation of _flatten_* passes the updated max_depth to nested calls to prevent stack overflows on maliciously deep input.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/data_enrichment/service.py around lines 754 - 766, The current implementation recompiles regexes on every call: update caching so `_compiled_material_strip_patterns()` does not recompile each time (restore `@lru_cache` or use a module-level cached tuple) and have `_material_strip_patterns()` return that cached value; ensure the cache is based on `DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS` (the config constant) and keep the same error-handling behavior (logging invalid patterns), since `_strip_material_context_noise` invoked inside `_normalize_materials` relies on repeated accesses.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/data_enrichment/shopify_catalog.py around lines 452 - 461, The type annotation for function category_attribute_match_tokens is redundant: replace the union return type parameter dict[str, object] | dict[str, Any] with the simpler dict[str, Any]; update the function signature to def category_attribute_match_tokens(item: dict[str, Any]) -> set[str] so callers and static checkers use the single subsuming type (function name: category_attribute_match_tokens).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/data_enrichment/shopify_catalog.py around lines 69 - 71, The function string_iterable filters based on str(item).strip() but returns the untrimmed str(item), so preserve-consistent trimming by returning str(item).strip() instead of str(item); update the implementation of string_iterable (which uses object_iterable) to map to stripped values while keeping the same filter condition to exclude whitespace-only strings.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_dom_extractor.py around lines 404 - 412, The helper _visible_node_text repeatedly creates a new BeautifulSoup from str(node) which is expensive when called many times from _variant_choice_entry_value; change it to reuse the existing parsed node or a cached parse: detect if node is already a BeautifulSoup/bs4.element.Tag and operate on it directly (use node.select(...) and node.get_text(...)) instead of re-parsing, or add a small memoization keyed by the node object (e.g., id(node)) to return previously computed visible text so repeated calls in _variant_choice_entry_value reuse the result; update only _visible_node_text (and add a simple cache structure if chosen) and keep the same return behavior.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_dom_extractor.py around lines 1296 - 1309, Remove the now-unused index-based fallback dead code: delete the index_fallback_allowed variable and the conditional branch that checks it (the "if existing_row is None and index_fallback_allowed:" block) in the loop over dom_variant_rows, and simplify the logic to only use existing_by_key and merge_variant_pair (or dom_row) when resolving existing_row; keep references to merged_rows, dom_variant_rows, existing_by_key, existing_by_index and merge_variant_pair so the intent and behavior remain clear.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_dom_extractor.py around lines 529 - 531, Remove the redundant local imports of absolute_url in detail_dom_extractor.py: delete the inner "from app.services.field_value_core import absolute_url" occurrences and use the module-level imported absolute_url (already imported near the top) wherever it's called (the two places that currently return absolute_url(page_url, url)); ensure no other local shadowing remains and run tests to confirm imports resolve.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_identity.py around lines 248 - 269, The hardcoded list of job path markers used in the any(...) check should be extracted into a shared config constant (e.g., JOB_POSTING_PATH_MARKERS) under app/services/config/ and imported into detail_identity.py; replace the tuple literal in the any(...) generator with that constant (ensuring it is an iterable of strings) so the check becomes any(marker in parsed.path for marker in JOB_POSTING_PATH_MARKERS) and update imports accordingly to reuse the centralized config like other marker sets (e.g., JOB_LISTING_DETAIL_PATH_MARKERS).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_identity.py around lines 145 - 147, Replace the broad "except Exception" that wraps the URL structural check with a narrow exception handler that only catches expected parsing errors (for example "except ValueError as e:" or "except (ValueError, urlparse.ParseError) as e:"), keep the logger.debug("URL structural check failed for %s", page_url, exc_info=True) call inside that specific except and return False there, and let all other exceptions (AttributeError, TypeError, etc.) propagate (or re-raise them) so you don’t silently swallow programming errors in the try/except block around the URL structural check.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_price_extractor.py around lines 923 - 934, The module exports list (__all__) includes reconcile_detail_price_magnitudes but the helper reconcile_parent_price_against_variant_range is not exported; decide whether it's public or private: if it should be public, add "reconcile_parent_price_against_variant_range" to the __all__ list alongside the other exported symbols; if it should be internal, rename the function to _reconcile_parent_price_against_variant_range and update any internal references (calls from reconcile_detail_price_magnitudes or tests) to the new name so the code and export intent remain consistent.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_raw_signals.py around lines 329 - 338, The current loop removes every H1 that doesn't match a pruned product name, which can accidentally strip valid extra H1s; change the condition to be explicit: compute h1_text via the existing _norm(h1.get_text(...)) and only call h1.decompose() when h1_text is non-empty AND h1_text not in pruned_norms (i.e., replace the current continue/decompose pattern with an explicit if h1_text and h1_text not in pruned_norms: h1.decompose()), keeping the references to pruned_product_names, _norm, pruned_norms, soup.find_all("h1"), h1_text, and h1.decompose().

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_record_finalizer.py around lines 518 - 523, The local identity_url is redundant because _sanitize_ecommerce_detail_record already resolves requested_page_url internally; remove the identity_url variable and call _sanitize_ecommerce_detail_record with the original requested_page_url (e.g. _sanitize_ecommerce_detail_record(record, page_url=page_url, requested_page_url=requested_page_url)), letting the function perform resolution, and remove any dead code related to identity_url to avoid duplicated semantics in _sanitize_ecommerce_detail_record.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_record_finalizer.py around lines 1054 - 1084, The noise token set hard-coded in _detail_image_family_tokens should be moved to a configuration constant in app/services/config/extraction_rules.py (e.g., IMAGE_FAMILY_NOISE_TOKENS) and imported into this module; update _detail_image_family_tokens to read the noise set from that constant instead of the inline noise variable, keep the filtering logic and minimum segment length intact, and add a unit-test or ensure existing tests import the config constant to validate behavior when tokens change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_record_finalizer.py around lines 912 - 926, The hardcoded image path tokens in _detail_path_looks_like_image_asset should be moved into the extraction rules config: create (or add) a list like IMAGE_PATH_TOKENS in app/services/config/extraction_rules.py, import that constant into detail_record_finalizer and replace the literal tuple in _detail_path_looks_like_image_asset with a reference to IMAGE_PATH_TOKENS (ensure you handle missing config by falling back to the previous default list); keep the regex check as-is and only swap the hardcoded tokens for the configurable variable so the function uses the config-provided tokens at runtime.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_record_finalizer.py around lines 148 - 149, Replace the hardcoded set {"category", "categories", "uncategorized"} in detail_record_finalizer.py with a config constant: add CATEGORY_PLACEHOLDER_VALUES (all lowercased) to app.services.config.extraction_rules.py (next to CANDIDATE_PLACEHOLDER_VALUES), import it into detail_record_finalizer.py, and change the check to if category.lower() in CATEGORY_PLACEHOLDER_VALUES: record.pop("category", None) so the noise tokens live in config rather than service code.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_record_finalizer.py around lines 365 - 385, The _materials_value_looks_like_org_name function contains hardcoded material keywords and org suffix tokens; move those token lists into config constants in app/services/config/extraction_rules.py (e.g., MATERIAL_KEYWORDS and ORG_SUFFIXES), update extraction_rules.py to expose them, and then import and use those constants in detail_record_finalizer._materials_value_looks_like_org_name (replace the inline tuple and regex word list with the config values, constructing the regex from ORG_SUFFIXES). Ensure the function still performs the same lowercasing, membership check against MATERIAL_KEYWORDS, and the regex/org-name fullmatch logic using the injected ORG_SUFFIXES.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 582 - 620, The function detail_long_text_chunk_is_other_product contains hardcoded thresholds and prefixes—extract the word-count bounds (3, 14), token-length thresholds (4, 5) and the prefix list ("official ", "shop for ") into config constants (e.g. LONG_TEXT_MIN_WORDS, LONG_TEXT_MAX_WORDS, TOKEN_MIN_LEN_DISTINCTIVE, TOKEN_MIN_LEN_CHUNK, LONG_TEXT_PREFIXES) placed under app/services/config/*; update the function to read those constants instead of literals and keep existing logic that uses detail_product_text_tokens, cross_product_text_type_tokens, cross_product_text_generic_tokens and detail_long_text_chunk_has_product_name_shape unchanged (just reference the new config names and import them).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 533 - 543, The hardcoded literal checks in detail_long_text_chunk_is_legal_tail should be moved into a config collection under app/services/config/extraction_rules and the function should use that collection; create a new constant (e.g., DETAIL_LEGAL_TAIL_PATTERNS) holding the string patterns ("product safety", "powered by product details have been supplied by the manufacturer", "view more", "privacy" & "policy", and contact/customer-service indicators) and import it into detail_text_sanitizer.py, then refactor detail_long_text_chunk_is_legal_tail to consult that collection for substring matches while keeping the existing digit-check logic for "customer service" and "contact " and the exact match for "view more".

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 437 - 449, Cache and preprocess DETAIL_LONG_TEXT_UI_TAIL_PHRASES at module import time into a module-level tuple (e.g., long_text_ui_tail_phrases) by running clean_text(...).lower() and filtering out empty results (same pattern as fulfillment_only_long_text_phrases), then update the _strip_long_text_ui_tail function to iterate over that cached long_text_ui_tail_phrases instead of converting DETAIL_LONG_TEXT_UI_TAIL_PHRASES to a tuple on every call; ensure comparisons still use cleaned/lowered variants and preserve the existing behavior of returning "" when the whole text matches a phrase and trimming the trailing phrase otherwise.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_card_fragments.py around lines 327 - 329, The media CSS selector used in _node_has_listing_media is hardcoded; move it into app/services/config/selectors.py as a named constant (e.g., LISTING_MEDIA_SELECTOR), then import that constant into listing_card_fragments.py and replace the inline string in the call to listing_node_css with the constant. Update any relevant imports and ensure _node_has_listing_media(node) calls listing_node_css(node, LISTING_MEDIA_SELECTOR) so the selector lives in the config module.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_card_fragments.py around lines 292 - 293, Add the hardcoded tokens "newsletter" and "whatsapp" into the shared config constant LISTING_UTILITY_TITLE_TOKENS in app/services/config/extraction_rules.py, then remove the inline strings from listing_card_fragments.py and import/use LISTING_UTILITY_TITLE_TOKENS there instead; ensure any references in the function or class that iterates or matches title tokens (e.g., where LISTING_UTILITY_TITLE_TOKENS is used) treat the new tokens consistently (same casing/normalization) as the existing entries.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_card_fragments.py around lines 224 - 243, The hardcoded weak selector strings in listing_selector_is_weak should be moved into a config constant (e.g., WEAK_SELECTOR_PATTERNS) in the config module (app/services/config/selectors.py or app/services/config/extraction_rules.py) and imported into this service; update listing_selector_is_weak to normalize the selector and check normalized == ".product" or any(token in normalized for token in WEAK_SELECTOR_PATTERNS), remove the inline tuple, and add/update tests or usages to refer to the new constant; ensure the config file exports a clear name (WEAK_SELECTOR_PATTERNS) so the function can import it.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_card_fragments.py around lines 331 - 348, The _node_has_detail_like_link function uses hardcoded tokens, prefixes and a fixed anchor scan limit; move those values into the extraction_rules config module as named constants (e.g., JOB_HREF_TOKENS, PRODUCT_HREF_TOKENS, HREF_IGNORE_PREFIXES, ANCHOR_SCAN_LIMIT), import them into this service, replace the inline tuples ("/job/...", "/products/..." etc.), the ["#", "javascript:"] check and the anchors[:6] slice with the config constants, and keep existing calls to listing_node_css and _listing_href_is_structural; also add sensible defaults or fallback logic when the config entries are missing.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_card_fragments.py around lines 60 - 116, Replace hardcoded numeric thresholds inside base_listing_fragment_score with named constants imported from app.services.config.extraction_rules: e.g., NEGATIVE_TAG_SCORE, NEGATIVE_SIGNATURE_SCORE, POSITIVE_SIGNATURE_BONUS, LINK_ZERO_SCORE, LINK_ONE_BONUS, LINK_SMALL_BONUS, LINK_MEDIUM_PENALTY, LINK_LARGE_PENALTY, TEXT_TOO_SHORT_PENALTY, TEXT_NORMAL_BONUS, TEXT_TOO_LONG_PENALTY, PRICE_BONUS, CARD_TAG_BONUS, STRONG_CARD_BONUS, and TEXT_LENGTH_LIMIT (or similarly descriptive names). Update base_listing_fragment_score to import and use these identifiers instead of -100, -10, 6, 4, 2, -1, -6, -3, 3, 12, 2000, and ensure the config file documents each constant with its purpose so thresholds can be tuned without changing service code.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_card_fragments.py around lines 219 - 222, Extract the hardcoded regex string from _PRICE_HINT_RE and move it into the extraction rules config module as a named constant (e.g., PRICE_HINT_PATTERN) in the extraction rules config; then in listing_card_fragments replace the inline pattern with _PRICE_HINT_RE = re.compile(config.PRICE_HINT_PATTERN, re.I) (import the config symbol), ensuring the exact pattern (currency symbols and number formats) is preserved; update any references to _PRICE_HINT_RE to use the compiled regex and add a small comment in the config explaining the pattern purpose for regional updates.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/shared_variant_logic.py around lines 468 - 483, The check `if not ints:` in _is_sequential_integer_run is unreachable because the preceding guard ensures len(values) >= 5 and the loop either appends to ints for each digit-only value or returns False immediately on a non-digit; remove the redundant `if not ints:` branch from _is_sequential_integer_run to simplify the function and rely on the existing logic that guarantees ints is non-empty before sorting and range-checking.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/shared_variant_logic.py around lines 637 - 644, The inline CSS selector string _swatch_button_selectors and the hardcoded slice limit 20 should be moved to a config module as constants (suggest names VARIANT_SWATCH_BUTTON_SELECTOR and VARIANT_SWATCH_BUTTON_SLICE_LIMIT), then import and use them in this file: replace the local _swatch_button_selectors definition with the imported VARIANT_SWATCH_BUTTON_SELECTOR and replace the btn_slice creation logic (all_btns[:20] if len(all_btns) > 20 else all_btns) with a slice using VARIANT_SWATCH_BUTTON_SLICE_LIMIT (e.g., all_btns[:VARIANT_SWATCH_BUTTON_SLICE_LIMIT] or equivalent), keeping the existing behavior but sourcing values from config.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/shared_variant_logic.py around lines 590 - 606, The code uses many hardcoded numeric thresholds (e.g., 4, 8, 20, 24, 4, 6, 3, 12, 32) across functions like iter_variant_select_groups, iter_variant_choice_groups, _nearby_variant_group_name, and resolve_variant_group_name; extract these magic numbers into named constants in a central extraction_rules module (e.g., MAX_VARIANT_GROUPS, MAX_CHOICE_GROUPS, SLICE_SIZE, TRAVERSAL_DEPTH, VALIDATION_THRESHOLD, etc.), import those constants into shared_variant_logic.py, replace the inline literals with the constants, and keep existing behavior by preserving the current values as defaults; update any unit tests or callers that rely on the numeric values to use the new constants where necessary.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/variant_record_normalization.py around lines 108 - 119, The second call to _enforce_variant_currency_context appears redundant because _enforce_variant_currency_context is already called before _backfill_variant_prices_from_record and the backfill only sets currency when currency is empty, so variants should already have parent_currency; remove the duplicate _enforce_variant_currency_context invocation after _backfill_variant_prices_from_record to simplify the flow (or, if you intended defensive idempotency, replace the duplicate call with a concise inline comment next to the first call explaining why a second enforcement is required and what invariants it preserves).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/variant_record_normalization.py around lines 701 - 707, The try/except chain around computing max_rows should defensively handle the last conversion too: wrap the final int(FALLBACK_MAX_VARIANT_ROWS) conversion in its own try/except and if it fails set max_rows = 1 (or another safe hardcoded default); update the block that references crawler_runtime_settings.detail_max_variant_rows, DEFAULT_DETAIL_MAX_VARIANT_ROWS and FALLBACK_MAX_VARIANT_ROWS so any TypeError/ValueError at the final fallback won't propagate and max_rows always ends up as an integer.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extraction_runtime.py around lines 711 - 742, The _best_nested_listing_items function currently uses hardcoded safety bounds (depth > 6 and list slicing [:10]) which should be configurable like crawler_runtime_settings.raw_json_surface_field_overlap_ratio; introduce configurable settings (either module-level constants or fields on crawler_runtime_settings) such as max_nested_depth and nested_list_scan_limit, defaulting to 6 and 10, update all occurrences in _best_nested_listing_items (the depth check and both [:10] slices) to use those settings, and pass surface through unchanged; ensure tests and any callers still work with the default values.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extraction_runtime.py around lines 341 - 366, The function _iter_listing_price_candidates currently uses hardcoded limits (depth > 4 and value[:200]); extract these magic numbers into configurable constants (e.g., LISTING_PRICE_CANDIDATE_MAX_DEPTH and LISTING_PRICE_CANDIDATE_MAX_ITER) in the existing config module and replace the literals with those constants, importing them at the top of the file; ensure the function uses LISTING_PRICE_CANDIDATE_MAX_DEPTH for the depth check and LISTING_PRICE_CANDIDATE_MAX_ITER for slicing the list to preserve current behavior while allowing adjustments via config.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extraction_runtime.py around lines 397 - 410, The hardcoded currency set inside _listing_candidate_price should be moved to a runtime config constant (e.g., CURRENCIES_TREATED_AS_CENTS) under app/services/config/* and imported where _listing_candidate_price is defined; replace the inline set {"AUD","CAD","EUR","GBP","NZD","USD"} with that config constant, update any tests or callers as needed, and add a short code comment next to the interpret_integral_as_cents check (or in the config constant's docstring) noting the 3-vs-4-digit boundary behavior so it’s explicit to future readers; ensure imports and config access follow existing config modules’ patterns (use the same symbol name you add in config and reference it in _listing_candidate_price and normalize_decimal_price call).

- 

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/field_value_core.py around lines 113 - 127, The _CURRENCY_CODE_PATTERN generator unnecessarily calls str() on values already guarded by isinstance(code, str); update the comprehension inside _CURRENCY_CODE_PATTERN to use len(code) instead of len(str(code)) and use re.escape(code) (or remove the outer str() there) so you don't convert strings redundantly while building the joined pattern.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/field_value_core.py around lines 946 - 955, The emission condition still checks for "flavor" even though earlier code moves a lone flavor into merged["color"] and removes merged["flavor"]; update the emission predicate in the block containing has_option_axis and the any(...) check to remove "flavor" from the tuple of field_names (leaving ("color","size")) or add a clarifying comment if you intentionally want to keep "flavor" for future cases; locate the logic around merged, text_or_none, and has_option_axis in field_value_core.py (the earlier block that copies merged["flavor"] to merged["color"]) and change the any(...) fields or add a comment accordingly to avoid the redundant check.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/field_value_dom.py around lines 1006 - 1047, _SECTION_LABEL_SELECTOR, _SECTION_CONTAINER_SELECTORS, and _SECTION_STOP_TAGS are hardcoded in field_value_dom but similar selectors come from config; move these constants into the shared config (add keys like SECTION_LABEL_SELECTOR, SECTION_CONTAINER_SELECTORS, SECTION_STOP_TAGS), export them alongside DETAIL_TEXT_SCOPE_SELECTORS/FEATURE_SECTION_SELECTORS, then replace the in-file definitions with imports and use the imported names in functions that reference _SECTION_LABEL_SELECTOR, _SECTION_CONTAINER_SELECTORS, and _SECTION_STOP_TAGS; ensure defaults or backwards-compatible values are provided in the config and update any unit tests or callers that assume the local constants.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/field_value_dom.py around lines 1048 - 1068, Move the hardcoded tuple _MATERIAL_TEXT_HINTS out of field_value_dom and into a config module under app/services/config (e.g. a materials config file), export it as a named config constant, and replace the in-file tuple with an import of that config constant; update any references in field_value_dom to use the imported config symbol so material keywords can be tuned per vertical/site without changing service code.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/field_value_dom.py around lines 866 - 867, Replace the hardcoded limit 12 with the configured limit variable _max_selector_matches to keep behavior consistent: change the condition "if len(values) >= 12: break" to use self._max_selector_matches (or _max_selector_matches if in a static/context where self isn't available) in the function containing that code, and make the same replacement in the filter_values_by_regex function where a similar "12" is used so both places read the configured limit instead of the magic number.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/field_value_dom.py around lines 272 - 275, The tuples _WIDTH_NAMES and _HEIGHT_NAMES are being rebuilt on every call to image_candidate_score despite depending only on the module-level frozenset _CDN_IMAGE_QUERY_PARAMS; move their computation to module scope (e.g. define _WIDTH_PARAM_NAMES and _HEIGHT_PARAM_NAMES right after _CDN_IMAGE_QUERY_PARAMS) and then update image_candidate_score to call _int_param(*_WIDTH_PARAM_NAMES) and _int_param(*_HEIGHT_PARAM_NAMES) instead of recreating the tuples each call.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/field_value_dom.py at line 113, The tuple _PAGE_FILE_EXTENSIONS is hardcoded in field_value_dom.py; move it into the shared config module (e.g., extraction_rules.PAGE_FILE_EXTENSIONS), remove the local _PAGE_FILE_EXTENSIONS definition, add an import for PAGE_FILE_EXTENSIONS in field_value_dom, and update any uses of _PAGE_FILE_EXTENSIONS to reference PAGE_FILE_EXTENSIONS so the value lives with other extraction rules and tunables.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/js_state_mapper.py at line 134, The file defines a public alias map_configured_state_payload pointing to a supposedly private function _map_configured_state_payload, causing inconsistent naming; either make the function genuinely public by renaming _map_configured_state_payload to map_configured_state_payload (and update any references/imports) or remove the alias and keep the underscore-prefixed name for internal use (also update __all__ or export lists if present) so the module's public API naming is consistent.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/js_state_mapper.py at line 206, The hardcoded slice limit "8" at the return of the deduped list should be moved to config: add a constant (e.g. JS_STATE_MAX_PRODUCT_PAYLOADS = 8) in your config module (suggested: app/services/config/field_mappings.py) and replace the inline literal with deduped[:JS_STATE_MAX_PRODUCT_PAYLOADS]; update any imports in js_state_mapper.py to import that constant and ensure tests or callers use the config value instead of the hardcoded number.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/js_state_mapper.py around lines 946 - 960, This block duplicates the axis name list already defined as variant_axis_keys earlier; extract that list to a single module-level constant (or reuse the existing variant_axis_keys) and replace the inline tuple in the fallback branch with that constant to avoid two sources of truth—update any other references (e.g., the code iterating over ("color","size",...)) to iterate over the new constant and ensure the constant name is exported/visible where this function (the fallback branch in js_state_mapper.py that uses variant.get and _display_option_value) runs.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/js_state_mapper.py around lines 607 - 618, In _discounted_percentage_price, remove the unreachable ZeroDivisionError from the except clause (the divisor is the constant 100.0) and only catch TypeError/ValueError when parsing numeric values; also add a brief inline comment next to the ("Dis",) key to explain that "Dis" is the platform-specific discount-percentage field (e.g., "platform discount %") so future readers understand its meaning.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/llm_provider_client.py around lines 83 - 107, The three shared client accessors (_shared_anthropic_client, _shared_nvidia_client, _shared_aws_client) mutate module globals without synchronization causing race conditions; add per-provider asyncio locks (e.g. _anthropic_client_lock, _nvidia_client_lock, _aws_client_lock) at module scope and wrap the body of each accessor in an "async with <lock>:" block mirroring the pattern used by _shared_groq_client so only one coroutine can call _refresh_shared_client for that provider at a time, preserving and returning the module-level client and timeout safely.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/normalizers/__init__.py around lines 32 - 38, The regex for currency context (_CURRENCY_CONTEXT_RE) currently hardcodes keywords; move those tokens into the existing config module that already exports CURRENCY_CODES by adding a new constant (e.g., CURRENCY_CONTEXT_KEYWORDS or CURRENCY_CONTEXT_PATTERN) there, then import that constant into this module and rebuild _CURRENCY_CONTEXT_RE to use rf"{_CURRENCY_CODE_CONTEXT_PATTERN}|{CURRENCY_CONTEXT_PATTERN}" with the same anchors/word boundaries and re.I flag so behavior is unchanged; ensure the config string is properly escaped/anchored (including the "starting(?:\s+at)?" fragment) and update the import list to reference the new config symbol.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py around lines 364 - 397, Capture the returned record from extract_records(...) into a variable and add assertions that verify the deep-merge behavior: assert that record["variant_axes"] contains the adapter-provided "size" axis plus the parsed "color" axis (e.g. {"size": ["S","M"], "color": ["black","olive"]}), and assert that record["selected_variant"] preserved adapter values (e.g. selected_variant["sku"] == "TRAIL-S" and selected_variant["option_values"] == {"size": "S"}); update the test function test_extract_records_deep_merges_structured_variant_fields_across_tiers to use these assertions so the test validates merging rather than only ensuring no exception.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py around lines 346 - 361, The test test_selector_synthesis_keep_worthy_tags_round_trip_through_export uses brittle path construction via Path(__file__).parents[2] to locate selectors.exports.json; replace that with a robust project-root resolution (e.g., use an existing test fixture or helper that finds the repo root by walking up for a marker file like pyproject.toml/README or use package resource loading) so load_export_data reads the file reliably; update the test to obtain the selectors.exports.json path via that root-finding utility (still asserting exports["SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS"] == SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS) and reference the symbols test_selector_synthesis_keep_worthy_tags_round_trip_through_export, load_export_data, and SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS when making the change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_field_value_core.py around lines 71 - 82, Add a brief inline comment inside test_validate_and_clean_drops_fields_outside_surface_schema explaining that validate_and_clean uses a narrower surface schema than validate_record_for_surface (so fields like "title" are intentionally dropped even though they exist in the broader ecommerce schema); reference the test name and the validate_and_clean function to make the rationale clear to future readers.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_field_value_core.py around lines 710 - 715, The test test_extract_urls_keeps_normal_urls uses a substring check which is loose; change it to assert the exact expected URL returned by extract_urls for input "https://cdn.example.com/product/image.jpg" and "https://example.com/p". Replace the two assertions with a single exact equality check against the expected list (use extract_urls and compare to the exact string value), referencing the test name and the extract_urls function to locate the change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_field_value_dom_regressions.py around lines 50 - 63, The test test_dedupe_image_urls_keeps_highest_resolution_cdn_variant uses set(result) == set(expected) which can hide duplicate entries returned by dedupe_image_urls; update the assertion to verify no duplicates and exact membership/order you expect by checking len(result) == len(set(result)) (to ensure uniqueness) and either assert sorted(result) == sorted(expected) or assert result == expected (if order matters), referencing the dedupe_image_urls function and the test name so you modify the assertions accordingly.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_listing_identity_regressions.py around lines 34 - 38, The test function test_embedded_category_marker_segment_stays_structural is missing a docstring (other tests in this module include one); add a brief docstring at the top of that function explaining the regression scenario — e.g., that embedded "-productlist-sale" path segments should be treated as structural — to match the style of the other tests that call listing_url_is_structural.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_structure.py at line 94, The test updates increased size budgets for several files without recording why; update the test expectations in test_structure.py to include a short comment or accompanying docstring entry explaining the rationale for each +5 LOC change (e.g., note what feature or benign formatting change caused the bump), and for entries referencing Path("app/services/config/extraction_rules.py") and the files field_value_dom.py and field_value_core.py, mention the existing TODO/refactor status and whether refactoring was considered before raising the budget; keep the change minimal — add these explanatory comments next to the budget entries so future reviewers can see why each budget was raised.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/test_harness_support.py around lines 881 - 1020, Duplicate test helper classes _FakeSession and _FakeSettingsView are defined in both test_run_site_harness_supports_acquisition_only_mode and test_run_site_harness_surfaces_challenge_summary_in_acquisition_only_mode; refactor by moving _FakeSession and _FakeSettingsView to module-level (or a pytest fixture) and update those two tests to reference the shared _FakeSession and _FakeSettingsView instead of redefining them, keeping their behavior identical (async context manager for _FakeSession and acquisition_plan returning AcquisitionPlan for _FakeSettingsView); ensure monkeypatch.setattr calls still create the SessionLocal and create_crawl_run behavior as before.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/app/admin/llm/page.tsx around lines 304 - 384, Replace the outer IIFE that computes todayStr/yesterdayStr and the inline time-formatting IIFE inside the costLog.map with a useMemo and a small helper: add const { todayStr, yesterdayStr } = useMemo(() => { ... }, [] ) near other hooks/state and create a function formatRelativeTime(dateStr, todayStr, yesterdayStr) that contains the logic currently inside the inner IIFE (the new Date(entry.created_at) logic and formatting). Then update the costLog.slice(0,40).map render to use todayStr/yesterdayStr and call formatRelativeTime(entry.created_at, todayStr, yesterdayStr) where the IIFEs were. This removes nested IIFEs and keeps behavior identical (preserve time formatting options and "Yesterday" semantics).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/app/runs/page.tsx at line 291, The wrapperClassName currently sets a CSS custom property (--runs-table-offset) on the same element that consumes it, adding unnecessary indirection; update the wrapperClassName in frontend/app/runs/page.tsx (the prop named wrapperClassName) to use a direct hardcoded value instead of the CSS variable (e.g., replace the custom property and calc using --runs-table-offset with a direct calc using the numeric value), removing the unused --runs-table-offset declaration so the class becomes a single max-h-[calc(100vh_-_260px)]-style expression.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/crawl-run-screen.tsx around lines 786 - 788, Extract the hard-coded route strings used in router.replace calls into a central routes constant object (e.g., ROUTES) and replace occurrences in functions like resetToConfig and the other action handlers that currently call router.replace('/crawl?module=category&mode=single') (and similar literals) with references to those constants (e.g., ROUTES.CRAWL_CATEGORY_SINGLE). Add the new ROUTES export in a shared routes/config file and import it into frontend/components/crawl/crawl-run-screen.tsx, updating all router.replace invocations to use the named constants to improve maintainability.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/crawl-run-screen.tsx at line 1229, The code injects HTML via dangerouslySetInnerHTML with syntaxHighlightJson(recordsJson); inspect the implementation of syntaxHighlightJson (imported from ../../lib/ui/syntax) and ensure it fully escapes/sanitizes any string values before wrapping them in HTML tags—if it currently returns raw HTML, change it to either (a) escape all user-supplied content (e.g., replace <, >, &, " with entities) and then optionally sanitize the output with a proven library like DOMPurify, or (b) avoid dangerouslySetInnerHTML altogether by returning React nodes/tokens from syntaxHighlightJson so you render text safely; alternatively swap to a vetted highlighter that emits safe DOM or add CSP headers as defense-in-depth. Ensure the fix is applied where syntaxHighlightJson is defined and keep the usage in crawl-run-screen.tsx unchanged once the function is safe.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/crawl-run-screen.tsx around lines 250 - 253, Extract the magic number 800 into a named constant (e.g. MAX_RECORDS_FETCH_LIMIT) in your shared constants file and import it into crawl-run-screen.tsx; then update the recordsFetchLimit calculation to use MAX_RECORDS_FETCH_LIMIT instead of the literal 800, keeping the existing Math.min/Math.max logic with CRAWL_DEFAULTS.TABLE_PAGE_SIZE and jsonVisibleCount so behavior is unchanged.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/crawl-run-screen.tsx around lines 218 - 1497, CrawlRunScreen is too large and should be split: create a useLogWebSocket(runId, shouldFetchLogs, logCursorAfterId, refs...) hook to encapsulate the WebSocket setup/teardown and socketLogItems/logSocketConnected state (currently in the useEffect that builds wsUrl and manages ws.onmessage/onopen/onclose); create a useRunPolling({runId, live, shouldFetchTableRecords, shouldFetchJsonRecords, shouldFetchLogs, shouldFetchMarkdown, refetchFns...}) hook to contain the various polling useEffects and panelRefreshErrors tracking; move action handlers downloadExport, runControl, applyFieldLearningAction, retryFailedPanels, triggerBatchCrawlFromResults, triggerProductIntelligenceFromResults, triggerDataEnrichmentFromResults into a useRunActions(runId, refs...) hook or module that returns the functions and pending/error state; and finally break the JSX tab content into small components TableTab, JsonTab, MarkdownTab, LogsTab, LearningTab that accept props like records, tableRecords, markdown, logs, domainRecipe, handlers, and visibleColumns so CrawlRunScreen only composes hooks and renders high-level components.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/crawl-run-screen.tsx at line 604, The variable filteredTableRecords is misleading because it simply aliases tableRecords with no filtering; update the code in crawl-run-screen.tsx to either remove filteredTableRecords and use tableRecords directly wherever filteredTableRecords is referenced, or rename filteredTableRecords to a clearer name like visibleTableRecords (and update all references), or implement the actual filter logic where filteredTableRecords is declared if filtering was intended; ensure you change all uses of filteredTableRecords to the chosen approach so there are no dangling references.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/crawl-run-screen.tsx at line 166, Extract the magic multiplier used when slicing records into a named constant: add a top-level constant RECORDS_BATCH_MULTIPLIER (e.g., const RECORDS_BATCH_MULTIPLIER = 4) and replace all literal `* 4` uses (for example in the expressions using CRAWL_DEFAULTS.TABLE_PAGE_SIZE like in the records mapping at records: payload.records.slice(0, CRAWL_DEFAULTS.TABLE_PAGE_SIZE * 4).map(...), and the other occurrences at the same file) with `CRAWL_DEFAULTS.TABLE_PAGE_SIZE * RECORDS_BATCH_MULTIPLIER` so the multiplier is centralized and maintainable.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/lib/ui/status.ts around lines 72 - 78, The function isStatusFlat conflicts semantically with existing isFlatStatus; either remove the alias and have callers use isSubduedStatus directly, or rename isStatusFlat to a clearer name (e.g., isSubduedStatusAlias or isFlatSubduedStatus) and update all callers accordingly; locate the definitions for isSubduedStatus and isStatusFlat in frontend/lib/ui/status.ts and update references throughout the codebase so naming clearly reflects that the function checks subdued/completed/killed statuses and does not collide with isFlatStatus which has different semantics.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/lib/ui/status.ts around lines 84 - 86, Extract the repeated normalization logic into a small helper function, e.g., add function normalizeVerdict(summary?: RunSummaryLike): string { return String(summary?.extraction_verdict ?? '').trim().toLowerCase(); } and replace the duplicated expressions that assign verdict (and similar variables at the other two sites) with calls to normalizeVerdict(summary) so all normalization uses the single helper; update references for variables named verdict (and the similar variables at the other locations) to call normalizeVerdict instead of repeating String(...).trim().toLowerCase().

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: Import-time global namespace mutation can silently override module symbols.
   Path: backend/app/services/config/extraction_rules.py
   Lines: 14-14

2. logic error: Narrow iterable handling can silently discard configured CDN query parameters.
   Path: backend/app/services/config/extraction_rules.py
   Lines: 49-49

3. logic error: Hardcoded fallback token changes the exported pattern set and can break matching behavior.
   Path: backend/app/services/config/extraction_rules.py
   Lines: 16-16

4. logic error: Introducing an unmapped flat variant key creates a schema mismatch in variant flattening.
   Path: backend/app/services/config/field_mappings.py
   Lines: 227-227

5. logic error: Fractional scroll settings are silently truncated, changing configured behavior.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 405-405

6. logic error: A falsy exported allow-list is silently replaced with the built-in default.
   Path: backend/app/services/config/selectors.py
   Lines: 22-22

7. logic error: Restricting iterable handling causes valid attribute data to be silently ignored.
   Path: backend/app/services/data_enrichment/shopify_catalog.py
   Lines: 63-63

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.