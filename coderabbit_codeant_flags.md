# Codeant / CodeRabbit Flags — Open Issues

Verify each finding against current code before fixing.

---

## Adapters

### 5. shopify.py — Unused `_selectable_axes` from `_split_selectable_axes`
**File:** `backend/app/services/adapters/shopify.py` · **Lines:** ~172–174, ~344

`_selectable_axes` is assigned but never used after `self._split_selectable_axes(axes)`. Either unpack only `single_value_attributes` or create a dedicated method that returns just that value, and remove the unused `_selectable_axes` variable from both call sites.


---

## Config & Schema

### 18. detail_price_extractor.py — Redundant early-return in `_detail_price_from_html`
**File:** `backend/app/services/extract/detail_price_extractor.py` · **Lines:** ~579–581

`if jsonld_price: return jsonld_price` is defensive—callers already gate on `jsonld_price or _detail_price_from_html(...)`. Either remove the check or add a comment explaining it's intentional defensive coding.

---

## Extraction — DOM & Variants

### 21. detail_record_finalizer.py — `strip_chars` TypeError risk
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Line:** ~287

`"".join(tuple(DETAIL_BREADCRUMB_SEPARATOR_LABELS or ()))` will raise `TypeError` if the iterable contains non-string elements. Use `"".join(map(str, DETAIL_BREADCRUMB_SEPARATOR_LABELS or ()))` to coerce each element.

### 22. detail_record_finalizer.py — Hardcoded `"in_stock"` literal
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Lines:** ~560, ~1081–1082

`parent_availability == "in_stock"` and `record["availability"] = "in_stock"` use a hardcoded literal. Add `AVAILABILITY_IN_STOCK = "in_stock"` to config and import it.

### 23. detail_record_finalizer.py — Brittle brace check for features placeholder
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Lines:** ~154–155

`feature_text.startswith("{") and feature_text.endswith("}")` is a heuristic that can false-positive on legitimate JSON-like feature text. Replace with `json.loads(feature_text)` in a try/except and only pop when the parsed result is a `dict`.

### 31. field_value_core.py — `_coerce_barcode` rebuilds set on every call
**File:** `backend/app/services/field_value_core.py` · **Line:** ~1246

`len(digits) not in set(PUBLIC_RECORD_BARCODE_LENGTHS or ())` rebuilds the set each call. Pre-compute `_PUBLIC_RECORD_BARCODE_LENGTHS_SET` at module level.

### 32. field_value_candidates.py — Duplicate `option_values` predicate
**File:** `backend/app/services/field_value_candidates.py` · **Lines:** ~809–818

`isinstance(row.get("option_values"), dict) and bool(row.get("option_values"))` appears twice—once in the `any()` filter and once in the list comprehension. Extract into a local variable (e.g., `has_option_values`) and reuse.

### 34. field_value_dom.py — Hardcoded feature section selectors
**File:** `backend/app/services/field_value_dom.py` · **Line:** ~1355

`"[data-section='features'], .features, .product-features, #features"` is inline. Move to `FEATURE_SECTION_SELECTORS` in extraction rules config and import it.

### 35. field_value_dom.py — Hardcoded scope weights in `_scope_score`
**File:** `backend/app/services/field_value_dom.py` · **Lines:** ~377, ~379, ~387

Weights `4000`, `2000`, `1000` and inline tokens `("product", "detail", "pdp")` are hardcoded. Extract into config constants so they can be tuned without changing service code.

### 36. field_value_dom.py — `_node_has_cross_product_cluster` uses empty base URL
**File:** `backend/app/services/field_value_dom.py` · **Line:** ~345

`absolute_url("", str(link.get("href") or ""))` passes empty string as base, so relative hrefs never resolve correctly. Accept a `page_url`/`base_url` parameter to resolve relative links against a real base.

---

## Selector Self-Heal

### 37. selector_self_heal.py — Redundant low-value check in `_append_reduced_node`
**File:** `backend/app/services/selector_self_heal.py` · **Lines:** ~86–89

`if node.name in SELECTOR_SYNTHESIS_LOW_VALUE_TAGS and not _keep_low_value_node(node): return 0` is redundant because `_remove_low_value_nodes(soup)` already decomposes such nodes before `_append_reduced_node` runs. Either remove the check or add a comment explaining it's defensive against callers skipping the pre-filter.

