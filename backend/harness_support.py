from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.crawl import CrawlRun
from app.models.user import User
from app.services.extract.shared_variant_logic import variant_axis_name_is_semantic
from app.services._batch_runtime import process_run
from app.services.adapters.registry import registered_adapters
from app.services.crawl_crud import create_crawl_run, get_run_records
from app.services.pipeline.core import process_single_url
from app.services.pipeline.types import URLProcessingConfig
from app.services.platform_policy import configured_adapter_names, detect_platform_family, job_platform_families, platform_config_for_family
from app.services.publish import VERDICT_PARTIAL, VERDICT_SUCCESS
from app.services.config.extraction_rules import (
    LISTING_UTILITY_TITLE_PATTERNS,
    LISTING_UTILITY_TITLE_TOKENS,
    LISTING_UTILITY_URL_TOKENS,
)
from sqlalchemy import select

HARNESS_MODE_ACQUISITION_ONLY = "acquisition_only"
HARNESS_MODE_FULL_PIPELINE = "full_pipeline"
DEFAULT_SITE_SET_PATH = (
    Path(__file__).resolve().parent / "test_site_sets" / "commerce_browser_heavy.json"
)

_DETAIL_HINTS = ("/products/", "/product/", "/p/", "/dp/", "/job/", "/viewjob", "showjob=", "/release/")
_LISTING_HINTS = ("/collections", "/shop/", "/category/", "/careers", "/jobs", "job-search", "career-page", "jobboard", "recruitment", "currentopenings")
_JOB_LISTING_HINTS = (
    "/jobs",
    "/careers",
    "/search/results",
    "/search?",
    "job-search",
    "career-page",
    "jobboard",
    "recruitment",
    "currentopenings",
    "searchrelation=",
    "mode=location",
    "sortby=",
    "page=",
)
_SUCCESS_VERDICTS = {VERDICT_SUCCESS.lower(), VERDICT_PARTIAL.lower()}
_PLACEHOLDER_TITLES = {
    "404",
    "all products",
    "edit",
    "page not found",
    "sylius demo",
}
_DETAIL_SLUG_WITH_ID_RE = re.compile(r".+_\d+$")
_DETAIL_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*\.(?:html?|htm)$")
_NON_DETAIL_FILE_RE = re.compile(r"^(?:index|page[-_]?\d+)\.(?:html?|htm)$")
_UTILITY_TITLE_REGEXES = tuple(
    re.compile(pattern, re.I) for pattern in LISTING_UTILITY_TITLE_PATTERNS
)
_IDENTITY_SEGMENT_SKIP = {
    "c",
    "catalog",
    "collections",
    "dp",
    "item",
    "items",
    "p",
    "page",
    "product",
    "products",
    "release",
    "releases",
    "shop",
    "store",
    "w",
}
_IDENTITY_TOKEN_SKIP = {
    "and",
    "for",
    "from",
    "the",
    "with",
}
_GENERIC_DETAIL_SECTION_TITLES = {
    "customers also bought",
    "frequently bought together",
    "recommended products",
    "related products",
    "you may also like",
}


