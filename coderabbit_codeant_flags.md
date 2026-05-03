# Codeant / CodeRabbit Flags — Open Issues

Verify each finding against current code before fixing.

---

## Adapters

### 1. amazon.py — SKU set to fallback ASIN
**File:** `backend/app/services/adapters/amazon.py` · **Lines:** ~176–180

`sku = asin` even when `asin` is a fallback from `_detail_value_from_table(detail_table, "item model number")`. Update so `product_id` retains the fallback but `sku` is only populated when a real ASIN was extracted (from URL or `detail_table["asin"]`). Otherwise omit `sku`.

### 2. amazon.py — Selected variant dropped
**File:** `backend/app/services/adapters/amazon.py` · **Line:** ~366

Removing the selected variant breaks callers that rely on a single current variant record.

### 3. myntra.py — Variant count inconsistency
**File:** `backend/app/services/adapters/myntra.py` · **Lines:** ~216, ~241

Variant counts become inconsistent after flattening the variant list. Detail records also no longer include variant metadata that downstream consumers expect.

### 4. shopify.py — Selected variant & axis metadata dropped
**File:** `backend/app/services/adapters/shopify.py` · **Line:** ~198

Removing the selected-variant payload breaks consumers depending on the active variant's full data. Dropping variant axis metadata removes structured option information needed by callers.

### 5. shopify.py — Unused `_selectable_axes` from `_split_selectable_axes`
**File:** `backend/app/services/adapters/shopify.py` · **Lines:** ~172–174, ~344

`_selectable_axes` is assigned but never used after `self._split_selectable_axes(axes)`. Either unpack only `single_value_attributes` or create a dedicated method that returns just that value, and remove the unused `_selectable_axes` variable from both call sites.

### 6. shopify.py — Variant count after flattening
**File:** `backend/app/services/adapters/shopify.py` · **Line:** ~199

`variant_count` is computed from `flat_variants` after flattening, which can produce an incorrect total when the adapter's internal variant structure differs from the flattened output.

---

## Config & Schema

### 7. field_mappings.exports.json — Legacy variant aliases removed
**File:** `backend/app/services/config/field_mappings.exports.json` · **Line:** ~73

Dropping legacy variant aliases from the export breaks existing variant parsing for older payloads.

### 8. field_mappings.exports.json — `price_original` missing from JS state fields
**File:** `backend/app/services/config/field_mappings.exports.json` · **Line:** ~248

Removing `price_original` from `ECOMMERCE_DETAIL_JS_STATE_FIELDS` creates a schema mismatch with the live extractor data model.

### 9. data_enrichment.py — Narrowed crawl sources
**File:** `backend/app/services/config/data_enrichment.py` · **Line:** ~142

Narrowing the crawl sources can make enrichment miss color, size, and availability data on existing records.

### 10. data_enrichment.py — `selected_variant` in enrichment sources
**File:** `backend/app/services/config/data_enrichment.py` · **Lines:** ~151, ~160, ~165

`SELECTED_VARIANT_FIELD` is still referenced in color, size, and availability candidate sources. If selected_variant is no longer populated by adapters, these enrichment paths will never find data for products that only expose stock/color/size on the chosen variant.

### 11. extraction_rules.py — String-typed price thresholds
**File:** `backend/app/services/config/extraction_rules.py` · **Lines:** ~222–224

`DETAIL_PRICE_COMPARISON_TOLERANCE = "0.01"`, `DETAIL_LOW_SIGNAL_PRICE_MAX = "1"`, `DETAIL_LOW_SIGNAL_PARENT_MIN = "10"` are defined as strings, causing type inconsistency with the surrounding numeric constants (`DETAIL_PRICE_MAGNITUDE_EPSILON = 0.01`, `DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA = 10.0`). Change to `Decimal("0.01")`, `Decimal("1")`, `Decimal("10")` (or floats) and update any code that expects strings.

### 12. llm_runtime.py — No non-negative validation on rate Decimals
**File:** `backend/app/services/config/llm_runtime.py` · **Lines:** ~49–53

The `try` block converts rates to `Decimal` but does not check `>= 0`. Add validation: if either rate is negative, return `None` (same as existing error handling).

### 13. normalizers/__init__.py — `_AVAILABILITY_TOKENS` not defensive
**File:** `backend/app/services/normalizers/__init__.py` · **Line:** ~39

