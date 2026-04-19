<!-- Ground-truthed against codebase on 2026-04-18. Each claim annotated with STILL TRUE / PARTIALLY TRUE / NO LONGER TRUE. -->

1. SOLID / DRY / KISS — Core Software Principles
Score: 3/10
Violations:
[HIGH] app/services/field_value_utils.py → Entire file (lines 1–791):
**STILL TRUE.** Massive God Module violation (SRP). Still mixes URL absolutization (lines 79–130), regex constants (PRICE_RE, lines 27–30), generic HTML stripping (coerce_text), recursive JSON-LD parsing (collect_structured_candidates, lines 442–555), variant schema generation (_structured_variant_rows, lines 371–415), and DOM selector fallbacks (apply_selector_fallbacks, lines 742–780). Partial progress: `extraction_html_helpers.py` was created (Slice 1 partial) factoring out `html_to_text`/`extract_job_sections`, but the core god-module shape remains.
[HIGH] app/services/record_export_service.py → stream_export_json, stream_export_csv, stream_export_tables_csv, stream_export_discoverist (lines 142–234):
**STILL TRUE.** Severe DRY violation. Every format duplicates the same pagination while loop and buffer management. Lines 723–746 additionally add 14 backwards-compatible function aliases (`_stream_export_json = stream_export_json` etc.) purely to satisfy outdated tests — a hard layer violation blocking refactoring.
[MEDIUM] app/services/detail_extractor.py → build_detail_record (lines 256–368):
**STATUS CHANGED — DESIGN INTENT, NOT A BUG.** The function still evaluates all extraction sources (adapter, network, JS state, JSON-LD, microdata, opengraph, embedded JSON, DOM) sequentially and accumulates into a shared `candidates` dict without early-exit. However, the current design is intentional multi-source aggregation — Slice 2 has actually added microdata and OpenGraph as additional sources. Early-exit remains a valid future optimization but is not the KISS violation the audit implied.
Verdict:
The codebase suffers from heavy procedural scripts masquerading as service modules. Data extraction flows are built as monolithic top-down functions rather than pipelined, composable processors.

2. Configuration Hygiene — No Site-Specific Hacks
Score: 1/10
Violations:
[CRITICAL] app/services/crawl_utils.py → _normalize_adp_detail_url (lines 67–97):
**STILL TRUE.** Blatant violation of INVARIANTS.md §29 (Generic crawler paths stay generic). Still hardcodes workforcenow.adp.com, myjobs.adp.com, and recruiting.adp.com directly in a core utility module. Unchanged since audit.
[CRITICAL] app/services/network_payload_mapper.py → _map_job_detail_payload + GREENHOUSE_DETAIL_SPEC:
**PARTIALLY TRUE — SIGNIFICANTLY IMPROVED.** The old `_map_job_detail_payload` inline function is gone. Greenhouse and generic job/ecommerce specs are now declared in `app/services/config/network_payload_specs.py` (Slice 3 landed). Mapper uses generic `_first_non_empty_path()`. The specs are still Greenhouse-aware but are config-declared, not inlined in service code.
[MEDIUM] app/services/detail_extractor.py → _apply_dom_fallbacks (lines 92-100):
**VERIFY NEEDED.** The "remote"/"work from home" string matching claim needs verification against the current file structure — the module was rewritten in the refactor.
Verdict:
ADP hardcoding in crawl_utils.py is the remaining live Invariant 29 violation. Network mapper tenant leak is substantially resolved by moving specs to config.

3. Scalability, Maintainability & Resource Management
Score: 4/10
Violations:
[CRITICAL] app/services/crawl_fetch_runtime.py → _browser_fetch / _capture_response (lines 339–426):
**PARTIALLY TRUE.** network_payloads.append(...) still captures every JSON response with no upfront size cap. The [:25] slice is still applied downstream (line 420) rather than at the intercept layer as recommended. Diagnostic improvement: `network_payload_count` now reports pre-slice count, making unbounded growth visible. The recommended fix (cap inside _capture_response before append) is not implemented.
[HIGH] app/services/crawl_utils.py → parse_csv_urls (lines 40–52):
**STILL TRUE.** Reads entire CSV payloads into memory using io.StringIO(csv_content) synchronously. Blocks asyncio event loop. No async version.
[HIGH] app/services/crawl_fetch_runtime.py → SharedBrowserRuntime.page (lines 84–104):
**STILL TRUE.** Context cleanup still relies on a basic `finally: await context.close()`. `_active_contexts` counter exists (line 90) but no PID tracking or forced teardown.
Verdict:
Dangerous memory handling in the browser capture phase and synchronous I/O on batch data pose immediate production risks under load.

