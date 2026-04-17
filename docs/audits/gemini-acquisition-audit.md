Phase 4 Boundary Review
Scope
Target file or slice: backend/app/services/acquisition/acquirer.py
Files reviewed: acquirer.py, test_acquirer.py
Boundary question being decided: Does the acquisition waterfall correctly separate network I/O and escalation policy from DOM parsing, page-type discovery, and source detection?
Executive Decision
Verdict: MIXED
Primary reason: The file properly orchestrates network fallbacks (HTTP to Browser) but violently breaches the extraction/discovery boundary by importing BeautifulSoup and manually parsing the DOM to count JSON-LD tags, identify job iframes, and execute price regexes.
Can the file stay in its current package? YES (but DOM parsing and semantic evaluation must be evicted).
Ownership Map
Concern: Network fetching, attempt pacing, and curl-to-playwright escalation policy.
Current owner: acquirer.py (_try_http, _try_browser, _acquire_once)
Correct owner: acquirer.py (Acquire stage)
Evidence: Orchestrates fetch_html_result and fetch_rendered_html based on runtime profiles.
Keep / move / split / delete: Keep
Notes: This is the exact intended purpose of the acquisition orchestration shell.
Concern: Proxy rotation and proxy cooldown state management.
Current owner: acquirer.py (ProxyRotator, _PROXY_FAILURE_STATE, _mark_proxy_failed)
Correct owner: acquire (e.g., proxy_manager.py)
Evidence: Manages round-robin selection and exponential backoff for network routing.
Keep / move / split / delete: Split (within acquire)
Notes: Safely belongs in the acquisition boundary, but clutters the main orchestrator file.
Concern: Listing signal detection (counting <a> tags, running price regexes, finding images).
Current owner: acquirer.py (_collect_listing_signal_summary, _analyze_html_sync)
Correct owner: discover (e.g., signal_inventory.py)
Evidence: Uses BeautifulSoup(html, HTML_PARSER), soup.select("a[href]"), and price_re.search(anchor.get_text()) to determine if a page is a listing.
Keep / move / split / delete: Move
Notes: Network I/O layers must not parse the DOM or understand the semantic definition of a "listing card".
Concern: JSON-LD schema inspection.
Current owner: acquirer.py (_count_json_ld_type_signals, _count_json_ld_non_product_types)
Correct owner: discover
Evidence: Parses raw HTML strings to count "@type": "Product" and "@type": "JobPosting".
Keep / move / split / delete: Move
Notes: Schema.org detection is a discovery and extraction concern.
Concern: Promoted iframe discovery (ATS/Job board detection).
Current owner: acquirer.py (_find_promotable_iframe_sources, _promotable_job_iframe_tokens)
Correct owner: discover
Evidence: Inspects <iframe src> and <frame src> tags for tokens like "job", "career", and specific ATS domains.
Keep / move / split / delete: Move
Notes: Identifying target data sources within a page is the definition of the discover stage.
Boundary Violations
Violation 1
Severity: critical
Concern: Listing card counting and semantic page evaluation.
Current location: _collect_listing_signal_summary and _analyze_html_sync in acquirer.py.
Why it violates the boundary: Forces the acquisition layer to parse HTML and evaluate data semantics (e.g., finding prices and images inside anchor tags) just to decide if the HTTP payload is "good enough" or if it needs to escalate to the browser.
Correct destination: app.services.discover (or app.services.extract.signal_inventory).
What should remain behind: The boolean decision logic (if not page_signals.is_extractable: escalate_to_browser()).
What should be deleted instead of moved: Inline BeautifulSoup instantiation inside the network retry loop.
Violation 2
Severity: high
Concern: JSON-LD and Next.js data signal detection.
Current location: _assess_extractable_html, _count_json_ld_type_signals, _count_json_ld_non_product_types in acquirer.py.
Why it violates the boundary: Acquisition should not know what __NEXT_DATA__ is or how to count Schema.org types. It couples network escalation to specific frontend frameworks and schema formats.
Correct destination: app.services.discover.
What should remain behind: A simple call to discover.assess_extractability(html, url).
What should be deleted instead of moved: The raw string-matching html_lower.find('"@type"') logic, which duplicates robust JSON-LD parsing that already exists in the extraction stage.
Violation 3
Severity: medium
Concern: Job board iframe token heuristics.
Current location: _promotable_job_iframe_tokens and _find_promotable_iframe_sources in acquirer.py.
Why it violates the boundary: Hardcodes domain knowledge (e.g., "career", "jobs") inside the network fetching module to find iframe URLs.
Correct destination: app.services.discover.
What should remain behind: The orchestration logic that takes a list of promoted_sources and attempts to fetch them (_try_promoted_source_acquire).
What should be deleted instead of moved: None.
Canonical Homes
Helper or policy: Extractability Assessment (_assess_extractable_html and children)
Canonical home: app.services.discover (or app.services.extract.signal_inventory.py)
Why: Evaluating the semantic usefulness of HTML bytes requires DOM parsing and domain rules. It is the core responsibility of the discovery stage.
Helper or policy: Proxy Rotation and Cooldown State (ProxyRotator, _PROXY_FAILURE_STATE)
Canonical home: app.services.acquisition.proxy_manager
Why: This is a strictly acquisition-owned concern, but splitting it prevents the main orchestrator file from becoming a dumping ground for global lock state and time-based eviction logic.
Refactor Guardrails
What must not be mixed in the same slice: Network HTTP/Browser clients must not be in the same file as BeautifulSoup or regexes that search for prices/job titles.
What is safe to defer: Moving the proxy rotation logic out of acquirer.py. It is ugly but does not violate a cross-stage boundary.
What naming change is required, if any: _assess_extractable_html should be integrated into the cross-stage SignalInventory payload so the parsing happens exactly once.
Final Recommendation
SPLIT BY OWNERSHIP
Reason:
The file successfully acts as the acquisition orchestrator but currently subsumes the discover stage's responsibilities by manually parsing HTML to grade page quality. The DOM parsing and semantic signal detection must be evicted to establish a strict boundary.
First 3 concrete next actions:
Move _collect_listing_signal_summary, _count_json_ld_type_signals, and _find_promotable_iframe_sources to a dedicated discover or signal_inventory module.
Refactor _analyze_html_sync and _assess_extractable_html into a single external contract (e.g., assess_html_signals(html, url) -> SignalSummary) that acquirer.py imports.
Remove from bs4 import BeautifulSoup from acquirer.py to physically enforce the boundary preventing DOM traversal inside the acquisition module.