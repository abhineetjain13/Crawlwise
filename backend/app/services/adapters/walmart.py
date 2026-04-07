# Walmart platform adapter.
from __future__ import annotations

import json
from json import loads as parse_json

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter


class WalmartAdapter(BaseAdapter):
    """Adapter for extracting Walmart product data from detail and listing pages.
    Parameters:
        - url (str): Source page URL used to populate record links and identify the page.
        - html (str): Raw HTML content to parse for embedded JSON and fallback DOM data.
        - surface (str): Page type indicating whether to extract a single product detail or a listing page.
    Processing Logic:
        - Prefers Walmart's embedded __NEXT_DATA__ JSON for product and search result extraction.
        - Falls back to basic DOM selectors for detail pages when structured JSON is unavailable.
        - Filters listing results to include only product items and builds canonical Walmart URLs.
    """
    name = "walmart"
    domains = ["walmart.com", "walmart.ca"]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(d in url for d in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        """Extract product records from Walmart HTML for detail or listing pages.
        Parameters:
            - url (str): The source page URL.
            - html (str): The raw HTML content to parse.
            - surface (str): The page type to extract from, such as "ecommerce_detail" or "ecommerce_listing".
        Returns:
            - AdapterResult: An object containing extracted records, source type, and adapter name."""
        soup = BeautifulSoup(html, "html.parser")
        records = []
        # Walmart embeds __NEXT_DATA__ with product info
        next_data = self._get_next_data(soup)
        if surface in ("ecommerce_detail",):
            record = self._extract_detail(soup, next_data, url)
            if record:
                records.append(record)
        elif surface in ("ecommerce_listing",):
            records = self._extract_listing(soup, next_data, url)
        return AdapterResult(
            records=records,
            source_type="walmart_adapter",
            adapter_name=self.name,
        )

    def _get_next_data(self, soup: BeautifulSoup) -> dict:
        """Extract the JSON data embedded in the page's __NEXT_DATA__ script tag.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML document to search for the Next.js data script.
        Returns:
            - dict: Parsed JSON data from the script tag, or an empty dictionary if the tag is missing or invalid."""
        node = soup.select_one("script#__NEXT_DATA__")
        if node and node.string:
            try:
                return parse_json(node.string)
            except json.JSONDecodeError:
                pass
        return {}

    def _extract_detail(self, soup: BeautifulSoup, next_data: dict, url: str) -> dict | None:
        # Try __NEXT_DATA__ first
        """Extract product details from Next.js data or the page DOM.
        Parameters:
            - self (object): Instance of the containing class.
            - soup (BeautifulSoup): Parsed HTML used as a fallback source.
            - next_data (dict): Parsed __NEXT_DATA__ JSON payload from the page.
            - url (str): Product page URL.
        Returns:
            - dict | None: A dictionary of product details such as title, brand, price, image URL, description, rating, review count, availability, category, and URL; or None if no product data is found."""
        props = next_data.get("props", {}).get("pageProps", {})
        initial_data = props.get("initialData", {}).get("data", {})
        product = initial_data.get("product", {})
        if product:
            price_info = product.get("priceInfo", {}).get("currentPrice", {})
            return {
                "title": product.get("name"),
                "brand": product.get("brand"),
                "price": str(price_info.get("price", "")) if price_info.get("price") else None,
                "image_url": product.get("imageInfo", {}).get("thumbnailUrl"),
                "description": product.get("shortDescription"),
                "rating": product.get("averageRating"),
                "review_count": product.get("numberOfReviews"),
                "availability": "in_stock" if product.get("availabilityStatus") == "IN_STOCK" else product.get("availabilityStatus"),
                "category": product.get("category", {}).get("path", [{}])[-1].get("name") if product.get("category") else None,
                "url": url,
            }
        # Fallback to DOM
        title_el = soup.select_one("[itemprop='name'], h1")
        price_el = soup.select_one("[itemprop='price'], [data-automation-id='product-price'] span")
        if title_el:
            return {
                "title": title_el.get_text(strip=True),
                "price": price_el.get_text(strip=True) if price_el else None,
                "url": url,
            }
        return None

    def _extract_listing(self, soup: BeautifulSoup, next_data: dict, url: str) -> list[dict]:
        """Extract product listing data from Walmart search result page data.
        Parameters:
            - self (object): The instance of the class containing this method.
            - soup (BeautifulSoup): Parsed HTML document; included for interface consistency.
            - next_data (dict): Parsed __NEXT_DATA__ JSON containing search result information.
            - url (str): The source page URL; included for interface consistency.
        Returns:
            - list[dict]: A list of product records with title, price, image URL, canonical URL, rating, and review count."""
        records = []
        # Try __NEXT_DATA__ search results
        props = next_data.get("props", {}).get("pageProps", {})
        initial_data = props.get("initialData", {}).get("searchResult", {})
        items = initial_data.get("itemStacks", [{}])
        for stack in items if isinstance(items, list) else [items]:
            for item in stack.get("items", []):
                if item.get("__typename") != "Product":
                    continue
                price_info = item.get("priceInfo", {}).get("currentPrice", {})
                records.append({
                    "title": item.get("name"),
                    "price": str(price_info.get("price", "")) if price_info.get("price") else None,
                    "image_url": item.get("imageInfo", {}).get("thumbnailUrl"),
                    "url": f"https://www.walmart.com{item.get('canonicalUrl', '')}",
                    "rating": item.get("averageRating"),
                    "review_count": item.get("numberOfReviews"),
                })
        return records
