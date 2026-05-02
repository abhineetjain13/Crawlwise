# Verified Code Review Issues

This file contains only verified bugs and issues found across the codebase. Duplicates, unverified concerns, and purely stylistic preferences have been removed.

---

## Backend — Models & Config

1. **backend/app/models/llm.py** (lines 44-48)
   CheckConstraint uses literal strings `"success"` / `"error"`. Define a centralized `StrEnum` or module-level constants and reference them so service code avoids magic strings.

2. **backend/app/services/config/extraction_rules.py** (line 144)
   `OPTION_VALUE_NOISE_WORDS` duplicates terms without a shared canonical symbol. Consolidate into a single `NOISE_WORDS` tuple and compose derived patterns from it.

3. **backend/app/services/config/extraction_rules.py** (lines 268-285)
   `AVAILABILITY_URL_MAP` maps schema URL variants to inconsistent naming: `"preorder"` instead of snake_case `"pre_order"`. Align all entries to `"pre_order"`.

4. **backend/app/services/config/llm_runtime.py** (lines 22-24)
   `DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD` only lists `"groq/llama-3.3-70b-versatile"` while `SUPPORTED_LLM_PROVIDERS` also includes `"anthropic"` and `"nvidia"`. Add sensible default pricing entries for those providers.

5. **backend/app/services/config/llm_runtime.py** (lines 76-100)
   `get_token_pricing` can return an empty dict when the user-provided JSON parses successfully but all entries are malformed or filtered out. Fallback to `DEFAULT_LLM_TOKEN_PRICING_PER_MILLION_USD` when the resulting dict is empty.

6. **backend/app/services/config/block_signatures.py** (lines 26-28)
   Phrase list contains a redundant entry: `"unusual traffic from your computer network"` is a substring of `"our systems have detected unusual traffic from your computer network"`. Remove the shorter string or deduplicate.

7. **backend/app/services/config/data_enrichment.py** (lines 132-138)
   `DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS` uses a broad `r"\biron\b"` that strips legitimate material phrases (e.g. "wrought iron", "iron oxide"). Narrow it to ironing/care-instruction variants only.

8. **backend/app/services/config/data_enrichment.py** (lines 139-158)
   `DATA_ENRICHMENT_TAXONOMY_CONTEXT_BLOCKS` lacks a docstring explaining semantics of `context_terms` (positive context) vs `path_terms` (exclusions), casing expectations, and disambiguation logic.

---

## Backend — Data Enrichment

9. **backend/app/services/data_enrichment/service.py** (lines 718-723)
   `_normalize_materials()` only falls back to `DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS` when primary fields return *nothing*. If primary fields return unusable/noisy values, fallback is skipped.

10. **backend/app/services/data_enrichment/service.py** (lines 628-636)
    `_normalize_sizes()` suppresses all valid sizes when `category_match` claims the category does not support size, even if explicit size data exists in the record.

11. **backend/app/services/data_enrichment/service.py** (lines 739-751)
    `COMPILED_DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS` is compiled at module-import time via `_compiled_material_strip_patterns()`, causing `logger.warning()` before logging is configured. Defer compilation to first use.

12. **backend/app/services/data_enrichment/shopify_catalog.py** (lines 49-57)
    `normalize_taxonomy_token` redundantly calls `.casefold()` even though `tokenize_text` already casefolds tokens before passing them.

13. **backend/app/services/data_enrichment/shopify_catalog.py** (lines 49-58)
    `normalize_taxonomy_token` handles `-ies` and `-sses` plurals but misses other `-es` plurals (e.g. `boxes` -> `box`). Add an `endswith("es")` branch after the existing checks.

14. **backend/app/services/data_enrichment/shopify_catalog.py** (lines 166-173)
    Scoring weights (`0.35`, `0.15`, `0.3`) and the `0.6` no-primary penalty are hardcoded. Extract into a config constant (e.g. `DATA_ENRICHMENT_TAXONOMY_SCORE_WEIGHTS`).

15. **backend/app/services/data_enrichment/shopify_catalog.py** (lines 196-214)
    `joined_source = " ".join(sorted(source_tokens))` alphabetizes tokens, breaking multi-word phrase matching in `context_terms` substring checks. Preserve original token order or switch to bag-of-words/n-gram matching.

