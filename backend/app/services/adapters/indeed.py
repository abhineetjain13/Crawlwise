# Indeed job board adapter.
from __future__ import annotations

from app.services.adapters.base import AdapterResult, BaseAdapter
from bs4 import BeautifulSoup


class IndeedAdapter(BaseAdapter):
    name = "indeed"
    platform_family = "indeed"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
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
