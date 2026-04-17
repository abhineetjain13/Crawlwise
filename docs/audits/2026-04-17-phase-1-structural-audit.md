---
title: "phase 1 structural audit"
type: refactor-audit
status: complete
date: 2026-04-17
phase: 1
---

# Phase 1 Structural Audit

## Scope

This audit establishes the initial evidence baseline for the backend refactor program. It focuses on:

- oversized modules
- high-complexity functions
- cross-stage coupling
- duplication signals
- stage ownership violations across `acquire -> discover -> extract -> normalize -> publish`

This is the completed Phase 1 artifact and should be used as the source of truth for downstream Phase 2 and Phase 3 work.

## Tooling Used

- `python` one-off repo scans for file-size ranking
- `radon cc backend/app/services -s -j`
- AST-based cross-area import scan
- AST-based repeated-function-name scan
- `rg` helper-pattern scan

## File-Size Leaderboard

| Rank | File | Lines | Audit note |
|---|---|---:|---|
| 1 | `backend/app/services/acquisition/acquirer.py` | 2917 | primary P0 hotspot; acquisition policy, escalation, diagnosis, and recovery remain combined |
| 2 | `backend/app/services/config/extraction_rules.py` | 2179 | oversized config/policy surface; likely carrying behavior through config ownership |
| 3 | `backend/app/services/acquisition/traversal.py` | 1925 | traversal strategies and heuristics are concentrated in one owner |
| 4 | `backend/app/services/extract/variant_builder.py` | 1701 | variant extraction, reconciliation, and normalization likely mixed |
| 5 | `backend/app/services/acquisition/browser_client.py` | 1544 | browser fetch/runtime concerns still large even after prior decomposition |
| 6 | `backend/app/services/extract/listing_card_extractor.py` | 1458 | card-specific extraction remains large but appears more cohesive than the P0 files |
| 7 | `backend/app/services/llm_runtime.py` | 1421 | large runtime owner, but not yet on the critical refactor path for stage separation |
| 8 | `backend/app/services/normalizers/__init__.py` | 1340 | normalization is still concentrated in a single package entry file |
| 9 | `backend/app/services/extract/service.py` | 1300 | detail candidate orchestration remains oversized |
| 10 | `backend/app/services/extract/source_parsers.py` | 944 | discover-like ownership is still embedded in extract |

## Highest-Complexity Functions

| Rank | File | Function | Complexity | Working interpretation |
|---|---|---|---:|---|
| 1 | `backend/app/services/extract/listing_quality.py` | `assess_listing_record_quality` | 90 | quality, filtering, and policy likely collapsed into one decision engine |
| 2 | `backend/app/services/acquisition/browser_client.py` | `_fetch_rendered_html_attempt` | 64 | fetch orchestration still mixes runtime setup, navigation, readiness, and fallback |
| 3 | `backend/app/services/normalizers/__init__.py` | `validate_value` | 60 | normalization contract is too centralized |
| 4 | `backend/app/services/extract/listing_item_normalizer.py` | `_normalize_listing_value` | 55 | normalization logic likely mixed with source-aware extraction assumptions |
| 5 | `backend/app/services/acquisition/blocked_detector.py` | `detect_blocked_page` | 54 | blocked detection is carrying too many policy branches |
| 6 | `backend/app/services/acquisition/acquirer.py` | `_browser_escalation_decision` | 49 | escalation policy is a clear extraction candidate |
| 7 | `backend/app/services/pipeline/detail_flow.py` | `extract_detail` | 44 | pipeline orchestration still owns too much detail extraction behavior |
| 8 | `backend/app/services/extract/semantic_support.py` | `_build_semantic_rows` | 42 | semantic extraction logic is large and probably under-factored |
| 9 | `backend/app/services/extract/listing_structured_extractor.py` | `_normalize_ld_item` | 42 | structured extraction and normalization still overlap |
| 10 | `backend/app/services/acquisition/traversal.py` | `collect_paginated_html` | 40 | traversal policy and execution remain entangled |

## Coupling Findings

Cross-area import scan identified these structural issues:

