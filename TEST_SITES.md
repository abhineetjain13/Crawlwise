# CrawlerAI Test Corpus — Commerce & Jobs Only

**Version:** 3.0
**Scope:** Real-world commerce + job sites only
**Primary Issue:** Output data coverage & quality  
**Focus:** E-commerce listing/detail, Job listing/detail, Traversal

> **Maintenance rules**
> - `†` = spot-check before running (job detail URLs expire, refurbished SKUs rotate)
> - No per-domain hacks. Any fix that makes one site pass must generalise.

---

## Section S — Commerce Sandboxes

Deterministic commerce test fixtures. No bot protection.

| # | URL | Surface | What It Tests |
|---|---|---|---|
| S01 | `https://web-scraping.dev/products` | Listing | JSON-LD Product, data attributes, pagination, variant selectors |
| S02 | `https://web-scraping.dev/product/1` | Detail | Rich PDP — price, rating, reviews, JSON-LD, hidden DOM fields |
| S05 | `https://books.toscrape.com/catalogue/page-1.html` | Listing | Static HTML paginated listing, rating encoded as CSS class |
| S06 | `https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html` | Detail | Static PDP — price, availability, UPC in table, no JS needed |
| S11 | `https://webscraper.io/test-sites/e-commerce/allinone/computers/laptops` | Listing | Paginated e-commerce listing, price + rating in card DOM |
| S12 | `https://webscraper.io/test-sites/e-commerce/ajax/computers/laptops` | AJAX listing | Same listing loaded via AJAX — tests XHR interception |
| S13 | `https://webscraper.io/test-sites/e-commerce/scroll/computers/laptops` | Infinite scroll | Scroll-triggered load-more |
| S18 | `https://sandbox.oxylabs.io/products` | Listing | Oxylabs sandbox — JSON-LD, data-* attrs, pagination, no auth |
| S19 | `https://sandbox.oxylabs.io/products/1` | Detail | Oxylabs PDP — specs, multi-source fields |
| S20 | `https://scrapingcourse.com/ecommerce/` | Listing | Infinite scroll e-commerce, price/rating in DOM |
| S21 | `https://scrapingcourse.com/ecommerce/products/chaz-kangeroo-hoodie` | Detail | PDP with size/color variant matrix |
| S22 | `https://practicesoftwaretesting.com` | SPA Listing | Angular SPA — full JS render required, faceted filters |
| S23 | `https://practicesoftwaretesting.com/product/01HB` | SPA Detail | SPA product detail, tabbed specs, reviews |

---

## Section TC — Traversal Canaries (Commerce only)

| # | URL | Surface | Traversal Mode | What It Tests |
|---|---|---|---|---|
| TC01 | `https://books.toscrape.com/` | Listing | `paginate` | Classic numbered pagination from root path |
| TC02 | `https://www.myntra.com/hand-towels` | Listing | `paginate` | Real commerce pagination, duplicate-page suppression |
| TC03 | `https://in.puma.com/in/en/mens/mens-shoes/mens-shoes-sneakers` | Listing | `scroll` | Real infinite scroll, async settling, item-growth stop conditions |
| TC05 | `https://webscraper.io/test-sites/e-commerce/scroll/computers/laptops` | Infinite scroll | `scroll` / `load_more` | Scroll-triggered growth with repeatable sandbox behavior |

---

## Section LC — Listing Commerce

| # | URL | Engine | Complexity | What Makes It Interesting |
|---|---|---|---|---|
| LC01 | `https://www.reverb.com/marketplace?product_type=electric-guitars` | Browser | Medium | Marketplace infinite scroll, condition + price facets |
| LC02 | `https://www.discogs.com/sell/list?genre=Electronic` | Browser | Medium | Vinyl marketplace, seller metadata, paginated |
| LC03 | `https://www.musiciansfriend.com/snare-drum-heads` | HTTP | Medium | Paginated catalog, JSON-LD ProductList, faceted filters |
| LC06 | `https://www.uline.com/BL_8421/Boxes` | HTTP | Medium | Packaging catalog, table-based layout, variant data in DOM |
| LC08 | `https://www.autozone.com/filters-and-pcv/oil-filter` | Browser | Medium | Auto parts, vehicle fitment filter, nested window state JSON |
| LC10 | `https://www.chewy.com/b/dry-dog-food-294` | Browser | Medium | JS-rendered product cards, ingredient previews in listing |
| LC12 | `https://www.backmarket.com/en-us/l/iphone/e8724fea-197e-4815-85ce-21b8068020cc` | Browser | Medium | Refurbished marketplace, grade taxonomy, JSON-LD ProductList |
| LC13 | `https://www.ifixit.com/Parts` | HTTP | Easy | Repair parts tree, device compatibility hierarchy, clean HTML |
| LC14 | `https://www.abebooks.com/servlet/SearchResults?kn=python&pt=book` | HTTP | Medium | Used books, multi-seller listing per title, ISBN-keyed |
| LC15 | `https://www.thriftbooks.com/browse/?b.search=science` | HTTP | Easy | Book reseller, edition + condition variants in card, pagination |
| LC17 | `https://www.thomann.de/gb/guitars.html` | HTTP | Medium | EU music retailer, numbered pages, JSON-LD structured |
| LC18 | `https://www.rockler.com/wood/exotic-lumber` | HTTP | Medium | Specialty retail, category facets, inline JSON product data |
| LC19 | `https://www.govplanet.com/for-sale/equipment` | Browser | Hard | Gov't surplus heavy equipment — auction site, JS listing |