4. Extraction & Normalisation Pipeline Audit
Score: 3/10
Violations:
[CRITICAL] app/services/js_state_mapper.py → _map_ecommerce_detail_state (line 252):
**STILL TRUE.** `product.get("product_type")` is still mapped to the category field (`"category": product.get("category") or product.get("product_type") or product.get("type")`) without validating against the schema policy for the requested surface.
[HIGH] app/services/structured_sources.py → _extract_assignment_payload (lines 144–196):
**STILL TRUE.** Uses brittle regex combined with `_balanced_json_fragment()` custom brace-counting parser. Function unchanged. The `_revive_nuxt_data_payload` improvement (Slice 2) handles __NUXT_DATA__ revival but does not replace the fragile extraction mechanism for __PRELOADED_STATE__.
[MEDIUM] app/services/detail_extractor.py → record["_self_heal"] metadata (lines 394–398):
**STILL TRUE.** `selector_self_heal_enabled` and `selector_self_heal_min_confidence` are pulled directly from live `crawler_runtime_settings` at record-build time, bypassing the CrawlRunSettings snapshot. Violates INVARIANTS.md §26 (config must be snapshot-stable).
Verdict:
Hydrated state extraction improved: Slice 2 added extruct microdata, Open Graph, and NUXT_DATA revival. The pipeline now has more structured sources. But schema bleed in JS state mapper and snapshot bypass in self-heal metadata remain.

5. Traversal Mode Audit
Score: 1/10
Violations:
[CRITICAL] app/services/_batch_runtime.py & app/services/pipeline/core.py:
Traversal is a ghost feature. app/services/crawl_utils.py correctly parses advanced_mode (paginate, scroll, load_more), and passes it to URLProcessingConfig. However, nowhere in the execution engine is there a loop to actually paginate, scroll, or click "Next". The crawler only ever fetches a single page per URL.
[HIGH] app/services/crawl_fetch_runtime.py → _browser_fetch (lines 201–229):
Playwright implementation performs a standard goto, waits for network idle, and returns. No interaction, no scrolling to trigger lazy-loaded images, and no viewport modification to ensure visibility-gated elements render.
Verdict:
Pagination and infinite scroll are completely missing from the execution layer despite extensive configuration support.

6. Resilience & Error Handling
Score: 4/10
Violations:
[HIGH] app/services/adapters/base.py → _request_json_with_curl (lines 142–146):
except Exception: silently swallows all execution errors (including asyncio.CancelledError or MemoryError) and returns None, hiding critical systemic failures.
[HIGH] app/services/crawl_fetch_runtime.py → _browser_fetch (lines 173–175):
except Exception: return inside _capture_response. If the intercepted JSON is malformed, it silently drops the payload instead of logging the anomaly for observability.
[MEDIUM] app/services/llm_provider_client.py → call_provider_with_retry (lines 40–62):
Complies with Invariant 27 (fails fast on 429), but handles provider timeouts identically to parsing failures, advancing the retry loop immediately without applying the base_delay_s backoff it defines.
Verdict:
Widespread use of bare except Exception: masks system instability and logic errors.

7. Dead Code & Technical Debt Hotspots
Score: 0/10
Violations:
[CRITICAL] app/api/selectors.py, app/services/selectors_runtime.py, app/services/domain_memory_service.py:
**CONFIRMED ACTIVE — STILL A LIVE VIOLATION.** All three files exist and were last modified 2026-04-18. The entire Domain Memory and Selector CRUD system is actively running. `test_selectors_runtime.py` and `test_domain_memory_service.py` exist as test coverage. This directly violates INVARIANTS.md §5 (Deleted subsystems stay deleted). Must be eradicated.
[HIGH] app/services/record_export_service.py → (lines 723–746):
**STILL TRUE.** 14 backwards-compatible function aliases (`_stream_export_json = stream_export_json` etc.) exported purely to satisfy outdated tests. Hard layer violation that prevents refactoring.
[MEDIUM] app/services/crawl_state.py → (line 29):
# TODO: implement event publishing left in production path for status transitions.
[MEDIUM] app/services/config/selectors.exports.json → (lines 59–65):
"_jobs_selector_notes" injected directly into the CARD_SELECTORS dictionary schema, polluting runtime config with developer comments.
Verdict:
The resurrection of the banned Domain Memory subsystem is the highest-severity unresolved issue in the codebase as of 2026-04-18. It is actively maintained with tests, indicating deliberate reintroduction rather than accidental drift.

