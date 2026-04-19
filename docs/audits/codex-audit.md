1. SOLID / DRY / KISS
Score: 3/10
Violations:

[CRITICAL] backend/app/services/crawl_fetch_runtime.py -> _browser_fetch, fetch_page (lines 512-1084): one module owns HTTP transport, curl fallback, browser pool lifecycle, block detection, traversal, network capture, readiness waits, and expansion. That is a hard SRP/KISS failure and directly contradicts the architectural intent in CLAUDE.md. Production failure: any change to browser escalation or traversal can break unrelated transport behavior.
[HIGH] backend/app/services/crawl_engine.py -> extract_records (lines 15-57), plus acquisition imports in backend/app/services/acquisition/acquirer.py (lines 9-13), http_client.py (lines 12-15), browser_client.py (line 6), browser_pool.py (lines 6-9): high-level acquisition code imports runtime helpers from a mixed extraction facade. That breaks DIP. Production failure: acquisition refactors are coupled to extraction namespace and wrapper churn.
[MEDIUM] backend/app/services/pipeline/core.py -> get_selector_defaults, get_canonical_fields (lines 99-105): both are thin or no-op wrappers over other modules. backend/app/services/acquisition/browser_client.py -> fetch_rendered_html (lines 25-52) is the same pattern. This is KISS debt. Production failure: more seams to keep synchronized, more test breakage during refactors.
Verdict: The runtime is not modular; it is a pile. The codebase is still depending on wrapper shells and mixed-layer imports instead of owning one clean acquisition boundary.

2. Configuration Hygiene
Score: 4/10
Violations:

[HIGH] backend/app/services/acquisition/acquirer.py -> acquire (lines 61-67): generic acquisition rewrites ADP URLs via detect_platform_family(...) == "adp" and normalize_adp_detail_url(...). That violates INVARIANTS.md rule 19: generic crawler paths must stay generic. Production failure: every new platform exception gets incentivized into shared runtime.
[HIGH] backend/app/services/network_payload_mapper.py -> _payload_priority (lines 54-80): shared ranking logic hardcodes platform families greenhouse, workday, lever, shopify, nextjs. That violates the config-driven runtime rule in INVARIANTS.md rule 7. Production failure: ranking changes require code edits instead of config updates.
[HIGH] backend/app/services/selectors_runtime.py -> infer_surface (lines 48-59): generic selector runtime hardcodes "greenhouse.io" and jobs/careers URL heuristics. That is another rule 19 violation. Production failure: selector documents misclassify non-Greenhouse job pages and pollute the wrong surface.
[MEDIUM] backend/app/services/config/runtime_settings.py (lines 71-76), backend/app/models/crawl_settings.py -> max_pages, max_scrolls, sleep_ms (lines 81-105), backend/app/services/acquisition/acquirer.py -> AcquisitionRequest defaults (lines 17-24), backend/app/services/crawl_fetch_runtime.py -> fetch_page (lines 1041-1050): traversal and pacing defaults are defined in multiple layers with different baselines. Production failure: UI, model normalization, and runtime execution can drift.
Verdict: Site behavior is still leaking into shared code. The config story is not authoritative because the same knobs are defined in multiple places and some platform behavior bypasses config entirely.

3. Scalability, Maintainability & Resource Management
Score: 4/10
Violations:

[HIGH] backend/app/services/pipeline/core.py -> _run_persistence_stage (lines 580-618) calling backend/app/services/artifact_store.py -> persist_html_artifact (lines 9-18): synchronous filesystem writes are executed from an async hot path. That violates INVARIANTS.md rule 21. Production failure: event-loop stalls under concurrent large-page persistence.
[HIGH] backend/app/services/acquisition/http_client.py -> request_result (lines 35-108), _request_with_httpx (lines 111-134): a fresh httpx.AsyncClient is created and closed per adapter request. Production failure: no connection reuse, repeated TLS handshakes, throughput collapse on multi-request adapters.
[HIGH] backend/app/services/acquisition/pacing.py -> wait_for_host_slot, reset_pacing_state (lines 4-9): both functions are empty. Production failure: the code pretends host pacing exists while issuing unthrottled bursts.
[MEDIUM] backend/app/services/crawl_fetch_runtime.py -> _remember_browser_host, _host_prefers_browser (lines 339-373): _BROWSER_PREFERRED_HOSTS only grows on insert and only evicts on lookup. Production failure: long-lived workers accumulate stale host entries.
[MEDIUM] backend/app/services/crawl_fetch_runtime.py -> file size and responsibility spread (lines 1-1084): this file is beyond safe modification radius and already violates the structure budget tested in backend/tests/services/test_structure.py (lines 36-42). Production failure: simple fixes become regression-prone.
Verdict: The concurrency story is weak. Async entrypoints still hide sync I/O, adapter networking wastes connections, and the pacing API is decorative.

