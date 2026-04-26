# CE10 — Commerce Extended 10-Site Listing + Derived Detail Report

Generated: 2026-04-26T02:38:15Z
Run mode: `full_pipeline` (timeout_owner=batch_runtime)

---

## 1. Listing Run (10 sites)

| Site | Records | Method | Quality | Time | Notes |
|---|---|---|---|---|---|
| CE01 zadig-et-voltaire | 50 | curl_cffi | good | 10.4s | 48/50 prices numeric |
| CE05 karenmillen | 29 | browser | good | 38.1s | Browser escalation (empty-extraction retry) |
| CE06 ganni | 12 | curl_cffi | good | 7.8s | 12/12 prices numeric |
| CE08 toddsnyder | 24 | curl_cffi | good | 7.0s | 23/24 prices numeric |
| CE09 savannahs | 59 | curl_cffi | good | 7.0s | 53/59 prices numeric |
| CE10 kitchenaid | 12 | browser | good | 19.8s | Akamai/Recaptcha challenge, usable content |
| CE11 dyson.in | 5 | curl_cffi | good | 1.7s | 5/5 prices numeric |
| CE12 grailed | 73 | browser | good | 11.8s | 49/73 prices numeric (marketplace variance) |
| CE13 desertcart | 46 | browser | good | 19.0s | Cloudflare+Recaptcha, usable after networkidle |
| CE15 stadiumgoods | 500 | curl_cffi | good | 9.8s | 100/100 prices numeric (sampled) |

**Listing summary:** 10/10 pass, 0 failures, 0 tracked issues.

---

## 2. Detail Run (derived URLs from listings above)

| Site | Records | Method | Verdict | Quality | Time | Issue |
|---|---|---|---|---|---|---|
| CE01 zadig-et-voltaire detail | 1 | curl_cffi | success | good | 4.1s | — |
| CE05 karenmillen detail | 1 | curl_cffi | success | good | 4.9s | — |
| CE06 ganni detail | 1 | curl_cffi | success | good | 3.0s | — |
| CE08 toddsnyder detail | 1 | curl_cffi | success | good | 3.6s | — |
| CE09 savannahs detail | 0 | browser | empty | bad_output | 5.3s | **shell_false_success** |
| CE10 kitchenaid detail | 0 | browser | blocked | blocked | 26.6s | **Blocked** (Akamai/Recaptcha) |
| CE11 dyson.in detail | 0 | browser | blocked | blocked | 8.4s | **Blocked** (bot detection) |
| CE12 grailed detail | 1 | curl_cffi | success | good | 1.7s | — |
| CE13 desertcart detail | 0 | browser | blocked | blocked | 25.2s | **Blocked** (Cloudflare/Recaptcha) |
| CE15 stadiumgoods detail | 1 | curl_cffi | success | good | 4.8s | — |

**Detail summary:** 6/10 success, 3 blocked, 1 shell_false_success.

---

## 3. Failure Mode Breakdown

| Failure Mode | Count | Sites |
|---|---|---|
| success | 6 | CE01, CE05, CE06, CE08, CE12, CE15 |
| blocked | 3 | CE10 kitchenaid, CE11 dyson.in, CE13 desertcart |
| shell_false_success | 1 | CE09 savannahs |

---

## 4. Quality / Output Observations

### Field coverage (successful detail pages)
- **CE01 zadig-et-voltaire**: 23 fields — rich PDP with variants (size axis: S/M/L/XL), care instructions, materials, barcode, product_id
- **CE05 karenmillen**: 17 fields — 18 size variants, rich description, availability as schema.org/LimitedAvailability
- **CE06 ganni**: 12 fields — size/color variants, barcode, brand
- **CE08 toddsnyder**: 8 fields — price, brand, rating (5.0), review_count
- **CE12 grailed**: 6 fields — marketplace listing (price, brand, image)
- **CE15 stadiumgoods**: 10 fields — SKU, size, brand, price, availability, image, description

### Blocking patterns
- **CE10 kitchenaid detail**: Akamai + reCaptcha challenge page. Browser navigates but gets challenge iframe. `browser_outcome: usable_content` on listing, detail gets blocked.
- **CE11 dyson.in detail**: Bot detection on detail path. Same domain listing works via curl_cffi, detail page blocks browser.
- **CE13 desertcart detail**: Cloudflare + Recaptcha on detail. Similar to kitchenaid — listing recovers after networkidle, detail does not.

### SPA / JS-rendered gaps
- **CE09 savannahs detail**: `shell_false_success` — Shopify page loads shell but no hydrated content extracted. 0 records after 5.3s. Likely needs wait or DOM interaction for variant/price hydration.

---

## 5. Efficiency Summary

| Metric | Value |
|---|---|
| Listing total time | ~134s (10 sites) |
| Detail total time | ~83s (10 sites) |
| Avg listing time | 13.4s |
| Avg detail time | 8.3s |
| Fastest listing | CE11 dyson.in (1.7s) |
| Slowest listing | CE05 karenmillen (38.1s, browser) |
| Fastest detail | CE12 grailed (1.7s) |
| Slowest detail | CE10 kitchenaid (26.6s, blocked) |

---

## 6. Key Takeaways

1. **Listing extraction is strong on CE sites** — 10/10 listings succeed, even JS-rendered ones (karenmillen, kitchenaid, grailed, desertcart) recover via browser escalation.
2. **Detail pages are harder** — only 6/10 succeed. The same anti-bot measures that challenge listings (Akamai, Cloudflare) often hard-block detail pages.
3. **Shopify detail hydration issue** — savannahs (Shopify) gets shell_false_success. This is the same pattern seen previously on practicesoftwaretesting and thriftbooks.
4. **curl_cffi is sufficient for most detail pages** when the listing already succeeded via curl_cffi (zadig, ganni, toddsnyder, stadiumgoods). Browser detail runs hit the same challenges as browser listings.
