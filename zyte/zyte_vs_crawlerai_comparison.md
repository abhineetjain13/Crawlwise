# Zyte vs CrawlerAI Comparison

- Total Zyte URLs: 51
- Direct matches: 48
- Forced matches: 0
- Missing CrawlerAI records: 3
- Zyte baseline errors: 6
- Orphaned CrawlerAI records: 0
- **Critical data quality issues: 18**

## 🚨 Critical Data Quality Issues

- **scalar_field_pollution**: 5
- **availability_mismatch**: 4
- **price_outlier**: 4
- **identity_mismatch**: 3
- **variant_axis_pollution**: 3

## All Failure Modes

- zyte_error: 6
- scalar_field_pollution: 5
- availability_mismatch: 4
- price_outlier: 4
- crawler_missing_record: 3
- identity_mismatch: 3
- variant_axis_pollution: 3

## Architecture Buckets

- variant_extraction: 7
- baseline_gap: 6
- availability_extraction: 4
- price_extraction: 4
- identity_extraction: 3
- record_alignment: 3

## URL-wise Results

### 01. https://www.sneakersnstuff.com/products/dime-soft-rock-crewneck-dime2sp2542blk
- **CRITICAL**: scalar_field_pollution
- alignment: matched
- zyte_status: error
- crawler_url: https://www.sneakersnstuff.com/products/dime-soft-rock-crewneck-dime2sp2542blk
- failure_modes: zyte_error, scalar_field_pollution
- architecture_buckets: baseline_gap, variant_extraction
- mismatches:
  - color_looks_like_id: crawler=BLACK | zyte=None

### 02. https://www.samsclub.com/ip/Scotch-Heavy-Duty-Shipping-Packaging-Tape-Dispensers-1-88-x-27-7-yd-6-Pack/5113185138?classType=REGULAR
- alignment: crawler_missing
- zyte_status: ok
- crawler_url: missing
- failure_modes: crawler_missing_record
- architecture_buckets: record_alignment

### 03. https://www.goat.com/sneakers/dunk-low-black-white-dd1391-100
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.goat.com/sneakers/dunk-low-black-white-dd1391-100
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=DD1391 100 | zyte=2021

### 04. https://stockx.com/nike-dunk-low-retro-white-black-2021
- **CRITICAL**: availability_mismatch
- alignment: matched
- zyte_status: ok
- crawler_url: https://stockx.com/nike-dunk-low-retro-white-black-2021
- failure_modes: availability_mismatch
- architecture_buckets: availability_extraction
- mismatches:
  - title: crawler=Nike Dunk Low Retro White Black Panda | zyte=Nike Dunk Low Retro
  - brand: crawler=Nike | zyte=StockX Logo
  - barcode: crawler=59302223 | zyte=00194502876055
  - availability: crawler=in_stock | zyte=out_of_stock

### 05. https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - title: crawler=Nike Air Force 1 '07 Men's Shoes | zyte=Nike Air Force 1 '07

### 06. https://www.amazon.com/dp/B08J5F3G18
- **CRITICAL**: price_outlier
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.amazon.com/dp/B08J5F3G18
- failure_modes: price_outlier
- architecture_buckets: price_extraction
- mismatches:
  - price: crawler=135977.51 | zyte=1849.99

### 07. https://www.apple.com/shop/buy-iphone/iphone-16
- **CRITICAL**: price_outlier
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.apple.com/shop/buy-iphone/iphone-16
- failure_modes: price_outlier
- architecture_buckets: price_extraction
- mismatches:
  - title: crawler=iPhone 16 | zyte=Buy iPhone 16
  - original_price: crawler=729.00 | zyte=29.12

### 08. https://kith.com/collections/mens-footwear-sneakers/products/st40002-02000
- **CRITICAL**: identity_mismatch
- alignment: matched
- zyte_status: ok
- crawler_url: https://kith.com/collections/mens-footwear-sneakers/products/st40002-02000
- failure_modes: identity_mismatch
- architecture_buckets: identity_extraction
- mismatches:
  - title: crawler=SATISFY TheROCKER - Jet Black | zyte=TheROCKER
  - sku: crawler=13876003 | zyte=8286347526272
  - color: crawler=Nocturnal | zyte=Jet Black

