D1. SOLID / DRY / KISS
Dimension: SOLID / DRY / KISS
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
MEDIUM [app/services/platform_url_normalizers.py → normalize_platform_acquisition_url (lines 14-20)]:
The platform_url_normalizers.py module contains a hardcoded if family == "adp": check. This is an Open/Closed Principle (OCP) violation. Normalization for ADP is hardcoded into the generic acquisition path rather than being owned by the ADPAdapter itself.
INVARIANTS.md clause 21: "Generic crawler paths stay generic. Do not hardcode tenant- or site-specific behavior in shared runtime."
Production failure mode it enables: Adding new platform URL normalization requires modifying shared acquisition core logic instead of simply updating an adapter class, leading to merge conflicts and surface bleed.
Verification: grep -r "family == \"adp\"" backend/app/services/platform_url_normalizers.py
Verdict: The codebase has undergone a significant refactor and exhibits strong separation of concerns across extraction and acquisition boundaries. The OCP violation in URL normalization is an isolated leak in an otherwise well-structured domain model.
D2. Configuration Hygiene
Dimension: Configuration Hygiene
Floor: 9/10 | Ceiling: 9/10 | Score: 9.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
No violations found.
Verification: grep -r "if \"amazon\" in" backend/app/services/ returns empty. grep -rn "timeout=" backend/app/services/ predominantly references crawler_runtime_settings.
Verdict: Configuration hygiene is excellent. Timeouts, limits, and boolean flags are tightly controlled via crawler_runtime_settings. Platform-specific heuristics are accurately constrained to platform_policy.py and JSON configuration.
D3. Scalability & Resource Management
Dimension: Scalability & Resource Management
Floor: 7/10 | Ceiling: 9/10 | Score: 8.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
MEDIUM [app/services/acquisition/browser_capture.py → read_network_payload_body (lines 201-204)]:
The payload body is read into memory entirely via body_bytes = await response.body() before its size is checked against payload_budget. If the server streams a multi-gigabyte response without a Content-Length header (e.g., chunked transfer encoding), this will cause an immediate Out Of Memory (OOM) crash in the Playwright worker.
ENGINEERING_STRATEGY.md AP-8 (Resource unboundedness).
Production failure mode it enables: Malicious or misconfigured target servers streaming infinite payloads will kill the browser container, dropping all active browser sessions.
Verification: grep -A 2 "await response.body()" backend/app/services/acquisition/browser_capture.py
Verdict: Browser context limits, semaphores, and queue draining are handled properly. However, the unchecked reading of network responses directly into memory is a latent denial-of-service vulnerability.
D4. Extraction & Normalisation Pipeline
Dimension: Extraction & Normalisation Pipeline
Floor: 4/10 | Ceiling: 8/10 | Score: 6.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
CRITICAL [app/services/normalizers.py → normalize_decimal_price (lines 47-66)]:
normalize_decimal_price blindly extracts any digit sequence using _NUMERIC_TEXT_RE.search(text). When adapter data or JSON-LD mislabels a generic string (e.g., "review_count": "157") as a price, this function silently accepts it because it does not require a currency symbol or contextual boundary. The attached Field Audit Report confirms that generic integers ("126", "136") are polluting the price fields.
INVARIANTS.md clause 4: "Acquisition returns observational facts only... Do not fabricate".
Production failure mode it enables: Corrupted pricing data silently enters the data warehouse, destroying e-commerce data integrity.
Verification: grep -r "_NUMERIC_TEXT_RE.search" backend/app/services/normalizers.py
HIGH [app/services/detail_extractor.py → _apply_dom_fallbacks (lines 104-109)]:
extract_page_images(..., exclude_linked_detail_images=True) is called unconditionally for detail surfaces. On detail pages, product gallery thumbnails are almost always wrapped in <a> tags pointing to the full-resolution image URL. By excluding linked images, the extractor is stripping the primary product image gallery. The Field Audit Report confirms additional_images is missing on 50% of detail runs.
INVARIANTS.md clause 11: "Persisted record.data contains only populated logical fields." (Loss of primary data).
Production failure mode it enables: Severe data loss for visual e-commerce and real estate scraping where multiple images are required.
Verification: grep -A 5 "extract_page_images(" backend/app/services/detail_extractor.py
MEDIUM [app/services/config/extraction_rules.exports.json → LISTING_TITLE_CTA_TITLES (approx lines 1500)]:
_listing_title_is_noise relies on hardcoded string lists. It does not proactively reject numeric-only strings. The ranking heuristics in listing_candidate_ranking.py subtract points for digits but do not nullify them, allowing "1" or "37" to be saved as a title if it is the only candidate.
INVARIANTS.md clause 13: "Commerce/job extraction must filter page chrome and metadata noise before persistence."
Production failure mode it enables: Garbage records containing pagination numbers or menu indexes saved as products.
Verification: grep -r "title.isdigit()" backend/app/services/listing_extractor.py (Returns empty).
Verdict: The extraction hierarchy is structurally sound, leveraging advanced mechanisms like ghost-routing and JS-state parsing. However, weak normalizers and overly aggressive image deduplication filters are causing severe data loss and corruption at the final yard line.
D5. Traversal Mode
Dimension: Traversal Mode
Floor: 9/10 | Ceiling: 9/10 | Score: 9.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
No violations found.
Verification: grep -r "_is_same_origin" backend/app/services/acquisition/traversal.py
Verdict: Traversal logic correctly separates DOM mutation triggers from the evaluation of layout progression. Cross-tenant path boundaries are rigorously enforced.
D6. Resilience & Error Handling
Dimension: Resilience & Error Handling
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
LOW [app/services/acquisition/browser_page_flow.py → navigate_browser_page_impl (lines 142-156)]:
Broad except Exception as final_exc: block catches everything, including base KeyboardInterrupt or SystemExit if they bubble up, potentially interfering with graceful shutdown, though the context is narrow.
Verification: grep -r "except Exception as final_exc:" backend/app/services/acquisition/browser_page_flow.py
Verdict: Excellent separation of HTTP protocol errors and browser rendering errors. Diagnostic footprints are preserved perfectly into browser_diagnostics.
D7. Dead Code & Technical Debt
Dimension: Dead Code & Technical Debt
Floor: 9/10 | Ceiling: 9/10 | Score: 9.0/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
No violations found.
Verification: grep -rn "TODO\|FIXME\|HACK" backend/app/services/ returns empty.
Verdict: Codebase is clean, post-refactor, and free of lingering development stubs.
D8. Acquisition Mode
Dimension: Acquisition Mode
Floor: 8/10 | Ceiling: 9/10 | Score: 8.5/10
Previous score: N/A → Change: N/A
Reason for change: FIRST RUN
Violations:
LOW [app/services/platform_policy.py → detect_platform_family (lines 154-159)]:
Uses sequential regex searching over entire HTML strings re.search(raw_pattern, normalized_html, re.IGNORECASE). While it limits by platform configurations, executing heavy regex against 2MB+ HTML payloads blocks the event loop for milliseconds per pattern.
Verification: grep -A 2 "re.search(raw_pattern, normalized_html" backend/app/services/platform_policy.py
Verdict: Proxies are properly threaded through the entire HTTP and Playwright stacks. Identity generation leverages browserforge correctly and is validated for coherency.
Final Summary
Overall Score: 8.2/10 (previous: N/A, delta: N/A)
Root Cause Findings (architectural — require a plan, not a bug fix):
RC-1: platform_url_normalizers.py contains hardcoded platform checks for ADP, violating OCP and generic extraction boundaries. — affects D1, D2.
Leaf Node Findings (isolated bugs — Codex can fix directly):
LN-1: normalize_decimal_price corrupts non-currency numeric strings into price fields.
LN-2: extract_page_images(exclude_linked_detail_images=True) drops legitimate product gallery images on detail pages.
LN-3: _listing_title_is_noise allows numeric-only strings (like pagination digits) to be extracted as titles.
LN-4: read_network_payload_body reads unbounded response payloads into memory, risking OOM.
Genuine Strengths (file-level evidence only, no generic praise):
app/services/network_payload_mapper.py: Ghost routing implementation brilliantly identifies unregistered API payloads by signature-matching keys against known Job/Product schemas without requiring explicit domain-to-API config mappings.
WORK ORDER RC-1: Move Platform URL Normalization to Adapters
Touches buckets: 3 (Acquisition + Browser Runtime), 4 (Extraction)
Risk: MEDIUM
Do NOT touch: crawl_fetch_runtime.py
What is wrong
app/services/platform_url_normalizers.py hardcodes if family == "adp":. The acquisition layer should not contain hardcoded knowledge of specific platforms. URL normalization requirements are platform-specific and belong in the adapters.
What to do
Add a method def normalize_acquisition_url(self, url: str) -> str: to BaseAdapter returning url by default.
Move the ADP-specific URL normalization logic into ADPAdapter.normalize_acquisition_url in app/services/adapters/adp.py.
In acquirer.py, replace the call to normalize_platform_acquisition_url with a dynamic lookup: iterate registered adapters, if adapter.can_handle returns true, use adapter.normalize_acquisition_url.
Delete app/services/platform_url_normalizers.py completely.
Acceptance criteria

