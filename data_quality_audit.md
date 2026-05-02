# E-Commerce Data Quality Audit Report

## Executive Summary

| Metric | Value |
|--------|-------|
| **Total Records** | 37 |
| **Platforms** | Sephora, Target, ASOS, Wayfair, Home Depot, Grailed, and others |
| **Categories** | Apparel, footwear, cosmetics, furniture, hardware, electronics, books |

**Key Findings**
- **Critical:** Pricing anomalies (magnitude errors, missing decimals, missing values)
- **High:** UI artifacts polluting taxonomies and descriptions
- **High:** Misidentified product variants (promotions scraped as variants)
- **Medium:** System artifacts bleeding into data (fake SKUs, artifact product types)
- **Improved:** Availability flags standardized; ratings now numeric

---

## 1. Field Coverage Analysis

| Field | Presence | Coverage % | Status | Notes |
|-------|----------|------------|--------|-------|
| `url`, `title`, `image_url` | 37/37 | 100% | ✅ Excellent | Base identifiers fully covered |
| `description` | 37/37 | 100% | ⚠️ Present | Always present but quality varies heavily |
| `brand` | 35/37 | 94.5% | ⚠️ Partial | Missing on Firstcry (Babyhug), Target (Duvet) |
| `price`, `currency` | 34/37 | 91.8% | 🔴 Critical | Missing on Target (Duvet), ASOS (Pants), Wayfair (Sofa) |
| `sku` | 33/37 | 89.1% | ⚠️ Partial | Includes system generation errors |
| `availability` | 33/37 | 89.1% | ⚠️ Partial | Missing on Target, ASOS, Wayfair, Firstcry |
| `review_count`, `rating` | 19/37 | 51.3% | ⚠️ Partial | Present in roughly half the dataset |
| `category` | 28/37 | 75.6% | 🔴 Critical | Polluted with UI artifacts |
| `variants` | 18/37 | 48.6% | ℹ️ Expected | Good for apparel/makeup; absent for books, tools, electronics |
| `color`, `size` | < 15/37 | < 40% | ℹ️ Expected | Category-dependent (mostly apparel/makeup) |

---

## 2. Issues by Category

### 2.1 Pricing & Currency

**Severity: 🔴 Critical**

| Issue | Example | Expected |
|-------|---------|----------|
| Missing decimal point | KitchenAid Food Processor: `22999.00` USD | `$229.99` |
| Missing decimal point | Hormone Healthy Eats (Book): `545700.00` INR | `545.00 INR` |
| Parent/variant price mismatch | Puma Speedcat: parent `9999` vs variant `99.99` | Align parent with variant |
| Missing price entirely | ASOS Pants, Target Duvet, Wayfair Sofa | Require price for all records |
| Installment price scraped as total | Willy Chavarria Leather Jacket: `38.90` USD (~$1,500+ item) | Actual retail price |

### 2.2 Taxonomy & Category Pollution

**Severity: 🔴 Critical**

| Issue Type | Example | Contaminant |
|------------|---------|-------------|
| UI breadcrumb buttons | Adidas Stan Smith: `"Back > Home > Men > Shoes"` | Navigation buttons |
| Pagination controls | Todd Snyder Suit: `"Previous > Next"` | Pagination |
| Homepage link | Philipp Plein Jacket: `"Men Home > Philipp Plein..."` | Homepage link |
| Dropdown text | Zadig&Voltaire T-shirt: `"MEN : VIEW ALL"` | Menu label |
| Truncation ellipsis | Birkenstock Sandals: `"... > Shoes > Women's Shoes..."` | Truncated breadcrumb |
| Marketing collection | Frank Body Scrub: `"Best Sellers"` | Promo collection |
| Campaign text | Decathlon Padel Balls: `"...Back to the court"` | Seasonal campaign |
| Product name appended | ColourPop Eyeshadow: `"... > Going Coconuts"` | Product name |

### 2.3 Description & Specification Contamination

**Severity: 🟡 High**

