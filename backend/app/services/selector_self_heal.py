from __future__ import annotations

from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRun
from app.services.crawl_engine import extract_records
from app.services.domain_memory_service import (
    load_domain_memory,
    save_domain_memory,
    selector_payload_from_rules,
    selector_rules_from_memory,
)
from app.services.domain_utils import normalize_domain
from app.services.field_policy import field_allowed_for_surface
from app.services.llm_runtime import discover_xpath_candidates
from app.services.xpath_service import extract_selector_value


def reduce_html_for_selector_synthesis(html: str) -> str:
    soup = BeautifulSoup(str(html or ""), "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    for tag in soup.find_all(True):
        allowed_attrs = {
            key: value
            for key, value in tag.attrs.items()
            if key
            in {"class", "id", "data-testid", "itemprop", "name", "aria-label", "href"}
        }
        tag.attrs = allowed_attrs
    text = str(soup)
    return text[:200_000]


def selector_self_heal_enabled(run: CrawlRun) -> tuple[bool, float]:
    snapshot = run.settings_view.extraction_runtime_snapshot()
    selector_self_heal = (
        snapshot.get("selector_self_heal") if isinstance(snapshot, dict) else None
    )
    enabled = bool(
        selector_self_heal.get("enabled")
        if isinstance(selector_self_heal, dict)
        else False
    )
    threshold = _safe_float(
        (
            selector_self_heal.get("min_confidence")
            if isinstance(selector_self_heal, dict)
            else None
        ),
        default=0.55,
    )
    return enabled, threshold


def selector_self_heal_targets(
    *,
    run: CrawlRun,
    record: dict[str, object],
) -> list[str]:
    confidence = _mapping_or_empty(record.get("_confidence"))
    requested_fields = [
        str(field_name or "").strip().lower()
        for field_name in list(run.requested_fields or [])
        if str(field_name or "").strip()
    ]
    targets: list[str] = []
    for field_name in requested_fields:
        if (
            field_allowed_for_surface(run.surface, field_name)
            and record.get(field_name) in (None, "", [], {})
            and field_name not in targets
        ):
            targets.append(field_name)
    if targets:
        return targets[:6]
    for field_name in _list_or_empty(confidence.get("missing_fields")):
        normalized = str(field_name or "").strip().lower()
        if (
            normalized
            and field_allowed_for_surface(run.surface, normalized)
            and normalized not in targets
        ):
            targets.append(normalized)
    return targets[:6]


async def apply_selector_self_heal(
    session: AsyncSession,
    *,
    run: CrawlRun,
    page_url: str,
    html: str,
    records: list[dict[str, object]],
    adapter_records: list[dict[str, object]] | None,
    network_payloads: list[dict[str, object]] | None,
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    enabled, threshold = selector_self_heal_enabled(run)
    if not enabled or not run.settings_view.llm_enabled() or "detail" not in run.surface:
        return records, selector_rules

    domain = normalize_domain(page_url)
    updated_records: list[dict[str, object]] = []
    current_rules = list(selector_rules or [])
    memory = await load_domain_memory(session, domain=domain, surface=run.surface)
    existing_rule_count = len(selector_rules_from_memory(memory))
    reduced_html = reduce_html_for_selector_synthesis(html)

    for record in records:
        next_record = dict(record)
        confidence = _mapping_or_empty(next_record.get("_confidence"))
        requested_missing_fields = [
            field_name
            for field_name in [
                str(value or "").strip().lower()
                for value in list(run.requested_fields or [])
                if str(value or "").strip()
            ]
            if next_record.get(field_name) in (None, "", [], {})
        ]
        if _safe_float(confidence.get("score"), default=1.0) >= threshold:
            updated_records.append(next_record)
            continue
        if existing_rule_count > 0 and not requested_missing_fields:
            updated_records.append(next_record)
            continue
        target_fields = selector_self_heal_targets(run=run, record=next_record)
        if not target_fields:
            updated_records.append(next_record)
            continue
        candidates, error_message = await discover_xpath_candidates(
            session,
            run_id=run.id,
            domain=domain,
            url=page_url,
            html_text=reduced_html,
            missing_fields=target_fields,
            existing_values={
                key: value
                for key, value in next_record.items()
                if not str(key).startswith("_")
            },
        )
        synthesized_rules = _validated_xpath_rules(
            html=html,
            candidates=candidates,
            target_fields=target_fields,
        )
        if not synthesized_rules:
            next_record["_self_heal"] = {
                "enabled": True,
                "triggered": True,
                "threshold": threshold,
                "mode": "selector_synthesis",
                "cache_hit": False,
                "error": error_message or "no_valid_selectors",
            }
            updated_records.append(next_record)
            continue
        current_rules = _merge_selector_rules(current_rules, synthesized_rules)
        await save_domain_memory(
            session,
            domain=domain,
            surface=run.surface,
            selectors=selector_payload_from_rules(current_rules),
        )
        rerun_records = extract_records(
            html,
            page_url,
            run.surface,
            max_records=1,
            requested_fields=list(run.requested_fields or []),
            adapter_records=adapter_records,
            network_payloads=network_payloads,
            selector_rules=current_rules,
            extraction_runtime_snapshot=run.settings_view.extraction_runtime_snapshot(),
        )
        rerun_record = dict(rerun_records[0]) if rerun_records else next_record
        rerun_record["_self_heal"] = {
            "enabled": True,
            "triggered": True,
            "threshold": threshold,
            "mode": "selector_synthesis",
            "cache_hit": existing_rule_count > 0,
            "synthesized_fields": [
                str(row.get("field_name") or "").strip().lower()
                for row in synthesized_rules
            ],
            "error": error_message or None,
        }
        updated_records.append(rerun_record)
        existing_rule_count += len(synthesized_rules)
    await session.flush()
    return updated_records, current_rules


def _validated_xpath_rules(
    *,
    html: str,
    candidates: object,
    target_fields: list[str],
) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    allowed_fields = {str(field_name or "").strip().lower() for field_name in target_fields}
    for row in _list_or_empty(candidates):
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("field_name") or "").strip().lower()
        xpath = str(row.get("xpath") or "").strip()
        if not field_name or field_name not in allowed_fields or not xpath:
            continue
        sample_value, count, selector_used = extract_selector_value(html, xpath=xpath)
        if count <= 0 or sample_value in (None, ""):
            continue
        rules.append(
            {
                "field_name": field_name,
                "css_selector": None,
                "xpath": selector_used or xpath,
                "regex": None,
                "sample_value": sample_value,
                "source": "selector_self_heal",
                "status": "validated",
                "is_active": True,
            }
        )
    return rules


def _merge_selector_rules(
    existing_rules: list[dict[str, object]],
    new_rules: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged = list(existing_rules or [])
    seen = {
        (
            str(row.get("field_name") or "").strip().lower(),
            str(row.get("css_selector") or "").strip(),
            str(row.get("xpath") or "").strip(),
            str(row.get("regex") or "").strip(),
        )
        for row in merged
        if isinstance(row, dict)
    }
    next_id = max(
        (
            parsed_id
            for row in merged
            if isinstance(row, dict)
            for parsed_id in [_safe_int(row.get("id"), default=None)]
            if parsed_id is not None
        ),
        default=0,
    ) + 1
    for row in new_rules:
        key = (
            str(row.get("field_name") or "").strip().lower(),
            str(row.get("css_selector") or "").strip(),
            str(row.get("xpath") or "").strip(),
            str(row.get("regex") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append({"id": next_id, **row})
        next_id += 1
    return merged


def _safe_float(value: object, *, default: float) -> float:
    try:
        if value is None:
            return default
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, *, default: int | None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _mapping_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _list_or_empty(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []
