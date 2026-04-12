from __future__ import annotations

import re

from app.services.config.crawl_runtime import (
    DYNAMIC_FIELD_NAME_MAX_TOKENS,
    MAX_CANDIDATES_PER_FIELD,
)
from app.services.config.platform_registry import known_ats_domains

__all__ = [
    "DYNAMIC_FIELD_NAME_MAX_TOKENS",
    "MAX_CANDIDATES_PER_FIELD",
]

SITE_POLICY_REGISTRY = {}
ACTION_ADD_TO_CART = "add to cart"
ACTION_BUY_NOW = "buy now"
ACTION_SIGN_IN = "sign in"
NEXT_FLIGHT_BACK_WINDOW = 1200
NEXT_FLIGHT_FORWARD_WINDOW = 2200
NEXT_FLIGHT_PAIR_PATTERNS: tuple[str, ...] = (
    r'"displayName":"(?P<title>[^"]+)".{0,900}?"listingUrl":"(?P<url>[^"]+)"',
    r'"listingUrl":"(?P<url>[^"]+)".{0,900}?"displayName":"(?P<title>[^"]+)"',
)
NEXT_FLIGHT_BRAND_PATTERNS: tuple[str, ...] = (
    r'"name":"(?P<brand>[^"]+)","__typename":"ManufacturerCuratedBrand"',
    r'"brand":\{"name":"(?P<brand>[^"]+)"',
)
NEXT_FLIGHT_SALE_PRICE_PATTERN = (
    r'"priceVariation":"(?:SALE|PRIMARY)".{0,220}?"amount":"(?P<amount>[\d.]+)"'
)
NEXT_FLIGHT_ORIGINAL_PRICE_PATTERN = (
    r'"priceVariation":"PREVIOUS".{0,220}?"amount":"(?P<amount>[\d.]+)"'
)
NEXT_FLIGHT_RATING_PATTERN = (
    r'"averageRating":(?P<rating>[\d.]+),"totalCount":(?P<count>\d+)'
)
NEXT_FLIGHT_AVAILABILITY_PATTERN = (
    r'"(?:shortInventoryStatusMessage|stockStatus)":"(?P<availability>[^"]+)"'
)