### 38. selector_self_heal.py — Hardcoded attrs/tokens in `_keep_low_value_node`
**File:** `backend/app/services/selector_self_heal.py` · **Lines:** ~133–138, ~155–156

`("data-variant-id", "data-product-id", "data-price", "value")` and `("buy", "cart", "pdp", "product", "variant")` are hardcoded. Extract to `SELECTOR_SYNTHESIS_KEEP_ATTRS` and `SELECTOR_SYNTHESIS_KEEP_TOKENS` in config and import them.

---

## Service Logic

### 41. harness_support.py — Case-sensitive gender validation
**File:** `backend/harness_support.py` · **Lines:** ~1188–1189

`gender not in _ALLOWED_GENDERS` is case-sensitive—`"men"` or `"WOMEN"` would fail. Normalize both sides: compare `gender.lower()` against a precomputed `_ALLOWED_GENDERS_LOWER` set.

### 42. harness_support.py — Missing high-denomination currency "CLP"
**File:** `backend/harness_support.py` · **Line:** ~42

`_HIGH_DENOMINATION_PRICE_CURRENCIES` includes `{"INR", "JPY", "KRW", "VND", "IDR", "HUF"}` but is missing `"CLP"`. Add it so the 10,000 threshold applies correctly.

---

## Test Assertions

### 43. test_crawl_engine.py — Missing length assertion before `rows[0]`
**File:** `backend/tests/services/test_crawl_engine.py` · **Lines:** ~5071, ~5101

Both `test_extract_detail_scopes_text_away_from_customers_also_viewed_products` and `test_extract_detail_rejects_placeholder_and_ui_asset_images` access `rows[0]` without verifying `rows` is non-empty. Add `assert len(rows) == 1` before accessing `rows[0]`.

### 44. test_network_payload_mapper.py — Permissive `>= 1` assertions
**File:** `backend/tests/services/test_network_payload_mapper.py` · **Lines:** ~310, 337, 361, 396

Change `assert len(rows) >= 1` to `assert len(rows) == 1` to catch unexpected duplicates or extra rows.

### 45. test_harness_support.py — Missing variant-artifact & failure-mode assertions
**File:** `backend/tests/test_harness_support.py` · **Lines:** ~537–576

`test_evaluate_quality_flags_cross_cutting_detail_invariants` sets `require_clean_variants=True` but omits asserting `quality["quality_checks"]["variant_artifacts_ok"]` and `quality["observed_failure_mode"]`. Add both assertions.

### 46. test_detail_extractor_structured_sources.py — Test name mismatches behavior
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~1608, ~1636–1637

`test_extract_ecommerce_detail_recovers_generic_dom_variant_axes_without_site_hardcoding` asserts `variant_count` and `variants` are **absent**, meaning non-standard axes (Weight/Flavour) are ignored. Rename to `test_extract_ecommerce_detail_ignores_nonstandard_variant_axes` to match actual behavior.

## Acquisition — Browser Runtime

### 52. browser_runtime.py — `inject_init_script` semantics inverted in native Chrome branch
**File:** `backend/app/services/acquisition/browser_runtime.py` · **Lines:** ~420–427

The native Chrome branch enters when `not inject_init_script` (i.e., caller says "don't inject"), yet it injects a masking init script anyway. In the non-native branch (line ~442), `if inject_init_script: return spec` means the flag enables the built-in script. The flag has opposite semantics in the two code paths. Either rename the parameter to clarify intent (e.g., `inject_standard_init_script`) or restructure so the native Chrome branch also respects the flag consistently.

### 54. runtime_settings.py — Silent clamp on `min_max_pages`
**File:** `backend/app/services/config/runtime_settings.py` · **Lines:** ~372–373

`self.min_max_pages = 1` silently clamps instead of raising `ValueError` like other validations. Replace with `raise ValueError(...)` for consistency with `_require_positive` / `_require_non_negative` pattern.

### 55. runtime_settings.py — Repeated browser_behavior clamping should use helper
**File:** `backend/app/services/config/runtime_settings.py` · **Lines:** ~395–416

Seven `max(0, int(...))` blocks for browser behavior fields. Extract a `_clamp_to_non_negative(field_name)` helper and replace the inline blocks.

