Dead Code & Duplicate Findings (Cross-File)
Before the per-file plans, these cross-cutting issues apply to multiple files:

Pattern	Location	Finding
_safe_int	field_value_dom.py:77 AND field_value_core.py:200	Duplicate — different signatures but same intent; canonical version belongs in shared/coerce_primitives.py
_coerce_float	detail_extractor.py:115	Already exists as _coerce_int in field_value_core; detail_extractor's copy is dead after migration to extract/ children
_is_placeholder_image_url	field_value_core.py:868	Image URL logic stranded in core text coercion; belongs in field_value_dom's image module
absolute_url / same_host	field_value_core.py:349/363	URL utilities with no coercion concern; should move to a shared/url_utils.py
_ensure_scheme	crawl_fetch_runtime.py:109	Primitive URL helper isolated in a 43KB fetch orchestration file; candidate for shared/url_utils.py
Image scoring cluster	field_value_dom.py (8 functions) vs field_value_core.py:868	Image URL logic is split between two files; consolidate into one image module
Variant logic fragmentation	js_state_mapper.py (8 _variant_* functions) + field_value_core.py (6 _variant_*) + extract/shared_variant_logic.py (57KB)	Three files doing variant normalization; js_state_mapper's variant functions shadow or partially duplicate shared_variant_logic
detail_extractor.py orchestration body	10 imports from extract/ children	The file already decomposed its logic into children but retains ~1400 lines of orchestration + shell-detection that grew back — _looks_like_site_shell_record (166 lines), _materialize_record (140 lines) are undecomposed god-functions inside the god-file
1. crawl_fetch_runtime.py (43KB)
Logical Responsibilities
Fetch context init — _FetchRuntimeContext dataclass, run config snapshot, pacing setup

HTTP fetch path — _select_http_fetcher, _resolve_http_timeout, _retryable_status_for_http_fetch, cookie handoff

Browser engine selection — _browser_engine_attempts, _browser_first_decision, _hard_browser_requirement, _browser_escalation_lane, escalation after vendor block

Proxy resolution — _resolve_proxy_attempts, _browser_escalation_proxies, _normalize_proxy_profile, session rewrite

Vendor block detection — _vendor_confirmed_block, block-triggered engine strategy

Diagnostics/tracing — _attach_exception_browser_diagnostics, _attach_browser_attempt_diagnostics, _host_policy_snapshot

Proposed Split
text
backend/app/services/
├── fetch/
│   ├── __init__.py
│   ├── fetch_context.py          # _FetchRuntimeContext, _normalize_fetch_mode, _ensure_scheme → shared/url_utils.py
│   ├── http_fetch_path.py        # _select_http_fetcher, _resolve_http_timeout, _retryable_status_for_http_fetch, _handoff_cookie_engines
│   ├── browser_engine_strategy.py # _browser_engine_attempts, _browser_first_decision, _hard_browser_requirement, _browser_escalation_lane, _default_browser_engine_attempts, _append_engine_once, _prefer_engine_first
│   ├── proxy_resolution.py       # _resolve_proxy_attempts, _browser_escalation_proxies, _normalize_proxy_profile, _proxy_session_rewrite_enabled, _attach_proxy_run_session
│   └── fetch_diagnostics.py      # _attach_exception_browser_diagnostics, _attach_browser_attempt_diagnostics, _resolve_browser_reason, _host_policy_snapshot
└── crawl_fetch_runtime.py        # Thin orchestrator: imports and delegates; SharedBrowserRuntime class remains here as the public API entry
Shared Helpers to Extract
_ensure_scheme → shared/url_utils.py alongside absolute_url/same_host from field_value_core

Circular Dependency Risks
browser_engine_strategy.py must not import from proxy_resolution.py — pass proxy list as argument to avoid the cycle. Currently _browser_escalation_proxies is called from within the engine strategy body; invert the dependency by having the orchestrator resolve proxies then pass them in.

2. detail_extractor.py (48KB)
Logical Responsibilities
The extract/ child split already happened, but the parent grew back with undecomposed logic:

Candidate collection — _collect_record_candidates, _collect_structured_payload_candidates, source ranking

Shell/spam detection — _looks_like_site_shell_record (166 lines), _detail_structured_payload_is_irrelevant_product (68 lines), _prune_irrelevant_detail_structured_payload — this is new code that grew back post-decomposition

