from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from app.services.config.listing_heuristics import (
    LISTING_JOB_SIGNAL_FIELDS,
    LISTING_MINIMAL_VISUAL_FIELDS,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_PRODUCT_SIGNAL_FIELDS,
    LISTING_WEAK_METADATA_FIELDS,
    LISTING_WEAK_TITLES,
)

_EMPTY_VALUES = (None, "", [], {})
_NUMERIC_ONLY_RE = re.compile(r"^\s*\(?\s*[\d,]+\s*\)?\s*$")
_FILTER_COUNT_RE = re.compile(r"^\s*\(\s*\d[\d,]*\s*\)\s*$")
_JOB_REQUIRED_CONTEXT_FIELDS = frozenset({
    "url",
    "job_id",
    "company",
    "location",
    "department",
    "category",
    "posted_date",
    "apply_url",
    "job_type",
    "salary",
    "description",
})
_JOB_STRONG_SIGNALS = frozenset({
    "company",
    "location",
    "salary",
    "job_id",
    "apply_url",
    "job_type",
    "posted_date",
})


@dataclass(frozen=True)
class ListingQualityAssessment:
    surface: str
    public_fields: dict[str, object]
    quality: str
    extractable: bool
    meaningful: bool
    product_signal_keys: frozenset[str]
    job_signal_keys: frozenset[str]
    reasons: tuple[str, ...]