EXTRACTION_RULES = {
    "dom_patterns": {
        "title": "h1, [itemprop='name'], meta[property='og:title'], title",
        "price": "[itemprop='price'], .price, .product-price",
        "sale_price": ".sale-price, .discount-price, [data-sale-price]",
        "original_price": ".original-price, .compare-price, [data-original-price]",
        "description": "[itemprop='description'], .product-description, [data-description], meta[name='description'], meta[property='og:description']",
        "brand": "[itemprop='brand'], .brand, .product-brand",
        "image_url": "[itemprop='image'], meta[property='og:image']",
        "rating": "[itemprop='ratingValue']",
        "review_count": "[itemprop='reviewCount']",
        "sku": "[itemprop='sku']",
        "availability": "[itemprop='availability'], .availability, [data-stock], [data-availability]",
        "category": "[itemprop='category'], nav.breadcrumb li:last-child",
        "company": ".company-name, [itemprop='hiringOrganization'] [itemprop='name']",
        "location": ".job-location, [itemprop='jobLocation'] [itemprop='name']",
        "salary": ".salary, [itemprop='baseSalary']",
        "job_type": "[itemprop='employmentType']",
        "apply_url": "a[data-apply-url], a.apply-button",
        "responsibilities": "[data-section='responsibilities'], .responsibilities, #responsibilities",
        "qualifications": "[data-section='qualifications'], .qualifications, #qualifications",
        "benefits": "[data-section='benefits'], .benefits, #benefits",
        "skills": "[data-section='skills'], .skills, #skills",
        "specifications": "[data-section='specifications'], .specifications, .product-specifications, #specifications",
        "features": "[data-section='features'], .features, .product-features, #features",
    },
    "candidate_cleanup": {
        "placeholder_values": [
            "-",
            "—",
            "--",
            "n/a",
            "na",
            "none",
            "null",
            "undefined",
        ],
        "generic_category_values": [
            "detail-page",
            "detail_page",
            "product",
            "page",
            "pdp",
            "simple",
            "configurable",
            "image",
            "imageobject",
            "listitem",
            "itemlist",
            "collectionpage",
            "productcard",
            "contentcard",
            "aggregateoffer",
            "productgroup",
            "aggregaterating",
            "review",
            "person",
            "rating",
            "merchantreturnpolicy",
            "merchantreturnpolicyseasonaloverride",
            "webpage",
            "organization",
            "speakablespecification",
            "individualproduct",
            "peopleaudience",
            "brand",
            "offer",
            "postaladdress",
            "country",
            "quantitativevalue",
            "unitpricespecification",
            "pricespecification",
            "deliverychargespecification",
            "openinghoursspecification",
            "geopoint",
            "geocoordinates",
            "place",
            "contactpoint",
            "searchaction",
            "readaction",
            "buyaction",
            "sitenavigationelement",
            "wpadblock",
            "creativework",
            "article",
            "newsarticle",
            "blogposting",
            "howto",
            "faqpage",
            "videoobject",
            "localbusiness",
            "store",
            "thing",
            "guest",
            "max_discount",
            "website",
            "web site",
            "all",
            "shop",
            "products",
            "items",
            "collection",
            "collections",
            "catalog",
            "new",
            "sale",
            "clearance",
            "featured",
            "trending",
            "popular",
            "recommended",
        ],
        "generic_title_values": [
            "chrome",
            "firefox",
            "safari",
            "edge",
            "home",
            "cookie preferences",
            "cookie settings",
            "privacy preferences",
            "privacy settings",
            "manage cookies",
            "consent preferences",
            "accept cookies",
            ACTION_SIGN_IN,
            "log in",
            "my account",
            "newsletter",
            "create account",
            "register",
        ],
        "title_noise_tokens": [
            "cookie",
            "cookies",
            "privacy",
            "consent",
            "preferences",
            ACTION_SIGN_IN,
            "log in",
            "login",
            "register",
            "my account",
            "newsletter",
            "subscribe",
            "terms",
            "conditions",
            "gdpr",
            "ccpa",
        ],
        "title_noise_phrases": [
            "cookie preferences",
            "privacy policy",
            "terms of service",
            ACTION_SIGN_IN,
            "log in",
            "my account",
            ACTION_ADD_TO_CART,
            "shopping cart",
            "department navigation",
            "cookie manager banner",
        ],
        "category_noise_phrases": [
            "breadcrumb",
            "view all",
            "filter by",
            "sort by",
            "shop all",
            "purchased",
            ACTION_ADD_TO_CART,
            "add to bag",
            "quick view",
            "quick shop",
            "shop now",
            ACTION_BUY_NOW,
            "learn more",
            "see details",
            "view details",
            "more info",
            "read more",
            "click here",
            "free shipping",
            "free returns",
            "on sale",
            "new arrival",
            "best seller",
            "top rated",
            "customer favorite",
        ],
        "availability_noise_phrases": [
            "select options",
            "choose options",
            ACTION_ADD_TO_CART,
            "quantity",
            "wishlist",
        ],
        "ga_data_layer_keys": [
            "event",
            "ecommerce",
            "gtm.start",
            "gtm.uniqueEventId",
            "pageType",
            "pageName",
            "visitorType",
        ],
        "field_groups": {
            "url": ["url", "apply_url"],
            "image_primary": ["image_url"],
            "image_collection": ["additional_images"],
            "numeric": [
                "price",
                "sale_price",
                "original_price",
                "rating",
                "review_count",
            ],
            "salary": ["salary"],
            "currency": ["currency"],
            "availability": ["availability"],
            "category": ["category"],
            "title": ["title"],
            "description": ["description", "summary"],
            "job_text": [
                "responsibilities",
                "requirements",
                "qualifications",
                "benefits",
                "skills",
            ],
            "entity_name": ["brand", "company"],
            "identifier": ["sku", "vin", "dealer_name"],
        },
        "field_name_patterns": {
            "url_suffixes": ["_url", "url", "_link", "link", "_href", "href"],
            "image_tokens": [
                "image",
                "images",
                "gallery",
                "photo",
                "thumbnail",
                "hero",
            ],
            "image_collection_tokens": ["images", "gallery", "photos", "media"],
            "currency_tokens": ["currency"],
            "price_tokens": ["price", "amount", "cost"],
            "salary_tokens": ["salary", "pay", "rate", "compensation"],
            "rating_tokens": ["rating", "score"],
            "review_count_tokens": ["review_count", "reviews", "rating_count"],
            "availability_tokens": ["availability", "stock"],
            "category_tokens": ["category", "department", "breadcrumb"],
            "description_tokens": ["description", "summary", "overview", "details"],
            "identifier_tokens": ["sku", "id", "code", "vin", "mpn"],
        },
        "ui_noise_phrases": [
            "add to wishlist",
            "add to bag",
            ACTION_ADD_TO_CART,
            ACTION_BUY_NOW,
            "selling fast",
            "best seller",
            "top seller",
            "limited stock",
            "low stock",
            "sold out",
            "out of stock",
            "view more",
            "learn more",
        ],
        "image_noise_tokens": ["logo", "sprite", "icon", "badge", "favicon"],
        "image_url_hint_tokens": ["/image", "/images/", "/img", "image=", "im/"],
        "image_candidate_dict_keys": [
            "url",
            "contentUrl",
            "src",
            "image",
            "thumbnail",
            "href",
        ],
        "color_css_noise_tokens": [
            "padding:",
            "font-size",
            "font-weight",
            "transition:",
            "position:",
            "-webkit-",
            "css-",
        ],
        "size_css_noise_tokens": [
            "max-width",
            "min-width",
            "vw",
            "vh",
            "sizes=",
            "srcset",
            "padding:",
            "font-size",
            "font-weight",
            "transition:",
            "position:",
            "-webkit-",
            "size",
        ],
        "size_package_tokens": ["pkg of", "pack of", "pack size", "package"],
        "availability_status_tokens": {
            "limited_stock": ["limited stock", "low stock", "only", "left in stock"],
            "in_stock": ["in stock", "instock", "available", "ready to ship"],
            "out_of_stock": ["out of stock", "oos", "sold out", "unavailable"],
            "preorder": ["pre-order", "preorder", "backorder", "back-order"],
        },
        "dynamic_field_name_hard_rejects": [
            "from",
            "location",
            "recommended",
            "reviews",
            "votes",
        ],
        "dynamic_field_name_schema_noise_patterns": [
            r"^elp\d+$",
            r"^e\d+d_[a-z0-9_]+$",
            r"^e\d+[a-z]_[a-z]{2}$",
            r"^el_[a-z0-9]{2,6}_\d+$",
            r"^c\d{3,5}$",
            r"^[a-z]{1,2}\d{2,6}[a-z]?_[a-z0-9_]+$",
        ],
        "dynamic_field_name_tickerlike_blocklist": [
            "xrp",
            "btc",
            "eth",
            "bnb",
            "sol",
            "ada",
            "doge",
            "trx",
            "ltc",
            "dot",
            "avax",
            "matic",
            "arb",
            "op",
            "uni",
            "atom",
            "near",
            "ftm",
            "cro",
        ],
        "description_meta_selectors": [
            "meta[name='description']",
            "meta[property='og:description']",
            "meta[name='twitter:description']",
        ],
        "description_fallback_content_selectors": ["article", "main", "body"],
        "tracking_param_exact_keys": ["ref", "ref_src"],
        "tracking_param_prefixes": ["utm_", "fbclid", "gclid", "mc_"],
        "candidate_url_allowed_schemes": ["http", "https"],
        "candidate_url_absolute_prefixes": ["http://", "https://"],
        "asset_file_extensions": [
            ".woff",
            ".woff2",
            ".ttf",
            ".otf",
            ".eot",
            ".css",
            ".js",
            ".map",
        ],
        "image_file_extensions": [
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
            ".gif",
            ".avif",
            ".svg",
        ],
        "deep_alias_list_scan_limit": 40,
        "nested_collection_scan_limit": 20,
        "dynamic_numeric_field_pattern": r"\d+(?:[_-]\d+)*?",
        "dynamic_field_name_pattern": r"[a-z][a-z0-9_]*",
        "color_variant_count_pattern": r"^\d+\s+colors?\b",
        "rating_word_tokens": ["one", "two", "three", "four", "five"],
        "analytics_dimension_token_pattern": r"dimension\d+|metric\d+|cd\d+|ev\d+",
        "alpha_char_pattern": r"[A-Za-z]",
        "ui_noise_token_pattern": r"\b[a-z]+_[a-z0-9_]+\b",
        "ui_icon_token_pattern": r"(corporate_fare|bar_chart|home_pin|location_on|travel_explore|business_center|storefront|schedule|payments|school|work)(?=[A-Z]|\b)|place(?=[A-Z])",
        "script_noise_pattern": r"\b(?:imageloader|document\.getelementbyid|fallback-image)\b",
        "promo_only_title_pattern": r"^(?:[-–—]?\s*)?(?:\d{1,3}%\s*(?:off)?|sale|new(?:\s+in)?|view\s*\d+|best seller|top seller)\s*$",
    },
    "discovered_field_cleanup": {
        "field_noise_tokens": [
            "review",
            "reviews",
            "reviewer",
            "rating",
            "ratings",
            "votes",
            "vote",
            "stars",
            "star",
            "helpful",
            "report",
            "distribution",
            "verified",
            "language",
            "incentives",
            "submission",
        ],
        "value_noise_phrases": [
            "verified reviewer",
            "was this helpful",
            "recommend this product",
            "review this product",
            "filter reviews",
            "rating distribution",
            "overall rating",
            "out of 5",
            "too small",
            "too big",
            "runs very narrow",
            "runs very wide",
            "report this review",
            "reviews with",
            "select to rate",
        ],
    },
    "semantic_detail": {
        "section_skip_patterns": [
            ACTION_ADD_TO_CART,
            ACTION_BUY_NOW,
            "checkout",
            "login",
            ACTION_SIGN_IN,
            "subscribe",
            "review this product",
            "filter reviews",
            "rating distribution",
            "overall rating",
            "verified reviewer",
            "read the story",
            "shop women",
            "shop men's",
            "shop mens",
            "shop men",
        ],
        "section_ancestor_stop_tags": ["footer", "header", "nav", "aside", "form"],
        "section_ancestor_stop_tokens": [
            "footer",
            "header",
            "nav",
            "menu",
            "newsletter",
            "breadcrumbs",
            "breadcrumb",
            "cookie",
            "consent",
            "bazaarvoice",
            "bv-rnr",
            "review",
            "reviews",
            "ratings",
        ],
        "spec_label_block_patterns": [
            "play video",
            "watch video",
            "video",
            "learn more",
            ACTION_ADD_TO_CART,
            ACTION_BUY_NOW,
            "primary guide",
            "guide",
            "discount",
            "verified reviewer",
            "rating summary",
            "filter reviews",
            "report",
            "helpful",
        ],
        "spec_drop_labels": [
            "qty",
            "quantity",
            "details",
            "total",
            "subtotal",
            "delivery",
            "shipping",
            "aggregaterating",
            "aggregate_rating",
            "breadcrumblist",
            "breadcrumb_list",
            "organization",
            "webpage",
            "website",
            "imageobject",
            "image_object",
            "listitem",
            "list_item",
            "searchaction",
            "search_action",
            "offer",
            "itemlist",
            "item_list",
            "howto",
            "faqpage",
            "videoobject",
            "video_object",
            "creativework",
            "creative_work",
            "type",
            "@type",
            "@context",
            "you_are_here",
            "breadcrumb",
            "age",
            "language",
            "incentives",
            "verified_reviewer",
            "rating_distribution",
            "overall_rating",
            "review_this_product",
            "filter_reviews",
            "rating_summary",
            "select",
        ],
        "spec_label_drop_country_names": True,
        "feature_section_aliases": [
            "features",
            "feature",
            "highlights",
            "key_features",
            "key features",
        ],
        "dimension_keywords": [
            "width",
            "height",
            "depth",
            "length",
            "diameter",
            "weight",
            "dimensions",
            "size",
            "measurement",
            "measurements",
        ],
        "aggregate_separator": " | ",
    },
    "jsonld_structural_keys": [
        "@type",
        "@context",
        "@id",
        "@graph",
        "@vocab",
        "@list",
        "@set",
    ],
    "jsonld_non_product_block_types": [
        "organization",
        "website",
        "webpage",
        "breadcrumblist",
        "searchaction",
        "sitenavigationelement",
        "imageobject",
        "videoobject",
        "faqpage",
        "howto",
        "person",
        "localbusiness",
        "store",
    ],
    "product_identity_fields": [
        "title",
        "price",
        "sale_price",
        "original_price",
        "brand",
        "description",
        "sku",
        "image_url",
        "additional_images",
        "availability",
        "category",
    ],
    "nested_non_product_keys": [
        "review",
        "reviews",
        "aggregaterating",
        "aggregate_rating",
        "author",
        "publisher",
        "creator",
        "contributor",
        "breadcrumb",
        "breadcrumblist",
        "itemlistelement",
        "potentialaction",
        "mainentityofpage",
    ],
    "jsonld_type_noise": [
        "aggregaterating",
        "aggregate_rating",
        "breadcrumblist",
        "breadcrumb_list",
        "organization",
        "webpage",
        "website",
        "imageobject",
        "image_object",
        "listitem",
        "list_item",
        "searchaction",
        "search_action",
        "offer",
        "itemlist",
        "item_list",
        "howto",
        "faqpage",
        "videoobject",
        "video_object",
        "creativework",
        "creative_work",
        "type",
        "context",
    ],
    "dynamic_field_name_drop_tokens": [
        "arrivals",
        "bag",
        "best",
        "browse",
        "buy",
        "cart",
        "featured",
        "gifts",
        "less",
        "location",
        "menu",
        "more",
        "new",
        "now",
        "recommended",
        "review",
        "reviews",
        "save",
        "sell",
        "seller",
        "shop",
        "shopping",
        "similar",
        "sort",
        "top",
        "trending",
        "vote",
        "votes",
    ],
    "source_ranking": {
        "contract_xpath": 11,
        "contract_regex": 10,
        "adapter": 9,
        "product_detail": 9,
        "datalayer": 10,
        "json_ld": 9,
        "network_intercept": 8,
        "hydrated_state": 6,
        "embedded_json": 6,
        "open_graph": 6,
        "next_data": 6,
        "microdata": 5,
        "selector": 4,
        "semantic_section": 3,
        "semantic_spec": 3,
        "dom_buy_box": 8,
        "dom": 1,
        "llm_xpath": 0,
    },
    "field_pollution_rules": {
        "title": {
            "reject_phrases": [
                "cookie preferences",
                "privacy policy",
                ACTION_SIGN_IN,
                "log in",
                ACTION_ADD_TO_CART,
            ],
        },
        "brand": {
            "reject_phrases": [
                "cookie",
                "privacy",
                ACTION_SIGN_IN,
                "log in",
                ">",
                "/",
            ],
        },
        "category": {
            "reject_phrases": [
                "cookie",
                "privacy",
                ACTION_SIGN_IN,
                "log in",
            ],
        },
        "description": {
            "reject_phrases": [
                "cookie preferences",
                "privacy settings",
                "manage cookies",
            ],
        },
    },
    "listing_extraction": {
        "card_title_selectors": [
            ".item_description_title",
            "[itemprop='name']",
            ".product-title",
            ".pro-title .text",
            ".pro-title",
            ".name [data-field='description']",
            ".productDescription [data-field='description']",
            ".job-title",
            ".card-title",
            "a.title",
            ".title",
            "h2 a",
            "h3 a",
            "h4 a",
            "h2",
            "h3",
            "h4",
            "a img[alt]",
            "a[title]",
        ],
        "minimal_visual_fields": ["title", "image_url"],
        "product_signal_fields": [
            "price",
            "sku",
            "brand",
            "rating",
            "description",
            "availability",
            "review_count",
            "category",
            "salary",
            "company",
            "location",
        ],
        "job_signal_fields": [
            "company",
            "location",
            "salary",
            "job_type",
            "posted_date",
            "apply_url",
        ],
        "detail_path_markers": [
            "/product/",
            "/products/",
            "/pdp/",
            "/dp/",
            "/detail/",
            "/p/",
            "/item/",
            "piid=",
            "/job/",
            "/jobs/detail/",
            "/jobs/",
            "/position/",
            "/opening/",
            "/job-detail/",
        ],
        "swatch_container_selectors": [
            "[class*='swatch']",
            "[class*='color-chip']",
            "[class*='color-option']",
            "[data-color]",
            "[aria-label*='color' i]",
        ],
        "image_exclude_tokens": [
            "icon",
            "logo",
            "sprite",
            "badge",
            "favicon",
            "placeholder",
            "vehicle-new",
            "fitment-warning",
        ],
        "color_action_values": [
            ACTION_ADD_TO_CART,
            "add to bag",
            "quick view",
            "quick shop",
            "save",
            "wishlist",
            "add to wishlist",
            "more options",
            "select",
            "choose",
            ACTION_BUY_NOW,
            "checkout",
            "shop now",
        ],
        "color_action_prefixes": [
            "add to ",
            "select ",
            "choose ",
            "shop ",
            "buy ",
            "view ",
        ],
        "filter_option_keys": [
            "name",
            "value",
            "selected",
            "tooltip",
            "count",
            "sort",
            "showicon",
            "description",
            "displayname",
            "filtertype",
        ],
        "non_listing_path_tokens": [
            "hiring",
            "employers",
            "recruiter",
            "recruiters",
            "postjobs",
            "demo",
            "pricing",
            "brand",
            "brands",
            "shop",
            "store",
            "catalog",
            "search",
            "results",
            "plans",
            "about",
            "aboutus",
            "contact",
            "contactus",
            "privacy",
            "terms",
            "faq",
            "help",
            "support",
            "careers",
            "press",
            "news",
            "blog",
            "legal",
            "sitemap",
        ],
        "hub_path_segments": [
            "brand",
            "brands",
            "browse",
            "catalog",
            "categories",
            "category",
            "collections",
            "clearance",
            "deals",
            "departments",
            "offers",
            "parts",
            "promo",
            "promotions",
            "results",
            "sale",
            "search",
            "shop",
            "store",
        ],
        "weak_metadata_fields": [
            "title",
            "url",
            "image_url",
            "additional_images",
            "publication_date",
            "posted_date",
            "date",
        ],
        "facet_query_keys": [
            "sv",
            "facet",
            "filter",
            "filters",
            "color",
            "size",
            "material",
            "sort",
        ],
        "facet_path_fragments": ["/see-all", "/filter", "/filters", "/facet"],
        "category_path_markers": [
            "products",
            "categories",
            "category",
            "collections",
            "departments",
            "browse",
            "parts",
        ],
        "buy_box_heading_texts": [
            "select a size",
            "select an option",
            "pricing and availability",
        ],
        "buy_box_required_tokens": ["Pack Size", "SKU", "Availability", "Price"],
        "buy_box_pack_size_pattern": r"Pack Size\s+(?P<value>.+?)\s+SKU(?:\s|$)",
        "buy_box_sku_pattern": r"SKU\s+(?P<value>[A-Za-z0-9-]{3,})",
        "buy_box_availability_pattern": r"Availability\s+(?P<value>.+?)\s+Price(?:\s|$)",
        "buy_box_price_pattern": r"Price\s+(?P<value>[$€£₹]\s*[\d,.]+)",
        "buy_box_currency_symbol_map": {
            "$": "USD",
            "£": "GBP",
            "€": "EUR",
            "₹": "INR",
        },
        "product_detail_required_keys": ["productNumber", "productKey", "name"],
        "product_detail_presence_any_keys": [
            "description",
            "variants",
            "detailedImages",
        ],
        "product_detail_list_scan_limit": 20,
        "structured_spec_groups_key": "specificationGroups",
        "structured_spec_search_max_depth": 7,
        "structured_spec_group_limit": 8,
        "structured_spec_row_limit": 24,
        "product_detail_image_source_keys": [
            "images",
            "detailedImages",
            "colourAlternateViews",
            "variants",
        ],
        "product_detail_top_level_payload_keys": ["getProductDetail", "product"],
        "product_detail_props_path": ["props", "pageProps", "data", "getProductDetail"],
        "product_detail_product_blob_path": ["props", "pageProps", "product"],
        "buy_box_heading_scan_tags": ["h2", "h3", "button", "p", "span"],
        "description_candidate_fields": ["description", "summary"],
        "materials_and_care_section_labels": {
            "materials": "Materials:",
            "care": "Care:",
        },
    },
    "acquisition_guards": {
        "job_redirect_shell_titles": [
            "GovernmentJobs | City, State, Federal & Public Sector Jobs"
        ],
        "job_redirect_shell_canonical_urls": ["https://www.schooljobs.com/"],
        "job_redirect_shell_headings": ["log in", "sign in to apply"],
        "job_error_page_titles": ["Sorry. The page you requested could not be found."],
        "job_error_page_headings": [
            "sorry. the page you requested could not be found."
        ],
    },
    "listing_noise_filters": {
        "navigation_title_hints": [
            "home",
            "login",
            "log in",
            ACTION_SIGN_IN,
            "sign up",
            "register",
            "account",
            "contact",
            "contact us",
            "help",
            "support",
            "read more",
            "learn more",
            "view more",
            "view all",
            "shop all",
            "next",
            "previous",
            "prev",
            "back",
            "checkout",
            "cart",
            "basket",
        ],
        "merchandising_title_prefixes": [
            "shop ",
            "discover ",
            "explore ",
            "find your ",
            "save up ",
            "enjoy ",
            "get ",
        ],
        "editorial_title_patterns": [
            r"\bsponsored\b",
            r"\byou are seeing this ad\b",
            r"\bpromoted\b",
            r"\btrending now\b",
            r"^(?:(?:up to\s+)?\d{1,3}%\s*(?:off\s+)?)?(?:clearance\s+)?sale$",
        ],
        "alt_text_title_pattern": r"\b(?:worn|wearing|shown|shot|mid-shot|close-up|detail(?:ed)? view|view of|front view|back view)\b",
        "weak_listing_titles": [
            "new",
            "sale",
            "featured",
            "best seller",
            "top seller",
            "top rated",
        ],
    },
}

