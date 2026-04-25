# RemoteOK JSON/HTML adapter.
from __future__ import annotations

import json
from json import loads as parse_json

from app.services.adapters.base import AdapterResult, BaseAdapter


class RemoteOkAdapter(BaseAdapter):
    name = "remoteok"
    platform_family = "remoteok"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        return AdapterResult(
            records=self._extract_remoteok_from_html(html),
            source_type="remoteok_adapter",
            adapter_name=self.name,
        )

    def _extract_remoteok_from_html(self, html: str) -> list[dict]:
        """Extract RemoteOK jobs from rendered HTML or a JSON body."""
        try:
            data = parse_json(str(html or "").strip())
        except (json.JSONDecodeError, ValueError):
            return []

        if not isinstance(data, list):
            return []

        records = []
        for job in data:
            if not isinstance(job, dict):
                continue
            if not job.get("position") or not job.get("company"):
                continue
            record = {
                "title": job.get("position", ""),
                "company": job.get("company", ""),
                "url": job.get("url", ""),
                "location": job.get("location", "Worldwide"),
                "salary": _format_salary(job),
                "tags": job.get("tags", []),
                "description": job.get("description", ""),
                "publication_date": job.get("date", ""),
                "image_url": job.get("company_logo", ""),
            }
            records.append(record)
        return records


def _format_salary(job: dict) -> str:
    min_sal = _safe_int(job.get("salary_min"))
    max_sal = _safe_int(job.get("salary_max"))
    if min_sal is not None and max_sal is not None:
        return f"${min_sal:,}-${max_sal:,}"
    if min_sal is not None:
        return f"${min_sal:,}+"
    if max_sal is not None:
        return f"Up to ${max_sal:,}"
    return ""


def _safe_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        return None
