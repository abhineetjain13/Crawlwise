Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/api/crawls.py around lines 96 - 98, The conditional in _domain_run_profile_payload is a no-op (value if isinstance(value, Mapping) else value); either simplify payload = value or, if the intent was to convert non-Mapping Pydantic models, replace the else branch with converting the model to a dict (e.g., call .model_dump() or .dict() on the BaseModel instance) before passing to DomainRunProfilePayload.model_validate; update _domain_run_profile_payload to detect Mapping vs BaseModel and produce a mapping accordingly so model_validate receives the correct input.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/acquirer.py at line 198, The assignment to profile uses "acquisition_profile or request.acquisition_profile" which treats empty dicts as falsy; change it to explicitly prefer a provided acquisition_profile only when it's not None (e.g., use a conditional expression that checks "acquisition_profile is not None") so an empty dict is honored; update the assignment in acquirer.py where profile is set and mirror the same fix pattern used in _resolve_fetch_mode to avoid dropping empty dicts from request.acquisition_profile.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/acquirer.py at line 172, The assignment to profile uses a falsy check that treats an explicit empty dict as absent; replace the fallback logic in acquirer.py so profile is set to acquisition_profile when acquisition_profile is provided (including empty dicts) and only uses request.acquisition_profile when acquisition_profile is None — i.e., change the conditional that sets profile (currently "profile = acquisition_profile or request.acquisition_profile") to an explicit None check on the acquisition_profile parameter so callers passing {} are honored and you avoid re-reading/requesting request.acquisition_profile.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/acquirer.py at line 216, The current assignment profile = acquisition_profile or request.acquisition_profile incorrectly treats an empty dict as falsy; change it to use an explicit None check so an empty dict passed in is preserved (e.g. set profile to acquisition_profile if acquisition_profile is not None, otherwise use request.acquisition_profile), updating the assignment in acquirer.py where acquisition_profile, request.acquisition_profile and profile are referenced.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/adapters/shopify.py around lines 467 - 475, The _localized_product_path function can drop a leading locale when "/products/" isn't present; update it so when marker_index < 0 it attempts to detect and preserve a leading locale prefix from raw_path (e.g., a leading segment like "/en" or "/en-GB") using a start-of-path check/regex and assign that to prefix; keep the existing behavior when marker_index >= 0 (prefix from before "/products/") and return f"{prefix}/products/{product_handle}" as before, with the same empty-handle fallback logic in _localized_product_path.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.exports.json around lines 1153 - 1159, Multiple currency symbol maps are duplicated and inconsistent; ensure the yen mapping (unicode \u00a5 or "¥" -> "JPY") is present in every map or, better, consolidate to a single canonical map and have other places reference it. Update CURRENCY_SYMBOL_MAP, EXTRACTION_RULES.listing_extraction.buy_box_currency_symbol_map, LISTING_BUY_BOX_CURRENCY_SYMBOL_MAP, and NORMALIZATION_RULES.currency_symbol_map so they either all include the "\u00a5"/"¥" -> "JPY" entry or are replaced to import/alias a single shared map constant, and update any consumers to read from that canonical symbol map to avoid divergence.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/field_mappings.exports.json around lines 43 - 90, The ecommerce_detail schema currently lists "vendor" as a distinct field while FIELD_ALIASES.brand includes "vendor", causing ambiguity; decide which behavior you want and implement it: either remove "vendor" from the ecommerce_detail "items" array to enforce alias normalization into brand (update the ecommerce_detail definition to exclude "vendor"), or remove "vendor" from FIELD_ALIASES.brand so vendor remains an independent field (update FIELD_ALIASES.brand to drop "vendor"); ensure whichever side you change is the one referenced by the normalization logic so that ingestion yields a single, unambiguous field.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/field_mappings.exports.json around lines 449 - 455, The "size" alias mapping (the JSON object with key "size") is missing the canonical field name in its "items" array; update the "items" list for the "size" mapping to include "size" itself (in addition to "sizes" and "variant_size") so exact-source fields named "size" will normalize correctly when using the alias lookup logic.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/js_state_mapper.py around lines 902 - 904, The variant_id assignment currently falls back to productId/product_id which is incorrect; change the variant_id extraction (the variant_id variable) to only use true variant identifiers such as "id", "variantId", or "variant_id" (e.g. text_or_none(variant.get("id") or variant.get("variantId") or variant.get("variant_id"))), remove any use of productId/product_id as a fallback for variant_id, and keep productId fallback only where appropriate (e.g., sku logic). This ensures URLs built from variant_id and functions like _variant_identity/_merge_variant_rows keep variant-level uniqueness.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/globals.css around lines 2005 - 2008, The .commerce-table .ct-muted rule applies both color and opacity which can stack and drop contrast below WCAG; remove the opacity property and instead pick a single, lower-contrast token (e.g., use an existing muted token or create a dedicated token like --color-text-muted) and set only color: var(--your-muted-token) in the .ct-muted selector so muted text preserves accessible contrast.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/product-intelligence/page.tsx around lines 296 - 299, The header that toggles the config (the JSX element using onClick={() => setConfigExpanded(!configExpanded)}) is not keyboard-accessible; update that element to act like a button by adding role="button", tabIndex={0}, aria-expanded={configExpanded} and implement an onKeyDown handler that calls setConfigExpanded(!configExpanded) when Enter or Space is pressed so keyboard users can toggle the section; ensure the handler references the existing setConfigExpanded and configExpanded symbols.

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/crawl/crawl-config-screen.tsx at line 744, The hasTarget boolean incorrectly only checks targetUrl when singleUrlMode is true; update its condition to also treat sitemap mode as a single-target case by checking categoryMode === "sitemap". Concretely, change the hasTarget expression so that if singleUrlMode || categoryMode === "sitemap" it validates targetUrl.trim().length > 0, otherwise it checks bulkUrls.trim().length > 0 || csvFile !== null; update the variable where defined (hasTarget) and keep references to singleUrlMode, categoryMode, targetUrl, bulkUrls, and csvFile intact.

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/crawl/crawl-run-screen.tsx around lines 837 - 844, The stepper currently sets the "Crawl" step active based only on live, so when terminal is true (run finished) the prior "Crawl" step appears inactive; update the relevant JSX using CsFlowStep and CsFlowConnector: change the second step's active prop to active={live || terminal} (CsFlowStep step={2} label="Crawl" ...) and also update the connector before the "Complete" step (CsFlowConnector) to active={live || terminal} so completed runs render prior steps as done.

