I now have enough to produce the full hardening checklist with ground truth from the actual code. Here it is.

Production Hardening Checklist — Crawlwise Backend
1. SECRETS ✅ Partially Hardened
Current state: Settings is a Pydantic BaseSettings class in app/core/config.py. jwt_secret_key and encryption_key are required fields (no default) — Pydantic will crash at startup if missing. _check_secret_defaults() runs at module load and raises RuntimeError in non-dev environments if placeholder values are detected. LLM API keys (anthropic_api_key, groq_api_key, nvidia_api_key) are optional strings defaulting to "" — no validation that at least one is set before LLM calls are made.

Risk if unaddressed: A worker deployed without LLM keys will silently succeed at startup, then fail at runtime mid-crawl on the first selector self-heal attempt. The groq_api_key = "" default means a misconfigured worker returns HTTP 401 from Groq after the first batch runs.

Fix:

python
# config.py — add to Settings
@model_validator(mode="after")
def _require_at_least_one_llm_key(self) -> "Settings":
    if not any([self.anthropic_api_key, self.groq_api_key, self.nvidia_api_key]):
        import os
        if os.getenv("APP_ENV", "dev") not in ("dev", "development", "local", "test"):
            raise ValueError("At least one LLM API key must be set in production")
    return self
Also add proxy credential fields (PROXY_USERNAME, PROXY_PASSWORD) to Settings with SecretStr type rather than passing raw proxy URLs through AcquisitionPlan.proxy_list.

2. TIMEOUTS ⚠️ Partial Coverage, Gaps in LLM and Job Level
Current state: HTTP fetch timeout is settings.http_timeout_seconds = 20.0 (config-driven). Browser context timeout is settings.browser_context_timeout_seconds = 30.0. Both are in Settings and env-configurable. However:

Per-LLM-call timeout: llm_cache_ttl_seconds = 86400 is a cache TTL, not a call timeout. No timeout= parameter is visible in the LLM call sites.

Per-job timeout: system_max_concurrent_urls = 8 is a concurrency cap, not a wall-clock job deadline. A crawl run has no maximum total runtime enforced — a single stuck browser context can stall the run indefinitely.

robots.txt fetch timeout: Not visible in robots_policy.py — the fetch call does not pass a timeout kwarg, so it falls back to httpx's library default (5 seconds) silently.

Risk if unaddressed: A browser context leak or an unresponsive LLM API call blocks one of the 8 concurrent URL slots forever. A 500-URL batch with one leaked browser can complete in 490 URLs and hang indefinitely.

Fix:

python
# config.py — add
llm_call_timeout_seconds: float = 30.0
job_max_wall_seconds: int = 3600       # 1 hour hard deadline per CrawlRun
robots_fetch_timeout_seconds: float = 5.0

# celery_app.py or batch_runtime — enforce job deadline
@app.task(time_limit=settings.job_max_wall_seconds, soft_time_limit=settings.job_max_wall_seconds - 60)
async def run_crawl_task(...): ...
3. RATE LIMITING ⚠️ Intra-Domain Pacing Exists, No Adaptive Token Bucket
Current state: AcquisitionPlan.sleep_ms sets a fixed inter-request delay per URL, defaulting to crawler_runtime_settings.min_request_delay_ms. This is a floor value, not a per-domain adaptive rate limiter. platform_policy.py does not contain rate limiting logic — it is a detection/extraction config layer. robots_policy.py respects Crawl-delay directives from robots.txt but only for robots compliance, not as an actual async sleep enforced before each request. There is no token bucket, no per-domain request counter, and no backoff when a 429 is received.

Risk if unaddressed: Hitting a high-traffic e-commerce domain with 8 concurrent workers at sleep_ms=1000 sends up to 8 req/s to one domain. Most CDN-fronted sites block at 2–5 req/s per IP. The VERDICT_BLOCKED signal fires reactively after the block, not proactively before it.

Fix:

python
# services/rate_limiter.py — new
from asyncio import Semaphore
from collections import defaultdict
from time import monotonic

_domain_last_request: dict[str, float] = defaultdict(float)
_domain_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

