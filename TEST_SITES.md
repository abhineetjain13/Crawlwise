# CrawlerAI Extended Test Corpus — 100 Real-World Sites

**Version:** 2.0  
**Scope:** Real-world + dedicated scraping sandboxes  
**Primary Issue:** Output data coverage & quality  
**Focus:** DOM · JSON · JSON-LD · Rendered JS · Hidden DOM · Data Attributes  

> **Maintenance rules**
> - `†` = spot-check before running (job detail URLs expire, refurbished SKUs rotate)
> - Detail job URLs should be re-discovered from listing pages if they 404
> - Sandboxes (Section 0) never 404 by design — run these first for baseline
> - No per-domain hacks. Any fix that makes one site pass must generalise.

---

## Regression Order

1. **Sandboxes first** — baseline your extractor against deterministic fixtures: `§0`
2. **Rich data APIs** — pure JSON/structured paths: `§RD`
3. **Listing commerce** — static + JS listing extraction: `§LC`
4. **Listing jobs (ATS boards)** — board-level extraction: `§LJ`
5. **Detail commerce** — multi-source PDP extraction: `§DC`
6. **Detail jobs** — job posting schema extraction: `§DJ`

---

## Section 0 — Scraping Sandboxes & Test Fixtures

Deterministic sites built specifically for crawler/scraper testing. No bot protection,
no cookie walls, no anti-scraping. Run these to establish a coverage baseline before
touching real-world targets.

| # | URL | Surface | What It Tests |
|---|---|---|---|
| S01 | `https://web-scraping.dev/products` | Listing | JSON-LD Product, data attributes, pagination, variant selectors |
| S02 | `https://web-scraping.dev/product/1` | Detail | Rich PDP — price, rating, reviews, JSON-LD, hidden DOM fields |
| S03 | `https://web-scraping.dev/reviews` | Listing | Nested review objects, pagination, date parsing |
| S04 | `https://web-scraping.dev/login` | Auth pattern | Cookie/session flow (test that crawler handles graceful skip) |
| S05 | `https://books.toscrape.com/catalogue/page-1.html` | Listing | Static HTML paginated listing, rating encoded as CSS class |
| S06 | `https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html` | Detail | Static PDP — price, availability, UPC in table, no JS needed |
| S07 | `https://quotes.toscrape.com/` | Listing | Simple HTML, author + tag extraction, pagination |
| S08 | `https://quotes.toscrape.com/js/` | JS Listing | Same data as S07 but JS-rendered — engine selection test |
| S09 | `https://quotes.toscrape.com/scroll` | Infinite scroll | Infinite scroll variant — pagination detection test |
| S10 | `https://quotes.toscrape.com/tableful` | Table DOM | Table-based layout extraction |
| S11 | `https://webscraper.io/test-sites/e-commerce/allinone/computers/laptops` | Listing | Paginated e-commerce listing, price + rating in card DOM |
| S12 | `https://webscraper.io/test-sites/e-commerce/ajax/computers/laptops` | AJAX listing | Same listing loaded via AJAX — tests XHR interception |
| S13 | `https://webscraper.io/test-sites/e-commerce/scroll/computers/laptops` | Infinite scroll | Scroll-triggered load-more |
| S14 | `https://webscraper.io/test-sites/tables` | Tables | Complex nested table extraction |
| S15 | `https://www.scrapethissite.com/pages/simple/` | Simple HTML | Countries table — clean field extraction baseline |
| S16 | `https://www.scrapethissite.com/pages/forms/` | Search + results | Form-triggered results page |
| S17 | `https://www.scrapethissite.com/pages/ajax-javascript/` | AJAX | AJAX-fetched data, year-filtered |
| S18 | `https://sandbox.oxylabs.io/products` | Listing | Oxylabs sandbox — JSON-LD, data-* attrs, pagination, no auth |
| S19 | `https://sandbox.oxylabs.io/products/1` | Detail | Oxylabs PDP — specs, multi-source fields |
| S20 | `https://scrapingcourse.com/ecommerce/` | Listing | Infinite scroll e-commerce, price/rating in DOM |
| S21 | `https://scrapingcourse.com/ecommerce/products/chaz-kangeroo-hoodie` | Detail | PDP with size/color variant matrix |
| S22 | `https://practicesoftwaretesting.com/#/` | SPA | Angular SPA — full JS render required, faceted filters |
| S23 | `https://practicesoftwaretesting.com/#/product/01HB` | SPA Detail | SPA product detail, tabbed specs, reviews |
| S24 | `https://fakestoreapi.com/products` | JSON API | Fake store REST API — schema validation baseline |
| S25 | `https://dummyjson.com/products` | JSON API | Rich fake product JSON — 30+ fields per record, nested rating |
| S26 | `https://jsonplaceholder.typicode.com/posts` | JSON API | Simplest possible JSON array — extractor smoke test |
| S27 | `https://the-internet.herokuapp.com/tables` | Tables | Sortable tables, multi-column extraction |
| S28 | `https://the-internet.herokuapp.com/infinite_scroll` | Infinite scroll | Pure infinite scroll test |
| S29 | `https://crawler-test.com/` | Multi-pattern | Meta tags, encoding, redirects, robots.txt behaviour |
| S30 | `https://demo.opencart.com/` | Full e-commerce | OpenCart demo — listing + detail + cart state, no auth needed |

