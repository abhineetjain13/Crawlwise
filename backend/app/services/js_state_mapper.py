from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup
from glom import Coalesce, glom


NEXT_DATA_ECOMMERCE_SPEC = {
    "title": Coalesce(
        "props.pageProps.product.title",
        "props.pageProps.product.name",
        "props.pageProps.productData.title",
        "query.product.title",
        default=None,
    ),
    "brand": Coalesce(
        "props.pageProps.product.vendor",
        "props.pageProps.product.brand",
        default=None,
    ),
    "vendor": Coalesce("props.pageProps.product.vendor", default=None),
    "handle": Coalesce("props.pageProps.product.handle", default=None),
    "description": Coalesce(
        "props.pageProps.product.description",
        "props.pageProps.product.body_html",
        default=None,
    ),
}

REMIX_GREENHOUSE_SPEC = {
    "title": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.title",
        default=None,
    ),
    "company": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.company_name",
        default=None,
    ),
    "location": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.job_post_location",
        default=None,
    ),
    "apply_url": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.public_url",
        default=None,
    ),
    "posted_date": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.published_at",
        default=None,
    ),
    "description_html": Coalesce(
        "state.loaderData.routes/$url_token_.jobs_.$job_post_id.jobPost.content",
        default=None,
    ),
}


def map_js_state_to_fields(
    js_state_objects: dict[str, Any],
    *,
    surface: str,
    page_url: str,
) -> dict[str, Any]:
    del page_url
    normalized_surface = str(surface or "").strip().lower()
    if not js_state_objects:
        return {}
    if normalized_surface == "job_detail":
        return _map_job_detail_state(js_state_objects)
    if normalized_surface == "ecommerce_detail":
        return _map_ecommerce_detail_state(js_state_objects)
    return {}


def _map_job_detail_state(js_state_objects: dict[str, Any]) -> dict[str, Any]:
    remix_state = js_state_objects.get("__remixContext")
    if not isinstance(remix_state, dict):
        return {}
    loader_data = (
        remix_state.get("state", {}).get("loaderData", {})
        if isinstance(remix_state.get("state"), dict)
        else {}
    )
    route_data = (
        loader_data.get("routes/$url_token_.jobs_.$job_post_id", {})
        if isinstance(loader_data, dict)
        else {}
    )
    job_post = route_data.get("jobPost", {}) if isinstance(route_data, dict) else {}
    mapped = _compact_dict(
        {
            "title": job_post.get("title"),
            "company": job_post.get("company_name"),
            "location": job_post.get("job_post_location"),
            "apply_url": job_post.get("public_url"),
            "posted_date": job_post.get("published_at"),
            "description_html": job_post.get("content"),
        }
    )
    description_html = str(mapped.pop("description_html", "") or "").strip()
    if description_html:
        mapped.update(_extract_job_sections(description_html))
        if "description" not in mapped:
            mapped["description"] = _html_to_text(description_html)
    if mapped.get("apply_url") and not mapped.get("url"):
        mapped["url"] = mapped["apply_url"]
    return mapped


def _map_ecommerce_detail_state(js_state_objects: dict[str, Any]) -> dict[str, Any]:
    next_data = js_state_objects.get("__NEXT_DATA__")
    if isinstance(next_data, dict):
        mapped = _compact_dict(glom(next_data, NEXT_DATA_ECOMMERCE_SPEC, default={}))
        product = _find_product_payload(next_data)
        if isinstance(product, dict):
            mapped.update(
                _compact_dict(
                    {
                        "product_id": product.get("id"),
                        "handle": mapped.get("handle") or product.get("handle"),
                        "category": product.get("product_type") or product.get("type"),
                    }
                )
            )
        if mapped:
            return mapped

    for key in ("__NUXT__", "__NUXT_DATA__", "__INITIAL_STATE__", "__PRELOADED_STATE__"):
        payload = js_state_objects.get(key)
        product = _find_product_payload(payload)
        if not isinstance(product, dict):
            continue
        return _compact_dict(
            {
                "title": product.get("title") or product.get("name"),
                "brand": _name_or_value(product.get("brand") or product.get("vendor")),
                "vendor": _name_or_value(product.get("vendor")),
                "handle": product.get("handle"),
                "description": product.get("description") or product.get("body_html"),
                "product_id": product.get("id"),
                "category": product.get("product_type") or product.get("type"),
            }
        )
    return {}


def _find_product_payload(value: Any, *, depth: int = 0, limit: int = 8) -> dict[str, Any] | None:
    if depth > limit:
        return None
    if isinstance(value, dict):
        if any(key in value for key in ("variants", "product_type", "vendor", "handle")) and any(
            key in value for key in ("title", "name")
        ):
            return value
        for item in value.values():
            found = _find_product_payload(item, depth=depth + 1, limit=limit)
            if found is not None:
                return found
    elif isinstance(value, list):
        for item in value[:25]:
            found = _find_product_payload(item, depth=depth + 1, limit=limit)
            if found is not None:
                return found
    return None


def _extract_job_sections(html: str) -> dict[str, str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    sections: dict[str, str] = {}
    for heading in soup.find_all(["h2", "h3", "strong"]):
        heading_text = " ".join(heading.get_text(" ", strip=True).split()).strip()
        if not heading_text:
            continue
        collected: list[str] = []
        for sibling in heading.next_siblings:
            sibling_name = getattr(sibling, "name", "")
            if sibling_name in {"h1", "h2", "h3"}:
                break
            text = (
                sibling.get_text(" ", strip=True)
                if hasattr(sibling, "get_text")
                else str(sibling)
            )
            cleaned = " ".join(str(text or "").split()).strip()
            if cleaned:
                collected.append(cleaned)
        if collected:
            sections[heading_text.lower()] = " ".join(collected)

    mapped: dict[str, str] = {}
    for label, value in sections.items():
        if "what you" in label or "responsibil" in label:
            mapped["responsibilities"] = value
        elif "should have" in label or "qualif" in label or "who you are" in label:
            mapped["qualifications"] = value
        elif "benefit" in label or "perks" in label or "what we offer" in label:
            mapped["benefits"] = value
        elif "skill" in label or "bring" in label:
            mapped["skills"] = value
    return mapped


def _html_to_text(value: str) -> str:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split()).strip()


def _name_or_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("name") or value.get("title") or value.get("value")
    return value


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in dict(value or {}).items()
        if item not in (None, "", [], {})
    }
