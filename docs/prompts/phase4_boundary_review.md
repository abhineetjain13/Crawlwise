You are performing a Phase 4 BOUNDARY REVIEW for an in-progress backend refactor program.

Your job is to decide whether the supplied module or helper bundle is owned by the correct stage, or whether behavior should move to a different stage owner based on the actual code in the evidence pack.

You are not implementing code.
You are not allowed to recommend generic "shared utils" extraction.

CONTEXT
This review is for a bounded refactor slice where stage ownership is the primary concern.

The refactor program prefers:
- one explicit owner per behavior
- orchestration-only pipeline modules
- stable canonical homes
- deletion of stale seams instead of wrapper accumulation
- strict stage boundaries across `acquire -> discover -> extract -> normalize -> publish`

IMPORTANT RULES
- The supplied evidence pack wins over assumptions.
- Do NOT give generic layering advice.
- Do NOT propose a broad framework rewrite.
- Do NOT recommend moving discover-owned parsing into extract.
- Do NOT recommend moving persistence or verdict logic back into pipeline.
- Every ownership claim must cite specific functions/helpers and the exact behavior they perform.
- Distinguish orchestration glue from real business logic.
- Distinguish extraction behavior from output shaping and persistence behavior.
- If evidence is insufficient, say exactly: INSUFFICIENT EVIDENCE.

PRIMARY TASK
Using only the supplied files and evidence pack, decide:
- whether the target module is owned by the correct stage
- which helper groups, if any, belong to a different owner
- whether the cleanest next step is to keep, split, move, or defer
- what must explicitly stay with the current owner

REQUIRED OUTPUT FORMAT
Output ONLY in the format below.

# Phase 4 Boundary Review
## Scope
- Target slice or concern:
- Files reviewed:
- Boundary being tested:

## Executive Decision
- Verdict: CLEAN / MINOR OWNERSHIP DRIFT / HARMFUL OWNERSHIP DRIFT
- Primary reason:
- Should this module move now? YES / NO

## Function Ownership Findings
For each meaningful helper or helper group, use this exact structure:

### Helper N
- Function or group:
- Current owner:
- Recommended owner:
- Why the current owner is correct or incorrect:
- Evidence from the supplied files:
- Action: keep as-is / move / split / defer
- What must not move with it:

## Canonical Ownership Table
- Behavior:
- Chosen owner:
- Why this owner is correct:
- Files that should stop owning it:

## Refactor Guardrails
- Boundary moves that should happen now:
- Boundary moves that should wait:
- Anti-patterns to avoid:

## Final Recommendation
Use exactly one of:
- KEEP IN PIPELINE
- SPLIT IN CURRENT SLICE
- DEFER WITHOUT MOVING

Then add:
- Reason:
- First 3 concrete next actions:

If you cannot meet that standard with the supplied evidence, say:
INSUFFICIENT EVIDENCE
and then provide only the missing-evidence list.
