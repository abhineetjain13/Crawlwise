# Remotive JSON/HTML adapter.
from __future__ import annotations

import json
from json import loads as parse_json

from app.services.adapters.base import AdapterResult, BaseAdapter


class RemotiveAdapter(BaseAdapter):
    name = "remotive"
    platform_family = "remotive"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        return self._result(self._extract_remotive_from_html(html))

    def _extract_remotive_from_html(self, html: str) -> list[dict]:
        """Extract Remotive jobs from rendered HTML or a JSON body."""
        try:
            data = parse_json(str(html or "").strip())
        except (json.JSONDecodeError, ValueError):
            return []

        if isinstance(data, dict):
            jobs = data.get("jobs", [])
        elif isinstance(data, list):
            jobs = data
        else:
            return []

        records = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            record = {
                "title": job.get("title", ""),
                "company": job.get("company_name", ""),
                "url": job.get("url", ""),
                "location": job.get("candidate_required_location", ""),
                "salary": job.get("salary", ""),
                "category": job.get("category", ""),
                "description": job.get("description", ""),
                "publication_date": job.get("publication_date", ""),
                "tags": job.get("tags", []),
            }
            if record["title"]:
                records.append(record)
        return records
