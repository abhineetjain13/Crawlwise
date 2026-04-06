# Paycom ATS adapter.
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

from app.services.adapters.base import AdapterResult, BaseAdapter

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


_CONFIG_RE = re.compile(r"var configsFromHost = (\{.*?\});\s*var Mountable", re.DOTALL)
_JOB_ID_RE = re.compile(r"/jobs/(\d+)", re.IGNORECASE)


class PaycomAdapter(BaseAdapter):
    name = "paycom"
    domains = ["paycomonline.net"]

    async def can_handle(self, url: str, html: str) -> bool:
        lowered_url = str(url or "").lower()
        lowered_html = str(html or "").lower()
        return (
            "paycomonline.net" in lowered_url
            or "configsfromhost" in lowered_html
            or "portal-applicant-tracking" in lowered_html
            or "/career-page" in lowered_url
        )

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        records = await self.try_public_endpoint(url, html, surface)
        return AdapterResult(
            records=records,
            source_type="paycom_adapter",
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
        host_config = self._extract_host_config(html)
        if not host_config:
            return []
        service_base = str(host_config.get("service_base") or "").rstrip("/")
        auth_token = str(host_config.get("auth_token") or "").strip()
        locale = str(host_config.get("locale") or "en-US").strip() or "en-US"
        if not service_base or not auth_token:
            return []

        request_kwargs = {
            "impersonate": "chrome124",
            "timeout": 12,
            "headers": {
                "accept": "application/json, text/plain, */*",
                "authorization": auth_token,
                "locale": locale,
                "origin": f"{urlparse(url).scheme}://{urlparse(url).netloc}",
                "portal-host-referrer": url,
                "referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/",
            },
        }
        if proxy:
            request_kwargs["proxies"] = {"http": proxy, "https": proxy}

        if "detail" in str(surface or "").lower():
            job_id = self._extract_job_id(url)
            if not job_id:
                return []
            record = await self._fetch_detail(
                service_base=service_base,
                request_kwargs=request_kwargs,
                page_url=url,
                locale=locale,
                job_id=job_id,
            )
            return [record] if record else []

        records = await self._fetch_listing(
            service_base=service_base,
            request_kwargs=request_kwargs,
            page_url=url,
            locale=locale,
        )
        return records

    async def _fetch_listing(
        self,
        *,
        service_base: str,
        request_kwargs: dict,
        page_url: str,
        locale: str,
    ) -> list[dict]:
        endpoint = f"{service_base}/api/ats/job-posting-previews/search"
        records: list[dict] = []
        seen_ids: set[str] = set()
        skip = 0
        take = 100
        while True:
            payload = {
                "skip": skip,
                "take": take,
                "filtersForQuery": {
                    "distanceFrom": 0,
                    "workEnvironments": [],
                    "positionTypes": [],
                    "educationLevels": [],
                    "categories": [],
                    "travelTypes": [],
                    "shiftTypes": [],
                    "otherFilters": [],
                    "keywordSearchText": "",
                    "location": "",
                    "sortOption": "",
                },
            }
            try:
                response = await asyncio.to_thread(
                    curl_requests.post,
                    endpoint,
                    json=payload,
                    **request_kwargs,
                )
                if response.status_code != 200:
                    break
                body = response.json()
            except Exception:
                break
            previews = body.get("jobPostingPreviews") if isinstance(body, dict) else []
            if not isinstance(previews, list) or not previews:
                break
            for preview in previews:
                normalized = self._normalize_preview(preview, page_url=page_url)
                if not normalized:
                    continue
                job_id = str(normalized.get("job_id") or "").strip()
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                records.append(normalized)
            total = int(body.get("jobPostingPreviewsCount", 0) or 0) if isinstance(body, dict) else 0
            skip += take
            if len(previews) < take or (total and skip >= total):
                break
        return records

    async def _fetch_detail(
        self,
        *,
        service_base: str,
        request_kwargs: dict,
        page_url: str,
        locale: str,
        job_id: str,
    ) -> dict | None:
        endpoint = f"{service_base}/api/ats/job-postings/{job_id}"
        try:
            response = await asyncio.to_thread(curl_requests.get, endpoint, **request_kwargs)
            if response.status_code != 200:
                return None
            body = response.json()
        except Exception:
            return None
        posting = body.get("jobPosting") if isinstance(body, dict) else None
        if not isinstance(posting, dict):
            return None
        title = self._clean_text(posting.get("jobTitle"))
        if not title:
            return None
        record = {
            "title": title,
            "job_id": job_id,
            "url": page_url,
            "apply_url": page_url,
            "location": self._clean_text(posting.get("location")),
            "job_type": self._clean_text(posting.get("positionType") or posting.get("employmentType")),
            "description": self._clean_text(posting.get("jobDescription") or posting.get("description")),
            "posted_date": self._clean_text(posting.get("postedOn")),
        }
        return {key: value for key, value in record.items() if value not in (None, "", [], {})}

    def _extract_host_config(self, html: str) -> dict[str, str]:
        match = _CONFIG_RE.search(str(html or ""))
        if not match:
            return {}
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return {}
        lib_config_raw = payload.get("libConfig")
        try:
            lib_config = json.loads(lib_config_raw) if isinstance(lib_config_raw, str) else {}
        except json.JSONDecodeError:
            lib_config = {}
        return {
            "auth_token": str(payload.get("sessionJWT") or "").strip(),
            "service_base": str(lib_config.get("atsPortalMantleServiceUrl") or "").strip(),
            "locale": str(lib_config.get("locale") or "").strip(),
        }

    def _normalize_preview(self, preview: object, *, page_url: str) -> dict | None:
        if not isinstance(preview, dict):
            return None
        title = self._clean_text(preview.get("jobTitle"))
        job_id = self._clean_text(preview.get("jobId"))
        if not title or not job_id:
            return None
        record = {
            "title": title,
            "job_id": job_id,
            "url": urljoin(page_url, f"jobs/{job_id}"),
            "apply_url": urljoin(page_url, f"jobs/{job_id}"),
            "location": self._clean_text(preview.get("locations")),
            "job_type": self._clean_text(preview.get("positionType") or preview.get("remoteType")),
            "description": self._clean_text(preview.get("description")),
            "posted_date": self._clean_text(preview.get("postedOn")),
        }
        return {key: value for key, value in record.items() if value not in (None, "", [], {})}

    def _extract_job_id(self, url: str) -> str:
        match = _JOB_ID_RE.search(urlparse(str(url or "")).path)
        return self._clean_text(match.group(1)) if match else ""

    def _clean_text(self, value: object) -> str:
        return " ".join(str(value or "").split()).strip()
