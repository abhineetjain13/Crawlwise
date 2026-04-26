# CrawlerAI-Advanced-Automation-Engine.

**Disclaimer:** This tool is for educational and research purposes only. The authors are not responsible for any misuse of this tool. Users must comply with the Terms of Service of any target website.

Research-first crawler framework for studying modern web acquisition, anti-bot resilience, and deterministic extraction quality.

## Research Focus

- Acquisition strategy under bot pressure: HTTP first, browser escalation when needed.
- Browser surface hardening and fingerprint coherence testing.
- Deterministic extraction pipeline across ecommerce, jobs, autos, and tabular pages.
- Structured source and network payload mining before expensive DOM fallback.
- Measured, opt-in LLM backfill for missing fields only.

## High-Level Architecture

- Backend: FastAPI, PostgreSQL, Redis, Celery, Playwright.
- Frontend: Next.js.
- Core extraction order: adapter -> structured source -> DOM.
- Runtime control: env-driven settings and config modules under `backend/app/services/config/*`.

## Key Technical Areas

- Acquisition:
  - Shared HTTP client + retry/backoff + proxy orchestration.
  - Browser runtime pool and challenge recovery.
  - Network payload capture/classification with payload budgets and noise filtering.
- Fingerprinting:
  - BrowserForge identity generation.
  - Runtime coherence patches for navigator/webgl/canvas/audio/fonts/intl/permissions/performance.
  - Surface probe tooling for anti-bot benchmark sites.
- Extraction:
  - Adapter registry for known platforms.
  - Multi-tier detail extraction with confidence scoring and early-exit guardrails.
  - Listing extraction with candidate ranking, network backfill, and selector memory hooks.

## Repository Layout

- `backend/` API, workers, acquisition, extraction, adapters, tests.
- `frontend/` UI and operator workflows.
- `docs/` architecture, invariants, plans, and research notes.

## Local Verify (Backend)

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```
