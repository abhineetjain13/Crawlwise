# Web Crawling Platform — Requirements & System Invariants
**Document Type:** Product Requirements + System Invariants  
**Scope:** Internal Tool POC  
**Stack:** Next.js (frontend) + FastAPI (backend) + SQLite (persistence, scalable)  
**Crawl Engine:** Hybrid — HTTP/HTML parsing for static pages, Browser automation (Playwright/Puppeteer) for JS-rendered/SPA pages  
**Job Execution:** Background workers with status polling  
**Version:** 1.0 — Draft  

---

## 1. Glossary

| Term | Definition |
|---|---|
| **PDP** | Product Detail Page — a single product/listing page being crawled |
| **SPA Crawler** | Category or listing page crawler; handles JavaScript-rendered content |
| **Site Memory** | Persisted XPath/field mappings scoped to a domain, auto-applied on revisit |
| **LLM Cleanup Layer** | Non-deterministic normalization pass over raw multi-source data; output is user-confirmed before storage |
| **Discoverist CSV** | Customer-specific export schema; column definitions to be maintained separately |
| **Run** | A single crawl job execution instance |
| **Active Job** | A Run that is currently in `PENDING`, `RUNNING`, or `PAUSED` state |
| **Acquisition hardening** | Generic transport-layer resilience controls such as retries, browser fallback, header normalization, challenge detection, proxy rotation, and diagnostics capture that apply consistently across production targets rather than being tailored to one site |
| **Fetched artifact** | The persisted evidence captured for one acquisition attempt, consisting of raw response content and associated capture metadata; examples include raw HTML, the HTTP response envelope (status, headers, final URL), and browser artifacts such as screenshots when a browser engine was used |

---

## 2. User Roles & Permissions

### 2.1 Role Definitions

**Admin**
- Full access to all modules
- Can create, deactivate, and reactivate user accounts
- Can view all users' run history
- Can manage LLM configuration
- Can trigger global kill on any active job
- Can clear history platform-wide

**Normal User**
- Can run crawls, view their own run history, manage their own jobs
- Cannot access the Admin panel or LLM Config
- Cannot kill another user's jobs
- Cannot clear history platform-wide

### 2.2 Authentication

- Registration is email-based; no OAuth in scope for POC
- Login returns a session token (JWT or equivalent)
- All API routes must be protected; unauthenticated requests receive `401`
- Admin role is assigned manually or at first-user bootstrap

---

## 3. Module Requirements

### 3.1 Admin Panel — User Management

**Functional Requirements**
- Display a paginated list of all registered users
- Each user entry shows: name, email, role, status (Active / Inactive), registration date
- Filters: search by name or email, filter by Active / Inactive status
- Admin can deactivate a user (revokes all active sessions immediately)
- Admin can reactivate a deactivated user
- Admin can change a user's role (Normal ↔ Admin)
- Deactivated users cannot log in; existing tokens for deactivated users are rejected

**Out of Scope (POC)**
- Password reset flows
- Email verification
- Invite-only registration

---

### 3.2 Dashboard

**Functional Requirements**
- Summary cards: total runs, runs today, active jobs count, total URLs crawled
- Recent activity feed: last 10 runs across the platform (admins) or last 10 runs by the user (normal users)
- Quick-launch entry points to Category Crawl and PDP Crawl modules
- Active jobs count is a live-polling value (refresh interval: configurable, default 10s)

---

### 3.3 Category Crawl / SPA Crawler

**Purpose:** Crawl a category listing page or sitemap to discover and extract a set of URLs or records.

**Inputs**
- Category listing page URL, or
- Sitemap URL (XML format)

**Settings (per run)**

| Setting | Type | Description |
|---|---|---|
| Max Records | Integer | Hard cap on records to collect |
| Sleep Time | Integer (ms) | Delay between requests |
| Number of Pages | Integer | Maximum pagination depth |
| Proxy | Toggle + list | Use rotating proxy pool for this run |

**Pre-run Preview**
- Before execution, display a summary of: target URL, estimated scope (pages × records), active settings, proxy status
- User must confirm before the job is dispatched

**Output Tabs**

| Tab | Description |
|---|---|
| Table | Paginated tabular view of extracted records |
| JSON | Raw JSON of all extracted records |
| Intelligence | LLM-generated summary/classification of the crawled dataset |
| Logs | Real-time job log stream (status, errors, page transitions, proxy events) |