- Verify each finding against the current code and only fix it if needed.

In @frontend/next-env.d.ts at line 3, The import in next-env.d.ts manually references "./.next/types/routes.d.ts" which may be incorrect or overwritten by Next.js; verify whether next-env.d.ts should be left to Next.js auto-generation and either remove the manual import or update it to the correct generated path for your Next.js version (e.g., ".next/dev/types" vs ".next/types") as appropriate; specifically check and adjust the import string in next-env.d.ts and, if this import is required, document why it must be manual and add a CI/build step or Next.js config to ensure the correct generated path is produced rather than relying on a hand-edited file.

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: Read endpoints can fail when a stored profile is not normalized before validation.
   Path: backend/app/api/crawls.py
   Lines: 96-96

2. possible bug: Response metadata can be silently stripped from route definitions.
   Path: backend/app/api/records.py
   Lines: 42-42

3. logic error: Malformed record payloads are silently converted into empty dictionaries, masking bad data.
   Path: backend/app/schemas/crawl.py
   Lines: 63-63

4. possible bug: Invalid payload types are accepted instead of being rejected, breaking the model's validation contract.
   Path: backend/app/schemas/crawl.py
   Lines: 68-68

5. logic error: New sensitive-key filtering can remove legitimate settings from the response.
   Path: backend/app/schemas/crawl.py
   Lines: 365-365

6. possible bug: Non-dict acquisition profiles are silently discarded, breaking profile-driven acquisition behavior.
   Path: backend/app/services/acquisition/acquirer.py
   Lines: 88-88

7. logic error: The new keyword selection logic ignores all detail surfaces except commerce and job pages.
   Path: backend/app/services/acquisition/browser_detail.py
   Lines: 486-486

8. possible bug: Identity creation can now fail hard when fingerprint alignment returns no value.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 418-418

9. possible bug: A new progress-event gate can prevent capturing the rendered DOM even after a successful traversal.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 833-833

10. resource leak: Upstream connection cleanup can become inconsistent because relay and teardown use different local handles.
   Path: backend/app/services/acquisition/browser_proxy_bridge.py
   Lines: 127-127

11. logic error: Shared phrase matching can misclassify usable pages as empty terminal pages.
   Path: backend/app/services/acquisition/browser_readiness.py
   Lines: 248-248

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.