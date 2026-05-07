# SaaSHR / UKG Ready careers adapter.
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from app.services.adapters.base import PublicEndpointAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.field_value_core import clean_text
from bs4 import BeautifulSoup


_COMPANY_RE = re.compile(r"/ta/([^/?#]+)\.careers", re.IGNORECASE)
SAASHR_DOMAIN = "saashr.com"
SECURE7_SAASHR_DOMAIN = f"secure7.{SAASHR_DOMAIN}"


class SaaSHRAdapter(PublicEndpointAdapter):
    name = "saashr"
    platform_family = "saashr"
    job_surface_only = True

    async def can_handle(self, url: str, html: str) -> bool:
        return bool(self._discover_board_url(url, html))

    async def _try_public_endpoint(
        self,
        url: str,
        html: str,
        surface: str,
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        board_url = self._discover_board_url(url, html)
        if not board_url:
            return []
        parsed = urlparse(board_url)
        company_code = self._extract_company_code(board_url)
        if not company_code:
            return []
        target_job_id = self._requested_job_id(board_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        ein_id = str(params.get("ein_id") or "").strip()
        career_portal_id = str(params.get("career_portal_id") or "").strip()
        lang = str(params.get("lang") or "en-US").strip() or "en-US"
        if not ein_id or not career_portal_id:
            return []
        base_url = f"{parsed.scheme}://{parsed.netloc}"
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
                payload = await self._request_json(
                    endpoint,
                    proxy=proxy,
                    timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
                )
                if not isinstance(payload, dict):
                    break
            except (OSError, RuntimeError, ValueError, TypeError):
                break
            if not company_name:
                company_name = await self._fetch_company_name(
                    base_url=base_url,
                    company_code=company_code,
                    ein_id=ein_id,
                    career_portal_id=career_portal_id,
                    lang=lang,
                    proxy=proxy,
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
                if target_job_id and job_id != target_job_id:
                    continue
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                records.append(normalized)
                if target_job_id and records:
                    return records
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
        proxy: str | None = None,
    ) -> str:
        endpoint = (
            f"{base_url}/ta/rest/ui/recruitment/companies/%7C{company_code}/job-search/config"
            f"?ein_id={ein_id}&career_portal_id={career_portal_id}&lang={lang}"
        )
        try:
            payload = await self._request_json(
                endpoint,
                proxy=proxy,
                timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
            )
            if not isinstance(payload, dict):
                return ""
        except (OSError, RuntimeError, ValueError, TypeError):
            return ""
        return clean_text(payload.get("comp_name")) if isinstance(payload, dict) else ""

    def _discover_board_url(self, url: str, html: str) -> str:
        if SAASHR_DOMAIN in str(url or "").lower():
            return url
        soup = BeautifulSoup(str(html or ""), "html.parser")
        iframe = soup.select_one(f"iframe[src*='{SAASHR_DOMAIN}/ta/'][src*='.careers']")
        if iframe is None:
            return ""
        src = str(iframe.get("src") or "").strip()
        return urljoin(url, src) if src else ""

    def _extract_company_code(self, board_url: str) -> str:
        match = _COMPANY_RE.search(urlparse(str(board_url or "")).path)
        return clean_text(match.group(1)) if match else ""

    def _normalize_row(
        self, row: object, *, board_url: str, company_name: str
    ) -> dict | None:
        if not isinstance(row, dict):
            return None
        title = clean_text(row.get("job_title"))
        job_id = clean_text(row.get("id"))
        if not title or not job_id:
            return None
        location_payload_raw = row.get("location")
        location_payload = (
            location_payload_raw if isinstance(location_payload_raw, dict) else {}
        )
        location = ", ".join(
            part
            for part in [
                clean_text(location_payload.get("city")),
                clean_text(location_payload.get("state")),
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
            "description": clean_text(row.get("job_description")),
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _build_detail_url(self, board_url: str, job_id: str) -> str:
        parsed = urlparse(board_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["ShowJob"] = job_id
        query = urlencode(params)
        return parsed._replace(query=query).geturl()

    def _requested_job_id(self, board_url: str) -> str:
        params = dict(parse_qsl(urlparse(board_url).query, keep_blank_values=True))
        return clean_text(params.get("ShowJob"))
