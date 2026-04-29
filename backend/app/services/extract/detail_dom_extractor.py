from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR
from app.services.field_value_core import (
    RATING_RE,
    REVIEW_COUNT_RE,
    absolute_url,
    clean_text,
    coerce_field_value,
    extract_currency_code,
    is_title_noise,
    surface_alias_lookup,
    surface_fields,
    text_or_none,
)
from app.services.field_value_dom import (
    apply_selector_fallbacks,
    extract_heading_sections,
    extract_page_images,
)

logger = logging.getLogger(__name__)


def primary_dom_context(
    context: Any,
    *,
    page_url: str,
) -> tuple[LexborHTMLParser, BeautifulSoup]:
    cleaned_parser = context.dom_parser
    cleaned_soup = context.soup
    if (
        cleaned_parser.css_first(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
        or cleaned_soup.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
    ):
        return cleaned_parser, cleaned_soup
    original_parser = LexborHTMLParser(context.original_html)
    original_soup = BeautifulSoup(context.original_html, "html.parser")
    if not (
        original_parser.css_first(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
        or original_soup.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
    ):
        return cleaned_parser, cleaned_soup
    logger.debug("Using original DOM after cleaned DOM lost primary content for %s", page_url)
    return original_parser, original_soup


def apply_dom_fallbacks(
    dom_parser: LexborHTMLParser,
    soup: BeautifulSoup,
    *,
    page_url: str,
    surface: str,
    requested_fields: list[str] | None,
    candidates: dict[str, list[object]],
    candidate_sources: dict[str, list[str]],
    field_sources: dict[str, list[str]],
    selector_trace_candidates: dict[str, list[dict[str, object]]],
    selector_rules: list[dict[str, object]] | None,
    add_sourced_candidate: Callable[..., None],
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
        add_sourced_candidate(
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
    canonical_href = canonical.get("href") if canonical is not None else None
    if canonical_href:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "url",
            absolute_url(page_url, canonical_href),
            source="dom_canonical",
        )
    images = extract_page_images(
        soup,
        page_url,
        exclude_linked_detail_images="detail" in str(surface or "").strip().lower(),
        surface=surface,
    )
    if images:
        add_sourced_candidate(
            candidates,
            candidate_sources,
            field_sources,
            selector_trace_candidates,
            "image_url",
            images[0],
            source="dom_images",
        )
        add_sourced_candidate(
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
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                normalized,
                coerce_field_value(normalized, value, page_url),
                source="dom_sections",
            )
    body_node = dom_parser.body
    body_text = clean_text(body_node.text(separator=" ", strip=True)) if body_node else ""
    if "currency" in fields and not candidates.get("currency"):
        for price_value in list(candidates.get("price") or []):
            currency_code = extract_currency_code(price_value)
            if not currency_code:
                continue
            add_sourced_candidate(
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
            add_sourced_candidate(
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
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "rating",
                rating_match.group(1),
                source="dom_text",
            )
    normalized_surface = str(surface or "")
    if normalized_surface.startswith("job_") and "remote" in fields and not candidates.get("remote"):
        lowered = body_text.lower()
        if "remote" in lowered or "work from home" in lowered:
            add_sourced_candidate(
                candidates,
                candidate_sources,
                field_sources,
                selector_trace_candidates,
                "remote",
                "remote",
                source="dom_text",
            )
