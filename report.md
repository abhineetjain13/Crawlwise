SLICE 1: Core Arbitration & The "Discovered Data" Boundary
Goal: Restore "Source-Aware Arbitration" and implement the missing discovered_data routing.
Target Files: service.py, core.py, field_mappings.py
Fix Arbitration Bypass: In service.py -> _collect_candidates(), remove the continue statements after _collect_adapter_candidates() and _collect_contract_candidates(). Append all sources to rows so FieldDecisionEngine can arbitrate properly.
Implement discovered_data Routing: In service.py -> _finalize_candidates(), when processing merged_dynamic_rows, strictly check keys against canonical_target_fields. If a key is NOT canonical, do not add it to final_candidates. Instead, return it in a new dictionary (e.g., discovered_fields) so core.py can save it to the discovered_data database column as required by the plan.
Enforce Surface Isolation: In service.py -> _finalize_candidates(), ensure ECOMMERCE_ONLY_FIELDS are strictly stripped from Job surfaces (and vice versa) during the dynamic row pass.
Fix Alias Pollution: In field_mappings.py, remove "size" from the dimensions aliases, and remove "dimension_label" from the size aliases to prevent bidirectional cross-field leakage.
SLICE 2: Variant Deduplication & Platform Agnosticism
Goal: Clean up duplicate Shopify logic, fix cents-to-dollars, and build a real Demandware path.
Target Files: service.py, shopify.py
Deduplicate Shopify Variant Logic: Delete _build_shopify_variant_rows, _normalize_shopify_variant, and _shopify_option_names from service.py completely. Rely entirely on the output of shopify.py (the adapter).
Fix Shopify Cents Bug: In shopify.py -> _normalize_price(), check if string values are pure integers (e.g., "15800"). If so, cast to Decimal and divide by 100.
Fix Default Variant Selection: In shopify.py -> try_public_endpoint(), ensure selected_variant strictly prioritizes the URL query parameter (?variant=...), then the embedded default, and only uses "first available" as an absolute last resort.
Remove Fake Demandware DOM Scraping: In service.py, delete _build_dom_variant_rows(). The current implementation creates phantom variant combinations and uses hardcoded Salesforce Commerce Cloud selectors (.color-attribute). Replace it with logic that searches the network_payloads for Demandware Product-Variation JSON responses, as required by the plan.
Filter Single-Value Axes: When building variant_axes, if an axis (like style: KN4991300) has exactly 1 value shared across all variants, it is a product attribute, not a selectable axis. Move it to product_attributes.
SLICE 3: Rich Text, Formatting & Data Deduplication
Goal: Stop flattening tables into blobs, fix breadcrumbs, and prevent duplicate data in the JSON.
Target Files: service.py
Preserve Rich Text Formatting: Audit _product_detail_features, _build_dom_section_rows, and _section_content_text. Stop using .get_text(" ") on complex nodes like tables. Ensure paragraphs (<p>) and lists (<li>) maintain line breaks and aren't squashed into a single line.
Remove Giro Hardcoding: In _build_dom_section_rows(), replace the hardcoded .accordion-item selector with generic logic that looks for <details>, [data-tab], or standard <h2>/<h3> to <p> structures.
Fix Breadcrumb Looping: In _extract_breadcrumb_category(), check the last item in the parsed breadcrumb list. If it fuzzy-matches the PDP's title, pop it off so the category doesn't end with the product name.
Prevent Redundant Data: If a field like specifications or materials is successfully populated as a top-level canonical field, explicitly pop() it out of product_attributes so it isn't duplicated in the JSON output payload.
SLICE 4: The "Auto-Learning" Schema Teardown
Goal: Enforce the strict "No Auto-Learning" rule and stop DB mutation during extraction.
Target Files: schema_service.py, core.py
Remove Dynamic DB Schema Updates: In schema_service.py, delete learn_schema_from_record(). The pipeline must treat schemas strictly as static configurations defined by CANONICAL_SCHEMAS.
Remove Core Hooks: In core.py, delete _refresh_schema_from_record() and any code attempting to mutate, save, or learn new schema fields during _process_json_response() or _extract_detail().
SLICE 5: Performance, Export & Minor Tech Debt
Goal: Remove redundant traversals, clean up dead variables, and fix the Markdown export.
Target Files: service.py, __init__.py, records.py
Cache Payload Traversals: In service.py -> _finalize_candidates(), _find_variant_product_payload() is called twice and _structured_source_payloads() is iterated three times. Refactor to compute these lists/payloads exactly once per request.
Deduplicate Size Normalization: Delete _normalize_size_candidate() in service.py. Route size strings exclusively through the standard _coerce_size_field() in __init__.py.
Clean up Tech Debt: In service.py, remove the redundant _DYNAMIC_FIELD_NAME_DROP_TOKENS = DYNAMIC_FIELD_NAME_DROP_TOKENS re-assignment. In __init__.py, remove the duplicated _CATEGORY_PLACEHOLDER_VALUES check from validate_value since _coerce_category_field already handles it.
Remove Markdown Regex Anti-pattern: In records.py, delete the _legacy_fallback_markdown_rows() regex function. Ensure structured table/row data is passed down the pipeline natively instead of serializing to Markdown just to regex-parse it back into dicts.
SLICE 6: Investigate Cross-Artifact Contamination
Goal: Find out why Cashmere Polo specifications ended up in a Terry Sweatshirt JSON output.
Target Files: core.py, service.py, semantic_detail_extractor.py (assumed)
Task for Agent: Analyze how semantic data is passed into _collect_candidates and _finalize_candidates. Determine if the LLM cache, global state, or stale adapter_records are leaking data between instances. Add strict URL/Product ID scoping to all semantic extraction layers to guarantee isolation.