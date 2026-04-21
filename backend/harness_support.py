from __future__ import annotations

import html
import os
from pathlib import Path

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import User
from app.services._batch_runtime import process_run
from app.services.adapters.registry import registered_adapters
from app.services.crawl_crud import create_crawl_run, get_run_records
from app.services.pipeline.core import process_single_url
from app.services.pipeline.types import URLProcessingConfig
from app.services.platform_policy import configured_adapter_names, detect_platform_family, job_platform_families, platform_config_for_family
from app.services.publish import VERDICT_PARTIAL, VERDICT_SUCCESS
from sqlalchemy import select

HARNESS_MODE_ACQUISITION_ONLY = "acquisition_only"
HARNESS_MODE_FULL_PIPELINE = "full_pipeline"

_DETAIL_HINTS = ("/products/", "/product/", "/p/", "/dp/", "/job/", "/viewjob", "showjob=")
_LISTING_HINTS = ("/collections", "/shop/", "/category/", "/careers", "/jobs", "job-search", "career-page", "jobboard", "recruitment", "currentopenings")
_JOB_LISTING_HINTS = ("/jobs", "/careers", "job-search", "career-page", "jobboard", "recruitment", "currentopenings", "searchrelation=", "mode=location", "sortby=", "page=")
_SUCCESS_VERDICTS = {VERDICT_SUCCESS.lower(), VERDICT_PARTIAL.lower()}
_PLACEHOLDER_TITLES = {
    "404",
    "all products",
    "edit",
    "page not found",
    "sylius demo",
}


def infer_surface(url: str, explicit_surface: object | None = None) -> str:
    explicit = str(explicit_surface or "").strip().lower()
    if explicit:
        return explicit
    normalized_url = str(url or "").strip().lower()
    family = detect_platform_family(normalized_url)
    if family in job_platform_families():
        if any(token in normalized_url for token in _JOB_LISTING_HINTS):
            return "job_listing"
        return "job_detail" if any(token in normalized_url for token in ("/job/", "/viewjob", "showjob=")) else "job_listing"
    if any(token in normalized_url for token in _JOB_LISTING_HINTS):
        return "job_listing"
    if any(token in normalized_url for token in _DETAIL_HINTS):
        return "job_detail" if "/job" in normalized_url else "ecommerce_detail"
    if any(token in normalized_url for token in _LISTING_HINTS):
        return "job_listing" if "job" in normalized_url or "career" in normalized_url else "ecommerce_listing"
    return "ecommerce_listing"


def parse_test_sites_markdown(path: Path, *, start_line: int) -> list[dict[str, str]]:
    if not isinstance(start_line, int) or start_line < 1:
        raise ValueError("parse_test_sites_markdown start_line must be an integer >= 1")
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[start_line - 1 :]:
        value = html.unescape(str(line or "").strip())
        if value.startswith(("http://", "https://")):
            rows.append({"name": value, "url": value, "surface": infer_surface(value)})
    return rows


def unavailable_configured_adapters() -> set[str]:
    return set(configured_adapter_names()) - {adapter.name for adapter in registered_adapters()}


def timeout_owner_for_mode(mode: str) -> str:
    return "batch_runtime" if mode == HARNESS_MODE_FULL_PIPELINE else "acquisition_runtime"


def status_for_result(result: dict[str, object]) -> str:
    return "PASS" if classify_failure_mode(result) == "success" else "FAIL"


async def run_site_harness(*, url: str, surface: str, mode: str) -> dict[str, object]:
    async with SessionLocal() as session:
        run = await create_crawl_run(
            session,
            await _ensure_harness_user_id(session),
            {"run_type": "crawl", "url": url, "surface": surface, "settings": {"max_pages": 5, "max_scrolls": 5}},
        )
        if mode == HARNESS_MODE_FULL_PIPELINE:
            await process_run(session, run.id)
            await session.refresh(run)
            rows, total_records = await get_run_records(session, run.id, 1, 5)
            first = rows[0] if rows else None
            data = dict(first.data) if first else {}
            acquisition = dict((first.source_trace or {}).get("acquisition") or {}) if first else {}
            summary = run.summary_dict()
            return {
                "run_id": run.id,
                "status": run.status,
                "verdict": str(summary.get("extraction_verdict") or ""),
                "method": _summary_value(summary, "methods"),
                "platform_family": _summary_value(summary, "platform_families"),
                "status_code": acquisition.get("status_code"),
                "blocked": bool(acquisition.get("blocked")),
                "browser_diagnostics": dict(acquisition.get("browser_diagnostics") or {}),
                "records": max(total_records, _safe_int(summary.get("record_count"))),
                "sample_title": str(data.get("title") or "")[:120],
                "populated_fields": _populated_field_count(data),
                "error": str(summary.get("error") or "").strip() or None,
            }
            url_result = await process_single_url(
            session=session,
            run=run,
            url=url,
            config=URLProcessingConfig.from_acquisition_plan(
                run.settings_view.acquisition_plan(surface=surface),
                update_run_state=False,
                persist_logs=False,
                prefetch_only=True,
            ),
        )
        metrics = dict(url_result.url_metrics or {})
        return {
            "run_id": run.id,
            "status": run.status,
            "verdict": str(url_result.verdict or ""),
            "method": str(metrics.get("method") or "").strip() or None,
            "platform_family": str(metrics.get("platform_family") or "").strip() or None,
            "status_code": metrics.get("status_code"),
            "blocked": bool(metrics.get("blocked")),
            "browser_diagnostics": {},
            "records": int(metrics.get("record_count", 0) or 0),
            "sample_title": "",
            "populated_fields": 0,
            "error": str(metrics.get("error") or "").strip() or None,
        }