`_AVAILABILITY_TOKENS = NORMALIZER_AVAILABILITY_TOKENS` assigns directly without `tuple()` wrapping or `or ()` fallback. If the config value is `None`, downstream iteration will raise `TypeError`. Mirror the defensive pattern used for other config symbols.

---

## Extraction — Price

### 14. detail_price_extractor.py — `original_price` source always "dom_text"
**File:** `backend/app/services/extract/detail_price_extractor.py` · **Lines:** ~174–186

`original_price` is assigned from `jsonld_original_price` or `_detail_original_price_from_html` but source is always "dom_text". Detect which source was used and set accordingly: `append_record_field_source(record, "original_price", "jsonld")` or `"dom_text"`.

### 15. detail_price_extractor.py — Early return on currency-only skips later offers with prices
**File:** `backend/app/services/extract/detail_price_extractor.py` · **Lines:** ~709–735

In `_detail_jsonld_price_bundle`, the loop returns as soon as any offer has `price`, `original_price`, **or** `offer_currency`. An offer with only currency (e.g., "USD") causes an early return of `(None, None, "USD")`, skipping later offers with actual prices. Only return immediately when `price` or `original_price` is present; save currency and continue iterating. After the loop, return saved currency if no price was found.

### 16. detail_price_extractor.py — `results` declared twice in `_offers_from_jsonld_node`
**File:** `backend/app/services/extract/detail_price_extractor.py` · **Lines:** ~758–774

`results: list[dict[str, Any]] = []` is declared in both the `list` branch (line ~761) and the `dict` branch (line ~767). While they're in separate branches and each returns independently, consolidate into a single declaration at the top of the function for clarity.

### 17. detail_price_extractor.py — Module-level jsonld tuples should be underscore-prefixed
**File:** `backend/app/services/extract/detail_price_extractor.py` · **Lines:** ~53–73

`jsonld_graph_fields`, `jsonld_type_fields`, `jsonld_offer_fields`, `jsonld_price_fields`, `jsonld_original_price_fields`, `jsonld_price_specification_fields`, `jsonld_currency_fields` are module-level implementation details. Rename with leading underscore (`_jsonld_graph_fields`, etc.) and update all references in this file.

### 18. detail_price_extractor.py — Redundant early-return in `_detail_price_from_html`
**File:** `backend/app/services/extract/detail_price_extractor.py` · **Lines:** ~579–581

`if jsonld_price: return jsonld_price` is defensive—callers already gate on `jsonld_price or _detail_price_from_html(...)`. Either remove the check or add a comment explaining it's intentional defensive coding.

---

## Extraction — DOM & Variants

### 19. detail_dom_extractor.py — Hardcoded promo noise tokens
**File:** `backend/app/services/extract/detail_dom_extractor.py` · **Lines:** ~342–346

`any(token in lowered for token in ("off", "discount", "promo"))` uses hardcoded tokens. Add `VARIANT_PROMO_NOISE_TOKENS` to extraction rules config and import it, matching the existing `VARIANT_OPTION_VALUE_NOISE_TOKENS` pattern.

### 20. detail_record_finalizer.py — Hardcoded placeholder image checks
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Lines:** ~850–854

`"placeholder" in lowered`, `"via.placeholder.com" in lowered`, `lowered.endswith("/white.svg")` are hardcoded. Add `PLACEHOLDER_IMAGE_PATTERNS` to extraction rules config and replace the literals.

### 21. detail_record_finalizer.py — `strip_chars` TypeError risk
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Line:** ~287

`"".join(tuple(DETAIL_BREADCRUMB_SEPARATOR_LABELS or ()))` will raise `TypeError` if the iterable contains non-string elements. Use `"".join(map(str, DETAIL_BREADCRUMB_SEPARATOR_LABELS or ()))` to coerce each element.

### 22. detail_record_finalizer.py — Hardcoded `"in_stock"` literal
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Lines:** ~560, ~1081–1082

`parent_availability == "in_stock"` and `record["availability"] = "in_stock"` use a hardcoded literal. Add `AVAILABILITY_IN_STOCK = "in_stock"` to config and import it.

### 23. detail_record_finalizer.py — Brittle brace check for features placeholder
**File:** `backend/app/services/extract/detail_record_finalizer.py` · **Lines:** ~154–155

`feature_text.startswith("{") and feature_text.endswith("}")` is a heuristic that can false-positive on legitimate JSON-like feature text. Replace with `json.loads(feature_text)` in a try/except and only pop when the parsed result is a `dict`.

