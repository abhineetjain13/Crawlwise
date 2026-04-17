"""Detail-level source-aware arbitration and reconciliation.

Extract owns this boundary: deciding which candidate wins per field, merging
adapter + candidate records through the arbitration engine, and post-processing
the reconciled detail values (coercion, image dedup). Pipeline orchestrates;
it does not own this logic.
"""
from __future__ import annotations

from urllib.parse import urlparse

from app.services.extract.candidate_processing import coerce_field_candidate_value
from app.services.extract.field_decision import FieldDecisionEngine


def _compact_dict(payload: dict) -> dict:
    return {
        key: value for key, value in payload.items() if value not in (None, "", [], {})
    }


def reconcile_detail_candidate_values(
    candidates: dict[str, list[dict]],
    *,
    allowed_fields: set[str],
    url: str,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    engine = FieldDecisionEngine(base_url=url)
    reconciled: dict[str, object] = {}
    reconciliation: dict[str, dict[str, object]] = {}

    for field_name in sorted(allowed_fields):
        rows = list(candidates.get(field_name) or [])
        if not rows:
            continue

        decision = engine.decide_from_rows(field_name, rows)
        if not decision.accepted:
            if decision.rejected_rows:
                reconciliation[field_name] = {
                    "status": "rejected",
                    "rejected": decision.rejected_rows[:6],
                }
            continue

        reconciled[field_name] = decision.value
        if decision.rejected_rows:
            reconciliation[field_name] = _compact_dict(
                {
                    "status": "accepted_with_rejections",
                    "accepted_source": decision.source,
                    "rejected": decision.rejected_rows[:6],
                }
            )

    return reconciled, reconciliation


def merge_detail_reconciliation(
    base: dict[str, dict[str, object]],
    merge: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    if not merge:
        return dict(base)
    combined = dict(base)
    for field_name, merge_entry in merge.items():
        existing_entry = combined.get(field_name)
        if not isinstance(existing_entry, dict):
            combined[field_name] = {"merge": merge_entry}
            continue
        combined[field_name] = {**existing_entry, "merge": merge_entry}
    return combined


def merge_record_fields(
    primary: dict,
    secondary: dict,
    *,
    return_reconciliation: bool = False,
) -> dict | tuple[dict, dict[str, dict[str, object]]]:
    """Merge two records through the extract arbitration engine."""
    engine = FieldDecisionEngine()
    merged = engine.merge_record_fields(
        primary,
        secondary,
        return_reconciliation=return_reconciliation,
    )
    if return_reconciliation:
        merged_record, reconciliation = merged
        return merged_record, {
            key: _compact_dict(value) for key, value in reconciliation.items()
        }
    return merged


def normalize_detail_candidate_values(
    candidate_values: dict[str, object], *, url: str
) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for field_name, value in candidate_values.items():
        coerced = coerce_field_candidate_value(field_name, value, base_url=url)
        if coerced in (None, "", [], {}):
            continue
        normalized[field_name] = coerced

    primary_image = str(normalized.get("image_url") or "").strip()
    additional_images = str(normalized.get("additional_images") or "").strip()
    if additional_images:
        image_parts = [part.strip() for part in additional_images.split(",") if part.strip()]
        primary_path = urlparse(primary_image).path if primary_image else ""
        seen_paths: set[str] = {primary_path} if primary_path else set()
        deduped_parts: list[str] = []
        for part in image_parts:
            part_path = urlparse(part).path
            if not part_path or part_path in seen_paths:
                continue
            seen_paths.add(part_path)
            deduped_parts.append(part)
        if deduped_parts:
            normalized["additional_images"] = ", ".join(deduped_parts)
        else:
            normalized.pop("additional_images", None)

    return normalized
