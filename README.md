# CrawlerAI

> Deterministic web acquisition, extraction, and review system for ecommerce, jobs, automobiles, and tabular targets.

**Disclaimer:** This tool is for educational and research purposes only. Users must comply with the Terms of Service of any target website.

## What It Does

CrawlerAI is a research-first crawling framework that prioritizes deterministic extraction over LLM inference. It acquires pages using an HTTP-first strategy with browser escalation when needed, then extracts structured data through a tiered pipeline: known-platform adapters, structured source mining (JSON-LD, Open Graph, network payloads), and finally DOM traversal. LLM backfill is opt-in and only fills missing fields.

## Architecture

| Layer | Stack |
|-------|-------|
| Frontend | Next.js 16, React 19, Tailwind CSS, Radix UI |
| API | FastAPI, Uvicorn, Pydantic |
| Workers | Celery + Redis |
| Database | PostgreSQL (asyncpg), SQLAlchemy, Alembic |
| Browser | Playwright (patchright), BrowserForge fingerprints |
| Extraction | BeautifulSoup, selectolax, lxml, extruct |
| Observability | structlog, prometheus-client |

### Extraction Pipeline

```
URL -> Adapter (known platform) -> Structured Source (JSON-LD/OG/payload)
                                    -> DOM traversal -> Confidence scoring
                                    -> LLM backfill (opt-in, gaps only)
```

## Project Structure

```
backend/
  app/
    api/          FastAPI routes and dependencies
    core/         Config, security, logging, DB engine
    data/         Extraction, acquisition, adapters, selectors
  tests/          Unit, integration, and smoke tests
  alembic/        Database migrations
frontend/
  app/            Next.js App Router pages
  components/     React components (crawl, layout, selectors)
  lib/            API clients, utilities, constants
docs/
  INVARIANTS.md   Hard runtime contracts
  CODEBASE_MAP.md File and subsystem ownership
  BUSINESS_LOGIC.md User-visible decision rules
  ENGINEERING_STRATEGY.md Architecture constraints
  plans/          Active and archived work plans
```

## Prerequisites

- Python >= 3.12
- Node.js >= 20
- PostgreSQL >= 15
- Redis >= 7

## Setup

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env with your database, Redis, and secret values
```

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"   # Windows
.venv/bin/pip install -e ".[dev]"       # Linux/macOS

# Initialize database
.venv\Scripts\python init_db.py
```

### 3. Frontend

```bash
cd frontend
npm install
```

## Running Locally

### Windows (shortcut)

```bash
start.bat
```

### Manual

```bash
# Terminal 1 — Backend
cd backend
.venv\Scripts\python run_dev_server.py

# Terminal 2 — Frontend
cd frontend
npm run dev
```

The API runs at `http://127.0.0.1:8000` and the frontend at `http://127.0.0.1:3000`.

## Testing

### Backend

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

### Frontend

```bash
cd frontend
npm run test           # Unit tests (Vitest)
npm run test:e2e       # Playwright E2E
npm run lint
```

## Key Design Principles

- **HTTP first, browser second.** Only escalate to Playwright when anti-bot or JS rendering is required.
- **Deterministic extraction before LLM.** Structured sources and DOM selectors are preferred; LLM is a backfill gap-filler.
- **Config lives in `app/services/config/*`, not service code.**
- **Fix upstream, not downstream.** Bugs in acquisition or extraction are fixed at the source, not compensated for in publishers or exports.

## License

See repository for license details.
