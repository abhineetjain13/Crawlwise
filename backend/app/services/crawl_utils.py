# Shared utility functions for crawl operations.
# Extracted to break circular dependencies between crawl_crud, pipeline, and _batch_runtime.
from __future__ import annotations

import csv
import io
import logging
import re
from html import unescape
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlparse

import regex as regex_lib
from app.services.xpath_service import validate_xpath_syntax

HTTP_URL_PREFIXES = ("http://", "https://")
logger = logging.getLogger(__name__)


def _log_for_pytest(level: int, message: str, *args: object) -> None:
    logger.log(level, message, *args)
    root_logger = logging.getLogger()
    if any(type(handler).__name__ == "LogCaptureHandler" for handler in root_logger.handlers):
        root_logger.log(level, message, *args)

_JOB_HOST_HINTS = (
    "workforcenow.adp.com",
    "myjobs.adp.com",
    "recruiting.adp.com",
    "icims.com",
    "ultipro.com",
    "ukg.com",
    "oraclecloud.com",
    "myworkdayjobs.com",
    "greenhouse.io",
    "lever.co",
    "paycomonline.net",
    "saashr.com",
    "jobvite.com",
)
_JOB_LISTING_PATH_HINTS = (
    "/careers",
    "/jobs",
    "/search-jobs",
    "/jobboard",
    "/requisitions",
)
_JOB_DETAIL_PATH_HINTS = (
    "/job/",
    "/jobs/",
    "/job-detail",
    "/job-details",
    "/jobdetail",
    "/jobboard/jobdetails",
    "/opportunitydetail",
    "/requisition/",
)
_COMMERCE_LISTING_PATH_HINTS = (
    "/category/",
    "/categories/",
    "/collections/",
    "/shop/",
    "/search",
    "/c/",
)
_COMMERCE_DETAIL_PATH_HINTS = (
    "/product/",
    "/products/",
    "/p/",
    "/dp/",
    "/item/",
)


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


# URL normalization and collection

def normalize_target_url(value: object) -> str:
    """Normalize a target URL by removing whitespace and unescaping HTML entities."""
    text = unescape(str(value or "")).strip()
    if not text:
        return ""
    return re.sub(r"\s+", "", text)


def infer_surface_from_url(url: object, fallback_surface: str = "") -> str:
    """Infer the crawl surface from URL structure, with fallback preservation."""
    normalized_url = normalize_target_url(url)
    normalized_fallback = str(fallback_surface or "").strip().lower()
    valid_surfaces = {"job_listing", "job_detail", "ecommerce_listing", "ecommerce_detail"}
    if not normalized_fallback:
        fallback = "ecommerce_listing"
    elif normalized_fallback in valid_surfaces:
        fallback = normalized_fallback
    else:
        raise ValueError(f"Invalid fallback_surface: {normalized_fallback}")
    if not normalized_url:
        return fallback
    try:
        parsed = urlparse(normalized_url)
    except ValueError:
        return fallback
    path = str(parsed.path or "").lower()
    query = str(parsed.query or "").lower()
    combined = f"{path}?{query}" if query else path
    hostname = str(parsed.hostname or "").lower()
    query_keys = {
        str(key or "").strip().lower()
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        if str(key or "").strip()
    }

    job_host = any(
        hostname == hint or hostname.endswith(f".{hint}") for hint in _JOB_HOST_HINTS
    )
    if (
        any(token in combined for token in _JOB_DETAIL_PATH_HINTS)
        or {"jobid", "job_id", "opportunityid", "showjob"} & query_keys
    ):
        return "job_detail"
    if (
        any(token in combined for token in _JOB_LISTING_PATH_HINTS)
        or job_host
        or {"keywords", "careersearch"} & query_keys
    ):
        return "job_listing"
    if (
        any(token in combined for token in _COMMERCE_DETAIL_PATH_HINTS)
        or {"sku", "variant"} & query_keys
    ):
        return "ecommerce_detail"
    if (
        any(token in combined for token in _COMMERCE_LISTING_PATH_HINTS)
        or {"category", "q", "query"} & query_keys
    ):
        return "ecommerce_listing"
    return fallback


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

_TRAVERSAL_MODES = {"paginate", "scroll", "load_more"}


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
    # `auto` means "no explicit traversal helper requested".
    mode = str(
        settings_view.get("traversal_mode")
        or settings_view.get("advanced_mode")
        or ""
    ).strip().lower()
    if mode in {"", "none", "single"}:
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
    if advanced_enabled:
        _log_for_pytest(
            logging.WARNING,
            "Unrecognized traversal_mode=%r with advanced_enabled=true; defaulting to auto",
            mode,
        )
        return "auto"
    _log_for_pytest(logging.WARNING, "Unrecognized traversal_mode=%r; ignoring", mode)
    return None


# Field name normalization

def normalize_committed_field_name(value: object) -> str:
    """Normalize a field name to snake_case format."""
    text = str(value or "").strip()
    if not text:
        return ""
    # Convert camelCase to snake_case
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    # Replace spaces with underscores and lowercase
    normalized = re.sub(r"\s+", "_", text.lower())
    # Remove non-alphanumeric characters except underscores
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    # Collapse multiple underscores
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


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
