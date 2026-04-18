from __future__ import annotations


def build_acquisition_profile(settings_view) -> dict[str, object]:
    if hasattr(settings_view, "acquisition_profile"):
        return dict(settings_view.acquisition_profile())
    return {}


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
    return {
        "method": acquisition_result.method,
        "status_code": acquisition_result.status_code,
        "blocked": bool(acquisition_result.blocked),
        "final_url": acquisition_result.final_url,
        "requested_fields": list(requested_fields or []),
        "browser_used": acquisition_result.method == "browser",
        "browser_attempted": acquisition_result.method == "browser",
        "network_payloads": len(list(acquisition_result.network_payloads or [])),
        "adapter_name": acquisition_result.adapter_name,
        "platform_family": acquisition_result.adapter_name,
        "browser_navigation_strategy": browser_diagnostics.get("navigation_strategy"),
    }


def finalize_url_metrics(
    url_metrics: dict[str, object],
    *,
    record_count: int,
) -> dict[str, object]:
    finalized = dict(url_metrics or {})
    finalized["record_count"] = max(0, int(record_count))
    return finalized
