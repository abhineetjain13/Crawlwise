P1
Check lazy-loaded image hints against the real image URL
Dismiss
When a listing card uses a placeholder src plus data-src/data-original for the real product image, this code evaluates only the placeholder URL before deciding whether the image is noise. That causes _extract_image_title_hint() to skip the node entirely, so cards whose visible title is review text or another placeholder never get promoted from the image alt/title and can be dropped altogether. A Zivame-style card with src=solid-loader.gif and a real data-original image now reproduces this.


C:\Projects\pre_poc_ai_crawler\backend\app\services\listing_extractor.py:1046-1052
P2
Retry the JSON records query during terminal reconciliation
Dismiss
This recovery loop only refetches tableRecordsQuery. If a completed run opens on the JSON tab, or the first JSON fetch races the backend and returns empty while records are still materializing, jsonRecordsQuery never gets another retry even after the table query eventually fills in. The previous implementation retried both endpoints, so this change leaves the JSON preview stale/blank for exactly the late-arriving-records case this effect is meant to heal.


C:\Projects\pre_poc_ai_crawler\frontend\components\crawl\crawl-run-screen.tsx:613-622

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/config/extraction_rules.py at line 91, The regex entry r"^product name$" in extraction_rules.py is overly generic and will exclude any literal product titled "Product Name"; update this rule in the extraction rules list to avoid false positives by either removing it, making it more specific (e.g., require surrounding context or additional tokens/keywords), or constrain it with case-insensitive and optional separators only if that fits extraction intent; locate the literal pattern r"^product name$" in the rules list and adjust or delete it accordingly and add a brief comment explaining the rationale for the change.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/domain_utils.py around lines 66 - 69, The current check in the function uses "hostname_only, separator, _port = host.partition(':')" and then requires "and not separator", which causes names like "localhost:3000" to be treated as non-special; remove the "and not separator" restriction so that membership against _SPECIAL_USE_HOSTNAMES and suffix checks against _SPECIAL_USE_SUFFIXES operate on hostname_only regardless of whether a port was present (i.e., keep partition to strip port but don't gate the special-hostname check on separator); update the expression that returns the boolean to use "hostname_only in _SPECIAL_USE_HOSTNAMES or any(hostname_only.endswith(suffix) for suffix in _SPECIAL_USE_SUFFIXES)" and add a brief comment explaining ports are ignored when classifying special-use hostnames.

- Verify each finding against the current code and only fix it if needed.

In @frontend/lib/constants/timing.ts at line 6, TERMINAL_RECORDS_RETRY_LIMIT is a count and shouldn't live in POLLING_INTERVALS (which only holds millisecond durations); extract TERMINAL_RECORDS_RETRY_LIMIT into a new constants object (e.g., RETRY_LIMITS or POLLING_RETRY_LIMITS) and remove it from POLLING_INTERVALS (or alternatively rename POLLING_INTERVALS to POLLING_CONFIG if you intend to keep mixed types), then update all usages that reference POLLING_INTERVALS.TERMINAL_RECORDS_RETRY_LIMIT to reference the new symbol (e.g., RETRY_LIMITS.TERMINAL_RECORDS_RETRY_LIMIT) so naming and types remain semantically correct.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Unnormalized query parameters can make profile listing return inconsistent results.
   Path: backend/app/api/crawls.py
   Lines: 300-300

2. possible bug: Changing the persistence function's return contract can break callers that depend on its previous behavior.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 115-115

3. logic error: The new special-use-domain checks suppress cookie storage for localhost-style domains.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 71-71

4. possible bug: `list_domain_cookie_memory` filters special-use domains after fetching all rows.
   Path: backend/app/services/acquisition/cookie_store.py
   Lines: 178-178

5. logic error: Non-job listings without extra signals are now rejected because support depends on a structured-only source tag.
   Path: backend/app/services/listing_extractor.py
   Lines: 486-486

6. logic error: _looks_like_real_listing_row now accepts rows with populated_fields >= 3 even when price_present is false.
   Path: backend/harness_support.py
   Lines: 952-952

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.