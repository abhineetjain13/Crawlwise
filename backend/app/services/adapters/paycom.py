# Paycom ATS adapter.
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlparse

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.acquisition.http_client import requests as curl_requests
from app.services.field_value_utils import clean_text


_CONFIG_RE = re.compile(r"var configsFromHost = (\{.*?\});\s*var Mountable", re.DOTALL)
_JOB_ID_RE = re.compile(r"/jobs/(\d+)", re.IGNORECASE)


class PaycomAdapter(BaseAdapter):
    name = "paycom"
    platform_family = "paycom"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

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
        html: str = "",
        surface: str = "",
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        if "job" not in str(surface or "").lower():
            return []
        host_config = self._extract_host_config(html)
        if not host_config:
            return []
        service_base = str(host_config.get("service_base") or "").rstrip("/")
        auth_token = str(host_config.get("auth_token") or "").strip()
        locale = str(host_config.get("locale") or "en-US").strip() or "en-US"
        if not service_base or not auth_token:
            return []

        request_headers = {
            "accept": "application/json, text/plain, */*",
            "authorization": auth_token,
            "locale": locale,
            "origin": f"{urlparse(url).scheme}://{urlparse(url).netloc}",
            "portal-host-referrer": url,
            "referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/",
        }

        if "detail" in str(surface or "").lower():
            job_id = self._extract_job_id(url)
            if not job_id:
                return []
            record = await self._fetch_detail(
                service_base=service_base,
                request_headers=request_headers,
                page_url=url,
                job_id=job_id,
                proxy=proxy,
            )
            return [record] if record else []

        records = await self._fetch_listing(
            service_base=service_base,
            request_headers=request_headers,
            page_url=url,
            proxy=proxy,
        )
        return records

    async def _fetch_listing(
        self,
        *,
        service_base: str,
        request_headers: dict[str, str],
        page_url: str,
        proxy: str | None,
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
                body = await self._request_json_with_curl(
                    curl_requests.post,
                    endpoint,
                    headers=request_headers,
                    json_body=payload,
                    proxy=proxy,
                    timeout_seconds=12,
                )
                if not isinstance(body, dict):
                    break
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ):
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
            total = (
                int(body.get("jobPostingPreviewsCount", 0) or 0)
                if isinstance(body, dict)
                else 0
            )
            skip += take
            if len(previews) < take or (total and skip >= total):
                break
        return records

    async def _fetch_detail(
        self,
        *,
        service_base: str,
        request_headers: dict[str, str],
        page_url: str,
        job_id: str,
        proxy: str | None,
    ) -> dict | None:
        endpoint = f"{service_base}/api/ats/job-postings/{job_id}"
        try:
            body = await self._request_json_with_curl(
                curl_requests.get,
                endpoint,
                headers=request_headers,
                proxy=proxy,
                timeout_seconds=12,
            )
            if not isinstance(body, dict):
                return None
        except (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            return None
        posting = body.get("jobPosting") if isinstance(body, dict) else None
        if not isinstance(posting, dict):
            return None
        title = clean_text(posting.get("jobTitle"))
        if not title:
            return None
        record = {
            "title": title,
            "job_id": job_id,
            "url": page_url,
            "apply_url": page_url,
            "location": clean_text(posting.get("location")),
            "job_type": clean_text(
                posting.get("positionType") or posting.get("employmentType")
            ),
            "description": clean_text(
                posting.get("jobDescription") or posting.get("description")
            ),
            "posted_date": clean_text(posting.get("postedOn")),
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

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
            lib_config = (
                json.loads(lib_config_raw)
                if isinstance(lib_config_raw, str)
                else (lib_config_raw if isinstance(lib_config_raw, dict) else {})
            )
        except json.JSONDecodeError:
            lib_config = {}
        return {
            "auth_token": str(payload.get("sessionJWT") or "").strip(),
            "service_base": str(
                lib_config.get("atsPortalMantleServiceUrl") or ""
            ).strip(),
            "locale": str(lib_config.get("locale") or "").strip(),
        }

    def _normalize_preview(self, preview: object, *, page_url: str) -> dict | None:
        if not isinstance(preview, dict):
            return None
        title = clean_text(preview.get("jobTitle"))
        job_id = clean_text(preview.get("jobId"))
        if not title or not job_id:
            return None
        record = {
            "title": title,
            "job_id": job_id,
            "url": urljoin(page_url, f"jobs/{job_id}"),
            "apply_url": urljoin(page_url, f"jobs/{job_id}"),
            "location": clean_text(preview.get("locations")),
            "job_type": clean_text(
                preview.get("positionType") or preview.get("remoteType")
            ),
            "description": clean_text(preview.get("description")),
            "posted_date": clean_text(preview.get("postedOn")),
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _extract_job_id(self, url: str) -> str:
        match = _JOB_ID_RE.search(urlparse(str(url or "")).path)
        return clean_text(match.group(1)) if match else ""
