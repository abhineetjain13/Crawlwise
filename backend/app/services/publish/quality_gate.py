from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.models.crawl import CrawlRecord, CrawlRun
from app.services.config import export_settings
from app.services.export.schema import clean_export_data
from app.services.field_policy import canonical_requested_fields


def export_quality_report(
    run: CrawlRun | None,
    rows: Sequence[CrawlRecord],
) -> dict[str, Any]:
    required_fields = canonical_requested_fields(
        list(getattr(run, "requested_fields", []) or [])
    )
    total = len(rows)
    field_reports = {
        field_name: _field_fill_report(field_name, rows, total=total)
        for field_name in required_fields
    }
    failed_fields = [
        field_name
        for field_name, report in field_reports.items()
        if float(report["fill_rate"]) < export_settings.EXPORT_REQUIRED_FIELD_MIN_FILL_RATE
    ]
    return {
        "passed": not failed_fields,
        "record_count": total,
        "required_fields": required_fields,
        "min_fill_rate": export_settings.EXPORT_REQUIRED_FIELD_MIN_FILL_RATE,
        "fields": field_reports,
        "failed_fields": failed_fields,
    }


def export_quality_headers(report: dict[str, Any]) -> dict[str, str]:
    return {
        export_settings.EXPORT_QUALITY_GATE_HEADER: "pass"
        if report.get("passed")
        else "fail",
        export_settings.EXPORT_QUALITY_REPORT_HEADER: json.dumps(
            report,
            ensure_ascii=True,
            separators=(",", ":"),
        ),
    }


def _field_fill_report(
    field_name: str,
    rows: Sequence[CrawlRecord],
    *,
    total: int,
) -> dict[str, Any]:
    filled = 0
    for row in rows:
        data = clean_export_data(row.data if isinstance(row.data, dict) else {})
        if data.get(field_name) not in (None, "", [], {}):
            filled += 1
    return {
        "filled": filled,
        "total": total,
        "fill_rate": round(filled / total, 4) if total else 0.0,
    }
