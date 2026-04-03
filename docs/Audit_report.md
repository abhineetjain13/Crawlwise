# CrawlerAI — Pending Architecture Audit & Tech Debt Report

**Date:** 2026-04-03  
**Reviewer:** Antigravity (Principal Architecture Review)  
**Scope:** Pending Remediation Items (Frontend, Backend, DB)

This document contains **only the pending items** that still require remediation to achieve full architectural compliance and reduce technical debt, cross-referenced with `Requirements_Invariants.md`. Phase 1 and Phase 2 critical mitigations (security defaults, orphan-run recovery, pool limits, cascade deletes, domain normalization) are complete and have been removed from this list.

---

## 1. Pending Invariant Violations

| Invariant | Status | Remediation Required |
|---|---|---|
| **INV-AUTH-02** | ⚠️ Partial | **Deactivated user tokens:** JWT is stateless and lacks a blocklist. A deactivated user's token works until natural expiration. *Fix: Implement token blocklist or server-side session cache.* |
| **INV-JOB-01** | ❌ Violated | **Strict state machine:** Missing `PAUSED`, `KILLED`, `PROXY_EXHAUSTED`. State transitions are unvalidated. *Fix: Implement JobStatus enum with a `transition(from, to)` gatekeeper.* |
| **INV-JOB-02** | ❌ Violated | **Partial output on kill:** `cancel_run()` sets status to cancelled immediately without an explicit checkpoint protocol for in-memory records. *Fix: Force flush memory buffers before committing terminal state.* |
| **INV-JOB-05** | ⚠️ Partial | **Max records ceiling:** The listing extractor may over-fetch before slicing `extracted_records[:max_records]`. *Fix: Inject max_records threshold directly into extraction loop termination condition.* |
| **INV-CRAWL-01** | ⚠️ Partial | **Strict sleep times:** Sleep is missing between initial HTTP fetch and browser fallback, and between pagination requests in `browser_client.py`. *Fix: Enforce global delay mechanism for all outbound signals.* |
| **INV-CRAWL-03** | ❌ Violated | **Selector validation:** `extraction_contract` XPath/Regex are never validated syntactically before dispatch. *Fix: Add pre-flight syntax checker before spawning jobs.* |
| **INV-PROXY-01/03** | ❌ Violated | **Proxy exhaust & bypass:** Adapter recovery calls bypass proxy entirely. `ProxyRotator` picks one proxy but doesn't retry failures through the pool. *Fix: Wrap all outbound calls in a proxy-retry loop, yielding `PROXY_EXHAUSTED` only when explicitly exhausted.* |
| **INV-LLM-01/02** | ⚠️ Partial | **LLM output auto-merge & silent fail:** LLM XPath suggestions auto-merge without user review. Failures are silent. *Fix: Add approval gate, and log/notify users on LLM failure instead of quiet fallback.* |
| **INV-LLM-04** | ⚠️ Partial | **Config snapshot:** `resolve_active_config()` queries DB at runtime instead of job creation. *Fix: Bind LLM Config ID to the Crawl Run at creation.* |

---

## 2. Structural & Codebase Tech Debt

### [Severity: High] CRL-01 — The `crawl_service.py` God Object
**Context:** At 931 lines, it orchestrates parsing, run CRUD, extraction, verdicts, formatting, and LLM triggers. 
**Remediation:** Decompose into distinct modules:
1. `crawl_crud.py` (DB states)
2. `pipeline_orchestrator.py` (State execution loop)
3. `verdict.py` (Validation rules)
4. `record_builder.py` (Data formatting)

### [Severity: Medium] CRL-11 — Hardcoded Discoverist CSV Schema
**Context:** Exporter in `records.py` hardcodes `["source_url", "title", "description"]`.
**Remediation:** Externalize to `data/knowledge_base/discoverist_schema.json` and manage via `pipeline_config.py`.

### [Severity: Low] CRL-12 — Bypass of Alembic Migrations
**Context:** `schema_bootstrap.py` executes raw SQL schemas, fracturing Source of Truth with Alembic.
**Remediation:** Remove `schema_bootstrap.py` entirely and consolidate DB initialization into `alembic upgrade head`.

### [Severity: Low] CRL-13 — Untyped Frontend Errors
**Context:** `frontend/lib/api/client.ts` throws generic `Error` with body text. Transients (`502/503`) aren't retried. 
**Remediation:** Create a typed `ApiError`, inject exponential backoffs for 5XX, and cleanly trap 401s to bounce to login.

---

## 3. Pending Architectural Decision Records (ADRs)

The following open items (from `OI-01` to `OI-06`) require formal technical documentation before scale:

1. **State Persistence Limitations:** When does the projected load necessitate migrating off SQLite WAL to PostgreSQL?
2. **In-process Worker vs Celery:** Current workers use `asyncio` inside the ASGI process. Does the queue stability now require Celery/Redis?
3. **Auth Model (Stateless vs Stateful):** To solve INV-AUTH-02, a decision between a Redis Token Blocklist vs DB-backed sessions must be made.

*End of Pending Report*