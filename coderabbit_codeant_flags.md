Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/adapters/amazon.py at line 323, Remove the unused dict axis_values_by_name: stop populating it and instead use axis_entries where its keys/values are needed; specifically, in the block that builds axis_entries and currently fills axis_values_by_name (around the code that declares axis_values_by_name and later checks for emptiness), delete the axis_values_by_name declaration and its population, and replace the emptiness check that references axis_values_by_name with a check on axis_entries (and any other places that read axis_values_by_name should read axis_entries instead). Ensure functions/methods referencing axis_entries continue to work unchanged.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/adapters/amazon.py around lines 176 - 180, The code currently assigns sku = asin even when asin is a fallback from _detail_value_from_table(detail_table, "item model number"), causing sku to sometimes contain a model number instead of a real ASIN; update the logic where product_id and sku are set so that product_id retains the asin fallback but sku is only populated when a real ASIN was extracted (e.g., from the URL or the detail_table "asin" field) — otherwise omit sku or set it to None/empty; adjust the assignment near the product_id/sku creation and/or add a small helper to detect a real ASIN, and optionally add a brief comment documenting the fallback behavior for asin.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py around lines 127 - 134, DETAIL_TEXT_SCOPE_SELECTORS currently references DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR directly which can raise NameError if that key is missing in _STATIC_EXPORTS; change the module to defensively resolve DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR via _STATIC_EXPORTS.get('DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR', '<default-selector>') (or an appropriate default string) before building DETAIL_TEXT_SCOPE_SELECTORS so the tuple uses the safely obtained variable; mirror the existing pattern used by other constants that call .get() for fallbacks to avoid import-time errors.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/field_mappings.py around lines 208 - 218, FLAT_VARIANT_KEYS mixes predefined constants (COLOR_FIELD, SIZE_FIELD, SKU_FIELD) with raw string literals ("price", "currency", "url", "image_url", "availability", "stock_quantity"); extract those raw strings into named constants (e.g., PRICE_FIELD, CURRENCY_FIELD, URL_FIELD, IMAGE_URL_FIELD, AVAILABILITY_FIELD, STOCK_QUANTITY_FIELD) and replace the literals in FLAT_VARIANT_KEYS so all entries are consistent and can be referenced elsewhere; update any other references to those string keys to use the new constants and keep naming consistent with existing constant conventions.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/field_mappings.py around lines 25 - 27, Add NORMALIZER_LIST_TEXT_FIELDS to the module's explicit exports by including "NORMALIZER_LIST_TEXT_FIELDS" in the _EXTRA_EXPORTS list and simplify its definition by removing the unnecessary tuple() wrapper; keep using _STATIC_EXPORTS.get("NORMALIZER_LIST_TEXT_FIELDS", ()) as the iterable to be unpacked into the frozenset along with "features" so the constant will always be exported and the code is cleaner.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/data_enrichment/service.py around lines 758 - 759, Restore caching for compiled regexes to avoid recompilation in hot paths: add an LRU cache (e.g., @lru_cache(maxsize=1)) to the _material_strip_patterns function (or otherwise cache the result of _compiled_material_strip_patterns()) so calls from _normalize_materials do not recompile patterns on every product; if dynamic config is required, implement a clear-cache helper that calls _material_strip_patterns.cache_clear() or document the tradeoff.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/detail_extractor.py around lines 148 - 149, The code checks field_name against LONG_TEXT_FIELDS but also hardcodes the string "features" in detail_extractor.py; move that literal into configuration by adding "features" to the LONG_TEXT_FIELDS constant (or to the appropriate config file under app/services/config and have LONG_TEXT_FIELDS import it) and then change the conditional to only reference LONG_TEXT_FIELDS (i.e., remove the inline "features" literal); keep the existing return using DETAIL_LONG_TEXT_SOURCE_RANKS.get(str(source or ""), 20) unchanged and update any tests/imports that reference LONG_TEXT_FIELDS.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_dom_extractor.py around lines 1260 - 1278, The current merge logic risks merging unrelated variants by falling back to existing_by_index when dom_key is None and uses unnecessary tuple keys; update the merge in the block that builds existing_by_key/existing_by_index and selects existing_row so that existing_by_key maps row_key (string) -> row (not ("", row_key)), only use index-based fallback (existing_by_index) when there is strong positional correlation (e.g., len(dom_variant_rows) == len(existing_variants) and index < len(existing_variants) or when counts differ by at most 1) and otherwise treat the DOM variant as unmatched (skip merging) to avoid corrupting price/availability; adjust variable names dom_key, existing_row, existing_by_key, existing_by_index, dom_variant_rows and existing_variants accordingly.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_dom_extractor.py around lines 342 - 346, Remove the redundant clause re.fullmatch(r"\d+\s*%\s*off", lowered) from the boolean expression checking promotional text: the subsequent condition ("%" in lowered and any(token in lowered for token in ("off", "discount", "promo"))) already covers strings like "10% off"; keep the "%" check and the any(...("off","discount","promo")) check and delete the r"\d+\s*%\s*off" alternative so the expression only uses the "%" presence plus token match on the variable lowered.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_price_extractor.py around lines 174 - 186, original_price is assigned from jsonld_original_price or _detail_original_price_from_html but the source is always recorded as "dom_text"; change this to mirror how `price` is handled by detecting whether `jsonld_original_price` was used and set the source accordingly: when `jsonld_original_price` is truthy set record["original_price_source"] (or the existing source field pattern used for `price`, e.g., `price_source`) to "jsonld" and call append_record_field_source(record, "original_price", "jsonld"); otherwise set the source to "dom_text" and call append_record_field_source(record, "original_price", "dom_text"); use the variables `jsonld_original_price`, `_detail_original_price_from_html`, `original_price`, and `append_record_field_source` to locate and implement the change.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_record_finalizer.py around lines 419 - 425, Add a brief inline comment above the if that checks variant.get(axis_key) not in (None, "", [], {}) to explain intent: this block synchronizes existing size/color scalar fields on the variant with the cleaned_value from option_values rather than populating size/color when they are missing; reference the variables axis_key, variant.get(axis_key), and cleaned_value so future readers know this is deliberate behavior and not a bug.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 336 - 344, The code currently does redundant checks: sanitize_detail_long_text(text, title=title) already returns "" when detail_long_text_is_numeric_sequence or detail_long_text_is_guide_or_glossary_dump are true, so the subsequent explicit checks of detail_long_text_is_numeric_sequence(cleaned) and detail_long_text_is_guide_or_glossary_dump(cleaned) (and possibly lowered) can be removed; update the block around cleaned = sanitize_detail_long_text(...) to either (A) remove those redundant OR clauses and keep only not cleaned and the disclaimer pattern check (long_text_disclaimer_patterns), or (B) if you intended to re-validate after chunk filtering, add a short comment above the if explaining that sanitize_detail_long_text can join filtered chunks and we re-check numeric/guide/glossary conditions on the joined result—apply this change to the conditional that currently references cleaned, detail_long_text_is_numeric_sequence, detail_long_text_is_guide_or_glossary_dump, and long_text_disclaimer_patterns.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py at line 183, Precompute a module-level frozenset named artifact_price_values from DETAIL_ARTIFACT_PRICE_VALUES (similar to low_signal_title_values), e.g. build artifact_price_values = frozenset(clean_text(v).lower() for v in tuple(DETAIL_ARTIFACT_PRICE_VALUES or ()) if clean_text(v)); then update the check inside _price_candidate_is_artifact to use "if cleaned in artifact_price_values" instead of constructing frozenset(DETAIL_ARTIFACT_PRICE_VALUES or ()) on each call so the set is allocated once and comparisons use the precomputed set.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 420 - 423, Replace the hardcoded threshold 3 with a configurable constant by adding DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS = 3 to app/services/config/extraction_rules and then use that constant in the sanitizer: compute heading_hits as before (using guide_glossary_heading_tokens and lowered) and return heading_hits >= extraction_rules.DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS; ensure you import the constant from app.services.config.extraction_rules at the top of detail_text_sanitizer.py.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_text_sanitizer.py around lines 238 - 246, Precompute the tuple and int once at module level instead of converting on every call: add module-level symbols noise_prefixes (tuple of clean_text(prefix).lower() for prefix in DETAIL_NOISE_PREFIXES when non-empty) and long_text_ui_tail_min_product_words (int(DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS)); then update the logic in the function that currently references DETAIL_NOISE_PREFIXES and DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS so it uses noise_prefixes in the lowered.startswith check and long_text_ui_tail_min_product_words in the length comparison (replace tuple(DETAIL_NOISE_PREFIXES or ()) and int(DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS) usages).

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_tiers.py around lines 131 - 138, The intersection and subset checks are inconsistent and can raise on None: normalize and None-guard both config lists before comparing—call .strip().lower() on each entry of DETAIL_BREADCRUMB_JSONLD_TYPES and wrap it with a safe iterable (e.g., DETAIL_BREADCRUMB_JSONLD_TYPES or ()) when constructing the frozenset used in the check with normalized_types, and likewise protect DETAIL_IRRELEVANT_JSON_LD_TYPES by iterating over (DETAIL_IRRELEVANT_JSON_LD_TYPES or ()) when building irrelevant_types; update the references to DETAIL_BREADCRUMB_JSONLD_TYPES and DETAIL_IRRELEVANT_JSON_LD_TYPES so both are lowercased and None-safe before using normalized_types, breadcrumb intersection, or the subset comparison.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 979 - 1009, Add a short docstring to the function containing this two-stage merge (surrounding the code that uses merged_by_identity, deduped_rows, merged_by_semantic, variant_semantic_identity, variant_row_richness, merge_variant_pair, and emitted_semantic) that clearly explains the algorithm: 1) exact-identity dedupe via merged_by_identity and ordered_keys, 2) semantic merging into merged_by_semantic using variant_semantic_identity/variant_row_richness and merge_variant_pair, and 3) why rows with no semantic identity are preserved and re-emitted unchanged; keep it concise, mention the rationale for the two passes and the role of emitted_semantic in preventing duplicates.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 782 - 785, The current code returns a URL-based identity ("url:{variant_url}") which can cause duplicate variant rows; change the fallback to avoid using URL as an identity: replace the branch that returns f"url:{variant_url}" so it returns None instead (i.e., do not produce an identity from variant_url), or make this behavior configurable and document it; update any callers / tests that assume URL-based identities (see the variant_url variable, text_or_none() usage, and merge_variant_rows) so unidentifiable variants are dropped/merged by merge_variant_rows instead of being keyed by URL.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 161 - 177, The function _variant_node_in_noise_context uses VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH directly in range(), which can raise if the config is None or not an int; validate or coerce this config before use (e.g., ensure it's an int >= 0 or fall back to a safe default like 3) and raise or log a clear error if it's invalid. Update either module initialization to validate VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH or change _variant_node_in_noise_context to coerce/validate (cast to int with try/except, check for negative values) before calling range(), referencing the VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH symbol and the _variant_node_in_noise_context function to locate the change. Ensure behavior is deterministic (use default when missing) and add a brief comment noting the validation.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 66 - 96, The module mixes underscore-prefixed and non-prefixed processed config names; pick a consistent convention (prefer module-private with a leading underscore) and rename the non-prefixed symbols to match – e.g. rename variant_context_noise_tokens -> _variant_context_noise_tokens, variant_scope_selector -> _variant_scope_selector, variant_axis_allowed_single_tokens -> _variant_axis_allowed_single_tokens, variant_axis_generic_tokens -> _variant_axis_generic_tokens, variant_axis_technical_patterns -> _variant_axis_technical_patterns, variant_quantity_attr_tokens -> _variant_quantity_attr_tokens (keep or normalize _VARIANT_SIZE_ALIAS_SUFFIXES as needed), and update all internal imports/usages to the new names to avoid breaking references.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/variant_record_normalization.py around lines 149 - 154, Pre-compute the uppercased currency set at module import time instead of recreating it on every call to _currency_code: add a module-level constant (e.g., _CURRENCY_CODES_UPPER) built once from CURRENCY_CODES using frozenset(str(code).upper() for code in tuple(CURRENCY_CODES or ()) if str(code).strip()), then update _currency_code to check membership against _CURRENCY_CODES_UPPER (use text.upper() as before) and remove the inline frozenset construction.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_candidates.py at line 494, The code repeatedly wraps config values in int() (e.g., STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT and STRUCTURED_CANDIDATE_LIST_SLICE used inside the function in field_value_candidates.py), which indicates the config is supplying strings; update the config to expose these constants as integers (or coerce them once at module load) so callers no longer need per-call int() conversions; modify the config definitions or add a single top-level conversion (e.g., set STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT = int(raw_value) and STRUCTURED_CANDIDATE_LIST_SLICE = int(raw_value)) and remove the redundant int() calls where those names are used in the function.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_candidates.py around lines 831 - 833, The conditional currently returns rows for both branches so other STRUCTURED_MULTI_FIELDS are never converted to a single string; update the branch so that when field_name is one of {"additional_images", "features", "tags"} you return rows or None, but for other multi-fields (use the same field_name/rows/STRUCTURED_MULTI_FIELDS symbols) return a joined string (e.g., join rows with a sensible separator) or None instead of returning the list.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_core.py around lines 521 - 548, The function _coerce_structured_multi_rows declares the local variable rows with a type annotation twice (once in the dict branch and again in the (list, tuple, set) branch), which is confusing and effectively shadows the first declaration; remove the redundant annotation in the second assignment (keep a single declaration like rows = [] or a single annotated declaration in whichever branch you prefer) inside the (list, tuple, set) handling so that only one rows initialization exists and subsequent rows.extend(...) calls operate on that single variable.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_core.py around lines 1028 - 1039, The integer-field branch is inconsistent: when field_name is in _INTEGER_FIELD_NAMES numeric inputs are cast to int in the block around the int(value) return, but string inputs are returned as text from coerce_text in the subsequent block; change the string branch in the integer handling so that after coerce_text(value) you parse numeric strings to int (e.g., detect digits/optional sign and use int(...) on the cleaned text) and return None for non-numeric sentinel strings; update the logic in the function handling field_name/value (the blocks referencing _INTEGER_FIELD_NAMES and coerce_text) to normalize both numeric types and numeric strings to int while preserving the current None behavior for non-numeric strings.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_dom.py around lines 399 - 407, The current deepcopy(scope) in _pruned_text_scope_root can be very expensive for large DOMs; instead, avoid cloning the entire subtree up front and build a pruned clone incrementally: create a new root node (using BeautifulSoup/Tag APIs) and recursively walk the original scope (from _best_text_scope()), appending cloned nodes only when _node_is_hidden_or_auxiliary(node) and _node_has_cross_product_cluster(node) are false; keep the same return shape and behavior of _pruned_text_scope_root but replace the deepcopy + descendant decompose pattern with this selective-copy approach to minimize memory and CPU overhead.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_dom.py around lines 384 - 388, _scope_is_product_like currently calls node.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR) without guarding that the selector is non-empty which can raise SelectorSyntaxError; update the function (_scope_is_product_like) to first check that DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR is truthy (e.g., "if DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR and node.select_one(...)") before calling node.select_one, preserving the existing early-return logic and using the same guard pattern as in _scope_score; no other behavior should change and keep references to _node_attr_text and DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR intact.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_dom.py around lines 1026 - 1030, The code in _extract_sibling_content uses int() directly on DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS and DETAIL_LONG_TEXT_MAX_SECTION_CHARS which can raise ValueError/TypeError for malformed or empty config; add a module-level safe conversion (e.g., _safe_int(value, default) catching ValueError and TypeError) to compute _max_section_blocks and _max_section_chars (use sensible defaults like 8 and 1200), and replace the inline int(...) uses in _extract_sibling_content with these precomputed _max_section_blocks and _max_section_chars to ensure defensive handling.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_dom.py around lines 331 - 350, Extract the hardcoded cross-product detection tokens from _node_has_cross_product_cluster into a configurable constant in app/services/config/extraction_rules.py (e.g., CROSS_PRODUCT_TOKENS or get_cross_product_tokens()) and import it into field_value_dom.py; replace the inline tuple ("also-viewed", "also viewed", "customers", "recommend", "related", "similar", "sponsored") with a reference to the imported list, and keep a sensible default in extraction_rules.py so behavior is unchanged if the config is missing.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/js_state_mapper.py around lines 253 - 256, The conditional in js_state_mapper.py is redundant; replace the expression "(base_url or mapped_url) and base_url and mapped_url and base_url == mapped_url" with a simplified check such as "base_url and mapped_url and base_url == mapped_url" so the branch in the function that compares URLs uses only the necessary truthiness checks for base_url and mapped_url before comparing them.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/normalizers/__init__.py around lines 25 - 28, The list comprehension that builds the escaped currency regex uses redundant str() calls after checking isinstance(code, str); update the comprehension to call re.escape(code.lower()) and compare code.strip().lower() != "rs" (no wrapping in str()), keeping the existing tuple(CURRENCY_CODES or ()) and the isinstance(code, str) guard so re.escape and the comparison operate directly on the confirmed string value.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/normalizers/__init__.py around lines 66 - 73, The membership checks in _normalize_bool repeatedly call tuple(REMOTE_BOOLEAN_TRUE_TOKENS or ()) and tuple(REMOTE_BOOLEAN_FALSE_TOKENS or ()), which is unnecessary and inefficient; replace those calls by using the collections directly (e.g., REMOTE_BOOLEAN_TRUE_TOKENS or ()) or, better, normalize them once at module import into a set/list (e.g., NORMALIZED_REMOTE_BOOLEAN_TRUE = set(REMOTE_BOOLEAN_TRUE_TOKENS or ()) and NORMALIZED_REMOTE_BOOLEAN_FALSE = set(REMOTE_BOOLEAN_FALSE_TOKENS or ())) and then change the checks to use "if text in NORMALIZED_REMOTE_BOOLEAN_TRUE" and "if text in NORMALIZED_REMOTE_BOOLEAN_FALSE", keeping the existing uses of _normalize_text and returned values unchanged.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/pipeline/core.py around lines 441 - 446, Extract acquisition_result.browser_diagnostics into a local variable and use it to compute browser_attempted; specifically, assign something like browser_diagnostics = getattr(acquisition_result, "browser_diagnostics", {}) and then compute browser_attempted = bool(browser_diagnostics and browser_diagnostics.get("browser_attempted")). This removes the duplicated getattr calls and makes the intent in the acquisition_result/browser_diagnostics handling clearer.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/public_record_firewall.py around lines 93 - 100, Replace the hardcoded URL field name literals ("url", "apply_url", "canonical_url") in public_record_firewall.py with the canonical constants you define in the field_mappings config and import into this module; update the conditional that calls public_navigation_url_safe and the subsequent membership check to use those imported constants (e.g., URL_FIELD, APPLY_URL_FIELD, CANONICAL_URL_FIELD) instead of string literals, ensuring you reference the same constant names used elsewhere (like BARCODE_FIELD, SKU_FIELD, VARIANTS_FIELD) and keep the logic that sets rejected[str(raw_field_name)] = "unsafe_navigation_url" unchanged.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/public_record_firewall.py around lines 78 - 87, When ROUTE_BARCODE_TO_SKU is enabled and BARCODE_FIELD is routed, the code assigns routed_sku (from coerce_field_value) directly into data[SKU_FIELD] and marks rejected, bypassing the normal shape check; update the block in public_record_firewall.py so that after computing routed_sku you call _public_record_field_shape_valid(SKU_FIELD, routed_sku, page_url) (or the existing shape-validation routine used elsewhere) and only write to data[SKU_FIELD] and set rejected[str(raw_field_name)] = "routed_to_sku" if the shape check passes, otherwise treat it as invalid (set rejected appropriately) — reference symbols: BARCODE_FIELD, ROUTE_BARCODE_TO_SKU, coerce_field_value, SKU_FIELD, _public_record_field_shape_valid, data, rejected, raw_field_name, allowed_fields, record.