| Issue Type | Example | Contaminant |
|------------|---------|-------------|
| UI button text | Wayfair Sofa: ends with `"Show More"` | Expand button |
| UI link text | Walmart AirPods: specs end with `"More details"` | Details link |
| Care info link | Pura Vida Bracelet: care ends with `"Learn more about our materials..."` | Info link |
| Shipping/promo text | Target Duvet Set: `"Choose from Same Day Delivery..."` | Delivery options (no real description) |
| SEO boilerplate | JD Sports Shorts: `"Shop adidas Originals... ✓Free Standard Delivery..."` | Store marketing copy |
| SEO boilerplate | Zappos Hoka Shoes: `"Read Hoka Women's Hoka Bondi 9 product reviews..."` | SEO template text |
| Entirely missing | Sleep Number Mattress: `"Product Label ​"` | No content extracted |
| Truncated | Decathlon Padel Balls: `"This tri-pack contains 3 tubes of 3…"` | Truncated mid-sentence |
| Redundancy | Hormone Healthy Eats: specs = 100% duplicate of description | Exact duplicate |
| Legal fine print | Walmart Apple AirPods: massive Apple testing disclaimers | Legal boilerplate |
| Install disclaimers | Home Depot Tile: vendor liability text | Non-product text |

### 2.4 Variant Extraction Failures

**Severity: 🟡 High**

| Issue | Example |
|-------|---------|
| Promotions scraped as variants | Adidas Stan Smith: `{"name": "off", "value": false}`, `{"name": "20%", "value": 20}` |
| Hex code as color name | ColourPop Eyeshadow: `"color": "#000000"` |

### 2.5 Cross-Field Data Leakage

**Severity: 🟡 High**

| Leakage Type | Example |
|--------------|---------|
| Reviews into materials | Phase Eight Dress: materials ends with `"Lining: Polyester 100% Reviews ( 23 )"` |
| Care instructions into materials | Lululemon Joggers: materials contains `"Care Machine Wash Cold Do Not Bleach..."` |
| Global site text into description | Untuckit Shirt: description lists all fit definitions instead of specific shirt |
| Global glossary into materials | Todd Snyder Suit: materials lists all brand fabrics instead of suit's fabric |

### 2.6 Logical Contradictions

**Severity: 🟡 High**

| Issue | Example |
|-------|---------|
| Gender contradiction | Babyhug Denim Set: `gender: "Boy"` but description says `"Female 12-18M"` |

### 2.7 System Artifacts

**Severity: 🟠 Medium**

| Artifact | Example | Source |
|----------|---------|--------|
| Fake SKU | Fashion Nova Pant Set: `sku: "COPY-1720644688978"` | DB duplication ID |
| Artifact product type | Karen Millen Trouser: `product_type: "default"` | Default value |
| Artifact product type | Target Duvet: `product_type: "Tag"` | Internal tag |
| Artifact product type | Adidas Stan Smith: `product_type: "inline"` | Layout marker |

---

## 3. Schema & Typing Observations

| Field | Current State | Issue | Recommendation |
|-------|---------------|-------|----------------|
| `rating` | Numeric (`4.7`) | ✅ Fixed from previous string values | Keep as float |
| `price` | String (`"128.00"`) | 🔴 Cannot sort or compute | Cast to float/decimal |
| `availability` | Standardized values | ✅ Fixed from Schema.org URL anomaly | Keep `in_stock` / `out_of_stock` / `limited_stock` |

---

## 4. Remediation Recommendations

### 4.1 Pricing
- [ ] **Parent/variant alignment:** Ensure parent prices mathematically match variant prices
- [ ] **Type coercion:** Convert `price` and `original_price` from strings to floats/decimals

### 4.2 Taxonomy
- [ ] **UI word filter:** Strip `Previous`, `Next`, `Back`, `Home`, `VIEW ALL`, `...` from category strings via regex
- [ ] **Collection exclusion:** Exclude marketing collections (`Best Sellers`, `Back to the court`) from taxonomy
- [ ] **Product name deduplication:** Remove product name from end of category path

### 4.3 Descriptions
- [ ] **UI text stripping:** Remove trailing `Show More`, `More details`, `Learn more...` strings
- [ ] **Shipping text exclusion:** Detect and exclude delivery/promo boilerplate
- [ ] **Redundancy detection:** Flag when `specifications` is an exact duplicate of `description`

### 4.4 Variants
- [ ] **Exclusion list:** Prevent UI elements (`off`, `on`, `20%`, `10%`, `discount`) from being stored as variants
- [ ] **Color mapping:** Map hex codes (`#000000`) to human-readable color names

### 4.5 System Artifacts
- [ ] **SKU validation:** Reject or flag SKUs matching `COPY-*` pattern
- [ ] **Product type cleanup:** Replace `default`, `Tag`, `inline` with null or inferred value

---

## Appendix: Issue Count by Severity

| Severity | Count | Categories |
|----------|-------|------------|
| 🔴 Critical | 10 | Pricing (5), Taxonomy (5) |
| 🟡 High | 14 | Description (7), Variants (2), Leakage (4), Contradictions (1) |
| 🟠 Medium | 4 | System Artifacts (4) |


