# Amazon platform adapter.
from __future__ import annotations

import re
from urllib.parse import urlparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import AdapterResult, BaseAdapter


def _text(node: object) -> str:
    return node.text(strip=True) if node is not None else ""


def _attr(node: object, name: str) -> str | None:
    if node is None:
        return None
    value = node.attributes.get(name)
    if value is None:
        return None
    return str(value).strip() or None


class AmazonAdapter(BaseAdapter):
    name = "amazon"
    domains = [
        "amazon.com",
        "amazon.co.uk",
        "amazon.de",
        "amazon.fr",
        "amazon.it",
        "amazon.es",
        "amazon.ca",
        "amazon.in",
        "amazon.co.jp",
        "amazon.com.au",
        "amazon.com.br",
    ]

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
            source_type="amazon_adapter",
            adapter_name=self.name,
        )

    def _extract_detail(self, parser: LexborHTMLParser, url: str) -> dict | None:
        title_el = parser.css_first("#productTitle")
        price_el = parser.css_first(
            ".a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice"
        )
        brand_el = parser.css_first("#bylineInfo, .po-brand .a-span9 .a-size-base")
        rating_el = parser.css_first("#acrPopover .a-icon-alt, .a-icon-star span")
        review_el = parser.css_first("#acrCustomerReviewText")
        image_el = parser.css_first("#landingImage, #imgBlkFront")
        desc_el = parser.css_first("#productDescription p, #feature-bullets")
        avail_el = parser.css_first("#availability span")
        if not title_el:
            return None
        rating_text = _text(rating_el)
        rating_match = re.search(r"(\d+\.?\d*)", rating_text)
        review_text = _text(review_el)
        review_match = re.search(r"([\d,]+)", review_text)
        return {
            "title": _text(title_el) or None,
            "price": _text(price_el) or None,
            "brand": _text(brand_el)
            .replace("Brand: ", "")
            .replace("Visit the ", "")
            .rstrip(" Store")
            if brand_el
            else None,
            "rating": float(rating_match.group(1)) if rating_match else None,
            "review_count": int(review_match.group(1).replace(",", ""))
            if review_match
            else None,
            "image_url": _attr(image_el, "src") or _attr(image_el, "data-old-hires")
            if image_el
            else None,
            "description": desc_el.text(separator=" ", strip=True) if desc_el else None,
            "availability": _text(avail_el) or None,
            "url": url,
        }

    def _extract_listing(self, parser: LexborHTMLParser, url: str) -> list[dict]:
        records = []
        cards = parser.css("[data-component-type='s-search-result']")
        for card in cards:
            title_el = card.css_first("h2 a span")
            price_whole = card.css_first(".a-price-whole")
            price_frac = card.css_first(".a-price-fraction")
            image_el = card.css_first(".s-image")
            link_el = card.css_first("h2 a")
            rating_el = card.css_first(".a-icon-star-small span")
            price = None
            if price_whole:
                whole = _text(price_whole).rstrip(".")
                frac = _text(price_frac) if price_frac else "00"
                price = f"{whole}.{frac}"
            rating_text = _text(rating_el)
            rating_match = re.search(r"(\d+\.?\d*)", rating_text)
            href = _attr(link_el, "href") or ""
            if href and not href.startswith("http"):
                parsed = urlparse(url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            if title_el:
                records.append(
                    {
                        "title": _text(title_el),
                        "price": price,
                        "image_url": _attr(image_el, "src"),
                        "url": href,
                        "rating": float(rating_match.group(1))
                        if rating_match
                        else None,
                    }
                )
        return records
