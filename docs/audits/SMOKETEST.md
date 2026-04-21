Smoke Test Results — 20 Complex Sites
13 PASS / 7 FAIL (65% pass rate)

Report saved: @/c:/Projects/pre_poc_ai_crawler/backend/artifacts/test_sites_acceptance/20260421T094742Z__full_pipeline__test_sites_tail.json

Failure Breakdown by Mode
Failure Mode	Count	Sites
blocked (anti-bot challenge)	5	Autozone (×2), Chewy (×2), KitchenAid
listing_detection_failed	1	GovPlanet
error (pipeline crash/timeout)	1	Reverb
FM-1: Anti-Bot Challenge Pages (5 sites — highest impact)
All 5 used browser method and hit challenge pages:

Autozone (listing + detail) — PerimeterX detected in adorama diagnostics; likely same vendor
Chewy (listing + detail) — visible_text=4 after all probes, fully blocked
KitchenAid — 1.1MB HTML fetched but classified as challenge_page by browser diagnostics
Root cause: Browser acquisition reaches the page but anti-bot JS (PerimeterX, Akamai BMP, etc.) serves a challenge shell. The acquisition runtime correctly detects challenge_page but has no counter-strategy — it just marks verdict=blocked and gives up.

Fix area: acquisition/runtime — needs challenge-wait + retry cycle, or cookie/resolution rotation.

FM-2: Listing Detection Failed (1 site — GovPlanet)
GovPlanet — browser fetched content, but listing_detection_failed verdict
GovPlanet is an auction site with unusual DOM structure (auction cards, bid UI)
Root cause: Listing extractor doesn't recognize the card pattern. No platform adapter registered for govplanet.

Fix area: listing_extractor.py card detection heuristics, or a govplanet adapter.

FM-3: Pipeline Error / Timeout (1 site — Reverb)
Reverb — verdict=error, 93.77s elapsed, no method/status_code recorded
Likely a timeout or unhandled exception during acquisition
Root cause: Probably a browser timeout or crash. The browser_diagnostics={} (empty) suggests the acquisition never completed the probe cycle.

Fix area: Need to check run logs for the actual exception. Likely acquisition/runtime timeout handling.

Quality Issues in "PASS" Sites (false positives)
Several PASS sites have garbage sample titles or surface misclassification, meaning extraction quality is poor despite the "success" verdict:

Site	Sample Title	Issue
USAJOBS	"Sort by Sort by Clear SortBy (optional)..."	UI chrome extracted as title; surface=ecommerce_listing (should be job_listing)
Startup.jobs	"Bookmark Apply"	Button text as title; surface=ecommerce_listing (should be job_listing)
Adorama PDP	"10 Content Trends to Expect in 2024..."	Wrong content (blog); surface=ecommerce_listing (should be ecommerce_detail); HTTP 404
BackMarket detail	"Great deals"	Promo text, not product name
Zadig & Voltaire	"1"	Garbage title; only 3 populated fields
Karen Millen	"extra 15% off everything* code: KMEXTRA15"	Promo banner as title; only 2 records
Surface Misclassification
infer_surface() in @/c:/Projects/pre_poc_ai_crawler/backend/harness_support.py:35-51 misclassified 3 sites:

USAJOBS → ecommerce_listing (should be job_listing) — URL has /search/results/ which doesn't match _JOB_LISTING_HINTS
Startup.jobs → ecommerce_listing (should be job_listing) — domain has "jobs" but path / doesn't match hints
Autozone PDP → ecommerce_listing (should be ecommerce_detail) — URL has /881036_0_0 suffix but no /dp/ or /product/ hint
Summary of Actionable Failure Modes
Anti-bot challenge (5 sites) — biggest gap. Need challenge-wait/retry in acquisition runtime
Surface inference (3 sites) — infer_surface() hint lists are incomplete; causes wrong extractor path
Listing detection on non-standard DOM (1 site) — GovPlanet auction cards not recognized
Extraction quality on "passing" sites (6 sites) — garbage titles, promo text, UI chrome extracted as record data
Pipeline crash on complex SPAs (1 site) — Reverb timeout with empty diagnostics
Task complete. 20 complex sites smoked, 7 hard failures identified across 3 distinct failure modes, plus 6 quality issues in "passing" sites. The anti-bot challenge mode accounts for 5/7 failures and is the highest-impact fix target. Surface misclassification in infer_surface() is the second priority — it sends job sites down the ecommerce extraction path, producing garbage results.

23 PASS / 2 FAIL (92% pass rate)

Report: @/c:/Projects/pre_poc_ai_crawler/backend/artifacts/test_sites_acceptance/20260421T101917Z__full_pipeline__test_sites_tail.json

Hard Failures (2)
#	Site	Failure Mode	Root Cause
1	lafayette148ny.com/media/sitemap-products.xml	error (90s timeout)	XML sitemap parsed as HTML by BeautifulSoup — XMLParsedAsHTMLWarning. Pipeline tries to extract listing records from an XML sitemap, hangs processing 1MB+ of <url> nodes
2	quotes.toscrape.com/scroll	listing_extraction_empty	Infinite-scroll page fetched via browser, but listing extractor doesn't recognize quote cards as listing items (non-commerce DOM pattern)
Quality Issues in "PASS" Sites (false positives)
Site	Sample Title	Populated Fields	Issue
books.toscrape detail	"Product Description"	—	Detail page classified as listing; title is a heading, not product name
ifixit iPhone 14 battery	"1"	14	Title is garbage ("1"); 14 fields populated suggests data is there but title extraction fails
thriftbooks Pragmatic Programmer	"The Biggest Loser Fitness Program..."	6	Wrong book extracted as sample — listing page has multiple books, first record is unrelated
discogs sell list	"Purchases"	3	UI nav text as title; only 2 records from a page with 25+ listings
musiciansfriend	"Save 20% With Code SPRING"	7	Promo banner as title; 60 records extracted but first is a promo card
uline	"Products"	3	Nav heading as title; only 2 records; HTTP 404 on the URL
abebooks	"Ask Schüling Buchkurier a question..."	7	Seller contact CTA as title, not book title
thomann.de	"5230 beyerdynamic DT-770 Pro 80 Ohm £133"	5	Price concatenated into title; HTTP 404
rockler	"1"	3	Garbage title; only 3 populated fields
scrapethissite simple	"South Georgia and the South Sandwich Islands"	3	Countries table — only 1 record extracted from 250+ rows
Traversal-Specific Findings
Site	Traversal Mode	Records	Notes
books.toscrape/	paginate	20	✅ Works — standard pagination
quotes.toscrape/scroll	scroll	0	❌ Listing detection fails on non-commerce infinite scroll
webscraper.io/scroll	scroll	3	⚠️ Only 3 records — scroll didn't trigger enough load-more
webscraper.io/ajax	AJAX	6	⚠️ Only 6 records — AJAX interception partial
scrapingcourse.com	infinite scroll	16	✅ Works via curl_cffi (server-rendered)