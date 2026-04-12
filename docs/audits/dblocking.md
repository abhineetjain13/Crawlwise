Audit Summary: Database Locking Issue When Resetting During Active Crawl
Critical Issues Found:
No Transaction Isolation/Locking Strategy

reset_application_data() performs bulk deletes with delete(CrawlRun) which attempts to delete ALL rows
If a crawl is running, it likely has locks on the CrawlRun row (for status updates) and CrawlRecord rows (for inserts)
PostgreSQL will block the DELETE operation until those locks are released
Order of Deletion Creates Deadlock Risk


delete(CrawlLog)        # Foreign key to CrawlRun
delete(CrawlRecord)     # Foreign key to CrawlRun  
delete(ReviewPromotion) # Foreign key to CrawlRun
delete(LLMCostLog)      # No FK but might be accessed
delete(CrawlRun)        # Parent table - deleted last
Deleting child tables first while parent is locked by active crawl = potential deadlock
Active crawl might be: inserting CrawlRecord → updating CrawlRun status → flushing
Reset tries: delete CrawlRecord → delete CrawlRun (blocked by crawl's lock)
No Timeout on Reset Operation

The reset function has no statement timeout
If it blocks waiting for locks, it will wait indefinitely (or until pool_timeout of 10 seconds)
User sees a "huge error" when the timeout expires
Active Crawl Lock Points:

_persist_and_update_run() in _batch_runtime.py - holds locks during flush/commit
record_persistence.py - inserts records with session.flush() inside nested transactions
runtime_helpers.py - updates run summary with session.flush()
All these operations hold row-level locks that block the DELETE
No Check for Active Runs

Reset doesn't check if any runs have status IN ('pending', 'running', 'paused')
Should fail fast with a clear error instead of blocking
Why It Happens:
Active crawl holds row-level locks on crawl_runs and crawl_records
Reset's DELETE statements wait for those locks to be released
PostgreSQL default lock timeout can cause the operation to hang or fail with cryptic errors
Recommended Fixes (for future):
Add a pre-check for active runs before attempting reset
Add a statement timeout specifically for the reset operation
Consider using DELETE ... WHERE status NOT IN ('running', 'pending', 'paused') to avoid active runs
Add better error handling with user-friendly messages
Optionally: Force-kill active runs first, then reset (with user confirmation)