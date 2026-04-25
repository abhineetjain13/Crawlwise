from __future__ import annotations

from typing import Final

from app.services.config.runtime_settings import crawler_runtime_settings


FieldPathMap = dict[str, tuple[str, ...]]
PayloadMappingSpec = dict[
    str,
    str | tuple[str, ...] | tuple[tuple[str, ...], ...] | FieldPathMap,
]
NETWORK_PAYLOAD_SIGNATURE_MIN_MATCH: Final[int] = (
    crawler_runtime_settings.network_payload_signature_min_match
)
NETWORK_PAYLOAD_PRODUCT_SIGNATURE: Final[frozenset[str]] = frozenset(
    {
        "availability",
        "body_html",
        "brand",
        "brand_name",
        "category",
        "compare_at_price",
        "currency",
        "description",
        "detail_url",
        "image",
        "image_url",
        "images",
        "inventory_quantity",
        "name",
        "price",
        "product_name",
        "product_specifications",
        "product_title",
        "product_type",
        "sku",
        "title",
        "url",
        "variant",
        "variants",
        "vendor",
    }
)
NETWORK_PAYLOAD_JOB_SIGNATURE: Final[frozenset[str]] = frozenset(
    {
        "title",
        "description",
        "location",
        "company",
        "apply_url",
        "posted_date",
        "employment_type",
        "salary",
        "department",
        "qualifications",
        "responsibilities",
        "benefits",
        "remote",
        "date_posted",
        "datePosted",
        "applyUrl",
        "job_type",
        "content",
        "absolute_url",
        "company_name",
    }
)
NETWORK_PAYLOAD_LIST_COLLECTION_KEYS: Final[frozenset[str]] = frozenset(
    {"data", "edges", "items", "listings", "nodes", "products", "records", "results"}
)
NETWORK_PAYLOAD_DETAIL_CONTAINER_KEYS: Final[frozenset[str]] = frozenset(
    {"item", "job", "posting", "product", "record"}
)
GHOST_ROUTE_COMPATIBLE_SURFACES: Final[frozenset[str]] = frozenset(
    {
        "ecommerce_detail",
        "job_detail",
    }
)
DETAIL_URL_IGNORE_TOKENS: Final[frozenset[str]] = frozenset(
    {"detail", "details", "dp", "item", "job", "p", "product", "products"}
)


NETWORK_PAYLOAD_SPECS: Final[dict[str, tuple[PayloadMappingSpec, ...]]] = {
    "job_detail": (
        {
            "name": "greenhouse_detail",
            "endpoint_families": ("greenhouse",),
            "required_path_groups": (
                ("content",),
                ("absolute_url",),
            ),
            "field_paths": {
                "title": ("title",),
                "company": ("company_name",),
                "location": ("location.name",),
                "apply_url": ("absolute_url",),
                "posted_date": ("first_published",),
                "updated_at": ("updated_at",),
                "description_html": ("content",),
            },
        },
        {
            "name": "workday_detail",
            "endpoint_families": ("workday",),
            "required_path_groups": (
                ("jobPostingInfo.title",),
                ("jobPostingInfo.jobDescription",),
            ),
            "field_paths": {
                "title": ("jobPostingInfo.title",),
                "company": ("hiringOrganization.name",),
                "location": ("jobPostingInfo.location",),
                "apply_url": ("jobPostingInfo.externalUrl",),
                "posted_date": ("jobPostingInfo.postedOn",),
                "job_type": ("jobPostingInfo.timeType",),
                "job_id": ("jobPostingInfo.jobReqId",),
                "country": ("jobPostingInfo.country",),
                "description_html": ("jobPostingInfo.jobDescription",),
            },
        },
        {
            "name": "lever_detail",
            "endpoint_families": ("lever",),
            "required_path_groups": (
                ("text", "description", "categories.team"),
                ("applyUrl", "hostedUrl", "urls.apply"),
            ),
            "field_paths": {
                "title": ("text",),
                "company": ("company",),
                "location": ("categories.location",),
                "team": ("categories.team",),
                "department": ("categories.department",),
                "commitment": ("categories.commitment",),
                "workplace_type": ("categories.workplaceType",),
                "apply_url": ("applyUrl", "hostedUrl", "urls.apply"),
                "posted_date": ("createdAt",),
                "description_html": ("description", "descriptionPlain"),
            },
        },
        {
            "name": "generic_job_detail",
            "endpoint_type": "job_api",
            "endpoint_path_tokens": (
                "/jobs/",
                "/job_posts/",
                "/postings/",
                "/positions/",
                "/requisition/",
                "/careers/",
            ),
            "required_path_groups": (
                (
                    "posting.title",
                    "job.title",
                    "job.name",
                    "position.title",
                    "position.name",
                    "data.job.title",
                    "data.job.name",
                    "data.posting.title",
                    "title",
                    "name",
                ),
                (
                    "posting.description",
                    "posting.content",
                    "job.description",
                    "job.content",
                    "position.description",
                    "position.content",
                    "data.job.description",
                    "data.posting.description",
                    "description",
                    "content",
                ),
            ),
            "field_paths": {
                "title": (
                    "posting.title",
                    "job.title",
                    "job.name",
                    "position.title",
                    "position.name",
                    "data.job.title",
                    "data.job.name",
                    "data.posting.title",
                    "title",
                    "name",
                ),
                "company": (
                    "posting.organization.name",
                    "job.company.name",
                    "job.company",
                    "position.company.name",
                    "position.company",
                    "company.name",
                    "company",
                    "employer.name",
                    "employer",
                    "organization.name",
                    "organization",
                    "data.job.company.name",
                    "data.posting.organization.name",
                ),
                "location": (
                    "posting.location.name",
                    "posting.locations[0].name",
                    "job.location.name",
                    "job.location",
                    "job.locations[0].name",
                    "position.location.name",
                    "position.location",
                    "location.name",
                    "location",
                    "locations[0].name",
                    "data.job.location.name",
                    "data.posting.location.name",
                ),
                "apply_url": (
                    "posting.applyUrl",
                    "posting.apply_url",
                    "job.applyUrl",
                    "job.apply_url",
                    "position.applyUrl",
                    "position.apply_url",
                    "applyUrl",
                    "apply_url",
                    "applicationUrl",
                    "application_url",
                    "url",
                ),
                "posted_date": (
                    "posting.datePosted",
                    "posting.postedAt",
                    "posting.publishedAt",
                    "job.datePosted",
                    "job.postedAt",
                    "job.publishedAt",
                    "position.datePosted",
                    "datePosted",
                    "postedAt",
                    "publishedAt",
                ),
                "updated_at": (
                    "posting.updatedAt",
                    "job.updatedAt",
                    "position.updatedAt",
                    "updatedAt",
                ),
                "description_html": (
                    "posting.description",
                    "posting.content",
                    "job.description",
                    "job.content",
                    "position.description",
                    "position.content",
                    "data.job.description",
                    "data.posting.description",
                    "description",
                    "content",
                ),
            },
        },
    ),
    "ecommerce_detail": (
        {
            "name": "generic_ecommerce_detail",
            "endpoint_type": "product_api",
            "endpoint_families": ("shopify", "nextjs"),
            "endpoint_path_tokens": (
                "/products/",
                "/product/",
                "product.js",
                "/variants/",
                "/cart.js",
            ),
            "required_path_groups": (
                (
                    "product.title",
                    "product.name",
                    "item.title",
                    "item.name",
                    "data.product.title",
                    "data.product.name",
                    "title",
                    "name",
                ),
                (
                    "product.price.current",
                    "product.price.value",
                    "product.price.amount",
                    "product.price",
                    "product.offers.price",
                    "item.price.current",
                    "item.price.value",
                    "item.price.amount",
                    "item.price",
                    "pricing.current",
                    "pricing.price",
                    "price.current",
                    "price.value",
                    "price.amount",
                    "price",
                    "sku",
                    "product.sku",
                    "item.sku",
                ),
            ),
            "field_paths": {
                "title": (
                    "product.title",
                    "product.name",
                    "item.title",
                    "item.name",
                    "data.product.title",
                    "data.product.name",
                    "title",
                    "name",
                ),
                "brand": (
                    "product.brand.name",
                    "product.brand",
                    "product.vendor.name",
                    "product.vendor",
                    "item.brand.name",
                    "item.brand",
                    "item.vendor.name",
                    "item.vendor",
                    "brand.name",
                    "brand",
                    "vendor.name",
                    "vendor",
                    "manufacturer.name",
                    "manufacturer",
                    "data.product.brand.name",
                    "data.product.brand",
                ),
                "vendor": (
                    "product.vendor.name",
                    "product.vendor",
                    "item.vendor.name",
                    "item.vendor",
                    "vendor.name",
                    "vendor",
                    "seller.name",
                    "seller",
                    "data.product.vendor.name",
                    "data.product.vendor",
                ),
                "sku": (
                    "product.sku",
                    "item.sku",
                    "variant.sku",
                    "sku",
                    "data.product.sku",
                ),
                "price": (
                    "product.price.current",
                    "product.price.value",
                    "product.price.amount",
                    "product.offers.price",
                    "product.price",
                    "item.price.current",
                    "item.price.value",
                    "item.price.amount",
                    "item.price",
                    "pricing.current",
                    "pricing.price",
                    "price.current",
                    "price.value",
                    "price.amount",
                    "price",
                ),
                "currency": (
                    "product.price.currency",
                    "product.price.currencyCode",
                    "product.currency",
                    "product.priceCurrency",
                    "item.price.currency",
                    "item.price.currencyCode",
                    "item.currency",
                    "item.priceCurrency",
                    "pricing.currency",
                    "price.currency",
                    "price.currencyCode",
                    "currency",
                ),
                "availability": (
                    "product.availability",
                    "product.stockStatus",
                    "product.inventory.status",
                    "product.inventoryStatus",
                    "item.availability",
                    "item.stockStatus",
                    "item.inventory.status",
                    "availability",
                    "stockStatus",
                ),
                "image_url": (
                    "product.images[0].url",
                    "product.images[0].src",
                    "product.images[0]",
                    "product.image.url",
                    "product.image.src",
                    "product.image",
                    "item.images[0].url",
                    "item.images[0].src",
                    "item.images[0]",
                    "item.image.url",
                    "item.image.src",
                    "item.image",
                    "images[0].url",
                    "images[0].src",
                    "images[0]",
                    "image.url",
                    "image.src",
                    "image",
                ),
                "additional_images": (
                    "product.images[].url",
                    "product.images[].src",
                    "product.images",
                    "item.images[].url",
                    "item.images[].src",
                    "item.images",
                    "images[].url",
                    "images[].src",
                    "images",
                ),
                "description": (
                    "product.description",
                    "product.body_html",
                    "item.description",
                    "item.body_html",
                    "description",
                    "body_html",
                ),
                "category": (
                    "product.category",
                    "product.product_type",
                    "product.type",
                    "item.category",
                    "item.product_type",
                    "item.type",
                    "category",
                    "product_type",
                    "type",
                ),
                "url": (
                    "product.url",
                    "item.url",
                    "url",
                ),
            },
        },
    ),
}


def endpoint_type_path_tokens() -> dict[str, dict[str, tuple[str, ...]]]:
    tokens_by_surface: dict[str, dict[str, tuple[str, ...]]] = {}
    for surface, specs in NETWORK_PAYLOAD_SPECS.items():
        surface_tokens: dict[str, tuple[str, ...]] = {}
        for spec in specs:
            endpoint_type = str(spec.get("endpoint_type") or "").strip().lower()
            raw_tokens = spec.get("endpoint_path_tokens")
            if not endpoint_type or not isinstance(raw_tokens, tuple) or not raw_tokens:
                continue
            existing_tokens = surface_tokens.get(endpoint_type, ())
            surface_tokens[endpoint_type] = tuple(
                dict.fromkeys([*existing_tokens, *raw_tokens])
            )
        if surface_tokens:
            tokens_by_surface[surface] = surface_tokens
    return tokens_by_surface
