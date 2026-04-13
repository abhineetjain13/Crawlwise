from __future__ import annotations

DATALAYER_ECOMMERCE_FIELD_MAP = {
    # GA4 schema
    "items[0].price": "price",
    "items[0].discount": "discount_amount",
    "items[0].item_category": "category",
    "items[0].currency": "price_currency",
    # UA schema
    "detail.products[0].price": "price",
    "detail.products[0].category": "category",
    "currencyCode": "price_currency",
}

CANONICAL_SCHEMAS = {
    "ecommerce_listing": [
        "title",
        "brand",
        "sku",
        "part_number",
        "price",
        "sale_price",
        "discount_amount",
        "discount_percentage",
        "original_price",
        "currency",
        "availability",
        "image_url",
        "additional_images",
        "color",
        "size",
        "dimensions",
        "rating",
        "review_count",
        "url",
    ],
    "ecommerce_detail": [
        "title",
        "brand",
        "sku",
        "part_number",
        "price",
        "sale_price",
        "discount_amount",
        "discount_percentage",
        "original_price",
        "currency",
        "availability",
        "image_url",
        "additional_images",
        "description",
        "rating",
        "review_count",
        "category",
        "color",
        "size",
        "materials",
        "care",
        "features",
        "specifications",
        "product_attributes",
        "variant_axes",
        "variants",
        "selected_variant",
    ],
    "job_listing": [
        "title",
        "job_id",
        "company",
        "location",
        "salary",
        "job_type",
        "posted_date",
        "department",
        "description",
        "url",
        "apply_url",
    ],
    "job_detail": [
        "title",
        "company",
        "location",
        "salary",
        "job_type",
        "posted_date",
        "apply_url",
        "description",
        "requirements",
        "responsibilities",
        "qualifications",
        "benefits",
        "skills",
        "remote",
    ],
    "automobile_listing": [
        "title",
        "price",
        "url",
        "image_url",
        "make",
        "model",
        "year",
        "mileage",
        "location",
        "dealer_name",
    ],
    "automobile_detail": [
        "title",
        "price",
        "currency",
        "make",
        "model",
        "year",
        "trim",
        "mileage",
        "vin",
        "condition",
        "body_style",
        "fuel_type",
        "transmission",
        "drivetrain",
        "exterior_color",
        "interior_color",
        "location",
        "dealer_name",
        "image_url",
        "description",
    ],
    "tabular": [],
}