---

## Backend — Extraction & Identity

16. **backend/app/services/detail_extractor.py** (lines 1123-1124)
    `_prepare_detail_extraction` creates a second full `BeautifulSoup` parse (`raw_soup`) duplicating memory already held in `soup`. Reuse the existing parse or defer until needed.

17. **backend/app/services/detail_extractor.py** (lines 957-963)
    `_requires_dom_completion` compares `record.get("category")` to `breadcrumb_category` with raw string equality. Normalization (casefold, whitespace collapse, separator normalization) is missing, causing unnecessary DOM tier completion when values are semantically equivalent.

18. **backend/app/services/extract/detail_identity.py** (lines 28-50)
    `_DETAIL_IDENTITY_STOPWORDS` is a hardcoded `frozenset`. Move it into `app/services/config/extraction_rules.py` and import it.

19. **backend/app/services/extract/detail_identity.py** (lines 140-148)
    `detail_roots` (`{"job","jobs","opening",...}`) is hardcoded inline. Move to config under a clear constant name (e.g. `JOB_LISTING_DETAIL_PATH_MARKERS`).

20. **backend/app/services/extract/detail_identity.py** (lines 617-629)
    Magic number `8` (minimum identity code length) is hardcoded in `_normalized_detail_identity_code` and the `re.findall(r"[A-Za-z0-9]{8,}", ...)` regex. Extract to a named config constant.

21. **backend/app/services/extract/detail_identity.py** (lines 277-292)
    Substring check `any(token in chunk for token in generic_terminal_tokens)` is too permissive; terminals like `productsABC123XYZ` are incorrectly skipped because a generic token matches inside the chunk. Use exact token matching or word-boundary checks.

22. **backend/app/services/extract/detail_dom_extractor.py** (lines 321-327)
    Chained boolean expression in variant-option noise check has `is not None` dangling on its own line, hurting readability. Reformat so each `re.fullmatch(...)` and its `is not None` stay paired on the same logical line.

23. **backend/app/services/extract/detail_raw_signals.py** (lines 33-39)
    `breadcrumb_category_from_dom` parameter `current_title` is typed too broadly as `object`. Tighten to `str | None = None` and propagate the change to callers.

24. **backend/app/services/extract/detail_raw_signals.py** (lines 56-61)
    In `breadcrumb_labels_from_dom`, the `if labels:` check is outside the inner `for container` loop. Results from earlier containers are overwritten by the last container; the first non-empty breadcrumb from any container should be returned immediately.

25. **backend/app/services/extract/detail_raw_signals.py** (lines 97-124)
    `_trim_breadcrumb_labels` uses `.strip().lower()` for the root-label check but `.casefold()` for title comparison. Use consistent Unicode-aware normalization (`clean_text(...).casefold()`) and ensure `DETAIL_BREADCRUMB_ROOT_LABELS` values are casefolded at comparison time.

---

## Backend — Field Value, Normalizers, Pipeline & LLM

26. **backend/app/services/field_value_core.py** (lines 475-480)
    `coerce_text` flags any string containing `&` as HTML, incorrectly treating normal text like `"AT&T"`. Detect real HTML entity patterns (alphanumeric/numeric references followed by `;`) before calling `html_to_text`.

27. **backend/app/services/field_value_dom.py** (lines 49-53)
    `VARIANT_OPTION_CHILD_DROP_RE` compiles regex patterns at import time without error handling. A malformed pattern will raise `re.error` and prevent module import. Wrap compilation in `try/except re.error`, log invalid patterns, and collect only successfully compiled objects.

28. **backend/app/services/field_value_dom.py** (lines 490-501)
    `_variant_option_node_text` uses `del field_name` to suppress the unused parameter. Rename the parameter to `_field_name` in the signature and remove the `del` line.

29. **backend/app/services/field_value_candidates.py** (lines 107-116)
    Inline import `from urllib.parse import urlparse` is inside a function instead of at module scope. Move it to the top, and replace the broad `except Exception: pass` with a specific parsing-related exception handler.

30. **backend/app/services/normalizers/__init__.py** (lines 17-24)
    `_CURRENCY_CODE_CONTEXT_PATTERN` explicitly excludes `"rs"` but has no comment explaining why. Add an inline comment noting the false-positive risk with that substring.

