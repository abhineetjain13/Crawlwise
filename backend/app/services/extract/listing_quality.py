from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, parse_qsl, urlparse

from app.services.config.extraction_rules import (
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_CATEGORY_PATH_MARKERS,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_FACET_PATH_FRAGMENTS,
    LISTING_FACET_QUERY_KEYS,
    LISTING_HUB_PATH_SEGMENTS,
    LISTING_JOB_SIGNAL_FIELDS,
    LISTING_MINIMAL_VISUAL_FIELDS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_PRODUCT_SIGNAL_FIELDS,
    LISTING_WEAK_METADATA_FIELDS,
    LISTING_WEAK_TITLES,
)
from app.services.extract.noise_policy import is_noise_title, is_social_url

_EMPTY_VALUES = (None, "", [], {})
_NUMERIC_ONLY_RE = re.compile(r"^\s*\(?\s*[\d,]+\s*\)?\s*$")
_FILTER_COUNT_RE = re.compile(r"^\s*\(\s*\d[\d,]*\s*\)\s*$")
_MIN_VIABLE_RECORDS = 2
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
_LISTING_HOST_TOKEN_STOPWORDS = {
    "www",
    "m",
    "amp",
    "api",
    "cdn",
    "img",
    "images",
    "static",
    "backend",
    "edge",
    "shop",
    "store",
    "fashion",
    "brand",
    "retail",
    "market",
    "media",
    "hub",
    "assets",
    "cloud",
    "content",
    "merchant",
    "com",
    "net",
    "org",
    "co",
    "io",
    "app",
}
_TRANSACTIONAL_PATH_TOKENS = frozenset(
    {
        "cart",
        "cartupdate",
        "cartupdate.aspx",
        "checkout",
        "basket",
        "bag",
        "addtocart",
        "add-to-cart",
    }
)
_TRANSACTIONAL_QUERY_ACTION_VALUES = frozenset(
    {
        "add",
        "addtocart",
        "add-to-cart",
        "buy",
        "buy-now",
        "buynow",
        "checkout",
    }
)


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

    if is_merchandising_listing_record(public_fields):
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
        and _looks_like_transactional_url_for_listing(url_value)
    ):
        return _invalid_assessment(
            normalized_surface,
            public_fields,
            product_signal_keys,
            job_signal_keys,
            "transactional_url",
        )

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


def is_merchandising_listing_record(record: dict[str, object]) -> bool:
    title = str(record.get("title") or "").strip()
    if not title:
        has_detail_url = bool(str(record.get("url") or "").strip())
        has_visual = record.get("image_url") not in _EMPTY_VALUES
        has_pricing = record.get("price") not in _EMPTY_VALUES
        has_company = record.get("company") not in _EMPTY_VALUES
        return not (has_detail_url and (has_visual or has_pricing or has_company))

    return is_noise_title(
        title,
        navigation_hints=LISTING_NAVIGATION_TITLE_HINTS,
        merchandising_prefixes=LISTING_MERCHANDISING_TITLE_PREFIXES,
        editorial_patterns=LISTING_EDITORIAL_TITLE_PATTERNS,
        alt_text_pattern=LISTING_ALT_TEXT_TITLE_PATTERN,
        weak_titles=LISTING_WEAK_TITLES,
    )


def has_strong_ecommerce_listing_signal(record: dict[str, object]) -> bool:
    public_fields = {
        key: value
        for key, value in record.items()
        if not str(key).startswith("_") and value not in _EMPTY_VALUES
    }
    if not public_fields:
        return False

    url_value = str(public_fields.get("url") or "").strip()
    if url_value and _looks_like_detail_record_url_for_listing(url_value):
        return True

    strong_fields = {
        "price",
        "sale_price",
        "original_price",
        "image_url",
        "additional_images",
        "brand",
        "availability",
        "rating",
        "review_count",
        "color",
        "size",
        "dimensions",
        "materials",
        "part_number",
    }
    if set(public_fields) & strong_fields:
        return True

    if {"sku", "part_number"} & set(public_fields) and {
        "brand",
        "image_url",
        "price",
    } & set(public_fields):
        return True

    return False


