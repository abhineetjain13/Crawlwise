# Backend Pending Items

> Consolidated on 2026-04-05 from `audit_pipeline.md`, `audit3.md`, `Audit_report.md`, `Audit_report2.md`, and the previous backlog sections of `docs/backend-architecture.md`.

## Purpose

This file is the single backlog for major backend bugs, refactors, and architectural follow-up work. `docs/backend-architecture.md` should describe the current system only. `CLAUDE.md` should point here instead of duplicating long pending-item lists.

## Recently Closed

- AutoZone SSR false-positive browser escalation, nested JSON-LD listing extraction, numeric/filter-count listing noise, and JSON recursion depth issues were fixed in acquisition and listing extraction.
- LLM prompt truncation now preserves valid JSON-oriented sections instead of blindly slicing serialized payloads.
- CSV export now derives headers from the full export row stream instead of a capped sample.
- Worker orphan recovery no longer fails every active run at startup; it now only recovers stale `claimed`/`running` runs after a grace window.
- XPath validation now rejects disallowed axes, union expressions, variables, and non-allowlisted functions before selector or contract evaluation.
- Pause/kill responsiveness now reaches into host pacing, configured acquire sleeps, browser readiness polling, challenge waits, and scroll/load-more delays via cooperative checkpoints instead of only checking around URL boundaries.
- Anti-bot roadmap for Cloudflare/Akamai and related providers is tracked in `docs/anti-bot-hardening-plan.md`.
- Listing extraction now rejects more category/facet hub cards that only expose visual fields plus a hub-like URL while still allowing detail-like item URLs.
- Stale architecture-doc findings about missing `DiscoveryManifest`/`discover_sources` imports are no longer applicable.
- Standard record responses already lazy-load heavy provenance: manifest-heavy payloads are hidden from `/api/crawls/{run_id}/records`, with a dedicated `/api/records/{record_id}/provenance` endpoint for full trace inspection.

## Priority 1

- Worker ownership and heartbeat for orphan recovery.
  Current state: startup recovery now uses a grace window, which avoids immediately killing fresh active jobs.
  Remaining gap: there is still no per-worker ownership or heartbeat column on `crawl_runs`, so multi-worker recovery is still heuristic rather than authoritative.

- Pagination architecture rewrite.
  Current state: `_collect_paginated_html()` still concatenates multiple pages with `<!-- PAGE BREAK -->`, and listing extraction re-parses those fragments later.
  Remaining gap: this is memory-heavy and structurally brittle on large runs. Replace concatenated HTML with page-by-page processing and merge extracted records in Python.

- Batch orchestration and pause responsiveness.
  Current state: `process_run()` is still sequential, but pause/kill now interrupts many long acquisition/browser waits through cooperative checkpoints instead of only at URL boundaries.
  Remaining gap: one in-flight network call or browser navigation can still hold the worker until that call returns, and large batches still suffer head-of-line blocking because URLs are processed serially.

## Priority 2

- Dynamic schema phase 2 follow-up.
  Current state: runtime schema resolution is now domain-scoped and DB-backed via `site_memory`.
  Remaining gap: exports, frontend/admin schema visibility, explicit global-promotion workflow, and broader heuristic-to-config cleanup are still deferred.

- Extraction-quality cleanup for static/detail pages.
  Continue improving table/spec normalization for fields like `price`, `sku`, and `image_url`, and keep filtering CSS/style/unit leakage from semantic fields such as `color`, `size`, and `category`.

- Listing classification and non-product hub detection.
  Current state: the extractor now rejects more nav/facet/category hub cards, especially title/image-only records with non-detail hub URLs.
  Remaining gap: some taxonomy/search landing pages can still look listing-like when they include richer merchandised tiles or sparse product metadata.

- Arbitrary SPA listing-state extraction.
  Discovery can preserve hydrated state blobs, but listing extraction still misses some React/Angular page shapes where items are buried under app-specific component state rather than obvious collection keys.