### 56. runtime_settings.py — Profile defaults overwrite explicitly-set `None`
**File:** `backend/app/services/config/runtime_settings.py` · **Lines:** ~346–350

The condition `getattr(self, field_name) is None` overwrites fields the user explicitly set to `None`. Add `field_name not in explicitly_set` guard so only unset fields receive profile defaults.

---

## Config — LLM

### 57. llm_runtime.py — `aws_proxy_url` hardcoded localhost default
**File:** `backend/app/services/config/llm_runtime.py` · **Line:** ~102

`aws_proxy_url: str = "http://localhost:4000/v1/chat/completions"` is a hardcoded local proxy URL. Either make it env-backed (e.g., `os.getenv("AWS_PROXY_URL", "")`) or add an explicit comment explaining the LiteLLM proxy architecture requirement.

### 64. detail_dom_extractor.py — Positional fallback merges mismatched variants
**File:** `backend/app/services/extract/detail_dom_extractor.py` · **Line:** ~1276

When `dom_key` doesn't match any `existing_by_key`, the code falls back to `existing_by_index.get(index)`. If DOM order changes between extractions, this can merge unrelated variant pairs. Consider logging a warning when positional fallback is used, or tightening the `index_fallback_allowed` condition.

### 66. detail_text_sanitizer.py — `DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS` not precomputed
**File:** `backend/app/services/extract/detail_text_sanitizer.py` · **Line:** ~433

`heading_hits >= DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS` uses the raw config value at runtime. Precompute `_guide_glossary_heading_min_hits = int(DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS)` at module level, matching the pattern of `_long_text_ui_tail_min_product_words`.

### 67. detail_tiers.py — Recomputes normalized JSON-LD type sets every call
**File:** `backend/app/services/extract/detail_tiers.py` · **Lines:** ~131–143

`_detail_json_ld_payload_is_irrelevant` rebuilds `frozenset(...)` for `DETAIL_BREADCRUMB_JSONLD_TYPES` and `DETAIL_IRRELEVANT_JSON_LD_TYPES` on every call. Precompute as `_NORMALIZED_DETAIL_BREADCRUMB_JSONLD_TYPES` and `_NORMALIZED_DETAIL_IRRELEVANT_JSON_LD_TYPES` at module level.

### 68. shared_variant_logic.py — Missing `or ()` on three config iterables
**File:** `backend/app/services/extract/shared_variant_logic.py` · **Lines:** ~51–64

`VARIANT_COLOR_HINT_WORDS`, `VARIANT_SIZE_VALUE_PATTERNS`, and `VARIANT_OPTION_VALUE_NOISE_TOKENS` are iterated directly without `or ()` fallback (unlike `VARIANT_GROUP_ATTR_NOISE_PATTERNS` on line 48 which uses `or ()`). Add the defensive fallback to all three.

### 69. shared_variant_logic.py — Silent `continue` drops data on missing semantic key
**File:** `backend/app/services/extract/shared_variant_logic.py` · **Lines:** ~1021–1023

When `merged_by_semantic.get(semantic_identity)` returns `None`, the row is silently skipped. Log a warning and append the original row as fallback instead of dropping data.

### 70. shared_variant_logic.py — `VARIANT_SCOPE_MAX_ROOTS` unsafe if `None`/non-int
**File:** `backend/app/services/extract/shared_variant_logic.py` · **Line:** ~201

`len(roots) >= VARIANT_SCOPE_MAX_ROOTS` will raise `TypeError` if the config is `None`. Add defensive coercion (treat `None` as "no limit") matching the pattern used for `VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH`.

---

## Field URL Normalization

### 74. field_url_normalization.py — Magic number thresholds
**File:** `backend/app/services/field_url_normalization.py` · **Lines:** ~23, ~89, ~92

`len(lowered) > 3`, `len(normalized_value) > 8`, and `{0,8}` regex quantifier are magic numbers. Extract to `MAX_TRACKING_KEY_LENGTH` and `MAX_TRACKING_VALUE_LENGTH` config constants.

---

## Field Value — Core

### 75. field_value_core.py — Hardcoded color keyword regex
**File:** `backend/app/services/field_value_core.py` · **Lines:** ~662–666