def assess_listing_record_quality(record: dict, *, surface: str = "") -> ListingQualityAssessment:
    public_fields = {
        key: value
        for key, value in dict(record or {}).items()
        if not str(key).startswith("_") and value not in _EMPTY_VALUES
    }
    normalized_surface = str(surface or record.get("_surface") or "").strip().lower()
    if not public_fields:
        return ListingQualityAssessment(
            surface=normalized_surface,
            public_fields={},
            quality="invalid",
            extractable=False,
            meaningful=False,
            product_signal_keys=frozenset(),
            job_signal_keys=frozenset(),
            reasons=("empty_public_fields",),
        )

    reasons: list[str] = []
    meaningful_keys = {key for key in public_fields if key != "url"}
    product_signal_keys = frozenset(meaningful_keys & LISTING_PRODUCT_SIGNAL_FIELDS)
    job_signal_keys = frozenset(meaningful_keys & LISTING_JOB_SIGNAL_FIELDS)
    url_value = str(public_fields.get("url") or "").strip()
    title_value = str(public_fields.get("title") or "").strip()
    is_job_surface = "job" in normalized_surface
    is_job_like_record = bool(
        {"job_id", "company", "location", "department", "category", "posted_date", "apply_url", "job_type", "salary"}
        & meaningful_keys
    )

    if _is_merchandising_record(public_fields):
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "merchandising_noise")

    if title_value:
        lowered_title = title_value.lower()
        raw_title = public_fields.get("title")
        if isinstance(raw_title, (int, float)) and not isinstance(raw_title, bool):
            return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "numeric_title_value")
        if _FILTER_COUNT_RE.match(title_value):
            return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "filter_count_title")
        if _NUMERIC_ONLY_RE.match(title_value) and not ("price" in meaningful_keys or "image_url" in meaningful_keys):
            return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "numeric_only_title")
        if lowered_title in LISTING_WEAK_TITLES:
            reasons.append("weak_title")

    raw_price = public_fields.get("price")
    if raw_price in (0, "0", "$0", "0.00", "$0.00") and not url_value and not title_value and len(public_fields) <= 2:
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "zero_price_shell")

    if meaningful_keys == LISTING_MINIMAL_VISUAL_FIELDS and not url_value:
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "visual_only_shell")

    if url_value and _looks_like_category_url(url_value) and not product_signal_keys and not is_job_like_record:
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "category_link")
    if url_value and _looks_like_facet_or_filter_url(url_value) and not product_signal_keys and not is_job_like_record:
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "facet_link")

    if (
        url_value
        and not product_signal_keys
        and meaningful_keys.issubset(LISTING_MINIMAL_VISUAL_FIELDS)
        and not is_job_like_record
    ):
        parsed = urlparse(url_value)
        path = parsed.path.rstrip("/")
        segments = [segment for segment in path.split("/") if segment]
        path_token_set = {segment.lower().replace("-", "") for segment in segments}
        if len(segments) <= 1 and not parsed.query:
            return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "hub_link")
        if path_token_set & LISTING_NON_LISTING_PATH_TOKENS:
            return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "non_listing_path_token")
        if not _looks_like_detail_record_url(url_value) and _looks_like_listing_hub_url(url_value):
            return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "listing_hub_link")

    if (
        url_value
        and not product_signal_keys
        and meaningful_keys.issubset(LISTING_WEAK_METADATA_FIELDS)
        and _looks_like_listing_hub_url(url_value)
        and not _looks_like_detail_record_url(url_value)
        and not is_job_like_record
    ):
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "weak_metadata_hub_link")

    if job_signal_keys and not public_fields.get("title") and not public_fields.get("salary"):
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "job_metadata_without_anchor")

    if (
        "job" in normalized_surface
        and title_value
        and not url_value
        and not is_job_like_record
        and not product_signal_keys
        and meaningful_keys == {"title"}
    ):
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "title_only_without_url")

    if is_job_surface and title_value and not (set(public_fields) & _JOB_REQUIRED_CONTEXT_FIELDS):
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "job_title_without_context")

    if (
        ("commerce" in normalized_surface or "ecommerce" in normalized_surface)
        and url_value
        and not product_signal_keys
        and _looks_like_job_url(url_value)
    ):
        return _invalid_assessment(
            normalized_surface,
            public_fields,
            product_signal_keys,
            job_signal_keys,
            "job_like_url_on_ecommerce_surface",
        )

    if not title_value and not url_value and not job_signal_keys and not product_signal_keys:
        return _invalid_assessment(normalized_surface, public_fields, product_signal_keys, job_signal_keys, "missing_anchor_fields")

    extractable = bool(
        (
            title_value
            and (
                url_value
                or job_signal_keys
                or product_signal_keys
                or ("job" not in normalized_surface)
            )
        )
        or (
            "job" not in normalized_surface
            and url_value
            and ("image_url" in public_fields or bool(product_signal_keys))
        )
    )
    meaningful = _is_meaningful_for_surface(public_fields, normalized_surface, product_signal_keys, job_signal_keys)
    if meaningful:
        quality = "meaningful"
    elif extractable:
        quality = "extractable"
    else:
        quality = "link_only"
    if quality == "link_only" and not reasons:
        reasons.append("weak_listing_record")
    return ListingQualityAssessment(
        surface=normalized_surface,
        public_fields=public_fields,
        quality=quality,
        extractable=extractable,
        meaningful=meaningful,
        product_signal_keys=product_signal_keys,
        job_signal_keys=job_signal_keys,
        reasons=tuple(reasons),
    )


def is_meaningful_listing_record(record: dict, *, surface: str = "") -> bool:
    assessment = assess_listing_record_quality(record, surface=surface)
    normalized_surface = str(surface or record.get("_surface") or "").strip()
    if not normalized_surface:
        field_names = set(assessment.public_fields)
        if field_names == {"title"}:
            return False
        url_value = str(assessment.public_fields.get("url") or "").strip()
        if not _looks_like_detail_record_url(url_value) and field_names.issubset(LISTING_WEAK_METADATA_FIELDS | {"title", "url"}):
            return False
        if not _looks_like_detail_record_url(url_value) and "title" in field_names and "url" in field_names and len(field_names) <= 3:
            return False
    return assessment.quality in {"extractable", "meaningful"}


