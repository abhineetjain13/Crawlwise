# Review and promotion service.
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.models.crawl import CrawlRecord, CrawlRun, ReviewPromotion
from app.services.config.extraction_rules import REVIEW_CONTAINER_KEYS
from app.services.db_utils import mapping_or_empty
from app.services.domain_run_profile_service import (
    load_domain_run_profile,
    save_domain_run_profile,
)
from app.services.domain_utils import normalize_domain
from app.services.field_policy import normalize_field_key, normalize_review_target
from app.services.normalizers import normalize_value
from app.services.publish import refresh_record_commit_metadata
from app.services.schema_service import load_resolved_schema
from app.services.selectors_runtime import (
    create_selector_record,
    list_selector_records,
    update_selector_record,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _load_domain_mapping(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> dict[str, str]:
    result = await session.execute(
        select(ReviewPromotion.field_mapping)
        .where(
            ReviewPromotion.domain == domain,
            ReviewPromotion.surface == surface,
        )
        .order_by(ReviewPromotion.created_at.desc(), ReviewPromotion.id.desc())
        .limit(1)
    )
    mapping = result.scalar_one_or_none()
    return dict(mapping) if isinstance(mapping, dict) else {}


async def build_review_payload(session: AsyncSession, run_id: int) -> dict | None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return None
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run_id)
    )
    records = list(records_result.scalars().all())
    domain = normalize_domain(run.url)
    canonical_fields = (await load_resolved_schema(session, run.surface, domain)).fields
    domain_mapping = await _load_domain_mapping(
        session,
        domain=domain,
        surface=run.surface,
    )
    normalized_fields = sorted(
        {
            key
            for record in records
            for key, val in mapping_or_empty(record.data).items()
            if val not in (None, "", [], {}) and not str(key).startswith("_")
        }
    )
    discovered_field_names: set[str] = set()
    for record in records:
        for row in _review_bucket_rows(record):
            key = str(row.get("key") or "").strip()
            if key:
                discovered_field_names.add(key)
    if not discovered_field_names:
        for record in records:
            for src in (
                mapping_or_empty(record.discovered_data),
                mapping_or_empty(record.raw_data),
                mapping_or_empty(record.data),
            ):
                for key, val in src.items():
                    if (
                        val not in (None, "", [], {})
                        and not str(key).startswith("_")
                        and key not in REVIEW_CONTAINER_KEYS
                    ):
                        discovered_field_names.add(str(key))
    discovered_fields = sorted(discovered_field_names)
    suggested_mapping = {
        field: domain_mapping.get(field, field) for field in discovered_fields
    }
    return {
        "run": run,
        "records": records,
        "normalized_fields": normalized_fields,
        "discovered_fields": discovered_fields,
        "canonical_fields": canonical_fields,
        "domain_mapping": domain_mapping,
        "suggested_mapping": suggested_mapping,
    }


async def load_review_html(session: AsyncSession, run_id: int) -> str:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return ""
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run_id)
    )
    records = list(records_result.scalars().all())
    return _load_review_html(records)