31. **backend/app/services/normalizers/__init__.py** (lines 74-82)
    Boolean/remote token set (`"true","1","yes","remote",...`) is hardcoded inline. Move to a config constant (e.g. `REMOTE_BOOLEAN_TOKENS`) under `app/services/config/`.

32. **backend/app/services/normalizers/__init__.py** (lines 170-172)
    `if mapped:` in `_normalize_availability` skips falsy but valid mapped values (e.g. `""`, `0`, `False`). Change to `if mapped is not None:`.

33. **backend/app/services/pipeline/extraction_retry_decision.py** (lines 213-219)
    Stale inline comment above the identity/price check still says `"title OR image_url"`. Update it to reflect configurable `DETAIL_IDENTITY_FIELDS` and `_html_has_configured_detail_price`.

34. **backend/app/services/pipeline/extraction_retry_decision.py** (lines 286-294)
    Variant field names `{"variants", "selected_variant"}` are hardcoded. Extract into a config constant (e.g. `VARIANT_FIELDS`) similar to `DETAIL_IDENTITY_FIELDS` / `PRICE_FIELDS`.

35. **backend/app/services/llm_provider_client.py** (lines 109-113)
    `_safe_token_count` parameter is typed as `object` but is only ever called with `int | None`. Tighten the type hint to `int | None`.

36. **backend/app/services/llm_tasks.py** (lines 229-261)
    `_record_cost_log` calls `session.add(...)` and `await session.flush()` without error handling. A DB error bubbles up and can discard a valid LLM result. Wrap cost-logging in `try/except`, log the failure, and return quietly.

37. **backend/alembic/versions/20260501_0021_llm_cost_log_outcome.py** (lines 43-45)
    Index creation on `ix_llm_cost_log_outcome` is a full index and not created concurrently. For PostgreSQL, use `postgresql_concurrently=True` and run outside a transaction. Optionally also make it a partial index (`postgresql_where=sa.text("outcome = 'error'")`).

38. **backend/app/schemas/llm.py** (lines 72-84)
    `error_category` Literal includes redundant `"none"` alongside `""`. Remove `"none"` and ensure all assignments/checks use `""` consistently.

---

## Backend — Product Intelligence

39. **backend/app/services/product_intelligence/discovery.py** (lines 392-403)
    `_google_native_blocked` hardcodes Google detection strings (`"/sorry/"`, `"unusual traffic..."`, etc.). Move them to config constants (`GOOGLE_NATIVE_BLOCKED_URL_PATTERNS`, `GOOGLE_NATIVE_BLOCKED_HTML_PATTERNS`).

40. **backend/app/services/product_intelligence/discovery.py** (lines 415-420)
    `_google_native_blocked` calls `classify_blocked_page(html, 200)` with a hardcoded HTTP 200 status, which can mislead classification. Forward the real response status when available, or pass `None`/document the intentional default.

41. **backend/app/services/product_intelligence/discovery.py** (line 343)
    Hardcoded `+1500` typing extra wait is not configurable. Add a runtime tunable (e.g. `GOOGLE_NATIVE_TYPING_EXTRA_WAIT_MS`) and reference it.

42. **backend/app/services/product_intelligence/discovery.py** (lines 344-357)
    Two identical fallback navigation blocks (`page.goto(...) + page.wait_for_timeout(...)`) are duplicated. Extract into a helper or consolidate after the conditional branches.

43. **backend/app/services/product_intelligence/service.py** (lines 181-182)
    Authorization check uses hardcoded `"admin"` role string. Replace with a config constant (e.g. `ADMIN_ROLE`).

44. **backend/app/services/product_intelligence/service.py** (lines 436-438)
    Loop calls `await session.flush()` per iteration to get `source.id`, causing N+1 DB round-trips. Collect instances, add them all, then call a single `flush()` after the loop.

45. **backend/app/services/product_intelligence/service.py** (lines 633-634)
    Final-status set `{"completed", "failed", "killed", "proxy_exhausted"}` is hardcoded inline. Extract into a config constant (e.g. `CRAWL_RUN_FINAL_STATUSES`).

---

## Frontend