def filter_relevant_network_record_set(
    records: list[dict],
    *,
    payload_url: str,
    page_url: str,
    surface: str,
) -> list[dict]:
    if not records or "job" in str(surface or "").lower():
        return records
    if is_social_url(payload_url):
        return []
    if _hosts_look_related(payload_url, page_url):
        return [r for r in records if is_meaningful_listing_record(r, surface=surface)]

    relevant_records = [
        record
        for record in records
        if _record_url_matches_listing_page(record, page_url=page_url)
    ]
    if len(relevant_records) >= _MIN_VIABLE_RECORDS:
        return relevant_records
    return []


def looks_like_facet_or_filter_url_for_listing(url_value: str) -> bool:
    return _looks_like_facet_or_filter_url_for_listing(url_value)


def looks_like_category_url_for_listing(url_value: str) -> bool:
    return _looks_like_category_url_for_listing(url_value)


def looks_like_listing_hub_url_for_listing(url_value: str) -> bool:
    return _looks_like_listing_hub_url_for_listing(url_value)


def looks_like_detail_record_url_for_listing(url_value: str) -> bool:
    return _looks_like_detail_record_url_for_listing(url_value)


def looks_like_transactional_url_for_listing(url_value: str) -> bool:
    return _looks_like_transactional_url_for_listing(url_value)


def looks_like_navigation_or_action_title(title: str, url: str = "") -> bool:
    lowered = (title or "").strip().lower()
    if not lowered:
        return True
    if lowered in LISTING_NAVIGATION_TITLE_HINTS:
        return True
    if re.fullmatch(r"(?:next|previous|prev|back)(?:\s+\W+)?", lowered):
        return True
    if re.fullmatch(r"[a-z0-9.-]+\.(?:com|net|org|io|co|ai|in|uk)", lowered):
        return True
    lowered_url = url.lower().strip()
    if lowered in {"login", "log in", "sign in"} and "/login" in lowered_url:
        return True
    return False


def looks_like_alt_text_title(title: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(title or "")).strip()
    if not normalized:
        return False
    word_count = len(re.findall(r"[A-Za-z]{2,}", normalized))
    if (
        word_count >= 12
        and LISTING_ALT_TEXT_TITLE_PATTERN
        and LISTING_ALT_TEXT_TITLE_PATTERN.search(normalized)
    ):
        return True
    if len(normalized) >= 95 and ("," in normalized or ";" in normalized):
        return True
    return False


def looks_like_editorial_or_taxonomy_title(
    title: str,
    url: str = "",
    price: str = "",
) -> bool:
    lowered = title.lower().strip()
    if not lowered:
        return False
    if any(pattern.search(lowered) for pattern in LISTING_EDITORIAL_TITLE_PATTERNS):
        return True
    if lowered.startswith(LISTING_MERCHANDISING_TITLE_PREFIXES) and not price:
        return True
    if re.search(r"\(\d+\)\s*$", title):
        return True
    return False


def is_listing_like_record(record: dict) -> bool:
    title = str(record.get("title") or "").strip()
    url = str(record.get("url") or "").strip()
    price = str(record.get("price") or "").strip()
    image = str(record.get("image_url") or record.get("image") or "").strip()
    salary = str(record.get("salary") or "").strip()
    company = str(record.get("company") or "").strip()

    if title and looks_like_navigation_or_action_title(title, url):
        return False
    if title and looks_like_alt_text_title(title):
        return False
    if title and looks_like_editorial_or_taxonomy_title(title, url, price):
        return False

    evidence = 0
    if title:
        evidence += 1
    if price or salary:
        evidence += 2
    if image:
        evidence += 1
    if company:
        evidence += 1
    if _looks_like_detail_record_url_for_listing(url):
        evidence += 2
    elif url and not _looks_like_listing_hub_url_for_listing(url):
        evidence += 1

    return evidence >= 2


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
    if any(segment.startswith("all-") for segment in segments):
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


