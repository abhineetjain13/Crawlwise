# Failure Mode Report v7

Scope: 36 seed URLs in logs.md. 33 records in json.md. 3 failures (8.3%).

## Complete Failures

| Site | Reason | Status |
|------|--------|--------|
| New Balance | challenge_shell | Persistent |
| REI | timeout | Regression from v6 |
| ColourPop | interrupted | Infrastructure |

## Fixed / Improved

| Site | Issue | v7 State |
|------|-------|----------|
| Lowes | 0 records in v6 | FIXED - 1 full record |
| Kith | No price anywhere | FIXED - price present |
| Farfetch | Price "13880" no decimal | FIXED - "138.80" |
| SSENSE | Price "3890" no decimal | FIXED - "38.90" |
| Zappos | Broken image URLs | FIXED - valid URLs |
| Sephora | features = star widget | FIXED - real benefits |
| Macy's | Description pollution | FIXED - clean description |
| B&H Photo | No price/image | Partially fixed - has price, missing images/variants |
| ASOS | Identity mismatch | Changed - still mismatched, different product |

## Persistent Issues

| Site | Issue |
|------|-------|
| GOAT | Missing brand, price, currency, availability, variants, barcode, review_count |
| Amazon | Missing price, currency, availability, variants, barcode; thumbnail images |
| Apple | description is trade-in offer; missing price, currency, availability, variants |
| Target | Missing sku, price, brand, variants, barcode, currency, availability |
| Wayfair | Missing sku, price, brand, variants, barcode, currency, availability |
| Walmart | Truncated specs + legal boilerplate |
| Costco | Empty description |
| Dick's | Cross-sell images (unrelated Birkenstock) |
| PUMA | sku still GTIN instead of style code |
| Nike | Price "115" no cents |
| JD Sports | Price "3500" no decimal |
| Ulta | Price "32" missing cents |
| Frank Body | sku is Shopify internal ID |
| Zara | sku is style-color-size; color is "striped" |
| Lululemon | Price "128.000000" 6 decimals |
| Adidas | Regressed: all prices now "1", should be ~$100 |

## New Issues in v7

| Site | Issue |
|------|-------|
| ASOS | URL concatenates two URLs; SKU does not match product_id |
| Wayfair | specifications bloated with 650+ words of raw tables |
| Macy's | discount_amount "223", discount_percentage "225" - nonsensical |
| Adidas | All 25 variants out_of_stock but selected_variant says in_stock |
| Zara | Cross-image leakage: last image is different product |

## Missing Fields % (33 records)

| Field | Missing % |
|-------|-----------|
| sku | 6% |
| brand | 21% |
| price | 15% |
| currency | 15% |
| availability | 27% |
| description | 12% |
| image_url | 15% |
| additional_images | 24% |
| variants | 39% |
| barcode | 85% |

## Root Causes

| Cause | Status |
|-------|--------|
| challenge_shell detection too aggressive | Open |
| REI timeout regression | Open |
| ASOS URL parser concatenation | Open |
| Price formatting (no decimal, wrong precision) | Open |
| Shopify sku internal ID leakage | Open |
| Adidas price regression to "1" | Open - likely JSON-LD parsing error |

---

Report generated from logs.md and json.md.
