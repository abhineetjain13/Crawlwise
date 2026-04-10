# Web Crawling Platform - Deep-Tissue Architectural Audit
## Software Engineering Principles & System Architecture Review

**Audit Date:** April 10, 2026  
**Auditor Role:** Principal Software Architect & Systems Engineer  
**Scope:** Backend FastAPI + Celery + Playwright + PostgreSQL  
**Focus:** First Principles violations, SOLID principles, architectural patterns, production stability

---

## 1. Executive Summary

**Production Readiness Score: 3/10** (downgraded from 4/10 after principles review)

This platform demonstrates solid engineering fundamentals but contains **critical architectural redlines** that will cause system crashes, security breaches, and operational failures at scale. The codebase shows evidence of rapid prototyping with insufficient hardening for production workloads processing 100k+ URLs.

### Key Findings:
- **CRITICAL:** Hardcoded API keys and secrets committed to version control (.env file)
- **CRITICAL:** Browser pool lacks robust zombie process cleanup under hard-kill scenarios
- **CRITICAL:** SSRF protection exists but DNS rebinding attacks are possible
- **HIGH:** Database connection pool undersized for concurrent workloads (5 connections)
- **HIGH:** No connection pool health checks or pre-ping configured
- **HIGH:** Celery worker lifecycle management has race conditions
- **MEDIUM:** Redis fail-open pattern can cause state inconsistencies
- **MEDIUM:** Disk I/O operations block async event loop in critical paths

---

## 2. Critical Architectural Redlines

### 2.1 **SECURITY BREACH: Hardcoded Secrets in Version Control**

**File:** `.env` (lines 1-22)  
**Severity:** CRITICAL - Production Blocker

```
ANTHROPIC_API_KEY=sk-ant-api03-IO0ZFTYRE2inL5TaFAX6GamxXfoLB54yJCE...
FIRECRAWL_API_KEY=fc-1b8416c1e7e74db0850eaa34602f5934
NVIDIA_API_KEY=nvapi-6QDITrSZ9HbAqitIm-MIbHNNwvX237UH5aLFhbomZQ0...
GROQ_API_KEY=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
```

**Impact:**
- All API keys are exposed in plaintext in the repository
- Anyone with repository access can extract and abuse these credentials
- Violates SOC 2, PCI-DSS, and GDPR compliance requirements
- Default admin credentials (`admin@admin.com` / `YourSecurePassword123!`) are hardcoded

**Evidence of Awareness:**
- `backend/app/core/config.py:82-110` contains security checks for default secrets
- However, the `.env` file itself is tracked in git (should be in `.gitignore`)

---

### 2.2 **SYSTEM CRASH: Browser Pool Zombie Process Risk**

**Files:**
- `backend/app/services/acquisition/browser_client.py:318-350`
- `backend/app/tasks.py:20-22`

**Severity:** CRITICAL - Will cause memory exhaustion

**Issue:** Browser pool cleanup relies on graceful shutdown signals. Under hard-kill scenarios (OOM killer, SIGKILL, container termination), browsers become zombie processes.

**Code Analysis:**
```python
# browser_client.py:318-350
try:
    context = await asyncio.wait_for(
        browser.new_context(...),
        timeout=15.0
    )
except (TimeoutError, PlaywrightError):
    await _evict_browser(_browser_pool_key(launch_profile, proxy), browser)
    # FIX APPLIED: Retry logic exists, but...
```

**Missing Safeguards:**
1. No PID tracking for spawned browser processes
2. No orphan process cleanup on worker restart
3. `shutdown_browser_pool_sync()` (line 2064) uses `asyncio.run()` which can fail if event loop is already running
4. Browser pool state is per-PID (`_BrowserPoolState.pid`) but doesn't clean up child processes from previous PIDs

**Failure Scenario:**
```
1. Celery worker spawns 6 browsers (pool max)
2. Worker receives SIGKILL (OOM or manual kill -9)
3. Python process dies, but 6 Chromium processes remain
4. New worker starts, spawns 6 more browsers
5. Repeat 100 times = 600 zombie Chromium processes
6. System OOM crash
```

---

### 2.3 **SECURITY: SSRF Protection Incomplete (DNS Rebinding)**

**File:** `backend/app/services/url_safety.py:45-80`  
**Severity:** CRITICAL - Security vulnerability

