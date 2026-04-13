from __future__ import annotations

import logging
import re
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urljoin, urlparse

from app.services.config.extraction_rules import (
    LISTING_CARD_TITLE_SELECTORS,
    LISTING_COLOR_ACTION_PREFIXES,
    LISTING_COLOR_ACTION_VALUES,
    LISTING_DETAIL_PATH_MARKERS,
    LISTING_IMAGE_EXCLUDE_TOKENS,
    LISTING_SWATCH_CONTAINER_SELECTORS,
)
from app.services.config.extraction_audit_settings import (
    LISTING_CARD_COLOR_LABEL_MAX_CHARS,
    LISTING_CARD_COMMERCE_PARTIAL_SIGNAL_SCORE,
    LISTING_CARD_COMMERCE_STRONG_SIGNAL_SCORE,
    LISTING_CARD_GENERIC_HEADING_SIGNAL_SCORE,
    LISTING_CARD_GENERIC_MEDIA_SIGNAL_SCORE,
    LISTING_CARD_GENERIC_TEXT_SIGNAL_SCORE,
    LISTING_CARD_GROUP_MIN_SIGNAL_RATIO,
    LISTING_CARD_GROUP_MIN_SIZE,
    LISTING_CARD_GROUP_SAMPLE_SIZE,
    LISTING_CARD_JOB_COMPANY_LINE_MAX_CHARS,
    LISTING_CARD_JOB_COMPANY_SUFFIX_MAX_CHARS,
    LISTING_CARD_JOB_LOCATION_LINE_MAX_CHARS,
    LISTING_CARD_JOB_METADATA_TEXT_MAX_CHARS,
    LISTING_CARD_JOB_METADATA_SALARY_MAX_CHARS,
    LISTING_CARD_JOB_PARTIAL_SIGNAL_SCORE,
    LISTING_CARD_JOB_STRONG_SIGNAL_SCORE,
    LISTING_CARD_JOB_TITLE_MIN_CHARS,
    LISTING_CARD_LISTING_TITLE_MIN_CHARS,
    LISTING_CARD_MAX_REGEX_INPUT_CHARS,
    LISTING_CARD_MIN_PATH_SEGMENTS,
    LISTING_CARD_MULTI_ELEMENT_MIN_CHILDREN,
    LISTING_CARD_PRODUCT_URL_SCAN_MAX_DEPTH,
    LISTING_CARD_PRODUCT_URL_SCAN_MAX_LIST_ITEMS,
    LISTING_CARD_REPEATED_LINK_ROOT_MAX_DEPTH,
    LISTING_CARD_SUBSTANTIAL_TEXT_MIN_CHARS,
)
from app.services.config.nested_field_rules import PAGE_URL_CURRENCY_HINTS
from app.services.config.selectors import CARD_SELECTORS as _CARD_SELECTORS
from app.services.extract.listing_quality import (
    looks_like_category_url_for_listing as _looks_like_category_url,
    looks_like_detail_record_url_for_listing as _looks_like_detail_record_url,
    looks_like_facet_or_filter_url_for_listing as _looks_like_facet_or_filter_url,
    looks_like_listing_hub_url_for_listing as _looks_like_listing_hub_url,
    looks_like_navigation_or_action_title as _looks_like_navigation_or_action_title,
)
from app.services.extract.noise_policy import (
    is_listing_noise_group,
    strip_noise_containers,
)
from app.services.runtime_metrics import incr
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

CARD_SELECTORS_COMMERCE = _CARD_SELECTORS.get("ecommerce", [])
CARD_SELECTORS_JOBS = _CARD_SELECTORS.get("jobs", [])

_LISTING_VARIANT_PROMPT_RE = re.compile(
    r"^(?:select|choose|pick)\s+(?:a|an|the|your)?\s*"
    r"(?:size|sizes|color|colors|colour|colours|option|options|variant|variants|"
    r"style|styles|fit|fits|waist|length|width)\b",
    re.IGNORECASE,
)
_PRICE_LIKE_RE = re.compile(r"^[\s$£€¥₹]?\d[\d,.\s]*$")
_PRICE_WITH_CURRENCY_RE = re.compile(r"[\$£€¥₹]\s*\d[\d,.\s]*")
_PRICE_EXTRACT_RE = re.compile(r"[\$£€¥₹]?\s*\d[\d,.\s]*")
_MEASUREMENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:\"|in|cm|mm|ft)\b", re.I)
_DIMENSION_TOKEN_RE = re.compile(
    r"\b(?:h\s*x|w\s*x|d\s*x|height|width|depth|diameter)\b", re.I
)
_GENERIC_SIZE_VALUE_RE = re.compile(r"^(multiple|various)\s+sizes?$", re.I)
_SIZE_VALUE_SIGNAL_RE = re.compile(
    r"\b(?:[SMLX]{1,3}|[0-9]+(?:\.[0-9]+)?(?:\s*(?:in|cm|mm|oz|lb|kg|g))?)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class _CardGroupSample:
    has_link: bool
    has_image: bool
    has_price: bool
    has_heading: bool
    has_substantial_text: bool
    has_multi_elements: bool


_PRIMARY_CARD_CONTAINER_SELECTOR = (
    "ul, ol, div.grid, div.row, div[class*='results'], "
    "div[class*='product'], div[class*='listing'], div[class*='search'], "
    "div[class*='tile'], div[class*='card']"
)
_FALLBACK_CARD_CONTAINER_SELECTOR = "main, section"


@dataclass(frozen=True, slots=True)
class _GroupedCardCandidates:
    cards: list[Tag]
    selector: str
    score: tuple[float, int]


def _auto_detect_cards(soup: BeautifulSoup, surface: str = "") -> tuple[list[Tag], str]:
    cards, selector = _detect_repeated_link_card_roots(soup, surface=surface)
    if cards:
        return cards, selector

    cleaned_soup = _prepare_card_detection_soup(soup)
    cards, selector = _detect_cards_from_container_groups(
        cleaned_soup,
        surface=surface,
    )
    if cards:
        return cards, selector

    return _detect_cards_from_known_selectors(cleaned_soup, surface=surface)


def _prepare_card_detection_soup(soup: BeautifulSoup) -> BeautifulSoup:
    cleaned_soup = deepcopy(soup)
    strip_noise_containers(cleaned_soup)
    return cleaned_soup


def _detect_cards_from_container_groups(
    soup: BeautifulSoup,
    *,
    surface: str,
) -> tuple[list[Tag], str]:
    selectors = (
        _PRIMARY_CARD_CONTAINER_SELECTOR,
        _FALLBACK_CARD_CONTAINER_SELECTOR,
    )
    best_match = _GroupedCardCandidates(
        cards=[],
        selector="",
        score=(LISTING_CARD_GROUP_MIN_SIGNAL_RATIO, 0),
    )
    for selector in selectors:
        best_match = _select_best_grouped_cards(
            soup.select(selector),
            score_group=_card_group_scorer(surface),
            best_match=best_match,
        )
        if best_match.cards:
            return best_match.cards, best_match.selector
    return [], ""


def _select_best_grouped_cards(
    containers: list[Tag],
    *,
    score_group: Callable[[list[Tag]], tuple[float, int]],
    best_match: _GroupedCardCandidates,
) -> _GroupedCardCandidates:
    current_best = best_match
    for container in containers:
        group = _best_container_child_group(container, score_group=score_group)
        if group.score > current_best.score:
            current_best = group
    return current_best


def _best_container_child_group(
    container: Tag,
    *,
    score_group: Callable[[list[Tag]], tuple[float, int]],
) -> _GroupedCardCandidates:
    children = [child for child in container.children if isinstance(child, Tag)]
    if len(children) < LISTING_CARD_GROUP_MIN_SIZE:
        return _GroupedCardCandidates(cards=[], selector="", score=(0.0, 0))

    best_match = _GroupedCardCandidates(cards=[], selector="", score=(0.0, 0))
    for signature, group in _group_children_by_signature(children).items():
        if len(group) < LISTING_CARD_GROUP_MIN_SIZE:
            continue
        score = score_group(group)
        if score > best_match.score:
            best_match = _GroupedCardCandidates(
                cards=group,
                selector=_card_group_selector(signature),
                score=score,
            )
    return best_match


def _group_children_by_signature(
    children: list[Tag],
) -> dict[tuple[str, tuple[str, ...]], list[Tag]]:
    grouped_children: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}
    for child in children:
        signature = (
            child.name,
            tuple(sorted(child.get("class", []))),
        )
        grouped_children.setdefault(signature, []).append(child)
    return grouped_children