### 09. https://www.farfetch.com/in/shopping/men/philipp-plein-leather-disco-biker-jacket-item-18497263.aspx
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.farfetch.com/in/shopping/men/philipp-plein-leather-disco-biker-jacket-item-18497263.aspx
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=14080 | zyte=18497263

### 10. https://www.ssense.com/en-us/men/product/willy-chavarria/brown-ruff-rider-leather-jacket/19072301
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.ssense.com/en-us/men/product/willy-chavarria/brown-ruff-rider-leather-jacket/19072301
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=261232M181023 | zyte=19072301

### 11. https://www.costco.com/p/-/sleep-number-ultimate-12-mattress/4201005351?langId=-1
- alignment: matched
- zyte_status: error
- crawler_url: https://www.costco.com/p/-/sleep-number-ultimate-12-mattress/4201005351?langId=-1
- failure_modes: zyte_error
- architecture_buckets: baseline_gap

### 12. https://www.target.com/p/tobago-stripe-duvet-cover-set-levtex-home/-/A-1002150739?preselect=1002150742#lnk=sametab
- **CRITICAL**: scalar_field_pollution
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.target.com/p/tobago-stripe-duvet-cover-set-levtex-home/-/A-1002150739?preselect=1002150742#lnk=sametab
- failure_modes: scalar_field_pollution
- architecture_buckets: variant_extraction
- mismatches:
  - size_looks_polluted: crawler=twin/twin xl | zyte=twin/twin xl

### 13. https://www.walmart.com/ip/Apple-AirPods-with-Charging-Case-2nd-Generation/604342441
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.walmart.com/ip/Apple-AirPods-with-Charging-Case-2nd-Generation/604342441
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - color: crawler=White | zyte=White - Out of stock

### 14. https://www.lowes.com/pd/Minka-Lavery-Lansdale-Sand-Black-Transitional-Opal-Glass-Lantern-Pendant-Light/1001420790
- alignment: matched
- zyte_status: error
- crawler_url: https://www.lowes.com/pd/Minka-Lavery-Lansdale-Sand-Black-Transitional-Opal-Glass-Lantern-Pendant-Light/1001420790
- failure_modes: zyte_error
- architecture_buckets: baseline_gap

### 15. https://www.homedepot.com/p/MSI-Yellow-Pebbles-12-in-x-12-in-Polished-Quartzite-Floor-and-Wall-Tile-10-sq-ft-case-LPEBMYEL1212POL/202515091
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.homedepot.com/p/MSI-Yellow-Pebbles-12-in-x-12-in-Polished-Quartzite-Floor-and-Wall-Tile-10-sq-ft-case-LPEBMYEL1212POL/202515091
- failure_modes: ok
- architecture_buckets: -

### 16. https://www.ulta.com/p/shape-tape-concealer-xlsImpprod14251035
- **CRITICAL**: scalar_field_pollution
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.ulta.com/p/shape-tape-concealer-xlsImpprod14251035
- failure_modes: scalar_field_pollution
- architecture_buckets: variant_extraction
- mismatches:
  - size_looks_polluted: crawler=0.33 oz | zyte=0.33 oz
  - title: crawler=Shape Tape Concealer - 22N Light Neutral | zyte=Shape Tape Concealer
  - sku: crawler=2501218 | zyte=xlsImpprod14251035
  - color: crawler=22N Light Neutral | zyte=22N Light Neutral light skin with a balance of warm & cool undertones

### 17. https://www.dickssportinggoods.com/p/birkenstock-womens-arizona-big-buckle-soft-footbed-sandals-25birwcasuwrznbgbcegp/25birwcasuwrznbgbcegp?color=Sandcastle
- alignment: crawler_missing
- zyte_status: error
- crawler_url: missing
- failure_modes: crawler_missing_record, zyte_error
- architecture_buckets: baseline_gap, record_alignment

