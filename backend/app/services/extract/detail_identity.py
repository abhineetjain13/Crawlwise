from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlparse

from app.services.config.extraction_rules import (
    CANDIDATE_PLACEHOLDER_VALUES,
    DETAIL_COLLECTION_PATH_TOKENS,
    DETAIL_NON_PAGE_FILE_EXTENSIONS,
    DETAIL_PRODUCT_PATH_TOKENS,
    DETAIL_SEARCH_QUERY_KEYS,
    DETAIL_UTILITY_PATH_TOKENS,
)
from app.services.field_value_core import (
    PRODUCT_URL_HINTS,
    clean_text,
    is_title_noise,
    same_site,
    text_or_none,
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
_DETAIL_URL_PLACEHOLDER_SEGMENTS = frozenset(
    {
        str(value).strip().lower()
        for value in tuple(CANDIDATE_PLACEHOLDER_VALUES or ())
        if str(value).strip()
    }
)


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


def _detail_title_from_url(page_url: str) -> str | None:
    path_segments = _detail_url_path_segments(page_url)
    if not path_segments:
        return None
    for index in range(len(path_segments) - 1, -1, -1):
        segment = path_segments[index]
        terminal = re.sub(r"\.(html?|htm)$", "", segment, flags=re.I)
        if not terminal or terminal.isdigit():
            continue
        if _detail_segment_looks_like_identity_code(terminal):
            parent_segment = (
                str(path_segments[index - 1]).strip().lower()
                if index > 0
                else ""
            )
            if parent_segment in {"product", "products", "item", "items"}:
                return None
            continue
        if re.fullmatch(r"[a-f0-9]{8,}(?:-[a-f0-9]{4,}){2,}", terminal, re.I):
            continue
        if terminal in {
            "p",
            "dp",
            "product",
            "products",
            "job",
            "jobs",
            "release",
            "color",
            "colors",
            "size",
            "sizes",
            "width",
            "widths",
            "style",
            "styles",
            "variant",
            "variants",
        }:
            continue
        title = clean_text(re.sub(r"[-_]+", " ", terminal))
        if title and not is_title_noise(title):
            return title
    return None


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
    record: dict[str, object],
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    record_field_codes = _detail_identity_codes_from_record_fields(record)
    if detail_identity_codes_match(requested_codes, record_field_codes):
        return True
    record_url_codes = _detail_identity_codes_from_url(record.get("url"))
    requested_title = _detail_title_from_url(requested_page_url)
    requested_tokens = _detail_identity_tokens(requested_title)
    candidate_tokens = _detail_identity_tokens(record.get("title"))
    if not candidate_tokens:
        candidate_tokens = _detail_identity_tokens(record.get("description"))
    title_matches = False
    if requested_tokens and candidate_tokens:
        overlap = requested_tokens & candidate_tokens
        if len(requested_tokens) == 1:
            title_matches = bool(overlap)
        else:
            title_matches = len(overlap) >= min(2, len(requested_tokens))
    if not title_matches and requested_tokens:
        supplemental_tokens = _detail_identity_record_tokens(record)
        if supplemental_tokens:
            overlap = requested_tokens & supplemental_tokens
            if len(requested_tokens) == 1:
                title_matches = bool(overlap)
            else:
                title_matches = len(overlap) >= min(2, len(requested_tokens))
    if title_matches:
        return True
    return bool(
        requested_codes
        and not requested_tokens
        and detail_identity_codes_match(requested_codes, record_url_codes)
    )


def _detail_identity_record_tokens(record: dict[str, object]) -> set[str]:
    tokens: set[str] = set()
    for field_name in ("title", "brand", "color", "size", "description"):
        tokens.update(_detail_identity_tokens(record.get(field_name)))
    return tokens


def _detail_url_matches_requested_identity(
    candidate_url: str,
    *,
    requested_page_url: str,
) -> bool:
    requested_codes = _detail_identity_codes_from_url(requested_page_url)
    candidate_codes = _detail_identity_codes_from_url(candidate_url)
    if detail_identity_codes_match(requested_codes, candidate_codes):
        return True
    requested_title = _detail_title_from_url(requested_page_url)
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


def _same_url_title_only_shell_like(
    record: dict[str, object],
    *,
    page_url: str,
) -> bool:
    title = clean_text(record.get("title"))
    requested_title = clean_text(_detail_title_from_url(page_url))
    if not title or not requested_title or title.casefold() != requested_title.casefold():
        return False
    if any(
        record.get(field_name) not in (None, "", [], {})
        for field_name in (
            "image_url",
            "additional_images",
            "description",
            "product_details",
            "specifications",
            "features",
            "price",
            "brand",
            "availability",
            "variant_axes",
            "variants",
            "selected_variant",
        )
    ):
        return False
    if _detail_identity_codes_from_url(page_url):
        return False
    return any(
        token.endswith("s")
        for token in re.split(r"[^a-z0-9]+", title.lower())
        if len(token) >= 3
    )


def _detail_identity_tokens(value: object) -> set[str]:
    cleaned = clean_text(value).lower()
    return {
        token
        for token in re.split(r"[^a-z0-9]+", cleaned)
        if len(token) >= 3 and token not in _DETAIL_IDENTITY_STOPWORDS
    }


def _semantic_detail_identity_tokens(value: object) -> set[str]:
    return {
        token
        for token in _detail_identity_tokens(value)
        if re.search(r"[a-z]", token) and not re.search(r"\d", token)
    }


def _detail_identity_codes_from_url(url: object) -> set[str]:
    text = text_or_none(url)
    if not text:
        return set()
    parsed = urlparse(text)
    codes: set[str] = set()
    for segment in _detail_url_path_segments(text):
        terminal = re.sub(r"\.(html?|htm)$", "", segment, flags=re.I)
        code_like_terminal = _detail_segment_code(terminal)
        if code_like_terminal:
            codes.add(code_like_terminal)
        for match in re.findall(r"[A-Za-z0-9]{8,}", terminal):
            normalized = _normalized_detail_identity_code(match)
            if normalized:
                codes.add(normalized)
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        match = re.match(
            r"dwvar_([A-Za-z0-9][A-Za-z0-9_-]{6,}[A-Za-z0-9])_",
            str(key or ""),
            flags=re.I,
        )
        if match is None:
            continue
        normalized = _detail_segment_code(match.group(1))
        if normalized:
            codes.add(normalized)
    return codes


def _detail_identity_codes_from_record_fields(record: dict[str, object]) -> set[str]:
    codes: set[str] = set()
    for field_name in ("sku", "product_id", "variant_id", "part_number"):
        normalized = _normalized_detail_identity_code(record.get(field_name))
        if normalized:
            codes.add(normalized)
    return codes


def _detail_segment_looks_like_identity_code(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if re.fullmatch(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+){0,2}", text) is None:
        return False
    return _normalized_detail_identity_code(text) is not None


def _detail_segment_code(value: object) -> str | None:
    text = str(value or "").strip()
    if not _detail_segment_looks_like_identity_code(text):
        return None
    return _normalized_detail_identity_code(text)


def _normalized_detail_identity_code(value: object) -> str | None:
    text = re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()
    if len(text) < 8:
        return None
    if not re.search(r"[A-Z]", text) or not re.search(r"\d", text):
        return None
    return text


def detail_identity_codes_match(
    expected_codes: set[str],
    candidate_codes: set[str],
) -> bool:
    if not expected_codes or not candidate_codes:
        return False
    return not expected_codes.isdisjoint(candidate_codes)


def _detail_redirect_identity_is_mismatched(
    record: dict[str, object],
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
    if requested_codes and record_field_codes and not detail_identity_codes_match(
        requested_codes,
        record_field_codes,
    ):
        candidate_url = text_or_none(record.get("url")) or current
        if not (
            candidate_url
            and _detail_url_matches_requested_identity(
                candidate_url,
                requested_page_url=requested,
            )
            and _record_matches_requested_detail_identity(
                record,
                requested_page_url=requested,
            )
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
    if current and requested == current:
        requested_title = _detail_title_from_url(requested)
        has_product_like_signal = any(
            record.get(field_name) not in (None, "", [], {})
            for field_name in (
                "image_url",
                "additional_images",
                "price",
                "brand",
                "description",
                "availability",
                "category",
                "product_details",
                "selected_variant",
                "variants",
            )
        )
        if (
            requested_title
            and has_product_like_signal
            and not _record_matches_requested_detail_identity(
                record,
                requested_page_url=requested,
            )
        ):
            return True
        if requested_title and _same_url_title_only_shell_like(record, page_url=requested):
            return True
        return False
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