**Downloads**
- CSV export of all records
- JSON export of all records

**Proxy Behaviour**
- User provides a list of proxies (host:port or host:port:user:pass format)
- Proxies rotate per request (round-robin or random; configurable)
- Failed proxies are skipped and logged; run continues on remaining proxies
- If all proxies fail, run status is set to `PROXY_EXHAUSTED` and the job pauses

---

### 3.4 PDP Crawl — New

**Purpose:** Extract structured data from one or many product detail pages, combining multiple data sources into a single normalised output.

**Input Modes**

| Mode | Description |
|---|---|
| Single Page | One URL entered manually |
| Batch | Multiple URLs entered as a newline-separated list |
| CSV Upload | Upload a CSV file; user maps the URL column |

**Settings (per run)**

| Setting | Type | Description |
|---|---|---|
| Max Records | Integer | Hard cap on records to process |
| Sleep Time | Integer (ms) | Delay between page requests |
| Proxy | Toggle + list | Use rotating proxy pool for this run |

- Show: detected/configured output columns, their data source (HTML XPath, JSON-LD, API, Regex), and a sample value if a preview fetch is available
- User can add, remove, or reorder columns before confirming

**Field Configuration**
- System auto-detects fields from: HTML (XPath/CSS), JSON-LD, embedded JSON, and external API responses
- User can add custom fields by:
  - Name only → system auto-detects the most likely source
  - XPath expression → user-defined extraction rule
  - Regex pattern → applied against raw page content
- All field configurations are persisted to Site Memory for the domain

**LLM Cleanup Layer**
- After raw extraction, all multi-source data is passed to the configured LLM
- The LLM produces a set of cleaned, normalised column suggestions (name + value per record)
- User reviews suggestions in a column-accept/reject UI before the final output is committed
- Accepted columns are stored; rejected columns are discarded and logged
- This step is non-deterministic; results may vary across runs for the same input

**Output Tabs**

| Tab | Description |
|---|---|
| Table | Paginated tabular view of normalised output |
| JSON | Raw JSON of all records |
| Intelligence | LLM-generated summary, anomaly flags, data quality notes |
| Logs | Real-time job log stream |

**Downloads**
- CSV
- JSON
- Discoverist CSV (customer-specific column schema — schema definition maintained separately)

**Data Persistence**
- All confirmed output is stored in SQLite for future reference and reuse
- Each record is linked to its Run ID, source URL, and timestamp

**Proxy Behaviour**
- Same as Category Crawl (§3.3)

---

### 3.5 CSS / XPath Selector

**Purpose:** Given a URL and expected column names, suggest and validate XPath selectors interactively.

**Inputs**
- Page URL
- Expected column names (comma-separated or list input)

**Behaviour**
- System fetches the page and runs LLM-assisted XPath suggestion for each expected column
- Suggestions are displayed alongside a live preview of the extracted value
- User can:
  - Accept a suggestion as-is
  - Manually edit the XPath and re-test
  - Test any arbitrary XPath against the loaded page DOM
- All accepted XPath mappings are saved to Site Memory under the page's domain

**Output**
- A saved XPath configuration per domain, reusable in PDP Crawl and Category Crawl

---

### 3.6 Run History

**Functional Requirements**
- Paginated list of all past runs (admin sees all users; normal user sees own runs)
- Each entry shows: Run ID, crawl type, target URL, started at, completed at, status, record count, triggered by
- Filters:
  - Date range
  - Website URL (partial match / search)
  - Crawl Type: Single Page, Batch, CSV Upload, Category, Sitemap

**Actions per Run**
- View full output (re-opens the output tabs for that run)
- Download output (CSV, JSON)
- Re-run with the same configuration

**Retention**
- Retention policy is undefined for POC; an admin-controlled manual "Clear History" action is the only deletion mechanism until a policy is set

---

### 3.7 LLM Config

**Purpose:** Manage the LLM used by the platform for XPath suggestion, field auto-detection, and the data cleanup layer.

**Functional Requirements**
- Admin-only access
- Configure: provider (e.g. OpenAI, Anthropic, local), model name, API key, endpoint URL
- Test connection before saving
- Active config is applied globally to all LLM-dependent features
- Config changes take effect on the next job that invokes an LLM call; in-flight jobs use the config at job creation time

---

### 3.8 Active Jobs

**Purpose:** Real-time visibility and control over all running crawl jobs.

