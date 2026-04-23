# Shared utility functions for crawl operations.
# Extracted to break circular dependencies between crawl_crud, pipeline, and _batch_runtime.
from __future__ import annotations

import csv
import io
import logging
import re
import asyncio
from html import unescape
from typing import Any, Protocol

import regex as regex_lib
from app.services.exceptions import CrawlerConfigurationError
from app.services.xpath_service import validate_xpath_syntax

HTTP_URL_PREFIXES = ("http://", "https://")
logger = logging.getLogger(__name__)


class _SettingsViewLike(Protocol):
    def urls(self) -> list[str]: ...
    def get(self, key: str, default: Any = None) -> Any: ...
    def has(self, key: str) -> bool: ...
    def advanced_enabled(self) -> bool: ...


# CSV parsing


def parse_csv_urls(csv_content: str) -> list[str]:
    """Parse URLs from CSV content (first column, skip header if present)."""
    urls: list[str] = []
    reader = csv.reader(io.StringIO(csv_content))
    for i, row in enumerate(reader):
        if not row:
            continue
        cell = row[0].strip()
        if i == 0 and not cell.startswith(HTTP_URL_PREFIXES):
            continue  # skip header
        if cell.startswith(HTTP_URL_PREFIXES):
            urls.append(cell)
    return urls


async def parse_csv_urls_async(csv_content: str) -> list[str]:
    return await asyncio.to_thread(parse_csv_urls, csv_content)


# URL normalization and collection


def normalize_target_url(value: object) -> str:
    """Normalize a target URL while rejecting pasted multi-value inputs."""
    text = unescape(str(value or "")).strip()
    if not text:
        return ""
    if re.search(r"\s", text):
        logger.warning("Rejected target URL containing internal whitespace: %r", text)
        return ""
    from app.services.field_value_core import strip_tracking_query_params

    normalized = strip_tracking_query_params(text)
    if normalized:
        return normalized
    return text


def _settings_view(settings: object) -> _SettingsViewLike | dict:
    if (
        hasattr(settings, "urls")
        and hasattr(settings, "get")
        and hasattr(settings, "has")
        and hasattr(settings, "advanced_enabled")
    ):
        return settings
    return settings if isinstance(settings, dict) else {}


def collect_target_urls(
    payload: dict,
    settings: object,
) -> list[str]:
    """Collect and deduplicate all target URLs from payload and settings."""
    settings_view = _settings_view(settings)
    candidates: list[str] = []

    # Direct URL from payload
    direct_url = normalize_target_url(payload.get("url"))
    if direct_url:
        candidates.append(direct_url)

    # URLs array from payload
    for value in payload.get("urls") or []:
        candidate = normalize_target_url(value)
        if candidate:
            candidates.append(candidate)

    # URLs array from settings
    setting_urls = (
        settings_view.urls()
        if hasattr(settings_view, "urls")
        else (settings_view.get("urls") or [])
    )
    for value in setting_urls:
        candidate = normalize_target_url(value)
        if candidate:
            candidates.append(candidate)

    # CSV content from settings
    csv_content = str(settings_view.get("csv_content") or "")
    if csv_content:
        candidates.extend(parse_csv_urls(csv_content))

    # Deduplicate while preserving order
    return list(dict.fromkeys(candidates))


# Traversal mode resolution

_TRAVERSAL_MODES = {"paginate", "scroll", "load_more", "single", "sitemap", "crawl"}


def resolve_traversal_mode(settings: object) -> str | None:
    """Resolve and validate the traversal mode from settings."""
    settings_view = _settings_view(settings)
    advanced_enabled_value = settings_view.get("advanced_enabled")
    advanced_enabled = (
        settings_view.advanced_enabled()
        if hasattr(settings_view, "advanced_enabled")
        else bool(advanced_enabled_value)
    )
    advanced_flag_present = (
        settings_view.has("advanced_enabled")
        if hasattr(settings_view, "has")
        else advanced_enabled_value is not None
    )
    if advanced_flag_present and not advanced_enabled:
        return None
    # Preserve user-owned advanced mode semantics from the unified crawl UI.
    # `auto` means the app must detect the effective listing traversal mode.
    mode = (
        str(
            settings_view.get("traversal_mode")
            or settings_view.get("advanced_mode")
            or ""
        )
        .strip()
        .lower()
    )
    if mode in {"", "none"}:
        return None
    if mode == "auto":
        return "auto" if advanced_enabled else None
    if mode == "pagination":
        mode = "paginate"
    if mode == "infinite_scroll":
        mode = "scroll"
    if mode == "view_all":
        mode = "load_more"
    if mode in _TRAVERSAL_MODES:
        return mode
    logger.error("Unrecognized traversal_mode=%r", mode)
    raise CrawlerConfigurationError(f"Unsupported traversal_mode: {mode}")


# Extraction contract validation


def validate_extraction_contract(contract_rows: list[dict]) -> None:
    """Validate extraction contract rows for field names, XPath, and regex syntax.

    Raises ValueError if any validation errors are found.
    """
    errors: list[str] = []
    for index, row in enumerate(contract_rows, start=1):
        field_name = str(row.get("field_name") or "").strip()
        xpath = str(row.get("xpath") or "").strip()
        regex = str(row.get("regex") or "").strip()

        if not field_name:
            errors.append(f"Row {index}: field_name is required")

        if xpath:
            valid_xpath, xpath_error = validate_xpath_syntax(xpath)
            if not valid_xpath:
                errors.append(
                    f"Row {index} ({field_name or 'unnamed'}): invalid XPath ({xpath_error})"
                )

        if regex:
            try:
                regex_lib.compile(regex)
            except regex_lib.error as exc:
                errors.append(
                    f"Row {index} ({field_name or 'unnamed'}): invalid regex ({exc})"
                )

    if errors:
        raise ValueError("; ".join(errors))