### 18. https://www.jdsports.co.uk/product/pink-adidas-originals-classic-shorts/19741988/
- alignment: matched
- zyte_status: error
- crawler_url: https://www.jdsports.co.uk/product/pink-adidas-originals-classic-shorts/19741988/
- failure_modes: zyte_error
- architecture_buckets: baseline_gap

### 19. https://shop.lululemon.com/p/men-joggers/ABC-Jogger/_/prod8530240
- alignment: matched
- zyte_status: ok
- crawler_url: https://shop.lululemon.com/p/men-joggers/Abc-Jogger/_/prod8530240
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=147151490 | zyte=prod8530240

### 20. https://in.puma.com/in/en/pd/speedcat-sneakers/406329?swatch=02
- alignment: matched
- zyte_status: ok
- crawler_url: https://in.puma.com/in/en/pd/speedcat-sneakers/406329?swatch=02
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - brand: crawler=PUMA | zyte=PUMA.com
  - sku: crawler=4069159504308 | zyte=406329_02

### 21. https://www.adidas.com/us/stan-smith-shoes/M20324.html
- alignment: crawler_missing
- zyte_status: ok
- crawler_url: missing
- failure_modes: crawler_missing_record
- architecture_buckets: record_alignment

### 22. https://www.sephora.com/product/colorful-eyeshadow-P515026?skuId=2820108&icid2=products%20grid:p515026:product
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.sephora.com/product/colorful-eyeshadow-P515026
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=COLORFUL-EYESHADOW-P515026 | zyte=2820108

### 23. https://www.zappos.com/kratos/p/womens-hoka-bondi-9-berry-jam-berry-patch/product/9984296/color/318988?zlfid=191&ref=pd_search_nr-1-bqcp_1
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.zappos.com/p/womens-hoka-bondi-9-berry-jam-berry-patch/product/9984296/color/318988
- failure_modes: ok
- architecture_buckets: -

### 24. https://www.macys.com/shop/product/tommy-hilfiger-mens-hiday-casualized-hybrid-oxfords?ID=19116329&swatchColor=Black
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.macys.com/shop/product/tommy-hilfiger-mens-hiday-casualized-hybrid-oxfords?ID=19116329
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=199277621121USA | zyte=19116329
  - color: crawler=Black/Black | zyte=9372768

### 25. https://www.bhphotovideo.com/c/product/1882297-REG/cozyla_cd_8v543f0_white_us_32_4k_calendar_gen2_white.html
- **CRITICAL**: availability_mismatch
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.bhphotovideo.com/c/product/1882297-REG/cozyla_cd_8v543f0_white_us_32_4k_calendar_gen2_white.html
- failure_modes: availability_mismatch
- architecture_buckets: availability_extraction
- mismatches:
  - availability: crawler=in_stock | zyte=out_of_stock

### 26. https://www.asos.com/us/asos-curve/asos-design-curve-lightweight-pull-on-barrel-pants-in-darkwash/prd/210397084#colourWayId-210397088
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.asos.com/us/asos-curve/asos-design-curve-lightweight-pull-on-barrel-pants-in-darkwash/prd/210397084
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=155394360 | zyte=210397084

### 27. https://www.wayfair.com/furniture/pdp/flexsteel-bryce-power-reclining-sofa-with-power-headrest-xtya1522.html?piid=94673717&auctionId=db4b38eb-7955-4fc9-8d81-0dae00f68111&trackingId={%22adType%22:%22WSP%22,%22auctionId%22:%22db4b38eb-7955-4fc9-8d81-0dae00f68111%22}&adTypeId=1
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.wayfair.com/furniture/pdp/flexsteel-bryce-power-reclining-sofa-with-power-headrest-xtya1522.html?piid=94673717&auctionId=db4b38eb-7955-4fc9-8d81-0dae00f68111&trackingId={"adType":"WSP","auctionId":"db4b38eb-7955-4fc9-8d81-0dae00f68111"}&adTypeId=1
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - title: crawler=Flexsteel Bryce Power Reclining Sofa with Power Headrest & Reviews | Wayfair | zyte=Bryce Power Reclining Sofa with Power Headrest

### 28. https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html?v1=527078510
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - brand: crawler=ZARA | zyte=NEW
  - sku: crawler=527078510-104-2 | zyte=p04424306
  - size: crawler=S | zyte=4424/306/104

