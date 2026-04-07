# Amazon platform adapter.
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter


class AmazonAdapter(BaseAdapter):
    """
    Amazon HTML adapter for extracting product and listing data from Amazon pages.
    Parameters:
        - url (str): Source page URL used to associate extracted data with the page.
        - html (str): HTML content to parse for product or listing information.
        - surface (str): Extraction mode indicating detail or listing page handling.
    Processing Logic:
        - Identifies Amazon pages by checking whether the URL contains a supported Amazon domain.
        - On detail pages, extracts a single product record only when a title element is present.
        - Parses rating and review counts from text using regular expressions.
        - On listing pages, iterates through search result cards and normalizes relative product links to absolute Amazon URLs.
    """
    name = "amazon"
    domains = ["amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr",
               "amazon.it", "amazon.es", "amazon.ca", "amazon.in",
               "amazon.co.jp", "amazon.com.au", "amazon.com.br"]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(d in url for d in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        """Extract product records from Amazon detail or listing page HTML.
        Parameters:
            - url (str): The page URL used to associate extracted records with the source page.
            - html (str): The HTML content to parse and extract records from.
            - surface (str): The extraction mode, such as "ecommerce_detail" or "ecommerce_listing".
        Returns:
            - AdapterResult: An object containing the extracted records, source type, and adapter name."""
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
        """Extract detailed product information from an Amazon product page HTML soup.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML content of the product page.
            - url (str): Source URL of the product page.
        Returns:
            - dict | None: A dictionary containing product details such as title, price, brand, rating, review count, image URL, description, availability, and URL; returns None if no title is found."""
        title_el = soup.select_one("#productTitle")
        price_el = soup.select_one(".a-price .a-offscreen, #priceblock_ourprice, #priceblock_dealprice")
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
            "brand": brand_el.get_text(strip=True).replace("Brand: ", "").replace("Visit the ", "").rstrip(" Store") if brand_el else None,
            "rating": float(rating_match.group(1)) if rating_match else None,
            "review_count": int(review_match.group(1).replace(",", "")) if review_match else None,
            "image_url": image_el.get("src") or image_el.get("data-old-hires") if image_el else None,
            "description": desc_el.get_text(" ", strip=True) if desc_el else None,
            "availability": avail_el.get_text(strip=True) if avail_el else None,
            "url": url,
        }

    def _extract_listing(self, soup: BeautifulSoup, url: str) -> list[dict]:
        """Extract listing details from Amazon search result cards.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML containing search result cards.
            - url (str): Source page URL. 
        Returns:
            - list[dict]: A list of dictionaries with listing fields such as title, price, image_url, url, and rating."""
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
                records.append({
                    "title": title_el.get_text(strip=True),
                    "price": price,
                    "image_url": image_el.get("src") if image_el else None,
                    "url": href,
                    "rating": float(rating_match.group(1)) if rating_match else None,
                })
        return records
