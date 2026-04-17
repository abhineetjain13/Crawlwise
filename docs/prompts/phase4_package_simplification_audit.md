# Gemini Prompt: Slice Codemap And Simplification Map

Use this prompt to make Gemini do the investigative work for one backend slice.

The goal is not a generic audit.
The goal is to force Gemini to build a usable codemap for that slice so another coding agent can simplify it with confidence.

## Best upload pattern

Upload one coherent slice at a time:
- one service package such as `acquisition/`, `extract/`, `pipeline/`, `normalizers/`, or `config/`
- 2-6 collaborator files outside that package if they are direct dependencies
- 2-5 relevant test files
- optionally `docs/plans/2026-04-17-backend-refactor-program-tracker.md`

## Paste this into Gemini AI Studio

```text
I uploaded a bounded backend slice. Build a detailed codemap and simplification map for only the uploaded files.

You are acting like a senior software architect delegating investigative work to a junior engineer.
Do not implement code. Do not give generic advice. Produce structured repo intelligence that another coding agent can use to simplify the code safely.

Primary objective:
- explain how this slice actually works today
- identify where responsibilities are mixed or duplicated
- identify what should stay, what should move, what should shrink, and what should be deleted
- produce a codemap that is specific enough to guide implementation

Context:
- this backend is being simplified around stage boundaries: acquire -> discover -> extract -> normalize -> publish
- we care about SOLID, DRY, KISS, and YAGNI
- architecture may already be better than before, so do not recommend movement unless the uploaded files show a real problem
- simplification is more important than decomposition theater

Rules:
- Use only the uploaded files.
- Cite exact files, classes, and functions.
- Do not recommend a broad rewrite.
- Do not suggest generic shared utils.
- Do not pad the answer with clean-code filler.
- Distinguish actual business logic from orchestration glue.
- Distinguish acceptable complexity from harmful complexity.
- If evidence is insufficient, say exactly: INSUFFICIENT EVIDENCE.

Return exactly this shape:

# Slice Codemap
## 1. Slice Purpose
- What this slice is supposed to own:
- What it actually owns today:
- Main mismatch, if any:

## 2. File Inventory
For each important uploaded production file:
- File:
- Primary role:
- Secondary roles it also carries:
- Key entry points:
- Main downstream dependencies:
- Main upstream callers if visible:
- Classification: cohesive / orchestrator / mixed-responsibility / duplicate-strategy / stale-seam

## 3. Responsibility Matrix
List the main behaviors/rules in the uploaded files.
For each behavior:
- Behavior:
- Current owner:
- Correct owner:
- Why:
- Keep / move / split / delete / defer

## 4. Flow Map
Describe the major runtime flows visible in the uploaded files.
For each flow:
- Flow name:
- Start point:
- Main steps:
- Files/functions crossed:
- Where understanding breaks down because of indirection or branching:

## 5. Dependency And Coupling Map
- Tight couplings:
- Suspicious cross-stage dependencies:
- Files that know too much about neighbors:
- Files that act as hidden policy hubs:

## 6. Simplification Targets
List the top simplification targets in priority order.
For each target:
- Rank:
- File/function/helper group:
- Problem type: branch explosion / duplicated policy / stale seam / mixed concern / helper indirection / data-shape churn / config-as-behavior / test-coupled structure
- Why it increases confusion:
- Smallest high-value simplification:
- Expected payoff:
- Risk level:

## 7. Deletion Candidates
- Dead seam or compatibility layer:
- Why it looks deletable:
- What would need verification before deletion:

## 8. Test Risk Map
Using only uploaded tests:
- Tests that protect good behavior:
- Tests that look coupled to internals:
- Tests that likely preserve bad structure:
- Missing stable seam coverage:

## 9. Recommended Next Work
- First simplification slice:
- Second simplification slice:
- Third simplification slice:
- Things to explicitly leave alone for now:

## 10. Questions For Follow-Up
- Unknown 1:
- Unknown 2:
- Unknown 3:

If the uploaded files are insufficient, say exactly:
INSUFFICIENT EVIDENCE
and then list the missing files or missing context.
```
