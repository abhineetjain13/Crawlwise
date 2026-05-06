from __future__ import annotations

import logging
import re
from urllib.parse import parse_qsl, urlparse

from app.services.config.extraction_rules import (
    CANDIDATE_PLACEHOLDER_VALUES,
    DETAIL_COLLECTION_PATH_TOKENS,
    DETAIL_GENERIC_TERMINAL_TOKENS,
    DETAIL_IDENTITY_CODE_MIN_LENGTH,
    DETAIL_IDENTITY_STOPWORDS,
    DETAIL_NON_PAGE_FILE_EXTENSIONS,
    DETAIL_PRODUCT_PATH_TOKENS,
    DETAIL_SEARCH_QUERY_KEYS,
    DETAIL_UTILITY_PATH_TOKENS,
    JOB_LISTING_DETAIL_ROOT_MARKERS,
    JOB_LISTING_DETAIL_PATH_MARKERS,
    LISTING_CATEGORY_PATH_SEGMENTS,
    LISTING_CATEGORY_PATH_PREFIXES,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_NON_LISTING_PATH_TOKENS,
    LISTING_PRODUCT_DETAIL_ID_RE,
    PRODUCT_SLUG_MIN_TERMINAL_TOKENS,
    YEAR_SLUG_PATTERN,
)
from app.services.config.surface_hints import detail_path_hints
from app.services.extract.listing_candidate_ranking import (
    job_listing_url_is_hub as _job_listing_url_is_hub,
    job_listing_url_looks_like_posting as _job_listing_url_looks_like_posting,
)
from app.services.field_value_core import (
    PRODUCT_URL_HINTS,
    clean_text,
    is_title_noise,
    same_site,
    text_or_none,
)

logger = logging.getLogger(__name__)
_DETAIL_URL_PLACEHOLDER_SEGMENTS = frozenset(
    {
        str(value).strip().lower()
        for value in tuple(CANDIDATE_PLACEHOLDER_VALUES or ())
        if str(value).strip()
    }
)
_LISTING_CATEGORY_PATH_SEGMENTS = frozenset(
    {
        str(value).strip().lower()
        for value in tuple(LISTING_CATEGORY_PATH_SEGMENTS or ())
        if str(value).strip()
    }
)


def _path_segment_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[\-\.]+", str(value or "").strip().lower())
        if token
    }


def _listing_url_has_product_detail_identity(url: str) -> bool:
    return LISTING_PRODUCT_DETAIL_ID_RE.search(str(url or "")) is not None


def _listing_url_has_category_path_segment(path: str) -> bool:
    segments = [
        segment.strip().lower()
        for segment in str(path or "").split("/")
        if segment.strip()
    ]
    for segment in segments:
        # Broader split is intentional here, unlike _path_segment_tokens:
        # _LISTING_CATEGORY_PATH_SEGMENTS may be embedded behind "_" or mixed punctuation.
        segment_tokens = {token for token in re.split(r"[^a-z0-9]+", segment) if token}
        if segment in _LISTING_CATEGORY_PATH_SEGMENTS:
            return True
        if _LISTING_CATEGORY_PATH_SEGMENTS.intersection(segment_tokens):
            return True
    return False


def listing_url_is_structural(url: str, page_url: str) -> bool:
    lowered = url.lower()
    if lowered.startswith(("javascript:", "#", "mailto:")):
        return True
    if lowered == page_url.lower():
        return True
    try:
        parsed = urlparse(url)
        page_parsed = urlparse(page_url)
        if parsed.path in ("", "/"):
            return True
        if parsed.path.rstrip("/").lower() == page_parsed.path.rstrip("/").lower():
            return True
        if _listing_url_has_product_detail_identity(lowered):
            return False
        # Sibling-category rejection.
        # When both the listing page and the candidate share a known
        # category path prefix (e.g. both /c/<slug>), the candidate is
        # a navigation link to another category, not a product.
        candidate_path = parsed.path.lower()
        page_path = page_parsed.path.lower()
        if _listing_url_has_category_path_segment(
            page_path
        ) and _listing_url_has_category_path_segment(candidate_path):
            return True
        for prefix in LISTING_CATEGORY_PATH_PREFIXES:
            if page_path.startswith(prefix) and candidate_path.startswith(prefix):
                return True
        raw_segments = [
            segment.strip().lower()
            for segment in parsed.path.split("/")
            if segment.strip()
        ]
        tokenized_segments = [_path_segment_tokens(segment) for segment in raw_segments]
        terminal_tokens = tokenized_segments[-1] if tokenized_segments else set()
        terminal_raw = raw_segments[-1] if raw_segments else ""
        non_listing_tokens = set(LISTING_NON_LISTING_PATH_TOKENS)
        if terminal_tokens & non_listing_tokens or terminal_raw in non_listing_tokens:
            return True
        leading_tokens = tokenized_segments[:-1] if len(tokenized_segments) <= 2 else []
        leading_raw = raw_segments[:-1] if len(raw_segments) <= 2 else []
        terminal_token_list = [
            token for token in re.split(r"[-.]+", terminal_raw) if token
        ]
        # Year-led slugs like 2025-ceo-letter are editorial, not product.
        year_led_terminal = bool(
            terminal_token_list
            and re.fullmatch(YEAR_SLUG_PATTERN, terminal_token_list[0])
        )
        # Use the ordered token list (not the deduped set) so slugs like
        # "blue-blue-widget" are still recognized as product slugs.
        terminal_looks_like_product_slug = (
            len(terminal_token_list) >= PRODUCT_SLUG_MIN_TERMINAL_TOKENS
            and any(re.search(r"[a-z]", token) for token in terminal_token_list)
            and "-" in terminal_raw
            and not year_led_terminal
        )
        if not terminal_looks_like_product_slug and (
            any(tokens & non_listing_tokens for tokens in leading_tokens)
            or any(segment in non_listing_tokens for segment in leading_raw)
        ):
            return True
    except ValueError:
        logger.debug("URL structural check failed for %s", page_url, exc_info=True)
    return False


