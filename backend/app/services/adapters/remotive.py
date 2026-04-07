# Remotive / RemoteOK JSON API adapter.
#
# These APIs return structured JSON directly:
#   - Remotive: https://remotive.com/api/remote-jobs
#   - RemoteOK: https://remoteok.com/api
from __future__ import annotations

from app.services.adapters.base import AdapterResult, BaseAdapter


class RemotiveAdapter(BaseAdapter):
    """Adapter for normalizing Remotive and RemoteOK job listings from HTML fallback pages.
    Parameters:
        - url (str): Page URL used to determine which supported site-specific extractor to use.
        - html (str): Raw HTML content that may contain embedded JSON job data.
        - surface (str): Target extraction surface or context.
    Processing Logic:
        - Uses domain matching to route extraction to the correct site-specific parser.
        - Skips non-job metadata entries when parsing RemoteOK payloads.
        - Normalizes salary ranges into a readable string when range fields are available.
        - Returns only records with a populated title field."""
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
        """Extract and normalize listing records from HTML fallback pages for supported job sites.
        Parameters:
            - url (str): The page URL used to identify the source site and select the appropriate extractor.
            - html (str): The HTML content to parse when the response is not handled by the JSON-first pipeline.
            - surface (str): The target surface or context for extraction.
        Returns:
            - AdapterResult: Normalized extraction result containing records, source type, and adapter name."""
        records: list[dict] = []

        if "remotive.com" in url:
            records = self._extract_remotive_from_html(html, url)
        elif "remoteok.com" in url:
            records = self._extract_remoteok_from_html(html, url)

        return AdapterResult(
            records=records,
            source_type="remotive_adapter",
            adapter_name=self.name,
        )

    def _extract_remotive_from_html(self, html: str, url: str) -> list[dict]:
        """Extract Remotive jobs from rendered HTML (non-API path)."""
        from json import loads as parse_json
        # Remotive sometimes renders JSON in the page body
        try:
            data = parse_json(html.strip())
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
        from json import loads as parse_json
        try:
            data = parse_json(html.strip())
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
        """Format a job's salary range as a human-readable string.
        Parameters:
            - job (dict): Job data containing optional "salary_min" and "salary_max" fields.
        Returns:
            - str: Formatted salary range such as "$50,000-$70,000", "$50,000+", or an empty string if no salary is available."""
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