### 29. https://us.frankbody.com/products/original-coffee-scrub
- alignment: matched
- zyte_status: ok
- crawler_url: https://us.frankbody.com/products/original-coffee-scrub
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - brand: crawler=Frank Body | zyte=Frank Body | USA
  - sku: crawler=10080453 | zyte=704120772

### 30. https://colourpop.com/products/going-coconuts-eyeshadow-palette
- **CRITICAL**: identity_mismatch
- alignment: matched
- zyte_status: ok
- crawler_url: https://colourpop.com/products/going-coconuts-eyeshadow-palette
- failure_modes: identity_mismatch
- architecture_buckets: identity_extraction
- mismatches:
  - title: crawler=Going Coconuts | zyte=9-Pan Palette
  - sku: crawler=EyePalette-GoingCoconuts | zyte=4353268842578

### 31. https://www.fashionnova.com/products/just-vibes-strapless-pant-set-yellow?recommendationAttributionId=error-nosto-1-fallback-nosto-1-copy-1720644688978
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.fashionnova.com/products/just-vibes-strapless-pant-set-yellow
- failure_modes: ok
- architecture_buckets: -

### 32. https://www.puravidabracelets.com/products/black-seascape-stretch-bracelet?pr_prod_strat=e5_desc&pr_rec_id=3ef961ba9&pr_rec_pid=7216396632150&pr_ref_pid=7559267778646&pr_seq=uniform&variant=41298450153558
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.puravidabracelets.com/products/black-seascape-stretch-bracelet
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=50907BLCKO | zyte=7216396632150

### 33. https://www.untuckit.com/collections/shirts/products/cameron-wr-2
- **CRITICAL**: variant_axis_pollution
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.untuckit.com/collections/shirts/products/cameron-wr-2
- failure_modes: variant_axis_pollution
- architecture_buckets: variant_extraction
- mismatches:
  - variant_size_pollution: crawler=[{'fit': 'Slim Fit', 'sku': '40878BluSlmXS', 'url': 'https://www.untuckit.com/collections/shirts/products/cameron-wr-2?variant=39660288999502', 'size': 'X-Small', 'image_url': 'https://www.untuckit.com/cdn/shop/files/CAMERON-UNTUCKIT-LIGHT-BLUE-1.jpg?v=1771520506&width=1667', 'availability': 'out_of_stock'}, {'fit': 'Regular Fit', 'sku': '40878BluRegXL', 'url': 'https://www.untuckit.com/collections/shirts/products/cameron-wr-2?variant=39660289392718', 'size': 'X-Large', 'image_url': 'https://www.untuckit.com/cdn/shop/files/CAMERON-UNTUCKIT-LIGHT-BLUE-1.jpg?v=1771520506&width=1667', 'availability': 'in_stock'}, {'fit': 'Relaxed Fit', 'sku': '40878BluRelXL', 'url': 'https://www.untuckit.com/collections/shirts/products/cameron-wr-2?variant=39660289425486', 'size': 'X-Large', 'image_url': 'https://www.untuckit.com/cdn/shop/files/CAMERON-UNTUCKIT-LIGHT-BLUE-1.jpg?v=1771520506&width=1667', 'availability': 'in_stock'}, {'fit': 'Slim Fit', 'sku': '40878BluSlmXL', 'url': 'https://www.untuckit.com/collections/shirts/products/cameron-wr-2?variant=39660289458254', 'size': 'X-Large', 'image_url': 'https://www.untuckit.com/cdn/shop/files/CAMERON-UNTUCKIT-LIGHT-BLUE-1.jpg?v=1771520506&width=1667', 'availability': 'in_stock'}, {'fit': 'Tall Regular Fit', 'sku': '40878BluTreXL', 'url': 'https://www.untuckit.com/collections/shirts/products/cameron-wr-2?variant=39660289491022', 'size': 'X-Large', 'image_url': 'https://www.untuckit.com/cdn/shop/files/CAMERON-UNTUCKIT-LIGHT-BLUE-1.jpg?v=1771520506&width=1667', 'availability': 'in_stock'}] | zyte=[]
  - sku: crawler=40878BluRegSM | zyte=6698396614734
  - size: crawler=Small | zyte=S

