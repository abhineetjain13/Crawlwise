# Bug Triage — Exact Extracted Values, Root Causes & Fix Locations

**Source:** `json.json` + `bugs.md` cross-referenced  
**Sites affected:** 38 domains  
**Total symptoms:** ~67 (grouped into 6 root-cause buckets)

> **DECISION: Drop `tags` field entirely.** It is a garbage collector for internal backend noise (see Allbirds, Bombas, Glossier, Fender, Revolver Club). Zero product-semantic value.

---

## Bucket A: DOM Text Concatenation / Truncation (11 bugs)

**Birkenstock** (`arizona-core-birkoflor-0-eva-u_1.html`)
- **Field:** `materials`
- **Scraped:** `"Birko-Flor® Birko-Flor® is a skin-friendly, tear-resistant and easy-to-care-for synthetic material which is exclusively used by BIRKENSTOCK. Birko-Flor® Cork Cork is a sustainable material extracted from the bark layer of the cork oak. This natural product is insulating and offers very good cushioning. Cork"`
- **Expected:** `"Birko-Flor®, Cork"` or a clean paragraph per material with separators.
- **Root cause:** `clean_text()` collapses repeated `<span>`/`<div>` blocks for the same material into one run-on sentence with no punctuation or line breaks.

**Patagonia** (`mens-nano-puff-insulated-jacket/84213.html`)
- **Field:** `description`
- **Scraped:** `"We built the Nano Puff® Jacket for climbers who needed a weather-resistant, lightweight and packable synthetic insulation layer that could stay warm even when wet and withstand seasons of use. - Aquatic Blue We built the Nano Puff® Jacket for climbers who needed a weather-resistant, lightweight and packable synthetic insulation layer that could stay warm even when wet and withstand seasons of use. - Black We built..."` (repeated for ~10 colors)
- **Expected:** Single product description, not per-color accordion content concatenated.
- **Root cause:** Accordion/tabbed color-variant content is dumped into one DOM node; `_extract_sibling_content()` traverses across all tab panels instead of stopping at the active/default panel.

**Urban Outfitters** (`bdg-cindy-shoulder-bag`)
- **Field:** `features[0]`
- **Scraped:** `"- BDG Cindy bag - Washed faux leather bag with a heart charm accent - Oversized, it fits your essentials and more - Perfect as an everyday bag - Slouchy shoulder bag silhouette - Tumbled faux leather - Zippered main compartment - Soft woven lining - Zippered interior pocket - Zippered exterior pockets - Soft carry handles - Adjustable crossbody strap - Add your fave bag charms, not included - UO exclusive"`
- **Expected:** Array of individual feature bullets, not a single markdown-style string.
- **Root cause:** `_split_feature_text()` is splitting on `<li>` but the source is a single `<p>` or `<div>` with dash-separated text; no `<ul>`/`<li>` structure detected.

**Revolver Club** (`technics-sl-1200mk7`)
- **Field:** `features[0]`
- **Scraped:** `"Coreless Direct-Drive Motor Achieving Stable RotationDiverse New Functions Adapt to Various Playing StylesHigh Sensitive TonearmStylus Illuminator Featuring a High-brightness and Long-life White LEDPower / Phono Cable TerminalsHigh-rigidity Cabinet and High-damping Insulator"`
- **Expected:** Separated sentences/bullets.
- **Root cause:** Feature rows are `<div>` siblings without block tags; `" ".join()` collapses them into one string because there is no whitespace between adjacent inline elements.

**Fellow Products** (`stagg-ekg-electric-pour-over-kettle`) — from `bugs.md`
- **Field:** `features`
- **Scraped:** `"Precision Pour Spout To-the-degree temperature control Quick Heat Time Schedule in advance"`
- **Expected:** `["Precision Pour Spout", "To-the-degree temperature control", "Quick Heat Time", "Schedule in advance"]`

**Brooklinen** (`plush-bath-towels`) — from `bugs.md`
- **Field:** `description`
- **Scraped:** `"...Modern, effor"` (cut off mid-word) + `"How It FeelsPlush"` (missing space between blocks)
- **Root cause:** `DETAIL_LONG_TEXT_MAX_SECTION_CHARS` truncates mid-word; inline block boundaries (`<span>How It Feels</span><span>Plush</span>`) lose spacing.

