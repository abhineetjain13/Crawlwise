# Session Prompts

Copy-paste these at the start of each session. Fill in the `[bracketed]` parts.
Always attach `CLAUDE.md` alongside any of these prompts.

---

## PROMPT: Start a New Session (Generic)

```
Read CLAUDE.md fully before responding.
Then read docs/CODEBASE_MAP.md and docs/ENGINEERING_STRATEGY.md.
Then check docs/plans/ACTIVE.md.

If there is an active plan, tell me which slice we are on and what the next action is.
If there is no active plan, wait for me to assign a task.

Do not write any code yet.
```

---

## PROMPT: Fix a Bug

```
Read CLAUDE.md, docs/CODEBASE_MAP.md, and docs/agent/SKILLS.md before responding.

Bug: [describe the bug — what's wrong, what surface/field/URL is affected, what the
actual vs expected output is]

Steps:
1. Identify which extraction stage produces the bad value (trace upstream, not downstream).
2. Show me your diagnosis before writing any code.
3. Follow the "Fix an Extraction Bug" skill from docs/agent/SKILLS.md.
4. Write a failing test first if the bug is in extraction behavior.
5. Fix it, run `pytest tests -q`, confirm passing.
6. Update the plan if one is active.

Do not add compensating logic in pipeline/core.py, publish/, or pipeline/persistence.py.
```

---

## PROMPT: Build a Feature

```
Read CLAUDE.md, docs/CODEBASE_MAP.md, docs/ENGINEERING_STRATEGY.md, and
docs/agent/PLAN_PROTOCOL.md before responding.

Feature: [describe the feature]

Steps:
1. Identify which ownership buckets this feature touches.
2. Draft a plan using the template in docs/agent/PLAN_PROTOCOL.md.
3. Present the plan (goal + slices + do-not-touch list) before writing any code.
4. Wait for my confirmation.
5. Then execute slice by slice, running tests after each slice.

Anti-patterns to watch for: read docs/ENGINEERING_STRATEGY.md Anti-Patterns section.
```

---

## PROMPT: Create a Plan (Planning Session Only)

```
Read CLAUDE.md, docs/CODEBASE_MAP.md, and docs/agent/PLAN_PROTOCOL.md.

Task: [describe the task]

Produce a plan document only — no code. Use the template from PLAN_PROTOCOL.md.
Include:
- Which ownership buckets are touched
- Slices with specific file lists
- An explicit "Do Not Touch" list
- Acceptance criteria with a pytest command
- Which canonical docs need updating when done

Output the plan as a markdown block. I will save it to docs/plans/[slug]-plan.md.
```

---

## PROMPT: Run an Audit / Code Review

```
Read CLAUDE.md, docs/CODEBASE_MAP.md, docs/ENGINEERING_STRATEGY.md, and docs/INVARIANTS.md.

Audit scope: [subsystem name or file list — e.g., "Bucket 3: Acquisition" or
"all files touched in the last plan"]

For each finding, report:
- File + line number (exact, not approximate)
- Which principle or anti-pattern it violates (reference ENGINEERING_STRATEGY.md by AP number)
- Severity: BLOAT | BUG | DRIFT | MINOR
- Specific fix (not "consider refactoring" — say exactly what to do)

Score each ownership bucket 1–10 on: correctness, ownership clarity, test coverage, doc accuracy.
Do not report findings you are not confident about. Be forensic, not comprehensive.
```

---

## PROMPT: Continue an Active Plan

```
Read CLAUDE.md and docs/plans/ACTIVE.md. Then read the full active plan file it points to.

Tell me:
1. Which slice we are on and its current status.
2. What the next action is (specific file + what to change).
3. Any blockers noted in the plan.

Then execute the next slice. Run the slice's verify step when done. Mark it DONE in the plan.
Do not start the next slice without confirming with me.
```

---

## PROMPT: Clean Up / Delete Dead Code

```
Read CLAUDE.md and docs/CODEBASE_MAP.md.

Target: [file, symbol, or subsystem to clean up]

Steps:
1. Grep for all callers of the target symbol across backend/app.
2. List every caller — if any are live callers (not private test imports), stop and tell me.
3. If zero live callers: delete the symbol and any tests that only tested its internals.
4. Run `pytest tests -q` — confirm passing.
5. Remove any references in canonical docs.
6. Do NOT leave re-export stubs at the old location.
```

---

## PROMPT: Update Docs After Implementation

```
Read CLAUDE.md and docs/agent/SKILLS.md (the "Update Docs After Implementation" skill).

What changed: [describe what was implemented — which files, what behavior, which contracts]

Update only the docs that the skill specifies for what changed. Do not add new sections
for small changes. Do not update CHANGELOG. Do not duplicate content across docs.

After updating, show me a diff summary of what changed in each doc.
```

---

## PROMPT: Gemini — Full Codebase Analysis

```
Read docs/CODEBASE_MAP.md in full. This tells you the complete file layout and ownership buckets.

Analysis task: [what to analyze — e.g., "find all violations of AP-3 cross-bucket field aliases"
or "identify files that have grown beyond one clear responsibility"]

For each finding:
- Exact file path and line range
- Which anti-pattern or principle it violates
- Severity
- Recommended fix

Do not surface findings you cannot cite with an exact file + line.
Group findings by ownership bucket.
```

---

## Notes on Prompt Usage

- **For Codex:** Use "Fix a Bug", "Build a Feature", or "Continue an Active Plan". Codex is best for mechanical implementation once a plan exists.
- **For Opus:** Use "Run an Audit", "Create a Plan", or "Build a Feature" when architecture judgment is needed.
- **For Gemini:** Use "Full Codebase Analysis" for wide-scan audits across many files.
- **For Claude:** Use "Create a Plan" or prompt engineering tasks.

Always attach `CLAUDE.md`. For implementation sessions also attach the active plan file from `docs/plans/`.
For audit sessions also attach `docs/ENGINEERING_STRATEGY.md` and `docs/INVARIANTS.md`.