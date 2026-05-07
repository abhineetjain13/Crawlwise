Q1 — What Triggers a Batch Run?
Three trigger paths exist, with explicit fallback logic in crawl_service.py:

python
# crawl_service.dispatch_run() L255
async def dispatch_run(session, run):
    if not settings.celery_dispatch_enabled:
        return await _dispatch_run_locally(session, run)   # Path A
    # ... enqueue to Celery ...                             # Path B
    except Exception:
        # Celery failed → fall back to in-process           # Path C (fallback)
        return await _dispatch_run_locally(session, run)
Path A — In-process asyncio task (default when celery_dispatch_enabled=False): _dispatch_run_locally calls _track_local_run_task which wraps _run_with_local_session(run_id) as an asyncio.Task. This is fire-and-forget inside the FastAPI process.

Path B — Celery queue (when celery_dispatch_enabled=True): run is enqueued to Celery with a task ID stored in run.summary["task_id"].

Path C — Silent fallback: if Celery enqueue raises any exception, the code silently falls back to in-process execution and only logs a warning. An operator monitoring Celery queue depth would see no task arrive, while the run still completes — this is a hidden operational blind spot.

The actual execution entry point in all paths is process_run(session, run_id) in _batch_runtime.py. _batch_runtime.py is not a scheduler or queue consumer — it is the execution body. There is no explicit scheduler (APScheduler, cron) in these files; recurring runs would need an external trigger calling dispatch_run.

Q2 — Is crawl_state.py a State Machine or Status Enum Wrapper?
It is a status enum wrapper with no transition enforcement. The full file is 58 lines. It defines:

CrawlStatus enum: PENDING, RUNNING, PAUSED, COMPLETED, FAILED, KILLED, CANCELLED

TERMINAL_STATUSES: frozenset — {COMPLETED, FAILED, KILLED, CANCELLED}

update_run_status(run, status) — sets run.status_value = status with no guard at all

get_control_request / set_control_request — read/write a control_request key from run.summary

There are zero transition guards. The code in _batch_runtime.process_run manually checks if run.status_value in TERMINAL_STATUSES: return and if run.status_value == CrawlStatus.PAUSED: return before proceeding — but these are defensive if checks in the caller, not enforced by update_run_status. Nothing prevents calling update_run_status(run, CrawlStatus.RUNNING) on a COMPLETED run. The illegal transition COMPLETED → RUNNING is currently possible.

Q3 — Does crawl_crud.py Mix DB Queries With Business Logic?
Yes — three categories of leakage:

Business Logic Found	Lines	Should Be In
Domain run profile merging (merge_saved_run_profile, load_domain_run_profile)	L8–10, called in create_run	crawl_service.py or a dedicated run_factory.py
STAGE_ACQUIRE constant imported and written to run.summary during create	L7, L95	_batch_runtime.py (stage tracking belongs to the executor)
repair_target_fields_for_surface validation call during create	L22, L98	crawl_service.py (request validation layer)
Selector rules loading and attaching to the run during create	L104–118	selectors_runtime.py or run_factory.py
Default acquisition_plan computation inlined in create_run	L75–90	settings_view / run configuration layer
crawl_crud.py does have a clean get_run, list_runs, delete_run section, but create_run (the main function, ~120 lines) has absorbed domain logic, field validation, selector attachment, and run profiling. It is not a clean data access layer.

Q4 — Are crawl_events.py Events Persisted, Queued, or In-Memory Only?
Persisted to DB only — no queue, no pub/sub. The events pattern is:

python
# crawl_events.py
async def log_event(session, run_id, level, message):
    event = CrawlEvent(run_id=run_id, level=level, message=message, ...)
    session.add(event)
    # NOTE: no session.commit() here — caller must commit
Events are CrawlEvent ORM rows written to a crawl_events table via SQLAlchemy. Key properties:

No emit to external queue — no Redis pub/sub, no Kafka, no webhook fan-out

No in-memory event bus — no Observer pattern, no callbacks

Commit responsibility on caller — log_event only does session.add(); the calling code in _batch_runtime.py commits explicitly after each log_event call. This means a crash between log_event and commit silently loses the event with no indication.

crawl_events.py also contains get_run_events and tail_run_events — these are query functions for the API layer, not an event system

There is also publish_run_update imported from app.services.publish in crawl_service.py, but this is a separate module not in scope — the event system in crawl_events.py itself has no fanout mechanism.

Q5 — What Happens If _batch_runtime.py Crashes Mid-Run?
Partial resume exists but is weak — no URL-level deduplication.

The crash/resume logic:

python
# process_run: at the top
if run.status_value in TERMINAL_STATUSES:
    return   # don't reprocess terminal runs

# progress_state reads from existing summary
record_count = as_int(run.get_summary("record_count", 0))
progress_state = run.build_batch_progress_state(
    persisted_record_count=record_count,
    ...
)
What works: if a run is re-dispatched after a crash (e.g., by recover_stale_local_runs), it reads the existing record_count from run.summary and will stop early once record_count >= max_records. The resolved_url_list is also written to summary at the start.

