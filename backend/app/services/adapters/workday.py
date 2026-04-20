# Workday Candidate Experience adapter.
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.extraction_html_helpers import extract_job_sections, html_to_text
from app.services.field_value_core import clean_text

_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.IGNORECASE)


class WorkdayAdapter(BaseAdapter):
    name = "workday"
    platform_family = "workday"
    max_records = 500
    max_pages = 25

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        if self._looks_like_detail(url, surface):
            record = await self._extract_detail(url, html)
            records = [record] if record else []
        else:
            records = await self._extract_listing(url, html)
        return AdapterResult(
            records=records,
            source_type="workday_adapter",
            adapter_name=self.name,
        )

    async def _extract_listing(self, url: str, html: str) -> list[dict]:
        context = self._site_context(url, html)
        if not context:
            return []
        endpoint = context["api_base"] + "/jobs"
        records: list[dict] = []
        seen_urls: set[str] = set()
        limit = 20
        offset = 0
        total: int | None = None
        pages_processed = 0

        while True:
            if len(records) >= self.max_records or pages_processed >= self.max_pages:
                break
            payload = await self._request_json(
                endpoint,
                method="POST",
                headers={"Content-Type": "application/json"},
                json_body={
                    "appliedFacets": {},
                    "limit": limit,
                    "offset": offset,
                    "searchText": "",
                },
                timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
            )
            if not isinstance(payload, dict):
                break
            if total is None:
                try:
                    total = int(payload.get("total") or 0)
                except (TypeError, ValueError):
                    total = 0
            rows = payload.get("jobPostings")
            if not isinstance(rows, list) or not rows:
                break
            pages_processed += 1
            for row in rows:
                if len(records) >= self.max_records:
                    break
                normalized = self._normalize_listing_row(row, context=context)
                if not normalized:
                    continue
                record_url = str(normalized.get("url") or "").strip()
                if not record_url or record_url in seen_urls:
                    continue
                seen_urls.add(record_url)
                records.append(normalized)
            offset += len(rows)
            if len(rows) < limit or (total is not None and offset >= total):
                break
        return records

    async def _extract_detail(self, url: str, html: str) -> dict | None:
        context = self._site_context(url, html)
        if not context:
            return None
        detail_path = self._detail_api_path(url, site_slug=context["site_slug"])
        if not detail_path:
            return None
        endpoint = f"{context['api_base']}/{detail_path}"
        payload = await self._request_json(
            endpoint,
            timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
        )
        if not isinstance(payload, dict):
            return None
        info = payload.get("jobPostingInfo")
        if not isinstance(info, dict):
            return None
        title = clean_text(info.get("title"))
        if not title:
            return None
        description_html = str(info.get("jobDescription") or "")
        record = {
            "title": title,
            "url": url,
            "apply_url": clean_text(info.get("externalUrl")) or url,
            "location": clean_text(info.get("location")),
            "posted_date": clean_text(info.get("postedOn")),
            "job_type": clean_text(info.get("timeType")),
            "job_id": clean_text(info.get("jobReqId") or info.get("jobPostingId")),
            "start_date": clean_text(info.get("startDate")),
            "country": clean_text(info.get("country")),
        }
        hiring_org = payload.get("hiringOrganization")
        if isinstance(hiring_org, dict):
            record["company"] = clean_text(
                hiring_org.get("name") or hiring_org.get("legalName")
            )
        if description_html:
            description = html_to_text(description_html)
            if description:
                record["description"] = description
            record.update(extract_job_sections(description_html))
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _site_context(self, url: str, html: str) -> dict[str, str] | None:
        parsed = urlparse(str(url or ""))
        host = str(parsed.netloc or "").strip()
        if not host:
            return None
        hostname_parts = host.split(".")
        tenant = hostname_parts[0].strip() if hostname_parts else ""
        if not tenant:
            return None
        locale, path_segments = self._split_localized_path(parsed.path)
        site_slug = path_segments[0] if path_segments else "External"
        localized_prefix = self._localized_prefix(
            html=html,
            site_slug=site_slug,
            locale=locale,
        )
        api_base = f"{parsed.scheme}://{host}/wday/cxs/{tenant}/{site_slug}"
        return {
            "api_base": api_base,
            "base_url": f"{parsed.scheme}://{host}",
            "localized_prefix": localized_prefix,
            "site_slug": site_slug,
        }

    def _localized_prefix(self, *, html: str, site_slug: str, locale: str) -> str:
        if locale:
            return f"/{locale}/{site_slug}"
        pattern = re.compile(
            rf'href="(?P<prefix>/[a-z]{{2}}(?:-[A-Z]{{2}})?/{re.escape(site_slug)})/job/',
            re.IGNORECASE,
        )
        match = pattern.search(str(html or ""))
        if match:
            return clean_text(match.group("prefix"))
        return f"/{site_slug}"

    def _normalize_listing_row(
        self,
        row: object,
        *,
        context: dict[str, str],
    ) -> dict | None:
        if not isinstance(row, dict):
            return None
        title = clean_text(row.get("title"))
        external_path = clean_text(row.get("externalPath"))
        if not title or not external_path:
            return None
        normalized_prefix = "/" + str(context["localized_prefix"]).strip("/")
        normalized_path = "/" + external_path.lstrip("/")
        if normalized_path.startswith(normalized_prefix + "/") or normalized_path == normalized_prefix:
            detail_path = normalized_path
        else:
            detail_path = f"{normalized_prefix}{normalized_path}"
        detail_url = (
            f"{context['base_url']}{detail_path}"
        )
        record = {
            "title": title,
            "url": detail_url,
            "apply_url": detail_url,
            "location": clean_text(row.get("locationsText")),
            "posted_date": clean_text(row.get("postedOn")),
        }
        bullet_fields = row.get("bulletFields")
        if isinstance(bullet_fields, list):
            for value in bullet_fields:
                cleaned = clean_text(value)
                if cleaned and not record.get("job_id"):
                    record["job_id"] = cleaned
                    break
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _detail_api_path(self, url: str, *, site_slug: str) -> str:
        parsed = urlparse(str(url or ""))
        _, path_segments = self._split_localized_path(parsed.path)
        if not path_segments:
            return ""
        if path_segments[0] != site_slug:
            return ""
        suffix = "/".join(path_segments[1:])
        if not suffix.startswith("job/"):
            return ""
        return suffix

    def _looks_like_detail(self, url: str, surface: str) -> bool:
        lowered_surface = str(surface or "").lower()
        lowered_path = urlparse(str(url or "").lower()).path
        return "detail" in lowered_surface or "/job/" in lowered_path

    def _split_localized_path(self, path: str) -> tuple[str, list[str]]:
        path_segments = [segment for segment in str(path or "").split("/") if segment]
        if path_segments and _LOCALE_RE.fullmatch(path_segments[0]):
            return path_segments[0], path_segments[1:]
        return "", path_segments
