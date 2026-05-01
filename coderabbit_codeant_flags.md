These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: The prompt can preserve an incorrect existing category instead of updating it from current evidence.
   Path: backend/app/data/prompts/data_enrichment_semantic.system.txt
   Lines: 4-4

2. logic error: Rejecting zero-valued source run IDs changes the stored contract and drops valid sentinel values.
   Path: backend/app/models/crawl_settings.py
   Lines: 241-241

3. possible bug: DATA_ENRICHMENT_TAXONOMY_PATH now points to shopify_categories.json, but the file path is constructed from backend/app/data/enrichment, and there is no evidence in the repo that the corresponding Shopify taxonomy file exists there. If the deployment still ships only the old Google taxonomy assets, any loader that consumes data_enrichment_settings.taxonomy_path will fail at startup or when enrichment runs.
   Path: backend/app/services/config/data_enrichment.py
   Lines: 27-27

4. possible bug: DATA_ENRICHMENT_ATTRIBUTES_PATH was renamed to shopify_attributes.json, but the config change does not update any corresponding loader or fallback logic. If downstream code expects the previous Google Product Data schema, this new filename will cause a hard failure or empty attribute metadata when the file is read.
   Path: backend/app/services/config/data_enrichment.py
   Lines: 28-28

5. logic error: The re-enrichment test asserts taxonomy_version before the rerun job is processed.
   Path: backend/tests/services/test_data_enrichment.py
   Lines: 275-275

6. possible bug: The prompt-context test uses an empty candidate list, unlike the service's production call path.
   Path: backend/tests/services/test_data_enrichment.py
   Lines: 376-376

7. possible bug: The LLM merge test assumes deterministic fields always win, but the service contract must be verified.
   Path: backend/tests/services/test_data_enrichment.py
   Lines: 638-638

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: The prompt can preserve an incorrect existing category instead of updating it from current evidence.
   Path: backend/app/data/prompts/data_enrichment_semantic.system.txt
   Lines: 4-4

2. logic error: Rejecting zero-valued source run IDs changes the stored contract and drops valid sentinel values.
   Path: backend/app/models/crawl_settings.py
   Lines: 241-241

3. possible bug: DATA_ENRICHMENT_TAXONOMY_PATH now points to shopify_categories.json, but the file path is constructed from backend/app/data/enrichment, and there is no evidence in the repo that the corresponding Shopify taxonomy file exists there. If the deployment still ships only the old Google taxonomy assets, any loader that consumes data_enrichment_settings.taxonomy_path will fail at startup or when enrichment runs.
   Path: backend/app/services/config/data_enrichment.py
   Lines: 27-27

4. possible bug: DATA_ENRICHMENT_ATTRIBUTES_PATH was renamed to shopify_attributes.json, but the config change does not update any corresponding loader or fallback logic. If downstream code expects the previous Google Product Data schema, this new filename will cause a hard failure or empty attribute metadata when the file is read.
   Path: backend/app/services/config/data_enrichment.py
   Lines: 28-28

5. logic error: The re-enrichment test asserts taxonomy_version before the rerun job is processed.
   Path: backend/tests/services/test_data_enrichment.py
   Lines: 275-275

6. possible bug: The prompt-context test uses an empty candidate list, unlike the service's production call path.
   Path: backend/tests/services/test_data_enrichment.py
   Lines: 376-376

7. possible bug: The LLM merge test assumes deterministic fields always win, but the service contract must be verified.
   Path: backend/tests/services/test_data_enrichment.py
   Lines: 638-638

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.