---

## Section LC — Listing Commerce (20)

JS-rendered and complex HTTP listing pages. No aggressive bot protection.

| # | URL | Engine | Complexity | What Makes It Interesting |
|---|---|---|---|---|
| LC01 | `https://www.reverb.com/marketplace?product_type=electric-guitars` | Browser | Medium | Marketplace infinite scroll, condition + price facets, mixed DOM + inline JSON |
| LC02 | `https://www.discogs.com/sell/list?genre=Electronic` | Browser | Medium | Vinyl marketplace, seller metadata, paginated, release-linked JSON |
| LC03 | `https://www.musiciansfriend.com/guitars/electric-guitars` | HTTP | Medium | Paginated catalog, JSON-LD ProductList, faceted filters |
| LC04 | `https://www.adorama.com/catalog.tpl?cat=DLCAM` | HTTP | Medium | Photo/video listing, numbered pagination, inline JSON product arrays |

| LC06 | `https://www.uline.com/BL_8421/Boxes` | HTTP | Medium | Packaging catalog, table-based layout, variant data in DOM |
| LC07 | `https://www.webstaurantstore.com/list/191/commercial-refrigerators.html` | HTTP | Medium | Commercial equipment, paginated, spec summaries in card DOM |
| LC08 | `https://www.autozone.com/filters-and-pcv/oil-filter` | Browser | Medium | Auto parts, vehicle fitment filter, nested window state JSON |
| LC10 | `https://www.chewy.com/b/dry-dog-food-294` | Browser | Medium | JS-rendered product cards, ingredient previews in listing |
| LC12 | `https://www.backmarket.com/en-us/l/smartphones/6b74ac09-dc46-4c8e-a5a3-5a2f98e53aec` | Browser | Medium | Refurbished marketplace, grade taxonomy, JSON-LD ProductList |
| LC13 | `https://www.ifixit.com/Parts` | HTTP | Easy | Repair parts tree, device compatibility hierarchy, clean HTML |
| LC14 | `https://www.abebooks.com/servlet/SearchResults?kn=python&pt=book` | HTTP | Medium | Used books, multi-seller listing per title, ISBN-keyed |
| LC15 | `https://www.thriftbooks.com/browse/?b.search=science` | HTTP | Easy | Book reseller, edition + condition variants in card, pagination |
| LC17 | `https://www.thomann.de/gb/guitars.html` | HTTP | Medium | EU music retailer, numbered pages, JSON-LD structured |
| LC18 | `https://www.rockler.com/woodworking-tools` | HTTP | Medium | Specialty retail, category facets, inline JSON product data |
| LC19 | `https://www.govplanet.com/for-sale/equipment` | Browser | Hard | Gov't surplus heavy equipment — auction site, JS listing, unusual domain |

