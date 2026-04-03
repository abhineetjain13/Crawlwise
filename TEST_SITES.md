# CrawlerAI Test Sites

Single real-world test corpus for the current product scope.

**Scope:**

- E-commerce: product detail, listing, JSON APIs, pagination, infinite scroll, load-more
- Jobs: ATS boards, niche boards, JSON APIs, JS-rendered listings
- Difficulty ranges from clean JSON/API to JS-heavy, bot-protected, and deep DOM

**Maintenance:**

- Prefer stable URLs over campaign links, search sessions, or temporary redirects.
- Validate new links with a quick browser load or crawl smoke test before adding.
- Remove duplicates and dead links when they stop being useful.

---

## Regression Order

1. **JSON/API first** — validate pure JSON/API paths: `#3, 5, 9, 38, 39, 40`
2. **ATS boards** — validate board extraction: `#27–35`
3. **Commerce HTML/listing** — `#1, 2, 4, 7, 14, 15, 21–23, 25`
4. **Hard group last** — `#10–13, 16–18, 20, 24, 44–50`

---

## Section A — Ecommerce (Core 25)

| #   | URL                                                                              | Surface        | Difficulty |
| --- | -------------------------------------------------------------------------------- | -------------- | ---------- |
| 1   | `https://www.allbirds.com/products/mens-wool-runners`                            | product detail | easy       |
| 2   | `https://www.allbirds.com/collections/mens`                                      | listing        | easy       |
| 3   | `https://www.allbirds.com/products.json`                                         | JSON API       | easy       |
| 4   | `https://www.gymshark.com/collections/all-products`                              | listing        | medium     |
| 5   | `https://www.gymshark.com/collections/all-products.json`                         | JSON API       | easy       |
| 7   | `https://www.chubbiesshorts.com/collections/men`                                 | listing        | medium     |
| 8   | `https://world.openfoodfacts.org/product/5449000000996/coca-cola-original-taste` | product detail | easy       |
| 9   | `https://world.openfoodfacts.org/category/sodas.json`                            | JSON listing   | easy       |
| 10  | `https://www.dyson.in/air-treatment`                                             | listing        | hard       |
| 11  | `https://www.dyson.in/vacuum-cleaners`                                           | listing        | hard       |
| 12  | `https://www.underarmour.com/en-us/c/mens/`                                      | listing        | hard       |
| 13  | `https://www.underarmour.com/en-us/c/shoes/`                                     | listing        | hard       |
| 14  | `https://www.footlocker.com/category/mens/shoes.html`                            | listing        | medium     |
| 15  | `https://www.footlocker.com/category/women/shoes.html`                           | listing        | medium     |
| 16  | `https://www2.hm.com/en_us/women/products/view-all.html`                         | listing        | hard       |
| 17  | `https://www.uniqlo.com/us/en/men/tops`                                          | listing        | hard       |
| 18  | `https://www.johnlewis.com/browse/electricals/c6000014`                          | listing        | medium     |
| 20  | `https://www.nike.com/w/mens-shoes-nik1zy7ok`                                    | listing        | hard       |
| 21  | `https://us.puma.com/us/en/men/shop-all-mens`                                    | listing        | medium     |
| 22  | `https://www.converse.com/shop/mens-shoes`                                       | listing        | medium     |
| 23  | `https://www.ae.com/us/en/c/men/shoes/cat6470582`                                | listing        | medium     |
| 24  | `https://www.ajio.com/shop/men`                                                  | listing        | hard       |
| 25  | `https://www.lifestylestores.com/in/en/men/c/LS-Men`                             | listing        | medium     |

---

## Section B — Ecommerce (Specialist / Deep DOM)

Technical specs, industrial parts, complex consumer electronics with nested DOM structures and interactive data tables.

