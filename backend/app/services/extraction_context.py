from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import NOISE_CONTAINER_REMOVAL_SELECTOR
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.structured_sources import (
    harvest_js_state_objects,
    parse_embedded_json,
    parse_json_ld,
    parse_microdata,
    parse_opengraph,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractionContext:
    original_html: str
    cleaned_html: str
    dom_parser: LexborHTMLParser
    _soup: BeautifulSoup | None = None

    @property
    def soup(self) -> BeautifulSoup:
        current = self._soup
        if current is None:
            current = BeautifulSoup(self.cleaned_html, "html.parser")
            object.__setattr__(self, "_soup", current)
        return current


def prepare_extraction_context(html: str) -> ExtractionContext:
    parser = LexborHTMLParser(html)
    try:
        for node in parser.css(NOISE_CONTAINER_REMOVAL_SELECTOR):
            tag = str(getattr(node, "tag", "") or "").strip().lower()
            if tag in {"html", "body"}:
                continue
            node.decompose()
    except Exception as exc:
        logger.debug(
            "noise_removal_failed selector=%s error=%s",
            NOISE_CONTAINER_REMOVAL_SELECTOR,
            exc,
        )
    cleaned_html = parser.html
    return ExtractionContext(
        original_html=html,
        cleaned_html=cleaned_html,
        dom_parser=parser,
    )


def collect_structured_source_payloads(
    context: ExtractionContext,
    *,
    page_url: str,
) -> tuple[tuple[str, list[dict[str, Any]]], ...]:
    json_ld_payloads = parse_json_ld(context.soup)
    skip_extruct_fallbacks = _json_ld_listing_confident(json_ld_payloads)
    js_state_objects = harvest_js_state_objects(None, context.cleaned_html)
    js_state_payloads = [
        payload for payload in js_state_objects.values() if isinstance(payload, dict)
    ]
    return (
        ("json_ld", json_ld_payloads),
        (
            "microdata",
            []
            if skip_extruct_fallbacks
            else parse_microdata(context.soup, context.cleaned_html, page_url),
        ),
        (
            "opengraph",
            []
            if skip_extruct_fallbacks
            else parse_opengraph(context.soup, context.cleaned_html, page_url),
        ),
        ("embedded_json", parse_embedded_json(context.soup, context.cleaned_html)),
        ("js_state", js_state_payloads),
    )


def _json_ld_listing_confident(payloads: list[dict[str, Any]]) -> bool:
    listing_like = 0
    for payload in payloads:
        if _looks_like_listing_payload(payload):
            listing_like += 1
        if _payload_has_item_list(payload):
            return True
    return listing_like >= max(3, int(crawler_runtime_settings.listing_min_items))


def _looks_like_listing_payload(payload: dict[str, Any]) -> bool:
    raw_type = payload.get("@type")
    normalized_type = (
        " ".join(str(item or "") for item in raw_type)
        if isinstance(raw_type, list)
        else str(raw_type or "")
    ).strip().lower()
    if "itemlist" in normalized_type:
        return True
    if any(token in normalized_type for token in ("product", "jobposting", "offer", "aggregateoffer")):
        return bool(payload.get("name") or payload.get("title") or payload.get("url"))
    return _payload_has_item_list(payload)


def _payload_has_item_list(payload: dict[str, Any]) -> bool:
    item_list = payload.get("itemListElement")
    if isinstance(item_list, list) and item_list:
        return True
    main_entity = payload.get("mainEntity")
    if isinstance(main_entity, dict):
        nested_items = main_entity.get("itemListElement")
        if isinstance(nested_items, list) and nested_items:
            return True
    return False