**Current Protection:**
```python
async def validate_public_target(url: str) -> ValidatedTarget:
    # ... validates hostname resolves to public IP
    resolved_ips = await _resolve_host_ips(hostname, port)
    for ip_text in resolved_ips:
        _raise_if_non_public_ip(ip_value, hostname)
```

**Vulnerability:** Time-of-Check-Time-of-Use (TOCTOU) DNS Rebinding

**Attack Scenario:**
```
1. Attacker controls DNS for evil.com
2. Initial validation: evil.com → 1.2.3.4 (public IP) ✓
3. DNS TTL expires (1 second)
4. Browser fetch: evil.com → 127.0.0.1 (localhost) ✗
5. Attacker reads AWS metadata, internal services, etc.
```

**Missing Safeguards:**
1. No DNS pinning after validation
2. No re-validation before browser navigation
3. Browser route guard (`_guard_non_public_request`) validates URLs but doesn't prevent DNS rebinding
4. No check for AWS metadata endpoints (`169.254.169.254`)

**Evidence:**
- `browser_client.py:395-415` has route-level blocking, but it's reactive, not preventive
- `url_safety.py:14` blocks `metadata.google.internal` but not AWS metadata IP

---

### 2.4 **SYSTEM CRASH: Database Connection Pool Exhaustion**

**File:** `backend/app/core/database.py:22-23`  
**Severity:** HIGH - Will cause request failures at scale

```python
if not _database_url.drivername.startswith("sqlite"):
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10
```

**Issue:** Total connection limit = 15 connections for entire application

**Failure Math:**
```
- 1 FastAPI worker = 1 connection per request
- 10 concurrent API requests = 10 connections
- 1 Celery worker processing batch = 1-5 connections
- 1 background task (stale run recovery) = 1 connection
Total: 12-16 connections → Pool exhausted
```

**Missing Configuration:**
1. No `pool_pre_ping=True` (dead connections cause errors)
2. No `pool_recycle` (connections held indefinitely)
3. No `pool_timeout` (requests hang forever when pool exhausted)
4. No connection leak detection

**Evidence of Problem:**
- `_batch_runtime.py:45-60` uses `async with SessionLocal()` correctly
- But `crawl_service.py:180-195` has multiple nested session operations that can hold connections

---

### 2.5 **RACE CONDITION: Celery Worker Lifecycle**

**File:** `backend/app/tasks.py:14-22`  
**Severity:** HIGH - Causes worker crashes

```python
@worker_process_init.connect
def _worker_process_init(**_kwargs) -> None:
    prepare_browser_pool_for_worker_process()

@worker_process_shutdown.connect
def _worker_process_shutdown(**_kwargs) -> None:
    shutdown_browser_pool_sync()
```

**Issue:** `shutdown_browser_pool_sync()` uses `asyncio.run()` which fails if event loop exists

**Code Path:**
```python
# browser_client.py:2064-2069
def shutdown_browser_pool_sync() -> None:
    try:
        asyncio.run(_shutdown_browser_pool())  # ← FAILS if loop running
    except RuntimeError:
        prepare_browser_pool_for_worker_process()  # ← Wrong recovery
```

**Failure Scenario:**
```
1. Celery worker receives shutdown signal
2. Worker has active async task with running event loop
3. shutdown_browser_pool_sync() calls asyncio.run()
4. RuntimeError: "Cannot run event loop while another loop is running"
5. Exception handler calls prepare_browser_pool_for_worker_process()
6. This CREATES a new pool instead of cleaning up
7. Browsers leak
```

---

### 2.6 **DATA LOSS: Redis Fail-Open Pattern**

**File:** `backend/app/core/redis.py:35-75`  
**Severity:** MEDIUM - Causes state inconsistencies

```python
async def redis_fail_open(operation, *, default, operation_name):
    if not redis_is_enabled():
        return default
    try:
        return await operation(get_redis())
    except Exception as exc:
        _temporarily_disable_redis(exc)
        return default  # ← Silent failure
```

**Issue:** Redis failures return default values without alerting the application

**Failure Scenario:**
```
1. Crawl run stores state in Redis (distributed lock, progress tracking)
2. Redis connection fails mid-operation
3. System silently falls back to local state
4. Two workers process same URL (no distributed lock)
5. Duplicate records inserted
6. No error logged to user
```

