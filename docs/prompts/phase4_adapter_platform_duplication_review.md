You are performing a Phase 4 DUPLICATION AND CANONICAL-HOME REVIEW for an in-progress backend refactor program.

Your job is to identify concrete duplication within a bounded slice and decide the single canonical home for each repeated helper, heuristic, or policy.

You are not implementing code.
You are not allowed to recommend generic "shared utils" consolidation.

CONTEXT
This review is specifically about adapter and platform strategy duplication.
The local evidence already says the remaining pending point is:
- consolidate platform fingerprinting into a single family-based detector scoped to the minimum required families

The refactor program prefers:
- one explicit owner per rule
- stable canonical homes
- deletion of duplicate copies
- no generic dumping-ground utility modules
- family-based platform handling only where it is actually required

IMPORTANT RULES
- The supplied evidence pack wins over assumptions.
- Repeated adapter interface methods do not automatically mean harmful duplication.
- Adapter-local extraction logic may stay duplicated when it is platform-specific.
- Repeated family detection, domain matching, HTML marker checks, and registry-routing heuristics count as duplication if they express the same routing rule in multiple places.
- Invariant 29 applies: generic crawler paths stay generic; platform behavior must stay family-based and minimized to the required families.

STRICT REVIEW BEHAVIOR
- Do NOT give generic DRY advice.
- Do NOT propose a broad adapter framework rewrite.
- Do NOT recommend moving extraction behavior into platform policy.
- Every duplication claim must cite specific files and the exact repeated routing rule.
- Distinguish acceptable platform-specific extraction logic from harmful repeated platform detection logic.
- If evidence is insufficient, say exactly: INSUFFICIENT EVIDENCE.

PRIMARY TASK
Given the supplied files and evidence pack, decide:
- whether adapter `can_handle()` logic is duplicating the same platform-family detection that already exists in platform policy
- which platform detection rules should stay in `app.services.platform_policy`
- which adapter checks should become thin delegations over the canonical detector
- which repeated heuristics must stay adapter-local because they are extraction-specific, not routing-specific

REQUIRED OUTPUT FORMAT
Output ONLY in the format below.

# Phase 4 Duplication Review
## Scope
- Target slice or concern:
- Files reviewed:
- Duplicate cluster being reviewed:

## Executive Decision
- Verdict: CLEAN / MINOR DUPLICATION / HARMFUL DUPLICATION
- Primary reason:
- Is canonical-home action required now? YES / NO

## Duplication Findings
For each duplicate cluster, use this exact structure:

### Cluster N
- Severity: high / medium / low
- Rule or helper:
- Files involved:
- Why this is real duplication:
- Why it is harmful or acceptable:
- Canonical home:
- Action: keep as-is / consolidate / move / delete
- What must not be generalized:

## Canonical-Home Table
- Rule/helper:
- Chosen home:
- Why this owner is correct:
- Files that should stop owning it:

## Refactor Guardrails
- Duplication that should wait until a later slice:
- Duplication that must be resolved before implementation:
- Anti-patterns to avoid during cleanup:

## Final Recommendation
Use exactly one of:
- NO ACTION NEEDED
- CONSOLIDATE IN CURRENT SLICE
- DEFER TO LATER SLICE

Then add:
- Reason:
- First 3 concrete next actions:

If you cannot meet that standard with the supplied evidence, say:
INSUFFICIENT EVIDENCE
and then provide only the missing-evidence list.