### 24. detail_text_sanitizer.py — False positive on `[`-prefixed text
**File:** `backend/app/services/extract/detail_text_sanitizer.py` · **Line:** ~381

`text.lstrip().startswith(("{", "["))` returns `""` for any bracket-prefixed string, causing false positives for bracketed product descriptions. Only treat leading `{` as JSON, or perform lightweight JSON detection before returning `""`. Preserve `[`-prefixed strings unless they truly parse as structured data.

### 25. detail_text_sanitizer.py — `heading_hits` substring false positives
**File:** `backend/app/services/extract/detail_text_sanitizer.py` · **Lines:** ~430–432

`heading_hits = sum(1 for token in guide_glossary_heading_tokens if token and token in lowered)` uses substring matching. Tokenize `lowered` into words (e.g., `re.findall(r"\w+")`) and check membership against a set for word-boundary matching.

### 26. variant_record_normalization.py — Comment double `_enforce_variant_currency_context` call
**File:** `backend/app/services/extract/variant_record_normalization.py` · **Lines:** ~52, ~57

`_enforce_variant_currency_context` is called twice—before dedup and after backfill. Add inline comments explaining the ordering intent so future maintainers don't collapse them.

### 27. variant_record_normalization.py — `any()` early return skips image backfill for other variants
**File:** `backend/app/services/extract/variant_record_normalization.py` · **Lines:** ~514–518

`if any(variant.get("image_url") not in (None, "", [], {}) for variant in variants): return` exits when **any** variant has an image, leaving others without. Remove the `any()` guard and always iterate, setting `variant["image_url"] = fallback_image` only when the variant's image is missing.

### 28. variant_record_normalization.py — `max_rows` int conversion can raise
**File:** `backend/app/services/extract/variant_record_normalization.py` · **Line:** ~446

`max_rows = max(1, int(crawler_runtime_settings.detail_max_variant_rows))` will raise `ValueError`/`TypeError` for non-numeric settings. Wrap in try/except and fall back to a safe default.

### 29. variant_record_normalization.py — Rebuilds frozenset on every `_value_is_placeholder` call
**File:** `backend/app/services/extract/variant_record_normalization.py` · **Lines:** ~184–186

`frozenset(VARIANT_PLACEHOLDER_VALUES or ())` and `tuple(VARIANT_PLACEHOLDER_PREFIXES or ())` are rebuilt every call. Pre-compute as module-level constants `_VARIANT_PLACEHOLDER_VALUES_SET` and `_VARIANT_PLACEHOLDER_PREFIXES_LOWER`.

### 30. variant_record_normalization.py — `re.fullmatch` not pre-compiled for option fields
**File:** `backend/app/services/extract/variant_record_normalization.py` · **Line:** ~535

`re.fullmatch(r"option\d+_(?:name|values?)", str(field_name))` is called in a loop. Pre-compile as `_OPTION_FIELD_PATTERN = re.compile(r"option\d+_(?:name|values?)")` at module level.

---

## Field Value & DOM Scoring

### 31. field_value_core.py — `_coerce_barcode` rebuilds set on every call
**File:** `backend/app/services/field_value_core.py` · **Line:** ~1246

`len(digits) not in set(PUBLIC_RECORD_BARCODE_LENGTHS or ())` rebuilds the set each call. Pre-compute `_PUBLIC_RECORD_BARCODE_LENGTHS_SET` at module level.

### 32. field_value_candidates.py — Duplicate `option_values` predicate
**File:** `backend/app/services/field_value_candidates.py` · **Lines:** ~809–818

`isinstance(row.get("option_values"), dict) and bool(row.get("option_values"))` appears twice—once in the `any()` filter and once in the list comprehension. Extract into a local variable (e.g., `has_option_values`) and reuse.

### 33. field_value_dom.py — Duplicated context tokens in `_scope_is_product_like`
**File:** `backend/app/services/field_value_dom.py` · **Lines:** ~384, ~393

`_scope_score` uses `("product", "detail", "pdp")` and `_scope_is_product_like` uses `("product", "pdp", "detail")`—same tokens, different order, duplicated. Create a single `SCOPE_PRODUCT_CONTEXT_TOKENS` constant and reference it from both functions.

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

### 39. data_enrichment/service.py — Regex recompilation in hot path
**File:** `backend/app/services/data_enrichment/service.py` · **Lines:** ~758–759