def infer_surface(url: str, explicit_surface: object | None = None) -> str:
    explicit = str(explicit_surface or "").strip().lower()
    if explicit:
        return explicit
    normalized_url = str(url or "").strip().lower()
    parsed_url = urlsplit(normalized_url)
    host = str(parsed_url.hostname or "").strip().lower()
    host_label = host.removeprefix("www.").split(".", 1)[0]
    path_segments = [segment for segment in parsed_url.path.split("/") if segment]
    family = detect_platform_family(normalized_url)
    if (
        family in job_platform_families()
        or host.endswith(".jobs")
        or host.endswith("startup.jobs")
        or host.endswith("usajobs.gov")
    ):
        if any(token in normalized_url for token in _JOB_LISTING_HINTS):
            return "job_listing"
        return "job_detail" if any(token in normalized_url for token in ("/job/", "/viewjob", "showjob=")) else "job_listing"
    if any(token in host_label for token in ("job", "career")) and not any(
        token in normalized_url for token in _DETAIL_HINTS
    ):
        return "job_listing"
    if any(token in normalized_url for token in _JOB_LISTING_HINTS):
        return "job_listing"
    if host.endswith("autozone.com") and normalized_url.rstrip("/").rsplit("/", 1)[-1].count("_") >= 2:
        return "ecommerce_detail"
    if (
        len(path_segments) >= 2
        and path_segments[-1] == "index.html"
        and _DETAIL_SLUG_WITH_ID_RE.fullmatch(path_segments[-2])
    ):
        return "ecommerce_detail"
    if any(token in normalized_url for token in _DETAIL_HINTS):
        return "job_detail" if "/job" in normalized_url else "ecommerce_detail"
    terminal = path_segments[-1].lower() if path_segments else ""
    if (
        _DETAIL_FILE_RE.fullmatch(terminal)
        and not _NON_DETAIL_FILE_RE.fullmatch(terminal)
        and any(separator in terminal for separator in ("-", "_"))
        and not any(token in terminal for token in ("jobs", "careers", "category", "collection"))
    ):
        return "ecommerce_detail"
    if any(token in normalized_url for token in _LISTING_HINTS):
        return "job_listing" if "job" in normalized_url or "career" in normalized_url else "ecommerce_listing"
    return "ecommerce_listing"


def build_explicit_sites(
    urls: list[str],
    *,
    explicit_surfaces: list[str] | None = None,
) -> list[dict[str, str]]:
    normalized_urls = [str(value or "").strip() for value in list(urls or []) if str(value or "").strip()]
    normalized_surfaces = [
        str(value or "").strip()
        for value in list(explicit_surfaces or [])
        if str(value or "").strip()
    ]
    if normalized_surfaces and len(normalized_surfaces) != len(normalized_urls):
        raise ValueError("Explicit URL and surface counts must match")
    rows: list[dict[str, str]] = []
    for index, url in enumerate(normalized_urls):
        explicit_surface = normalized_surfaces[index] if index < len(normalized_surfaces) else ""
        rows.append(
            {
                "name": url,
                "url": url,
                "surface": infer_surface(url, explicit_surface=explicit_surface),
            }
        )
    return rows


def load_site_set(path: Path, *, site_set_name: str) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("site_sets"), dict):
        site_set = payload["site_sets"].get(site_set_name)
        if not isinstance(site_set, dict):
            raise ValueError(f"Unknown site set: {site_set_name}")
        sites = site_set.get("sites")
        if not isinstance(sites, list):
            raise ValueError(f"Site set {site_set_name} has no sites list")
    elif isinstance(payload, dict) and isinstance(payload.get("sites"), list):
        manifest_name = str(payload.get("name") or path.stem).strip()
        if site_set_name not in {"", manifest_name, path.stem}:
            raise ValueError(f"Unknown site set: {site_set_name}")
        sites = payload["sites"]
    else:
        raise ValueError(f"Invalid site-set payload in {path}")
    rows: list[dict[str, object]] = []
    for item in sites:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        row = {
            "name": str(item.get("name") or url).strip(),
            "url": url,
            "surface": infer_surface(
                url,
                explicit_surface=item.get("surface"),
            ),
            "bucket": str(item.get("bucket") or "").strip().lower() or None,
            "expected_failure_modes": [
                str(value).strip()
                for value in list(item.get("expected_failure_modes") or [])
                if str(value).strip()
            ],
            "artifact_run_id": _safe_int(item.get("artifact_run_id")) or None,
            "seed_failure_mode": str(item.get("seed_failure_mode") or "").strip().lower() or None,
            "quality_expectations": dict(item.get("quality_expectations") or {}) if isinstance(item.get("quality_expectations"), (dict, type(None))) else {},
        }
        gate = str(item.get("gate") or "").strip().lower() or None
        expected = dict(item.get("expected") or {}) if isinstance(item.get("expected"), dict) else {}
        known_failure_mode = str(item.get("known_failure_mode") or "").strip() or None
        if gate:
            row["gate"] = gate
        if expected:
            row["expected"] = expected
        if known_failure_mode:
            row["known_failure_mode"] = known_failure_mode
        rows.append(row)
    return rows


