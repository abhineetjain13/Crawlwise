# Remotive / RemoteOK JSON API adapter.
#
# These APIs return structured JSON directly:
#   - Remotive: https://remotive.com/api/remote-jobs
#   - RemoteOK: https://remoteok.com/api
from __future__ import annotations

from app.services.adapters.base import AdapterResult, BaseAdapter


class RemotiveAdapter(BaseAdapter):
    name = "remotive"
    domains = ["remotive.com", "remoteok.com"]

    async def can_handle(self, url: str, html: str) -> bool:
        return any(d in url for d in self.domains)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        # These APIs return JSON, so the pipeline's JSON-first path handles
        # the actual parsing. The adapter's role is to normalize the fields
        # if the data has already been fetched and parsed.
        #
        # When the pipeline detects JSON content type, it routes to
        # extract_json_listing() which handles the field normalization.
        # The adapter here handles the HTML fallback case where the
        # response was rendered as an HTML page containing JSON.
        records: list[dict] = []

        if "remotive.com" in url:
            records = self._extract_remotive_from_html(html, url)
        elif "remoteok.com" in url:
            records = self._extract_remoteok_from_html(html, url)

        return AdapterResult(
            records=records,
            source_type="remotive_adapter",
            confidence=0.90,
            adapter_name=self.name,
        )

    def _extract_remotive_from_html(self, html: str, url: str) -> list[dict]:
        """Extract Remotive jobs from rendered HTML (non-API path)."""
        import json
        # Remotive sometimes renders JSON in the page body
        try:
            data = json.loads(html.strip())
            if isinstance(data, dict):
                jobs = data.get("jobs", [])
            elif isinstance(data, list):
                jobs = data
            else:
                return []
        except (json.JSONDecodeError, ValueError):
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

    def _extract_remoteok_from_html(self, html: str, url: str) -> list[dict]:
        """Extract RemoteOK jobs from rendered HTML (non-API path)."""
        import json
        try:
            data = json.loads(html.strip())
            if isinstance(data, list):
                jobs = data
            else:
                return []
        except (json.JSONDecodeError, ValueError):
            return []

        records = []
        for job in jobs:
            if not isinstance(job, dict):
                continue
            # RemoteOK first item is usually metadata, skip it
            if not job.get("position") and not job.get("company"):
                continue
            record = {
                "title": job.get("position", ""),
                "company": job.get("company", ""),
                "url": job.get("url", ""),
                "location": job.get("location", "Worldwide"),
                "salary": self._format_salary(job),
                "tags": job.get("tags", []),
                "description": job.get("description", ""),
                "publication_date": job.get("date", ""),
                "image_url": job.get("company_logo", ""),
            }
            if record["title"]:
                records.append(record)
        return records

    @staticmethod
    def _format_salary(job: dict) -> str:
        min_sal = _safe_int(job.get("salary_min"))
        max_sal = _safe_int(job.get("salary_max"))
        if min_sal and max_sal:
            return f"${min_sal:,}-${max_sal:,}"
        if min_sal:
            return f"${min_sal:,}+"
        return ""


def _safe_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
