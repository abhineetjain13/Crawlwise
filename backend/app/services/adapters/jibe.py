# Jibe careers adapter.
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.acquisition.http_client import requests as curl_requests
from bs4 import BeautifulSoup


_SEARCH_CONFIG_RE = re.compile(r"window\.searchConfig\s*=\s*(\{.*?\});", re.DOTALL)


class JibeAdapter(BaseAdapter):
    name = "jibe"
    platform_family = "jibe"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

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
        html: str = "",
        surface: str = "",
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        parsed = urlparse(url)
        api_url = f"{parsed.scheme}://{parsed.netloc}/api/jobs"
        query = self._build_query(url, html, surface)
        request_url = (
            api_url if not query else f"{api_url}?{urlencode(query, doseq=True)}"
        )
        try:
            payload = await self._request_json_with_curl(
                curl_requests.get,
                request_url,
                proxy=proxy,
                timeout_seconds=10,
            )
            if not isinstance(payload, dict):
                return []
        except (
            OSError,
            RuntimeError,
            ValueError,
            TypeError,
        ):
            return []
        jobs = payload.get("jobs") if isinstance(payload, dict) else []
        if not isinstance(jobs, list):
            return []
        normalized = [
            self._normalize_job(row, base_url=f"{parsed.scheme}://{parsed.netloc}")
            for row in jobs
        ]
        records = [row for row in normalized if row]
        if "detail" in str(surface or "").lower():
            target_id = self._extract_job_id_from_url(url)
            if target_id:
                records = [
                    row for row in records if str(row.get("job_id") or "") == target_id
                ]
        return records

    def _build_query(self, url: str, html: str, surface: str) -> list[tuple[str, str]]:
        parsed = urlparse(url)
        query_params = parse_qsl(parsed.query, keep_blank_values=False)
        merged: dict[str, str] = {}
        for key, value in query_params:
            if value:
                merged[key] = value
        search_config = self._extract_search_config(html)
        config_query = (
            search_config.get("query")
            if isinstance(search_config.get("query"), dict)
            else {}
        )
        for key, value in config_query.items():
            normalized = self._normalize_query_value(value)
            if normalized and key not in merged:
                merged[key] = normalized
        if "listing" in str(surface or "").lower():
            merged.setdefault("limit", merged.get("limit") or "100")
            merged.setdefault("page", merged.get("page") or "1")
        return [(key, value) for key, value in merged.items() if value]

    def _extract_search_config(self, html: str) -> dict:
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
        categories = (
            payload.get("categories")
            if isinstance(payload.get("categories"), list)
            else []
        )
        tags7 = payload.get("tags7")
        description_html = str(payload.get("description") or "")
        description = self._html_to_text(description_html)
        full_location = self._clean_text(payload.get("full_location"))
        if not full_location:
            full_location = ", ".join(
                part
                for part in [
                    self._clean_text(
                        payload.get("location_name") or payload.get("city")
                    ),
                    self._clean_text(payload.get("state")),
                ]
                if part
            )
        record = {
            "title": title,
            "url": url,
            "apply_url": self._clean_text(payload.get("apply_url")),
            "job_id": job_id,
            "location": full_location or None,
            "company": self._clean_text(payload.get("hiring_organization")),
            "department": self._clean_text(payload.get("department"))
            or self._join_names(categories),
            "job_type": self._clean_text(payload.get("employment_type")),
            "posted_date": self._clean_text(payload.get("posted_date")),
            "description": description or None,
            "salary": self._clean_text(tags7),
            "category": self._join_names(categories),
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _join_names(self, values: object) -> str:
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