def parse_test_sites_markdown(path: Path, *, start_line: int) -> list[dict[str, str]]:
    if not isinstance(start_line, int) or start_line < 1:
        raise ValueError("parse_test_sites_markdown start_line must be an integer >= 1")
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[start_line - 1 :]:
        value = html.unescape(str(line or "").strip())
        if not value:
            continue
        if value.startswith(("http://", "https://")):
            rows.append({"name": value, "url": value, "surface": infer_surface(value)})
            continue
        if not value.startswith("|") or "http" not in value:
            continue
        cells = [cell.strip() for cell in value.strip("|").split("|")]
        url = ""
        explicit_surface = ""
        name = ""
        for index, cell in enumerate(cells):
            match = re.search(r"https?://[^`\s|>]+", cell)
            if match is not None and not url:
                url = match.group(0).strip().rstrip("`")
                name = url
            if not explicit_surface and index > 0:
                normalized = re.sub(r"[^a-z0-9]+", "_", str(cell or "").strip().lower()).strip("_")
                if normalized in {
                    "listing",
                    "ajax_listing",
                    "infinite_scroll",
                    "spa_listing",
                    "detail",
                    "spa_detail",
                }:
                    explicit_surface = {
                        "listing": "ecommerce_listing",
                        "ajax_listing": "ecommerce_listing",
                        "infinite_scroll": "ecommerce_listing",
                        "spa_listing": "ecommerce_listing",
                        "detail": "ecommerce_detail",
                        "spa_detail": "ecommerce_detail",
                    }[normalized]
                    break
        if url:
            rows.append(
                {
                    "name": name or url,
                    "url": url,
                    "surface": infer_surface(url, explicit_surface=explicit_surface),
                }
            )
    return rows


def unavailable_configured_adapters() -> set[str]:
    return set(configured_adapter_names()) - {adapter.name for adapter in registered_adapters()}


def timeout_owner_for_mode(mode: str) -> str:
    return "batch_runtime" if mode == HARNESS_MODE_FULL_PIPELINE else "acquisition_runtime"


def status_for_result(result: dict[str, object]) -> str:
    if "ok" in result:
        return "PASS" if bool(result.get("ok")) else "FAIL"
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
            rows, total_records = await get_run_records(session, run.id, 1, 100)
            return _persisted_run_result(
                run=run,
                rows=rows,
                total_records=total_records,
                requested_url=url,
                run_source="live_run",
            )
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
        challenge_summary = _challenge_summary_from_diagnostics(
            dict(metrics.get("browser_diagnostics") or {})
        )
        return {
            "run_id": run.id,
            "status": run.status,
            "requested_url": url,
            "verdict": str(url_result.verdict or ""),
            "method": str(metrics.get("method") or "").strip() or None,
            "platform_family": str(metrics.get("platform_family") or "").strip() or None,
            "status_code": metrics.get("status_code"),
            "blocked": bool(metrics.get("blocked")),
            "browser_diagnostics": {},
            "records": int(metrics.get("record_count", 0) or 0),
            "sample_title": "",
            "populated_fields": 0,
            "challenge_summary": challenge_summary,
            "run_source": "live_run",
            "error": str(metrics.get("error") or "").strip() or None,
        }


async def review_saved_run(
    *,
    run_id: int,
    requested_url: str | None = None,
) -> dict[str, object]:
    async with SessionLocal() as session:
        run = (
            await session.execute(select(CrawlRun).where(CrawlRun.id == int(run_id)).limit(1))
        ).scalar_one_or_none()
        if run is None:
            raise RuntimeError(f"Saved harness run {run_id} was not found")
        rows, total_records = await get_run_records(session, run.id, 1, 100)
        return _persisted_run_result(
            run=run,
            rows=rows,
            total_records=total_records,
            requested_url=str(requested_url or run.url or "").strip(),
            run_source="artifact_review",
        )


