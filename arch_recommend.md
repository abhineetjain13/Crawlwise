Current Bottleneck: Sequential Execution
The current crawl_service.py handles batch URLs using a synchronous for loop. This means URL #100 must wait for URLs 1 through 99 to finish execution, including any timeouts or browser hangs.

1. Database: Move from SQLite to PostgreSQL
Current State: You are using SQLite (crawlerai.db is already ~436MB).
The Issue: SQLite uses database-level locking for writes. In a bulk scenario where 10+ workers are trying to save records and logs simultaneously, you will hit database is locked errors and severe performance degradation.
Recommendation: Install PostgreSQL. It supports high-concurrency row-level locking, which is essential for multi-worker extraction where hundreds of records are being written per second.
2. Task Orchestration: Redis + Celery
Current State: Crawls run inside the FastAPI process. If the server restarts, in-flight crawls are lost. There is no parallelization across URLs within a single batch.
The Recommendation:
Redis: Install this as your "Broker." It acts as a high-speed queue for URLs waiting to be processed.
Celery: Install this as your "Worker Engine." Instead of one loop processing 100 URLs, you dispatch 100 independent tasks to Celery.
Why? This allows you to scale horizontally. You can have 4, 8, or 16 workers running in parallel. If one worker gets stuck on a 2-minute AutoZone hang, the other 15 workers keep processing the rest of the queue.
3. Concurrency & Rate Limiting
Browser Management: Playwright is resource-heavy (RAM/CPU). With Celery, you can set a "Concurrency" limit (e.g., max 5 browsers at once) to prevent your server from crashing while still maximizing throughput.
Domain Throttling: You can use Redis to ensure you don't hit the same domain (e.g., AutoZone) with 50 requests at once, avoiding IP bans while still crawling other sites at full speed.
Summary of Recommended Stack
PostgreSQL: For concurrent data persistence.
Redis: For task queuing and temporary state management.
Celery: For distributed execution and automatic retries.
Flower: A dashboard to monitor your Celery workers in real-time.