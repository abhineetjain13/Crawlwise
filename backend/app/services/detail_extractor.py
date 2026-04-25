from __future__ import annotations

import logging
import re
from itertools import product
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.confidence import score_record_confidence
from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
    ECOMMERCE_DETAIL_JS_STATE_FIELDS,
    VARIANT_DOM_FIELD_NAMES,
)
from app.services.config.extraction_rules import (
    CANDIDATE_PLACEHOLDER_VALUES,
    DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES,
    DETAIL_BRAND_SHELL_TITLE_TOKENS,
    DETAIL_COLLECTION_PATH_TOKENS,
    DETAIL_CURRENT_PRICE_SELECTORS,
    DETAIL_NON_PAGE_FILE_EXTENSIONS,
    DETAIL_ORIGINAL_PRICE_SELECTORS,
    DETAIL_PRODUCT_PATH_TOKENS,
    DETAIL_SEARCH_QUERY_KEYS,
    DETAIL_UTILITY_PATH_TOKENS,
    DETAIL_TITLE_SOURCE_RANKS,
    LISTING_ALT_TEXT_TITLE_PATTERN,
    LISTING_ACTION_NOISE_PATTERNS,
    LISTING_EDITORIAL_TITLE_PATTERNS,
    LISTING_MERCHANDISING_TITLE_PREFIXES,
    SOURCE_PRIORITY,
    LISTING_NAVIGATION_TITLE_HINTS,
    LISTING_TITLE_CTA_TITLES,
    LISTING_WEAK_TITLES,
    TITLE_PROMOTION_PREFIXES,
    TITLE_PROMOTION_SEPARATOR,
    TITLE_PROMOTION_SUBSTRINGS,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_SIZE_VALUE_PATTERNS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extraction_context import (
    collect_structured_source_payloads,
    prepare_extraction_context,
)
from app.services.structured_sources import harvest_js_state_objects
from app.services.field_value_core import (
    LONG_TEXT_FIELDS,
    PRODUCT_URL_HINTS,
    RATING_RE,
    REVIEW_COUNT_RE,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    clean_text,
    coerce_field_value,
    extract_currency_code,
    finalize_record,
    is_title_noise,
    same_site,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)
from app.services.field_value_candidates import (
    add_candidate,
    collect_structured_candidates,
    finalize_candidate_value,
    record_score,
)
from app.services.field_value_dom import (
    apply_selector_fallbacks,
    dedupe_image_urls,
    extract_heading_sections,
    extract_page_images,
    requested_content_extractability,
)
from app.services.js_state_mapper import map_js_state_to_fields
from app.services.js_state_helpers import select_variant
from app.services.network_payload_mapper import map_network_payloads_to_fields
from app.services.normalizers import normalize_decimal_price
from app.services.extract.shared_variant_logic import (
    infer_variant_group_name_from_values,
    iter_variant_choice_groups,
    iter_variant_select_groups,
    normalized_variant_axis_display_name,
    normalized_variant_axis_key,
    resolve_variants,
    resolve_variant_group_name,
    split_variant_axes,
    variant_axis_name_is_semantic,
    variant_dom_cues_present,
)
from app.services.field_policy import exact_requested_field_key
from app.services.extract.detail_tiers import (
    DetailTierState,
    collect_authoritative_tier,
    collect_dom_tier,
    collect_js_state_tier,
    collect_structured_data_tier,
    materialize_detail_tier,
)

logger = logging.getLogger(__name__)
_DETAIL_VARIANT_SIZE_VALUE_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in VARIANT_SIZE_VALUE_PATTERNS
    if str(pattern).strip()
)
_VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS = tuple(
    re.compile(str(pattern), re.I)
    for pattern in VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS
    if str(pattern).strip()
)
_LOW_SIGNAL_ZERO_PRICE_SOURCES = frozenset(
    {
        "dom_selector",
        "dom_sections",
        "dom_text",
        "selector_rule",
    }
)
_LOW_SIGNAL_LONG_TEXT_VALUES = frozenset(
    {
        "description",
        "details",
        "normal",
        "overview",
        "product summary",
        "specifications",
    }
)
_DETAIL_IDENTITY_STOPWORDS = frozenset(
    {
        "and",
        "buy",
        "fit",
        "for",
        "men",
        "online",
        "oversized",
        "product",
        "products",
        "shirt",
        "shirts",
        "souled",
        "store",
        "tee",
        "tees",
        "the",
        "tshirt",
        "tshirts",
        "women",
    }
)
_LONG_TEXT_SOURCE_RANKS = {
    "adapter": 0,
    "network_payload": 1,
    "dom_sections": 2,
    "selector_rule": 3,
    "dom_selector": 4,
    "json_ld": 5,
    "microdata": 6,
    "embedded_json": 7,
    "js_state": 8,
    "opengraph": 9,
    "dom_h1": 10,
    "dom_canonical": 11,
    "dom_images": 12,
    "dom_text": 13,
}
_DETAIL_PLACEHOLDER_TITLE_PATTERNS = (
    re.compile(r"^404$"),
    re.compile(r"^oops!? the page you(?:'|’)re looking for can(?:'|’)t be found\.?$", re.I),
    re.compile(r"\bpage not found\b", re.I),
    re.compile(r"\bnot found\b", re.I),
    re.compile(r"\baccess denied\b", re.I),
)
_DETAIL_URL_PLACEHOLDER_SEGMENTS = frozenset(
    {
        str(value).strip().lower()
        for value in tuple(CANDIDATE_PLACEHOLDER_VALUES or ())
        if str(value).strip()
    }
)


def _object_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _object_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _detail_url_path_segments(url: str) -> list[str]:
    parsed = urlparse(str(url or ""))
    segments = [
        segment
        for segment in str(parsed.path or "").strip("/").split("/")
        if segment
    ]
    fragment = str(parsed.fragment or "").strip()
    if fragment:
        fragment_path = fragment.split("?", 1)[0].split("&", 1)[0].strip()
        if "/" in fragment_path:
            segments.extend(
                segment
                for segment in fragment_path.strip("!/").split("/")
                if segment
            )
    return segments
def _field_source_rank(surface: str, field_name: str, source: str | None) -> int:
    if str(surface or "").strip().lower() == "ecommerce_detail":
        if field_name == "title":
            return DETAIL_TITLE_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in LONG_TEXT_FIELDS:
            return _LONG_TEXT_SOURCE_RANKS.get(str(source or ""), 20)
        if field_name in ECOMMERCE_DETAIL_JS_STATE_FIELDS and source == "js_state":
            return 2
    return 100 + _SOURCE_PRIORITY_RANK.get(str(source or ""), len(_SOURCE_PRIORITY_RANK))
def _detail_title_from_url(page_url: str) -> str | None:
    path_segments = _detail_url_path_segments(page_url)
    if not path_segments:
        return None
    for segment in reversed(path_segments):
        terminal = re.sub(r"\.(html?|htm)$", "", segment, flags=re.I)
        if not terminal or terminal.isdigit():
            continue
        if re.fullmatch(r"[a-f0-9]{8,}(?:-[a-f0-9]{4,}){2,}", terminal, re.I):
            continue
        if terminal in {"p", "dp", "product", "products", "job", "jobs", "release"}:
            continue
        title = clean_text(re.sub(r"[-_]+", " ", terminal))
        if title and not is_title_noise(title):
            return title
    return None
def _apply_dom_fallbacks(
    dom_parser: LexborHTMLParser,
    soup: BeautifulSoup,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    selector_rules: list[dict[str, object]] | None = None,
) -> None:
    fields = surface_fields(surface, requested_fields)
    h1 = dom_parser.css_first("h1")
    page_title = dom_parser.css_first("title")
    h1_title = text_or_none(h1.text(separator=" ", strip=True) if h1 else "")
    page_title_text = text_or_none(page_title.text(separator=" ", strip=True) if page_title else "")
    title = next(
        (
            candidate
            for candidate in (h1_title, page_title_text)
            if candidate and not is_title_noise(candidate)
        ),
        None,
    )
    if title:
        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "title",
            title,
            source="dom_h1",
        )
    apply_selector_fallbacks(
        soup,
        page_url,
        surface,
        requested_fields,
        candidates,
        selector_rules=selector_rules,
        candidate_sources=candidate_sources,
        field_sources=field_sources,
        selector_trace_candidates=selector_trace_candidates,
    )
    canonical = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
    if canonical is not None:
        from app.services.field_value_core import absolute_url

        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "url",
            absolute_url(page_url, canonical.get("href")),
            source="dom_canonical",
        )
    images = extract_page_images(
        soup,
        page_url,
        exclude_linked_detail_images=False,
        surface=surface,
    )
    if images:
        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "image_url",
            images[0],
            source="dom_images",
        )
        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "additional_images",
            images[1:],
            source="dom_images",
        )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    for label, value in extract_heading_sections(soup).items():
        normalized = alias_lookup.get(label.lower()) or alias_lookup.get(
            re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        )
        if normalized:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                normalized,
                coerce_field_value(normalized, value, page_url),
                source="dom_sections",
            )
    body_node = dom_parser.body
    body_text = (
        clean_text(body_node.text(separator=" ", strip=True)) if body_node else ""
    )
    if "currency" in fields and not candidates.get("currency"):
        for price_value in list(candidates.get("price") or []):
            currency_code = extract_currency_code(price_value)
            if not currency_code:
                continue
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "currency",
                currency_code,
                source="dom_text",
            )
            break
    if "review_count" in fields and not candidates.get("review_count"):
        review_match = REVIEW_COUNT_RE.search(body_text)
        if review_match:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "review_count",
                review_match.group(1),
                source="dom_text",
            )
    if "rating" in fields and not candidates.get("rating"):
        rating_match = RATING_RE.search(body_text)
        if rating_match:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "rating",
                rating_match.group(1),
                source="dom_text",
            )
    if surface.startswith("job_") and "remote" in fields and not candidates.get(
        "remote"
    ):
        lowered = body_text.lower()
        if "remote" in lowered or "work from home" in lowered:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "remote",
                "remote",
                source="dom_text",
            )
def _add_sourced_candidate(
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    field_name: str,
    value: object,
    *,
    source: str,
) -> None:
    if _long_text_candidate_is_noise(field_name, value, source=source):
        return
    before = len(candidates.get(field_name, []))
    add_candidate(candidates, field_name, value)
    after = len(candidates.get(field_name, []))
    if after <= before:
        return
    candidate_sources.setdefault(field_name, []).extend([source] * (after - before))
    bucket = field_sources.setdefault(field_name, [])
    if source not in bucket:
        bucket.append(source)

def _long_text_candidate_is_noise(
    field_name: str,
    value: object,
    *,
    source: str | None = None,
) -> bool:
    if field_name not in LONG_TEXT_FIELDS:
        return False
    cleaned = clean_text(value)
    lowered = cleaned.lower()
    if not lowered:
        return True
    if lowered in _LOW_SIGNAL_LONG_TEXT_VALUES:
        return True
    if field_name in {"description", "specifications"} and lowered.startswith(
        ("check the details", "product summary")
    ):
        return True
    if (
        source == "dom_sections"
        and field_name in {"description", "specifications", "product_details"}
        and len(cleaned.split()) <= 4
        and not any(token in cleaned for token in ".:;!?\n")
    ):
        return True
    return len(cleaned.split()) < 2
def _collect_record_candidates(
    record: dict[str, Any],
    *,
    page_url: str,
    fields: list[str],
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    source: str,
) -> None:
    allowed_fields = set(fields)
    for field_name, value in dict(record or {}).items():
        normalized_field = str(field_name or "").strip()
        if (
            not normalized_field
            or normalized_field.startswith("_")
            or normalized_field not in allowed_fields
        ):
            continue
        _add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            normalized_field,
            coerce_field_value(normalized_field, value, page_url),
            source=source,
        )