**Missing Safeguards:**
1. No distinction between "Redis disabled" vs "Redis failed"
2. No metrics/alerts on fail-open events
3. No graceful degradation strategy (should pause crawls, not continue)

---

## 3. Technical Debt & Scaling Bottlenecks

### 3.1 **Write Amplification: CrawlLog Table**

**File:** `backend/app/models/crawl.py:40-47`  
**Severity:** HIGH - Database performance degradation

```python
class CrawlLog(Base):
    __tablename__ = "crawl_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(...), index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), ...)
```

**Issue:** No composite index on `(run_id, created_at)` for log queries

**Scaling Problem:**
```
- 100k URLs × 50 log entries per URL = 5M rows
- Query: "SELECT * FROM crawl_logs WHERE run_id = ? ORDER BY created_at"
- Without composite index: Full table scan on 5M rows
- Query time: 2-5 seconds (blocks API response)
```

**Missing Indexes:**
1. `(run_id, created_at)` for time-ordered log retrieval
2. `(run_id, level)` for filtered log queries
3. No partitioning strategy for log retention

---

### 3.2 **Memory Bloat: In-Memory HTML Storage**

**File:** `backend/app/services/acquisition/browser_client.py:600-650`  
**Severity:** MEDIUM - Worker OOM crashes

**Issue:** Traversal mode collects all pages in memory before writing to disk

```python
# Pagination collects HTML in memory
combined_html = traversal_result.html  # ← Can be 50MB+ for 100 pages
result.html = combined_html
# ... later ...
await asyncio.to_thread(path.write_text, result.html, encoding="utf-8")
```

**Failure Scenario:**
```
- Crawl 100 pages × 500KB per page = 50MB per URL
- 10 concurrent URLs = 500MB memory
- Worker has 1GB limit → OOM kill
```

**Missing Optimization:**
1. No streaming write to disk during pagination
2. No memory limit checks before collecting pages
3. No compression of HTML before storage

---

### 3.3 **Blocking I/O in Async Context**

**File:** `backend/app/services/acquisition/acquirer.py:450-470`  
**Severity:** MEDIUM - Throughput degradation

**Issue:** Disk writes block the async event loop

```python
# acquirer.py (original code before FIX comments)
path.write_text(result.html, encoding="utf-8")  # ← Blocks event loop
_write_network_payloads(run_id, url, result.network_payloads)  # ← Blocks
_write_diagnostics(run_id, url, result, path, diagnostics_path)  # ← Blocks
```

**Impact:**
- Each disk write blocks for 10-50ms
- 3 writes per URL = 30-150ms blocked
- 100 concurrent requests = event loop stalls
- API latency spikes to 5+ seconds

**Partial Fix Applied:**
```python
# Lines 450-470 show asyncio.to_thread() wrappers
await asyncio.to_thread(_write_network_payloads, ...)
```
**Status:** Fix is present in code but needs verification in all paths

---

### 3.4 **Hot Row: LLM Config Reads**

**File:** `backend/app/services/llm_runtime.py:125-150`  
**Severity:** MEDIUM - Database contention

**Issue:** Every extraction reads LLM config from database

```python
# Implied from llm_runtime.py structure
config = await session.execute(
    select(LLMConfig).where(LLMConfig.task_type == task_type)
)
```

**Scaling Problem:**
```
- 100k URLs × 3 LLM calls per URL = 300k config reads
- All reads hit same row (hot row contention)
- PostgreSQL row-level lock causes serialization
- Throughput: 100 reads/sec max
```

**Missing Optimization:**
1. No application-level caching of LLM configs
2. No read replicas for config queries
3. No config versioning (changes require restart)

---

### 3.5 **Unbounded Concurrency**

**File:** `backend/app/services/pipeline_config.py` (implied)  
**Severity:** MEDIUM - Resource exhaustion

**Issue:** No global concurrency limits enforced at system level

**Evidence:**
- `_batch_runtime.py:150` has `url_batch_concurrency` setting
- But it's per-run, not system-wide
- No enforcement of `max_records` at database level (only application level)

