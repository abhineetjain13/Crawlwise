# Regression Baseline v1 Results

- Manifest: `backend/test_site_sets/regression_baseline_v1.json`
- Harness report: `backend/artifacts/test_sites_acceptance/20260423T025250Z__full_pipeline__test_sites_tail.json`
- Backend verification: `backend/.venv/Scripts/python.exe -m pytest tests -q` => `601 passed, 4 skipped`

## Manifest Summary

- Total sites: 50
- `must_pass` + `hard`: 25
- `must_pass` + `soft`: 9
- `tracked` + `soft`: 16

## Harness Summary

- Overall status: `ok=50` `failed=0` `tracked_issues=0`
- Failure modes: `{"blocked": 2, "detail_extraction_empty": 4, "error": 2, "listing_extraction_empty": 3, "success": 39}`
- Quality verdicts: `{"bad_output": 14, "blocked": 2, "good": 34}`
- Observed failure modes: `{"bad_output": 5, "blocked": 2, "control_good": 34, "listing_chrome_noise": 5, "shell_false_success": 4}`

## Soft-Gated / Tracked Sites

| url | bucket | gate | failure_mode | observed_failure_mode | records |
|---|---|---|---:|
| https://www.reverb.com/marketplace?product_type=electric-guitars | tracked | soft | success | listing_chrome_noise | 1 |
| https://www.karenmillen.com/eu/categories/womens-trousers | tracked | soft | success | listing_chrome_noise | 1 |
| https://www.rockler.com/jessem-mast-r-lift-ii-excel-router-lift | tracked | soft | success | listing_chrome_noise | 1 |
| https://www.vitacost.com/now-foods-ultra-omega-3-fish-oil-500-epa-250-dha-180-softgels | tracked | soft | success | listing_chrome_noise | 1 |
| https://www.vitacost.com/now | tracked | soft | error | bad_output | 0 |
| https://www.firstcry.com/sets-and--suits/6/166?scat=166&gender=girl,unisex&ref2=menu_dd_girl-fashion_sets-and-suits_H | tracked | soft | error | bad_output | 0 |
| https://www.govplanet.com/for-sale/equipment | tracked | soft | listing_extraction_empty | bad_output | 0 |
| https://www.uline.com/BL_8421/Boxes | tracked | soft | listing_extraction_empty | bad_output | 0 |
| https://www.customink.com/products/sweatshirts/hoodies/71 | tracked | soft | listing_extraction_empty | bad_output | 0 |
| https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html?trksrc=navbar&trkid=l2 | must_pass | soft | success | control_good | 61 |
| https://www.dyson.in/vacuum-cleaners/cord-free | must_pass | soft | success | control_good | 7 |
| https://www.kitchenaid.com/countertop-appliances/food-processors/food-processor-and-chopper-products | must_pass | soft | success | control_good | 19 |
| https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos | must_pass | soft | success | control_good | 23 |
| https://www.lafayette148ny.com/media/sitemap-products.xml | tracked | soft | success | listing_chrome_noise | 100 |
| https://www.abebooks.com/9780132350884/Clean-Code-Handbook-Agile-Software-0132350882/plp | must_pass | soft | success | control_good | 1 |
| https://www.thriftbooks.com/w/the-pragmatic-programmer_david-thomas_andrew-hunt/286697/ | tracked | soft | detail_extraction_empty | shell_false_success | 0 |
| https://practicesoftwaretesting.com/#/product/01HB | tracked | soft | detail_extraction_empty | shell_false_success | 0 |
| https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html | must_pass | soft | success | control_good | 1 |
| https://www.bhphotovideo.com/c/product/1666763-REG/ttartisan_a34b_17mm_f_1_4_lens_for.html | must_pass | soft | success | control_good | 1 |
| https://www.customink.com/t-shirts/medic-shirts | tracked | soft | detail_extraction_empty | shell_false_success | 0 |
| https://www.backmarket.com/en-us/p/iphone-14-128-gb-midnight/dba71a89-1e8e-4278-967e-0ef1c0d05f31 | must_pass | soft | success | control_good | 1 |
| https://www.ifixit.com/products/macbook-pro-15-inch-retina-display-mid-2015-battery | tracked | soft | detail_extraction_empty | shell_false_success | 0 |
| https://www.discogs.com/release/1529440 | must_pass | soft | success | control_good | 1 |
| https://www.rockler.com/jessem-mast-r-lift-ii-excel-router-lift | tracked | soft | blocked | blocked | 0 |
| https://www.etsy.com/listing/1210769675/black-popular-and-in-demand-unisex-t | tracked | soft | blocked | blocked | 0 |
