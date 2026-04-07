# ADP WorkForceNow recruitment adapter.
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter


class ADPAdapter(BaseAdapter):
    """
    ADP recruitment page adapter for extracting job listings and job details from ADP-powered career sites.
    Parameters:
        - self (ADPAdapter): Adapter instance used to inspect pages and build extracted job records.
    Processing Logic:
        - Detects detail pages using URL, HTML markers, or surface hints before choosing extraction strategy.
        - Parses listing cards to collect unique jobs, including title, location, posting date, and job-specific anchors.
        - Extracts detail-page fields such as requisition ID, salary, description, and apply URL when available.
        - Normalizes text and filters out incomplete records to reduce duplicates and low-quality entries.
    """
    name = "adp"
    domains = ["workforcenow.adp.com", "myjobs.adp.com", "recruiting.adp.com"]

    async def can_handle(self, url: str, html: str) -> bool:
        """Determine whether the given URL or HTML matches supported recruitment page patterns.
        Parameters:
            - url (str): The URL to inspect.
            - html (str): The HTML content to inspect.
        Returns:
            - bool: True if the URL or HTML contains a supported domain or page marker; otherwise False."""
        lowered_url = str(url or "").lower()
        lowered_html = str(html or "").lower()
        return (
            any(domain in lowered_url for domain in self.domains)
            or "recruitment_root" in lowered_html
            or "current-openings-item" in lowered_html
            or "current-opening-post-date" in lowered_html
        )

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        """Extract records from a detail or listing page based on the provided URL, HTML, and surface.
        Parameters:
            - url (str): The URL of the page to analyze.
            - html (str): The page HTML content to extract data from.
            - surface (str): The surface or context used to determine extraction behavior.
        Returns:
            - AdapterResult: An AdapterResult containing the extracted records, source type, and adapter name."""
        if self._looks_like_detail(url, html, surface):
            records = [self._extract_detail(url, html)] if html else []
        else:
            records = self._extract_listing(url, html)
        return AdapterResult(
            records=[record for record in records if record],
            source_type="adp_adapter",
            adapter_name=self.name,
        )

    def _extract_listing(self, url: str, html: str) -> list[dict]:
        """Extract job listing records from an HTML page.
        Parameters:
            - url (str): Source page URL used to populate listing links and source metadata.
            - html (str): HTML content containing job listing cards to parse.
        Returns:
            - list[dict]: A list of unique job listing dictionaries with fields such as title, url, source_url, job_id, location, additional_locations, and posted_date."""
        soup = BeautifulSoup(html, "html.parser")
        records: list[dict] = []
        seen_keys: set[str] = set()
        for card in soup.select(".current-openings-item"):
            title_node = card.select_one("[id^='lblTitle_'], sdf-link, a")
            title = self._clean_text(title_node.get_text(" ", strip=True) if title_node is not None else "")
            if len(title) < 3:
                continue

            job_dom_id = self._extract_job_dom_id(card)
            record: dict[str, str] = {
                "title": title,
                "source_url": url,
            }
            if job_dom_id:
                record["job_id"] = job_dom_id
                record["url"] = f"{url}#{job_dom_id}"
            else:
                record["url"] = url

            location_values: list[str] = []
            for node in card.select(".current-opening-location-item span, .current-opening-location-item"):
                value = self._clean_text(node.get_text(" ", strip=True))
                if value and value not in location_values:
                    location_values.append(value)
            location = " | ".join(location_values)
            post_elem = card.select_one(".current-opening-post-date")
            posted = self._clean_text(post_elem.get_text(" ", strip=True) if post_elem is not None else "")
            more_locations = self._clean_text(
                " ".join(
                    node.get_text(" ", strip=True)
                    for node in card.select("[id^='job_item_location_'], .mdf-overlay-popover sdf-button")
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
        """Extract structured job detail data from HTML content.
        Parameters:
            - self (object): Instance used to access helper methods for cleaning text and extracting fields.
            - url (str): The job detail page URL.
            - html (str): Raw HTML content of the job detail page.
        Returns:
            - dict | None: A dictionary containing extracted job fields such as title, url, job_id, location, posted_date, requisition_id, salary, description, and apply_url; or None if no valid title is found."""
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.select_one("h1, .job-details-title, .job-description-title")
        title = self._clean_text(title_node.get_text(" ", strip=True) if title_node is not None else "")
        if len(title) < 3:
            return None

        body_text = self._clean_text(soup.get_text(" ", strip=True))
        record: dict[str, str] = {
            "title": title,
            "url": url,
        }
        job_id = self._extract_job_id_from_url(url)
        if job_id:
            record["job_id"] = job_id

        location = self._extract_detail_location(soup)
        if location:
            record["location"] = location

        posted_match = re.search(r"(\d+\+?\s+days?\s+ago)", body_text, flags=re.IGNORECASE)
        if posted_match:
            record["posted_date"] = self._clean_text(posted_match.group(1))

        requisition_match = re.search(r"Requisition\s+ID:\s*([A-Za-z0-9\-_]+)", body_text, flags=re.IGNORECASE)
        if requisition_match:
            record["requisition_id"] = requisition_match.group(1)

        salary_match = re.search(
            r"Salary\s+Range:\s*([$€£].+?(?:Annually|Hourly|Monthly|Weekly))\b",
            body_text,
            flags=re.IGNORECASE,
        )
        if salary_match:
            record["salary"] = self._clean_text(salary_match.group(1))

        description = self._extract_detail_description(body_text)
        if description:
            record["description"] = description

        apply_url = self._build_apply_url(url, job_id)
        if apply_url:
            record["apply_url"] = apply_url
        return record

    def _extract_detail_location(self, soup: BeautifulSoup) -> str:
        details = []
        for node in soup.select(".current-opening-location-item span, .current-opening-location-item"):
            value = self._clean_text(node.get_text(" ", strip=True))
            if value and value not in details:
                details.append(value)
        return " | ".join(details[:4])

    def _extract_detail_description(self, body_text: str) -> str:
        """Extracts and cleans a job detail description from the provided body text.
        Parameters:
            - body_text (str): The raw text to search for a detail description.
        Returns:
            - str: The cleaned detail description if found; otherwise, an empty string."""
        patterns = [
            r"Apply\s+Salary\s+Range:.*?\s(.*?)(?:BackApply|Copyright)",
            r"Apply\s+(.*?)(?:BackApply|Copyright)",
        ]
        for pattern in patterns:
            match = re.search(pattern, body_text, flags=re.IGNORECASE)
            if not match:
                continue
            value = self._clean_text(match.group(1))
            if value and len(value) > 40:
                return value
        return ""

    def _build_apply_url(self, url: str, job_id: str | None) -> str | None:
        """Builds a URL with the given job ID added as a query parameter.
        Parameters:
            - url (str): The base URL to update.
            - job_id (str | None): The job ID to append; if not provided, no URL is built.
        Returns:
            - str | None: The updated URL containing the jobId query parameter, or None if job_id is not provided."""
        if not job_id:
            return None
        parsed = urlparse(url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["jobId"] = job_id
        next_query = urlencode(params)
        return urlunparse(parsed._replace(query=next_query))

    def _extract_job_dom_id(self, card: BeautifulSoup) -> str | None:
        """Extract the first job DOM ID matching a digit-and-underscore pattern from a card or its descendants.
        Parameters:
            - card (BeautifulSoup): The BeautifulSoup element representing a job card to inspect.
        Returns:
            - str | None: The matched DOM ID string if found; otherwise None."""
        candidates = [
            str(card.get("id") or "").strip(),
        ]
        for node in card.select("[id]"):
            candidates.append(str(node.get("id") or "").strip())
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
        """Determine whether a page appears to be a job detail page based on URL, HTML, or surface text.
        Parameters:
            - url (str): The page URL to inspect for detail-page indicators.
            - html (str): The page HTML content to search for detail-related markers.
            - surface (str): A surface or label string used to detect detail-page context.
        Returns:
            - bool: True if the input appears to represent a detail page; otherwise False."""
        lowered_surface = str(surface or "").lower()
        lowered_url = str(url or "").lower()
        lowered_html = str(html or "").lower()
        return (
            "detail" in lowered_surface
            or "jobid=" in lowered_url
            or "requisition id:" in lowered_html
            or "backapply" in lowered_html
        )

    def _clean_text(self, value: str) -> str:
        return " ".join(str(value or "").split()).strip()