**Sneakersnstuff** (`dime-soft-rock-crewneck`)
- **Field:** `description`
- **Scraped:** `"...Soft Rock Crewneck100% CottonHeavyweight 14ozScreen printed logoPre-shrunk"`
- **Expected:** Sentence-separated description with spaces between blocks.
- **Root cause:** Inline block boundaries (`<span>Soft Rock Crewneck</span><span>100% Cotton</span>`) lose whitespace padding during text extraction.

**Amazon** (`B08J5F3G18`)
- **Field:** `features[3]`
- **Scraped:** `"Triple HDB fans 9 iCX3 thermal sensors offer higher performance cooling and much quieter acoustic noiseAvoid using unofficial software"`
- **Expected:** Separate sentences with a space between `"noise"` and `"Avoid"`.
- **Root cause:** Adjacent inline elements with no whitespace between sentence boundaries are concatenated into one word.

**ASOS** (`155394360`)
- **Field:** `description`
- **Scraped:** `"Jeans by ASOS Curve Barrel leg High rise Drawstring waist Side pockets"`
- **Expected:** `"Jeans by ASOS Curve. Barrel leg. High rise. Drawstring waist. Side pockets."` or similar separated text.
- **Root cause:** Block tag boundaries (e.g. `<p>`, `<div>` with class-based grid cells) are stripped but no whitespace padding is inserted between inline siblings.

**Thomann** (`akg-k-702`)
- **Field:** `description`
- **Scraped:** `"High End Reference Headphones Flat-wire voice coil technology Varimotion two-layer diaphra..."`
- **Expected:** `"High End Reference Headphones. Flat-wire voice coil technology. Varimotion two-layer diaphragm..."`
- **Root cause:** Adjacent `<span>`/`<div>` blocks in spec grids collapse without whitespace padding.

**Zadig-et-Voltaire** (`Teddyx T-shirt`)
- **Field:** `features`
- **Scraped:** `"Composition: 100% Cotton* *100% of fibers comes fr..."`
- **Expected:** Clean bullet per composition line.
- **Root cause:** Structured text rows lose spacing between inline elements and truncate mid-sentence.

**Fix Location** `field_value_dom.py`
- `_section_text()` — `preserve_block_breaks=True` still collapses adjacent inline blocks without whitespace padding.
- `_extract_sibling_content()` — `" ".join()` on inline siblings loses paragraph boundaries when block tags are absent.
- `_split_feature_text()` — only splits on `<li>`/`<br>`; needs to split on sentence boundaries or dash lists when no HTML list structure exists.
- Config: `DETAIL_LONG_TEXT_MAX_SECTION_CHARS` should truncate at word boundary, not character.

---

## Bucket B: UI Noise / Non-Product Text Leaking into Fields (15 bugs)

**LEGO** (`millennium-falcon-75192`)
- **Field:** `features[0]`
- **Scraped:** `"\"Punch it!\" The ultimate LEGO® Star Wars ™ Millennium Falcon is here. With 7,500 elements... © & ™ Lucasfilm Ltd. 6+ 5.0 Luke Skywalker™ Pilot Key Chain $5.99 Add to Bag 6+ 3.6 Lightsaber Gel Pen – Black $4.99 Add to Bag..."` (entire "You may also like" carousel dumped)
- **Expected:** Actual product features only.

**LEGO**
- **Field:** `variants[].size`
- **Scraped:** `["View all", "Previous", "Next", "Play"]`
- **Expected:** Size should be `null` or absent (this product has no size variants).
- **Root cause:** `_collect_variant_choice_entries()` picks up carousel pagination buttons as variant options.

**YETI** (`rambler-8-oz-stackable-cup`)
- **Field:** `size`
- **Scraped:** `"8 oz Ceramic 8 oz Ceramic 16 oz 20 oz 30 oz Compare Size"`
- **Expected:** `"8 oz"` or size absent (size picker UI text).