def classify_failure_mode(result: dict[str, object]) -> str:
    verdict = str(result.get("verdict") or "").strip().lower()
    diagnostics = dict(result.get("browser_diagnostics")) if isinstance(result.get("browser_diagnostics"), dict) else {}
    error_text = str(result.get("error") or "").lower()
    browser_outcome = str(diagnostics.get("browser_outcome") or "").strip().lower()
    status_code = _safe_int(result.get("status_code"))
    if verdict in _SUCCESS_VERDICTS and _looks_like_detail_identity_mismatch(result):
        return "detail_identity_mismatch"
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
    if verdict == "blocked":
        return "blocked"
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


def _challenge_summary_from_diagnostics(diagnostics: dict[str, object]) -> dict[str, object] | None:
    if not _diagnostics_indicate_challenge(diagnostics):
        return None
    provider_hits = [
        str(item or "").strip()
        for item in list(diagnostics.get("challenge_provider_hits") or [])
        if str(item or "").strip()
    ]
    element_hits = [
        str(item or "").strip()
        for item in list(diagnostics.get("challenge_element_hits") or [])
        if str(item or "").strip()
    ]
    evidence = [
        str(item or "").strip()
        for item in list(diagnostics.get("challenge_evidence") or [])
        if str(item or "").strip()
    ]
    summary = {
        "browser_outcome": str(diagnostics.get("browser_outcome") or "").strip().lower() or None,
        "provider": provider_hits[0].lower() if provider_hits else None,
        "providers": [item.lower() for item in provider_hits],
        "elements": element_hits,
        "evidence": evidence[:5],
    }
    return summary


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


def _looks_like_utility_chrome_success(result: dict[str, object]) -> bool:
    sample_records = result.get("sample_records")
    if isinstance(sample_records, list):
        for row in sample_records[:2]:
            if not isinstance(row, dict):
                continue
            if _looks_like_utility_record(
                title=row.get("title"),
                url=row.get("url"),
            ):
                return True
    if bool(result.get("sample_looks_like_utility_chrome")):
        return True
    return _looks_like_utility_record(
        title=result.get("sample_title"),
        url=result.get("sample_url"),
    )


def _looks_like_detail_identity_mismatch(result: dict[str, object]) -> bool:
    surface = str(result.get("surface") or "").strip().lower()
    if not surface.endswith("_detail"):
        return False
    requested_url = str(result.get("requested_url") or "").strip()
    if not requested_url:
        return False
    sample_url = str(result.get("sample_url") or "").strip()
    if not sample_url:
        return False
    sample_path = _identity_path(sample_url)
    requested_path = _identity_path(requested_url)
    if sample_path in {"", "/"} and requested_path not in {"", "/"} and sample_path != requested_path:
        return True
    requested_tokens = _primary_identity_tokens(requested_url)
    if len(requested_tokens) < 2:
        return False
    sample_url_tokens = _primary_identity_tokens(sample_url)
    sample_title = " ".join(str(result.get("sample_title") or "").strip().lower().split())
    sample_title_tokens = _identity_tokens(sample_title)
    overlap = max(
        _identity_overlap_count(requested_tokens, sample_url_tokens),
        _identity_overlap_count(requested_tokens, sample_title_tokens),
    )
    required_overlap = _required_identity_overlap(len(requested_tokens))
    if sample_title in _GENERIC_DETAIL_SECTION_TITLES and overlap < required_overlap:
        return True
    return bool((sample_url_tokens or sample_title_tokens) and overlap < required_overlap)


def _looks_like_placeholder_title(title: str, *, populated_fields: int) -> bool:
    normalized = " ".join(str(title or "").strip().lower().split())
    if "can't be found" in normalized or normalized.startswith("oops!"):
        return populated_fields <= 6
    if normalized not in _PLACEHOLDER_TITLES:
        return False
    return populated_fields <= 2


def _populated_field_count(record: dict[str, object]) -> int:
    return sum(1 for key, value in record.items() if value not in (None, "", [], {}) and not str(key).startswith("_"))


