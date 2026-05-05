# Codeant / CodeRabbit Flags — Open Issues

Verify each finding against current code before fixing.

## Open Issues

### detail_record_finalizer.py — Brittle brace check for features placeholder
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Lines:** ~154–155

`feature_text.startswith("{") and feature_text.endswith("}")` is a heuristic that can false-positive on legitimate JSON-like feature text. Replace with `json.loads(feature_text)` in a try/except and only pop when the parsed result is a `dict`.

### field_value_candidates.py — Duplicate `option_values` predicate
**File:** `backend/app/services/field_value_candidates.py` · **Lines:** ~809–818

`isinstance(row.get("option_values"), dict) and bool(row.get("option_values"))` appears twice — once in the `any()` filter and once in the list comprehension. Extract into a local variable (e.g., `has_option_values`) and reuse.

---

## Selector Self-Heal

### selector_self_heal.py — Redundant low-value check in `_append_reduced_node`
**File:** `backend/app/services/selector_self_heal.py` · **Lines:** ~86–89

`if node.name in SELECTOR_SYNTHESIS_LOW_VALUE_TAGS and not _keep_low_value_node(node): return 0` is redundant because `_remove_low_value_nodes(soup)` already decomposes such nodes before `_append_reduced_node` runs. Either remove the check or add a comment explaining it's defensive against callers skipping the pre-filter.

---

## Acquisition — Browser Runtime

### detail_dom_extractor.py — Positional fallback merges mismatched variants
**File:** `backend/app/services/extract/detail_dom_extractor.py` · **Line:** ~1276

When `dom_key` doesn't match any `existing_by_key`, the code falls back to `existing_by_index.get(index)`. If DOM order changes between extractions, this can merge unrelated variant pairs. Consider logging a warning when positional fallback is used, or tightening the `index_fallback_allowed` condition.

---

## Field URL Normalization

### field_url_normalization.py — Unreachable and fragile code
**File:** `backend/app/services/field_url_normalization.py` · **Lines:** ~28–35, ~122–137

`URL_CONCATENATION_ALLOWED_PREFIX_SEPARATORS` is double-wrapped in `tuple()`. Remove the redundant `tuple()` wrapper.

---

## Data Enrichment

### data_enrichment/service.py — Memoizing regex can freeze config changes
**File:** `backend/app/services/data_enrichment/service.py` · **Line:** ~758

