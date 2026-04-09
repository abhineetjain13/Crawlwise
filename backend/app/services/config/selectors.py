from __future__ import annotations

from urllib.parse import urlparse

TITLE_SELECTOR = "h1 a, h2 a, h3 a, h4 a, h5 a, h1, h2, h3, h4, h5"
ANCHOR_SELECTOR = "a[href]"

DOM_PATTERNS = {
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
}

CARD_SELECTORS = {
    "ecommerce": [
        "[data-component-type='s-search-result']",
        ".s-item",
        ".product-card",
        ".product-item",
        ".product-tile",
        ".product-grid-item",
        "[data-testid='product-card']",
        ".grid-item[data-product-id]",
        ".product_pod",
        ".collection-product-card",
        "[data-testid='grid-view-products'] > article",
        "[data-testid='list-view-products'] > article",
        "li.grid__item",
        ".plp-card",
        ".search-result-gridview-item",
        ".product",
        "article.product",
        "[itemscope][itemtype*='Product']",
        ".thumbnail[itemscope]",
        "[class*='ProductCard']",
        "[class*='product-tile']",
        "[class*='SearchResultTile']",
        "[class*='AllEditionsItem-tile']",
        "[class*='search-result-item']",
    ],
    "jobs": [
        "[data-qa-id='search-result']",
        "#search-results > div.border.border-gray-lighter.bg-white.p-4",
        ".job_seen_beacon",
        ".base-card",
        ".job-card",
        ".job-listing",
        ".job-result",
        ".posting",
        "[data-testid='job-card']",
        ".jobsearch-ResultsList > div",
        "li.jobs-search__results-list-item",
        "article.elementor-post",
        "article[class*='category-jobs']",
        ".elementor-post",
        "li[data-testid='careers-search-result-listing']",
        ".pp-content-post.job_listing",
        ".pp-content-grid-post.job_listing",
        "div.job_listing",
        "tr.job-row",
        "div[data-job-id]",
        ".opening",
    ],
    "_jobs_selector_notes": [
        "USAJobs search result cards render as direct children of #search-results with classes border border-gray-lighter bg-white p-4; see backend/tests/services/extract/test_listing_extractor_urls.py.",
    ],
}

PAGINATION_SELECTORS = {
    "next_page": [
        "a[rel='next']",
        "a[aria-label*='next' i]",
        "a[title*='next' i]",
        "a:has-text('Next')",
        "button[aria-label*='next' i]",
    ],
    "load_more": [
        "button:has-text('Load More')",
        "button:has-text('Show More')",
        "button:has-text('View All')",
        "a:has-text('Load More')",
        "[data-testid='load-more']",
        ".load-more",
    ],
}

CONSENT_SELECTORS = [
    "button#onetrust-accept-btn-handler",
    "button#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "button#CybotCookiebotDialogBodyUnderlayAccept",
    "#truste-consent-button",
    "[data-consent='accept']",
    "[data-consent-action='accept']",
    "[data-accept='true']",
    "[data-testid='cookie-accept']",
    "[data-testid='consent-accept']",
    ".cookie-banner [data-consent='accept']",
    ".cookie-banner [data-accept='true']",
    ".cookie-consent-accept",
    "#cookieConsentAccept",
    ".fc-button.fc-cta-consent",
    ".fc-button.fc-cta-accept",
    ".fc-primary-button",
    "[id*='accept' i][id*='cookie' i]",
    "[class*='accept' i][class*='cookie' i]",
    "[id*='consent' i][id*='accept' i]",
    "[class*='consent' i][class*='accept' i]",
    "[aria-label='Accept Cookies']",
    "[aria-label='Accept all']",
    "[aria-label='Accept All']",
    "[aria-label='Accept cookie policy']",
    "[aria-label='Aceptar cookies']",
    "[aria-label='Aceptar todo']",
    "[aria-label='Tout accepter']",
    "[aria-label='Accepter les cookies']",
    "[aria-label='Alle akzeptieren']",
    "[aria-label='Akzeptieren']",
    "[aria-label='Aceitar cookies']",
    "[aria-label='Aceitar tudo']",
    "button:has-text('Accept All')",
    "button:has-text('Accept Cookies')",
    "button:has-text('I Accept')",
    "button:has-text('Agree')",
    "button:has-text('Aceptar todo')",
    "button:has-text('Aceptar cookies')",
    "button:has-text('Acepto')",
    "button:has-text('Tout accepter')",
    "button:has-text('Accepter')",
    "button:has-text('Accepter les cookies')",
    "button:has-text('Alle akzeptieren')",
    "button:has-text('Akzeptieren')",
    "button:has-text('Ich akzeptiere')",
    "button:has-text('Aceitar tudo')",
    "button:has-text('Aceitar cookies')",
    "button:has-text('Concordo')",
]