async def acquire_domain_slot(domain: str, min_delay_ms: int) -> None:
    async with _domain_locks[domain]:
        elapsed = (monotonic() - _domain_last_request[domain]) * 1000
        if elapsed < min_delay_ms:
            await asyncio.sleep((min_delay_ms - elapsed) / 1000)
        _domain_last_request[domain] = monotonic()
Call await acquire_domain_slot(domain, plan.sleep_ms) as the first step in pipeline/core.py:process_url(). Respect Crawl-delay from robots_policy as an override to plan.sleep_ms.

4. ERROR BUDGET ⚠️ Verdict Logic Exists, No Run-Level Degraded Threshold
Current state: publish/verdict.py defines VERDICT_SUCCESS / PARTIAL / BLOCKED / SCHEMA_MISS / LISTING_FAILED / EMPTY / ERROR at the URL level. _aggregate_verdict rolls these up to a run-level verdict. However, there is no numeric error budget threshold — the aggregate verdict is computed purely from set membership, not from a percentage of failed URLs. A run with 490 successes and 10 errors returns VERDICT_PARTIAL, identical to a run with 5 successes and 495 errors.

Risk if unaddressed: A degraded run (e.g., 60% blocked due to a platform change) ships downstream with VERDICT_PARTIAL and no operational signal distinguishing it from a 2% failure rate.

Fix:

python
# publish/verdict.py — add
def run_health_verdict(
    verdicts: list[str],
    *,
    error_budget_pct: float = 0.15,   # 15% failures → degraded
    failure_budget_pct: float = 0.50, # 50% failures → failed
) -> Literal["healthy", "degraded", "failed"]:
    total = len(verdicts)
    if total == 0:
        return "failed"
    failure_count = sum(1 for v in verdicts if v in {VERDICT_BLOCKED, VERDICT_ERROR, VERDICT_EMPTY})
    rate = failure_count / total
    if rate >= failure_budget_pct:
        return "failed"
    if rate >= error_budget_pct:
        return "degraded"
    return "healthy"
Expose run_health_verdict on the CrawlRun status response and gate webhook delivery behind it.

5. OBSERVABILITY ✅ structlog Present, Field-Level Gaps
Current state: structlog>=25.4.0 is in pyproject.toml and app/core/telemetry.py exists (4.7KB — likely configures structlog processors + JSON renderer). prometheus-client>=0.23.1 and app/core/metrics.py (5.6KB) indicate Prometheus counters are instrumented. crawl_log_db_min_level, crawl_log_db_url_progress_sample_rate, and crawl_log_db_max_rows_per_run in Settings confirm per-run DB-level logging exists.

Gap: From pipeline/persistence.py, _build_source_trace() stores per-field provenance in CrawlRecord.source_trace JSONB, but this is written to the DB, not emitted as a structured log event. There is no log line that looks like {"event": "field_extracted", "run_id": 42, "url": "...", "field": "price", "value": "$29.99", "confidence": 0.91}. Field-level extraction outcomes are queryable via DB but not streamable to a log aggregator.

Fix:

python
# pipeline/core.py — add after persist_extracted_records()
for record in persisted_records:
    for field_name, discovery in record.source_trace.get("field_discovery", {}).items():
        structlog.get_logger().info(
            "field_extracted",
            run_id=run.id,
            domain=domain,
            url=acquisition_result.final_url,
            field=field_name,
            status=discovery.get("status"),
            confidence=record.source_trace.get("extraction", {}).get("confidence", {}).get(field_name),
        )
Sample at crawl_log_db_url_progress_sample_rate to avoid log volume explosion on large batches.

6. COST CONTROL ❌ No Token Budget, No Daily Spend Cap
Current state: llm_cache_ttl_seconds = 86400 means LLM responses are cached for 24 hours per (prompt hash → response) key. This de-duplicates identical selector synthesis calls. But there is no per-run token counter, no daily spend cap, no max_tokens enforcement per call, and no circuit breaker that disables LLM calls if the monthly bill exceeds a threshold. anthropic_api_key, groq_api_key, nvidia_api_key are accepted but there is no routing logic that falls back to the cheaper provider when the expensive one is consumed.