def _sample_records(rows: list[object]) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for row in list(rows or [])[:3]:
        data = dict(getattr(row, "data", {}) or {})
        samples.append(
            {
                "title": str(data.get("title") or "")[:160],
                "url": str(data.get("url") or "")[:240],
                "populated_fields": _populated_field_count(data),
                "price_present": data.get("price") not in (None, "", [], {}),
            }
        )
    return samples


def _sample_record_audit(sample_records: list[dict[str, object]]) -> dict[str, object]:
    coverage_values = [
        _safe_int(row.get("populated_fields"))
        for row in sample_records
        if isinstance(row, dict)
    ]
    utility_hits = [
        index
        for index, row in enumerate(sample_records, start=1)
        if isinstance(row, dict)
        and _looks_like_utility_record(
            title=row.get("title"),
            url=row.get("url"),
        )
    ]
    return {
        "field_coverage": {
            "avg_populated_fields": round(sum(coverage_values) / max(1, len(coverage_values)), 2),
            "max_populated_fields": max(coverage_values, default=0),
            "min_populated_fields": min(coverage_values, default=0),
        },
        "utility_noise_hits": utility_hits,
        "looks_like_utility_chrome": bool(utility_hits),
    }


def _looks_like_utility_record(*, title: object, url: object) -> bool:
    normalized_title = " ".join(str(title or "").strip().lower().split())
    normalized_url = str(url or "").strip().lower()
    if normalized_title:
        if any(pattern.search(normalized_title) for pattern in _UTILITY_TITLE_REGEXES):
            return True
        if any(token in normalized_title for token in LISTING_UTILITY_TITLE_TOKENS):
            return True
    return bool(
        normalized_url
        and any(token in normalized_url for token in LISTING_UTILITY_URL_TOKENS)
    )


def _identity_path(url: str) -> str:
    parsed = urlsplit(str(url or "").strip())
    path = str(parsed.path or "").strip()
    if path in {"", "/"} and str(parsed.fragment or "").strip():
        fragment = str(parsed.fragment or "").strip()
        return fragment if fragment.startswith("/") else f"/{fragment}"
    return path


def _persisted_run_result(
    *,
    run: CrawlRun,
    rows: list[object],
    total_records: int,
    requested_url: str,
    run_source: str,
) -> dict[str, object]:
    first = rows[0] if rows else None
    data = dict(first.data) if first else {}
    acquisition = dict((first.source_trace or {}).get("acquisition") or {}) if first else {}
    summary = run.summary_dict()
    sample_records = _sample_records(rows)
    sample_audit = _sample_record_audit(sample_records)
    challenge_summary = _challenge_summary_from_diagnostics(
        dict(acquisition.get("browser_diagnostics") or {})
    )
    return {
        "run_id": run.id,
        "status": run.status,
        "requested_url": requested_url,
        "verdict": str(summary.get("extraction_verdict") or ""),
        "method": _summary_value(summary, "methods"),
        "platform_family": _summary_value(summary, "platform_families"),
        "status_code": acquisition.get("status_code"),
        "blocked": bool(acquisition.get("blocked")),
        "browser_diagnostics": dict(acquisition.get("browser_diagnostics") or {}),
        "records": max(total_records, _safe_int(summary.get("record_count"))),
        "sample_title": str(data.get("title") or "")[:120],
        "sample_url": str(data.get("url") or "")[:240],
        "sample_record_data": data,
        "sample_records": sample_records,
        "sample_semantics": _sample_semantics(data),
        "listing_contract": _listing_contract(rows),
        "populated_fields": _populated_field_count(data),
        "sample_field_coverage": sample_audit["field_coverage"],
        "sample_utility_noise_hits": sample_audit["utility_noise_hits"],
        "sample_looks_like_utility_chrome": sample_audit["looks_like_utility_chrome"],
        "challenge_summary": challenge_summary,
        "run_source": run_source,
        "error": str(summary.get("error") or "").strip() or None,
    }