def _card_group_selector(signature: tuple[str, tuple[str, ...]]) -> str:
    tag_name, class_names = signature
    class_selector = ".".join(class_names)
    return f"{tag_name}.{class_selector}" if class_selector else tag_name


def _detect_cards_from_known_selectors(
    soup: BeautifulSoup,
    *,
    surface: str,
) -> tuple[list[Tag], str]:
    for selector in _surface_card_selectors(surface):
        found = soup.select(selector)
        if len(found) >= LISTING_CARD_GROUP_MIN_SIZE:
            return found, selector
    return [], ""


def _surface_card_selectors(surface: str) -> list[str]:
    normalized_surface = str(surface or "").lower()
    if "commerce" in normalized_surface or "ecommerce" in normalized_surface:
        return CARD_SELECTORS_COMMERCE
    return CARD_SELECTORS_JOBS


def _card_group_score(group: list[Tag], surface: str = "") -> tuple[float, int]:
    return _card_group_scorer(surface)(group)


def _card_group_scorer(surface: str = "") -> Callable[[list[Tag]], tuple[float, int]]:
    sample_scorer = _card_signal_scorer(surface)

    def _score_group(group: list[Tag]) -> tuple[float, int]:
        if is_listing_noise_group(group):
            return (0.0, 0)
        signals = 0.0
        sample_size = min(len(group), LISTING_CARD_GROUP_SAMPLE_SIZE)
        for el in group[:sample_size]:
            sample = _card_group_sample(el)
            if not sample.has_link:
                continue
            signals += sample_scorer(sample)
        ratio = signals / sample_size if sample_size > 0 else 0.0
        return (ratio, len(group))

    return _score_group


def _card_signal_scorer(surface: str = "") -> Callable[[_CardGroupSample], float]:
    normalized_surface = str(surface or "").lower()
    if "commerce" in normalized_surface:
        return _score_commerce_card_sample
    if "job" in normalized_surface:
        return _score_job_card_sample
    return _score_generic_card_sample


def _card_group_sample(el: Tag) -> _CardGroupSample:
    text = el.get_text(" ", strip=True)
    return _CardGroupSample(
        has_link=bool(el.select_one("a[href]")),
        has_image=bool(el.select_one("img, picture, [style*='background-image']")),
        has_price=bool(
            el.select_one("[itemprop='price'], .price, .product-price, .a-price .a-offscreen, .s-item__price, .amount, [data-testid*='price']")
        ),
        has_heading=bool(el.select_one("h1, h2, h3, h4, h5, [class*='title' i]")),
        has_substantial_text=len(text) > LISTING_CARD_SUBSTANTIAL_TEXT_MIN_CHARS,
        has_multi_elements=(
            len([child for child in el.children if isinstance(child, Tag)])
            >= LISTING_CARD_MULTI_ELEMENT_MIN_CHILDREN
        ),
    )


def _score_commerce_card_sample(sample: _CardGroupSample) -> float:
    if sample.has_image and sample.has_price:
        return LISTING_CARD_COMMERCE_STRONG_SIGNAL_SCORE
    if sample.has_image or sample.has_price:
        return LISTING_CARD_COMMERCE_PARTIAL_SIGNAL_SCORE
    return 0.0


def _score_job_card_sample(sample: _CardGroupSample) -> float:
    if sample.has_heading and sample.has_multi_elements:
        return LISTING_CARD_JOB_STRONG_SIGNAL_SCORE
    if sample.has_heading or sample.has_substantial_text:
        return LISTING_CARD_JOB_PARTIAL_SIGNAL_SCORE
    return 0.0


