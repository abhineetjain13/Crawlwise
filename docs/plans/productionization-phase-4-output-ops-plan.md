# Plan: Productionization Phase 4 - Output Layer And Operations

**Status:** READY
**Purpose:** Harden output contracts, delivery, policy enforcement, and production observability after extraction structure is stable.
**Primary audits:** `docs/audits/publish-audit.md`, `docs/audits/production-audit.md`, `docs/audits/acquisition-audit.md`, `docs/audits/selfheal-audit.md`, `docs/audits/batch-audit.md`
**Secondary audits:** `docs/audits/pipeline-audit.md`, `docs/audits/llm-audit.md`
**Scope:** Output contracts, idempotency, storage abstraction, quality gates, policy middleware, rate limiting, metrics, alerts, dependency hardening.

STRICT LOC DISCIPLINE:
- Every file you MODIFY must have deletions >= 50% of additions (net LOC change must be ≤ +50% of what you add).
- Every new file you CREATE must correspond to code MOVED from an existing file, not net-new logic. State which source file the code came from.
- You are not permitted to add to detail_extractor.py, field_value_core.py, field_value_dom.py, js_state_mapper.py, or crawl_fetch_runtime.py without an equal or greater deletion from the same file.
- If you cannot delete code to offset an addition, stop and explain why, do not add anyway.
- After implementation, output a table: filename | lines added | lines deleted | net change. Flag any file with net > +20 lines that was not in the task scope.

## Independent Context

After Phase 3, pipeline and extraction should have clear owners. Phase 4 uses those owners to enforce production contracts at boundaries: records written to DB, artifacts written to storage, exports delivered downstream, domain policies applied around fetches, and operational health visible through logs/metrics/alerts.

Do not compensate downstream for bad extraction. Quality gates may block webhook delivery and annotate exports, but extraction defects must still be fixed upstream.

## Objectives

1. Add typed export/persistence schema and use it at the pipeline/export boundary.
2. Add artifact storage abstraction while preserving local filesystem behavior.
3. Add cross-run idempotency support.
4. Add export quality gate before webhook delivery.
5. Add policy middleware and per-domain adaptive rate limiting.
6. Add run health verdict and field-level observability.
7. Finish remaining production hardening: alerts, LLM key validation, dependency checks, selector health controls.

## Audit Findings Covered

- Publish audit: untyped `dict` record contract, local-only artifact storage, no cross-run dedup, no delivered-once webhook guarantee.
- Production audit: no post-run quality gate, no alert rules, no per-domain rate limiter, no numeric run health/error budget, LLM key validation gap, dependency pinning/audit gap.
- Acquisition audit: policy enforcement is scattered; domain profile/platform/selector staleness are weak.
- Self-heal audit: no selector health metric, no domain daily LLM cap, no re-heal cooldown, weak selector synthesis gate.
- Batch audit: event persistence only; metrics stub not wired; state and resume must feed operational status.
- Pipeline audit: output validation should be explicit, not silent `None` drops.

## Non-Goals

- Do not split god-files in this phase.
- Do not redesign candidate generation.
- Do not hide extraction defects with publisher fallbacks.
- Do not force S3/GCS adoption; add interface with local implementation first.

## Implementation Slices

### Slice 1: ArtifactStorage Protocol

**Files:** `app/services/storage/base.py`, `app/services/storage/local.py`, `app/services/storage/factory.py`, `app/services/artifact_store.py`, tests

**Requirements:**

- Add `ArtifactStorage` protocol.
- Add `LocalArtifactStorage` matching current filesystem behavior.
- Add factory driven by config under `app/services/config/*`.
- Keep existing `artifact_store.py` functions as facade.

**Acceptance:**

- Existing artifact paths remain compatible.
- Artifact tests pass.
- No caller outside `artifact_store.py` knows storage backend type.

### Slice 2: ExportRecord Pydantic Schema

**Files:** `app/services/export/schema.py` or `app/services/publish/schema.py`, `pipeline/persistence.py`, `record_export_service.py`, tests

**Requirements:**

- Add `FieldProvenance`, `ExtractionTrace`, `AcquisitionTrace`, `ExportRecord`.
- Preserve native JSON values in field discovery.
- Validate URL identity and provenance shape at persistence/export boundary.
- Keep public export field shape stable unless explicitly versioned.

**Acceptance:**

- Bad provenance shape fails tests before export.
- Public records remain downloadable as before.
- Export schema has explicit version field if payload shape changes.

### Slice 3: Idempotency And Content Fingerprint

