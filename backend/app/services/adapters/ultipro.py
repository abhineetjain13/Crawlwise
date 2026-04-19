# UltiPro / UKG recruiting adapter.
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.field_value_utils import clean_text

_DEFAULT_ORDER = "postedDateDesc"
_SEARCH_FILTERS: tuple[dict[str, object], ...] = (
    {"t": "TermsSearchFilterDto", "fieldName": 4, "extra": None, "values": []},
    {"t": "TermsSearchFilterDto", "fieldName": 5, "extra": None, "values": []},
    {"t": "TermsSearchFilterDto", "fieldName": 6, "extra": None, "values": []},
)


class UltiProAdapter(BaseAdapter):
    name = "ultipro_ukg"
    platform_family = "ultipro_ukg"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        if self._looks_like_detail(url, surface):
            record = self._extract_detail_from_html(url, html)
            records = [record] if record else []
        else:
            records = await self._extract_listing(url)
        return AdapterResult(
            records=records,
            source_type="ultipro_adapter",
            adapter_name=self.name,
        )

    async def _extract_listing(self, url: str) -> list[dict]:
        context = self._board_context(url)
        if not context:
            return []
        endpoint = (
            f"{context['base_url']}/{context['company_code']}/JobBoard/"
            f"{context['board_id']}/JobBoardView/LoadSearchResults"
        )
        page_size = 50
        skip = 0
        records: list[dict] = []
        seen_ids: set[str] = set()
        while True:
            payload = await self._request_json(
                endpoint,
                method="POST",
                headers={"Content-Type": "application/json"},
                json_body=self._search_body(
                    top=page_size,
                    skip=skip,
                    query_string=context["query"],
                    order_value=context["order_by"],
                ),
                timeout_seconds=12,
            )
            if not isinstance(payload, dict):
                break
            rows = payload.get("opportunities")
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                normalized = self._normalize_listing_row(row, context=context)
                if not normalized:
                    continue
                job_id = str(normalized.get("job_id") or "").strip()
                if not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                records.append(normalized)
            if len(rows) < page_size:
                break
            skip += len(rows)
        return records

    def _board_context(self, url: str) -> dict[str, str] | None:
        parsed = urlparse(str(url or ""))
        path_segments = [segment for segment in parsed.path.split("/") if segment]
        if len(path_segments) < 3:
            return None
        company_code = path_segments[0]
        try:
            jobboard_index = next(
                index
                for index, segment in enumerate(path_segments)
                if segment.lower() == "jobboard"
            )
        except StopIteration:
            return None
        if jobboard_index + 1 >= len(path_segments):
            return None
        board_id = path_segments[jobboard_index + 1]
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        return {
            "base_url": f"{parsed.scheme}://{parsed.netloc}",
            "board_id": board_id,
            "company_code": company_code,
            "order_by": clean_text(params.get("o")) or _DEFAULT_ORDER,
            "query": clean_text(params.get("q")),
            "board_url": f"{parsed.scheme}://{parsed.netloc}/{company_code}/JobBoard/{board_id}/",
        }

    def _search_body(
        self,
        *,
        top: int,
        skip: int,
        query_string: str,
        order_value: str,
    ) -> dict[str, object]:
        return {
            "opportunitySearch": {
                "Top": top,
                "Skip": skip,
                "QueryString": query_string,
                "OrderBy": [
                    {
                        "Value": order_value or _DEFAULT_ORDER,
                        "PropertyName": "PostedDate",
                        "Ascending": False,
                    }
                ],
                "Filters": [dict(item) for item in _SEARCH_FILTERS],
            },
            "matchCriteria": {
                "PreferredJobs": [],
                "Educations": [],
                "LicenseAndCertifications": [],
                "Skills": [],
                "SkippedSkills": [],
                "hasNoLicenses": False,
            },
        }

    def _normalize_listing_row(
        self,
        row: object,
        *,
        context: dict[str, str],
    ) -> dict | None:
        if not isinstance(row, dict):
            return None
        title = clean_text(row.get("Title") or row.get("title"))
        opportunity_id = clean_text(row.get("Id") or row.get("id"))
        if not title or not opportunity_id:
            return None
        detail_url = self._build_detail_url(
            context["board_url"],
            opportunity_id=opportunity_id,
            posting_id=clean_text(row.get("PostingId") or row.get("postingId")),
        )
        record = {
            "title": title,
            "job_id": opportunity_id,
            "url": detail_url,
            "apply_url": detail_url,
            "location": clean_text(
                row.get("LocationName")
                or row.get("Location")
                or row.get("location")
            ),
            "posted_date": clean_text(row.get("PostedDate") or row.get("postedDate")),
            "requisition_id": clean_text(
                row.get("RequisitionNumber") or row.get("requisitionNumber")
            ),
            "category": clean_text(
                row.get("JobCategoryName") or row.get("jobCategoryName")
            ),
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _build_detail_url(
        self,
        board_url: str,
        *,
        opportunity_id: str,
        posting_id: str,
    ) -> str:
        parsed = urlparse(board_url)
        params = []
        if opportunity_id:
            params.append(("opportunityId", opportunity_id))
        if posting_id:
            params.append(("postingId", posting_id))
        query = urlencode(params)
        detail_path = f"{parsed.path.rstrip('/')}/OpportunityDetail"
        return urlunparse(parsed._replace(path=detail_path, query=query))

    def _extract_detail_from_html(self, url: str, html: str) -> dict | None:
        soup = BeautifulSoup(str(html or ""), "html.parser")
        title_node = soup.select_one("h1, h2")
        title = clean_text(
            title_node.get_text(" ", strip=True) if title_node is not None else ""
        )
        if not title:
            return None
        body_text = clean_text(soup.get_text(" ", strip=True))
        record = {
            "title": title,
            "url": url,
            "apply_url": url,
            "description": body_text or None,
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }

    def _looks_like_detail(self, url: str, surface: str) -> bool:
        lowered_surface = str(surface or "").lower()
        parsed = urlparse(str(url or ""))
        return (
            "detail" in lowered_surface
            or "opportunitydetail" in parsed.path.lower()
            or "opportunityid=" in parsed.query.lower()
        )
