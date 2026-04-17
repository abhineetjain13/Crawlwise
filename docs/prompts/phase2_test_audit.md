You are performing a Phase 2 TEST AUDIT for an in-progress backend refactor program.

Your job is not to give general code-quality advice.
Your job is to produce an ACTIONABLE, EVIDENCE-BOUND audit that we can directly use to decide which tests to trust, rewrite, replace, or delete before refactor work continues.

You must follow these rules strictly.

CONTEXT
We are running a backend refactor program with these goals:
- remove code bloat and duplicated strategy logic
- eliminate stale tests that preserve bad behavior
- enforce strict stage boundaries across: acquire -> discover -> extract -> normalize -> publish
- prefer deletion and simplification over compatibility wrappers
- spend compute only on findings that are specific enough to act on

Phase 2 purpose:
- stop stale tests from blocking the refactor
- classify tests by trust level and purpose
- identify tests that preserve wrong behavior, deleted seams, or private implementation details
- define replacement coverage at stable seams

IMPORTANT OPERATING RULES
- Existing tests are NOT automatically correct.
- Tests that lock in bugs, dead seams, wrong ownership, or internal structure are allowed to be rewritten or deleted.
- We keep invariant tests and contract tests.
- We rewrite characterization tests only when they still protect intended behavior.
- We avoid adding tests that couple to private helpers unless there is no better seam.
- If your conclusion conflicts with the supplied evidence pack, the evidence pack wins.

STRICT AUDIT BEHAVIOR
- Do NOT give generic advice.
- Do NOT say “consider”, “might”, “could”, or “possibly” unless you explicitly label the point as a hypothesis.
- Do NOT recommend broad rewrites without naming the exact file, test, and reason.
- Do NOT repeat architecture principles unless they directly explain a concrete test decision.
- Do NOT produce filler sections like “overall thoughts”, “best practices”, or “future improvements”.
- Every nontrivial claim must cite evidence from the supplied files/tests.
- If evidence is insufficient, say exactly: INSUFFICIENT EVIDENCE, and name what is missing.

PRIMARY TASK
Using only the supplied evidence pack and test files, produce a Phase 2 test audit for the target module or slice.

REQUIRED CLASSIFICATION MODEL
For each relevant test or test group, classify into exactly one primary category:
- invariant
- contract
- characterization
- coupled-to-internals
- obsolete

Also assign a trust level:
- high-trust
- medium-trust
- low-trust
- do-not-trust

DECISION STANDARD
Use these definitions:

invariant:
- protects behavior that should remain true across refactors
- usually stable at public seam or stable domain rule
- should usually be kept

contract:
- verifies a public interface, boundary, or stable cross-module agreement
- should usually be kept, maybe rewritten at a better seam

characterization:
- documents current behavior mainly to enable safe change
- may be useful temporarily
- should not be mistaken for intended behavior unless evidence says so

coupled-to-internals:
- asserts private helpers, call ordering, monkeypatch-heavy internals, internal branching, intermediate objects, or implementation structure
- candidate for rewrite or deletion

obsolete:
- preserves deleted seams, wrong ownership, dead code paths, outdated architecture, or behavior that the refactor is explicitly removing
- candidate for deletion or full replacement

AUDIT PRIORITY
Prioritize identifying:
1. tests that preserve wrong behavior
2. tests that preserve deleted or stale seams
3. tests that block stage-boundary enforcement
4. tests that are too coupled to implementation details
5. the minimum invariant/contract coverage that must survive the refactor

REQUIRED OUTPUT FORMAT
Output ONLY in the format below.

# Phase 2 Audit
## Scope
- Target module/slice:
- Files reviewed:
- Related production files:
- Boundary being enforced:

## Executive Decision
- Audit verdict: PASSABLE / HIGH-RISK / BLOCKED
- Primary reason:
- Can refactor proceed before test cleanup? YES / NO
- Minimum cleanup required before proceeding:

## Findings
For each finding, use this exact structure:

### Finding N
- Severity: critical / high / medium / low
- Test file:
- Test name or test group:
- Classification:
- Trust level:
- Problem:
- Evidence:
- Why this blocks or does not block refactor:
- Action: keep / rewrite / replace / delete
- Replacement seam:
- Notes:

Rules:
- One finding per actionable issue.
- If multiple tests have the same issue, group only if they truly share one reason and one action.
- “Evidence” must mention concrete assertions, fixtures, monkeypatches, helper coupling, stale ownership, or deleted seam references.

## Keep List
List only tests or groups that should survive with little or no change.

Format:
- Test file:
- Test name/group:
- Why it is safe:
- Classification:
- Trust level:

## Rewrite/Delete Queue
Rank the cleanup queue in execution order.

Format:
1. Test file:
   Test/group:
   Action:
   Why first:
   Stable seam to target instead:

## Replacement Coverage Plan
For each area that loses stale coverage, specify the minimum replacement test needed.

Format:
- Behavior to protect:
- Public/stable seam:
- Test style: invariant / contract / characterization
- What to avoid asserting:

## Unknowns
List only genuine blockers caused by missing evidence.

Format:
- Missing evidence:
- Why it matters:
- Impact on confidence:

## Final Recommendation
Use exactly one of:
- PROCEED
- PROCEED AFTER TARGETED TEST CLEANUP
- DO NOT PROCEED

Then add:
- Reason:
- First 3 concrete next actions:

SCORING GUARDRAILS
Your output is bad if:
- it contains generic advice that could apply to any repo
- it does not identify specific stale or coupled tests
- it recommends rewriting tests without naming a better seam
- it fails to distinguish intended behavior from accidental current behavior
- it treats all existing tests as equally trustworthy

Your output is good only if:
- a developer can immediately open the named tests and act
- each finding explains exactly why the test is trustworthy or not
- the cleanup order is clear
- replacement coverage is narrower and more stable than the old tests

If you cannot meet that standard with the supplied evidence, say:
INSUFFICIENT EVIDENCE
and then provide only the missing-evidence list.

Now perform the audit on the supplied files.