---

## Section LJ — Listing Jobs (20)

ATS boards and job listing pages across multiple platforms. Covers Greenhouse, Lever,
Workable, and independent boards — none in the original corpus.

| # | URL | Platform | Complexity | Notes |
|---|---|---|---|---|
| LJ01 | `https://boards.greenhouse.io/embed/job_board?for=airbnb` | Greenhouse | Easy | New company vs original GH set, department grouping |
| LJ02 | `https://boards.greenhouse.io/embed/job_board?for=shopify` | Greenhouse | Easy | Large board, many departments, clean embed |
| LJ03 | `https://boards.greenhouse.io/embed/job_board?for=discord` | Greenhouse | Easy | Flat listing, team taxonomy |
| LJ04 | `https://boards.greenhouse.io/embed/job_board?for=palantir` | Greenhouse | Easy | Unusual role taxonomy, classified-adjacent titles |
| LJ05 | `https://jobs.lever.co/stripe` | Lever | Easy | New company vs original Lever set |
| LJ06 | `https://jobs.lever.co/intercom` | Lever | Easy | SaaS mid-size, standard Lever board |
| LJ07 | `https://jobs.lever.co/brex` | Lever | Easy | Fintech, compact listing |
| LJ08 | `https://apply.workable.com/deel/` | Workable | Easy | New ATS platform — Workable not in original corpus |
| LJ09 | `https://apply.workable.com/remote/` | Workable | Easy | Remote.com on Workable — location-free job fields |
| LJ10 | `https://startup.jobs/` | Custom | Medium | JS-rendered, startup categorisation, equity + stage tags |
| LJ11 | `https://www.idealist.org/en/jobs` | Custom | Medium | Non-profit sector, cause tags, volunteering vs paid flag |
| LJ12 | `https://www.usajobs.gov/search/results/?k=software+engineer&p=1` | Government | Hard | JS-rendered, government schema, pay grade, series code |
| LJ13 | `https://www.governmentjobs.com/careers/california` | NeoGov | Medium | State govt jobs, iframe-free, paginated, benefits structured |
| LJ14 | `https://www.higheredjobs.com/admin/search.cfm?JobCat=108` | Custom | Easy | Academic jobs, rank + tenure fields, salary band |
| LJ15 | `https://remote.co/remote-jobs/` | Custom | Easy | Remote-only board, clean HTML, category tree |
| LJ16 | `https://dynamitejobs.com/remote-jobs` | Custom | Medium | Remote listing, async-work tags, lifestyle-business framing |
| LJ17 | `https://jobicy.com/` | Custom | Easy | JSON-LD JobPosting heavy, clean remote board |
| LJ18 | `https://jobs.80000hours.org/jobs` | Custom | Medium | Impact jobs — cause area taxonomy, priority rating field |
| LJ19 | `https://cryptocurrencyjobs.co/` | Custom | Easy | Web3 domain, token comp fields, tag-heavy listing |
| LJ20 | `https://euremotejobs.com/` | Custom | Easy | EU jurisdiction flag, GDPR-explicit, mixed language listings |

---

## Section DC — Detail Commerce (20)

Product detail pages with rich multi-source data. Prioritises sites with JSON-LD +
spec tables + inline JSON simultaneously — the hardest multi-source extraction test.