Adding `@lru_cache` to `_material_strip_patterns` (flag #39) would freeze pattern compilation until restart. If config can change at runtime, add a `cache_clear()` mechanism or use a module-level variable with explicit invalidation instead.

---

## Low Priority — Test Assertions & Naming

### test_crawl_engine.py — Missing length assertion before `rows[0]`
**File:** `backend/tests/services/test_crawl_engine.py` · **Lines:** ~5071, ~5101

`test_extract_detail_scopes_text_away_from_customers_also_viewed_products` accesses `rows[0]` without verifying `rows` is non-empty. Add `assert len(rows) == 1` before accessing `rows[0]`.

### test_harness_support.py — Missing variant-artifact & failure-mode assertions
**File:** `backend/tests/test_harness_support.py` · **Lines:** ~537–576

`test_evaluate_quality_flags_cross_cutting_detail_invariants` sets `require_clean_variants=True` but omits asserting `quality["quality_checks"]["variant_artifacts_ok"]` and `quality["observed_failure_mode"]`. Add both assertions.

### test_detail_extractor_structured_sources.py — Test name mismatches behavior
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~1608, ~1636–1637

`test_extract_ecommerce_detail_recovers_generic_dom_variant_axes_without_site_hardcoding` asserts `variant_count` and `variants` are **absent**, meaning non-standard axes (Weight/Flavour) are ignored. Rename to `test_extract_ecommerce_detail_ignores_nonstandard_variant_axes` to match actual behavior.

### test_detail_extractor_structured_sources.py — Missing JS-state-vs-DOM variant precedence assertion
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~2094–2096

Test extracts `record` but doesn't assert that JS state variants take precedence over DOM fallback. Add assertions on variant fields.

### test_detail_extractor_structured_sources.py — Missing promo/hex variant rejection assertions
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~1559–1561

Test only asserts `len(rows) == 1`. Add assertions that promo and hex-only DOM variant values are rejected.

### test_detail_extractor_structured_sources.py — Missing Costco textual variant assertions
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~4265–4268

Test is missing assertions that "Queen" and "King" textual variants are mapped into the size field.

### test_detail_extractor_structured_sources.py — Missing generic selector axis assertion
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~2269–2272

Test doesn't assert that generic selector axis names are ignored. Add negative assertions.

### test_detail_extractor_structured_sources.py — Missing plain-button variant assertion
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~2409–2412

Test extracts `record` but never asserts the plain-button variant data. Add variant content assertions.

### test_detail_extractor_structured_sources.py — Missing newsletter rejection and content assertions
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~1528–1530

Test only checks `len(rows) == 1`. Add assertions that newsletter keys are absent and product fields are correct.

### test_detail_extractor_structured_sources.py — Missing marketing-axis pruning assertion
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~2178–2181

Test doesn't assert that single-value marketing axes ("Soft Fabric", "High Waisted") are pruned. Add negative assertions.

### test_field_value_core.py — Non-deterministic concatenated-URL rejection reason
**File:** `backend/tests/services/test_field_value_core.py` · **Lines:** ~646–656

Test allows two rejection reasons via set membership. Make deterministic by expecting the exact reason string.

---

## Refactoring — Verified Open (from coderabbit.md)

### variant_record_normalization.py
**File:** `backend/app/services/extract/variant_record_normalization.py` (lines 305-312)
**Issue:** `_size_candidate_is_gender_artifact` builds a regex at call time from `_GENDER_ARTIFACT_PATTERN` instead of using a pre-compiled module-level regex.
**Fix:** Pre-compile the formatted pattern at module scope or import a compiled `GENDER_ARTIFACT_RE` from config.

---

### test_listing_identity_regressions.py
**File:** `backend/tests/services/test_listing_identity_regressions.py` (lines 12-15)
**Issue:** Mixed module-level and local imports reduce consistency.
**Fix:** Move utility imports into each test; avoid direct use of `_unsupported_non_detail_ecommerce_merchandise_hint`.

**File:** `backend/tests/services/test_listing_identity_regressions.py` (lines 54-61)
**Issue:** Missing docstring on `test_dell_industry_landing_page_not_rescued_as_merchandise`.
**Fix:** Add docstring describing Dell industry landing page regression scenario.

**File:** `backend/tests/services/test_listing_identity_regressions.py` (lines 151-162)
**Issue:** Loop in `test_explicit_detail_markers_still_recognized` should be parametrized.
**Fix:** Use `@pytest.mark.parametrize("url", [...])` for per-URL failure reporting.

---

## Logic Errors — Open

1. `_detail_redirect_identity_is_mismatched()` skips the equal-URL shell-title rejection.
   Path: `backend/app/services/extract/detail_identity.py` · Lines: 588-606
   **Status:** Verified. When `requested == current`, the function always returns `False` regardless of whether the record has product-like signals, so shell pages with matching URLs are no longer rejected.

2. The placeholder-title regexes are too broad and will strip legitimate product titles.
   Path: `backend/app/services/extract/detail_record_finalizer.py` · Lines: 77-86
   **Status:** Verified. Patterns such as `\bnot found\b`, `\baccess denied\b`, `\bplease wait while we verify\b`, etc. can match legitimate product titles.

3. Valid object-like text can now be stripped entirely as if it were noise.
   Path: `backend/app/services/extract/detail_text_sanitizer.py` · Lines: 392-407
   **Status:** Verified. `_text_is_structured_object_repr` uses blanket `.replace("'", '"')` and similar replacements that corrupt values inside quoted strings before `json.loads`.

---

## Service Refactoring — Verified Open

### detail_extractor.py
**File:** `backend/app/services/detail_extractor.py` · Lines: 251-255
**Issue:** `add_candidate(...)` is called directly and source-tracking is appended unconditionally, bypassing `_add_sourced_candidate` validation.
**Fix:** Route additions through `_add_sourced_candidate(field_name, value, source)` or validate with `detail_candidate_is_valid` before adding and only append source after confirming the candidate was actually added.

### detail_price_extractor.py
**File:** `backend/app/services/extract/detail_price_extractor.py` · Lines: 350-354
**Issue:** `detail_price_decimal(variant.get("price"))` is invoked twice per variant in the list comprehension.
**Fix:** Compute the parsed value once per iteration and filter out `None` results.

**File:** `backend/app/services/extract/detail_price_extractor.py` · Lines: 367-368
**Issue:** Hard-coded `Decimal("0.5")` and `Decimal("2")` bounds for the parent/variant price ratio check.
**Fix:** Extract to config constants `DETAIL_PARENT_VARIANT_PRICE_RATIO_MIN` and `DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX` in `extraction_rules.py` and import them.

### detail_raw_signals.py
**File:** `backend/app/services/extract/detail_raw_signals.py` · Lines: 219-222
**Issue:** Inline imports of `_detail_url_matches_requested_identity` and `_record_matches_requested_detail_identity` to avoid circular imports.
**Fix:** Add an explanatory comment above the inline import stating it is intentionally local to avoid a circular dependency.

**File:** `backend/app/services/extract/detail_raw_signals.py` · Lines: 228-229
**Issue:** `import json` inside a hot loop causes repeated import overhead.
**Fix:** Move `import json` to the module-level imports and remove the inline import.

**File:** `backend/app/services/extract/detail_raw_signals.py` · Lines: 284-302
**Issue:** H1 pruning loop removes any H1 not exactly matching a pruned JSON-LD name, which is too aggressive.
**Fix:** Only prune H1s when there are multiple H1s and the H1 text fuzzily matches a pruned name, or only consider the first/primary H1 for pruning.

**File:** `backend/app/services/extract/detail_raw_signals.py` · Line: 7
**Issue:** `Tag` is imported from `bs4` but never used in the module.
**Fix:** Remove `Tag` from the import.

**File:** `backend/app/services/extract/detail_raw_signals.py` · Lines: 116-119
**Issue:** Hardcoded CSS pattern `r"\barrow-right(?:-[a-z]+)?\b"` in text-cleaning block.
**Fix:** Move to a config constant `DETAIL_BREADCRUMB_NOISE_ICON_PATTERNS` in `extraction_rules.py` and apply dynamically.

**File:** `backend/app/services/extract/detail_raw_signals.py` · Lines: 305-316
**Issue:** Hardcoded CSS selectors in `noise_selectors` tuple.
**Fix:** Move to a config constant `DETAIL_NOISE_SECTION_SELECTORS` in `extraction_rules.py` and import it.

**File:** `backend/app/services/extract/detail_raw_signals.py` · Lines: 284-285
**Issue:** Bare `except Exception:` silently swallows JSON-LD parsing errors.
**Fix:** Use targeted `except json.JSONDecodeError` for parse failures and log or re-raise unexpected exceptions.

### detail_record_finalizer.py
**File:** `backend/app/services/extract/detail_record_finalizer.py` · Lines: 80-86
**Issue:** WAF/queue regex patterns (`\bplease wait while we verify\b`, `\bqueue-it\b`, etc.) are inline in `_DETAIL_PLACEHOLDER_TITLE_PATTERNS`.
**Fix:** Extract queue/WAF patterns into a separate configurable constant (e.g., `WAF_QUEUE_PATTERNS`) in `extraction_rules.py`.

**File:** `backend/app/services/extract/detail_record_finalizer.py` · Lines: 57-61
**Issue:** Imports private symbol `_variant_axis_allowed_single_tokens` from `shared_variant_logic`.
**Fix:** Either expose a public constant in `shared_variant_logic` or import from `extraction_rules` and update all references.

### detail_text_sanitizer.py
**File:** `backend/app/services/extract/detail_text_sanitizer.py` · Lines: 82-85
**Issue:** Hardcoded regex `_MATERIALS_ZERO_PERCENT_PATTERN`.
**Fix:** Move to `extraction_rules.py` as `DETAIL_MATERIALS_ZERO_PERCENT_PATTERN` and compile from the imported constant.

**File:** `backend/app/services/extract/detail_text_sanitizer.py` · Lines: 392-407
**Issue:** `_text_is_structured_object_repr` corrupts values via blanket `.replace(...)` before `json.loads`.
**Fix:** Use `ast.literal_eval` first, fall back to `json.loads`, and catch `ValueError`/`SyntaxError` without destructive string replacements.

### listing_card_fragments.py
**File:** `backend/app/services/extract/listing_card_fragments.py` · Line: 286
**Issue:** Hardcoded `800` in `listing_node_text(node)[:800]`.
**Fix:** Extract to `LISTING_CHROME_TEXT_LIMIT` in `extraction_rules.py` and import it.

### shared_variant_logic.py
**File:** `backend/app/services/extract/shared_variant_logic.py` · Lines: 668-697
**Issue:** Repeated literal hint tokens (`"swatch"`, `"variant"`, `"color"`, `"size"`, `"option"`) inline in swatch-detection logic.
**Fix:** Consolidate into a single tuple constant (e.g., `VARIANT_CLASS_HINT_TOKENS`) in `extraction_rules.py` and import it.

**File:** `backend/app/services/extract/shared_variant_logic.py` · Lines: 631-640
**Issue:** Hardcoded selector string and numeric cap `20` for swatch button discovery.
**Fix:** Extract `VARIANT_SWATCH_BUTTON_SELECTOR` and `VARIANT_SWATCH_BUTTON_CAP` to `extraction_rules.py` and import them.

**File:** `backend/app/services/extract/shared_variant_logic.py` · Lines: 683-698
**Issue:** `resolve_variant_group_name(parent)` is called repeatedly inside the hot loop without caching.
**Fix:** Add a `_parent_variant_group_cache` (similar to `_parent_swatch_cache`) and use it to avoid redundant DOM traversal.

### variant_record_normalization.py
**File:** `backend/app/services/extract/variant_record_normalization.py` · Lines: 143, 472, 503, 615
**Issue:** The expression `any(clean_text(variant.get(axis)) for axis in ("size", "color", *VARIANT_AXIS_ALLOWED_SINGLE_TOKENS))` is duplicated four times.
**Fix:** Extract into a helper `_variant_has_axis_value(variant)` and replace all occurrences.

### field_value_core.py
**File:** `backend/app/services/field_value_core.py` · Lines: 904-908
**Issue:** The loop handling `VARIANT_AXIS_ALLOWED_SINGLE_TOKENS` validates the raw candidate but not the `coerce_text` result, allowing `None` or empty values into `merged`.
**Fix:** Assign `coerced = coerce_text(candidate)` and only set `merged[key] = coerced` when `coerced not in (None, "", [], {})`.

**File:** `backend/app/services/field_value_core.py` · Lines: 1470-1477
**Issue:** Function-local import of `UNRESOLVED_TEMPLATE_URL_TOKENS` in `_is_template_url` causes per-call overhead.
**Fix:** Move import and token normalization to module level, building a precomputed lowercase tuple similar to `_placeholder_image_url_tokens`.

### field_value_dom.py
**File:** `backend/app/services/field_value_dom.py` · Lines: 360-361
**Issue:** The list comprehension for `links` and the `product_links` filter are overly long and hard to read.
**Fix:** Split into clear steps: iterate over `node.select("a[href]")` up to `_max_selector_matches`, compute href/text, skip if empty, append resolved URL, then filter `product_links`.

**File:** `backend/app/services/field_value_dom.py` · Lines: 665-667
**Issue:** `_clone_visible_only(node) or node` leaks hidden content when cloning returns `None`.
**Fix:** Check the clone result into a variable; if `None`, return/emit an explicit placeholder instead of falling back to the original node.

### test_detail_extractor_structured_sources.py
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · Lines: 2042-2043
**Issue:** Test `test_extract_ecommerce_detail_does_not_treat_etsy_report_radios_as_variants` contradicts its assertions (it asserts `variant_count == 3` and `variants[0]["type"]`).
**Fix:** Rename the test to match behavior (e.g., `test_extract_ecommerce_detail_extracts_etsy_report_radios_as_type_variants`) or revert assertions to match the "does not treat" intent.


---

## Config & Runtime

### extraction_rules.py — Missing exports for DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS and NOISY_PRODUCT_ATTRIBUTE_KEYS
**File:** `backend/app/services/config/extraction_rules.py` · Lines: 203-209, 856-984
**Issue:** `DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS` and `NOISY_PRODUCT_ATTRIBUTE_KEYS` are defined at module level but not included in `_EXTRA_EXPORTS`.
**Fix:** Append `"DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS"` and `"NOISY_PRODUCT_ATTRIBUTE_KEYS"` to `_EXTRA_EXPORTS`.

### extraction_rules.py — Ambiguous naming for variant context noise depth constants
**File:** `backend/app/services/config/extraction_rules.py` · Lines: 293, 511
**Issue:** `VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH` (hard limit = 6) and `VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT` (fallback = 3) have similar names and no inline comments explaining their relationship.
**Fix:** Rename the fallback constant to `VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK` (or similar) and add a single-line comment next to both constants. Decide whether `MAX_TRACKING_KEY_LENGTH`, `MAX_TRACKING_VALUE_LENGTH`, `SCOPE_SCORE_MAIN_WEIGHT`, `SCOPE_SCORE_PRIORITY_WEIGHT`, `SCOPE_SCORE_PRODUCT_CONTEXT_WEIGHT`, and `MAX_SELECTOR_MATCHES` should be public; if so, add them to `_EXTRA_EXPORTS`.

### runtime_settings.py — Inconsistent validation for browser behavior timing fields
**File:** `backend/app/services/config/runtime_settings.py` · Lines: 395-421
**Issue:** Browser behavior fields (`browser_behavior_scroll_steps`, `browser_behavior_scroll_min_px`, `browser_behavior_scroll_max_px`, `browser_behavior_pause_min_ms`, `browser_behavior_pause_jitter_ms`, `browser_behavior_typing_min_delay_ms`, `browser_behavior_typing_jitter_ms`) use silent `_clamp_to_non_negative` instead of error-raising `_require_non_negative` like other fields.
**Fix:** Replace `_clamp_to_non_negative` with `_require_non_negative` for those fields.

---

## Acquisition / Fetch

### crawl_fetch_runtime.py — http_max_retries can be None
**File:** `backend/app/services/crawl_fetch_runtime.py` · Line: 773
**Issue:** `max(1, int(crawler_runtime_settings.http_max_retries) + 1)` raises `TypeError` when `http_max_retries` is `None`.
**Fix:** Coalesce the raw value before conversion (e.g., `retries = int(crawler_runtime_settings.http_max_retries or 0)` then `max_attempts = max(1, retries + 1)`).

### crawl_fetch_runtime.py — _sleep_before_retry calls int() on possibly-None backoff values
**File:** `backend/app/services/crawl_fetch_runtime.py` · Lines: 1133-1136
**Issue:** `int(crawler_runtime_settings.http_retry_backoff_base_ms)` and `int(crawler_runtime_settings.http_retry_backoff_max_ms)` can raise `TypeError` if the config values are `None`.
**Fix:** Guard with `or 0` before `int()`, mirroring the `_resolve_http_timeout` defensive pattern.

### crawl_fetch_runtime.py — _retryable_status_for_http_fetch can raise ValueError
**File:** `backend/app/services/crawl_fetch_runtime.py` · Lines: 1128-1130
**Issue:** The set comprehension `{int(value) for value in ...}` raises `ValueError` if any entry in `http_retry_status_codes` is non-numeric.
**Fix:** Build the set only from successfully parsed integers inside a `try/except`.

---

## Extraction

### detail_dom_extractor.py — DOM_VARIANT_GROUP_LIMIT not coerced defensively
**File:** `backend/app/services/extract/detail_dom_extractor.py` · Lines: 1092-1093
**Issue:** `int(DOM_VARIANT_GROUP_LIMIT)` can raise `ValueError` if the config is `None`/empty/non-numeric.
**Fix:** Use a safe parse with a fallback to `1` while preserving `max(1, ...)` semantics.

### detail_raw_signals.py — @graph normalization ignores single-dict case
**File:** `backend/app/services/extract/detail_raw_signals.py` · Lines: 229-244
**Issue:** When `item.get("@graph")` returns a single `dict`, the code falls back to `[item]` instead of treating it as a single-element list.
**Fix:** Normalize dict-to-list for both the list-comprehension flattening and the `graph = payload.get("@graph")` branch.

### detail_raw_signals.py — import json inside hot loop
**File:** `backend/app/services/extract/detail_raw_signals.py` · Lines: 228-229
**Issue:** `import json` is repeated inside the JSON-LD script loop.
**Fix:** Move `import json` to the module-level imports.

### detail_record_finalizer.py — Literal "out_of_stock" instead of config constant
**File:** `backend/app/services/extract/detail_record_finalizer.py` · Lines: 1088-1091
**Issue:** `record["availability"] = "out_of_stock"` uses a hardcoded literal while `AVAILABILITY_IN_STOCK` is already imported from config.
**Fix:** Define `AVAILABILITY_OUT_OF_STOCK` in `extraction_rules.py` and use it.

### detail_record_finalizer.py — PEP8 blank line violations between top-level functions
**File:** `backend/app/services/extract/detail_record_finalizer.py` · Lines: 187-195
**Issue:** Only one blank line separates `_feature_text_is_json_object` and `_sanitize_detail_identity_scalars`; PEP8 requires two.
**Fix:** Add two blank lines before `_feature_text_is_json_object` and two before `_sanitize_detail_identity_scalars`.

### detail_text_sanitizer.py — Hardcoded word_count threshold in bracket-prose extraction
**File:** `backend/app/services/extract/detail_text_sanitizer.py` · Lines: 421-431
**Issue:** `word_count >= 5` is a magic number in the bracket-prose candidate loop.
**Fix:** Extract to `DETAIL_BRACKET_PROSE_MIN_WORDS` in `extraction_rules.py` and import it.

### listing_card_fragments.py — Broad except Exception in CSS selector parsing
**File:** `backend/app/services/extract/listing_card_fragments.py` · Lines: 54-56
**Issue:** `except Exception:` catches `MemoryError`, `KeyboardInterrupt`, etc.
**Fix:** Narrow to the specific selectolax parsing exception(s) and `ValueError`, keeping `logger.warning(..., exc_info=True)`.

### shared_variant_logic.py — Fallback depth conversion unguarded
**File:** `backend/app/services/extract/shared_variant_logic.py` · Lines: 165-169
**Issue:** `int(VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT)` in the fallback path can itself raise `TypeError`/`ValueError`.
**Fix:** Wrap that conversion in its own `try/except`; if it fails, set `depth = 0`.

### variant_record_normalization.py — Hardcoded gender regex in _size_candidate_is_gender_artifact usage
**File:** `backend/app/services/extract/variant_record_normalization.py` · Lines: 285-286
**Issue:** `re.search(r"\b(?:men|women|boys|girls)['']?s\b", text.lower())` is inline and duplicates the gender-detection concept already in `_GENDER_ARTIFACT_PATTERN`.
**Fix:** Replace the inline regex with the config-driven `_GENDER_ARTIFACT_PATTERN` (or a dedicated constant) so gender artifacts are handled consistently.

### variant_record_normalization.py — DEFAULT_DETAIL_MAX_VARIANT_ROWS fallback not guarded
**File:** `backend/app/services/extract/variant_record_normalization.py` · Lines: 603-606
**Issue:** `int(DEFAULT_DETAIL_MAX_VARIANT_ROWS)` in the fallback can raise if misconfigured.
**Fix:** Wrap both conversions defensively and ultimately ensure `max_rows = max(1, safe_value)` with a hard-coded safe fallback if both fail.

### variant_record_normalization.py — Hardcoded gender keyword set in size extraction
**File:** `backend/app/services/extract/variant_record_normalization.py` · Lines: 399-409
**Issue:** Inline set `{"men", "mens", "women", "womens", "boys", "girls"}` is duplicated and not centralized.
**Fix:** Import a centralized `GENDER_KEYWORD_TOKENS` constant from `extraction_rules.py` and replace all inline occurrences.

---

## Field Value & Core

### field_value_candidates.py — Hardcoded price field sets
**File:** `backend/app/services/field_value_candidates.py` · Lines: 442-444
**Issue:** `_source_key_is_price_field` uses inline sets `{"price", "sale_price", "original_price", "compare_at_price"}`.
**Fix:** Move to config constants (`PRICE_SOURCE_KEY_FIELDS`, `CANONICAL_PRICE_FIELDS`) in `extraction_rules.py` and import them.

### field_value_core.py — _price_text_is_negative hardcodes currency symbols
**File:** `backend/app/services/field_value_core.py` · Lines: 595-600
**Issue:** `re.match(r"^\s*-\s*(?:[$€£¥₹]|[A-Z]{3}\b)?\s*\d", ...)` embeds literal symbols.
**Fix:** Build the character class dynamically from `CURRENCY_SYMBOL_MAP` keys, escaping as needed; fall back to a pattern that only checks for leading `-` and digit if the map is empty.

### field_value_core.py — SIZE_REJECT_TOKENS rebuilt on every call
**File:** `backend/app/services/field_value_core.py` · Lines: 705-706
**Issue:** `frozenset(SIZE_REJECT_TOKENS or ())` is constructed inline inside `_sanitize_option_scalar` on every call.
**Fix:** Pre-compute a module-level `_SIZE_REJECT_TOKENS` frozenset (casefolded) at import time.

### field_value_dom.py — _split_feature_text uses aggressive lstrip
**File:** `backend/app/services/field_value_dom.py` · Lines: 1360-1372
**Issue:** `cleaned.lstrip("- ")` removes any leading `-` or space characters individually, so `'---note'` becomes `'note'`.
**Fix:** Use `re.sub(r'^-\s*', '', cleaned)` for targeted single-dash removal before splitting.

---

## Provider / Pipeline / Misc Services

### llm_provider_client.py — New AsyncClient per request in _call_groq
**File:** `backend/app/services/llm_provider_client.py` · Lines: 143-167
**Issue:** `_call_groq` creates a new `httpx.AsyncClient` per request, preventing connection reuse.
**Fix:** Use a shared/reused `AsyncClient` (module-level or injected), configured with `llm_runtime_settings.provider_timeout_seconds`, and ensure it is properly started/closed on app startup/shutdown.

### normalizers/__init__.py — Hardcoded currency regex in early-return branch
**File:** `backend/app/services/normalizers/__init__.py` · Lines: 101-102
**Issue:** `re.match(r"^\s*-\s*(?:[$€£¥₹]|[A-Za-z]{3}\b)?\s*\d", text)` hardcodes symbols and `[A-Za-z]{3}` instead of using `_CURRENCY_CODE_CONTEXT_PATTERN`.
**Fix:** Replace `[A-Za-z]{3}` with the config-driven `_CURRENCY_CODE_CONTEXT_PATTERN`; drop the redundant `^\s*` since `_normalize_text` already strips whitespace.

### pipeline/core.py — Unused browser_diagnostics assignment
**File:** `backend/app/services/pipeline/core.py` · Lines: 441-443
**Issue:** `browser_diagnostics = getattr(acquisition_result, "browser_diagnostics", {})` is assigned but never used in the subsequent condition.
**Fix:** Remove the unused assignment and keep the condition that uses `_effective_blocked(acquisition_result)` and `_browser_attempted(acquisition_result)`.

### selector_self_heal.py — Hardcoded slice limit [:6]
**File:** `backend/app/services/selector_self_heal.py` · Lines: 179-207
**Issue:** `targets[:6]` is a magic number used in two places.
**Fix:** Extract to a configurable constant (e.g., `SELF_HEAL_TARGET_LIMIT`) with a default of `6`.

### selector_self_heal.py — Hardcoded keep-worthy tag set
**File:** `backend/app/services/selector_self_heal.py` · Lines: 128-155
**Issue:** `node.name not in {"button", "input", "select"}` is inline.
**Fix:** Move to `SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS` in `app/services/config/selectors.py` and import it.

### selector_self_heal.py — Hardcoded default confidence 0.55
**File:** `backend/app/services/selector_self_heal.py` · Lines: 168-175
**Issue:** `default=0.55` is inline in the confidence extraction call.
**Fix:** Extract to `SELECTOR_SELF_HEAL_DEFAULT_MIN_CONFIDENCE` in the selectors config.

### harness_support.py — Missing log on password sync
**File:** `backend/harness_support.py` · Lines: 1513-1527
**Issue:** When `verify_password` fails and the harness user password is re-hashed, no log entry is emitted.
**Fix:** Add an informational log (e.g., `logger.info(...)`) in the sync branch that records the user ID/email and a short context message.

---

## Tests

### test_crawl_engine.py — Duplicate assertion
**File:** `backend/tests/services/test_crawl_engine.py` · Line: 1009-1010
**Issue:** Two identical consecutive lines `assert len(rows) == 1`.
**Fix:** Remove one of the duplicate assertions.

### test_field_value_dom_regressions.py — Missing null guard after _img()
**File:** `backend/tests/services/test_field_value_dom_regressions.py` · Lines: 13-18
**Issue:** `_img()` returns `Tag | None`; test callers access `node.get("src")` without checking for `None`.
**Fix:** Add `assert node is not None` immediately after each `_img()` call.

### test_network_payload_mapper.py — Incomplete job-api non-dict rejection test
**File:** `backend/tests/services/test_network_payload_mapper.py` · Lines: 253-260
**Issue:** `test_looks_like_job_api_rejects_non_dict` only asserts `None`; `test_looks_like_product_api_rejects_non_dict` covers both string and list.
**Fix:** Add string and list assertions to the job-api test, mirroring the product-api test.

### test_state_mappers.py — Missing size assertion
**File:** `backend/tests/services/test_state_mappers.py` · Lines: 197-198
**Issue:** The test asserts `mapped["color"] == "Cool Grey"` but the input includes a size variation that is never checked.
**Fix:** Add `assert mapped["size"] == "S"` alongside the color assertion.

### test_harness_support.py — Duplicate _FakeSession class
**File:** `backend/tests/test_harness_support.py` · Lines: 840-846, 904-910
**Issue:** `_FakeSession` is defined identically in two tests.
**Fix:** Extract to a shared pytest fixture (e.g., in `conftest.py` or module top) and have both tests use it.

### test_harness_support.py — Hardcoded Windows path
**File:** `backend/tests/test_harness_support.py` · Lines: 74-93
**Issue:** `Path("C:/Projects/pre_poc_ai_crawler/TEST_SITES.md")` is non-portable.
**Fix:** Build the path from `Path(__file__).parent / "TEST_SITES.md"` (or equivalent relative-to-repo logic).

---

## Skipped / Not Applicable

- `backend/app/services/config/browser_fingerprint_profiles.py` line 35 — `REAL_CHROME_IGNORE_DEFAULT_ARGS` is defined but never referenced anywhere in the codebase; cannot verify the claim about automation flags remaining enabled. Skipping.
- `backend/app/services/config/field_mappings.py` line 222 — `BRAND_LIKE_FIELDS` is an intentionally-defined frozenset (`{"brand", "company", "dealer_name", "vendor"}`); no specific missing aliases were identified. Skipping.
- `backend/app/services/config/field_mappings.py` line 223 — `OPTION_SCALAR_FIELDS` is an intentionally-defined frozenset (`{COLOR_FIELD, "condition", "material", SIZE_FIELD, "storage", "style"}`); no specific missing fields were identified. Skipping.
- `backend/app/services/config/runtime_settings.py` line 372 — `min_max_pages < 1` validation is consistent with the rest of the file's validation style; no evidence that prior clamping was replaced by this raise. Skipping.