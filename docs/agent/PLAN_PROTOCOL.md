# Plan Protocol

Agents and humans follow this protocol for any non-trivial task.
**Non-trivial = more than one file changed, OR a new behavior introduced, OR a bug fix
that touches more than one subsystem.**

For tiny fixes (single function, single file, obvious change): just do it, run tests, done.

---

## Creating a Plan

When assigned a non-trivial task:

1. Check `docs/plans/ACTIVE.md` — if a plan is already active, continue it instead of starting a new one unless the user explicitly assigns a new task.
2. Create `docs/plans/[short-slug]-plan.md` using the template below.
3. Update `docs/plans/ACTIVE.md` to point to the new file.
4. State the plan to the user (goal + slices) and wait for confirmation before writing any code.

### Plan File Template

```markdown
# Plan: [Title]

**Created:** YYYY-MM-DD
**Agent:** [Codex | Opus | Gemini | Claude]
**Status:** IN PROGRESS | BLOCKED | DONE
**Touches buckets:** [list ownership buckets this plan modifies]

## Goal

One paragraph. What problem does this solve and what does done look like?

## Acceptance Criteria

- [ ] Specific, testable outcome 1
- [ ] Specific, testable outcome 2
- [ ] `python -m pytest tests -q` exits 0

## Do Not Touch

Files and modules out of scope — with reason:
- `[file]` — reason

## Slices

### Slice 1: [Name]
**Status:** TODO | IN PROGRESS | DONE
**Files:** list files to change
**What:** specific instructions
**Verify:** command or observable outcome to confirm done

### Slice 2: [Name]
...

## Doc Updates Required

- [ ] `docs/backend-architecture.md` — section/reason
- [ ] `docs/CODEBASE_MAP.md` — if new files added or moved
- [ ] `docs/INVARIANTS.md` — if a contract changed
- [ ] `docs/ENGINEERING_STRATEGY.md` — if a new anti-pattern was discovered

## Notes

Running notes as execution proceeds: blockers, decisions made, things discovered.
```

---

## Executing a Plan

- Work one slice at a time. Do not skip ahead.
- After each slice: run the slice's verify step.
- Mark the slice `DONE` before moving to the next.
- If a slice is blocked: mark it `BLOCKED`, write the blocker in Notes, surface it to the user.
- Do not add scope that was not in the plan. If new work is needed, add a new slice and note it.

---

## Closing a Plan

Before marking a plan `DONE`:

1. All acceptance criteria are checked off.
2. `python -m pytest tests -q` passes.
3. All "Doc Updates Required" items are completed.
4. Update `docs/plans/ACTIVE.md` to reflect completion (or point to next plan).

---

## ACTIVE.md Format

```markdown
# Active Plan

**Current:** [plan title] → `docs/plans/[slug]-plan.md`
**Status:** IN PROGRESS
**Started:** YYYY-MM-DD
**Last slice completed:** Slice N — [name]

## Queue
1. [next plan title] — not yet started
```

When no plan is active:

```markdown
# Active Plan

No active plan.
```

---

## Historical Plans

Completed plan files stay in `docs/plans/` permanently. They explain why things are the
way they are. Do not delete them. Do not clean up their notes sections.

---

## Agent Handoff Pattern

When one agent hands off to another mid-plan:

1. The outgoing agent marks the current slice as `IN PROGRESS` with a note explaining exactly where it stopped and why.
2. The incoming agent reads `docs/plans/ACTIVE.md` → the plan file → the notes section before writing any code.
3. The incoming agent does NOT restart from scratch or re-plan. It continues from the noted slice.