**Functional Requirements**
- Live list of all active jobs (status: `PENDING`, `RUNNING`, `PAUSED`)
- Each entry shows: Run ID, user, crawl type, target URL, progress (records collected / max), elapsed time, status
- Auto-refreshes via polling (default: 5s)

**Controls**

| Action | Behaviour |
|---|---|
| Pause | Suspends the job after the current in-flight request completes; status → `PAUSED`; partial output is preserved |
| Resume | Restarts a `PAUSED` job from where it left off |
| Hard Kill | Terminates the job immediately; partial output collected so far is saved and accessible; status → `KILLED` |

**Permission**
- Normal users can pause/resume/kill their own jobs
- Admins can pause/resume/kill any job

---

### 3.9 Site Memory

**Purpose:** Accumulate and reuse domain-level crawl intelligence across sessions.

**Stored Per Domain**
- XPath / CSS selector mappings (field name → selector)
- Regex patterns
- Field-to-source mappings (which source: HTML, JSON-LD, API, etc.)
- LLM-accepted column configurations
- Last crawl timestamp

**Auto-Apply Behaviour**
- When a user enters a URL whose domain has a stored Site Memory entry, the system automatically pre-populates field configurations in the crawl setup
- A banner notifies the user: "Loaded X fields from Site Memory for [domain]"
- User can override, extend, or clear the auto-loaded config for the current session without affecting stored memory
- Saving new configurations from a session updates (merges) Site Memory for the domain

**Management**
- Users can view, edit, and delete Site Memory entries per domain
- Admin can clear all Site Memory entries

---

### 3.10 Clear History

**Functional Requirements**
- Admin-only action for full platform history wipe
- Normal users can delete their own individual run records
- Confirmation dialog required before any destructive deletion
- Clearing history removes run records and output data; Site Memory is unaffected unless explicitly cleared separately

---

## 4. System Invariants

Invariants are conditions that must hold true at all times, regardless of application state, user action, or system load. Any code or architectural decision that violates an invariant is a defect.

### 4.1 Authentication & Authorisation

- **INV-AUTH-01:** Every API endpoint, except login and register, must validate the session token before processing the request. A missing or invalid token always returns `401`.
- **INV-AUTH-02:** A deactivated user's token is rejected immediately, even if the token has not expired.
- **INV-AUTH-03:** Role-restricted endpoints (Admin Panel, LLM Config, global kill) always verify role server-side. Frontend gating is cosmetic only.
- **INV-AUTH-04:** A normal user can never read, modify, or kill another user's jobs or data through any API path.

### 4.2 Job Lifecycle

- **INV-JOB-01:** A job's state transitions are strictly ordered: `PENDING → RUNNING → (PAUSED ↔ RUNNING) → COMPLETED | KILLED | FAILED | PROXY_EXHAUSTED`. No other transitions are valid.
- **INV-JOB-02:** Partial output is always persisted before a job transitions to `KILLED`. A hard kill never results in data loss of records already collected.
- **INV-JOB-03:** A job in `COMPLETED` or `KILLED` or `FAILED` state cannot be re-paused, re-killed, or re-resumed. A re-run creates a new job with a new Run ID.
- **INV-JOB-04:** Job state is stored in the database, not in memory. A worker/server restart must not cause a running job to silently disappear — it must surface as `FAILED` with a restart event logged.
- **INV-JOB-05:** The `max records` setting is a hard ceiling. A job must not collect more records than this value under any circumstance.

### 4.3 LLM Cleanup Layer

- **INV-LLM-01:** No LLM-produced column output is committed to the output dataset without explicit user acceptance. Rejection is the default if the user closes the review UI without acting.
- **INV-LLM-02:** The LLM cleanup layer is applied after raw extraction and before final output storage. It is never skipped silently; if the LLM call fails, the user is notified and can proceed with raw (uncleaned) data or retry.
- **INV-LLM-03:** LLM API keys are never exposed to the frontend or included in any client-visible response.
- **INV-LLM-04:** The LLM config active at job creation time is used for the duration of that job. Mid-job config changes do not affect in-flight jobs.

### 4.4 Site Memory

