# Gemini Prompt: Simplification Audit

Upload the target file plus a small set of nearby collaborators, then paste this prompt into Gemini AI Studio.

```text
Audit the uploaded files for residual complexity after a backend refactor.

I do not want implementation. I want an evidence-based audit I can hand to another coding agent.

Focus:
- identify where ownership is probably already correct
- identify where the code is still too complex inside that owner
- prefer simplification over more decomposition

Bias:
- prefer deletion over indirection
- prefer branch reduction over helper proliferation
- prefer one obvious policy seam over scattered micro-helpers
- do not suggest generic shared utils
- do not suggest a broad rewrite

Questions to answer:
1. Is the main target file in the correct owner now, or is there still real ownership drift?
2. Which functions or helper groups create the most unnecessary complexity?
3. Which issues are real simplification opportunities versus acceptable orchestration complexity?
4. What are the smallest concrete changes that would reduce complexity the most?

Output format:

# Simplification Audit
## Executive Verdict
- Ownership verdict:
- Simplification verdict:
- Primary reason:

## Findings
For each finding include:
- Severity
- File
- Function or helper group
- Complexity type: branch explosion / parameter fan-out / duplicated policy / data-shape churn / stale seam / helper indirection / mixed concern
- Evidence from uploaded files
- Simplest corrective action
- What should stay unchanged

## Do Now
- 1:
- 2:
- 3:

## Leave Alone
- 1:
- 2:

If the uploaded files are not enough, say exactly:
INSUFFICIENT EVIDENCE
and list what is missing.
```
