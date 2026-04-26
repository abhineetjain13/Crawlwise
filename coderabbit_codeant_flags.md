These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Browser diagnostics are misclassified because block state is discarded.
   Path: backend/app/services/acquisition/acquirer.py
   Lines: 95-95

2. logic error: The new browser behavior telemetry misreports activity when only scrolling occurs.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 230-230

3. possible bug: Swallowing typing errors hides partial input and can leave forms in a corrupted state.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 253-253

4. possible bug: Behavior realism failures are ignored and do not affect the fetch flow.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 1421-1421

5. logic error: Overly broad detail-page detection can misclassify listing pages and skip valid listing extraction.
   Path: backend/app/services/adapters/adp.py
   Lines: 226-226

6. logic error: Image extraction can drop the fallback URL even when an alternate image attribute exists.
   Path: backend/app/services/adapters/amazon.py
   Lines: 122-122

7. security: Loose suffix host matching can route unrelated domains to the wrong adapter.
   Path: backend/app/services/adapters/base.py
   Lines: 45-45

8. possible bug: Overly broad text extraction handling can silently drop valid node content.
   Path: backend/app/services/adapters/base.py
   Lines: 20-20

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/schemas/product_intelligence.py at line 29, The new Literal restriction on the search_provider field in product_intelligence.py will break existing "duckduckgo" values; add a Pydantic pre-validator on the search_provider field (e.g., @validator('search_provider', pre=True) def _map_duckduckgo(cls, v): ...) that maps the string "duckduckgo" → "serpapi" and returns other values unchanged so existing persisted jobs keep validating against the Literal["serpapi","google_native"] type; alternatively, if you want to keep the option live, include "duckduckgo" in the Literal options instead.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/adapters/base.py around lines 45 - 50, The function adapter_host_matches currently treats inputs as possibly None but types them as str; update its signature to accept Optional[str] (or union str | None) so the type hints match the defensive checks in adapter_host_matches, keep the existing str(host or "")/str(expected or "") normalization, and add a concise docstring to adapter_host_matches explaining it normalizes inputs (trim/lower) and returns true for exact host matches or when the host is a subdomain of expected (i.e., endswith ".expected"); alternatively, if you guarantee non-None callers, remove the "or ''" guards and keep the parameters as str, still adding the same docstring to document subdomain matching behavior.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/adapters/nike.py at line 112, Replace the hardcoded "INR" currency literal in the product payload with a dynamic value: first try to read product.get("currency") from the parsed product data (use that if present), otherwise derive the currency from the request domain (map nike.com→USD, nike.co.uk→GBP, nike.com.au→AUD, nike.ca→CAD) and use a sensible default fallback (e.g., USD). Update the code location that builds the product dict (the place containing the "currency": "INR" entry) to perform this lookup so downstream consumers receive correct currency per domain or page data.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/pipeline/extraction_retry_decision.py around lines 5 - 8, The file references AcquisitionResult as a type on lines ~12 and ~44 but doesn't import it; add an import for AcquisitionResult (e.g., alongside PageEvidence) from the module that defines it (for example, import AcquisitionResult from app.services.acquisition.acquirer) so static type checkers and runtime typing utilities (typing.get_type_hints) can resolve the symbol used in the functions/methods that reference AcquisitionResult.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/product_intelligence/discovery.py around lines 267 - 279, When typed_chars > 0 the code attempts to call page.keyboard.press but if keyboard.press is missing it currently falls through and never triggers navigation; update the block handling typed (the branch using typed.get("typed_chars")) to add a fallback that calls page.goto(_google_native_search_url(normalized_query, result_limit), wait_until="domcontentloaded", timeout=int(GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS)) and then awaits page.wait_for_timeout(int(GOOGLE_NATIVE_RESULT_WAIT_MS)) when press is not callable (or catch exceptions from await press and perform the same fallback), ensuring the behavior matches the existing else branch; you can also factor out the shared navigation+wait logic into a helper to avoid duplication.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/data/prompts/product_intelligence_brand_inference.system.txt at line 11, Update the rule that currently reads "Do not return a retailer or marketplace name as the brand..." to explicitly handle retailer-owned private-label brands: add a sentence stating that retailer-owned private-label brand names (e.g., "Amazon Basics", "Great Value", "Kirkland Signature", "Up & Up") should be returned as the brand when the product is labeled/marketed under that private-label name, while excluding only the retailer/corporate name when it is not the product's brand; include both positive and negative examples to make the decision deterministic for the brand inference logic.