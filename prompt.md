Project Context
CrawlerAI is a POC web crawler at c:\Projects\pre_poc_ai_crawler with a FastAPI backend (backend/) and Next.js frontend (frontend/). The architecture follows ACQUIRE → BLOCKED DETECT → DISCOVER → EXTRACT → UNIFY → PUBLISH. All tunable values MUST live in data/knowledge_base/*.json and be loaded via pipeline_config.py — never hardcode in service code. Read CLAUDE.md for full architecture invariants, docs/Requirements_Invariants.md for product requirements, and docs/PENDING_IMPROVEMENTS.md for known tech debt.

Run tests with: cd backend && $env:PYTHONPATH='.' && pytest tests -q (279 tests must pass).

Current State & What Was Already Done
LLM retry/backoff removed from llm_runtime.py — calls fail fast now (free API)
JSON-LD noise filtering added in extract/service.py — non-product blocks (Organization, WebSite) skipped, structural keys (@type, @context) filtered, nested non-product containers (review, author, breadcrumb) skipped during recursion
Intelligence tab noise reduced — candidate cap (5 per field), zero-quality filtering for dynamic fields, text pattern extraction fallback for "Label: Value" patterns
Accordion expansion added in browser_client.py — _expand_accordions() clicks aria-expanded="false" elements after page load
Smoke test sites expanded to 10 in run_extraction_smoke.py
New pipeline_tuning.json values added: max_candidates_per_field: 5, dynamic_field_name_max_tokens: 7, accordion_expand_max: 20, accordion_expand_wait_ms: 500
Tasks To Complete (in priority order)
Task 1: Wire pipeline_tuning.json values through pipeline_config.py
Status: Values exist in pipeline_tuning.json but are NOT yet exported from pipeline_config.py or consumed by service code.

Steps:

In backend/app/services/pipeline_config.py, add these exports after the "Browser runtime" section (~line 96):


# Extraction tuning
MAX_CANDIDATES_PER_FIELD: int = _TUNING.get("max_candidates_per_field", 5)
DYNAMIC_FIELD_NAME_MAX_TOKENS: int = _TUNING.get("dynamic_field_name_max_tokens", 7)
ACCORDION_EXPAND_MAX: int = _TUNING.get("accordion_expand_max", 20)
ACCORDION_EXPAND_WAIT_MS: int = _TUNING.get("accordion_expand_wait_ms", 500)
In backend/app/services/extract/service.py:

Replace hardcoded _MAX_CANDIDATES_PER_FIELD = 5 (line ~386) with import from pipeline_config.MAX_CANDIDATES_PER_FIELD
Replace hardcoded _DYNAMIC_FIELD_NAME_MAX_TOKENS = 7 (line ~96) with import from pipeline_config.DYNAMIC_FIELD_NAME_MAX_TOKENS
In backend/app/services/acquisition/browser_client.py:

The _expand_accordions() function (line ~260) currently hardcodes count >= 20 and uses await asyncio.sleep(0.5). Import ACCORDION_EXPAND_MAX and ACCORDION_EXPAND_WAIT_MS from pipeline_config and use them instead.
The accordion JS string will need the max injected as a parameter to page.evaluate().
Task 2: Remaining Magic Numbers Audit
Search ALL files under backend/app/services/ for hardcoded numeric constants, string patterns, and frozensets that should be in knowledge_base/*.json. Key files to audit:

crawl_service.py — confidence thresholds (0.78, 0.7), LLM params (max_tokens: 1200, temperature: 0.1)
llm_runtime.py — any remaining hardcoded params
extract/service.py — frozensets like _JSONLD_STRUCTURAL_KEYS, _JSONLD_NON_PRODUCT_BLOCK_TYPES, _PRODUCT_IDENTITY_FIELDS, _NESTED_NON_PRODUCT_KEYS should be in extraction_rules.json
browser_client.py — any remaining hardcoded timeouts, selectors
For each found: move value to appropriate knowledge_base/*.json file, add export in pipeline_config.py, import in consuming code. Maintain logical file organization — don't dump everything into one JSON.

Task 3: Site Memory Implementation (§3.9 from Requirements_Invariants.md)
This is the highest-value feature. Per the requirements doc:

What to store per domain (keyed by normalized domain — strip scheme, normalize www):

XPath / CSS selector mappings (field name → selector)
Regex patterns discovered during extraction
Field-to-source mappings (which source: HTML, JSON-LD, API, etc.)
LLM-accepted column configurations
Last crawl timestamp
Backend implementation:

Create a site_memory table in the database (domain as key, JSON blob for field configs, timestamps)
Create backend/app/services/site_memory_service.py with:
get_memory(domain: str) -> SiteMemory | None
save_memory(domain: str, fields: dict, selectors: dict, source_mappings: dict)
merge_memory(domain: str, new_fields: dict) — merges, never silently deletes (INV-MEM-03)
Domain normalization: https://www.example.com/a → example.com (INV-MEM-01)
After extraction completes in crawl_service.py, save discovered field→source mappings and any validated selectors to site memory
Before extraction, check site memory for the domain and pre-populate field configs
Create API routes: GET /api/site-memory/{domain}, PUT /api/site-memory/{domain}, DELETE /api/site-memory/{domain}, GET /api/site-memory (list all)
Frontend implementation:

When user enters a URL in crawl studio, check site memory for domain
If found, show banner: "Loaded X fields from Site Memory for [domain]"
Pre-populate extraction contract / additional fields from memory
After crawl completes, offer to save new fields to memory
Add a Site Memory management page (view/edit/delete per domain)
Auto-apply behavior (INV-MEM-02): Auto-load is one-time pre-population. User's manual edits after auto-load are never overwritten.

Task 4: Advanced Crawler Modes (Pagination/Scroll/Load More)
**CRITICAL**: Frontend/backend contract is broken — see Advanced Crawler Audit (lines 124-143) for details. Must fix schema mismatch before proceeding.

The code in browser_client.py already has implementations for scroll (_scroll_to_bottom), load_more (button clicking), and paginate (_collect_paginated_html). The issue is:

Pagination is incomplete — _collect_paginated_html exists but may not handle all next-page patterns. Test with real listing sites (Puma, AutoZone from smoke tests). Ensure max_pages setting is respected.
Auto mode currently only scrolls, should also try pagination if scroll yields no new content.
End-to-end wiring — verify that multi-page HTML is properly concatenated and fed through listing extraction with deduplication.
Test sites: https://in.puma.com/in/en/womens/womens-clothing/womens-clothing-t-shirts-and-tops, https://www.autozone.com/filters-and-pcv/oil-filter
Task 5: Shadow DOM Selector Support
Modern web components use Shadow DOM which standard CSS selectors can't pierce. Add support for:

In browser_client.py, after page load and accordion expansion, run a JS function that recursively opens shadow roots and flattens content into the main DOM (or extracts innerHTML from shadow roots and appends to a data attribute)
In extraction code, handle >>> or ::shadow piercing selector syntax if needed
Playwright has page.locator() which can pierce shadow DOM — leverage this for selector-based extraction
Task 6: LLM Usage Optimization
Currently LLM is config-only. When enabled:

Use site memory to skip LLM calls for fields already mapped — if site memory has a validated selector for "price", don't send it to LLM
Track which fields needed LLM cleanup vs deterministic extraction — store this in site memory
On re-crawls of same domain, only send new/unmapped fields to LLM
The existing LLM cleanup prompts are in data/knowledge_base/prompts/ — ensure they stay there, not inline in code
Task 7: UI Updates
Site Memory UI — new page under admin/settings to view/edit/delete site memory entries per domain
Additional fields — the extraction contract editor in crawl studio should show auto-populated fields from site memory with a visual indicator
Advanced crawler settings — the existing dropdown (auto/paginate/scroll/load_more) should have tooltips explaining each mode
Intelligence tab — should show only fields that are legitimate but not part of canonical/extended/enriched fields (not garbage noise)
Architecture Rules (MUST follow)
All tunable values in data/knowledge_base/*.json, loaded via pipeline_config.py
No blocking calls on async event loop — use asyncio.to_thread() for sync HTTP libs
Verdict based on core fields only, not requested fields
record.data strips empty/null values and _-prefixed keys in API responses
Listing pages with 0 records → listing_detection_failed, never detail-style fallback
Cookie reuse is policy-driven via cookie_policy.json
Run existing tests after every change: cd backend && pytest tests -q
Don't add unnecessary error handling, comments, or type annotations to unchanged code
Don't create documentation files unless asked
File Map (key files)
backend/app/services/pipeline_config.py — single source of truth for all config
backend/app/services/extract/service.py — detail page extraction (~600 lines)
backend/app/services/extract/listing_extractor.py — listing page extraction
backend/app/services/acquisition/browser_client.py — Playwright browser automation
backend/app/services/acquisition/acquirer.py — acquisition waterfall (curl→Playwright)
backend/app/services/crawl_service.py — main crawl orchestration
backend/app/services/llm_runtime.py — LLM provider dispatch
backend/app/data/knowledge_base/ — all JSON config files
backend/app/data/knowledge_base/pipeline_tuning.json — numeric thresholds
backend/app/data/knowledge_base/extraction_rules.json — field aliases, patterns, cleanup rules
frontend/components/crawl/crawl-run-screen.tsx — crawl results display
frontend/components/crawl/shared.tsx — shared crawl UI components
docs/Requirements_Invariants.md — full product requirements including Site Memory §3.9
Advanced Crawler Audit Findings (Critical)
The advanced crawler modes have a broken frontend→backend contract:

Frontend sends advanced_enabled: true/false (boolean toggle) in crawl-config-screen.tsx buildDispatch() (~line 467). There is NO UI to select "scroll" / "paginate" / "load_more" / "auto".
Backend expects advanced_mode: "scroll" | "paginate" | "load_more" | "auto" | null in crawl_service.py line 374: settings.get("advanced_mode"). Since frontend never sends it, it's always None — so advanced modes never trigger.
max_scrolls is hardcoded at 10 in acquirer.py lines 72/94 and never passed from settings. User has no control.
Multi-page HTML concatenation is broken: _collect_paginated_html() joins pages with <!-- PAGE BREAK:N:url --> markers, but extract_listing_records() parses the whole blob as one DOM tree via BeautifulSoup. No code splits by markers before extraction.
Fixes needed for Task 4 (Advanced Crawler):

Frontend: Add mode selector UI (radio/dropdown: Auto / Scroll / Load More / Paginate) when advanced toggle is on. Send advanced_mode string in settings, not just advanced_enabled boolean. Add max_scrolls slider.
Backend schema: crawl_service.py should map advanced_enabled: true → advanced_mode: "auto" as fallback when advanced_mode is missing (backward compat).
Pass max_scrolls: Wire from settings.max_scrolls through acquire() → acquire_html() → fetch_rendered_html(). Move default 10 to pipeline_tuning.json.
Fix multi-page extraction: Either (a) split combined HTML by <!-- PAGE BREAK: markers and extract each page separately with dedup, or (b) extract from the concatenated DOM but track page provenance.
Pagination selectors are hardcoded in browser_client.py lines 216-223 (6 CSS selectors) and 374-381 (6 load-more selectors). Move to new pagination_selectors.json in knowledge_base.
Key files:

frontend/components/crawl/crawl-config-screen.tsx — buildDispatch() function
backend/app/services/acquisition/browser_client.py — _apply_advanced_mode(), _collect_paginated_html(), _scroll_to_bottom(), _click_load_more()
backend/app/services/crawl_service.py — _process_single_url() line 537
backend/app/services/acquisition/acquirer.py — acquire() and acquire_html() parameter chains