**YETI**
- **Field:** `color`
- **Scraped:** `"Desert Bloom Trio 1 2 3 4 5 6 7 8 9 10 − + Desert Bloom Trio Venom Trio Camp Green/Firefly Yellow Trio Moon Dust Trio Wetlands Camo Trio Black Forest Green Trio Cherry Blossom Trio Cape Taupe Trio Navy/Seafoam/White"`
- **Expected:** `"Tropical Pink"` (the selected/default color) or `"Desert Bloom Trio"`.
- **Root cause:** Variant swatch picker DOM contains quantity stepper buttons (`1 2 3 4 5 6 7 8 9 10 − +`) and all color names concatenated.

**Canon** (`eos-r5`)
- **Field:** `description`
- **Scraped:** `"...Expandable to 102400 Footnote 1 . High-Speed Continuous Shooting...Subject tracking of People and Animals Footnote 2 using Deep Learning Technology..."`
- **Expected:** `"...Expandable to 102400. High-Speed Continuous Shooting...Subject tracking of People and Animals using Deep Learning Technology..."`
- **Root cause:** Footnote reference spans (`<sup>1</sup>`) are converted to plain text as `"Footnote 1"`.

**Canon**
- **Field:** `features[0]`
- **Scraped:** `"Protect Images"`
- **Expected:** Actual feature, not a UI button label.

**DTLR** (`jordan-air-jordan-5-retro-white-metallic`)
- **Field:** `description`
- **Scraped:** `"...Classic AJ5 details like the side netting, shark tooth midsole design, and \"23\" embroidery keep the heritage alive while elevating your everyday rotation. DTLR wants you to be fully satisfied with your purchase. You can view our Returns Policy here."`
- **Expected:** Description should end after `"...elevating your everyday rotation."`

**Bose** (`bose-ultra-open-earbuds`)
- **Field:** `description`
- **Scraped:** `"...With a cuff-like fit, Ultra Open Earbuds leave your ears open to hear the world around you while OpenAudio technology delivers rich, private sound. Read more"`
- **Expected:** Remove `" Read more"` suffix.

**Bluenile** (`classic-four-prong-solitaire-engagement-ring`) — from `bugs.md`
- **Field:** `features`
- **Scraped:** `["2025-11-04", "er,wr,fj,dc", "What is your shipping policy?,What is your return policy?,What payment methods do you accept?", "+1 724-204-1868"]`
- **Root cause:** Analytics payload, date, FAQ accordion, and phone number scraped as "features".

**Roamluggage** (`large-check-in`) — from `bugs.md`
- **Field:** `variants[].size`
- **Scraped:** `["Change Size", "Add to Cart", "Features", "Size and Weight", "100-Day Free Trial", "Lifetime Warranty"]`
- **Root cause:** Tab buttons and marketing banners treated as size options.

**Hermanmiller** (`aeron-chair`) — from `bugs.md`
- **Field:** `variants[].size`
- **Scraped:** `"View this product in: Size Size A - Small disable-danger"`
- **Root cause:** Screen-reader text + CSS class names (`disable-danger`) concatenated.

**Sneakersnstuff** (`dime-soft-rock-crewneck`)
- **Field:** `variants[].type`
- **Scraped:** `["Slide 1 of 4", "Slide 2 of 4", "Check availability", "Close"]`
- **Expected:** `null` or absent (this product has no type variants).
- **Root cause:** Image carousel pagination labels and modal UI buttons are collected as variant choice entries.

**Home Depot** (`flush-mount-led-ceiling-light`)
- **Field:** `variants[].color`
- **Scraped:** `["Search Field Icon", "Button for Searching by Scanning a Barcode with Your Phone"]`
- **Expected:** Actual color name or `null`.
- **Root cause:** Mobile search-bar UI elements (SVG icons + button labels) are picked up by variant color swatch selector.

**Sephora** (`sephora-collection-colorful-eyeshadow`)
- **Field:** `description`
- **Scraped:** `"Shop SEPHORA COLLECTION's Colorful Eyeshadow at Sephora. Rich, ultra-pigmented color."`
- **Expected:** Actual product description without platform boilerplate.
- **Root cause:** Meta/SEO description or storefront promo text is scraped instead of product body copy.

