# Gemini Prompt: `review_shaping.py` Audit

Upload these files to Gemini AI Studio:
- `backend/app/services/publish/review_shaping.py`
- `backend/app/services/publish/verdict.py`
- `backend/app/services/normalizers/__init__.py`
- `backend/app/services/pipeline/utils.py`
- optionally: `backend/app/services/extract/llm_cleanup.py`
- optionally: `docs/plans/2026-04-17-backend-refactor-program-tracker.md`

Then paste this:

```text
Audit the uploaded files, with `backend/app/services/publish/review_shaping.py` as the main target.

Context:
- review shaping was moved out of pipeline into publish ownership during a backend refactor
- I do not want another architecture essay unless the uploaded files show real ownership drift
- I want to know whether this module is already lean enough or still hiding avoidable policy layering

What I want:
- identify whether `review_shaping.py` is simple enough to leave alone
- if not, identify the smallest changes that would make it clearer and smaller
- separate real review-shaping logic from imported helper churn or duplicated filtering logic

Do not do this:
- do not move publish behavior back into pipeline without strong evidence
- do not recommend generic shared utils
- do not give broad rewrite advice
- do not fill the response with clean-code generalities

Pay extra attention to:
- `_should_surface_discovered_field()`
- `_merge_review_bucket_entries()`
- `_normalize_llm_cleanup_review()`
- `_split_llm_cleanup_payload()`
- `_normalize_llm_review_bucket_item()`

Questions:
1. Is the module already small and coherent enough to keep as-is?
2. If not, where is the real complexity: duplicated filtering rules, data-shape churn, helper indirection, or misplaced normalization policy?
3. Which imported dependencies are justified and which ones just obscure local rules?
4. What are the top 3 simplifications with the best payoff-to-risk ratio?

Return exactly this shape:

# Review Shaping Audit
## Executive Verdict
- Ownership verdict:
- Simplification verdict:
- Primary reason:

## Findings
For each finding include:
- Severity
- File
- Function or helper group
- Complexity type
- Evidence from uploaded files
- Smallest corrective action
- What should stay unchanged

## Top 3 Actions
- 1:
- 2:
- 3:

## Leave Alone
- 1:
- 2:

If the uploaded files are insufficient, say exactly:
INSUFFICIENT EVIDENCE
and list the missing files.
```
