from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.crawl_settings import CrawlRunSettings

if TYPE_CHECKING:
    from app.services.acquisition import AcquisitionResult


def _clamp_quality_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score, 1.0))


def _quality_level_from_score(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _quality_score(
    url_metrics: dict[str, object],
    *,
    record_count: int,
    requested_total: int,
) -> float:
    if record_count <= 0:
        return 0.0

    requested_found_best = int(url_metrics.get("requested_fields_found_best", 0) or 0)
    requested_coverage = (
        min(requested_found_best / requested_total, 1.0) if requested_total > 0 else 0.6
    )
    score = 0.45 + (requested_coverage * 0.4)

    listing_quality = str(url_metrics.get("listing_quality") or "").strip().lower()
    if listing_quality == "meaningful":
        score = max(score, 0.85)
    elif listing_quality == "extractable":
        score = max(score, 0.65)
    elif listing_quality == "link_only":
        score = min(score, 0.45)
    elif listing_quality == "invalid":
        score = 0.0

    listing_completeness = (
        url_metrics.get("listing_completeness")
        if isinstance(url_metrics.get("listing_completeness"), dict)
        else {}
    )
    if listing_completeness.get("applicable"):
        if listing_completeness.get("complete", True):
            score = max(score, 0.8)
        else:
            score = min(score, 0.45)

    variant_completeness = (
        url_metrics.get("variant_completeness")
        if isinstance(url_metrics.get("variant_completeness"), dict)
        else {}
    )
    if variant_completeness.get("applicable") and not variant_completeness.get(
        "complete", True
    ):
        score = min(score, 0.45)

    return _clamp_quality_score(score)


def build_acquisition_profile(
    run_settings: dict | CrawlRunSettings | None,
) -> dict[str, object]:
    settings_view = (
        run_settings
        if isinstance(run_settings, CrawlRunSettings)
        else CrawlRunSettings.from_value(run_settings)
    )
    return settings_view.acquisition_profile()


def build_url_metrics(
    acq: AcquisitionResult,
    *,
    requested_fields: list[str],
) -> dict[str, object]:
    diagnostics = acq.diagnostics if isinstance(acq.diagnostics, dict) else {}
    surface_selection_warnings = (
        diagnostics.get("surface_selection_warnings")
        if isinstance(diagnostics.get("surface_selection_warnings"), list)
        else []
    )
    surface_warning_signals = sorted(
        {
            str(signal).strip()
            for warning in surface_selection_warnings
            if isinstance(warning, dict)
            for signal in (warning.get("signals") or [])
            if str(signal).strip()
        }
    )
    timing_map = (
        diagnostics.get("timings_ms")
        if isinstance(diagnostics.get("timings_ms"), dict)
        else {}
    )
    browser_diag = (
        diagnostics.get("browser_diagnostics")
        if isinstance(diagnostics.get("browser_diagnostics"), dict)
        else {}
    )
    raw_traversal_summary = (
        diagnostics.get("traversal_summary") or browser_diag.get("traversal_summary")
    )
    traversal_summary = (
        raw_traversal_summary if isinstance(raw_traversal_summary, dict) else {}
    )
    mode_used = str(traversal_summary.get("mode_used") or "").strip() or None
    fallback_used = bool(traversal_summary.get("fallback_used"))
    pages_collected = int(traversal_summary.get("pages_collected", 0) or 0)
    stop_reason = str(traversal_summary.get("stop_reason") or "").strip() or None
    return {
        key: value
        for key, value in {
            "method": acq.method,
            "content_type": acq.content_type,
            "platform_family": str(diagnostics.get("curl_platform_family") or "").strip()
            or None,
            "browser_attempted": bool(diagnostics.get("browser_attempted")),
            "browser_used": acq.method == "playwright",
            "acquisition_outcome": str(diagnostics.get("acquisition_outcome") or "").strip()
            or None,
            "invalid_surface_page": bool(diagnostics.get("invalid_surface_page")),
            "soft_404_page": bool(diagnostics.get("soft_404_page")),
            "transactional_page": bool(diagnostics.get("transactional_page")),
            "surface_warning_signals": surface_warning_signals or None,
            "memory_browser_first": bool(diagnostics.get("memory_browser_first")),
            "proxy_used": bool(diagnostics.get("proxy_used")),
            "network_payloads": len(acq.network_payloads or []),
            "promoted_sources": len(acq.promoted_sources or []),
            "frame_sources": len(acq.frame_sources or []),
            "host_wait_seconds": float(
                diagnostics.get("host_wait_seconds", 0.0) or 0.0
            ),
            "requested_fields": len(requested_fields or []),
            "curl_fetch_ms": int(timing_map.get("curl_fetch_ms", 0) or 0),
            "browser_decision_ms": int(timing_map.get("browser_decision_ms", 0) or 0),
            "browser_launch_ms": int(timing_map.get("browser_launch_ms", 0) or 0),
            "browser_origin_warm_ms": int(
                timing_map.get("browser_origin_warm_ms", 0) or 0
            ),
            "browser_navigation_ms": int(
                timing_map.get("browser_navigation_ms", 0) or 0
            ),
            "browser_challenge_wait_ms": int(
                timing_map.get("browser_challenge_wait_ms", 0) or 0
            ),
            "browser_listing_readiness_wait_ms": int(
                timing_map.get("browser_listing_readiness_wait_ms", 0) or 0
            ),
            "browser_traversal_ms": int(
                timing_map.get("browser_traversal_ms", 0) or 0
            ),
            "traversal_attempted": bool(traversal_summary),
            "traversal_fallback_used": fallback_used,
            "traversal_pages_collected": pages_collected,
            "traversal_mode_used": mode_used,
            "traversal_stop_reason": stop_reason,
        }.items()
        if value not in (None, "", [], {})
    }


def finalize_url_metrics(
    url_metrics: dict[str, object],
    *,
    records: list[dict],
    requested_fields: list[str],
) -> dict[str, object]:
    from app.services.pipeline.field_normalization import _requested_field_coverage

    found_counts = [
        int(
            (_requested_field_coverage(record, requested_fields) or {}).get("found", 0)
            or 0
        )
        for record in records
    ]
    requested_total = len([field for field in requested_fields if field])
    url_metrics["record_count"] = len(records)
    if requested_total > 0:
        url_metrics["requested_fields_total"] = requested_total
        url_metrics["requested_fields_found_best"] = max(found_counts or [0])
    quality_score = _quality_score(
        url_metrics,
        record_count=len(records),
        requested_total=requested_total,
    )
    quality_summary = {
        key: value
        for key, value in {
            "record_count": len(records),
            "requested_fields_total": requested_total or None,
            "requested_fields_found_best": url_metrics.get(
                "requested_fields_found_best"
            ),
            "score": quality_score,
            "level": _quality_level_from_score(quality_score)
            if len(records) > 0
            else "unknown",
            "acquisition_outcome": url_metrics.get("acquisition_outcome"),
            "listing_quality": url_metrics.get("listing_quality"),
            "listing_quality_flags": url_metrics.get("listing_quality_flags"),
            "listing_completeness": url_metrics.get("listing_completeness"),
            "variant_completeness": url_metrics.get("variant_completeness"),
            "winning_sources": url_metrics.get("winning_sources"),
        }.items()
        if value not in (None, "", [], {})
    }
    if quality_summary:
        url_metrics["quality_summary"] = quality_summary
    return url_metrics