def _score_generic_card_sample(sample: _CardGroupSample) -> float:
    if sample.has_image or sample.has_price:
        return LISTING_CARD_GENERIC_MEDIA_SIGNAL_SCORE
    if sample.has_heading and sample.has_substantial_text:
        return LISTING_CARD_GENERIC_HEADING_SIGNAL_SCORE
    if sample.has_substantial_text and sample.has_multi_elements:
        return LISTING_CARD_GENERIC_TEXT_SIGNAL_SCORE
    return 0.0


def _detect_repeated_link_card_roots(
    soup: BeautifulSoup,
    *,
    surface: str,
) -> tuple[list[Tag], str]:
    min_group_size = LISTING_CARD_GROUP_MIN_SIZE
    grouped: dict[tuple[str, tuple[str, ...]], list[Tag]] = {}
    score_group = _card_group_scorer(surface)

    for link in soup.select("a[href]"):
        href = str(link.get("href") or "").strip()
        if not _looks_like_card_link_href(href):
            continue
        current: Tag | None = link
        for _depth in range(LISTING_CARD_REPEATED_LINK_ROOT_MAX_DEPTH):
            current = current.parent if isinstance(current.parent, Tag) else None
            if not isinstance(current, Tag) or current.name in {"body", "html"}:
                break
            signature = (
                current.name,
                tuple(
                    sorted(
                        class_name
                        for class_name in current.get("class", [])
                        if class_name
                    )
                ),
            )
            grouped.setdefault(signature, []).append(current)

    best_cards: list[Tag] = []
    best_selector = ""
    best_score: tuple[float, int] = (LISTING_CARD_GROUP_MIN_SIGNAL_RATIO, 0)
    for signature, group in grouped.items():
        deduped = _dedupe_card_tags(group)
        if len(deduped) < min_group_size:
            continue
        score = score_group(deduped)
        if score > best_score:
            best_cards = deduped
            class_selector = ".".join(signature[1])
            best_selector = (
                f"{signature[0]}.{class_selector}" if class_selector else signature[0]
            )
            best_score = score
    return best_cards, best_selector


def _dedupe_card_tags(tags: list[Tag]) -> list[Tag]:
    deduped: list[Tag] = []
    seen: set[int] = set()
    for tag in tags:
        identity = id(tag)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(tag)
    return deduped


def _looks_like_card_link_href(href: str) -> bool:
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return False
    lowered = href.lower()
    if _looks_like_facet_or_filter_url(lowered):
        return False
    if any(marker in lowered for marker in LISTING_DETAIL_PATH_MARKERS):
        return True
    parsed = urlparse(lowered)
    path = parsed.path.strip("/")
    if not path:
        return False
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < LISTING_CARD_MIN_PATH_SEGMENTS:
        return False
    if _looks_like_category_url(f"https://example.com/{path}"):
        return False
    return not _looks_like_listing_hub_url(f"https://example.com/{path}")