def _sample_semantics(record: dict[str, object]) -> dict[str, object]:
    variant_axes = dict(record.get("variant_axes") or {}) if isinstance(record.get("variant_axes"), dict) else {}
    axis_keys = [str(key).strip() for key in variant_axes.keys() if str(key).strip()]
    selected_variant = dict(record.get("selected_variant") or {}) if isinstance(record.get("selected_variant"), dict) else {}
    variants = list(record.get("variants") or []) if isinstance(record.get("variants"), list) else []
    return {
        "price_present": record.get("price") not in (None, "", [], {}),
        "currency_present": record.get("currency") not in (None, "", [], {}),
        "variant_count": max(_safe_int(record.get("variant_count")), len(variants)),
        "variant_axes_keys": axis_keys,
        "variant_axes_semantic": bool(axis_keys) and all(
            variant_axis_name_is_semantic(key) for key in axis_keys
        ),
        "selected_variant_present": bool(selected_variant),
        "selected_variant_has_price": selected_variant.get("price") not in (None, "", [], {}),
        "selected_variant_has_option_values": bool(
            isinstance(selected_variant.get("option_values"), dict)
            and selected_variant.get("option_values")
        ),
    }


def _listing_contract(rows: list[object]) -> dict[str, object]:
    detail_url_count = 0
    price_present_count = 0
    numeric_price_count = 0
    sampled = 0
    for row in list(rows or []):
        data = dict(getattr(row, "data", {}) or {})
        sampled += 1
        row_url = str(data.get("url") or "").strip()
        if row_url and not _looks_like_utility_record(title=data.get("title"), url=row_url):
            detail_url_count += 1
        if data.get("price") not in (None, "", [], {}):
            price_present_count += 1
            if _looks_numeric_price(data.get("price")):
                numeric_price_count += 1
    return {
        "sampled_records": sampled,
        "detail_url_count": detail_url_count,
        "detail_urls_present": detail_url_count > 0,
        "price_present_count": price_present_count,
        "price_numeric_count": numeric_price_count,
    }


def evaluate_quality(
    site: dict[str, object],
    result: dict[str, object],
) -> dict[str, object]:
    expectations = _quality_expectations(site, result=result)
    checks = {
        "identity_ok": _quality_identity_ok(result),
        "listing_noise_ok": _quality_listing_noise_ok(result, expectations=expectations),
        "variant_presence_ok": _quality_variant_presence_ok(result, expectations=expectations),
        "variant_labels_ok": _quality_variant_labels_ok(result, expectations=expectations),
        "selected_variant_price_ok": _quality_selected_variant_price_ok(result, expectations=expectations),
    }
    observed_failure_mode = _observed_quality_failure_mode(
        site,
        result,
        checks=checks,
        expectations=expectations,
    )
    quality_verdict = _quality_verdict(
        result,
        checks=checks,
        expectations=expectations,
        observed_failure_mode=observed_failure_mode,
    )
    return {
        "quality_verdict": quality_verdict,
        "observed_failure_mode": observed_failure_mode,
        "quality_checks": checks,
    }


def _quality_expectations(
    site: dict[str, object],
    *,
    result: dict[str, object],
) -> dict[str, bool]:
    surface = str((site.get("surface") or result.get("surface") or "")).strip().lower()
    configured = dict(site.get("quality_expectations") or {})
    expectations = {
        "require_identity": surface.endswith("_detail"),
        "require_listing_noise_free": surface.endswith("_listing"),
        "require_price": False,
        "expect_variants": False,
        "require_semantic_variant_labels": False,
        "require_selected_variant_price": False,
    }
    for key in list(expectations):
        if key in configured:
            expectations[key] = bool(configured.get(key))
    return expectations


def _quality_identity_ok(result: dict[str, object]) -> bool:
    diagnostics = dict(result.get("browser_diagnostics") or {})
    if str(result.get("failure_mode") or "").strip().lower() == "blocked":
        return False
    if _looks_like_placeholder_or_wrong_content(result, diagnostics):
        return False
    if _looks_like_detail_identity_mismatch(result):
        return False
    surface = str(result.get("surface") or "").strip().lower()
    if surface.endswith("_listing"):
        sample_records = list(result.get("sample_records") or [])
        return any(
            isinstance(row, dict)
            and str(row.get("title") or "").strip()
            and str(row.get("url") or "").strip()
            and not _looks_like_utility_record(title=row.get("title"), url=row.get("url"))
            for row in sample_records
        )
    return not (_looks_like_site_shell_success(result) or _looks_like_promo_or_wrong_page(result))