4. Extraction & Normalisation Pipeline
Score: 4/10
Violations:

[HIGH] backend/app/services/detail_extractor.py -> _SOURCE_PRIORITY (lines 43-56), build_detail_record (lines 583-664): hydrated JS state is ranked and applied before JSON-LD, microdata, and Open Graph. That contradicts the stated source hierarchy. Production failure: stale app state can overwrite stronger structured data for price, availability, and title.
[HIGH] backend/app/services/js_state_mapper.py -> _map_platform_job_detail_state (lines 116-132) with backend/app/services/config/platforms.json -> Workday entry (lines 107-125): job-detail state mapping only works when a configured extractor exists, and Workday has none despite platform detection expecting __next_data__. Production failure: Workday pages silently fall to DOM/LLM instead of deterministic hydration mapping.
[HIGH] backend/app/services/network_payload_mapper.py -> _payload_priority (lines 68-80) with backend/app/services/config/network_payload_specs.py (lines 10-326): the mapper boosts Workday, Lever, Shopify, and Next.js families, but concrete payload specs only exist for Greenhouse, generic job detail, and generic ecommerce detail. Production failure: captured JSON is ranked as authoritative without having family-specific extraction logic.
[HIGH] backend/app/services/selector_self_heal.py -> apply_selector_self_heal (lines 222-257), _validated_xpath_rules (lines 288-318): synthesized selectors are persisted to domain memory before rerun quality is proven, and validation only checks count > 0 plus a non-empty sample. That violates INVARIANTS.md rule 15. Production failure: one bad selector pollutes future runs for the same (domain, surface).
[MEDIUM] backend/app/services/listing_extractor.py -> extract_listing_records (lines 262-304): listing extraction only considers JSON-LD and embedded JSON as structured sources, ignoring microdata, Open Graph, and hydrated state. Production failure: listing pages with card data outside JSON-LD fall back to weaker DOM heuristics.
[MEDIUM] backend/app/services/pipeline/core.py -> _build_source_trace (lines 151-181), _persist_records (lines 184-236): persisted provenance only stores confidence and a thin source trace even though response schemas and export paths expect manifest_trace, review_bucket, and semantic structures. Production failure: provenance APIs advertise data that the pipeline never writes.
[MEDIUM] backend/app/services/field_value_dom.py -> extract_page_images (lines 160-175): image extraction accepts the first 12 absolute <img> URLs with no analytics/pixel filtering. Production failure: garbage image URLs leak into records.
Verdict: Direct surface bleed is mostly fenced by field_policy.py and field_value_core.py, but the actual extraction pipeline is still misordered and incomplete. The system is paying for browser and XHR capture without consistently converting that into deterministic fields.

5. Traversal Mode Audit
Score: 5/10
Violations:

[HIGH] backend/app/services/crawl_utils.py -> resolve_traversal_mode (lines 128-175), backend/app/services/acquisition/traversal.py -> should_run_traversal (lines 39-47): only auto, paginate, scroll, and load_more are handled. single, sitemap, and crawl are not explicitly modeled; unknown values are ignored. Production failure: user traversal intent can be silently dropped.
[MEDIUM] backend/app/services/acquisition/traversal.py -> _run_paginate_traversal (lines 216-226): javascript: links are filtered, but fragment-only pagination links are not. Production failure: no-progress paginator loops waste page budget.
[MEDIUM] backend/app/services/acquisition/traversal.py -> _find_actionable_locator (lines 250-264), _card_count (lines 300-309), _wait_for_domcontentloaded (lines 386-395): traversal exceptions are swallowed or converted to empty behavior. Production failure: broken selectors degrade into silent zero-record listings instead of explicit traversal failure.
Verdict: The separation between browser escalation and traversal authorization is present, but traversal semantics are incomplete and too quiet when they fail. Silent fallthrough is still part of the design.

