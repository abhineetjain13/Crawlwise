# Review and promotion service.
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.models.crawl import (
    CrawlRecord,
    CrawlRun,
    DomainCookieMemory,
    DomainFieldFeedback,
    ReviewPromotion,
)
from app.services.config.extraction_rules import EXTRACTION_RULES, REVIEW_CONTAINER_KEYS
from app.services.db_utils import mapping_or_empty
from app.services.domain_run_profile_service import (
    load_domain_run_profile,
    save_domain_run_profile,
)
from app.services.domain_utils import normalize_domain
from app.services.field_policy import normalize_field_key, normalize_review_target
from app.services.field_value_core import object_list as _object_list, safe_int as _safe_int
from app.services.normalizers import normalize_value
from app.services.publish import refresh_record_commit_metadata
from app.services.schema_service import load_resolved_schema
from app.services.selectors_runtime import (
    create_selector_record,
    list_selector_records,
    update_selector_record,
)
from sqlalchemy import desc
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
        | {
            str(field_name)
            for record in records
            for field_name, payload in mapping_or_empty(
                mapping_or_empty(record.source_trace).get("field_discovery")
            ).items()
            if isinstance(payload, dict) and payload.get("status") == "found"
        }
    )
    requested_fields = [str(value) for value in list(run.requested_fields or []) if str(value or "").strip()]
    if not found_fields and requested_fields:
        dom_patterns = mapping_or_empty(EXTRACTION_RULES.get("dom_patterns"))
        found_fields = sorted(
            field_name
            for field_name in requested_fields
            if str(dom_patterns.get(field_name) or "").strip()
        )
    selector_candidates: dict[str, dict[str, object]] = {}
    field_learning: dict[tuple[str, str, str], dict[str, object]] = {}
    browser_required = False
    actual_fetch_method: str | None = None
    browser_reason: str | None = None
    affordance_candidates: dict[str, object] = {
        "accordions": [],
        "tabs": [],
        "carousels": [],
        "shadow_hosts": [],
        "iframe_promotion": None,
        "browser_required": False,
    }
    feedback_index = await _latest_field_feedback_index(
        session,
        domain=domain,
        surface=run.surface,
    )
    for record in records:
        source_trace = mapping_or_empty(record.source_trace)
        acquisition = mapping_or_empty(source_trace.get("acquisition"))
        browser_diagnostics = mapping_or_empty(acquisition.get("browser_diagnostics"))
        if actual_fetch_method is None:
            method = str(acquisition.get("method") or "").strip()
            if method:
                actual_fetch_method = method
        if browser_reason is None:
            next_browser_reason = str(browser_diagnostics.get("browser_reason") or "").strip().lower()
            if next_browser_reason:
                browser_reason = next_browser_reason
        if (
            str(acquisition.get("method") or "").strip().lower() == "browser"
            and str(browser_diagnostics.get("browser_reason") or "").strip().lower()
            in {"http-escalation", "vendor-block", "traversal-required", "host-preference"}
        ):
            browser_required = True
        _merge_affordance_candidates(
            affordance_candidates,
            acquisition=acquisition,
            browser_diagnostics=browser_diagnostics,
        )
        field_discovery = mapping_or_empty(source_trace.get("field_discovery"))
        for field_name, payload in field_discovery.items():
            payload_map = payload if isinstance(payload, dict) else {}
            selector_trace = mapping_or_empty(payload_map.get("selector_trace"))
            selector_kind = str(selector_trace.get("selector_kind") or "").strip()
            selector_value = str(selector_trace.get("selector_value") or "").strip()
            source_labels = [
                str(value)
                for value in list(payload_map.get("sources") or [])
                if str(value or "").strip()
            ]
            if (
                payload_map.get("status") == "found"
                and payload_map.get("value") not in (None, "", [], {})
                and selector_kind == "xpath"
                and selector_value
            ):
                learning_key = (
                    str(field_name or "").strip().lower(),
                    selector_kind,
                    selector_value or (source_labels[-1] if source_labels else ""),
                )
                feedback_row = feedback_index.get(learning_key)
                learning_entry = field_learning.setdefault(
                    learning_key,
                    {
                        "field_name": str(field_name or "").strip().lower(),
                        "value": payload_map.get("value"),
                        "source_labels": source_labels,
                        "selector_kind": selector_kind or None,
                        "selector_value": selector_value or None,
                        "source_record_ids": [],
                        "feedback": (
                            _serialize_feedback_row(feedback_row)
                            if feedback_row is not None
                            else None
                        ),
                    },
                )
                learning_entry["source_record_ids"] = sorted(
                    {
                        parsed
                        for value in [
                            *_object_list(learning_entry.get("source_record_ids")),
                            record.id,
                        ]
                        if (parsed := _safe_int(value)) is not None
                    }
                )
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
                        _object_list(payload_map.get("sources"))[-1]
                        if _object_list(payload_map.get("sources"))
                        else None
                    ),
                },
            )
            entry["source_record_ids"] = sorted(
                {
                    parsed
                    for value in [*_object_list(entry.get("source_record_ids")), record.id]
                    if (parsed := _safe_int(value)) is not None
                }
            )
    acquisition_summary = mapping_or_empty(
        mapping_or_empty(run.result_summary).get("acquisition_summary")
    )
    if actual_fetch_method is None and mapping_or_empty(
        acquisition_summary.get("methods")
    ).get("browser"):
        actual_fetch_method = "browser"
    if browser_reason is None and actual_fetch_method == "browser":
        browser_reason = "http-escalation"
    if not selector_candidates:
        fallback_rows = [*saved_selectors, *run.settings_view.extraction_contract()]
        for row in fallback_rows:
            field_name = str(row.get("field_name") or "").strip().lower()
            selector_value = str(row.get("css_selector") or "").strip()
            if not field_name or not selector_value:
                continue
            candidate_key = f"{field_name}|css_selector|{selector_value}"
            saved_selector = saved_selector_index.get(
                _selector_signature(
                    field_name=field_name,
                    selector_kind="css_selector",
                    selector_value=selector_value,
                )
            )
            selector_candidates[candidate_key] = {
                "candidate_key": candidate_key,
                "field_name": field_name,
                "selector_kind": "css_selector",
                "selector_value": selector_value,
                "selector_source": str(row.get("source") or "run_contract"),
                "sample_value": row.get("sample_value"),
                "source_record_ids": [],
                "source_run_id": row.get("source_run_id") or run.id,
                "saved_selector_id": saved_selector.get("id") if isinstance(saved_selector, dict) else None,
                "already_saved": isinstance(saved_selector, dict),
                "final_field_source": None,
            }
    saved_profile_record = await load_domain_run_profile(
        session,
        domain=domain,
        surface=run.surface,
    )
    cookie_memory_exists = await _domain_cookie_memory_exists(session, domain=domain)
    browser_required = browser_required or actual_fetch_method == "browser"
    affordance_candidates["browser_required"] = browser_required
    return {
        "run_id": run.id,
        "domain": domain,
        "surface": run.surface,
        "requested_field_coverage": {
            "requested": requested_fields,
            "found": [field for field in requested_fields if field in found_fields],
            "missing": [field for field in requested_fields if field not in found_fields],
        },
        "acquisition_evidence": {
            "actual_fetch_method": actual_fetch_method,
            "browser_used": actual_fetch_method == "browser",
            "browser_reason": browser_reason,
            "acquisition_summary": mapping_or_empty(run.result_summary).get("acquisition_summary") or {},
            "cookie_memory_available": cookie_memory_exists,
        },
        "field_learning": sorted(
            field_learning.values(),
            key=lambda row: (
                str(row.get("field_name") or ""),
                str(row.get("selector_kind") or ""),
                str(row.get("selector_value") or ""),
            ),
        ),
        "selector_candidates": sorted(
            selector_candidates.values(),
            key=lambda row: (
                str(row.get("field_name") or ""),
                str(row.get("selector_kind") or ""),
                str(row.get("selector_value") or ""),
            ),
        ),
        "affordance_candidates": affordance_candidates,
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
    commit: bool = True,
) -> list[dict[str, object]]:
    domain = normalize_domain(run.url)
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

    existing = await list_selector_records(
        session,
        domain=domain,
        surface=run.surface,
    )
    by_signature = {
        _saved_selector_signature(row): row
        for row in existing
    }
    saved_rows: list[dict[str, object]] = []
    for row in selectors:
        selector_kind = str(row.get("selector_kind") or "").strip()
        selector_value = str(row.get("selector_value") or "").strip()
        field_name = normalize_field_key(str(row.get("field_name") or ""))
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
        signature = _selector_signature(
            field_name=field_name,
            selector_kind=selector_kind,
            selector_value=selector_value,
        )
        existing_row = by_signature.get(signature)
        if (
            isinstance(existing_row, dict)
            and "id" in existing_row
            and existing_row["id"] is not None
        ):
            selector_id = _safe_int(existing_row.get("id"))
            if selector_id is None:
                continue
            updated_row = await update_selector_record(
                session,
                selector_id=selector_id,
                payload=payload,
                commit=commit,
            )
            if updated_row is not None:
                saved_rows.append(updated_row)
            continue
        created_row = await create_selector_record(
                session,
                domain=domain,
                surface=run.surface,
                payload=payload,
                commit=commit,
            )
        if created_row is not None:
            saved_rows.append(created_row)
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
        commit=True,
    )