def _looks_like_facet_or_filter_url_for_listing(url_value: str) -> bool:
    parsed = urlparse(url_value)
    query_keys = {
        key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if query_keys & LISTING_FACET_QUERY_KEYS:
        return True

    path = parsed.path.lower()
    return any(fragment in path for fragment in LISTING_FACET_PATH_FRAGMENTS) and bool(
        parsed.query
    )


def _looks_like_category_url_for_listing(url_value: str) -> bool:
    parsed = urlparse(str(url_value or "").strip())
    path = parsed.path.lower().rstrip("/")
    if not path:
        return False
    for prefix in LISTING_DETAIL_PATH_MARKERS:
        if prefix in path:
            return False
    segments = [s for s in path.split("/") if s]
    if len(segments) < 2:
        return False
    last = segments[-1]
    for i, seg in enumerate(segments[:-1]):
        if seg in LISTING_CATEGORY_PATH_MARKERS and i + 1 < len(segments):
            if re.fullmatch(r"[a-z][a-z0-9\-]+", last) and len(last) < 60:
                return True
    return False


def _looks_like_listing_hub_url_for_listing(url_value: str) -> bool:
    parsed = urlparse(str(url_value or "").strip())
    path = parsed.path.lower().rstrip("/")
    if not path:
        return bool(parsed.query)
    if _looks_like_facet_or_filter_url_for_listing(
        url_value
    ) or _looks_like_category_url_for_listing(url_value):
        return True
    if _looks_like_detail_record_url_for_listing(url_value):
        return False
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return True
    normalized_segments = [segment.lower().replace("-", "") for segment in segments]
    if any(segment in LISTING_HUB_PATH_SEGMENTS for segment in normalized_segments):
        return True
    if len(segments) <= 2 and parsed.query:
        return True
    return False


def _looks_like_detail_record_url_for_listing(url_value: str) -> bool:
    lowered = str(url_value or "").lower()
    if not lowered.startswith("http"):
        return False
    if _looks_like_transactional_url_for_listing(lowered):
        return False
    if _looks_like_facet_or_filter_url_for_listing(lowered):
        return False
    if _looks_like_category_url_for_listing(lowered):
        return False
    return any(marker in lowered for marker in LISTING_DETAIL_PATH_MARKERS)


def _looks_like_transactional_url_for_listing(url_value: str) -> bool:
    parsed = urlparse(str(url_value or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return False
    path = parsed.path.lower()
    segments = [
        segment.lower()
        for segment in re.split(r"[^a-z0-9.]+", path)
        if segment.strip(".")
    ]
    if any(
        segment in _TRANSACTIONAL_PATH_TOKENS or "cartupdate" in segment
        for segment in segments
    ):
        return True
    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    query_map = {
        str(key or "").strip().lower(): str(value or "").strip().lower()
        for key, value in query_items
    }
    if any(key in {"addtocart", "add-to-cart"} for key in query_map):
        return True
    action_value = query_map.get("action", "")
    if action_value in _TRANSACTIONAL_QUERY_ACTION_VALUES and any(
        token in path for token in ("/checkout", "/cart", "/basket", "/bag")
    ):
        return True
    return False


def _record_url_matches_listing_page(record: dict, *, page_url: str) -> bool:
    record_url = str(record.get("url") or record.get("apply_url") or "").strip()
    if not record_url:
        return False
    if _looks_like_transactional_url_for_listing(record_url):
        return False
    if is_social_url(record_url):
        return False
    if not _hosts_look_related(record_url, page_url):
        return False
    has_primary_listing_data = any(
        record.get(field_name) not in _EMPTY_VALUES
        for field_name in ("title", "price", "brand")
    )
    return _looks_like_detail_record_url_for_listing(record_url) or has_primary_listing_data


def _hosts_look_related(left: str, right: str) -> bool:
    def _host_like_value(value: str) -> str:
        raw = str(value or "").strip().lower()
        parsed_host = urlparse(raw).netloc.lower()
        if parsed_host:
            return parsed_host
        if re.fullmatch(r"[a-z0-9.-]+", raw) and "." in raw and ".." not in raw:
            return raw
        return ""

    left_host = _host_like_value(left)
    right_host = _host_like_value(right)
    if not left_host or not right_host:
        return False
    if left_host == right_host:
        return True
    if left_host.endswith(f".{right_host}") or right_host.endswith(f".{left_host}"):
        return True
    left_tokens = _listing_host_tokens(left_host)
    right_tokens = _listing_host_tokens(right_host)
    return len(left_tokens & right_tokens) >= 1


def _listing_host_tokens(host: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(host or "").lower())
        if len(token) >= 2 and token not in _LISTING_HOST_TOKEN_STOPWORDS
    }
