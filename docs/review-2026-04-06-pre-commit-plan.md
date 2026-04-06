# Review 2026-04-06: Pre-Commit Plan

## Scope reviewed

- Earlier architecture audit in `arch_review.md`
- Today's committed changes (`2bf9c2c`, `c3f410d`)
- Current uncommitted backend/frontend/docs changes in the working tree

## Test evidence

- `pytest tests/services/acquisition/test_browser_client.py tests/services/acquisition/test_acquirer.py tests/services/extract/test_listing_extractor.py tests/services/test_crawl_service.py -q`
- `pytest tests/services/test_schema_service.py tests/services/test_page_classifier.py tests/services/test_site_memory_service.py tests/test_knowledge_boundary.py -q`
- Result: `184 passed`

## Critical findings

### 1. Page-classification LLM path is not wired into the prompt registry

- Severity: Critical
- References:
  - `backend/app/services/llm_integration/page_classifier.py:265`
  - `backend/app/data/knowledge_base/prompt_registry.json:1`
  - `backend/app/services/llm_runtime.py:107`

#### Problem

`classify_page()` calls `run_prompt_task(task_type="page_classification")`, but `prompt_registry.json` does not define `page_classification`. Any heuristic miss with `llm_enabled=true` will therefore return `payload=None` from `run_prompt_task()`.

#### Failure scenario

A page that needs LLM classification falls through heuristics, the prompt lookup fails, and classification silently degrades to `"unknown"` instead of using the new prompt files that were added today. That can suppress intended surface correction and leave downstream extraction on the wrong path.

#### Fix plan

1. Add a `page_classification` entry to `backend/app/data/knowledge_base/prompt_registry.json`.
2. Add an integration test that exercises `run_prompt_task()` against the registry for `page_classification` without monkeypatching the task lookup.
3. Fail fast in `classify_page()` when `result.error_message` is set, instead of treating an LLM setup error as a valid `"unknown"` classification.

### 2. Schema inference persists successful-looking snapshots even when the LLM call failed

- Severity: Critical
- References:
  - `backend/app/services/schema_service.py:262`
  - `backend/app/services/schema_service.py:277`
  - `backend/app/services/schema_service.py:291`
  - `backend/app/services/llm_runtime.py:108`
  - `backend/app/services/llm_runtime.py:136`

#### Problem

`_infer_schema_via_llm()` does not check `result.error_message` or `result.payload is None`. It always constructs a `ResolvedSchema` with `source="llm_inferred"` and `confidence=0.6`, even when the prompt/config/provider/parsing path failed.

#### Failure scenario

If the LLM call fails once, the code can persist a baseline-only schema snapshot as if it were a successful inference. Because that snapshot is then marked fresh, future runs may stop retrying schema enrichment for up to 7 days and site memory will contain misleading provenance.

#### Fix plan

1. In `_infer_schema_via_llm()`, return `None` when `result.error_message` is non-empty or `result.payload` is not a dict.
2. Only mark `source="llm_inferred"` when at least one of `confirmed_fields`, `new_fields`, or `absent_fields` is actually produced.
3. Add tests for:
   - missing prompt/config
   - provider/parsing failure returning `payload=None`
   - no-op payloads that should not be persisted

### 3. New LLM integrations bypass run-scoped config snapshots and cost attribution

- Severity: High
- References:
  - `backend/app/services/crawl_service.py:118`
  - `backend/app/services/crawl_service.py:699`
  - `backend/app/services/llm_integration/page_classifier.py:266`
  - `backend/app/services/schema_service.py:263`
  - `backend/app/services/llm_runtime.py:83`
  - `backend/app/services/llm_runtime.py:162`

#### Problem

`create_crawl_run()` captures `llm_config_snapshot`, but both new call sites pass `run_id=None` into `run_prompt_task()`. That means page classification and schema inference do not use the per-run snapshot and their cost logs are not linked to the crawl run.

#### Failure scenario

If an active LLM config is changed while a crawl is running, these new steps can use different models/settings than the rest of the run. Cost/accounting will also be incomplete because `LLMCostLog.run_id` stays null for those requests.

#### Fix plan

1. Thread `run.id` into `classify_page()` and `_infer_schema_via_llm()`.
2. Pass that run id through to `run_prompt_task()`.
3. Extend tests to assert snapshot usage and `LLMCostLog.run_id` population for page classification and schema inference.

## Commit recommendation

Do not make the final commit until Findings 1 and 2 are fixed. Finding 3 should be fixed in the same patch if you want reproducible, auditable LLM behavior from this change set.

## Safe-commit checklist

- Add registry wiring for `page_classification`
- Guard `classify_page()` against `run_prompt_task()` error results
- Guard `_infer_schema_via_llm()` against empty/error LLM results
- Pass `run.id` through all new LLM task call sites
- Add regression tests for the three paths above
- Remove any accidental source artifacts before commit, especially `backend/app/services/llm_integration/__pycache__/`
