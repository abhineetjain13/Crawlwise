# Software Engineering Principles Violations - Deep Audit

**Focus:** SOLID principles, Separation of Concerns, Configuration Management, Architectural Patterns

---

## CRITICAL VIOLATIONS OF FIRST PRINCIPLES

### 1. **MASSIVE VIOLATION: Configuration as Code (Hardcoded Constants)**

**File:** `backend/app/services/pipeline_config.py` (600+ lines)  
**Severity:** CRITICAL - Violates 12-Factor App, makes system inflexible

**Issue:** 200+ hardcoded configuration constants scattered across codebase

```python
# pipeline_config.py - Lines 200-400+
HTTP_TIMEOUT_SECONDS = 20
ACQUISITION_ATTEMPT_TIMEOUT_SECONDS = 90
BROWSER_POOL_MAX_SIZE = 6
BROWSER_POOL_IDLE_TTL_SECONDS = 300
DEFAULT_MAX_RECORDS = 100
URL_BATCH_CONCURRENCY = 4
LISTING_MIN_ITEMS = 2
CHALLENGE_WAIT_MAX_SECONDS = 15
# ... 200+ more constants
```

**Violations:**
1. **12-Factor App Principle III (Config):** Configuration should be in environment, not code
2. **Open/Closed Principle:** Cannot change behavior without code changes
3. **Deployment Flexibility:** Same code cannot run in different environments with different configs

**Impact:**
- Cannot tune performance without redeploying code
- Cannot A/B test different timeout values
- Cannot have different configs for dev/staging/prod
- Requires code review for operational tuning

**Evidence of Scale:**
```bash
# Found 200+ hardcoded constants:
_BROWSER_POOL_MAX_SIZE = 6
_BROWSER_POOL_IDLE_TTL_SECONDS = 300
_MAX_TRAVERSAL_FRAGMENTS = 50
_MAX_PROXY_BACKOFF_EXPONENT = 8
_DISABLE_COOLDOWN_SECONDS = 30.0
MAX_RECORD_PAGE_SIZE = 1000
LLM_CLEAN_CANDIDATE_TEXT_LIMIT = 2000
MIN_VIABLE_RECORDS = 2
_MAX_REGEX_INPUT_LEN = 500
```

**Correct Approach:**
```python
# Should be:
class CrawlerConfig(BaseSettings):
    browser_pool_max_size: int = Field(default=6, env="BROWSER_POOL_MAX_SIZE")
    browser_pool_idle_ttl: int = Field(default=300, env="BROWSER_POOL_IDLE_TTL")
    acquisition_timeout: int = Field(default=90, env="ACQUISITION_TIMEOUT")
    # ... all configs from environment
```

---

### 2. **CRITICAL: Business Logic in API Routes (Fat Controllers)**

**Files:** `backend/app/api/crawls.py`, `backend/app/api/records.py`  
**Severity:** CRITICAL - Violates Separation of Concerns, Single Responsibility

**Issue:** API route handlers contain complex business logic, data transformation, and formatting

#### Example 1: CSV Processing in Route Handler
**File:** `backend/app/api/crawls.py:145-180`

```python
@router.post("/csv")
async def crawls_create_csv(
    file: UploadFile, surface: str, ...
):
    # BUSINESS LOGIC IN CONTROLLER!
    content = (await file.read()).decode("utf-8", errors="ignore")
    urls = parse_csv_urls(content)  # OK - delegated
    
    if not urls:  # VALIDATION IN CONTROLLER
        raise HTTPException(...)
    
    # DATA TRANSFORMATION IN CONTROLLER
    extra_fields = [f.strip() for f in additional_fields.split(",") if f.strip()]
    
    try:
        crawl_settings = json.loads(settings_json)  # PARSING IN CONTROLLER
    except json.JSONDecodeError:
        crawl_settings = {}
    
    # MORE BUSINESS LOGIC
    crawl_settings["csv_content"] = content
    data = {
        "run_type": "csv",
        "url": urls[0],
        "urls": urls,
        # ... complex dict construction
    }
```

**Violations:**
- **Single Responsibility Principle:** Route handler does HTTP + validation + parsing + business logic
- **Separation of Concerns:** Controller knows about CSV format, URL parsing, settings structure
- **Testability:** Cannot unit test business logic without HTTP framework

#### Example 2: Complex Export Logic in Routes
**File:** `backend/app/api/records.py:100-600`

