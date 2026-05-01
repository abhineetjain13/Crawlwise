E-Commerce Data Quality Audit Report
1. Executive Summary
The dataset contains 19 product records sourced from various e-commerce platforms (Wayfair, ASOS, Zara, Puma, etc.). While the core fields (URL, Price, Title) are consistently captured, the dataset suffers from severe schema inconsistency, data leakage (prices embedded in attributes), and scraping artifacts (loading GIFs, stringified Python dictionaries).
2. Field Coverage Analysis (Completeness)
Because the data comes from varied sources without a unified schema, field presence fluctuates heavily.
Field	Presence	Coverage %	Notes
url, price, title, currency, description	19/19	100%	Excellent coverage for core e-commerce fields.
image_url	18/19	94.7%	Missing on Cozyla 32" 4K Calendar (SKU: COCD8V543F0W).
brand	18/19	94.7%	Missing on Babyhug Denim Set (Firstcry).
sku	16/19	84.2%	High coverage, but formats vary drastically.
additional_images	15/19	78.9%	Generally well-populated.
availability	14/19	73.6%	Missing on several fashion items.
product_id	14/19	73.6%	Often duplicates the SKU.
category	13/19	68.4%	Missing on items like the KitchenAid processor.
variants / selected_variant	12/19	63.1%	Expected absence on single-SKU items.
color	11/19	57.8%	Good coverage for fashion/accessories.
review_count / variant_axes	10/19	52.6%	Present in about half the dataset.
size	9/19	47.3%	Present in apparel/shoes.
rating, barcode, materials	7/19	36.8%	Low coverage.
gender	6/19	31.5%	Only captured on a few apparel items.
vendor, product_details, care, specifications, product_type, part_number	< 5/19	< 26%	Highly fragmented; platform-specific fields.
3. Field-Wise Data Quality Issues
A. Attributes & Variations (Critical Issues)
Data Leakage in Options (color, condition, storage):
The iPhone 15 (Back Market) includes prices and text inside the attribute values. Examples: "color": "Black $382.00", "condition": "Excellent $450.01 Popular". This breaks filtering and faceted search capabilities.
The ColourPop makeup palette uses a Hex Code ("#000000") for the color attribute instead of a human-readable string.
Brand Name Corruption:
The iPhone 15 brand is scraped as "0 Apple" instead of "Apple".
B. Pricing & Currency Inconsistencies
Decimal/Parsing Errors:
The Puma Mostro Ecstasy shoes have a parent price of "113999" but the variants have a price of "1139.99". This is a severe parsing error (likely missing the decimal point in the parent object).
Data Type Inconsistencies:
Prices are currently represented as Strings (e.g., "249.99"). Best practice dictates these should be numerical Types (Float/Decimal).
C. Availability Flags (Formatting Mismatch)
Mixed Vocabularies:
Most items use standard snake_case strings: "in_stock", "out_of_stock", "limited_stock".
The Karen Millen trousers use a Schema.org URL instead: "https://schema.org/LimitedAvailability". This will break frontend logic expecting standard boolean or string statuses.
D. Images & Media
Scraper Artifacts / Junk Images:
The Babyhug Denim Set (Firstcry) contains site UI elements in the additional_images array rather than actual product images: "https://cdn.fcglcdn.com/brainbees/images/n/ic_to_arrow.png" and "https://cdn.fcglcdn.com/brainbees/images/LodingCart.gif".
E. Categories & Taxonomy
Inconsistent Breadcrumb Formatting:
Some use standard delimiters: "Power Tools > Sawing > Table Saws".
Some are flat strings: "Smartphones".
Some contain UI text: "MEN : VIEW ALL".
F. Scraping Code Bleed-Through
Python Dictionary as String:
The Puma shoes contain "product_type": "{'variationGroup': True}". This is a raw Python dictionary stringified into the JSON, indicating a bug in the scraping script.
G. Text Blobs (Descriptions, Specs, Care)
Unformatted Concatenations:
The specifications for the Rockler Table Saw and Wayfair Sofa are massive, unformatted text blocks missing line breaks (e.g., "Brand Rockler Weight 18.25 Tech Spec Brand: Rockler Materials..."). This is illegible for end-users.
4. Summary of Schema & Typing Issues
Mixed Data Types:
review_count is correctly typed as an Integer (e.g., 25).
rating is incorrectly typed as a String (e.g., "4.5" instead of 4.5).
Variant Redundancy:
The selected_variant object often duplicates the exact same fields present in the parent object (SKU, Image URL, Price), leading to bloated JSON payloads.
Missing Base Fields:
A product (Cozyla Calendar) is entirely missing images, which violates basic e-commerce display requirements.


