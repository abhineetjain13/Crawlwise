from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import NOISE_CONTAINER_REMOVAL_SELECTOR
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
    soup: BeautifulSoup


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
        soup=BeautifulSoup(cleaned_html, "html.parser"),
    )


def collect_structured_source_payloads(
    context: ExtractionContext,
    *,
    page_url: str,
) -> tuple[tuple[str, list[dict[str, Any]]], ...]:
    js_state_objects = harvest_js_state_objects(context.soup, context.cleaned_html)
    js_state_payloads = [
        payload for payload in js_state_objects.values() if isinstance(payload, dict)
    ]
    return (
        ("json_ld", parse_json_ld(context.soup)),
        ("microdata", parse_microdata(context.soup, context.cleaned_html, page_url)),
        ("opengraph", parse_opengraph(context.soup, context.cleaned_html, page_url)),
        ("embedded_json", parse_embedded_json(context.soup, context.cleaned_html)),
        ("js_state", js_state_payloads),
    )


def collect_js_state_objects(context: ExtractionContext) -> dict[str, Any]:
    return harvest_js_state_objects(context.soup, context.cleaned_html)
