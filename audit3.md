ested 10 unique URLs from the corpus and saved the raw report at qa_10sites_report.json.

Summary: 7/10 had full expected-field coverage, 2/10 were partial, 1/10 failed. The bigger problem is that 10/10 runs escalated to Playwright, including simple static pages. That is the main time bug.

Top findings

Every run used browser acquisition. Static pages like books.toscrape, web-scraping.dev, and webscraper.io should not need Playwright. This is the largest persistent latency issue.
Requested-field section opening is overmatching badly. On static pages it “clicks” broad DOM regions and dumps huge page text into diagnostics, which is noise and likely contributes to unnecessary browser fallback.
Data coverage is decent on easy PDPs, but data quality is still weak on normalized output: CSS/style values leak into fields, descriptions duplicate or include junk, and source labels are being stored as field values.
Listing classification is still weak for “category hub” pages. The pipeline can mark success on non-product navigational tiles.
Static tabular PDP coverage is not reliable enough yet. books.toscrape detail missed fields that are visibly present on the page.
Per-run issues

Listing web-scraping.dev (24.6s, full coverage)
Bug: should not need Playwright.
Quality risk: browser used even though curl had enough visible HTML.
Listing books.toscrape (15.4s, full coverage)
Bug: should not need Playwright.
Quality issue: title is truncated to A Light in the ... instead of full title.
Bug: requested-field section matcher is clearly overmatching; diagnostics show giant page-text captures for price.
Listing webscraper laptops (62.9s, full coverage)
Major time issue: far too slow for a simple test listing.
Bug: browser fallback is too aggressive.
Listing oxylabs sandbox (14.8s, failed)
Critical bug: listing_detection_failed with 0 records on a sandbox page that should be easy.
Improvement area: listing extractor/discovery does not understand this page shape.
Listing ifixit parts (17.7s, 0.75 coverage)
Bug: pipeline treats this category hub as a successful listing although price is absent.
Improvement area: distinguish product listings from taxonomy/navigation hubs.
Detail web-scraping.dev (12.6s, full coverage)
Coverage pass, but quality issues:
color captured as #fff
size captured as 1rem
summary is bloated with page chrome and cart text
Detail books.toscrape (10.0s, 0.4 coverage)
Critical coverage bug: missed price, image_url, and sku even though the page clearly has them.
Quality issue: description is duplicated and includes ...more.
Improvement area: table/spec mapping to canonical fields is weak.
Detail oxylabs sandbox (7.3s, full coverage)
Coverage pass, but quality issues:
brand became Developer: Nintendo
category became singleplayer
price stayed as locale string 91,99
Detail scrapingcourse hoodie (17.0s, full coverage)
Best overall detail run.
Minor quality risk: color/size are concatenated option sets rather than normalized variants.
Detail ifixit battery (18.2s, full coverage)
Coverage pass, but quality issues:
category is malformed: Phone\\
description has token corruption like re ment
color is a CSS variable value
size is a style unit (1em)
This is a strong sign that style/meta noise is still leaking into semantic fields.
Pipeline improvement plan

Fix browser escalation first.

Make curl the default when HTML already contains extractable content.
Stop using requested-field label absence as a browser trigger on static pages.
Add an explicit acquisition decision trace: why curl was rejected, with one boolean per rule.
Tighten requested-field interaction logic.

Restrict section matching to real interactive controls only.
Never let generic text matches “click” containers/body-level nodes.
Record selector/count diagnostics, not whole-page text blobs.
Improve static detail extraction quality.

Add stronger table/spec normalization for price, sku, upc, image_url.
Clean duplicated descriptions and strip ...more/chrome text.
Reject CSS/style/unit-looking values for semantic fields like color, size, category.
Improve listing classification.

Distinguish product-card listings from navigation/category hubs.
If cards have no product signals like price/url/image/title consistency, do not mark listing success.
Add support for Oxylabs sandbox listing patterns as a generic card normalization improvement, not a site hack.
Add a QA gate for coverage and latency.

Promote this 10-URL set into a repeatable regression suite.
Track per-run:
acquisition method
acquisition time
record count
expected-field coverage
data-quality violations
Set budgets:
static listing/detail should stay on curl unless clearly justified
simple corpus pages should not take ~15-60s
Add output quality validators before publish.

Flag values that look like CSS colors, CSS units, breadcrumb labels, or source-prefixed text.
Flag truncated titles on listings.
Flag duplicated long descriptions.
Highest-ROI next work:

Fix browser escalation and requested-field overmatching.
Fix static PDP table/spec mapping for books.toscrape-style pages.
Add field-value quality filters for style/meta leakage.
Add listing-vs-category-hub detection.