FIELD_ALIASES = {
    "title": [
        "title",
        "name",
        "job_title",
        "position",
        "headline",
        "productName",
        "product_name",
    ],
    "url": [
        "url",
        "link",
        "href",
        "canonical_url",
        "canonicalUrl",
        "product_url",
        "productUrl",
        "productURL",
        "pdp_url",
        "pdpUrl",
        "pdpURL",
        "seo_url",
        "seoUrl",
        "item_url",
        "itemUrl",
        "landingPageUrl",
        "detailPageLink",
        "detail_page_link",
        "detailUrl",
        "detail_url",
        "workUrl",
        "listingUrl",
        "positionURI",
    ],
    "slug": ["slug"],
    "price": [
        "price",
        "amount",
        "cost",
        "current_price",
        "buyNowPrice",
        "lowPrice",
    ],
    "sale_price": [
        "sale_price",
        "saleprice",
        "sellingprice",
        "newprice",
        "discount_price",
        "discountedPrice",
    ],
    "discount_amount": [
        "discount_amount",
        "discount",
        "discountValue",
        "discount_value",
    ],
    "discount_percentage": [
        "discount_percentage",
        "discount_percent",
        "percent_off",
        "off_percentage",
    ],
    "original_price": [
        "compare_at_price",
        "list_price",
        "regular_price",
        "was_price",
        "original_price",
        "mrp",
        "listPrice",
        "highPrice",
    ],
    "currency": ["currency", "currency_code", "price_currency"],
    "brand": [
        "brand",
        "vendor",
        "manufacturer",
        "manufacturer_name",
        "brand_name",
        "designer",
        "brandName",
    ],
    "image_url": [
        "image",
        "image_url",
        "thumbnail",
        "img",
        "photo",
        "logo",
        "featured_image",
        "primary_image",
        "searchImage",
        "imageUrl",
    ],
    "additional_images": [
        "image",
        "images",
        "gallery",
        "gallery_images",
        "product_images",
        "media",
        "photos",
        "assets",
    ],
    "color": ["color", "colors", "color_name", "finish", "frame_color", "colour"],
    "color_variants": [
        "color_variants",
        "color variants",
        "available colors",
        "swatch",
        "color_swatch",
        "color_options",
    ],
    "size": ["sizes", "variant_size"],
    "variant_axes": ["variant_axes", "options", "product_options", "option_axes"],
    "variants": ["variants", "variant_rows", "variant_matrix"],
    "selected_variant": ["selected_variant", "current_variant", "active_variant"],
    "product_attributes": [
        "product_attributes",
        "attributes",
        "product_attrs",
        "productAttributes",
    ],
    "materials": ["materials", "material", "fabric", "composition", "fabric_content"],
    "care": ["care", "care_instructions", "product_care"],
    "company": [
        "company",
        "company_name",
        "companyName",
        "organization",
        "employer",
        "hiring_organization",
        "agency",
    ],
    "location": [
        "location",
        "candidate_required_location",
        "job_location",
        "city",
        "region",
    ],
    "salary": ["salary", "compensation", "pay", "salary_range", "salaryDisplay"],
    "salary_currency": ["salary_currency", "salary_currency_code", "pay_currency"],
    "salary_min": ["salary_min", "min_salary", "minimum_salary"],
    "salary_max": ["salary_max", "max_salary", "maximum_salary"],
    "job_id": [
        "job_id",
        "jobId",
        "requisition_id",
        "requisitionId",
        "req_id",
        "opening_id",
    ],
    "category": [
        "category",
        "type",
        "product_type",
    ],
    "department": ["department", "team", "division", "org_department"],
    "sku": ["sku", "product_id", "item_id", "id"],
    "part_number": [
        "part_number",
        "part",
        "part_no",
        "partNumber",
        "mpn",
        "manufacturer_part_number",
    ],
    "availability": ["availability", "in_stock", "stock_status", "inStock"],
    "tags": ["tags", "labels", "keywords"],
    "rating": ["rating", "average_rating", "score", "rating_value", "aggregate_rating"],
    "review_count": ["review_count", "total_reviews", "num_reviews", "numberOfReviews"],
    "stock_quantity": ["stock_quantity", "inventory_quantity", "quantity_available"],
    "publication_date": [
        "publication_date",
        "date",
        "created_at",
        "published_at",
        "pub_date",
        "published_date",
    ],
    "posted_date": ["posted_date", "date_posted", "posted_at", "job_posted_date"],
    "apply_url": ["apply_url", "application_url", "job_url", "product_link"],
    "company_logo": ["company_logo", "companyLogo", "employer_logo"],
    "responsibilities": [
        "responsibilities",
        "duties",
        "job_duties",
        "what_you_ll_do",
        "what_you_will_do",
    ],
    "qualifications": [
        "qualifications",
        "job_qualification",
        "minimum_requirements",
        "preferred_qualifications",
        "who_you_are",
    ],
    "benefits": [
        "benefits",
        "job_benefits",
        "perks",
        "compensation_benefits",
        "what_we_offer",
    ],
    "skills": [
        "skills",
        "job_skills",
        "competencies",
        "abilities",
        "what_you_ll_bring",
    ],
    "remote": ["remote", "work_from_home", "wfh", "telecommute"],
    "employment_type": ["employment_type", "schedule_type"],
    "experience_level": ["experience_level", "experience", "experienceLevel"],
    "job_function": ["job_function", "function", "jobFunction"],
    "seniority_level": ["seniority_level", "seniority", "seniorityLevel"],
    "work_model": ["work_model", "workplace_type", "workplaceType"],
    "specifications": [
        "specifications",
        "details",
        "technical_details",
        "product_details",
        "the_details",
    ],
    "features": ["features", "highlights", "key_features"],
    "dimensions": ["dimensions", "sizing", "measurements"],
    "summary": ["summary", "overview", "about"],
    "requirements": ["requirements", "job_requirements", "prerequisites"],
    "job_type": ["job_type"],
    "make": ["make"],
    "model": ["model"],
    "year": ["year"],
    "trim": ["trim"],
    "mileage": ["mileage", "distance"],
    "vin": ["vin"],
    "condition": ["condition"],
    "body_style": ["body_style", "body type"],
    "fuel_type": ["fuel_type", "fuel"],
    "transmission": ["transmission"],
    "drivetrain": ["drivetrain"],
    "exterior_color": ["exterior_color", "exterior color"],
    "interior_color": ["interior_color"],
    "dealer_name": ["dealer_name", "dealer"],
    "price_original": ["price_original"],
}

