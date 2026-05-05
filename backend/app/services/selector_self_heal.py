from __future__ import annotations

from copy import deepcopy

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl import CrawlRun
from app.services.config.selectors import (
    SELECTOR_SYNTHESIS_ALLOWED_ATTRS,
    SELECTOR_SELF_HEAL_DEFAULT_MIN_CONFIDENCE,
    SELECTOR_SELF_HEAL_TARGET_LIMIT,
    SELECTOR_SYNTHESIS_DROP_TAGS,
    SELECTOR_SYNTHESIS_KEEP_ATTRS,
    SELECTOR_SYNTHESIS_KEEP_TOKENS,
    SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS,
    SELECTOR_SYNTHESIS_LOW_VALUE_TAGS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.db_utils import mapping_or_empty
from app.services.extraction_runtime import extract_records_async
from app.services.domain_memory_service import (
    load_domain_memory,
    save_domain_memory,
    selector_payload_from_rules,
    selector_rules_from_memory,
)
from app.services.domain_utils import normalize_domain
from app.services.field_policy import (
    field_allowed_for_surface,
    repair_target_fields_for_surface,
)
from app.services.field_value_core import safe_int as _safe_int
from app.services.extraction_html_helpers import prune_html_tree
from app.services.llm_runtime import discover_xpath_candidates
from app.services.xpath_service import extract_selector_value, validate_or_convert_xpath


def reduce_html_for_selector_synthesis(html: str) -> str:
    soup = prune_html_tree(
        BeautifulSoup(str(html or ""), "html.parser"),
        drop_tags=tuple(SELECTOR_SYNTHESIS_DROP_TAGS),
        allowed_attrs=set(SELECTOR_SYNTHESIS_ALLOWED_ATTRS),
    )
    _remove_low_value_nodes(soup)
    reduced = BeautifulSoup("<html><body></body></html>", "html.parser")
    source_root = soup.body or soup
    target_root = reduced.body or reduced
    _append_reduced_children(
        reduced,
        target_root,
        list(source_root.children),
        crawler_runtime_settings.selector_synthesis_max_html_chars - len(str(reduced)),
    )
    return str(reduced)


def _append_reduced_children(
    output_soup: BeautifulSoup,
    target_parent: Tag | BeautifulSoup,
    children: list[object],
    budget: int,
) -> int:
    used = 0
    for child in children:
        remaining = budget - used
        if remaining <= 0:
            break
        used += _append_reduced_node(output_soup, target_parent, child, remaining)
    return used


def _append_reduced_node(
    output_soup: BeautifulSoup,
    target_parent: Tag | BeautifulSoup,
    node: object,
    budget: int,
) -> int:
    if budget <= 0:
        return 0
    if isinstance(node, NavigableString):
        text = str(node)
        if not text.strip():
            return 0
        chunk = text[:budget]
        target_parent.append(chunk)
        return len(chunk)
    if not isinstance(node, Tag):
        return 0
    # Defensive for direct callers that skip reduce_html_for_selector_synthesis().
    if node.name in SELECTOR_SYNTHESIS_LOW_VALUE_TAGS and not _keep_low_value_node(node):
        return 0
    if node.name == "template" and not node.has_attr("shadowrootmode"):
        return 0
    serialized = str(node)
    if len(serialized) <= budget:
        target_parent.append(deepcopy(node))
        return len(serialized)
    clone_attrs = {
        str(key): " ".join(str(item) for item in value)
        if isinstance(value, (list, tuple))
        else str(value or "")
        for key, value in dict(node.attrs).items()
    }
    clone = output_soup.new_tag(node.name, attrs=clone_attrs)
    empty_size = len(str(clone))
    if empty_size >= budget:
        return 0
    used = _append_reduced_children(
        output_soup,
        clone,
        list(node.children),
        budget - empty_size,
    )
    if used <= 0 and not clone.attrs:
        return 0
    target_parent.append(clone)
    return len(str(clone))


def _remove_low_value_nodes(soup: BeautifulSoup) -> None:
    for node in list(soup.find_all(True)):
        if node.name in SELECTOR_SYNTHESIS_LOW_VALUE_TAGS and not _keep_low_value_node(
            node
        ):
            node.decompose()


def _keep_low_value_node(node: Tag) -> bool:
    if node.name not in SELECTOR_SYNTHESIS_KEEP_WORTHY_TAGS:
        return False
    attrs = dict(node.attrs)
    if (
        not any(
            attrs.get(attr_name) not in (None, "", [], {})
            for attr_name in SELECTOR_SYNTHESIS_KEEP_ATTRS
        )
        and not str(attrs.get("aria-label") or "").strip()
    ):
        return False
    current: Tag | None = node
    while isinstance(current, Tag):
        probe = " ".join(
            str(part)
            for part in (
                current.name,
                current.get("id"),
                current.get("class"),
                current.get("data-testid"),
            )
            if part
        ).lower()
        if any(token in probe for token in SELECTOR_SYNTHESIS_KEEP_TOKENS):
            return True
        current = current.parent if isinstance(current.parent, Tag) else None
    return False


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
        default=float(SELECTOR_SELF_HEAL_DEFAULT_MIN_CONFIDENCE),
    )
    return enabled, threshold


