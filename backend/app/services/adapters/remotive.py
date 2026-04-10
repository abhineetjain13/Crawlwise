# Remotive JSON/HTML adapter.
from __future__ import annotations

import json
from json import loads as parse_json

from app.services.adapters.base import AdapterResult, BaseAdapter


class RemotiveAdapter(BaseAdapter):
    name = "remotive"
    domains = ["remotive.com"]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(domain in str(url or "").lower() for domain in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        return AdapterResult(
            records=self._extract_remotive_from_html(html),
            source_type="remotive_adapter",
            adapter_name=self.name,
        )

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