NORMALIZATION_RULES = {
    "price_fields": ["price", "sale_price", "original_price"],
    "price_regex": r"\d[\d,.]*",
    "salary_fields": [
        "salary",
        "compensation",
        "pay",
        "salary_range",
        "base_salary",
        "pay_range",
        "compensation_range",
    ],
    "salary_range_regex": r"(?:(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?\s*\d[\d,.]*[kKmMbB]?\s*(?:[-–—]|to|until)\s*(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?\s*\d[\d,.]*[kKmMbB]?\s*(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?(?:\s*/\s*[a-zA-Z]+)?|(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)\s*\d[\d,.]*[kKmMbB]?(?:\s*(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__))?(?:\s*/\s*[a-zA-Z]+)?|\d[\d,.]*[kKmMbB]?(?:\s*(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__))?(?:\s*/\s*[a-zA-Z]+)?)",
    "currency_codes": [
        "AED",
        "AFN",
        "ALL",
        "AMD",
        "ANG",
        "AOA",
        "ARS",
        "AUD",
        "AWG",
        "AZN",
        "BAM",
        "BBD",
        "BDT",
        "BGN",
        "BHD",
        "BIF",
        "BMD",
        "BND",
        "BOB",
        "BOV",
        "BRL",
        "BSD",
        "BTN",
        "BWP",
        "BYN",
        "BZD",
        "CAD",
        "CDF",
        "CHE",
        "CHF",
        "CHW",
        "CLF",
        "CLP",
        "CNY",
        "COP",
        "COU",
        "CRC",
        "CUP",
        "CVE",
        "CZK",
        "DJF",
        "DKK",
        "DOP",
        "DZD",
        "EGP",
        "ERN",
        "ETB",
        "EUR",
        "FJD",
        "FKP",
        "GBP",
        "GEL",
        "GHS",
        "GIP",
        "GMD",
        "GNF",
        "GTQ",
        "GYD",
        "HKD",
        "HNL",
        "HTG",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "IQD",
        "IRR",
        "ISK",
        "JMD",
        "JOD",
        "JPY",
        "KES",
        "KGS",
        "KHR",
        "KMF",
        "KPW",
        "KRW",
        "KWD",
        "KYD",
        "KZT",
        "LAK",
        "LBP",
        "LKR",
        "LRD",
        "LSL",
        "LYD",
        "MAD",
        "MDL",
        "MGA",
        "MKD",
        "MMK",
        "MNT",
        "MOP",
        "MRU",
        "MUR",
        "MVR",
        "MWK",
        "MXN",
        "MXV",
        "MYR",
        "MZN",
        "NAD",
        "NGN",
        "NIO",
        "NOK",
        "NPR",
        "NZD",
        "OMR",
        "PAB",
        "PEN",
        "PGK",
        "PHP",
        "PKR",
        "PLN",
        "PYG",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "RWF",
        "SAR",
        "SBD",
        "SCR",
        "SDG",
        "SEK",
        "SGD",
        "SHP",
        "SLE",
        "SOS",
        "SRD",
        "SSP",
        "STN",
        "SVC",
        "SYP",
        "SZL",
        "THB",
        "TJS",
        "TMT",
        "TND",
        "TOP",
        "TRY",
        "TTD",
        "TWD",
        "TZS",
        "UAH",
        "UGX",
        "USD",
        "USN",
        "UYI",
        "UYU",
        "UYW",
        "UZS",
        "VED",
        "VES",
        "VND",
        "VUV",
        "WST",
        "XAF",
        "XAG",
        "XAU",
        "XBA",
        "XBB",
        "XBC",
        "XBD",
        "XCD",
        "XDR",
        "XOF",
        "XPD",
        "XPF",
        "XPT",
        "XSU",
        "XTS",
        "XUA",
        "XXX",
        "YER",
        "ZAR",
        "ZMW",
        "ZWG",
    ],
    "currency_symbol_map": {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR"},
    "color_noise_tokens": [
        "rgb(",
        "rgba(",
        "hsl(",
        "var(",
        "background",
        "color:",
        "border:",
        "display:",
        "margin",
        "padding",
        "font-family",
        "font-size",
        "inherit",
    ],
    "size_noise_tokens": [
        "max-width",
        "min-width",
        "vw",
        "vh",
        "sizes=",
        "srcset",
        "rem",
        "em",
        "px",
        "padding",
        "margin",
        "font-size",
        "display:",
        "border:",
        "auto",
    ],
    "non_content_rich_text_tags": [
        "script",
        "style",
        "svg",
        "noscript",
        "iframe",
        "template",
        "meta",
        "link",
    ],
    "noisy_product_attribute_key_tokens": [
        "about",
        "acerca",
        "account",
        "ayuda",
        "contact",
        "cookie",
        "customer",
        "faq",
        "footer",
        "help",
        "newsletter",
        "policy",
        "privacy",
        "return",
        "service",
        "servicios",
        "shipping",
        "social",
        "store",
        "suscrib",
        "terms",
    ],
    "product_attribute_css_noise_pattern": r"(?i)(?:^|\s)(?:@media|@supports|\.?[a-z0-9_-]+\s*\{|(?:padding|margin|display|position|justify-content|align-items|font-size|font-weight|line-height|z-index|flex(?:-direction)?|background|border|width|height|min-width|max-width)\s*:)",
    "product_attribute_digit_only_key_pattern": r"^\d+(?:[_-]\d+)*$",
    "page_url_currency_hints": {
        "/us/": "USD",
        "/en-us/": "USD",
        "/gb/": "GBP",
        "/uk/": "GBP",
        "/en-gb/": "GBP",
        "/ca/": "CAD",
        "/en-ca/": "CAD",
        "/au/": "AUD",
        "/en-au/": "AUD",
        "/eu/": "EUR",
        "/de/": "EUR",
        "/fr/": "EUR",
        "/es/": "EUR",
        "/it/": "EUR",
        "/nl/": "EUR",
        "/in/": "INR",
        "/en-in/": "INR",
        "/jp/": "JPY",
        "/ja-jp/": "JPY",
    },
    "nested_object_keys": {
        "text_fields": [
            "name",
            "label",
            "title",
            "text",
            "value",
            "content",
            "description",
            "alt",
        ],
        "url_fields": ["href", "url", "link", "canonical_url"],
        "price_fields": [
            "specialValue",
            "currentValue",
            "special",
            "current",
            "price",
            "amount",
            "value",
            "lowPrice",
            "minPrice",
            "displayPrice",
            "formattedPrice",
        ],
        "original_price_fields": [
            "compareAtPrice",
            "compare_at_price",
            "listPrice",
            "regularPrice",
            "wasPrice",
            "originalPrice",
            "maxPrice",
            "currentValue",
            "price",
        ],
        "currency_fields": [
            "currency",
            "currencyCode",
            "priceCurrency",
            "currency_code",
        ],
        "category_fields": ["name", "path", "pathEn", "breadcrumb", "categoryPath"],
    },
}

_CANDIDATE_CLEANUP = EXTRACTION_RULES.get("candidate_cleanup", {})
_CANDIDATE_FIELD_GROUPS = _CANDIDATE_CLEANUP.get("field_groups", {})
CANDIDATE_FIELD_GROUPS = {
    str(group): {str(field) for field in fields}
    for group, fields in _CANDIDATE_FIELD_GROUPS.items()
    if isinstance(fields, list)
}
_CANDIDATE_FIELD_NAME_PATTERNS = _CANDIDATE_CLEANUP.get("field_name_patterns", {})
CANDIDATE_URL_SUFFIXES = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "url_suffixes", ["_url", "url", "_link", "link", "_href", "href"]
    )
)
CANDIDATE_IMAGE_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "image_tokens", ["image", "images", "gallery", "photo", "thumbnail", "hero"]
    )
)
CANDIDATE_IMAGE_COLLECTION_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "image_collection_tokens", ["images", "gallery", "photos", "media"]
    )
)
CANDIDATE_CURRENCY_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get("currency_tokens", ["currency"])
)
CANDIDATE_PRICE_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get("price_tokens", ["price", "amount", "cost"])
)
CANDIDATE_SALARY_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "salary_tokens", ["salary", "pay", "rate", "compensation"]
    )
)
CANDIDATE_REVIEW_COUNT_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "review_count_tokens", ["review_count", "reviews", "rating_count"]
    )
)
CANDIDATE_RATING_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get("rating_tokens", ["rating", "score"])
)
CANDIDATE_AVAILABILITY_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get("availability_tokens", ["availability", "stock"])
)
CANDIDATE_CATEGORY_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "category_tokens", ["category", "department", "breadcrumb"]
    )
)
CANDIDATE_IDENTIFIER_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "identifier_tokens", ["sku", "id", "code", "vin", "mpn"]
    )
)
GA_DATA_LAYER_KEYS = frozenset(_CANDIDATE_CLEANUP.get("ga_data_layer_keys", []))
CANDIDATE_DESCRIPTION_TOKENS = tuple(
    _CANDIDATE_FIELD_NAME_PATTERNS.get(
        "description_tokens", ["description", "summary", "overview", "details"]
    )
)
CANDIDATE_UI_NOISE_PHRASES = tuple(_CANDIDATE_CLEANUP.get("ui_noise_phrases", []))
CANDIDATE_IMAGE_NOISE_TOKENS = tuple(_CANDIDATE_CLEANUP.get("image_noise_tokens", []))
CANDIDATE_IMAGE_URL_HINT_TOKENS = tuple(
    _CANDIDATE_CLEANUP.get("image_url_hint_tokens", [])
)
CANDIDATE_IMAGE_CANDIDATE_DICT_KEYS = tuple(
    _CANDIDATE_CLEANUP.get("image_candidate_dict_keys", [])
)
CANDIDATE_COLOR_CSS_NOISE_TOKENS = tuple(
    _CANDIDATE_CLEANUP.get("color_css_noise_tokens", [])
)
CANDIDATE_SIZE_CSS_NOISE_TOKENS = tuple(
    _CANDIDATE_CLEANUP.get("size_css_noise_tokens", [])
)
CANDIDATE_NON_CONTENT_RICH_TEXT_TAGS = frozenset(
    _CANDIDATE_CLEANUP.get(
        "non_content_rich_text_tags",
        ["script", "style", "svg", "noscript", "iframe", "template", "meta", "link"],
    )
)
CANDIDATE_NOISY_PRODUCT_ATTRIBUTE_KEY_TOKENS = frozenset(
    _CANDIDATE_CLEANUP.get(
        "noisy_product_attribute_key_tokens",
        [
            "about",
            "acerca",
            "account",
            "ayuda",
            "contact",
            "cookie",
            "customer",
            "faq",
            "footer",
            "help",
            "newsletter",
            "policy",
            "privacy",
            "return",
            "service",
            "servicios",
            "shipping",
            "social",
            "store",
            "suscrib",
            "terms",
        ],
    )
)
CANDIDATE_PRODUCT_ATTRIBUTE_CSS_NOISE_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "product_attribute_css_noise_pattern",
        r"(?i)(?:^|\s)(?:@media|@supports|\.?[a-z0-9_-]+\s*\{|(?:padding|margin|display|position|justify-content|align-items|font-size|font-weight|line-height|z-index|flex(?:-direction)?|background|border|width|height|min-width|max-width)\s*:)",
    )
)
CANDIDATE_PRODUCT_ATTRIBUTE_DIGIT_ONLY_KEY_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "product_attribute_digit_only_key_pattern",
        r"^\d+(?:[_-]\d+)*$",
    )
)
CANDIDATE_SIZE_PACKAGE_TOKENS = tuple(_CANDIDATE_CLEANUP.get("size_package_tokens", []))
CANDIDATE_AVAILABILITY_NOISE_PHRASES = tuple(
    _CANDIDATE_CLEANUP.get("availability_noise_phrases", [])
)
CANDIDATE_CATEGORY_NOISE_PHRASES = tuple(
    _CANDIDATE_CLEANUP.get("category_noise_phrases", [])
)
CANDIDATE_DESCRIPTION_META_SELECTORS = tuple(
    _CANDIDATE_CLEANUP.get("description_meta_selectors", [])
)
CANDIDATE_DESCRIPTION_FALLBACK_CONTENT_SELECTORS = tuple(
    _CANDIDATE_CLEANUP.get("description_fallback_content_selectors", [])
)
CANDIDATE_TRACKING_PARAM_EXACT_KEYS = frozenset(
    _CANDIDATE_CLEANUP.get("tracking_param_exact_keys", [])
)
CANDIDATE_TRACKING_PARAM_PREFIXES = tuple(
    _CANDIDATE_CLEANUP.get("tracking_param_prefixes", [])
)
CANDIDATE_URL_ALLOWED_SCHEMES = frozenset(
    _CANDIDATE_CLEANUP.get("candidate_url_allowed_schemes", ["http", "https"])
)


