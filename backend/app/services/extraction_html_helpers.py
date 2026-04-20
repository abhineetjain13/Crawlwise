from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.field_policy import HTML_SECTION_FIELDS, normalize_requested_field


def html_to_text(value: str) -> str:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split()).strip()


def extract_job_sections(html: str) -> dict[str, str]:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    mapped: dict[str, str] = {}
    for heading in list(soup.find_all(["h2", "h3", "strong"])):
        heading_text = " ".join(heading.get_text(" ", strip=True).split()).strip()
        if not heading_text:
            continue
        section = normalize_requested_field(heading_text)
        if section not in HTML_SECTION_FIELDS:
            continue
        collected: list[str] = []
        for sibling in heading.next_siblings:
            sibling_name = getattr(sibling, "name", "")
            if sibling_name in {"h1", "h2", "h3", "strong"}:
                break
            text = (
                sibling.get_text(" ", strip=True)
                if hasattr(sibling, "get_text")
                else str(sibling)
            )
            cleaned = " ".join(str(text or "").split()).strip()
            if cleaned:
                collected.append(cleaned)
        value = " ".join(collected).strip()
        if not value:
            continue
        combined = " ".join(
            piece for piece in (mapped.get(section), value) if str(piece or "").strip()
        )
        mapped[section] = " ".join(combined.split()).strip()
    return mapped
