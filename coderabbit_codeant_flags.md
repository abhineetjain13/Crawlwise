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