| # | URL | Engine | Complexity | What Makes It Interesting |
|---|---|---|---|---|
| DC01 | `https://www.thomann.de/gb/shure_sm58_lc.htm` | HTTP | Medium | Spec table, reviews, JSON-LD Product, multi-currency pricing |
| DC02 | `https://www.thomann.de/gb/akg_k702.htm` | HTTP | Medium | Headphone FR data in DOM, tabbed specs, multi-warehouse stock |
| DC03 | `https://www.discogs.com/release/1529440` | HTTP | Medium | Daft Punk RAM — track listing, multi-edition, MusicBrainz-linked JSON-LD |
| DC04 | `https://www.discogs.com/release/249504` | HTTP | Medium | Classic release — label / barcode / matrix / pressing data, multi-format |
| DC05 | `https://www.parts-express.com/dayton-audio-dc28f-8-1-1-8-silk-dome-tweeter-8-ohm/275-010` | HTTP | Medium | Thiele-Small params table (Fs, Qts, Xmax), JSON-LD, linked datasheet PDF |
| DC06 | `https://www.parts-express.com/dayton-audio-rs150-4-6-reference-woofer-4-ohm/295-315` | HTTP | Medium | Speaker T/S params, mounting template tab, alt SKU variants |
| DC07 | `https://www.sweetwater.com/store/detail/ATH-M50x--audio-technica-ath-m50x-professional-studio-monitor-headphones` | Browser | Medium | Awards, gear notes, Q&A section, rich JSON-LD, JS-rendered reviews |
| DC08 | `https://www.webstaurantstore.com/avantco-ice-e80-ahc-half-dice-undercounter-ice-machine/19E80AHC.html` | HTTP | Medium | NSF/UL certs, capacity spec table, installation dimensions, alt SKUs |
| DC09 | `https://www.autozone.com/motor-oil-and-transmission-fluid/motor-oil/mobil-1/mobil-1-extended-performance-full-synthetic-motor-oil-5w-30-5-quart/881036_0_0` | Browser | Medium | Fitment data, API spec in DOM, store availability from JSON |
| DC10 | `https://www.ifixit.com/products/iphone-14-battery` | HTTP | Easy | Repair part — compatibility list, teardown links, schema.org Product |
| DC11 | `https://www.ifixit.com/products/macbook-pro-15-inch-retina-display-mid-2015-battery` | HTTP | Easy | Version compatibility matrix in DOM, conditional specs |
| DC12 | `https://www.vitacost.com/now-foods-ultra-omega-3-fish-oil-500-epa-250-dha-180-softgels` | HTTP | Medium | Supplement Facts panel, third-party cert badges, size variant selector |
| DC13 | `https://www.chewy.com/royal-canin-golden-retriever-adult-dry/dp/177115` | Browser | Medium | Ingredient list, guaranteed analysis table, breed-specific claim extraction |
| DC14 | `https://www.thriftbooks.com/w/the-pragmatic-programmer_david-thomas_andrew-hunt/286697/` | HTTP | Easy | Multi-edition price compare, ISBN-13, condition grading, seller count |
| DC15 | `https://www.abebooks.com/9780132350884/Clean-Code-Handbook-Agile-Software-0132350882/plp` | HTTP | Medium | Multi-seller table, shipping region data, condition descriptions |
| DC16 | `https://www.adorama.com/ib5dviii.html` | Browser | Medium | Camera body — bundle options, rebate data in DOM, multi-source pricing |
| DC17 | `https://www.rockler.com/jessem-mast-r-lift-ii-excel-router-lift` | HTTP | Medium | Compatibility chart, video embed, spec table, router size matrix |
| DC18 | `https://www.globalindustrial.com/p/rubbermaid-fg454000bla-brute-tote-storage-container-40-gal` | HTTP | Easy | Industrial product — weight/volume specs, compliance certifications |
| DC19 | `https://www.swappa.com/buy/apple-iphone-15-pro` | Browser | Medium | Live marketplace — condition grades, seller ratings, pricing distribution |
| DC20 | `https://www.backmarket.com/en-us/p/iphone-14-128-gb-midnight/dba71a89-1e8e-4278-967e-0ef1c0d05f31` | Browser | Medium | Refurbished grade taxonomy, warranty terms, JSON-LD Product† |

---

## Section DJ — Detail Jobs (20)

> ⚠️ Job detail URLs expire when roles close. Government and academic URLs are most
> stable (weeks–months). ATS detail URLs should be re-discovered from LJ listing pages
> if they return 404.