Restore caching for compiled regexes. Add `@lru_cache(maxsize=1)` to `_material_strip_patterns` so calls from `_normalize_materials` don't recompile on every product. If dynamic config is required, implement a `cache_clear()` helper.

### 40. public_record_firewall.py — Barcode→SKU bypasses shape check
**File:** `backend/app/services/public_record_firewall.py` · **Lines:** ~78–87

When `ROUTE_BARCODE_TO_SKU` is enabled, `routed_sku` is written directly to `data[SKU_FIELD]` bypassing `_public_record_field_shape_valid`. Add the shape check after computing `routed_sku` and only write if it passes.

---

## Harness & Test Support

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

### 50. browser_runtime.py — Hardcoded `"no_viewport": True` context option
**File:** `backend/app/services/acquisition/browser_runtime.py` · **Lines:** ~426

`{"no_viewport": True}` is hardcoded inside the native Chrome context branch. Move to a config constant (e.g., `NATIVE_REAL_CHROME_CONTEXT_OPTIONS`) under `app/services/config/` and pass it into `PlaywrightContextSpec(context_options=...)`.

### 51. browser_runtime.py — Imports private `_playwright_masking_init_script`
**File:** `backend/app/services/acquisition/browser_runtime.py` · **Line:** ~424

`from app.services.acquisition.browser_identity import _playwright_masking_init_script` imports a private symbol. Promote it to a public name (`playwright_masking_init_script`) in `browser_identity` and update the import/call site.

### 52. browser_runtime.py — `inject_init_script` semantics inverted in native Chrome branch
**File:** `backend/app/services/acquisition/browser_runtime.py` · **Lines:** ~420–427

The native Chrome branch enters when `not inject_init_script` (i.e., caller says "don't inject"), yet it injects a masking init script anyway. In the non-native branch (line ~442), `if inject_init_script: return spec` means the flag enables the built-in script. The flag has opposite semantics in the two code paths. Either rename the parameter to clarify intent (e.g., `inject_standard_init_script`) or restructure so the native Chrome branch also respects the flag consistently.

### 53. browser_runtime.py — Hardcoded warmup reason tokens
**File:** `backend/app/services/acquisition/browser_runtime.py` · **Lines:** ~1580–1588

The warmup eligibility check uses inline string literals (`"host-preference"`, `"http-escalation"`, `"platform-required"`, `"traversal-required"`, `"empty-extraction retry"`, `"thin-listing retry"`, `"vendor-block:"`). Extract into `WARMUP_ELIGIBLE_BROWSER_REASONS` and `WARMUP_VENDOR_BLOCK_PREFIX` config constants.

---

## Config — Runtime Settings

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

### 58. llm_config_service.py — AWS `"api_key_set": True` is misleading
**File:** `backend/app/services/llm_config_service.py` · **Line:** ~175

AWS Bedrock uses ambient credentials (IAM/boto3), not an API key. Hardcoding `"api_key_set": True` misleads about credential availability. Replace with `"uses_ambient_auth": True` or compute dynamically.

### 59. llm_provider_client.py — Unconditional `api_key` check rejects AWS
**File:** `backend/app/services/llm_provider_client.py` · **Lines:** ~33–34

`if not api_key: return error` fires for AWS even though `_call_aws` deletes `api_key` and uses ambient auth. Make the check provider-aware: skip when `normalized_provider == "aws"`.

### 60. llm_provider_client.py — `_call_aws` doesn't validate `aws_proxy_url`
**File:** `backend/app/services/llm_provider_client.py` · **Lines:** ~250–255

`_call_aws` creates an `httpx.AsyncClient` targeting `aws_proxy_url` without checking it's non-empty or a valid URL. Add validation at the start and return `_http_error(...)` if invalid.

### 61. llm_provider_client.py — `base_delay_s` deleted, no retry backoff
**File:** `backend/app/services/llm_provider_client.py` · **Line:** ~56

`del base_delay_s` removes the backoff parameter, so retries happen with zero delay. Restore exponential backoff: `await asyncio.sleep(base_delay_s * (2 ** _attempt))` after a failed attempt.

---

## Config — Field Mappings

### 62. field_mappings.py — `_STATIC_EXPORTS.get(...)` can return `None`
**File:** `backend/app/services/config/field_mappings.py` · **Line:** ~26

`_STATIC_EXPORTS.get("NORMALIZER_LIST_TEXT_FIELDS", ())` is safe (has fallback), but the dynamic `globals()` injection at line 23 has no `None` guard. If a JSON key maps to `None`, the module-level symbol becomes `None` and downstream iteration crashes. Add a `or ()` fallback in the globals injection loop.