| #   | URL                                                                                                                                             | Surface            | Difficulty |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ---------- |
| B1  | `https://www.mcmaster.com/pipe-fittings/high-pressure-stainless-steel-threaded-pipe-fittings/`                                                  | industrial listing | medium     |
| B2  | `https://www.specialized.com/us/en/s-works-tarmac-sl8-shimano-dura-ace-di2/p/216953`                                                            | product detail     | medium     |
| B3  | `https://www.bhphotovideo.com/c/product/1730114-REG/sony_ilce_7rm5_b_alpha_a7r_v_mirrorless.html`                                               | product detail     | medium     |
| B4  | `https://www.sweetwater.com/store/detail/Matriarch--moog-matriarch-paraphonic-semi-modular-analog-synthesizer-and-step-sequencer`               | product detail     | medium     |
| B5  | `https://www.mouser.com/ProductDetail/Texas-Instruments/MSPM0H3216SRGZR`                                                                        | product detail     | medium     |
| B6  | `https://www.digikey.in/en/products/detail/tdk-corporation/BCL3520FT-100M-D/14634358`                                                           | product detail     | medium     |
| B7  | `https://www.sigmaaldrich.com/US/en/product/sigma/s9888`                                                                                        | product detail     | hard       |
| B8  | `https://www.rockauto.com/en/catalog/ford,2024,f-150,3.5l+v6+turbocharged,3453880,brake+&+wheel+hub,brake+pad,1684`                             | product listing    | medium     |
| B9  | `https://www.build.com/kohler-k-22972/s1613088`                                                                                                 | product detail     | medium     |
| B10 | `https://www.thomann.de/gb/fender_am_pro_ii_strat_mn_pne.htm`                                                                                   | product detail     | medium     |
| B11 | `https://www.newegg.com/asrock-z790-taichi-lite/p/N82E16813162137`                                                                              | product detail     | medium     |
| B12 | `https://www.grainger.com/product/DAYTON-Industrial-Direct-Drive-Axial-1WDR1`                                                                   | product detail     | medium     |
| B13 | `https://www.rei.com/product/216223/osprey-atmos-ag-65-pack-mens`                                                                               | product detail     | medium     |
| B14 | `https://www.fastenal.com/product/details/0121148`                                                                                              | product detail     | medium     |
| B15 | `https://www.mscdirect.com/product/details/00227181`                                                                                            | product detail     | medium     |
| B16 | `https://www.uline.com/Product/Detail/H-1225/Industrial-Shelving/Wide-Span-Storage-Rack-72-x-24-x-72`                                           | product detail     | medium     |
| B17 | `https://www.zoro.com/dayton-hvac-motor-13-hp-1075-rpm-48-frame-voltage-115208-230-1wjp2/i/G0417734/`                                           | product detail     | medium     |
| B18 | `https://www.automationdirect.com/adc/shopping/catalog/programmable_controllers/click_series_programmable_control_system/plc_units/c0-12dd1e-d` | product detail     | hard       |
| B19 | `https://www.onlinemetals.com/en/buy/aluminum/aluminum-plate-6061-t651/pid/1210`                                                                | product detail     | medium     |
| B20 | `https://www.tequipment.net/Rigol/DS1102Z-E/Digital-Oscilloscopes/`                                                                             | product detail     | medium     |
| B21 | `https://www.adafruit.com/product/5700`                                                                                                         | product detail     | easy       |
| B22 | `https://www.sparkfun.com/products/19030`                                                                                                       | product detail     | easy       |
| B23 | `https://www.parts-express.com/Dayton-Audio-UM18-22-18-Ultimax-DVC-Subwoofer-2-Ohms-Per-Co-295-518`                                             | product detail     | medium     |
| B24 | `https://www.crutchfield.com/p_500S2W8/Alpine-S2-W8D4.html`                                                                                     | product detail     | medium     |
| B25 | `https://www.backcountry.com/arc-teryx-beta-lt-jacket-mens`                                                                                     | product detail     | medium     |
| B26 | `https://www.evo.com/snowboards/lib-tech-skate-banana-btx-snowboard`                                                                            | product detail     | medium     |
| B27 | `https://www.wayfair.com/furniture/pdp/allmodern-hailey-84-vegan-leather-sofa-w004245607.html`                                                  | product detail     | hard       |
| B28 | `https://www.westelm.com/products/anton-solid-wood-dining-table-h4231/`                                                                         | product detail     | medium     |
| B29 | `https://www.ikea.com/us/en/p/dirigera-hub-for-smart-products-white-smart-50503414/`                                                            | product detail     | hard       |
| B30 | `https://www.printful.com/custom/mens/t-shirts/unisex-staple-t-shirt-bella-canvas-3001`                                                         | product detail     | easy       |
| B31 | `https://www.grizzly.com/products/grizzly-10-2-hp-hybrid-table-saw/g0771z`                                                                      | product detail     | medium     |