| # | URL | Platform | Stability | Structured Data |
|---|---|---|---|---|
| DJ01 | `https://www.usajobs.gov/job/836178100` | USAJOBS | High | Gov job schema, salary bands, OPM series code, duty station |
| DJ02 | `https://www.usajobs.gov/job/836402700` | USAJOBS | High | Federal — grade range, clearance level, travel requirement |
| DJ03 | `https://www.governmentjobs.com/careers/california/jobs/4817400` | NeoGov | High | State — bargaining unit, benefits table, bilingual flag |
| DJ04 | `https://www.higheredjobs.com/jobs/details.cfm?JobCode=178200990` | HigherEdJobs | High | Academic — rank, tenure track, department, review date |
| DJ06 | `https://jobicy.com/jobs/senior-fullstack-engineer-remote` | Jobicy | Medium | JSON-LD JobPosting, salary range, timezone requirement† |
| DJ07 | `https://www.themuse.com/jobs/airbnb/software-engineer-backend` | The Muse | Medium | Company profile + role merged, JSON-LD, perks section† |
| DJ08 | `https://www.themuse.com/jobs/shopify/senior-software-engineer` | The Muse | Medium | Benefits accordion, culture tags, video embed† |
| DJ10 | `https://startup.jobs/senior-backend-engineer-at-vercel` | Startup.jobs | Medium | Equity range, company stage, team size structured† |
| DJ11 | `https://boards.greenhouse.io/airbnb/jobs/6290875` | Greenhouse | Medium | GH job detail — department, location, req ID, custom questions |
| DJ12 | `https://boards.greenhouse.io/shopify/jobs/6318200` | Greenhouse | Medium | Multi-location Greenhouse, GDPR consent section in DOM |
| DJ13 | `https://jobs.lever.co/stripe/36fc41dd-3de0-4b5a-9efa-a28b13a16ffe` | Lever | Medium | Lever job detail — team, commitment, work type, apply flow† |
| DJ14 | `https://jobs.lever.co/intercom/9c2d4b23-7f88-4b6a-9a1c-3e7f2d8c5b10` | Lever | Medium | Benefits accordion, team description, Lever standard template† |
| DJ16 | `https://cryptocurrencyjobs.co/engineering/stripe-backend-engineer/` | Crypto Jobs | Medium | Token compensation field, DAO-optional role data† |
| DJ17 | `https://euremotejobs.com/job/senior-fullstack-developer-remote-europe` | EURemoteJobs | Low | EUR salary, jurisdiction field, GDPR compliance note† |
| DJ18 | `https://remote.co/job/senior-full-stack-developer/` | Remote.co | Medium | Full HTML, no JS needed, clean JSON-LD JobPosting |
| DJ19 | `https://dynamitejobs.com/remote-jobs/backend-engineer` | Dynamite | Low | Async-first culture fields, lifestyle-business framing† |
| DJ20 | `https://www.workingnomads.com/jobs?category=development` | WorkingNomads | Medium | Timezone overlap field, nomad-specific perks† |

---

## Section RD — Rich / Structured Data (20)

Highest signal for multi-source extraction testing. Prioritises deep nesting,
parallel arrays, and non-standard schema patterns that stress-test normalisation.