- **INV-MEM-01:** Site Memory is keyed by normalised domain (scheme-stripped, www-normalised). `https://www.example.com/a` and `http://example.com/b` resolve to the same domain key: `example.com`.
- **INV-MEM-02:** Auto-applying Site Memory to a new session never overwrites the user's manual field edits made after auto-load. Auto-load is a one-time pre-population event, not a live sync.
- **INV-MEM-03:** Saving a session's field config to Site Memory performs a merge (new fields are added; existing fields are updated only if the new value is explicitly saved). Nothing is silently deleted from Site Memory.
- **INV-MEM-04:** Clearing run history never deletes Site Memory. These are independent data stores.

### 4.5 Proxy

- **INV-PROXY-01:** When proxy is enabled, no outbound crawl request is made directly from the server's IP. All requests are routed through a proxy from the pool.
- **INV-PROXY-02:** Proxy credentials (user:pass) are stored server-side only and are never returned to the frontend.
- **INV-PROXY-03:** A proxy failure on a single request does not fail the job. The request is retried through the next proxy in the pool. Only full pool exhaustion triggers a `PROXY_EXHAUSTED` status.

### 4.6 Data Integrity

- **INV-DATA-01:** Every output record is linked to exactly one Run ID. Orphaned records (records with no associated run) are invalid and must not appear in any output view.
- **INV-DATA-02:** SQLite write operations are serialised using WAL (Write-Ahead Logging) mode to prevent corruption under concurrent job writes.
- **INV-DATA-03:** Deleting a run record also deletes all associated output records in the same transaction. Partial deletes are not permitted.
- **INV-DATA-04:** Exports (CSV, JSON, Discoverist CSV) are generated from the stored output data, not re-fetched from the source URL. The exported data reflects what was captured at run time.

### 4.7 Crawl Behaviour

- **INV-CRAWL-01:** `sleep time` is applied between every consecutive outbound request within a job, without exception. A sleep time of 0ms is valid but must be explicitly set by the user.
- **INV-CRAWL-02:** The hybrid crawler selects the engine (HTTP or browser automation) per page, not per job. Static pages always use the lightweight HTTP path unless the page is detected as JS-rendered.
- **INV-CRAWL-03:** XPath and Regex expressions provided by the user are validated for syntactic correctness before a job is dispatched. A job with an invalid expression is rejected with a descriptive error; it never starts.
- **INV-CRAWL-04:** Acquisition hardening must remain generic. No production code that runs against external or customer-facing target sites may contain per-domain hacks, allowlists, or special-case bypasses to make one production target pass. Internal test fixtures, local mocks, and deterministic adapter fixtures used only under test are allowed, provided they remain isolated from production acquisition paths and exercise the same acquisition hardening controls (retries, browser fallback, challenge detection, error handling) validated in production.
- **INV-CRAWL-05:** Every successful acquisition attempt at the page-fetch level, regardless of whether downstream extraction later yields zero records, persists both the fetched artifact and a machine-readable diagnostics record so transport regressions can be investigated without depending on ephemeral logs. At minimum, the fetched artifact set must preserve raw HTML for HTTP/browser fetches, the HTTP response envelope when available (final URL, status, headers), and a screenshot for browser-engine acquisitions when one was captured. The diagnostics record must be stored in a machine-readable JSON payload and/or a dedicated SQLite table under the existing persistence model in §3.4 Data Persistence, extending the SQLite guarantees in [§4.6 Data Integrity](#46-data-integrity) and retaining records according to [OI-01](#5-open-items). Minimum diagnostics fields are: `timestamp`, `url`, `final_url`, `http_status`, `response_time_ms`, `proxy`, `engine_type`, `error_code`, `error_detail`, `blocked_verdict`, and references to the persisted fetched artifacts.

---

## 5. Open Items

| # | Item | Owner | Notes |
|---|---|---|---|
| OI-01 | Data retention policy | To be decided | Until resolved, retention is indefinite; manual clear is the only mechanism |
| OI-02 | Discoverist CSV column schema | Client / stakeholder | Must be formally documented before the Download button is implemented |
| OI-03 | Concurrency limit per user | Engineering | Multiple concurrent jobs per user are permitted; a sensible cap (e.g. 5) should be agreed before load testing |
| OI-04 | Browser automation engine | Engineering | Playwright vs Puppeteer decision pending; either satisfies the hybrid invariant |
| OI-05 | Background job queue | Engineering | Celery (Python) is the natural fit given FastAPI; confirm Redis vs RabbitMQ as broker |
| OI-06 | Session token strategy | Engineering | JWT (stateless) vs server-side session; deactivation invariant (INV-AUTH-02) favours server-side or token blocklist |

---

*End of Document*