`re.search(r"\b(?:color|colour|black|blue|...)\b", suffix, flags=re.I)` has an inline color keyword list. Move to `COLOR_KEYWORD_PATTERN` in extraction rules config.

### 76. field_value_core.py — Inline numeric/tracking-pixel patterns
**File:** `backend/app/services/field_value_core.py` · **Lines:** ~651–655

`re.fullmatch(r"\d{1,2}", cleaned)` and `re.fullmatch(r"_[a-z]+", cleaned, flags=re.I)` are inline. Move to config constants `SMALL_NUMERIC_RE` and `TRACKING_PIXEL_RE`. The `len(cleaned) <= 2` check is redundant given `\d{1,2}`.

### 77. field_value_core.py — Hardcoded GIF prefix and Cloudinary tokens
**File:** `backend/app/services/field_value_core.py` · **Lines:** ~815–817

`"r0lgodlh"` and `("g_auto", "f_auto", "q_auto", "c_fill")` are inline. Move to `GIF_BASE64_PREFIX` and `URL_DETECTION_TOKENS` in extraction rules config.

### 78. field_value_core.py — Repeated inline field-name sets
**File:** `backend/app/services/field_value_core.py` · **Lines:** ~1015–1026

`{"brand", "company", "dealer_name", "vendor"}` appears twice and `{"color", "condition", "material", "size", "storage", "style"}` is inline. Extract to `BRAND_LIKE_FIELDS` and `OPTION_SCALAR_FIELDS` in field_mappings config.

### 79. field_value_core.py — Hardcoded noisy attribute tokens
**File:** `backend/app/services/field_value_core.py` · **Line:** ~143

`{"availability", "available", "in_stock", "stock_status"}` is unioned into `_NOISY_PRODUCT_ATTRIBUTE_KEYS` inline. Move these tokens to `NOISY_PRODUCT_ATTRIBUTE_KEYS` in extraction rules config so no hardcoded strings remain in service code.

---

## Field Value — DOM Scoring (continued)

### 80. field_value_dom.py — Magic number `12` for selector match cap
**File:** `backend/app/services/field_value_dom.py` · **Line:** ~706

`safe_select(root, selector)[:12]` uses a magic number. Define `_MAX_SELECTOR_MATCHES = 12` at module level and use it consistently.

### 84. js_state_mapper.py — Dead `flat_variants` assignment
**File:** `backend/app/services/js_state_mapper.py` · **Line:** ~484

`flat_variants = flatten_variants_for_public_output(variants, page_url=page_url)` is assigned but never used (code uses `variants` directly). Remove the dead assignment and the unused import if applicable.

---

## Data Enrichment

### 85. data_enrichment/service.py — Dead `_bigrams` function
**File:** `backend/app/services/data_enrichment/service.py` · **Lines:** ~1194–1196

`_bigrams` is defined but never called—`_semantic_bigrams` is used instead. Remove the dead function.

### 86. data_enrichment/service.py — Memoizing regex can freeze config changes
**File:** `backend/app/services/data_enrichment/service.py` · **Line:** ~758