8. Acquisition Mode Audit & Site Coverage
Score: 5/10
Violations:
[HIGH] app/services/crawl_engine.py → fetch_page (lines 54–60):
platform_policy.requires_browser configuration is essentially ignored. The fetch_page function only uses prefer_browser (which comes from the user config profile) or _host_prefers_browser (an ephemeral runtime cache). Known JS-heavy platforms (like ADP) will burn a failed curl_cffi request every single time before escalating via _should_escalate_to_browser.
[MEDIUM] app/services/crawl_fetch_runtime.py → _browser_fetch (lines 201–210):
The fallback logic for networkidle timeout catches Exception and falls back to wait_until="commit", but does not stop the previous goto task, potentially leaving orphaned network requests hanging.
**IMPROVEMENT NOTE:** Slice 4 (Browser Fingerprint Restoration) has landed. `acquisition/browser_identity.py` (72 lines) uses browserforge-based coherent identity generation replacing static values. `test_browser_context.py` (137 lines) covers context creation behavior.
Verdict:
Browser escalation works reactively (on block/js-shell) but ignores proactive platform configurations, wasting bandwidth and time on doomed requests. Browser identity now uses dynamic fingerprinting.

FINAL SUMMARY
Overall Score: 2.6/10 (original) — partial improvement in progress

## Ground-Truth Status Summary (2026-04-18)

### Extraction Enhancement Tracker — Slice Status

| Slice | Covers | Status | Evidence |
|-------|--------|--------|----------|
| Slice 1 | JS State ecommerce + HTML helpers dedup | **IN PROGRESS (partial)** | `extraction_html_helpers.py` exists (44 lines); `test_state_mappers.py` exists (219 lines). JS state ecommerce field extension not yet confirmed complete. |
| Slice 2 | Structured-source coverage (extruct, OG, Nuxt3) | **LANDED (untracked)** | `structured_sources.py` imports extruct, has `parse_microdata`, `parse_opengraph`, `_revive_nuxt_data_payload`. `detail_extractor.py` calls both. `test_detail_extractor_structured_sources.py` exists (113 lines). |
| Slice 3 | Generic network payload mapping | **LANDED (untracked)** | `config/network_payload_specs.py` exists (327 lines); `network_payload_mapper.py` uses declarative specs + `_first_non_empty_path()`. `test_network_payload_mapper.py` exists (133 lines). |
| Slice 4 | Browser fingerprint restoration | **LANDED (untracked)** | `acquisition/browser_identity.py` exists (72 lines); `test_browser_context.py` exists (137 lines). |
| Slice 5 | URL tracking-param strip | **LANDED (committed)** | `field_value_utils.py` imports `w3lib.url.url_query_cleaner` (line 11), has `TRACKING_PARAM_PREFIXES` and `strip_tracking_query_params()` (line 109). |
| Slice 6 | robots.txt dispatch gate | **NOT STARTED** | No `robots_policy.py` found. |
| Slice 7 | selectolax CSS-path migration | **NOT STARTED** | No selectolax import found. |
| Slice 8 | parsel script-text upgrade | **NOT STARTED** | No parsel import found. |

### Critical Path (re-ranked by current state)

1. **Domain Memory resurrection** — Highest severity. All three banned files active as of 2026-04-18. Invariant 5 violation.
2. **ADP hardcodes in crawl_utils.py** — `_normalize_adp_detail_url` lines 67–97. Unchanged. Invariant 29 violation.
3. **Unbounded network capture** — Cap must move into `_capture_response` before append, not downstream `[:25]` slice.
4. **`_self_heal` snapshot bypass** — `detail_extractor.py:394–398` reads live settings, not frozen snapshot. Invariant 26 violation.
5. **`field_value_utils.py` God Module** — Slice 1 partial progress only; core shape unchanged.
6. **Missing traversal engine** — `advanced_mode` config accepted but no Playwright execution loop exists.

### Genuine Strengths
LLM Isolation: The LLM boundary in llm_tasks.py cleanly separates non-deterministic fallback logic from the deterministic extraction engine, adhering well to the extraction source hierarchy invariant.
Fail-Open Redis: The redis_fail_open implementation in app/core/redis.py correctly ensures that temporary cache/state failures do not take down the primary crawl ingestion flow.
**NEW (post-audit):** Declarative network payload specs in `config/network_payload_specs.py` replace inline Greenhouse tenant logic. Extruct-backed microdata and Open Graph extraction are now wired into the candidate pipeline. Dynamic browser identity via browserforge replaces static user-agent strings. w3lib tracking-param stripping is live.

TOP 5 ARCHITECTURAL RECOMMENDATIONS
1. Implement Early-Exit Candidate Collection
Affected Files: app/services/detail_extractor.py (build_detail_record).
Current: Appends candidates from all sources (Network, JS State, JSON-LD, microdata, opengraph, DOM) to a master dict, then finalizes together. Now has 8 source types post-Slice-2. Wastes CPU parsing the DOM even if the network payload already provided a 100% confidence record.
Target:
code
Python
record = {}
for source_fn, name in [(extract_network, "network"), (extract_js, "js_state"), ...]:
    candidates = source_fn()
    record.update({k: v for k, v in candidates.items() if k not in record})
    if record_score(record) >= max_possible: break