def _coerce_int_config(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


CANDIDATE_DEEP_ALIAS_LIST_SCAN_LIMIT = _coerce_int_config(
    _CANDIDATE_CLEANUP.get("deep_alias_list_scan_limit", 40),
    40,
)
CANDIDATE_PLACEHOLDER_VALUES = tuple(_CANDIDATE_CLEANUP.get("placeholder_values", []))
NORMALIZATION_SENTINEL_VALUES = frozenset(
    {
        "object",
        "array",
        "boolean",
        "null",
        "none",
        "undefined",
        "unknown",
        "pending",
        "n/a",
        "na",
    }
).union(CANDIDATE_PLACEHOLDER_VALUES)
CANDIDATE_GENERIC_CATEGORY_VALUES = tuple(
    _CANDIDATE_CLEANUP.get("generic_category_values", [])
)
CANDIDATE_GENERIC_TITLE_VALUES = tuple(
    _CANDIDATE_CLEANUP.get("generic_title_values", [])
)
CANDIDATE_TITLE_NOISE_PHRASES = tuple(_CANDIDATE_CLEANUP.get("title_noise_phrases", []))
CANDIDATE_PROMO_ONLY_TITLE_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "promo_only_title_pattern",
        r"^(?:[-–—]?\s*)?(?:\d{1,3}%\s*(?:off)?|sale|new(?:\s+in)?|view\s*\d+|best seller|top seller)\s*$",
    )
)
CANDIDATE_RATING_WORD_TOKENS = tuple(
    _CANDIDATE_CLEANUP.get(
        "rating_word_tokens", ["one", "two", "three", "four", "five"]
    )
)
CANDIDATE_ANALYTICS_DIMENSION_TOKEN_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "analytics_dimension_token_pattern", r"dimension\d+|metric\d+|cd\d+|ev\d+"
    )
)
CANDIDATE_ALPHA_CHAR_PATTERN = str(
    _CANDIDATE_CLEANUP.get("alpha_char_pattern", r"[A-Za-z]")
)
CANDIDATE_UI_NOISE_TOKEN_PATTERN = str(
    _CANDIDATE_CLEANUP.get("ui_noise_token_pattern", r"\b[a-z]+_[a-z0-9_]+\b")
)
CANDIDATE_UI_ICON_TOKEN_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "ui_icon_token_pattern",
        r"\b(corporate_fare|bar_chart|home_pin|location_on|travel_explore|business_center|storefront|schedule|payments|school|work|place)\b",
    )
)
CANDIDATE_SCRIPT_NOISE_PATTERN = str(
    _CANDIDATE_CLEANUP.get(
        "script_noise_pattern",
        r"\b(?:imageloader|document\.getelementbyid|fallback-image)\b",
    )
)
CANDIDATE_URL_ABSOLUTE_PREFIXES = tuple(
    _CANDIDATE_CLEANUP.get("candidate_url_absolute_prefixes", ["http://", "https://"])
)
CANDIDATE_ASSET_FILE_EXTENSIONS = tuple(
    _CANDIDATE_CLEANUP.get(
        "asset_file_extensions",
        [".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js", ".map"],
    )
)
CANDIDATE_IMAGE_FILE_EXTENSIONS = tuple(
    _CANDIDATE_CLEANUP.get(
        "image_file_extensions",
        [".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif", ".svg"],
    )
)
CANDIDATE_NESTED_COLLECTION_SCAN_LIMIT = int(
    _CANDIDATE_CLEANUP.get("nested_collection_scan_limit", 20)
)
CANDIDATE_DYNAMIC_NUMERIC_FIELD_PATTERN = str(
    _CANDIDATE_CLEANUP.get("dynamic_numeric_field_pattern", r"\d+(?:[_-]\d+)*?")
)
CANDIDATE_DYNAMIC_FIELD_NAME_PATTERN = str(
    _CANDIDATE_CLEANUP.get("dynamic_field_name_pattern", r"[a-z][a-z0-9_]*")
)
CANDIDATE_COLOR_VARIANT_COUNT_PATTERN = str(
    _CANDIDATE_CLEANUP.get("color_variant_count_pattern", r"^\d+\s+colors?\b")
)
CANDIDATE_AVAILABILITY_TOKENS_LIMITED_STOCK = tuple(
    _CANDIDATE_CLEANUP.get("availability_status_tokens", {}).get("limited_stock", [])
)
CANDIDATE_AVAILABILITY_TOKENS_IN_STOCK = tuple(
    _CANDIDATE_CLEANUP.get("availability_status_tokens", {}).get("in_stock", [])
)
CANDIDATE_AVAILABILITY_TOKENS_OUT_OF_STOCK = tuple(
    _CANDIDATE_CLEANUP.get("availability_status_tokens", {}).get("out_of_stock", [])
)
CANDIDATE_AVAILABILITY_TOKENS_PREORDER = tuple(
    _CANDIDATE_CLEANUP.get("availability_status_tokens", {}).get("preorder", [])
)