def is_meaningful_structured_listing_record(record: dict, *, surface: str = "") -> bool:
    assessment = assess_listing_record_quality(record, surface=surface)
    if assessment.quality == "invalid":
        return False
    field_names = set(assessment.public_fields)
    if field_names == {"title"} or field_names == {"url"}:
        return False
    if field_names == {"title", "url"}:
        url_value = str(assessment.public_fields.get("url") or "").strip()
        return _looks_like_detail_record_url(url_value) and not _looks_like_listing_hub_url(url_value)
    return assessment.quality in {"extractable", "meaningful"}


def has_meaningful_listing_set(records: list[dict], *, surface: str = "") -> bool:
    return any(assess_listing_record_quality(record, surface=surface).meaningful for record in records or [])


def listing_set_quality(records: list[dict], *, surface: str = "") -> str:
    assessments = [assess_listing_record_quality(record, surface=surface) for record in records or []]
    if any(assessment.meaningful for assessment in assessments):
        return "meaningful"
    if any(assessment.extractable for assessment in assessments):
        return "extractable"
    if assessments:
        return "link_only"
    return "invalid"


def _invalid_assessment(
    surface: str,
    public_fields: dict[str, object],
    product_signal_keys: frozenset[str],
    job_signal_keys: frozenset[str],
    reason: str,
) -> ListingQualityAssessment:
    return ListingQualityAssessment(
        surface=surface,
        public_fields=public_fields,
        quality="invalid",
        extractable=False,
        meaningful=False,
        product_signal_keys=product_signal_keys,
        job_signal_keys=job_signal_keys,
        reasons=(reason,),
    )


def _is_meaningful_for_surface(
    public_fields: dict[str, object],
    surface: str,
    product_signal_keys: frozenset[str],
    job_signal_keys: frozenset[str],
) -> bool:
    title = public_fields.get("title")
    url = public_fields.get("url")
    if "job" in surface:
        return bool(title and (_JOB_STRONG_SIGNALS & set(public_fields)))
    if "commerce" in surface or "ecommerce" in surface:
        return bool(title and (url or product_signal_keys))
    return bool(title and (url or product_signal_keys or job_signal_keys))


def _is_merchandising_record(record: dict[str, object]) -> bool:
    title = str(record.get("title") or "").strip().lower()
    url = str(record.get("url") or "").strip().lower()
    if not title and not url:
        return False
    if any(token in title for token in ("sort by", "filter by", "shop all", "view all", "load more")):
        return True
    if url and any(token in url for token in ("/search", "/category", "/categories", "/collections", "/filters")):
        if not (set(record) & (_JOB_STRONG_SIGNALS | set(LISTING_PRODUCT_SIGNAL_FIELDS))):
            return True
    return False


def _looks_like_category_url(url: str) -> bool:
    lowered = str(url or "").strip().lower()
    return any(token in lowered for token in ("/category", "/categories", "/collections", "/departments"))


def _looks_like_facet_or_filter_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    query = parse_qs(parsed.query)
    if any(key.lower() in {"filter", "filters", "facet", "facets", "brand", "color", "size", "department"} for key in query):
        return True
    lowered = parsed.path.lower()
    return any(token in lowered for token in ("/filter/", "/filters/", "/facet/", "/facets/"))


def _looks_like_listing_hub_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path.rstrip("/").lower()
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) <= 1:
        return True
    return len(segments) <= 2 and any(segment in {"jobs", "careers", "products", "shop", "collections"} for segment in segments)


def _looks_like_job_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    lowered = parsed.path.lower()
    return any(
        token in lowered for token in ("/jobs", "/job/", "/careers", "/career/")
    )


def _looks_like_detail_record_url(url: str) -> bool:
    parsed = urlparse(str(url or "").strip())
    path = parsed.path.rstrip("/")
    if not path:
        return False
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) == 1 and segments[0].lower() in {"jobs", "careers", "products", "deals", "shop", "collections", "category", "categories"}:
        return False
    if len(segments) >= 2:
        return True
    if re.search(r"(job|jobs|product|products|position|opening|role)[-/]", path, re.I):
        return True
    return bool(re.search(r"/[a-z0-9][a-z0-9-]{2,}$", path, re.I))
