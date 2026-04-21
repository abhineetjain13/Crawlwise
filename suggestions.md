Extraction/Output Failure Mode Audit — Root Causes & Code Fixes
All findings are from tracing actual code paths. No site-specific hacks — only systemic bugs and missing guards.

BUG 1: Detail title falls back to raw <h1> text without noise filtering
Severity: P0 — affects 15/45 sites (garbage titles like "1", "Products", promo banners)

Root cause: _apply_dom_fallbacks() in @/c:/Projects/pre_poc_ai_crawler/backend/app/services/detail_extractor.py:163-177 extracts the <h1> or <title> text and adds it as a dom_h1 candidate unconditionally:

python
h1 = dom_parser.css_first("h1")
page_title = dom_parser.css_first("title")
title = text_or_none(
    (h1.text(separator=" ", strip=True) if h1 else "")
    or (page_title.text(separator=" ", strip=True) if page_title else "")
)
if title:
    _add_sourced_candidate(candidates, candidate_sources, field_sources, "title", title, source="dom_h1")
The problem: no noise filtering is applied to the dom_h1 title candidate. The listing extractor has _listing_title_is_noise() which catches CTAs, promo prefixes, sort/filter UI, etc. — but the detail extractor has no equivalent guard. So <h1>Products</h1>, <h1>1</h1>, <h1>Save 20% With Code SPRING</h1> all pass through as valid title candidates.

The _promote_detail_title() function at line 804 only triggers when the title matches TITLE_PROMOTION_PREFIXES ("buy ") or TITLE_PROMOTION_SEPARATOR ("|") or TITLE_PROMOTION_SUBSTRINGS ("apparel for") — far too narrow to catch the garbage we're seeing.

Fix: Add a _detail_title_is_noise() guard in _apply_dom_fallbacks() that rejects dom_h1 candidates matching known noise patterns. Reuse the listing extractor's noise lists:

python
# In detail_extractor.py, inside _apply_dom_fallbacks, after line 168:
if title and not _detail_title_is_noise(title):
    _add_sourced_candidate(...)
Where _detail_title_is_noise checks:

Title is a single digit or very short (< 4 chars)
Title matches LISTING_MERCHANDISING_TITLE_PREFIXES (promo codes, sale prefixes)
Title matches _VISUAL_CTA_TITLES ("add to cart", "apply", etc.)
Title matches LISTING_NAVIGATION_TITLE_HINTS ("home", "next", etc.)
Title matches LISTING_WEAK_TITLES ("sale", "new", "featured")
BUG 2: finalize_candidate_value for title takes first candidate regardless of quality
Severity: P1 — amplifies Bug 1

Root cause: @/c:/Projects/pre_poc_ai_crawler/backend/app/services/field_value_candidates.py:353 — for scalar fields (including title), finalize_candidate_value simply returns values[0]:

python
return values[0]
For the detail extractor, the winning source is selected first via _ordered_candidates_for_field + _winning_candidates_for_field, so this is partially mitigated by source ranking. But for the listing extractor, _listing_record_from_card at line 900 pre-seeds candidates["title"] = [title] with the card title, and then finalize_candidate_value("title", candidates["title"]) returns that first value — even if it's garbage like "1" or "Products".

The listing extractor does have _listing_title_is_noise() at line 881, but the minimum length check is len(title) < 4 — single digits like "1" are 1 char, so they should be caught. However, "Products" (8 chars) and "Save 20% With Code SPRING" (24 chars) pass the length check and aren't in the noise lists.

Fix: Add promo-code and generic-heading patterns to LISTING_MERCHANDISING_TITLE_PREFIXES and LISTING_WEAK_TITLES in extraction_rules.exports.json:

Add "save " and "extra " and "code " to LISTING_MERCHANDISING_TITLE_PREFIXES
Add "products", "purchases", "results", "items" to LISTING_WEAK_TITLES
BUG 3: Detail <h1> is ranked ABOVE structured sources for title
Severity: P1 — structured data (JSON-LD name) is more reliable than DOM <h1>, but DOM wins