def classify_failure_mode(result: dict[str, object]) -> str:
    verdict = str(result.get("verdict") or "").strip().lower()
    diagnostics = dict(result.get("browser_diagnostics")) if isinstance(result.get("browser_diagnostics"), dict) else {}
    error_text = str(result.get("error") or "").lower()
    browser_outcome = str(diagnostics.get("browser_outcome") or "").strip().lower()
    status_code = _safe_int(result.get("status_code"))
    if verdict in _SUCCESS_VERDICTS and not _looks_like_placeholder_or_wrong_content(result, diagnostics):
        return "success"
    if diagnostics.get("networkidle_timed_out"):
        return "spa_readiness_timeout"
    if browser_outcome == "low_content_shell" and status_code in {404, 410}:
        return "spa_shell_404"
    if browser_outcome == "low_content_shell":
        return "spa_shell_low_content"
    if "timeout" in error_text:
        return "timeout"
    if "getaddrinfo failed" in error_text:
        return "dns_or_network_failure"
    if "chrome-error://chromewebdata/" in error_text:
        return "browser_navigation_failure"
    if result.get("blocked") or _diagnostics_indicate_challenge(diagnostics):
        return "blocked"
    if verdict == "listing_detection_failed":
        return "listing_extraction_empty"
    if verdict == "empty":
        return "detail_extraction_empty"
    if verdict == "error":
        return "error"
    if _looks_like_placeholder_or_wrong_content(result, diagnostics):
        return "wrong_content_or_placeholder"
    family = str(result.get("platform_family") or "").strip().lower()
    expected_adapters = {
        str(name).strip().lower()
        for name in ((platform_config_for_family(family).adapter_names if platform_config_for_family(family) else []))
        if str(name or "").strip()
    }
    missing_registrations = unavailable_configured_adapters()
    if expected_adapters and expected_adapters.issubset(missing_registrations):
        return "adapter_not_registered"
    if expected_adapters and not result.get("adapter_name"):
        return "adapter_not_matched"
    if family and not expected_adapters and str(result.get("surface") or "").startswith("job_"):
        return "platform_family_without_adapter"
    if _safe_int(result.get("records")) == 0:
        return "listing_extraction_empty" if str(result.get("surface") or "").endswith("_listing") else "detail_extraction_empty"
    return "unknown_failure"


def _diagnostics_indicate_challenge(diagnostics: dict[str, object]) -> bool:
    evidence = [str(item or "").strip().lower() for item in list(diagnostics.get("challenge_evidence") or []) if str(item or "").strip()]
    return str(diagnostics.get("browser_outcome") or "").strip().lower() == "challenge_page" or bool(list(diagnostics.get("challenge_element_hits") or [])) or bool(list(diagnostics.get("challenge_provider_hits") or [])) or any(item.startswith(("title:", "strong:", "provider:", "active_provider:", "challenge_element:")) for item in evidence)


def _looks_like_placeholder_or_wrong_content(result: dict[str, object], diagnostics: dict[str, object]) -> bool:
    sample_title = str(result.get("sample_title") or "").strip()
    return (
        str(diagnostics.get("browser_outcome") or "").strip().lower() == "low_content_shell"
        or (
            _safe_int(result.get("records")) > 0
            and not sample_title
            and _safe_int(result.get("populated_fields")) <= 1
        )
        or _looks_like_placeholder_title(sample_title, populated_fields=_safe_int(result.get("populated_fields")))
    )


def _looks_like_placeholder_title(title: str, *, populated_fields: int) -> bool:
    normalized = " ".join(str(title or "").strip().lower().split())
    if normalized not in _PLACEHOLDER_TITLES:
        return False
    return populated_fields <= 2


def _populated_field_count(record: dict[str, object]) -> int:
    return sum(1 for key, value in record.items() if value not in (None, "", [], {}) and not str(key).startswith("_"))


def _summary_value(summary: dict[str, object], key: str) -> str | None:
    values = dict(summary.get("acquisition_summary") or {}).get(key)
    return str(next(iter(values))) if isinstance(values, dict) and values else None


async def _ensure_harness_user_id(session) -> int:
    if _is_production_environment():
        raise RuntimeError("Harness user access is disabled outside local/test environments")
    harness_email = str(os.getenv("HARNESS_EMAIL") or "").strip().lower()
    harness_password = str(os.getenv("HARNESS_PASSWORD") or "").strip()
    harness_role = str(os.getenv("HARNESS_ROLE") or "harness").strip().lower() or "harness"
    if not harness_email:
        raise RuntimeError("HARNESS_EMAIL must be configured for harness runs")
    if not harness_password:
        raise RuntimeError("HARNESS_PASSWORD must be configured for harness runs")
    user = (
        await session.execute(select(User).where(User.email == harness_email).limit(1))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            email=harness_email,
            hashed_password=hash_password(harness_password),
            role=harness_role,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return int(user.id)


def _is_production_environment() -> bool:
    env_name = (
        os.getenv("APP_ENV")
        or os.getenv("FLASK_ENV")
        or os.getenv("ENV")
        or "development"
    )
    return str(env_name).strip().lower() not in {"", "development", "dev", "local", "test", "testing"}


def _safe_int(value: object) -> int:
    try:
        return 0 if value in (None, "") else int(str(value))
    except (TypeError, ValueError):
        return 0