What does not work:

The URL loop always starts at idx=1 — there is no checkpoint of which URLs were already processed. If a 50-URL batch crashes on URL 35, re-dispatching reprocesses URLs 1–34 again. This causes duplicate records.

resolved_url_list is saved in run.summary at start, so the URL list is stable across retries, but the loop index is not.

recover_stale_local_runs (L371 in crawl_service.py) checks last_heartbeat_at staleness and re-dispatches stale RUNNING runs — but only for in-process mode (if settings.celery_dispatch_enabled: return — stale Celery runs are completely unrecovered).

_recover_url_failure has a double-session fallback (new SessionLocal) which is good defensive code, but it persists the failure log and continues — it does not mark the URL as "skip on retry."

Q6 — Is runtime_metrics.py Wired to Anything?
No. It is an unused stub. The full file is 36 lines:

python
# runtime_metrics.py (entire file)
from dataclasses import dataclass, field

@dataclass
class RuntimeMetrics:
    pages_fetched: int = 0
    pages_failed: int = 0
    records_extracted: int = 0
    llm_calls: int = 0
    llm_tokens_used: int = 0
    selector_heal_attempts: int = 0
    selector_heal_successes: int = 0
    duration_ms: int = 0
    url_metrics: list[dict] = field(default_factory=list)
A grep across all 7 files finds zero imports of runtime_metrics. The fields it defines (llm_calls, llm_tokens_used, selector_heal_attempts) are the exact metrics needed to answer the unbounded LLM cost question from the previous audit. They exist as a dataclass with no instantiation, no wiring into _batch_runtime.process_run, no aggregation, no persistence, and no emission.

Q7 — Proposed State Machine, Idempotent Execution, and Metrics Contract
Proposed State Machine
text
                    ┌─────────────────────────────────────────────────────────┐
                    │               ALLOWED TRANSITIONS                        │
                    └─────────────────────────────────────────────────────────┘

  [CREATE]
     │
     ▼
  PENDING ──── dispatch() ────────────────────────────────────► RUNNING
     │                                                              │
     │◄─── cancel() ──────────────────────────────────────────────►│
     ▼                                                              │
  CANCELLED (terminal)                           pause()◄──────────┤
                                                    │               │
                                                    ▼               │
                                                 PAUSED             │
                                                    │               │
                                          resume() │               │
                                                    └──► PENDING ──►│
                                                                     │
                                           ┌─────────────────────── │
                                           │  success / all_urls     │
                                           ▼                         │
                                       COMPLETED (terminal)          │
                                                                     │
                                           ┌─────────────────────── │
                                           │  unrecoverable error    │
                                           ▼                         │
                                        FAILED (terminal)            │
                                                                     │
                                           ┌─────────────────────── │
                                           │  kill() signal          │
                                           ▼
                                        KILLED (terminal)

ILLEGAL (must raise TransitionError, currently not enforced):
  COMPLETED → RUNNING, FAILED → RUNNING, KILLED → RUNNING
  PENDING → COMPLETED, PENDING → FAILED, PENDING → KILLED
  PAUSED → COMPLETED, PAUSED → FAILED (must go through PENDING/RUNNING)
Implementation:

python
# crawl_state.py — replace update_run_status with:
ALLOWED_TRANSITIONS: dict[CrawlStatus, frozenset[CrawlStatus]] = {
    CrawlStatus.PENDING:   frozenset({CrawlStatus.RUNNING, CrawlStatus.CANCELLED}),
    CrawlStatus.RUNNING:   frozenset({CrawlStatus.COMPLETED, CrawlStatus.FAILED, CrawlStatus.KILLED, CrawlStatus.PAUSED}),
    CrawlStatus.PAUSED:    frozenset({CrawlStatus.PENDING, CrawlStatus.CANCELLED}),
    CrawlStatus.COMPLETED: frozenset(),
    CrawlStatus.FAILED:    frozenset(),
    CrawlStatus.KILLED:    frozenset(),
    CrawlStatus.CANCELLED: frozenset(),
}

def transition_run_status(run: CrawlRun, to: CrawlStatus) -> None:
    current = CrawlStatus(run.status_value)
    if to not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStatusTransition(
            f"Cannot transition run {run.id} from {current} → {to}"
        )
    run.status_value = to
Idempotent Job Execution
python
# _batch_runtime.process_run — replace the URL loop with:

processed_urls: set[str] = set(run.get_summary("processed_urls") or [])

for idx, url in enumerate(url_list, start=1):
    if url in processed_urls:
        continue  # ← idempotency: skip already-completed URLs on retry

    # ... process url ...

    processed_urls.add(url)
    run.update_summary(processed_urls=list(processed_urls))
    await session.commit()  # checkpoint after each URL
This requires writing processed_urls as a summary key after each URL commit. On re-dispatch after a crash, URLs already in processed_urls are skipped, eliminating the duplicate-record problem.