def _best_card_link(card: Tag, page_url: str) -> str:
    fallback = ""
    for link_el in card.select("a[href]"):
        href = str(link_el.get("href") or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        resolved = urljoin(page_url, href) if page_url else href
        if not fallback:
            fallback = resolved
        parsed_path = urlparse(resolved).path.lower()
        if any(marker in parsed_path for marker in LISTING_DETAIL_PATH_MARKERS):
            return resolved
    return fallback


def _extract_from_card(
    card: Tag,
    _target_fields: set[str],
    surface: str,
    page_url: str,
) -> dict:
    record: dict = {}
    normalized_surface = str(surface or "").lower()
    is_job_surface = "job" in normalized_surface
    is_ecommerce_surface = "ecommerce" in normalized_surface

    if is_ecommerce_surface:
        record |= _extract_ecommerce_price_fields(card)

    record |= _extract_card_link_and_title(
        card,
        page_url=page_url,
        is_job_surface=is_job_surface,
    )

    if not is_job_surface:
        record |= _extract_card_image_fields(card, page_url=page_url)

    record |= _extract_card_common_metadata(card)
    card_text_lines = _card_text_lines(card)
    record |= _extract_card_identifier_fields(card, card_text_lines)
    if is_ecommerce_surface:
        record |= _extract_ecommerce_card_fields(
            card,
            card_text_lines,
            page_url=page_url,
            record=record,
        )

    if is_job_surface:
        record |= _extract_job_card_fields(
            card,
            card_text_lines=card_text_lines,
            record=record,
        )
        record = _finalize_job_card_record(record)

    return record


def _extract_card_link_and_title(
    card: Tag,
    *,
    page_url: str,
    is_job_surface: bool,
) -> dict[str, str]:
    record = _extract_card_title(card)
    if "title" not in record and not is_job_surface:
        inferred_title = _infer_listing_title_from_links(card)
        if inferred_title:
            record["title"] = _normalize_listing_title_text(inferred_title)

    url = _best_card_link(card, page_url)
    if url:
        record["url"] = url
    if "title" not in record:
        inferred_title = _infer_job_title_from_links(card)
        if inferred_title:
            record["title"] = _normalize_listing_title_text(inferred_title)
    return record


def _extract_card_common_metadata(card: Tag) -> dict[str, str]:
    record: dict[str, str] = {}
    brand_text = _extract_card_text_value(
        card,
        ".brand, [itemprop='brand'], .product-brand",
        include_aria=False,
    )
    if brand_text:
        record["brand"] = brand_text

    rating_text = _extract_card_text_value(
        card,
        "[aria-label*='star'], .rating, [itemprop='ratingValue']",
    )
    if rating_text:
        record["rating"] = rating_text

    review_count_text = _extract_card_text_value(
        card,
        "[itemprop='reviewCount'], [aria-label*='review'], .review-count, .reviewCount",
    )
    if review_count_text:
        record["review_count"] = review_count_text
    return record


def _extract_card_text_value(
    card: Tag,
    selector: str,
    *,
    include_aria: bool = True,
) -> str:
    element = card.select_one(selector)
    if element is None:
        return ""
    value = element.get("content")
    if include_aria and not value:
        value = element.get("aria-label", "")
    if not value:
        value = element.get_text(" ", strip=True)
    return " ".join(str(value or "").split()).strip()


def _extract_card_identifier_fields(
    card: Tag,
    card_text_lines: list[str],
) -> dict[str, str]:
    return {
        field_name: value
        for field_name, value in _extract_card_identifiers(card, card_text_lines).items()
        if value
    }


def _extract_ecommerce_card_fields(
    card: Tag,
    card_text_lines: list[str],
    *,
    page_url: str,
    record: dict[str, object],
) -> dict[str, str]:
    patch: dict[str, str] = {}
    for field_name, value in _iter_ecommerce_card_field_values(
        card,
        card_text_lines,
        page_url=page_url,
        record=record,
    ):
        patch[field_name] = value
    return patch


def _iter_ecommerce_card_field_values(
    card: Tag,
    card_text_lines: list[str],
    *,
    page_url: str,
    record: dict[str, object],
) -> list[tuple[str, str]]:
    field_values = [
        ("color", _extract_card_color(card, card_text_lines)),
        ("size", _extract_card_size(card_text_lines)),
        ("dimensions", _match_dimensions_line(card_text_lines)),
    ]
    inferred_currency = _extract_listing_currency(page_url=page_url, record=record)
    if inferred_currency:
        field_values.append(("currency", inferred_currency))
    return [(field_name, value) for field_name, value in field_values if value]


def _extract_listing_currency(*, page_url: str, record: dict[str, object]) -> str:
    if not record.get("price") or record.get("currency"):
        return ""
    return _infer_currency_from_page_url(page_url)


def _finalize_job_card_record(record: dict) -> dict:
    finalized = dict(record)
    if finalized.get("url") and not finalized.get("apply_url"):
        finalized["apply_url"] = str(finalized["url"])
    finalized.pop("image_url", None)
    finalized.pop("additional_images", None)
    return finalized


def _extract_ecommerce_price_fields(card: Tag) -> dict[str, str]:
    record: dict[str, str] = {}
    for selector in (
        "[itemprop='price']",
        "[data-testid*='current'][data-testid*='price'], [data-test*='current'][data-test*='price'], [data-qa*='current'][data-qa*='price']",
        "[data-testid*='price']:not([data-testid*='was']):not([data-testid*='original']):not([data-testid*='old']):not([data-testid*='compare']), [data-test*='price']:not([data-test*='was']):not([data-test*='original']):not([data-test*='old']):not([data-test*='compare']), [data-qa*='price']:not([data-qa*='was']):not([data-qa*='original']):not([data-qa*='old']):not([data-qa*='compare'])",
        ".price:not(.was-price):not(.original-price):not(.compare-price), .product-price, .a-price .a-offscreen, .s-item__price, span[data-price], .amount",
    ):
        for price_el in card.select(selector):
            if _price_node_looks_non_current(price_el):
                continue
            raw_price = price_el.get("content") or price_el.get_text(" ", strip=True)
            price = _clean_price_text(raw_price)
            if price is not None:
                record["price"] = price
                break
        if record.get("price"):
            break
    for selector in (
        "[data-testid*='was'][data-testid*='price'], [data-testid*='original'][data-testid*='price'], [data-testid*='compare'][data-testid*='price'], [data-test*='was'][data-test*='price'], [data-test*='original'][data-test*='price'], [data-test*='compare'][data-test*='price'], [data-qa*='was'][data-qa*='price'], [data-qa*='original'][data-qa*='price'], [data-qa*='compare'][data-qa*='price']",
        ".original-price, .compare-price, .was-price, [data-original-price]",
        "s, del, .strike",
    ):
        for original_price_el in card.select(selector):
            if selector == "s, del, .strike" and not _looks_like_original_price_node(
                original_price_el
            ):
                continue
            raw_op = original_price_el.get("content") or original_price_el.get_text(" ", strip=True)
            original_price = _clean_price_text(raw_op)
            if original_price is not None:
                record["original_price"] = original_price
                break
        if record.get("original_price"):
            break
    return record


def _price_node_looks_non_current(node: Tag) -> bool:
    if node.name in {"s", "del"}:
        return True
    for current in [node, *node.parents]:
        if not isinstance(current, Tag):
            continue
        classes = " ".join(current.get("class", []))
        attrs = " ".join(
            str(value)
            for key, value in current.attrs.items()
            if key.startswith("data-") or key in {"class", "aria-label"}
        )
        lowered = f"{classes} {attrs}".lower()
        if any(token in lowered for token in ("was-price", "original-price", "compare-price", "old-price")):
            return True
    return False


def _looks_like_original_price_node(node: Tag) -> bool:
    raw_text = node.get("content") or node.get_text(" ", strip=True)
    if not _text_contains_price_token(raw_text):
        return False
    if _price_node_looks_non_current(node):
        return True
    context = " ".join(
        str(value)
        for current in [node, *node.parents]
        if isinstance(current, Tag)
        for value in (
            " ".join(current.get("class", [])),
            current.get("aria-label", ""),
        )
    ).lower()
    return any(token in context for token in ("was", "original", "compare", "old"))


def _text_contains_price_token(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    return bool(_PRICE_WITH_CURRENCY_RE.search(text) or _PRICE_EXTRACT_RE.search(text))


def _extract_card_title(card: Tag) -> dict[str, str]:
    for selector in LISTING_CARD_TITLE_SELECTORS:
        title_el = card.select_one(selector)
        if not title_el or title_el.name == "meta":
            continue
        text = _extract_listing_title_text(title_el)
        if (
            text
            and not _PRICE_LIKE_RE.match(text)
            and not _LISTING_VARIANT_PROMPT_RE.match(text)
        ):
            return {
                "title": _normalize_listing_title_text(text),
                "_selector_title": selector,
            }
    return {}


def _extract_listing_title_text(node: Tag) -> str:
    text = node.get_text(" ", strip=True)
    if text:
        return text
    for attr in ("alt", "title", "aria-label", "content"):
        value = " ".join(str(node.get(attr) or "").split()).strip()
        if value:
            return value
    if node.name != "img":
        image = node.select_one("img[alt], img[title]")
        if image is not None:
            return _extract_listing_title_text(image)
    return ""


def _extract_card_image_fields(card: Tag, *, page_url: str) -> dict[str, str]:
    record: dict[str, str] = {}
    img_el = card.select_one("[itemprop='image']")
    if img_el:
        src = img_el.get("src") or img_el.get("data-src") or img_el.get("content", "")
        if src:
            record["image_url"] = urljoin(page_url, src) if page_url else src
    if "image_url" not in record:
        images = _extract_card_images(card, page_url)
        if images:
            record["image_url"] = images[0]
            if len(images) > 1:
                record["additional_images"] = ", ".join(images[1:])
    return record


def _extract_job_card_fields(
    card: Tag,
    *,
    card_text_lines: list[str],
    record: dict[str, object],
) -> dict[str, str]:
    patch: dict[str, str] = {}
    metadata_fields = _extract_job_metadata_fields(card)
    company_el = card.select_one(
        ".company, .companyName, [data-testid='company-name'], [data-testid*='company-name'], "
        "[data-testid*='listing-company-name'], [itemprop='publisher'] [itemprop='name'], "
        "[itemprop='hiringOrganization'] [itemprop='name']"
    )
    if company_el:
        company_value = company_el.get("content") or company_el.get_text(" ", strip=True)
        company_value = " ".join(str(company_value or "").split()).strip()
        if company_value:
            patch["company"] = company_value
    location_el = card.select_one(
        ".location, .companyLocation, [data-testid='text-location'], [data-testid*='job-location'], "
        "[data-testid*='listing-job-location'], [itemprop='jobLocation']"
    )
    if location_el:
        location_value = location_el.get("content") or location_el.get_text(" ", strip=True)
        location_value = " ".join(str(location_value or "").split()).strip()
        if location_value:
            patch["location"] = location_value
    salary_el = card.select_one(
        ".salary, .salary-snippet-container, [data-testid*='salary']"
    )
    if salary_el:
        salary_value = " ".join(salary_el.get_text(" ", strip=True).split()).strip()
        if salary_value:
            patch["salary"] = salary_value
    for field_name, value in metadata_fields.items():
        if value and field_name not in patch and field_name not in record:
            patch[field_name] = value
    title = patch.get("title") or record.get("title")
    department = patch.get("department") or record.get("department")
    if not (patch.get("company") or record.get("company")) and not department:
        inferred_company = _infer_job_company(card_text_lines, title=title)
        if inferred_company:
            patch["company"] = inferred_company
    if not (patch.get("location") or record.get("location")):
        inferred_location = _infer_job_location(card_text_lines, title=title)
        if inferred_location:
            patch["location"] = inferred_location
    if not (patch.get("salary") or record.get("salary")):
        inferred_salary = _infer_job_salary(card_text_lines)
        if inferred_salary:
            patch["salary"] = inferred_salary
    inferred_job_type = _infer_job_type(card_text_lines)
    if inferred_job_type and "job_type" not in patch and "job_type" not in record:
        patch["job_type"] = inferred_job_type
    inferred_posted_date = _infer_job_posted_date(card_text_lines)
    if inferred_posted_date and "posted_date" not in patch and "posted_date" not in record:
        patch["posted_date"] = inferred_posted_date
    return patch


def _extract_image_candidates(value: object, *, page_url: str = "") -> list[str]:
    if value in (None, "", [], {}):
        return []
    raw_items: list[object] = value if isinstance(value, list) else [value]

    images: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        candidate = ""
        if isinstance(item, dict):
            media_type = str(item.get("type") or "").strip().upper()
            if media_type == "VIDEO":
                continue
            candidate = str(
                item.get("url") or item.get("contentUrl") or item.get("src") or ""
            ).strip()
        else:
            candidate = str(item).strip()
        if not candidate:
            continue
        resolved = urljoin(page_url, candidate) if page_url else candidate
        if urlparse(resolved).path.lower().endswith(
            (".woff", ".woff2", ".ttf", ".otf", ".eot", ".css", ".js", ".map")
        ):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        images.append(resolved)
    return images


def _extract_card_images(card: Tag, page_url: str) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()
    swatch_containers = {
        id(node)
        for selector in LISTING_SWATCH_CONTAINER_SELECTORS
        for node in card.select(selector)
    }
    for img_el in card.select("img"):
        parent = img_el.parent
        skip_image = False
        while parent and parent is not card:
            if id(parent) in swatch_containers:
                skip_image = True
                break
            parent = parent.parent
        if skip_image:
            continue
        src = (
            img_el.get("src")
            or img_el.get("data-src")
            or img_el.get("data-original")
            or img_el.get("srcset", "").split(",")[0].strip().split(" ")[0]
        )
        if not src:
            continue
        resolved = urljoin(page_url, src) if page_url else src
        lowered_resolved = resolved.lower()
        if any(token in lowered_resolved for token in LISTING_IMAGE_EXCLUDE_TOKENS):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        images.append(resolved)
    return images


@lru_cache(maxsize=64)
def _compile_case_insensitive_regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.I)


def _clean_price_text(raw: str) -> str | None:
    raw = raw.strip()
    if len(raw) > LISTING_CARD_MAX_REGEX_INPUT_CHARS:
        incr("listing_price_regex_input_too_long_total")
        logger.debug(
            "Skipping price regex extraction for overlong input: len=%d",
            len(raw),
        )
        return None
    matches = list(_PRICE_WITH_CURRENCY_RE.finditer(raw))
    if matches:
        return matches[-1].group(0).strip()
    matches = list(_PRICE_EXTRACT_RE.finditer(raw))
    return matches[-1].group(0).strip() if matches else raw


def _card_text_lines(card: Tag) -> list[str]:
    lines: list[str] = []
    for text in card.stripped_strings:
        cleaned = " ".join(str(text).split()).strip()
        if cleaned:
            lines.append(cleaned)
    return lines


def _match_line(lines: list[str], pattern: str) -> str:
    regex = _compile_case_insensitive_regex(pattern)
    for line in lines:
        if regex.search(line):
            return line
    return ""


def _match_dimensions_line(lines: list[str]) -> str:
    for line in lines:
        if _DIMENSION_TOKEN_RE.search(line):
            return line
        if _MEASUREMENT_RE.search(line):
            return line
    return ""


def _infer_job_title_from_links(card: Tag) -> str:
    for link_el in card.select("a[href]"):
        href = str(link_el.get("href") or "").strip()
        if not href:
            continue
        candidate = link_el.get_text(" ", strip=True)
        if not candidate:
            continue
        candidate = re.sub(r"\([0-9a-f]{24,}\)$", "", candidate, flags=re.I).strip()
        if not candidate or len(candidate) < LISTING_CARD_JOB_TITLE_MIN_CHARS:
            continue
        if _PRICE_LIKE_RE.match(candidate):
            continue
        if candidate.lower() in {"apply now", "easy apply", "company logo", "save job"}:
            continue
        if _looks_like_detail_record_url(href):
            return candidate
    for link_el in card.select("a[href]"):
        href = str(link_el.get("href") or "").strip()
        if not href:
            continue
        candidate = str(link_el.get("aria-label") or "").strip()
        candidate = re.sub(r"(?i)^view details for\s+", "", candidate).strip()
        candidate = re.sub(r"\([0-9a-f]{24,}\)$", "", candidate, flags=re.I).strip()
        if not candidate or len(candidate) < LISTING_CARD_JOB_TITLE_MIN_CHARS:
            continue
        if candidate.lower() in {"apply now", "easy apply", "company logo", "save job"}:
            continue
        if _looks_like_detail_record_url(href):
            return candidate
    return ""


def _infer_listing_title_from_links(card: Tag) -> str:
    for link_el in card.select("a[href]"):
        candidate = link_el.get_text(" ", strip=True)
        if not candidate or len(candidate) < LISTING_CARD_LISTING_TITLE_MIN_CHARS:
            continue
        if _PRICE_LIKE_RE.match(candidate):
            continue
        if _looks_like_navigation_or_action_title(
            candidate,
            str(link_el.get("href") or ""),
        ):
            continue
        return candidate
    for link_el in card.select("a[aria-label]"):
        candidate = str(link_el.get("aria-label") or "").strip()
        if not candidate or len(candidate) < LISTING_CARD_LISTING_TITLE_MIN_CHARS:
            continue
        if _looks_like_navigation_or_action_title(
            candidate,
            str(link_el.get("href") or ""),
        ):
            continue
        return candidate
    return ""


def _infer_job_company(lines: list[str], *, title: object = None) -> str:
    title_text = str(title or "").strip()
    for line in lines:
        if not line or line == title_text:
            continue
        if line.startswith((",", ";", ":", "-", "/")):
            continue
        if _infer_job_location([line], title=title):
            continue
        if _infer_job_salary([line]):
            continue
        if _infer_job_type([line]):
            continue
        if _infer_job_posted_date([line]):
            continue
        lowered = line.lower()
        if lowered in {
            "apply now",
            "save job",
            "sponsored",
            "today",
            "yesterday",
            "no comments",
        }:
            continue
        if lowered in {
            "location",
            "locations",
            "posted on",
            "posted",
            "job id",
            "job number",
            "requisition",
        }:
            continue
        if re.search(r"(?i)\b\d+\s+locations?\b", line):
            continue
        if re.match(r"^[A-Z]{2,4}\s*-\s*[A-Za-z]", line):
            continue
        if any(
            token in lowered
            for token in (
                "comment",
                "read more",
                "purpose:",
                "responsible for",
                "responsibilities",
            )
        ):
            continue
        if re.fullmatch(r"[A-Z]\d{4,}", line):
            continue
        if lowered.endswith(":") and len(line) <= LISTING_CARD_JOB_COMPANY_SUFFIX_MAX_CHARS:
            continue
        if len(line) <= LISTING_CARD_JOB_COMPANY_LINE_MAX_CHARS:
            return line
    return ""


def _infer_job_location(lines: list[str], *, title: object = None) -> str:
    title_text = str(title or "").strip()
    for line in lines:
        lowered = line.lower()
        if not line or line == title_text:
            continue
        if line.startswith((",", ";", ":", "-", "/")):
            continue
        if title_text and title_text.lower() in lowered:
            continue
        if lowered == "multiple locations":
            return line
        if re.search(r"(?i)\b\d+\s+locations?\b", line):
            return line
        if re.match(r"^[A-Z]{2,4}\s*-\s*[A-Za-z]", line):
            return line
        if any(token in lowered for token in ("remote", "hybrid", "on-site", "onsite")):
            return line
        if any(
            token in lowered
            for token in (
                "purpose:",
                "responsible for",
                "responsibilities",
                "read more",
                "comment",
            )
        ):
            continue
        if len(line) > LISTING_CARD_JOB_LOCATION_LINE_MAX_CHARS:
            continue
        if (
            "," in line
            and re.search(r"[A-Za-z].*,\s*[A-Za-z]", line)
            and not _infer_job_salary([line])
            and not _infer_job_posted_date([line])
        ):
            return line
    return ""


def _infer_job_salary(lines: list[str]) -> str:
    salary_pattern = re.compile(
        r"(?i)(?:(?:[$€£₹]|usd|eur|gbp|inr)\s*\d.*(?:/|\bper\b)\s*(?:hr|wk|mo|yr|hour|day|week|month|year)\b)|"
        r"(?:(?:[$€£₹]|usd|eur|gbp|inr)\s*\d[\d,.\s]*/(?:hr|wk|mo|yr)\b(?:\s*est)?)|"
        r"(?:(?:[$€£₹]|usd|eur|gbp|inr)\s*\d.*(?:salary|compensation|annual))|"
        r"(?:\d[\d,]*(?:\.\d+)?\s*(?:/|\bper\b)\s*(?:hr|wk|mo|yr|hour|day|week|month|year)\b)"
    )
    for line in lines:
        match = salary_pattern.search(line)
        if match:
            return " ".join(match.group(0).split()).strip()
    return ""


def _extract_job_metadata_fields(card: Tag) -> dict[str, str]:
    fields: dict[str, str] = {}

    for container in card.select("dt"):
        label = " ".join(container.get_text(" ", strip=True).split()).strip()
        value_node = container.find_next("dd")
        value = (
            " ".join(value_node.get_text(" ", strip=True).split()).strip()
            if value_node is not None
            else ""
        )
        if not label or not value:
            continue
        _assign_job_metadata_field(fields, label=label, value=value)

    for container in card.select("p, div, span"):
        icon = container.find(["img", "i"], recursive=False)
        if icon is None:
            continue
        text = " ".join(container.get_text(" ", strip=True).split()).strip()
        if not text or len(text) > LISTING_CARD_JOB_METADATA_TEXT_MAX_CHARS:
            continue
        marker = " ".join(
            part
            for part in (
                icon.get("src"),
                icon.get("alt"),
                icon.get("title"),
                icon.get("aria-label"),
                " ".join(icon.get("class", [])),
            )
            if part
        )
        _assign_job_metadata_field(fields, label=marker, value=text)

    return fields


def _assign_job_metadata_field(
    fields: dict[str, str],
    *,
    label: str,
    value: str,
) -> None:
    normalized_label = re.sub(r"[^a-z0-9]+", " ", str(label or "").lower()).strip()
    normalized_value = " ".join(str(value or "").split()).strip()
    if not normalized_label or not normalized_value:
        return

    if any(token in normalized_label for token in ("location", "map marker", "address")):
        fields.setdefault("location", normalized_value)
        return
    if "job location" in normalized_label:
        fields.setdefault("location", normalized_value)
        return
    if any(token in normalized_label for token in ("salary", "pay", "compensation")) or (
        len(normalized_value) <= LISTING_CARD_JOB_METADATA_SALARY_MAX_CHARS
        and _infer_job_salary([normalized_value])
    ):
        fields.setdefault("salary", normalized_value)
        return
    if any(
        token in normalized_label
        for token in ("employment type", "job type", "suitcase", "shift")
    ):
        fields.setdefault("job_type", _infer_job_type([normalized_value]) or normalized_value)
        return
    if any(
        token in normalized_label
        for token in ("department", "division", "team", "category", "sitemap")
    ):
        fields.setdefault("department", normalized_value)
        return
    if any(
        token in normalized_label
        for token in ("job number", "job id", "requisition", "identifier")
    ):
        fields.setdefault("job_id", normalized_value)
        return
    if "start" in normalized_label:
        fields.setdefault("start_date", normalized_value.removeprefix("Start:").strip())


def _infer_job_type(lines: list[str]) -> str:
    job_type_pattern = re.compile(
        r"(?i)\b(full[- ]?time|part[- ]?time|contract|temporary|internship|intern|freelance|permanent)\b"
    )
    for line in lines:
        match = job_type_pattern.search(line)
        if match:
            return match.group(1)
    return ""


def _infer_job_posted_date(lines: list[str]) -> str:
    posted_pattern = re.compile(
        r"(?i)\b(posted\s+\d+\s+(?:minute|hour|day|week|month)s?\s+ago|"
        r"posted\s+(?:today|yesterday)|today|yesterday|\d+\s+(?:minute|hour|day|week|month)s?\s+ago)\b"
    )
    for line in lines:
        match = posted_pattern.search(line)
        if match:
            return match.group(0)
    return ""


def _extract_card_color(card: Tag, lines: list[str]) -> str:
    swatch_selectors = [
        "[data-color]",
        "[data-color-name]",
        "[data-testid*='color' i]",
        "[aria-label*='color' i]",
        "[title*='color' i]",
        "[class*='swatch'] [aria-label]",
        "[class*='swatch'][aria-label]",
        "[role='radio'][aria-label]",
        "button[aria-label]",
    ]
    for selector in swatch_selectors:
        for node in card.select(selector):
            color = _extract_color_label_from_node(node)
            if color:
                return color

    color_line = _match_line(lines, r"\bcolors?\b")
    if color_line:
        match = re.search(r"(?i)colors?\s*[:\-]\s*(.+)", color_line)
        if match:
            color_value = match.group(1).strip()
            if not re.match(r"^\d+\s+colors?$", color_value, re.I):
                return color_value
    return ""


def _extract_color_label_from_node(node: Tag) -> str:
    candidate_values = [
        node.get("data-color"),
        node.get("data-color-name"),
        node.get("aria-label"),
        node.get("title"),
        node.get_text(" ", strip=True),
    ]
    for raw_value in candidate_values:
        text = " ".join(str(raw_value or "").split()).strip()
        if not text:
            continue
        text = re.sub(r"(?i)^(selected\s+)?colors?\s*[:\-]\s*", "", text).strip()
        text = re.sub(r"(?i)^(view|select|choose)\s+colors?\s*[:\-]?\s*", "", text).strip()
        text = re.sub(r"(?i)\b(?:button|swatch|option)$", "", text).strip(" -,:;/")
        if not text:
            continue
        lowered = text.lower()
        if lowered in {"color", "colors", "select color", "choose color"}:
            continue
        if "fits your vehicle" in lowered:
            continue
        if lowered in LISTING_COLOR_ACTION_VALUES or any(
            lowered.startswith(prefix) for prefix in LISTING_COLOR_ACTION_PREFIXES
        ):
            continue
        if len(text) > LISTING_CARD_COLOR_LABEL_MAX_CHARS:
            continue
        return text
    return ""


def _extract_card_size(lines: list[str]) -> str:
    size_line = _match_line(lines, r"\bsizes?\b")
    if not size_line:
        return ""
    match = re.search(r"(?i)sizes?\s*[:\-]\s*(.+)", size_line)
    if match:
        size_value = match.group(1).strip()
        if not _GENERIC_SIZE_VALUE_RE.match(size_value):
            return size_value
        return ""
    if _SIZE_VALUE_SIGNAL_RE.search(size_line):
        cleaned = re.sub(r"(?i)^sizes?\s*[:\-]?\s*", "", size_line).strip()
        if cleaned and cleaned.lower() not in {"size", "sizes"}:
            return cleaned
    return ""


def _extract_card_identifiers(card: Tag, lines: list[str]) -> dict[str, str]:
    identifiers: dict[str, str] = {}
    selector_map = {
        "part_number": (
            "[data-testid='product-part-number']",
            "[data-testid*='part-number' i]",
        ),
        "sku": (
            "[data-testid='product-sku-number']",
            "[data-testid*='sku-number' i]",
            "[itemprop='sku']",
        ),
    }
    for field_name, selectors in selector_map.items():
        for selector in selectors:
            node = card.select_one(selector)
            if node is None:
                continue
            text = " ".join(node.get_text(" ", strip=True).split())
            match = re.search(r"#\s*([A-Z0-9-]+)\b", text, re.I)
            if match:
                identifiers[field_name] = match.group(1)
                break

    joined_lines = " ".join(lines)
    if not identifiers.get("part_number"):
        match = re.search(r"(?i)\bpart\s*#\s*([A-Z0-9-]+)\b", joined_lines)
        if match:
            identifiers["part_number"] = match.group(1)
    if not identifiers.get("sku"):
        match = re.search(r"(?i)\bsku\s*#\s*([A-Z0-9-]+)\b", joined_lines)
        if match:
            identifiers["sku"] = match.group(1)
    if not identifiers.get("job_id"):
        match = re.search(
            r"(?i)\b(?:job\s*(?:id|number)|requisition(?:\s*(?:id|number))?|req(?:uisition)?\s*#?)[:#\s-]*([A-Z]?\d{4,})\b",
            joined_lines,
        )
        if match:
            identifiers["job_id"] = match.group(1)
    if not identifiers.get("job_id"):
        for line in lines:
            candidate = str(line or "").strip()
            if re.fullmatch(r"[A-Z]?\d{4,}", candidate):
                identifiers["job_id"] = candidate
                break
    detail_link = card.select_one("a[href]")
    href = str(detail_link.get("href") or "").strip() if isinstance(detail_link, Tag) else ""
    if href and not identifiers.get("id"):
        tail = urlparse(href).path.rstrip("/").split("/")[-1]
        if re.fullmatch(r"[0-9]{4,}", tail):
            identifiers["id"] = tail
            lowered_href = href.lower()
            if "job" in lowered_href or "career" in lowered_href:
                identifiers.setdefault("job_id", tail)
    return identifiers


def _harvest_product_url_from_item(item: dict, *, page_url: str) -> str:
    if not isinstance(item, dict) or not page_url:
        return ""
    direct = _first_href_from_nested_link(item)
    resolved_direct = _coerce_listing_product_url_candidate(direct, page_url)
    if resolved_direct:
        return resolved_direct

    for key in (
        "urlTemplate",
        "productUrlTemplate",
        "pdpUrlTemplate",
        "itemUrlPattern",
        "urlPattern",
    ):
        tpl = item.get(key)
        if not isinstance(tpl, str) or "{" not in tpl:
            continue
        ident = _primary_commerce_identifier(item)
        if not ident:
            continue
        try:
            filled = tpl.format(
                sku=ident,
                id=ident,
                ID=ident,
                productId=ident,
                product_id=ident,
            )
        except (KeyError, ValueError, IndexError):
            filled = (
                tpl.replace("{sku}", ident)
                .replace("{id}", ident)
                .replace("{ID}", ident)
                .replace("{productId}", ident)
                .replace("{product_id}", ident)
                .replace("{0}", ident)
            )
            if "{" in filled or "}" in filled or re.search(r"\{[^}]+\}", filled):
                continue
        resolved = _coerce_listing_product_url_candidate(filled, page_url)
        if resolved:
            return resolved

    return _scan_payload_for_product_url(item, page_url, depth=0)


def _normalize_listing_title_text(value: object) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    text = re.sub(r"\s+([,;:/|])", r"\1", text)
    text = re.sub(r"([(/])\s+", r"\1", text)
    text = re.sub(r"\s+([)])", r"\1", text)
    text = re.sub(r"\s*[,;/|:-]+\s*$", "", text).strip()
    return text


def _infer_currency_from_page_url(page_url: str) -> str:
    raw_page_url = str(page_url or "").strip()
    if not raw_page_url:
        return ""
    url_path = urlparse(raw_page_url).path.lower()
    if not url_path:
        return ""
    for pattern, currency in PAGE_URL_CURRENCY_HINTS.items():
        if pattern.search(url_path):
            return currency
    return ""


def _primary_commerce_identifier(item: dict) -> str:
    for key in (
        "sku",
        "product_id",
        "productId",
        "item_id",
        "itemId",
        "articleNumber",
        "part_number",
        "styleNumber",
    ):
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value).strip()
    return ""