async def save_review(
    session: AsyncSession, run: CrawlRun, selections: list[dict]
) -> dict:
    selected_rows = [
        row
        for row in selections
        if bool(row.get("selected", True))
        and str(row.get("source_field") or "").strip()
        and str(row.get("output_field") or "").strip()
    ]
    domain = normalize_domain(run.url)
    mapping: dict[str, str] = {}
    for row in selected_rows:
        source_field = normalize_field_key(row.get("source_field"))
        target_field = normalize_review_target(run.surface, row.get("output_field"))
        if source_field and target_field:
            mapping[source_field] = target_field
    resolved_schema = await load_resolved_schema(session, run.surface, domain)
    next_fields = [
        *resolved_schema.fields,
        *list(mapping.values()),
    ]
    normalized_baseline_fields = list(
        dict.fromkeys(
            normalized_field
            for field in resolved_schema.baseline_fields
            if (
                normalized_field := normalize_review_target(run.surface, field)
            )
        )
    )
    normalized_new_fields = list(
        dict.fromkeys(
            normalized_field
            for field in resolved_schema.new_fields
            if (
                normalized_field := normalize_review_target(run.surface, field)
            )
        )
    )
    normalized_baseline_field_set = set(normalized_baseline_fields)
    updated_schema = resolved_schema.__class__(
        surface=resolved_schema.surface,
        domain=resolved_schema.domain,
        baseline_fields=normalized_baseline_fields,
        fields=list(dict.fromkeys(field for field in next_fields if field)),
        new_fields=list(
            dict.fromkeys(
                [
                    *normalized_new_fields,
                    *[
                        normalized_value
                        for value in mapping.values()
                        if (
                            normalized_value := normalize_review_target(
                                run.surface, value
                            )
                        )
                        and normalized_value not in normalized_baseline_field_set
                    ],
                ]
            )
        ),
        deprecated_fields=list(resolved_schema.deprecated_fields),
        source="review",
        saved_at=None,
        stale=False,
    )
    db_run = await session.get(CrawlRun, run.id)
    if db_run is None:
        raise RuntimeError(f"CrawlRun not found for review save: run_id={run.id}")
    saved_at = datetime.now(UTC).isoformat()
    promotion = ReviewPromotion(
        run_id=db_run.id,
        domain=domain,
        surface=db_run.surface,
        approved_schema={
            "fields": updated_schema.fields,
            "baseline_fields": updated_schema.baseline_fields,
            "new_fields": updated_schema.new_fields,
            "deprecated_fields": updated_schema.deprecated_fields,
            "source": updated_schema.source,
            "saved_at": saved_at,
        },
        field_mapping=mapping,
    )
    session.add(promotion)
    await _promote_review_bucket_fields(session, db_run, mapping)
    await session.commit()
    return {
        "run_id": run.id,
        "domain": domain,
        "surface": run.surface,
        "selected_fields": list(dict.fromkeys(mapping.values())),
        "canonical_fields": updated_schema.fields,
        "field_mapping": mapping,
    }


def _load_review_html(records: list[CrawlRecord]) -> str:
    for record in records:
        html = _load_record_html(record)
        if html:
            return html
    return ""


def _load_record_html(record: CrawlRecord) -> str:
    raw_path = str(record.raw_html_path or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path)
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _serialize_record(record: CrawlRecord) -> dict:
    return {
        "id": record.id,
        "run_id": record.run_id,
        "source_url": record.source_url,
        "data": mapping_or_empty(record.data),
        "raw_data": mapping_or_empty(record.raw_data),
        "discovered_data": mapping_or_empty(record.discovered_data),
        "source_trace": mapping_or_empty(record.source_trace),
        "raw_html_path": record.raw_html_path,
        "created_at": record.created_at,
    }


def _review_bucket_rows(record: CrawlRecord) -> list[dict]:
    discovered_data = mapping_or_empty(record.discovered_data)
    rows = discovered_data.get("review_bucket")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


async def _promote_review_bucket_fields(
    session: AsyncSession, run: CrawlRun, mapping: dict[str, str]
) -> None:
    if not mapping:
        return
    normalized_mapping = {
        normalized_source_field: normalized_target_field
        for source_field, target_field in mapping.items()
        if (normalized_source_field := normalize_field_key(source_field))
        and (normalized_target_field := normalize_field_key(target_field))
    }
    if not normalized_mapping:
        return
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id)
    )
    records = list(records_result.scalars().all())
    for record in records:
        review_bucket = _review_bucket_rows(record)
        if not review_bucket:
            continue

        selected_values: dict[str, dict] = {}
        remaining_rows: list[dict] = []
        for row in review_bucket:
            source_field = normalize_field_key(row.get("key"))
            output_field = normalized_mapping.get(source_field)
            if not source_field or not output_field:
                remaining_rows.append(row)
                continue
            current_value = mapping_or_empty(record.data).get(output_field)
            if current_value not in (None, "", [], {}):
                remaining_rows.append(row)
                continue
            existing = selected_values.get(output_field)
            if existing is None:
                selected_values[output_field] = row

        if not selected_values and len(remaining_rows) == len(review_bucket):
            continue

        data = dict(mapping_or_empty(record.data))
        for output_field, row in selected_values.items():
            normalized_value = normalize_value(output_field, row.get("value"))
            data[output_field] = normalized_value
        record.data = data

        discovered_data = dict(mapping_or_empty(record.discovered_data))
        mapped_source_fields = {
            source_field for source_field in normalized_mapping.keys() if source_field
        }
        discovered_data["review_bucket"] = [
            row
            for row in remaining_rows
            if normalize_field_key(row.get("key"))
            not in mapped_source_fields
            or mapping_or_empty(record.data).get(
                normalized_mapping.get(
                    normalize_field_key(row.get("key")), ""
                )
            )
            not in (None, "", [], {})
        ]
        record.discovered_data = {
            key: value
            for key, value in discovered_data.items()
            if value not in (None, "", [], {})
        }

        for output_field, _row in selected_values.items():
            refresh_record_commit_metadata(
                record,
                run=run,
                field_name=output_field,
                value=data[output_field],
                source_label="review_promotion",
            )