---

## Section C — Pagination / Scroll Patterns

| #   | URL                                                           | Pattern                            | Difficulty |
| --- | ------------------------------------------------------------- | ---------------------------------- | ---------- |
| C1  | `https://www.amazon.in/s?k=shoes`                             | numbered pagination + query params | hard       |
| C2  | `https://www.flipkart.com/search?q=mobiles`                   | numbered pagination                | hard       |
| C3  | `https://www.myntra.com/shoes`                                | numbered pagination                | hard       |
| C4  | `https://www.ajio.com/men-shoes/c/830207`                     | numbered pagination                | hard       |
| C5  | `https://www.nykaa.com/makeup/c/12`                           | numbered pagination                | medium     |
| C6  | `https://www.snapdeal.com/products/mens-footwear`             | numbered pagination                | medium     |
| C7  | `https://in.pinterest.com/search/pins/?q=shoes`               | infinite scroll                    | hard       |
| C8  | `https://unsplash.com/s/photos/shoes`                         | infinite scroll                    | hard       |
| C9  | `https://www.behance.net/search/projects?search=shoes`        | infinite scroll                    | medium     |
| C10 | `https://www2.hm.com/en_in/men/products/shoes.html`           | load-more button                   | hard       |
| C11 | `https://www.zara.com/in/en/man-shoes-l769.html`              | load-more button                   | hard       |
| C12 | `https://www.asos.com/men/shoes-boots-trainers/cat/?cid=4209` | load-more button                   | hard       |
| C13 | `https://www.ikea.com/in/en/cat/chairs-fu002/`                | lazy load + viewport               | hard       |
| C14 | `https://www.target.com/c/shoes/-/N-55b0`                     | mixed pagination + infinite scroll | hard       |
| C15 | `https://www.walmart.com/browse/clothing/men/5438_133197`     | lazy load + anti-bot               | hard       |

---

## Section D — Jobs (ATS Boards)

| #   | URL                                                          | ATS        | Difficulty |
| --- | ------------------------------------------------------------ | ---------- | ---------- |
| 27  | `https://boards.greenhouse.io/embed/job_board?for=stripe`    | Greenhouse | easy       |
| 28  | `https://boards.greenhouse.io/embed/job_board?for=doordash`  | Greenhouse | easy       |
| 29  | `https://boards.greenhouse.io/embed/job_board?for=notion`    | Greenhouse | easy       |
| 30  | `https://boards.greenhouse.io/embed/job_board?for=figma`     | Greenhouse | easy       |
| 31  | `https://jobs.lever.co/reddit`                               | Lever      | easy       |
| 32  | `https://jobs.lever.co/figma`                                | Lever      | easy       |
| 33  | `https://jobs.lever.co/notion`                               | Lever      | easy       |
| 34  | `https://jobs.lever.co/vercel`                               | Lever      | easy       |
| 35  | `https://jobs.lever.co/linear`                               | Lever      | easy       |
| 36  | `https://remotive.com/remote-jobs`                           | Remotive   | medium     |
| 37  | `https://remotive.com/remote-jobs/software-dev`              | Remotive   | medium     |
| 38  | `https://remotive.com/api/remote-jobs`                       | JSON API   | easy       |
| 39  | `https://remotive.com/api/remote-jobs?category=software-dev` | JSON API   | easy       |
| 40  | `https://remoteok.com/api`                                   | JSON API   | easy       |
| 41  | `https://remoteok.com/remote-dev-jobs`                       | RemoteOK   | medium     |
| 42  | `https://remoteok.com/remote-react-jobs`                     | RemoteOK   | medium     |
| 43  | `https://news.ycombinator.com/jobs`                          | HN         | easy       |
| 44  | `https://walmart.wd5.myworkdayjobs.com/WalmartExternal`      | Workday    | hard       |
| 45  | `https://disney.wd5.myworkdayjobs.com/disneycareer`          | Workday    | hard       |
| 46  | `https://target.wd5.myworkdayjobs.com/TargetCareers`         | Workday    | hard       |
| 47  | `https://careers.homedepot.com/job-search-results/`          | custom     | hard       |
| 48  | `https://jobs.lowes.com/job-search-results/`                 | custom     | hard       |
| 49  | `https://careers.mcdonalds.com/us-restaurants`               | custom     | hard       |
| 50  | `https://www.dice.com/jobs?q=python&location=Remote`         | Dice       | hard       |

