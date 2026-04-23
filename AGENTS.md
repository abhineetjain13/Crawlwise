# AGENTS.md — CrawlerAI Session Bootstrap

Attach this file at session start. Use it to route into the right canonical doc.
Do not preload the whole doc stack for small tasks.
Speak tersely in caveman style: short, direct, low-fluff sentences; keep technical accuracy and full task context.

---

## What This Project Is

CrawlerAI is a deterministic crawl, extraction, review, and export system for ecommerce, jobs, automobiles, and tabular targets.

- Backend: FastAPI + PostgreSQL + Redis + Celery + Playwright
- Frontend: Next.js
- Extraction order: adapter -> structured source -> DOM
- LLM is opt-in backfill only, never the primary extractor

---

## Default Startup Flow

Before coding:

1. Check `docs/plans/ACTIVE.md`.
2. Identify the owning area from `docs/CODEBASE_MAP.md` if file ownership is unclear.
3. Read only the canonical doc that matches the task.
4. Grep before adding code: `grep -r "concept_or_function_name" backend/app`

Do not read every project doc by default.
Read more only when the task crosses subsystem boundaries or changes shared behavior.

---

## Read-On-Demand Guide

Read these only when relevant:

- `docs/INVARIANTS.md`
  Read for extraction, acquisition, persistence, selector memory, LLM gating, config placement, or any shared runtime contract.
- `docs/CODEBASE_MAP.md`
  Read when ownership is unclear, when moving files, or before creating a new file.
- `docs/BUSINESS_LOGIC.md`
  Read when changing user-visible behavior, run shaping, verdicts, routing, review flows, or output semantics.
- `docs/ENGINEERING_STRATEGY.md`
  Read when refactoring, adding structure, or touching shared architecture. Pay attention to AP-12 through AP-15.
- `docs/agent/SKILLS.md`
  Read when the task matches an existing recipe.
- `docs/backend-architecture.md`
  Read for backend subsystem detail not covered above.
- `docs/frontend-architecture.md`
  Read for frontend structure or UI flow changes.
- `docs/agent/PLAN_PROTOCOL.md`
  Read only when creating or repairing a plan.

---

## Always-On Rules

1. Config does not live in service code.
   Strings, thresholds, tokens, field names, and runtime tunables belong in `app/services/config/*`.

2. Fix upstream, not downstream.
   Do not compensate in `publish/*`, `pipeline/*`, or exports for bugs caused in acquisition or extraction.

3. Grep before adding.
   Extend or consolidate existing code before creating a new function, class, file, or config source.

4. One concern, one owner.
   If a change does not clearly belong to an existing subsystem, stop and identify the owning file from `docs/CODEBASE_MAP.md`.

5. Delete before adding.
   Remove duplication, dead branches, compat shims, or now-redundant logic as part of the change.

6. Respect explicit user controls.
   Do not silently rewrite `surface`, traversal intent, proxy settings, or `llm_enabled`.

7. LLM is explicit and degradable.
   It only runs when enabled by both run settings and active config. It fills gaps; it does not replace deterministic extraction.

8. Do not attach stale docs.
   Ignore archived audits and abandoned plans unless the task explicitly asks for historical review.

9. Keep responses terse.
   Prefer caveman-style brevity: less filler, fewer words, same meaning.

---

## Extraction Warning

Do not redesign the detail candidate system in `detail_extractor.py`.
It is already field-by-field and correct.

If the task is about missing ecommerce variants or price gaps, read `docs/INVARIANTS.md` Rule 3 first.
Known root causes already documented there:

- early exit before DOM tier when variant DOM cues exist
- JS state mapper returning after the first object
- backfill calls skipped on early return paths

Fix those in place before adding browser interaction or downstream fallbacks.

---

## Plans

- `docs/plans/ACTIVE.md` is the only start point for plan state.
- If the active plan is `COMPLETE`, do not keep treating it as active work.
- A slice is not done until its verify step passes.
- Do not open a new plan for a problem already covered by an unverified plan.

---

## Quick Task Routing

- Small/local bugfix or UI tweak:
  Check `docs/plans/ACTIVE.md`, then inspect code directly. Open other docs only if ownership or behavior is unclear.
- New behavior or contract change:
  Read `docs/BUSINESS_LOGIC.md` and any relevant section of `docs/INVARIANTS.md`.
- Refactor or file creation:
  Read `docs/CODEBASE_MAP.md` and `docs/ENGINEERING_STRATEGY.md`.
- Extraction/acquisition bug:
  Read `docs/INVARIANTS.md`, then `docs/agent/SKILLS.md` if needed.
- Plan work:
  Read `docs/plans/ACTIVE.md` and the pointed plan file. Open `docs/agent/PLAN_PROTOCOL.md` only if the plan needs to be created or repaired.

---

## Verify Commands

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Run the smallest relevant verify step for the slice, then run broader verification when the change affects shared behavior.

---

## Canonical Docs

- `AGENTS.md` — session bootstrap only
- `docs/INVARIANTS.md` — hard runtime contracts
- `docs/CODEBASE_MAP.md` — file and bucket ownership
- `docs/BUSINESS_LOGIC.md` — user-visible decision rules
- `docs/ENGINEERING_STRATEGY.md` — engineering constraints and anti-patterns
- `docs/backend-architecture.md` — backend reference
- `docs/frontend-architecture.md` — frontend reference
- `docs/agent/SKILLS.md` — task recipes
- `docs/agent/PLAN_PROTOCOL.md` — planning workflow
- `docs/plans/ACTIVE.md` — current plan pointer

Do not create a new doc unless none of the canonical docs can absorb the information cleanly.
