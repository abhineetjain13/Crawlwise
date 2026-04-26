from __future__ import annotations


def build_acquisition_profile(settings_view) -> dict[str, object]:
    if hasattr(settings_view, "acquisition_profile"):
        return dict(settings_view.acquisition_profile())
    return {}


def _challenge_evidence_rows(diagnostics: dict[str, object]) -> list[str]:
    raw_evidence = diagnostics.get("challenge_evidence")
    evidence_items = raw_evidence if isinstance(raw_evidence, list) else []
    return [
        str(item or "").strip().lower()
        for item in evidence_items
        if str(item or "").strip()
    ]


def _readiness_probes(diagnostics: dict[str, object]) -> list[dict[str, object]]:
    raw_probes = diagnostics.get("readiness_probes")
    if not isinstance(raw_probes, list):
        return []
    return [dict(item) for item in raw_probes if isinstance(item, dict)]


def _has_ready_readiness_probe(diagnostics: dict[str, object]) -> bool:
    return any(bool(probe.get("is_ready")) for probe in _readiness_probes(diagnostics))


def _has_strong_challenge_evidence(
    diagnostics: dict[str, object],
    evidence: list[str],
) -> bool:
    return any(
        item.startswith(("title:", "strong:", "active_provider:"))
        for item in evidence
    )


def diagnostics_indicate_block(diagnostics: dict[str, object] | object) -> bool:
    payload = dict(diagnostics or {}) if isinstance(diagnostics, dict) else {}
    browser_outcome = str(payload.get("browser_outcome") or "").strip().lower()
    provider_hits_raw = payload.get("challenge_provider_hits")
    provider_hits = provider_hits_raw if isinstance(provider_hits_raw, list) else []
    evidence = _challenge_evidence_rows(payload)
    if browser_outcome == "challenge_page":
        return True
    if _has_strong_challenge_evidence(payload, evidence):
        return True
    if browser_outcome == "usable_content" and _has_ready_readiness_probe(payload):
        return False
    provider_evidence = provider_hits or [
        item for item in evidence if item.startswith("provider:")
    ]
    if provider_evidence:
        return browser_outcome != "usable_content"
    if browser_outcome == "usable_content":
        return False
    return False


def is_effectively_blocked(acquisition_result) -> bool:
    if bool(getattr(acquisition_result, "blocked", False)):
        return True
    diagnostics = (
        dict(getattr(acquisition_result, "browser_diagnostics", {}) or {})
        if isinstance(getattr(acquisition_result, "browser_diagnostics", {}), dict)
        else {}
    )
    return diagnostics_indicate_block(diagnostics)


def build_url_metrics(
    acquisition_result,
    *,
    requested_fields: list[str] | None = None,
) -> dict[str, object]:
    browser_diagnostics = (
        dict(acquisition_result.browser_diagnostics or {})
        if isinstance(acquisition_result.browser_diagnostics, dict)
        else {}
    )
    selected_traversal_mode = str(
        browser_diagnostics.get("selected_traversal_mode")
        or browser_diagnostics.get("requested_traversal_mode")
        or ""
    ).strip()
    requested_traversal_mode = str(
        browser_diagnostics.get("requested_traversal_mode") or ""
    ).strip()
    traversal_activated = bool(browser_diagnostics.get("traversal_activated"))
    progress_events = int(browser_diagnostics.get("traversal_progress_events", 0) or 0)
    pages_advanced = int(browser_diagnostics.get("pages_advanced", 0) or 0)
    collected_pages = 1
    if traversal_activated:
        if selected_traversal_mode == "paginate":
            collected_pages = max(1, pages_advanced + 1)
        else:
            collected_pages = max(1, progress_events + 1)
    phase_timings_ms = (
        dict(browser_diagnostics.get("phase_timings_ms") or {})
        if isinstance(browser_diagnostics.get("phase_timings_ms"), dict)
        else {}
    )
    browser_attempted = bool(browser_diagnostics.get("browser_attempted")) or (
        acquisition_result.method == "browser"
    )
    return {
        "method": acquisition_result.method,
        "status_code": acquisition_result.status_code,
        "blocked": is_effectively_blocked(acquisition_result),
        "final_url": acquisition_result.final_url,
        "requested_fields": list(requested_fields or []),
        "browser_used": acquisition_result.method == "browser",
        "browser_attempted": browser_attempted,
        "browser_reason": browser_diagnostics.get("browser_reason"),
        "browser_outcome": browser_diagnostics.get("browser_outcome"),
        "html_bytes": int(browser_diagnostics.get("html_bytes", 0) or 0),
        "browser_phase_timings_ms": phase_timings_ms,
        "network_payloads": len(list(acquisition_result.network_payloads or [])),
        "adapter_name": acquisition_result.adapter_name,
        "platform_family": getattr(acquisition_result, "platform_family", None),
        "failure_reason": browser_diagnostics.get("failure_reason"),
        "browser_navigation_strategy": browser_diagnostics.get("navigation_strategy"),
        "network_payload_count": int(
            browser_diagnostics.get("network_payload_count", 0) or 0
        ),
        "malformed_network_payloads": int(
            browser_diagnostics.get("malformed_network_payloads", 0) or 0
        ),
        "requested_traversal_mode": requested_traversal_mode or None,
        "traversal_mode_used": selected_traversal_mode or None,
        "traversal_stop_reason": browser_diagnostics.get("traversal_stop_reason"),
        "traversal_attempted": bool(requested_traversal_mode),
        "traversal_succeeded": progress_events > 0,
        "traversal_fell_back": bool(requested_traversal_mode) and not traversal_activated,
        "traversal_fallback_used": bool(
            browser_diagnostics.get("traversal_fallback_used")
        ),
        "traversal_fallback_recovered": bool(
            browser_diagnostics.get("traversal_fallback_recovered")
        ),
        "traversal_fallback_record_count": int(
            browser_diagnostics.get("traversal_fallback_record_count", 0) or 0
        ),
        "pages_collected": collected_pages,
        "pages_scrolled": pages_advanced,
        "scroll_iterations": int(browser_diagnostics.get("scroll_iterations", 0) or 0),
        "load_more_clicks": int(browser_diagnostics.get("load_more_clicks", 0) or 0),
        "traversal_iterations": int(
            browser_diagnostics.get("traversal_iterations", 0) or 0
        ),
    }


def finalize_url_metrics(
    url_metrics: dict[str, object],
    *,
    record_count: int,
) -> dict[str, object]:
    finalized = dict(url_metrics or {})
    finalized["record_count"] = max(0, int(record_count))
    return finalized
