"""Helper functions for listing extraction and processing."""
from __future__ import annotations

import re
from urllib.parse import urljoin

from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition.blocked_detector import detect_blocked_page

from .utils import _clean_candidate_text

HTTP_URL_PREFIXES = ("http://", "https://")


def _listing_acquisition_blocked(acq: AcquisitionResult, html: str) -> bool:
    """Check if listing acquisition was blocked."""
    if html and detect_blocked_page(html).is_blocked:
        return True
    diagnostics = acq.diagnostics if isinstance(acq.diagnostics, dict) else {}
    if bool(diagnostics.get("browser_blocked")):
        return True
    browser_diagnostics = diagnostics.get("browser_diagnostics")
    if isinstance(browser_diagnostics, dict) and bool(
        browser_diagnostics.get("blocked")
    ):
        return True
    return False


def _looks_like_loading_listing_shell(html: str, *, surface: str) -> bool:
    """Detect if page is a loading skeleton/shell."""
    if not html or "listing" not in str(surface or "").lower():
        return False
    lowered = html.lower()
    if "job" in str(surface or "").lower():
        return False
    if lowered.count("product-card-skeleton") >= 4:
        return True
    if 'data-test-id="content-grid"' in lowered and lowered.count("animate-pulse") >= 8:
        return True
    return False


def _sanitize_listing_record_fields(
    record: dict, *, surface: str, page_base_url: str = ""
) -> dict:
    """Sanitize and normalize listing record fields."""
    sanitized = dict(record or {})
    if not sanitized:
        return sanitized

    # Normalize title
    title = str(sanitized.get("title") or "").strip()
    if title:
        normalized_title = re.sub(
            r"\s+([,;:/|])", r"\1", " ".join(title.split())
        ).strip()
        normalized_title = re.sub(r"\s*[,;/|:-]+\s*$", "", normalized_title).strip()
        if normalized_title:
            sanitized["title"] = normalized_title

    # Resolve relative URLs
    for url_field in ("url", "apply_url"):
        raw_url = str(sanitized.get(url_field) or "").strip()
        if raw_url and not raw_url.startswith(HTTP_URL_PREFIXES):
            sanitized[url_field] = (
                urljoin(page_base_url, raw_url) if page_base_url else raw_url
            )

    # Job-specific sanitization
    if "job" not in str(surface or "").lower():
        return sanitized

    # Map price to salary for job listings
    if sanitized.get("price") not in (None, "", [], {}) and sanitized.get("salary") in (
        None,
        "",
        [],
        {},
    ):
        sanitized["salary"] = sanitized.get("price")

    for field_name in (
        "price",
        "sale_price",
        "original_price",
        "currency",
        "sku",
        "part_number",
        "color",
        "availability",
        "rating",
        "review_count",
        "image_url",
        "additional_images",
    ):
        sanitized.pop(field_name, None)
    
    # Summarize job description
    description = _summarize_job_listing_description(sanitized.get("description"))
    if description:
        sanitized["description"] = description
    else:
        sanitized.pop("description", None)
    
    return sanitized


def _summarize_job_listing_description(value: object) -> str:
    """Summarize job listing description to ~180 chars."""
    text = _clean_candidate_text(value, limit=None)
    if not text:
        return ""
    text = " ".join(str(text).split()).strip()
    if not text:
        return ""
    if len(text) <= 180:
        return text

    # Split into sentences
    parts = [
        segment.strip(" -|,:;/")
        for segment in re.split(r"(?<=[.!?])\s+", text)
        if segment and segment.strip(" -|,:;/")
    ]
    if not parts:
        return text[:180].rstrip(" ,;:-") + "..."

    # Build summary from first few sentences
    summary_parts: list[str] = []
    summary_len = 0
    for part in parts:
        projected = summary_len + len(part) + (1 if summary_parts else 0)
        if projected > 180:
            break
        summary_parts.append(part)
        summary_len = projected
        if summary_len >= 80 or len(summary_parts) >= 4:
            break

    summary = " ".join(summary_parts).strip()
    if len(summary) >= 35:
        return summary
    return text[:180].rstrip(" ,;:-") + "..."