- `acquisition/acquirer.py` imports `adapters`, `config`, and `pipeline`.
  Acquisition should not depend on pipeline ownership.
- `pipeline/detail_flow.py` imports `acquisition`, `adapters`, and `extract`.
  Some orchestration reach is expected, but the current complexity shows behavior leakage.
- `pipeline/listing_flow.py`, `pipeline/stages.py`, and `pipeline/trace_builders.py` all depend on both `acquisition` and `extract`.
  Stage orchestration and stage-specific business logic are still mixed.
- `extract/source_parsers.py` behaves like `discover`, but lives under `extract`.
  This is a naming and ownership mismatch.
- `pipeline/field_normalization.py` depends on `extract` and `normalizers`.
  Normalization policy is not yet isolated.
- `schema_service.py` importing `pipeline` is an inversion risk.

## Duplication Signals

Initial duplication scan found these clusters:

- Normalization helpers are spread across:
  - `normalizers/__init__.py`
  - `extract/candidate_processing.py`
  - `extract/listing_item_normalizer.py`
  - `extract/listing_normalize.py`
  - `extract/listing_structured_extractor.py`
  - `pipeline/field_normalization.py`
- URL and shape heuristics are spread across:
  - `extract/listing_quality.py`
  - `pipeline/stages.py`
  - `pipeline/listing_helpers.py`
  - `acquisition/acquirer.py`
  - several adapters
- Missing canonical-home signals:
  - `_elapsed_ms`
  - `get_canonical_fields`
  - `_build_xpath_tree`
- Adapter-local duplication worth later review:
  - `_clean_text`
  - `_extract_job_id_from_url`

## Hotspot Classification

| File | Classification | Reason |
|---|---|---|
| `backend/app/services/acquisition/acquirer.py` | `mixed-responsibility` | combines acquisition execution, escalation policy, diagnosis, retry, and platform hints |
| `backend/app/services/pipeline/detail_flow.py` | `mixed-responsibility` | pipeline owner is carrying detail extraction logic and reconciliation policy |
| `backend/app/services/extract/source_parsers.py` | `stale-seam` | discover behavior is placed under extract, which obscures the stage model |
| `backend/app/services/config/extraction_rules.py` | `stale-seam` | config appears to be compensating for unclear ownership boundaries |
| `backend/app/services/acquisition/traversal.py` | `duplicate-strategy` | multiple traversal strategies and heuristics are concentrated together |
| `backend/app/services/acquisition/browser_client.py` | `orchestrator` | still too large, but its core problem is overloaded orchestration more than arbitrary duplication |

## Recommended Hotspot Order

1. `backend/app/services/acquisition/acquirer.py`
   Reason: largest active hotspot and highest architectural leverage for boundary cleanup.
2. `backend/app/services/pipeline/detail_flow.py`
   Reason: direct pressure point between pipeline orchestration, extraction, and normalization.
3. `backend/app/services/extract/source_parsers.py`
   Reason: likely first concrete `discover` extraction target.
4. `backend/app/services/config/extraction_rules.py`
   Reason: revisit after boundary cleanup starts so config can be reduced rather than shuffled.
5. `backend/app/services/acquisition/traversal.py`
   Reason: follow acquisition boundary clarification so traversal refactors do not move policy twice.

## Architectural Conclusion

The dominant issue is not just file size. It is boundary confusion:

- `discover` logic is still living under `extract`
- `normalize` logic is still split across extract, pipeline, and normalizers
- acquisition still reaches upward into pipeline-aware decisions

Refactor slices should therefore be organized by stage ownership, not by raw file size alone.

## Exit Criteria Status

| Phase 1 exit criterion | Status | Note |
|---|---|---|
| top hotspot modules identified with evidence | complete | file-size and complexity leaderboard captured |
| each hotspot tagged by failure mode | complete | orchestrator / mixed-responsibility / duplicate-strategy / stale-seam applied |
| first-pass stage boundaries proposed | complete | `acquire`, `discover`, `extract`, `normalize`, `publish` model established |

## Handoff

- Phase 2 owner: external test audit
- Phase 3 owner: module-wise refactor plan and execution slicing

Use this audit together with the program tracker before approving any refactor slice.