def _quality_listing_noise_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_listing_noise_free"):
        return True
    if _looks_like_utility_chrome_success(result):
        return False
    sample_records = list(result.get("sample_records") or [])
    if sample_records and not any(_looks_like_real_listing_row(row) for row in sample_records[:3]):
        return False
    return True


def _quality_variant_presence_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("expect_variants"):
        return True
    semantics = dict(result.get("sample_semantics") or {})
    return _safe_int(semantics.get("variant_count")) >= 2 and bool(semantics.get("selected_variant_present"))


def _quality_variant_labels_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_semantic_variant_labels"):
        return True
    semantics = dict(result.get("sample_semantics") or {})
    axis_keys = list(semantics.get("variant_axes_keys") or [])
    return bool(axis_keys) and bool(semantics.get("variant_axes_semantic"))


def _quality_selected_variant_price_ok(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_selected_variant_price"):
        return True
    semantics = dict(result.get("sample_semantics") or {})
    return bool(semantics.get("selected_variant_has_price"))


def _price_requirement_failed(
    result: dict[str, object],
    *,
    expectations: dict[str, bool],
) -> bool:
    if not expectations.get("require_price"):
        return False
    surface = str(result.get("surface") or "").strip().lower()
    if surface.endswith("_listing"):
        return not any(
            isinstance(row, dict) and bool(row.get("price_present"))
            for row in list(result.get("sample_records") or [])
        )
    semantics = dict(result.get("sample_semantics") or {})
    return not bool(semantics.get("price_present"))


def _observed_quality_failure_mode(
    site: dict[str, object],
    result: dict[str, object],
    *,
    checks: dict[str, bool],
    expectations: dict[str, bool],
) -> str:
    if str(result.get("failure_mode") or "").strip().lower() == "blocked":
        return "blocked"
    if not checks["identity_ok"]:
        if _looks_like_promo_or_wrong_page(result):
            return "promo_or_wrong_page"
        if _looks_like_site_shell_success(result):
            return "shell_false_success"
        if _looks_like_detail_identity_mismatch(result):
            return "detail_identity_mismatch"
        return "bad_output"
    if not checks["listing_noise_ok"]:
        return "listing_chrome_noise"
    if expectations.get("expect_variants") and not checks["variant_presence_ok"]:
        return "thin_detail"
    if expectations.get("require_semantic_variant_labels") and not checks["variant_labels_ok"]:
        return "axis_pollution"
    if expectations.get("require_selected_variant_price") and not checks["selected_variant_price_ok"]:
        return "selected_variant_price_missing"
    if _price_requirement_failed(result, expectations=expectations):
        return "thin_detail"
    seeded_failure_mode = str(site.get("seed_failure_mode") or "").strip().lower()
    if str(result.get("run_source") or "").strip().lower() == "artifact_review" and seeded_failure_mode:
        return seeded_failure_mode
    return "control_good"


def _quality_verdict(
    result: dict[str, object],
    *,
    checks: dict[str, bool],
    expectations: dict[str, bool],
    observed_failure_mode: str,
) -> str:
    if str(result.get("failure_mode") or "").strip().lower() == "blocked":
        return "blocked"
    if observed_failure_mode in {
        "bad_output",
        "detail_identity_mismatch",
        "listing_chrome_noise",
        "promo_or_wrong_page",
        "shell_false_success",
    }:
        return "bad_output"
    if _price_requirement_failed(result, expectations=expectations):
        return "usable_with_gaps"
    if not all(bool(value) for value in checks.values()):
        return "usable_with_gaps"
    return "good"


def _looks_like_site_shell_success(result: dict[str, object]) -> bool:
    surface = str(result.get("surface") or "").strip().lower()
    if not surface.endswith("_detail"):
        return False
    sample_title = " ".join(str(result.get("sample_title") or "").strip().lower().split())
    if not sample_title:
        return True
    semantics = dict(result.get("sample_semantics") or {})
    if bool(semantics.get("price_present")) or _safe_int(semantics.get("variant_count")) >= 2:
        return False
    title_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", sample_title)
        if len(token) >= 3
    }
    host = str(urlsplit(str(result.get("requested_url") or result.get("url") or "")).hostname or "").strip().lower()
    host_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", host.removeprefix("www."))
        if len(token) >= 3
    }
    return bool(host_tokens and host_tokens & title_tokens and _safe_int(result.get("populated_fields")) <= 6)


