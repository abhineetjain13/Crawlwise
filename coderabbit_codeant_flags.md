
   These are comments left during a code review. Please review all issues and provide fixes.


2. possible bug: The public `coerce_int` alias is behaviorally identical here.
   Path: backend/app/services/acquisition/browser_detail.py
   Lines: 20-20

3. logic error: The markdown refactor can now return empty output for link-only pages.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 1179-1179

4. possible bug: Narrowed exception handling can let accessibility snapshot failures abort markdown generation.
   Path: backend/app/services/acquisition/browser_page_flow.py
   Lines: 1207-1207

5. possible bug: Name-only platform entries can be registered as available without any signal to detect them correctly.
   Path: backend/app/services/config/platforms.json
   Lines: 366-366

6. security: Proxy diagnostics can leak the full proxy URL instead of a redacted value.
   Path: backend/app/services/crawl_fetch_runtime.py
   Lines: 528-528

7. logic error: Early exit can now return an uncorrected title that the DOM path would have fixed.
   Path: backend/app/services/detail_extractor.py
   Lines: 1245-1245


Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.