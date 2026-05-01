Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/data/prompts/data_enrichment_semantic.user.txt at line 9, The prompt entry "category_path" is vague about "when evidence is weak"—replace that subjective phrase with an objective rule or concrete examples to ensure consistent outputs; update the value for "category_path" to either revert to the prior objective condition (e.g., "or the JSON null value (null) when no category exists") or specify explicit thresholds/examples for weak evidence (e.g., "or null when product title/description contains fewer than 2 category-indicative keywords, missing brand/category tokens, or only generic words like 'item'/'product'") so models have clear deterministic criteria.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/data/prompts/data_enrichment_semantic.user.txt at line 9, Update the "category_path" instruction to explicitly define the expected format for the Plain ecommerce category path: state it must be a hierarchical string (e.g., "Electronics > Computers > Laptops") using " > " as the separator, allow free-form names but prefer a controlled vocabulary when available, enforce a max depth of 5 levels, and return the JSON null value only when evidence is weak; reference the "category_path" key in data_enrichment_semantic.user.txt and ensure any downstream consumers are checked/updated to accept this new string format instead of Google Product Category IDs.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_core.py around lines 938 - 948, The _coerce_brand_text function is rejecting valid brand strings because urlparse treats "foo:bar" as a scheme and _BARE_HOST_URL_RE.search allows partial host matches; update _coerce_brand_text to only treat values as URLs when urlparse(text).scheme is one of known URL schemes (e.g., "http","https","ftp","mailto") rather than any non-empty scheme, and change the bare-host regex check to use _BARE_HOST_URL_RE.fullmatch(text) so only whole-string hostnames are rejected; keep using coerce_text and preserve returning None for actual URLs or bare hosts.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/data-enrichment/enrichment-components.tsx around lines 88 - 98, The current price-rendering branch treats any object (including arrays) as an object and, when no numeric amount/price_min is found, falls through to String(price) which yields "[object Object]"; update the fallback so that in the object branch (the block using p and amount and calling formatAmount) you detect arrays via Array.isArray(price) and, when an object/array has no numeric amount, return a readable representation (e.g. safely JSON.stringify(price) inside a try/catch) instead of String(price); preserve the existing numeric paths that call formatAmount(price, currency) and only change the final fallback to return JSON.stringify(price) for objects/arrays (or String(price) for other types).

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/data-enrichment/page.tsx at line 176, The displayed label uses a nested ternary that checks activeJob?.status before createMutation.isPending, causing "Enriching..." to show when createMutation.isPending is true but activeJob is still null; update the JSX conditional around createMutation/isRunning/activeJob (the expression using createMutation.isPending, isRunning and activeJob?.status) so createMutation.isPending takes precedence and returns "Starting..." whenever createMutation.isPending is true (or when activeJob is null and creation is pending), otherwise fall back to checking isRunning and activeJob?.status to choose "Starting..." vs "Enriching...".

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Changing the output category guidance can make enriched categories diverge from the taxonomy expected by downstream matching.
   Path: backend/app/data/prompts/data_enrichment_semantic.system.txt
   Lines: 4-4

2. logic error: Zero-valued source run IDs are no longer normalized to an unset value.
   Path: backend/app/models/crawl_settings.py
   Lines: 239-239

3. logic error: Removing the blocked_html_checker fallback changes blocked-page detection.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 132-132

4. resource leak: Passing `analysis.soup` into `_prepare_markdown_soup` mutates the cached HTML analysis tree.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 845-845

5. logic error: Removing `thriftbooks` from the adapter registry breaks registry-driven lookup for that configured platform.
   Path: backend/app/services/adapters/registry.py
   Lines: 32-32

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.