# Indeed job board adapter.
from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter


class IndeedAdapter(BaseAdapter):
    """
    Indeed job page adapter for extracting records from job detail and job listing pages.
    Parameters:
        - url (str): Source page URL used for domain matching and record links.
        - html (str): Raw HTML content of the Indeed page.
        - surface (str): Page type selector indicating whether to parse a job detail or job listing view.
    Processing Logic:
        - Matches only Indeed domains before extraction is attempted.
        - Uses page surface to switch between single-job and multi-job parsing.
        - Returns None for detail pages when no job title is found.
        - Normalizes relative listing links to an Indeed absolute URL when needed.
    """
    name = "indeed"
    domains = ["indeed.com", "indeed.co.uk", "indeed.ca", "indeed.com.au", "indeed.co.in"]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(d in url for d in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        """Extract job records from Indeed HTML based on the page surface.
        Parameters:
            - url (str): The source page URL.
            - html (str): The HTML content to parse.
            - surface (str): The page type to extract from, such as "job_detail" or "job_listing".
        Returns:
            - AdapterResult: An object containing extracted records, source type, and adapter name."""
        soup = BeautifulSoup(html, "html.parser")
        records = []
        if surface in ("job_detail",):
            record = self._extract_detail(soup, url)
            if record:
                records.append(record)
        elif surface in ("job_listing",):
            records = self._extract_listing(soup, url, html)
        return AdapterResult(
            records=records,
            source_type="indeed_adapter",
            adapter_name=self.name,
        )

    def _extract_detail(self, soup: BeautifulSoup, url: str) -> dict | None:
        """Extract job detail information from a BeautifulSoup page and return it as a dictionary.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML document containing job detail elements.
            - url (str): Source URL for the job posting.
        Returns:
            - dict | None: A dictionary with keys such as title, company, location, salary, description, apply_url, and url; returns None if no title is found."""
        title_el = soup.select_one(".jobsearch-JobInfoHeader-title, h1")
        company_el = soup.select_one("[data-company-name] a, .jobsearch-InlineCompanyRating div a")
        location_el = soup.select_one(".jobsearch-JobInfoHeader-subtitle div:last-child, [data-testid='job-location']")
        salary_el = soup.select_one("#salaryInfoAndJobType span, [data-testid='attribute_snippet_testid']")
        desc_el = soup.select_one("#jobDescriptionText, .jobsearch-jobDescriptionText")
        if not title_el:
            return None
        return {
            "title": title_el.get_text(strip=True),
            "company": company_el.get_text(strip=True) if company_el else None,
            "location": location_el.get_text(strip=True) if location_el else None,
            "salary": salary_el.get_text(strip=True) if salary_el else None,
            "description": desc_el.get_text(" ", strip=True) if desc_el else None,
            "apply_url": url,
            "url": url,
        }

    def _extract_listing(self, soup: BeautifulSoup, url: str, html: str) -> list[dict]:
        """Extract job listing details from an Indeed job search page.
        Parameters:
            - soup (BeautifulSoup): Parsed HTML document used to locate job listing elements.
            - url (str): The page URL, included for context and link handling.
            - html (str): Raw HTML content of the page.
        Returns:
            - list[dict]: A list of job listing records containing title, company, location, salary, and apply URL."""
        records = []
        # Try embedded JSON data first (window._initialData)
        cards = soup.select(".job_seen_beacon, .tapItem, [data-jk]")
        for card in cards:
            title_el = card.select_one("h2 a span, .jobTitle span")
            company_el = card.select_one("[data-testid='company-name'], .companyName")
            location_el = card.select_one("[data-testid='text-location'], .companyLocation")
            salary_el = card.select_one(".salary-snippet-container, .estimated-salary, .metadata.salary-snippet-container")
            link_el = card.select_one("h2 a, a.jcs-JobTitle")
            if not title_el:
                continue
            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = f"https://www.indeed.com{href}"
            records.append({
                "title": title_el.get_text(strip=True),
                "company": company_el.get_text(strip=True) if company_el else None,
                "location": location_el.get_text(strip=True) if location_el else None,
                "salary": salary_el.get_text(strip=True) if salary_el else None,
                "apply_url": href,
            })
        return records