**Fix Locations**
- `detail_dom_extractor.py`
  - `_variant_option_value_is_noise()` — add tokens: `"View all"`, `"Previous"`, `"Next"`, `"Play"`, `"Change Size"`, `"Compare Size"`, `"Read more"`, `"Add to Cart"`, `"disable-danger"`, footnote refs, FAQ text, analytics payloads.
  - `_collect_variant_choice_entries()` — exclude `[role='button']`, tab panels, marketing banners.
- `field_value_dom.py`
  - `_section_text_is_meaningful()` — reject strings containing phone numbers, raw dates, FAQ questions, store locations.
- `field_value_core.py`
  - `clean_text()` — strip `"Read more"`, `"Footnote N"`, policy text suffixes.
- Config: `VARIANT_OPTION_VALUE_NOISE_TOKENS`, `SEMANTIC_SECTION_NOISE`, `DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS`

---

## Bucket C: Structured Data (JSON-LD / Schema / Shopify State) Parsing Defects (6 bugs)

**Bombas** (`mens-all-purpose-performance-ankle-socks`)
- **Field:** `variants[].color`
- **Scraped:** `"{'id': 'black-onyx', 'title': 'black onyx', 'swatch': {'id': '7csvZrVqBm3bqzhRMmtPZj', '__typename': 'Asset'}, 'group': None, '__typename': 'Color'}"`
- **Expected:** `"black onyx"`
- **Root cause:** Structured payload contains a dict; `coerce_field_value()` or `_coerce_structured_candidate_value()` calls `str()` on it instead of extracting the `title` field.

**Glossier** (`balm-dotcom`)
- **Field:** `variants` (mixed keys)
- **Scraped:** Some variants have key `"flavor"`, others have `"color"`, and standalone rows have `"color": "Sparkling Rosé variant option"`
- **Expected:** All flavor variants should use `"flavor"` consistently (or map to `"color"` canonically). Remove `" variant option"` suffix.

**Glossier**
- **Field:** `original_price`
- **Scraped:** `"5400.00"` with `currency: "INR"`
- **Field:** `price`
- **Scraped:** `"16.00"`
- **Expected:** `original_price` should be `null` (a $16 lip balm has no original_price of 5400 INR). Currency should be USD for both. Price mismatch indicates USD/INR field collision from different JSON-LD contexts (India storefront vs US base price).

**One Peloton** (`shop/tread`)
- **Field:** `price`
- **Scraped:** `"300900"`
- **Expected:** `"3295.00"`
- **Field:** `currency` — **MISSING entirely**
- **Expected:** `"USD"`
- **Root cause:** `300900` is not cents (300900/100 = 3009, still wrong). It is likely scraped from a product ID, SKU, or an internal numeric field that is not price. `interpret_integral_as_cents=True` is misfiring on a non-price integer because no decimal/currency symbol is present in the source payload.

