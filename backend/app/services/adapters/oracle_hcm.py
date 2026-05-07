# Oracle HCM Candidate Experience adapter.
from __future__ import annotations

import ast
import json
from html import unescape
from urllib.parse import urlparse

from app.services.adapters.base import PublicEndpointAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.config.extraction_rules import (
    ORACLE_HCM_CX_CONFIG_RE,
    ORACLE_HCM_DEFAULT_FACETS,
    ORACLE_HCM_JOB_PATH_RE,
    ORACLE_HCM_LANG_PATH_RE,
    ORACLE_HCM_LOCATION_LIST_KEYS,
    ORACLE_HCM_SITE_PATH_RE,
)
from app.services.extraction_html_helpers import html_to_text
from app.services.field_value_core import clean_text
from bs4 import BeautifulSoup


class OracleHCMAdapter(PublicEndpointAdapter):
    name = "oracle_hcm"
    platform_family = "oracle_hcm"
    job_surface_only = True

    async def _try_public_endpoint(
        self,
        url: str,
        html: str,
        surface: str,
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        parsed = urlparse(url)
        site_number = self._extract_site_number(url, html)
        if not site_number:
            return []
        site_lang = self._extract_site_lang(url, html) or "en"
        company = self._extract_site_name(html)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        target_job_id = (
            self._extract_job_id_from_url(url)
            if "detail" in str(surface or "").lower()
            else ""
        )
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
                payload = await self._request_json(
                    endpoint,
                    proxy=proxy,
                    timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
                )
                if not isinstance(payload, (dict, list)):
                    break
            except (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError):
                break

            items = payload.get("items") if isinstance(payload, dict) else payload
            if not isinstance(items, list) or not items:
                break

            response_item_count = len(items)
            batch_count = 0
            for item in items:
                requisitions = (
                    item.get("requisitionList") if isinstance(item, dict) else None
                )
                if not isinstance(requisitions, list):
                    requisitions = [item] if isinstance(item, dict) else []
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

    def _build_endpoint(
        self, *, base_url: str, site_number: str, limit: int, offset: int
    ) -> str:
        finder = (
            f"findReqs;siteNumber={site_number},facetsList={ORACLE_HCM_DEFAULT_FACETS},"
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
        title = clean_text(requisition.get("Title"))
        job_id = clean_text(requisition.get("Id"))
        if not title or not job_id:
            return None

        description_parts = [
            html_to_text(str(requisition.get("ShortDescriptionStr") or "")),
            html_to_text(str(requisition.get("ExternalResponsibilitiesStr") or "")),
            html_to_text(str(requisition.get("ExternalQualificationsStr") or "")),
        ]
        description = "\n\n".join(part for part in description_parts if part)
        location = self._join_locations(requisition)
        department = clean_text(requisition.get("Department"))
        category = clean_text(
            requisition.get("Organization")
            or requisition.get("JobFunction")
            or requisition.get("JobFamily")
        )
        job_type = clean_text(
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
            "posted_date": clean_text(requisition.get("PostedDate")),
            "location": location or None,
            "company": company or None,
            "department": department or None,
            "category": category or department or None,
            "job_type": job_type or None,
            "description": description or None,
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _extract_site_number(self, url: str, html: str) -> str:
        path_match = ORACLE_HCM_SITE_PATH_RE.search(urlparse(str(url or "")).path)
        if path_match:
            return clean_text(path_match.group(1))
        config = self._extract_cx_config(html)
        app_payload = config.get("app")
        app = app_payload if isinstance(app_payload, dict) else {}
        return clean_text(app.get("siteNumber"))

    def _extract_site_lang(self, url: str, html: str) -> str:
        path_match = ORACLE_HCM_LANG_PATH_RE.search(urlparse(str(url or "")).path)
        if path_match:
            return clean_text(path_match.group(1))
        config = self._extract_cx_config(html)
        app_payload = config.get("app")
        app = app_payload if isinstance(app_payload, dict) else {}
        return clean_text(app.get("siteLang"))

    def _extract_site_name(self, html: str) -> str:
        config = self._extract_cx_config(html)
        app_payload = config.get("app")
        app = app_payload if isinstance(app_payload, dict) else {}
        site_name = clean_text(app.get("siteName"))
        if site_name:
            return site_name
        soup = BeautifulSoup(str(html or ""), "html.parser")
        meta = soup.find("meta", attrs={"property": "og:site_name"})
        if meta is not None:
            return clean_text(meta.get("content"))
        return clean_text(
            soup.title.get_text(" ", strip=True) if soup.title is not None else ""
        )

    def _extract_cx_config(self, html: str) -> dict:
        match = ORACLE_HCM_CX_CONFIG_RE.search(str(html or ""))
        raw = (
            unescape(match.group(1)) if match else self._extract_cx_config_object(html)
        )
        if not raw:
            return {}
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

    def _extract_cx_config_object(self, html: str) -> str:
        source = str(html or "")
        marker = "CX_CONFIG"
        marker_index = source.find(marker)
        if marker_index < 0:
            return ""
        assignment_index = source.find("=", marker_index)
        if assignment_index < 0:
            return ""
        fragment = source[assignment_index + 1 :]
        start = fragment.find("{")
        if start < 0:
            return ""
        depth = 0
        in_string = False
        escaped = False
        for index, char in enumerate(fragment[start:], start=start):
            if in_string:
                if escaped:
                    escaped = False
                    continue
                if char == "\\":
                    escaped = True
                    continue
                if char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
                continue
            if char == "}":
                depth -= 1
                if depth == 0:
                    return fragment[start : index + 1]
        return ""

    def _extract_job_id_from_url(self, url: str) -> str:
        path = urlparse(str(url or "")).path
        match = ORACLE_HCM_JOB_PATH_RE.search(path)
        return clean_text(match.group(1)) if match else ""

    def _format_location_item(self, item: dict) -> str:
        parts = [
            clean_text(item.get("TownOrCity")),
            clean_text(item.get("Region2")),
            clean_text(item.get("Country")),
        ]
        location = ", ".join(part for part in parts if part)
        return location or clean_text(item.get("LocationName"))

    def _iter_location_values(self, requisition: dict):
        primary = clean_text(requisition.get("PrimaryLocation"))
        if primary:
            yield primary
        for key in ORACLE_HCM_LOCATION_LIST_KEYS:
            payload = requisition.get(key)
            if not isinstance(payload, list):
                continue
            for item in payload:
                if isinstance(item, dict):
                    location = self._format_location_item(item)
                    if location:
                        yield location

    def _join_locations(self, requisition: dict) -> str:
        unique_locations = dict.fromkeys(self._iter_location_values(requisition))
        return " | ".join(unique_locations)
