from __future__ import annotations

from typing import Any

import jmespath
from bs4 import BeautifulSoup


GREENHOUSE_DETAIL_SPEC = {
    "title": "title",
    "company": "company_name",
    "location": "location.name",
    "apply_url": "absolute_url",
    "posted_date": "first_published",
    "updated_at": "updated_at",
    "description_html": "content",
}


def map_network_payloads_to_fields(
    payloads: list[dict[str, object]] | None,
    *,
    surface: str,
    page_url: str,
) -> list[dict[str, Any]]:
    del page_url
    normalized_surface = str(surface or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for payload in payloads or []:
        if not isinstance(payload, dict):
            continue
        body = payload.get("body")
        if not isinstance(body, (dict, list)):
            continue
        if normalized_surface == "job_detail":
            mapped = _map_job_detail_payload(body)
            if mapped:
                rows.append(mapped)
    return rows


def _map_job_detail_payload(body: object) -> dict[str, Any]:
    if isinstance(body, dict) and body.get("content") and body.get("absolute_url"):
        mapped = {
            field: jmespath.search(path, body)
            for field, path in GREENHOUSE_DETAIL_SPEC.items()
        }
        result = {
            key: value
            for key, value in mapped.items()
            if value not in (None, "", [], {})
        }
        description_html = str(result.pop("description_html", "") or "").strip()
        if description_html:
            result.update(_extract_job_sections(description_html))
            if "description" not in result:
                result["description"] = _html_to_text(description_html)
        if result.get("apply_url") and not result.get("url"):
            result["url"] = result["apply_url"]
        return result
    return {}


def _extract_job_sections(html: str) -> dict[str, str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    sections: dict[str, str] = {}
    for heading in soup.find_all(["h2", "h3", "strong"]):
        heading_text = " ".join(heading.get_text(" ", strip=True).split()).strip()
        if not heading_text:
            continue
        values: list[str] = []
        for sibling in heading.next_siblings:
            sibling_name = getattr(sibling, "name", "")
            if sibling_name in {"h1", "h2", "h3"}:
                break
            text = (
                sibling.get_text(" ", strip=True)
                if hasattr(sibling, "get_text")
                else str(sibling)
            )
            cleaned = " ".join(str(text or "").split()).strip()
            if cleaned:
                values.append(cleaned)
        if values:
            sections[heading_text.lower()] = " ".join(values)

    mapped: dict[str, str] = {}
    for label, value in sections.items():
        if "what you" in label or "responsibil" in label:
            mapped["responsibilities"] = value
        elif "should have" in label or "qualif" in label or "who you are" in label:
            mapped["qualifications"] = value
        elif "benefit" in label or "perks" in label or "what we offer" in label:
            mapped["benefits"] = value
        elif "skill" in label or "bring" in label:
            mapped["skills"] = value
    return mapped


def _html_to_text(value: str) -> str:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split()).strip()
