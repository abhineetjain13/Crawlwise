from __future__ import annotations

from app.models.crawl_settings import CrawlRunSettings
from app.services.acquisition.acquirer import AcquisitionResult


def build_acquisition_profile(run_settings: dict | CrawlRunSettings | None) -> dict[str, object]:
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
    timing_map = (
        diagnostics.get("timings_ms")
        if isinstance(diagnostics.get("timings_ms"), dict)
        else {}
    )
    # Prefer top-level traversal_summary (surfaced by acquirer) over nested browser_diagnostics
    _browser_diag = diagnostics.get("browser_diagnostics") if isinstance(diagnostics.get("browser_diagnostics"), dict) else {}
    _raw_ts = diagnostics.get("traversal_summary") or _browser_diag.get("traversal_summary")
    traversal_summary = _raw_ts if isinstance(_raw_ts, dict) else {}
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
            "requested_surface": str(diagnostics.get("surface_requested") or "").strip()
            or None,
            "effective_surface": str(diagnostics.get("surface_effective") or "").strip()
            or None,
            "browser_attempted": bool(diagnostics.get("browser_attempted")),
            "browser_used": acq.method == "playwright",
            "acquisition_outcome": str(diagnostics.get("acquisition_outcome") or "").strip()
            or None,
            "memory_browser_first": bool(diagnostics.get("memory_browser_first")),
            "proxy_used": bool(diagnostics.get("proxy_used")),
            "network_payloads": len(acq.network_payloads or []),
            "promoted_sources": len(acq.promoted_sources or []),
            "frame_sources": len(acq.frame_sources or []),
            "host_wait_seconds": float(diagnostics.get("host_wait_seconds", 0.0) or 0.0),
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
            "browser_traversal_ms": int(timing_map.get("browser_traversal_ms", 0) or 0),
            "traversal_attempted": bool(traversal_summary),
            "traversal_fallback_used": fallback_used,
            "traversal_pages_collected": pages_collected,
            "traversal_mode_used": mode_used,
            "traversal_stop_reason": stop_reason,
            "surface_remapped": bool(diagnostics.get("surface_remapped")),
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
    quality_summary = {
        key: value
        for key, value in {
            "record_count": len(records),
            "requested_fields_total": requested_total or None,
            "requested_fields_found_best": url_metrics.get("requested_fields_found_best"),
            "acquisition_outcome": url_metrics.get("acquisition_outcome"),
            "listing_quality": url_metrics.get("listing_quality"),
            "listing_quality_flags": url_metrics.get("listing_quality_flags"),
            "winning_sources": url_metrics.get("winning_sources"),
        }.items()
        if value not in (None, "", [], {})
    }
    if quality_summary:
        url_metrics["quality_summary"] = quality_summary
    return url_metrics