def selector_self_heal_targets(
    *,
    run: CrawlRun,
    record: dict[str, object],
) -> list[str]:
    confidence = mapping_or_empty(record.get("_confidence"))
    target_limit = max(1, _safe_int(SELECTOR_SELF_HEAL_TARGET_LIMIT, default=6) or 6)
    requested_fields = repair_target_fields_for_surface(
        run.surface,
        run.requested_fields or [],
    )
    targets: list[str] = []
    for field_name in requested_fields:
        if (
            field_allowed_for_surface(run.surface, field_name)
            and record.get(field_name) in (None, "", [], {})
            and field_name not in targets
        ):
            targets.append(field_name)
    if targets:
        return targets[:target_limit]
    for missing_field in _list_or_empty(confidence.get("missing_fields")):
        normalized = str(missing_field or "").strip().lower()
        if (
            normalized
            and field_allowed_for_surface(run.surface, normalized)
            and normalized not in targets
        ):
            targets.append(normalized)
    return targets[:target_limit]


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
    if (
        not enabled
        or not run.settings_view.llm_enabled()
        or "detail" not in run.surface
    ):
        return records, selector_rules

    domain = normalize_domain(page_url)
    updated_records: list[dict[str, object]] = []
    current_rules = list(selector_rules or [])
    memory = await load_domain_memory(session, domain=domain, surface=run.surface)
    existing_rule_count = len(selector_rules_from_memory(memory))
    reduced_html = reduce_html_for_selector_synthesis(html)

    persisted_rules = False
    for record in records:
        next_record = dict(record)
        confidence = mapping_or_empty(next_record.get("_confidence"))
        confidence_score = _safe_float(confidence.get("score"), default=1.0)
        requested_missing_fields = [
            field_name
            for field_name in repair_target_fields_for_surface(
                run.surface,
                run.requested_fields or [],
            )
            if next_record.get(field_name) in (None, "", [], {})
        ]
        if existing_rule_count > 0 and not requested_missing_fields:
            updated_records.append(next_record)
            continue
        if confidence_score >= threshold and not requested_missing_fields:
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
        candidate_rules = _merge_selector_rules(current_rules, synthesized_rules)
        rerun_records = await extract_records_async(
            html,
            page_url,
            run.surface,
            max_records=1,
            requested_fields=repair_target_fields_for_surface(
                run.surface,
                run.requested_fields or [],
            ),
            adapter_records=adapter_records,
            network_payloads=network_payloads,
            selector_rules=candidate_rules,
            extraction_runtime_snapshot=run.settings_view.extraction_runtime_snapshot(),
        )
        rerun_record = dict(rerun_records[0]) if rerun_records else next_record
        improved = _selector_heal_improved_record(
            before_record=next_record,
            after_record=rerun_record,
            target_fields=target_fields,
        )
        if improved:
            current_rules = candidate_rules
            await save_domain_memory(
                session,
                domain=domain,
                surface=run.surface,
                selectors=selector_payload_from_rules(current_rules),
            )
            persisted_rules = True
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
            "persisted": improved,
            "error": error_message or (None if improved else "no_quality_improvement"),
        }
        updated_records.append(rerun_record)
        if improved:
            existing_rule_count += len(synthesized_rules)
    if persisted_rules:
        await session.flush()
    return updated_records, current_rules


def _validated_xpath_rules(
    *,
    html: str,
    candidates: object,
    target_fields: list[str],
) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    allowed_fields = {
        str(field_name or "").strip().lower() for field_name in target_fields
    }
    for row in _list_or_empty(candidates):
        if not isinstance(row, dict):
            continue
        field_name = str(row.get("field_name") or "").strip().lower()
        xpath = str(row.get("xpath") or "").strip()
        if not field_name or field_name not in allowed_fields or not xpath:
            continue
        validated_xpath, _ = validate_or_convert_xpath(xpath)
        if not validated_xpath:
            continue
        sample_value, count, selector_used = extract_selector_value(
            html,
            xpath=validated_xpath,
        )
        if count <= 0 or sample_value in (None, ""):
            continue
        rules.append(
            {
                "field_name": field_name,
                "css_selector": None,
                "xpath": selector_used or validated_xpath,
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
    next_id = (
        max(
            (
                parsed_id
                for row in merged
                if isinstance(row, dict)
                for parsed_id in [_safe_int(row.get("id"), default=None)]
                if parsed_id is not None
            ),
            default=0,
        )
        + 1
    )
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


def _selector_heal_improved_record(
    *,
    before_record: dict[str, object],
    after_record: dict[str, object],
    target_fields: list[str],
) -> bool:
    for field_name in target_fields:
        before_value = before_record.get(field_name)
        after_value = after_record.get(field_name)
        if before_value in (None, "", [], {}) and after_value not in (None, "", [], {}):
            return True
        if before_value != after_value and after_value not in (None, "", [], {}):
            return True
    return False


def _safe_float(value: object, *, default: float) -> float:
    try:
        if value is None:
            return default
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _list_or_empty(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []
