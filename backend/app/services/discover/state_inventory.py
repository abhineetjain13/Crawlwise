from __future__ import annotations

from glom import Coalesce, glom

from app.services.config.field_mappings import COLLECTION_KEYS

_EMPTY_VALUES = (None, "", [], {})
_MAX_SAMPLE_ITEMS = 40

_ECOMMERCE_DETAIL_SPEC = {
    "title": Coalesce(
        "props.pageProps.product.title",
        "props.pageProps.product.name",
        "props.pageProps.initialData.name",
        "props.pageProps.data.getProductDetail.name",
        "query.product.title",
        "product.title",
        "product.name",
        default=None,
    ),
    "brand": Coalesce(
        "props.pageProps.product.vendor",
        "props.pageProps.product.brand.name",
        "props.pageProps.brand",
        "product.vendor",
        "product.brand.name",
        default=None,
    ),
    "price": Coalesce(
        "props.pageProps.product.priceRange.minVariantPrice.amount",
        "props.pageProps.product.price.amount",
        "props.pageProps.product.price",
        "props.pageProps.price",
        "product.price.amount",
        "product.price",
        default=None,
    ),
    "original_price": Coalesce(
        "props.pageProps.product.compareAtPrice.amount",
        "props.pageProps.product.compareAtPrice",
        "product.compareAtPrice.amount",
        "product.compareAtPrice",
        default=None,
    ),
    "currency": Coalesce(
        "props.pageProps.product.priceRange.minVariantPrice.currencyCode",
        "props.pageProps.product.price.currencyCode",
        "props.pageProps.product.currency",
        "product.price.currencyCode",
        "product.currency",
        default=None,
    ),
    "sku": Coalesce(
        "props.pageProps.product.selectedOrFirstAvailableVariant.sku",
        "props.pageProps.product.sku",
        "props.pageProps.data.getProductDetail.materialId",
        "product.selectedOrFirstAvailableVariant.sku",
        "product.sku",
        default=None,
    ),
    "image_url": Coalesce(
        "props.pageProps.product.featuredImage.url",
        "props.pageProps.product.images[0].url",
        "props.pageProps.product.images[0]",
        "product.featuredImage.url",
        "product.images[0].url",
        "product.images[0]",
        default=None,
    ),
    "description": Coalesce(
        "props.pageProps.product.description",
        "props.pageProps.product.descriptionHtml",
        "props.pageProps.data.getProductDetail.description",
        "product.description",
        "product.descriptionHtml",
        default=None,
    ),
    "category": Coalesce(
        "props.pageProps.product.productType",
        "props.pageProps.product.category.name",
        "product.productType",
        "product.category.name",
        default=None,
    ),
    "availability": Coalesce(
        "props.pageProps.product.selectedOrFirstAvailableVariant.availableForSale",
        "props.pageProps.product.availableForSale",
        "product.selectedOrFirstAvailableVariant.availableForSale",
        "product.availableForSale",
        default=None,
    ),
}

_JOB_DETAIL_SPEC = {
    "title": Coalesce(
        "job.title",
        "job.job_title",
        "position.title",
        "props.pageProps.job.title",
        "props.pageProps.job.job_title",
        default=None,
    ),
    "company": Coalesce(
        "company.name",
        "job.company.name",
        "props.pageProps.company.name",
        default=None,
    ),
    "location": Coalesce(
        "job.location.name",
        "job.location",
        "props.pageProps.job.location.name",
        "props.pageProps.job.location",
        default=None,
    ),
    "job_type": Coalesce(
        "job.employmentType",
        "job.job_type",
        "props.pageProps.job.employmentType",
        "props.pageProps.job.job_type",
        default=None,
    ),
    "description": Coalesce(
        "job.description",
        "job.job_description",
        "props.pageProps.job.description",
        "props.pageProps.job.job_description",
        default=None,
    ),
    "apply_url": Coalesce(
        "job.applyUrl",
        "job.apply_url",
        "props.pageProps.job.applyUrl",
        "props.pageProps.job.apply_url",
        default=None,
    ),
}

_FIELD_SPECS = {
    "ecommerce_detail": _ECOMMERCE_DETAIL_SPEC,
    "job_detail": _JOB_DETAIL_SPEC,
}

_LISTING_COLLECTION_PATHS = {
    "ecommerce_listing": (
        "props.pageProps.products",
        "props.pageProps.collection.products",
        "props.pageProps.category.products",
        "props.pageProps.search.results.products",
        "props.pageProps.initialState.search.results.products",
        "props.pageProps.initialState.products",
        "props.pageProps.productGrid.products",
        "query.products",
        "searchStore.works",
        "products",
        "items",
        "results",
    ),
    "job_listing": (
        "props.pageProps.jobs",
        "props.pageProps.search.results.jobs",
        "props.pageProps.initialState.jobs",
        "jobs",
        "results",
        "positions",
        "openings",
    ),
}


def map_state_fields(payload: object, *, surface: str) -> dict[str, object]:
    spec = _FIELD_SPECS.get(str(surface or "").strip().lower())
    if not spec or not isinstance(payload, dict):
        return {}
    try:
        mapped = glom(payload, spec)
    except Exception:
        return {}
    return {
        field_name: value
        for field_name, value in mapped.items()
        if value not in _EMPTY_VALUES
    }


def discover_listing_items(
    payload: object,
    *,
    surface: str,
    max_depth: int,
) -> list[dict]:
    collection = _discover_listing_collection(
        payload,
        surface=str(surface or "").strip().lower(),
        depth=0,
        max_depth=max_depth,
    )
    return [item for item in collection if isinstance(item, dict)]


def _discover_listing_collection(
    payload: object,
    *,
    surface: str,
    depth: int,
    max_depth: int,
) -> list[object]:
    if depth > max_depth or payload in _EMPTY_VALUES:
        return []

    if collection := _collection_from_specs(payload, surface=surface):
        return collection

    if isinstance(payload, list):
        objects = [item for item in payload if isinstance(item, dict)]
        if len(objects) >= 2:
            return objects
        for item in payload[:_MAX_SAMPLE_ITEMS]:
            if not isinstance(item, (dict, list)):
                continue
            if nested := _discover_listing_collection(
                item,
                surface=surface,
                depth=depth + 1,
                max_depth=max_depth,
            ):
                return nested
        return []

    if not isinstance(payload, dict):
        return []

    state_data = _glom_value(payload, "state.data")
    if state_data not in _EMPTY_VALUES:
        if nested := _discover_listing_collection(
            state_data,
            surface=surface,
            depth=depth + 1,
            max_depth=max_depth,
        ):
            return nested

    for key in COLLECTION_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            objects = [item for item in value if isinstance(item, dict)]
            if len(objects) >= 2:
                return objects

    for value in payload.values():
        if not isinstance(value, (dict, list)):
            continue
        if nested := _discover_listing_collection(
            value,
            surface=surface,
            depth=depth + 1,
            max_depth=max_depth,
        ):
            return nested

    return []


def _collection_from_specs(payload: object, *, surface: str) -> list[object]:
    if not isinstance(payload, dict):
        return []
    for path in _LISTING_COLLECTION_PATHS.get(surface, ()):
        value = _glom_value(payload, path)
        if _looks_like_item_collection(value):
            return list(value)
    return []


def _glom_value(payload: object, path: str) -> object | None:
    try:
        return glom(payload, path)
    except Exception:
        return None


def _looks_like_item_collection(value: object) -> bool:
    if not isinstance(value, list):
        return False
    objects = [item for item in value if isinstance(item, dict)]
    return len(objects) >= 2