Data Enrichment Quality Audit Report
1. Executive Summary
This enriched dataset contains 23 product records. While the enrichment pipeline successfully normalized certain formats (e.g., lowercasing colors, identifying size types as alpha/numeric), it suffers from severe taxonomy hallucinations, contextual extraction errors (pulling care instructions into materials), and inconsistent coverage for deep enrichment fields (personas, cross-sells).
2. Field Coverage Analysis (Completeness)
The dataset represents missing values with --. Deep enrichment fields (rows 11–15) were only generated for about 35% of the products.
Deduced Field Name	Presence	Coverage %	Notes
url, keywords_n_grams	23/23	100%	Base fields; n-grams generated universally.
availability	20/23	86.9%	Missing on ASOS, Zadig, Karen Millen, Firstcry, Wayfair.
price_and_currency	21/23	91.3%	Missing entirely for ASOS (#15) and Wayfair (#16).
taxonomy_category	14/23	60.8%	Decent coverage, but see quality issues below.
material	13/23	56.5%	Captured mostly for apparel and hardware.
color	11/23	47.8%	Expected absence on non-visual items (e.g., Table Saw).
size, gender	8/23	34.7%	Extracted primarily for apparel/footwear.
deep_enrichment (Uses, Personas, Styles, Clusters, Cross-Sells)	8/23	34.7%	Low. Only processed for items #1-7 and #12. Completely dropped for the rest.
3. Field-Wise Data Quality Issues
A. Taxonomy & Categorization (Critical Hallucinations)
The enrichment model completely misclassified several items, mapping them to wildly incorrect Google-style taxonomies:
❌ Fashion Nova Pant Set (#20): Categorized as Furniture > Furniture Sets (It is women's apparel).
❌ Tommy Hilfiger Oxfords (#13): Categorized as Apparel & Accessories > Clothing > Men's Undergarments (These are shoes, not underwear).
❌ Zadig & Voltaire T-Shirt (#4): Categorized as Business & Industrial > Retail > Paper & Plastic Shopping Bags > T-Shirt Shopping Bags (It confused a literal T-shirt with plastic grocery bags).
B. Material Extraction Artifacts (Context Blindness)
The extraction logic is failing to distinguish between the actual product material and other text on the page:
Todd Snyder Suit (#10): Materials list cashmere, cotton, denim, leather, linen, suede, twill, fabric. The model scraped the brand's global fabric glossary from the footer/description rather than the specific material of the seersucker suit.
Untuckit Shirt (#22): Materials list fabric, iron, linen. "Iron" was mistakenly extracted from the care instructions ("Iron warm, if needed").
C. Price & Currency Formatting
Missing Currency Code: Firstcry (#7) lists 868.21 without a currency code (should be INR). All other populated prices correctly feature the ISO code (e.g., USD 249.99, GBP 127.20).
Missing Data entirely: ASOS (#15) and Wayfair (#16) failed to output any price data.
D. Size and Sizing Logic Flaws
Contextual Error: ColourPop Eyeshadow (#19) lists a size of 24 with size type numeric. This is an eyeshadow palette; "24" likely refers to the grams/weight or pan count, not a wearable apparel size. Applying numeric sizing here is a false positive.
Variant Aggregation: Puma (#5) and Todd Snyder (#10) successfully aggregated all available sizes into a comma-separated array (e.g., 35.5, 36, 37...), which is a great structural feature for search indexing.
E. Keyword Generation (Repetitive & Bloated)
The keyword generation relies heavily on basic unigrams and bigrams derived directly from the title, leading to redundancy.
Example (#21): black, seascape, stretch, bracelet, ..., black seascape, seascape stretch, stretch bracelet.
This provides very little semantic enrichment value beyond what a basic standard search index already does.
4. Recommendations for Pipeline Remediation
Overhaul Taxonomy Mapping: The NLP model categorizing products is relying on naive keyword matching (e.g., "T-shirt" -> "T-shirt Shopping Bags"). Introduce context-aware categorization (e.g., zero-shot classification using an LLM) and strictly enforce a verified category tree.
Fix Material Extraction: Update the prompt/script to explicitly ignore "Care Instructions" (to avoid extracting "iron" or "wash") and limit extraction to the primary "Product Details" or "Composition" nodes to avoid scraping global website footers.
Standardize Fallbacks for Enrichment Fields: If the deep enrichment fields (Personas, Uses, Cross-sells) are meant to be generated for all items, the batch job timed out or failed silently after item #7 (and #12). Investigate the pipeline logs for API timeouts or token limits.
Contextual Validation for Sizes: Add a rule: If Category != Apparel/Footwear, suppress the size_type (alpha/numeric) field to prevent assigning shoe-size logic to makeup, hardware, or appliances.