Adding `@lru_cache` to `_material_strip_patterns` (flag #39) would freeze pattern compilation until restart. If config can change at runtime, add a `cache_clear()` mechanism or use a module-level variable with explicit invalidation instead.

---

## Normalizers

### 88. pipeline/core.py — `count_failure` argument inverted
**File:** `backend/app/services/pipeline/core.py` · **Line:** ~1301

`count_failure=verdict != VERDICT_LISTING_FAILED` yields `False` when the listing actually failed (i.e., when `verdict == VERDICT_LISTING_FAILED`). The semantic intent is "count this as a failure", so it should be `verdict == VERDICT_LISTING_FAILED`.

---

## Public Record Firewall

### 92. harness_support.py — Redundant lower-bound re-check in price sanity
**File:** `backend/harness_support.py` · **Line:** ~1009

`return _MIN_SANE_PRICE <= price <= max_price` re-checks the lower bound, but line 1005 already returns `False` if `price < _MIN_SANE_PRICE`. Simplify to `return price <= max_price`.

### 93. harness_support.py — Redundant third condition in identity mismatch
**File:** `backend/harness_support.py` · **Line:** ~624

`and sample_path != requested_path` is redundant when `sample_path in {"", "/"}` and `requested_path not in {"", "/"}`. Remove the third condition.

### 94. harness_support.py — Harness user password not synced with env
**File:** `backend/harness_support.py` · **Lines:** ~1509–1522

When an existing harness user's password differs from the current `HARNESS_PASSWORD` env var, the code returns without updating. Add: if `user.hashed_password != hash_password(harness_password)`, update it.

### 95. harness_support.py — Hex color regex only matches 6-digit
**File:** `backend/harness_support.py` · **Line:** ~1149

`re.fullmatch(r"#[0-9a-fA-F]{6}", text)` misses 3-digit shorthand, 4-digit RGBA, and 8-digit RGBA. Broaden to `r"#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})"`.

---

## Test Assertions (continued)

### 96. test_detail_extractor_structured_sources.py — Missing JS-state-vs-DOM variant precedence assertion
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~2094–2096

Test extracts `record` but doesn't assert that JS state variants take precedence over DOM fallback. Add assertions on variant fields.

### 97. test_detail_extractor_structured_sources.py — Missing promo/hex variant rejection assertions
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~1559–1561

Test only asserts `len(rows) == 1`. Add assertions that promo and hex-only DOM variant values are rejected.

### 98. test_detail_extractor_structured_sources.py — Missing Costco textual variant assertions
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~4265–4268

Test is missing assertions that "Queen" and "King" textual variants are mapped into the size field.

### 99. test_detail_extractor_structured_sources.py — Missing generic selector axis assertion
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~2269–2272

Test doesn't assert that generic selector axis names are ignored. Add negative assertions.

### 100. test_detail_extractor_structured_sources.py — Missing plain-button variant assertion
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~2409–2412

Test extracts `record` but never asserts the plain-button variant data. Add variant content assertions.

### 101. test_detail_extractor_structured_sources.py — Missing newsletter rejection and content assertions
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~1528–1530

Test only checks `len(rows) == 1`. Add assertions that newsletter keys are absent and product fields are correct.

### 102. test_detail_extractor_structured_sources.py — Missing marketing-axis pruning assertion
**File:** `backend/tests/services/test_detail_extractor_structured_sources.py` · **Lines:** ~2178–2181

Test doesn't assert that single-value marketing axes ("Soft Fabric", "High Waisted") are pruned. Add negative assertions.

### 103. test_field_value_core.py — Non-deterministic concatenated-URL rejection reason
**File:** `backend/tests/services/test_field_value_core.py` · **Lines:** ~646–656

Test allows two rejection reasons via set membership. Make deterministic by expecting the exact reason string.

### 104. test_field_value_core.py — `merge_variant_rows` test only asserts sizes
**File:** `backend/tests/services/test_field_value_core.py` · **Lines:** ~675–683

Test only checks size preservation, not price. Add `assert [row["price"] for row in rows] == ["100", "100"]`.

### 105. test_field_value_core.py — `test_coerce_size_rejects_ui_tab_labels` should use `parametrize`
**File:** `backend/tests/services/test_field_value_core.py` · **Lines:** ~608–613

Repeated asserts on different labels. Refactor to `@pytest.mark.parametrize("label", [...])`.

### 106. test_selectolax_css_migration.py — No guard for missing artifact
**File:** `backend/tests/services/test_selectolax_css_migration.py` · **Lines:** ~469–489

`read_optional_artifact_text` can return `None`. Add `pytest.skip()` guard before passing to `extract_listing_records`.

### 107. test_state_mappers.py — Four tests with no assertions
**File:** `backend/tests/services/test_state_mappers.py` · **Lines:** ~716–734, ~736–754, ~1053–1096, ~1147–1178

Four tests call `map_js_state_to_fields` but have zero assertions. Add assertions for:
- variant query parameter replacement
- ambiguous availability neutrality
- selectedOptions population + marketing axis skip
- `compare_at_price` / `compareAtPrice` → `original_price` mapping

---

## Config — Extraction Rules

### 109. extraction_rules.py — Dynamic first selector can misdirect extraction
**File:** `backend/app/services/config/extraction_rules.py` · **Line:** ~128

`DETAIL_TEXT_SCOPE_SELECTORS` starts with `_STATIC_EXPORTS.get("DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR", "main")` which is dynamic at import time. If the JSON export changes, the first selector can misdirect detail extraction to the wrong DOM scope. Consider making the fallback order explicit and deterministic.


Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_runtime.py at line 334, The hardcoded ignored args assigned to launch_kwargs["ignore_default_args"] should be moved into configuration and validated against Patchright's API: add a new config entry (e.g. IGNORED_DEFAULT_ARGS) in app/services/config/browser_fingerprint_profiles.py and read it where launch_kwargs is constructed so launch_kwargs["ignore_default_args"] = <config value> instead of the literal ["--enable-automation"]; also confirm that chromium.launch() in Patchright supports ignore_default_args and, if it does not, translate the config into the supported API (or use an alternative call) inside the same function where launch_kwargs is used to avoid runtime errors.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/browser_fingerprint_profiles.py around lines 34 - 46, Add the three new constants to the module export list and give WARMUP_VENDOR_BLOCK_PREFIX a type annotation: update __all__ to include "NATIVE_REAL_CHROME_CONTEXT_OPTIONS", "WARMUP_ELIGIBLE_BROWSER_REASONS", and "WARMUP_VENDOR_BLOCK_PREFIX", and change the WARMUP_VENDOR_BLOCK_PREFIX declaration to include a type (e.g., str) to match the other constants; verify the same change is applied consistently where these constants appear later in the file (around the other occurrences at lines ~309-318).

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/field_mappings.py around lines 217 - 221, NAVIGATION_URL_FIELDS and PUBLIC_RECORD_CANONICAL_URL_FIELDS are defined as identical frozensets; either deduplicate by having one reference the other (e.g., set PUBLIC_RECORD_CANONICAL_URL_FIELDS = NAVIGATION_URL_FIELDS) or, if they are conceptually different, add a short clarifying comment above the two constants explaining their distinct purposes and why they currently contain the same members so future changes are clear; update references to PUBLIC_RECORD_CANONICAL_URL_FIELDS or NAVIGATION_URL_FIELDS accordingly.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/crawl_fetch_runtime.py around lines 788 - 796, The code assumes crawler_runtime_settings.http_timeout_seconds is a number and will raise TypeError if it's None; mirror the handoff-timeout guard used earlier by computing http_timeout only when http_timeout_seconds is not None. Specifically, in the block around http_timeout, check if crawler_runtime_settings.http_timeout_seconds is None and if so set http_timeout = context.resolved_timeout; otherwise set http_timeout = min(float(crawler_runtime_settings.http_timeout_seconds), context.resolved_timeout) before calling wait_for_host_slot and fetcher.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/crawl_fetch_runtime.py around lines 684 - 690, The handoff_timeout calculation can raise TypeError if crawler_runtime_settings.http_timeout_seconds is None; update the logic around where handoff_timeout is computed (the block that sets handoff_timeout before calling _curl_fetch with context.url and context.resolved_timeout) to guard against None by using a default (e.g., treat None as 0 or another sensible default) or explicitly check for None and handle accordingly so float(...) is never called on None.

- Verify each finding against the current code and only fix it if needed.

### 108. browser_runtime.py — Hardcoded ignored args
**File:** `backend/app/services/acquisition/browser_runtime.py` · **Line:** ~334

The hardcoded `["--enable-automation"]` assigned to `launch_kwargs["ignore_default_args"]` should be moved into configuration (e.g., `app/services/config/browser_fingerprint_profiles.py`).

### 109. browser_fingerprint_profiles.py — Missing exports and types
**File:** `backend/app/services/config/browser_fingerprint_profiles.py` · **Lines:** ~34–46

`WARMUP_VENDOR_BLOCK_PREFIX` needs a type annotation. Add `NATIVE_REAL_CHROME_CONTEXT_OPTIONS`, `WARMUP_ELIGIBLE_BROWSER_REASONS`, and `WARMUP_VENDOR_BLOCK_PREFIX` to `__all__`.

### 110. field_mappings.py — Duplicate canonical/navigation url fields
**File:** `backend/app/services/config/field_mappings.py` · **Lines:** ~217–221

`NAVIGATION_URL_FIELDS` and `PUBLIC_RECORD_CANONICAL_URL_FIELDS` are identical. Deduplicate them or add a comment explaining why they must stay separate.

### 111. crawl_fetch_runtime.py — TypeError risks on timeouts
**File:** `backend/app/services/crawl_fetch_runtime.py` · **Lines:** ~684–690, ~788–796

`crawler_runtime_settings.http_timeout_seconds` can be `None`. Calling `float()` on it for `handoff_timeout` or `http_timeout` will raise a TypeError.

### 112. detail_dom_extractor.py — Overwriting existing variants
**File:** `backend/app/services/extract/detail_dom_extractor.py` · **Lines:** ~1263–1271

The loop populating `existing_by_key` overwrites earlier rows when `variant_id` or `url` duplicates. Either preserve the first occurrence or collect them in a list.

### 113. detail_dom_extractor.py — Hex color regex uses A-F
**File:** `backend/app/services/extract/detail_dom_extractor.py` · **Line:** ~347

The regex `r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?"` checks against `compact` which is already lowercased. Simplify the character class to `[0-9a-f]`.

### 114. detail_record_finalizer.py — Rebuilding placeholder pattern tuple
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Lines:** ~851–852

Calling `tuple(PLACEHOLDER_IMAGE_URL_PATTERNS or ())` per-call creates unnecessary allocation. Pre-compute a cached lowercased tuple at module load.

### 115. detail_text_sanitizer.py — Brittle JSON object check
**File:** `backend/app/services/extract/detail_text_sanitizer.py` · **Lines:** ~400–402

Treating a leading `{` as sufficient to drop text is brittle. Use `json.loads` or a structural check to verify it's a real JSON object before dropping.

### 116. shared_variant_logic.py — Hardcoded noise ancestor depth
**File:** `backend/app/services/extract/shared_variant_logic.py` · **Lines:** ~162–166

The fallback depth `3` is hardcoded. Extract to a config constant like `VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT`.

### 117. variant_record_normalization.py — Hardcoded fallback max_rows
**File:** `backend/app/services/extract/variant_record_normalization.py` · **Lines:** ~456–459

The fallback `max_rows = 1` is hardcoded. Extract to a config constant like `DEFAULT_DETAIL_MAX_VARIANT_ROWS`.

### 118. field_url_normalization.py — Unreachable and fragile code
**File:** `backend/app/services/field_url_normalization.py` · **Lines:** ~28–35, ~122–137

`len(scheme_matches) == 1` branch is unreachable because `_URL_SCHEME_RE.finditer` already finds all matches. Also, `URL_CONCATENATION_ALLOWED_PREFIX_SEPARATORS` is double-wrapped in `tuple()`.

### 119. field_value_core.py — Redundant length check
**File:** `backend/app/services/field_value_core.py` · **Lines:** ~656–661

`re.fullmatch(r"\d{1,2}", cleaned)` already guarantees 1-2 chars. The trailing `and len(cleaned) <= 2` is redundant.

### 120. field_value_dom.py — Bare int() calls on config values
**File:** `backend/app/services/field_value_dom.py` · **Lines:** ~81, ~387–397

Bare `int()` calls on config values like `MAX_SELECTOR_MATCHES` and `SCOPE_SCORE_MAIN_WEIGHT` will raise TypeError on `None`. Use `_safe_int`.

### 121. llm_provider_client.py — Retry loop semantics and unused parameter
**File:** `backend/app/services/llm_provider_client.py` · **Lines:** ~60–61, ~254

The retry loop treats `max_retries` as total attempts. The `api_key` parameter is deleted using `del api_key` instead of prefixing with `_`.

### 122. pipeline/core.py — Duplicated browser_attempted logic
**File:** `backend/app/services/pipeline/core.py` · **Lines:** ~441–444

The code duplicates logic to determine if the browser attempted. Use the existing `_browser_attempted(acquisition_result)` helper.

### 123. test_state_mappers.py — Missing product-level mappings assertion
**File:** `backend/tests/services/test_state_mappers.py` · **Lines:** ~97–146

The test only asserts variant-level mappings. Extend it to assert product-level fields like `mapped["color"]` and `mapped["size"]`.

### 124. crawl-run-screen.tsx — Tone badge logic warns on empty
**File:** `frontend/components/crawl/crawl-run-screen.tsx` · **Lines:** ~1117–1129

The Badge uses `tone={llmSummary.touchedRecords > 0 ? 'accent' : 'warning'}`, treating "LLM enabled, no repair" as a warning. Change fallback to a neutral tone.