DOM completion gating — _requires_dom_completion (84 lines), _requires_dom_long_text_completion, _missing_requested_fields

Record materialization — _materialize_record (140 lines), _materialize_image_fields, image/title shell checks

Public API — build_detail_record, detail_record_rejection_reason, extract_detail_records

Proposed Split
text
backend/app/services/extract/
├── detail_candidate_collector.py   # _collect_record_candidates, _collect_structured_payload_candidates, _add_sourced_candidate, _ordered_candidates_for_field, _group_ordered_candidates_by_source
├── detail_shell_filter.py          # _looks_like_site_shell_record, _detail_structured_payload_is_irrelevant_product, _prune_irrelevant_detail_structured_payload (166+68 line functions; this is the regrowth hotspot)
├── detail_dom_completion.py        # _requires_dom_completion, _requires_dom_long_text_completion, _missing_requested_fields (move OUT of detail_extractor into extract/)
└── detail_materializer.py          # _materialize_record, _materialize_image_fields, _finalize_early_detail_record, _finalize_dom_detail_record
Then detail_extractor.py becomes a thin facade calling into extract/ — matching what already happened for detail_dom_extractor, detail_price_extractor, etc.

Dead Code Flag
_coerce_float (L115) is a local primitive that duplicates field_value_core._coerce_int/float — remove and import from core.

_primary_source_for_record and _field_source_rank are used only within candidate collection; they should move into detail_candidate_collector.py and not re-export.

Circular Dependency Risks
detail_shell_filter.py will need field_value_core.slug_tokens and field_value_dom.extract_page_images — both are in separate files already, so no cycle, but do not let detail_shell_filter import from detail_candidate_collector since the collection phase feeds into the filter, not vice versa.

3. field_value_dom.py (57KB)
Logical Responsibilities
Image URL processing — canonical_image_url, image_candidate_score, dedupe_image_urls, upgrade_low_resolution_image_url, _srcset_urls, _looks_like_image_asset_url, _is_proxy_image_url (8 URL-level functions, no BS4)

Image DOM extraction — _is_in_product_gallery_context, _is_garbage_image_candidate, _gallery_image_score, _candidate_image_urls_from_node, extract_page_images (needs BS4 Tag)

DOM text scoping — _node_attr_text, _node_is_hidden_or_auxiliary, _node_style_is_hidden, _candidate_text_scope_nodes, _scope_score, _best_text_scope, _clone_visible_only, _pruned_text_scope_root

Selector/XPath/Regex extraction — safe_select, extract_node_value, extract_selector_values, extract_xpath_values, extract_regex_values, filter_values_by_regex

Section/label extraction — extract_label_value_pairs, extract_heading_sections, extract_feature_rows, _section_* family (15 functions)

Variant DOM node detection — _looks_like_variant_option_node, _variant_option_node_text, apply_selector_fallbacks

Proposed Split
text
backend/app/services/dom/
├── __init__.py
├── image_url_utils.py     # Pure URL functions: canonical_image_url, image_candidate_score, dedupe_image_urls, upgrade_low_resolution_image_url, _srcset_urls, _looks_like_image_asset_url, _is_proxy_image_url, _normalize_image_url_text, _effective_image_url
│                          # Absorbs field_value_core._is_placeholder_image_url (move here)
├── image_dom_extractor.py # BS4-dependent: extract_page_images, _is_in_product_gallery_context, _is_garbage_image_candidate, _gallery_image_score, _candidate_image_urls_from_node, _image_node_context
├── text_scope.py          # DOM text scoping: _node_attr_text, _node_is_hidden_or_auxiliary, _node_style_is_hidden, _candidate_text_scope_nodes, _scope_score, _best_text_scope, _clone_visible_only, _pruned_text_scope_root, _node_within_scope, _node_has_cross_product_cluster
├── selector_engine.py     # safe_select, extract_node_value, extract_selector_values, extract_xpath_values, extract_regex_values, filter_values_by_regex, _selector_regex_timeout_seconds
└── section_extractor.py   # extract_label_value_pairs, extract_heading_sections, extract_feature_rows, _section_* family (15 functions), _extract_product_materials
field_value_dom.py at root level becomes a re-export shim (from app.services.dom.X import *) to preserve existing import paths during migration.