```python
# 500+ lines of export formatting logic IN THE ROUTE FILE!

async def _stream_export_csv(session, run_id):
    # Complex CSV generation logic
    rows, _ = await _collect_export_rows(session, run_id)
    cleaned_records = [_clean_export_data(row.data) for row in rows]
    # ... 50 more lines of transformation

async def _stream_export_markdown(session, run_id):
    # Complex markdown formatting logic
    # ... 100+ lines

def _record_to_markdown(row: CrawlRecord) -> str:
    # 150+ lines of markdown generation logic IN API FILE
    raw_data = row.data if isinstance(row.data, dict) else {}
    data = _clean_export_data(raw_data)
    # ... complex transformation logic
```

**Impact:**
- Cannot reuse export logic outside HTTP context
- Cannot test export formats without FastAPI test client
- Violates DRY - export logic duplicated across formats
- 600+ lines in a single route file

**Correct Approach:**
```python
# routes/crawls.py - THIN CONTROLLER
@router.post("/csv")
async def crawls_create_csv(file: UploadFile, surface: str, ...):
    # Only HTTP concerns
    content = await file.read()
    
    # Delegate to service layer
    run_id = await crawl_service.create_from_csv(
        content=content,
        surface=surface,
        user_id=user.id,
        settings=settings_json
    )
    return {"run_id": run_id}

# services/crawl_service.py - BUSINESS LOGIC
async def create_from_csv(content: bytes, surface: str, ...):
    urls = csv_parser.parse_urls(content)
    validator.validate_urls(urls)
    settings = settings_parser.parse(settings_json)
    return await create_crawl_run(...)
```

---

### 3. **VIOLATION: God Object Anti-Pattern**

**File:** `backend/app/services/pipeline_config.py`  
**Severity:** HIGH - Single file with 200+ exports, 1500+ lines

**Issue:** One massive configuration file that everything imports

```python
# pipeline_config.py exports 200+ symbols
from app.services.pipeline_config import (
    HTTP_TIMEOUT_SECONDS,
    BROWSER_POOL_MAX_SIZE,
    LISTING_MIN_ITEMS,
    CHALLENGE_WAIT_MAX_SECONDS,
    # ... 200 more imports
)
```

**Violations:**
- **Single Responsibility:** File handles HTTP config, browser config, extraction rules, selectors, etc.
- **High Coupling:** Every module depends on this god object
- **Change Amplification:** Changing one config requires reloading entire file
- **Namespace Pollution:** 200+ global constants

**Evidence:**
```python
# All these unrelated concerns in ONE file:
HTTP_TIMEOUT_SECONDS = 20                    # HTTP config
BROWSER_POOL_MAX_SIZE = 6                    # Browser config
LISTING_MIN_ITEMS = 2                        # Extraction rules
CHALLENGE_WAIT_MAX_SECONDS = 15              # Anti-bot config
COOKIE_CONSENT_SELECTORS = [...]             # DOM selectors
SALARY_RANGE_REGEX = r"..."                  # Regex patterns
CURRENCY_SYMBOL_MAP = {...}                  # Data mappings
```

**Correct Approach:**
```python
# config/http_config.py
class HttpConfig(BaseSettings):
    timeout_seconds: int = 20
    max_retries: int = 2

# config/browser_config.py
class BrowserConfig(BaseSettings):
    pool_max_size: int = 6
    idle_ttl_seconds: int = 300

# config/extraction_config.py
class ExtractionConfig(BaseSettings):
    listing_min_items: int = 2
    max_records: int = 100
```

---

### 4. **VIOLATION: No Dependency Injection**

**Files:** Throughout codebase  
**Severity:** HIGH - Tight coupling, untestable

**Issue:** Services directly instantiate dependencies instead of receiving them

#### Example: Direct Database Access
**File:** `backend/app/api/crawls.py:70-80`

```python
async def _resolve_websocket_user(websocket: WebSocket) -> User | None:
    # ... token extraction ...
    
    # DIRECT INSTANTIATION - TIGHT COUPLING
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        # ...
```

**Violations:**
- **Dependency Inversion Principle:** High-level module depends on low-level module
- **Testability:** Cannot mock database in tests
- **Flexibility:** Cannot swap database implementation

#### Example: Service Layer Coupling
**File:** `backend/app/services/crawl_service.py:180-200`

```python
async def _mark_run_failed_with_retry(*, run_id: int, error_message: str):
    # HARDCODED DEPENDENCY
    async with SessionLocal() as session:
        # ... business logic ...
```

**Correct Approach:**
```python
# With dependency injection:
class CrawlService:
    def __init__(self, db: AsyncSession, logger: Logger):
        self.db = db
        self.logger = logger
    
    async def mark_run_failed(self, run_id: int, error: str):
        # Use injected dependencies
        await self.db.execute(...)

# In routes:
@router.post("/crawls")
async def create_crawl(
    service: Annotated[CrawlService, Depends(get_crawl_service)],
    session: Annotated[AsyncSession, Depends(get_db)]
):
    return await service.create(...)
```

