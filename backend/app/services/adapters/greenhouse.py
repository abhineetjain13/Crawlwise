# Greenhouse ATS board adapter.
#
# Greenhouse serves job boards via:
#   - HTML boards at boards.greenhouse.io/<company>
#   - Embedded boards using <div id="grnhse_app">
#   - JSON API at boards-api.greenhouse.io/v1/boards/<company>/jobs
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


class GreenhouseAdapter(BaseAdapter):
    name = "greenhouse"
    greenhouse_board_host = "boards.greenhouse.io"
    domains = [greenhouse_board_host, "boards-api.greenhouse.io"]

    async def can_handle(self, url: str, html: str) -> bool:
        if any(d in url for d in self.domains):
            return True
        # Embedded Greenhouse boards on company domains
        if "greenhouse.io" in html and ("grnhse_app" in html or "greenhouse" in html.lower()):
            return True
        return False

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        records: list[dict] = []

        # Try JSON API first (most reliable)
        company_slug = self._extract_company_slug(url, html)
        if company_slug:
            api_records = await self._try_api(company_slug)
            if api_records:
                records.extend(api_records)

        # Fall back to HTML parsing
        if not records:
            records = self._extract_from_html(html, url)

        return AdapterResult(
            records=records,
            source_type="greenhouse_adapter",
            adapter_name=self.name,
        )

    def _extract_company_slug(self, url: str, html: str) -> str | None:
        """Extract the company slug from URL or embedded script."""
        parsed = urlparse(url)

        # boards.greenhouse.io/embed/job_board?for=<company>
        if self.greenhouse_board_host in parsed.netloc and parsed.path.startswith("/embed/job_board"):
            company = parse_qs(parsed.query).get("for", [""])[0].strip()
            if company:
                return company

        # boards.greenhouse.io/<company>
        if self.greenhouse_board_host in parsed.netloc:
            parts = parsed.path.strip("/").split("/")
            if parts and parts[0]:
                return parts[0]

        # boards-api.greenhouse.io/v1/boards/<company>/jobs
        if "boards-api.greenhouse.io" in parsed.netloc:
            match = re.search(r"/boards/([^/]+)/", parsed.path)
            if match:
                return match.group(1)

        # Embedded: look for Greenhouse embed script
        match = re.search(r'greenhouse\.io/embed/job_board\?for=([a-zA-Z0-9_-]+)', html)
        if match:
            return match.group(1)

        match = re.search(rf"{re.escape(self.greenhouse_board_host)}/([a-zA-Z0-9_-]+)", html)
        if match:
            return match.group(1)

        return None

    async def _try_api(self, company_slug: str) -> list[dict]:
        """Fetch jobs from Greenhouse JSON API."""
        if curl_requests is None:
            return []
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
        try:
            resp = await asyncio.to_thread(
                curl_requests.get,
                api_url,
                impersonate="chrome110",
                timeout=10,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception:
            return []

        jobs = data.get("jobs", [])
        records = []
        for job in jobs:
            location = job.get("location", {})
            if isinstance(location, dict):
                location = location.get("name", "")

            departments = job.get("departments", [])
            if departments and isinstance(departments[0], dict):
                dept_name = departments[0].get("name", "")
            elif departments and isinstance(departments[0], str):
                dept_name = departments[0]
            else:
                dept_name = ""

            record = {
                "title": job.get("title", ""),
                "url": job.get("absolute_url", ""),
                "location": location,
                "category": dept_name,
                "company": company_slug.replace("-", " ").title(),
                "publication_date": job.get("updated_at", ""),
            }
            records.append(record)
        return records

    def _extract_from_html(self, html: str, url: str) -> list[dict]:
        """Extract jobs from the Greenhouse HTML board page."""
        soup = BeautifulSoup(html, "html.parser")
        records = []

        # Standard Greenhouse board HTML structure
        openings = soup.select(".opening, tr.job-post, [data-mapped='true']")
        for opening in openings:
            anchor = opening.select_one("a[href]")
            title_el = (
                opening.select_one(".opening-title, td.cell-title a, a .body--medium, a [class*='title'], a p")
                or anchor
            )
            location_el = opening.select_one(".location, .opening-location, td.cell-location")
            if not title_el and not anchor:
                continue
            if anchor is None and title_el is not None:
                anchor = title_el if title_el.name == "a" else title_el.find_parent("a")
            href = anchor.get("href", "") if anchor else ""
            if href and not href.startswith("http"):
                href = urljoin(url, href)
            title = self._clean_text(title_el.get_text(" ", strip=True) if title_el else "")
            if not title and anchor:
                title = self._clean_text(anchor.get_text(" ", strip=True))
            if not title:
                continue
            if location_el is None:
                location_el = opening.select_one(
                    ".body__secondary.body--metadata, .body--metadata, a [class*='location'], a p + p",
                )
            location = self._clean_text(location_el.get_text(" ", strip=True) if location_el else "")
            records.append({
                "title": title,
                "url": href,
                "location": location,
            })

        return records

    def _clean_text(self, value: str) -> str:
        return " ".join(str(value or "").split()).strip()