def _collect_structured_payload_candidates(
    payload: object,
    *,
    alias_lookup: dict[str, str],
    page_url: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    source: str,
) -> None:
    structured_candidates: dict[str, list[object]] = {}
    collect_structured_candidates(
        payload,
        alias_lookup,
        page_url,
        structured_candidates,
    )
    for field_name, values in structured_candidates.items():
        for value in values:
            _add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                field_name,
                value,
                source=source,
            )
def _primary_source_for_record(
    record: dict[str, Any],
    selected_field_sources: dict[str, str],
) -> str:
    del record
    selected_sources = [
        str(source or "").strip()
        for source in selected_field_sources.values()
        if str(source or "").strip()
    ]
    if selected_sources:
        return min(
            selected_sources,
            key=lambda source_name: _SOURCE_PRIORITY_RANK.get(
                source_name,
                len(_SOURCE_PRIORITY_RANK),
            ),
        )
    return "structured_dom"

_SOURCE_PRIORITY_RANK = {source_name: index for index, source_name in enumerate(SOURCE_PRIORITY)}
def _ordered_candidates_for_field(
    surface: str,
    field_name: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> list[tuple[str | None, object]]:
    values = list(candidates.get(field_name, []))
    sources = list(candidate_sources.get(field_name, []))
    indexed_entries = [
        (
            _field_source_rank(
                surface,
                field_name,
                sources[index] if index < len(sources) else None,
            ),
            index,
            sources[index] if index < len(sources) else None,
            value,
        )
        for index, value in enumerate(values)
    ]
    indexed_entries.sort(key=lambda row: (row[0], row[1]))
    return [(source, value) for _, _, source, value in indexed_entries]
def _winning_candidates_for_field(
    ordered_candidates: list[tuple[str | None, object]],
) -> tuple[list[object], str | None]:
    if not ordered_candidates:
        return [], None
    winning_source = ordered_candidates[0][0]
    return (
        [value for source, value in ordered_candidates if source == winning_source],
        winning_source,
    )

def _detail_url_candidate_is_low_signal(candidate_url: object, *, page_url: str) -> bool:
    candidate = text_or_none(candidate_url)
    if not candidate:
        return False
    candidate_parsed = urlparse(candidate)
    page_parsed = urlparse(page_url)
    candidate_host = (candidate_parsed.hostname or "").lower()
    page_host = (page_parsed.hostname or "").lower()
    if candidate_host and page_host and not same_site(page_url, candidate):
        return True
    candidate_path = str(candidate_parsed.path or "").strip()
    page_path = str(page_parsed.path or "").strip()
    if any(candidate_path.lower().endswith(ext) for ext in DETAIL_NON_PAGE_FILE_EXTENSIONS):
        return True
    candidate_segments = {
        segment.strip().lower()
        for segment in candidate_path.split("/")
        if segment.strip()
    }
    if candidate_segments & _DETAIL_URL_PLACEHOLDER_SEGMENTS:
        return True
    if same_site(page_url, candidate) and _detail_url_is_utility(candidate):
        return True
    return page_path not in {"", "/"} and candidate_path in {"", "/"}

def _preferred_detail_identity_url(
    *,
    surface: str,
    page_url: str,
    requested_page_url: str | None,
) -> str:
    if str(surface or "").strip().lower() != "ecommerce_detail":
        return page_url
    requested = text_or_none(requested_page_url)
    current = text_or_none(page_url)
    if not requested or not current or requested == current:
        return current or requested or page_url
    if not same_site(requested, current):
        return current
    if not _detail_url_looks_like_product(requested):
        return current
    if not _detail_url_is_utility(current):
        return current
    return requested

def _detail_url_looks_like_product(url: str) -> bool:
    path_segments = _detail_url_path_segments(url)
    path = f"/{'/'.join(path_segments)}".lower() if path_segments else ""
    if any(hint in path for hint in PRODUCT_URL_HINTS):
        return True
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return False
    terminal = next(
        (segment.strip().lower() for segment in reversed(segments) if segment.strip()),
        "",
    )
    if not terminal or terminal.isdigit():
        terminal = next(
            (
                segment.strip().lower()
                for segment in reversed(segments[:-1])
                if segment.strip() and not segment.strip().isdigit()
            ),
            "",
        )
        if not terminal:
            return False
    if _detail_url_is_utility(url):
        return False
    if _detail_url_is_collection_like(url):
        return False
    if any(token in terminal for token in ("category", "collections", "search", "sale")):
        return False
    return any(separator in terminal for separator in ("-", "_"))

def _detail_url_is_utility(url: str) -> bool:
    path_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", "/".join(_detail_url_path_segments(url)).lower())
        if token
    }
    if any(token in path_tokens for token in DETAIL_UTILITY_PATH_TOKENS):
        return True
    query_keys = {
        str(key).strip().lower()
        for key, value in parse_qsl(str(urlparse(url).query or ""), keep_blank_values=False)
        if str(key).strip() and str(value).strip()
    }
    if not query_keys:
        return False
    return any(str(key).strip().lower() in query_keys for key in DETAIL_SEARCH_QUERY_KEYS)

def _detail_url_is_collection_like(url: str) -> bool:
    path_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", "/".join(_detail_url_path_segments(url)).lower())
        if token
    }
    if any(token in path_tokens for token in DETAIL_PRODUCT_PATH_TOKENS):
        return False
    return any(token in path_tokens for token in DETAIL_COLLECTION_PATH_TOKENS)

def _record_matches_requested_detail_identity(
    record: dict[str, Any],
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    record_codes = _detail_identity_codes_from_record(record)
    if _detail_identity_codes_match(requested_codes, record_codes):
        return True
    requested_title = _detail_title_from_url(requested_page_url) or requested_page_url
    requested_tokens = _detail_identity_tokens(requested_title)
    if not requested_tokens:
        return False
    candidate_tokens = _detail_identity_tokens(record.get("title"))
    if not candidate_tokens:
        candidate_tokens = _detail_identity_tokens(record.get("description"))
    if not candidate_tokens:
        return False
    overlap = requested_tokens & candidate_tokens
    if len(requested_tokens) == 1:
        return bool(overlap)
    return len(overlap) >= min(2, len(requested_tokens))

def _detail_url_matches_requested_identity(
    candidate_url: str,
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    candidate_codes = _detail_identity_codes_from_url(candidate_url)
    if _detail_identity_codes_match(requested_codes, candidate_codes):
        return True
    requested_title = _detail_title_from_url(requested_page_url) or requested_page_url
    requested_tokens = _detail_identity_tokens(requested_title)
    if not requested_tokens:
        return False
    candidate_title = _detail_title_from_url(candidate_url) or candidate_url
    candidate_tokens = _detail_identity_tokens(candidate_title)
    if not candidate_tokens:
        return False
    overlap = requested_tokens & candidate_tokens
    if len(requested_tokens) == 1:
        return bool(overlap)
    return len(overlap) >= min(2, len(requested_tokens))

def _detail_identity_tokens(value: object) -> set[str]:
    cleaned = clean_text(value).lower()
    return {
        token
        for token in re.split(r"[^a-z0-9]+", cleaned)
        if len(token) >= 3 and token not in _DETAIL_IDENTITY_STOPWORDS
    }


def _detail_identity_codes_from_url(url: object) -> set[str]:
    text = text_or_none(url)
    if not text:
        return set()
    parsed = urlparse(text)
    codes: set[str] = set()
    for segment in _detail_url_path_segments(text):
        terminal = re.sub(r"\.(html?|htm)$", "", segment, flags=re.I)
        for match in re.findall(r"[A-Za-z0-9]{8,}", terminal):
            normalized = _normalized_detail_identity_code(match)
            if normalized:
                codes.add(normalized)
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        match = re.match(r"dwvar_([A-Za-z0-9]{8,})_", str(key or ""), flags=re.I)
        if match is None:
            continue
        normalized = _normalized_detail_identity_code(match.group(1))
        if normalized:
            codes.add(normalized)
    return codes


def _detail_identity_codes_from_record(record: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    codes.update(_detail_identity_codes_from_record_fields(record))
    record_url = text_or_none(record.get("url"))
    if record_url:
        codes.update(_detail_identity_codes_from_url(record_url))
    return codes


def _detail_identity_codes_from_record_fields(record: dict[str, Any]) -> set[str]:
    codes: set[str] = set()
    for field_name in ("sku", "product_id", "variant_id"):
        normalized = _normalized_detail_identity_code(record.get(field_name))
        if normalized:
            codes.add(normalized)
    return codes


def _normalized_detail_identity_code(value: object) -> str | None:
    text = re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()
    if len(text) < 8:
        return None
    if not re.search(r"[A-Z]", text) or not re.search(r"\d", text):
        return None
    return text


def _detail_identity_codes_match(
    expected_codes: set[str],
    candidate_codes: set[str],
) -> bool:
    if not expected_codes or not candidate_codes:
        return False
    return not expected_codes.isdisjoint(candidate_codes)

def _detail_redirect_identity_is_mismatched(
    record: dict[str, Any],
    *,
    page_url: str,
    requested_page_url: str | None,
) -> bool:
    requested = text_or_none(requested_page_url)
    current = text_or_none(page_url)
    if not requested:
        return False
    if not _detail_url_looks_like_product(requested):
        return False
    requested_codes = _detail_identity_codes_from_url(requested)
    record_field_codes = _detail_identity_codes_from_record_fields(record)
    if requested_codes and record_field_codes and not _detail_identity_codes_match(
        requested_codes,
        record_field_codes,
    ):
        return True
    candidate_url = text_or_none(record.get("url")) or current
    if candidate_url and candidate_url != requested and same_site(requested, candidate_url):
        if not _detail_url_matches_requested_identity(
            candidate_url,
            requested_page_url=requested,
        ):
            return True
        if not _record_matches_requested_detail_identity(
            record,
            requested_page_url=requested,
        ):
            return True
    if not current or requested == current:
        return False
    if not same_site(requested, current):
        return False
    if not _detail_url_is_utility(current):
        return False
    return not _record_matches_requested_detail_identity(
        record,
        requested_page_url=requested,
    )
def _selector_self_heal_config(
    extraction_runtime_snapshot: dict[str, object] | None,
) -> dict[str, object]:
    selector_self_heal = (
        extraction_runtime_snapshot.get("selector_self_heal")
        if isinstance(extraction_runtime_snapshot, dict)
        else None
    )
    return {
        "enabled": bool(
            selector_self_heal.get("enabled")
            if isinstance(selector_self_heal, dict)
            and selector_self_heal.get("enabled") is not None
            else crawler_runtime_settings.selector_self_heal_enabled
        ),
        "threshold": _coerce_float(
            selector_self_heal.get("min_confidence")
            if isinstance(selector_self_heal, dict)
            and selector_self_heal.get("min_confidence") is not None
            else crawler_runtime_settings.selector_self_heal_min_confidence,
            default=float(crawler_runtime_settings.selector_self_heal_min_confidence),
        ),
    }

def _selected_selector_trace(
    *,
    field_name: str,
    finalized_value: object,
    selector_trace_candidates: dict[str, list[dict[str, object]]],
) -> dict[str, object] | None:
    traces = list(selector_trace_candidates.get(field_name) or [])
    if not traces:
        return None
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        if trace.get("_candidate_value") == finalized_value:
            return {
                key: value
                for key, value in trace.items()
                if not str(key).startswith("_")
            }
    trace = next((row for row in traces if isinstance(row, dict)), {})
    if not isinstance(trace, dict):
        return None
    return {
        key: value
        for key, value in trace.items()
        if not str(key).startswith("_")
    }
def _materialize_record(
    *,
    page_url: str,
    requested_page_url: str | None,
    surface: str,
    requested_fields: list[str] | None,
    fields: list[str],
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    extraction_runtime_snapshot: dict[str, object] | None,
    tier_name: str,
    completed_tiers: list[str],
) -> dict[str, Any]:
    identity_url = _preferred_detail_identity_url(
        surface=surface,
        page_url=page_url,
        requested_page_url=requested_page_url,
    )
    record: dict[str, Any] = {"source_url": identity_url, "url": identity_url}
    selected_field_sources: dict[str, str] = {}
    selected_selector_traces: dict[str, dict[str, object]] = {}
    merged_images, merged_image_source = _materialize_image_fields(
        surface=surface,
        candidates=candidates,
        candidate_sources=candidate_sources,
    )
    for field_name in fields:
        if field_name in {"image_url", "additional_images"}:
            continue
        ordered_candidates = _ordered_candidates_for_field(
            surface,
            field_name,
            candidates,
            candidate_sources,
        )
        winning_values, selected_source = _winning_candidates_for_field(ordered_candidates)
        finalized = (
            finalize_candidate_value(field_name, [value for _, value in ordered_candidates])
            if field_name in STRUCTURED_OBJECT_FIELDS | STRUCTURED_OBJECT_LIST_FIELDS
            else finalize_candidate_value(field_name, winning_values)
        )
        if (
            field_name == "url"
            and "detail" in str(surface or "").strip().lower()
            and _detail_url_candidate_is_low_signal(finalized, page_url=page_url)
        ):
            continue
        if finalized not in (None, "", [], {}):
            record[field_name] = finalized
            if selected_source:
                selected_field_sources[field_name] = selected_source
                if selected_source == "selector_rule":
                    selector_trace = _selected_selector_trace(
                        field_name=field_name,
                        finalized_value=finalized,
                        selector_trace_candidates=selector_trace_candidates,
                    )
                    if selector_trace:
                        selected_selector_traces[field_name] = selector_trace
    if merged_images:
        record["image_url"] = merged_images[0]
        if len(merged_images) > 1:
            record["additional_images"] = merged_images[1:]
        if merged_image_source:
            selected_field_sources["image_url"] = merged_image_source
    promoted = _promote_detail_title(
        record,
        page_url=page_url,
        candidates=candidates,
        candidate_sources=candidate_sources,
    )
    if promoted:
        selected_field_sources["title"] = promoted[1]
        selected_selector_traces.pop("title", None)
    record["_field_sources"] = {
        field_name: list(source_list)
        for field_name, source_list in field_sources.items()
        if field_name in record
    }
    if selected_selector_traces:
        record["_selector_traces"] = selected_selector_traces
    record["_source"] = _primary_source_for_record(record, selected_field_sources)
    _normalize_variant_record(record)
    drop_low_signal_zero_detail_price(record)
    _dedupe_primary_and_additional_images(record)
    confidence = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    selector_self_heal = _selector_self_heal_config(extraction_runtime_snapshot)
    record["_confidence"] = confidence
    record["_extraction_tiers"] = {"completed": list(completed_tiers), "current": tier_name}
    record["_self_heal"] = {
        "enabled": bool(selector_self_heal["enabled"]),
        "triggered": False,
        "threshold": _coerce_float(selector_self_heal.get("threshold")),
    }
    return finalize_record(record, surface=surface)

def _normalize_variant_record(record: dict[str, Any]) -> None:
    _backfill_selected_variant_from_record(record)
    _apply_variant_axis_label_aliases(record)
    _dedupe_variant_rows(record)
    _prune_non_selectable_variant_axes(record)
    _normalize_variant_option_summaries(record)
    _prune_duplicate_variant_axis_fields(record)
    _prune_redundant_size_option_summary(record)
    _backfill_variant_prices_from_record(record)


def _price_value_is_zero(value: object) -> bool:
    text = text_or_none(value)
    if not text:
        return False
    normalized = normalize_decimal_price(
        text,
        interpret_integral_as_cents=False,
    )
    if not normalized:
        return False
    return _coerce_float(normalized, default=1.0) == 0.0


def _price_value_is_positive(value: object) -> bool:
    text = text_or_none(value)
    if not text:
        return False
    normalized = normalize_decimal_price(
        text,
        interpret_integral_as_cents=False,
    )
    if not normalized:
        return False
    return _coerce_float(normalized, default=0.0) > 0.0


def _record_field_sources(record: dict[str, Any], field_name: str) -> set[str]:
    field_sources = _object_dict(record.get("_field_sources"))
    return {
        str(source).strip()
        for source in _object_list(field_sources.get(field_name))
        if str(source).strip()
    }


def _append_record_field_source(
    record: dict[str, Any],
    field_name: str,
    source: str,
) -> None:
    normalized_source = str(source).strip()
    if not normalized_source:
        return
    field_sources = record.setdefault("_field_sources", {})
    if not isinstance(field_sources, dict):
        return
    source_bucket = field_sources.setdefault(field_name, [])
    if not isinstance(source_bucket, list):
        return
    if normalized_source not in source_bucket:
        source_bucket.append(normalized_source)


def _detail_record_has_positive_price_corroboration(record: dict[str, Any]) -> bool:
    if _price_value_is_positive(record.get("original_price")):
        return True
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict) and any(
        _price_value_is_positive(selected_variant.get(field_name))
        for field_name in ("price", "original_price")
    ):
        return True
    variants = record.get("variants")
    if not isinstance(variants, list):
        return False
    return any(
        isinstance(variant, dict)
        and any(
            _price_value_is_positive(variant.get(field_name))
            for field_name in ("price", "original_price")
        )
        for variant in variants
    )


def drop_low_signal_zero_detail_price(record: dict[str, Any]) -> None:
    if not _price_value_is_zero(record.get("price")):
        return
    price_sources = _record_field_sources(record, "price")
    if not price_sources:
        return
    if not price_sources <= _LOW_SIGNAL_ZERO_PRICE_SOURCES:
        return
    if _detail_record_has_positive_price_corroboration(record):
        return
    record.pop("price", None)
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict) and _price_value_is_zero(selected_variant.get("price")):
        selected_variant.pop("price", None)
        selected_variant.pop("currency", None)
    variants = record.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict) or not _price_value_is_zero(variant.get("price")):
                continue
            variant.pop("price", None)
            variant.pop("currency", None)
    currency_sources = _record_field_sources(record, "currency")
    if (not currency_sources or currency_sources <= _LOW_SIGNAL_ZERO_PRICE_SOURCES) and record.get(
        "original_price"
    ) in (None, "", [], {}):
        record.pop("currency", None)


