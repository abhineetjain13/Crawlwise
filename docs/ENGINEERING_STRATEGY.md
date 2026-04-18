# Engineering Strategy

## Purpose

CrawlerAI is a web crawler. The backend should stay small, explicit, and easy to debug.

This document defines the active engineering rules for backend work:

- keep API behavior stable for the current frontend
- keep `EXTRACTION_ENHANCEMENT_SPEC.md` unchanged until feature work starts
- prefer deletion over abstraction
- give every concern one obvious home
- keep tests focused on contracts and behavior

## Backend Shape

The backend is organized around seven responsibilities:

1. crawl orchestration
2. acquisition
3. extraction
4. normalization
5. persistence and review mapping
6. export
7. LLM and admin support

Anything that does not clearly belong to one of those areas is candidate debt.

## Current Module Ownership

### Crawl orchestration

- `backend/app/services/crawl_crud.py`
- `backend/app/services/pipeline/core.py`
- `backend/app/services/_batch_runtime.py`

These modules create runs, process URLs, persist records, and keep run state moving.

### Acquisition

- `backend/app/services/acquisition/acquirer.py`
- `backend/app/services/acquisition/http_client.py`
- `backend/app/services/acquisition/browser_client.py`
- `backend/app/services/acquisition/browser_pool.py`
- `backend/app/services/crawl_fetch_runtime.py`

Rules:

- fetch logic lives here
- browser escalation lives here
- extraction logic does not live here

### Extraction

- `backend/app/services/crawl_engine.py`
- `backend/app/services/detail_extractor.py`
- `backend/app/services/listing_extractor.py`
- `backend/app/services/structured_sources.py`
- `backend/app/services/field_value_utils.py`

Rules:

- `crawl_engine.py` is the public extraction facade
- detail and listing extraction stay separate
- structured-source parsing stays separate from DOM extraction
- extraction produces candidate records, not schema mutations

### Normalization

- `backend/app/services/normalizers/__init__.py`

Rules:

- normalization shapes values after extraction
- normalization does not decide what fields are allowed

### Field policy and schema persistence

- `backend/app/services/field_policy.py`
- `backend/app/services/schema_service.py`
- `backend/app/services/review/__init__.py`

Rules:

- `field_policy.py` is the single field-rule entrypoint
- canonical fields, aliases, requested-field expansion, and review-target validation belong there
- `schema_service.py` is persistence-oriented and narrow
- extraction and LLM code must not mutate schema state

### Export

- `backend/app/services/record_export_service.py`

Rules:

- export is formatting over stored records
- export does not re-interpret extraction semantics

### LLM support

- `backend/app/services/llm_runtime.py`
- `backend/app/services/llm_config_service.py`
- `backend/app/services/llm_provider_client.py`
- `backend/app/services/llm_cache.py`
- `backend/app/services/llm_circuit_breaker.py`
- `backend/app/services/llm_tasks.py`
- `backend/app/services/llm_types.py`

Rules:

- `llm_runtime.py` stays a thin facade
- provider transport, cache, config lookup, retries, and task validation stay separate
- LLM code must not sit in the extraction path

## Non-Negotiable Design Rules

### KISS

- prefer plain data flow over pipelines of hooks and policies
- prefer explicit modules over generic frameworks
- prefer a few clear conditionals over hidden indirection

### DRY

- deduplicate rules only when the duplicated logic is truly the same rule
- do not create “shared” helpers that mix unrelated concerns

### SOLID in practice

- single responsibility per module
- stable facades at subsystem boundaries
- downstream modules consume data contracts, not upstream internals

### YAGNI

- do not add speculative adapters, ranking layers, plugin points, or schema engines
- build only what the current frontend and the extraction enhancement work will actually need

## File Size Guardrail

Backend service files should stay under 1000 lines.

If a file approaches that limit:

- split by responsibility before adding more behavior
- keep the public facade file small
- move helpers into explicitly named modules

## Testing Rules

Tests should verify behavior and contracts.

Good tests:

- requested fields expand correctly
- fetch runtime escalates to browser when needed
- extraction returns normalized records
- review save persists mappings and promotes values
- export serializes stored records cleanly
- LLM task execution validates payloads and handles provider failures safely

Bad tests:

- private helper imports with no user-facing contract
- assertions about call order inside a module
- tests that only lock implementation details

## Change Workflow

When changing backend behavior:

1. identify the owning subsystem
2. edit the smallest responsible file set
3. keep names explicit
4. add or update contract tests
5. run the backend test suite

## Active Simplification Target

The backend should remain easy to inspect under pressure.

A bug should be traceable quickly to one of these places:

- fetch/runtime
- extraction
- normalization
- review/schema persistence
- export
- LLM support
- pipeline/orchestration

If a change makes that harder, it is moving in the wrong direction.
