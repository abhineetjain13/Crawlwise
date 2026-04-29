# ADP WorkForceNow recruitment adapter.
from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import (
    AdapterResult,
    BaseAdapter,
    selectolax_node_attr,
    selectolax_node_text,
)
from app.services.field_value_core import clean_text


class ADPAdapter(BaseAdapter):
    name = "adp"
    platform_family = "adp"

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html)

    def normalize_acquisition_url(self, url: str | None) -> str | None:
        parsed = urlparse(str(url or "").strip())
        if not self._matches_platform_family(parsed.geturl(), ""):
            return url
        if "recruitment/recruitment.html" not in parsed.path.lower():
            return url
        if parsed.fragment:
            return url
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        job_id = " ".join(str(query.get("jobId") or "").split()).strip()
        if not job_id:
            return url
        normalized_pairs: list[tuple[str, str]] = []
        replaced_job_id = False
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key == "jobId":
                normalized_pairs.append((key, job_id))
                replaced_job_id = True
                continue
            normalized_pairs.append((key, value))
        if not replaced_job_id:
            normalized_pairs.append(("jobId", job_id))
        return urlunparse(
            parsed._replace(query=urlencode(normalized_pairs, doseq=True))
        )

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        records: list[dict] = []
        if self._looks_like_detail(url, html, surface):
            detail = self._extract_detail(url, html) if html else None
            if detail:
                records.append(detail)
        else:
            records = self._extract_listing(url, html)
        return self._result(records)

    def _extract_listing(self, url: str, html: str) -> list[dict]:
        parser = LexborHTMLParser(html)
        records: list[dict] = []
        seen_keys: set[str] = set()
        for card in parser.css(".current-openings-item"):
            title_node = card.css_first("[id^='lblTitle_'], sdf-link, a")
            title = clean_text(selectolax_node_text(title_node, separator=" "))
            if len(title) < 3:
                continue

            job_dom_id = self._extract_job_dom_id(card)
            record: dict[str, str] = {
                "title": title,
                "source_url": url,
            }
            if job_dom_id:
                record["job_id"] = job_dom_id
                detail_url = self._build_apply_url(url, job_dom_id)
                record["url"] = detail_url or f"{url}#{job_dom_id}"
                if detail_url:
                    record["apply_url"] = detail_url
            else:
                record["url"] = url

            location_values: list[str] = []
            for node in card.css(
                ".current-opening-location-item span, .current-opening-location-item"
            ):
                value = clean_text(selectolax_node_text(node, separator=" "))
                if value and value not in location_values:
                    location_values.append(value)
            location = " | ".join(location_values)
            post_elem = card.css_first(".current-opening-post-date")
            posted = clean_text(selectolax_node_text(post_elem, separator=" "))
            more_locations = clean_text(
                " ".join(
                    selectolax_node_text(node, separator=" ")
                    for node in card.css(
                        "[id^='job_item_location_'], .mdf-overlay-popover sdf-button"
                    )
                )
            )
            if location:
                record["location"] = location
            if more_locations and more_locations not in {location, title}:
                record["additional_locations"] = more_locations
            if posted:
                record["posted_date"] = posted

            key = str(record.get("job_id") or record.get("title") or "").strip().lower()
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            records.append(record)
        return records

    def _extract_detail(self, url: str, html: str) -> dict | None:
        parser = LexborHTMLParser(html)
        title_node = parser.css_first("h1, .job-details-title, .job-description-title")
        title = clean_text(selectolax_node_text(title_node, separator=" "))
        if len(title) < 3:
            return None

        body_text = clean_text(selectolax_node_text(parser.body, separator=" "))
        record: dict[str, str] = {
            "title": title,
            "url": url,
        }
        job_id = self._extract_job_id_from_url(url)
        if job_id:
            record["job_id"] = job_id

        location = self._extract_detail_location(parser)
        if location:
            record["location"] = location

        posted_match = re.search(
            r"(\d+\+?\s+days?\s+ago)", body_text, flags=re.IGNORECASE
        )
        if posted_match:
            record["posted_date"] = clean_text(posted_match.group(1))

        requisition_match = re.search(
            r"Requisition\s+ID:\s*([A-Za-z0-9\-_]+)", body_text, flags=re.IGNORECASE
        )
        if requisition_match:
            record["requisition_id"] = requisition_match.group(1)

        salary_match = re.search(
            r"Salary\s+Range:\s*([$€£].+?(?:Annually|Hourly|Monthly|Weekly))\b",
            body_text,
            flags=re.IGNORECASE,
        )
        if salary_match:
            record["salary"] = clean_text(salary_match.group(1))

        description = self._extract_detail_description(body_text)
        if description:
            record["description"] = description

        apply_url = self._build_apply_url(url, job_id)
        if apply_url:
            record["apply_url"] = apply_url
        return record

    def _extract_detail_location(self, parser: LexborHTMLParser) -> str:
        details = []
        for node in parser.css(
            ".current-opening-location-item span, .current-opening-location-item"
        ):
            value = clean_text(selectolax_node_text(node, separator=" "))
            if value and value not in details:
                details.append(value)
        return " | ".join(details[:4])

    def _extract_detail_description(self, body_text: str) -> str:
        patterns = [
            r"Apply\s+Salary\s+Range:.*?\s(.*?)(?:BackApply|Copyright)",
            r"Apply\s+(.*?)(?:BackApply|Copyright)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, flags=re.IGNORECASE)
            if not match:
                continue
            value = clean_text(match.group(1))
            if value and len(value) > 40:
                return value
        return ""

    def _build_apply_url(self, url: str, job_id: str | None) -> str | None:
        if not job_id:
            return None
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["jobId"] = job_id
        next_query = urlencode(params)
        # ADP boards are inconsistent: some resolve detail state from `jobId`,
        # others still rely on the hash route. Carry both so listing->detail
        # handoff stays valid for browser navigation and follow-up detail fetches.
        return urlunparse(parsed._replace(query=next_query, fragment=job_id))

    def _extract_job_dom_id(self, card: Any) -> str | None:
        candidates = [
            selectolax_node_attr(card, "id") or "",
        ]
        for node in card.css("[id]"):
            candidates.append(selectolax_node_attr(node, "id") or "")
        for candidate in candidates:
            if not candidate:
                continue
            match = re.search(r"(\d[\d_]{5,})", candidate)
            if match:
                return match.group(1)
        return None

    def _extract_job_id_from_url(self, url: str) -> str | None:
        params = dict(parse_qsl(urlparse(str(url or "")).query, keep_blank_values=True))
        value = str(params.get("jobId") or "").strip()
        return value or None

    def _looks_like_detail(self, url: str, html: str, surface: str) -> bool:
        lowered_surface = str(surface or "").lower()
        lowered_url = str(url or "").lower()
        lowered_html = str(html or "").lower()
        return (
            "detail" in lowered_surface
            or "jobid=" in lowered_url
            or "requisition id:" in lowered_html
            or "backapply" in lowered_html
        )