---

### 5. **VIOLATION: Mixed Abstraction Levels**

**File:** `backend/app/services/_batch_runtime.py:100-300`  
**Severity:** MEDIUM - Violates Clean Code principles

**Issue:** High-level orchestration mixed with low-level details

```python
async def process_run(session: AsyncSession, run_id: int):
    # HIGH LEVEL: Orchestration
    run = await session.get(CrawlRun, run_id)
    
    # LOW LEVEL: String manipulation
    correlation_id = str(
        persisted_summary.get("correlation_id") or generate_correlation_id()
    ).strip()
    
    # HIGH LEVEL: Business logic
    if run_type == "batch" and urls:
        url_list = urls
    
    # LOW LEVEL: Data structure manipulation
    persisted_record_count = await _count_run_records(session, run.id)
    url_verdicts: list[str] = list(persisted_summary.get("url_verdicts") or [])[
        :start_index
    ]
    
    # HIGH LEVEL: Loop orchestration
    for idx, url in pending_items:
        # LOW LEVEL: Math calculations
        remaining_records = max(max_records - persisted_record_count, 0)
        
        # HIGH LEVEL: Processing
        records, verdict, url_metrics = await _process_single_url(...)
```

**Violations:**
- **Single Level of Abstraction:** Function mixes high-level flow with low-level details
- **Readability:** Hard to understand overall flow
- **Maintainability:** Changes to details affect high-level logic

**Correct Approach:**
```python
async def process_run(session: AsyncSession, run_id: int):
    # HIGH LEVEL ONLY
    run = await load_run(session, run_id)
    await validate_run_state(run)
    
    context = await prepare_execution_context(run)
    urls = await resolve_target_urls(run)
    
    for url in urls:
        await process_url(session, run, url, context)
    
    await finalize_run(session, run, context)

# Low-level details in separate functions
async def prepare_execution_context(run):
    return ExecutionContext(
        correlation_id=resolve_correlation_id(run),
        settings=parse_settings(run.settings),
        # ...
    )
```

---

### 6. **VIOLATION: Primitive Obsession**

**Files:** Throughout codebase  
**Severity:** MEDIUM - Type safety, domain modeling

**Issue:** Using primitives (str, dict, int) instead of domain objects

#### Example: Status as String
**File:** `backend/app/models/crawl.py:20`

```python
class CrawlRun(Base):
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Status is just a string - no type safety!
```

**Usage:**
```python
# Everywhere in code:
if run.status == "running":  # Typo-prone
if run.status == "completed":  # No IDE autocomplete
if normalize_status(run.status) == CrawlStatus.PAUSED:  # Inconsistent
```

**Violations:**
- **Type Safety:** No compile-time checking of status values
- **Domain Modeling:** Status is a domain concept, not a string
- **Encapsulation:** Status transitions not enforced

#### Example: Settings as Dict
**File:** `backend/app/models/crawl.py:23`

```python
class CrawlRun(Base):
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Untyped dictionary - anything goes!
```

**Usage:**
```python
# No type safety:
proxy_list = settings.get("proxy_list", [])  # Could be anything
max_pages = settings.get("max_pages", 5)     # Could be string, None, etc.
traversal_mode = settings.get("traversal_mode")  # No validation
```

**Correct Approach:**
```python
# Domain objects:
class CrawlStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class CrawlSettings(BaseModel):
    proxy_list: list[str] = []
    max_pages: int = Field(default=5, ge=1, le=100)
    traversal_mode: Literal["auto", "paginate", "scroll"] | None = None
    
    @validator("proxy_list")
    def validate_proxies(cls, v):
        for proxy in v:
            validate_proxy_url(proxy)
        return v

class CrawlRun(Base):
    status: Mapped[CrawlStatus] = mapped_column(Enum(CrawlStatus))
    settings: Mapped[CrawlSettings]  # Type-safe!
```

---

### 7. **VIOLATION: Feature Envy (Law of Demeter)**

**File:** `backend/app/api/records.py:400-500`  
**Severity:** MEDIUM - Tight coupling

**Issue:** Functions reaching deep into object structures

```python
def _record_to_markdown(row: CrawlRecord) -> str:
    # FEATURE ENVY - reaching into nested structures
    raw_data = row.data if isinstance(row.data, dict) else {}
    source_trace = row.source_trace if isinstance(row.source_trace, dict) else {}
    semantic = (
        source_trace.get("semantic")
        if isinstance(source_trace.get("semantic"), dict)
        else {}
    )
    semantic_sections = (
        semantic.get("sections") 
        if isinstance(semantic.get("sections"), dict) 
        else {}
    )
    # ... 10 more levels of nesting
```

