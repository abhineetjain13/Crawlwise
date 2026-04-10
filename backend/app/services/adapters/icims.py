# iCIMS ATS board adapter.
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from app.services.adapters.base import AdapterResult, BaseAdapter
from bs4 import BeautifulSoup, Tag
from curl_cffi.requests.errors import RequestsError as CurlRequestsError

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


_ROW_RE = re.compile(
    r'<(?:tr|div|li)\s[^>]*class=["\'][^"\']*(?:iCIMS_Job|job-?row|job-?card|listitem|search-result)[^"\']*["\'][^>]*>(.*?)</(?:tr|div|li)>',
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
logger = logging.getLogger(__name__)


class ICIMSAdapter(BaseAdapter):
    name = "icims"
    domains = ["icims.com"]

    async def can_handle(self, url: str, html: str) -> bool:
        lowered_url = str(url or "").lower()
        lowered_html = str(html or "").lower()
        return (
            any(domain in lowered_url for domain in self.domains)
            or "/ajax/joblisting/" in lowered_url
            or "icims_jobstable" in lowered_html
            or "icims_mainwrapper" in lowered_html
            or "/ajax/joblisting/" in lowered_html
        )

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        if "detail" in str(surface or "").lower() or self._looks_like_detail_url(url):
            html = await self._follow_embedded_content_url(url, html)
            record = self._extract_detail(url, html)
            return AdapterResult(
                records=[record] if record else [],
                source_type="icims_adapter",
                adapter_name=self.name,
            )

        records = await self._extract_listing(url, html)
        return AdapterResult(
            records=records,
            source_type="icims_adapter",
            adapter_name=self.name,
        )

    async def _extract_listing(self, url: str, html: str) -> list[dict]:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        embedded_board_url = self._discover_embedded_board_url(url, html)
        if embedded_board_url:
            html = await self._fetch_embedded_content(url=embedded_board_url, fallback_html=html)

        inline_records = self._extract_from_listing_html(html, base_url)
        if inline_records:
            return inline_records

        endpoint = self._discover_ajax_endpoint(url, html)
        if not endpoint or curl_requests is None:
            return []

        records: list[dict] = []
        seen_urls: set[str] = set()
        for offset in range(0, 1000, 100):
            page_url = self._paginate_endpoint(endpoint, offset)
            try:
                response = await asyncio.to_thread(
                    curl_requests.get,
                    page_url,
                    impersonate="chrome110",
                    timeout=15,
                )
            except (OSError, RuntimeError, ValueError, TypeError, CurlRequestsError):
                break
            if response.status_code != 200 or not response.text:
                break
            batch = self._parse_ajax_rows(response.text, base_url)
            if not batch:
                break
            for record in batch:
                record_url = str(record.get("url") or "").strip()
                if not record_url or record_url in seen_urls:
                    continue
                seen_urls.add(record_url)
                records.append(record)
            if len(batch) < 100:
                break
        return records

    def _discover_ajax_endpoint(self, url: str, html: str) -> str | None:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        match = re.search(r"(/ajax/joblisting/\?[^\"']+)", html, flags=re.IGNORECASE)
        if match:
            endpoint = match.group(1)
            return endpoint if endpoint.startswith("http") else f"{base_url}{endpoint}"
        if "/ajax/joblisting/" in str(html or "").lower():
            return f"{base_url}/ajax/joblisting/?num_items=100&offset=0"
        return None

    def _discover_embedded_board_url(self, url: str, html: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")
        iframe = soup.select_one("iframe[src*='icims.com/jobs/search'], iframe[src*='in_iframe=1']")
        if iframe is None:
            return None
        src = str(iframe.get("src") or "").strip()
        if not src:
            return None
        return urljoin(url, src)

    async def _follow_embedded_content_url(self, url: str, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        iframe = soup.select_one("iframe[src*='in_iframe=1'], iframe[src*='icims.com/jobs/']")
        if iframe is None:
            return html
        src = str(iframe.get("src") or "").strip()
        if not src:
            return html
        embedded_url = urljoin(url, src)
        return await self._fetch_embedded_content(url=embedded_url, fallback_html=html)

    async def _fetch_embedded_content(self, *, url: str, fallback_html: str) -> str:
        if curl_requests is None:
            return fallback_html
        try:
            response = await asyncio.to_thread(
                curl_requests.get,
                url,
                impersonate="chrome110",
                timeout=15,
            )
        except (OSError, RuntimeError, ValueError, TypeError, CurlRequestsError):
            logger.exception("Failed to fetch embedded iCIMS content URL: %s", url)
            return fallback_html
        if response.status_code == 200 and response.text:
            return response.text
        return fallback_html

    def _paginate_endpoint(self, endpoint: str, offset: int) -> str:
        page_url = re.sub(r"offset=\d+", f"offset={offset}", endpoint) if "offset=" in endpoint else f"{endpoint}{'&' if '?' in endpoint else '?'}offset={offset}"
        if "num_items=" not in page_url:
            page_url = f"{page_url}{'&' if '?' in page_url else '?'}num_items=100"
        return page_url

    def _extract_from_listing_html(self, html: str, base_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select(
            ".iCIMS_JobsTable > .row, .iCIMS_JobsTable tr, .iCIMS_Job, [class*='job-card'], [class*='job-listing'], [class*='search-result'], .listitem"
        )
        records: list[dict] = []
        seen_urls: set[str] = set()
        for row in rows:
            record = self._extract_row_from_soup(row, base_url)
            if not record:
                continue
            record_url = str(record.get("url") or "").strip()
            if not record_url or record_url in seen_urls:
                continue
            seen_urls.add(record_url)
            records.append(record)
        return records

    def _parse_ajax_rows(self, html_fragment: str, base_url: str) -> list[dict]:
        soup = BeautifulSoup(html_fragment, "html.parser")
        jobs = self._extract_from_listing_html(str(soup), base_url)
        if jobs:
            return jobs

        seen_urls: set[str] = set()
        fallback_jobs: list[dict] = []
        rows = _ROW_RE.findall(html_fragment)
        for row_html in rows:
            record = self._extract_row_from_html(row_html, base_url)
            if not record:
                continue
            record_url = str(record.get("url") or "").strip()
            if not record_url or record_url in seen_urls:
                continue
            seen_urls.add(record_url)
            fallback_jobs.append(record)
        return fallback_jobs

    def _extract_row_from_soup(self, row: Tag, base_url: str) -> dict | None:
        link = row.select_one("a[href]")
        if link is None:
            return None
        title_node = link.select_one("h1, h2, h3, h4") or link
        title = self._clean_text(title_node.get_text(" ", strip=True))
        title = re.sub(r"(?i)^posting job title\s+", "", title).strip()
        if not title or len(title) < 3:
            return None
        metadata = self._extract_header_fields(row)
        record = {
            "title": title,
            "url": self._normalize_job_url(link.get("href", ""), base_url=base_url),
        }
        description = row.select_one(".description, .iCIMS_JobContent, [class*='description'], [class*='Description']")
        location = row.select_one("[class*='location'], [class*='Location'], .iCIMS_JobLocation")
        department = row.select_one("[class*='category'], [class*='Category'], [class*='department'], [class*='Department'], .iCIMS_JobCategory")
        posted = row.select_one("[class*='date'], [class*='Date'], [class*='posted'], .iCIMS_JobDate")
        if location is not None:
            value = self._clean_text(location.get_text(" ", strip=True))
            if value and value != title:
                record["location"] = value
        if department is not None:
            value = self._clean_text(department.get_text(" ", strip=True))
            if value and value != title:
                record["department"] = value
        if posted is not None:
            value = self._clean_text(posted.get_text(" ", strip=True))
            if value:
                record["posted_date"] = value
        if description is not None:
            value = self._clean_text(description.get_text(" ", strip=True))
            if value:
                record["description"] = value
        self._apply_metadata_fields(record, metadata)
        return record

    def _extract_row_from_html(self, row_html: str, base_url: str) -> dict | None:
        link_match = re.search(
            r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            row_html,
            re.IGNORECASE | re.DOTALL,
        )
        if not link_match:
            return None
        title = self._clean_text(_HTML_TAG_RE.sub("", link_match.group(2)))
        title = re.sub(r"(?i)^posting job title\s+", "", title).strip()
        if not title or len(title) < 3:
            return None
        record: dict[str, str] = {
            "title": title,
            "url": self._normalize_job_url(link_match.group(1), base_url=base_url),
        }
        for field_name, pattern in {
            "location": r'(?:class=["\'][^"\']*(?:location|Location|addr)[^"\']*["\'][^>]*>)(.*?)(?:</)',
            "department": r'(?:class=["\'][^"\']*(?:category|Category|department|Department|team|Type)[^"\']*["\'][^>]*>)(.*?)(?:</)',
            "posted_date": r'(?:class=["\'][^"\']*(?:date|Date|posted|Posted)[^"\']*["\'][^>]*>)(.*?)(?:</)',
        }.items():
            match = re.search(pattern, row_html, re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            value = self._clean_text(_HTML_TAG_RE.sub("", match.group(1)))
            if value and value != title:
                record[field_name] = value
        return record

    def _extract_detail(self, url: str, html: str) -> dict | None:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.select_one("h1, .iCIMS_JobHeader h1, [class*='jobtitle'], [class*='JobTitle']")
        if title is None:
            return None
        record = {
            "title": self._clean_text(title.get_text(" ", strip=True)),
            "url": self._normalize_job_url(url),
        }
        metadata = self._extract_header_fields(soup)
        location = soup.select_one("[class*='location'], [class*='Location'], .iCIMS_JobLocation")
        description = soup.select_one(".iCIMS_JobContent, [class*='jobdescription'], [class*='JobDescription']")
        if location is not None:
            value = self._clean_text(location.get_text(" ", strip=True))
            if value:
                record["location"] = value
        if description is not None:
            value = self._clean_text(description.get_text(" ", strip=True))
            if value:
                record["description"] = value
        self._apply_metadata_fields(record, metadata)
        return record

    def _extract_header_fields(self, node: BeautifulSoup | Tag) -> dict[str, str]:
        fields: dict[str, str] = {}
        for tag in node.select(".iCIMS_JobHeaderTag"):
            label = tag.select_one(".iCIMS_JobHeaderField, dt")
            value = tag.select_one(".iCIMS_JobHeaderData, dd")
            label_text = self._normalize_header_label(label.get_text(" ", strip=True) if label is not None else "")
            value_text = self._clean_text(value.get_text(" ", strip=True) if value is not None else "")
            if label_text and value_text and label_text not in fields:
                fields[label_text] = value_text
        return fields

    def _apply_metadata_fields(self, record: dict[str, str], fields: dict[str, str]) -> None:
        metadata_mapping = {
            "campus_location": "location",
            "location": "location",
            "job_category": "department",
            "category": "department",
            "division": "company",
            "company": "company",
            "job_type": "job_type",
            "employment_type": "job_type",
            "job_number": "job_id",
            "requisition_number": "job_id",
        }
        for source_name, target_name in metadata_mapping.items():
            value = fields.get(source_name)
            if value and not record.get(target_name):
                record[target_name] = value

    def _normalize_header_label(self, value: str) -> str:
        cleaned = self._clean_text(value).lower()
        return re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")

    def _normalize_job_url(self, value: str, *, base_url: str = "") -> str:
        resolved = urljoin(base_url, value) if base_url else str(value or "").strip()
        if not resolved:
            return ""
        parsed = urlparse(resolved)
        params = [(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True) if key != "in_iframe"]
        return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))

    def _looks_like_detail_url(self, url: str) -> bool:
        path = urlparse(str(url or "").lower()).path
        return bool(
            re.search(r"/[a-f0-9]{20,}/job/?$", path, flags=re.IGNORECASE)
            or re.search(r"/jobs?/\d+", path, flags=re.IGNORECASE)
        )

    def _clean_text(self, value: str) -> str:
        return " ".join(str(value or "").split()).strip()