Shared Helpers to Extract
image_url_utils.py is immediately usable by js_state_mapper._extract_product_images — currently that function re-implements URL deduplication inline.

Circular Dependency Risks
selector_engine.py uses text_scope.py helpers (_node_attr_text) — one-way dependency, fine.

image_dom_extractor.py uses image_url_utils.py — one-way, fine.

Risk: section_extractor.py currently calls _best_text_scope — keep both in the same module or accept text_scope.py → section_extractor.py is a one-way import only.

4. field_value_core.py (53KB)
Logical Responsibilities
Primitive coercers — _safe_int, _coerce_int, _object_list, _object_dict (also duplicated in field_value_dom._safe_int)

Text coercion — clean_text, strip_html_tags, coerce_text, coerce_long_text, is_title_noise, text_or_none, slug_tokens, _coerce_literal_text_list, _split_multivalue_text_rows

URL utilities — absolute_url, same_host, extract_urls, _trim_trailing_url_candidate, _looks_like_malformed_relative_url_candidate

Price / currency coercers — extract_price_text, extract_currency_code, coerce_structured_scalar, _price_text_is_negative, salary_from_json, coerce_location

Variant public contract — flatten_variants_for_public_output, enforce_flat_variant_public_contract, _drop_parent_shared_variant_fields, _drop_unanimous_variant_transport_fields, _canonical_variant_axis_key, _coerce_variant_axis_value

Field-specific coercers — coerce_field_value (200+ line dispatcher L1206–1416), _coerce_brand_text, _coerce_title_text, _coerce_sku, _coerce_gender, _coerce_barcode, coerce_product_attributes, coerce_availability_value, coerce_rating_value

Record validation/finalization — validate_record_for_surface, clean_record, surface_fields, surface_alias_lookup, direct_record_to_surface_fields, finalize_record

Proposed Split
text
backend/app/services/shared/
├── coerce_primitives.py    # _safe_int (canonical), _coerce_int, _object_list, _object_dict
│                           # Eliminates field_value_dom._safe_int duplicate
├── url_utils.py            # absolute_url, same_host, extract_urls, _trim_trailing_url_candidate, _looks_like_malformed_relative_url_candidate, _ensure_scheme (from crawl_fetch_runtime), _is_placeholder_image_url (from field_value_core)
├── text_coerce.py          # clean_text, strip_html_tags, coerce_text, coerce_long_text, is_title_noise, text_or_none, slug_tokens, _coerce_literal_text_list, _split_multivalue_text_rows, _coerce_structured_multi_rows
└── field_coerce.py         # coerce_field_value (the big dispatcher), _coerce_brand_text, _coerce_title_text, _coerce_sku, _coerce_gender, _coerce_barcode, coerce_product_attributes, coerce_availability_value, coerce_rating_value, coerce_location, salary_from_json

backend/app/services/
├── field_value_price.py    # extract_price_text, extract_currency_code, coerce_structured_scalar, _price_text_is_negative
├── field_value_variant_contract.py  # flatten_variants_for_public_output, enforce_flat_variant_public_contract, _drop_parent_shared_variant_fields, _drop_unanimous_variant_transport_fields, _canonical_variant_axis_key, _coerce_variant_axis_value
└── record_contract.py      # validate_record_for_surface, clean_record, surface_fields, surface_alias_lookup, direct_record_to_surface_fields, finalize_record, infer_brand_from_title_marker, infer_brand_from_product_url
Dead Code Flag
_is_placeholder_image_url (L868) is stranded here — all callers are in DOM image code. Move to dom/image_url_utils.py.

_decimal_for_shared_price / _normalize_shared_price_decimal_text (L1052–1087) serve only the variant shared price path; move them alongside field_value_variant_contract.py.

Circular Dependency Risks
field_coerce.py calls coerce_text and text_or_none — resolve by having field_coerce import from text_coerce (one-way). Do not let text_coerce import from field_coerce.

record_contract.py will need surface_fields which field_coerce.coerce_field_value also references — put surface_fields in record_contract and have field_coerce import it from there.

5. js_state_mapper.py (48KB)
Logical Responsibilities
State key normalization — _normalized_state_payload, _revive_nuxt_data_array, map_js_state_to_fields entry point

