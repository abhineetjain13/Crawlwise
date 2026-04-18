# CrawlerAI Architecture SRS v2.1

## 1. Scope

This document describes the live backend architecture.

The current system is intentionally simple:

- FastAPI routes remain stable for the current frontend
- crawl execution uses a compact fetch and extraction core
- review persists approved mappings
- export formats stored records
- LLM support is isolated from crawl extraction

`EXTRACTION_ENHANCEMENT_SPEC.md` remains the source for upcoming extraction features. This document describes the current baseline those features must build on.

## 2. System Overview

The backend flow is:

1. create crawl run
2. acquire page HTML
3. extract detail or listing records
4. normalize record values
5. persist records
6. review and promote discovered fields when needed
7. export stored records

## 3. Subsystem Boundaries

### 3.1 Crawl orchestration

Primary modules:

- `backend/app/services/crawl_crud.py`
- `backend/app/services/pipeline/core.py`
- `backend/app/services/_batch_runtime.py`

Responsibilities:

- create and list runs
- expand requested fields before execution
- process URLs
- persist extracted records
- update run status and summary

### 3.2 Acquisition

Primary modules:

- `backend/app/services/crawl_fetch_runtime.py`
- `backend/app/services/acquisition/acquirer.py`
- `backend/app/services/acquisition/http_client.py`
- `backend/app/services/acquisition/browser_client.py`
- `backend/app/services/acquisition/browser_pool.py`

Responsibilities:

- pooled HTTP fetch
- pooled browser rendering
- blocked-page detection
- JS-shell detection and browser escalation

Constraints:

- acquisition does not extract fields
- acquisition returns page content and fetch metadata only

### 3.3 Extraction

Primary modules:

- `backend/app/services/crawl_engine.py`
- `backend/app/services/detail_extractor.py`
- `backend/app/services/listing_extractor.py`
- `backend/app/services/structured_sources.py`
- `backend/app/services/field_value_utils.py`

Responsibilities:

- choose detail vs listing extraction
- parse structured sources such as JSON-LD and embedded JSON
- apply DOM fallbacks
- build candidate records
- finalize normalized record payloads

Constraints:

- extraction does not own schema mutation
- extraction does not depend on LLM modules

### 3.4 Field policy and schema persistence

Primary modules:

- `backend/app/services/field_policy.py`
- `backend/app/services/schema_service.py`
- `backend/app/services/review/__init__.py`

Responsibilities:

- define canonical fields by surface
- resolve aliases
- expand requested fields
- validate review target fields
- persist approved review mappings and resolved schemas

Constraints:

- `field_policy.py` is the single field-rule entrypoint
- schema persistence is isolated from extraction and export

### 3.5 Normalization

Primary module:

- `backend/app/services/normalizers/__init__.py`

Responsibilities:

- normalize extracted field values and finalized records

### 3.6 Export

Primary module:

- `backend/app/services/record_export_service.py`

Responsibilities:

- stream JSON, CSV, markdown, and artifact exports
- format stored records only

Constraints:

- export does not infer new field meaning
- export should strip internal-only payload noise

### 3.7 LLM support

Primary modules:

- `backend/app/services/llm_runtime.py`
- `backend/app/services/llm_config_service.py`
- `backend/app/services/llm_provider_client.py`
- `backend/app/services/llm_cache.py`
- `backend/app/services/llm_circuit_breaker.py`
- `backend/app/services/llm_tasks.py`
- `backend/app/services/llm_types.py`

Responsibilities:

- resolve active configs
- load prompts
- call providers safely
- cache task responses
- validate task payloads
- expose a thin runtime facade

Constraints:

- LLM support is not part of the extraction import path
- LLM support does not own schema decisions

## 4. Data Contracts

### 4.1 Crawl run

A crawl run must contain:

- `run_type`
- `url`
- `surface`
- `status`
- `requested_fields`
- `result_summary`

Requested fields are normalized before execution.

### 4.2 Acquisition result

Acquisition returns:

- requested URL
- final URL
- HTML
- fetch method
- status code
- content type
- blocked flag
- response headers

### 4.3 Extracted record

An extracted record is a plain dictionary with:

- canonical field values
- `source_url`
- optional `url`
- `_source` during in-memory processing

Before persistence, internal-only keys are filtered out of stored `data`.

### 4.4 Review promotion

Review promotion persists:

- domain
- surface
- approved schema snapshot
- source-to-target field mapping

Review can also promote selected review-bucket values into stored records when the target field is still empty.

## 5. API Stability Requirements

This simplification pass keeps these stable:

- current frontend expectations
- current API routes and payload shapes used by the frontend
- review and export behavior at the route boundary

Internal module boundaries may change as long as those contracts remain stable.

## 6. Engineering Constraints

- backend service files should remain under 1000 lines
- module names must describe responsibility directly
- one concern should have one obvious implementation home
- new features should extend existing subsystem boundaries instead of creating parallel ones

## 7. Test Requirements

The backend test suite must cover:

- crawl run requested-field expansion
- acquisition browser escalation behavior
- detail extraction contracts
- listing extraction contracts
- review save and field promotion
- export serialization
- LLM task validation and failure handling
- structural guardrails for file size and import boundaries

## 8. Extension Rules

Future extraction enhancements should:

- extend `crawl_engine` through detail/listing/structured-source modules
- use `field_policy.py` for field naming decisions
- preserve API compatibility with the current frontend
- avoid adding feature-specific schema mutation paths

Any future complexity should be added only where the owning subsystem already exists.
