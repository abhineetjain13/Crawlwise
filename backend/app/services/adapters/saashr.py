# SaaSHR / UKG Ready careers adapter.
from __future__ import annotations

import asyncio
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


_COMPANY_RE = re.compile(r"/ta/([^/?#]+)\.careers", re.IGNORECASE)


class SaaSHRAdapter(BaseAdapter):
    """
    Adapter for detecting and extracting job listings from SaaShr career pages.
    Parameters:
        - url (str): Page URL used to identify and resolve the SaaShr board.
        - html (str): Page HTML used to detect embedded SaaShr career content.
        - surface (str): Surface name used to determine whether job requisitions should be fetched.
    Processing Logic:
        - Discovers the careers board URL from either the page URL or an embedded SaaShr iframe.
        - Queries the public recruitment API in paginated batches and stops when results end or a request fails.
        - Normalizes each job row into a cleaned record and removes duplicates by job ID.
        - Attempts to fetch the company name once and reuses it for all extracted records.
    """
    name = "saashr"
    domains = ["saashr.com"]

    async def can_handle(self, url: str, html: str) -> bool:
        """Determine whether the provided URL or HTML indicates a SaaShr careers page.
        Parameters:
            - url (str): The page URL to inspect.
            - html (str): The page HTML content to inspect.
        Returns:
            - bool: True if the URL or HTML matches known SaaShr indicators; otherwise False."""
        lowered_url = str(url or "").lower()
        lowered_html = str(html or "").lower()
        return (
            "saashr.com" in lowered_url
            or "secure7.saashr.com" in lowered_html
            or "inframeset=1" in lowered_html and ".careers" in lowered_html
        )

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        records = await self.try_public_endpoint(url, html, surface)
        return AdapterResult(
            records=records,
            source_type="saashr_adapter",
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
        """Try to fetch public job requisitions from a company career endpoint.
        Parameters:
            - self (object): Instance used to access helper methods for URL discovery, normalization, and company name lookup.
            - url (str): The page URL used to discover the company board endpoint.
            - html (str): HTML content used to help locate the board URL.
            - surface (str): Surface name used to determine whether the endpoint should be queried.
            - proxy (str | None): Optional proxy URL for HTTP and HTTPS requests.
        Returns:
            - list[dict]: A list of normalized job records, or an empty list if the endpoint cannot be queried or no results are found."""
        if curl_requests is None or "job" not in str(surface or "").lower():
            return []
        board_url = self._discover_board_url(url, html)
        if not board_url:
            return []
        parsed = urlparse(board_url)
        company_code = self._extract_company_code(board_url)
        if not company_code:
            return []
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        ein_id = str(params.get("ein_id") or "").strip()
        career_portal_id = str(params.get("career_portal_id") or "").strip()
        lang = str(params.get("lang") or "en-US").strip() or "en-US"
        if not ein_id or not career_portal_id:
            return []
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        request_kwargs = {"impersonate": "chrome124", "timeout": 12}
        if proxy:
            request_kwargs["proxies"] = {"http": proxy, "https": proxy}

        records: list[dict] = []
        seen_ids: set[str] = set()
        size = 50
        offset = 1
        company_name = ""
        while True:
            endpoint = (
                f"{base_url}/ta/rest/ui/recruitment/companies/%7C{company_code}/job-requisitions"
                f"?offset={offset}&size={size}&sort=desc&ein_id={ein_id}&lang={lang}&career_portal_id={career_portal_id}"
            )
            try:
                response = await asyncio.to_thread(curl_requests.get, endpoint, **request_kwargs)
                if response.status_code != 200:
                    break
                payload = response.json()
            except Exception:
                break
            if not company_name:
                company_name = await self._fetch_company_name(
                    base_url=base_url,
                    company_code=company_code,
                    ein_id=ein_id,
                    career_portal_id=career_portal_id,
                    lang=lang,
                    request_kwargs=request_kwargs,
                )
            rows = payload.get("job_requisitions") if isinstance(payload, dict) else []
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                normalized = self._normalize_row(
                    row,
                    board_url=board_url,
                    company_name=company_name,
                )
                if not normalized:
                    continue
                job_id = str(normalized.get("job_id") or "").strip()
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                records.append(normalized)
            if len(rows) < size:
                break
            offset += size
        return records

    async def _fetch_company_name(
        self,
        *,
        base_url: str,
        company_code: str,
        ein_id: str,
        career_portal_id: str,
        lang: str,
        request_kwargs: dict,
    ) -> str:
        """Fetch the company name from the recruitment job-search configuration endpoint.
        Parameters:
            - base_url (str): Base URL of the recruitment service.
            - company_code (str): Company code used to build the endpoint URL.
            - ein_id (str): Employer identification number query parameter.
            - career_portal_id (str): Career portal identifier query parameter.
            - lang (str): Language code query parameter.
            - request_kwargs (dict): Additional keyword arguments passed to the HTTP request.
        Returns:
            - str: Cleaned company name if successfully retrieved; otherwise an empty string."""
        endpoint = (
            f"{base_url}/ta/rest/ui/recruitment/companies/%7C{company_code}/job-search/config"
            f"?ein_id={ein_id}&career_portal_id={career_portal_id}&lang={lang}"
        )
        try:
            response = await asyncio.to_thread(curl_requests.get, endpoint, **request_kwargs)
            if response.status_code != 200:
                return ""
            payload = response.json()
        except Exception:
            return ""
        return self._clean_text(payload.get("comp_name")) if isinstance(payload, dict) else ""

    def _discover_board_url(self, url: str, html: str) -> str:
        """Discover the SaasHR board URL from a page URL or HTML iframe source.
        Parameters:
            - url (str): The page URL to inspect and resolve relative iframe URLs against.
            - html (str): The HTML content to search for a SaasHR careers iframe.
        Returns:
            - str: The discovered board URL, or an empty string if none is found."""
        if "saashr.com" in str(url or "").lower():
            return url
        soup = BeautifulSoup(str(html or ""), "html.parser")
        iframe = soup.select_one("iframe[src*='saashr.com/ta/'][src*='.careers']")
        if iframe is None:
            return ""
        src = str(iframe.get("src") or "").strip()
        return urljoin(url, src) if src else ""

    def _extract_company_code(self, board_url: str) -> str:
        match = _COMPANY_RE.search(urlparse(str(board_url or "")).path)
        return self._clean_text(match.group(1)) if match else ""

    def _normalize_row(self, row: object, *, board_url: str, company_name: str) -> dict | None:
        """Normalize a raw job row into a cleaned job record.
        Parameters:
            - row (object): Raw row data to normalize; expected to be a dictionary.
            - board_url (str): Base URL used to build the job detail URL.
            - company_name (str): Company name to include in the normalized record.
        Returns:
            - dict | None: Normalized job record with cleaned fields, or None if the row is invalid or incomplete."""
        if not isinstance(row, dict):
            return None
        title = self._clean_text(row.get("job_title"))
        job_id = self._clean_text(row.get("id"))
        if not title or not job_id:
            return None
        location_payload = row.get("location") if isinstance(row.get("location"), dict) else {}
        location = ", ".join(
            part
            for part in [
                self._clean_text(location_payload.get("city")),
                self._clean_text(location_payload.get("state")),
            ]
            if part
        )
        detail_url = self._build_detail_url(board_url, job_id)
        record = {
            "title": title,
            "job_id": job_id,
            "url": detail_url,
            "apply_url": detail_url,
            "location": location or None,
            "company": company_name or None,
            "description": self._clean_text(row.get("job_description")),
        }
        return {key: value for key, value in record.items() if value not in (None, "", [], {})}

    def _build_detail_url(self, board_url: str, job_id: str) -> str:
        parsed = urlparse(board_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["ShowJob"] = job_id
        query = urlencode(params)
        return parsed._replace(query=query).geturl()

    def _clean_text(self, value: object) -> str:
        return " ".join(str(value or "").split()).strip()