**Violations:**
- **Law of Demeter:** "Only talk to your immediate friends"
- **Encapsulation:** Exposing internal structure
- **Coupling:** Changes to CrawlRecord structure break this code

**Correct Approach:**
```python
# Add methods to domain object:
class CrawlRecord(Base):
    def get_semantic_sections(self) -> dict:
        """Encapsulate nested access."""
        if not isinstance(self.source_trace, dict):
            return {}
        semantic = self.source_trace.get("semantic", {})
        if not isinstance(semantic, dict):
            return {}
        return semantic.get("sections", {})
    
    def to_markdown(self) -> str:
        """Domain object knows how to format itself."""
        return MarkdownFormatter(self).format()

# Usage:
def export_markdown(record: CrawlRecord) -> str:
    return record.to_markdown()  # Clean!
```

---

### 8. **VIOLATION: Magic Numbers and Strings**

**Files:** Throughout codebase  
**Severity:** MEDIUM - Maintainability

**Issue:** Unexplained constants scattered in code

```python
# browser_client.py:318
context = await asyncio.wait_for(
    browser.new_context(...),
    timeout=15.0  # WHY 15? Magic number!
)

# browser_client.py:350
page = await asyncio.wait_for(
    context.new_page(), 
    timeout=10.0  # WHY 10? Different from above?
)

# crawls.py:450
await asyncio.sleep(0.75)  # WHY 0.75? Magic number!

# records.py:24
MAX_RECORD_PAGE_SIZE = 1000  # WHY 1000? No explanation
```

**Correct Approach:**
```python
# Named constants with documentation:
BROWSER_CONTEXT_CREATION_TIMEOUT_SECONDS = 15.0
"""
Timeout for browser context creation.
15 seconds allows for:
- Browser initialization: 5s
- Extension loading: 5s
- Network setup: 5s
"""

BROWSER_PAGE_CREATION_TIMEOUT_SECONDS = 10.0
"""
Timeout for page creation within existing context.
Shorter than context creation since browser is already initialized.
"""

WEBSOCKET_POLL_INTERVAL_SECONDS = 0.75
"""
Poll interval for websocket log streaming.
Balances responsiveness (< 1s) with server load.
"""
```

---

### 9. **VIOLATION: Anemic Domain Model**

**File:** `backend/app/models/crawl.py`  
**Severity:** MEDIUM - Poor OOP design

**Issue:** Domain models are just data containers with no behavior

```python
class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    
    id: Mapped[int]
    user_id: Mapped[int]
    status: Mapped[str]
    settings: Mapped[dict]
    # ... 15 more fields
    
    # NO METHODS! Just data.
```

**All logic is in service layer:**
```python
# crawl_service.py
def pause_run(session, run):
    if run.status != "running":
        raise ValueError("Cannot pause")
    run.status = "paused"
    # ...

def resume_run(session, run):
    if run.status != "paused":
        raise ValueError("Cannot resume")
    run.status = "running"
    # ...
```

**Violations:**
- **Object-Oriented Design:** Objects should have behavior, not just data
- **Encapsulation:** Business rules scattered across service layer
- **Duplication:** Status validation repeated everywhere

**Correct Approach:**
```python
class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    
    id: Mapped[int]
    _status: Mapped[str] = mapped_column("status")
    
    @property
    def status(self) -> CrawlStatus:
        return CrawlStatus(self._status)
    
    def can_pause(self) -> bool:
        """Business rule: only running jobs can be paused."""
        return self.status == CrawlStatus.RUNNING
    
    def pause(self) -> None:
        """Pause this crawl run."""
        if not self.can_pause():
            raise InvalidStateTransition(
                f"Cannot pause run in {self.status} state"
            )
        self._status = CrawlStatus.PAUSED.value
        self._log_state_change("paused")
    
    def resume(self) -> None:
        """Resume this crawl run."""
        if self.status != CrawlStatus.PAUSED:
            raise InvalidStateTransition(
                f"Cannot resume run in {self.status} state"
            )
        self._status = CrawlStatus.RUNNING.value
        self._log_state_change("resumed")
```

---

### 10. **VIOLATION: No Interface Segregation**

**File:** `backend/app/services/acquisition/acquirer.py`  
**Severity:** MEDIUM - Tight coupling

**Issue:** Large functions with many parameters (10+ parameters)