def _first_href_from_nested_link(item: dict) -> str:
    for key in ("link", "links", "urlInfo", "productLink"):
        node = item.get(key)
        if isinstance(node, dict):
            for href_key in ("href", "url", "path", "pathname"):
                value = node.get(href_key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""


def _coerce_listing_product_url_candidate(text: str, page_url: str) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    lowered = text.lower()
    if any(
        fragment in lowered
        for fragment in ("/product", "/p/", "/pd/", "/item/", "/products/", "/pdps/")
    ):
        return urljoin(page_url, text)
    return ""


def _scan_payload_for_product_url(item: object, page_url: str, depth: int) -> str:
    if depth > LISTING_CARD_PRODUCT_URL_SCAN_MAX_DEPTH or not page_url:
        return ""
    if isinstance(item, dict):
        for key, value in item.items():
            lowered_key = str(key).lower()
            if isinstance(value, str) and value.strip():
                if any(
                    token in lowered_key
                    for token in (
                        "producturl",
                        "pdpurl",
                        "itemurl",
                        "canonicalurl",
                        "detailurl",
                        "product_url",
                        "pdp_url",
                    )
                ):
                    resolved = _coerce_listing_product_url_candidate(value, page_url)
                    if resolved:
                        return resolved
            nested = _scan_payload_for_product_url(value, page_url, depth + 1)
            if nested:
                return nested
    elif isinstance(item, list):
        for element in item[:LISTING_CARD_PRODUCT_URL_SCAN_MAX_LIST_ITEMS]:
            nested = _scan_payload_for_product_url(element, page_url, depth + 1)
            if nested:
                return nested
    return ""
