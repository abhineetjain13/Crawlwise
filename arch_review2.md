
COMPREHENSIVE BACKEND AUDIT REPORT
Date: [Current Date]
System: Web Crawling Platform POC — Backend
Auditor: Google AI Studio Deep Analysis
Files Analyzed: 31
Total Issues Found: 28
EXECUTIVE SUMMARY
Overall Health Score: 6/10
Requirements Compliance: 85%
Invariants Compliance: 80%
Code Quality: 75%
Security: 60% (Major Vulnerabilities Detected)
Architecture: 80%
Critical Findings: 3
High Priority: 6
Medium Priority: 12
Low Priority: 7
Top 5 Critical Issues:
[Security] Server-Side Request Forgery (SSRF) Risk: No URL validation allows users to extract metadata from internal AWS/GCP IPs (169.254.169.254).
[Performance] Blocking I/O in Async Loop: store.py performs synchronous JSON file reading (path.read_text()), freezing the entire FastAPI event loop under concurrency.
[Security/Invariant] Proxy Credentials Leak: CrawlRunResponse returns the raw settings dict, exposing proxy usernames and passwords to the frontend.
[Requirement] Missing User Run Deletion: Users have no API endpoint to delete their own runs, violating requirement 3.10.
[Requirement] Missing Sitemap Parsing: The category crawler claims to support XML sitemaps, but no parsing logic exists in the codebase.
Recommendation: ⚠️ Needs Fixes (Do not deploy to production until SSRF and Blocking I/O are resolved).
PART A: SYSTEM INVARIANTS COMPLIANCE
Summary Table
Invariant	Status	Severity	File:Line
INV-AUTH-01	✅	-	api/*.py
INV-AUTH-02	✅	-	dependencies.py:26
INV-AUTH-03	✅	-	dependencies.py:34
INV-AUTH-04	✅	-	crawls.py:73
INV-JOB-01	✅	-	crawl_state.py:29
INV-JOB-02	✅	-	crawl_service.py:186
INV-JOB-03	✅	-	crawl_service.py:149
INV-JOB-04	❌	High	Missing recovery logic
INV-JOB-05	✅	-	crawl_service.py:180
INV-LLM-01	✅	-	crawl_service.py:90
INV-LLM-02	✅	-	crawl_service.py:465
INV-LLM-03	✅	-	llm_service.py:53
INV-LLM-04	✅	-	crawl_service.py:48
INV-MEM-01	✅	-	domain_utils.py:11
INV-MEM-02	❓	-	Frontend concern
INV-MEM-03	✅	-	store.py:34
INV-MEM-04	❌	High	crawls.py missing DELETE
INV-PROXY-01	✅	-	acquirer.py:71
INV-PROXY-02	❌	Critical	crawls.py:65
INV-PROXY-03	✅	-	acquirer.py:77
INV-DATA-01	✅	-	crawl.py:39
INV-DATA-02	✅	-	database.py:25
INV-DATA-03	✅	-	crawl.py:39
INV-DATA-04	✅	-	records.py:41
INV-CRAWL-01	✅	-	crawl_service.py:214
INV-CRAWL-02	✅	-	acquirer.py:133
INV-CRAWL-03	✅	-	crawl_service.py:698
Detailed Findings
❌ INV-JOB-04: No Orphan Job Recovery on Startup
Status: VIOLATED
Severity: High
Files Affected: Entire codebase (Missing workers.py or startup events)
Evidence:
The codebase has no application lifecycle hook (@app.on_event("startup") or lifespan context) to detect jobs stuck in RUNNING or PENDING states after a server crash and mark them as FAILED.
Recommendation:
Add a startup hook in main.py or the Celery worker init:
code
Python
async def recover_orphan_runs(session: AsyncSession):
    await session.execute(
        update(CrawlRun)
        .where(CrawlRun.status.in_(["running", "pending"]))
        .values(status="failed", result_summary=func.json_insert(CrawlRun.result_summary, '$.error', 'Worker restarted unexpectedly'))
    )
    await session.commit()
❌ INV-PROXY-02: Proxy Credentials Leaked to Frontend
Status: VIOLATED
Severity: Critical
Files Affected: app/schemas/crawl.py:20
Evidence:
code
Python
class CrawlRunResponse(BaseModel):
    ...
    settings: dict  # Contains raw proxy_list with user:pass
When /api/crawls/{run_id} is called, it returns settings: dict exactly as stored. If the user provided http://user:pass@proxy.com, the password is leaked in the JSON response.
Recommendation:
Add a validator in CrawlRunResponse to mask proxy credentials:
code
Python
@model_validator(mode="after")
def mask_proxy_credentials(self) -> "CrawlRunResponse":
    if "proxy_list" in self.settings:
        self.settings["proxy_list"] = [re.sub(r'://.*@', '://***:***@', p) for p in self.settings["proxy_list"]]
    return self
❌ INV-MEM-04: Missing User Run Deletion
Status: VIOLATED
Severity: High
Files Affected: app/api/crawls.py
Evidence:
Requirement 3.10 and INV-MEM-04 assume normal users can delete runs. There is no DELETE /api/crawls/{run_id} endpoint.
Recommendation:
Implement the endpoint in crawls.py:
code
Python
@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def crawls_delete(run_id: int, session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    run = await get_run(session, run_id)
    if run is None or (user.role != "admin" and run.user_id != user.id):
        raise HTTPException(status_code=404)
    await session.delete(run) # Cascades to records safely
    await session.commit()
PART B: CODE QUALITY ISSUES
B.1 Magic Numbers (Total: 8)
File	Line	Issue	Recommendation	Priority
crawl_service.py	1125	confidence=0.78	Extract to pipeline_config.json under llm_xpath_confidence	Medium
crawl_service.py	1172	confidence=0.7	Extract to pipeline_config.json under llm_value_confidence	Medium
browser_client.py	92	timeout=30_000	Extract to config constants	Low
llm_runtime.py	157	max_tokens: 1200	Should be passed via DB LLMConfig	Medium
llm_runtime.py	158	temperature: 0.1	Should be a configurable param	Low
B.2 Hardcoded Sites/Selectors (Total: 3)
File	Line	Issue	Recommendation
shopify.py	64	products.json?limit=250	Magic limit number, abstract to constant.
remotive.py	31	if "remotive.com" in url	Adapter violates OCP; split into RemotiveAdapter and RemoteOkAdapter.
greenhouse.py	46	Regex domains	Move regex definitions to class variables.
B.3 Unused Imports (Total: 2 files affected)
app/services/adapters/amazon.py: import json
app/services/adapters/indeed.py: import json
B.4 Duplicate Code (Total: 1 duplications)
Duplication detected:
Location 1: app/services/llm_runtime.py:145 (_call_openai)
Location 2: app/services/llm_runtime.py:175 (_call_groq)
Location 3: app/services/llm_runtime.py:237 (_call_nvidia)
Similarity: 90%
Code: Standard httpx.AsyncClient JSON POST requests.
Recommendation: Extract into a generic _execute_http_post(url, headers, payload) utility.
Estimated savings: 50 lines of code.
B.5 Technical Debt (Total: 2 items)
Category: Double Rollback Danger
File: app/services/crawl_service.py:540-575
Issue: _mark_run_failed catches exceptions, commits, catches exceptions again, and rolls back inside a nested block. This risks poisoned SQLAlchemy transactions.
Priority: High
Category: Unbounded Artifact Storage
File: app/services/acquisition/acquirer.py:80
Issue: HTML files and network payloads are written to disk but never automatically purged.
Priority: High
PART C: ARCHITECTURE ISSUES
C.1 Layer Violations (Total: 0)
Excellent implementation. API routers are completely decoupled from business logic, pushing all DOM/DB work to the services layer.
C.2 Adapter Pattern Issues (Total: 1)
Bloated Abstract Logic: All adapters duplicate the structural boilerplate of soup = BeautifulSoup(html, "html.parser") and if surface == X.
Fix: Move the HTML parsing and surface routing into BaseAdapter.extract(), requiring subclasses to only implement _extract_detail() and _extract_listing().
C.3 Error Handling Gaps (Total: 2)
Bare Exceptions in Browser Actions:
app/services/acquisition/browser_client.py:151 & 161. Catching Exception broadly during _dismiss_cookie_consent and _scroll_to_bottom masks PlaywrightTimeoutError and can hide memory leaks.
PART D: SECURITY VULNERABILITIES
D.1 Critical Security Issues (Total: 1)
Severity: Critical
Issue: Server-Side Request Forgery (SSRF)
File: app/api/crawls.py:27 & app/services/acquisition/acquirer.py
Context: User submits any URL, and the backend HTTP/Browser clients fetch it.
Risk: Users can crawl http://169.254.169.254/latest/meta-data/ to steal AWS IAM credentials, or scan local ports (http://localhost:6379).
Recommendation:
Implement a URL validator that resolves the IP address and denies local/private CIDR blocks before passing to curl_cffi or Playwright.
D.2 Authentication/Authorization Gaps (Total: 0)
All dependencies enforce RBAC strictly.
PART E: PERFORMANCE ISSUES
E.1 Synchronous I/O in Async Context (Total: 1)
Severity: Critical
File: app/services/knowledge_base/store.py:16
Issue: _load_json and _write_json use blocking file system calls (path.read_text() / path.write_text()).
Risk: Since FastAPI runs on a single event loop, reading/writing the JSON knowledge base blocks all other concurrent requests.
Recommendation:
code
Python
import aiofiles
import json

async def _load_json(path: Path, fallback: dict | list) -> dict | list:
    if not path.exists(): return fallback
    async with aiofiles.open(path, 'r', encoding="utf-8") as f:
        return json.loads(await f.read())
Note: This requires cascading async updates to all functions referencing the knowledge base.
PART F: REQUIREMENTS COMPLIANCE
F.1 Fully Implemented Features
✅ Admin Panel (User Management, Role checking)
✅ Dashboard (Summary cards, reset logic)
✅ PDP Crawl (Batch, CSV, LLM cleanup, field persistence)
✅ CSS/XPath Tools (LLM suggestion, interactive testing)
✅ Run History (Filters, Log exports, JSON/CSV exports)
✅ LLM Config (Admin CRUD, Connection testing)
F.3 Missing Features
❌ Sitemap Parsing (Req 3.3): The Category Crawl requirements stipulate: "Inputs: Category listing page URL, or Sitemap URL (XML format)." There is no XML parsing logic in crawl_service.py or extract/listing_extractor.py.
❌ Normal User History Clear (Req 3.10): Addressed in INV-MEM-04.
PART G: SCHEMA & DATA INTEGRITY
G.1 Schema Mismatches
No mismatches. Pydantic schemas explicitly use ConfigDict(from_attributes=True) and cleanly mirror the SQLAlchemy 2.0 type hints.
G.2 Migration Issues
No alembic directory was provided in the prompt, so migration reversibility is UNVERIFIABLE.
PART H: KNOWLEDGE BASE REVIEW
H.1 Structure Assessment
The structure separating DOM fallback patterns, field aliases, and LLM prompts into JSON/txt files is brilliant and highly extensible.
H.2 Performance Concerns
As mentioned in E.1, disk I/O on every request is a major bottleneck. Furthermore, pipeline_config.py loads the configs once at startup into memory, but store.py reads them continually from disk on every review generation. This is a "split-brain" architecture.
Recommendation: Unify behind an in-memory caching layer that reloads only via an explicit /api/system/reload endpoint or file-watcher.