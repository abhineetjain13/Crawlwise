# LinkedIn Jobs adapter.
from __future__ import annotations

from collections.abc import Mapping

from selectolax.lexbor import LexborHTMLParser

from app.services.adapters.base import AdapterResult, BaseAdapter


def _text(node: object, *, separator: str = "") -> str:
    if node is None:
        return ""
    text_fn = getattr(node, "text", None)
    if not callable(text_fn):
        return ""
    try:
        return str(text_fn(separator=separator, strip=True) or "")
    except Exception:
        return ""


def _attr(node: object, name: str) -> str | None:
    if node is None:
        return None
    raw_attrs = getattr(node, "attributes", {}) or {}
    attrs = raw_attrs if isinstance(raw_attrs, Mapping) else {}
    value = attrs.get(name)
    if value is None:
        return None
    return str(value).strip() or None


class LinkedInAdapter(BaseAdapter):
    name = "linkedin"
    platform_family = "linkedin"

    async def can_handle(self, url: str, html: str) -> bool:
        lowered_url = str(url or "").lower()
        return self._matches_platform_family(url, html) and (
            "/jobs/" in lowered_url or "/job/" in lowered_url
        )

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        parser = LexborHTMLParser(html)
        records = []
        if surface in ("job_detail",):
            record = self._extract_detail(parser, url)
            if record:
                records.append(record)
        elif surface in ("job_listing",):
            records = self._extract_listing(parser, url)
        return AdapterResult(
            records=records,
            source_type="linkedin_adapter",
            adapter_name=self.name,
        )

    def _extract_detail(self, parser: LexborHTMLParser, url: str) -> dict | None:
        title_el = parser.css_first(".top-card-layout__title, h1")
        company_el = parser.css_first(
            ".topcard__org-name-link, .top-card-layout__company-name, a[data-tracking-control-name='public_jobs_topcard-org-name']"
        )
        location_el = parser.css_first(
            ".topcard__flavor--bullet, .top-card-layout__bullet"
        )
        desc_el = parser.css_first(".description__text, .show-more-less-html__markup")
        criteria = parser.css(".description__job-criteria-item")
        job_type = None
        for item in criteria:
            header = item.css_first(".description__job-criteria-subheader")
            value = item.css_first(".description__job-criteria-text")
            if header and value:
                h = _text(header).lower()
                v = _text(value)
                if "employment type" in h:
                    job_type = v
        if not title_el:
            return None
        return {
            "title": _text(title_el),
            "company": _text(company_el) or None,
            "location": _text(location_el) or None,
            "job_type": job_type,
            "description": _text(desc_el, separator=" ") or None,
            "apply_url": url,
            "url": url,
        }

    def _extract_listing(self, parser: LexborHTMLParser, url: str) -> list[dict]:
        records = []
        cards = parser.css(
            ".base-card, .job-search-card, .jobs-search__results-list li"
        )
        for card in cards:
            title_el = card.css_first(".base-search-card__title, h3")
            company_el = card.css_first(".base-search-card__subtitle a, h4 a")
            location_el = card.css_first(".job-search-card__location")
            link_el = card.css_first("a.base-card__full-link, a")
            date_el = card.css_first("time")
            if not title_el:
                continue
            records.append(
                {
                    "title": _text(title_el),
                    "company": _text(company_el) or None,
                    "location": _text(location_el) or None,
                    "posted_date": _attr(date_el, "datetime"),
                    "apply_url": _attr(link_el, "href") or "",
                }
            )
        return records
