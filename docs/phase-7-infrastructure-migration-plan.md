# Phase 7 Infrastructure Migration Plan

Last updated: 2026-04-08  
Scope owner: Backend platform  
Status: Planning complete, implementation pending

---

## Objective

Migrate infrastructure in three independently deployable steps:

1. Postgres (persistence first)
2. Redis (shared runtime state + queue coordination)
3. Celery (durable background execution)

Order is mandatory: **Postgres -> Redis -> Celery**.

---

## Non-Goals

- No changes to extraction contracts, traversal semantics, or user-owned controls.
- No feature work mixed with migration slices.
- No simultaneous multi-component cutover.

---

## Success Criteria

- Zero contract regressions for crawl API behavior and run lifecycle.
- Each migration stage is deployable and reversible independently.
- Recovery path for in-flight work is tested for each stage.
- Observability supports go/no-go decisions with concrete checks.

---

## Baseline Requirements Before Starting

- Phase 0-6 verified and stable in current environment.
- Freeze non-critical backend refactors during migration window.
- Capture baseline metrics (throughput, run completion rate, p95 run latency, failure distribution).
- Back up current SQLite/crawler DB artifacts before first schema migration.

---

## Stage 1 - Postgres Migration

### Goal
Replace SQLite/in-process persistence with Postgres while preserving data model and API semantics.

### Decision Record
- Async SQLAlchemy remains the access layer.
- Alembic remains migration mechanism.
- Keep model structure stable; avoid schema redesign in first cut.

### Implementation Slices

#### 1-A: Provision + connectivity
- Add Postgres service config variables (`DATABASE_URL`, pool sizing, connect timeout).
- Add local/dev compose profile for Postgres.
- Add startup readiness checks for DB connectivity.

#### 1-B: Schema parity + migration path
- Generate canonical Alembic baseline from current models.
- Add deterministic bootstrap flow for fresh DB and existing data migration.
- Build one-time migration script from SQLite -> Postgres for:
  - users
  - crawl_runs
  - crawl_records
  - crawl_logs

#### 1-C: Runtime cutover guard
- Add environment flag: `DB_BACKEND=sqlite|postgres`.
- Implement dual-run smoke validation mode in non-prod:
  - write to Postgres
  - compare read-path outcomes against current behavior

#### 1-D: Verification + rollback
- Smoke suite against Postgres-only mode.
- Rollback plan: revert env to SQLite and restore prior DB snapshot.

### Acceptance Checks
- Full backend tests pass with Postgres target.
- Core API endpoints produce identical response shapes.
- Existing run lifecycle states and summaries remain stable.

---

## Stage 2 - Redis Migration

### Goal
Move transient runtime state from process memory to Redis-backed shared state.

### Decision Record
- Redis is authoritative for short-lived coordination state only.
- Durable records stay in Postgres.
- TTLs are mandatory for ephemeral keys.

### Implementation Slices

#### 2-A: Introduce Redis client and health checks
- Add Redis connection config and startup probe.
- Add namespaced key conventions (`crawler:*`).
- Add serializer helpers for small structured payloads.

#### 2-B: Migrate volatile state
- Move run-control/worker coordination state from in-memory maps to Redis.
- Move proxy cooldown/shared pacing state to Redis.
- Ensure lock semantics are explicit and timeout-bound.

#### 2-C: Safety + resilience
- Add fail-open/fail-closed rules per state type:
  - control plane state: fail-safe (pause/kill still possible)
  - pacing/cooldown state: degrade gracefully
- Add Redis outage handling and fallback diagnostics.

#### 2-D: Verification + rollback
- Concurrency and restart-recovery tests under Redis mode.
- Rollback plan: disable Redis integration flags and return to local in-memory state.

### Acceptance Checks
- Multi-worker contention tests pass.
- No stale key growth (TTL enforcement verified).
- Pause/kill controls work across process boundaries.

---

## Stage 3 - Celery Migration

### Goal
Replace direct/in-process run execution dispatch with durable Celery workers.

### Decision Record
- Broker: Redis (stage 2 dependency).
- Result backend: Postgres or Redis (pick one; default Redis for speed, Postgres for auditability).
- Queue topology by workload class:
  - `crawl.default`
  - `crawl.heavy`
  - `maintenance`

### Implementation Slices

#### 3-A: Task boundary design
- Define idempotent `process_run(run_id)` task contract.
- Introduce task-level correlation IDs and run ownership checks.
- Enforce max retries and retryable error taxonomy.

#### 3-B: Worker integration
- Add Celery app config and worker startup profiles.
- Route API-triggered runs to Celery enqueue path.
- Keep legacy direct path behind feature flag during rollout.

#### 3-C: Reliability controls
- Add visibility timeout/ack strategy and dead-letter handling.
- Add startup orphan recovery aligned with queued/in-flight semantics.
- Add worker liveness and backlog monitoring metrics.

#### 3-D: Verification + rollback
- Smoke tests with queued runs and worker restarts.
- Rollback plan: switch dispatch flag back to in-process runtime.

### Acceptance Checks
- Enqueued runs complete with same state transitions as pre-Celery.
- No duplicate run execution under retry/restart scenarios.
- Queue backlog and worker health are observable.

---

## Cross-Stage Testing Strategy

### Required test groups per stage
- API contract tests (crawls, records, dashboard, review).
- Run lifecycle tests (pending -> running -> terminal states).
- Recovery tests (restart, pause/kill, timeout behavior).
- Concurrency tests (parallel runs, lock contention).

### Smoke commands
- `pytest tests -q` (backend full)
- Focused slices for migration stages:
  - DB + run lifecycle tests during stage 1
  - worker/control/cooldown tests during stage 2
  - queue/worker integration tests during stage 3

---

## Rollout and Feature Flags

- `DB_BACKEND=sqlite|postgres`
- `REDIS_STATE_ENABLED=true|false`
- `CELERY_DISPATCH_ENABLED=true|false`
- `LEGACY_INPROCESS_RUNNER_ENABLED=true|false` (temporary rollback lever)

Rollout policy:
- Enable one flag at a time.
- Observe for one stabilization window before next stage.
- Keep previous stage rollback lever active until next stage is stable.

---

## Go/No-Go Checklist (Per Stage)

- Migration scripts validated in staging with production-like snapshot.
- Error budget and rollback owner assigned.
- Monitoring dashboard includes stage-specific leading indicators.
- On-call playbook updated and rehearsed.
- Explicit rollback command sequence documented and tested.

---

## Risks and Mitigations

- Data migration mismatch -> dry-run with checksums and row-count validation.
- Cross-process race conditions -> Redis locks with TTL + integration tests.
- Duplicate task execution -> idempotency guard keyed by run ID + terminal-state checks.
- Partial rollout drift -> strict feature-flag matrix and deployment gates.

---

## Deliverables

- Stage 1: Postgres migration scripts + cutover runbook + rollback runbook.
- Stage 2: Redis state adapter + TTL policy + resiliency tests.
- Stage 3: Celery dispatch/workers + queue topology + operations runbook.
- Final: consolidated post-migration verification report.

