# Oracle HCM Candidate Experience adapter.
from __future__ import annotations

import asyncio
import ast
import json
import re
from html import unescape
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


_CX_CONFIG_RE = re.compile(r"var\s+CX_CONFIG\s*=\s*(\{.*?\})\s*;", re.DOTALL)
_SITE_PATH_RE = re.compile(r"/sites/([^/?#]+)", re.IGNORECASE)
_LANG_PATH_RE = re.compile(r"/CandidateExperience/([^/?#]+)/sites/", re.IGNORECASE)
_JOB_PATH_RE = re.compile(r"/job/([^/?#]+)/?", re.IGNORECASE)
_DEFAULT_FACETS = "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS"


class OracleHCMAdapter(BaseAdapter):
    name = "oracle_hcm"
    domains = ["fa.ocs.oraclecloud.com"]

    async def can_handle(self, url: str, html: str) -> bool:
        lowered_url = str(url or "").lower()
        lowered_html = str(html or "").lower()
        return any((
            any(domain in lowered_url for domain in self.domains),
            "/hcmui/candidateexperience/" in lowered_url,
            "var cx_config" in lowered_html,
            "candidateexperience" in lowered_html and "oraclecloud.com" in lowered_html,
            "recruitingcejobrequisitions" in lowered_html,
        ))

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        records = await self.try_public_endpoint(url, html, surface)
        return AdapterResult(
            records=records,
            source_type="oracle_hcm_adapter",
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
        if curl_requests is None or "job" not in str(surface or "").lower():
            return []

        parsed = urlparse(url)
        site_number = self._extract_site_number(url, html)
        if not site_number:
            return []
        site_lang = self._extract_site_lang(url, html) or "en"
        company = self._extract_site_name(html)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        request_kwargs = {"impersonate": "chrome124", "timeout": 12}
        if proxy:
            request_kwargs["proxies"] = {"http": proxy, "https": proxy}

        target_job_id = self._extract_job_id_from_url(url) if "detail" in str(surface or "").lower() else ""
        page_size = 100 if "listing" in str(surface or "").lower() else 25
        offset = 0
        records: list[dict] = []
        seen_job_ids: set[str] = set()

        while True:
            endpoint = self._build_endpoint(
                base_url=base_url,
                site_number=site_number,
                limit=page_size,
                offset=offset,
            )
            try:
                response = await asyncio.to_thread(curl_requests.get, endpoint, **request_kwargs)
                if response.status_code != 200:
                    break
                payload = response.json()
            except Exception:
                break

            items = payload.get("items") if isinstance(payload, dict) else []
            if not isinstance(items, list) or not items:
                break

            response_item_count = len(items)
            batch_count = 0
            for item in items:
                requisitions = item.get("requisitionList") if isinstance(item, dict) else None
                if not isinstance(requisitions, list):
                    continue
                for requisition in requisitions:
                    normalized = self._normalize_requisition(
                        requisition,
                        base_url=base_url,
                        site_lang=site_lang,
                        site_number=site_number,
                        company=company,
                    )
                    if not normalized:
                        continue
                    job_id = str(normalized.get("job_id") or "").strip()
                    if target_job_id and job_id != target_job_id:
                        continue
                    if job_id and job_id in seen_job_ids:
                        continue
                    if job_id:
                        seen_job_ids.add(job_id)
                    records.append(normalized)
                    batch_count += 1
                    if target_job_id and job_id == target_job_id:
                        return [normalized]

            if response_item_count < page_size:
                break
            offset += page_size

        return records

    def _build_endpoint(self, *, base_url: str, site_number: str, limit: int, offset: int) -> str:
        finder = (
            f"findReqs;siteNumber={site_number},facetsList={_DEFAULT_FACETS},"
            f"offset={offset},limit={limit},sortBy=POSTING_DATES_DESC"
        )
        expand = (
            "requisitionList.workLocation,requisitionList.otherWorkLocations,"
            "requisitionList.secondaryLocations,flexFieldsFacet.values,requisitionList.requisitionFlexFields"
        )
        return (
            f"{base_url}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand={expand}&finder={finder}"
        )

    def _normalize_requisition(
        self,
        requisition: object,
        *,
        base_url: str,
        site_lang: str,
        site_number: str,
        company: str,
    ) -> dict | None:
        if not isinstance(requisition, dict):
            return None
        title = self._clean_text(requisition.get("Title"))
        job_id = self._clean_text(requisition.get("Id"))
        if not title or not job_id:
            return None

        description_parts = [
            self._html_to_text(requisition.get("ShortDescriptionStr")),
            self._html_to_text(requisition.get("ExternalResponsibilitiesStr")),
            self._html_to_text(requisition.get("ExternalQualificationsStr")),
        ]
        description = "\n\n".join(part for part in description_parts if part)
        location = self._join_locations(requisition)
        department = self._clean_text(requisition.get("Department"))
        category = self._clean_text(
            requisition.get("Organization")
            or requisition.get("JobFunction")
            or requisition.get("JobFamily")
        )
        job_type = self._clean_text(
            requisition.get("JobType")
            or requisition.get("WorkerType")
            or requisition.get("ContractType")
            or requisition.get("JobSchedule")
            or requisition.get("WorkplaceType")
        )
        record = {
            "title": title,
            "url": f"{base_url}/hcmUI/CandidateExperience/{site_lang}/sites/{site_number}/job/{job_id}/",
            "apply_url": f"{base_url}/hcmUI/CandidateExperience/{site_lang}/sites/{site_number}/job/{job_id}/",
            "job_id": job_id,
            "posted_date": self._clean_text(requisition.get("PostedDate")),
            "location": location or None,
            "company": company or None,
            "department": department or None,
            "category": category or department or None,
            "job_type": job_type or None,
            "description": description or None,
        }
        return {key: value for key, value in record.items() if value not in (None, "", [], {})}

    def _extract_site_number(self, url: str, html: str) -> str:
        path_match = _SITE_PATH_RE.search(urlparse(str(url or "")).path)
        if path_match:
            return self._clean_text(path_match.group(1))
        config = self._extract_cx_config(html)
        app = config.get("app") if isinstance(config.get("app"), dict) else {}
        return self._clean_text(app.get("siteNumber"))

    def _extract_site_lang(self, url: str, html: str) -> str:
        path_match = _LANG_PATH_RE.search(urlparse(str(url or "")).path)
        if path_match:
            return self._clean_text(path_match.group(1))
        config = self._extract_cx_config(html)
        app = config.get("app") if isinstance(config.get("app"), dict) else {}
        return self._clean_text(app.get("siteLang"))

    def _extract_site_name(self, html: str) -> str:
        config = self._extract_cx_config(html)
        app = config.get("app") if isinstance(config.get("app"), dict) else {}
        site_name = self._clean_text(app.get("siteName"))
        if site_name:
            return site_name
        soup = BeautifulSoup(str(html or ""), "html.parser")
        meta = soup.find("meta", attrs={"property": "og:site_name"})
        if meta is not None:
            return self._clean_text(meta.get("content"))
        return self._clean_text(soup.title.get_text(" ", strip=True) if soup.title is not None else "")

    def _extract_cx_config(self, html: str) -> dict:
        match = _CX_CONFIG_RE.search(str(html or ""))
        if not match:
            return {}
        raw = unescape(match.group(1))
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                try:
                    parsed = json.loads(raw.replace("'", '"'))
                except json.JSONDecodeError:
                    return {}
        return parsed if isinstance(parsed, dict) else {}

    def _extract_job_id_from_url(self, url: str) -> str:
        path = urlparse(str(url or "")).path
        match = _JOB_PATH_RE.search(path)
        return self._clean_text(match.group(1)) if match else ""

    def _join_locations(self, requisition: dict) -> str:
        values: list[str] = []
        primary = self._clean_text(requisition.get("PrimaryLocation"))
        if primary:
            values.append(primary)
        for key in ("workLocation", "otherWorkLocations", "secondaryLocations"):
            payload = requisition.get(key)
            if not isinstance(payload, list):
                continue
            for item in payload:
                if not isinstance(item, dict):
                    continue
                parts = [
                    self._clean_text(item.get("TownOrCity")),
                    self._clean_text(item.get("Region2")),
                    self._clean_text(item.get("Country")),
                ]
                location = ", ".join(part for part in parts if part)
                if not location:
                    location = self._clean_text(item.get("LocationName"))
                if location and location not in values:
                    values.append(location)
        return " | ".join(values)

    def _html_to_text(self, value: object) -> str:
        html = str(value or "").strip()
        if not html:
            return ""
        if "<" not in html or ">" not in html:
            return self._clean_text(html)
        soup = BeautifulSoup(html, "html.parser")
        return self._clean_text(soup.get_text(" ", strip=True))

    def _clean_text(self, value: object) -> str:
        return " ".join(str(value or "").split()).strip()