def _apply_variant_axis_label_aliases(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    aliases: dict[str, dict[str, str]] = {}
    rows_by_identity: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        identity = text_or_none(variant.get("variant_id")) or text_or_none(variant.get("sku"))
        if identity:
            rows_by_identity.setdefault(identity, []).append(variant)
    for rows in rows_by_identity.values():
        for left in rows:
            left_options = left.get("option_values")
            if not isinstance(left_options, dict):
                continue
            for right in rows:
                if left is right:
                    continue
                right_options = right.get("option_values")
                if not isinstance(right_options, dict):
                    continue
                for axis_name, left_value in left_options.items():
                    right_value = right_options.get(axis_name)
                    if not _axis_values_describe_same_choice(
                        left_options,
                        right_options,
                        axis_name=str(axis_name),
                    ):
                        continue
                    code, label = _code_label_pair(left_value, right_value)
                    if code and label:
                        aliases.setdefault(str(axis_name), {})[code] = label
    if not aliases:
        return
    _rewrite_variant_axis_values(record, aliases)


def _axis_values_describe_same_choice(
    left_options: dict[str, Any],
    right_options: dict[str, Any],
    *,
    axis_name: str,
) -> bool:
    for other_axis, left_value in left_options.items():
        if str(other_axis) == axis_name:
            continue
        right_value = right_options.get(other_axis)
        if clean_text(left_value).lower() != clean_text(right_value).lower():
            return False
    return True


def _code_label_pair(left: object, right: object) -> tuple[str, str] | tuple[None, None]:
    left_text = clean_text(left)
    right_text = clean_text(right)
    if not left_text or not right_text or left_text.lower() == right_text.lower():
        return (None, None)
    if _variant_axis_value_looks_like_code(left_text) and not _variant_axis_value_looks_like_code(right_text):
        return left_text, right_text
    if _variant_axis_value_looks_like_code(right_text) and not _variant_axis_value_looks_like_code(left_text):
        return right_text, left_text
    return (None, None)


def _variant_axis_value_looks_like_code(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{2,6}", str(value or "").strip()))


def _rewrite_variant_axis_values(
    record: dict[str, Any],
    aliases: dict[str, dict[str, str]],
) -> None:
    for axis_name, axis_aliases in aliases.items():
        if clean_text(record.get(axis_name)) in axis_aliases:
            record[axis_name] = axis_aliases[clean_text(record.get(axis_name))]
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict):
        for axis_name, axis_values in list(variant_axes.items()):
            axis_aliases = aliases.get(str(axis_name)) or {}
            if not axis_aliases or not isinstance(axis_values, list):
                continue
            rewritten = [axis_aliases.get(clean_text(value), value) for value in axis_values]
            variant_axes[axis_name] = list(dict.fromkeys(clean_text(value) for value in rewritten if clean_text(value)))
    for row in [record.get("selected_variant"), *list(record.get("variants") or [])]:
        if not isinstance(row, dict):
            continue
        for axis_name, axis_aliases in aliases.items():
            if clean_text(row.get(axis_name)) in axis_aliases:
                row[axis_name] = axis_aliases[clean_text(row.get(axis_name))]
        option_values = row.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for axis_name, axis_aliases in aliases.items():
            current = clean_text(option_values.get(axis_name))
            if current in axis_aliases:
                option_values[axis_name] = axis_aliases[current]


def _normalize_variant_option_summaries(record: dict[str, Any]) -> None:
    variant_axes = record.get("variant_axes")
    if not isinstance(variant_axes, dict) or not variant_axes:
        return
    axis_keys = {str(axis_name).strip() for axis_name in variant_axes if str(axis_name).strip()}
    if not axis_keys:
        return
    for index in range(1, 5):
        name_key = f"option{index}_name"
        option_name = text_or_none(record.get(name_key))
        if not option_name:
            continue
        axis_key = normalized_variant_axis_key(option_name)
        if axis_key not in axis_keys:
            continue
        display_name = normalized_variant_axis_display_name(option_name)
        if display_name and display_name != option_name:
            record[name_key] = display_name

def _backfill_selected_variant_from_record(record: dict[str, Any]) -> None:
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    for field_name in (
        "price",
        "original_price",
        "currency",
        "availability",
        "sku",
        "barcode",
        "image_url",
    ):
        if selected_variant.get(field_name) not in (None, "", [], {}):
            continue
        fallback_value = record.get(field_name)
        if fallback_value in (None, "", [], {}):
            continue
        selected_variant[field_name] = fallback_value

def _dedupe_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    best_by_identity: dict[tuple[tuple[str, str], ...] | str, dict[str, Any]] = {}
    ordered_keys: list[tuple[tuple[str, str], ...] | str] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        option_values = variant.get("option_values")
        identity_key: tuple[tuple[str, str], ...] | str | None = None
        if isinstance(option_values, dict) and option_values:
            normalized_pairs = tuple(
                sorted(
                    (
                        str(axis_name).strip(),
                        clean_text(axis_value),
                    )
                    for axis_name, axis_value in option_values.items()
                    if str(axis_name).strip() and clean_text(axis_value)
                )
            )
            if normalized_pairs:
                identity_key = normalized_pairs
        if identity_key is None:
            identity_key = (
                text_or_none(variant.get("variant_id"))
                or text_or_none(variant.get("sku"))
                or text_or_none(variant.get("url"))
            )
        if not identity_key:
            continue
        existing = best_by_identity.get(identity_key)
        candidate = dict(variant)
        if existing is None:
            best_by_identity[identity_key] = candidate
            ordered_keys.append(identity_key)
            continue
        if len(candidate) > len(existing):
            best_by_identity[identity_key] = candidate
            existing = candidate
        for field_name, field_value in candidate.items():
            if existing.get(field_name) in (None, "", [], {}) and field_value not in (
                None,
                "",
                [],
                {},
            ):
                existing[field_name] = field_value
    deduped_variants = [best_by_identity[key] for key in ordered_keys]
    if not deduped_variants:
        return
    record["variants"] = deduped_variants
    record["variant_count"] = len(deduped_variants)
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    selected_option_values = selected_variant.get("option_values")
    if isinstance(selected_option_values, dict) and selected_option_values:
        selected_key = tuple(
            sorted(
                (
                    str(axis_name).strip(),
                    clean_text(axis_value),
                )
                for axis_name, axis_value in selected_option_values.items()
                if str(axis_name).strip() and clean_text(axis_value)
            )
        )
        if selected_key in best_by_identity:
            record["selected_variant"] = _merge_selected_variant_candidate(
                selected_variant,
                best_by_identity[selected_key],
            )

def _merge_selected_variant_candidate(
    selected_variant: dict[str, Any],
    matched_variant: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(matched_variant)
    selected_option_values = selected_variant.get("option_values")
    selected_option_axes = (
        {
            str(axis_name).strip()
            for axis_name, axis_value in selected_option_values.items()
            if str(axis_name).strip() and axis_value not in (None, "", [], {})
        }
        if isinstance(selected_option_values, dict)
        else set()
    )
    for field_name, field_value in selected_variant.items():
        if merged.get(field_name) in (None, "", [], {}) and field_value not in (
            None,
            "",
            [],
            {},
        ):
            merged[field_name] = field_value
    if selected_option_axes:
        for axis_name in selected_option_axes:
            if axis_name not in selected_variant and axis_name in merged:
                merged.pop(axis_name, None)
    return merged

def _prune_non_selectable_variant_axes(record: dict[str, Any]) -> None:
    variant_axes = record.get("variant_axes")
    if not isinstance(variant_axes, dict) or not variant_axes:
        return
    always_selectable_axes = {"size"}
    for axis_name in _referenced_variant_axes(record):
        if axis_name in variant_axes:
            always_selectable_axes.add(axis_name)
    selectable_axes, _single_value_attributes = split_variant_axes(
        variant_axes,
        always_selectable_axes=frozenset(always_selectable_axes),
    )
    if selectable_axes:
        record["variant_axes"] = selectable_axes
    else:
        record.pop("variant_axes", None)
    for field_name, field_value in _single_value_attributes.items():
        if record.get(field_name) in (None, "", [], {}):
            normalized_value = clean_text(field_value)
            if normalized_value:
                record[field_name] = normalized_value
    for field_name, axis_values in selectable_axes.items():
        if record.get(field_name) not in (None, "", [], {}):
            continue
        if not isinstance(axis_values, list) or len(axis_values) != 1:
            continue
        normalized_value = clean_text(axis_values[0])
        if normalized_value:
            record[field_name] = normalized_value
    allowed_axes = set(selectable_axes)
    if not allowed_axes:
        return
    _prune_variant_option_values(record.get("selected_variant"), allowed_axes=allowed_axes)
    variants = record.get("variants")
    if not isinstance(variants, list):
        return
    for variant in variants:
        _prune_variant_option_values(variant, allowed_axes=allowed_axes)

def _referenced_variant_axes(record: dict[str, Any]) -> set[str]:
    referenced_axes: set[str] = set()
    selected_variant = record.get("selected_variant")
    if isinstance(selected_variant, dict):
        option_values = selected_variant.get("option_values")
        if isinstance(option_values, dict):
            referenced_axes.update(
                str(axis_name).strip()
                for axis_name, axis_value in option_values.items()
                if str(axis_name).strip() and axis_value not in (None, "", [], {})
            )
    variants = record.get("variants")
    if isinstance(variants, list):
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            option_values = variant.get("option_values")
            if not isinstance(option_values, dict):
                continue
            referenced_axes.update(
                str(axis_name).strip()
                for axis_name, axis_value in option_values.items()
                if str(axis_name).strip() and axis_value not in (None, "", [], {})
            )
    return referenced_axes

def _prune_variant_option_values(
    value: object,
    *,
    allowed_axes: set[str],
) -> None:
    if not isinstance(value, dict):
        return
    option_values = value.get("option_values")
    if not isinstance(option_values, dict) or not option_values:
        return
    pruned = {
        str(axis_name): axis_value
        for axis_name, axis_value in option_values.items()
        if str(axis_name) in allowed_axes and axis_value not in (None, "", [], {})
    }
    if pruned:
        value["option_values"] = pruned
        return
    value.pop("option_values", None)


def _prune_duplicate_variant_axis_fields(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list):
        return
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict) or len(option_values) < 2:
            continue
        for axis_name, axis_value in option_values.items():
            normalized_axis = str(axis_name).strip()
            if not normalized_axis:
                continue
            normalized_value = clean_text(axis_value)
            if not normalized_value:
                continue
            if clean_text(variant.get(normalized_axis)) == normalized_value:
                variant.pop(normalized_axis, None)


def _prune_redundant_size_option_summary(record: dict[str, Any]) -> None:
    has_size_summary = bool(
        record.get("available_sizes")
        or (
            isinstance(record.get("variant_axes"), dict)
            and bool(record["variant_axes"].get("size"))
        )
    )
    if not has_size_summary:
        return
    option_pairs: list[tuple[str, object]] = []
    removed_size_summary = False
    for index in range(1, 5):
        name_key = f"option{index}_name"
        values_key = f"option{index}_values"
        option_name = text_or_none(record.get(name_key))
        option_values = record.get(values_key)
        record.pop(name_key, None)
        record.pop(values_key, None)
        if option_name is None and option_values in (None, "", [], {}):
            continue
        if normalized_variant_axis_key(option_name) == "size":
            removed_size_summary = True
            continue
        if option_name is not None and option_values not in (None, "", [], {}):
            option_pairs.append((option_name, option_values))
    if not removed_size_summary:
        for index, (option_name, option_values) in enumerate(option_pairs, start=1):
            record[f"option{index}_name"] = option_name
            record[f"option{index}_values"] = option_values
        return
    for index, (option_name, option_values) in enumerate(option_pairs, start=1):
        record[f"option{index}_name"] = option_name
        record[f"option{index}_values"] = option_values

def _backfill_variant_prices_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    fallback_fields = {
        field_name: record.get(field_name)
        for field_name in ("price", "original_price", "currency")
        if record.get(field_name) not in (None, "", [], {})
    }
    if not fallback_fields:
        return

    def _has_distinct_variant_value(field_name: str) -> bool:
        fallback_value = text_or_none(fallback_fields.get(field_name))
        if fallback_value is None:
            return False
        return any(
            isinstance(variant, dict)
            and text_or_none(variant.get(field_name)) not in (None, fallback_value)
            for variant in variants
        )

    distinct_price = _has_distinct_variant_value("price")
    distinct_original_price = _has_distinct_variant_value("original_price")
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if not distinct_price and variant.get("price") in (None, "", [], {}):
            variant["price"] = fallback_fields.get("price")
        if not distinct_original_price and variant.get("original_price") in (None, "", [], {}):
            variant["original_price"] = fallback_fields.get("original_price")
        if variant.get("currency") in (None, "", [], {}) and fallback_fields.get("currency") not in (
            None,
            "",
            [],
            {},
        ):
            variant["currency"] = fallback_fields.get("currency")
    selected_variant = record.get("selected_variant")
    if not isinstance(selected_variant, dict):
        return
    if not distinct_price and selected_variant.get("price") in (None, "", [], {}):
        selected_variant["price"] = fallback_fields.get("price")
    if not distinct_original_price and selected_variant.get("original_price") in (None, "", [], {}):
        selected_variant["original_price"] = fallback_fields.get("original_price")
    if selected_variant.get("currency") in (None, "", [], {}) and fallback_fields.get("currency") not in (
        None,
        "",
        [],
        {},
    ):
        selected_variant["currency"] = fallback_fields.get("currency")

def _dedupe_primary_and_additional_images(record: dict[str, Any]) -> None:
    raw_additional_images = record.get("additional_images")
    additional_images = (
        list(raw_additional_images)
        if isinstance(raw_additional_images, (list, tuple, set))
        else ([raw_additional_images] if raw_additional_images not in (None, "", [], {}) else [])
    )
    values: list[str] = []
    for raw_value in (
        record.get("image_url"),
        *additional_images,
    ):
        image = text_or_none(raw_value)
        if image:
            values.append(image)
    merged = dedupe_image_urls(values)
    if not merged:
        record.pop("image_url", None)
        record.pop("additional_images", None)
        return
    record["image_url"] = merged[0]
    if len(merged) > 1:
        record["additional_images"] = merged[1:]
        return
    record.pop("additional_images", None)

def _looks_like_site_shell_record(record: dict[str, Any], *, page_url: str) -> bool:
    title = text_or_none(record.get("title")) or ""
    field_sources = _object_dict(record.get("_field_sources"))
    title_field_sources = _object_list(field_sources.get("title"))
    title_sources = {
        str(source).strip()
        for source in title_field_sources
        if str(source).strip()
    }
    if is_title_noise(title):
        return True
    if _detail_url_is_collection_like(page_url):
        return True
    generic_detail_fields = (
        "price",
        "currency",
        "brand",
        "category",
    )
    strong_detail_fields = (
        "brand",
        "sku",
        "part_number",
        "barcode",
        "availability",
        "variant_axes",
        "variants",
        "selected_variant",
    )
    has_generic_detail_fields = any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in generic_detail_fields
    )
    if (
        "url_slug" in title_sources
        and float((record.get("_confidence") or {}).get("score") or 0.0) < 0.5
        and str(record.get("_source") or "").strip() in {"opengraph", "json_ld_page_level", "microdata"}
        and not any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in strong_detail_fields
        )
    ):
        return True
    if (
        _detail_title_looks_like_placeholder(title)
        and not has_generic_detail_fields
        and not any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in strong_detail_fields
        )
    ):
        return True
    if not _title_needs_promotion(title, page_url=page_url):
        if (
            _title_looks_like_brand_shell(title, page_url=page_url)
            and not has_generic_detail_fields
            and not any(
                record.get(field_name) not in (None, "", [], {})
                for field_name in strong_detail_fields
            )
            and (
                _description_looks_like_shell_copy(record.get("description"))
                or _detail_image_looks_like_tracking_or_shell(record.get("image_url"))
                or len(clean_text(record.get("description"))) <= 120
            )
        ):
            return True
        if not _detail_url_is_utility(page_url):
            return False
        record_url = text_or_none(record.get("url")) or ""
        has_strong_detail_fields = any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in strong_detail_fields
        )
        return not has_strong_detail_fields or _detail_url_is_utility(record_url)
    if str(record.get("_source") or "").strip() in {
        "adapter",
        "network_payload",
        "json_ld",
        "microdata",
        "embedded_json",
        "js_state",
    }:
        return False
    if (
        _title_looks_like_brand_shell(title, page_url=page_url)
        and not has_generic_detail_fields
        and _description_looks_like_shell_copy(record.get("description"))
    ):
        return True
    return not any(record.get(field_name) not in (None, "", [], {}) for field_name in strong_detail_fields)