**Failure Scenario:**
```
- User submits 10 batch jobs with 10k URLs each
- Each job spawns 10 concurrent workers (url_batch_concurrency)
- Total: 100 concurrent browser instances
- System: 16 CPU cores → thrashing
```

---

### 3.6 **Proxy Credential Leakage**

**File:** `backend/app/services/acquisition/acquirer.py:50-80`  
**Severity:** MEDIUM - Security & compliance

**Issue:** Proxy credentials logged in diagnostics

```python
_SENSITIVE_KEY_TOKENS = (
    "authorization", "api_key", "token", "secret", "password", ...
)
# But proxy URLs like "http://user:pass@proxy.com" are logged
```

**Evidence:**
- `acquirer.py:50` defines sensitive token patterns
- But proxy URLs in diagnostics contain embedded credentials
- `browser_client.py:300` logs proxy usage without redaction

---

## 4. Implementation Roadmap for Coding Agent

### Phase 1: Critical Security Fixes (P0 - Deploy Immediately)

#### Task 1.1: Remove Hardcoded Secrets
```
- File: .env
- Action: Add .env to .gitignore
- Action: Create .env.example with placeholder values
- Action: Rotate all exposed API keys (Anthropic, Groq, NVIDIA, etc.)
- Action: Document secret management in README.md
- Validation: Verify .env not in git history (use git-filter-repo if needed)
```

#### Task 1.2: Fix DNS Rebinding SSRF
```
- File: backend/app/services/url_safety.py
- Action: Add AWS metadata IP to blocked list: "169.254.169.254"
- Action: Implement DNS pinning: Store resolved IPs in ValidatedTarget
- Action: Add re-validation before browser navigation
- File: backend/app/services/acquisition/browser_client.py
- Action: Pass resolved IPs to browser, block DNS lookups
- Validation: Test with DNS rebinding attack simulation
```

#### Task 1.3: Add Database Connection Health Checks
```
- File: backend/app/core/database.py
- Action: Add pool_pre_ping=True to engine kwargs
- Action: Add pool_recycle=3600 (1 hour)
- Action: Add pool_timeout=30 (fail fast)
- Action: Increase pool_size to 20, max_overflow to 30
- Validation: Load test with 50 concurrent requests
```

---

### Phase 2: Browser Pool Hardening (P0 - Critical Stability)

#### Task 2.1: Implement PID Tracking
```
- File: backend/app/services/acquisition/browser_client.py
- Action: Add browser_pids: dict[str, int] to _BrowserPoolState
- Action: Store browser.process.pid when launching
- Action: On worker init, kill orphaned PIDs from previous workers
- Code:
  def _kill_orphaned_browsers():
      for pid in browser_pids.values():
          try:
              os.kill(pid, signal.SIGTERM)
          except ProcessLookupError:
              pass
```

#### Task 2.2: Fix Shutdown Race Condition
```
- File: backend/app/tasks.py
- Action: Replace shutdown_browser_pool_sync() with proper async cleanup
- Code:
  @worker_process_shutdown.connect
  def _worker_process_shutdown(**_kwargs):
      loop = asyncio.get_event_loop()
      if loop.is_running():
          loop.create_task(_shutdown_browser_pool())
      else:
          asyncio.run(_shutdown_browser_pool())
```

#### Task 2.3: Add Browser Process Monitoring
```
- File: backend/app/services/acquisition/browser_client.py
- Action: Add health check to verify browser processes are alive
- Action: Kill and evict browsers with dead processes
- Code:
  def _browser_process_alive(browser) -> bool:
      pid = getattr(browser, '_pid', None)
      if not pid:
          return True
      try:
          os.kill(pid, 0)  # Signal 0 checks existence
          return True
      except OSError:
          return False
```

---

### Phase 3: Database Optimization (P1 - Performance)

#### Task 3.1: Add Composite Indexes
```
- File: Create new Alembic migration
- Action: Add index on crawl_logs(run_id, created_at)
- Action: Add index on crawl_logs(run_id, level)
- Action: Add index on crawl_records(run_id, created_at)
- SQL:
  CREATE INDEX idx_crawl_logs_run_time ON crawl_logs(run_id, created_at DESC);
  CREATE INDEX idx_crawl_logs_run_level ON crawl_logs(run_id, level);
```