def _looks_like_promo_or_wrong_page(result: dict[str, object]) -> bool:
    sample_title = " ".join(str(result.get("sample_title") or "").strip().lower().split())
    sample_url = str(result.get("sample_url") or "").strip().lower()
    promo_tokens = ("promo", "new arrivals", "sale", "shop all", "category", "categories")
    return any(token in sample_title for token in promo_tokens) or any(
        token in sample_url for token in ("/promo", "promo-", "products=newarrival", "/sale", "/category")
    )


def _summary_value(summary: dict[str, object], key: str) -> str | None:
    values = dict(summary.get("acquisition_summary") or {}).get(key)
    return str(next(iter(values))) if isinstance(values, dict) and values else None


def _primary_identity_tokens(value: str) -> set[str]:
    raw_value = str(value or "").strip()
    if not raw_value:
        return set()
    parsed = urlsplit(raw_value)
    if parsed.scheme or parsed.netloc or raw_value.startswith("/"):
        path = unquote(str(parsed.path or "").strip())
        segments = [segment for segment in path.split("/") if segment]
        for segment in reversed(segments):
            cleaned = re.sub(r"\.(?:html?|htm)$", "", segment.strip().lower())
            if not cleaned or cleaned.isdigit() or cleaned in _IDENTITY_SEGMENT_SKIP:
                continue
            return _identity_tokens(cleaned)
        return set()
    return _identity_tokens(unquote(raw_value.lower()))


def _identity_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").strip().lower())
        if len(token) >= 2 and not token.isdigit() and token not in _IDENTITY_TOKEN_SKIP
    }


def _identity_overlap_count(left: set[str], right: set[str]) -> int:
    if not left or not right:
        return 0
    return len(left & right)


def _required_identity_overlap(token_count: int) -> int:
    if token_count <= 2:
        return token_count
    if token_count == 3:
        return 2
    return max(2, (token_count * 3 + 4) // 5)


def _looks_like_real_listing_row(row: object) -> bool:
    if not isinstance(row, dict):
        return False
    title = row.get("title")
    url = row.get("url")
    return (
        bool(str(title or "").strip())
        and bool(str(url or "").strip())
        and bool(row.get("price_present"))
        and not _looks_like_utility_record(title=title, url=url)
    )


async def _ensure_harness_user_id(session) -> int:
    if _is_production_environment():
        raise RuntimeError("Harness user access is disabled outside local/test environments")
    harness_email = str(os.getenv("HARNESS_EMAIL") or "").strip().lower()
    harness_password = str(os.getenv("HARNESS_PASSWORD") or "").strip()
    harness_role = str(os.getenv("HARNESS_ROLE") or "harness").strip().lower() or "harness"
    if not harness_email:
        harness_email = "harness@local.invalid"
    if not harness_password:
        harness_password = "HarnessLocalOnly123!"
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


def _looks_numeric_price(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            normalized = text.replace(".", "").replace(",", ".")
        else:
            normalized = text.replace(",", "")
    elif "," in text and re.fullmatch(r"^\d+,\d+$", text):
        normalized = text.replace(",", ".")
    elif "." in text and re.fullmatch(r"^\d{1,3}(?:\.\d{3})+$", text):
        normalized = text.replace(".", "")
    return bool(re.fullmatch(r"^\d+(?:\.\d+)?$", normalized))