_DISCOVERED_FIELD_CLEANUP = EXTRACTION_RULES.get("discovered_field_cleanup", {})
DISCOVERED_FIELD_NOISE_TOKENS = set(
    _DISCOVERED_FIELD_CLEANUP.get("field_noise_tokens", [])
)
DISCOVERED_VALUE_NOISE_PHRASES = tuple(
    _DISCOVERED_FIELD_CLEANUP.get("value_noise_phrases", [])
)


def _currency_symbol_class(symbol_map: dict[object, object]) -> str:
    symbols = sorted(
        {str(symbol).strip() for symbol in symbol_map.keys() if str(symbol).strip()}
    )
    if not symbols:
        return r"[$€£¥₹]"
    single_char_symbols = [symbol for symbol in symbols if len(symbol) == 1]
    multi_char_symbols = sorted(
        [symbol for symbol in symbols if len(symbol) > 1], key=len, reverse=True
    )
    if multi_char_symbols:
        alternates = [re.escape(symbol) for symbol in multi_char_symbols]
        if single_char_symbols:
            alternates.append(
                "[" + "".join(re.escape(symbol) for symbol in single_char_symbols) + "]"
            )
        return "(?:" + "|".join(alternates) + ")"
    return "[" + "".join(re.escape(symbol) for symbol in single_char_symbols) + "]"


