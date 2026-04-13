"""Centralized field arbitration engine for detail extraction."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any

from app.services.extract.candidate_processing import (
    candidate_source_rank,
    finalize_candidate_row,
    sanitize_field_value,
    sanitize_field_value_with_reason,
)

logger = logging.getLogger(__name__)
_LOW_QUALITY_MERGE_TOKENS = frozenset(
    {"cookie", "privacy", "sign in", "log in", "account", "home", "menu", "agree", "policy"}
)
_LONG_FORM_MERGE_FIELDS = frozenset(
    {
        "description",
        "specifications",
        "responsibilities",
        "requirements",
        "company",
        "location",
        "salary",
        "department",
    }
)
_SHORT_FORM_MERGE_FIELDS = frozenset(
    {"brand", "category", "color", "size", "availability"}
)


@dataclass
class FieldDecision:
    """Result of arbitration for a single field."""

    field_name: str
    value: Any = None
    source: str | None = None
    rank: int = 0
    rejection_reason: str | None = None
    rejected_rows: list[dict[str, Any]] = field(default_factory=list)
    accepted_rows: list[dict[str, Any]] = field(default_factory=list)
    accepted: bool = False
    winning_row: dict[str, Any] | None = None


@dataclass
class MergeDecision:
    """Result of deciding whether a candidate should replace an existing value."""

    field_name: str
    value: Any = None
    accepted: bool = False
    used_candidate: bool = False
    source: str | None = None
    rejection_reason: str | None = None
    existing_value: Any = None
    candidate_value: Any = None


class FieldDecisionEngine:
    """Single authority for detail field arbitration and merge preference."""

    def __init__(self, *, base_url: str = "") -> None:
        self._base_url = base_url

    def decide_from_rows(
        self,
        field_name: str,
        rows: list[dict],
    ) -> FieldDecision:
        """Pick the best candidate value for *field_name* from *rows*."""
        decision = FieldDecision(field_name=field_name)

        accepted_rows: list[dict] = []
        for row in rows:
            original_value = row.get("value")
            normalised_value, rejection_reason = finalize_candidate_row(
                field_name,
                row,
                base_url=self._base_url,
            )
            if normalised_value in (None, "", [], {}):
                decision.rejected_rows.append(
                    {
                        "value": original_value,
                        "reason": rejection_reason or "rejected",
                        "source": row.get("source"),
                    }
                )
                continue
            accepted_rows.append({**row, "value": normalised_value})

        if not accepted_rows:
            if decision.rejected_rows:
                decision.rejection_reason = "all_candidates_rejected"
                logger.debug(
                    "field_decision: %s - all %d candidates rejected",
                    field_name,
                    len(decision.rejected_rows),
                )
            return decision

        decision.accepted_rows = accepted_rows
        best_row = accepted_rows[0]
        best_rank = candidate_source_rank(field_name, best_row.get("source"))
        for candidate_row in accepted_rows[1:]:
            candidate_rank = candidate_source_rank(
                field_name,
                candidate_row.get("source"),
            )
            if candidate_rank > best_rank:
                best_row = candidate_row
                best_rank = candidate_rank
        if field_name in {"title", "description", "responsibilities", "requirements", "company", "location", "salary"}:
            for candidate_row in accepted_rows:
                if (
                    candidate_source_rank(field_name, candidate_row.get("source")) == best_rank
                    and str(candidate_row.get("source") or "").strip()
                    == str(best_row.get("source") or "").strip()
                    and len(str(candidate_row["value"]).strip()) > len(str(best_row["value"]).strip())
                ):
                    best_row = candidate_row

        decision.value = best_row["value"]
        decision.source = best_row.get("source")
        decision.rank = best_rank
        decision.accepted = True
        decision.winning_row = best_row

        logger.debug(
            "field_decision: %s - winner source=%s rank=%d (of %d accepted, %d rejected)",
            field_name,
            decision.source,
            decision.rank,
            len(accepted_rows),
            len(decision.rejected_rows),
        )
        return decision

    def decide_merge(
        self,
        field_name: str,
        existing: object,
        candidate: object,
        *,
        candidate_source: str = "detail_candidates",
    ) -> MergeDecision:
        """Return the merge decision for adapter primary vs candidate secondary."""
        decision = MergeDecision(
            field_name=field_name,
            value=existing,
            source="existing" if existing not in (None, "", [], {}) else None,
            existing_value=existing,
            candidate_value=candidate,
        )
        if candidate in (None, "", [], {}):
            decision.rejection_reason = "empty_candidate"
            return decision

        sanitised, rejection_reason = sanitize_field_value_with_reason(
            field_name, candidate
        )
        if sanitised in (None, "", [], {}):
            logger.debug(
                "field_decision merge: %s - candidate rejected (%s), keeping existing",
                field_name,
                rejection_reason,
            )
            decision.rejection_reason = rejection_reason or "candidate_rejected"
            return decision

        decision.accepted = True
        decision.candidate_value = sanitised
        should_prefer, preference_reason = self._should_prefer_candidate(
            field_name,
            existing,
            sanitised,
        )
        if should_prefer:
            decision.value = sanitised
            decision.used_candidate = True
            decision.source = candidate_source
            return decision

        decision.rejection_reason = preference_reason
        return decision

    def merge_record_fields(
        self,
        primary: dict,
        secondary: dict,
        *,
        return_reconciliation: bool = False,
    ) -> dict | tuple[dict, dict[str, dict[str, object]]]:
        """Merge two records using field arbitration decisions from this engine."""
        merged = dict(primary)
        reconciliation: dict[str, dict[str, object]] = {}
        for key, value in secondary.items():
            if key.startswith("_"):
                continue
            decision = self.decide_merge(
                key,
                merged.get(key),
                value,
            )
            merged[key] = decision.value
            if not return_reconciliation:
                continue
            if decision.used_candidate:
                continue
            if decision.candidate_value in (None, "", [], {}) and value in (
                None,
                "",
                [],
                {},
            ):
                continue
            reconciliation[key] = {
                "status": "kept_existing",
                "existing_value": decision.existing_value,
                "candidate_value": (
                    decision.candidate_value
                    if decision.candidate_value not in (None, "", [], {})
                    else value
                ),
                "reason": decision.rejection_reason,
            }
        if return_reconciliation:
            return merged, reconciliation
        return merged

    def _should_prefer_candidate(
        self,
        field_name: str,
        existing: object,
        candidate: object,
    ) -> tuple[bool, str | None]:
        if candidate in (None, "", [], {}):
            return False, "empty_candidate"
        if existing in (None, "", [], {}):
            return True, None

        existing_text = _clean_merge_candidate_text(existing).casefold()
        candidate_text = _clean_merge_candidate_text(candidate).casefold()
        if not candidate_text:
            return False, "empty_candidate"

        if field_name in _LONG_FORM_MERGE_FIELDS:
            return (True, None) if len(candidate_text) > len(existing_text) else (False, "existing_preferred")

        if field_name in _SHORT_FORM_MERGE_FIELDS:
            if len(candidate_text) > 40 or len(candidate_text.split()) > 5:
                return False, "candidate_too_long"
            existing_is_noisy = any(
                token in existing_text for token in _LOW_QUALITY_MERGE_TOKENS
            )
            candidate_is_noisy = any(
                token in candidate_text for token in _LOW_QUALITY_MERGE_TOKENS
            )
            if existing_is_noisy and not candidate_is_noisy:
                return True, None
            if not existing_is_noisy and candidate_is_noisy:
                return False, "candidate_noisy"
            return (True, None) if len(candidate_text) > len(existing_text) else (False, "existing_preferred")

        if field_name == "additional_images":
            return (
                (True, None)
                if _image_candidate_count(candidate) > _image_candidate_count(existing)
                else (False, "existing_preferred")
            )

        return False, "existing_preferred"


def _clean_merge_candidate_text(value: object) -> str:
    text = unescape(str(value or "")).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _image_candidate_count(value: object) -> int:
    sanitized = sanitize_field_value("additional_images", value)
    if sanitized in (None, "", [], {}):
        return 0
    if isinstance(sanitized, (list, tuple)):
        return len([part for part in sanitized if str(part).strip()])
    return len([part for part in str(sanitized).split(",") if part.strip()])
