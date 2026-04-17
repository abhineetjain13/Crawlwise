from __future__ import annotations

import re

import jmespath

_EMPTY_VALUES = (None, "", [], {})

_PLATFORM_PATTERNS = {
    "greenhouse": (r"greenhouse\.io",),
    "workday": (r"workday",),
    "saashr": (r"saashr\.com", r"job-requisitions", r"job-search/config"),
}

_PAYLOAD_SPECS: dict[str, dict[str, str]] = {
    "greenhouse": {
        "title": "title",
        "department": "departments[0].name",
        "location": "location.name",
        "salary_min": "pay_input_ranges[0].min_cents",
        "salary_max": "pay_input_ranges[0].max_cents",
        "description": "content",
    },
    "workday": {
        "title": "title",
        "company": "bulletFields[?type=='company'].value | [0]",
        "location": "bulletFields[?type=='location'].value | [0]",
        "job_type": "bulletFields[?type=='timeType'].value | [0]",
        "description": "jobDescription",
    },
    "saashr_detail": {
        "title": "job_title",
        "description": "job_description",
        "requirements": "job_requirement",
        "benefits": "job_preview",
        "job_type": "employee_type.name",
        "apply_url": "_page_url",
    },
    "saashr_company": {
        "company": "comp_name",
    },
}


def collect_network_payload_candidates(
    field_name: str,
    *,
    payloads: list[dict],
    surface: str,
    page_url: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        payload_url = str(payload.get("url") or "")
        body = payload.get("body")
        if not isinstance(body, dict):
            continue
        spec_name = _payload_spec_name(payload_url, body=body, surface=surface)
        if not spec_name:
            continue
        projected = dict(body)
        projected["_page_url"] = page_url
        value = _search_spec_value(spec_name, field_name=field_name, payload=projected)
        if value in _EMPTY_VALUES:
            continue
        rows.append(
            {
                "value": value,
                "source": _source_label_for_spec(spec_name),
                "payload_url": payload_url,
            }
        )
    return rows


def _payload_spec_name(payload_url: str, *, body: dict, surface: str) -> str | None:
    surface_name = str(surface or "").strip().lower()
    url = payload_url.lower()
    if "job" not in surface_name:
        return None
    if _matches_platform("saashr", url):
        if "job-requisitions" in url:
            return "saashr_detail"
        if "job-search/config" in url:
            return "saashr_company"
    if _matches_platform("greenhouse", url):
        return "greenhouse"
    if _matches_platform("workday", url):
        return "workday"
    if "job_title" in body or "job_description" in body:
        return "saashr_detail"
    if "comp_name" in body:
        return "saashr_company"
    return None


def _matches_platform(platform: str, payload_url: str) -> bool:
    return any(
        re.search(pattern, payload_url, re.IGNORECASE)
        for pattern in _PLATFORM_PATTERNS.get(platform, ())
    )


def _search_spec_value(spec_name: str, *, field_name: str, payload: dict) -> object:
    expression = _PAYLOAD_SPECS.get(spec_name, {}).get(field_name)
    if not expression:
        return None
    try:
        return jmespath.search(expression, payload)
    except Exception:
        return None


def _source_label_for_spec(spec_name: str) -> str:
    if spec_name.startswith("saashr_"):
        return "saashr_detail"
    return "network_intercept"

