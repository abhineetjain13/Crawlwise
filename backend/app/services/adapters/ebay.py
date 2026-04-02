# eBay platform adapter.
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter


class EbayAdapter(BaseAdapter):
    name = "ebay"
    domains = ["ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr", "ebay.ca", "ebay.com.au"]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(d in url for d in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        soup = BeautifulSoup(html, "html.parser")
        records = []
        if surface in ("ecommerce_detail",):
            record = self._extract_detail(soup, url)
            if record:
                records.append(record)
        elif surface in ("ecommerce_listing",):
            records = self._extract_listing(soup, url)
        return AdapterResult(
            records=records,
            source_type="ebay_adapter",
            confidence=0.88,
            adapter_name=self.name,
        )

    def _extract_detail(self, soup: BeautifulSoup, url: str) -> dict | None:
        title_el = soup.select_one("h1.x-item-title__mainTitle span, h1#itemTitle")
        price_el = soup.select_one(".x-price-primary span, #prcIsum")
        image_el = soup.select_one("#icImg, .ux-image-carousel-item img")
        condition_el = soup.select_one(".x-item-condition-value span, #vi-itm-cond")
        seller_el = soup.select_one(".x-sellercard-atf__info__about-seller span, .mbg-nw")
        if not title_el:
            return None
        return {
            "title": title_el.get_text(strip=True),
            "price": price_el.get_text(strip=True) if price_el else None,
            "image_url": image_el.get("src") if image_el else None,
            "availability": condition_el.get_text(strip=True) if condition_el else None,
            "brand": seller_el.get_text(strip=True) if seller_el else None,
            "url": url,
        }

    def _extract_listing(self, soup: BeautifulSoup, url: str) -> list[dict]:
        records = []
        cards = soup.select(".s-item, .srp-results .s-item__wrapper")
        for card in cards:
            title_el = card.select_one(".s-item__title span, .s-item__title")
            price_el = card.select_one(".s-item__price")
            image_el = card.select_one(".s-item__image-wrapper img")
            link_el = card.select_one(".s-item__link")
            title_text = title_el.get_text(strip=True) if title_el else ""
            if not title_text or title_text.lower() == "shop on ebay":
                continue
            records.append({
                "title": title_text,
                "price": price_el.get_text(strip=True) if price_el else None,
                "image_url": image_el.get("src") if image_el else None,
                "url": link_el.get("href", "") if link_el else "",
            })
        return records