def _currency_code_alternation(currency_codes: object) -> str:
    if not currency_codes:
        normalized_codes: list[object] | tuple[object, ...] | set[object] = []
    elif isinstance(currency_codes, str):
        normalized_codes = [currency_codes]
    elif isinstance(currency_codes, (list, tuple, set)):
        normalized_codes = currency_codes
    else:
        normalized_codes = [currency_codes]
    codes = sorted(
        {str(code).strip().upper() for code in normalized_codes if str(code).strip()}
    )
    if not codes:
        return r"[A-Z]{3}"
    return "(?:" + "|".join(re.escape(code) for code in codes) + ")"


def _coerce_symbol_map(value: object) -> dict[object, object]:
    return dict(value) if isinstance(value, dict) else {}


def _expand_salary_range_regex(rules: dict[str, object]) -> str:
    """Build the salary range regex with ReDoS-safe patterns.

    The regex avoids nested quantifiers by using bounded repetition
    (``{0,20}`` instead of ``*``) and non-overlapping character classes
    to prevent catastrophic backtracking on adversarial input.
    """
    raw_pattern = str(rules.get("salary_range_regex") or "").strip()
    if not raw_pattern:
        # ReDoS-hardened pattern:
        # - ``\d[\d,.]{0,20}`` bounds digit sequences to prevent unbounded backtracking
        # - ``\s{0,5}`` bounds whitespace instead of ``\s*``
        # - Each branch is non-overlapping by requiring a distinct leading token
        _NUM = r"\d[\d,.]{0,20}[kKmMbB]?"
        _WS = r"\s{0,5}"
        _SEP = r"(?:[-–—]|to|until)"
        _UNIT = rf"(?:{_WS}/{_WS}[a-zA-Z]{{1,20}})?"
        raw_pattern = (
            rf"(?:(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?{_WS}{_NUM}{_WS}"
            rf"{_SEP}{_WS}(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?{_WS}"
            rf"{_NUM}{_WS}(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__)?{_UNIT}"
            rf"|(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__){_WS}"
            rf"{_NUM}(?:{_WS}(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__))?{_UNIT}"
            rf"|{_NUM}(?:{_WS}(?:__CURRENCY_SYMBOL_CLASS__|__CURRENCY_CODE_ALT__))?{_UNIT})"
        )
    currency_symbol_map = _coerce_symbol_map(rules.get("currency_symbol_map"))
    expanded = raw_pattern.replace(
        "__CURRENCY_SYMBOL_CLASS__",
        _currency_symbol_class(currency_symbol_map),
    ).replace(
        "__CURRENCY_CODE_ALT__",
        _currency_code_alternation(rules.get("currency_codes", [])),
    )
    return expanded if expanded.startswith("(?i)") else f"(?i){expanded}"


