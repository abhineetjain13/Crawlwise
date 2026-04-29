# eBay platform adapter.
from __future__ import annotations

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import (
    AdapterResult,
    BaseAdapter,
    selectolax_node_attr,
    selectolax_node_text,
)


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
        return self._result(records)

    def _extract_detail(self, parser: LexborHTMLParser, url: str) -> dict | None:
        title_el = parser.css_first("h1.x-item-title__mainTitle span, h1#itemTitle")
        price_el = parser.css_first(".x-price-primary span, #prcIsum")
        image_el = parser.css_first("#icImg, .ux-image-carousel-item img")
        condition_el = parser.css_first(".x-item-condition-value span, #vi-itm-cond")
        seller_el = parser.css_first(
            ".x-sellercard-atf__info__about-seller span, .mbg-nw"
        )
        title = selectolax_node_text(title_el)
        if not title:
            return None
        return {
            "title": title,
            "price": selectolax_node_text(price_el) or None,
            "image_url": selectolax_node_attr(image_el, "src"),
            "availability": selectolax_node_text(condition_el) or None,
            "brand": selectolax_node_text(seller_el) or None,
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
            title_text = selectolax_node_text(title_el)
            if not title_text or title_text.lower() == "shop on ebay":
                continue
            records.append(
                {
                    "title": title_text,
                    "price": selectolax_node_text(price_el) or None,
                    "image_url": selectolax_node_attr(image_el, "src"),
                    "url": selectolax_node_attr(link_el, "href") or "",
                }
            )
        return records