COOKIE_CONSENT_SELECTORS = CONSENT_SELECTORS

PLATFORM_LISTING_READINESS_SELECTORS: dict[str, list[str]] = {
    "oracle_hcm": [
        "a[href*='/job/']",
    ],
    "adp": [
        ".current-openings-item",
        "[id^='lblTitle_']",
    ],
    "paycom": [
        "a[href*='/jobs/']",
    ],
    "ultipro_ukg": [
        "a[href*='/jobboard/jobdetails/']",
        "a[href*='/jobboard/']",
        "[data-testid*='job' i]",
    ],
}

PLATFORM_LISTING_READINESS_URL_PATTERNS: dict[str, list[list[str]]] = {
    "oracle_hcm": [["candidateexperience", "oraclecloud.com"]],
    "adp": [["workforcenow.adp.com"]],
    "paycom": [["paycomonline.net"]],
    "ultipro_ukg": [["recruiting.ultipro.com"]],
}

PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES: dict[str, int] = {
    "oracle_hcm": 25_000,
    "adp": 20_000,
    "paycom": 20_000,
    "ultipro_ukg": 20_000,
}


def _build_listing_readiness_overrides() -> dict[str, dict[str, object]]:
    """Backward-compatible domain lookup map derived from platform patterns."""
    overrides: dict[str, dict[str, object]] = {}
    for platform, pattern_groups in PLATFORM_LISTING_READINESS_URL_PATTERNS.items():
        selectors = PLATFORM_LISTING_READINESS_SELECTORS.get(platform) or []
        if not selectors:
            continue
        max_wait_ms = int(PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES.get(platform, 0) or 0)
        groups = pattern_groups if isinstance(pattern_groups, list) else []
        for group in groups:
            if not isinstance(group, list):
                continue
            normalized_group = [
                str(token or "").strip().lower()
                for token in group
                if str(token or "").strip()
            ]
            domain_tokens = [
                token
                for token in normalized_group
                if "." in token
            ]
            prefix_tokens = [token for token in normalized_group if "." not in token]
            for domain in domain_tokens:
                overrides[domain] = {
                    "platform": platform,
                    "selectors": list(selectors),
                    "max_wait_ms": max_wait_ms,
                }
                for prefix in prefix_tokens:
                    combined = f"{prefix}.{domain}"
                    overrides[combined] = {
                        "platform": platform,
                        "selectors": list(selectors),
                        "max_wait_ms": max_wait_ms,
                    }
    return overrides


LISTING_READINESS_OVERRIDES: dict[str, dict[str, object]] = _build_listing_readiness_overrides()

def resolve_listing_readiness_override(page_url: str) -> dict[str, object] | None:
    """Return platform override using configured URL patterns and selector maps."""
    normalized_url = str(page_url or "").strip().lower()
    if not normalized_url:
        return None
    domain = str(urlparse(normalized_url).netloc or "").strip().lower()
    for platform, pattern_groups in PLATFORM_LISTING_READINESS_URL_PATTERNS.items():
        groups = pattern_groups if isinstance(pattern_groups, list) else []
        if not any(
            isinstance(group, list)
            and group
            and all(str(token or "").strip().lower() in normalized_url for token in group)
            for group in groups
        ):
            continue
        selectors = PLATFORM_LISTING_READINESS_SELECTORS.get(platform) or []
        max_wait_ms = int(PLATFORM_LISTING_READINESS_MAX_WAIT_OVERRIDES.get(platform, 0) or 0)
        if not selectors:
            continue
        return {
            "platform": platform,
            "domain": domain,
            "selectors": list(selectors),
            "max_wait_ms": max_wait_ms,
        }
    return None

REVIEW_CONTAINER_KEYS = [
    "adapter_data",
    "network_payloads",
    "next_data",
    "_hydrated_states",
    "json_ld",
    "microdata",
    "tables",
    "content_type",
    "source",
    "full_json_response",
    "json_record_keys",
    "requested_field_coverage",
    "sections",
    "specifications",
    "promoted_fields",
    "coverage",
    "is_blocked",
    "reason",
    "provider",
]

MARKDOWN_VIEW = {
    "long_form_fields": [
        "description",
        "summary",
        "responsibilities",
        "qualifications",
        "requirements",
        "benefits",
        "skills",
        "how_to_apply",
        "next_steps",
        "education",
        "additional_information",
        "conditions_of_employment",
        "required_documents",
        "how_you_will_be_evaluated",
        "features",
        "fit_and_sizing",
        "materials_and_care",
    ],
    "section_blacklist": ["help", "close_this_window"],
    "section_min_chars": 12,
    "scalar_max_chars": 180,
}

DISCOVERIST_SCHEMA = ["source_url", "title", "description"]
