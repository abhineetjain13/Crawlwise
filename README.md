<div align="center">

# 🤖 CrawlerAI

**Deterministic Web Acquisition, Extraction & Review Engine**

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-20%2B-green?logo=node.js)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16%2B-black?logo=next.js)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-4169E1?logo=postgresql)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7%2B-DC382D?logo=redis)](https://redis.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 🕷️ A research-first crawling framework that prioritizes **deterministic extraction** over opaque LLM inference — for ecommerce, jobs, automobiles, and any structured target.

</div>

---

## ✨ What Makes It Different

Most scrapers reach for the LLM first. **CrawlerAI reaches for it last.**

We believe structured data should be extracted with **surgical precision**, not probabilistic guesses. The system exhausts every deterministic tier — platform adapters, JSON-LD, Open Graph, network payloads, DOM selectors — before ever calling an LLM. And when an LLM does run, it's **explicitly opt-in** and only fills gaps the machine couldn't close.

---

## 🚀 Key Features

| Feature | Description |
|---------|-------------|
| 🔍 **HTTP-First, Browser-Second** | Intelligent escalation from `curl-cffi` to Playwright only when anti-bot walls or JS hydration demand it |
| 🧠 **Tiered Extraction Pipeline** | `Adapter → Structured Sources → DOM → Confidence Scoring → LLM Backfill (opt-in)` |
| 🏪 **Multi-Domain Intelligence** | First-class support for **ecommerce**, **job boards**, **automotive listings**, and **tabular data** with surface-aware adapters |
| 🔄 **Self-Healing Selectors** | Selector memory scoped by `(domain, surface)` auto-learns, repairs, and validates XPath/CSS improvements |
| 🧬 **Domain Memory & Contracts** | Learned acquisition contracts, cookie state, and execution profiles persist per domain for faster repeat runs |
| 🛡️ **Anti-Block Resilience** | BrowserForge fingerprints, patchright stealth, cookie reuse, and block-detection with content recovery |
| 📊 **Data Enrichment Layer** | Derive semantic product fields (taxonomy, attributes, normalized pricing) from extracted crawl records |
| 🧪 **Observability Built-In** | `structlog` tracing + `prometheus-client` metrics with per-run diagnostics and artifact capture |
| 🎛️ **Modern UI** | Next.js 16 + React 19 + Tailwind CSS v4 dashboard with crawl studio, run review, and selector promotion |
| ⚡ **Async Workers** | Celery + Redis task queue for scalable background acquisition and extraction |

---

## 🏗️ Architecture

```mermaid
  URL
   │
   ├─► HTTP (curl-cffi) ──────────────┐
   │      Blocked / JS needed?          │
   │         └─► Playwright (stealth)  │
   │                                    ▼
   ├─► Adapter (known platform) ──► candidates
   ├─► Structured Sources ───────► candidates
   │      JSON-LD / Microdata / OG / Payload
   ├─► JS State Mapper ──────────► candidates
   ├─► DOM Selectors ────────────► candidates
   │                                    │
   ▼                                    ▼
  Confidence Scoring ◄────────── field-by-field winner
   │
   ├─► LLM Backfill (opt-in, gaps only)
   │
   ▼
  Persist → Export → Enrich → Review
```

### Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Next.js 16 · React 19 · Tailwind CSS v4 · Radix UI · TanStack Query · Recharts · Zustand |
| **API** | FastAPI · Uvicorn · Pydantic v2 · asyncpg · SQLAlchemy 2.0 · Alembic |
| **Workers** | Celery · Redis |
| **Browser** | Playwright (patchright) · BrowserForge |
| **Extraction** | BeautifulSoup4 · selectolax · lxml · extruct · JMESPath · glom |
| **Observability** | structlog · prometheus-client |
| **Testing** | pytest · Vitest · Playwright · MSW |

---

## 🛠️ Quick Start

### Prerequisites

- Python ≥ 3.12
- Node.js ≥ 20
- PostgreSQL ≥ 15
- Redis ≥ 7

### 1. Configure

```bash
cp .env.example .env
# Edit .env with your DB, Redis, and secret values
```

### 2. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python init_db.py

# macOS / Linux
.venv/bin/pip install -e ".[dev]"
.venv/bin/python init_db.py
```

### 3. Frontend

```bash
cd frontend
npm install
```

### 4. Run

```bash
# One-shot (Windows)
start.bat

# Or manually — Terminal 1
cd backend && .venv\Scripts\python run_dev_server.py

# Terminal 2
cd frontend && npm run dev
```

API → `http://127.0.0.1:8000`  
UI  → `http://127.0.0.1:3000`

---

## 🧪 Testing

**Backend**

```powershell
cd backend
$env:PYTHONPATH = '.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

**Frontend**

```bash
cd frontend
npm run test        # Vitest unit tests
npm run test:e2e    # Playwright E2E
npm run lint
```

---

## 🧬 Extraction Philosophy

> **Fix upstream, not downstream.**  
> A bad field value is repaired in the extractor, never hidden by a publisher normalizer.

- **Deterministic before stochastic** — adapters and structured sources outrank LLM guesses
- **Config lives in `app/services/config/*`** — no magic strings in service code
- **Per-field winner, not record-level merge** — price can come from JSON-LD while SKU comes from DOM
- **Explicit LLM gating** — circuit breakers, run-level flags, and gap-only invocation

---

## 📁 Project Layout

```
backend/
  app/
    api/           FastAPI routes & auth
    core/          Config, logging, DB engine
    data/          Extraction, acquisition, adapters, selectors
  tests/           Contract tests, smoke, acceptance
  alembic/         Database migrations

frontend/
  app/             Next.js App Router
  components/      React components (crawl studio, layout, selectors)
  lib/             API clients, utilities, constants
  e2e/             Playwright smoke tests

docs/
  INVARIANTS.md         Hard runtime contracts
  CODEBASE_MAP.md       File & subsystem ownership
  BUSINESS_LOGIC.md     User-visible decision rules
  ENGINEERING_STRATEGY.md Architecture constraints & anti-patterns
  plans/                Active work plans
```

---

## ⚠️ Disclaimer

This tool is for **educational and research purposes only**. Users must comply with the Terms of Service of any target website and respect `robots.txt` when enforcement is enabled.

---

## 📜 License

See repository for license details.