---

## Section E — Jobs (Niche Boards)

Individual job detail pages and niche boards — useful for JS-rendered job description extraction.

| #   | URL                                                                                           | Board          | Difficulty |
| --- | --------------------------------------------------------------------------------------------- | -------------- | ---------- |
| E1  | `https://himalayas.app/jobs/product-designer/runway`                                          | Himalayas      | medium     |
| E2  | `https://himalayas.app/jobs/principal-product-success-architect/servicenow`                   | Himalayas      | medium     |
| E3  | `https://himalayas.app/jobs/ml-scientist/mercor`                                              | Himalayas      | medium     |
| E4  | `https://himalayas.app/jobs/senior-data-analytics-engineer/betsol`                            | Himalayas      | medium     |
| E5  | `https://himalayas.app/jobs/senior-client-success-manager-strategic-accounts/rithum`          | Himalayas      | medium     |
| E6  | `https://climatebase.org/job/71829304/senior-software-engineer-managed-ai-ai-model-lifecycle` | Climatebase    | medium     |
| E7  | `https://climatebase.org/job/71829305/principal-engineer-ai-model-lifecycle`                  | Climatebase    | medium     |
| E8  | `https://climatebase.org/job/71829308/director-of-product-management-muon-halo`               | Climatebase    | medium     |
| E9  | `https://climatebase.org/job/71829309/technical-project-developer`                            | Climatebase    | medium     |
| E10 | `https://climatebase.org/job/71829310/real-estate-strategy-manager`                           | Climatebase    | medium     |
| E11 | `https://climatebase.org/job/71829311/enterprise-cloud-security-engineer`                     | Climatebase    | medium     |
| E12 | `https://climatebase.org/job/63706324/general-applicant-2026`                                 | Climatebase    | medium     |
| E13 | `https://read.cv/teams/linear/jobs/product-designer`                                          | Read.cv        | medium     |
| E14 | `https://contra.com/opportunity/senior-frontend-engineer-contract`                            | Contra         | medium     |
| E15 | `https://www.levels.fyi/jobs/software-engineer/google/l4`                                     | Levels.fyi     | medium     |
| E16 | `https://relocate.me/germany/berlin/delivery-hero/senior-frontend-developer-react-3677`       | Relocate.me    | medium     |
| E17 | `https://www.workatastartup.com/jobs/founder-associate-at-replit`                             | WorkAtAStartup | medium     |
| E18 | `https://www.ycombinator.com/jobs/role/software-engineer`                                     | YC             | medium     |
| E19 | `https://wellfound.com/jobs/2864501-senior-software-engineer`                                 | Wellfound      | medium     |
| E20 | `https://arc.dev/remote-jobs/senior-backend-developer`                                        | Arc.dev        | medium     |
| E21 | `https://weworkremotely.com/remote-jobs/full-stack-developer-ruby-on-rails`                   | WWR            | medium     |
| E24 | `https://nofluffjobs.com/job/senior-backend-developer-java-remote`                            | NoFluffJobs    | medium     |
| E26 | `https://cutshort.io/jobs/startup-jobs`                                                       | Cutshort       | medium     |
| E28 | `https://www.workingnomads.com/jobs`                                                          | WorkingNomads  | medium     |