#### Task 3.2: Implement LLM Config Caching
```
- File: backend/app/services/llm_runtime.py
- Action: Add TTLCache for LLM configs (5 minute TTL)
- Code:
  from cachetools import TTLCache
  _llm_config_cache = TTLCache(maxsize=100, ttl=300)
  
  async def get_llm_config(task_type: str):
      if task_type in _llm_config_cache:
          return _llm_config_cache[task_type]
      config = await _fetch_from_db(task_type)
      _llm_config_cache[task_type] = config
      return config
```

#### Task 3.3: Add Connection Pool Monitoring
```
- File: backend/app/core/database.py
- Action: Add metrics endpoint for pool stats
- Code:
  def get_pool_stats():
      return {
          "size": engine.pool.size(),
          "checked_in": engine.pool.checkedin(),
          "checked_out": engine.pool.checkedout(),
          "overflow": engine.pool.overflow(),
      }
```

---

### Phase 4: Redis Reliability (P1 - Data Consistency)

#### Task 4.1: Add Redis Failure Alerts
```
- File: backend/app/core/redis.py
- Action: Replace silent fail-open with logged warnings
- Action: Increment metrics counter on Redis failures
- Code:
  async def redis_fail_open(...):
      try:
          return await operation(get_redis())
      except Exception as exc:
          logger.error("Redis operation failed: %s", operation_name, exc_info=True)
          incr("redis_failure_total")
          return default
```

#### Task 4.2: Implement Circuit Breaker
```
- File: backend/app/core/redis.py
- Action: Add circuit breaker pattern (open after 5 failures)
- Action: Auto-recover after 60 seconds
- Library: Use pybreaker or implement custom
```

---

### Phase 5: Memory & I/O Optimization (P2 - Scalability)

#### Task 5.1: Stream HTML to Disk
```
- File: backend/app/services/acquisition/browser_client.py
- Action: Write each page to disk immediately during pagination
- Action: Store file paths instead of HTML in memory
- Code:
  async def _collect_paginated_html_streaming(page, ...):
      page_files = []
      for page_num in range(max_pages):
          html = await page.content()
          path = f"{run_id}_page_{page_num}.html"
          await asyncio.to_thread(Path(path).write_text, html)
          page_files.append(path)
      return page_files
```

#### Task 5.2: Add Memory Limit Checks
```
- File: backend/app/services/acquisition/browser_client.py
- Action: Check available memory before collecting pages
- Action: Fail fast if memory < 500MB
- Code:
  import psutil
  def _check_memory_available():
      mem = psutil.virtual_memory()
      if mem.available < 500 * 1024 * 1024:
          raise MemoryError("Insufficient memory for traversal")
```

#### Task 5.3: Verify All Disk I/O is Async
```
- File: backend/app/services/acquisition/acquirer.py
- Action: Audit all Path.write_text() calls
- Action: Wrap in asyncio.to_thread() if not already
- Validation: Search codebase for "\.write_text\(" without "to_thread"
```

---

### Phase 6: Concurrency Controls (P2 - Resource Management)

#### Task 6.1: Add System-Wide Concurrency Limit
```
- File: backend/app/core/config.py
- Action: Add SYSTEM_MAX_CONCURRENT_URLS setting
- File: backend/app/services/_batch_runtime.py
- Action: Implement semaphore to enforce global limit
- Code:
  _global_url_semaphore = asyncio.Semaphore(SYSTEM_MAX_CONCURRENT_URLS)
  
  async def _process_single_url(...):
      async with _global_url_semaphore:
          # existing logic
```

#### Task 6.2: Add Database-Level max_records Enforcement
```
- File: backend/app/models/crawl.py
- Action: Add CHECK constraint on CrawlRun
- SQL:
  ALTER TABLE crawl_runs ADD CONSTRAINT check_max_records
  CHECK (
      (settings->>'max_records')::int IS NULL OR
      (SELECT COUNT(*) FROM crawl_records WHERE run_id = id) <= (settings->>'max_records')::int
  );
```

---

### Phase 7: Observability (P2 - Operations)

#### Task 7.1: Add Structured Logging
```
- File: backend/app/core/telemetry.py
- Action: Replace print() with structured JSON logs
- Action: Add correlation IDs to all log entries
- Library: Use structlog
```