6. Resilience & Error Handling
Score: 4/10
Violations:

[HIGH] backend/app/services/listing_extractor.py -> _prepare_listing_dom (lines 46-53): except Exception: pass. Production failure: parser cleanup failures disappear without any signal.
[HIGH] backend/app/services/acquisition/traversal.py -> _find_actionable_locator (lines 250-264): except Exception: continue. Production failure: broken locators are silently skipped.
[HIGH] backend/app/services/acquisition/traversal.py -> _card_count (lines 300-309): except Exception: continue. Production failure: traversal confidence drops to zero with no hard failure.
[HIGH] backend/app/services/pipeline/core.py -> _mark_run_failed (lines 704-719): except SQLAlchemyError: pass. Production failure: failure-state persistence can itself fail invisibly.
[HIGH] backend/app/services/llm_provider_client.py -> _call_groq (lines 156-158), _call_anthropic (lines 183-188), _call_nvidia (lines 225-227), with call_provider (lines 33-52): response.json() is unguarded, while the outer handler only catches httpx.HTTPError. Production failure: malformed provider JSON escapes the structured LLM fallback path as an unhandled exception.
[HIGH] backend/app/services/crawl_fetch_runtime.py -> _http_fetch (lines 455-483), _curl_fetch_sync (lines 486-505): 4xx and 5xx are both handed downstream as ordinary fetch results with the same handling path. Production failure: retry and recovery policy cannot distinguish client errors from server instability.
[HIGH] backend/app/services/acquisition/acquirer.py -> acquire (lines 71-85): proxy exhaustion is raised based on request.proxy_list presence, even though fetch_page discards proxies. Production failure: false ProxyPoolExhausted errors hide the real direct-connect failure mode.
Verdict: The code still uses broad catches as a control-flow shortcut. Some of the nastiest failures are not handled honestly; they are either swallowed or mislabeled.

7. Dead Code & Technical Debt Hotspots
Score: 5/10
Violations:

[HIGH] backend/app/services/schema_service.py -> load_resolved_schema (lines 136-174), persist_resolved_schema (lines 177-183), resolve_schema (lines 186-205): the DB session and most inputs are discarded, and no real persistence happens. This is a hollow compatibility shell, not a service. Production failure: review/schema workflows appear persistent while reverting to static defaults.
[MEDIUM] backend/app/services/acquisition/browser_client.py -> fetch_rendered_html (lines 25-52): no active callers were found outside package re-export. backend/app/services/acquisition/acquirer.py -> scrub_network_payloads_for_storage (lines 111-125) and detect_blocked_page (lines 128-129) are in the same state. Production failure: dead wrappers create false API surface and maintenance noise.
[LOW] backend/app/services/crawl_state.py -> update_run_status (lines 31-35): lingering TODO for event publishing in core state transition logic. Production failure: intent and implementation remain diverged in a sensitive path.
[MEDIUM] backend/tests/services/test_crawl_fetch_runtime.py (lines 5-12), test_detail_extractor_priority_and_selector_self_heal.py (lines 7-11), test_pipeline_core.py (line 7), test_publish_metrics.py (line 5): tests import private functions directly. Production failure: structural refactors break tests even when behavior remains correct.
Verdict: There is real dead weight here, not just polish debt. The schema/review layer is the worst offender because it presents behavior that does not exist.

8. Acquisition Mode Audit & Site Coverage
Score: 4/10
Violations:

[CRITICAL] backend/app/services/crawl_fetch_runtime.py -> fetch_page (lines 1049-1078) and backend/app/services/acquisition/acquirer.py -> acquire (lines 71-85): proxy_list is discarded at the runtime boundary, but acquisition still reports proxy exhaustion. That violates INVARIANTS.md rule 1. Production failure: proxy-enabled runs go direct and fail dishonestly.
[HIGH] backend/app/services/adapters/registry.py -> _ADAPTER_FACTORIES, registered_adapters (lines 30-69) with backend/app/services/config/platforms.json -> Lever and Rippling entries (lines 127-145): config declares platforms that do not have registered adapters. Taleo and Dice are absent entirely. Production failure: platform detection promises coverage that the adapter layer cannot deliver.
[HIGH] backend/app/services/js_state_mapper.py -> _map_platform_job_detail_state (lines 116-132) with platforms.json Workday/Rippling entries (lines 107-145): hydrated-state coverage is incomplete for platforms already routed as job platforms. Production failure: partial records on JS-heavy job detail pages.
[HIGH] backend/app/services/config/network_payload_specs.py (lines 10-326) versus network_payload_mapper.py -> _payload_priority (lines 68-80): Workday and Lever JSON families are recognized and boosted, but not concretely mapped. Production failure: XHR ghost routes are captured and then wasted.
[MEDIUM] backend/app/services/acquisition/acquirer.py -> acquire (lines 64-66): ADP URL normalization is embedded in shared acquisition routing instead of adapter-owned planning. Production failure: acquisition behavior remains platform-heuristic driven in the wrong layer.
Verdict: Routing is curl_cffi first, httpx second, Playwright for explicit/browser-required/traversal cases; that part is understandable. Coverage is the problem: several platforms are half-declared, half-implemented, and the proxy control path is outright broken.

Final Summary
Overall Score: 3/10

Critical Path:

proxy_list is dropped in crawl_fetch_runtime.fetch_page, so every proxy-configured run can silently go direct and then raise a fake ProxyPoolExhausted.
detail_extractor applies js_state before JSON-LD/microdata/Open Graph, so weaker hydrated state can overwrite stronger structured truth on detail pages.
selector_self_heal saves synthesized selectors before proving the rerun improved extraction, so one bad LLM guess can poison domain memory for future runs.
Workday/Lever family payloads are recognized but not concretely mapped, so the browser capture path still leaks into DOM/LLM fallback and returns partial records.
Block detection still treats provider markers as sufficient evidence in is_blocked_html, which can misclassify legitimate pages and trigger wrong acquisition escalation.
Genuine Strengths:

backend/app/schemas/crawl.py -> serialize_crawl_record_response (lines 373-400) aggressively strips private keys, empty values, and legacy manifest noise from the user-facing record contract.
backend/app/services/domain_memory_service.py -> load_domain_memory, save_domain_memory, load_domain_selector_rules (lines 9-54, 122-148) correctly partition selector memory by normalized (domain, surface) and merge generic rules additively.
backend/app/services/acquisition/browser_identity.py -> create_browser_identity, build_playwright_context_options (lines 37-76) and backend/app/services/crawl_fetch_runtime.py -> SharedBrowserRuntime.page (lines 146-171) show that browser identity generation is coherent and actually applied to Playwright contexts.
backend/app/services/crawl_utils.py -> resolve_traversal_mode (lines 128-175), backend/app/services/acquisition/traversal.py -> should_run_traversal (lines 39-47), and backend/app/services/crawl_fetch_runtime.py -> fetch_page (lines 1053-1058) preserve the important invariant that browser escalation and traversal activation are separate decisions.
Top 5 Architectural Recommendations

Remove backend/app/services/crawl_engine.py as an acquisition facade and point acquisition/acquirer.py, http_client.py, browser_client.py, and browser_pool.py directly at acquisition-owned runtime modules. Current structure mixes extraction and transport namespaces for no gain. Target:
# acquisition/__init__.py
from .runtime import fetch_page, is_blocked_html
from .browser_runtime import browser_runtime_snapshot, shutdown_browser_runtime
This deletes a wrapper layer and several cross-layer imports. Outcome: DIP violations disappear and dimensions 1 and 8 improve.

Thread one normalized acquisition plan end-to-end and stop redefining runtime defaults. The broken path is AcquisitionRequest -> pipeline/types.py -> crawl_settings.py -> fetch_page, where proxy_list and sleep_ms are lost and defaults are duplicated. Target:
plan = settings_view.acquisition_plan()
result = await fetch_page(url, plan=plan)
This removes repeated default fields from multiple files and eliminates the fake-proxy bug class. Outcome: dimensions 2, 6, and 8 improve.