async def apply_domain_recipe_field_action(
    session: AsyncSession,
    *,
    run: CrawlRun,
    action: dict[str, object],
) -> dict[str, object]:
    domain = normalize_domain(run.url)
    field_name = normalize_field_key(str(action.get("field_name") or ""))
    action_name = str(action.get("action") or "").strip().lower()
    selector_kind = str(action.get("selector_kind") or "").strip().lower()
    selector_value = str(action.get("selector_value") or "").strip()
    if not field_name or action_name not in {"keep", "reject"}:
        raise ValueError("Invalid domain recipe field action.")

    source_kind = "selector" if selector_kind and selector_value else "field_source"
    source_value = selector_value or None
    try:
        if action_name == "keep" and selector_kind and selector_value:
            await promote_domain_recipe_selectors(
                session,
                run=run,
                selectors=[
                    {
                        "field_name": field_name,
                        "selector_kind": selector_kind,
                        "selector_value": selector_value,
                    }
                ],
                commit=False,
            )
        if action_name == "reject" and selector_kind and selector_value:
            existing = await list_selector_records(
                session,
                domain=domain,
                surface=run.surface,
            )
            for row in existing:
                matched_value = (
                    row.get("css_selector")
                    if selector_kind == "css_selector"
                    else row.get("xpath")
                    if selector_kind == "xpath"
                    else row.get("regex")
                )
                if (
                    normalize_field_key(str(row.get("field_name") or "")) == field_name
                    and str(matched_value or "").strip() == selector_value
                    and row.get("id") is not None
                ):
                    selector_id = _safe_int(row.get("id"))
                    if selector_id is None:
                        continue
                    await update_selector_record(
                        session,
                        selector_id=selector_id,
                        payload={"is_active": False},
                        commit=False,
                    )
                    break

        feedback = DomainFieldFeedback(
            domain=domain,
            surface=run.surface,
            field_name=field_name,
            action=action_name,
            source_kind=source_kind,
            source_value=source_value,
            source_run_id=run.id,
            payload={
                "selector_kind": selector_kind or None,
                "selector_value": selector_value or None,
                "source_record_ids": [
                    parsed
                    for parsed in (
                        _safe_int(value)
                        for value in _object_list(action.get("source_record_ids"))
                    )
                    if parsed is not None
                ],
            },
        )
        session.add(feedback)
        await session.commit()
        await session.refresh(feedback)
        return _serialize_feedback_row(feedback)
    except Exception:
        await session.rollback()
        raise


