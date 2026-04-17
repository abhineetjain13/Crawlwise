Phase 4 Boundary Review
Scope
Target slice or concern: LLM integration and review bucket helpers
Files reviewed: pipeline/llm_integration.py, pipeline/review_helpers.py, tests/services/pipeline/test_pipeline_coupling.py
Boundary being tested: Does pipeline correctly own LLM candidate cleanup and review-bucket shaping, or do these behaviors belong in extract and publish?
Executive Decision
Verdict: HARMFUL OWNERSHIP DRIFT
Primary reason: pipeline/llm_integration.py contains deep candidate arbitration, candidate mutation, and evidence-gathering logic that reaches directly into trace structures. Pipeline is acting as the LLM extractor and output shaper instead of orchestrating an extract-owned LLM cleanup step.
Should this module move now? YES
Function Ownership Findings
Helper 1
Function or group: _apply_llm_suggestions_to_candidate_values, _select_llm_review_candidates
Current owner: pipeline/llm_integration.py
Recommended owner: extract
Why the current owner is correct or incorrect: These functions mutate the candidate_values dictionary, perform arbitration based on distinct values and sources, and inject trace metadata. This is extraction-stage candidate arbitration, not pipeline orchestration.
Evidence from the supplied files: Calls coerce_field_candidate_value, modifies candidate_values[normalized_field], checks row.get("source") == "llm_xpath", and inserts auto_promoted status into source_trace["candidates"].
Action: move
What must not move with it: Final record persistence or generic normalization helpers.
Helper 2
Function or group: _build_llm_candidate_evidence, _build_llm_discovered_sources, _snapshot_for_llm
Current owner: pipeline/llm_integration.py
Recommended owner: extract
Why the current owner is correct or incorrect: Compiling discovered sources and trace candidates into an LLM prompt payload is part of extraction-stage candidate evaluation and context building.
Evidence from the supplied files: Calls parse_page_sources(html) from discover, iterates trace_candidates, and formats extraction-specific fields like xpath, css_selector, and regex.
Action: move
What must not move with it: parse_page_sources itself, which remains discover-owned.
Helper 3
Function or group: _split_llm_cleanup_payload, _normalize_llm_cleanup_review, _normalize_llm_review_bucket_item
Current owner: pipeline/llm_integration.py
Recommended owner: publish
Why the current owner is correct or incorrect: These helpers take raw LLM output, normalize review values, and shape review-bucket structures that feed the downstream review artifact. Pipeline should not own output shaping.
Evidence from the supplied files: Calls _normalize_review_value, _passes_detail_quality_gate, and _review_values_equal while producing canonical-review and review_bucket rows.
Action: split
What must not move with it: Candidate generation and mutation logic.
Helper 4
Function or group: _merge_review_bucket_entries, _should_surface_discovered_field
Current owner: pipeline/review_helpers.py
Recommended owner: publish
Why the current owner is correct or incorrect: Deduplicating and shaping the review bucket to be saved is a publish/review concern, not pipeline orchestration.
Evidence from the supplied files: Imports _review_bucket_fingerprint from app.services.publish.verdict and applies discovered-field/source/value noise filters before surfacing review rows.
Action: move
What must not move with it: Pipeline sequencing or LLM runtime invocation.
Canonical Ownership Table
Behavior: LLM candidate arbitration, candidate selection, and context building
Chosen owner: app.services.extract
Why this owner is correct: Evaluating candidates, building extraction context, and selecting LLM review targets are extraction behaviors.
Files that should stop owning it: backend/app/services/pipeline/llm_integration.py
Behavior: Review bucket shaping, deduplication, and noise filtering
Chosen owner: app.services.publish
Why this owner is correct: The review bucket is a downstream review artifact aligned with publish-owned verdict and save-time shaping.
Files that should stop owning it: backend/app/services/pipeline/review_helpers.py, backend/app/services/pipeline/llm_integration.py
Refactor Guardrails
Boundary moves that should happen now: Split candidate-focused LLM cleanup helpers into extract and review-bucket shaping helpers into publish.
Boundary moves that should wait: Any move of app.services.llm_runtime.py is out of scope for this slice.
Anti-patterns to avoid: Do not create a generic pipeline/utils.py for these helpers. Do not leave candidate manipulation in pipeline.detail_flow.py once the new owners exist.
Final Recommendation
SPLIT IN CURRENT SLICE
Reason:
pipeline/llm_integration.py and pipeline/review_helpers.py violate the orchestration-only boundary by owning candidate arbitration, candidate mutation, value normalization, and review-bucket formatting. Split the behaviors between extract and publish.
First 3 concrete next actions:
Move _merge_review_bucket_entries and _should_surface_discovered_field from pipeline/review_helpers.py into a publish-owned review shaping module.
Move candidate-focused LLM functions (_apply_llm_suggestions_to_candidate_values, _build_llm_candidate_evidence, _build_llm_discovered_sources, _select_llm_review_candidates, _snapshot_for_llm) to an extract-owned LLM cleanup module.
Move payload splitting and review-bucket normalization helpers (_split_llm_cleanup_payload, _normalize_llm_cleanup_review, _normalize_llm_review_bucket_item) into the publish-owned review shaping module, leaving pipeline as the caller only.
