These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Currency is being read from price fields instead of currency fields, causing incorrect or missing values.
   Path: backend/app/services/adapters/belk.py
   Lines: 167-167

2. logic error: Legitimate zero-priced products are stripped from extracted detail records.
   Path: backend/app/services/detail_extractor.py
   Lines: 1027-1027

3. logic error: A postprocessing step can incorrectly remove detail records that already gained a valid price.
   Path: backend/app/services/extraction_runtime.py
   Lines: 252-252

4. logic error: Overly narrow JSON-LD type filtering drops valid structured candidates.
   Path: backend/app/services/field_value_candidates.py
   Lines: 271-271

5. logic error: Brand inference fails when the trademark marker is the first character of the title.
   Path: backend/app/services/field_value_core.py
   Lines: 204-204

6. logic error: A single overlong URL slug can prevent otherwise valid brand inference.
   Path: backend/app/services/field_value_core.py
   Lines: 230-230

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/field_value_candidates.py around lines 289 - 294, The conditional is a no-op because both branches return normalized_types; change the branch handling in the function where normalized_types is computed so that when normalized_types is non-empty and fully contained in DETAIL_IRRELEVANT_JSON_LD_TYPES (the set created from DETAIL_IRRELEVANT_JSON_LD_TYPES values), the function returns an empty set (or set()) to suppress irrelevant types, otherwise return normalized_types as before; update the check that builds the comparison set from DETAIL_IRRELEVANT_JSON_LD_TYPES and ensure you reference the same normalized_types variable and the constant DETAIL_IRRELEVANT_JSON_LD_TYPES.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/publish/metrics.py around lines 55 - 68, The final any(item.startswith("provider:") for item in evidence) check is dead code because provider_evidence was already computed from provider_hits or the same list comprehension; remove the redundant check and simplify the tail of the function in publish/metrics.py (the block using _has_strong_challenge_evidence, provider_evidence, browser_outcome, and _has_ready_readiness_probe): after the provider_evidence block and the browser_outcome == "usable_content" check, delete the any(...) branch and let the function fall through to the final return False (or explicitly return False) to eliminate unreachable code; alternatively, if you prefer to keep it for future-proofing, replace it with a brief comment explaining why the defensive check remains.