app/services/platform_url_normalizers.py is removed.

grep -r "adp" backend/app/services/ does not return matches in the generic acquisition pipeline.

python -m pytest tests -q exits 0
What NOT to do
Do not instantiate every adapter for every URL; use configured_adapter_names or the existing resolve_adapter logic efficiently.
WORK ORDER LN-1: Fix Price Normalization Corruption (single-session fix)
File: app/services/normalizers.py
Function: normalize_decimal_price
Fix: Check if the raw text contains a currency symbol or the word "price" before falling back to the raw _NUMERIC_TEXT_RE. If interpret_integral_as_cents is False and the text lacks currency context, reject it. Alternatively, rely on the upstream PRICE_RE from field_value_core.py to enforce currency bounds.
Test: python -m pytest tests/test_normalizers.py (ensure "126" is rejected but "$126" is accepted).
WORK ORDER LN-2: Preserve Detail Page Gallery Images (single-session fix)
File: app/services/detail_extractor.py
Function: _apply_dom_fallbacks
Fix: Change exclude_linked_detail_images=True to exclude_linked_detail_images=False in the extract_page_images call. Detail pages should extract images wrapped in anchors because they are the gallery thumbnails.
Test: grep -A 5 "extract_page_images(" backend/app/services/detail_extractor.py should show exclude_linked_detail_images=False.
WORK ORDER LN-3: Reject Numeric-Only Titles (single-session fix)
File: app/services/listing_extractor.py
Function: _listing_title_is_noise
Fix: Add a direct check if clean_text(title).isdigit(): return True at the top of the function to instantly reject pagination numbers or raw IDs masquerading as titles.
Test: grep -r "isdigit()" backend/app/services/listing_extractor.py should return the new condition.
WORK ORDER LN-4: Bound Network Payload Reading (single-session fix)
File: app/services/acquisition/browser_capture.py
Function: read_network_payload_body
Fix: Use an async stream reader to enforce the budget size without loading the full payload. Alternatively, check response.headers.get("content-length") and if it exceeds budget, skip. If it's missing, read in chunks and abort if bytes exceed _MAX_CAPTURED_NETWORK_PAYLOAD_BYTES.
Test: grep -r "await response.body()" backend/app/services/acquisition/browser_capture.py should return empty; replaced by safe stream reading.
ARCHITECTURAL RECOMMENDATIONS
1. Schema.org Variant Matrix Reconstruction
Gap Found: Missing variants on structured-source-heavy detail pages (Audit D4 Variant Gap).
Slot: structured_sources.py -> json_ld_candidates
Pseudocode:
code
Python
def _reconstruct_jsonld_variants(node):
    variants = node.get("hasVariant", [])
    if not isinstance(variants, list): return {}
    axes = {}
    for v in variants:
        for k in ("color", "size", "material"):
            if v.get(k): axes.setdefault(k, set()).add(v[k])
    return {"variant_axes": {k: list(v) for k, v in axes.items()}}
Yield: Restores variant_axes and variants output for standard Shopify/WooCommerce JSON-LD nodes that currently get flattened or ignored.
2. Network Payload JSON Fast-Pathing
Gap Found: Playwright processes evaluate expensive regexes (D8) against massive strings.
Slot: browser_capture.py -> _decode_network_payload
Pseudocode:
code
Python
def _decode_network_payload(body_bytes, content_type):
    # using orjson or msgspec for ultra-fast strict JSON parsing
    import orjson
    try:
        return orjson.loads(body_bytes)
    except orjson.JSONDecodeError:
        return None
Yield: Eliminates event-loop blocking when parsing 5MB+ Graphql/AppSync responses intercepted by Playwright. Reduces CPU stall and timeout failures.