def _detail_title_looks_like_placeholder(title: str) -> bool:
    normalized = clean_text(title)
    if not normalized:
        return False
    lowered = normalized.lower()
    if lowered in {"404", "not found"}:
        return True
    return any(pattern.search(normalized) for pattern in _DETAIL_PLACEHOLDER_TITLE_PATTERNS)

def _detail_image_looks_like_tracking_or_shell(value: object) -> bool:
    image_url = text_or_none(value)
    if not image_url:
        return False
    lowered = image_url.lower()
    return any(
        token in lowered
        for token in (
            "facebook.com/tr?",
            "facebook.com/tr&id=",
            "/tr?id=",
            "doubleclick",
            "googletagmanager",
            "google-analytics",
            "pixel",
        )
    )

def _title_looks_like_brand_shell(title: str, *, page_url: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    if not normalized_title:
        return False
    host = str(urlparse(page_url).hostname or "").strip().lower()
    host_label = host.removeprefix("www.").split(".", 1)[0]
    compact_title = re.sub(r"[^a-z0-9]+", "", normalized_title)
    compact_host = re.sub(r"[^a-z0-9]+", "", host_label)
    if compact_title and compact_host and compact_title == compact_host:
        return True
    host_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", host_label)
        if len(token) >= 3
    }
    if not host_tokens:
        return False
    title_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", normalized_title)
        if len(token) >= 3
    }
    if not title_tokens or not (title_tokens & host_tokens):
        return False
    extra_tokens = title_tokens - host_tokens
    return bool(extra_tokens) and (
        extra_tokens <= set(DETAIL_BRAND_SHELL_TITLE_TOKENS)
        or (len(extra_tokens) <= 3 and len(title_tokens) <= 5)
    )