async def list_domain_field_feedback(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
    limit: int = 50,
) -> list[dict[str, object]]:
    statement = select(DomainFieldFeedback).order_by(
        desc(DomainFieldFeedback.created_at),
        desc(DomainFieldFeedback.id),
    )
    if domain:
        statement = statement.where(DomainFieldFeedback.domain == domain)
    if surface:
        statement = statement.where(DomainFieldFeedback.surface == surface)
    rows = list((await session.execute(statement.limit(max(1, limit)))).scalars().all())
    return [_serialize_feedback_record(row) for row in rows]


async def _domain_cookie_memory_exists(
    session: AsyncSession,
    *,
    domain: str,
) -> bool:
    result = await session.execute(
        select(DomainCookieMemory.id)
        .where(DomainCookieMemory.domain == domain)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _latest_field_feedback_index(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> dict[tuple[str, str, str], DomainFieldFeedback]:
    rows = list(
        (
            await session.execute(
                select(DomainFieldFeedback)
                .where(
                    DomainFieldFeedback.domain == domain,
                    DomainFieldFeedback.surface == surface,
                )
                .order_by(desc(DomainFieldFeedback.created_at), desc(DomainFieldFeedback.id))
            )
        ).scalars().all()
    )
    index: dict[tuple[str, str, str], DomainFieldFeedback] = {}
    for row in rows:
        key = (
            str(row.field_name or "").strip().lower(),
            str((row.payload or {}).get("selector_kind") or "").strip(),
            str(row.source_value or "").strip(),
        )
        index.setdefault(key, row)
    return index


def _serialize_feedback_row(row: DomainFieldFeedback) -> dict[str, object]:
    return {
        "action": row.action,
        "source_kind": row.source_kind,
        "source_value": row.source_value,
        "source_run_id": row.source_run_id,
        "created_at": row.created_at,
    }


def _serialize_feedback_record(row: DomainFieldFeedback) -> dict[str, object]:
    payload = row.payload or {}
    return {
        "id": row.id,
        "domain": row.domain,
        "surface": row.surface,
        "field_name": row.field_name,
        "action": row.action,
        "source_kind": row.source_kind,
        "source_value": row.source_value,
        "source_run_id": row.source_run_id,
        "selector_kind": payload.get("selector_kind"),
        "selector_value": payload.get("selector_value"),
        "source_record_ids": [
            parsed
            for parsed in (
                _safe_int(value)
                for value in list(payload.get("source_record_ids") or [])
            )
            if parsed is not None
        ],
        "created_at": row.created_at,
    }


def _merge_affordance_candidates(
    affordance_candidates: dict[str, object],
    *,
    acquisition: dict[str, object],
    browser_diagnostics: dict[str, object],
) -> None:
    accordion_labels = _object_list(affordance_candidates.get("accordions"))
    tab_labels = _object_list(affordance_candidates.get("tabs"))
    if not affordance_candidates.get("iframe_promotion"):
        final_url = str(acquisition.get("final_url") or "").strip()
        if final_url and final_url != str(acquisition.get("requested_url") or "").strip():
            affordance_candidates["iframe_promotion"] = final_url
    detail_expansion = mapping_or_empty(browser_diagnostics.get("detail_expansion"))
    for label in _string_values(detail_expansion.get("expanded_elements")):
        if label not in accordion_labels:
            accordion_labels.append(label)
    for label in _string_values(mapping_or_empty(detail_expansion.get("aom")).get("expanded_elements")):
        if label not in tab_labels:
            tab_labels.append(label)
    affordance_candidates["accordions"] = accordion_labels
    affordance_candidates["tabs"] = tab_labels


def _string_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]
