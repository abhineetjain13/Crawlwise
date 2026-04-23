# Baseline Triage

Baseline source window: persisted crawl runs created between 2026-04-23 00:49 UTC to 2026-04-23 01:12 UTC (run IDs 212-259).

| url | surface | bucket | record_count | confidence | root_cause_note |
|---|---|---|---:|---:|---|
| https://www.ifixit.com/Parts | ecommerce_listing | LISTING_PARTIAL | 25 | - | price coverage 24/25; detail URLs 24/25; noise records 1 |
| https://www.abebooks.com/servlet/SearchResults?kn=python&pt=book | ecommerce_listing | LISTING_PARTIAL | 30 | - | price coverage 26/30; detail URLs 30/30; noise records 4 |
| https://www.thriftbooks.com/browse/?b.search=science | ecommerce_listing | LISTING_PARTIAL | 100 | - | price coverage 50/100; detail URLs 100/100; noise records 50 |
| https://www.thomann.de/gb/guitars.html | ecommerce_listing | LISTING_PARTIAL | 73 | - | price coverage 72/73; detail URLs 73/73; noise records 1 |
| https://www.rockler.com/wood/exotic-lumber | ecommerce_listing | LISTING_PARTIAL | 2 | - | price coverage 0/2; detail URLs 2/2; noise records 2 |
| https://www.govplanet.com/for-sale/equipment | ecommerce_listing | LISTING_ZERO | 0 | - | browser escalated; listing card detection failed after render |
| https://www.instahyre.com/search-jobs | ecommerce_listing | LISTING_PARTIAL | 20 | - | price coverage 0/20; detail URLs 20/20; noise records 20 |
| https://www.thomann.de/gb/shure_sm58_lc.htm | ecommerce_detail | DETAIL_OK | 1 | 0.462 | price present=True; confidence=0.462 |
| https://www.thomann.de/gb/akg_k702.htm | ecommerce_detail | DETAIL_OK | 1 | 0.572 | price present=True; confidence=0.572 |
| https://www.discogs.com/release/1529440 | ecommerce_detail | DETAIL_SHELL | 1 | 0.378 | confidence=0.378; title="Error 404 ." |
| https://www.discogs.com/release/249504 | ecommerce_detail | DETAIL_OK | 1 | 0.720 | price present=True; confidence=0.72 |
| https://www.ifixit.com/products/iphone-14-battery | ecommerce_detail | DETAIL_OK | 1 | 0.675 | price present=True; confidence=0.675 |
| https://www.ifixit.com/products/macbook-pro-15-inch-retina-display-mid-2015-battery | ecommerce_detail | DETAIL_SHELL | 1 | 0.126 | confidence=0.126; title="macbook pro 15 inch retina display mid 2015 battery" |
| https://www.vitacost.com/now-foods-ultra-omega-3-fish-oil-500-epa-250-dha-180-softgels | ecommerce_listing | LISTING_GARBAGE | 1 | - | price missing; short-circuit source=visual_listing |
| https://www.thriftbooks.com/w/the-pragmatic-programmer_david-thomas_andrew-hunt/286697/ | ecommerce_listing | LISTING_PARTIAL | 8 | - | price coverage 1/8; detail URLs 8/8; noise records 7 |
| https://www.abebooks.com/9780132350884/Clean-Code-Handbook-Agile-Software-0132350882/plp | ecommerce_listing | LISTING_PARTIAL | 58 | - | price coverage 18/58; detail URLs 40/58; noise records 58 |
| https://www.rockler.com/jessem-mast-r-lift-ii-excel-router-lift | ecommerce_listing | LISTING_GARBAGE | 1 | - | title matches page <title>; price missing; short-circuit source=structured_listing |
| https://www.backmarket.com/en-us/p/iphone-14-128-gb-midnight/dba71a89-1e8e-4278-967e-0ef1c0d05f31 | ecommerce_detail | DETAIL_SHELL | 1 | 0.276 | confidence=0.276; title="iPhone" |
| https://zadig-et-voltaire.com/eu/uk/c/tshirts-sweatshirts-for-men-127 | ecommerce_listing | LISTING_PARTIAL | 48 | - | price coverage 0/48; detail URLs 48/48; noise records 48 |
| https://31philliplim.com/collections | ecommerce_listing | LISTING_OK | 100 | - | price coverage 100/100; detail URLs 100/100 |
| https://www.lafayette148ny.com/media/sitemap-products.xml | ecommerce_listing | LISTING_PARTIAL | 100 | - | price coverage 0/100; detail URLs 100/100; noise records 100 |
| https://ar.puma.com/lo-mas-vendido | ecommerce_listing | LISTING_OK | 16 | - | price coverage 16/16; detail URLs 16/16 |
| https://www.karenmillen.com/eu/categories/womens-trousers | ecommerce_listing | LISTING_GARBAGE | 1 | - | price missing |
| https://www.ganni.com/en-gb/trainers/ | ecommerce_listing | LISTING_OK | 12 | - | price coverage 12/12; detail URLs 12/12 |
| https://www.phase-eight.com/clothing/dresses/ | ecommerce_listing | LISTING_OK | 58 | - | price coverage 58/58; detail URLs 58/58 |
| https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos | ecommerce_listing | LISTING_PARTIAL | 23 | - | price coverage 23/23; detail URLs 0/23; noise records 23 |
| https://savannahs.com/collections/all-boots | ecommerce_listing | LISTING_OK | 29 | - | price coverage 29/29; detail URLs 29/29 |
| https://www.kitchenaid.com/countertop-appliances/food-processors/food-processor-and-chopper-products | ecommerce_listing | LISTING_PARTIAL | 19 | - | price coverage 1/19; detail URLs 8/19; noise records 19 |
| https://www.dyson.in/vacuum-cleaners/cord-free | ecommerce_listing | LISTING_PARTIAL | 7 | - | price coverage 6/7; detail URLs 2/7; noise records 6 |
| https://www.grailed.com/categories/womenswear/blazers | ecommerce_listing | LISTING_OK | 78 | - | price coverage 78/78; detail URLs 78/78 |
| https://www.desertcart.in/search?query=Nutrition+%26+Healthy+Eating | ecommerce_listing | LISTING_OK | 43 | - | price coverage 43/43; detail URLs 43/43 |
| https://www.firstcry.com/sets-and--suits/6/166?scat=166&gender=girl,unisex&ref2=menu_dd_girl-fashion_sets-and-suits_H | ecommerce_listing | LISTING_ZERO | 0 | - | browser escalated; listing card detection failed after render |
| https://www.stadiumgoods.com/collections/adidas-shoes | ecommerce_listing | BLOCKED | 0 | - | bot protection / rate limiting detected |
| https://www2.hm.com/en_in/men/shoes/view-all.html | ecommerce_detail | BLOCKED | 0 | - | verdict=error; title="Shoes For Men \| Boots, Trainers & Smart Shoes \| H&M IN" |
| https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html?trksrc=navbar&trkid=l2 | ecommerce_detail | BLOCKED | 0 | - | verdict=empty; title="Women Pajama Sets - Buy Pyjama Sets Online in India \| Zivame" |
| https://www2.hm.com/en_in/men/shoes/view-all.html | ecommerce_listing | LISTING_OK | 19 | - | price coverage 19/19; detail URLs 19/19 |
| https://www.zivame.com/sleepwear-nightwear/sleep-pyjama-sets.html?trksrc=navbar&trkid=l2 | ecommerce_listing | LISTING_PARTIAL | 61 | - | price coverage 56/61; detail URLs 61/61; noise records 5 |
| https://www.zivame.com/zivame-knit-cotton-pyjama-set-burnt-coral.html?productId=867563&trksrc=category&trkid=Nightwear | ecommerce_detail | BLOCKED | 0 | - | verdict=empty; redirected to https://www.zivame.com/promo-2.html?products=newarrival&sortorder=desc&sortby=newarrival&brands=Zivame&category=bras,nightwear,activewear,shapewear,panties&topsku=ZPCTB03-Silver%20Pink,ZPCTB03-Tapshoe,ZI6554-Chambray%20Blue,ZI654P-PINKLEOPARD,ZI19J6-Purple,ZI19E7-Red%20Violet,ZI655I-Gilf%20Stream,ZI651O-Cameo%20Pink,ZI19D6-Red%20Dahlia,ZI19CT-Black,ZI19D4-Chocolate%20Fondant,ZI651Y-Ethereal%20Gr,ZI19D6-Orion%20Blue,ZI19D7-Crystal%20Pink,ZI651X-Windward%20Bl,ZI652E-Barely%20Pink,ZI199J-Claret%20Red,ZI19FM-Grey,ZC45C4-Riviera,ZC45BM-Darkpurple,ZI19DA-Silver%20Bullet,ZI199J-Orion%20Blue&trksrc=navbar&trkid=l1; title="Buy Zivame Floral Hush Knit Cotton Pyjama Set - Burnt Coral at Rs.848 online \| Nightwear online" |
| https://www.zivame.com/zivame-knit-poly-pyjama-set-salsa.html?productId=869459&trksrc=category&trkid=Nightwear | ecommerce_detail | BLOCKED | 0 | - | verdict=empty; redirected to https://www.zivame.com/promo-2.html?products=newarrival&sortorder=desc&sortby=newarrival&brands=Zivame&category=bras,nightwear,activewear,shapewear,panties&topsku=ZPCTB03-Silver%20Pink,ZPCTB03-Tapshoe,ZI6554-Chambray%20Blue,ZI654P-PINKLEOPARD,ZI19J6-Purple,ZI19E7-Red%20Violet,ZI655I-Gilf%20Stream,ZI651O-Cameo%20Pink,ZI19D6-Red%20Dahlia,ZI19CT-Black,ZI19D4-Chocolate%20Fondant,ZI651Y-Ethereal%20Gr,ZI19D6-Orion%20Blue,ZI19D7-Crystal%20Pink,ZI651X-Windward%20Bl,ZI652E-Barely%20Pink,ZI199J-Claret%20Red,ZI19FM-Grey,ZC45C4-Riviera,ZC45BM-Darkpurple,ZI19DA-Silver%20Bullet,ZI199J-Orion%20Blue&trksrc=navbar&trkid=l1; title="Buy Zivame Smurf Collection Knit Poly Pyjama Set - Salsa at Rs.1048 online \| Nightwear online" |
| https://www2.hm.com/en_in/productpage.1317259001.html | ecommerce_detail | BLOCKED | 0 | - | verdict=blocked; bot protection / rate limiting detected |
| https://www2.hm.com/en_in/productpage.1331404001.html | ecommerce_detail | BLOCKED | 0 | - | verdict=blocked; bot protection / rate limiting detected; title="Access Denied" |
| https://www.myntra.com/hand-towels | ecommerce_listing | LISTING_OK | 50 | - | price coverage 50/50; detail URLs 50/50 |
| https://www.reverb.com/marketplace?product_type=electric-guitars | ecommerce_listing | LISTING_GARBAGE | 1 | - | price missing |
| https://www.vitacost.com/now | ecommerce_listing | LISTING_ZERO | 0 | - | browser escalated; listing card detection failed after render |
| https://web-scraping.dev/product/1 | ecommerce_detail | DETAIL_MISSING_VARIANTS | 1 | 0.900 | variant DOM cues present but variant_axes empty; early_exit=none |
| https://www.myntra.com/hand-towels | ecommerce_listing | LISTING_OK | 50 | - | price coverage 50/50; detail URLs 50/50 |
| https://zadig-et-voltaire.com/eu/uk/c/tshirts-sweatshirts-for-men-127 | ecommerce_listing | LISTING_OK | 48 | - | price coverage 48/48; detail URLs 48/48 |
| https://www.karenmillen.com/eu/categories/womens-trousers | ecommerce_listing | LISTING_GARBAGE | 1 | - | price missing |
| https://www.reverb.com/marketplace?product_type=electric-guitars | ecommerce_listing | LISTING_GARBAGE | 1 | - | price missing |
| https://zadig-et-voltaire.com/eu/uk/p/JMTS01718021/t-shirt-men-teddy-t-shirt-carbone-jmts01718 | ecommerce_detail | DETAIL_OK | 1 | 0.900 | price present=True; confidence=0.9 |
| https://zadig-et-voltaire.com/eu/uk/p/JMTS01779103/mens-white-tommy-t-shirt | ecommerce_detail | DETAIL_OK | 1 | 0.900 | price present=True; confidence=0.9 |

## Summary

| bucket | count |
|---|---:|
| BLOCKED | 7 |
| DETAIL_MISSING_VARIANTS | 1 |
| DETAIL_OK | 6 |
| DETAIL_SHELL | 3 |
| LISTING_GARBAGE | 6 |
| LISTING_OK | 11 |
| LISTING_PARTIAL | 14 |
| LISTING_ZERO | 3 |