async def build_domain_recipe_payload(
    session: AsyncSession,
    *,
    run: CrawlRun,
) -> dict[str, object]:
    records_result = await session.execute(
        select(CrawlRecord).where(CrawlRecord.run_id == run.id).order_by(CrawlRecord.id.asc())
    )
    records = list(records_result.scalars().all())
    domain = normalize_domain(run.url)
    saved_selectors = await list_selector_records(
        session,
        domain=domain,
        surface=run.surface,
    )
    def _selector_signature(
        *,
        field_name: object,
        selector_kind: object,
        selector_value: object,
    ) -> tuple[str, str, str]:
        return (
            str(field_name or "").strip().lower(),
            str(selector_kind or "").strip().lower(),
            str(selector_value or "").strip(),
        )

    def _saved_selector_signature(row: dict[str, object]) -> tuple[str, str, str]:
        if row.get("css_selector"):
            selector_kind = "css_selector"
            selector_value = row.get("css_selector")
        elif row.get("xpath"):
            selector_kind = "xpath"
            selector_value = row.get("xpath")
        else:
            selector_kind = "regex"
            selector_value = row.get("regex")
        return _selector_signature(
            field_name=row.get("field_name"),
            selector_kind=selector_kind,
            selector_value=selector_value,
        )

    saved_selector_index = {
        _saved_selector_signature(row): row
        for row in saved_selectors
    }
    found_fields = sorted(
        {
            str(field_name)
            for record in records
            for field_name, value in mapping_or_empty(record.data).items()
            if value not in (None, "", [], {})
        }
    )
    requested_fields = [str(value) for value in list(run.requested_fields or []) if str(value or "").strip()]
    selector_candidates: dict[str, dict[str, object]] = {}
    browser_required = False
    for record in records:
        source_trace = mapping_or_empty(record.source_trace)
        acquisition = mapping_or_empty(source_trace.get("acquisition"))
        browser_diagnostics = mapping_or_empty(acquisition.get("browser_diagnostics"))
        if (
            str(acquisition.get("method") or "").strip().lower() == "browser"
            and str(browser_diagnostics.get("browser_reason") or "").strip().lower()
            in {"http-escalation", "vendor-block", "traversal-required", "host-preference"}
        ):
            browser_required = True
        field_discovery = mapping_or_empty(source_trace.get("field_discovery"))
        for field_name, payload in field_discovery.items():
            payload_map = payload if isinstance(payload, dict) else {}
            selector_trace = mapping_or_empty(payload_map.get("selector_trace"))
            selector_kind = str(selector_trace.get("selector_kind") or "").strip()
            selector_value = str(selector_trace.get("selector_value") or "").strip()
            if not selector_kind or not selector_value:
                continue
            candidate_key = f"{field_name}|{selector_kind}|{selector_value}"
            saved_selector = saved_selector_index.get(
                _selector_signature(
                    field_name=field_name,
                    selector_kind=selector_kind,
                    selector_value=selector_value,
                )
            )
            entry = selector_candidates.setdefault(
                candidate_key,
                {
                    "candidate_key": candidate_key,
                    "field_name": str(field_name or "").strip().lower(),
                    "selector_kind": selector_kind,
                    "selector_value": selector_value,
                    "selector_source": str(selector_trace.get("selector_source") or ""),
                    "sample_value": selector_trace.get("sample_value") or payload_map.get("value"),
                    "source_record_ids": [],
                    "source_run_id": selector_trace.get("source_run_id") or run.id,
                    "saved_selector_id": saved_selector.get("id") if isinstance(saved_selector, dict) else None,
                    "already_saved": isinstance(saved_selector, dict),
                    "final_field_source": (
                        list(payload_map.get("sources"))[-1]
                        if isinstance(payload_map.get("sources"), list) and payload_map.get("sources")
                        else None
                    ),
                },
            )
            entry["source_record_ids"] = sorted(
                {int(value) for value in [*list(entry.get("source_record_ids") or []), record.id]}
            )
    saved_profile_record = await load_domain_run_profile(
        session,
        domain=domain,
        surface=run.surface,
    )
    return {
        "run_id": run.id,
        "domain": domain,
        "surface": run.surface,
        "requested_field_coverage": {
            "requested": requested_fields,
            "found": [field for field in requested_fields if field in found_fields],
            "missing": [field for field in requested_fields if field not in found_fields],
        },
        "selector_candidates": sorted(
            selector_candidates.values(),
            key=lambda row: (
                str(row.get("field_name") or ""),
                str(row.get("selector_kind") or ""),
                str(row.get("selector_value") or ""),
            ),
        ),
        "affordance_candidates": {
            "accordions": [],
            "tabs": [],
            "carousels": [],
            "shadow_hosts": [],
            "iframe_promotion": None,
            "browser_required": browser_required,
        },
        "saved_selectors": saved_selectors,
        "saved_run_profile": (
            dict(saved_profile_record.profile or {})
            if saved_profile_record is not None
            else None
        ),
    }