Metrics Emission Contract
Wire RuntimeMetrics (the existing stub) into process_run:

python
# _batch_runtime.process_run
metrics = RuntimeMetrics()  # instantiate at run start

# Per URL, accumulate:
metrics.pages_fetched += 1  (or += 0 on error)
metrics.pages_failed  += (1 if verdict == VERDICT_ERROR else 0)
metrics.records_extracted += records_count

# From url_result.url_metrics (already populated by pipeline):
metrics.llm_calls           += url_result.url_metrics.get("llm_calls", 0)
metrics.llm_tokens_used     += url_result.url_metrics.get("llm_tokens", 0)
metrics.selector_heal_attempts  += url_result.url_metrics.get("heal_attempts", 0)
metrics.selector_heal_successes += url_result.url_metrics.get("heal_successes", 0)

# At run end, persist to run.summary:
run.update_summary(runtime_metrics=asdict(metrics))

# Emit to observability (Prometheus/Datadog/StatsD):
emit_counter("crawl.pages_fetched",   metrics.pages_fetched,   tags={"domain": domain})
emit_counter("crawl.llm_calls",       metrics.llm_calls,       tags={"domain": domain})
emit_counter("crawl.llm_tokens",      metrics.llm_tokens_used, tags={"domain": domain})
emit_histogram("crawl.duration_ms",   metrics.duration_ms,     tags={"surface": run.surface})
Full Job Lifecycle Sequence Diagram
text
API/Caller          crawl_service       crawl_crud         _batch_runtime       pipeline.core      crawl_events
    │                    │                  │                    │                    │                  │
    │─ POST /runs ──────►│                  │                    │                    │                  │
    │                    │─ create_run() ──►│                    │                    │                  │
    │                    │                  │─ INSERT CrawlRun   │                    │                  │
    │                    │                  │  status=PENDING    │                    │                  │
    │                    │◄─ run ───────────│                    │                    │                  │
    │                    │                  │                    │                    │                  │
    │─ POST /dispatch ──►│                  │                    │                    │                  │
    │                    │─ dispatch_run() ─────────────────────►│                    │                  │
    │                    │  [asyncio.Task]  │                    │                    │                  │
    │◄─ run(PENDING) ────│                  │                    │                    │                  │
    │                    │                  │                    │                    │                  │
    │                    │                  │         process_run(run_id)             │                  │
    │                    │                  │                    │─ PENDING→RUNNING   │                  │
    │                    │                  │                    │─ resolve URLs      │                  │
    │                    │                  │                    │─ write summary ───►│                  │
    │                    │                  │                    │─ log_event ───────────────────────────►
    │                    │                  │                    │  "Starting crawl"  │                  │
    │                    │                  │                    │─ commit()          │                  │
    │                    │                  │                    │                    │                  │
    │                    │                  │          [URL loop: for each url]       │                  │
    │                    │                  │                    │─ check control_request (pause/kill)   │
    │                    │                  │                    │─ set_stage(ACQUIRE)│                  │
    │                    │                  │                    │─ process_single_url()                 │
    │                    │                  │                    │──────────────────►│                   │
    │                    │                  │                    │                   │─ fetch_page()     │
    │                    │                  │                    │                   │─ extract_records()│
    │                    │                  │                    │                   │─ apply_self_heal()│
    │                    │                  │                    │                   │─ publish()        │
    │                    │                  │                    │◄─ URLProcessingResult                 │
    │                    │                  │                    │─ update progress   │                  │
    │                    │                  │                    │─ accumulate metrics│                  │
    │                    │                  │                    │─ commit()          │                  │
    │                    │                  │                    │                    │                  │
    │                    │                  │          [end URL loop]                 │                  │
    │                    │                  │                    │                    │                  │
    │                    │                  │                    │─ RUNNING→COMPLETED │                  │
    │                    │                  │                    │─ write final summary                  │
    │                    │                  │                    │─ emit RuntimeMetrics                  │
    │                    │                  │                    │─ log_event ───────────────────────────►
    │                    │                  │                    │  "Pipeline finished"                  │
    │                    │                  │                    │─ commit()          │                  │
    │                    │                  │                    │                    │                  │
    │─ GET /runs/:id ───►│                  │                    │                    │                  │
    │◄─ run(COMPLETED) ──│                  │                    │                    │                  │

[ON CRASH at any point]
    │                    │                  │                    │                    │                  │
    │                    │─ recover_stale_local_runs()           │                    │                  │
    │                    │  [heartbeat check, re-dispatch]       │                    │                  │
    │                    │─ dispatch_run() ─────────────────────►│                    │                  │
    │                    │                  │         process_run(run_id)             │                  │
    │                    │                  │                    │─ status==RUNNING: PENDING→RUNNING     │
    │                    │                  │                    │─ read processed_urls from summary     │
    │                    │                  │                    │─ skip already-processed URLs [PROPOSED]
    │                    │                  │                    │─ resume from last checkpoint           │