### 34. https://www.decathlon.co.uk/p/pressurised-padel-balls-pb-speed-tri-pack/347273/m8804642
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.decathlon.co.uk/p/pressurised-padel-balls-pb-speed-tri-pack/347273/m8804642
- failure_modes: ok
- architecture_buckets: -

### 35. https://www.thomann.de/gb/akg_k702.htm
- alignment: matched
- zyte_status: error
- crawler_url: https://www.thomann.co.uk/akg_k702.htm
- failure_modes: zyte_error
- architecture_buckets: baseline_gap

### 36. https://www.discogs.com/release/249504
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.discogs.com/release/249504-Rick-Astley-Never-Gonna-Give-You-Up?redirected=true
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=SW1hZ2U6NjcxOTYzNw== | zyte=[r249504]

### 37. https://www.ifixit.com/products/iphone-16-plus-battery
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.ifixit.com/products/iphone-16-plus-battery
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - brand: crawler=iFixit | zyte=Aftermarket

### 38. https://www.vitacost.com/vitacost-vitamin-d3-mini-gels
- **CRITICAL**: scalar_field_pollution
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.vitacost.com/vitacost-vitamin-d3-mini-gels
- failure_modes: scalar_field_pollution
- architecture_buckets: variant_extraction
- mismatches:
  - size_looks_polluted: crawler=100 Softgels 200 Softgels 365 Softgels | zyte=1 Softgel
  - size: crawler=100 Softgels 200 Softgels 365 Softgels | zyte=1 Softgel

### 39. https://www.rockler.com/rockler-table-saw-crosscut-sled
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.rockler.com/rockler-table-saw-crosscut-sled
- failure_modes: ok
- architecture_buckets: -

### 40. https://www.backmarket.com/en-us/p/iphone-15-plus
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.backmarket.com/en-us/p/iphone-15-plus
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - brand: crawler=Apple | zyte=Back Market

### 41. https://31philliplim.com/collections/the-luna-bag-1/products/luna-1
- **CRITICAL**: scalar_field_pollution, variant_axis_pollution
- alignment: matched
- zyte_status: ok
- crawler_url: https://31philliplim.com/collections/the-luna-bag-1/products/luna-1
- failure_modes: scalar_field_pollution, variant_axis_pollution
- architecture_buckets: variant_extraction
- mismatches:
  - color_looks_like_id: crawler=LIPSTICK | zyte=LIPSTICK
  - size_looks_polluted: crawler=O/S | zyte=O/S
  - variant_size_pollution: crawler=[{'sku': 'AE26-B570-VRA-LI600', 'url': 'https://31philliplim.com/collections/the-luna-bag-1/products/luna-1?variant=51977352315194', 'size': 'O/S', 'color': 'LIPSTICK', 'price': '59400.00', 'image_url': 'https://cdn.shopify.com/s/files/1/0593/9809/5043/files/Luna_Bag_Red_Updated_1.png?v=1769811125'}, {'sku': 'AE26-B570-VRA-BA001', 'url': 'https://31philliplim.com/collections/the-luna-bag-1/products/luna-1?variant=51977352282426', 'size': 'O/S', 'color': 'BLACK', 'price': '59400.00', 'image_url': 'https://cdn.shopify.com/s/files/1/0593/9809/5043/files/Luna-BlackColorwayImage1__1.png?v=1769811735'}] | zyte=['0', '00', '10', '12', '2', '4', '6', '8']
  - sku: crawler=AE26-B570-VRA-LI600 | zyte=10065661296954

### 42. https://zadig-et-voltaire.com/eu/uk/p/JMTS01771443/t-shirt-teddyx-blue-sixtine
- **CRITICAL**: identity_mismatch
- alignment: matched
- zyte_status: ok
- crawler_url: https://zadig-et-voltaire.com/eu/uk/p/JMTS01771443/t-shirt-teddyx-blue-sixtine
- failure_modes: identity_mismatch
- architecture_buckets: identity_extraction
- mismatches:
  - title: crawler=Teddyx T-shirt | zyte=T-shirt Teddyx Blue Sixtine | Zadig&Voltaire
  - brand: crawler=Zadig&Voltaire | zyte=Zadig&Voltaire Logo