async def promote_domain_recipe_selectors(
    session: AsyncSession,
    *,
    run: CrawlRun,
    selectors: list[dict[str, object]],
) -> list[dict[str, object]]:
    domain = normalize_domain(run.url)
    existing = await list_selector_records(
        session,
        domain=domain,
        surface=run.surface,
    )
    by_signature = {
        (
            str(row.get("field_name") or "").strip().lower(),
            str(row.get("css_selector") or row.get("xpath") or row.get("regex") or "").strip(),
        ): row
        for row in existing
    }
    saved_rows: list[dict[str, object]] = []
    for row in selectors:
        selector_kind = str(row.get("selector_kind") or "").strip()
        selector_value = str(row.get("selector_value") or "").strip()
        field_name = normalize_field_key(row.get("field_name"))
        if not field_name or not selector_kind or not selector_value:
            continue
        payload = {
            "field_name": field_name,
            "css_selector": selector_value if selector_kind == "css_selector" else None,
            "xpath": selector_value if selector_kind == "xpath" else None,
            "regex": selector_value if selector_kind == "regex" else None,
            "sample_value": row.get("sample_value"),
            "source": "domain_recipe",
            "source_run_id": run.id,
            "status": "validated",
            "is_active": True,
        }
        signature = (field_name, selector_value)
        existing_row = by_signature.get(signature)
        if isinstance(existing_row, dict):
            saved_rows.append(
                await update_selector_record(
                    session,
                    selector_id=int(existing_row["id"]),
                    payload=payload,
                )
            )
            continue
        saved_rows.append(
            await create_selector_record(
                session,
                domain=domain,
                surface=run.surface,
                payload=payload,
            )
        )
    return [row for row in saved_rows if isinstance(row, dict)]


async def save_domain_recipe_run_profile(
    session: AsyncSession,
    *,
    run: CrawlRun,
    profile: dict[str, object],
) -> dict[str, object]:
    return await save_domain_run_profile(
        session,
        domain=normalize_domain(run.url),
        surface=run.surface,
        profile=profile,
        source_run_id=run.id,
    )
