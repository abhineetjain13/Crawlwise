Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_identity.py around lines 1337 - 1392, MaskedRTCPeerConnection is missing an addTrack method so callers using addTrack will get a TypeError; implement addTrack on the MaskedRTCPeerConnection class to mirror the stubbed behavior of removeTrack (accept a track and optional streams, return a placeholder sender object consistent with getSenders or a minimal object with a track property and a stop/remove mechanism) and ensure it updates any internal sender list if present and returns an object compatible with consumers of addTrack (reference the MaskedRTCPeerConnection class, its existing removeTrack(), getSenders(), createDataChannel(), and any internal sender tracking such as getSenders/getReceivers to keep behavior consistent).

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/browser_runtime.py around lines 672 - 686, The eviction loop uses "while sum(len(pool) for _pool_name, pool in pools) - len(candidates) >= max_entries" which over-evicts by continuing when the remaining size equals max_entries; change the loop condition to use ">" instead of ">=" so the loop stops once remaining entries equal max_entries. Update the condition in the block containing pools, candidates, and max_entries (the eviction loop that computes candidate_keys, remaining, and appends to candidates) to prevent selecting an extra eviction candidate; keep the rest of the eviction selection logic (eviction_key(), remaining.sort(...), candidates.append(...)) unchanged.

These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: Replacing the browser's WebRTC API with an incomplete stub breaks legitimate page behavior.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 1306-1306

2. logic error: _resolve_timezone_id() now returns the first timezone for any non-empty country entry, which can produce arbitrary timezone selection for multi-timezone countries.
   Path: backend/app/services/acquisition/browser_identity.py
   Lines: 836-836

3. logic error: Client rejection can be reported more than once on the same SOCKS connection.
   Path: backend/app/services/acquisition/browser_proxy_bridge.py
   Lines: 164-164

4. logic error: Eviction now crosses runtime pools and can close unrelated browsers unexpectedly.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 655-655

5. logic error: The init-script toggle is reversed, so the flag controls the opposite of what its name implies.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 375-375

6. logic error: Default browser context creation now discards the init script and changes browser behavior.
   Path: backend/app/services/crawl_fetch_runtime.py
   Lines: 135-135

7. logic error: Prefix-based identity matching can incorrectly equate different product identifiers.
   Path: backend/app/services/detail_extractor.py
   Lines: 727-727

8. logic error: Stripping suffix noise before deduplication can merge distinct variant options.
   Path: backend/app/services/detail_extractor.py
   Lines: 1555-1555

9. possible bug: A failing target diagnostic can abort the entire report generation.
   Path: backend/run_browser_surface_probe.py
   Lines: 1808-1808

10. possible bug: An invalid target URL stops the whole report instead of being skipped.
   Path: backend/run_browser_surface_probe.py
   Lines: 1812-1812

11. possible bug: The test assumes real-chrome and Chromium share the same eviction path without proving that contract.
   Path: backend/tests/services/test_browser_context.py
   Lines: 2219-2219

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.