from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.config.variant_migration_rules import VARIANT_GROUP_MIN_CONFIDENCE
from app.services.config.variant_policy import PUBLIC_VARIANT_AXIS_FIELDS
from app.services.extract.variant_dom_cues import variant_context_noise_tokens
from app.services.extract.variant_value_guards import variant_url_is_product_like
from app.services.field_value_core import clean_text

logger = logging.getLogger(__name__)
_PUBLIC_AXES = frozenset(str(axis).strip().lower() for axis in PUBLIC_VARIANT_AXIS_FIELDS if str(axis).strip())


@dataclass
class VariantCandidateGroup:
    name: str
    axis_key: str
    values: list[str]
    entries: list[dict[str, object]]
    container_tag: str
    container_classes: list[str]
    container_id: str | None
    container_role: str | None
    ancestor_class_tokens: list[str]
    extractor_path: str
    scope_source: str
    option_node_types: list[str]
    confidence: float = 0.0
    rejection_reasons: list[str] = field(default_factory=list)

    def as_option_group(self) -> dict[str, object]:
        return {"name": self.name, "values": self.values, "entries": self.entries}


class VariantGroupValidator:
    def validate(self, group: VariantCandidateGroup, *, page_url: str) -> bool:
        score = 0.0
        reasons: list[str] = []
        if group.axis_key in _PUBLIC_AXES:
            score += 0.3
        elif _name_has_compound_public_axis(group.name):
            score += 0.15
        if group.container_tag == "fieldset":
            score += 0.25
        if set(group.option_node_types) & {
            "input_radio",
            "input_checkbox",
            "role_radio",
            "role_option",
            "option",
            "data_selected",
        }:
            score += 0.2
        if 2 <= len(group.values) <= 8:
            score += 0.1
        if _container_has_variant_semantics(group):
            score += 0.15
        if any(entry.get("variant_id") for entry in group.entries):
            score += 0.2
        urls = {str(entry.get("url")) for entry in group.entries if entry.get("url")}
        if len(urls) >= 2 and all(variant_url_is_product_like(url) for url in urls):
            score += 0.15
        if group.scope_source == "trusted_scope":
            score += 0.1
        if group.extractor_path in {"select", "choice_radio"}:
            score += 0.05
        combined = " ".join([*group.container_classes, *group.ancestor_class_tokens]).lower()
        if any(token in combined for token in variant_context_noise_tokens):
            score -= 0.5
            reasons.append("noise_context")
        if len(urls) == 1 and not variant_url_is_product_like(next(iter(urls))):
            score -= 0.4
            reasons.append("all_urls_identical_non_product")
        if group.container_tag in {"nav", "header", "footer", "aside"}:
            score -= 0.4
            reasons.append(f"chrome_container:{group.container_tag}")
        product_url_set = len(urls) >= 2 and all(variant_url_is_product_like(url) for url in urls)
        if set(group.option_node_types) == {"a"} and not product_url_set:
            score -= 0.3
            reasons.append("all_options_are_anchors")
        if group.scope_source == "soft_scope":
            score -= 0.1
        elif group.scope_source == "full_page":
            score -= 0.3
            reasons.append("full_page_scope")
        group.confidence = max(0.0, min(1.0, score))
        group.rejection_reasons = reasons
        accepted = group.confidence >= float(VARIANT_GROUP_MIN_CONFIDENCE)
        logger.debug(
            "variant_group_decision",
            extra={
                "url": page_url,
                "axis": group.axis_key,
                "confidence": group.confidence,
                "accepted": accepted,
                "rejection_reasons": reasons,
                "extractor_path": group.extractor_path,
                "scope_source": group.scope_source,
            },
        )
        return accepted


def _container_has_variant_semantics(group: VariantCandidateGroup) -> bool:
    probe = " ".join(
        [
            *group.container_classes,
            group.container_id or "",
            group.container_role or "",
            *group.ancestor_class_tokens[:3],
        ]
    ).lower()
    return any(token in probe for token in ("variant", "option", "selector", "swatch", "radiogroup"))


def _name_has_compound_public_axis(value: object) -> bool:
    tokens = {token for token in clean_text(value).lower().replace("&", " ").split() if token}
    return bool(tokens & _PUBLIC_AXES) and len(tokens) >= 2
