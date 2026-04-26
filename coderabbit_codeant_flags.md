These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Seed generation is based on a different identity snapshot than the browser context.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 1188-1188

2. security: Enabling `iframe_content_window` is inconsistent with the stated stealth split.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 122-122

3. possible bug: New browser connection settings are never applied to runtime.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 192-192

4. logic error: Chrome runtime shim hard-codes extension behavior.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 402-402

5. possible bug: Screen orientation patch unconditionally overrides native behavior.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 914-914

6. possible bug: WebGL readPixels patch assumes a typed array buffer is always present.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 914-914

7. logic error: Redirect mismatch detection can incorrectly allow a wrong product record through.
   Path: backend/app/services/detail_extractor.py
   Lines: 782-782

8. logic error: A ready probe can now override stronger challenge evidence and hide a blocked response.
   Path: backend/app/services/publish/metrics.py
   Lines: 55-55

9. logic error: The new behavioral-smoke check can no longer distinguish trusted browser input from a synthetic fallback because `_collect_behavioral_smoke()` now uses Playwright's `page.mouse.move()` / `page.mouse.click()` for the only events it observes.
   Path: backend/run_browser_surface_probe.py
   Lines: 518-518

10. possible bug: Canonical product URLs with variant SKU suffixes can be rejected by overly strict identity matching.
   Path: backend/tests/services/test_crawl_engine.py
   Lines: 310-310

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.