def _description_looks_like_shell_copy(description: object) -> bool:
    normalized_description = str(text_or_none(description) or "").strip().lower()
    if not normalized_description:
        return False
    return any(
        phrase in normalized_description
        for phrase in DETAIL_BRAND_SHELL_DESCRIPTION_PHRASES
    )

def _variant_axis_value_count(value: object) -> int:
    if not isinstance(value, dict):
        return 0
    return sum(len([item for item in values if text_or_none(item)]) for values in value.values() if isinstance(values, list))

def _variant_rows_with_option_values(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return sum(1 for row in value if isinstance(row, dict) and isinstance(row.get("option_values"), dict) and bool(row.get("option_values")))

def _variant_signal_strength(*, variant_axes: object, variants: object, selected_variant: object) -> tuple[int, int, int, int, int]:
    return (
        len(variant_axes) if isinstance(variant_axes, dict) else 0,
        _variant_axis_value_count(variant_axes),
        len(variants) if isinstance(variants, list) else 0,
        _variant_rows_with_option_values(variants),
        int(
            isinstance(selected_variant, dict)
            and isinstance(selected_variant.get("option_values"), dict)
            and bool(selected_variant.get("option_values"))
        ),
    )

def _should_collect_dom_variants(
    candidates: dict[str, list[object]],
    dom_variants: dict[str, object],
) -> bool:
    if not any(candidates.get(field_name) for field_name in VARIANT_DOM_FIELD_NAMES):
        return True
    existing_variant_axes = finalize_candidate_value("variant_axes", list(candidates.get("variant_axes") or []))
    existing_variants = finalize_candidate_value("variants", list(candidates.get("variants") or []))
    existing_selected_variant = finalize_candidate_value("selected_variant", list(candidates.get("selected_variant") or []))
    existing_strength = _variant_signal_strength(
        variant_axes=existing_variant_axes,
        variants=existing_variants,
        selected_variant=existing_selected_variant,
    )
    if 0 in existing_strength[:4] or existing_strength[-1] == 0:
        return True
    dom_strength = _variant_signal_strength(
        variant_axes=dom_variants.get("variant_axes"),
        variants=dom_variants.get("variants"),
        selected_variant=dom_variants.get("selected_variant"),
    )
    return dom_strength > existing_strength

def _materialize_image_fields(
    *,
    surface: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> tuple[list[str], str | None]:
    values: list[str] = []
    primary_source: str | None = None
    ordered_candidates = [
        *_ordered_candidates_for_field(surface, "image_url", candidates, candidate_sources),
        *_ordered_candidates_for_field(surface, "additional_images", candidates, candidate_sources),
    ]
    for source, raw_value in ordered_candidates:
        if primary_source is None and source:
            primary_source = source
        items = raw_value if isinstance(raw_value, list) else [raw_value]
        for item in items:
            image = text_or_none(item)
            if image:
                values.append(image)
    return dedupe_image_urls(values), primary_source

def _resolve_dom_variant_group_name(node: Any) -> str:
    resolved = resolve_variant_group_name(node)
    if resolved:
        return resolved
    if not hasattr(node, "select"):
        return ""
    for input_node in node.select("input[type='radio'], input[type='checkbox']")[:24]:
        resolved = resolve_variant_group_name(input_node)
        if resolved:
            return resolved
    return ""

def _variant_option_value_is_noise(value: str | None) -> bool:
    if not value:
        return True
    lowered = value.lower()
    return (
        not value
        or lowered in {"select", "choose", "option", "size guide"}
        or re.fullmatch(r"[-\s]*(?:click\s+to\s+)?(?:choose|select)\b.*", lowered) is not None
        or re.fullmatch(r"[-\s]+.+[-\s]+", lowered) is not None
        or re.fullmatch(r"\(\d+\)", value) is not None
        or re.fullmatch(r"\d{3,5}/\d{2,5}/\d{2,5}", value) is not None
    )


def _strip_variant_option_value_suffix_noise(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    stripped = cleaned
    for pattern in _VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS:
        stripped = pattern.sub("", stripped).strip()
    return stripped or cleaned

def _variant_input_label(container: Any, input_node: Any) -> Any | None:
    input_id = text_or_none(input_node.get("id")) if hasattr(input_node, "get") else None
    if input_id:
        label = container.find("label", attrs={"for": input_id})
        if label is not None:
            return label
    if hasattr(input_node, "find_parent"):
        label = input_node.find_parent("label")
        if label is not None:
            return label
    sibling = getattr(input_node, "next_sibling", None)
    while sibling is not None:
        if getattr(sibling, "name", None) == "label":
            return sibling
        sibling = getattr(sibling, "next_sibling", None)
    return None

def _node_state_matches(node: Any, *tokens: str) -> bool:
    if not hasattr(node, "get"):
        return False
    class_attr = node.get("class")
    probe = (
        " ".join(str(value) for value in class_attr)
        if isinstance(class_attr, list)
        else str(class_attr or "")
    ).lower()
    return any(token in probe for token in tokens)

def _node_attr_is_truthy(node: Any, *attr_names: str) -> bool:
    if not hasattr(node, "get"):
        return False
    for attr_name in attr_names:
        value = node.get(attr_name)
        if value in (None, "", [], {}, False):
            continue
        if value is True:
            return True
        normalized = str(value).strip().lower()
        if normalized in {"", "false", "0", "none"}:
            continue
        return True
    return False

def _variant_option_availability(*, node: Any, label_node: Any | None) -> tuple[str | None, int | None]:
    attr_probe_parts: list[str] = []
    text_probe_parts: list[str] = []
    for candidate in (
        node,
        label_node,
        getattr(node, "parent", None),
        getattr(label_node, "parent", None) if label_node is not None else None,
    ):
        if candidate is None or not hasattr(candidate, "get"):
            continue
        class_attr = candidate.get("class")
        if isinstance(class_attr, list):
            attr_probe_parts.extend(str(value) for value in class_attr if value)
        elif class_attr not in (None, "", [], {}):
            attr_probe_parts.append(str(class_attr))
        for attr_name in ("aria-label", "data-testid", "name", "id"):
            value = candidate.get(attr_name)
            if value not in (None, "", [], {}):
                attr_probe_parts.append(str(value))
        if hasattr(candidate, "get_text"):
            text_probe_parts.append(candidate.get_text(" ", strip=True))
    attr_probe = clean_text(" ".join(attr_probe_parts)).lower()
    text_probe = clean_text(" ".join(text_probe_parts)).lower()
    if any(
        token in attr_probe
        for token in ("outstock", "out-stock", "soldout", "sold-out", "unavailable")
    ):
        return "out_of_stock", 0
    stock_match = re.search(r"\b(\d+)\s+left\b", text_probe)
    if stock_match:
        quantity = int(stock_match.group(1))
        return ("in_stock" if quantity > 0 else "out_of_stock"), quantity
    if "out of stock" in text_probe or "sold out" in text_probe:
        return "out_of_stock", 0
    if "in stock" in text_probe or "available" in text_probe:
        return "in_stock", None
    return None, None

def _variant_option_url(
    *,
    container: Any,
    node: Any,
    label_node: Any | None,
    page_url: str,
) -> str | None:
    attr_names = (
        "href",
        "data-href",
        "data-url",
        "data-product-url",
        "data-target-url",
        "data-link",
        "data-variant-url",
    )
    candidates: list[Any] = [node, label_node]
    if hasattr(node, "find_parent"):
        parent_anchor = node.find_parent("a", href=True)
        if parent_anchor is not None:
            candidates.append(parent_anchor)
    if label_node is not None and hasattr(label_node, "find_parent"):
        parent_anchor = label_node.find_parent("a", href=True)
        if parent_anchor is not None:
            candidates.append(parent_anchor)
    if hasattr(node, "find"):
        anchor = node.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    if label_node is not None and hasattr(label_node, "find"):
        anchor = label_node.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    if hasattr(container, "find"):
        anchor = container.find("a", href=True)
        if anchor is not None:
            candidates.append(anchor)
    for candidate in candidates:
        if candidate is None or not hasattr(candidate, "get"):
            continue
        for attr_name in attr_names:
            raw = candidate.get(attr_name)
            url = text_or_none(raw)
            if url:
                from app.services.field_value_core import absolute_url

                return absolute_url(page_url, url)
    return None

def _merge_variant_option_state(
    entry: dict[str, object],
    *,
    container: Any,
    node: Any,
    page_url: str,
    label_node: Any | None = None,
) -> None:
    selected = (
        _node_state_matches(node, "selected", "active", "current", "highlight", "checked")
        or _node_attr_is_truthy(
            node,
            "checked",
            "aria-checked",
        )
        or text_or_none(getattr(node, "get", lambda *_args, **_kwargs: None)("data-state")) == "checked"
    )
    if selected:
        entry["selected"] = True
    availability, stock_quantity = _variant_option_availability(node=node, label_node=label_node)
    if availability and entry.get("availability") in (None, "", [], {}):
        entry["availability"] = availability
    if stock_quantity is not None:
        entry["stock_quantity"] = stock_quantity
    variant_url = _variant_option_url(
        container=container,
        node=node,
        label_node=label_node,
        page_url=page_url,
    )
    if variant_url and entry.get("url") in (None, "", [], {}):
        entry["url"] = variant_url

def _collect_variant_choice_entries(container: Any, *, page_url: str) -> list[dict[str, object]]:
    axis_name = normalized_variant_axis_key(_resolve_dom_variant_group_name(container))
    entries_by_value: dict[str, dict[str, object]] = {}
    for node in container.select(
        "[data-value], [data-option-value], [aria-label], input[value], [role='radio']"
    )[:24]:
        cleaned = text_or_none(
            coerce_field_value(
                axis_name if axis_name in {"color", "size"} else "size",
                _variant_choice_entry_value(container, node),
                page_url,
            )
        )
        cleaned = _strip_variant_option_value_suffix_noise(cleaned)
        if _variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        _merge_variant_option_state(
            entry,
            container=container,
            node=node,
            page_url=page_url,
        )
        variant_id = text_or_none(
            node.get("data-sku")
            or node.get("data-variant-id")
            or node.get("data-product-id")
        )
        if variant_id and entry.get("variant_id") in (None, "", [], {}):
            entry["variant_id"] = variant_id
    for input_node in container.select("input[type='radio'], input[type='checkbox']")[:24]:
        label_node = _variant_input_label(container, input_node)
        cleaned = text_or_none(
            coerce_field_value(
                axis_name if axis_name in {"color", "size"} else "size",
                _variant_choice_entry_value(container, input_node, label_node=label_node),
                page_url,
            )
        )
        cleaned = _strip_variant_option_value_suffix_noise(cleaned)
        if _variant_option_value_is_noise(cleaned):
            continue
        entry = entries_by_value.setdefault(cleaned, {"value": cleaned})
        _merge_variant_option_state(
            entry,
            container=container,
            node=input_node,
            page_url=page_url,
            label_node=label_node,
        )
    return list(entries_by_value.values())


def _variant_choice_entry_value(
    container: Any,
    node: Any,
    *,
    label_node: Any | None = None,
) -> str:
    resolved_label = label_node or _variant_input_label(container, node)
    label_text = (
        resolved_label.get_text(" ", strip=True)
        if resolved_label is not None and hasattr(resolved_label, "get_text")
        else ""
    )
    return clean_text(
        label_text
        or node.get("data-value")
        or node.get("data-option-value")
        or node.get("aria-label")
        or node.get("value")
    )


def _split_compound_axis_name(name: object) -> list[tuple[str, str]]:
    cleaned = clean_text(name)
    if not cleaned:
        return []
    parts = [
        clean_text(part)
        for part in re.split(r"\s*(?:&|/|\band\b)\s*", cleaned, flags=re.I)
        if clean_text(part)
    ]
    if len(parts) < 2:
        return []
    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in parts:
        if not variant_axis_name_is_semantic(part):
            return []
        axis_key = normalized_variant_axis_key(part)
        if not axis_key or axis_key in seen:
            return []
        seen.add(axis_key)
        resolved.append((axis_key, normalized_variant_axis_display_name(part) or part))
    return resolved if len(resolved) >= 2 else []


def _strip_variant_option_price_suffix(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    without_price = re.sub(r"\s*\([^)]*[\d][^)]*\)\s*$", "", cleaned).strip()
    return without_price or cleaned


def _split_compound_option_value(
    value: object,
    *,
    axis_keys: tuple[str, ...],
) -> dict[str, str] | None:
    cleaned = _strip_variant_option_price_suffix(value)
    if not cleaned or len(axis_keys) != 2 or "size" not in axis_keys:
        return None
    other_axis = next((axis for axis in axis_keys if axis != "size"), "")
    if not other_axis:
        return None
    tokens = [token for token in cleaned.split() if token]
    for width in range(min(3, len(tokens)), 0, -1):
        size_candidate = " ".join(tokens[-width:])
        if not any(pattern.fullmatch(size_candidate) for pattern in _DETAIL_VARIANT_SIZE_VALUE_PATTERNS):
            continue
        other_value = clean_text(" ".join(tokens[:-width]))
        if not other_value:
            return None
        return {
            other_axis: other_value,
            "size": size_candidate,
        }
    return None


def _expand_compound_option_group(group: dict[str, object]) -> list[dict[str, object]] | None:
    axis_parts = _split_compound_axis_name(group.get("name"))
    if len(axis_parts) != 2:
        return None
    entries = [entry for entry in _object_list(group.get("entries")) if isinstance(entry, dict)]
    if not entries:
        return None
    axis_keys = tuple(axis_key for axis_key, _ in axis_parts)
    parsed_rows: list[dict[str, str]] = []
    for entry in entries:
        parsed = _split_compound_option_value(entry.get("value"), axis_keys=axis_keys)
        if not parsed:
            return None
        parsed_rows.append(parsed)
    axis_values: dict[str, list[str]] = {axis_key: [] for axis_key, _ in axis_parts}
    observed_combos: set[tuple[str, ...]] = set()
    for parsed in parsed_rows:
        combo = tuple(parsed.get(axis_key, "") for axis_key, _ in axis_parts)
        if any(not value for value in combo):
            return None
        observed_combos.add(combo)
        for axis_key, _ in axis_parts:
            axis_value = parsed[axis_key]
            if axis_value not in axis_values[axis_key]:
                axis_values[axis_key].append(axis_value)
    expected_combo_count = 1
    for axis_key, _ in axis_parts:
        values = axis_values.get(axis_key) or []
        if len(values) < 2:
            return None
        expected_combo_count *= len(values)
    if len(observed_combos) != len(parsed_rows) or len(observed_combos) != expected_combo_count:
        return None
    return [
        {
            "name": display_name,
            "values": axis_values[axis_key],
            "entries": [{"value": axis_value} for axis_value in axis_values[axis_key]],
        }
        for axis_key, display_name in axis_parts
    ]

def _variant_query_url(page_url: str, *, query_key: str, query_value: str) -> str | None:
    normalized_key = text_or_none(query_key)
    normalized_value = text_or_none(query_value)
    if not normalized_key or not normalized_value:
        return None
    parsed = urlsplit(str(page_url or "").strip())
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != normalized_key
    ]
    query_pairs.append((normalized_key, normalized_value))
    return urlunsplit(parsed._replace(query=urlencode(query_pairs, doseq=True)))

def _iter_variant_mapping_payloads(value: Any, *, depth: int = 0, limit: int = 8) -> list[dict[str, Any]]:
    if depth > limit:
        return []
    matches: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("options"), list):
            matches.append(value)
        for item in value.values():
            matches.extend(_iter_variant_mapping_payloads(item, depth=depth + 1, limit=limit))
    elif isinstance(value, list):
        for item in value[:25]:
            matches.extend(_iter_variant_mapping_payloads(item, depth=depth + 1, limit=limit))
    return matches

def _state_variant_targets(
    js_state_objects: dict[str, Any] | None,
    *,
    page_url: str,
) -> tuple[dict[str, dict[str, dict[str, object]]], dict[tuple[tuple[str, str], ...], dict[str, object]]]:
    axis_targets: dict[str, dict[str, dict[str, object]]] = {}
    combo_targets: dict[tuple[tuple[str, str], ...], dict[str, object]] = {}
    if not isinstance(js_state_objects, dict):
        return axis_targets, combo_targets
    mapping_row_id_keys = ("productId", "product_id", "variantId", "variant_id", "sku", "id")
    url_keys = ("url", "href", "productUrl", "product_url", "targetUrl", "target_url")
    for payload in _iter_variant_mapping_payloads(js_state_objects):
        raw_options = payload.get("options")
        if not isinstance(raw_options, list):
            continue
        option_definitions: list[dict[str, object]] = []
        for option in raw_options:
            if not isinstance(option, dict):
                continue
            axis_field = text_or_none(option.get("id") or option.get("key") or option.get("name"))
            axis_key = normalized_variant_axis_key(option.get("label") or axis_field)
            option_list = option.get("optionList") if isinstance(option.get("optionList"), list) else None
            if not axis_field or not axis_key or not option_list:
                continue
            value_by_id: dict[str, str] = {}
            for item in option_list:
                if not isinstance(item, dict):
                    continue
                option_id = text_or_none(item.get("id") or item.get("value"))
                option_value = text_or_none(item.get("title") or item.get("label") or item.get("value"))
                if option_id and option_value and not _variant_option_value_is_noise(option_value):
                    value_by_id[option_id] = option_value
            if value_by_id:
                option_definitions.append(
                    {
                        "axis_field": axis_field,
                        "axis_key": axis_key,
                        "value_by_id": value_by_id,
                    }
                )
        if not option_definitions:
            continue
        mapping_lists = [
            item
            for item in payload.values()
            if isinstance(item, list) and item and all(isinstance(row, dict) for row in item)
        ]
        for mapping_rows in mapping_lists:
            for mapping_row in mapping_rows:
                option_values: dict[str, str] = {}
                for option_definition in option_definitions:
                    axis_field = str(option_definition["axis_field"])
                    axis_key = str(option_definition["axis_key"])
                    mapping_value_by_id = _object_dict(option_definition.get("value_by_id"))
                    option_id = text_or_none(mapping_row.get(axis_field))
                    mapped_option_value = mapping_value_by_id.get(option_id or "")
                    if mapped_option_value:
                        option_values[axis_key] = str(mapped_option_value)
                if not option_values:
                    continue
                row_metadata: dict[str, object] = {}
                explicit_url = next(
                    (
                        text_or_none(mapping_row.get(key))
                        for key in url_keys
                        if text_or_none(mapping_row.get(key))
                    ),
                    None,
                )
                if explicit_url:
                    from app.services.field_value_core import absolute_url

                    row_metadata["url"] = absolute_url(page_url, explicit_url)
                for key in mapping_row_id_keys:
                    raw_value = text_or_none(mapping_row.get(key))
                    if not raw_value:
                        continue
                    row_metadata.setdefault("variant_id", raw_value)
                    if "url" not in row_metadata:
                        inferred_url = _variant_query_url(
                            page_url,
                            query_key=key,
                            query_value=raw_value,
                        )
                        if inferred_url:
                            row_metadata["url"] = inferred_url
                    break
                if not row_metadata:
                    continue
                if len(option_values) == 1:
                    axis_key, option_value = next(iter(option_values.items()))
                    axis_targets.setdefault(axis_key, {}).setdefault(option_value, {}).update(row_metadata)
                combo_targets[tuple(sorted(option_values.items()))] = row_metadata
    return axis_targets, combo_targets

def _extract_variants_from_dom(
    soup: BeautifulSoup,
    *,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> dict[str, object]:
    option_groups: list[dict[str, object]] = []
    for select in iter_variant_select_groups(soup):
        raw_option_values = [
            clean_text(option.get_text(" ", strip=True))
            for option in select.find_all("option")
            if clean_text(option.get_text(" ", strip=True))
        ]
        cleaned_name = (
            resolve_variant_group_name(select)
            or infer_variant_group_name_from_values(raw_option_values)
        )
        inferred_name = infer_variant_group_name_from_values(raw_option_values)
        if inferred_name and normalized_variant_axis_key(cleaned_name) != inferred_name:
            cleaned_name = inferred_name
        if not cleaned_name:
            continue
        option_entries: list[dict[str, object]] = []
        axis_key = normalized_variant_axis_key(cleaned_name)
        select_options = list(select.find_all("option"))
        for option_index, option in enumerate(select_options):
            cleaned_value = text_or_none(
                coerce_field_value(
                    axis_key if axis_key in {"color", "size"} else "size",
                    option.get_text(" ", strip=True),
                    page_url,
                )
            ) or clean_text(option.get_text(" ", strip=True))
            cleaned_value = _strip_variant_option_value_suffix_noise(cleaned_value)
            raw_value_attr = text_or_none(option.get("value"))
            if (
                not cleaned_value
                or _variant_option_value_is_noise(cleaned_value)
                or (raw_value_attr is not None and raw_value_attr.lower() in {"select", "choose"})
            ):
                continue
            entry: dict[str, object] = {"value": cleaned_value}
            if _node_attr_is_truthy(option, "selected", "aria-selected"):
                entry["selected"] = True
            variant_url = _variant_option_url(
                container=select,
                node=option,
                label_node=None,
                page_url=page_url,
            )
            if variant_url:
                entry["url"] = variant_url
            option_entries.append(entry)
        deduped_values = list(
            dict.fromkeys(
                str(entry["value"])
                for entry in option_entries
                if text_or_none(entry.get("value"))
            )
        )
        if len(deduped_values) >= 2:
            option_groups.append({"name": cleaned_name, "values": deduped_values, "entries": option_entries})

    for container in iter_variant_choice_groups(soup):
        cleaned_name = _resolve_dom_variant_group_name(container)
        if not cleaned_name:
            continue
        option_entries = _collect_variant_choice_entries(container, page_url=page_url)
        deduped_values = [str(entry["value"]) for entry in option_entries if text_or_none(entry.get("value"))]
        inferred_name = infer_variant_group_name_from_values(deduped_values)
        if inferred_name and normalized_variant_axis_key(cleaned_name) != inferred_name:
            cleaned_name = inferred_name
        if len(deduped_values) >= 2:
            option_groups.append(
                {
                    "name": cleaned_name,
                    "values": deduped_values,
                    "entries": option_entries,
                }
            )

    expanded_option_groups: list[dict[str, object]] = []
    for group in option_groups:
        compound_groups = _expand_compound_option_group(group)
        if compound_groups:
            expanded_option_groups.extend(compound_groups)
            continue
        expanded_option_groups.append(group)

    deduped_groups: list[dict[str, object]] = []
    merged_groups: dict[str, dict[str, object]] = {}
    for group in expanded_option_groups:
        values = [clean_text(value) for value in _object_list(group.get("values")) if clean_text(value)]
        if len(values) < 2:
            continue
        name = clean_text(group.get("name"))
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        merged = merged_groups.setdefault(axis_key, {"name": name or axis_key, "values": [], "entries": {}})
        if len(name) > len(str(merged.get("name") or "")):
            merged["name"] = name
        existing_values = _object_list(merged.get("values"))
        merged["values"] = list(dict.fromkeys([*existing_values, *values]))
        merged_entries = _object_dict(merged.setdefault("entries", {}))
        for group_entry in _object_list(group.get("entries")):
            if not isinstance(group_entry, dict):
                continue
            value = clean_text(group_entry.get("value"))
            if not value:
                continue
            existing = _object_dict(merged_entries.get(value, {"value": value}))
            availability = text_or_none(group_entry.get("availability"))
            if availability and existing.get("availability") in (None, "", [], {}):
                existing["availability"] = availability
            if group_entry.get("stock_quantity") not in (None, "", [], {}):
                existing["stock_quantity"] = group_entry.get("stock_quantity")
            if group_entry.get("selected"):
                existing["selected"] = True
            if group_entry.get("url") not in (None, "", [], {}) and existing.get("url") in (None, "", [], {}):
                existing["url"] = group_entry.get("url")
            if group_entry.get("variant_id") not in (None, "", [], {}) and existing.get("variant_id") in (None, "", [], {}):
                existing["variant_id"] = group_entry.get("variant_id")
            merged_entries[value] = existing
    for group in merged_groups.values():
        values = [clean_text(value) for value in _object_list(group.get("values")) if clean_text(value)]
        if len(values) < 2:
            continue
        merged_entries = _object_dict(group.get("entries"))
        deduped_groups.append(
            {
                "name": clean_text(group.get("name")),
                "values": values,
                "entries": list(merged_entries.values()),
            }
        )
        if len(deduped_groups) >= 4:
            break

    if not deduped_groups:
        return {}

    state_axis_targets, state_combo_targets = _state_variant_targets(
        js_state_objects,
        page_url=page_url,
    )
    record: dict[str, object] = {}
    variant_axes: dict[str, list[str]] = {}
    axis_option_metadata: dict[str, dict[str, dict[str, object]]] = {}
    axis_order: list[tuple[str, str, list[str]]] = []
    for group in deduped_groups:
        name = clean_text(group.get("name"))
        values = [str(value) for value in _object_list(group.get("values"))]
        axis_key = normalized_variant_axis_key(name)
        if not axis_key:
            continue
        axis_index = len(axis_order) + 1
        record[f"option{axis_index}_name"] = name
        record[f"option{axis_index}_values"] = values
        variant_axes[axis_key] = values
        axis_option_metadata[axis_key] = {
            clean_text(entry.get("value")): {
                key: entry.get(key)
                for key in ("availability", "selected", "stock_quantity", "url", "variant_id")
                if entry.get(key) not in (None, "", [], {})
            }
            for entry in _object_list(group.get("entries"))
            if isinstance(entry, dict)
            if clean_text(entry.get("value"))
        }
        for option_value, state_metadata in dict(state_axis_targets.get(axis_key) or {}).items():
            merged_metadata = axis_option_metadata[axis_key].setdefault(option_value, {})
            for key in ("url", "variant_id"):
                if state_metadata.get(key) not in (None, "", [], {}) and merged_metadata.get(key) in (None, "", [], {}):
                    merged_metadata[key] = state_metadata[key]
        axis_order.append((axis_key, name, values))
        if axis_key == "size" and not record.get("available_sizes"):
            record["available_sizes"] = values
    if not variant_axes:
        return {}

    variants: list[dict[str, object]] = []
    axis_names = [axis_key for axis_key, _label, _values in axis_order]
    axis_value_lists = [values for _axis_key, _label, values in axis_order]
    for combo in product(*axis_value_lists):
        option_values = {
            axis_name: value
            for axis_name, value in zip(axis_names, combo, strict=False)
            if clean_text(value)
        }
        if not option_values:
            continue
        variant: dict[str, object] = {
            "option_values": option_values,
        }
        for axis_name, value in option_values.items():
            variant[axis_name] = value
        combo_metadata = state_combo_targets.get(tuple(sorted(option_values.items())), {})
        for key in ("url", "variant_id"):
            if combo_metadata.get(key) not in (None, "", [], {}):
                variant[key] = combo_metadata[key]
        if len(axis_names) == 1:
            axis_key = axis_names[0]
            option_metadata = axis_option_metadata.get(axis_key, {}).get(str(combo[0]), {})
            availability = text_or_none(option_metadata.get("availability"))
            if availability:
                variant["availability"] = availability
            if option_metadata.get("stock_quantity") not in (None, "", [], {}):
                variant["stock_quantity"] = option_metadata.get("stock_quantity")
            for key in ("url", "variant_id"):
                if option_metadata.get(key) not in (None, "", [], {}):
                    variant[key] = option_metadata.get(key)
        variants.append(variant)

    selectable_axes, single_value_attributes = split_variant_axes(
        variant_axes,
        always_selectable_axes=frozenset({"size"}),
    )
    resolved_variants = resolve_variants(selectable_axes or variant_axes, variants) if variants else []
    selected_variant = select_variant(resolved_variants, page_url=page_url)
    selected_option_values = {
        axis_name: option_value
        for axis_name, option_value in (
            (
                axis_name,
                next(
                    (
                        value
                        for value, metadata in axis_option_metadata.get(axis_name, {}).items()
                        if metadata.get("selected")
                    ),
                    None,
                ),
            )
            for axis_name in axis_names
        )
        if option_value
    }
    if selected_option_values:
        selected_variant = next(
            (
                variant
                for variant in resolved_variants
                if variant.get("option_values") == selected_option_values
            ),
            selected_variant,
        )
    for axis_name, value in single_value_attributes.items():
        record.setdefault(axis_name, value)
    if selectable_axes:
        record["variant_axes"] = selectable_axes
    elif variant_axes:
        record["variant_axes"] = variant_axes
    if resolved_variants:
        record["variants"] = resolved_variants
        record["variant_count"] = len(resolved_variants)
        if selected_variant:
            record["selected_variant"] = selected_variant
            if record.get("availability") in (None, "", [], {}):
                selected_availability = text_or_none(selected_variant.get("availability"))
                if selected_availability:
                    record["availability"] = selected_availability
    return record

def _promote_detail_title(
    record: dict[str, Any],
    *,
    page_url: str,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
) -> tuple[str, str] | None:
    title = text_or_none(record.get("title"))
    if not title or not _title_needs_promotion(title, page_url=page_url):
        return None
    values = list(candidates.get("title", []))
    sources = list(candidate_sources.get("title", []))
    ranked_candidates = sorted(
        (
            (
                _field_source_rank("ecommerce_detail", "title", sources[index]),
                index,
                text_or_none(values[index]),
                sources[index],
            )
            for index in range(min(len(values), len(sources)))
            if text_or_none(values[index])
        ),
        key=lambda row: (row[0], row[1]),
    )
    current_rank = min(
        (
            _field_source_rank("ecommerce_detail", "title", source)
            for source, value in zip(sources, values, strict=False)
            if text_or_none(value) == title
        ),
        default=_field_source_rank("ecommerce_detail", "title", "dom_h1"),
    )
    replacement = next(
        (
            (candidate, source)
            for rank, _, candidate, source in ranked_candidates
            if candidate
            and candidate != title
            and not is_title_noise(candidate)
            and (
                rank < current_rank
                or (rank == current_rank and len(candidate) > len(title))
            )
        ),
        None,
    )
    if replacement:
        record["title"] = replacement[0]
        return replacement
    return None

def _title_needs_promotion(title: str, *, page_url: str) -> bool:
    normalized_title = str(title or "").strip().lower()
    host = str(urlparse(page_url).hostname or "").strip().lower()
    if not normalized_title:
        return False
    if is_title_noise(normalized_title):
        return True
    if any(normalized_title.startswith(prefix) for prefix in TITLE_PROMOTION_PREFIXES):
        return True
    if TITLE_PROMOTION_SEPARATOR in normalized_title:
        return True
    if any(substring in normalized_title for substring in TITLE_PROMOTION_SUBSTRINGS):
        return True
    if not host:
        return False
    host_label = host.removeprefix("www.").split(".", 1)[0]
    compact_title = re.sub(r"[^a-z0-9]+", "", normalized_title)
    compact_host = re.sub(r"[^a-z0-9]+", "", host_label)
    return compact_title == compact_host

def _missing_requested_fields(
    record: dict[str, Any],
    requested_fields: list[str] | None,
) -> set[str]:
    missing: set[str] = set()
    for field_name in list(requested_fields or []):
        normalized = exact_requested_field_key(str(field_name or ""))
        if normalized and record.get(normalized) in (None, "", [], {}):
            missing.add(normalized)
    return missing

def _requires_dom_completion(
    *,
    record: dict[str, Any],
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None,
    soup: BeautifulSoup,
) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    requested_missing_fields = _missing_requested_fields(record, requested_fields)
    if (
        normalized_surface == "ecommerce_detail"
        and record.get("variant_axes") in (None, "", [], {})
        and variant_dom_cues_present(soup)
    ):
        return True
    if normalized_surface == "ecommerce_detail" and variant_dom_cues_present(soup):
        if any(
            record.get(field_name) in (None, "", [], {})
            for field_name in ("variant_axes", "variants", "selected_variant")
        ):
            return True
    extractability = requested_content_extractability(
        soup,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
    )
    extractable_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("extractable_fields"))
        if str(field_name).strip()
    }
    high_value_fields = set(DOM_HIGH_VALUE_FIELDS.get(normalized_surface) or ())
    advertised_high_value_fields = extractable_fields & high_value_fields
    missing_high_value_fields = {
        field_name
        for field_name in advertised_high_value_fields
        if record.get(field_name) in (None, "", [], {})
    }
    missing_high_value_fields.update(
        {
            field_name
            for field_name in high_value_fields
            if field_name in requested_missing_fields
        }
    )
    if extractable_fields & requested_missing_fields:
        return True
    if missing_high_value_fields or requested_missing_fields & high_value_fields:
        return True
    optional_cue_fields = {
        field_name
        for field_name in set(DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ())
        if record.get(field_name) in (None, "", [], {})
    }
    dom_pattern_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("dom_pattern_fields"))
        if str(field_name).strip()
    }
    if optional_cue_fields & dom_pattern_fields:
        return True
    selector_backed_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("selector_backed_fields"))
        if str(field_name).strip()
    }
    return bool(requested_missing_fields & selector_backed_fields)