46. **frontend/components/crawl/crawl-run-screen.tsx** (line 859)
    Domain anchor uses `text-accent` while a similar anchor elsewhere uses `link-accent`. Unify to `link-accent` for consistent link color styling. **Risk:** `link-accent` CSS class does not currently exist in the codebase; creating or migrating to it requires broader styling audit.

47. **frontend/components/crawl/crawl-run-screen.tsx** (line 985)
    Anchor using `link-accent` redundantly re-declares `underline-offset-2 hover:underline`. If `link-accent` already includes underline rules, remove the duplicates; otherwise consider whether `link-accent` or `text-accent` is the correct semantic class. **Risk:** `link-accent` CSS class does not currently exist in the codebase.

---

## Tests

55. **backend/tests/services/test_data_enrichment.py** (lines 397-399)
    `test_data_enrichment_variant_dict_values_do_not_pollute_sizes_or_availability` uses parenthesized return annotation `-> (None)`. Replace with standard `-> None`.

56. **backend/tests/services/test_detail_extractor_structured_sources.py** (lines 21-23)
    `test_detail_currency_hint_host_matching_avoids_partial_word_false_positive` uses parenthesized return annotation `-> (None)`. Replace with `-> None` across all such defs in the file.

57. **backend/tests/services/test_llm_runtime.py** (lines 162-165)
    Assertion compares enum via `str(llm_runtime.LLMErrorCategory.RATE_LIMITED)`, which is fragile. Compare against `.value` or `.name` depending on serialization.

58. **backend/tests/services/test_normalizers.py** (lines 29-31)
    `test_normalize_decimal_price_rejects_ambiguous_integer_text_without_price_context` uses parenthesized return annotation `-> (None)`. Replace with `-> None` across the file.

59. **backend/tests/services/test_product_intelligence.py** (lines 67-96)
    `test_product_intelligence_query_keeps_brand_in_all_queries_when_brand_exists` and `test_product_intelligence_query_prefers_clean_brand_query_before_buy_for_aggregator_sources` assert exact query string equality, making tests brittle to minor formatting changes. Use structural/membership assertions instead.

60. **backend/tests/services/test_product_intelligence.py** (lines 161-164)
    `test_product_intelligence_classifies_common_aggregator_sources` is misnamed: it tests retailers/marketplaces (`myntra.com`, `nykaa.com`, `flipkart.com`), not aggregators. Rename to reflect actual assertions.

61. **backend/tests/services/test_product_intelligence.py** (lines 492-493)
    Assertions `assert second and third` are too weak. Add explicit content assertions (URL checks, length checks) matching the `first` assertions.

62. **backend/tests/services/test_product_intelligence.py** (lines 493-561)
    Mock browser setup (`_Page`, `_Runtime`, `_fake_runtime`, `_fake_html`, `actions`, `html_by_url`) is duplicated across `test_google_native_session_stops_after_google_sorry_page` and `test_google_native_session_reuses_single_page_across_queries`. Extract into a reusable pytest fixture.

63. **backend/tests/services/test_product_intelligence.py** (lines 564-570)
    `_fake_search_url` performs an inline `from urllib.parse import urlencode` instead of using a module-level import. Move the import to the top of the test file.

64. **backend/tests/services/test_product_intelligence.py** (lines 1226-1239)
    One `fake_search_results` mock suppresses unused parameters with `del provider, limit`, but other `fake_search_results` variants in the same file do not. Apply the same suppression consistently or remove it everywhere.

65. **backend/tests/services/test_selectolax_css_migration.py** (lines 94-96)
    `test_listing_extractor_prefers_row_detail_link_and_name_over_breadcrumb_links` uses parenthesized return annotation `-> (None)`. Replace with `-> None` across the file.

66. **backend/tests/services/test_structure.py** (lines 228-238)
    `test_data_enrichment_taxonomy_matching_does_not_use_manual_category_alias_maps` does a raw string search that can match comments/docstrings. Parse the config file with `ast.parse` and inspect actual AST nodes instead.

67. **backend/tests/services/test_structure.py** (lines 241-245)
    `test_private_service_imports_do_not_drift` checks bidirectional equality between offenders and the allowlist, but its name suggests a one-way check. Rename to reflect the bidirectional assertion (e.g. `test_private_service_imports_match_allowlist`).