**Files:** ORM model, Alembic migration, `pipeline/persistence.py`, tests

**Requirements:**

- Keep existing `(run_id, url_identity_key)` uniqueness.
- Add `content_fingerprint` column.
- Compute fingerprint from stable product identity fields where available.
- Add indexes for run/content fingerprint.
- On conflict, update changed rows and skip identical rows.

**Acceptance:**

- Same URL in same run remains idempotent.
- Same product at alternate URL can be detected by content fingerprint.
- Migration upgrades and downgrades cleanly.

### Slice 4: Export Quality Gate

**Files:** `app/services/publish/quality_gate.py`, `record_export_service.py`, webhook delivery tests

**Requirements:**

- Compute required-field fill rates from exported public records.
- Include quality metadata in JSON and webhook payloads.
- Block webhook delivery when gate fails.
- Keep CSV/JSON downloadable with quality metadata.
- Do not repair missing fields here.

**Acceptance:**

- Gate fails when required fields are below configured fill rate.
- Webhook is not sent on gate failure.
- CSV/JSON still export and expose quality report.

### Slice 5: PolicyMiddleware And Rate Limiter

**Files:** `app/services/acquisition/policy_middleware.py`, `app/services/acquisition/rate_limiter.py`, acquisition/pipeline tests

**Requirements:**

- Add pre-fetch middleware for robots, domain rate limiter, host protection, URL safety.
- Add post-fetch middleware for acquisition contract outcome, selector hit/miss updates, domain health metrics, platform refresh.
- Add adaptive per-domain token bucket / paced lock.
- Respect robots crawl-delay as stronger pacing input.

**Acceptance:**

- Every fetch path passes through pre-fetch policy.
- 429/block outcomes increase pacing/backoff for the domain.
- Policy decisions are logged and testable.

### Slice 6: Run Health Verdict And Webhook Gate

**Files:** `app/services/publish/verdict.py`, run status schemas/API, webhook delivery, tests

**Requirements:**

- Add numeric `run_health_verdict()` using error budget thresholds from config.
- Expose run health in status response.
- Gate webhook delivery on failed run health.
- Keep existing URL verdict strings.

**Acceptance:**

- Small failure percentage is healthy or degraded per config.
- Large failure percentage is failed.
- Webhook blocks on failed run health.

### Slice 7: Selector Health And LLM Domain Caps

**Files:** `selector_self_heal.py`, `selectors_runtime.py`, `domain_selector_health.py`, Redis/domain memory tests

**Requirements:**

- Add domain daily LLM cap before selector synthesis.
- Add `llm_enabled()` guard to direct selector synthesis paths.
- Add re-heal cooldown.
- Restrict LLM self-heal to critical fields by surface.
- Emit `ExtractionWarning` when a critical field reaches null after all fallback stages.
- Compute selector health from record confidence/source metadata.

**Acceptance:**

- Selector synthesis cannot bypass run-level LLM control.
- Same broken selector does not trigger daily LLM repeats.
- Selector health reports healthy/degraded/broken.

### Slice 8: Observability And Alerts

**Files:** `app/core/metrics.py`, pipeline/persistence or extraction event owner, `deploy/prometheus/alerts.yml`, tests

**Requirements:**

- Add field-level structured events after persistence.
- Wire runtime metrics from batch execution to Prometheus.
- Add alert rules for crawl error rate, LLM spike, Celery queue depth, DB pool saturation.
- Keep log volume sampled by config.

**Acceptance:**

- Metrics exist with bounded labels.
- Alert rules parse.
- Field logs include run, domain, URL, field, status, and confidence.

### Slice 9: Production Config And Dependency Hardening

**Files:** `app/core/config.py`, `pyproject.toml`, CI config, tests

**Requirements:**

- Validate at least one LLM API key in non-local environments when LLM is enabled.
- Use `SecretStr` for proxy credentials instead of raw proxy URLs where possible.
- Pin critical browser/LLM/Celery dependency ranges.
- Add lockfile drift and vulnerability audit checks in CI.

**Acceptance:**

- Production startup fails fast on missing required LLM config.
- Local/test environments can run without provider keys.
- CI catches lock drift.

## Verification

Run focused tests per slice, then:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\ruff.exe check app tests
.\.venv\Scripts\python.exe -m mypy app
```

## Handoff Prompt

Implement one Phase 4 slice from `docs/plans/productionization-phase-4-output-ops-plan.md`. Do not add downstream compensation for extraction defects. Keep config in `app/services/config/*` unless the owning config is already in `app/core/config.py`.