def _primary_dom_context(
    context,
    *,
    page_url: str,
) -> tuple[LexborHTMLParser, BeautifulSoup]:
    primary_selector = "main, article, h1, [itemprop='name']"
    cleaned_parser = context.dom_parser
    cleaned_soup = context.soup
    if cleaned_parser.css_first(primary_selector) or cleaned_soup.select_one(primary_selector):
        return cleaned_parser, cleaned_soup
    original_parser = LexborHTMLParser(context.original_html)
    original_soup = BeautifulSoup(context.original_html, "html.parser")
    if not (
        original_parser.css_first(primary_selector)
        or original_soup.select_one(primary_selector)
    ):
        return cleaned_parser, cleaned_soup
    logger.debug("Using original DOM after cleaned DOM lost primary content for %s", page_url)
    return original_parser, original_soup

def build_detail_record(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    *,
    requested_page_url: str | None = None,
    adapter_records: list[dict[str, Any]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> dict[str, Any]:
    context = prepare_extraction_context(html)
    dom_parser, soup = _primary_dom_context(
        context,
        page_url=page_url,
    )
    alias_lookup = surface_alias_lookup(surface, requested_fields)
    candidates: dict[str, list[object]] = {}
    candidate_sources: dict[str, list[str]] = {}
    field_sources: dict[str, list[str]] = {}
    selector_trace_candidates: dict[str, list[dict[str, object]]] = {}
    fields = surface_fields(surface, requested_fields)
    selector_self_heal = _selector_self_heal_config(extraction_runtime_snapshot)
    state = DetailTierState(page_url=page_url, requested_page_url=requested_page_url, surface=surface, requested_fields=requested_fields, fields=fields, candidates=candidates, candidate_sources=candidate_sources, field_sources=field_sources, selector_trace_candidates=selector_trace_candidates, extraction_runtime_snapshot=extraction_runtime_snapshot, completed_tiers=[])
    js_state_objects = harvest_js_state_objects(None, context.cleaned_html)
    js_state_record = map_js_state_to_fields(
        js_state_objects,
        surface=surface,
        page_url=page_url,
    )
    if surface == "ecommerce_detail" and is_title_noise(js_state_record.get("title")):
        js_state_record = dict(js_state_record)
        js_state_record.pop("title", None)

    collect_authoritative_tier(
        state,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        collect_record_candidates=_collect_record_candidates,
        map_network_payloads_to_fields=map_network_payloads_to_fields,
    )
    record = materialize_detail_tier(state, tier_name="authoritative", materialize_record=_materialize_record)

    collect_structured_data_tier(
        state,
        context=context,
        alias_lookup=alias_lookup,
        collect_structured_source_payloads=collect_structured_source_payloads,
        collect_structured_payload_candidates=_collect_structured_payload_candidates,
    )
    record = materialize_detail_tier(state, tier_name="structured_data", materialize_record=_materialize_record)
    collect_js_state_tier(
        state,
        js_state_record=js_state_record,
        collect_record_candidates=_collect_record_candidates,
    )
    record = materialize_detail_tier(state, tier_name="js_state", materialize_record=_materialize_record)
    if (
        _coerce_float(_object_dict(record.get("_confidence")).get("score"))
        >= _coerce_float(selector_self_heal.get("threshold"))
        and not _requires_dom_completion(
            record=record,
            surface=surface,
            requested_fields=requested_fields,
            selector_rules=selector_rules,
            soup=soup,
        )
    ):
        _backfill_detail_price_from_html(record, html=html)
        _backfill_variants_from_dom_if_missing(
            record,
            soup=soup,
            page_url=page_url,
            js_state_objects=js_state_objects,
        )
        drop_low_signal_zero_detail_price(record)
        record["_confidence"] = score_record_confidence(
            record,
            surface=surface,
            requested_fields=requested_fields,
        )
        record["_extraction_tiers"]["early_exit"] = "js_state"
        return record

    collect_dom_tier(
        state,
        dom_parser=dom_parser,
        soup=soup,
        selector_rules=selector_rules,
        apply_dom_fallbacks=_apply_dom_fallbacks,
        extract_variants_from_dom=(
            lambda dom_soup, *, page_url: _extract_variants_from_dom(
                dom_soup,
                page_url=page_url,
                js_state_objects=js_state_objects,
            )
        ),
        should_collect_dom_variants=_should_collect_dom_variants,
        add_sourced_candidate=_add_sourced_candidate,
    )
    record = materialize_detail_tier(state, tier_name="dom", materialize_record=_materialize_record)
    if surface == "ecommerce_detail" and _title_needs_promotion(
        text_or_none(record.get("title")) or "",
        page_url=page_url,
    ):
        preferred_title = text_or_none(js_state_record.get("title"))
        if preferred_title:
            record["title"] = preferred_title
        else:
            fallback_title = _detail_title_from_url(page_url)
            if fallback_title:
                record["title"] = fallback_title
                title_sources = record.setdefault("_field_sources", {}).setdefault("title", [])
                if "url_slug" not in title_sources:
                    title_sources.append("url_slug")
    if surface == "ecommerce_detail" and not text_or_none(record.get("title")):
        fallback_title = _detail_title_from_url(page_url)
        if fallback_title:
            record["title"] = fallback_title
            title_sources = record.setdefault("_field_sources", {}).setdefault("title", [])
            if "url_slug" not in title_sources:
                title_sources.append("url_slug")
    record["_confidence"] = score_record_confidence(
        record,
        surface=surface,
        requested_fields=requested_fields,
    )
    record["_extraction_tiers"]["early_exit"] = None
    return record


def detail_record_rejection_reason(
    record: dict[str, Any],
    *,
    page_url: str,
    requested_page_url: str | None = None,
) -> str | None:
    if _detail_redirect_identity_is_mismatched(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    ):
        return "detail_identity_mismatch"
    if _looks_like_site_shell_record(record, page_url=page_url):
        return "non_detail_seed"
    return None


def infer_detail_failure_reason(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    *,
    requested_page_url: str | None = None,
    adapter_records: list[dict[str, Any]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> str | None:
    if "detail" not in str(surface or "").strip().lower():
        return None
    record = build_detail_record(
        html,
        page_url,
        surface,
        requested_fields,
        requested_page_url=requested_page_url,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )
    return detail_record_rejection_reason(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    )

def extract_detail_records(
    html: str,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None = None,
    *,
    requested_page_url: str | None = None,
    adapter_records: list[dict[str, Any]] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
) -> list[dict[str, Any]]:
    record = build_detail_record(
        html,
        page_url,
        surface,
        requested_fields,
        requested_page_url=requested_page_url,
        adapter_records=adapter_records,
        network_payloads=network_payloads,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=extraction_runtime_snapshot,
    )
    if surface == "ecommerce_detail":
        _normalize_variant_record(record)
        _backfill_detail_price_from_html(record, html=html)
    if surface == "ecommerce_detail" and _looks_like_site_shell_record(
        record,
        page_url=page_url,
    ):
        return []
    if surface == "ecommerce_detail" and _detail_redirect_identity_is_mismatched(
        record,
        page_url=page_url,
        requested_page_url=requested_page_url,
    ):
        return []
    if record_score(record) <= 0:
        return []
    return [record]

def _backfill_detail_price_from_html(record: dict[str, Any], *, html: str) -> None:
    selected_variant = record.get("selected_variant")
    needs_price = record.get("price") in (None, "", [], {}) or (
        isinstance(selected_variant, dict)
        and selected_variant.get("price") in (None, "", [], {})
    )
    if not needs_price or not str(html or "").strip():
        return
    soup = BeautifulSoup(str(html or ""), "html.parser")
    currency = text_or_none(record.get("currency")) or _detail_currency_from_html(soup)
    if currency and record.get("currency") in (None, "", [], {}):
        record["currency"] = currency
        _append_record_field_source(record, "currency", "dom_text")
    price = _detail_price_from_html(soup, currency=currency)
    if price in (None, "", [], {}):
        return
    if record.get("price") in (None, "", [], {}):
        record["price"] = price
        _append_record_field_source(record, "price", "dom_text")
    if isinstance(selected_variant, dict) and selected_variant.get("price") in (None, "", [], {}):
        selected_variant["price"] = price
        if currency and selected_variant.get("currency") in (None, "", [], {}):
            selected_variant["currency"] = currency
    original_price = _detail_original_price_from_html(soup, currency=currency)
    if original_price not in (None, "", [], {}) and record.get("original_price") in (
        None,
        "",
        [],
        {},
    ):
        record["original_price"] = original_price
        _append_record_field_source(record, "original_price", "dom_text")
    if (
        isinstance(selected_variant, dict)
        and original_price not in (None, "", [], {})
        and selected_variant.get("original_price") in (None, "", [], {})
    ):
        selected_variant["original_price"] = original_price

def _backfill_variants_from_dom_if_missing(
    record: dict[str, Any],
    *,
    soup: BeautifulSoup,
    page_url: str,
    js_state_objects: dict[str, Any] | None = None,
) -> None:
    if record.get("variant_axes") not in (None, "", [], {}):
        return
    if not variant_dom_cues_present(soup):
        return
    dom_variants = _extract_variants_from_dom(
        soup,
        page_url=page_url,
        js_state_objects=js_state_objects,
    )
    for field_name in ("variant_axes", "variants", "variant_count", "selected_variant"):
        if record.get(field_name) in (None, "", [], {}) and dom_variants.get(field_name) not in (
            None,
            "",
            [],
            {},
        ):
            record[field_name] = dom_variants[field_name]
    currency = text_or_none(record.get("currency"))
    selected_variant = record.get("selected_variant")
    if not currency and isinstance(selected_variant, dict):
        currency = text_or_none(selected_variant.get("currency"))
    price = text_or_none(record.get("price"))
    if not price and isinstance(selected_variant, dict):
        price = text_or_none(selected_variant.get("price"))
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    if any(
        isinstance(variant, dict) and variant.get("price") not in (None, "", [], {})
        for variant in variants
    ):
        return
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if price:
            variant["price"] = price
        if currency and variant.get("currency") in (None, "", [], {}):
            variant["currency"] = currency

def _detail_price_from_html(soup: BeautifulSoup, *, currency: str | None) -> str | None:
    meta_selectors = (
        "meta[property='product:price:amount']",
        "meta[itemprop='price']",
        "meta[name='price']",
        "[itemprop='price']",
    )
    for selector in meta_selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        raw_value = node.get("content") if hasattr(node, "get") else None
        if raw_value in (None, "", [], {}):
            raw_value = node.get_text(" ", strip=True)
        normalized = _normalize_detail_price_candidate(raw_value, currency=currency)
        if normalized:
            return normalized
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = str(script.string or script.get_text() or "").strip()
        if not script_text or '"price"' not in script_text.lower():
            continue
        if re.search(r'"@type"\s*:\s*"(?:Product|ProductGroup|Offer)"', script_text) is None:
            continue
        match = re.search(r'"price"\s*:\s*"?(?P<price>\d+(?:\.\d+)?)', script_text)
        if match is None:
            continue
        normalized = _normalize_detail_price_candidate(
            match.group("price"),
            currency=currency,
        )
        if normalized:
            return normalized
    visible_price = _detail_price_from_selector_text(
        soup,
        selectors=DETAIL_CURRENT_PRICE_SELECTORS,
        currency=currency,
    )
    if visible_price:
        return visible_price
    return None

def _detail_original_price_from_html(soup: BeautifulSoup, *, currency: str | None) -> str | None:
    return _detail_price_from_selector_text(
        soup,
        selectors=DETAIL_ORIGINAL_PRICE_SELECTORS,
        currency=currency,
    )

def _detail_price_from_selector_text(
    soup: BeautifulSoup,
    *,
    selectors: tuple[str, ...],
    currency: str | None,
) -> str | None:
    for selector in selectors:
        for node in soup.select(selector):
            raw_value = node.get("aria-label") if hasattr(node, "get") else None
            if raw_value in (None, "", [], {}):
                raw_value = node.get_text(" ", strip=True)
            normalized = _normalize_detail_price_candidate(raw_value, currency=currency)
            if normalized:
                return normalized
    return None

def _detail_currency_from_html(soup: BeautifulSoup) -> str | None:
    currency_selectors = (
        "meta[property='product:price:currency']",
        "meta[itemprop='priceCurrency']",
    )
    for selector in currency_selectors:
        node = soup.select_one(selector)
        if node is None:
            continue
        currency = text_or_none(node.get("content") if hasattr(node, "get") else None)
        if currency:
            return currency
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        script_text = str(script.string or script.get_text() or "").strip()
        if not script_text:
            continue
        match = re.search(r'"priceCurrency"\s*:\s*"(?P<currency>[A-Z]{3})"', script_text)
        if match is not None:
            return text_or_none(match.group("currency"))
    return None

def _normalize_detail_price_candidate(
    value: object,
    *,
    currency: str | None,
) -> str | None:
    text = text_or_none(value)
    if not text:
        return None
    digits_only = re.sub(r"\D+", "", text)
    if currency and re.fullmatch(r"\d+(?:\.\d+)?", text) and "." not in text and len(digits_only) <= 3:
        return text
    candidate_text = text
    return normalize_decimal_price(
        candidate_text,
        interpret_integral_as_cents=(
            "." not in text
            and len(digits_only) >= 4
            and currency in {"AUD", "CAD", "EUR", "GBP", "NZD", "USD"}
        ),
    )