- Verify each finding against the current code and only fix it if needed.

In @backend/harness_support.py around lines 1003 - 1008, The validation currently only rejects None/<=0 and enforces a max via _HIGH_DENOMINATION_PRICE_CURRENCIES, but it needs a lower sanity bound to catch tiny suspicious values; add a minimum price threshold (e.g., MIN_PRICE = 0.01 or a per-currency map) and use it in the same check: after computing price and currency (from _price_number and currency variable) compute min_price then return False if price < min_price, otherwise keep the existing max_price comparison (price <= max_price); update the return condition so the function explicitly verifies price >= min_price && price <= max_price.

- Verify each finding against the current code and only fix it if needed.

In @backend/harness_support.py at line 42, The constant _HIGH_DENOMINATION_PRICE_CURRENCIES should include additional high-denomination currencies to avoid false positives; update the set defined as _HIGH_DENOMINATION_PRICE_CURRENCIES to add "VND", "IDR", and "HUF" (and optionally other similar currencies) so legitimate prices above 10,000 in those currencies are handled correctly; keep the symbol name _HIGH_DENOMINATION_PRICE_CURRENCIES and adjust any related logic that checks membership in this set accordingly.

- Verify each finding against the current code and only fix it if needed.

In @backend/harness_support.py at line 1148, The hex-color check currently uses re.fullmatch(r"#[0-9a-f]{6}", text) which misses uppercase hex digits; update the condition that references re.fullmatch and the literal regex r"#[0-9a-f]{6}" to accept A–F (for example r"#[0-9a-fA-F]{6}") or apply the re.IGNORECASE flag so the variable text will match both lowercase and uppercase hex colors.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_crawl_engine.py around lines 5071 - 5075, Add an explicit length assertion before accessing rows[0]: assert len(rows) == 1, so the test validates there is exactly one extracted record and yields a clear failure if extraction returns empty or multiple results; update the block using the variables rows and record (where record = rows[0]) to insert this assert immediately before dereferencing rows[0] to match the style used elsewhere in this test file.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_network_payload_mapper.py around lines 310 - 311, The tests currently use permissive assertions like `assert len(rows) >= 1` before grabbing `record = rows[0]`; change these to strict `assert len(rows) == 1` in each test case (the occurrences at the current checks around lines where `rows` is asserted: the assertions at 310, 337, 361, 396) to ensure the function returns exactly one mapping and to catch unexpected duplicates or extra rows; update the assertion for the `rows` variable and keep the subsequent `record = rows[0]` usages unchanged.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/test_harness_support.py around lines 537 - 576, The test function test_evaluate_quality_flags_cross_cutting_detail_invariants sets require_clean_variants=True but omits asserting the corresponding check and the observed failure mode; update the test to add an assertion that quality["quality_checks"]["variant_artifacts_ok"] is False (or the expected boolean based on the sample_record_data) and assert quality["observed_failure_mode"] equals the expected string (e.g., "cross_cutting_detail_invariants" or the same failure_mode used elsewhere) so the test matches the pattern used in other tests like test_evaluate_quality_flags_audit_variant_and_system_artifacts.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Malformed test-site entries will break consumers that expect one valid URL per line.
   Path: TEST_SITES.md
   Lines: 171-171

