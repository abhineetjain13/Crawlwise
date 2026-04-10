from __future__ import annotations

from app.services.acquisition.acquirer import AcquisitionResult


def _requested_field_coverage(record: dict, requested_fields: list[str]) -> dict:
    """Calculate coverage of requested fields in a record."""
    if not requested_fields:
        return {}
    normalized_requested = [field for field in requested_fields if field]
    found = [
        field
        for field in normalized_requested
        if record.get(field) not in (None, "", [], {})
    ]
    return {
        "requested": len(normalized_requested),
        "found": len(found),
        "missing": [field for field in normalized_requested if field not in found],
    }


def build_acquisition_profile(run_settings: dict | None) -> dict[str, object]:
    profile: dict[str, object] = {}
    settings = run_settings if isinstance(run_settings, dict) else {}
    if "anti_bot_enabled" in settings:
        profile["anti_bot_enabled"] = bool(settings.get("anti_bot_enabled"))
    if "ignore_https_errors" in settings:
        profile["ignore_https_errors"] = bool(settings.get("ignore_https_errors"))
    if "bypass_csp" in settings:
        profile["bypass_csp"] = bool(settings.get("bypass_csp"))
    return profile


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
    return url_metrics