Payload detection/scoring — _find_product_payloads, _find_product_payload, _looks_like_product_payload, _product_payload_score (77-line function)

Product field mapping — _map_product_payload (128 lines), _map_ecommerce_detail_state, _map_job_detail_state, _map_platform_job_detail_state, _map_configured_state_payload, _glom_product_base_fields, _map_jmespath_fields

Price extraction — _raw_current_price_value, _raw_original_price_value, _discounted_percentage_price, _raw_numeric_value, _raw_currency_value, _contextual_numeric_value

Variant normalization — _normalize_variant (92 lines), _variant_axis_value, _variant_selection_values (54 lines), _variant_option_values (112 lines), _option_value_labels (58 lines), _option_names, _product_variant_rows, _backfill_nested_variant_context

Product deduplication/merging — _dedupe_product_payloads, _merge_same_product_record, _merge_variant_fields, _mapped_product_identity_matches, _mapped_product_family_matches

Image extraction — _extract_product_images, _extract_nested_image_urls (reimplements URL deduplication inline; should use dom/image_url_utils.dedupe_image_urls)

Proposed Split
text
backend/app/services/js_state/
├── __init__.py
├── state_normalizer.py       # map_js_state_to_fields (entry), _normalized_state_payload, _revive_nuxt_data_array, _first_path_value, _path_value, _as_list
├── payload_detector.py       # _find_product_payloads, _find_product_payload, _looks_like_product_payload, _product_payload_score, _extract_product_payloads_from_normalized
├── product_field_mapper.py   # _map_product_payload, _map_ecommerce_detail_state, _map_job_detail_state, _map_platform_job_detail_state, _map_configured_state_payload, _glom_product_base_fields, _map_jmespath_fields, _first_non_empty_jmespath, _product_base_fields, _extract_ecommerce_description_fields
├── js_price_extractor.py     # _raw_current_price_value, _raw_original_price_value, _discounted_percentage_price, _raw_numeric_value, _raw_currency_value, _contextual_numeric_value, _raw_currency_value
└── js_variant_mapper.py      # _normalize_variant, _variant_axis_value, _variant_selection_values, _variant_option_values, _option_value_labels, _option_names, _product_variant_rows, _backfill_nested_variant_context
js_state_mapper.py + js_state_helpers.py merge into js_state/ — js_state_helpers.py (240 lines) contains select_variant, variant_axes, normalize_price, availability_value which are the public API consumed by callers; these become js_state/__init__.py re-exports.

Dead Code Flags
_extract_product_images / _extract_nested_image_urls (L955–983) duplicate URL scoring that field_value_dom.dedupe_image_urls already does — replace body with a call to that utility and delete the inline reimplementation.

_normalized_party_name, _title_tokens, _family_title_tokens (L401–413) — used only inside _mapped_product_family_matches; these 12-line utilities are only called once and should be inlined or moved to product_field_mapper.py as private helpers. They are dead for any external caller.

_connection_nodes / _name_or_value (L1367–1386) — GraphQL helper pair called only from _variant_option_values; move into js_variant_mapper.py.

_looks_like_shopify_product (L984) — called only from _product_payload_score; move with it into payload_detector.py.

Circular Dependency Risks
js_variant_mapper.py will import extract/shared_variant_logic.normalized_variant_axis_key — this is already the pattern in js_state_mapper's imports and is safe.

Risk: product_field_mapper.py calls js_variant_mapper for variant rows and js_price_extractor for prices. Both must be one-way imports into product_field_mapper; neither js_variant_mapper nor js_price_extractor should import from product_field_mapper.

state_normalizer.py (the entry point) will fan out to all four sub-modules — that is expected and not a cycle.

Shared Helpers That Should Move to shared/
text
backend/app/services/shared/
├── coerce_primitives.py   # _safe_int (canonical, fixes the dom/core duplicate), _coerce_int, _object_list, _object_dict
├── url_utils.py           # absolute_url, same_host, extract_urls, _ensure_scheme, _is_placeholder_image_url
└── text_coerce.py         # clean_text, strip_html_tags, coerce_text, coerce_long_text, is_title_noise, text_or_none, slug_tokens
All five god-files import these primitives — centralizing them removes the _safe_int duplication and prevents future regrowth of the same pattern.