Root cause: @/c:/Projects/pre_poc_ai_crawler/backend/app/services/detail_extractor.py:143-149 — _field_source_rank for ecommerce_detail:

python
if field_name == "title" and source in {"js_state", "dom_h1"}:
    return {"js_state": 2, "dom_h1": 3}[str(source)]
This gives js_state rank 2 and dom_h1 rank 3. But json_ld gets rank 100 + 2 = 102 and opengraph gets 100 + 4 = 104. So the priority order for title is:

adapter (100+0=100) — rarely present
js_state (2) — opt-in, rarely present
dom_h1 (3) — always present, often garbage
json_ld (102) — reliable but loses to dom_h1
opengraph (104)
So dom_h1 beats json_ld and opengraph for the title field on ecommerce_detail. This is backwards — JSON-LD name is almost always the correct product name, while <h1> is frequently a promo banner or section heading.

Fix: Change _field_source_rank to rank structured sources above dom_h1 for title:

python
def _field_source_rank(surface, field_name, source):
    if surface == "ecommerce_detail" and field_name == "title":
        ranking = {
            "adapter": 0, "network_payload": 1, "json_ld": 2,
            "microdata": 3, "opengraph": 4, "js_state": 5,
            "dom_h1": 10, "dom_selector": 11, "dom_text": 12,
        }
        return ranking.get(source, 20)
    ...
BUG 4: infer_surface misses common patterns — defaults to ecommerce_listing
Severity: P1 — 4 sites misclassified, causing wrong extractor path

Root cause: @/c:/Projects/pre_poc_ai_crawler/backend/harness_support.py:23-60 — the hint lists are incomplete:

_DETAIL_HINTS (line 23) doesn't include /products/ (singular with trailing slash) — only /product/. So ifixit.com/products/iphone-14-battery is classified as ecommerce_listing instead of ecommerce_detail.
_JOB_LISTING_HINTS (line 25) doesn't include /search/results or /search? — so USAJOBS /search/results/ falls through to ecommerce_listing.
Domain-level job detection (lines 43-51) only checks host.endswith(".jobs"), host.endswith("startup.jobs"), and host.endswith("usajobs.gov"). It doesn't check for indeed.com, linkedin.com/jobs, glassdoor.com, etc. — these rely on detect_platform_family which may not cover all cases.
XML sitemap URLs like /sitemap-products.xml have no content-type awareness — they're classified as ecommerce_listing and fed through the HTML extractor, causing 90s timeouts.
Fix:

Add "/products/" to _DETAIL_HINTS
Add "/search/results" and "/search?" to _JOB_LISTING_HINTS
Add an early return in infer_surface for URLs ending in .xml, .json, .rss → return a new surface like "sitemap" or short-circuit with a clear signal
BUG 5: Listing card detection requires <a href> — fails on non-commerce card patterns
Severity: P2 — causes listing_detection_failed on quote sites, table data, auction cards

Root cause: @/c:/Projects/pre_poc_ai_crawler/backend/app/services/listing_extractor.py:599-600 — _listing_fragment_score returns -100 if a fragment has zero links:

python
link_count = len(links)
if link_count == 0:
    return -100
And _listing_record_from_card at line 869-870 returns None if _select_primary_anchor finds no anchor:

python
primary_anchor = _select_primary_anchor(card, page_url, surface=surface)
if primary_anchor is None:
    return None
This means any card-like structure that doesn't wrap its content in <a href> is invisible to the listing extractor. Quotes on quotes.toscrape.com are in <div class="quote"> containers with no anchor — they're scored -100 and discarded.

