# Amazon platform adapter.
from __future__ import annotations

import re

from app.services.adapters.base import AdapterResult, BaseAdapter
from bs4 import BeautifulSoup


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
            source_type="amazon_adapter",
            adapter_name=self.name,
        )

    def _extract_detail(self, soup: BeautifulSoup, url: str) -> dict | None:
        title_el = soup.select_one("#productTitle")
        price_el = soup.select_one(
            ".a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice"
        )
        brand_el = soup.select_one("#bylineInfo, .po-brand .a-span9 .a-size-base")
        rating_el = soup.select_one("#acrPopover .a-icon-alt, .a-icon-star span")
        review_el = soup.select_one("#acrCustomerReviewText")
        image_el = soup.select_one("#landingImage, #imgBlkFront")
        desc_el = soup.select_one("#productDescription p, #feature-bullets")
        avail_el = soup.select_one("#availability span")
        if not title_el:
            return None
        rating_text = rating_el.get_text(strip=True) if rating_el else ""
        rating_match = re.search(r"(\d+\.?\d*)", rating_text)
        review_text = review_el.get_text(strip=True) if review_el else ""
        review_match = re.search(r"([\d,]+)", review_text)
        return {
            "title": title_el.get_text(strip=True) if title_el else None,
            "price": price_el.get_text(strip=True) if price_el else None,
            "brand": brand_el.get_text(strip=True)
            .replace("Brand: ", "")
            .replace("Visit the ", "")
            .rstrip(" Store")
            if brand_el
            else None,
            "rating": float(rating_match.group(1)) if rating_match else None,
            "review_count": int(review_match.group(1).replace(",", ""))
            if review_match
            else None,
            "image_url": image_el.get("src") or image_el.get("data-old-hires")
            if image_el
            else None,
            "description": desc_el.get_text(" ", strip=True) if desc_el else None,
            "availability": avail_el.get_text(strip=True) if avail_el else None,
            "url": url,
        }

    def _extract_listing(self, soup: BeautifulSoup, url: str) -> list[dict]:
        records = []
        cards = soup.select("[data-component-type='s-search-result']")
        for card in cards:
            title_el = card.select_one("h2 a span")
            price_whole = card.select_one(".a-price-whole")
            price_frac = card.select_one(".a-price-fraction")
            image_el = card.select_one(".s-image")
            link_el = card.select_one("h2 a")
            rating_el = card.select_one(".a-icon-star-small span")
            price = None
            if price_whole:
                whole = price_whole.get_text(strip=True).rstrip(".")
                frac = price_frac.get_text(strip=True) if price_frac else "00"
                price = f"{whole}.{frac}"
            rating_text = rating_el.get_text(strip=True) if rating_el else ""
            rating_match = re.search(r"(\d+\.?\d*)", rating_text)
            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = f"https://www.amazon.com{href}"
            if title_el:
                records.append(
                    {
                        "title": title_el.get_text(strip=True),
                        "price": price,
                        "image_url": image_el.get("src") if image_el else None,
                        "url": href,
                        "rating": float(rating_match.group(1))
                        if rating_match
                        else None,
                    }
                )
        return records
