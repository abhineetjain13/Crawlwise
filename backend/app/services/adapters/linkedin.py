# LinkedIn Jobs adapter.
from __future__ import annotations

from app.services.adapters.base import AdapterResult, BaseAdapter
from bs4 import BeautifulSoup


class LinkedInAdapter(BaseAdapter):
    name = "linkedin"
    platform_family = "linkedin"

    async def can_handle(self, url: str, html: str) -> bool:
        lowered_url = str(url or "").lower()
        return self._matches_platform_family(url, html) and (
            "/jobs/" in lowered_url or "/job/" in lowered_url
        )

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
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