# Fields that are only meaningful for ecommerce surfaces.
# These must NOT be resolved on job_listing or job_detail surfaces.
ECOMMERCE_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "additional_images",
        "availability",
        "brand",
        "color",
        "color_variants",
        "condition",
        "currency",
        "exterior_color",
        "image_url",
        "interior_color",
        "part_number",
        "price",
        "product_attributes",
        "price_original",
        "original_price",
        "rating",
        "review_count",
        "sale_price",
        "sku",
        "stock_quantity",
    }
)

# Fields that are only meaningful for job surfaces.
# These must NOT be resolved on ecommerce_listing or ecommerce_detail surfaces.
JOB_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "apply_url",
        "company",
        "company_logo",
        "employment_type",
        "experience_level",
        "job_function",
        "job_id",
        "location",
        "posted_date",
        "remote",
        "salary",
        "salary_currency",
        "salary_max",
        "salary_min",
        "seniority_level",
        "work_model",
    }
)

# Fields that must NEVER appear in any user-facing output on any surface.
INTERNAL_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "slug",
        "_raw_item",
        "_source",
        "_score",
    }
)


def excluded_fields_for_surface(surface: str) -> frozenset[str]:
    normalized = (surface or "").strip().lower()
    excluded: frozenset[str] = INTERNAL_ONLY_FIELDS
    if normalized in {"job_listing", "job_detail"}:
        return excluded | ECOMMERCE_ONLY_FIELDS
    if normalized in {"ecommerce_listing", "ecommerce_detail"}:
        return excluded | JOB_ONLY_FIELDS
    if normalized in {"automobile_listing", "automobile_detail"}:
        return excluded | JOB_ONLY_FIELDS | ECOMMERCE_ONLY_FIELDS
    return excluded


def field_allowed_for_surface(surface: str, field_name: str) -> bool:
    normalized_field = str(field_name or "").strip().lower()
    return bool(
        normalized_field and normalized_field not in excluded_fields_for_surface(surface)
    )


def get_surface_field_aliases(surface: str) -> dict[str, list[str]]:
    """
    Return FIELD_ALIASES filtered to only the fields appropriate for the given surface.

    - Job surfaces: exclude all ECOMMERCE_ONLY_FIELDS and INTERNAL_ONLY_FIELDS.
    - Ecommerce surfaces: exclude all JOB_ONLY_FIELDS and INTERNAL_ONLY_FIELDS.
    - Unknown/unset surface: exclude only INTERNAL_ONLY_FIELDS.
    """
    normalized = (surface or "").strip().lower()
    excluded = excluded_fields_for_surface(normalized)

    aliases = {
        canonical: list(aliases)
        for canonical, aliases in FIELD_ALIASES.items()
        if canonical not in excluded
    }
    if normalized in {"automobile_listing", "automobile_detail"}:
        automobile_aliases = {
            canonical: list(values) for canonical, values in aliases.items()
        }
        make_aliases = automobile_aliases.setdefault("make", [])
        if "manufacturer" not in make_aliases:
            make_aliases.append("manufacturer")
        brand_aliases = automobile_aliases.get("brand")
        if brand_aliases is not None:
            automobile_aliases["brand"] = [
                alias for alias in brand_aliases if alias != "manufacturer"
            ]
        return automobile_aliases
    return aliases