def listing_detail_like_path(url: str, *, is_job: bool) -> bool:
    lowered = url.lower()
    if is_job:
        return _job_detail_like_path(lowered)
    parsed = urlparse(lowered)
    if _listing_url_has_product_detail_identity(lowered):
        return True
    if _listing_url_has_category_path_segment(parsed.path):
        return False
    segments = [
        segment.strip().lower() for segment in parsed.path.split("/") if segment.strip()
    ]
    if "products" in segments:
        products_index = segments.index("products")
        tail_segments = segments[products_index + 1 :]
        if (
            len(tail_segments) > 2
            and not parsed.query
            and not any(re.search(r"\d", segment) for segment in tail_segments[-2:])
        ):
            return False
    if any(marker in lowered for marker in LISTING_DETAIL_PATH_MARKERS):
        return True
    hints = detail_path_hints("ecommerce_detail")
    return any(marker in lowered for marker in hints)


def _job_detail_like_path(url: str) -> bool:
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return False
    terminal = segments[-1].strip().lower()
    if not terminal or _job_listing_url_is_hub(url):
        return False
    query = parsed.query.lower()
    if any(token in query for token in ("showjob=", "jobid=", "job_id=", "gh_jid=")):
        return True
    if any(marker in parsed.path.lower() for marker in JOB_LISTING_DETAIL_PATH_MARKERS):
        return True
    if _job_listing_url_looks_like_posting(url):
        return True
    if re.match(r"jobs?-\d", terminal):
        return True
    for index, segment in enumerate(segments[:-1]):
        normalized = segment.strip().lower()
        if normalized not in JOB_LISTING_DETAIL_ROOT_MARKERS:
            continue
        next_segment = segments[index + 1].strip().lower()
        if next_segment and not _job_listing_url_is_hub(
            f"https://example.com/{next_segment}/"
        ):
            return True
    return False


def _detail_url_path_segments(url: str) -> list[str]:
    parsed = urlparse(str(url or ""))
    segments = [
        segment for segment in str(parsed.path or "").strip("/").split("/") if segment
    ]
    fragment = str(parsed.fragment or "").strip()
    if fragment:
        fragment_path = fragment.split("?", 1)[0].split("&", 1)[0].strip()
        if "/" in fragment_path:
            segments.extend(
                segment for segment in fragment_path.strip("!/").split("/") if segment
            )
    return segments