Replace the hand-written extraction stage sequence in detail_extractor.build_detail_record and listing_extractor.extract_listing_records with one ordered stage table that matches the documented hierarchy. Current structure repeats collect -> materialize -> append tier blocks and already got the order wrong. Target:
for stage in [adapter, network, structured, hydrated, dom]:
    collect(stage)
    record = materialize(...)
    if authoritative(record): break
This deletes repeated glue code and makes source order impossible to drift. Outcome: structured-truth ordering bugs disappear and dimensions 1 and 4 improve.

Change selector_self_heal.apply_selector_self_heal so domain memory is only persisted after rerun quality improves targeted fields. Current structure saves first and evaluates later. Target:
candidate_rules = validate_xpath(...)
rerun = extract_records(..., selector_rules=current_rules + candidate_rules)
if improved(rerun, missing_fields):
    await save_domain_memory(...)
This removes speculative writes and stops selector poisoning. Outcome: dimensions 4 and 6 improve.

Collapse adapter networking onto a shared client and either implement real pacing or delete the pacing abstraction entirely. acquisition/http_client.py creates per-request clients while acquisition/pacing.py is empty. Target:
client = await get_shared_adapter_client(proxy)
await maybe_wait_for_host_slot(host)
response = await client.request(...)
This cuts duplicate client setup code and removes a fake abstraction. Outcome: connection churn and fake-throttling bugs disappear; dimension 3 improves materially.

Extraction Enhancement Recommendations

JS-Truth / Hydrated State Interception
Competitors: Crawlee, Diffbot
Gap addressed: Workday and Rippling job-detail hydrated state is detected but not actually mapped in js_state_mapper.py and platforms.json.
Slot: hydrated-state source
family = detect_platform_family(page_url)
for state_key, payload in js_state_objects.items():
    spec = HYDRATED_STATE_SPECS.get((family, "job_detail", state_key))
    if not spec:
        continue
    root = first_match(payload, spec.root_paths)
    mapped = {field: first_match(root, paths) for field, paths in spec.field_paths.items()}
    mapped = normalize_non_empty(mapped)
    if mapped:
        return mapped
return {}
Expected yield: Workday/Rippling/Next.js-style job detail pages recover title, location, apply URL, posted date, and description before DOM parsing. Estimated LLM fallback reduction: 20-40% on JS-heavy job-detail surfaces.

XHR Ghost-Routing / Playwright Request Interception
Competitors: Apify, Zyte / Scrapy-Playwright
Gap addressed: _browser_fetch already captures network JSON, but network_payload_specs.py does not cover Workday, Lever, or Taleo-style payloads.
Slot: XHR/JSON source
captured = []
page.on("response", lambda resp: captured.append(resp))
await page.goto(url)

for resp in captured:
    if not is_candidate_json(resp.url):
        continue
    body = await safe_json(resp)
    spec = PLATFORM_PAYLOAD_SPECS.get(detect_family(resp.url, body))
    mapped = map_payload(body, spec)
    if mapped:
        add_candidates(mapped, source="network_payload")
        if authoritative_candidate_set():
            break
Expected yield: Workday, Lever, Taleo, and commerce SPAs recover deterministic detail fields from API payloads instead of post-render DOM guesses. Estimated LLM fallback reduction: 10-25%, with better title/company/location/price/availability completeness.

Accessibility Tree Expansion (AOM)
Competitors: Playwright best-practice flows, Crawlee browser heuristics
Gap addressed: expand_all_interactive_elements is keyword-driven and misses hidden specs/requirements behind accessible tabs and accordions.
Slot: pre-DOM-parse browser expansion
snapshot = await page.accessibility.snapshot()
for node in walk(snapshot):
    if node.role in {"button", "tab", "link"} and looks_expandable(node.name):
        locator = page.get_by_role(node.role, name=re.compile(node.name, re.I))
        if await locator.count():
            await locator.first.click()
await page.wait_for_timeout(250)
html = await page.content()
Expected yield: better recovery of collapsed ecommerce specs, materials, care sections, and job requirements/benefits blocks. Estimated field-completeness lift: 5-15% on interactive detail pages, with a smaller but real drop in LLM cleanup usage.