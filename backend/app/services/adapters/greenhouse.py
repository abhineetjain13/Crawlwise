# Greenhouse ATS board adapter.
#
# Greenhouse serves job boards via:
#   - HTML boards at boards.greenhouse.io/<company>
#   - Embedded boards using <div id="grnhse_app">
#   - JSON API at boards-api.greenhouse.io/v1/boards/<company>/jobs
from __future__ import annotations

import re
from decimal import Decimal
from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.domain_utils import normalize_domain
from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.field_value_core import clean_text
from bs4 import BeautifulSoup

_HTML_PARSER = "html.parser"
_GREENHOUSE_API_HOST = normalize_domain("https://boards-api.greenhouse.io")


class GreenhouseAdapter(BaseAdapter):
    name = "greenhouse"
    platform_family = "greenhouse"
    greenhouse_board_host = "boards.greenhouse.io"
    greenhouse_job_board_host = "job-boards.greenhouse.io"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        if "detail" in str(surface or "").lower():
            detail_record = await self._try_detail_api(url, html)
            return AdapterResult(
                records=[detail_record] if detail_record else [],
                source_type="greenhouse_adapter",
                adapter_name=self.name,
            )

        # Try JSON API first (most reliable)
        records: list[dict] = []
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
        host = normalize_domain(url)

        # boards.greenhouse.io/embed/job_board?for=<company>
        if (
            _host_matches(host, normalize_domain(f"https://{self.greenhouse_board_host}"))
            and parsed.path.startswith("/embed/job_board")
        ):
            company = parse_qs(parsed.query).get("for", [""])[0].strip()
            if company:
                return company

        # boards.greenhouse.io/<company>
        if any(
            _host_matches(host, candidate)
            for candidate in (
                normalize_domain(f"https://{self.greenhouse_board_host}"),
                normalize_domain(f"https://{self.greenhouse_job_board_host}"),
            )
        ):
            parts = parsed.path.strip("/").split("/")
            if parts and parts[0]:
                return parts[0]

        # boards-api.greenhouse.io/v1/boards/<company>/jobs
        if _host_matches(host, _GREENHOUSE_API_HOST):
            match = re.search(r"/boards/([^/]+)/", parsed.path)
            if match:
                return match.group(1)

        # Embedded: look for Greenhouse embed script
        match = re.search(r"greenhouse\.io/embed/job_board\?for=([a-zA-Z0-9_-]+)", html)
        if match:
            return match.group(1)

        match = re.search(
            rf"{re.escape(self.greenhouse_board_host)}/([a-zA-Z0-9_-]+)", html
        )
        if match:
            return match.group(1)
        match = re.search(
            rf"{re.escape(self.greenhouse_job_board_host)}/([a-zA-Z0-9_-]+)",
            html,
        )
        if match:
            return match.group(1)
        return None

    async def _try_api(self, company_slug: str) -> list[dict]:
        """Fetch jobs from Greenhouse JSON API."""
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs"
        try:
            data = await self._request_json(
                api_url,
                timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
            )
            if not isinstance(data, dict):
                return []
        except (ConnectionError, TimeoutError, ValueError, RuntimeError):
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
                "apply_url": job.get("absolute_url", ""),
                "location": location,
                "category": dept_name,
                "company": company_slug.replace("-", " ").title(),
                "posted_date": job.get("first_published", "") or job.get("updated_at", ""),
            }
            records.append(record)
        return records

    async def _try_detail_api(self, url: str, html: str) -> dict | None:
        company_slug = self._extract_company_slug(url, html)
        job_id = self._extract_job_id(url)
        if not company_slug or not job_id:
            return None
        api_url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs/{job_id}?content=true"
        try:
            data = await self._request_json(
                api_url,
                timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
            )
        except (OSError, TimeoutError, ValueError, RuntimeError):
            return None
        if not isinstance(data, dict):
            return None
        return self._normalize_detail_record(data, page_url=url)

    def _extract_from_html(self, html: str, url: str) -> list[dict]:
        """Extract jobs from the Greenhouse HTML board page."""
        soup = BeautifulSoup(html, _HTML_PARSER)
        records = []

        # Standard Greenhouse board HTML structure
        openings = soup.select(".opening, tr.job-post, [data-mapped='true']")
        for opening in openings:
            anchor = opening.select_one("a[href]")
            title_el = (
                opening.select_one(
                    ".opening-title, td.cell-title a, a .body--medium, a [class*='title'], a p"
                )
                or anchor
            )
            location_el = opening.select_one(
                ".location, .opening-location, td.cell-location"
            )
            if not title_el and not anchor:
                continue
            if anchor is None and title_el is not None:
                anchor = title_el if title_el.name == "a" else title_el.find_parent("a")
            raw_href = anchor.get("href", "") if anchor else ""
            href = raw_href if isinstance(raw_href, str) else ""
            if href and not href.startswith("http"):
                href = urljoin(url, href)
            title = clean_text(
                title_el.get_text(" ", strip=True) if title_el else ""
            )
            if not title and anchor:
                title = clean_text(anchor.get_text(" ", strip=True))
            if not title:
                continue
            if location_el is None:
                location_el = opening.select_one(
                    ".body__secondary.body--metadata, .body--metadata, a [class*='location'], a p + p",
                )
            location = clean_text(
                location_el.get_text(" ", strip=True) if location_el else ""
            )
            records.append(
                {
                    "title": title,
                    "url": href,
                    "location": location,
                }
            )

        return records

    def _normalize_detail_record(self, payload: dict, *, page_url: str) -> dict | None:
        title = clean_text(payload.get("title"))
        if not title:
            return None
        location = payload.get("location", {})
        location_name = (
            clean_text(location.get("name"))
            if isinstance(location, dict)
            else clean_text(location)
        )
        record: dict[str, object] = {
            "title": title,
            "url": clean_text(payload.get("absolute_url")) or page_url,
            "apply_url": clean_text(payload.get("absolute_url")) or page_url,
            "company": clean_text(payload.get("company_name")),
            "location": location_name or None,
            "posted_date": clean_text(
                payload.get("first_published") or payload.get("updated_at")
            ),
        }
        pay_ranges = payload.get("pay_input_ranges")
        if isinstance(pay_ranges, list) and pay_ranges:
            salary = self._normalize_pay_range(pay_ranges[0])
            if salary:
                record["salary"] = salary
        content = unescape(str(payload.get("content") or ""))
        if content:
            record.update(extract_job_sections(content))
            description = html_to_text(content)
            if description:
                record["description"] = description
        if location_name and "remote" in location_name.lower():
            record["remote"] = True
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _normalize_pay_range(self, payload: object) -> str:
        if not isinstance(payload, dict):
            return ""
        currency = clean_text(
            payload.get("currency_type", {}).get("name")
            if isinstance(payload.get("currency_type"), dict)
            else payload.get("currency_type")
        )
        min_value = self._normalize_pay_value(
            payload.get("min_cents"),
            payload.get("min_amount"),
        )
        max_value = self._normalize_pay_value(
            payload.get("max_cents"),
            payload.get("max_amount"),
        )
        interval = self._normalize_scalar_text(payload.get("title"))
        numbers = " - ".join(part for part in (min_value, max_value) if part)
        return " ".join(part for part in (currency, numbers, interval) if part).strip()

    def _normalize_pay_value(self, raw_cents: object, raw_amount: object) -> str:
        cents_text = self._normalize_scalar_text(raw_cents)
        cents_value = self._parse_int(cents_text)
        if cents_value is not None:
            whole_units, remainder = divmod(cents_value, 100)
            if remainder == 0:
                return str(whole_units)
            return f"{cents_value / 100:.2f}"
        return self._normalize_scalar_text(raw_amount)

    def _normalize_scalar_text(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, (int, float, Decimal)):
            return str(value)
        return clean_text(str(value))

    def _parse_int(self, value: object) -> int | None:
        text = self._normalize_scalar_text(value)
        if not text:
            return None
        try:
            return int(text)
        except (TypeError, ValueError):
            return None

    def _extract_job_id(self, url: str) -> str:
        match = re.search(r"/jobs/(\d+)", urlparse(str(url or "")).path)
        query_id = parse_qs(urlparse(str(url or "")).query).get("gh_jid", [""])[0]
        return clean_text(match.group(1) if match else query_id)


def _host_matches(host: str, expected: str) -> bool:
    normalized_host = str(host or "").strip().lower()
    normalized_expected = str(expected or "").strip().lower()
    return normalized_host == normalized_expected or normalized_host.endswith(
        f".{normalized_expected}"
    )
