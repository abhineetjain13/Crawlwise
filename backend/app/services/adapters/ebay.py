# eBay platform adapter.
from __future__ import annotations


from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter


class EbayAdapter(BaseAdapter):
    """
    Adapter for extracting eBay product and listing data from supported eBay domains.
    Parameters:
        - url (str): Source page URL used for domain matching and record output.
        - html (str): Raw HTML content to parse and extract data from.
        - surface (str): Page type indicating whether to extract a detail or listing view.
    Processing Logic:
        - Handles only URLs containing known eBay domains.
        - Uses different extraction paths for product detail pages and search listing pages.
        - Skips invalid listing cards such as generic “Shop on eBay” entries.
        - Returns a standardized AdapterResult with extracted records and adapter metadata.
    """
    name = "ebay"
    domains = ["ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr", "ebay.ca", "ebay.com.au"]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(d in url for d in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        """Extract records from eBay detail or listing HTML based on the given surface.
        Parameters:
            - self (object): The adapter instance.
            - url (str): The source page URL.
            - html (str): The page HTML content.
            - surface (str): The page type to extract, such as "ecommerce_detail" or "ecommerce_listing".
        Returns:
            - AdapterResult: An object containing extracted records, source type, and adapter name."""
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
            adapter_name=self.name,
        )

    def _extract_detail(self, soup: BeautifulSoup, url: str) -> dict | None:
        """Extract detailed item information from a parsed HTML page.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML soup used to locate item detail elements.
            - url (str): The source URL of the item page.
        Returns:
            - dict | None: A dictionary containing title, price, image_url, availability, brand, and url, or None if no title is found."""
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
        """Extract listing data from parsed eBay search result HTML.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML document to search for listing cards.
            - url (str): Source page URL.
        Returns:
            - list[dict]: A list of listing records, each containing title, price, image_url, and url."""
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