## Priority 3

- Provenance / review-bucket schema split.
  Current state: review-bucket rows and provenance lazy-loading both exist, and heavy manifest payloads are already hidden from the normal records API.
  Remaining gap: canonical fields, review-bucket attributes, and provenance data are still stored across overlapping JSON blobs rather than a cleaner staged backend model.

- Typed review/commit path.
  Manual review and LLM cleanup flows still flatten many values to strings. Preserve arrays, objects, booleans, and numerics end-to-end through review, commit, and export.

- `crawl_service.py` decomposition.
  The service still mixes CRUD, pipeline orchestration, verdict aggregation, progress tracking, and review-field commit logic in one large module.

## Platform Coverage

- Expand blocked-page adapter recovery beyond Shopify.
- Add Lever ATS support.
- Review whether additional ATS/ecommerce adapters should move from heuristics into first-class adapters based on failure frequency in smoke/audit runs.

## Operational Hardening

- Move pacing and host memory to shared storage.
  `pacing.py` and `host_memory.py` still rely on process-local/file-backed coordination, which is weak under multi-process or multi-container deployment.

- Revisit `crawl_runs.result_summary` mutability.
  The JSON blob still carries volatile execution state such as progress counters and verdict summaries. Consider promoting high-churn fields into dedicated columns if concurrent writers become more common.

## Testing Backlog

- Add worker-orphan recovery coverage for true multi-worker ownership once worker identity exists.
- Add pagination isolation tests that validate page-by-page extraction without concatenated DOMs.
- Add broader end-to-end pause/resume coverage for real browser/network waits beyond the current cooperative-checkpoint regression tests.
- Add offline evaluation fixtures for noisy detail/listing pages, especially for style-value leakage and review-bucket noise.

Intelligent Wait: Modify the browser client to recognize Datadome/Cloudflare interstitials and stay on the page until the actual product title or price selector appears.
Shared Cookie Store: Implement a mechanism to "harvest" Datadome cookies during a successful browser session and feed them back into the curl_cffi sessions for faster, authenticated scraping.
TLS Fingerprint Rotation: Update our HTTP client to more aggressively rotate TLS fingerprints (impersonating different browser versions) to bypass the initial 429 block.

## Phase 1: Lightweight Parallelism (Current Target)

The goal is a 5-10x speedup for batches of 50-100 URLs without the overhead of a dedicated task broker.

### [NEW] [Infra] PostgreSQL Migration
- Replace `aiosqlite` with `asyncpg` or similar PostgreSQL driver.
- Update `SQLALCHEMY_DATABASE_URL` in `.env`.
- Migrate schema using `alembic upgrade head`.

### [MODIFY] [crawl_service.py](file:///backend/app/services/crawl_service.py)
- **Semaphore Implementation**: Introduce `asyncio.Semaphore(limit)` (default 5-8) to control concurrent browser instances.
- **Orchestration Refactor**: Update `process_run` to use `asyncio.gather` with the semaphore instead of a sequential `for` loop.
- **Atomicity**: Implement `asyncio.Lock()` around `result_summary` updates to prevent race conditions during concurrent progress increments.

## Phase 2: Distributed Production (Future Roadmap)

Transition to a system capable of handling 10,000+ URLs across multiple nodes.

### [NEW] [Infra] Redis & Celery
- **Broker**: Deploy **Redis** as the message broker.
- **Workers**: Deploy **Celery** workers. Each URL in a batch becomes an independent Celery task (`@app.task`).
- **Monitoring**: Deploy **Flower** for real-time monitoring of task success rates and worker load.

### [REFRESH] System Architecture
- **API**: Decouples from execution. API only submits URLs to the queue.
- **State Management**: Use Redis for distributed locking (global rate limits per domain).
- **Scalability**: Horizontal scaling by simply spinning up more worker containers on different servers.
