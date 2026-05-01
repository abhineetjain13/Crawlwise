These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Stamping based on two columns can leave legacy databases at the wrong Alembic revision.
   Path: backend/app/core/migrations.py
   Lines: 67-67

2. logic error: Zero-valued quality success identifiers are collapsed to null during normalization.
   Path: backend/app/models/crawl_settings.py
   Lines: 222-222

3. logic error: Two commerce test URLs were accidentally concatenated into one invalid line.
   Path: TEST_SITES.md
   Lines: 152-152

4. security: A new admin reset endpoint can delete enrichment data immediately with no additional safety distinction.
   Path: backend/app/api/dashboard.py
   Lines: 71-71

5. possible bug: An unconditional router import can prevent the entire app from starting if the new module has import-time failures.
   Path: backend/app/main.py
   Lines: 15-15

6. possible bug: Duplicate ORM model definitions can break SQLAlchemy model registration and mapping.
   Path: backend/app/models/crawl.py
   Lines: 751-751

7. possible bug: Adding a new non-null column without the corresponding schema update will break database operations.
   Path: backend/app/models/crawl.py
   Lines: 529-529

8. logic error: Normalizing the quality snapshot now strips data that callers may expect to survive storage round-trips.
   Path: backend/app/models/crawl_settings.py
   Lines: 201-201

9. logic error: Successful captures never release reserved budget, so later captures are throttled by stale accounting.
   Path: backend/app/services/acquisition/browser_capture.py
   Lines: 263-263

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_page_flow.py around lines 1211 - 1215, The shallow copy call copy(analysis.soup) passed into _prepare_markdown_soup can still share nodes with the original BeautifulSoup tree so subsequent .decompose() calls mutate analysis.soup; replace the shallow copy with a deep copy (e.g., use copy.deepcopy(analysis.soup)) where analysis.soup is passed to _prepare_markdown_soup (and add the copy import if missing) to ensure _prepare_markdown_soup’s mutations don’t affect the original HtmlAnalysis.soup.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/data-enrichment/page.tsx around lines 64 - 65, The import for EnrichmentStatus and EnrichmentTableLoading is located after the loadPrefill function; move the statement "import { EnrichmentStatus, EnrichmentTableLoading } from './enrichment-components';" up into the main import block alongside the other imports (i.e., with the top-of-file imports), and remove the trailing duplicate import that currently appears after the loadPrefill function so all imports are grouped consistently at the top.

- Verify each finding against the current code and only fix it if needed.

In @frontend/app/data-enrichment/enrichment-components.tsx around lines 72 - 92, The formatPrice function can throw RangeError when Intl.NumberFormat receives an invalid currency code (from currency param or p.currency); to fix, validate or sanitize the currency before calling Intl.NumberFormat (e.g., ensure curr and currency are non-empty valid ISO 4217 strings and fallback to "USD"), or wrap the NumberFormat/format call in a try-catch and return a safe fallback like "--" or a plain numeric/string fallback; update the branches in formatPrice (the object branch using p.amount/p.price_min and curr, and the number branch using currency) to apply this validation/safe fallback consistently.

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: Replacing the existing HTML-to-text normalization may change extracted product text formatting and break downstream expectations.
   Path: backend/app/services/adapters/nike.py
   Lines: 213-213

2. logic error: Removing `thriftbooks` from the registry prevents that adapter from being instantiated.
   Path: backend/app/services/adapters/registry.py
   Lines: 32-32

3. logic error: Candidate finalization can now merge the wrong values from a source group.
   Path: backend/app/services/detail_extractor.py
   Lines: 390-390

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.