#### Task 7.2: Add Prometheus Metrics
```
- File: Create backend/app/core/metrics.py
- Action: Export Prometheus metrics endpoint
- Metrics:
  - crawl_runs_total{status}
  - browser_pool_size
  - database_connections_active
  - redis_failures_total
  - acquisition_duration_seconds
```

#### Task 7.3: Add Health Check Endpoint
```
- File: backend/app/main.py
- Action: Enhance /api/health to check dependencies
- Code:
  @app.get("/api/health")
  async def health():
      checks = {
          "database": await check_database(),
          "redis": await check_redis(),
          "browser_pool": check_browser_pool(),
      }
      status = "healthy" if all(checks.values()) else "degraded"
      return {"status": status, "checks": checks}
```

---

### Phase 8: Security Hardening (P2 - Defense in Depth)

#### Task 8.1: Redact Proxy Credentials in Logs
```
- File: backend/app/services/acquisition/acquirer.py
- Action: Add proxy URL sanitization to _REDACTED logic
- Code:
  def _redact_proxy_url(url: str) -> str:
      parsed = urlparse(url)
      if parsed.username:
          return f"{parsed.scheme}://***:***@{parsed.hostname}:{parsed.port}"
      return url
```

#### Task 8.2: Add Rate Limiting
```
- File: backend/app/main.py
- Action: Add rate limiting middleware
- Library: Use slowapi
- Config: 100 requests/minute per IP
```

#### Task 8.3: Add Request Size Limits
```
- File: backend/app/main.py
- Action: Add max request body size (10MB)
- Code:
  app.add_middleware(
      RequestSizeLimitMiddleware,
      max_upload_size=10 * 1024 * 1024
  )
```

---

## 5. Testing & Validation Checklist

### Load Testing
- [ ] 100 concurrent API requests (database pool)
- [ ] 1000 URLs in single batch (memory limits)
- [ ] 10 simultaneous batch jobs (system concurrency)
- [ ] Browser pool under worker restarts (zombie processes)

### Security Testing
- [ ] DNS rebinding attack simulation
- [ ] SSRF attempts (localhost, 169.254.169.254, private IPs)
- [ ] Proxy credential leakage in logs
- [ ] API key exposure in error messages

### Failure Testing
- [ ] Redis connection loss during crawl
- [ ] Database connection loss during crawl
- [ ] Worker SIGKILL during browser operation
- [ ] Disk full during HTML write
- [ ] OOM kill during pagination

### Performance Benchmarks
- [ ] Crawl 10k URLs: < 30 minutes
- [ ] API response time: p95 < 500ms
- [ ] Database query time: p99 < 100ms
- [ ] Memory usage: < 2GB per worker

---

## 6. Compliance & Production Readiness

### Required Before Production
- [ ] Secrets management (Vault, AWS Secrets Manager)
- [ ] Audit logging (all API calls, crawl operations)
- [ ] Data retention policy (log cleanup, artifact archival)
- [ ] Backup & disaster recovery plan
- [ ] Incident response runbook
- [ ] Monitoring & alerting (PagerDuty integration)
- [ ] Security review (penetration testing)
- [ ] Performance baseline (SLAs defined)

### Recommended Enhancements
- [ ] Multi-region deployment
- [ ] Read replicas for database
- [ ] CDN for artifact delivery
- [ ] Kubernetes autoscaling
- [ ] Blue-green deployment pipeline
- [ ] Chaos engineering tests

---

## 7. Conclusion

This platform has a solid foundation but requires **immediate attention** to critical security and stability issues before production deployment. The roadmap above provides a clear path to production-grade reliability.

**Estimated Effort:**
- Phase 1 (Security): 2-3 days
- Phase 2 (Browser Pool): 3-5 days
- Phase 3 (Database): 2-3 days
- Phase 4 (Redis): 1-2 days
- Phase 5 (Memory/I/O): 3-4 days
- Phase 6 (Concurrency): 2-3 days
- Phase 7 (Observability): 3-5 days
- Phase 8 (Security): 2-3 days

**Total: 18-28 days** for full production hardening.

**Priority Order:**
1. Remove hardcoded secrets (Day 1)
2. Fix SSRF vulnerability (Day 1-2)
3. Harden browser pool (Day 2-5)
4. Database optimization (Day 6-8)
5. Everything else (Day 9-28)

---

**End of Audit Report**
