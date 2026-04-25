# eBay platform adapter.
from __future__ import annotations

from collections.abc import Mapping

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import AdapterResult, BaseAdapter


def _text(node: object) -> str:
    if node is None:
        return ""
    text_fn = getattr(node, "text", None)
    if not callable(text_fn):
        return ""
    try:
        return str(text_fn(strip=True) or "")
    except Exception:
        return ""


def _attr(node: object, name: str) -> str | None:
    if node is None:
        return None
    raw_attrs = getattr(node, "attributes", {}) or {}
    attrs = raw_attrs if isinstance(raw_attrs, Mapping) else {}
    value = attrs.get(name)
    if value is None:
        return None
    return str(value).strip() or None


class EbayAdapter(BaseAdapter):
    name = "ebay"
    domains = ["ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr", "ebay.ca", "ebay.com.au"]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(d in url for d in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        parser = LexborHTMLParser(html)
        records = []
        if surface in ("ecommerce_detail",):
            record = self._extract_detail(parser, url)
            if record:
                records.append(record)
        elif surface in ("ecommerce_listing",):
            records = self._extract_listing(parser, url)
        return AdapterResult(
            records=records,
            source_type="ebay_adapter",
            adapter_name=self.name,
        )

    def _extract_detail(self, parser: LexborHTMLParser, url: str) -> dict | None:
        title_el = parser.css_first("h1.x-item-title__mainTitle span, h1#itemTitle")
        price_el = parser.css_first(".x-price-primary span, #prcIsum")
        image_el = parser.css_first("#icImg, .ux-image-carousel-item img")
        condition_el = parser.css_first(".x-item-condition-value span, #vi-itm-cond")
        seller_el = parser.css_first(
            ".x-sellercard-atf__info__about-seller span, .mbg-nw"
        )
        title = _text(title_el)
        if not title:
            return None
        return {
            "title": title,
            "price": _text(price_el) or None,
            "image_url": _attr(image_el, "src"),
            "availability": _text(condition_el) or None,
            "brand": _text(seller_el) or None,
            "url": url,
        }

    def _extract_listing(self, parser: LexborHTMLParser, url: str) -> list[dict]:
        records = []
        cards = parser.css(".s-item, .srp-results .s-item__wrapper")
        for card in cards:
            title_el = card.css_first(".s-item__title span, .s-item__title")
            price_el = card.css_first(".s-item__price")
            image_el = card.css_first(".s-item__image-wrapper img")
            link_el = card.css_first(".s-item__link")
            title_text = _text(title_el)
            if not title_text or title_text.lower() == "shop on ebay":
                continue
            records.append(
                {
                    "title": title_text,
                    "price": _text(price_el) or None,
                    "image_url": _attr(image_el, "src"),
                    "url": _attr(link_el, "href") or "",
                }
            )
        return records
