# Jibe careers adapter.
from __future__ import annotations

import asyncio
import json
import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


_SEARCH_CONFIG_RE = re.compile(r"window\.searchConfig\s*=\s*(\{.*?\});", re.DOTALL)


class JibeAdapter(BaseAdapter):
    """Adapter for detecting and extracting job listings from Jibe-powered career pages.
    Parameters:
        - url (str): Page URL used to detect Jibe signals and derive API/job identifiers.
        - html (str): Page HTML used to find embedded search config and normalize job data.
        - surface (str): Page type indicator used to adjust query defaults and filter detail pages.
    Processing Logic:
        - Detects Jibe pages using URL/domain checks and common Jibe-specific HTML markers.
        - Pulls jobs from the public `/api/jobs` endpoint and normalizes fields into a consistent record format.
        - Merges URL query parameters with embedded search config, adding listing defaults when needed.
        - Filters detail-page results to the matching job ID when one can be extracted from the URL."""
    name = "jibe"
    domains = ["jibeapply.com"]

    async def can_handle(self, url: str, html: str) -> bool:
        """Determine whether the given URL or HTML appears to belong to a Jibe-powered job search page.
        Parameters:
            - url (str): The page URL to inspect.
            - html (str): The HTML content to inspect.
        Returns:
            - bool: True if Jibe-specific markers are found in the URL or HTML; otherwise, False."""
        lowered_url = str(url or "").lower()
        lowered_html = str(html or "").lower()
        return any((
            "data-jibe-search-version" in lowered_html,
            "window._jibe" in lowered_html,
            "window.searchconfig" in lowered_html,
            "/dist/js/search.common.js" in lowered_html,
            "/api/jobs" in lowered_html,
            any(domain in lowered_url for domain in self.domains),
        ))

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        records = await self.try_public_endpoint(url, html, surface)
        return AdapterResult(
            records=records,
            source_type="jibe_adapter",
            adapter_name=self.name,
        )

    async def try_public_endpoint(
        self,
        url: str,
        html: str,
        surface: str,
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        """Try the public jobs API endpoint for a given page and return normalized job records.
        Parameters:
            - url (str): The page URL used to derive the API endpoint and base URL.
            - html (str): The page HTML used to build the query parameters.
            - surface (str): The page surface identifier, used to filter detail-page results.
            - proxy (str | None): Optional proxy URL to route the request through.
        Returns:
            - list[dict]: A list of normalized job records, or an empty list if the request fails or no jobs are found."""
        if curl_requests is None:
            return []
        parsed = urlparse(url)
        api_url = f"{parsed.scheme}://{parsed.netloc}/api/jobs"
        query = self._build_query(url, html, surface)
        request_url = api_url if not query else f"{api_url}?{urlencode(query, doseq=True)}"
        try:
            request_kwargs = {"impersonate": "chrome124", "timeout": 10}
            if proxy:
                request_kwargs["proxies"] = {"http": proxy, "https": proxy}
            response = await asyncio.to_thread(curl_requests.get, request_url, **request_kwargs)
            if response.status_code != 200:
                return []
            payload = response.json()
        except Exception:
            return []
        jobs = payload.get("jobs") if isinstance(payload, dict) else []
        if not isinstance(jobs, list):
            return []
        normalized = [self._normalize_job(row, base_url=f"{parsed.scheme}://{parsed.netloc}") for row in jobs]
        records = [row for row in normalized if row]
        if "detail" in str(surface or "").lower():
            target_id = self._extract_job_id_from_url(url)
            if target_id:
                records = [row for row in records if str(row.get("job_id") or "") == target_id]
        return records

    def _build_query(self, url: str, html: str, surface: str) -> list[tuple[str, str]]:
        """Build a merged list of query parameters from a URL, page HTML, and surface type.
        Parameters:
            - url (str): The source URL containing existing query parameters.
            - html (str): HTML content used to extract additional search configuration.
            - surface (str): Surface name used to apply listing-specific defaults.
        Returns:
            - list[tuple[str, str]]: A list of non-empty query parameter key-value pairs."""
        parsed = urlparse(url)
        query_params = parse_qsl(parsed.query, keep_blank_values=False)
        merged: dict[str, str] = {}
        for key, value in query_params:
            if value:
                merged[key] = value
        search_config = self._extract_search_config(html)
        config_query = search_config.get("query") if isinstance(search_config.get("query"), dict) else {}
        for key, value in config_query.items():
            normalized = self._normalize_query_value(value)
            if normalized and key not in merged:
                merged[key] = normalized
        if "listing" in str(surface or "").lower():
            merged.setdefault("limit", merged.get("limit") or "100")
            merged.setdefault("page", merged.get("page") or "1")
        return [(key, value) for key, value in merged.items() if value]

    def _extract_search_config(self, html: str) -> dict:
        """Extract the search configuration JSON object from HTML content.
        Parameters:
            - html (str): HTML text to search for the embedded search configuration.
        Returns:
            - dict: Parsed search configuration dictionary, or an empty dictionary if no valid configuration is found."""
        match = _SEARCH_CONFIG_RE.search(str(html or ""))
        if not match:
            return {}
        raw = match.group(1)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _normalize_query_value(self, value: object) -> str:
        text = str(value or "").strip()
        return unescape(text)

    def _normalize_job(self, row: object, *, base_url: str) -> dict | None:
        """Normalize a raw job row into a cleaned job record.
        Parameters:
            - row (object): Input row expected to be a dictionary containing a "data" payload.
            - base_url (str): Base URL used to build a job URL when a canonical URL is not provided.
        Returns:
            - dict | None: A normalized job dictionary with empty values removed, or None if the input is invalid or missing a usable title."""
        payload = row.get("data") if isinstance(row, dict) else None
        if not isinstance(payload, dict):
            return None
        title = self._clean_text(payload.get("title"))
        if not title:
            return None
        canonical_url = ""
        meta = payload.get("meta_data")
        if isinstance(meta, dict):
            canonical_url = self._clean_text(meta.get("canonical_url"))
        job_id = self._clean_text(payload.get("req_id") or payload.get("slug"))
        url = canonical_url or (urljoin(base_url, f"/jobs/{job_id}") if job_id else "")
        categories = payload.get("categories") if isinstance(payload.get("categories"), list) else []
        tags7 = payload.get("tags7")
        description_html = str(payload.get("description") or "")
        description = self._html_to_text(description_html)
        full_location = self._clean_text(payload.get("full_location"))
        if not full_location:
            full_location = ", ".join(
                part for part in [
                    self._clean_text(payload.get("location_name") or payload.get("city")),
                    self._clean_text(payload.get("state")),
                ] if part
            )
        record = {
            "title": title,
            "url": url,
            "apply_url": self._clean_text(payload.get("apply_url")),
            "job_id": job_id,
            "location": full_location or None,
            "company": self._clean_text(payload.get("hiring_organization")),
            "department": self._clean_text(payload.get("department")) or self._join_names(categories),
            "job_type": self._clean_text(payload.get("employment_type")),
            "posted_date": self._clean_text(payload.get("posted_date")),
            "description": description or None,
            "salary": self._clean_text(tags7),
            "category": self._join_names(categories),
        }
        return {key: value for key, value in record.items() if value not in (None, "", [], {})}

    def _join_names(self, values: object) -> str:
        """Join unique cleaned names from a list of values into a pipe-separated string.
        Parameters:
            - values (object): A list of items or dictionaries containing a "name" field.
        Returns:
            - str: A string of unique cleaned names joined by " | ", or an empty string if input is not a list."""
        if not isinstance(values, list):
            return ""
        names: list[str] = []
        for item in values:
            if isinstance(item, dict):
                cleaned = self._clean_text(item.get("name"))
            else:
                cleaned = self._clean_text(item)
            if cleaned and cleaned not in names:
                names.append(cleaned)
        return " | ".join(names)

    def _html_to_text(self, html: str) -> str:
        if "<" not in html or ">" not in html:
            return self._clean_text(html)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        return self._clean_text(text)

    def _extract_job_id_from_url(self, url: str) -> str:
        path = urlparse(url).path
        match = re.search(r"/jobs/(\d+)", path)
        return match.group(1) if match else ""

    def _clean_text(self, value: object) -> str:
        return " ".join(str(value or "").split()).strip()
