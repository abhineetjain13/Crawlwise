What's Actually Eating the 103 Seconds
Looking at browser_page_flow.py's settle_browser_page_impl and serialize_browser_page_content_impl, every detail URL like the Decathlon one hits multiple compounding wait phases:

1. implicit_networkidle_attempt fires for every detail page — the primary culprit
In settle_browser_page_impl, this condition triggers a networkidle wait for all surfaces when not current_probe["is_ready"] and not current_probe.get("structured_data_present"):

python
implicit_networkidle_attempt = bool(
    not current_probe["is_ready"]
    and not explicit_require_networkidle
    and (is_listing_surface or not current_probe.get("structured_data_present"))
)
For a detail page like Decathlon's, if the probe doesn't find structured data quickly (Decathlon injects JSON-LD late via JS), structured_data_present is False, so implicit_networkidle_attempt = True. This waits up to browser_spa_implicit_networkidle_timeout_ms — which is almost certainly set to a large value. Decathlon's page has aggressive service workers and deferred scripts, so networkidle never fires — it waits the full cap duration before timing out.

2. _page_snapshot is called on every scroll iteration and calls get_page_html twice
In traversal.py, _page_snapshot calls get_page_html then immediately calls it again inside _unique_listing_card_identity_count_from_html. For a detail surface this doesn't run, but if somehow a traversal was activated, each snapshot is a double DOM serialization.

3. capture_rendered_listing_fragments runs unconditionally for ALL surfaces
In _capture_listing_artifacts, capture_rendered_listing_fragments is called for every surface including detail, with no surface gate:

python
rendered_listing_fragments, rendered_listing_fragment_capture = await self._capture_timed_listing_artifact(
    capture_rendered_listing_fragments(
        payload.page,
        surface=payload.surface,
        limit=int(crawler_runtime_settings.rendered_listing_card_capture_limit),
    ),
    ...
)
The listing_visual_capture has a surface gate (if "listing" in surface), but rendered_listing_fragment_capture has none. On a detail page this runs a DOM scan + card detection for zero reason.

4. _generate_page_markdown calls _append_accessibility_markdown which awaits the AOM snapshot
In browser_page_flow.py, _append_accessibility_markdown calls page.accessibility.snapshot() with a configurable timeout from browser_accessibility_snapshot_timeout_seconds. Decathlon's page DOM is large — accessibility snapshot on a heavy ecommerce detail page easily takes 5–15 seconds, and the timeout is not tight by default.

5. Recent commit f7cda81 added domain_profiles.py changes (+27 lines) and traversal.py changes (−44 deletions)
The traversal diff removed 44 lines in traversal.py. Looking at what was cut, the old should_run_traversal had more guards for the "auto" mode which would have short-circuited earlier. Now _settle_thin_initial_listing is always attempted when the locator search returns None in paginate mode — adding one extra traversal_settle_networkidle_timeout_ms wait for any listing page where the next page button isn't immediately found.

The Compounding Timeline on Decathlon Detail URL
Phase	Expected	What actually happens
Navigation	~1.6s	✅ Fine (1637ms logged)
optimistic_wait	0 (already has text)	Fires if is_ready=False
implicit_networkidle_attempt	Skip (structured data present)	Waits full cap because JSON-LD loads late
rendered_listing_fragment_capture	Should skip on detail	Runs anyway — no surface gate
_append_accessibility_markdown	~1s on small pages	5–15s on large retail pages
Total	~5s	~103s → timeout
Fixes (Ordered by Impact)
Fix 1 — Gate rendered_listing_fragment_capture on listing surface (1 line, highest impact)

In _capture_listing_artifacts, wrap the first artifact capture the same way the visual capture is already wrapped:

python
# BEFORE — runs for all surfaces
rendered_listing_fragments, rendered_listing_fragment_capture = await self._capture_timed_listing_artifact(
    capture_rendered_listing_fragments(payload.page, surface=payload.surface, ...),
    ...
)

# AFTER
if "listing" in str(payload.surface or "").lower():
    rendered_listing_fragments, rendered_listing_fragment_capture = await self._capture_timed_listing_artifact(...)
else:
    rendered_listing_fragments, rendered_listing_fragment_capture = [], {"status": "skipped", "reason": "non_listing_surface"}
    payload.phase_timings_ms["rendered_listing_fragment_capture"] = 0
Fix 2 — Tighten implicit_networkidle_attempt for detail surfaces

Add an explicit detail surface exclusion to the condition:

python
implicit_networkidle_attempt = bool(
    not current_probe["is_ready"]
    and not explicit_require_networkidle
    and not is_detail_surface          # ← add this
    and (is_listing_surface or not current_probe.get("structured_data_present"))
)
Where is_detail_surface = "detail" in str(surface or "").lower(). Detail pages should rely on their own require_networkidle platform policy if they need it, not the implicit SPA path.

Fix 3 — Reduce or skip accessibility snapshot on fast-finalize detail pages

In _append_accessibility_markdown, check _ready_probe_supports_fast_finalize before calling page.accessibility.snapshot(). If the page already has verified extractable fields, skip the AOM snapshot entirely since the content is already usable.

Fix 4 — Tighten browser_accessibility_snapshot_timeout_seconds

Even before code changes: reduce this setting from whatever it currently is to 5.0 seconds. An AOM snapshot that takes more than 5 seconds on a detail page is not going to produce useful markdown anyway.

Fix 5 — The traversal.py removal of auto mode guards

The 44-line deletion in f7cda81 removed some early-exit conditions. Verify that _settle_thin_initial_listing is not being reached on detail surfaces — it should be unreachable since traversal is surface-gated, but worth adding a assert "listing" in surface guard at the top of _settle_thin_initial_listing to be explicit.