PRICE_FIELDS = tuple(NORMALIZATION_RULES.get("price_fields", []))
PRICE_REGEX = str(NORMALIZATION_RULES.get("price_regex", r"\d[\d,.]*"))
SALARY_RANGE_REGEX = _expand_salary_range_regex(NORMALIZATION_RULES)
CURRENCY_CODES = tuple(NORMALIZATION_RULES.get("currency_codes", []))
CURRENCY_SYMBOL_MAP = _coerce_symbol_map(NORMALIZATION_RULES.get("currency_symbol_map"))
COLOR_NOISE_TOKENS = tuple(NORMALIZATION_RULES.get("color_noise_tokens", []))
SIZE_NOISE_TOKENS = tuple(NORMALIZATION_RULES.get("size_noise_tokens", []))
HTTP_URL_PREFIXES: tuple[str, str] = ("http://", "https://")

VERDICT_RULES = {
    "detail_core_fields": ["title", "price", "brand"],
    "listing_core_fields": ["title"],
}

MAX_SELECTOR_ROWS_PER_FIELD = 100
EMPTY_SENTINEL_VALUES: frozenset[str] = frozenset(
    {"-", "—", "--", "n/a", "na", "none", "null", "undefined"}
)
DISCOVERED_SOURCE_NOISE_TOKENS: frozenset[str] = frozenset(
    {"review", "reviews", "bazaarvoice", "rating_distribution"}
)
REQUIRED_FIELDS_BY_SURFACE: dict[str, frozenset[str]] = {
    "job_detail": frozenset({"title", "company", "description"}),
    "ecommerce_detail": frozenset({"title"}),
}

HYDRATED_STATE_PATTERNS = [
    "__INITIAL_STATE__",
    "__NUXT__",
    "__APOLLO_STATE__",
    "__PRELOADED_STATE__",
    "__INITIAL_PROPS__",
    "__DATA__",
    "__myx",
    "__STORE__",
    "__APP_STATE__",
]

COOKIE_POLICY = {
    "persist_session_cookies": False,
    "max_persisted_ttl_seconds": 2592000,
    "blocked_name_prefixes": [
        "cf_",
        "__cf",
        "ak_",
        "bm_",
        "dd_",
        "datadome",
        "px",
        "_px",
        "kpsdk",
        "captcha",
    ],
    "blocked_name_contains": [
        "challenge",
        "captcha",
        "datadome",
        "perimeterx",
        "incap",
        "kasada",
        "bot",
    ],
    "harvest_cookie_names": [],
    "harvest_name_prefixes": [],
    "harvest_name_contains": [],
    "blocked_rules_precede_harvest": True,
    "reuse_in_http_client": True,
    "domain_overrides": {},
}

KNOWN_ATS_PLATFORMS = known_ats_domains()


def _compile_extraction_rule_pattern(pattern: object) -> re.Pattern[str]:
    raw_pattern = str(pattern or "").strip()
    if not raw_pattern:
        raise RuntimeError("Invalid empty regex in extraction_rules.py")
    return re.compile(raw_pattern, re.I)


def _compile_extraction_rule_patterns(
    patterns: object,
) -> tuple[re.Pattern[str], ...]:
    normalized_patterns = patterns if isinstance(patterns, (list, tuple)) else []
    return tuple(
        _compile_extraction_rule_pattern(pattern) for pattern in normalized_patterns
    )


DYNAMIC_FIELD_NAME_DROP_TOKENS = set(
    EXTRACTION_RULES.get("dynamic_field_name_drop_tokens", [])
)
CANDIDATE_DYNAMIC_FIELD_NAME_HARD_REJECTS = frozenset(
    _CANDIDATE_CLEANUP.get("dynamic_field_name_hard_rejects", [])
)
_CANDIDATE_SCHEMA_NOISE_PATTERNS = _CANDIDATE_CLEANUP.get(
    "dynamic_field_name_schema_noise_patterns", []
)
DYNAMIC_FIELD_NAME_SCHEMA_NOISE_REGEXES = tuple(
    compiled
    for compiled in (
        _compile_extraction_rule_pattern(pattern)
        for pattern in _CANDIDATE_SCHEMA_NOISE_PATTERNS
    )
    if compiled is not None
)
DYNAMIC_FIELD_NAME_TICKERLIKE_BLOCKLIST = frozenset(
    str(x).strip().lower()
    for x in _CANDIDATE_CLEANUP.get("dynamic_field_name_tickerlike_blocklist", [])
    if str(x).strip()
)
FIELD_POLLUTION_RULES = dict(EXTRACTION_RULES.get("field_pollution_rules", {}))
JSONLD_STRUCTURAL_KEYS = frozenset(
    EXTRACTION_RULES.get(
        "jsonld_structural_keys",
        ["@type", "@context", "@id", "@graph", "@vocab", "@list", "@set"],
    )
)
JSONLD_NON_PRODUCT_BLOCK_TYPES = frozenset(
    EXTRACTION_RULES.get(
        "jsonld_non_product_block_types",
        [
            "organization",
            "website",
            "webpage",
            "breadcrumblist",
            "searchaction",
            "sitenavigationelement",
            "imageobject",
            "videoobject",
            "faqpage",
            "howto",
            "person",
            "localbusiness",
            "store",
        ],
    )
)
JSONLD_TYPE_NOISE = set(EXTRACTION_RULES.get("jsonld_type_noise", []))
PRODUCT_IDENTITY_FIELDS = frozenset(
    EXTRACTION_RULES.get(
        "product_identity_fields",
        [
            "title",
            "price",
            "sale_price",
            "original_price",
            "brand",
            "description",
            "sku",
            "image_url",
            "additional_images",
            "availability",
            "category",
        ],
    )
)
NESTED_NON_PRODUCT_KEYS = frozenset(
    EXTRACTION_RULES.get(
        "nested_non_product_keys",
        [
            "review",
            "reviews",
            "aggregaterating",
            "aggregate_rating",
            "author",
            "publisher",
            "creator",
            "contributor",
            "breadcrumb",
            "breadcrumblist",
            "itemlistelement",
            "potentialaction",
            "mainentityofpage",
        ],
    )
)
SOURCE_RANKING = dict(EXTRACTION_RULES.get("source_ranking", {}))

_SEMANTIC_DETAIL_RULES = EXTRACTION_RULES.get("semantic_detail", {})
SECTION_SKIP_PATTERNS = tuple(
    _SEMANTIC_DETAIL_RULES.get(
        "section_skip_patterns",
        [ACTION_ADD_TO_CART, ACTION_BUY_NOW, "checkout", "login", ACTION_SIGN_IN, "subscribe"],
    )
)
SECTION_ANCESTOR_STOP_TAGS = set(
    _SEMANTIC_DETAIL_RULES.get(
        "section_ancestor_stop_tags", ["footer", "header", "nav", "aside", "form"]
    )
)
SECTION_ANCESTOR_STOP_TOKENS = set(
    _SEMANTIC_DETAIL_RULES.get(
        "section_ancestor_stop_tokens",
        [
            "footer",
            "header",
            "nav",
            "menu",
            "newsletter",
            "breadcrumbs",
            "breadcrumb",
            "cookie",
            "consent",
        ],
    )
)
SPEC_LABEL_BLOCK_PATTERNS = tuple(
    _SEMANTIC_DETAIL_RULES.get(
        "spec_label_block_patterns",
        [
            "play video",
            "watch video",
            "video",
            "learn more",
            ACTION_ADD_TO_CART,
            ACTION_BUY_NOW,
            "primary guide",
            "guide",
            "discount",
        ],
    )
)
SPEC_DROP_LABELS = set(
    _SEMANTIC_DETAIL_RULES.get("spec_drop_labels", ["qty", "quantity", "details"])
)
FEATURE_SECTION_ALIASES = set(
    _SEMANTIC_DETAIL_RULES.get(
        "feature_section_aliases",
        ["features", "feature", "highlights", "key_features", "key features"],
    )
)
DIMENSION_KEYWORDS = tuple(
    _SEMANTIC_DETAIL_RULES.get(
        "dimension_keywords",
        [
            "width",
            "height",
            "depth",
            "length",
            "diameter",
            "weight",
            "dimensions",
            "size",
            "measurement",
            "measurements",
        ],
    )
)
SEMANTIC_AGGREGATE_SEPARATOR = str(
    _SEMANTIC_DETAIL_RULES.get("aggregate_separator", " | ")
)