def _detail_title_from_url(page_url: str) -> str | None:
    path_segments = _detail_url_path_segments(page_url)
    if not path_segments:
        return None
    generic_terminal_tokens = set(DETAIL_GENERIC_TERMINAL_TOKENS)
    for index in range(len(path_segments) - 1, -1, -1):
        segment = path_segments[index]
        terminal = re.sub(r"\.(html?|htm)$", "", segment, flags=re.I)
        if not terminal or terminal.isdigit():
            continue
        if re.fullmatch(r"[a-z]{2}(?:[_-][a-z]{2})?", terminal, re.I):
            continue
        embedded_codes = [
            normalized
            for match in re.findall(
                rf"[A-Za-z0-9]{{{DETAIL_IDENTITY_CODE_MIN_LENGTH},}}", terminal
            )
            if (normalized := _normalized_detail_identity_code(match))
        ]
        if embedded_codes:
            alpha_chunks = [
                chunk.lower() for chunk in re.findall(r"[A-Za-z]+", terminal)
            ]
            if not alpha_chunks or all(
                set(_path_segment_tokens(chunk)) <= generic_terminal_tokens
                for chunk in alpha_chunks
            ):
                continue
        if _detail_segment_looks_like_identity_code(terminal):
            parent_segment = (
                str(path_segments[index - 1]).strip().lower() if index > 0 else ""
            )
            if parent_segment in {"product", "products", "item", "items"}:
                return None
            continue
        if re.fullmatch(r"[a-f0-9]{8,}(?:-[a-f0-9]{4,}){2,}", terminal, re.I):
            continue
        terminal_tokens = _path_segment_tokens(terminal)
        if terminal in generic_terminal_tokens or (
            terminal_tokens and terminal_tokens <= generic_terminal_tokens
        ):
            continue
        title = clean_text(re.sub(r"[-_]+", " ", terminal))
        if title and not is_title_noise(title):
            return title
    return None


def _detail_url_candidate_is_low_signal(
    candidate_url: object, *, page_url: str
) -> bool:
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
    if any(
        candidate_path.lower().endswith(ext) for ext in DETAIL_NON_PAGE_FILE_EXTENSIONS
    ):
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
    if any(
        token in terminal for token in ("category", "collections", "search", "sale")
    ):
        return False
    return any(separator in terminal for separator in ("-", "_"))


def _detail_url_is_utility(url: str) -> bool:
    path_tokens = _detail_url_path_tokens(url)
    if any(token in path_tokens for token in DETAIL_PRODUCT_PATH_TOKENS):
        return False
    if any(token in path_tokens for token in DETAIL_UTILITY_PATH_TOKENS):
        return True
    query_keys = {
        str(key).strip().lower()
        for key, value in parse_qsl(
            str(urlparse(url).query or ""), keep_blank_values=False
        )
        if str(key).strip() and str(value).strip()
    }
    if not query_keys:
        return False
    return any(
        str(key).strip().lower() in query_keys for key in DETAIL_SEARCH_QUERY_KEYS
    )


def _detail_url_is_collection_like(url: str) -> bool:
    path_tokens = _detail_url_path_tokens(url)
    if any(token in path_tokens for token in DETAIL_PRODUCT_PATH_TOKENS):
        return False
    return any(token in path_tokens for token in DETAIL_COLLECTION_PATH_TOKENS)


def _detail_url_path_tokens(url: str) -> set[str]:
    return {
        token
        for token in re.split(
            r"[^a-z0-9]+", "/".join(_detail_url_path_segments(url)).lower()
        )
        if token
    }


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


def _detail_identity_tokens(value: object) -> set[str]:
    cleaned = clean_text(value).lower()
    return {
        token
        for token in re.split(r"[^a-z0-9]+", cleaned)
        if len(token) >= 3 and token not in DETAIL_IDENTITY_STOPWORDS
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
        for match in re.findall(
            rf"[A-Za-z0-9]{{{DETAIL_IDENTITY_CODE_MIN_LENGTH},}}", terminal
        ):
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
    if len(text) < DETAIL_IDENTITY_CODE_MIN_LENGTH:
        return None
    if not re.search(r"\d", text):
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

    if current and requested == current:
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
                "variants",
            )
        )
        if has_product_like_signal:
            return False
        return False

    requested_codes = _detail_identity_codes_from_url(requested)
    record_field_codes = _detail_identity_codes_from_record_fields(record)
    if (
        requested_codes
        and record_field_codes
        and not detail_identity_codes_match(
            requested_codes,
            record_field_codes,
        )
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
    if (
        candidate_url
        and candidate_url != requested
        and same_site(requested, candidate_url)
    ):
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


detail_identity_codes_from_record_fields = _detail_identity_codes_from_record_fields
detail_identity_codes_from_url = _detail_identity_codes_from_url
detail_identity_tokens = _detail_identity_tokens
detail_redirect_identity_is_mismatched = _detail_redirect_identity_is_mismatched
detail_title_from_url = _detail_title_from_url
detail_url_candidate_is_low_signal = _detail_url_candidate_is_low_signal
detail_url_is_collection_like = _detail_url_is_collection_like
detail_url_is_utility = _detail_url_is_utility
detail_url_looks_like_product = _detail_url_looks_like_product
detail_url_matches_requested_identity = _detail_url_matches_requested_identity
preferred_detail_identity_url = _preferred_detail_identity_url
record_matches_requested_detail_identity = _record_matches_requested_detail_identity
semantic_detail_identity_tokens = _semantic_detail_identity_tokens
