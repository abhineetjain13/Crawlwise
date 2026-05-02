Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/field_mappings.exports.json around lines 624 - 632, The mapping is ambiguous because "product_id" appears both as a canonical field in the ecommerce_detail schema and as an alias of "sku" in the sku alias list; update the generator logic in app.services.config._export_data to enforce canonical-field precedence (so a source key matching a canonical field like product_id maps to that canonical field, not an alias) and regenerate field_mappings.exports.json, or alternatively remove "product_id" from the "sku" alias list in the generated output so the canonical ecommerce_detail.product_id remains authoritative; ensure the change is applied where aliases are assembled (the code that builds the "items" array for "sku") so future exports follow this precedence.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/field_mappings.exports.json around lines 388 - 400, The config defines two semantically overlapping field mappings, original_price and price_original, which causes duplication and confusion; either merge price_original into the original_price entry (moving its alias into the original_price "__type__": "list" items and removing the separate price_original entry), and update ECOMMERCE_ONLY_FIELDS to reference only original_price, or if they are intentionally distinct, add a clear comment in the generator explaining the difference and why price_original remains separate and ensure ECOMMERCE_ONLY_FIELDS is consistent with that decision; reference the mapping keys original_price and price_original and the ECOMMERCE_ONLY_FIELDS constant when making the change.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/llm_runtime.py around lines 103 - 110, The fallback loop duplicates the key parsing logic used earlier for DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD and omits validations; extract a small helper (e.g., _parse_provider_model_and_rates or parse_pricing_entry) that takes a dict key and value and returns (provider, model, rate1, rate2) or raises/returns None on validation/Decimal errors, incorporate provider membership check and rate format/Decimal error handling inside it, then call that helper from both the main loop and the fallback loop to populate pricing[(provider, model)] consistently.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/data_enrichment/shopify_catalog.py around lines 212 - 216, The generator expression inside the if in shopify_catalog.py contains a redundant truthy check: remove the unnecessary "tokens and" because the filter "(tokens := set(tokenize_text(term)))" already ensures tokens is non-empty; update the conditional that uses context_terms, tokenize_text, tokens and source_tokens so it simply tests "tokens <= source_tokens" for each term (refer to the generator using tokens, tokenize_text(term), context_terms, and source_tokens) to simplify the expression.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_price_extractor.py around lines 40 - 44, Rename the module-internal variable installment_price_text_tokens to follow the underscore convention (e.g., _installment_price_text_tokens) to match other internal constants like _LOW_SIGNAL_ZERO_PRICE_SOURCES; update its definition that consumes DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS and update any references (including the one noted at line 591) to the new name so the code consistently uses _installment_price_text_tokens everywhere.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_price_extractor.py around lines 225 - 256, The field-source path recorded in reconcile_detail_price_magnitudes is incorrect when selected_variant is present because variant_rows mixes selected_variant and the variants list; change the append_record_field_source call to compute the correct target path per row: if the row is the selected_variant (detect by index 0 when record.get("selected_variant") is a dict or by identity), use "selected_variant.price", otherwise map the variant_rows index to the correct variants list index (subtract 1 when selected_variant exists) and use f"variants[{variant_index}].price"; update the loop in reconcile_detail_price_magnitudes to derive this path before calling append_record_field_source so parent/variant magnitude corrections record the right field keys.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_price_extractor.py around lines 576 - 591, In _price_node_looks_like_installment, remove the unnecessary single-item loop `for candidate in (node,)` and operate directly on the node: check if node is None, then use node.get_text and node.get to build text_parts (same attr loop over ("aria-label",) and same handling for list/raw), compute lowered as before and return the token membership check against installment_price_text_tokens; preserve variable names text_parts, lowered and behavior exactly but without the redundant loop.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_raw_signals.py around lines 166 - 167, The condition `len(rows) >= 1` is redundant because an earlier early return guarantees `rows` is non-empty; update the check in the block using `rows`, `title`, and `_breadcrumb_label_matches_title` to remove `len(rows) >= 1` so it simply tests `title` and `_breadcrumb_label_matches_title(rows[-1], title)` (i.e., replace the `if` that references `rows`, `title`, and `_breadcrumb_label_matches_title` to drop the `len(rows) >= 1` part), leaving the slicing `rows = rows[:-1]` unchanged.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_raw_signals.py around lines 171 - 188, The function _breadcrumb_label_matches_title contains a hardcoded minimum label length value (8); move this magic number into configuration by adding a new constant DETAIL_BREADCRUMB_MIN_LABEL_LENGTH (e.g., in app/services/config/extraction_rules.py) and replace the literal 8 in _breadcrumb_label_matches_title with that constant; ensure imports/reference to DETAIL_BREADCRUMB_MIN_LABEL_LENGTH are added alongside the existing DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO so the length threshold is configurable and consistent with _breadcrumb_title_key and SequenceMatcher usage.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_record_finalizer.py around lines 507 - 512, The function _price_is_low_signal_copy currently uses hard-coded Decimal thresholds; create constants LOW_SIGNAL_PRICE_MAX = Decimal("1") and LOW_SIGNAL_PARENT_MIN = Decimal("10") in app/services/config/extraction_rules.py (and optionally a named ZERO constant if you prefer) and then update _price_is_low_signal_copy to import and use LOW_SIGNAL_PRICE_MAX and LOW_SIGNAL_PARENT_MIN instead of Decimal("1") and Decimal("10") (keep the Decimal("0") check as-is or replace with a ZERO constant if added) so the tunable thresholds are read from the config module.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_record_finalizer.py around lines 499 - 504, The tolerance Decimal("0.01") is hardcoded in _price_is_cents_copy; extract it to a config constant (e.g., PRICE_COMPARISON_TOLERANCE) under app/services/config and import it into detail_record_finalizer.py, then replace Decimal("0.01") with the config constant so the comparison uses the centralized tolerance value while keeping the same Decimal type and semantics.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_record_finalizer.py around lines 639 - 656, The hard-coded threshold 6 in _variant_title_can_be_option_label should be extracted to a config constant; add VARIANT_OPTION_LABEL_MAX_WORDS = 6 in app/services/config/extraction_rules.py, import that constant into the module containing _variant_title_can_be_option_label, and replace the literal 6 with VARIANT_OPTION_LABEL_MAX_WORDS, ensuring the function still uses clean_text(title).split() and the same logic paths (has_option_axis and final length check) remain unchanged.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 293 - 301, The _clean_materials_pollution function currently rebuilds pollution_tokens on every call; move that computation to module load by creating a module-level frozenset (e.g., materials_pollution_tokens) that maps DETAIL_MATERIALS_POLLUTION_TOKENS through clean_text(...).casefold() while filtering out empty results, then update _clean_materials_pollution to use the new materials_pollution_tokens instead of reconstructing the set each call to improve efficiency and match the low_signal_title_values pattern.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 130 - 145, The three predicate functions (_sku_candidate_is_artifact, _identifier_candidate_is_artifact, _product_type_candidate_is_artifact) lower-case the incoming cleaned value but compare it against module constants (DETAIL_ARTIFACT_SKU_PREFIXES, DETAIL_ARTIFACT_IDENTIFIER_VALUES, DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES) that are not normalized; normalize those config collections once at module import (e.g. create lowercased/cleaned equivalents or overwrite the originals: lowercased sets/lists for prefixes, identifier values, and product type values) and then have the functions compare against those normalized constants so both sides use the same case/cleaning logic.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py at line 199, The hardcoded noise prefixes in the conditional within detail_text_sanitizer.py (the if checking field_name and lowered.startswith(...)) should be moved into configuration: add a constant (e.g., NOISE_PREFIXES or DETAIL_NOISE_PREFIXES) in app/services/config (a new or existing config module), import that constant into detail_text_sanitizer.py, and replace the literal tuple ("check the details", "product summary") with the imported config constant in the startswith call so the prefixes are externalized and configurable.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 148 - 162, Replace the hardcoded artifact token set in _price_candidate_is_artifact with a config constant: add DETAIL_ARTIFACT_PRICE_VALUES = {"free", "n/a", "na", "unavailable", "contact us"} to app/services/config/extraction_rules.py, import DETAIL_ARTIFACT_PRICE_VALUES in detail_text_sanitizer, and use that constant instead of the inline set in the _price_candidate_is_artifact function so the artifact values are maintained in config.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 117 - 128, The function _category_candidate_is_noise compares lowercased parts against DETAIL_CATEGORY_UI_TOKENS but those tokens may not be lowercased, causing missed matches; create a module-level normalized frozenset (e.g., category_ui_tokens) that maps clean_text(token).lower() for each token in DETAIL_CATEGORY_UI_TOKENS (skipping empties) and then update _category_candidate_is_noise to use category_ui_tokens for all membership checks (replace usages at the list comprehension and the final any(...) check), ensuring all comparisons use the same cleaned/lowercased token set.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_tiers.py at line 133, The return condition is redundant: remove the unnecessary bool(normalized_types) prefix and simplify the return to just "return normalized_types <= irrelevant_types" (keep the existing variables normalized_types and irrelevant_types and the same return statement location in the function so the earlier empty-check behavior remains intact).

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_tiers.py around lines 128 - 129, The check for breadcrumb JSON-LD types currently uses hardcoded strings (the set {"breadcrumblist", "breadcrumb_list"}) in extract/detail_tiers.py; move these values into a config constant (e.g., add DETAIL_BREADCRUMB_JSON_LD_TYPES = {"breadcrumblist", "breadcrumb_list"} in app/services/config/extraction_rules.py or alongside DETAIL_IRRELEVANT_JSON_LD_TYPES) and update the code that checks normalized_types (the if normalized_types & {...} branch) to reference that new constant instead of the inline set so the runtime tunable is centralized in config.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 656 - 659, The selection logic using len(variant) > len(existing) when assigning variant_by_combo[combo] is inconsistent with merge_variant_rows; replace the raw key-count comparison with a richness comparison using the same helper (variant_row_richness) to decide the winner. In the block that currently checks existing = variant_by_combo.get(combo) and compares variant vs existing, call variant_row_richness(variant) and variant_row_richness(existing) (or its equivalent API used in merge_variant_rows) and use the richer result to assign variant_by_combo[combo] = variant. Ensure you handle None existing the same way as before and preserve short-circuit behavior.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 28 - 51, The module currently iterates directly over configuration constants VARIANT_AXIS_LABEL_NOISE_TOKENS, VARIANT_AXIS_LABEL_NOISE_PATTERNS, VARIANT_GROUP_ATTR_NOISE_TOKENS, and VARIANT_GROUP_ATTR_NOISE_PATTERNS which can be None; update each comprehension/tuple construction to iterate over (VARIANT_... or ()) so they safely fall back to an empty iterable (e.g., change "for token in VARIANT_AXIS_LABEL_NOISE_TOKENS" to "for token in (VARIANT_AXIS_LABEL_NOISE_TOKENS or ())" and do the same for the other three occurrences), preserving the existing stripping/lowercase and re.compile logic.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_candidates.py around lines 433 - 435, The function in backend/app/services/field_value_candidates.py currently hardcodes traversal thresholds (default parameter limit=8 and inline slices like [:20]); move these magic numbers into constants in app/services/config/extraction_rules (e.g., MAX_TRAVERSAL_LIMIT, MAX_CANDIDATES_SLICE) and replace the literal 8 and any [:20] slices in the function(s) that accept depth/limit (the signature with depth: int = 0, limit: int = 8) and other candidate-selection code with those config constants, defaulting the function parameter to the config value and importing the constants from app.services.config.extraction_rules.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_candidates.py around lines 345 - 365, The conversion of config lists to tuples in _uses_integral_price_payload is unnecessary; remove the tuple(...) calls and use INTEGRAL_PRICE_PAYLOAD_HINT_FIELDS and INTEGRAL_PRICE_PAYLOAD_VARIANT_FIELDS directly for membership checks and iteration so behavior remains the same but simpler; update references payload_hint_fields and variant_hint_fields (or eliminate them and reference the config names directly) in the any(...) checks and the variant loop to avoid the redundant tuple allocation.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_candidates.py around lines 131 - 136, The current check uses host.split(".")[0] which returns the leftmost subdomain (e.g., "shop" from "shop.example.com") and causes false positives; update the logic where page_url, host, and lowered are compared so that instead of host.split(".")[0] you extract the second-level domain (SLD) from host by splitting on "." and using the penultimate label (host_parts[-2] if len(host_parts) >= 2, fallback to host_parts[0] otherwise) before comparing to lowered, keeping the existing www. strip and null/length checks intact.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_candidates.py around lines 108 - 114, The current guard skips sorting when position values are strings like "1" even though _get_position can convert them; update the condition that checks raw_items before sorting to accept positions that are int/float or strings that can be converted to float (e.g., by testing isinstance(pos, (int, float)) or (isinstance(pos, str) and try: float(pos) except: False) so raw_items = sorted(raw_items, key=_get_position) runs for numeric strings as well while preserving the existing exception handling and logger.exception call; reference the raw_items variable and the _get_position function when making this change.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_core.py around lines 484 - 498, The _coerce_literal_text_list function currently only catches SyntaxError and ValueError from ast.literal_eval; update the except clause to also catch RecursionError (e.g., except (SyntaxError, ValueError, RecursionError):) and return an empty list to safely handle deeply nested/recursive literals coming from untrusted input, referencing ast.literal_eval in _coerce_literal_text_list.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_core.py around lines 1085 - 1125, The validate_and_clean function currently drops fields not present in _OUTPUT_SCHEMAS (it only copies schema-defined fields into cleaned) which is not documented; update the validate_and_clean docstring to explicitly state that fields not defined in the surface schema are omitted from the returned cleaned record and that callers like validate_record_for_surface are expected to merge back allowed/extra fields (or state the alternate behavior if you prefer to change the implementation), and mention related helpers clean_record and validate_record_for_surface so maintainers can find the merge/cleanup logic.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/js_state_mapper.py around lines 372 - 390, The function _find_product_payloads currently accumulates all matches before sorting and slicing to 8, risking large intermediate lists; change it to maintain a running top-k to avoid unbounded growth by either using heapq.nlargest (or a min-heap of size 8) keyed by _product_payload_score or by pruning the payloads list back to 8 after each extend/append; keep the existing depth/limit and per-list cap (list[:25]) but ensure you compare and keep only the highest-scoring items as you recurse so the intermediate list never grows beyond a small constant (e.g., 8 or slightly larger buffer).

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/js_state_mapper.py at line 204, Extract all hardcoded numeric limits and the always-selectable axes set into a centralized config module under app/services/config (e.g., constants like PRODUCT_PAYLOAD_LIMIT, LIST_ITERATION_LIMIT, RECURSION_DEPTH_LIMIT, AVAILABLE_SIZES_LIMIT, ALWAYS_SELECTABLE_AXES). Replace occurrences of deduped[:8], any loops using 25, recursion depth checks using 6, available sizes truncation using 20, and frozenset({"size"}) with references to these config constants; update callers in functions that use variables named deduped, the loop ranges, recursion checks, and wherever frozenset({"size"}) appears so they import and use the new config values. Ensure defaults match existing literals and add tests or comments showing where to override for environment-specific tuning.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/js_state_mapper.py around lines 913 - 927, Add a short clarifying comment above the direct_axis_keys creation and the subsequent filter that explains the deduplication intent: that direct_axis_keys collects axis names which already match their normalized form (using normalized_variant_axis_key on variation_values) so later when iterating (in the for loop using axis_name, raw_value and axis_key = normalized_variant_axis_key(axis_name)) we skip normalized duplicates (the check axis_key in direct_axis_keys and axis_key != str(axis_name).strip().lower()) to prefer raw/original keys like "colorID" over their normalized counterpart "color" and avoid emitting both; mention the roles of option_values and variant_axis_name_is_semantic in the filtering to make the conditions clear to future maintainers.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/js_state_mapper.py around lines 288 - 305, In _mapped_product_identity_matches, avoid treating both missing urls as a match by distinguishing explicit URLs from the page_url fallback: when computing base_url and mapped_url (using base_record.get("url") and mapped.get("url")), only perform the equality check using page_url if at least one of the two records provided an explicit url; if both records lack an explicit url (i.e., both would be using page_url fallback), skip the URL match and continue to the title check or return False accordingly so two different products extracted from the same page don't falsely match.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/llm_tasks.py around lines 268 - 270, The current except block in run_prompt_task calling session.rollback() will roll back the whole surrounding transaction; instead wrap the LLMCostLog persistence (the session.add/flush for LLMCostLog) in a savepoint using session.begin_nested() so failures only rollback that savepoint; move the try/except inside that begin_nested() context and on exception call await session.rollback() for the nested transaction or let the context manager rollback the savepoint and log the warning (logger.warning("Failed to persist LLM cost log", exc_info=True))—refer to run_prompt_task, the LLMCostLog insert/add/flush code and the except SQLAlchemyError handler to locate where to apply session.begin_nested().

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/llm_tasks.py at line 928, The hardcoded truncation placeholders ("[TRUNCATED DUE TO TOKEN LIMIT]" and "[TRUNCATED]") should be centralized into configuration constants and imported where used: create named constants (e.g., TRUNCATION_PLACEHOLDER_LONG and TRUNCATION_PLACEHOLDER_SHORT) in the app/services/config module, replace the inline strings (currently assigned to the local variable suffix and any other occurrences) with imports of those constants, and update all uses (the assignments to suffix and other truncation-related code paths) to reference the config symbols so the placeholders are no longer duplicated or hardcoded.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/normalizers/__init__.py around lines 38 - 50, Extract the _AVAILABILITY_TOKENS dictionary out of backend/app/services/normalizers/__init__.py and place it in the service config module alongside AVAILABILITY_URL_MAP; export it with a clear name (e.g., AVAILABILITY_TOKENS) and update all usages in normalizers to import AVAILABILITY_TOKENS from the config module instead of referencing the local _AVAILABILITY_TOKENS; ensure the symbol name and import paths are consistent, update any tests or modules that relied on the old private name, and run the test suite to confirm no import or reference breaks.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/pipeline/core.py around lines 166 - 178, The code currently unconditionally overwrites resolved_max_pages and resolved_max_scrolls with safety_iteration_cap; instead, first resolve user/config values (use _resolve_run_param with plan.max_pages, config.max_pages, max_pages and similarly for max_scrolls) and then clamp those resolved values to the ceiling by taking min(resolved_value, safety_iteration_cap). Keep the safety_iteration_cap from crawler_runtime_settings.traversal_max_iterations_cap but apply it as a ceiling, not a replacement, so resolved_max_pages and resolved_max_scrolls respect explicit user controls while enforcing the safety cap.

- Verify each finding against the current code and only fix it if needed.

In @backend/harness_support.py around lines 849 - 865, The function _quality_price_sane_ok currently only raises the max_price for currency "INR"; update its currency handling so high-denomination currencies (e.g., "JPY", "KRW") get appropriately higher thresholds too: locate _quality_price_sane_ok and extend the currency-to-max_price logic (the variables currency and max_price) to include JPY and KRW (and any other site-specific high-denomination codes) with a larger limit (e.g., 100000.0) while preserving the default 10000.0; ensure the currency string normalization (str(...).strip().upper()) is reused and add tests for sample_record_data/selected_variant price paths to cover these currencies.

- Verify each finding against the current code and only fix it if needed.

In @backend/harness_support.py around lines 1235 - 1249, The _price_number function mishandles values like "1.234,56" because when both '.' and ',' exist it unconditionally removes commas; update _price_number to mirror the logic in _looks_numeric_price by checking which separator occurs last (use str.rfind on normalized) to determine the decimal separator, then drop thousand separators and replace the chosen decimal separator with '.' before casting to float; keep the rest of the validation (empty -> None and try/except ValueError -> None) and reference the function name _price_number when making the change.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_crawls_api_domain_recipe.py around lines 260 - 264, The code redundantly wraps the result of await db_session.execute(select(DomainFieldFeedback)).scalars().all() in an extra list(); remove the outer list() and assign the result of (...).scalars().all() directly to feedback_rows. Locate the expression using db_session.execute, select(DomainFieldFeedback), and .scalars().all() and simplify by dropping the surrounding list(...) wrapper.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_detail_extractor_priority_and_selector_self_heal.py around lines 310 - 329, The test test_reduce_html_for_selector_synthesis_preserves_price_and_buy_box_controls is missing an assertion to verify that the input's value attribute survives reduction; update the test that calls reduce_html_for_selector_synthesis to include an assertion checking for value="sku-1" (e.g., assert "value=\"sku-1\"" in reduced) so the behavior is covered, or explicitly document/comment why reduce_html_for_selector_synthesis should drop input values if that is intentional.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_state_mappers.py around lines 934 - 1041, Tests are calling private helpers (_map_product_payload and _normalize_variant) which couples tests to implementation; update tests to exercise the public API map_js_state_to_fields instead, crafting input payloads that trigger the same code paths (including price normalization, variant handling and glom failure scenarios), and only keep direct calls to _map_product_payload/_normalize_variant when an edge case cannot be reached through map_js_state_to_fields; if a fault-injection (glom failure) is required, continue to monkeypatch js_state_mapper.glom but assert behavior via map_js_state_to_fields rather than private functions, or alternatively refactor the mapper to expose a small seam/hook (e.g., a parameter or wrapper function) that lets tests simulate glom failures without accessing internals.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/test_harness_support.py around lines 74 - 77, The test test_parse_test_sites_markdown_reads_urls_from_markdown_tables uses a hardcoded absolute Windows path which will fail on CI and non-Windows machines; change it to create a temporary markdown file (use the pytest tmp_path fixture) or compute a project-relative Path and write the TEST_SITES.md content within the test, then call parse_test_sites_markdown(fixture, start_line=1); consult the existing test_parse_test_sites_markdown_reads_urls_from_tail for the tmp_path pattern and mirror its file creation and content setup so the test is platform-independent.

- Verify each finding against the current code and only fix it if needed.

In @coderabbit_codeant_flags.md at line 73, There are two identical instances of the validation instruction string "Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else."—consolidate them by keeping a single copy and removing the duplicate: locate the two identical paragraphs (the validation instruction) and either (a) move one instance to the top of the document under a new "Validation procedure" or "General instructions" heading and delete the other instance, or (b) if the document structure already has a top-level instruction area, delete the later duplicate and keep the original; ensure no other content is changed and update any cross-references if present.

- Verify each finding against the current code and only fix it if needed.

In @coderabbit_codeant_flags.md at line 25, The current check "if not any(set(tokenize_text(term)) <= source_tokens for term in context_terms)" can produce false positives when tokenize_text(term) returns an empty set; update the loop/generator that iterates context_terms to compute tokens = set(tokenize_text(term)) and only consider the term if tokens is non-empty (e.g., use "if tokens and tokens <= source_tokens") so empty tokenizations are skipped; apply this change where context_terms, tokenize_text, and source_tokens are used (refer to the context_terms iterable and the tokenize_text function) to ensure terms with empty token sets don't count as matches.

- Verify each finding against the current code and only fix it if needed.

In @coderabbit_codeant_flags.md at line 5, The recursive fallback in get_token_pricing (llm_runtime.py) uses model_copy(...) to set token_pricing_json to DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD then calls fallback.get_token_pricing(), causing unnecessary allocation and recursion; replace that fallback block in get_token_pricing so it does not call model_copy or get_token_pricing again — instead either (a) set raw = DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD and re-run the existing parsing/validation logic in the same function to produce the parsed pricing, or (b) compute and return the parsed/default pricing inline from DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD so token_pricing_json, model_copy, and recursive get_token_pricing calls are eliminated.

- Verify each finding against the current code and only fix it if needed.

In @coderabbit_codeant_flags.md around lines 5 - 57, Update the file path notation in the documentation by removing the leading "@" from all service path references (e.g., change `@backend/app/services/config/llm_runtime.py` to `backend/app/services/config/llm_runtime.py`) so paths use standard relative notation; scan the diff excerpts (llm_runtime.py, product_intelligence.py, data_enrichment/service.py, shopify_catalog.py, extract/detail_raw_signals.py, field_value_candidates.py, llm_tasks.py, normalizers/__init__.py, product_intelligence/discovery.py, frontend/app/product-intelligence/page.tsx) and replace any other "@..." occurrences with the same non-aliased paths consistently across the document.

- Verify each finding against the current code and only fix it if needed.

In @coderabbit_codeant_flags.md around lines 3 - 55, The document coderabbit_codeant_flags.md contains the repeated sentence "Verify each finding against the current code and only fix it if needed." repeated many times; consolidate by removing the repeated occurrences and adding one global directive (e.g., a single top-of-file sentence or header) that states the verification instruction, and update any remaining issue blocks to omit the duplicate phrase—search for the exact phrase "Verify each finding against the current code and only fix it if needed." and replace all but the single global instance with nothing so each issue section only contains the specific guidance.

These are comments left during a code review. Please review all issues and provide fixes.

1. null pointer: Importing the config module now fails because a newly added constant references a name before it is defined.
   Path: backend/app/services/config/extraction_rules.py
   Lines: 396-396

2. logic error: Removing `currency` and `brand` from the ecommerce repair/retry targets reduces fallback recovery for those fields.
   Path: backend/app/services/config/field_mappings.exports.json
   Lines: 234-234

3. logic error: Allowing `role` in selector synthesis can make generated selectors unstable or incorrect.
   Path: backend/app/services/config/selectors.py
   Lines: 46-46

4. logic error: Removing form controls from `SELECTOR_SYNTHESIS_LOW_VALUE_TAGS` can make the selector generator overvalue generic interactive elements.
   Path: backend/app/services/config/selectors.py
   Lines: 65-65

5. logic error: Caching the compiled strip patterns freezes config-dependent normalization and can use stale rules.
   Path: backend/app/services/data_enrichment/service.py
   Lines: 750-750

6. logic error: Removing `ses` plural normalization breaks matching for common taxonomy terms.
   Path: backend/app/services/data_enrichment/shopify_catalog.py
   Lines: 55-55

7. logic error: `taxonomy_context_conflicts` now uses stricter token-set matching for context terms.
   Path: backend/app/services/data_enrichment/shopify_catalog.py
   Lines: 212-212

8. logic error: Parent price can be overwritten by a variant price, corrupting the extracted product price.
   Path: backend/app/services/detail_extractor.py
   Lines: 1418-1418

9. logic error: Percentage-based option values can now be incorrectly filtered out as noise.
   Path: backend/app/services/extract/detail_dom_extractor.py
   Lines: 318-318

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.