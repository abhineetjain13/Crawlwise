Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/crawl_fetch_runtime.py around lines 798 - 803, The timeout resolution logic duplicated in the block assigning _raw_http_timeout and http_timeout (and the identical code in _try_browser_http_handoff) should be extracted into a small helper function (e.g., _resolve_http_timeout) that accepts the _FetchRuntimeContext and returns the resolved float timeout using crawler_runtime_settings.http_timeout_seconds and context.resolved_timeout; replace both original blocks with calls to this helper to eliminate duplication and improve maintainability while keeping the same behavior.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_identity.py around lines 77 - 82, The code in detail_identity.py hardcodes the year regex and the token threshold directly inside the year_led_terminal and terminal_looks_like_product_slug expressions; move those magic values into the centralized config: add e.g. YEAR_REGEX = r"(?:19|20)\d{2}" (or a compiled pattern) and MIN_TERMINAL_TOKENS = 3 under app/services/config/*, import them into extract/detail_identity.py, and replace re.fullmatch(r"(?:19|20)\d{2}", terminal_token_list[0]) with re.fullmatch(YEAR_REGEX, terminal_token_list[0]) (or YEAR_REGEX.fullmatch if compiled) and replace len(terminal_tokens) >= 3 with len(terminal_tokens) >= MIN_TERMINAL_TOKENS so tuning is centralized and tests can override config.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/detail_identity.py around lines 81 - 86, The product-slug heuristic in terminal_looks_like_product_slug uses len(terminal_tokens) which is a set and de-duplicates tokens causing false negatives (e.g., "blue-blue-widget"); change the length check to use the original list (terminal_token_list) so repeated tokens count: update the condition in terminal_looks_like_product_slug to use len(terminal_token_list) >= 3 while keeping the other checks (any(re.search...), "-" in terminal_raw, and not year_led_terminal) intact.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/listing_card_fragments.py around lines 116 - 121, The condition link_count >= 1 is redundant because earlier logic already returns when link_count == 0; update the if in the scoring block to remove the redundant check so it reads logically as "if has_price and _node_has_image_descendant(node): score += 4" (referencing the variables link_count, has_price, _node_has_image_descendant, and score) to simplify the code while preserving behavior.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/listing_card_fragments.py around lines 125 - 130, Replace the duplicated helper _node_has_image_descendant with a call to the existing _node_has_listing_media helper: remove or consolidate the _node_has_image_descendant function and update any callers (the helper used near the earlier fragment extraction logic) to call _node_has_listing_media(node) instead so the single selector "img, picture img, picture source" is reused across the module.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/shared_variant_logic.py around lines 56 - 66, The three variable initializations _variant_color_hint_words, _variant_size_value_patterns, and _variant_option_value_noise_tokens use generator comprehensions without the tuple() wrapper while similar patterns elsewhere use tuple(... or ()); make the pattern consistent by applying the same tuple(...) coercion to these three (or alternately remove tuple(...) from the other occurrences) so all sequence constructions follow the same style—locate and update the initializers for _variant_color_hint_words, _variant_size_value_patterns, and _variant_option_value_noise_tokens to match the project's chosen tuple coercion pattern.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/variant_record_normalization.py around lines 305 - 312, The nested _size_candidate_is_gender_artifact function duplicates the gender-detection regex; extract a single compiled regex (e.g., GENDER_ARTIFACT_RE) at module scope or import it from config and use that instead of rebuilding the pattern inside _size_candidate_is_gender_artifact, updating the function to call GENDER_ARTIFACT_RE.search(lowered_text) and keep the same candidate logic (length check and re.escape(candidate.lower())) so detection is consistent across the module.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/variant_record_normalization.py around lines 391 - 392, The current branch returns " ".join(tokens) when len(tokens) <= 3 and color_indexes[-1] == len(tokens) - 1, which can include non-color tokens (e.g., "XS Blue"); change this to build the returned string from only tokens that are either indexed by color_indexes or match a small set of color modifiers (e.g., light, dark, pale, bright, navy, teal modifiers) before calling clean_text(...). Update the logic around tokens and color_indexes so you compute color_tokens = [t for i,t in enumerate(tokens) if i in color_indexes or t.lower() in COLOR_MODIFIERS] (define COLOR_MODIFIERS as a local set or config constant), then return clean_text(" ".join(color_tokens)).title() instead of joining all tokens.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/extract/variant_record_normalization.py around lines 277 - 282, Replace the hardcoded size set and gender regex in the conditional inside variant_record_normalization.py with config constants: import STANDARD_SIZE_VALUES and GENDER_ARTIFACT_PATTERN from app.services.config.extraction_rules and change the membership and regex checks to use STANDARD_SIZE_VALUES and re.search(GENDER_ARTIFACT_PATTERN, text.lower()) respectively; ensure the new constants match the original semantics (sizes lowercased set and pattern allowing straight and curly apostrophes) and add the import at top of the module.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_dom.py around lines 485 - 499, The hardcoded template placeholder tokens used to build _UNRESOLVED_TEMPLATE_URL_RE in field_value_dom.py should be moved to the config module and the service should consume that config; add a tuple (e.g. UNRESOLVED_TEMPLATE_URL_TOKENS) to app/services/config/extraction_rules and then replace the literal regex construction in field_value_dom.py with one built from those tokens (used by _UNRESOLVED_TEMPLATE_URL_RE) so _is_garbage_image_candidate continues to call that regex but the token list is configurable and centralized.

- Verify each finding against the current code and only fix it if needed.

In @backend/harness_support.py around lines 1145 - 1148, The hex-color regex redundantly includes an uppercase A-F range even though the input variable text is lowercased earlier; update the pattern used in the re.fullmatch call that checks for hex colors (the r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})" fragment) to use only the lowercase range [0-9a-f] for each quantifier (3,4,6,8) so the match is clearer and avoids an unreachable uppercase class while preserving the same length checks.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_field_value_dom_regressions.py around lines 39 - 48, The test function test_dict_value_is_rejected_for_description_field has a docstring that incorrectly references `specifications`; update the docstring to mention `description` (or otherwise accurately describe the field under test) so it matches the assertion using coerce_field_value("description", ...). Ensure the docstring text describes the regression being tested and references the function name `test_dict_value_is_rejected_for_description_field` and the call to `coerce_field_value` for clarity.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_field_value_dom_regressions.py around lines 10 - 15, The helper function _img currently types its return as object and constructs HTML via an f-string without escaping; update the signature to return the precise type (BeautifulSoup.Tag | None or Optional[Tag]) to reflect that soup.find("img") can be None, and ensure the src is safely embedded by escaping it (use html.escape(src)) before interpolating into the HTML string; locate and modify the _img function and its use of BeautifulSoup and find() accordingly.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_listing_identity_regressions.py around lines 12 - 15, The test file mixes module-level and local imports which reduces consistency: move the utility imports (looks_like_utility_url, looks_like_utility_record, listing_detail_like_path) into each test that uses them so tests remain self-contained, and either import the private helper _unsupported_non_detail_ecommerce_merchandise_hint at the same scope as listing_url_is_structural or, better, replace its direct use with assertions against the public behavior that calls it to avoid coupling to an underscore-prefixed implementation detail; adjust import locations and add a brief comment when you intentionally rely on the private symbol.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_listing_identity_regressions.py around lines 54 - 61, Add a concise docstring to the test function test_dell_industry_landing_page_not_rescued_as_merchandise describing the specific regression scenario it guards (e.g., that a Dell industry landing page with title "State & Local Government" and the given URL should not be classified as merchandise). Match the style and tone used in the existing test_dell_landing_page_not_rescued_as_merchandise docstring so the file remains consistent.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_listing_identity_regressions.py around lines 151 - 162, Replace the loop in test_explicit_detail_markers_still_recognized with a pytest parametrized test so each URL is a separate subtest; reference the test function name test_explicit_detail_markers_still_recognized and the helper listing_detail_like_path from app.services.extract.detail_identity, add @pytest.mark.parametrize("url", [ ... ]) above the test and assert listing_detail_like_path(url, is_job=False) is True for each param to ensure failures are reported per-URL.

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: Missing trailing newline can break line-based parsing of the last URL entry
   Path: TEST_SITES.md
   Lines: 193-193

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.