2. possible bug: Removing the selected variant breaks callers that rely on a single current variant record.
   Path: backend/app/services/adapters/amazon.py
   Lines: 366-366

3. possible bug: Dropping variant-axis metadata changes the output contract and can break consumers expecting those fields.
   Path: backend/app/services/adapters/amazon.py
   Lines: 321-321

4. logic error: Variant counts can become inconsistent after flattening the variant list.
   Path: backend/app/services/adapters/myntra.py
   Lines: 241-241

5. logic error: Dropping legacy variant aliases from the export breaks existing variant parsing for older payloads.
   Path: backend/app/services/config/field_mappings.exports.json
   Lines: 73-73

6. logic error: Removing `price_original` from `ECOMMERCE_DETAIL_JS_STATE_FIELDS` creates a schema mismatch with the live extractor data model.
   Path: backend/app/services/config/field_mappings.exports.json
   Lines: 248-248

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Two added entries concatenate multiple URLs on one line and will be parsed incorrectly.
   Path: TEST_SITES.md
   Lines: 172-172

2. logic error: The detail extractor no longer populates `sku`, even though the adapter still derives an ASIN and previously exposed it under that field.
   Path: backend/app/services/adapters/amazon.py
   Lines: 176-176

3. logic error: Detail records no longer include the variant metadata that downstream consumers expect.
   Path: backend/app/services/adapters/myntra.py
   Lines: 216-216

4. logic error: Removing the selected-variant payload breaks consumers that depend on the active variant’s full data.
   Path: backend/app/services/adapters/shopify.py
   Lines: 198-198

5. logic error: Dropping variant axis metadata removes structured option information needed by callers.
   Path: backend/app/services/adapters/shopify.py
   Lines: 198-198

6. logic error: Narrowing the crawl sources can make enrichment miss color, size, and availability data on existing records.
   Path: backend/app/services/config/data_enrichment.py
   Lines: 142-142

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.