---

## Section LJ — Listing Jobs

| # | URL | Platform | Complexity | Notes |
|---|---|---|---|---|
| LJ01 | `https://boards.greenhouse.io/embed/job_board?for=airbnb` | Greenhouse | Easy | Department grouping |
| LJ02 | `https://boards.greenhouse.io/embed/job_board?for=shopify` | Greenhouse | Easy | Large board, many departments |
| LJ03 | `https://boards.greenhouse.io/embed/job_board?for=discord` | Greenhouse | Easy | Flat listing, team taxonomy |
| LJ04 | `https://boards.greenhouse.io/embed/job_board?for=palantir` | Greenhouse | Easy | Unusual role taxonomy |
| LJ10 | `https://startup.jobs/` | Custom | Medium | JS-rendered, startup categorisation, equity + stage tags |
| LJ11 | `https://www.idealist.org/en/jobs` | Custom | Medium | Non-profit sector, cause tags |
| LJ12 | `https://www.usajobs.gov/search/results/?k=software+engineer&p=1` | Government | Hard | JS-rendered, government schema, pay grade |
| LJ13 | `https://www.governmentjobs.com/careers/california` | NeoGov | Medium | State govt jobs, paginated, benefits structured |
| LJ14 | `https://www.higheredjobs.com/admin/search.cfm?JobCat=108` | Custom | Easy | Academic jobs, rank + tenure fields, salary band |
| LJ16 | `https://dynamitejobs.com/remote-jobs` | Custom | Medium | Remote listing, async-work tags |
| LJ17 | `https://jobicy.com/` | Custom | Easy | JSON-LD JobPosting heavy, clean remote board |
| LJ18 | `https://jobs.80000hours.org/jobs` | Custom | Medium | Impact jobs — cause area taxonomy |
| LJ19 | `https://cryptocurrencyjobs.co/` | Custom | Easy | Web3 domain, token comp fields |
| LJ20 | `https://euremotejobs.com/` | Custom | Easy | EU jurisdiction flag, GDPR-explicit |
https://www.instahyre.com/search-jobs
---

## Section DC — Detail Commerce

| # | URL | Engine | Complexity | What Makes It Interesting |
|---|---|---|---|---|
| DC02 | `https://www.thomann.de/gb/akg_k702.htm` | HTTP | Medium | Headphone FR data in DOM, tabbed specs, multi-warehouse stock |
| DC04 | `https://www.discogs.com/release/249504` | HTTP | Medium | Label / barcode / matrix / pressing data, multi-format |
| DC10 | `https://www.ifixit.com/products/iphone-14-battery` | HTTP | Easy | Repair part — compatibility list, schema.org Product |
| DC11 | `https://www.ifixit.com/products/macbook-pro-15-inch-retina-display-mid-2015-battery` | HTTP | Easy | Version compatibility matrix in DOM, conditional specs |
| DC12 | `https://www.vitacost.com/vitacost-vitamin-d3-mini-gels` | HTTP | Medium | Supplement Facts panel, size variant selector |
| DC14 | `https://www.thriftbooks.com/w/the-pragmatic-programmer_david-thomas_andrew-hunt/286697/` | HTTP | Easy | Multi-edition price compare, ISBN-13, condition grading |
| DC15 | `https://www.abebooks.com/9780132350884/Clean-Code-Handbook-Agile-Software-0132350882/plp` | HTTP | Medium | Multi-seller table, shipping region data, condition descriptions |
| DC17 | `https://www.rockler.com/jessem-mast-r-lift-ii-excel-router-lift` | HTTP | Medium | Compatibility chart, spec table, router size matrix |
| DC20 | `https://www.backmarket.com/en-us/p/iphone-14-128-gb-midnight/dba71a89-1e8e-4278-967e-0ef1c0d05f31` | Browser | Medium | Refurbished grade taxonomy, warranty terms, JSON-LD Product† |

---

## Section DJ — Detail Jobs

> ⚠️ Job detail URLs expire when roles close. Government URLs are most stable.