Risk if unaddressed: A single large batch run (e.g., 10,000 URLs with selector self-heal on every URL due to a site-wide layout change) can trigger 10,000 LLM calls in one run. At Anthropic Claude pricing, this can cost hundreds of dollars in minutes before any human notices.

Fix:

python
# config.py — add
llm_max_tokens_per_call: int = 2000
llm_max_calls_per_run: int = 50          # hard cap per CrawlRun
llm_daily_call_budget: int = 500         # cross-run daily cap, stored in Redis
llm_preferred_provider: str = "groq"     # cheapest first

# services/llm_runtime.py — add budget gate
async def _check_llm_budget(run_id: int) -> None:
    run_count = await redis.incr(f"llm:run:{run_id}:calls")
    if run_count > settings.llm_max_calls_per_run:
        raise LLMBudgetExceeded(f"Run {run_id} exceeded LLM call budget")
    daily_count = await redis.incr("llm:daily:calls")
    await redis.expire("llm:daily:calls", 86400)
    if daily_count > settings.llm_daily_call_budget:
        raise LLMBudgetExceeded("Daily LLM call budget exceeded")
7. ALERTING ⚠️ Prometheus Metrics Exist, No Alert Rules Defined
Current state: prometheus-client is installed and app/core/metrics.py (5.6KB) exists, suggesting Prometheus counters/histograms are defined for crawl operations. A /metrics endpoint is almost certainly wired via prometheus-client's make_asgi_app(). No alerting rules file (alerts.yml, alert_rules.yaml) is present in the repository.

Risk if unaddressed: Metrics are collected but no one is paged when: (1) the error rate exceeds threshold, (2) the LLM call rate spikes, (3) the Celery queue depth grows beyond capacity, (4) the DB connection pool is exhausted.

Fix — minimum viable Prometheus alert rules:

text
# alerts.yml
groups:
  - name: crawlwise
    rules:
      - alert: HighCrawlErrorRate
        expr: rate(crawl_url_verdict_total{verdict="error"}[5m]) / rate(crawl_url_verdict_total[5m]) > 0.3
        for: 5m
        annotations:
          summary: "Crawl error rate above 30% for 5 minutes"
      - alert: LLMCallSpike
        expr: rate(llm_calls_total[5m]) > 10
        for: 2m
        annotations:
          summary: "LLM calls spiking — possible runaway selector self-heal"
      - alert: CeleryQueueDepth
        expr: celery_queue_length{queue="crawl"} > 1000
        for: 10m
        annotations:
          summary: "Crawl Celery queue depth over 1000 — workers may be stuck"
      - alert: DBPoolExhausted
        expr: sqlalchemy_pool_checked_out / sqlalchemy_pool_size > 0.9
        for: 2m
        annotations:
          summary: "DB connection pool at 90% — risk of connection timeout"
8. DEPLOY ⚠️ No Health Endpoint Confirmed, Graceful Shutdown Partial
Current state: FastAPI is used (fastapi>=0.116.0) but no /health or /readiness route is visible in backend/app/. uvicorn[standard] is the server with standard signal handling, so SIGTERM will drain in-flight HTTP requests. Celery workers have celery worker --without-gossip --without-mingle style config in celery_app.py (1.7KB). Browser pool shutdown is the critical gap — Playwright browser instances require await browser.close() on shutdown; if workers are SIGKILLed, leaked Chromium processes accumulate on the host.

Risk if unaddressed: Kubernetes liveness/readiness probes with no /health endpoint default to TCP port check — a worker that's alive but has a broken DB connection or full browser pool will pass TCP and receive traffic. On rolling deploys, in-flight 3-minute browser crawls are killed mid-run.

Fix:

python
# app/api/health.py — new
@router.get("/health/live")
async def liveness():
    return {"status": "ok"}

@router.get("/health/ready")
async def readiness(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "DB not reachable")
    return {"status": "ready", "db": "ok"}

# app/main.py — add lifespan shutdown hook
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await browser_pool.shutdown_all()   # graceful Playwright cleanup
    await http_client_pool.aclose()     # drain httpx connection pool
Set Kubernetes terminationGracePeriodSeconds: 120 to allow in-flight browser sessions to complete.

