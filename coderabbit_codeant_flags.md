Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/acquirer.py around lines 244 - 247, The current except block in acquirer.py conflates any httpx.HTTPError/TimeoutError/OSError with a drained proxy pool when request.proxy_list is set; change it so only an explicit proxy-exhaustion signal from the underlying fetch (e.g., a raised ProxyPoolExhausted from fetch_page or a special return value) results in raising ProxyPoolExhausted here—otherwise re-raise the original exception; specifically, update the except handling around the call to fetch_page/fetch_with_proxy to check for ProxyPoolExhausted (or inspect a sentinel return) and avoid wrapping generic network errors into ProxyPoolExhausted when request.proxy_list is non-empty.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/acquisition/acquirer.py around lines 173 - 176, The try/except around await on_event(level, message) silently swallows errors; change the bare except to capture the exception and log it so bugs are visible. Replace the silent return with an except Exception as e: that calls the module logger (e.g., logger.exception or logging.getLogger(__name__).exception) and include contextual info (level and message) in the log call, then return or re-raise as appropriate; update the handler in acquirer.py where on_event is awaited.

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/detail_extractor.py around lines 1012 - 1036, The DOM finalization path is missing the drop_low_signal_zero_detail_price call after backfilling price; update _finalize_dom_detail_record to invoke drop_low_signal_zero_detail_price(record) immediately after backfill_detail_price_from_html(record, html=html) (same placement as in _finalize_early_detail_record) so any zero prices introduced by backfill are filtered before variant backfill, currency reconciliation, and confidence scoring.

- 

- Verify each finding against the current code and only fix it if needed.

In @backend/app/services/domain_run_profile_service.py at line 151, The check creating payload currently uses isinstance(profile, dict) which is inconsistent with the rest of the file and will mis-handle dict-like objects; change that check to isinstance(profile, Mapping) (use the Mapping from collections.abc) so payload = dict(profile or {}) if isinstance(profile, Mapping) else {} and add or ensure an import for Mapping (from collections.abc import Mapping) at the top of the module so behavior matches other functions (see similar uses around lines referenced in the review).

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_crawl_fetch_runtime.py around lines 918 - 922, The test test_fetch_page_preserves_proxy_list_on_browser_first_path currently uses sorted(captured_proxies) which can mask ordering bugs; update the assertion to check exact order instead by asserting captured_proxies (or captured_proxies or []) equals ["http://proxy-one", "http://proxy-two"] so the test verifies the preserved order from the proxy_list passed into the fetch path and complements the separate _resolve_proxy_attempts order tests.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_crawl_fetch_runtime.py around lines 1440 - 1450, The test function test_read_network_payload_body_rejects_oversized_declared_content_length_before_body_read is misnamed because it asserts a successful read; rename it to reflect the actual behavior (e.g., test_read_network_payload_body_allows_small_actual_body_despite_oversized_content_length or test_read_network_payload_body_accepts_small_body_when_content_length_too_large) and update any test docstring or comments; locate the test by the function name and references to FakeBodyResponse and read_network_payload_body and change only the function name and surrounding description to match the asserted outcome.

- Verify each finding against the current code and only fix it if needed.

In @backend/tests/services/test_crawl_service.py around lines 288 - 316, The test saves a domain run profile but doesn't commit it, which can cause visibility issues for note_acquisition_contract_failure; after calling save_domain_run_profile(...) add an explicit await db_session.commit() so the profile is persisted before calling note_acquisition_contract_failure(db_session, domain="example.com", surface="ecommerce_detail", threshold=2).

- Verify each finding against the current code and only fix it if needed.

In @docs/INVARIANTS.md at line 79, There is a missing newline between the paragraph ending with "validation." and the horizontal rule '---'; edit the paragraph around the sentence that contains "It may fill empty fields with provenance and validation." and insert a blank line (or at least a newline) before the '---' separator so the markdown renders correctly; look for that exact sentence in INVARIANTS.md to locate and fix it.

- Verify each finding against the current code and only fix it if needed.

In @frontend/components/crawl/crawl-run-screen.tsx around lines 1182 - 1184, The label "XPath winner" is hardcoded even when item.selector_kind may be different or null; update the UI in the crawl-run-screen component to render a dynamic label based on item.selector_kind (e.g., show `${item.selector_kind} winner` when present, fallback to a generic label like "Selector winner" or omit the label if null/undefined) and keep the existing Sources line using item.source_labels.join(", ") || "—"; locate the element rendering the label near the JSX that references item.selector_kind and replace the static text with a conditional/dynamic expression that safely handles null/undefined values.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Persisting the acquisition contract in a new nested shape can drop existing contract data on round-trip.
   Path: backend/app/models/crawl_settings.py
   Lines: 175-175

2. logic error: The requested-field count can be inflated by repaired fields instead of reflecting the caller's actual request.
   Path: backend/app/services/confidence.py
   Lines: 117-117

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.