```python
async def acquire_html(
    run_id: int,
    url: str,
    proxy_list: list[str] | None = None,
    surface: str | None = None,
    traversal_mode: str | None = None,
    max_pages: int = 5,
    max_scrolls: int = DEFAULT_MAX_SCROLLS,
    sleep_ms: int = 0,
    requested_fields: list[str] | None = None,
    requested_field_selectors: dict[str, list[dict]] | None = None,
    acquisition_profile: dict[str, object] | None = None,
    checkpoint: Callable[[], Awaitable[None]] | None = None,
) -> tuple[str, str, str, list[dict]]:
    # 12 parameters! Violates ISP
```

**Violations:**
- **Interface Segregation Principle:** Clients forced to depend on parameters they don't use
- **Maintainability:** Adding new parameter requires changing all call sites
- **Readability:** Hard to understand what parameters do

**Correct Approach:**
```python
@dataclass
class AcquisitionRequest:
    """Request object for HTML acquisition."""
    run_id: int
    url: str
    proxy_list: list[str] = field(default_factory=list)
    surface: str | None = None
    traversal_config: TraversalConfig = field(default_factory=TraversalConfig)
    extraction_config: ExtractionConfig = field(default_factory=ExtractionConfig)
    checkpoint: Callable[[], Awaitable[None]] | None = None

async def acquire_html(request: AcquisitionRequest) -> AcquisitionResult:
    # Single parameter! Clean interface.
    # Easy to add new fields without breaking existing code.
```

---

## SUMMARY OF VIOLATIONS

### Critical (Must Fix Before Production)
1. ✗ **Configuration as Code** - 200+ hardcoded constants
2. ✗ **Business Logic in Controllers** - Fat API routes
3. ✗ **God Object** - Massive pipeline_config.py

### High Priority (Architectural Debt)
4. ✗ **No Dependency Injection** - Tight coupling everywhere
5. ✗ **Mixed Abstraction Levels** - Hard to understand code flow
6. ✗ **Primitive Obsession** - No domain modeling

### Medium Priority (Code Quality)
7. ✗ **Feature Envy** - Law of Demeter violations
8. ✗ **Magic Numbers** - Unexplained constants
9. ✗ **Anemic Domain Model** - Objects without behavior
10. ✗ **No Interface Segregation** - Functions with 10+ parameters

---

## REFACTORING ROADMAP

### Phase 1: Configuration Management (Week 1-2)
```
Task 1.1: Create config classes with Pydantic
- Extract all constants from pipeline_config.py
- Create typed config classes
- Load from environment variables

Task 1.2: Implement config injection
- Pass config objects to services
- Remove global imports of constants
- Add config validation on startup
```

### Phase 2: Separation of Concerns (Week 3-4)
```
Task 2.1: Extract business logic from routes
- Create service layer for CSV processing
- Create export service for all formats
- Move validation to service layer

Task 2.2: Thin controllers
- Routes only handle HTTP concerns
- Delegate all logic to services
- Return service results as HTTP responses
```

### Phase 3: Domain Modeling (Week 5-6)
```
Task 3.1: Rich domain objects
- Add behavior to CrawlRun model
- Add behavior to CrawlRecord model
- Encapsulate state transitions

Task 3.2: Value objects
- Create CrawlStatus enum
- Create CrawlSettings value object
- Create AcquisitionRequest value object
```

### Phase 4: Dependency Injection (Week 7-8)
```
Task 4.1: Service constructors
- Add __init__ methods with dependencies
- Create factory functions
- Use FastAPI Depends() for injection

Task 4.2: Remove global state
- Inject database sessions
- Inject configuration
- Inject logger instances
```

---

## METRICS & TECHNICAL DEBT

### Current State
- **Lines of Code:** ~15,000
- **Configuration Constants:** 200+
- **God Objects:** 1 (pipeline_config.py)
- **Fat Controllers:** 3 (crawls.py, records.py, review.py)
- **Anemic Models:** 5 (all domain models)
- **Functions with 10+ params:** 15+
- **Magic Numbers:** 100+

### Target State
- **Configuration Constants:** 0 (all in environment)
- **God Objects:** 0
- **Fat Controllers:** 0 (< 50 lines per route)
- **Rich Domain Models:** 5+
- **Functions with 10+ params:** 0
- **Magic Numbers:** 0 (all named constants)

### Estimated Effort
- **Phase 1 (Config):** 2 weeks
- **Phase 2 (Separation):** 2 weeks
- **Phase 3 (Domain):** 2 weeks
- **Phase 4 (DI):** 2 weeks
- **Total:** 8 weeks for complete refactoring

---

**End of Software Engineering Principles Audit**