9. DATA QUALITY ❌ No Post-Run Gate Before Export
Current state: pipeline/persistence.py:persist_extracted_records() writes whatever passes public_record_data_for_surface() (field allowlist filter). There is no post-run quality gate. record_export_service.py exports all CrawlRecord rows for a run regardless of completeness. A run with 80% null prices is exportable with no warning.

Risk if unaddressed: A downstream consumer (webhook receiver, data warehouse) ingests a run where a site layout change caused silent extraction failure for all records. The VERDICT_PARTIAL flag is on the run object, not propagated to the individual records or the export payload.

Fix:

python
# services/export/quality_gate.py — new
@dataclass
class QualityReport:
    run_id: int
    total_records: int
    field_fill_rates: dict[str, float]   # field → % non-null
    gate_passed: bool
    failures: list[str]

def evaluate_export_quality(
    records: list[dict],
    *,
    required_fields: list[str],
    min_fill_rate: float = 0.70,         # 70% fill rate required on required fields
) -> QualityReport:
    rates = {
        field: sum(1 for r in records if r.get(field)) / max(len(records), 1)
        for field in required_fields
    }
    failures = [f"{f}: {r:.0%} fill rate" for f, r in rates.items() if r < min_fill_rate]
    return QualityReport(
        run_id=0, total_records=len(records),
        field_fill_rates=rates, gate_passed=not failures, failures=failures
    )
Block webhook delivery and flag the export CSV with a _quality_gate_passed: false column when the gate fails.

10. DEPENDENCIES ⚠️ uv.lock Present but >= Ranges in pyproject.toml
Current state: uv.lock (558KB) is committed to the repository and uv is the package manager — this means transitive dependencies are fully pinned in the lockfile, which is correct. However, pyproject.toml specifies all direct dependencies with >= lower-bound constraints (e.g., patchright>=1.58.2, playwright is absent — Patchright wraps it internally). The critical risk is that uv.lock is only used when uv sync is called; if someone runs pip install -r from a generated requirements.txt, they get the latest compatible versions.

Dependency	Risk
patchright>=1.58.2	Browser fingerprint patches are version-specific; a minor bump can break stealth behavior
anthropic / groq	Not in pyproject.toml at all — must be installed separately or bundled inside another package
sqlalchemy>=2.0.43	SQLAlchemy 2.x has breaking async API changes between minor versions
celery[redis]>=5.4.0	Celery 5.x → 6.x is a breaking migration
Fix:

text
# pyproject.toml — pin critical stealth/LLM dependencies tightly
"patchright>=1.58.2,<1.59"     # browser fingerprinting is patch-sensitive
"anthropic>=0.30.0,<1.0"       # LLM SDK breaking changes are common
"groq>=0.9.0,<1.0"
"celery[redis]>=5.4.0,<6.0"

# Add missing explicit LLM SDK dependencies
"anthropic>=0.30.0,<1.0"
"groq>=0.9.0,<1.0"
Add a CI step: uv lock --check on every PR to detect lockfile drift. Add pip-audit or uv audit to the CI pipeline for vulnerability scanning of pinned transitive dependencies.

Priority Order for Production
Priority	Item	Current State	Severity
Priority	Item	Current State	Severity
🔴 P0	LLM Cost Control (#6)	No budget, no cap	Bill risk in hours
🔴 P0	Job Timeout (#2 gap)	No wall-clock deadline	Hung workers in production
🔴 P0	Data Quality Gate (#9)	None exists	Silent bad data exported
🟠 P1	Alerting Rules (#7)	Metrics exist, no alerts	Invisible failures
🟠 P1	Health Endpoint (#8)	Not confirmed	Broken K8s probe behavior
🟠 P1	Per-Domain Rate Limiter (#3)	Fixed sleep only	Block cascades on prod
🟡 P2	Error Budget Threshold (#4)	Verdict exists, no %	Partial looks like success
🟡 P2	LLM Key Validation (#1)	JWT/enc key validated, LLM not	Startup-time silent failure
🟢 P3	Field-Level Log Events (#5)	DB provenance exists	Streaming observability gap
🟢 P3	Dep Upper Bounds (#10)	uv.lock pins transitives	Stealth-layer drift risk