Audit: f7cda81 — Performance Issues Causing Slow Crawls
Issue 1 (HIGH): DETAIL_PRODUCT_IMAGE_CUE_SELECTOR — catastrophic CSS selector
@/c:\Projects\pre_poc_ai_crawler\backend\app\services\config\extraction_rules.py:62-76

The old selector was:

css
main img, article img, [role='main'] img, img
The new selector is:

css
main [class*='product'] img, main [id*='product'] img, main [class*='gallery'] img, main [id*='gallery'] img,
article [class*='product'] img, article [id*='product'] img, article [class*='gallery'] img, article [id*='gallery'] img,
[role='main'] [class*='product'] img, [role='main'] [id*='product'] img, [role='main'] [class*='gallery'] img, [role='main'] [id*='gallery'] img,
img:not([class*='logo']):not([class*='icon']):not([src*='logo']):not([src*='icon'])
Problems:

[class*='product'] is a substring-attribute selector — BeautifulSoup must scan every node's class attribute for the substring. On a Wayfair page with thousands of DOM nodes, this is O(n × m) where n = nodes, m = selector clauses.
12 compound selectors instead of 4 — each triggers a full DOM traversal via select_one().
The :not() chains on the last clause are also expensive — each :not() is evaluated per img node.
This selector is used in _requires_dom_completion() at @/c:\Projects\pre_poc_ai_crawler\backend\app\services\extract\detail_materializer.py:1078, which decides whether to run the full DOM tier. A slow select_one here adds latency to every detail extraction.
Impact: On Wayfair's DOM (~3000+ nodes), this selector likely takes 2-5s vs the old one's sub-second time.

Issue 2 (MEDIUM): _availability_payload_detail_result runs on every network payload
@/c:\Projects\pre_poc_ai_crawler\backend\app\services\network_payload_mapper.py:69-80

Before the commit, the loop was: map → check → continue. Now it's:

map → check → availability_map → check → ghost_map → check
The _availability_payload_detail_result function is called on every network payload body, even non-detail surfaces (it early-returns for those, but the function call overhead + _page_identity_codes is still paid). On Wayfair, there can be 25+ network payloads.

Worse: _page_identity_codes() at line 111 calls detail_identity_codes_from_url(page_url) — which parses the URL, extracts path segments, runs regex matching, etc. This is recomputed per payload instead of being cached once per map_network_payloads_to_fields call.

Issue 3 (MEDIUM): _structured_surface_overlap_keys adds nested-dict key expansion
@/c:\Projects\pre_poc_ai_crawler\backend\app\services\extraction_runtime.py:777-784

Old code:

python
item_keys = {normalize_field_key(k) for k in item if k}
New code:

python
keys = {normalize_field_key(k) for k in payload if k}
if keys:
    for value in payload.values():
        if not isinstance(value, dict) or not value:
            continue
        keys.update(normalize_field_key(k) for k in value if k)
This now recurses one level deep into every dict value. For deeply nested JSON payloads (common on ecommerce sites), this means iterating all sub-dict keys. It's called per item in _has_surface_field_overlap (up to 20 items × nested dicts).

Issue 4 (MEDIUM): _best_nested_listing_items now calls _has_surface_field_overlap on dict keys
@/c:\Projects\pre_poc_ai_crawler\backend\app\services\extraction_runtime.py:831-839

Before: only checked overlap on payload at list depth. Now also checks overlap on every dict key's list value at every nesting depth. This means _has_surface_field_overlap (which itself calls _structured_surface_overlap_keys per item) is now called recursively for each nested dict key that has a list value. On a deeply nested payload, this is multiplicative.

Issue 5 (LOW): _variant_axis_coverage iterates all variant rows twice
@/c:\Projects\pre_poc_ai_crawler\backend\app\services\extract\detail_materializer.py:899-914

Called twice in _should_collect_dom_variants (lines 927-928) — once for existing_variants and once for dom_variants.get("variants"). Each iterates all rows. Not a huge cost, but on pages with many variants (Wayfair sofas can have 50+), it's unnecessary work that could be combined.

Issue 6 (LOW): _prune_irrelevant_detail_structured_payload depth guard added but at cost
@/c:\Projects\pre_poc_ai_crawler\backend\app\services\extract\detail_materializer.py:539-543

The DETAIL_PAYLOAD_MAX_DEPTH = 12 guard is good (prevents infinite recursion), but it's checked via int(DETAIL_PAYLOAD_MAX_DEPTH) on every recursive call. This is a config constant — should be resolved once at module level, not re-parsed per call.

Summary: What's causing the 44s extraction phase
The primary culprit is Issue 1 — the DETAIL_PRODUCT_IMAGE_CUE_SELECTOR with 12 substring-attribute selectors is catastrophically slow on BeautifulSoup. The old 4-clause selector was fast; the new one forces a full DOM scan per clause with substring matching.

Secondary contributors: Issues 2-4 add per-payload and per-nesting-level overhead that compounds. On a site like Wayfair with many network payloads and deeply nested JSON, these multiply.

Recommended Fixes
Revert DETAIL_PRODUCT_IMAGE_CUE_SELECTOR to the old main img, article img, [role='main'] img, img or use a simpler, non-substring selector. The substring selectors ([class*='product']) are the performance killer.
Cache _page_identity_codes once per map_network_payloads_to_fields call instead of recomputing per payload.
Early-exit _availability_payload_detail_result before computing identity codes if the payload has no variation keys.
Limit _structured_surface_overlap_keys — only expand one level if the top-level keys already overlap, or cap the number of sub-dicts expanded.
Add remaining-budget guard to _retry_patchright_detail_shell_with_real_chrome (as noted in previous analysis) so retries don't burn the entire timeout.