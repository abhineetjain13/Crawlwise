# Database Lock Error Fix

## Problem

When running crawl pipelines with `url_batch_concurrency > 1`, the system would occasionally fail with:

```
OperationalError: (sqlite3.OperationalError) database is locked
[SQL: UPDATE crawl_runs SET result_summary=?, updated_at=? WHERE crawl_runs.id = ?]
```

This occurred because multiple concurrent tasks were trying to update the same `crawl_runs` row simultaneously, causing SQLite lock contention even with WAL mode enabled.

## Root Cause

The batch processing system spawns multiple isolated database sessions (one per URL) when `url_batch_concurrency > 1`. When multiple URLs complete processing at nearly the same time, they all try to commit updates to the `result_summary` field of the same `crawl_runs` row, causing lock contention.

Even though the database is configured with:
- WAL mode (`PRAGMA journal_mode=WAL`)
- 60-second busy timeout (`PRAGMA busy_timeout=60000`)
- Connection timeout of 60 seconds

SQLite can still experience brief lock contention when multiple writers compete for the same row.

## Solution

Implemented exponential backoff retry logic for database commits:

1. **Created `app/services/db_utils.py`** with a `commit_with_retry()` function that:
   - Catches `OperationalError` with "database is locked" message
   - Retries up to 5 times with exponential backoff (50ms → 100ms → 200ms → 400ms → 800ms)
   - Adds random jitter to reduce collision probability
   - Re-raises non-lock errors immediately
   - Re-raises lock errors after max retries

2. **Updated `app/services/_batch_runtime.py`** to use `commit_with_retry()` for all database commits in:
   - Pipeline start/resume
   - Progress updates after each URL
   - Control signal handling (pause/kill)
   - Final pipeline completion
   - Error handling

3. **Updated `app/services/pipeline/core.py`** to use `commit_with_retry()` in:
   - Failure state persistence
   - Error recovery commits

## Benefits

- **Resilient to transient lock contention**: Automatically retries on lock errors
- **Fast in normal cases**: No overhead when locks aren't contended
- **Configurable**: Retry parameters can be adjusted if needed
- **Minimal code changes**: Centralized retry logic in one utility function
- **Backward compatible**: Works with existing code and tests

## Testing

Added comprehensive unit tests in `tests/services/test_db_utils.py` covering:
- Success on first attempt
- Success after retries
- Non-lock errors raised immediately
- Max retries exceeded

All existing tests continue to pass.

## Alternative Solutions Considered

1. **Serialize updates with a lock/semaphore**: Would reduce concurrency benefits
2. **Use a queue to batch updates**: More complex, harder to maintain
3. **Switch to PostgreSQL**: Overkill for this issue, SQLite works well otherwise
4. **Increase busy_timeout further**: Already at 60 seconds, not the root cause

The retry approach provides the best balance of simplicity, performance, and reliability.