COLLECTION_KEYS = [
    "products",
    "items",
    "results",
    "records",
    "listings",
    "jobs",
    "job-list",
    "job_list",
    "postings",
    "positions",
    "openings",
    "hits",
    "nodes",
    "categories",
    "collections",
    "offers",
    "deals",
    "events",
    "properties",
    "rows",
]

def _dedupe_aliases(*groups: object) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if isinstance(group, str):
            candidates = (group,)
        elif isinstance(group, (list, tuple, set)):
            candidates = group
        else:
            continue
        for alias in candidates:
            cleaned = str(alias).strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                deduped.append(cleaned)
    return deduped


_REQUESTED_FIELD_ALIAS_BASES = {
    "responsibilities": FIELD_ALIASES["responsibilities"],
    "qualifications": FIELD_ALIASES["qualifications"],
    "benefits": FIELD_ALIASES["benefits"],
    "skills": FIELD_ALIASES["skills"],
    "summary": FIELD_ALIASES["summary"],
    "specifications": FIELD_ALIASES["specifications"],
    "features": FIELD_ALIASES["features"],
    "materials": FIELD_ALIASES["materials"],
    "material": FIELD_ALIASES["materials"],
    "care": FIELD_ALIASES["care"],
    "dimensions": FIELD_ALIASES["dimensions"],
    "remote": FIELD_ALIASES["remote"],
    "requirements": FIELD_ALIASES["requirements"],
    "country_of_origin": [
        "country of origin",
        "country_of_origin",
        "origin",
        "made in",
        "manufactured in",
        "importer",
        "importer_info",
        "importer name and address",
    ],
    "color_variants": FIELD_ALIASES["color_variants"],
}
_REQUESTED_FIELD_ALIAS_EXTRAS = {
    "responsibilities": (
        "job responsibilities",
        "key responsibilities",
        "job duties",
        "what you'll do",
        "what_you_ll_do",
        "what_you_will_do",
        "role responsibilities",
    ),
    "qualifications": (
        "job qualifications",
        "job_qualification",
        "minimum requirements",
        "minimum_requirements",
        "preferred qualifications",
        "preferred_qualifications",
        "who you are",
        "what we're looking for",
    ),
    "benefits": ("job benefits", "perks", "why you'll love this job", "life at stripe"),
    "skills": ("job skills", "job_skills", "experience", "what you'll bring"),
    "summary": ("description", "our opportunity", "about the role", "about the team"),
    "specifications": ("specs", "spec", "technical details", "tech specs", "the details"),
    "features": ("key features",),
    "materials": ("fabrics", "material composition"),
    "material": ("fabrics", "material composition"),
    "care": ("care instructions", "washing instructions"),
}

REQUESTED_FIELD_ALIASES = {
    canonical: _dedupe_aliases(
        _REQUESTED_FIELD_ALIAS_BASES[canonical],
        _REQUESTED_FIELD_ALIAS_EXTRAS.get(canonical, ()),
    )
    for canonical in _REQUESTED_FIELD_ALIAS_BASES
}

PROMPT_REGISTRY = {
    "xpath_discovery": {
        "system_file": "xpath_discovery.system.txt",
        "user_file": "xpath_discovery.user.txt",
        "response_type": "object",
        "data_key": "selectors",
    },
    "missing_field_extraction": {
        "system_file": "missing_field_extraction.system.txt",
        "user_file": "missing_field_extraction.user.txt",
        "response_type": "object",
    },
    "field_cleanup_review": {
        "system_file": "field_cleanup_review.system.txt",
        "user_file": "field_cleanup_review.user.txt",
        "response_type": "object",
    },
    "page_classification": {
        "system_file": "page_classification.system.txt",
        "user_file": "page_classification.user.txt",
        "response_type": "object",
    },
    "schema_inference": {
        "system_file": "schema_inference.system.txt",
        "user_file": "schema_inference.user.txt",
        "response_type": "object",
    },
}