### 63. field_mappings.py — `CANONICAL_URL_FIELD` declared but not wired
**File:** `backend/app/services/config/field_mappings.py` · **Line:** ~205

`CANONICAL_URL_FIELD = "canonical_url"` is defined but not used in `field_url_normalization.py` which hardcodes `{"apply_url", "canonical_url", "url"}` as inline literals. Wire the constant in.

---

## Extraction — DOM & Variants (continued)

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

### 71. field_url_normalization.py — Hardcoded tracking strip prefixes
**File:** `backend/app/services/field_url_normalization.py` · **Line:** ~36

`("ecommerce_", "job_")` is inline in `_surface_needs_tracking_strip`. Move to `TRACKING_STRIP_SURFACE_PREFIXES` in extraction rules config.

### 72. field_url_normalization.py — Hardcoded URL field names and surface
**File:** `backend/app/services/field_url_normalization.py` · **Lines:** ~140–143

`{"apply_url", "canonical_url", "url"}` and `"ecommerce_detail"` are inline literals. Move to config constants `PUBLIC_RECORD_CANONICAL_URL_FIELDS` and `PUBLIC_RECORD_CANONICAL_SURFACE`, and import `CANONICAL_URL_FIELD` from field_mappings.

### 73. field_url_normalization.py — Hardcoded scheme strings in concatenation check
**File:** `backend/app/services/field_url_normalization.py` · **Line:** ~127

`"https:/" in tail or "http:/" in tail` hardcodes two schemes, but `_URL_SCHEME_RE` matches more. Use the compiled pattern to search `tail` instead of hardcoded strings.

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

### 81. field_value_dom.py — Redundant `isinstance(attrs, dict)` check
**File:** `backend/app/services/field_value_dom.py` · **Line:** ~322

After the `not isinstance(attrs, dict)` branch handles traversal and continues, `attrs` is guaranteed to be a dict. The `isinstance(attrs, dict) and` prefix on line 322 is redundant—simplify to `if "hidden" in attrs:`.

### 82. field_value_dom.py — `clone_visible` unbounded recursion
**File:** `backend/app/services/field_value_dom.py` · **Lines:** ~414–424

`clone_visible` recurses without depth limit. On deeply nested DOMs this can blow the stack. Add a `remaining_depth` parameter (default e.g., 50) and return `None` when exhausted.

---

## JS State Mapper

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

### 87. normalizers/__init__.py — `flat_tokens` sort recomputed every call
**File:** `backend/app/services/normalizers/__init__.py` · **Lines:** ~171–176

`flat_tokens` is built and sorted on every `_normalize_availability` call. Precompute as `_SORTED_AVAILABILITY_TOKENS` at module level so the O(n log n) sort runs once.

---

## Pipeline

### 88. pipeline/core.py — `count_failure` argument inverted
**File:** `backend/app/services/pipeline/core.py` · **Line:** ~1301

`count_failure=verdict != VERDICT_LISTING_FAILED` yields `False` when the listing actually failed (i.e., when `verdict == VERDICT_LISTING_FAILED`). The semantic intent is "count this as a failure", so it should be `verdict == VERDICT_LISTING_FAILED`.

---

## Public Record Firewall

### 89. public_record_firewall.py — Hardcoded `"url"` string
**File:** `backend/app/services/public_record_firewall.py` · **Line:** ~53

`allowed_fields.add("url")` uses a literal instead of the imported `URL_FIELD` constant. Replace with `allowed_fields.add(URL_FIELD)`.

### 90. public_record_firewall.py — Hardcoded `"additional_images"` string
**File:** `backend/app/services/public_record_firewall.py` · **Line:** ~126

`field_name == "additional_images"` is a hardcoded literal. Add `ADDITIONAL_IMAGES_FIELD` to field_mappings config and import it, or add it to `STRUCTURED_MULTI_FIELDS` and check membership.

### 91. public_record_firewall.py — `NAVIGATION_URL_FIELDS` should live in config
**File:** `backend/app/services/public_record_firewall.py` · **Line:** ~37

`NAVIGATION_URL_FIELDS = frozenset({URL_FIELD, APPLY_URL_FIELD, CANONICAL_URL_FIELD})` is defined in service code. Move to the field-mappings config module alongside the other URL field constants.

---

## Harness & Test Support (continued)

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