_LISTING_EXTRACTION_RULES = EXTRACTION_RULES.get("listing_extraction", {})
LISTING_CARD_TITLE_SELECTORS = tuple(
    _LISTING_EXTRACTION_RULES.get("card_title_selectors", [])
)
LISTING_DETAIL_PATH_MARKERS = tuple(
    _LISTING_EXTRACTION_RULES.get("detail_path_markers", [])
)
LISTING_SWATCH_CONTAINER_SELECTORS = tuple(
    _LISTING_EXTRACTION_RULES.get("swatch_container_selectors", [])
)
LISTING_IMAGE_EXCLUDE_TOKENS = tuple(
    _LISTING_EXTRACTION_RULES.get("image_exclude_tokens", [])
)
LISTING_COLOR_ACTION_VALUES = frozenset(
    _LISTING_EXTRACTION_RULES.get("color_action_values", [])
)
LISTING_COLOR_ACTION_PREFIXES = tuple(
    _LISTING_EXTRACTION_RULES.get("color_action_prefixes", [])
)
LISTING_FILTER_OPTION_KEYS = frozenset(
    _LISTING_EXTRACTION_RULES.get("filter_option_keys", [])
)
LISTING_MINIMAL_VISUAL_FIELDS = frozenset(
    _LISTING_EXTRACTION_RULES.get("minimal_visual_fields", [])
)
LISTING_PRODUCT_SIGNAL_FIELDS = frozenset(
    _LISTING_EXTRACTION_RULES.get("product_signal_fields", [])
)
LISTING_JOB_SIGNAL_FIELDS = frozenset(
    _LISTING_EXTRACTION_RULES.get("job_signal_fields", [])
)
LISTING_NON_LISTING_PATH_TOKENS = frozenset(
    _LISTING_EXTRACTION_RULES.get("non_listing_path_tokens", [])
)
LISTING_HUB_PATH_SEGMENTS = frozenset(
    _LISTING_EXTRACTION_RULES.get("hub_path_segments", [])
)
LISTING_WEAK_METADATA_FIELDS = frozenset(
    _LISTING_EXTRACTION_RULES.get("weak_metadata_fields", [])
)
LISTING_FACET_QUERY_KEYS = frozenset(
    _LISTING_EXTRACTION_RULES.get("facet_query_keys", [])
)
LISTING_FACET_PATH_FRAGMENTS = tuple(
    _LISTING_EXTRACTION_RULES.get("facet_path_fragments", [])
)
LISTING_CATEGORY_PATH_MARKERS = frozenset(
    _LISTING_EXTRACTION_RULES.get("category_path_markers", [])
)
LISTING_BUY_BOX_HEADING_TEXTS = frozenset(
    _LISTING_EXTRACTION_RULES.get("buy_box_heading_texts", [])
)
LISTING_BUY_BOX_REQUIRED_TOKENS = tuple(
    _LISTING_EXTRACTION_RULES.get("buy_box_required_tokens", [])
)
LISTING_BUY_BOX_PACK_SIZE_PATTERN = str(
    _LISTING_EXTRACTION_RULES.get(
        "buy_box_pack_size_pattern", r"Pack Size\s+(?P<value>.+?)\s+SKU(?:\s|$)"
    )
)
LISTING_BUY_BOX_SKU_PATTERN = str(
    _LISTING_EXTRACTION_RULES.get(
        "buy_box_sku_pattern", r"SKU\s+(?P<value>[A-Za-z0-9-]{3,})"
    )
)
LISTING_BUY_BOX_AVAILABILITY_PATTERN = str(
    _LISTING_EXTRACTION_RULES.get(
        "buy_box_availability_pattern",
        r"Availability\s+(?P<value>.+?)\s+Price(?:\s|$)",
    )
)
LISTING_BUY_BOX_PRICE_PATTERN = str(
    _LISTING_EXTRACTION_RULES.get(
        "buy_box_price_pattern", r"Price\s+(?P<value>[$€£₹]\s*[\d,.]+)"
    )
)
LISTING_BUY_BOX_CURRENCY_SYMBOL_MAP = dict(
    _LISTING_EXTRACTION_RULES.get("buy_box_currency_symbol_map", {})
)
LISTING_PRODUCT_DETAIL_REQUIRED_KEYS = frozenset(
    _LISTING_EXTRACTION_RULES.get("product_detail_required_keys", [])
)
LISTING_PRODUCT_DETAIL_PRESENCE_ANY_KEYS = frozenset(
    _LISTING_EXTRACTION_RULES.get("product_detail_presence_any_keys", [])
)
LISTING_PRODUCT_DETAIL_LIST_SCAN_LIMIT = int(
    _LISTING_EXTRACTION_RULES.get("product_detail_list_scan_limit", 20)
)
LISTING_STRUCTURED_SPEC_GROUPS_KEY = str(
    _LISTING_EXTRACTION_RULES.get("structured_spec_groups_key", "specificationGroups")
)
LISTING_STRUCTURED_SPEC_SEARCH_MAX_DEPTH = int(
    _LISTING_EXTRACTION_RULES.get("structured_spec_search_max_depth", 7)
)
LISTING_STRUCTURED_SPEC_GROUP_LIMIT = int(
    _LISTING_EXTRACTION_RULES.get("structured_spec_group_limit", 8)
)
LISTING_STRUCTURED_SPEC_ROW_LIMIT = int(
    _LISTING_EXTRACTION_RULES.get("structured_spec_row_limit", 24)
)
LISTING_PRODUCT_DETAIL_IMAGE_SOURCE_KEYS = tuple(
    _LISTING_EXTRACTION_RULES.get(
        "product_detail_image_source_keys",
        ["images", "detailedImages", "colourAlternateViews", "variants"],
    )
)
LISTING_PRODUCT_DETAIL_TOP_LEVEL_PAYLOAD_KEYS = tuple(
    _LISTING_EXTRACTION_RULES.get(
        "product_detail_top_level_payload_keys",
        ["product", "item", "product group", "productgroup", "review"],
    )
)
LISTING_PRODUCT_DETAIL_PROPS_PATH = tuple(
    _LISTING_EXTRACTION_RULES.get(
        "product_detail_props_path", ["props", "pageProps", "data", "getProductDetail"]
    )
)
LISTING_PRODUCT_DETAIL_PRODUCT_BLOB_PATH = tuple(
    _LISTING_EXTRACTION_RULES.get(
        "product_detail_product_blob_path", ["props", "pageProps", "product"]
    )
)
LISTING_BUY_BOX_HEADING_SCAN_TAGS = tuple(
    _LISTING_EXTRACTION_RULES.get(
        "buy_box_heading_scan_tags", ["h2", "h3", "button", "p", "span"]
    )
)
LISTING_DESCRIPTION_CANDIDATE_FIELDS = tuple(
    _LISTING_EXTRACTION_RULES.get(
        "description_candidate_fields", ["description", "summary"]
    )
)
_LISTING_MATERIALS_AND_CARE_SECTION_LABELS = _LISTING_EXTRACTION_RULES.get(
    "materials_and_care_section_labels", {}
)
LISTING_MATERIALS_SECTION_LABEL = str(
    _LISTING_MATERIALS_AND_CARE_SECTION_LABELS.get("materials", "Materials:")
)
LISTING_CARE_SECTION_LABEL = str(
    _LISTING_MATERIALS_AND_CARE_SECTION_LABELS.get("care", "Care:")
)
_LISTING_NOISE = EXTRACTION_RULES.get("listing_noise_filters", {})
LISTING_NAVIGATION_TITLE_HINTS = frozenset(
    _LISTING_NOISE.get("navigation_title_hints", [])
)
LISTING_MERCHANDISING_TITLE_PREFIXES = tuple(
    _LISTING_NOISE.get("merchandising_title_prefixes", [])
)
LISTING_EDITORIAL_TITLE_PATTERNS = _compile_extraction_rule_patterns(
    _LISTING_NOISE.get("editorial_title_patterns", [])
)
LISTING_ALT_TEXT_TITLE_PATTERN = (
    _compile_extraction_rule_pattern(_LISTING_NOISE["alt_text_title_pattern"])
    if _LISTING_NOISE.get("alt_text_title_pattern")
    else None
)
LISTING_WEAK_TITLES = frozenset(_LISTING_NOISE.get("weak_listing_titles", []))