**ColourPop** (`true-blue-palette`)
- **Field:** `features[0]`
- **Scraped:** `"True"`
- **Expected:** Actual feature text (e.g. `"Matte shades")` or `null`.
- **Root cause:** Boolean `True` from structured state/JSON-LD is coerced to string `"True"` instead of being skipped or mapped to a meaningful feature.

**Discogs** (`rick-astley-never-gonna-give-you-up`)
- **Field:** `description`
- **Scraped:** `"'7\"', '45 RPM', 'Single', 'Stereo'"` (raw Python list syntax as plain text)
- **Expected:** `"7\" 45 RPM Single Stereo"` or clean formatted description.
- **Root cause:** Structured data list is stringified via `str()` instead of joined into a readable sentence.

**Fix Locations**
- `field_value_candidates.py`
  - `_coerce_structured_candidate_value()` — for price: validate that `interpret_integral_as_cents` only fires when payload shape confirms it is a price field (e.g. key name is literally `"price"` in the source object), not just any 5+ digit integer.
  - `_structured_variant_rows()` — for color dicts: extract `title` field instead of `str()` on the whole dict.
- `field_value_core.py`
  - `coerce_field_value("color", ...)` — if value is dict, extract known display fields (`title`, `name`, `label`) before falling back to `str()`.
- `js_state_mapper.py` / `shared_variant_logic.py`
  - `normalized_variant_axis_key()` — map `"flavor"` → canonical `"color"` (or keep as `"flavor"` consistently across all rows, never mix).

---

## Bucket D: Field Semantic Mis-mapping / Heading Alias Errors (8 bugs)

**Allbirds** (`mens-wool-runners-natural-black`)
- **Field:** `specifications`
- **Scraped:** `"A true original, our Wool Runner combines soft Merino wool with cloud-like comfort."`
- **Expected:** Actual specs (e.g. weight, materials, origin). This is marketing tagline copy.
- **Root cause:** Heading alias `"Specifications"` or `"Details"` mapped to DOM node containing brand story/marketing paragraph.

**Vans** (`old-skool-VN000E9TBPG`)
- **Field:** `specifications`
- **Scraped:** `"Signature waffle outsole pattern for reliable grip since '66"`
- **Expected:** Technical specs (materials, weight, dimensions).
- **Root cause:** Same as Allbirds — "Details"/"Specs" heading aliased to marketing copy node.

**Patagonia**
- **Field:** `care`
- **Scraped:** `"Made in a Fair Trade Certified™ factory"`
- **Expected:** Care instructions (wash/dry). This is manufacturing origin, not care.
- **Root cause:** `care` field mapped from "Care & Information" heading but the DOM content under that heading contains factory certification, not washing instructions.

**Urban Outfitters**
- **Field:** `specifications`
- **Scraped:** `"[ Product Sku: 101211381; Color Code: 048 Your new do-everything oversized shoulder bag comes in a large size that's perfect as an everyday bag, school bag, travel bag and everything in between... BDG Giving classics an original twist, BDG by Urban Outfitters offers an exclusive collection of premium denim and elevated wardrobe basics. ]"`
- **Expected:** Actual product specs (materials, dimensions, weight).
- **Root cause:** The "Specs" or "Details" section contains the full product description + care + brand boilerplate wrapped in brackets. Heading→content aliasing is too broad.

**Anthropologie** (`boho-bangle-bracelets-set-of-3`)
- **Field:** `product_details`
- **Scraped:** `"[ Style No. 108064080; Color Code: 012 14k gold-plated brass, resin Slip-on styling Imported ]"`
- **Expected:** Clean product details without SKU/Style No prefix and without brackets.
- **Root cause:** `coerce_field_value()` wraps list-to-string coercion in brackets (`[ ... ]`) when the source is a JSON array. Also the "Style No." text is raw DOM heading text that got concatenated with the content.

**Fender** (`american-vintage-ii-1972-telecaster-thinline`)
- **Field:** `size`
- **Scraped:** `"14"`
- **Expected:** Should be `null` (guitars don't have sizes).
- **Root cause:** Variant axis inference defaults to `"size"` when it cannot identify the axis. The payload likely has a variant ID or model number containing `14`.

**Sony India** (`ilce-9m3`)
- **Field:** `variants[].size`
- **Scraped:** `"9"`
- **Expected:** Should be `null` (cameras don't have sizes).
- **Root cause:** Camera model is "a9 III"; the `9` is extracted as a size variant because axis inference defaults to `"size"` on any unrecognized numeric variant.

**Sephora** (`sephora-collection-colorful-eyeshadow`)
- **Field:** `variants[].size`
- **Scraped:** `["209", "601", "73", "84", "366"]`
- **Expected:** `null` (eyeshadows have no size; these are shade/color codes).
- **Root cause:** Shade ID numbers are mis-mapped to `size` axis because axis inference defaults to `"size"` for unrecognized numeric variant values.

**31 Phillip Lim** (`mini-pashli-camera-bag`)
- **Field:** `variants[].size`
- **Scraped:** `["35", "4", "O/S"]`
- **Expected:** `null` (this is a handbag; shoe-size values do not apply).
- **Root cause:** Shoe-size values are leaking into a non-apparel domain because the variant axis inference defaults to `"size"` instead of `null` when the category is not footwear/apparel.

**Fix Locations**
- `field_value_dom.py`
  - `extract_heading_sections()` — tighten `_is_section_label()` so "Details"/"Specs" only maps to `specifications` when the paragraph contains measurable data (dimensions, materials, weight) and not narrative marketing copy.
  - `_section_text_is_meaningful()` — reject paragraphs that are purely brand story text (contains "We built", "combines soft", "cloud-like comfort").
- `field_value_core.py`
  - `coerce_field_value()` — bracket wrapping: do not wrap single string values in `[ ... ]` when coercing from list.
- `detail_dom_extractor.py` / `shared_variant_logic.py`
  - `infer_variant_group_name_from_values()` — for non-clothing products (detected by category or domain), do not default to `"size"`. Default to `null` or require explicit axis label.

---

## Bucket E: Description Truncation / Expansion Failure (11 bugs)

**Sweetwater** (`sony-wh-1000xm5`)
- **Field:** `description`
- **Scraped:** `"WH-1000XM5 Wireless Noise-canceling Headphones with Wireless"`
- **Expected:** Full description (e.g. `"WH-1000XM5 Wireless Noise-canceling Headphones with Wireless Noise-canceling Earbuds in Black — featuring industry-leading noise cancellation..."`)
- **Root cause:** Truncated mid-sentence; likely hits `DETAIL_LONG_TEXT_MAX_SECTION_CHARS` or accordion content is collapsed.

**Revolver Club**
- **Field:** `description`
- **Scraped:** `"Item ships out in 15 working days.The SL-1200 – A New Chapter BeginsAs the go-to choice o..."`
- **Expected:** Full description without ellipsis.
- **Root cause:** Source text ends with `...` (hardcoded ellipsis in HTML); crawler does not expand or follow "Read more"/"View more" buttons.

**Bose**
- **Field:** `description`
- **Scraped:** `"...Ultra Open Earbuds leave your ears open to hear the world around you while OpenAudio technology delivers rich, private sound. Read more"`
- **Expected:** Remove `" Read more"` suffix; ideally expand the collapsed text block.

**Patagonia**
- **Field:** `description`
- **Scraped:** Massive concatenation of identical sentence repeated for every color (see Bucket A). Also a truncation/expansion issue because each color tab's content is dumped into one node.

**DTLR**
- **Field:** `description`
- **Scraped:** `"Details The Air Jordan 5 Retro \"White Metallic\" brings clean, iconic energy... DTLR wants you to be fully satisfied with your purchase. You can view our Returns Policy here."`
- **Expected:** Just the product description (first sentence). The returns policy is footer noise appended at the end.

**Phase Eight** (`lucinda-spot-dress`)
- **Field:** `description`
- **Scraped:** `"Lucinda Spot Dress"` (heading only)
- **Expected:** Full product description body text.
- **Root cause:** Only the `<h1>`/heading text is extracted; the description body is either in a sibling block missed by traversal or hidden behind an expander.

**Backmarket** (`iphone-15-pro-max`)
- **Field:** `description`
- **Scraped:** `""` (empty)
- **Expected:** Actual product description.
- **Root cause:** Description body is likely lazy-loaded or lives in a JSON/XHR fragment not captured by the initial DOM scrape.

**Apple** (`iphone-15-pro-max`)
- **Field:** `description`
- **Scraped:** `"Get \$35-\$685 off iPhone 15 Pro Max when you trade in an iPhone 11 or higher.*"` (trade-in promo text)
- **Expected:** Product description (e.g. materials, camera specs, display details).
- **Root cause:** Marketing promo banner is mapped ahead of the real product description in DOM traversal priority.

**GOAT** (`nike-dunk-low`)
- **Field:** `description`
- **Scraped:** `"Shop the Nike Dunk Low at GOAT."` (platform meta-text)
- **Expected:** Actual product description.
- **Root cause:** SEO/meta description is scraped instead of product body copy.

**Grailed** (`velcro-strap-set-up`)
- **Field:** `description`
- **Scraped:** `"Searching for Velcro Strap Set-up? We’ve got Sacai outerwear starting at \$280 and plenty of other outerwear."` (platform meta-text)
- **Expected:** Actual product description.
- **Root cause:** Marketplace search/SEO snippet is scraped instead of product body copy.

**Target** (`tobago-stripe`)
- **Field:** `description`
- **Scraped:** `"Read reviews and buy Tobago Stripe Short Sleeve Linen Button-Down Shirt - Goodfellow & Co™ at Target."` (platform meta-text)
- **Expected:** Actual product description.
- **Root cause:** SEO/meta description is scraped instead of product body copy.

**Fix Locations**
- `detail_dom_extractor.py`
  - `primary_dom_context()` — when cleaned DOM yields collapsed text (ends with `"..."` or `"Read more"`), fall back to original raw HTML or expand sibling `<div>` hidden by CSS.
  - `apply_dom_fallbacks()` — if description contains `"Read more"`, attempt to click/expand or scrape the `data-full-text` attribute.
- `field_value_dom.py`
  - `_extract_sibling_content()` — stop traversal at accordion boundaries (`<summary>`, `[role="tabpanel"]`) instead of crossing them.
  - `DETAIL_LONG_TEXT_MAX_SECTION_CHARS` — increase limit or add heuristic: if text ends mid-sentence without terminal punctuation, continue traversing.

---

## Bucket F: Title / Rating / Image / Price / Missing Field Guards (16 bugs)

**Sweetwater**
- **Field:** `title`
- **Scraped:** `"Wh1Kxm5Blk Sony Wh 1000Xm5 Wireless Noise Canceling Headphones Black"`
- **Expected:** `"Sony WH-1000XM5 Wireless Noise-canceling Headphones - Black"`
- **Root cause:** Internal SKU `Wh1Kxm5Blk` is prepended to the title in the DOM or JSON-LD.

**Nordstrom** (`air-force-1-07`)
- **Field:** `rating`
- **Scraped:** `1`
- **Expected:** `~4.5` (Air Force 1 with 481 reviews cannot have aggregate rating 1).
- **Root cause:** `RATING_RE` likely captured a single `1-star` review badge (`"1"` near the review count) instead of the aggregate rating.

**Converse** (`chuck-taylor-all-star-retro-embroidery`)
- **Field:** `image_url`
- **Scraped:** **MISSING** (field absent)
- **Expected:** Hero image URL.
- **Root cause:** DOM image selector failed; `og:image` or JSON-LD `image` not checked as fallback.

**Endclothing** (`47-ny-yankees-clean-up-cap`)
- **Field:** `description`
- **Scraped:** **MISSING** (field absent)
- **Expected:** Product description.
- **Root cause:** No suitable DOM text block found; page may be image-heavy or lazy-loaded.

**Gucci** (`gg-wool-silk-jacquard-stole`)
- **Field:** `price`
- **Scraped:** `"-1"`
- **Expected:** `null` or actual price if available.
- **Root cause:** Site returns `-1` as unavailable/price-on-request placeholder. `extract_price_text()` / `coerce_field_value("price")` does not reject negative values.

**Glossier**
- **Field:** `variants[].image_url`
- **Scraped:** All flavor variants map to the same incorrect image: `"https://cdn.shopify.com/s/files/1/0627/9164/7477/files/glossier-bdc-wildfig-carousel-1.png?v=1762201257"` (Wild Fig image used for every flavor).
- **Expected:** Each flavor should have its own swatch/product image.
- **Root cause:** `_structured_variant_rows()` picks the first image from the parent product for all variants instead of per-variant image.

**Fender**
- **Field:** `size`
- **Scraped:** `"14"`
- **Expected:** `null` (see Bucket D).

**Sony India**
- **Field:** `variants[].size`
- **Scraped:** `"9"`
- **Expected:** `null` (see Bucket D).

**One Peloton**
- **Field:** `title`
- **Scraped:** `"Shop the Peloton Cross Training Tread"`
- **Expected:** `"Peloton Cross Training Tread"` or `"Peloton Tread"`
- **Root cause:** Scraped SEO/meta title instead of product title.

**GOAT** (`nike-dunk-low`)
- **Field:** `price`
- **Scraped:** `null`
- **Expected:** Actual price.
- **Root cause:** Price not present in DOM or structured data at crawl time; may require authenticated/session state or JS hydration.

**Amazon** (`B08J5F3G18`)
- **Field:** `price`
- **Scraped:** `null`
- **Expected:** Actual price.
- **Root cause:** Price may be in a dynamic widget or requires cookie/session; not captured in static scrape.

**Target** (`tobago-stripe`)
- **Field:** `price`
- **Scraped:** `null`
- **Expected:** Actual price.
- **Root cause:** Price may be lazy-loaded or behind A/B test fragment not captured.

**Home Depot** (`flush-mount-led-ceiling-light`)
- **Field:** `price`
- **Scraped:** `null`
- **Expected:** Actual price.
- **Root cause:** Price may be in a dynamic widget or requires zip-code/availability check.

**ASOS** (`155394360`)
- **Field:** `price`
- **Scraped:** `null`
- **Expected:** Actual price.
- **Root cause:** Price may be in a dynamic JS fragment not captured in static scrape.

**Phase Eight** (`lucinda-spot-dress`)
- **Field:** `image_url`
- **Scraped:** `null` (parent-level image missing)
- **Expected:** Hero product image URL.
- **Root cause:** Hero image is likely loaded via JS carousel or `data-src` attribute not resolved by static image selector.

**Backmarket** (`iphone-15-pro-max`)
- **Field:** `features`
- **Scraped:** `[]` (empty array)
- **Expected:** Actual features list.
- **Root cause:** Features likely rendered from JSON/XHR or lazy-loaded; not present in initial static DOM.

**Fix Locations**
- `field_value_core.py`
  - `is_title_noise()` / title cleaning — strip SKU-like prefixes (alphanumeric 8-12 chars at start of title).
  - `RATING_RE` — prefer structured aggregate rating over DOM regex. Add guard: if `review_count > 10` and `rating == 1`, reject and backfill from structured data.
  - `extract_price_text()` / `coerce_field_value("price")` — reject `"-1"`, `"0"`, negative values, and placeholders.
- `detail_dom_extractor.py`
  - `extract_page_images()` — if `image_url` missing, fall back to `meta[property="og:image"]`, then JSON-LD `image`, then first visible `<img>` in primary DOM context.
  - `_collect_variant_choice_entries()` — default axis assignment logic: do not infer `"size"` for unrecognized axes on non-apparel domains (detected by surface or domain family).
- `field_value_candidates.py`
  - `_structured_variant_rows()` — per-variant image_url extraction: if variant has its own `image` field, use it; only fall back to parent image when variant image is absent.

---

## Summary Table

| Bucket | Bugs | Primary File | Config File |
|--------|------|-------------|-------------|
| A Text concat/truncation | 11 | `field_value_dom.py` | `DETAIL_LONG_TEXT_*` |
| B UI noise leakage | 15 | `detail_dom_extractor.py` | `extraction_rules.py` (noise tokens) |
| C Structured data parsing | 6 | `field_value_candidates.py` | — |
| D Field mis-mapping | 8 | `field_value_dom.py` | `FIELD_ALIASES` |
| E Description truncation | 11 | `detail_dom_extractor.py`, `field_value_dom.py` | `DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR` |
| F Title/rating/image/price | 16 | `field_value_core.py`, `detail_dom_extractor.py` | `extraction_rules.py` |

**Recommended order:**
1. **Bucket B** — add noise tokens to config (lowest risk, highest count).
2. **Bucket F** — add guards in `field_value_core.py` for rating=1, price=-1, SKU-prefixed titles.
3. **Bucket A + E** — fix DOM text boundary splitting (`_split_feature_text`, `_extract_sibling_content`).
4. **Bucket C** — fix structured dict-to-string coercion for colors and integral-price misfire.
5. **Bucket D** — tighten heading alias rules and variant axis inference.
