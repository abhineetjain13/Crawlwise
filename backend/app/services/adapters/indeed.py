# Indeed job board adapter.
from __future__ import annotations

from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import (
    AdapterResult,
    BaseAdapter,
    selectolax_node_attr,
    selectolax_node_text,
)


class IndeedAdapter(BaseAdapter):
    name = "indeed"
    platform_family = "indeed"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        parser = LexborHTMLParser(html)
        records = []
        if surface in ("job_detail",):
            record = self._extract_detail(parser, url)
            if record:
                records.append(record)
        elif surface in ("job_listing",):
            records = self._extract_listing(parser, url)
        return self._result(records)

    def _extract_detail(self, parser: LexborHTMLParser, url: str) -> dict | None:
        title_el = parser.css_first(".jobsearch-JobInfoHeader-title, h1")
        company_el = parser.css_first(
            "[data-company-name] a, .jobsearch-InlineCompanyRating div a"
        )
        location_el = parser.css_first(
            ".jobsearch-JobInfoHeader-subtitle div:last-child, [data-testid='job-location']"
        )
        salary_el = parser.css_first(
            "#salaryInfoAndJobType span, [data-testid='attribute_snippet_testid']"
        )
        desc_el = parser.css_first("#jobDescriptionText, .jobsearch-jobDescriptionText")
        if not title_el:
            return None
        return {
            "title": selectolax_node_text(title_el),
            "company": selectolax_node_text(company_el) or None,
            "location": selectolax_node_text(location_el) or None,
            "salary": selectolax_node_text(salary_el) or None,
            "description": selectolax_node_text(desc_el, separator=" ") or None,
            "apply_url": url,
            "url": url,
        }

    def _extract_listing(self, parser: LexborHTMLParser, url: str) -> list[dict]:
        records = []
        parsed_url = urlsplit(str(url or "").strip())
        base_origin = (
            f"{parsed_url.scheme}://{parsed_url.netloc}"
            if parsed_url.scheme and parsed_url.netloc
            else "https://www.indeed.com"
        )
        cards = parser.css(".job_seen_beacon, .tapItem, [data-jk]")
        for card in cards:
            title_el = card.css_first("h2 a span, .jobTitle span")
            company_el = card.css_first("[data-testid='company-name'], .companyName")
            location_el = card.css_first(
                "[data-testid='text-location'], .companyLocation"
            )
            salary_el = card.css_first(
                ".salary-snippet-container, .estimated-salary, .metadata.salary-snippet-container"
            )
            link_el = card.css_first("h2 a, a.jcs-JobTitle")
            if not title_el:
                continue
            href = selectolax_node_attr(link_el, "href") or ""
            if href and not href.startswith("http"):
                href = (
                    f"{base_origin}{href}"
                    if href.startswith("/")
                    else f"{base_origin}/{href.lstrip('/')}"
                )
            records.append(
                {
                    "title": selectolax_node_text(title_el),
                    "company": selectolax_node_text(company_el) or None,
                    "location": selectolax_node_text(location_el) or None,
                    "salary": selectolax_node_text(salary_el) or None,
                    "apply_url": href,
                }
            )
        return records
