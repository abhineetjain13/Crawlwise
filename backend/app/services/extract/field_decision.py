"""Centralized field arbitration engine for detail extraction.

FieldDecisionEngine is the single authority for:
  - applying source policy (SOURCE_RANKING + per-field overrides)
  - running post-arbitration sanitization (sanitize_field_value gate)
  - logging the winning source and rejection reason per field
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.extract.service import (
    candidate_source_rank,
    finalize_candidate_row,
    sanitize_field_value_with_reason,
)
from app.services.pipeline.field_normalization import (
    _should_prefer_secondary_field,
)

logger = logging.getLogger(__name__)


@dataclass
class FieldDecision:
    """Result of arbitration for a single field."""

    field_name: str
    value: Any = None
    source: str | None = None
    rank: int = 0
    rejection_reason: str | None = None
    rejected_rows: list[dict[str, Any]] = field(default_factory=list)
    accepted: bool = False
    winning_row: dict[str, Any] | None = None


class FieldDecisionEngine:
    """Single authority for detail field arbitration.

    Centralises the sanitise-then-rank logic that was previously duplicated in
    ``_finalize_candidates`` (via ``_finalize_candidate_rows``) and
    ``_reconcile_detail_candidate_values``.

    Usage::

        engine = FieldDecisionEngine(base_url=url)

        # Path A – from candidate rows (replaces inline ranking in
        #          _finalize_candidates and _reconcile_detail_candidate_values)
        decision = engine.decide_from_rows("title", rows)

        # Path B – post-merge adapter/candidate preference
        value = engine.decide_merge_preference("brand", existing, candidate)
    """

    def __init__(self, *, base_url: str = "") -> None:
        self._base_url = base_url

    # ------------------------------------------------------------------
    # Primary arbitration: candidate rows → single winning value
    # ------------------------------------------------------------------

    def decide_from_rows(
        self,
        field_name: str,
        rows: list[dict],
    ) -> FieldDecision:
        """Pick the best candidate value for *field_name* from *rows*.

        Steps:
        1. Normalise + sanitise each row via ``finalize_candidate_row``.
        2. Reject invalid / empty / noisy values.
        3. Rank surviving rows with ``candidate_source_rank``.
        4. Return the highest-ranked row as winner.
        """
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
                    "field_decision: %s – all %d candidates rejected",
                    field_name,
                    len(decision.rejected_rows),
                )
            return decision

        # Rank and pick winner
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

        decision.value = best_row["value"]
        decision.source = best_row.get("source")
        decision.rank = best_rank
        decision.accepted = True
        decision.winning_row = best_row

        logger.debug(
            "field_decision: %s – winner source=%s rank=%d (of %d accepted, %d rejected)",
            field_name,
            decision.source,
            decision.rank,
            len(accepted_rows),
            len(decision.rejected_rows),
        )
        return decision

    # ------------------------------------------------------------------
    # Adapter-merge preference (wraps _should_prefer_secondary_field)
    # ------------------------------------------------------------------

    def decide_merge_preference(
        self,
        field_name: str,
        existing: object,
        candidate: object,
    ) -> object:
        """Return the preferred value when merging adapter primary with candidate secondary.

        Applies sanitisation to the candidate before the preference check. If
        the candidate is rejected by sanitisation the existing value wins.
        """
        if candidate in (None, "", [], {}):
            return existing

        # Sanitise candidate before merge preference check
        sanitised, rejection_reason = sanitize_field_value_with_reason(
            field_name, candidate
        )
        if sanitised in (None, "", [], {}):
            logger.debug(
                "field_decision merge: %s – candidate rejected (%s), keeping existing",
                field_name,
                rejection_reason,
            )
            return existing

        if _should_prefer_secondary_field(field_name, existing, sanitised):
            return sanitised
        return existing
