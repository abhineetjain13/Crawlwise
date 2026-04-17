# Gemini AI Studio Upload Recipe

Use this when you want Gemini to audit uploaded repo files and then bring the audit back here for follow-up.

The two file-specific prompts in this folder are examples, not the whole strategy.
If the problem spans many files, use the package-level or hotspot-triage prompts first.
The intended workflow is to make Gemini produce codemaps and investigation outputs, then bring those outputs back here for verification and implementation.

## What to upload

Upload only the target file and the minimum nearby collaborators needed for context.

Good upload bundle for a focused file audit:
- target file
- 2-6 directly related production files
- 1-3 relevant test files
- 1 plan or audit doc if the refactor context matters

Good upload bundle for a broad triage audit:
- one service package or one refactor slice
- key collaborators just outside that package
- the highest-signal test files for that area
- the tracker or one audit doc for context

Recommended workflow:
1. Use `phase4_hotspot_triage_audit.md` on a broad service area.
2. Use `phase4_package_simplification_audit.md` on the top hotspot bundle Gemini identifies.
3. Repeat for 2-4 slices.
4. Use `phase4_cross_slice_synthesis.md` on the collected Gemini outputs.
5. Bring the synthesis back here so implementation can start from a real codemap instead of guesswork.

Avoid:
- whole directories
- unrelated files
- large docs that Gemini does not need

Exception:
- whole directories are fine when the directory itself is the slice being audited, such as `acquisition/` or `extract/`

## How to frame the review

Tell Gemini exactly what kind of audit you want:
- simplification audit
- boundary audit
- duplication audit
- stale-test audit

Tell it what you do not want:
- no framework rewrite
- no generic utils advice
- no vague clean-code filler

## Copy-paste wrapper prompt

Paste this into Gemini AI Studio after uploading the files:

```text
I uploaded a bounded set of repo files. Audit only the uploaded files.

I am not asking you to implement changes. I want an evidence-based audit I can hand back to another coding agent for follow-up.

Review goal:
- [replace with simplification audit / boundary audit / duplication audit / stale-test audit]

Constraints:
- Use only the uploaded files.
- Do not invent missing code.
- Do not give generic clean-code advice.
- Do not recommend a broad rewrite.
- Do not suggest generic shared utils.
- Prefer deletion, consolidation, branch reduction, and clearer ownership over adding wrappers.
- If the uploaded files are insufficient, say exactly: INSUFFICIENT EVIDENCE.

Return:
1. Executive verdict
2. Top findings ordered by severity
3. Exact functions/helpers/tests involved
4. Concrete actions to take
5. What should explicitly stay unchanged
6. First 3 next actions

For every finding, cite the exact file and function/test name from the uploaded files.
```

## What to bring back here

Bring back:
- Gemini's full audit text
- the list of files you uploaded
- any place where Gemini said `INSUFFICIENT EVIDENCE`

That is enough for me to verify the audit against the repo and decide what to implement.