### 43. https://ar.puma.com/pd/zapatillas-mostro-ecstasy-unisex/397328.html?color=07
- **CRITICAL**: price_outlier
- alignment: matched
- zyte_status: ok
- crawler_url: https://ar.puma.com/pd/zapatillas-mostro-ecstasy-unisex/397328.html
- failure_modes: price_outlier
- architecture_buckets: price_extraction
- mismatches:
  - color: crawler=Verde | zyte=Fresh Mint-PUMA White
  - original_price: crawler=113999.00 | zyte=189999.00

### 44. https://www.karenmillen.com/eu/product/karen-millen-cotton-utility-button-detail-barrel-leg-trouser_bkk28382?colour=ivory
- **CRITICAL**: availability_mismatch
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.karenmillen.com/eu/product/karen-millen-cotton-utility-button-detail-barrel-leg-trouser_bkk28382
- failure_modes: availability_mismatch
- architecture_buckets: availability_extraction
- mismatches:
  - availability: crawler=limited_stock | zyte=in_stock

### 45. https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail
- failure_modes: ok
- architecture_buckets: -

### 46. https://www.kitchenaid.com/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html
- **CRITICAL**: price_outlier
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.kitchenaid.com/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html
- failure_modes: price_outlier
- architecture_buckets: price_extraction
- mismatches:
  - title: crawler=13-Cup Food Processor | zyte=13-Cup Food Processor - Contour Silver
  - brand: crawler=KitchenAid | zyte=KA LOGO
  - price: crawler=22999.00 | zyte=179.99

### 47. https://www.phase-eight.com/product/lucinda-spot-midi-dress-10015500806.html
- **CRITICAL**: variant_axis_pollution
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.phase-eight.com/product/lucinda-spot-midi-dress-10015500806.html
- failure_modes: variant_axis_pollution
- architecture_buckets: variant_extraction
- mismatches:
  - variant_size_pollution: crawler=[{'size': 'UK 06'}, {'size': 'UK 08'}, {'size': 'UK 10'}, {'size': 'UK 12'}, {'size': 'UK 14'}] | zyte=[]
  - sku: crawler=PE1001550 | zyte=10015500806

### 48. https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos/products/italian-seersucker-sutton-suit-2
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos/products/italian-seersucker-sutton-suit-2
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - sku: crawler=42738858426439 | zyte=7517449846855

### 49. https://savannahs.com/collections/all-boots/products/pavlova-100-lace-up-blush-satin-boots-cl28517s
- **CRITICAL**: availability_mismatch
- alignment: matched
- zyte_status: ok
- crawler_url: https://savannahs.com/collections/all-boots/products/pavlova-100-lace-up-blush-satin-boots-cl28517s
- failure_modes: availability_mismatch
- architecture_buckets: availability_extraction
- mismatches:
  - sku: crawler=CL28517S360 | zyte=8214362161218
  - size: crawler=36 | zyte=36 Variant sold out or unavailable
  - availability: crawler=in_stock | zyte=out_of_stock

### 50. https://www.grailed.com/listings/92502018-peter-do-velcro-strap-set-up-blazer-pants?g_aidx=Listing_by_listing_quality_production&g_aqid=dcff41da6c7483961c0b500769d4c7bc
- alignment: matched
- zyte_status: ok
- crawler_url: https://www.grailed.com/listings/92502018-peter-do-velcro-strap-set-up-blazer-pants
- failure_modes: ok
- architecture_buckets: -
- mismatches:
  - size: crawler=xs | zyte=36

### 51. https://www.desertcart.in/products/808107894-hormone-healthy-eats-100-recipes-to-balance-your-hormones-support?source=search
- alignment: matched
- zyte_status: ok
- crawler_url: https://desertcart.in/products/808107894-hormone-healthy-eats-100-recipes-to-balance-your-hormones-support
- failure_modes: ok
- architecture_buckets: -