| # | URL | Format | Nesting Depth | What to Extract |
|---|---|---|---|---|
| RD01 | `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson` | GeoJSON | Deep | Geometry coords, nested `properties`, magnitude type variants |
| RD02 | `https://api.fda.gov/drug/label.json?search=openfda.brand_name:tylenol&limit=3` | JSON API | Very deep | `openfda` nested object, warning arrays, multi-section text blocks |
| RD03 | `https://clinicaltrials.gov/api/query/full_studies?expr=diabetes&min_rnk=1&max_rnk=3&fmt=JSON` | JSON API | Extreme | 100+ fields per study, eligibility criteria, arm descriptions |
| RD04 | `https://musicbrainz.org/ws/2/recording/?query=bohemian+rhapsody&fmt=json` | JSON API | Deep | Disambiguation strings, relations array, area nesting |
| RD05 | `https://openlibrary.org/api/books?bibkeys=ISBN:0451526538&jscmd=details&format=json` | JSON API | Medium | Key-wrapped response object, bibkey-indexed, subject arrays |
| RD06 | `https://www.wikidata.org/wiki/Special:EntityData/Q42.json` | JSON-LD / JSON | Extreme | Entity graph — mainsnak, qualifiers, references, sitelinks |
| RD07 | `https://api.crossref.org/works/10.1038/nature12373` | JSON API | Deep | Academic — funder array, affiliation, ORCID, assertion fields |
| RD08 | `https://api.semanticscholar.org/graph/v1/paper/649def34f8be52c8b66281af98ae884c09aef38d?fields=title,abstract,authors,year,citationCount,references` | JSON API | Deep | Citation graph, author disambiguation, reference list |
| RD09 | `https://api.github.com/repos/vercel/next.js` | JSON API | Medium | 60+ top-level fields, nested owner / license / topics |
| RD10 | `https://openalex.org/works/W2741809807` | JSON API | Deep | Concepts, institutions array, locations, open-access status |
| RD11 | `https://api.coingecko.com/api/v3/coins/bitcoin` | JSON API | Deep | market_data nested 3 levels, community_data, developer_data |
| RD12 | `https://restcountries.com/v3.1/name/germany` | JSON API | Medium | Currency object, languages, translations, demonyms, flags map |
| RD13 | `https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&hourly=temperature_2m,relativehumidity_2m,windspeed_10m,precipitation` | JSON API | Medium | Time-series parallel arrays, hourly units, timezone metadata |
| RD14 | `https://apis.scryfall.com/cards/named?exact=Black+Lotus` | JSON API | Medium | Legalities map, image_uris, prices object, keywords array |
| RD15 | `https://pokeapi.co/api/v2/pokemon/charizard` | JSON API | Deep | 20+ nested arrays, sprites map, abilities / moves / types schema |
| RD16 | `https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/aspirin/JSON` | JSON API | Deep | Chemical props — SMILES, InChI, computed descriptors, CID |
| RD17 | `https://openfarm.cc/api/v1/crops/?q=tomato` | JSON:API | Medium | JSONAPI spec format (data/relationships/included), growing conditions |
| RD18 | `https://api.worldbank.org/v2/country/us/indicator/NY.GDP.MKTP.CD?format=json` | JSON API | Medium | Page-meta + data wrapped array, indicator + country nested |
| RD19 | `https://openlibrary.org/subjects/science.json` | JSON API | Medium | Subject listing — works array, author facets, edition count |
| RD20 | `https://www.thecocktaildb.com/api/json/v1/1/search.php?s=margarita` | JSON API | Medium | Denormalised — ingredient1–15 + measure1–15 as flat columns |

---

## Appendix — Coverage Matrix

Use this to track extraction completeness per site after each test run.

| Source | S (Sandbox) | LC | LJ | DC | DJ | RD |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| DOM text fields | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| JSON-LD (`@type: Product`) | ✓ | ✓ | — | ✓ | — | — |
| JSON-LD (`@type: JobPosting`) | — | — | ✓ | — | ✓ | — |
| Inline JSON (`window.__data__`) | ✓ | ✓ | — | ✓ | — | — |
| `<script type="application/json">` | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Open Graph meta tags | — | ✓ | ✓ | ✓ | ✓ | — |
| `data-*` attributes | ✓ | ✓ | — | ✓ | — | — |
| Hidden DOM (`display:none`, `aria-hidden`) | ✓ | ✓ | — | ✓ | — | — |
| Spec / data tables | — | ✓ | — | ✓ | ✓ | — |
| REST / JSON API response | — | — | — | — | — | ✓ |
| GeoJSON / JSONAPI spec | — | — | — | — | — | ✓ |
| Paginated continuation | ✓ | ✓ | ✓ | — | — | ✓ |

---

*End of document*