| # | URL | Platform | Stability | Structured Data |
|---|---|---|---|---|
| DJ01 | `https://www.usajobs.gov/job/836178100` | USAJOBS | High | Gov job schema, salary bands, OPM series code, duty station |
| DJ02 | `https://www.usajobs.gov/job/836402700` | USAJOBS | High | Federal — grade range, clearance level, travel requirement |
| DJ10 | `https://startup.jobs/senior-backend-engineer-at-vercel` | Startup.jobs | Medium | Equity range, company stage, team size structured† |
| DJ11 | `https://boards.greenhouse.io/airbnb/jobs/6290875` | Greenhouse | Medium | GH job detail — department, location, req ID |
| DJ12 | `https://boards.greenhouse.io/shopify/jobs/6318200` | Greenhouse | Medium | Multi-location Greenhouse, GDPR consent section |
| DJ13 | `https://jobs.lever.co/stripe/36fc41dd-3de0-4b5a-9efa-a28b13a16ffe` | Lever | Medium | Lever job detail — team, commitment, work type† |
| DJ16 | `https://cryptocurrencyjobs.co/engineering/stripe-backend-engineer/` | Crypto Jobs | Medium | Token compensation field† |
| DJ17 | `https://euremotejobs.com/job/senior-fullstack-developer-remote-europe` | EURemoteJobs | Low | EUR salary, jurisdiction field† |
| DJ19 | `https://dynamitejobs.com/remote-jobs/backend-engineer` | Dynamite | Low | Async-first culture fields† |
| DJ20 | `https://www.workingnomads.com/jobs?category=development` | WorkingNomads | Medium | Timezone overlap field, nomad-specific perks† |

---

## Section ATS — Enterprise ATS Boards

| # | URL | Platform | Notes |
|---|---|---|---|
| ATS01 | `https://www.vc5partners.com/jobs/` | Custom | Small VC firm jobs |
| ATS02 | `https://www.klingspor.com/jobs` | Custom | Manufacturing jobs |
| ATS03 | `https://ehccareers-emory.icims.com/jobs/search?pr=0&searchRelation=keyword_all` | iCIMS | Healthcare ATS |
| ATS04 | `https://careers.clarkassociatesinc.biz/` | Custom | Hospitality careers |
| ATS05 | `https://atlasmedstaff.com/job-search/` | Custom | Medical staffing |
| ATS06 | `https://smithnephew.wd5.myworkdayjobs.com/External` | Workday | MedTech enterprise |
| ATS07 | `https://ats.rippling.com/en-GB/inhance-technologies/jobs` | Rippling | HR platform ATS |
| ATS08 | `https://ibmwjb.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?mode=location` | Oracle HCM | Enterprise HCM |
| ATS09 | `https://www.paycomonline.net/v4/ats/web.php/portal/8EC14E985B45C7F52C531F487F62A2B8/career-page` | Paycom | Payroll/HR platform |
| ATS10 | `https://recruiting.ultipro.com/KAP1002KAPC/JobBoard/1e739e24-c237-44f3-9f7a-310b0cec4162/?q=&o=postedDateDesc` | UKG Ultipro | Enterprise HR |
| ATS11 | `https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=14fa7571-bfac-427f-aa18-9488391d4c5e&ccId=19000101_000001&type=MP&lang=en_US&selectedMenuKey=CurrentOpenings` | ADP Workforce Now | Enterprise payroll |

---

## Section CE — Commerce Extended

| # | URL | Surface | Notes |
|---|---|---|---|
| CE01 | `https://zadig-et-voltaire.com/eu/uk/c/tshirts-sweatshirts-for-men-127` | Listing | Luxury fashion, JS-rendered cards |
| CE02 | `https://31philliplim.com/collections` | Listing | Designer fashion, Shopify-like |
| CE04 | `https://ar.puma.com/lo-mas-vendido` | Listing | Puma LATAM, Spanish locale |
| CE05 | `https://www.karenmillen.com/eu/categories/womens-trousers` | Listing | Fashion retailer |
| CE06 | `https://www.ganni.com/en-gb/trainers/` | Listing | Scandinavian fashion |
| CE07 | `https://www.phase-eight.com/clothing/dresses/` | Listing | UK fashion retailer |
| CE08 | `https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos` | Listing | Menswear, Shopify |
| CE09 | `https://savannahs.com/collections/all-boots` | Listing | Luxury shoes, Shopify |
| CE10 | `https://www.kitchenaid.com/countertop-appliances/food-processors/food-processor-and-chopper-products` | Listing | Appliances, enterprise commerce |
| CE11 | `https://www.dyson.in/vacuum-cleaners/cord-free` | Listing | Dyson India, JS-rendered |
| CE12 | `https://www.grailed.com/categories/womenswear/blazers` | Listing | Fashion marketplace |
| CE13 | `https://www.desertcart.in/search?query=Nutrition+%26+Healthy+Eating` | Listing | Marketplace search results |
| CE14 | `https://www.firstcry.com/sets-and--suits/6/166?scat=166&gender=girl,unisex&ref2=menu_dd_girl-fashion_sets-and-suits_H` | Listing | Kids fashion category |
| CE15 | `https://www.stadiumgoods.com/collections/adidas-shoes` | Listing | Sneaker retail, browser-heavy |
https://www2.hm.com/en_in/men/shoes/view-all.html
https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html?trksrc=navbar&trkid=l2