Fix: For non-commerce surfaces (or when no anchors are found), allow card detection based on structural repetition alone. If N sibling elements share the same CSS class and each contains substantial text (>50 chars), treat them as listing cards even without anchors. Add a _repetition_based_card_fallback that fires when _listing_card_html_fragments returns empty.

BUG 6: _card_title_score doesn't penalize pure-numeric text
Severity: P2 — titles like "1" pass through

Root cause: @/c:/Projects/pre_poc_ai_crawler/backend/app/services/listing_extractor.py:736-739:

python
text_len = len(text)
if 8 <= text_len <= 180:
    score += 3
elif text_len < 4:
    score -= 6
The text_len < 4 penalty is -6, but the positive scoring from attribute matches (+6 for title/name/product in attrs at line 729-730) can outweigh it. A node with class="product-title" and text "1" gets: +6 (attrs) + 2 (tag h1/h2/a) - 6 (short text) + 2 (href) = +4, which is > 0, so it passes.

Fix: Add an explicit check for pure-numeric text in _card_title_score_parts:

python
if text.isdigit():
    score -= 20
BUG 7: _promote_detail_title only promotes to LONGER candidates — never to same-length structured data
Severity: P2 — detail title promotion is too conservative

Root cause: @/c:/Projects/pre_poc_ai_crawler/backend/app/services/detail_extractor.py:829-831:

python
replacement = next(
    ((candidate, source) for _, _, candidate, source in ranked_candidates if candidate and len(candidate) > len(title)),
    None,
)
It only replaces the title if a better candidate is strictly longer. So if dom_h1 gives "Products" (8 chars) and json_ld gives "Shoes" (5 chars), the promotion doesn't fire because 5 < 8. The logic assumes longer = better, but for titles, structured source quality matters more than length.

Fix: Change the condition to prefer structured sources over DOM when the current title is flagged as needing promotion, regardless of length:

python
replacement = next(
    ((candidate, source) for _, _, candidate, source in ranked_candidates
     if candidate and (source in {"json_ld", "opengraph", "js_state"} or len(candidate) > len(title))),
    None,
)
BUG 8: _extract_label_value_pairs_from_node extracts UI chrome as field data
Severity: P2 — causes records with noise fields like "Sort By: Relevance"

Root cause: @/c:/Projects/pre_poc_ai_crawler/backend/app/services/listing_extractor.py:838-849 — the function scans all li, p, div, span nodes for label: value patterns. There's no filter against UI chrome like "Sort by: Relevance", "Filter by: Price", "Clear: All". These get normalized and added as candidates.

Fix: Add a noise filter for label-value pairs where the label matches known UI patterns. Check the label against LISTING_STRUCTURE_NEGATIVE_HINTS ("sort", "filter", "pagination") before adding:

python
if any(token in label.lower() for token in ("sort", "filter", "clear", "show", "view", "page")):
    continue
Summary Table
Bug	File	Line(s)	Impact	Fix Complexity
1	detail_extractor.py	163-177	Garbage titles on 15/45 sites	Low — add noise guard
2	extraction_rules.exports.json	LISTING_WEAK_TITLES, MERCHANDISING_PREFIXES	Promo/generic titles pass filters	Low — extend lists
3	detail_extractor.py	143-149	dom_h1 beats json_ld for title	Low — reorder ranking
4	harness_support.py	23-60	Surface misclassification on 4 sites	Low — extend hints + XML guard
5	listing_extractor.py	599-600, 869-870	Cards without anchors invisible	Medium — repetition fallback
6	listing_extractor.py	736-739	Numeric titles pass scoring	Low — add isdigit penalty
7	detail_extractor.py	829-831	Title promotion too conservative	Low — relax length condition
8	listing_extractor.py	838-849	UI chrome extracted as fields	Low — add label noise filter
Bugs 1+3 are the highest-impact fix — together they explain why 15/45 sites produce garbage titles. The detail extractor blindly trusts <h1> over JSON-LD, and has no noise filter on DOM-sourced titles.