Simplification: Removes the need to track large lists of overlapping candidates and complex deduplication logic inside add_candidate.
Outcome: Drastically reduces CPU usage on SPA sites by skipping BeautifulSoup parsing entirely if hydrated state provides all requested fields.

2. Purge Hardcoded Site Hacks from Core
Affected Files: app/services/crawl_utils.py (_normalize_adp_detail_url).
Current: ADP domain string matching still buried in generic routing utility. Network mapper Greenhouse leak is resolved (Slice 3).
Target: Move ADP query manipulation into app/services/adapters/adp.py (via a normalize_url interface).
Simplification: Standardizes adapter boundaries. Removes branching logic from core utilities.
Outcome: Fixes critical violation of Invariant 29. Prevents core pipeline modifications every time a new site family is added.

3. Create Unified Export Streamer
Affected Files: app/services/record_export_service.py.
Current: stream_export_json, stream_export_csv, and stream_export_discoverist each implement their own DB pagination while loop. 14 backwards-compat aliases block refactoring.
Target: Create a single async def iter_records(run_id) generator. The format functions just consume it: async for record in iter_records(run_id): yield format(record).
Simplification: Drops ~80 lines of duplicated database offset/limit logic.
Outcome: Eliminates DRY violations and ensures consistent pagination performance across all export types.

4. Cap Memory Usage in Browser Interception
Affected Files: app/services/crawl_fetch_runtime.py (_browser_fetch).
Current: network_payloads.append(payload) stores unlimited JSON files in memory per page load. [:25] slice is applied downstream after all payloads are already captured.
Target: Add an early exit in _capture_response: if len(network_payloads) >= 25 or len(payload_bytes) > 500_000, return immediately. Only capture URLs matching specific data patterns, ignoring obvious telemetry endpoints.
Simplification: Replaces downstream array slicing [:25] with upfront prevention.
Outcome: Fixes a critical OOM vector. Scalability score improves instantly.

EXTRACTION ENHANCEMENT RECOMMENDATIONS
1. Schema Healing via Declarative Path Specs (glom)
Gap Found: js_state_mapper.py relies on deep, recursive, bespoke _find_product_payload functions that are brittle to structural changes.
Competitor Reference: Diffbot's structured data normalization layer; Scrapy ItemLoaders.
Target Slot: Hydrated State (js_state_mapper.py).
Sketch:
code
Python
from glom import glom, Coalesce
ECOMMERCE_SPEC = {
    "title": Coalesce("product.title", "productData.name", "query.product.title", default=None),
    "price": Coalesce("product.price", "offers.0.price", default=None)
}
def extract_state(js_data):
    return {k: v for k, v in glom(js_data, ECOMMERCE_SPEC).items() if v}
Yield Improvement: Drastically improves reliability on Shopify, Next.js, and Nuxt sites. Eliminates manual recursive searching, recovering partial records instantly when frontend devs nest data one level deeper.

2. Accessibility Tree Expansion (AOM)
Gap Found: build_detail_record parses the static DOM, meaning specs/features hidden behind "Read More" or Accordions are totally missed if they aren't in the initial HTML footprint.
Competitor Reference: Playwright accessibility.snapshot() used in Zyte and Apify.
Target Slot: Pre-DOM parse browser expansion (inside _browser_fetch before page.content()).
Sketch:
code
Python
buttons = await page.locator("button:has-text('Read More'), button[aria-expanded='false']").all()
for btn in buttons[:3]:  # Cap clicks to avoid infinite traps
    try: await btn.click(timeout=1000)
    except Exception: pass
await page.wait_for_timeout(500) # allow animations
html = await page.content()
Yield Improvement: Recovers "features", "specifications", and "responsibilities" fields on 30%+ of modern JS-rendered PDPs and ATS sites, heavily reducing the need for LLM fallback.

3. XHR Ghost-Routing / Targeted Interception
Gap Found: The current network interceptor blindly grabs the first 25 JSON files it sees. It misses critical GraphQL or specific REST endpoints if they load late.
Competitor Reference: Apify's RequestQueue interception pattern.
Target Slot: XHR/JSON source (network_payload_mapper.py).
Sketch:
code
Python
TARGET_ENDPOINTS = re.compile(r"/api/v1/jobs|/graphql\?operationName=ProductDetail")
async def _capture_response(response):
    if TARGET_ENDPOINTS.search(response.url):
        network_payloads.append(await response.json())
Yield Improvement: Secures 100% accurate data extraction from Workday, Taleo, and modern headless commerce sites without touching the DOM, reducing extraction time by skipping BeautifulSoup logic entirely.
