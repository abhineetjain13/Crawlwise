# LinkedIn Jobs adapter.
from __future__ import annotations


from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter


class LinkedInAdapter(BaseAdapter):
    """LinkedIn job page adapter for extracting structured job data from LinkedIn detail and listing pages.
    Parameters:
        - url (str): The page URL used to identify and populate extracted job records.
        - html (str): The raw HTML content of the LinkedIn page.
        - surface (str): The page type to parse, such as "job_detail" or "job_listing".
    Processing Logic:
        - Handles only LinkedIn job URLs containing "/jobs/" or "/job/".
        - Extracts a single detailed record from job detail pages when a title is present.
        - Extracts multiple records from listing pages by iterating over job card elements.
        - Normalizes common fields such as title, company, location, job type, and apply URL."""
    name = "linkedin"
    domains = ["linkedin.com"]

    async def can_handle(self, url: str, html: str) -> bool:
        return "linkedin.com" in url and ("/jobs/" in url or "/job/" in url)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        """Extract job records from LinkedIn HTML for a given surface type.
        Parameters:
            - url (str): The source URL of the page being parsed.
            - html (str): The raw HTML content to extract data from.
            - surface (str): The page surface type, such as "job_detail" or "job_listing".
        Returns:
            - AdapterResult: An object containing extracted records, source type, and adapter name."""
        soup = BeautifulSoup(html, "html.parser")
        records = []
        if surface in ("job_detail",):
            record = self._extract_detail(soup, url)
            if record:
                records.append(record)
        elif surface in ("job_listing",):
            records = self._extract_listing(soup, url)
        return AdapterResult(
            records=records,
            source_type="linkedin_adapter",
            adapter_name=self.name,
        )

    def _extract_detail(self, soup: BeautifulSoup, url: str) -> dict | None:
        """Extract detailed job information from a BeautifulSoup-parsed job page.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML content of the job detail page.
            - url (str): The job page URL to include in the returned data.
        Returns:
            - dict | None: A dictionary containing job details such as title, company, location, job type, description, and URLs; returns None if the job title cannot be found."""
        title_el = soup.select_one(".top-card-layout__title, h1")
        company_el = soup.select_one(".topcard__org-name-link, .top-card-layout__company-name, a[data-tracking-control-name='public_jobs_topcard-org-name']")
        location_el = soup.select_one(".topcard__flavor--bullet, .top-card-layout__bullet")
        desc_el = soup.select_one(".description__text, .show-more-less-html__markup")
        criteria = soup.select(".description__job-criteria-item")
        job_type = None
        for item in criteria:
            header = item.select_one(".description__job-criteria-subheader")
            value = item.select_one(".description__job-criteria-text")
            if header and value:
                h = header.get_text(strip=True).lower()
                v = value.get_text(strip=True)
                if "employment type" in h:
                    job_type = v
        if not title_el:
            return None
        return {
            "title": title_el.get_text(strip=True),
            "company": company_el.get_text(strip=True) if company_el else None,
            "location": location_el.get_text(strip=True) if location_el else None,
            "job_type": job_type,
            "description": desc_el.get_text(" ", strip=True) if desc_el else None,
            "apply_url": url,
            "url": url,
        }

    def _extract_listing(self, soup: BeautifulSoup, url: str) -> list[dict]:
        """Extract job listing details from a parsed HTML page.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML content containing job listing cards.
            - url (str): Source page URL used for context; currently unused.
        Returns:
            - list[dict]: A list of dictionaries with keys such as title, company, location, posted_date, and apply_url."""
        records = []
        cards = soup.select(".base-card, .job-search-card, .jobs-search__results-list li")
        for card in cards:
            title_el = card.select_one(".base-search-card__title, h3")
            company_el = card.select_one(".base-search-card__subtitle a, h4 a")
            location_el = card.select_one(".job-search-card__location")
            link_el = card.select_one("a.base-card__full-link, a")
            date_el = card.select_one("time")
            if not title_el:
                continue
            records.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else None,
                "location": location_el.get_text(strip=True) if location_el else None,
                "posted_date": date_el.get("datetime") if date_el else None,
                "apply_url": link_el.get("href", "") if link_el else "",
            })
        return records
